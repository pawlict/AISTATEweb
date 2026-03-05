"""GSM billing analysis API router.

Endpoints:
- POST /api/gsm/parse  — upload XLSX billing file and parse it
"""

from __future__ import annotations

import logging
import shutil
import tempfile
import traceback
import uuid
from pathlib import Path

from fastapi import APIRouter, File, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

log = logging.getLogger("aistate.api.gsm")

router = APIRouter()


def _app_log(msg: str) -> None:
    """Log to system task (visible in Logs tab) — best-effort."""
    try:
        from webapp.server import app_log
        app_log(msg)
    except Exception:
        pass


def _do_parse(file_path: Path, filename: str) -> dict:
    """Synchronous billing parse + analysis (runs in threadpool)."""
    from backend.gsm.pipeline import process_billing
    from backend.gsm.analyzer import analyze_billing

    _app_log(f"[GSM] Parsing billing: {filename}")

    result = process_billing(file_path)

    _app_log(
        f"[GSM] Parsed {len(result.records)} records, "
        f"operator={result.operator}, subscriber={result.subscriber.msisdn or '?'}"
    )

    analysis = analyze_billing(result)

    response = {
        "status": "ok",
        "id": str(uuid.uuid4()),
        "filename": filename,
        "operator": result.operator,
        "operator_id": result.operator_id,
        "subscriber": result.subscriber.to_dict(),
        "summary": result.summary.to_dict(),
        "warnings": result.warnings,
        "analysis": analysis.to_dict() if hasattr(analysis, "to_dict") else analysis,
        "record_count": len(result.records),
        # Send first 500 records to avoid huge payloads
        "records": [r.to_dict() for r in result.records[:500]],
        "records_truncated": len(result.records) > 500,
    }

    _app_log(f"[GSM] Done: {filename} — {len(result.records)} records, {len(result.warnings)} warnings")

    return response


@router.post("/api/gsm/parse")
async def gsm_parse(
    request: Request,
    file: UploadFile = File(...),
):
    """Upload an XLSX GSM billing file and parse it.

    Returns parsed records, subscriber info, summary, and analysis.
    """
    if not file.filename:
        return JSONResponse(
            {"status": "error", "detail": "Brak pliku"},
            status_code=400,
        )

    suffix = Path(file.filename).suffix.lower()
    if suffix not in (".xlsx", ".xls"):
        _app_log(f"[GSM] Rejected file (not XLSX): {file.filename}")
        return JSONResponse(
            {"status": "error", "detail": f"Wymagany plik XLSX, otrzymano: {suffix}"},
            status_code=400,
        )

    # Save uploaded file to temp location
    tmp_dir = Path(tempfile.mkdtemp(prefix="gsm_"))
    tmp_path = tmp_dir / file.filename
    try:
        content = await file.read()
        tmp_path.write_bytes(content)
        _app_log(f"[GSM] Upload: {file.filename} ({len(content)} bytes)")

        # Run sync parsing in threadpool to avoid blocking event loop
        response = await run_in_threadpool(_do_parse, tmp_path, file.filename)
        return JSONResponse(response)

    except Exception as e:
        tb = traceback.format_exc()
        error_msg = f"{type(e).__name__}: {e}"
        log.exception("GSM parse error: %s", e)
        _app_log(f"[GSM] ERROR parsing {file.filename}: {error_msg}\n{tb}")
        return JSONResponse(
            {"status": "error", "detail": error_msg},
            status_code=500,
        )
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
