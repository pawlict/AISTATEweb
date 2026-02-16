from __future__ import annotations

import time
import threading
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Callable, Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from webapp.auth.passwords import hash_password, verify_password, validate_password_strength, get_blacklist, _COMMON_PASSWORDS, _BUILTIN_FILE, PasswordBlacklist
from webapp.auth.user_store import UserStore, UserRecord
from webapp.auth.session_store import SessionStore
from webapp.auth.deployment_store import DeploymentStore
from webapp.auth.message_store import MessageStore, Message
from webapp.auth.audit_store import AuditStore
from webapp.auth.permissions import get_user_modules, ALL_USER_ROLES, ALL_ADMIN_ROLES
from webapp.auth.recovery_phrase import generate_and_hash, compute_hint, verify_phrase

router = APIRouter(prefix="/api/auth", tags=["auth"])

# Module-level references (injected via init())
_user_store: Optional[UserStore] = None
_session_store: Optional[SessionStore] = None
_deployment_store: Optional[DeploymentStore] = None
_message_store: Optional[MessageStore] = None
_audit_store: Optional[AuditStore] = None
_app_log_fn: Optional[Callable] = None
_get_session_timeout: Optional[Callable] = None
_get_settings: Optional[Callable] = None  # returns Settings dataclass

# Rate limiting for login: {ip: [timestamps]}
_login_attempts: dict = defaultdict(list)
_rate_lock = threading.Lock()
MAX_LOGIN_ATTEMPTS = 5
RATE_WINDOW_SECONDS = 60


def init(
    user_store: UserStore,
    session_store: SessionStore,
    deployment_store: DeploymentStore,
    app_log_fn: Callable,
    get_session_timeout: Callable,
    message_store: Optional[MessageStore] = None,
    audit_store: Optional[AuditStore] = None,
    get_settings: Optional[Callable] = None,
) -> None:
    global _user_store, _session_store, _deployment_store, _message_store, _app_log_fn, _get_session_timeout, _audit_store, _get_settings
    _user_store = user_store
    _session_store = session_store
    _deployment_store = deployment_store
    _message_store = message_store
    _audit_store = audit_store
    _app_log_fn = app_log_fn
    _get_session_timeout = get_session_timeout
    _get_settings = get_settings


def _settings():
    """Get current settings (with defaults if callback not set)."""
    if _get_settings:
        return _get_settings()
    # Fallback: import directly
    from backend.settings_store import load_settings
    return load_settings()


def _validate_pw(password: str) -> str | None:
    """Validate password against the configured policy. Returns error msg or None."""
    policy = getattr(_settings(), "password_policy", "basic")
    return validate_password_strength(password, policy)


def _is_rate_limited(ip: str) -> bool:
    now = time.time()
    with _rate_lock:
        attempts = _login_attempts[ip]
        # Remove old attempts
        _login_attempts[ip] = [t for t in attempts if now - t < RATE_WINDOW_SECONDS]
        return len(_login_attempts[ip]) >= MAX_LOGIN_ATTEMPTS


def _record_attempt(ip: str) -> None:
    with _rate_lock:
        _login_attempts[ip].append(time.time())


@router.post("/login")
async def login(request: Request) -> JSONResponse:
    assert _user_store and _session_store and _deployment_store

    if not _deployment_store.is_multiuser():
        return JSONResponse({"status": "error", "message": "Multi-user mode is not enabled"}, status_code=400)

    ip = request.client.host if request.client else "unknown"

    if _is_rate_limited(ip):
        return JSONResponse(
            {"status": "error", "message": "Too many login attempts. Try again later."},
            status_code=429,
        )

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"status": "error", "message": "Invalid request"}, status_code=400)

    username = (body.get("username") or "").strip()
    password = body.get("password") or ""
    fingerprint = body.get("fingerprint") or None
    # Sanitise fingerprint: only keep known safe string keys
    if isinstance(fingerprint, dict):
        _fp_keys = {"browser", "os", "screen", "timezone", "language", "platform"}
        fingerprint = {k: str(v)[:120] for k, v in fingerprint.items() if k in _fp_keys and isinstance(v, str)}
    else:
        fingerprint = None

    if not username or not password:
        _record_attempt(ip)
        return JSONResponse({"status": "error", "message": "Username and password required"}, status_code=400)

    user = _user_store.get_by_username(username)

    # --- Account lockout check ---
    if user is not None:
        locked_until = getattr(user, "locked_until", None)
        if locked_until:
            try:
                lock_dt = datetime.fromisoformat(locked_until)
                if datetime.now() < lock_dt:
                    remaining = int((lock_dt - datetime.now()).total_seconds() // 60) + 1
                    return JSONResponse({
                        "status": "error",
                        "message": f"Account locked. Try again in {remaining} min.",
                        "code": "locked",
                        "locked_minutes": remaining,
                    }, status_code=423)
                else:
                    # Auto-unlock
                    _user_store.update_user(user.user_id, {"locked_until": None, "failed_login_count": 0})
                    if _audit_store:
                        _audit_store.log_event("account_unlocked", user_id=user.user_id, username=user.username, ip=ip, detail="auto-unlock after lockout expired")
            except ValueError:
                pass

    if user is None or not verify_password(password, user.password_hash):
        _record_attempt(ip)
        if _app_log_fn:
            _app_log_fn(f"Auth: failed login attempt for '{username}' from {ip}")
        if _audit_store:
            _audit_store.log_event("login_failed", user_id=user.user_id if user else "", username=username, ip=ip, fingerprint=fingerprint)

        # --- Increment failed count & possibly lock ---
        if user is not None:
            settings = _settings()
            threshold = getattr(settings, "account_lockout_threshold", 5)
            lockout_min = getattr(settings, "account_lockout_duration", 15)
            new_count = getattr(user, "failed_login_count", 0) + 1
            updates: dict = {"failed_login_count": new_count}
            if threshold > 0 and new_count >= threshold:
                lock_until = (datetime.now() + timedelta(minutes=lockout_min)).isoformat()
                updates["locked_until"] = lock_until
                if _app_log_fn:
                    _app_log_fn(f"Auth: account '{username}' locked for {lockout_min}min after {new_count} failed attempts from {ip}")
                if _audit_store:
                    _audit_store.log_event("account_locked", user_id=user.user_id, username=user.username, ip=ip, detail=f"locked for {lockout_min}min after {new_count} failures", fingerprint=fingerprint)
                # Notify admins via Call Center
                if _message_store and new_count >= 10:
                    msg = Message(
                        author_id="system",
                        author_name="System",
                        subject=f"Podejrzana aktywność — {user.display_name or user.username}",
                        content=(
                            f'<p>Konto <b>{user.display_name or user.username}</b> (<code>{user.username}</code>) '
                            f'zostało zablokowane po <b>{new_count}</b> nieudanych próbach logowania z IP <code>{ip}</code>.</p>'
                            f'<p>Może to wskazywać na próbę ataku brute-force.</p>'
                        ),
                        target_groups=["Strażnik Dostępu", "Główny Opiekun"],
                    )
                    _message_store.create_message(msg)
            _user_store.update_user(user.user_id, updates)

        return JSONResponse({"status": "error", "message": "Invalid username or password"}, status_code=401)

    # Check pending approval
    if user.pending:
        guard_names = _user_store.get_access_guard_names()
        return JSONResponse({
            "status": "error",
            "message": "Account pending approval",
            "code": "pending",
            "approvers": guard_names,
        }, status_code=403)

    # Check ban
    if user.banned:
        if user.banned_until:
            try:
                until = datetime.fromisoformat(user.banned_until)
                if datetime.now() > until:
                    # Auto-unban
                    _user_store.update_user(user.user_id, {"banned": False, "banned_until": None, "ban_reason": None})
                else:
                    return JSONResponse({"status": "error", "message": "Account banned", "reason": user.ban_reason or ""}, status_code=403)
            except ValueError:
                pass
        else:
            return JSONResponse({"status": "error", "message": "Account banned", "reason": user.ban_reason or ""}, status_code=403)

    # --- Successful login: reset failed count ---
    now_iso = datetime.now().isoformat()
    login_updates: dict = {
        "last_login": now_iso,
        "failed_login_count": 0,
        "locked_until": None,
    }

    # Create session
    timeout = _get_session_timeout() if _get_session_timeout else 8
    token = _session_store.create_session(user.user_id, timeout_hours=timeout, ip=ip)

    _user_store.update_user(user.user_id, login_updates)

    if _app_log_fn:
        _app_log_fn(f"Auth: user '{username}' logged in from {ip}")
    if _audit_store:
        _audit_store.log_event("login", user_id=user.user_id, username=user.username, ip=ip, fingerprint=fingerprint)

    # --- Password expiry / first-login check ---
    password_expired = False
    must_change_password = False
    settings = _settings()
    expiry_days = getattr(settings, "password_expiry_days", 0)
    changed_at = getattr(user, "password_changed_at", None)

    # Force password change on first login (no password_changed_at recorded)
    if not changed_at:
        must_change_password = True
    elif expiry_days > 0:
        try:
            changed_dt = datetime.fromisoformat(changed_at)
            if datetime.now() > changed_dt + timedelta(days=expiry_days):
                password_expired = True
        except ValueError:
            pass

    response_data: dict = {
        "status": "ok",
        "user_id": user.user_id,
        "username": user.username,
        "language": user.language or "pl",
    }
    if must_change_password:
        response_data["must_change_password"] = True
        if _audit_store:
            _audit_store.log_event("password_expired_redirect", user_id=user.user_id, username=user.username, ip=ip,
                                   detail="first login — password change required", fingerprint=fingerprint)
    elif password_expired:
        response_data["password_expired"] = True
        if _audit_store:
            _audit_store.log_event("password_expired_redirect", user_id=user.user_id, username=user.username, ip=ip, fingerprint=fingerprint)

    # --- Recovery phrase pending display ---
    pending_phrase = getattr(user, "recovery_phrase_pending", None)
    if pending_phrase:
        response_data["recovery_phrase_pending"] = pending_phrase
        # Clear the pending phrase so it's shown only once
        _user_store.update_user(user.user_id, {"recovery_phrase_pending": None})

    response = JSONResponse(response_data)
    response.set_cookie(
        key=SessionStore.COOKIE_NAME,
        value=token,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=timeout * 3600,
        path="/",
    )
    return response


@router.post("/logout")
async def logout(request: Request) -> JSONResponse:
    assert _session_store
    user = getattr(request.state, "user", None)
    token = request.cookies.get(SessionStore.COOKIE_NAME)
    if token:
        _session_store.delete_session(token)
    if _audit_store and user:
        ip = (request.headers.get("x-forwarded-for", "") or request.client.host if request.client else "")
        _audit_store.log_event("logout", user_id=user.user_id, username=user.username, ip=ip)
    response = JSONResponse({"status": "ok"})
    response.delete_cookie(key=SessionStore.COOKIE_NAME, path="/")
    return response


@router.get("/me")
async def me(request: Request) -> JSONResponse:
    user = getattr(request.state, "user", None)
    if user is None:
        return JSONResponse({"status": "error", "message": "Not authenticated"}, status_code=401)

    modules = get_user_modules(user.role, user.is_admin, user.admin_roles, user.is_superadmin)
    return JSONResponse({
        "status": "ok",
        "user": {
            "user_id": user.user_id,
            "username": user.username,
            "display_name": user.display_name,
            "role": user.role,
            "is_admin": user.is_admin,
            "admin_roles": user.admin_roles,
            "is_superadmin": user.is_superadmin,
            "modules": modules,
            "language": user.language or "pl",
        },
    })


@router.post("/change-password")
async def change_password(request: Request) -> JSONResponse:
    assert _user_store
    user = getattr(request.state, "user", None)
    if user is None:
        return JSONResponse({"status": "error", "message": "Not authenticated"}, status_code=401)

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"status": "error", "message": "Invalid request"}, status_code=400)

    current = body.get("current_password") or ""
    new_pass = body.get("new_password") or ""

    if not current or not new_pass:
        return JSONResponse({"status": "error", "message": "Both current and new password required"}, status_code=400)

    if len(new_pass) < 6:
        return JSONResponse({"status": "error", "message": "Password must be at least 6 characters"}, status_code=400)

    # Password policy: admins always require "strong" (12+ chars, uppercase, lowercase, digit, special)
    if user.is_admin or user.is_superadmin:
        pw_err = validate_password_strength(new_pass, "strong")
        if pw_err:
            pw_err += " (wymóg dla kont administratorów / admin account requirement)"
    else:
        pw_err = _validate_pw(new_pass)
    if pw_err:
        return JSONResponse({"status": "error", "message": pw_err}, status_code=400)

    # Verify current password
    if not verify_password(current, user.password_hash):
        return JSONResponse({"status": "error", "message": "Current password is incorrect"}, status_code=401)

    # Update password + record timestamp
    _user_store.update_user(user.user_id, {
        "password_hash": hash_password(new_pass),
        "password_changed_at": datetime.now().isoformat(),
    })

    if _app_log_fn:
        _app_log_fn(f"Auth: user '{user.username}' changed their password")
    if _audit_store:
        _audit_store.log_event("password_changed", user_id=user.user_id, username=user.username)

    return JSONResponse({"status": "ok"})


@router.post("/language")
async def set_language(request: Request) -> JSONResponse:
    """Set the user's UI language preference (pl or en)."""
    assert _user_store
    user = getattr(request.state, "user", None)
    if user is None:
        return JSONResponse({"status": "error", "message": "Not authenticated"}, status_code=401)

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"status": "error", "message": "Invalid request"}, status_code=400)

    lang = (body.get("language") or "pl").strip().lower()
    if lang not in ("pl", "en"):
        lang = "pl"

    _user_store.update_user(user.user_id, {"language": lang})
    return JSONResponse({"status": "ok", "language": lang})


@router.post("/register")
async def register(request: Request) -> JSONResponse:
    """Self-registration: create a new account with pending=True."""
    assert _user_store and _deployment_store

    if not _deployment_store.is_multiuser():
        return JSONResponse({"status": "error", "message": "Registration not available"}, status_code=400)

    ip = request.client.host if request.client else "unknown"

    if _is_rate_limited(ip):
        return JSONResponse({"status": "error", "message": "Too many attempts. Try again later."}, status_code=429)

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"status": "error", "message": "Invalid request"}, status_code=400)

    username = (body.get("username") or "").strip()
    display_name = (body.get("display_name") or username).strip()
    password = body.get("password") or ""

    if not username:
        _record_attempt(ip)
        return JSONResponse({"status": "error", "message": "Username required"}, status_code=400)
    if len(username) < 3:
        _record_attempt(ip)
        return JSONResponse({"status": "error", "message": "Username must be at least 3 characters"}, status_code=400)
    if len(password) < 6:
        _record_attempt(ip)
        return JSONResponse({"status": "error", "message": "Password must be at least 6 characters"}, status_code=400)

    # Password policy check
    pw_err = _validate_pw(password)
    if pw_err:
        _record_attempt(ip)
        return JSONResponse({"status": "error", "message": pw_err}, status_code=400)

    # Check if username already exists
    existing = _user_store.get_by_username(username)
    if existing is not None:
        _record_attempt(ip)
        return JSONResponse({"status": "error", "message": "Username already taken"}, status_code=409)

    guard_names = _user_store.get_access_guard_names()

    # Generate recovery phrase
    phrase, phrase_hash, phrase_hint = generate_and_hash()

    try:
        rec = UserRecord(
            username=username,
            display_name=display_name,
            password_hash=hash_password(password),
            role=None,
            pending=True,
            created_by="self",
            password_changed_at=datetime.now().isoformat(),
            recovery_phrase_hash=phrase_hash,
            recovery_phrase_hint=phrase_hint,
        )
        rec = _user_store.create_user(rec)
    except ValueError as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=409)

    if _app_log_fn:
        _app_log_fn(f"Auth: new self-registration '{username}' from {ip} (pending approval)")

    return JSONResponse({
        "status": "ok",
        "message": "Account created, waiting for approval",
        "approvers": guard_names,
        "recovery_phrase": phrase,
    }, status_code=201)


@router.post("/request-reset")
async def request_password_reset(request: Request) -> JSONResponse:
    """Public endpoint: user requests a password reset from the login page.

    Sets a flag on the user record and sends a Call Center message to all
    admin groups so they see the request on their next login.
    """
    assert _user_store

    ip = request.client.host if request.client else "unknown"
    if _is_rate_limited(ip):
        return JSONResponse({"status": "error", "message": "Too many requests"}, status_code=429)
    _record_attempt(ip)

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"status": "error", "message": "Invalid request"}, status_code=400)

    username = (body.get("username") or "").strip()
    if not username:
        return JSONResponse({"status": "error", "message": "Username required"}, status_code=400)

    user = _user_store.get_by_username(username)
    if user is None or user.banned or user.pending:
        # Don't reveal whether the user exists
        return JSONResponse({"status": "ok", "message": "Request received"})

    # Already requested and not yet handled — don't create duplicate messages
    if user.password_reset_requested:
        return JSONResponse({"status": "ok", "message": "Request received"})

    # Mark the flag on the user record
    now = datetime.now().isoformat()
    _user_store.update_user(user.user_id, {
        "password_reset_requested": True,
        "password_reset_requested_at": now,
    })

    # Send Call Center message to admin groups
    if _message_store:
        display = user.display_name or user.username
        msg = Message(
            author_id="system",
            author_name="System",
            subject=f"Prośba o reset hasła — {display}",
            content=(
                f'<p>Użytkownik <b>{display}</b> (<code>{user.username}</code>) '
                f'wysłał prośbę o reset hasła ze strony logowania.</p>'
                f'<p>Zresetuj hasło w panelu <b>Użytkownicy</b>.</p>'
            ),
            target_groups=["Strażnik Dostępu", "Główny Opiekun"],
        )
        _message_store.create_message(msg)

    if _app_log_fn:
        _app_log_fn(f"Auth: password reset requested for '{user.username}' from {ip}")

    return JSONResponse({"status": "ok", "message": "Request received"})


# ---------------------------------------------------------------------------
# Recovery via seed phrase (no username required)
# ---------------------------------------------------------------------------

@router.post("/recover-by-phrase")
async def recover_by_phrase(request: Request) -> JSONResponse:
    """Public endpoint: recover account by entering the 12-word recovery phrase.

    The phrase hint (SHA256 prefix) is used for fast user lookup,
    then PBKDF2 verification confirms the match.
    On success, allows setting a new password.
    """
    assert _user_store

    ip = request.client.host if request.client else "unknown"
    if _is_rate_limited(ip):
        return JSONResponse({"status": "error", "message": "Too many requests"}, status_code=429)
    _record_attempt(ip)

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"status": "error", "message": "Invalid request"}, status_code=400)

    phrase = (body.get("phrase") or "").strip()
    new_password = (body.get("new_password") or "").strip()

    if not phrase:
        return JSONResponse({"status": "error", "message": "Recovery phrase required"}, status_code=400)

    # Count words
    words = phrase.lower().split()
    if len(words) != 12:
        return JSONResponse({"status": "error", "message": "Recovery phrase must be exactly 12 words"}, status_code=400)

    if not new_password:
        return JSONResponse({"status": "error", "message": "New password required"}, status_code=400)

    if len(new_password) < 6:
        return JSONResponse({"status": "error", "message": "Password must be at least 6 characters"}, status_code=400)

    # Compute hint for fast lookup
    hint = compute_hint(phrase)
    user = _user_store.get_by_phrase_hint(hint)

    if user is None:
        if _app_log_fn:
            _app_log_fn(f"Auth: failed recovery phrase attempt from {ip} (no user found for hint)")
        if _audit_store:
            _audit_store.log_event("recovery_phrase_failed", ip=ip, detail="no user found for hint")
        return JSONResponse({"status": "error", "message": "Invalid recovery phrase"}, status_code=401)

    # Verify full phrase with PBKDF2
    if not user.recovery_phrase_hash or not verify_phrase(phrase, user.recovery_phrase_hash):
        if _app_log_fn:
            _app_log_fn(f"Auth: failed recovery phrase verification for '{user.username}' from {ip}")
        if _audit_store:
            _audit_store.log_event("recovery_phrase_failed", user_id=user.user_id, username=user.username, ip=ip, detail="PBKDF2 verification failed")
        return JSONResponse({"status": "error", "message": "Invalid recovery phrase"}, status_code=401)

    # Check user status
    if user.banned:
        return JSONResponse({"status": "error", "message": "Account is banned"}, status_code=403)

    # Password policy check
    is_admin_user = user.is_admin or user.is_superadmin
    pw_policy = "strong" if is_admin_user else (getattr(_settings(), "password_policy", "basic"))
    pw_err = validate_password_strength(new_password, pw_policy)
    if pw_err:
        msg = pw_err
        if is_admin_user:
            msg += " (wymóg dla kont administratorów / admin account requirement)"
        return JSONResponse({"status": "error", "message": msg}, status_code=400)

    # Success — set new password
    _user_store.update_user(user.user_id, {
        "password_hash": hash_password(new_password),
        "password_changed_at": datetime.now().isoformat(),
        "password_reset_requested": False,
        "password_reset_requested_at": None,
        "failed_login_count": 0,
        "locked_until": None,
    })

    if _app_log_fn:
        _app_log_fn(f"Auth: password recovered via phrase for '{user.username}' from {ip}")
    if _audit_store:
        _audit_store.log_event("password_recovered_by_phrase", user_id=user.user_id, username=user.username, ip=ip)

    return JSONResponse({
        "status": "ok",
        "message": "Password has been reset successfully",
        "username": user.username,
    })


# ---------------------------------------------------------------------------
# Username availability check
# ---------------------------------------------------------------------------

@router.get("/check-username")
async def check_username(request: Request) -> JSONResponse:
    """Public endpoint: check if a username is already taken."""
    assert _user_store

    username = (request.query_params.get("username") or "").strip()
    if not username or len(username) < 3:
        return JSONResponse({"status": "ok", "available": False, "reason": "too_short"})

    existing = _user_store.get_by_username(username)
    return JSONResponse({
        "status": "ok",
        "available": existing is None,
    })


# ---------------------------------------------------------------------------
# Audit log endpoints
# ---------------------------------------------------------------------------

@router.get("/audit")
async def get_audit_log(request: Request) -> JSONResponse:
    """Admin endpoint: return auth audit events."""
    user = getattr(request.state, "user", None)
    if user is None:
        return JSONResponse({"status": "error", "message": "Not authenticated"}, status_code=401)
    if not user.is_admin and not user.is_superadmin:
        return JSONResponse({"status": "error", "message": "Admin access required"}, status_code=403)
    if not _audit_store:
        return JSONResponse({"status": "ok", "events": []})

    params = request.query_params
    uid = params.get("user_id", "")
    evt = params.get("event", "")
    limit = min(int(params.get("limit", "200")), 500)
    offset = int(params.get("offset", "0"))

    events = _audit_store.get_events(user_id=uid, event_type=evt, limit=limit, offset=offset)
    total = _audit_store.count_events(user_id=uid, event_type=evt)
    return JSONResponse({"status": "ok", "events": events, "total": total})


@router.get("/my-audit")
async def get_my_audit(request: Request) -> JSONResponse:
    """Authenticated user: see their own login history."""
    user = getattr(request.state, "user", None)
    if user is None:
        return JSONResponse({"status": "error", "message": "Not authenticated"}, status_code=401)
    if not _audit_store:
        return JSONResponse({"status": "ok", "events": []})

    events = _audit_store.get_user_events(user.user_id, limit=50)
    return JSONResponse({"status": "ok", "events": events})


# ---------------------------------------------------------------------------
# Password policy info (public — used by registration form for hints)
# ---------------------------------------------------------------------------

@router.get("/password-policy")
async def get_password_policy(request: Request) -> JSONResponse:
    """Return current password policy level so the UI can show hints."""
    settings = _settings()
    policy = getattr(settings, "password_policy", "basic")
    rules: dict = {"policy": policy}
    if policy == "basic":
        rules["min_length"] = 8
    elif policy == "medium":
        rules["min_length"] = 8
        rules["requires"] = ["lowercase", "uppercase", "digit"]
    elif policy == "strong":
        rules["min_length"] = 12
        rules["requires"] = ["lowercase", "uppercase", "digit", "special"]
    else:
        rules["min_length"] = 6
    return JSONResponse({"status": "ok", **rules})


# ---------------------------------------------------------------------------
# Password blacklist management (admin-only)
# ---------------------------------------------------------------------------

@router.get("/password-blacklist")
async def get_password_blacklist(request: Request) -> JSONResponse:
    """Admin endpoint: return all blacklisted passwords (built-in + custom)."""
    user = getattr(request.state, "user", None)
    if user is None:
        return JSONResponse({"status": "error", "message": "Not authenticated"}, status_code=401)
    if not user.is_admin and not user.is_superadmin:
        return JSONResponse({"status": "error", "message": "Admin access required"}, status_code=403)

    bl = get_blacklist()
    if bl is None:
        return JSONResponse({"status": "ok", "builtin": [], "custom": [], "builtin_file": str(_BUILTIN_FILE)})

    data = bl.get_all()
    return JSONResponse({"status": "ok", **data, "builtin_file": str(_BUILTIN_FILE)})


@router.post("/password-blacklist")
async def add_to_blacklist(request: Request) -> JSONResponse:
    """Admin endpoint: add password(s) to custom blacklist."""
    user = getattr(request.state, "user", None)
    if user is None:
        return JSONResponse({"status": "error", "message": "Not authenticated"}, status_code=401)
    if not user.is_admin and not user.is_superadmin:
        return JSONResponse({"status": "error", "message": "Admin access required"}, status_code=403)

    bl = get_blacklist()
    if bl is None:
        return JSONResponse({"status": "error", "message": "Blacklist not initialised"}, status_code=500)

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"status": "error", "message": "Invalid request"}, status_code=400)

    passwords = body.get("passwords")
    if isinstance(passwords, list):
        added = bl.add_bulk([str(p) for p in passwords if p])
        return JSONResponse({"status": "ok", "added": added})

    pw = body.get("password", "")
    if not pw or not isinstance(pw, str) or not pw.strip():
        return JSONResponse({"status": "error", "message": "Password required"}, status_code=400)

    # Duplicate check – distinguish builtin vs custom
    lower = pw.lower().strip()
    if lower in _COMMON_PASSWORDS:
        return JSONResponse({"status": "error", "message": "duplicate_builtin"}, status_code=409)

    ok = bl.add(pw)
    if not ok:
        return JSONResponse({"status": "error", "message": "duplicate_custom"}, status_code=409)
    return JSONResponse({"status": "ok", "added": 1})


@router.delete("/password-blacklist")
async def remove_from_blacklist(request: Request) -> JSONResponse:
    """Admin endpoint: remove a password from the custom blacklist."""
    user = getattr(request.state, "user", None)
    if user is None:
        return JSONResponse({"status": "error", "message": "Not authenticated"}, status_code=401)
    if not user.is_admin and not user.is_superadmin:
        return JSONResponse({"status": "error", "message": "Admin access required"}, status_code=403)

    bl = get_blacklist()
    if bl is None:
        return JSONResponse({"status": "error", "message": "Blacklist not initialised"}, status_code=500)

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"status": "error", "message": "Invalid request"}, status_code=400)

    pw = body.get("password", "")
    if not pw or not isinstance(pw, str):
        return JSONResponse({"status": "error", "message": "Password required"}, status_code=400)

    ok = bl.remove(pw)
    return JSONResponse({"status": "ok", "removed": 1 if ok else 0})


@router.post("/password-blacklist/reload")
async def reload_builtin_passwords(request: Request) -> JSONResponse:
    """Admin endpoint: reload builtin_passwords.txt after manual edit."""
    user = getattr(request.state, "user", None)
    if user is None:
        return JSONResponse({"status": "error", "message": "Not authenticated"}, status_code=401)
    if not user.is_admin and not user.is_superadmin:
        return JSONResponse({"status": "error", "message": "Admin access required"}, status_code=403)

    count = PasswordBlacklist.reload_builtin()
    return JSONResponse({"status": "ok", "builtin_count": count})
