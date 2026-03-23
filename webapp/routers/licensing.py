"""License management router — status, activation, removal."""

from __future__ import annotations

from typing import Any, Callable, Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from backend.licensing import LICENSING_ENABLED
from backend.licensing.models import ALL_FEATURES, default_community_license
from backend.licensing.validator import (
    activate_license,
    get_cached_license,
    load_license,
    remove_license,
)
from backend.settings import APP_NAME, APP_VERSION

router = APIRouter(prefix="/api/admin/license", tags=["license"])

# Injected at mount time
_app_log: Optional[Callable] = None


def init(app_log_fn: Callable) -> None:
    global _app_log
    _app_log = app_log_fn


def _require_superadmin(request: Request) -> Optional[JSONResponse]:
    """Only Glowny Opiekun can manage licenses."""
    user = getattr(request.state, "user", None)
    if user is None:
        return JSONResponse({"status": "error", "message": "Not authenticated"}, status_code=401)
    if not user.is_superadmin:
        return JSONResponse({"status": "error", "message": "Brak uprawnien"}, status_code=403)
    return None


@router.get("/status")
async def license_status(request: Request) -> JSONResponse:
    """Return current license information."""
    err = _require_superadmin(request)
    if err:
        return err

    lic = get_cached_license()

    return JSONResponse({
        "status": "ok",
        "licensing_enabled": LICENSING_ENABLED,
        "app_name": APP_NAME,
        "app_version": APP_VERSION,
        "license": lic.to_dict(),
        "all_features": ALL_FEATURES,
    })


@router.post("/activate")
async def activate(request: Request) -> JSONResponse:
    """Activate a license key."""
    err = _require_superadmin(request)
    if err:
        return err

    body = await request.json()
    key_string = body.get("key", "").strip()

    if not key_string:
        return JSONResponse(
            {"status": "error", "message": "Nie podano klucza licencyjnego"},
            status_code=400,
        )

    try:
        info = activate_license(key_string)

        if _app_log:
            _app_log(
                f"License activated: id={info.license_id} plan={info.plan} "
                f"expires={info.expires or 'perpetual'}"
            )

        return JSONResponse({
            "status": "ok",
            "message": "Licencja aktywowana pomy\u015blnie",
            "license": info.to_dict(),
        })
    except ValueError as e:
        if _app_log:
            _app_log(f"License activation failed: {e}")
        return JSONResponse(
            {"status": "error", "message": str(e)},
            status_code=400,
        )


@router.post("/remove")
async def remove(request: Request) -> JSONResponse:
    """Remove current license and revert to community."""
    err = _require_superadmin(request)
    if err:
        return err

    remove_license()
    lic = get_cached_license()

    if _app_log:
        _app_log("License removed — reverted to community")

    return JSONResponse({
        "status": "ok",
        "message": "Licencja usuni\u0119ta. Przywr\u00f3cono plan Community.",
        "license": lic.to_dict(),
    })
