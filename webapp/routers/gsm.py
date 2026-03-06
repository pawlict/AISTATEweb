"""GSM billing analysis API router.

Endpoints:
- POST /api/gsm/parse           — upload XLSX billing file and parse it
- POST /api/gsm/geolocate       — geolocate parsed billing records
- GET  /api/gsm/bts/stats       — BTS database statistics
- POST /api/gsm/bts/import      — import BTS data from CSV (UKE/OpenCelliD)
- POST /api/gsm/bts/clear       — clear BTS database
- GET  /api/gsm/bts/lookup      — lookup BTS station by LAC/CID
- GET  /api/gsm/tiles/info      — offline map tile info
- GET  /api/gsm/tiles/{z}/{x}/{y} — serve map tiles from MBTiles
"""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
import traceback
import uuid
from pathlib import Path

from fastapi import APIRouter, File, Form, Query, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, Response

log = logging.getLogger("aistate.api.gsm")

router = APIRouter()


def _data_dir() -> Path:
    return Path(os.environ.get("AISTATEWEB_DATA_DIR", "data_www"))


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
    from backend.gsm.imei_db import lookup_imei

    _app_log(f"[GSM] Parsing billing: {filename}")

    result = process_billing(file_path)

    _app_log(
        f"[GSM] Parsed {len(result.records)} records, "
        f"operator={result.operator}, subscriber={result.subscriber.msisdn or '?'}"
    )

    analysis = analyze_billing(result)

    # Enrich subscriber with device name from IMEI
    sub_dict = result.subscriber.to_dict()
    if result.subscriber.imei:
        dev = lookup_imei(result.subscriber.imei)
        if dev:
            sub_dict["device"] = dev.to_dict()

    # Geolocate records
    geo = None
    try:
        from backend.gsm.geolocation import geolocate_records
        from backend.gsm.bts_db import get_bts_db
        bts_db = get_bts_db(_data_dir())
        geo = geolocate_records(result.records, bts_db)

        # Auto-import BTS data from billing (T-Mobile has coords)
        records_with_coords = [
            r.to_dict() for r in result.records
            if r.extra.get("bts_x") and r.extra.get("bts_y")
        ]
        if records_with_coords:
            bts_db.import_from_billing_records(records_with_coords)
            _app_log(f"[GSM] Auto-imported {len(records_with_coords)} BTS stations from billing")
    except Exception as e:
        log.warning("Geolocation error: %s", e)

    response = {
        "status": "ok",
        "id": str(uuid.uuid4()),
        "filename": filename,
        "operator": result.operator,
        "operator_id": result.operator_id,
        "subscriber": sub_dict,
        "summary": result.summary.to_dict(),
        "warnings": result.warnings,
        "analysis": analysis.to_dict() if hasattr(analysis, "to_dict") else analysis,
        "record_count": len(result.records),
        "records": [r.to_dict() for r in result.records],
        "records_truncated": False,
    }

    # Add geolocation data
    if geo:
        response["geolocation"] = geo.to_dict()

    _app_log(f"[GSM] Done: {filename} — {len(result.records)} records, {len(result.warnings)} warnings")

    return response


@router.post("/api/gsm/parse")
async def gsm_parse(
    request: Request,
    file: UploadFile = File(...),
):
    """Upload an XLSX GSM billing file and parse it.

    Returns parsed records, subscriber info, summary, analysis, and geolocation.
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


# ---------------------------------------------------------------------------
# BTS Database endpoints
# ---------------------------------------------------------------------------

@router.get("/api/gsm/bts/stats")
async def bts_stats():
    """Get BTS database statistics."""
    try:
        from backend.gsm.bts_db import get_bts_db
        db = get_bts_db(_data_dir())
        stats = await run_in_threadpool(db.get_stats)
        return JSONResponse({"status": "ok", **stats})
    except Exception as e:
        return JSONResponse({"status": "ok", "total_stations": 0, "by_source": {}, "by_radio": {}, "unique_cities": 0, "db_size_mb": 0})


@router.post("/api/gsm/bts/import")
async def bts_import(
    request: Request,
    file: UploadFile = File(...),
    source: str = Form("opencellid"),
):
    """Import BTS data from CSV file.

    Args:
        file: CSV file (OpenCelliD or UKE format).
        source: 'opencellid' or 'uke'.
    """
    if not file.filename:
        return JSONResponse(
            {"status": "error", "detail": "Brak pliku"},
            status_code=400,
        )

    suffix = Path(file.filename).suffix.lower()
    if suffix not in (".csv", ".txt"):
        return JSONResponse(
            {"status": "error", "detail": f"Wymagany plik CSV, otrzymano: {suffix}"},
            status_code=400,
        )

    tmp_dir = Path(tempfile.mkdtemp(prefix="bts_"))
    tmp_path = tmp_dir / file.filename
    try:
        content = await file.read()
        tmp_path.write_bytes(content)
        size_mb = len(content) / 1048576
        _app_log(f"[GSM] BTS import: {file.filename} ({size_mb:.1f} MB, source={source})")

        from backend.gsm.bts_db import get_bts_db
        db = get_bts_db(_data_dir())

        if source == "uke":
            count = await run_in_threadpool(db.import_uke_csv, tmp_path)
        else:
            count = await run_in_threadpool(db.import_opencellid_csv, tmp_path)

        _app_log(f"[GSM] Imported {count} BTS stations from {source}")
        stats = await run_in_threadpool(db.get_stats)
        return JSONResponse({"status": "ok", "imported": count, **stats})

    except Exception as e:
        tb = traceback.format_exc()
        error_msg = f"{type(e).__name__}: {e}"
        log.exception("BTS import error: %s", e)
        _app_log(f"[GSM] ERROR importing BTS: {error_msg}")
        return JSONResponse(
            {"status": "error", "detail": error_msg},
            status_code=500,
        )
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


@router.post("/api/gsm/bts/clear")
async def bts_clear(
    request: Request,
    source: str = Form(""),
):
    """Clear BTS database (all or by source)."""
    try:
        from backend.gsm.bts_db import get_bts_db
        db = get_bts_db(_data_dir())
        deleted = await run_in_threadpool(db.clear, source or None)
        _app_log(f"[GSM] Cleared {deleted} BTS stations (source={source or 'all'})")
        stats = await run_in_threadpool(db.get_stats)
        return JSONResponse({"status": "ok", "deleted": deleted, **stats})
    except Exception as e:
        return JSONResponse(
            {"status": "error", "detail": str(e)},
            status_code=500,
        )


@router.get("/api/gsm/bts/lookup")
async def bts_lookup(
    lac: int = Query(...),
    cid: int = Query(...),
    mnc: int = Query(None),
):
    """Lookup BTS station by LAC and CID."""
    try:
        from backend.gsm.bts_db import get_bts_db
        db = get_bts_db(_data_dir())
        stations = await run_in_threadpool(db.lookup, lac, cid, mnc)
        return JSONResponse({
            "status": "ok",
            "stations": [s.to_dict() for s in stations],
        })
    except Exception as e:
        return JSONResponse(
            {"status": "error", "detail": str(e)},
            status_code=500,
        )


# ---------------------------------------------------------------------------
# Map tile endpoints
# ---------------------------------------------------------------------------

@router.get("/api/gsm/tiles/info")
async def tiles_info():
    """Get offline map tile info."""
    try:
        from backend.gsm.tile_server import get_tile_server
        server = get_tile_server(_data_dir())
        info = server.get_info()
        return JSONResponse({"status": "ok", **info})
    except Exception as e:
        return JSONResponse({"status": "ok", "available": False})


@router.get("/api/gsm/tiles/{z}/{x}/{y}")
async def get_tile(z: int, x: int, y: int):
    """Serve a single map tile from MBTiles."""
    try:
        from backend.gsm.tile_server import get_tile_server
        server = get_tile_server(_data_dir())

        tile_data = await run_in_threadpool(server.get_tile, z, x, y)

        if tile_data is None:
            return Response(status_code=204)  # No content — empty tile

        fmt = server.get_format()
        content_type = {
            "pbf": "application/x-protobuf",
            "png": "image/png",
            "jpg": "image/jpeg",
            "jpeg": "image/jpeg",
            "webp": "image/webp",
        }.get(fmt, "application/octet-stream")

        headers = {
            "Cache-Control": "public, max-age=86400",
            "Access-Control-Allow-Origin": "*",
        }

        # PBF tiles are usually gzip-compressed
        if fmt == "pbf" and tile_data[:2] == b"\x1f\x8b":
            headers["Content-Encoding"] = "gzip"

        return Response(
            content=tile_data,
            media_type=content_type,
            headers=headers,
        )

    except FileNotFoundError:
        return Response(status_code=404)
    except Exception as e:
        log.warning("Tile error z=%d x=%d y=%d: %s", z, x, y, e)
        return Response(status_code=500)
