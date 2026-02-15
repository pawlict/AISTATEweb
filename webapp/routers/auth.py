from __future__ import annotations

import time
import threading
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Callable, Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from webapp.auth.passwords import hash_password, verify_password, validate_password_strength
from webapp.auth.user_store import UserStore, UserRecord
from webapp.auth.session_store import SessionStore
from webapp.auth.deployment_store import DeploymentStore
from webapp.auth.message_store import MessageStore, Message
from webapp.auth.audit_store import AuditStore
from webapp.auth.permissions import get_user_modules, ALL_USER_ROLES, ALL_ADMIN_ROLES

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

    # --- Password expiry check ---
    password_expired = False
    settings = _settings()
    expiry_days = getattr(settings, "password_expiry_days", 0)
    if expiry_days > 0:
        changed_at = getattr(user, "password_changed_at", None)
        if changed_at:
            try:
                changed_dt = datetime.fromisoformat(changed_at)
                if datetime.now() > changed_dt + timedelta(days=expiry_days):
                    password_expired = True
            except ValueError:
                pass
        else:
            # No password_changed_at recorded — treat as expired to force first change
            password_expired = True

    response_data: dict = {
        "status": "ok",
        "user_id": user.user_id,
        "username": user.username,
        "language": user.language or "pl",
    }
    if password_expired:
        response_data["password_expired"] = True
        if _audit_store:
            _audit_store.log_event("password_expired_redirect", user_id=user.user_id, username=user.username, ip=ip, fingerprint=fingerprint)

    response = JSONResponse(response_data)
    response.set_cookie(
        key=SessionStore.COOKIE_NAME,
        value=token,
        httponly=True,
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

    # Password policy check
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

    try:
        rec = UserRecord(
            username=username,
            display_name=display_name,
            password_hash=hash_password(password),
            role=None,
            pending=True,
            created_by="self",
            password_changed_at=datetime.now().isoformat(),
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
