from __future__ import annotations

import time
import threading
from collections import defaultdict
from datetime import datetime
from typing import Any, Callable, Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from webapp.auth.passwords import hash_password, verify_password
from webapp.auth.user_store import UserStore, UserRecord
from webapp.auth.session_store import SessionStore
from webapp.auth.deployment_store import DeploymentStore
from webapp.auth.permissions import get_user_modules, ALL_USER_ROLES, ALL_ADMIN_ROLES

router = APIRouter(prefix="/api/auth", tags=["auth"])

# Module-level references (injected via init())
_user_store: Optional[UserStore] = None
_session_store: Optional[SessionStore] = None
_deployment_store: Optional[DeploymentStore] = None
_app_log_fn: Optional[Callable] = None
_get_session_timeout: Optional[Callable] = None

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
) -> None:
    global _user_store, _session_store, _deployment_store, _app_log_fn, _get_session_timeout
    _user_store = user_store
    _session_store = session_store
    _deployment_store = deployment_store
    _app_log_fn = app_log_fn
    _get_session_timeout = get_session_timeout


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

    if not username or not password:
        _record_attempt(ip)
        return JSONResponse({"status": "error", "message": "Username and password required"}, status_code=400)

    user = _user_store.get_by_username(username)
    if user is None or not verify_password(password, user.password_hash):
        _record_attempt(ip)
        if _app_log_fn:
            _app_log_fn(f"Auth: failed login attempt for '{username}' from {ip}")
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

    # Create session
    timeout = _get_session_timeout() if _get_session_timeout else 8
    token = _session_store.create_session(user.user_id, timeout_hours=timeout, ip=ip)

    # Update last_login
    _user_store.update_user(user.user_id, {"last_login": datetime.now().isoformat()})

    if _app_log_fn:
        _app_log_fn(f"Auth: user '{username}' logged in from {ip}")

    response = JSONResponse({"status": "ok", "user_id": user.user_id, "username": user.username, "language": user.language or "pl"})
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
    token = request.cookies.get(SessionStore.COOKIE_NAME)
    if token:
        _session_store.delete_session(token)
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

    # Verify current password
    if not verify_password(current, user.password_hash):
        return JSONResponse({"status": "error", "message": "Current password is incorrect"}, status_code=401)

    # Update password
    _user_store.update_user(user.user_id, {"password_hash": hash_password(new_pass)})

    if _app_log_fn:
        _app_log_fn(f"Auth: user '{user.username}' changed their password")

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
