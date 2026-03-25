"""Addon Modules router — list, install, uninstall PRO modules."""

from __future__ import annotations

import importlib.metadata
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request, UploadFile, File
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

router = APIRouter(prefix="/api/admin/modules", tags=["modules"])

_app_log: Optional[Callable] = None
_projects_dir: Optional[Path] = None

# Known modules with metadata
KNOWN_MODULES: Dict[str, Dict[str, Any]] = {
    "va_pro": {
        "id": "va_pro",
        "name": "Visual Analysis Pro",
        "name_pl": "Analiza Wizualna Pro",
        "description": "Graph visualization, link analysis, domain profiles, intelligence reporting",
        "description_pl": "Wizualizacja grafów, analiza powiązań, profile dziedzinowe, raporty wywiadowcze",
        "package_name": "aistateweb-va-pro",
        "import_name": "aistateweb_va_pro",
        "entry_point_group": "aistateweb.plugins",
        "entry_point_name": "va_pro",
        "required_feature": "va",
        "required_plan": "pro",
        "icon": "🔗",
        "version_available": "1.0.0",
    },
}


def init(*, projects_dir: Path, app_log_fn: Callable) -> None:
    global _app_log, _projects_dir
    _app_log = app_log_fn
    _projects_dir = projects_dir


def _log(msg: str) -> None:
    if _app_log:
        _app_log(f"[modules] {msg}")


def _require_superadmin(request: Request) -> Optional[JSONResponse]:
    user = getattr(request.state, "user", None)
    if user is None:
        return JSONResponse({"status": "error", "message": "Not authenticated"}, status_code=401)
    if not user.is_superadmin:
        return JSONResponse({"status": "error", "message": "Brak uprawnień"}, status_code=403)
    return None


def _is_module_installed(import_name: str) -> bool:
    try:
        importlib.import_module(import_name)
        return True
    except ImportError:
        return False


def _get_installed_version(package_name: str) -> Optional[str]:
    try:
        return importlib.metadata.version(package_name)
    except importlib.metadata.PackageNotFoundError:
        return None


def _check_license_for_module(module_info: Dict[str, Any]) -> Dict[str, Any]:
    """Check if current license allows this module."""
    try:
        from backend.licensing import LICENSING_ENABLED
        from backend.licensing.validator import get_cached_license
        if not LICENSING_ENABLED:
            return {"allowed": True, "reason": "licensing_disabled"}
        lic = get_cached_license()
        if lic.is_expired:
            return {"allowed": False, "reason": "license_expired", "plan": lic.plan}
        feature = module_info.get("required_feature", "")
        if feature and not lic.has_feature(feature):
            return {
                "allowed": False,
                "reason": "feature_locked",
                "plan": lic.plan,
                "required_plan": module_info.get("required_plan", "pro"),
            }
        return {"allowed": True, "plan": lic.plan}
    except ImportError:
        return {"allowed": True, "reason": "licensing_not_available"}


@router.get("")
async def api_list_modules(request: Request) -> JSONResponse:
    """List all known modules with install status and license info."""
    err = _require_superadmin(request)
    if err:
        return err

    modules = []
    for mid, info in KNOWN_MODULES.items():
        installed_version = _get_installed_version(info["package_name"])
        license_check = _check_license_for_module(info)
        modules.append({
            **info,
            "installed": installed_version is not None,
            "installed_version": installed_version,
            "license": license_check,
        })
    return JSONResponse({"status": "ok", "modules": modules})


@router.post("/install")
async def api_install_module(request: Request, file: UploadFile = File(...)) -> JSONResponse:
    """Install a module from uploaded .whl file."""
    err = _require_superadmin(request)
    if err:
        return err

    if not file.filename or not file.filename.endswith(".whl"):
        raise HTTPException(status_code=400, detail="Only .whl files are accepted")

    # Identify module from filename
    module_id = None
    for mid, info in KNOWN_MODULES.items():
        pkg = info["package_name"].replace("-", "_")
        if file.filename.startswith(pkg):
            module_id = mid
            break

    if not module_id:
        raise HTTPException(status_code=400, detail="Unknown module package")

    module_info = KNOWN_MODULES[module_id]

    # License check
    license_check = _check_license_for_module(module_info)
    if not license_check["allowed"]:
        raise HTTPException(
            status_code=403,
            detail=f"License does not allow this module. "
                   f"Required plan: {module_info.get('required_plan', 'pro')}. "
                   f"Current: {license_check.get('plan', 'unknown')}"
        )

    # Save .whl to temp
    import tempfile
    tmp = Path(tempfile.mkdtemp())
    whl_path = tmp / file.filename
    content = await file.read()
    whl_path.write_bytes(content)

    # Install via pip
    _log(f"Installing module {module_id} from {file.filename} ({len(content)} bytes)")
    try:
        result = await run_in_threadpool(
            _pip_install, str(whl_path)
        )
        _log(f"pip install result: {result}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Installation failed: {e}")
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)

    installed_version = _get_installed_version(module_info["package_name"])

    return JSONResponse({
        "status": "ok",
        "module_id": module_id,
        "installed_version": installed_version,
        "message": f"Module {module_info['name']} installed. Restart server to activate.",
        "restart_required": True,
    })


@router.post("/uninstall/{module_id}")
async def api_uninstall_module(module_id: str, request: Request) -> JSONResponse:
    """Uninstall a module."""
    err = _require_superadmin(request)
    if err:
        return err

    if module_id not in KNOWN_MODULES:
        raise HTTPException(status_code=404, detail="Unknown module")

    module_info = KNOWN_MODULES[module_id]
    if not _is_module_installed(module_info["import_name"]):
        raise HTTPException(status_code=400, detail="Module not installed")

    _log(f"Uninstalling module {module_id}")
    try:
        result = await run_in_threadpool(
            _pip_uninstall, module_info["package_name"]
        )
        _log(f"pip uninstall result: {result}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Uninstall failed: {e}")

    return JSONResponse({
        "status": "ok",
        "module_id": module_id,
        "message": f"Module {module_info['name']} uninstalled. Restart server to apply.",
        "restart_required": True,
    })


def _pip_install(whl_path: str) -> str:
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "--no-deps", whl_path],
        capture_output=True, text=True, timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError(f"pip install failed: {result.stderr}")
    return result.stdout


def _pip_uninstall(package_name: str) -> str:
    result = subprocess.run(
        [sys.executable, "-m", "pip", "uninstall", "-y", package_name],
        capture_output=True, text=True, timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(f"pip uninstall failed: {result.stderr}")
    return result.stdout
