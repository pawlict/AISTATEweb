"""API router for project workspaces, subprojects, members, invitations.

Prefix: /api/workspaces

NOTE: Static paths (like /invitations/mine) MUST be registered before
parametric paths (/{workspace_id}) to avoid FastAPI matching "invitations"
as a workspace_id.
"""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/api/workspaces", tags=["workspaces"])

# Injected from server.py
_STORE = None   # WorkspaceStore
_USER_STORE = None


def init(*, workspace_store, user_store) -> None:
    global _STORE, _USER_STORE
    _STORE = workspace_store
    _USER_STORE = user_store


def _uid(request: Request) -> str:
    """Get current user ID (multiuser or default admin)."""
    user = getattr(request.state, "user", None)
    if user:
        return user.user_id
    from backend.db.engine import get_default_user_id
    return get_default_user_id()


def _uname(request: Request) -> str:
    user = getattr(request.state, "user", None)
    if user:
        return user.display_name or user.username
    return "admin"


def _is_admin(request: Request) -> bool:
    user = getattr(request.state, "user", None)
    return bool(user and (user.is_admin or user.is_superadmin))


def _default_subproject_type(request: Request) -> str:
    """Determine default subproject type based on user's role."""
    user = getattr(request.state, "user", None)
    if not user or not getattr(user, "role", None):
        return "analysis"
    role = user.role
    _ROLE_TYPE_MAP = {
        "Transkryptor": "transcription",
        "Lingwista": "translation",
        "Analityk": "analysis",
        "Dialogista": "chat",
        "Strateg": "analysis",
        "Mistrz Sesji": "analysis",
    }
    return _ROLE_TYPE_MAP.get(role, "analysis")


def _ensure_data_dir(name: str, owner_id: str) -> str:
    """Create a file-based project directory and return its relative path."""
    import uuid
    import json
    from pathlib import Path
    from datetime import datetime
    import os

    _root = Path(__file__).resolve().parents[2]
    data_root = Path(
        os.environ.get("AISTATEWEB_DATA_DIR")
        or os.environ.get("AISTATEWWW_DATA_DIR")
        or os.environ.get("AISTATE_DATA_DIR")
        or str(_root / "data_www")
    ).resolve()
    projects_dir = data_root / "projects"
    projects_dir.mkdir(parents=True, exist_ok=True)

    pid = uuid.uuid4().hex
    pdir = projects_dir / pid
    pdir.mkdir(parents=True, exist_ok=True)
    meta = {
        "project_id": pid,
        "name": name,
        "created_at": datetime.now().isoformat(),
        "owner_id": owner_id,
    }
    meta_path = pdir / "project.json"
    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    return f"projects/{pid}"


# =====================================================================
# INVITATIONS — must be before /{workspace_id} to avoid route conflict
# =====================================================================

@router.get("/invitations/mine")
def my_invitations(request: Request):
    uid = _uid(request)
    invitations = _STORE.list_invitations_for_user(uid)
    return JSONResponse({"status": "ok", "invitations": invitations})


@router.post("/bulk-delete")
async def bulk_delete_workspaces(request: Request):
    """Delete multiple workspaces with all their subprojects and data directories."""
    body = await request.json()
    workspace_ids = body.get("workspace_ids", [])
    wipe_method = (body.get("wipe_method") or "none").strip().lower()

    if not workspace_ids or not isinstance(workspace_ids, list):
        return JSONResponse({"status": "error", "message": "workspace_ids required"}, 400)

    uid = _uid(request)
    is_admin = _is_admin(request)
    deleted = []
    errors = []

    for ws_id in workspace_ids:
        # Verify ownership
        role = _STORE.get_user_role(ws_id, uid)
        if role != "owner" and not is_admin:
            errors.append({"id": ws_id, "message": "Only owner can delete"})
            continue

        ws = _STORE.get_workspace(ws_id)
        if ws is None:
            errors.append({"id": ws_id, "message": "Not found"})
            continue

        # Delete all subproject data directories with wipe
        subs = _STORE.list_subprojects(ws_id)
        for sp in subs:
            data_dir = sp.get("data_dir", "")
            if data_dir:
                dir_id = data_dir.replace("projects/", "")
                if dir_id:
                    try:
                        _delete_project_data(dir_id, wipe_method)
                    except Exception:
                        pass  # best-effort

        # Hard-delete workspace + all DB records
        _STORE.hard_delete_workspace(ws_id)
        deleted.append(ws_id)

    return JSONResponse({
        "status": "ok",
        "deleted": deleted,
        "errors": errors,
    })


def _delete_project_data(project_id: str, wipe_method: str = "none"):
    """Delete a project data directory with optional secure wipe."""
    import os
    from pathlib import Path

    _root = Path(__file__).resolve().parents[2]
    data_root = Path(
        os.environ.get("AISTATEWEB_DATA_DIR")
        or os.environ.get("AISTATEWWW_DATA_DIR")
        or os.environ.get("AISTATE_DATA_DIR")
        or str(_root / "data_www")
    ).resolve()
    projects_dir = data_root / "projects"
    pdir = (projects_dir / project_id).resolve()

    if not pdir.exists() or not pdir.is_dir():
        return
    if projects_dir.resolve() not in pdir.parents:
        return

    try:
        from webapp.server import secure_delete_project_dir
        secure_delete_project_dir(pdir, wipe_method)
    except ImportError:
        import shutil
        shutil.rmtree(pdir, ignore_errors=True)


@router.post("/invitations/{invitation_id}/accept")
def accept_invitation(request: Request, invitation_id: str):
    uid = _uid(request)
    ok = _STORE.respond_invitation(invitation_id, uid, accept=True)
    if not ok:
        return JSONResponse({"status": "error", "message": "Invitation not found or already responded"}, 404)
    return JSONResponse({"status": "ok"})


@router.post("/invitations/{invitation_id}/reject")
def reject_invitation(request: Request, invitation_id: str):
    uid = _uid(request)
    ok = _STORE.respond_invitation(invitation_id, uid, accept=False)
    if not ok:
        return JSONResponse({"status": "error", "message": "Invitation not found or already responded"}, 404)
    return JSONResponse({"status": "ok"})


# =====================================================================
# WORKSPACES
# =====================================================================

@router.get("")
def list_workspaces(request: Request, status: str = "active"):
    uid = _uid(request)
    # Admins/superadmins see all workspaces
    if _is_admin(request):
        from backend.db.engine import get_conn
        with get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM project_workspaces WHERE status = ? ORDER BY updated_at DESC",
                (status,),
            ).fetchall()
            workspaces = []
            for r in rows:
                ws = dict(r)
                ws["member_count"] = conn.execute(
                    "SELECT COUNT(*) as cnt FROM project_members WHERE workspace_id = ? AND status='accepted'",
                    (ws["id"],),
                ).fetchone()["cnt"]
                ws["subproject_count"] = conn.execute(
                    "SELECT COUNT(*) as cnt FROM subprojects WHERE workspace_id = ?",
                    (ws["id"],),
                ).fetchone()["cnt"]
                ws["my_role"] = _STORE.get_user_role(ws["id"], uid) or "admin"
                ws["members"] = _STORE.list_members(ws["id"])
                workspaces.append(ws)
        return JSONResponse({"status": "ok", "workspaces": workspaces})
    workspaces = _STORE.list_workspaces(uid, status)
    return JSONResponse({"status": "ok", "workspaces": workspaces})


@router.post("")
async def create_workspace(request: Request):
    body = await request.json()
    name = (body.get("name") or "").strip()
    if not name:
        return JSONResponse({"status": "error", "message": "Name is required"}, 400)
    uid = _uid(request)
    ws = _STORE.create_workspace(
        owner_id=uid,
        name=name,
        description=body.get("description", ""),
        color=body.get("color", "#4a6cf7"),
        icon=body.get("icon", "folder"),
    )

    # Return workspace — user picks subproject type via the UI modal
    ws["subprojects"] = []

    return JSONResponse({"status": "ok", "workspace": ws})


# NOTE: /default MUST be before /{workspace_id} to avoid route conflict
@router.get("/default")
def get_default_workspace(request: Request):
    """Return user's default workspace (auto-create if none exists)."""
    uid = _uid(request)
    workspaces = _STORE.list_workspaces(uid, status="active")
    if not workspaces:
        ws = _STORE.create_workspace(owner_id=uid, name="Moje projekty")
    else:
        ws = _STORE.get_workspace(workspaces[0]["id"])
    if ws is None:
        return JSONResponse({"status": "error", "message": "Workspace error"}, 500)
    ws["my_role"] = _STORE.get_user_role(ws["id"], uid) or "owner"
    ws["members"] = _STORE.list_members(ws["id"])
    ws["subprojects"] = _STORE.list_subprojects(ws["id"])
    ws["activity"] = _STORE.get_activity(ws["id"], limit=20)
    return JSONResponse({"status": "ok", "workspace": ws})


@router.get("/{workspace_id}")
def get_workspace(request: Request, workspace_id: str):
    uid = _uid(request)
    ws = _STORE.get_workspace(workspace_id)
    if ws is None:
        return JSONResponse({"status": "error", "message": "Not found"}, 404)
    if not _STORE.can_user_access(workspace_id, uid) and not _is_admin(request):
        return JSONResponse({"status": "error", "message": "Access denied"}, 403)
    ws["my_role"] = _STORE.get_user_role(workspace_id, uid) or ("admin" if _is_admin(request) else None)
    ws["members"] = _STORE.list_members(workspace_id)
    ws["subprojects"] = _STORE.list_subprojects(workspace_id)
    ws["activity"] = _STORE.get_activity(workspace_id, limit=20)
    return JSONResponse({"status": "ok", "workspace": ws})


@router.patch("/{workspace_id}")
async def update_workspace(request: Request, workspace_id: str):
    uid = _uid(request)
    if not _STORE.can_user_manage(workspace_id, uid) and not _is_admin(request):
        return JSONResponse({"status": "error", "message": "Access denied"}, 403)
    body = await request.json()
    ws = _STORE.update_workspace(workspace_id, **body)
    if ws is None:
        return JSONResponse({"status": "error", "message": "Not found"}, 404)
    return JSONResponse({"status": "ok", "workspace": ws})


@router.delete("/{workspace_id}")
def delete_workspace(request: Request, workspace_id: str, wipe_method: str = "none"):
    uid = _uid(request)
    role = _STORE.get_user_role(workspace_id, uid)
    if role != "owner" and not _is_admin(request):
        return JSONResponse({"status": "error", "message": "Only owner can delete"}, 403)
    # Delete all subproject data directories before removing workspace from DB
    subs = _STORE.list_subprojects(workspace_id)
    for sp in subs:
        data_dir = sp.get("data_dir", "")
        if data_dir:
            dir_id = data_dir.replace("projects/", "")
            if dir_id:
                try:
                    _delete_project_data(dir_id, wipe_method)
                except Exception:
                    pass  # best-effort
    _STORE.delete_workspace(workspace_id)
    return JSONResponse({"status": "ok"})


# =====================================================================
# SUBPROJECTS
# =====================================================================

@router.get("/{workspace_id}/subprojects")
def list_subprojects(request: Request, workspace_id: str):
    uid = _uid(request)
    if not _STORE.can_user_access(workspace_id, uid) and not _is_admin(request):
        return JSONResponse({"status": "error", "message": "Access denied"}, 403)
    subs = _STORE.list_subprojects(workspace_id)
    return JSONResponse({"status": "ok", "subprojects": subs})


@router.post("/{workspace_id}/subprojects")
async def create_subproject(request: Request, workspace_id: str):
    uid = _uid(request)
    if not _STORE.can_user_edit(workspace_id, uid) and not _is_admin(request):
        return JSONResponse({"status": "error", "message": "Access denied"}, 403)
    body = await request.json()
    name = (body.get("name") or "").strip()
    if not name:
        return JSONResponse({"status": "error", "message": "Name is required"}, 400)

    sp_type = body.get("type", "analysis")
    data_dir = body.get("data_dir", "")
    audio_file = body.get("audio_file", "")
    link_to = body.get("link_to", "")

    # Auto-create file-based project directory if not provided
    if not data_dir:
        data_dir = _ensure_data_dir(name, uid)

    sp = _STORE.create_subproject(
        workspace_id=workspace_id,
        name=name,
        subproject_type=sp_type,
        data_dir=data_dir,
        audio_file=audio_file,
        created_by=uid,
        user_name=_uname(request),
    )

    if link_to:
        try:
            _STORE.link_subprojects(sp["id"], link_to)
        except Exception:
            pass

    return JSONResponse({"status": "ok", "subproject": sp})


@router.get("/{workspace_id}/subprojects/{subproject_id}")
def get_subproject(request: Request, workspace_id: str, subproject_id: str):
    uid = _uid(request)
    if not _STORE.can_user_access(workspace_id, uid) and not _is_admin(request):
        return JSONResponse({"status": "error", "message": "Access denied"}, 403)
    sp = _STORE.get_subproject(subproject_id)
    if sp is None:
        return JSONResponse({"status": "error", "message": "Not found"}, 404)
    return JSONResponse({"status": "ok", "subproject": sp})


@router.patch("/{workspace_id}/subprojects/{subproject_id}")
async def update_subproject(request: Request, workspace_id: str, subproject_id: str):
    uid = _uid(request)
    if not _STORE.can_user_edit(workspace_id, uid) and not _is_admin(request):
        return JSONResponse({"status": "error", "message": "Access denied"}, 403)
    body = await request.json()
    sp = _STORE.update_subproject(subproject_id, **body)
    if sp is None:
        return JSONResponse({"status": "error", "message": "Not found"}, 404)
    _STORE.log_activity(workspace_id, subproject_id, uid, _uname(request), "updated")
    return JSONResponse({"status": "ok", "subproject": sp})


@router.delete("/{workspace_id}/subprojects/{subproject_id}")
def delete_subproject(request: Request, workspace_id: str, subproject_id: str,
                      wipe_method: str = "none"):
    uid = _uid(request)
    if not _STORE.can_user_edit(workspace_id, uid) and not _is_admin(request):
        return JSONResponse({"status": "error", "message": "Access denied"}, 403)
    # Get subproject data_dir BEFORE deleting from DB so we can clean up files
    sp = _STORE.get_subproject(subproject_id)
    data_dir = sp.get("data_dir", "") if sp else ""
    if data_dir:
        dir_id = data_dir.replace("projects/", "")
        if dir_id:
            try:
                _delete_project_data(dir_id, wipe_method)
            except Exception:
                pass  # best-effort
    _STORE.delete_subproject(subproject_id)
    _STORE.log_activity(workspace_id, None, uid, _uname(request), "subproject_deleted")
    return JSONResponse({"status": "ok"})


# =====================================================================
# LINKS
# =====================================================================

@router.post("/{workspace_id}/subprojects/{subproject_id}/links")
async def link_subproject(request: Request, workspace_id: str, subproject_id: str):
    uid = _uid(request)
    if not _STORE.can_user_edit(workspace_id, uid) and not _is_admin(request):
        return JSONResponse({"status": "error", "message": "Access denied"}, 403)
    body = await request.json()
    target_id = body.get("target_id", "")
    if not target_id:
        return JSONResponse({"status": "error", "message": "target_id required"}, 400)
    link = _STORE.link_subprojects(subproject_id, target_id,
                                    body.get("link_type", "related"), body.get("note", ""))
    _STORE.log_activity(workspace_id, subproject_id, uid, _uname(request), "linked",
                        {"target_id": target_id})
    return JSONResponse({"status": "ok", "link": link})


@router.delete("/{workspace_id}/subprojects/{subproject_id}/links/{target_id}")
def unlink_subproject(request: Request, workspace_id: str, subproject_id: str, target_id: str):
    uid = _uid(request)
    if not _STORE.can_user_edit(workspace_id, uid) and not _is_admin(request):
        return JSONResponse({"status": "error", "message": "Access denied"}, 403)
    _STORE.unlink_subprojects(subproject_id, target_id)
    return JSONResponse({"status": "ok"})


# =====================================================================
# MEMBERS
# =====================================================================

@router.get("/{workspace_id}/members")
def list_members(request: Request, workspace_id: str):
    uid = _uid(request)
    if not _STORE.can_user_access(workspace_id, uid) and not _is_admin(request):
        return JSONResponse({"status": "error", "message": "Access denied"}, 403)
    members = _STORE.list_members(workspace_id)
    return JSONResponse({"status": "ok", "members": members})


@router.patch("/{workspace_id}/members/{member_user_id}")
async def update_member(request: Request, workspace_id: str, member_user_id: str):
    uid = _uid(request)
    if not _STORE.can_user_manage(workspace_id, uid) and not _is_admin(request):
        return JSONResponse({"status": "error", "message": "Access denied"}, 403)
    body = await request.json()
    new_role = body.get("role", "")
    if new_role not in ("manager", "editor", "viewer"):
        return JSONResponse({"status": "error", "message": "Invalid role"}, 400)
    _STORE.update_member_role(workspace_id, member_user_id, new_role)
    _STORE.log_activity(workspace_id, None, uid, _uname(request), "member_updated",
                        {"target_user": member_user_id, "new_role": new_role})
    return JSONResponse({"status": "ok"})


@router.delete("/{workspace_id}/members/{member_user_id}")
def remove_member(request: Request, workspace_id: str, member_user_id: str):
    uid = _uid(request)
    if not _STORE.can_user_manage(workspace_id, uid) and not _is_admin(request):
        return JSONResponse({"status": "error", "message": "Access denied"}, 403)
    _STORE.remove_member(workspace_id, member_user_id)
    _STORE.log_activity(workspace_id, None, uid, _uname(request), "member_removed",
                        {"target_user": member_user_id})
    return JSONResponse({"status": "ok"})


# =====================================================================
# INVITE (POST under workspace path — no conflict with /{workspace_id})
# =====================================================================

@router.post("/{workspace_id}/invite")
async def invite_user(request: Request, workspace_id: str):
    uid = _uid(request)
    if not _STORE.can_user_manage(workspace_id, uid) and not _is_admin(request):
        return JSONResponse({"status": "error", "message": "Access denied"}, 403)
    body = await request.json()
    username = (body.get("username") or "").strip()
    role = body.get("role", "viewer")
    message = body.get("message", "")

    if not username:
        return JSONResponse({"status": "error", "message": "Username required"}, 400)
    if role not in ("manager", "editor", "viewer"):
        return JSONResponse({"status": "error", "message": "Invalid role"}, 400)

    target_user = _USER_STORE.get_by_username(username)
    if target_user is None:
        return JSONResponse({"status": "error", "message": f"User '{username}' not found"}, 404)

    try:
        inv = _STORE.create_invitation(workspace_id, uid, target_user.user_id, role, message)
    except ValueError as e:
        return JSONResponse({"status": "error", "message": str(e)}, 409)

    _STORE.log_activity(workspace_id, None, uid, _uname(request), "invitation_sent",
                        {"invitee": username, "role": role})
    return JSONResponse({"status": "ok", "invitation": inv})


# =====================================================================
# ACTIVITY
# =====================================================================

@router.get("/{workspace_id}/activity")
def get_activity(request: Request, workspace_id: str, limit: int = 30):
    uid = _uid(request)
    if not _STORE.can_user_access(workspace_id, uid) and not _is_admin(request):
        return JSONResponse({"status": "error", "message": "Access denied"}, 403)
    activity = _STORE.get_activity(workspace_id, limit)
    return JSONResponse({"status": "ok", "activity": activity})
