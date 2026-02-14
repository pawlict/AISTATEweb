from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from webapp.auth.passwords import hash_password, validate_password_strength
from webapp.auth.user_store import UserStore, UserRecord
from webapp.auth.session_store import SessionStore
from webapp.auth.audit_store import AuditStore
from webapp.auth.permissions import ALL_USER_ROLES, ALL_ADMIN_ROLES, ROLE_MODULES, ADMIN_ROLE_MODULES, get_user_modules

router = APIRouter(prefix="/api/users", tags=["users"])

_user_store: Optional[UserStore] = None
_session_store: Optional[SessionStore] = None
_audit_store: Optional[AuditStore] = None
_app_log_fn: Optional[Callable] = None
_get_settings: Optional[Callable] = None


def init(
    user_store: UserStore,
    session_store: SessionStore,
    app_log_fn: Callable,
    audit_store: Optional[AuditStore] = None,
    get_settings: Optional[Callable] = None,
) -> None:
    global _user_store, _session_store, _app_log_fn, _audit_store, _get_settings
    _user_store = user_store
    _session_store = session_store
    _app_log_fn = app_log_fn
    _audit_store = audit_store
    _get_settings = get_settings


def _pw_policy() -> str:
    if _get_settings:
        return getattr(_get_settings(), "password_policy", "basic")
    return "basic"


def _require_access_guard(request: Request) -> Optional[JSONResponse]:
    """Check that the requester is Strażnik Dostępu or Główny Opiekun."""
    user = getattr(request.state, "user", None)
    if user is None:
        return JSONResponse({"status": "error", "message": "Not authenticated"}, status_code=401)
    if not user.is_admin:
        return JSONResponse({"status": "error", "message": "Admin access required"}, status_code=403)
    if not user.is_superadmin and "Strażnik Dostępu" not in (user.admin_roles or []):
        return JSONResponse({"status": "error", "message": "Access Guard role required"}, status_code=403)
    return None


def _user_to_dict(u: UserRecord) -> dict:
    return {
        "user_id": u.user_id,
        "username": u.username,
        "display_name": u.display_name,
        "role": u.role,
        "is_admin": u.is_admin,
        "admin_roles": u.admin_roles,
        "is_superadmin": u.is_superadmin,
        "banned": u.banned,
        "banned_until": u.banned_until,
        "ban_reason": u.ban_reason,
        "show_ban_expiry": getattr(u, "show_ban_expiry", True),
        "pending": u.pending,
        "pending_role": u.pending_role,
        "created_at": u.created_at,
        "created_by": u.created_by,
        "last_login": u.last_login,
        "language": u.language or "pl",
        "modules": get_user_modules(u.role, u.is_admin, u.admin_roles, u.is_superadmin),
        "failed_login_count": getattr(u, "failed_login_count", 0),
        "locked_until": getattr(u, "locked_until", None),
        "password_changed_at": getattr(u, "password_changed_at", None),
    }


@router.get("")
async def list_users(request: Request) -> JSONResponse:
    err = _require_access_guard(request)
    if err:
        return err
    assert _user_store
    users = _user_store.list_users()
    return JSONResponse({"status": "ok", "users": [_user_to_dict(u) for u in users]})


@router.get("/roles")
async def list_roles(request: Request) -> JSONResponse:
    """Return available role names for the UI."""
    err = _require_access_guard(request)
    if err:
        return err
    return JSONResponse({
        "status": "ok",
        "user_roles": ALL_USER_ROLES,
        "admin_roles": ALL_ADMIN_ROLES,
        "role_modules": {r: mods for r, mods in ROLE_MODULES.items()},
        "admin_role_modules": {r: mods for r, mods in ADMIN_ROLE_MODULES.items()},
    })


@router.post("")
async def create_user(request: Request) -> JSONResponse:
    err = _require_access_guard(request)
    if err:
        return err
    assert _user_store

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"status": "error", "message": "Invalid request"}, status_code=400)

    username = (body.get("username") or "").strip()
    display_name = (body.get("display_name") or username).strip()
    password = body.get("password") or ""
    role = body.get("role")
    is_admin = bool(body.get("is_admin", False))
    admin_roles = body.get("admin_roles") or []

    if not username:
        return JSONResponse({"status": "error", "message": "Username required"}, status_code=400)
    if len(password) < 6:
        return JSONResponse({"status": "error", "message": "Password must be at least 6 characters"}, status_code=400)

    # Password policy check
    pw_err = validate_password_strength(password, _pw_policy())
    if pw_err:
        return JSONResponse({"status": "error", "message": pw_err}, status_code=400)

    if not is_admin and role not in ALL_USER_ROLES:
        return JSONResponse({"status": "error", "message": f"Invalid role: {role}"}, status_code=400)
    if is_admin:
        for ar in admin_roles:
            if ar not in ALL_ADMIN_ROLES:
                return JSONResponse({"status": "error", "message": f"Invalid admin role: {ar}"}, status_code=400)

    caller = getattr(request.state, "user", None)

    try:
        rec = UserRecord(
            username=username,
            display_name=display_name,
            password_hash=hash_password(password),
            role=role if not is_admin else None,
            is_admin=is_admin,
            admin_roles=admin_roles if is_admin else [],
            is_superadmin=False,
            created_by=caller.user_id if caller else "system",
            password_changed_at=datetime.now().isoformat(),
        )
        rec = _user_store.create_user(rec)
    except ValueError as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=409)

    if _app_log_fn:
        _app_log_fn(f"Users: '{caller.username if caller else '?'}' created user '{username}' with role '{role or admin_roles}'")
    if _audit_store:
        _audit_store.log_event("user_created", user_id=rec.user_id, username=username,
                               actor_id=caller.user_id if caller else "", actor_name=caller.username if caller else "")

    return JSONResponse({"status": "ok", "user": _user_to_dict(rec)}, status_code=201)


@router.put("/{user_id}")
async def update_user(user_id: str, request: Request) -> JSONResponse:
    err = _require_access_guard(request)
    if err:
        return err
    assert _user_store

    existing = _user_store.get_user(user_id)
    if existing is None:
        return JSONResponse({"status": "error", "message": "User not found"}, status_code=404)

    # Cannot edit superadmin unless you ARE superadmin
    caller = getattr(request.state, "user", None)
    if existing.is_superadmin and (not caller or not caller.is_superadmin):
        return JSONResponse({"status": "error", "message": "Cannot modify Główny Opiekun"}, status_code=403)

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"status": "error", "message": "Invalid request"}, status_code=400)

    updates: dict = {}

    if "display_name" in body:
        updates["display_name"] = (body["display_name"] or "").strip()
    if "role" in body:
        role = body["role"]
        if role and role not in ALL_USER_ROLES:
            return JSONResponse({"status": "error", "message": f"Invalid role: {role}"}, status_code=400)
        updates["role"] = role
    if "is_admin" in body:
        updates["is_admin"] = bool(body["is_admin"])
    if "admin_roles" in body:
        for ar in body["admin_roles"]:
            if ar not in ALL_ADMIN_ROLES:
                return JSONResponse({"status": "error", "message": f"Invalid admin role: {ar}"}, status_code=400)
        updates["admin_roles"] = body["admin_roles"]
    if "password" in body and body["password"]:
        if len(body["password"]) < 6:
            return JSONResponse({"status": "error", "message": "Password must be at least 6 characters"}, status_code=400)
        pw_err = validate_password_strength(body["password"], _pw_policy())
        if pw_err:
            return JSONResponse({"status": "error", "message": pw_err}, status_code=400)
        updates["password_hash"] = hash_password(body["password"])
        updates["password_changed_at"] = datetime.now().isoformat()

    try:
        updated = _user_store.update_user(user_id, updates)
    except ValueError as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=409)

    if _app_log_fn:
        _app_log_fn(f"Users: '{caller.username if caller else '?'}' updated user '{existing.username}'")

    return JSONResponse({"status": "ok", "user": _user_to_dict(updated)})


@router.delete("/{user_id}")
async def delete_user(user_id: str, request: Request) -> JSONResponse:
    err = _require_access_guard(request)
    if err:
        return err
    assert _user_store and _session_store

    existing = _user_store.get_user(user_id)
    if existing is None:
        return JSONResponse({"status": "error", "message": "User not found"}, status_code=404)

    if existing.is_superadmin:
        return JSONResponse({"status": "error", "message": "Cannot delete Główny Opiekun"}, status_code=403)

    caller = getattr(request.state, "user", None)
    if caller and caller.user_id == user_id:
        return JSONResponse({"status": "error", "message": "Cannot delete yourself"}, status_code=403)

    _session_store.delete_user_sessions(user_id)
    _user_store.delete_user(user_id)

    if _app_log_fn:
        _app_log_fn(f"Users: '{caller.username if caller else '?'}' deleted user '{existing.username}'")
    if _audit_store:
        _audit_store.log_event("user_deleted", user_id=user_id, username=existing.username,
                               actor_id=caller.user_id if caller else "", actor_name=caller.username if caller else "")

    return JSONResponse({"status": "ok"})


@router.post("/{user_id}/ban")
async def ban_user(user_id: str, request: Request) -> JSONResponse:
    err = _require_access_guard(request)
    if err:
        return err
    assert _user_store and _session_store

    existing = _user_store.get_user(user_id)
    if existing is None:
        return JSONResponse({"status": "error", "message": "User not found"}, status_code=404)
    if existing.is_superadmin:
        return JSONResponse({"status": "error", "message": "Cannot ban Główny Opiekun"}, status_code=403)

    caller = getattr(request.state, "user", None)
    if caller and caller.user_id == user_id:
        return JSONResponse({"status": "error", "message": "Cannot ban yourself"}, status_code=403)

    try:
        body = await request.json()
    except Exception:
        body = {}

    reason = body.get("reason", "")
    until = body.get("until")  # ISO datetime string or None
    show_ban_expiry = bool(body.get("show_ban_expiry", True))

    _user_store.update_user(user_id, {
        "banned": True,
        "banned_until": until,
        "ban_reason": reason,
        "show_ban_expiry": show_ban_expiry,
    })

    # Immediately invalidate all sessions
    removed = _session_store.delete_user_sessions(user_id)

    if _app_log_fn:
        _app_log_fn(f"Users: '{caller.username if caller else '?'}' banned '{existing.username}' (reason: {reason}, sessions removed: {removed})")
    if _audit_store:
        _audit_store.log_event("user_banned", user_id=user_id, username=existing.username,
                               detail=f"reason: {reason}", actor_id=caller.user_id if caller else "", actor_name=caller.username if caller else "")

    return JSONResponse({"status": "ok", "sessions_removed": removed})


@router.post("/{user_id}/unban")
async def unban_user(user_id: str, request: Request) -> JSONResponse:
    err = _require_access_guard(request)
    if err:
        return err
    assert _user_store

    existing = _user_store.get_user(user_id)
    if existing is None:
        return JSONResponse({"status": "error", "message": "User not found"}, status_code=404)

    _user_store.update_user(user_id, {"banned": False, "banned_until": None, "ban_reason": None, "show_ban_expiry": True})

    caller = getattr(request.state, "user", None)
    if _app_log_fn:
        _app_log_fn(f"Users: '{caller.username if caller else '?'}' unbanned '{existing.username}'")
    if _audit_store:
        _audit_store.log_event("user_unbanned", user_id=user_id, username=existing.username,
                               actor_id=caller.user_id if caller else "", actor_name=caller.username if caller else "")

    return JSONResponse({"status": "ok"})


@router.post("/{user_id}/approve")
async def approve_user(user_id: str, request: Request) -> JSONResponse:
    err = _require_access_guard(request)
    if err:
        return err
    assert _user_store

    existing = _user_store.get_user(user_id)
    if existing is None:
        return JSONResponse({"status": "error", "message": "User not found"}, status_code=404)

    if not existing.pending:
        return JSONResponse({"status": "error", "message": "User is not pending"}, status_code=400)

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"status": "error", "message": "Invalid request"}, status_code=400)

    role = body.get("role")
    is_admin = bool(body.get("is_admin", False))
    admin_roles = body.get("admin_roles") or []

    if not is_admin and (not role or role not in ALL_USER_ROLES):
        return JSONResponse({"status": "error", "message": f"Invalid role: {role}"}, status_code=400)
    if is_admin:
        for ar in admin_roles:
            if ar not in ALL_ADMIN_ROLES:
                return JSONResponse({"status": "error", "message": f"Invalid admin role: {ar}"}, status_code=400)

    updates: dict = {
        "pending": False,
        "pending_role": None,
        "role": role if not is_admin else None,
        "is_admin": is_admin,
        "admin_roles": admin_roles if is_admin else [],
    }

    updated = _user_store.update_user(user_id, updates)

    caller = getattr(request.state, "user", None)
    if _app_log_fn:
        _app_log_fn(f"Users: '{caller.username if caller else '?'}' approved user '{existing.username}' with role '{role or admin_roles}'")
    if _audit_store:
        _audit_store.log_event("user_approved", user_id=user_id, username=existing.username,
                               actor_id=caller.user_id if caller else "", actor_name=caller.username if caller else "")

    return JSONResponse({"status": "ok", "user": _user_to_dict(updated)})


@router.post("/{user_id}/reject")
async def reject_user(user_id: str, request: Request) -> JSONResponse:
    err = _require_access_guard(request)
    if err:
        return err
    assert _user_store

    existing = _user_store.get_user(user_id)
    if existing is None:
        return JSONResponse({"status": "error", "message": "User not found"}, status_code=404)

    if not existing.pending:
        return JSONResponse({"status": "error", "message": "User is not pending"}, status_code=400)

    _user_store.delete_user(user_id)

    caller = getattr(request.state, "user", None)
    if _app_log_fn:
        _app_log_fn(f"Users: '{caller.username if caller else '?'}' rejected pending user '{existing.username}'")
    if _audit_store:
        _audit_store.log_event("user_rejected", user_id=user_id, username=existing.username,
                               actor_id=caller.user_id if caller else "", actor_name=caller.username if caller else "")

    return JSONResponse({"status": "ok"})


@router.post("/{user_id}/reset-password")
async def reset_password(user_id: str, request: Request) -> JSONResponse:
    err = _require_access_guard(request)
    if err:
        return err
    assert _user_store

    existing = _user_store.get_user(user_id)
    if existing is None:
        return JSONResponse({"status": "error", "message": "User not found"}, status_code=404)

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"status": "error", "message": "Invalid request"}, status_code=400)

    new_pass = body.get("new_password") or ""
    if len(new_pass) < 6:
        return JSONResponse({"status": "error", "message": "Password must be at least 6 characters"}, status_code=400)

    # Password policy check
    pw_err = validate_password_strength(new_pass, _pw_policy())
    if pw_err:
        return JSONResponse({"status": "error", "message": pw_err}, status_code=400)

    _user_store.update_user(user_id, {
        "password_hash": hash_password(new_pass),
        "password_reset_requested": False,
        "password_reset_requested_at": None,
        "password_changed_at": datetime.now().isoformat(),
    })

    caller = getattr(request.state, "user", None)
    if _app_log_fn:
        _app_log_fn(f"Users: '{caller.username if caller else '?'}' reset password for '{existing.username}'")
    if _audit_store:
        _audit_store.log_event("password_reset", user_id=user_id, username=existing.username,
                               actor_id=caller.user_id if caller else "", actor_name=caller.username if caller else "")

    return JSONResponse({"status": "ok"})


@router.post("/{user_id}/unlock")
async def unlock_user(user_id: str, request: Request) -> JSONResponse:
    """Admin endpoint: manually unlock a locked account."""
    err = _require_access_guard(request)
    if err:
        return err
    assert _user_store

    existing = _user_store.get_user(user_id)
    if existing is None:
        return JSONResponse({"status": "error", "message": "User not found"}, status_code=404)

    _user_store.update_user(user_id, {"locked_until": None, "failed_login_count": 0})

    caller = getattr(request.state, "user", None)
    if _app_log_fn:
        _app_log_fn(f"Users: '{caller.username if caller else '?'}' unlocked '{existing.username}'")
    if _audit_store:
        _audit_store.log_event("account_unlocked", user_id=user_id, username=existing.username,
                               detail="manual unlock by admin",
                               actor_id=caller.user_id if caller else "", actor_name=caller.username if caller else "")

    return JSONResponse({"status": "ok"})
