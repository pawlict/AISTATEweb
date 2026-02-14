from __future__ import annotations

from typing import Any, Callable, Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from webapp.auth.message_store import MessageStore, Message

router = APIRouter(prefix="/api/messages", tags=["messages"])

_message_store: Optional[MessageStore] = None
_app_log_fn: Optional[Callable] = None


def init(message_store: MessageStore, app_log_fn: Callable) -> None:
    global _message_store, _app_log_fn
    _message_store = message_store
    _app_log_fn = app_log_fn


def _msg_to_dict(m: Message) -> dict:
    return {
        "message_id": m.message_id,
        "author_id": m.author_id,
        "author_name": m.author_name,
        "subject": m.subject,
        "content": m.content,
        "target_groups": m.target_groups,
        "created_at": m.created_at,
        "read_by": m.read_by,
    }


@router.get("/unread")
async def get_unread(request: Request) -> JSONResponse:
    """Return unread messages for the current user."""
    user = getattr(request.state, "user", None)
    if user is None:
        return JSONResponse({"status": "error", "message": "Not authenticated"}, status_code=401)
    assert _message_store

    msgs = _message_store.get_unread_for_user(
        user_id=user.user_id,
        user_role=user.role,
        is_admin=user.is_admin,
        admin_roles=user.admin_roles,
        is_superadmin=user.is_superadmin,
    )
    return JSONResponse({"status": "ok", "messages": [_msg_to_dict(m) for m in msgs]})


@router.post("/{message_id}/read")
async def mark_read(message_id: str, request: Request) -> JSONResponse:
    """Mark a message as read by the current user."""
    user = getattr(request.state, "user", None)
    if user is None:
        return JSONResponse({"status": "error", "message": "Not authenticated"}, status_code=401)
    assert _message_store

    ok = _message_store.mark_read(message_id, user.user_id)
    if not ok:
        return JSONResponse({"status": "error", "message": "Message not found"}, status_code=404)
    return JSONResponse({"status": "ok"})


def _require_superadmin(request: Request) -> Optional[JSONResponse]:
    """Only Główny Opiekun can manage messages (for now)."""
    user = getattr(request.state, "user", None)
    if user is None:
        return JSONResponse({"status": "error", "message": "Not authenticated"}, status_code=401)
    if not user.is_superadmin:
        return JSONResponse({"status": "error", "message": "Only Główny Opiekun can manage messages"}, status_code=403)
    return None


@router.get("")
async def list_messages(request: Request) -> JSONResponse:
    """List all messages (admin only)."""
    err = _require_superadmin(request)
    if err:
        return err
    assert _message_store

    msgs = _message_store.list_messages()
    return JSONResponse({"status": "ok", "messages": [_msg_to_dict(m) for m in msgs]})


@router.post("")
async def create_message(request: Request) -> JSONResponse:
    """Create a new Call Center message."""
    err = _require_superadmin(request)
    if err:
        return err
    assert _message_store

    user = request.state.user
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"status": "error", "message": "Invalid request"}, status_code=400)

    subject = (body.get("subject") or "").strip()
    content = (body.get("content") or "").strip()
    target_groups = body.get("target_groups") or []

    if not subject:
        return JSONResponse({"status": "error", "message": "Subject required"}, status_code=400)
    if not content:
        return JSONResponse({"status": "error", "message": "Content required"}, status_code=400)
    if not target_groups:
        return JSONResponse({"status": "error", "message": "At least one target group required"}, status_code=400)

    msg = Message(
        author_id=user.user_id,
        author_name=user.display_name or user.username,
        subject=subject,
        content=content,
        target_groups=target_groups,
    )
    msg = _message_store.create_message(msg)

    if _app_log_fn:
        _app_log_fn(f"Messages: '{user.username}' sent message '{subject}' to groups: {target_groups}")

    return JSONResponse({"status": "ok", "message": _msg_to_dict(msg)}, status_code=201)


@router.delete("/{message_id}")
async def delete_message(message_id: str, request: Request) -> JSONResponse:
    """Delete a message."""
    err = _require_superadmin(request)
    if err:
        return err
    assert _message_store

    ok = _message_store.delete_message(message_id)
    if not ok:
        return JSONResponse({"status": "error", "message": "Message not found"}, status_code=404)

    user = request.state.user
    if _app_log_fn:
        _app_log_fn(f"Messages: '{user.username}' deleted message '{message_id}'")

    return JSONResponse({"status": "ok"})
