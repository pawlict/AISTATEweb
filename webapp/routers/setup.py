from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from webapp.auth.passwords import hash_password
from webapp.auth.user_store import UserStore, UserRecord
from webapp.auth.deployment_store import DeploymentStore

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/setup", tags=["setup"])

_user_store: Optional[UserStore] = None
_deployment_store: Optional[DeploymentStore] = None
_app_log_fn: Optional[Callable] = None
_projects_dir: Optional[Path] = None


def init(
    user_store: UserStore,
    deployment_store: DeploymentStore,
    app_log_fn: Callable,
    projects_dir: Path,
) -> None:
    global _user_store, _deployment_store, _app_log_fn, _projects_dir
    _user_store = user_store
    _deployment_store = deployment_store
    _app_log_fn = app_log_fn
    _projects_dir = projects_dir


@router.get("/status")
async def setup_status(request: Request) -> JSONResponse:
    assert _deployment_store and _user_store
    mode = _deployment_store.get_mode()
    has_users = _user_store.has_users()
    return JSONResponse({
        "status": "ok",
        "mode": mode,
        "configured": _deployment_store.is_configured(),
        "has_users": has_users,
    })


@router.post("/mode")
async def set_mode(request: Request) -> JSONResponse:
    assert _deployment_store
    if _deployment_store.is_configured():
        return JSONResponse({"status": "error", "message": "Already configured"}, status_code=400)

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"status": "error", "message": "Invalid request"}, status_code=400)

    mode = body.get("mode")
    if mode not in ("single", "multi"):
        return JSONResponse({"status": "error", "message": "Mode must be 'single' or 'multi'"}, status_code=400)

    _deployment_store.set_mode(mode)

    if _app_log_fn:
        _app_log_fn(f"Setup: deployment mode set to '{mode}'")

    return JSONResponse({"status": "ok", "mode": mode})


@router.post("/admin")
async def create_first_admin(request: Request) -> JSONResponse:
    """Create the first Główny Opiekun account during setup."""
    assert _deployment_store and _user_store

    if not _deployment_store.is_multiuser():
        return JSONResponse({"status": "error", "message": "Multi-user mode not enabled"}, status_code=400)

    if _user_store.has_users():
        return JSONResponse({"status": "error", "message": "Admin already exists"}, status_code=400)

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"status": "error", "message": "Invalid request"}, status_code=400)

    username = (body.get("username") or "").strip()
    display_name = (body.get("display_name") or username).strip()
    password = body.get("password") or ""

    if not username:
        return JSONResponse({"status": "error", "message": "Username required"}, status_code=400)
    if len(password) < 12:
        return JSONResponse({"status": "error", "message": "Password must be at least 12 characters"}, status_code=400)

    rec = UserRecord(
        username=username,
        display_name=display_name,
        password_hash=hash_password(password),
        role=None,
        is_admin=True,
        admin_roles=["Architekt Funkcji", "Strażnik Dostępu"],
        is_superadmin=True,
        created_by="system",
        password_changed_at=datetime.now().isoformat(),
    )
    rec = _user_store.create_user(rec)

    if _app_log_fn:
        _app_log_fn(f"Setup: Główny Opiekun '{username}' created")

    return JSONResponse({"status": "ok", "user_id": rec.user_id}, status_code=201)


@router.get("/projects")
async def list_existing_projects(request: Request) -> JSONResponse:
    """List existing projects for migration wizard."""
    assert _projects_dir
    projects: List[Dict[str, Any]] = []
    if _projects_dir.exists():
        for d in sorted(_projects_dir.iterdir()):
            if not d.is_dir() or d.name.startswith("_"):
                continue
            meta_path = d / "project.json"
            if meta_path.exists():
                try:
                    meta = json.loads(meta_path.read_text(encoding="utf-8"))
                    projects.append({
                        "project_id": d.name,
                        "name": meta.get("name", d.name),
                        "created_at": meta.get("created_at", ""),
                    })
                except Exception:
                    projects.append({"project_id": d.name, "name": d.name, "created_at": ""})

    return JSONResponse({"status": "ok", "projects": projects})


@router.post("/migrate")
async def migrate_projects(request: Request) -> JSONResponse:
    """Assign owners to existing projects during migration."""
    assert _projects_dir and _user_store

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"status": "error", "message": "Invalid request"}, status_code=400)

    assignments = body.get("assignments") or {}
    # assignments: { "project_id": "user_id" }

    migrated = 0
    for project_id, owner_id in assignments.items():
        meta_path = _projects_dir / project_id / "project.json"
        if not meta_path.exists():
            continue
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            meta["owner_id"] = owner_id
            if "shares" not in meta:
                meta["shares"] = []
            tmp = meta_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
            tmp.replace(meta_path)
            migrated += 1
        except Exception:
            continue

    if _app_log_fn:
        _app_log_fn(f"Setup: migrated {migrated} projects")

    return JSONResponse({"status": "ok", "migrated": migrated})


@router.get("/backups")
async def setup_list_backups(request: Request) -> JSONResponse:
    """List available backups for restore during initial setup."""
    from starlette.concurrency import run_in_threadpool
    from backend.db.backup import list_backups

    try:
        backups = await run_in_threadpool(list_backups)
        return JSONResponse({"status": "ok", "backups": backups})
    except Exception as exc:
        logger.exception("setup_list_backups failed")
        return JSONResponse(
            {"status": "error", "message": str(exc)}, status_code=500
        )


@router.post("/restore")
async def setup_restore_from_backup(request: Request) -> JSONResponse:
    """Restore application from backup during initial setup.

    Accepts either an auto-detected backup name or a manual filesystem path.
    After restore the caller should reload the page — the server will pick up
    the restored database and config on the next request.
    """
    from starlette.concurrency import run_in_threadpool
    from backend.db.backup import full_restore, restore_database, list_backups
    from backend.db.engine import init_db

    try:
        body = await request.json()
    except Exception:
        return JSONResponse(
            {"status": "error", "message": "Invalid request"}, status_code=400
        )

    backup_path_str = (body.get("path") or "").strip()
    if not backup_path_str:
        return JSONResponse(
            {"status": "error", "message": "Backup path is required"},
            status_code=400,
        )

    backup_path = Path(backup_path_str)

    # If user provided just a name (not absolute), try to resolve from backups list
    if not backup_path.is_absolute():
        try:
            known = await run_in_threadpool(list_backups)
            match = next(
                (b for b in known if b.get("name") == backup_path_str), None
            )
            if match:
                backup_path = Path(match["path"])
        except Exception:
            pass

    if not backup_path.exists():
        return JSONResponse(
            {"status": "error", "message": f"Backup not found: {backup_path}"},
            status_code=404,
        )

    try:
        if backup_path.is_dir():
            result = await run_in_threadpool(full_restore, backup_path)
        else:
            await run_in_threadpool(restore_database, backup_path)
            result = {"restored": ["database"], "errors": []}

        # Re-initialize DB so schema migrations run on restored data
        try:
            init_db()
        except Exception as init_exc:
            logger.warning("init_db after restore: %s", init_exc)

        if _app_log_fn:
            _app_log_fn(f"Setup: restored from backup '{backup_path.name}'")

        return JSONResponse({"status": "ok", **result})
    except Exception as exc:
        logger.exception("setup_restore_from_backup failed")
        return JSONResponse(
            {"status": "error", "message": str(exc)}, status_code=500
        )
