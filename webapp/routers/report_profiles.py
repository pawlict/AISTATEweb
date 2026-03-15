"""Report profiles API router.

Endpoints:
- GET    /api/report/profiles               — list all profiles
- POST   /api/report/profiles               — create new profile
- GET    /api/report/profiles/{id}           — get profile details + placeholders
- PUT    /api/report/profiles/{id}           — update profile (name/placeholders)
- DELETE /api/report/profiles/{id}           — delete profile
- GET    /api/report/profiles/{id}/template/{type}  — download template
- POST   /api/report/profiles/{id}/template/{type}  — upload custom template
- DELETE /api/report/profiles/{id}/template/{type}  — reset to default
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, File, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from backend.report_profiles import ReportProfileManager

router = APIRouter()


def _get_manager() -> ReportProfileManager:
    data_dir = Path(os.environ.get("AISTATEWEB_DATA_DIR", "data_www"))
    return ReportProfileManager(data_dir)


# ─── Profile CRUD ────────────────────────────────────────────────────────────

@router.get("/api/report/profiles")
async def list_profiles():
    """List all report profiles."""
    mgr = _get_manager()
    profiles = mgr.list_profiles()
    return JSONResponse({"status": "ok", "profiles": profiles})


@router.post("/api/report/profiles")
async def create_profile(payload: Dict[str, Any] = Body(...)):
    """Create a new report profile."""
    name = payload.get("name", "").strip()
    if not name:
        return JSONResponse({"status": "error", "detail": "Nazwa profilu jest wymagana."}, status_code=400)

    mgr = _get_manager()
    profile = mgr.create_profile(name)

    # Generate default templates for the new profile
    from backend.report_template_generator import generate_gsm_template, generate_aml_template
    mgr.save_default_template("gsm", generate_gsm_template())
    mgr.save_default_template("aml", generate_aml_template())

    return JSONResponse({"status": "ok", "profile": profile})


@router.get("/api/report/profiles/{profile_id}")
async def get_profile(profile_id: str):
    """Get profile details including placeholders."""
    mgr = _get_manager()
    profile = mgr.get_profile(profile_id)
    if profile is None:
        return JSONResponse({"status": "error", "detail": "Profil nie znaleziony."}, status_code=404)
    return JSONResponse({"status": "ok", "profile": profile})


@router.put("/api/report/profiles/{profile_id}")
async def update_profile(profile_id: str, payload: Dict[str, Any] = Body(...)):
    """Update profile name and/or placeholders."""
    mgr = _get_manager()
    name = payload.get("name")
    placeholders = payload.get("placeholders")

    ok = mgr.update_profile(profile_id, name=name, placeholders=placeholders)
    if not ok:
        return JSONResponse({"status": "error", "detail": "Profil nie znaleziony."}, status_code=404)
    return JSONResponse({"status": "ok"})


@router.delete("/api/report/profiles/{profile_id}")
async def delete_profile(profile_id: str):
    """Delete a profile."""
    mgr = _get_manager()
    ok = mgr.delete_profile(profile_id)
    if not ok:
        return JSONResponse({"status": "error", "detail": "Nie można usunąć profilu."}, status_code=400)
    return JSONResponse({"status": "ok"})


# ─── Template management ─────────────────────────────────────────────────────

@router.get("/api/report/profiles/{profile_id}/template/{report_type}")
async def download_template(profile_id: str, report_type: str):
    """Download profile's DOCX template (gsm or aml)."""
    if report_type not in ("gsm", "aml"):
        return JSONResponse({"status": "error", "detail": "Typ musi być 'gsm' lub 'aml'."}, status_code=400)

    mgr = _get_manager()
    path = mgr.get_template_path(profile_id, report_type)
    if path is None or not path.exists():
        return JSONResponse({"status": "error", "detail": "Szablon nie znaleziony."}, status_code=404)

    return FileResponse(
        str(path),
        filename=f"{report_type}_report_template.docx",
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )


@router.post("/api/report/profiles/{profile_id}/template/{report_type}")
async def upload_template(profile_id: str, report_type: str, file: UploadFile = File(...)):
    """Upload a custom DOCX template."""
    if report_type not in ("gsm", "aml"):
        return JSONResponse({"status": "error", "detail": "Typ musi być 'gsm' lub 'aml'."}, status_code=400)

    content = await file.read()
    if len(content) < 100:
        return JSONResponse({"status": "error", "detail": "Plik jest za mały."}, status_code=400)

    mgr = _get_manager()
    ok = mgr.save_template(profile_id, report_type, content)
    if not ok:
        return JSONResponse({"status": "error", "detail": "Nie udało się zapisać szablonu."}, status_code=400)

    return JSONResponse({"status": "ok"})


@router.delete("/api/report/profiles/{profile_id}/template/{report_type}")
async def reset_template(profile_id: str, report_type: str):
    """Reset template to default."""
    if report_type not in ("gsm", "aml"):
        return JSONResponse({"status": "error", "detail": "Typ musi być 'gsm' lub 'aml'."}, status_code=400)

    mgr = _get_manager()
    mgr.reset_template(profile_id, report_type)
    return JSONResponse({"status": "ok"})
