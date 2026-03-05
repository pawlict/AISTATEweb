"""GSM billing analysis API router.

Endpoints:
- POST /api/gsm/parse  — upload XLSX billing file and parse it
"""

from __future__ import annotations

import logging
import tempfile
import uuid
from pathlib import Path

from fastapi import APIRouter, File, Request, UploadFile
from fastapi.responses import JSONResponse

from backend.gsm.pipeline import process_billing
from backend.gsm.analyzer import analyze_billing

log = logging.getLogger("aistate.api.gsm")

router = APIRouter()


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
        return JSONResponse(
            {"status": "error", "detail": "Wymagany plik XLSX"},
            status_code=400,
        )

    # Save uploaded file to temp location
    tmp_dir = Path(tempfile.mkdtemp(prefix="gsm_"))
    tmp_path = tmp_dir / file.filename
    try:
        content = await file.read()
        tmp_path.write_bytes(content)

        # Parse billing
        result = process_billing(tmp_path)

        # Run analysis
        analysis = analyze_billing(result)

        response = {
            "status": "ok",
            "id": str(uuid.uuid4()),
            "filename": file.filename,
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
        return JSONResponse(response)

    except Exception as e:
        log.exception("GSM parse error: %s", e)
        return JSONResponse(
            {"status": "error", "detail": str(e)},
            status_code=500,
        )
    finally:
        # Clean up temp files
        import shutil
        shutil.rmtree(tmp_dir, ignore_errors=True)
