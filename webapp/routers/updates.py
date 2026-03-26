"""Software Update router — upload, install, rollback, restart."""

from __future__ import annotations

import shutil
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

from fastapi import APIRouter, Request, UploadFile, File
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from backend.settings import APP_VERSION
from backend.updater.models import UpdateInfo, UpdateState, UpdateStatus, UpdateHistoryEntry
from backend.updater.package_parser import (
    parse_update_package,
    get_staging_dir,
    cleanup_staging,
    UPDATES_DIR,
)
from backend.updater.installer import (
    create_backup,
    install_update,
    install_vendored_deps,
    run_migrations,
    record_history,
    get_history,
)
from backend.updater.rollback import list_backups, rollback_to
from backend.updater.restart_manager import RestartManager
from webapp.auth.message_store import MessageStore, Message

router = APIRouter(prefix="/api/admin/update", tags=["updates"])

# Injected at mount time
_message_store: Optional[MessageStore] = None
_app_log: Optional[Callable] = None
_restart_manager: Optional[RestartManager] = None

# In-memory state
_state = UpdateState()


def init(
    message_store: MessageStore,
    app_log_fn: Callable,
    restart_manager: RestartManager,
) -> None:
    global _message_store, _app_log, _restart_manager
    _message_store = message_store
    _app_log = app_log_fn
    _restart_manager = restart_manager


def _require_superadmin(request: Request) -> Optional[JSONResponse]:
    """Only Główny Opiekun can manage updates."""
    user = getattr(request.state, "user", None)
    if user is None:
        return JSONResponse({"status": "error", "message": "Not authenticated"}, status_code=401)
    if not user.is_superadmin:
        return JSONResponse({"status": "error", "message": "Brak uprawnień"}, status_code=403)
    return None


@router.post("/upload")
async def upload_update(request: Request, file: UploadFile = File(...)) -> JSONResponse:
    """Upload an update .zip package and validate it."""
    global _state
    err = _require_superadmin(request)
    if err:
        return err

    if not file.filename or not file.filename.endswith(".zip"):
        return JSONResponse({"status": "error", "message": "Wymagany plik .zip"}, status_code=400)

    _state = UpdateState(status=UpdateStatus.VALIDATING)

    try:
        # Save uploaded file
        UPDATES_DIR.mkdir(parents=True, exist_ok=True)
        upload_path = UPDATES_DIR / "uploaded.zip"
        content = await file.read()
        upload_path.write_bytes(content)

        # Parse and validate
        info = await run_in_threadpool(parse_update_package, upload_path)

        # Check min_version
        if info.min_version:
            current = APP_VERSION.replace(" beta", "").replace(" alpha", "").strip()
            if current < info.min_version:
                cleanup_staging()
                _state = UpdateState(status=UpdateStatus.IDLE)
                return JSONResponse({
                    "status": "error",
                    "message": f"Ta aktualizacja wymaga wersji {info.min_version} lub nowszej. "
                               f"Obecna wersja: {APP_VERSION}",
                }, status_code=400)

        _state = UpdateState(
            status=UpdateStatus.UPLOADED,
            current_info=info,
        )

        if _app_log:
            _app_log(f"Update package uploaded: v{info.version}")

        return JSONResponse({
            "status": "ok",
            "info": {
                "version": info.version,
                "changelog": info.changelog,
                "migrations": info.migrations,
                "new_dependencies": info.new_dependencies,
                "min_version": info.min_version,
                "min_python": info.min_python,
                "release_date": info.release_date,
            },
        })

    except ValueError as e:
        _state = UpdateState(status=UpdateStatus.FAILED, error=str(e))
        return JSONResponse({"status": "error", "message": str(e)}, status_code=400)
    except Exception as e:
        _state = UpdateState(status=UpdateStatus.FAILED, error=str(e))
        return JSONResponse({"status": "error", "message": f"Błąd: {e}"}, status_code=500)


@router.get("/status")
async def get_status(request: Request) -> JSONResponse:
    """Return current update status."""
    err = _require_superadmin(request)
    if err:
        return err

    restart_status = _restart_manager.get_status() if _restart_manager else {}

    return JSONResponse({
        "status": "ok",
        "current_version": APP_VERSION,
        "update_status": _state.status.value,
        "error": _state.error,
        "info": {
            "version": _state.current_info.version,
            "changelog": _state.current_info.changelog,
            "migrations": _state.current_info.migrations,
            "new_dependencies": _state.current_info.new_dependencies,
            "release_date": _state.current_info.release_date,
        } if _state.current_info else None,
        "restart": restart_status,
    })


@router.post("/install")
async def install(request: Request) -> JSONResponse:
    """Install the previously uploaded update package."""
    global _state
    err = _require_superadmin(request)
    if err:
        return err

    if _state.status != UpdateStatus.UPLOADED or not _state.current_info:
        return JSONResponse({
            "status": "error",
            "message": "Brak przesłanej paczki do instalacji",
        }, status_code=400)

    info = _state.current_info
    _state.status = UpdateStatus.INSTALLING

    try:
        staging = get_staging_dir()

        # 1. Backup
        if _app_log:
            _app_log(f"Creating backup of v{APP_VERSION}...")
        backup_path = await run_in_threadpool(create_backup, APP_VERSION)

        # 2. Install vendored dependencies
        dep_err = await run_in_threadpool(install_vendored_deps, staging)
        if dep_err:
            _state = UpdateState(status=UpdateStatus.FAILED, error=dep_err)
            if _app_log:
                _app_log(f"Update failed (deps): {dep_err}")
            return JSONResponse({"status": "error", "message": dep_err}, status_code=500)

        # 3. Install code
        if _app_log:
            _app_log(f"Installing update v{info.version}...")
        await run_in_threadpool(install_update, staging, info)

        # 4. Run migrations
        mig_err = await run_in_threadpool(run_migrations, staging, info)
        if mig_err:
            _state = UpdateState(status=UpdateStatus.FAILED, error=mig_err)
            if _app_log:
                _app_log(f"Update migration failed: {mig_err}")
            return JSONResponse({"status": "error", "message": mig_err}, status_code=500)

        # 5. Record history
        entry = UpdateHistoryEntry(
            version=info.version,
            installed_at=datetime.now().isoformat(),
            previous_version=APP_VERSION,
            backup_path=str(backup_path),
            status="installed",
            changelog=info.changelog,
        )
        await run_in_threadpool(record_history, entry)

        # 6. Set post-update flag for Call Center message
        from backend.db.engine import set_system_config
        set_system_config("post_update_pending", "1")
        set_system_config("post_update_version", info.version)
        set_system_config("post_update_changelog", info.changelog)

        # 7. Cleanup staging
        cleanup_staging()

        # 8. Schedule restart
        _state = UpdateState(status=UpdateStatus.INSTALLED, current_info=info)
        if _restart_manager:
            _restart_manager.schedule_restart(_state.restart_countdown_seconds)

        if _app_log:
            _app_log(f"Update v{info.version} installed successfully. Restart scheduled.")

        restart_status = _restart_manager.get_status() if _restart_manager else {}

        return JSONResponse({
            "status": "ok",
            "message": f"Aktualizacja do v{info.version} zainstalowana pomyślnie",
            "restart": restart_status,
        })

    except Exception as e:
        _state = UpdateState(status=UpdateStatus.FAILED, error=str(e))
        if _app_log:
            _app_log(f"Update installation failed: {e}")
        return JSONResponse({"status": "error", "message": f"Błąd instalacji: {e}"}, status_code=500)


@router.post("/restart-now")
async def restart_now(request: Request) -> JSONResponse:
    """Trigger immediate restart."""
    err = _require_superadmin(request)
    if err:
        return err
    if _restart_manager:
        if _app_log:
            _app_log("Manual restart triggered by admin")
        _restart_manager.restart_now()
    return JSONResponse({"status": "ok"})


@router.post("/cancel-restart")
async def cancel_restart(request: Request) -> JSONResponse:
    """Cancel a pending auto-restart."""
    err = _require_superadmin(request)
    if err:
        return err
    if _restart_manager:
        _restart_manager.cancel_restart()
        if _app_log:
            _app_log("Auto-restart cancelled by admin")
    return JSONResponse({"status": "ok"})


@router.post("/auto-restart")
async def set_auto_restart(request: Request) -> JSONResponse:
    """Enable/disable auto-restart and set delay."""
    err = _require_superadmin(request)
    if err:
        return err

    body = await request.json()
    enabled = body.get("enabled", True)
    delay = body.get("delay_seconds", 300)

    if _restart_manager:
        _restart_manager.set_auto_restart(enabled)
        if enabled and _state.status == UpdateStatus.INSTALLED:
            _restart_manager.schedule_restart(delay)

    _state.auto_restart = enabled
    _state.restart_countdown_seconds = delay

    return JSONResponse({"status": "ok"})


@router.post("/rollback")
async def rollback(request: Request) -> JSONResponse:
    """Rollback to a previous version from backup."""
    global _state
    err = _require_superadmin(request)
    if err:
        return err

    body = await request.json()
    backup_path_str = body.get("backup_path", "")
    if not backup_path_str:
        return JSONResponse({"status": "error", "message": "Nie podano ścieżki backupu"}, status_code=400)

    backup_path = Path(backup_path_str)

    _state = UpdateState(status=UpdateStatus.ROLLING_BACK)

    try:
        if _app_log:
            _app_log(f"Rolling back to: {backup_path.name}")

        await run_in_threadpool(rollback_to, backup_path)

        _state = UpdateState(status=UpdateStatus.INSTALLED)

        # Schedule restart after rollback
        if _restart_manager:
            _restart_manager.schedule_restart(300)

        if _app_log:
            _app_log(f"Rollback to {backup_path.name} completed. Restart scheduled.")

        return JSONResponse({
            "status": "ok",
            "message": f"Przywrócono wersję z backupu: {backup_path.name}",
            "restart": _restart_manager.get_status() if _restart_manager else {},
        })

    except ValueError as e:
        _state = UpdateState(status=UpdateStatus.FAILED, error=str(e))
        return JSONResponse({"status": "error", "message": str(e)}, status_code=400)
    except Exception as e:
        _state = UpdateState(status=UpdateStatus.FAILED, error=str(e))
        return JSONResponse({"status": "error", "message": f"Błąd rollbacku: {e}"}, status_code=500)


@router.get("/history")
async def history(request: Request) -> JSONResponse:
    """Get update history."""
    err = _require_superadmin(request)
    if err:
        return err

    entries = await run_in_threadpool(get_history)
    backups = await run_in_threadpool(list_backups)

    return JSONResponse({
        "status": "ok",
        "history": entries,
        "backups": backups,
        "current_version": APP_VERSION,
    })
