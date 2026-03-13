"""GSM billing analysis API router.

Endpoints:
- POST /api/gsm/parse           — upload XLSX billing file and parse it
- POST /api/gsm/import          — smart import: auto-detect billing/identification/ZIP
- POST /api/gsm/identification  — upload identification file(s) (XLSX/CSV)
- POST /api/gsm/geolocate       — geolocate parsed billing records
- GET  /api/gsm/bts/stats       — BTS database statistics
- POST /api/gsm/bts/import      — import BTS data from CSV (UKE/OpenCelliD)
- POST /api/gsm/bts/clear       — clear BTS database
- GET  /api/gsm/bts/nearby      — find nearby BTS stations in visible area
- GET  /api/gsm/bts/lookup      — lookup BTS station by LAC/CID
- GET  /api/gsm/tiles/info      — offline map tile info
- GET  /api/gsm/tiles/{z}/{x}/{y} — serve map tiles from MBTiles
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
import traceback
import uuid
from pathlib import Path

from typing import Any, Dict, List, Optional

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

        # Log BTS database status
        try:
            stats = bts_db.get_stats()
            _app_log(f"[GSM] BTS database: {stats.get('total_stations', 0)} stations "
                     f"(sources: {stats.get('by_source', {})})")
        except Exception:
            _app_log("[GSM] BTS database: unavailable or empty")

        geo = geolocate_records(result.records, bts_db)

        # Log geolocation summary
        if geo:
            dbg = geo.debug or {}
            _app_log(
                f"[GSM] Geolocation: {geo.geolocated_records}/{geo.total_records} resolved "
                f"(billing_coords={dbg.get('resolved_billing', 0)}, "
                f"bts_db={dbg.get('resolved_bts_db', 0)}, "
                f"lac_cid_miss={dbg.get('lookup_miss', 0)}, "
                f"no_data={dbg.get('no_location_data', 0)})"
            )

        # Clean up any previously imported bad coordinates from BTS database
        # (e.g. raw DDMMSS stored as decimal, sentinel -1/0 values)
        cleaned = bts_db.cleanup_bad_coords()
        if cleaned:
            _app_log(f"[GSM] Cleaned {cleaned} bad entries from BTS database")

        # Auto-import BTS data from billing (T-Mobile has coords)
        # Skip sentinel values (-1, 0) and UNKNOWN city — filtering is also
        # done inside import_from_billing_records() but pre-filter here too
        _sentinel = {"-1", "0", "", "UNKNOWN"}
        records_with_coords = [
            r.to_dict() for r in result.records
            if r.extra.get("bts_x") and r.extra.get("bts_y")
            and str(r.extra.get("bts_x")) not in _sentinel
            and str(r.extra.get("bts_y")) not in _sentinel
        ]
        if records_with_coords:
            count = bts_db.import_from_billing_records(records_with_coords)
            _app_log(f"[GSM] Auto-imported {count} BTS stations from billing")
    except Exception as e:
        log.warning("Geolocation error: %s", e, exc_info=True)
        _app_log(f"[GSM] Geolocation ERROR: {type(e).__name__}: {e}")

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
# Identification file upload
# ---------------------------------------------------------------------------

@router.post("/api/gsm/identification")
async def gsm_identification(
    request: Request,
    files: List[UploadFile] = File(...),
):
    """Upload identification file(s) (XLSX / CSV) and parse them.

    Returns a mapping of normalised MSISDN → subscriber info for
    frontend lookup in Top Contacts and Records tables.
    Supports Orange (XLSX), Play (CSV), Plus (CSV) formats with
    auto-detection.
    """
    if not files:
        return JSONResponse(
            {"status": "error", "detail": "Brak pliku"},
            status_code=400,
        )

    tmp_dir = Path(tempfile.mkdtemp(prefix="gsm_id_"))
    try:
        from backend.gsm.identification import IdentificationStore

        store = IdentificationStore()
        file_results = []

        for f in files:
            if not f.filename:
                continue

            suffix = Path(f.filename).suffix.lower()
            if suffix not in (".xlsx", ".xls", ".csv", ".txt"):
                file_results.append({
                    "filename": f.filename,
                    "status": "skipped",
                    "detail": f"Nieobsługiwany format: {suffix}",
                })
                continue

            tmp_path = tmp_dir / f.filename
            content = await f.read()
            tmp_path.write_bytes(content)

            try:
                count = await run_in_threadpool(store.load_file, tmp_path)
                file_results.append({
                    "filename": f.filename,
                    "status": "ok",
                    "records_loaded": count,
                })
                _app_log(
                    f"[GSM] Identification: {f.filename} — "
                    f"{count} records loaded"
                )
            except Exception as e:
                file_results.append({
                    "filename": f.filename,
                    "status": "error",
                    "detail": f"{type(e).__name__}: {e}",
                })
                log.warning("Identification parse error for %s: %s",
                            f.filename, e, exc_info=True)

        # Build a compact lookup map: normalised_number → {label, type}
        lookup_map = {}
        for msisdn, rec in store._records.items():
            lookup_map[msisdn] = {
                "label": rec.display_label,
                "type": rec.identification_type,
                "name": rec.name or "",
                "address": rec.address or "",
                "city": rec.city or "",
                "pesel": rec.pesel or "",
                "nip": rec.nip or "",
                "operator": rec.source_operator or "",
            }

        _app_log(
            f"[GSM] Identification done: {store.count} total records "
            f"from {len(file_results)} file(s)"
        )

        return JSONResponse({
            "status": "ok",
            "total_records": store.count,
            "files": file_results,
            "identification": lookup_map,
        })

    except Exception as e:
        tb = traceback.format_exc()
        error_msg = f"{type(e).__name__}: {e}"
        log.exception("Identification parse error: %s", e)
        _app_log(f"[GSM] ERROR identification: {error_msg}\n{tb}")
        return JSONResponse(
            {"status": "error", "detail": error_msg},
            status_code=500,
        )
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Smart import — auto-detect billing / identification / ZIP
# ---------------------------------------------------------------------------

@router.post("/api/gsm/import")
async def gsm_smart_import(
    request: Request,
    files: List[UploadFile] = File(...),
):
    """Smart import: upload files (XLSX, CSV, ZIP) and auto-detect type.

    Automatically classifies each file as billing, identification, or unknown.
    ZIPs are extracted recursively. Billing is parsed + analysed + geolocated.
    Identification records are returned as a lookup map.
    """
    if not files:
        return JSONResponse(
            {"status": "error", "detail": "Brak plików"},
            status_code=400,
        )

    tmp_dir = Path(tempfile.mkdtemp(prefix="gsm_import_"))
    extra_tmp_dirs: list = []

    try:
        # Save all uploaded files to temp directory
        saved_paths: list = []
        for f in files:
            if not f.filename:
                continue
            tmp_path = tmp_dir / f.filename
            content = await f.read()
            tmp_path.write_bytes(content)
            saved_paths.append(tmp_path)
            _app_log(f"[GSM] Import: {f.filename} ({len(content)} bytes)")

        # Scan and classify
        from backend.gsm.folder_scanner import scan_files
        scan_result, extra_tmp_dirs = await run_in_threadpool(
            scan_files, saved_paths
        )

        _app_log(
            f"[GSM] Scan: {len(scan_result.billing_files)} bilingów, "
            f"{len(scan_result.identification_files)} identyfikacji, "
            f"{len(scan_result.unknown_files)} nierozpoznanych, "
            f"{scan_result.zips_extracted} ZIP rozp."
        )

        response: dict = {
            "status": "ok",
            "scan": scan_result.to_dict(),
        }

        # --- Process billing files ---
        if scan_result.billing_files:
            # Use the first (or best confidence) billing file
            best_billing = max(scan_result.billing_files, key=lambda f: f.confidence)
            _app_log(f"[GSM] Processing billing: {best_billing.filename} ({best_billing.operator})")

            billing_data = await run_in_threadpool(
                _do_parse, best_billing.path, best_billing.filename
            )
            response["billing"] = billing_data

            # If there are more billing files, note them
            if len(scan_result.billing_files) > 1:
                extra = [f.filename for f in scan_result.billing_files if f is not best_billing]
                response["extra_billings"] = extra
                _app_log(f"[GSM] Additional billing files (not processed): {extra}")

        # --- Process identification files ---
        if scan_result.identification_files:
            from backend.gsm.identification import IdentificationStore
            store = IdentificationStore()

            id_file_results = []
            for sf in scan_result.identification_files:
                try:
                    count = store.load_file(sf.path)
                    id_file_results.append({
                        "filename": sf.filename,
                        "operator": sf.operator,
                        "status": "ok",
                        "records_loaded": count,
                    })
                    _app_log(f"[GSM] Identification: {sf.filename} ({sf.operator}) — {count} records")
                except Exception as e:
                    id_file_results.append({
                        "filename": sf.filename,
                        "operator": sf.operator,
                        "status": "error",
                        "detail": str(e),
                    })
                    log.warning("ID parse error for %s: %s", sf.filename, e)

            # Build lookup map
            lookup_map = {}
            for msisdn, rec in store._records.items():
                lookup_map[msisdn] = {
                    "label": rec.display_label,
                    "type": rec.identification_type,
                    "name": rec.name or "",
                    "address": rec.address or "",
                    "city": rec.city or "",
                    "pesel": rec.pesel or "",
                    "nip": rec.nip or "",
                    "operator": rec.source_operator or "",
                }

            response["identification"] = {
                "total_records": store.count,
                "files": id_file_results,
                "lookup": lookup_map,
            }

        _app_log(f"[GSM] Import complete")
        return JSONResponse(response)

    except Exception as e:
        tb = traceback.format_exc()
        error_msg = f"{type(e).__name__}: {e}"
        log.exception("Smart import error: %s", e)
        _app_log(f"[GSM] ERROR import: {error_msg}\n{tb}")
        return JSONResponse(
            {"status": "error", "detail": error_msg},
            status_code=500,
        )
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        for d in extra_tmp_dirs:
            shutil.rmtree(d, ignore_errors=True)


# ---------------------------------------------------------------------------
# GSM data persistence (project-scoped, multi-user aware)
# ---------------------------------------------------------------------------

def _gsm_project_helpers():
    """Lazy-import server helpers to avoid circular imports."""
    from webapp.server import (
        read_project_meta, write_project_meta,
        project_path, now_iso, _check_project_access,
    )
    return read_project_meta, write_project_meta, project_path, now_iso, _check_project_access


@router.post("/api/gsm/{project_id}/save")
async def gsm_save(request: Request, project_id: str):
    """Save GSM analysis results to the project.

    The request body should contain the full GSM state:
    { billing: {...}, identification: {...} }

    Data is stored in projects/{project_id}/analysis/gsm_latest.json
    and a flag is set in project.json for quick lookup.
    Access-controlled per user (multiuser mode).
    """
    read_meta, write_meta, proj_path, now_iso, check_access = _gsm_project_helpers()

    # Check user access
    check_access(request, project_id)

    try:
        payload = await request.json()
    except Exception:
        return JSONResponse({"status": "error", "detail": "Invalid JSON"}, status_code=400)

    try:
        # Ensure analysis directory exists
        analysis_dir = proj_path(project_id) / "analysis"
        analysis_dir.mkdir(parents=True, exist_ok=True)

        # Save full GSM data to separate file (can be large)
        gsm_path = analysis_dir / "gsm_latest.json"
        tmp = gsm_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        tmp.replace(gsm_path)  # Atomic write

        # Update project metadata with GSM flag
        meta = read_meta(project_id)
        meta["has_gsm"] = True
        meta["gsm_summary"] = {
            "saved_at": now_iso(),
            "filename": payload.get("billing", {}).get("filename", ""),
            "operator": payload.get("billing", {}).get("operator", ""),
            "record_count": payload.get("billing", {}).get("record_count", 0),
            "identification_count": len(
                (payload.get("identification", {}) or {}).get("lookup", {})
            ),
        }
        meta["updated_at"] = now_iso()
        write_meta(project_id, meta)

        _app_log(f"[GSM] Saved to project {project_id[:8]}…")
        return JSONResponse({"status": "ok"})

    except Exception as e:
        log.exception("GSM save error: %s", e)
        return JSONResponse(
            {"status": "error", "detail": f"{type(e).__name__}: {e}"},
            status_code=500,
        )


@router.get("/api/gsm/{project_id}/load")
async def gsm_load(request: Request, project_id: str):
    """Load saved GSM analysis results from the project.

    Returns the full GSM state (billing + identification) if it exists.
    Access-controlled per user (multiuser mode).
    """
    read_meta, write_meta, proj_path, now_iso, check_access = _gsm_project_helpers()

    # Check user access
    check_access(request, project_id)

    try:
        gsm_path = proj_path(project_id) / "analysis" / "gsm_latest.json"

        if not gsm_path.exists():
            return JSONResponse({"status": "ok", "has_data": False})

        data = json.loads(gsm_path.read_text(encoding="utf-8"))
        return JSONResponse({
            "status": "ok",
            "has_data": True,
            **data,
        })

    except Exception as e:
        log.exception("GSM load error: %s", e)
        return JSONResponse(
            {"status": "error", "detail": f"{type(e).__name__}: {e}"},
            status_code=500,
        )


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
        file: Data file (CSV for OpenCelliD; ZIP/XLSX/CSV for UKE).
        source: 'opencellid' or 'uke'.
    """
    if not file.filename:
        return JSONResponse(
            {"status": "error", "detail": "Brak pliku"},
            status_code=400,
        )

    suffix = Path(file.filename).suffix.lower()
    allowed_opencellid = (".csv", ".csv.gz", ".txt")
    allowed_uke = (".zip", ".xlsx", ".csv", ".txt")

    if source == "uke" and suffix not in allowed_uke:
        return JSONResponse(
            {"status": "error", "detail": f"UKE: wymagany plik ZIP, XLSX lub CSV, otrzymano: {suffix}"},
            status_code=400,
        )
    elif source != "uke" and suffix not in allowed_opencellid:
        return JSONResponse(
            {"status": "error", "detail": f"OpenCelliD: wymagany plik CSV, otrzymano: {suffix}"},
            status_code=400,
        )

    tmp_dir = Path(tempfile.mkdtemp(prefix="bts_"))
    tmp_path = tmp_dir / file.filename
    try:
        content = await file.read()
        tmp_path.write_bytes(content)
        size_mb = len(content) / 1048576
        _app_log(f"[GSM] BTS import: {file.filename} ({size_mb:.1f} MB, source={source})")

        # Save uploaded file to persistent storage
        folder_name = "UKE" if source == "uke" else "OpenCelliD"
        store_dir = _data_dir() / "gsm" / "BTS" / folder_name
        store_dir.mkdir(parents=True, exist_ok=True)
        (store_dir / file.filename).write_bytes(content)
        _app_log(f"[GSM] File saved to BTS/{folder_name}/{file.filename}")

        from backend.gsm.bts_db import get_bts_db
        db = get_bts_db(_data_dir())

        if source == "uke":
            count = await run_in_threadpool(db.import_uke_file, tmp_path)
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


@router.get("/api/gsm/bts/nearby")
async def bts_nearby(
    lat: float = Query(...),
    lon: float = Query(...),
    radius_deg: float = Query(0.01),
    limit: int = Query(80, ge=1, le=200),
):
    """Find BTS stations near given coordinates."""
    try:
        from backend.gsm.bts_db import get_bts_db
        db = get_bts_db(_data_dir())
        stations = await run_in_threadpool(db.search_nearby, lat, lon, radius_deg, limit)
        result = [s.to_dict() for s in stations[:limit]]
        return JSONResponse({"status": "ok", "stations": result})
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


# ---------------------------------------------------------------------------
# BTS database download (auto-download from internet)
# ---------------------------------------------------------------------------

@router.post("/api/gsm/bts/download")
async def bts_download(request: Request):
    """Download BTS database from the internet.

    Body JSON: { "source": "opencellid"|"uke", "token": "..." }
    For OpenCelliD, a token is required (from opencellid.org).
    For UKE, no token is needed.
    """
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"status": "error", "detail": "Invalid JSON body"}, status_code=400)

    source = body.get("source", "")
    token = body.get("token", "")

    # Fallback: use saved token from settings if not provided in request
    if source == "opencellid" and not token:
        try:
            from backend.settings_store import load_settings
            s = load_settings()
            token = getattr(s, "opencellid_token", "") or ""
        except Exception:
            pass

    if source == "opencellid":
        return await _download_opencellid(token)
    elif source == "uke":
        return await _download_uke()
    else:
        return JSONResponse({"status": "error", "detail": f"Unknown source: {source}"}, status_code=400)


async def _download_opencellid(token: str):
    """Download OpenCelliD Poland cell towers CSV."""
    if not token:
        return JSONResponse(
            {"status": "error", "detail": "Token API OpenCelliD jest wymagany. Uzyskaj go na opencellid.org."},
            status_code=400,
        )

    import gzip
    import io
    import httpx

    _app_log("[GSM] Downloading OpenCelliD Poland database...")

    url = f"https://opencellid.org/ocid/downloads?token={token}&type=full&file=cell_towers.csv.gz"

    tmp_dir = Path(tempfile.mkdtemp(prefix="bts_dl_"))
    try:
        # Download (can be large, ~100+ MB compressed)
        async with httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=30.0)) as client:
            resp = await client.get(url, follow_redirects=True)

        if resp.status_code == 403:
            return JSONResponse(
                {"status": "error", "detail": "Nieprawidłowy token API OpenCelliD. Sprawdź token na opencellid.org."},
                status_code=400,
            )
        if resp.status_code != 200:
            return JSONResponse(
                {"status": "error", "detail": f"Błąd pobierania: HTTP {resp.status_code}"},
                status_code=500,
            )

        raw = resp.content
        size_mb = len(raw) / 1048576
        _app_log(f"[GSM] Downloaded {size_mb:.1f} MB from OpenCelliD")

        # Save to persistent storage folder
        store_dir = _data_dir() / "gsm" / "BTS" / "OpenCelliD"
        store_dir.mkdir(parents=True, exist_ok=True)

        # Decompress if gzipped
        csv_path = tmp_dir / "cell_towers.csv"
        if raw[:2] == b"\x1f\x8b" or url.endswith(".gz"):
            decompressed = gzip.decompress(raw)
            csv_path.write_bytes(decompressed)
            _app_log(f"[GSM] Decompressed to {len(decompressed)/1048576:.1f} MB")
            # Save both compressed and decompressed to store
            (store_dir / "cell_towers.csv.gz").write_bytes(raw)
            (store_dir / "cell_towers.csv").write_bytes(decompressed)
        else:
            csv_path.write_bytes(raw)
            (store_dir / "cell_towers.csv").write_bytes(raw)

        # Import into BTS database
        from backend.gsm.bts_db import get_bts_db
        db = get_bts_db(_data_dir())
        count = await run_in_threadpool(db.import_opencellid_csv, csv_path)

        _app_log(f"[GSM] Imported {count} stations from OpenCelliD")
        stats = await run_in_threadpool(db.get_stats)
        return JSONResponse({"status": "ok", "imported": count, **stats})

    except httpx.TimeoutException:
        return JSONResponse(
            {"status": "error", "detail": "Timeout — plik jest duży, spróbuj ponownie."},
            status_code=500,
        )
    except Exception as e:
        log.exception("OpenCelliD download error: %s", e)
        return JSONResponse(
            {"status": "error", "detail": f"{type(e).__name__}: {e}"},
            status_code=500,
        )
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


async def _download_uke():
    """Download UKE (Polish regulator) BTS database.

    Scrapes the BIP UKE page listing GSM/UMTS/LTE/5G NR station permits,
    finds all XLSX download links, downloads each file and imports into
    the BTS database.

    Page: https://bip.uke.gov.pl/pozwolenia-radiowe/wykaz-pozwolen-radiowych-tresci/
          stacje-gsm-umts-lte-5gnr-oraz-cdma,12,0.html
    """
    import httpx
    import re as _re

    _app_log("[GSM] Downloading UKE BTS database...")

    # UKE BIP page with links to individual XLSX files per technology/band
    UKE_PAGE_URL = (
        "https://bip.uke.gov.pl/pozwolenia-radiowe/"
        "wykaz-pozwolen-radiowych-tresci/"
        "stacje-gsm-umts-lte-5gnr-oraz-cdma,12,0.html"
    )
    UKE_BASE = "https://bip.uke.gov.pl"

    tmp_dir = Path(tempfile.mkdtemp(prefix="bts_uke_"))
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(300.0, connect=30.0),
            follow_redirects=True,
        ) as client:
            # ── Step 1: fetch listing page ───────────────────────
            _app_log("[GSM] Fetching UKE BIP page...")
            page_resp = await client.get(UKE_PAGE_URL)
            if page_resp.status_code != 200:
                return JSONResponse(
                    {"status": "error",
                     "detail": f"Nie udało się pobrać strony UKE BIP (HTTP {page_resp.status_code}). "
                               f"Wgraj plik ZIP/XLSX ręcznie."},
                    status_code=500,
                )

            html = page_resp.text

            # ── Step 2: extract XLSX download links ──────────────
            # Links look like:
            #   href="/download/gfx/bip/pl/defaultaktualnosci/140/12/90/
            #         lte800_-_stan_na_2026-02-25.xlsx"
            xlsx_pattern = _re.compile(
                r'href="(/download/[^"]+\.xlsx)"', _re.IGNORECASE
            )
            xlsx_paths = list(set(xlsx_pattern.findall(html)))
            xlsx_paths.sort()

            if not xlsx_paths:
                _app_log("[GSM] ERROR: No XLSX links found on UKE page")
                return JSONResponse(
                    {"status": "error",
                     "detail": "Nie znaleziono linków XLSX na stronie BIP UKE. "
                               "Struktura strony mogła się zmienić. Wgraj plik ZIP/XLSX ręcznie."},
                    status_code=500,
                )

            _app_log(f"[GSM] Found {len(xlsx_paths)} XLSX files on UKE page")

            # ── Step 3: download and import each XLSX ────────────
            store_dir = _data_dir() / "gsm" / "BTS" / "UKE"
            store_dir.mkdir(parents=True, exist_ok=True)

            from backend.gsm.bts_db import get_bts_db
            db = get_bts_db(_data_dir())

            total_imported = 0
            downloaded = 0
            errors = []

            for xlsx_path in xlsx_paths:
                file_url = UKE_BASE + xlsx_path
                file_name = Path(xlsx_path).name

                try:
                    resp = await client.get(file_url)
                    if resp.status_code != 200:
                        errors.append(f"{file_name}: HTTP {resp.status_code}")
                        continue

                    raw = resp.content
                    if len(raw) < 500:
                        errors.append(f"{file_name}: plik zbyt mały ({len(raw)} B)")
                        continue

                    downloaded += 1
                    size_kb = len(raw) / 1024
                    _app_log(f"[GSM] Downloaded {file_name} ({size_kb:.0f} KB) [{downloaded}/{len(xlsx_paths)}]")

                    # Save to persistent storage
                    (store_dir / file_name).write_bytes(raw)

                    # Save to temp and import
                    tmp_path = tmp_dir / file_name
                    tmp_path.write_bytes(raw)

                    count = await run_in_threadpool(db.import_uke_xlsx, tmp_path)
                    total_imported += count
                    _app_log(f"[GSM] Imported {count} stations from {file_name}")

                except Exception as e:
                    errors.append(f"{file_name}: {e}")
                    log.warning("UKE download error for %s: %s", file_name, e)

            # ── Step 4: summary ──────────────────────────────────
            if errors:
                _app_log(f"[GSM] UKE download warnings: {'; '.join(errors)}")

            _app_log(
                f"[GSM] UKE done: downloaded {downloaded}/{len(xlsx_paths)} files, "
                f"imported {total_imported} stations total"
            )
            stats = await run_in_threadpool(db.get_stats)
            return JSONResponse({
                "status": "ok",
                "imported": total_imported,
                "files_downloaded": downloaded,
                "files_total": len(xlsx_paths),
                "errors": errors[:10] if errors else [],
                **stats,
            })

    except httpx.TimeoutException:
        return JSONResponse(
            {"status": "error",
             "detail": "Timeout przy pobieraniu z BIP UKE. Spróbuj ponownie."},
            status_code=500,
        )
    except Exception as e:
        log.exception("UKE download error: %s", e)
        return JSONResponse(
            {"status": "error", "detail": f"{type(e).__name__}: {e}"},
            status_code=500,
        )
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# MBTiles upload / remove
# ---------------------------------------------------------------------------

@router.post("/api/gsm/tiles/upload")
async def tiles_upload(
    file: UploadFile = File(...),
):
    """Upload an MBTiles file for offline map tiles."""
    if not file.filename:
        return JSONResponse({"status": "error", "detail": "Brak pliku"}, status_code=400)

    suffix = Path(file.filename).suffix.lower()
    if suffix != ".mbtiles":
        return JSONResponse(
            {"status": "error", "detail": f"Wymagany plik .mbtiles, otrzymano: {suffix}"},
            status_code=400,
        )

    gsm_dir = _data_dir() / "gsm"
    gsm_dir.mkdir(parents=True, exist_ok=True)
    target = gsm_dir / "map.mbtiles"

    try:
        # Write to temp file first, then move (atomic-ish)
        tmp_path = gsm_dir / "map.mbtiles.tmp"
        content = await file.read()
        tmp_path.write_bytes(content)

        # Basic validation — check it's a valid SQLite file
        if content[:16] != b"SQLite format 3\x00":
            tmp_path.unlink(missing_ok=True)
            return JSONResponse(
                {"status": "error", "detail": "Plik nie jest prawidłową bazą SQLite/MBTiles."},
                status_code=400,
            )

        # Replace existing file
        if target.exists():
            target.unlink()
        tmp_path.rename(target)

        # Reset tile server singleton so it picks up the new file
        try:
            import backend.gsm.tile_server as ts_mod
            ts_mod._default_server = None
        except Exception:
            pass

        size_mb = len(content) / 1048576
        _app_log(f"[GSM] MBTiles uploaded: {file.filename} ({size_mb:.1f} MB)")
        return JSONResponse({"status": "ok", "size_mb": round(size_mb, 1)})

    except Exception as e:
        log.exception("MBTiles upload error: %s", e)
        return JSONResponse(
            {"status": "error", "detail": f"{type(e).__name__}: {e}"},
            status_code=500,
        )


@router.post("/api/gsm/tiles/remove")
async def tiles_remove():
    """Remove the offline map MBTiles file."""
    target = _data_dir() / "gsm" / "map.mbtiles"
    try:
        if target.exists():
            target.unlink()
            _app_log("[GSM] MBTiles removed")

            # Reset tile server singleton
            try:
                import backend.gsm.tile_server as ts_mod
                ts_mod._default_server = None
            except Exception:
                pass

        return JSONResponse({"status": "ok"})
    except Exception as e:
        return JSONResponse({"status": "error", "detail": str(e)}, status_code=500)


# ---------------------------------------------------------------------------
# KMZ / KML overlay management
# ---------------------------------------------------------------------------

def _overlays_dir() -> Path:
    d = _data_dir() / "gsm" / "overlays"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _parse_kml_bytes(kml_bytes: bytes) -> Dict[str, List[Dict[str, Any]]]:
    """Extract Placemarks (points and polygons) from KML XML bytes."""
    import xml.etree.ElementTree as ET

    ns = {"kml": "http://www.opengis.net/kml/2.2"}
    root = ET.fromstring(kml_bytes)

    placemarks = root.findall(".//kml:Placemark", ns)
    if not placemarks:
        placemarks = root.findall(".//{http://www.opengis.net/kml/2.2}Placemark")
    if not placemarks:
        placemarks = root.findall(".//Placemark")

    def _find_el(parent, tag):
        el = parent.find(f"kml:{tag}", ns)
        if el is None:
            el = parent.find(f"{{http://www.opengis.net/kml/2.2}}{tag}")
        if el is None:
            el = parent.find(tag)
        return el

    def _kml_color_to_hex(kml_color: str) -> str:
        kml_color = kml_color.strip()
        if len(kml_color) == 8:
            return f"#{kml_color[6:8]}{kml_color[4:6]}{kml_color[2:4]}"
        return "#4a6cf7"

    points: List[Dict[str, Any]] = []
    polygons: List[Dict[str, Any]] = []

    for pm in placemarks:
        name_el = _find_el(pm, "name")
        name = name_el.text.strip() if name_el is not None and name_el.text else ""
        desc_el = _find_el(pm, "description")
        desc = desc_el.text.strip() if desc_el is not None and desc_el.text else ""

        # Check for Polygon
        poly_el = pm.find(".//kml:Polygon", ns)
        if poly_el is None:
            poly_el = pm.find(".//{http://www.opengis.net/kml/2.2}Polygon")
        if poly_el is None:
            poly_el = pm.find(".//Polygon")

        if poly_el is not None:
            coord_el = poly_el.find(".//kml:outerBoundaryIs/kml:LinearRing/kml:coordinates", ns)
            if coord_el is None:
                coord_el = poly_el.find(".//{http://www.opengis.net/kml/2.2}outerBoundaryIs/{http://www.opengis.net/kml/2.2}LinearRing/{http://www.opengis.net/kml/2.2}coordinates")
            if coord_el is None:
                coord_el = poly_el.find(".//outerBoundaryIs/LinearRing/coordinates")
            if coord_el is not None and coord_el.text:
                coords = []
                for part in coord_el.text.strip().split():
                    try:
                        c = part.strip().split(",")
                        if len(c) >= 2:
                            coords.append([float(c[1]), float(c[0])])
                    except (ValueError, IndexError):
                        continue
                if len(coords) >= 4 and coords[0] == coords[-1]:
                    coords = coords[:-1]
                if len(coords) >= 3:
                    fill_color = "#4a6cf7"
                    style_url = _find_el(pm, "styleUrl")
                    if style_url is not None and style_url.text:
                        sid = style_url.text.lstrip("#")
                        style_el = root.find(f".//kml:Style[@id='{sid}']/kml:PolyStyle/kml:color", ns)
                        if style_el is None:
                            style_el = root.find(f".//Style[@id='{sid}']/PolyStyle/color")
                        if style_el is not None and style_el.text:
                            fill_color = _kml_color_to_hex(style_el.text)
                    inline_color = pm.find(".//kml:Style/kml:PolyStyle/kml:color", ns)
                    if inline_color is None:
                        inline_color = pm.find(".//Style/PolyStyle/color")
                    if inline_color is not None and inline_color.text:
                        fill_color = _kml_color_to_hex(inline_color.text)
                    polygons.append({"name": name, "desc": desc, "coords": coords, "fillColor": fill_color})
            continue

        # Point coordinates
        coord_el = pm.find(".//kml:Point/kml:coordinates", ns)
        if coord_el is None:
            coord_el = pm.find(".//{http://www.opengis.net/kml/2.2}Point/{http://www.opengis.net/kml/2.2}coordinates")
        if coord_el is None:
            coord_el = pm.find(".//Point/coordinates")
        if coord_el is None or not coord_el.text:
            continue
        coord_text = coord_el.text.strip()
        parts = coord_text.split(",")
        if len(parts) < 2:
            continue
        try:
            lon = float(parts[0].strip())
            lat = float(parts[1].strip())
        except (ValueError, IndexError):
            continue
        points.append({"name": name, "desc": desc, "lat": lat, "lon": lon})

    return {"points": points, "polygons": polygons}


@router.post("/api/gsm/overlays/upload")
async def overlay_upload(
    file: UploadFile = File(...),
    name: str = Form(""),
):
    """Upload a KMZ or KML file and store as a named overlay."""
    if not file.filename:
        return JSONResponse({"status": "error", "detail": "Brak pliku"}, status_code=400)

    suffix = Path(file.filename).suffix.lower()
    if suffix not in (".kmz", ".kml"):
        return JSONResponse(
            {"status": "error", "detail": f"Wymagany plik .kmz lub .kml, otrzymano: {suffix}"},
            status_code=400,
        )

    content = await file.read()

    # Parse KML from KMZ (ZIP) or raw KML
    try:
        if suffix == ".kmz":
            import zipfile
            import io
            with zipfile.ZipFile(io.BytesIO(content)) as zf:
                kml_bytes = None
                for zname in zf.namelist():
                    if zname.lower().endswith(".kml"):
                        kml_bytes = zf.read(zname)
                        break
                if not kml_bytes:
                    return JSONResponse(
                        {"status": "error", "detail": "Plik KMZ nie zawiera pliku .kml"},
                        status_code=400,
                    )
        else:
            kml_bytes = content

        parsed = await run_in_threadpool(_parse_kml_bytes, kml_bytes)
    except Exception as e:
        log.exception("KML parse error: %s", e)
        return JSONResponse(
            {"status": "error", "detail": f"Błąd parsowania KML: {e}"},
            status_code=400,
        )

    points = parsed.get("points", [])
    polygons = parsed.get("polygons", [])

    if not points and not polygons:
        return JSONResponse(
            {"status": "error", "detail": "Nie znaleziono elementów (Placemark) w pliku KML."},
            status_code=400,
        )

    # Generate overlay ID and save
    overlay_id = uuid.uuid4().hex[:12]
    overlay_name = name.strip() or Path(file.filename).stem
    overlay_data = {
        "id": overlay_id,
        "name": overlay_name,
        "filename": file.filename,
        "point_count": len(points),
        "points": points,
        "polygon_count": len(polygons),
        "polygons": polygons,
    }

    out_path = _overlays_dir() / f"{overlay_id}.json"
    out_path.write_text(json.dumps(overlay_data, ensure_ascii=False, indent=1), encoding="utf-8")

    _app_log(f"[GSM] KML overlay uploaded: {overlay_name} ({len(points)} points, {len(polygons)} polygons)")

    return JSONResponse({
        "status": "ok",
        "id": overlay_id,
        "name": overlay_name,
        "point_count": len(points),
        "polygon_count": len(polygons),
    })


@router.get("/api/gsm/overlays")
async def overlay_list():
    """List all saved KMZ/KML overlays (without point data)."""
    overlays_dir = _overlays_dir()
    items = []
    for f in sorted(overlays_dir.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            items.append({
                "id": data.get("id", f.stem),
                "name": data.get("name", f.stem),
                "filename": data.get("filename", ""),
                "point_count": data.get("point_count", 0),
            })
        except Exception:
            continue
    return JSONResponse({"status": "ok", "overlays": items})


@router.get("/api/gsm/overlays/{overlay_id}")
async def overlay_get(overlay_id: str):
    """Get a single overlay with all point data."""
    fpath = _overlays_dir() / f"{overlay_id}.json"
    if not fpath.exists():
        return JSONResponse({"status": "error", "detail": "Nie znaleziono"}, status_code=404)
    try:
        data = json.loads(fpath.read_text(encoding="utf-8"))
        return JSONResponse({"status": "ok", **data})
    except Exception as e:
        return JSONResponse({"status": "error", "detail": str(e)}, status_code=500)


@router.delete("/api/gsm/overlays/{overlay_id}")
async def overlay_delete(overlay_id: str):
    """Delete a saved overlay."""
    fpath = _overlays_dir() / f"{overlay_id}.json"
    if fpath.exists():
        fpath.unlink()
        _app_log(f"[GSM] KML overlay deleted: {overlay_id}")
    return JSONResponse({"status": "ok"})


@router.post("/api/gsm/overlays/create")
async def overlay_create(request: Request):
    """Create a new empty user overlay (no file upload)."""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"status": "error", "detail": "Invalid JSON"}, status_code=400)

    overlay_name = (body.get("name") or "").strip()
    if not overlay_name:
        return JSONResponse({"status": "error", "detail": "Nazwa jest wymagana"}, status_code=400)

    overlay_id = uuid.uuid4().hex[:12]
    overlay_data = {
        "id": overlay_id,
        "name": overlay_name,
        "filename": "",
        "user_layer": True,
        "point_count": 0,
        "points": [],
        "polygon_count": 0,
        "polygons": [],
    }

    out_path = _overlays_dir() / f"{overlay_id}.json"
    out_path.write_text(json.dumps(overlay_data, ensure_ascii=False, indent=1), encoding="utf-8")
    _app_log(f"[GSM] User overlay created: {overlay_name}")

    return JSONResponse({"status": "ok", "id": overlay_id, "name": overlay_name})


@router.put("/api/gsm/overlays/{overlay_id}")
async def overlay_update(overlay_id: str, request: Request):
    """Update overlay points (for user-editable layers)."""
    fpath = _overlays_dir() / f"{overlay_id}.json"
    if not fpath.exists():
        return JSONResponse({"status": "error", "detail": "Nie znaleziono"}, status_code=404)

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"status": "error", "detail": "Invalid JSON"}, status_code=400)

    try:
        data = json.loads(fpath.read_text(encoding="utf-8"))
    except Exception as e:
        return JSONResponse({"status": "error", "detail": str(e)}, status_code=500)

    # Update fields
    if "name" in body:
        data["name"] = str(body["name"]).strip()
    if "points" in body:
        pts = body["points"]
        if not isinstance(pts, list):
            return JSONResponse({"status": "error", "detail": "points must be a list"}, status_code=400)
        # Validate point structure
        clean = []
        for p in pts:
            try:
                icon_raw = str(p.get("icon", ""))
                # Basic SVG sanitization: strip scripts, limit size
                if icon_raw:
                    icon_raw = icon_raw[:50000]  # max ~50KB
                    import re
                    icon_raw = re.sub(r"<script[\s\S]*?</script>", "", icon_raw, flags=re.IGNORECASE)
                    icon_raw = re.sub(r"\bon\w+\s*=", "data-x=", icon_raw)  # strip event handlers
                clean.append({
                    "name": str(p.get("name", "")),
                    "desc": str(p.get("desc", "")),
                    "lat": float(p["lat"]),
                    "lon": float(p["lon"]),
                    "color": str(p.get("color", "")),
                    "icon": icon_raw,
                })
            except (KeyError, ValueError, TypeError):
                continue
        data["points"] = clean
        data["point_count"] = len(clean)

    if "polygons" in body:
        pgns = body["polygons"]
        if not isinstance(pgns, list):
            return JSONResponse({"status": "error", "detail": "polygons must be a list"}, status_code=400)
        clean_pgns = []
        for pg in pgns:
            try:
                coords = pg.get("coords", [])
                if not isinstance(coords, list) or len(coords) < 3:
                    continue
                clean_coords = []
                for c in coords:
                    if isinstance(c, (list, tuple)) and len(c) >= 2:
                        clean_coords.append([float(c[0]), float(c[1])])
                if len(clean_coords) < 3:
                    continue
                clean_pgns.append({
                    "name": str(pg.get("name", "")),
                    "desc": str(pg.get("desc", "")),
                    "coords": clean_coords,
                    "fillColor": str(pg.get("fillColor", "#4a6cf7")),
                })
            except (KeyError, ValueError, TypeError):
                continue
        data["polygons"] = clean_pgns
        data["polygon_count"] = len(clean_pgns)

    fpath.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return JSONResponse({"status": "ok", "point_count": data.get("point_count", 0), "polygon_count": data.get("polygon_count", 0)})


@router.get("/api/gsm/overlays/{overlay_id}/export/kml")
async def overlay_export_kml(overlay_id: str):
    """Export overlay as KML file."""
    fpath = _overlays_dir() / f"{overlay_id}.json"
    if not fpath.exists():
        return JSONResponse({"status": "error", "detail": "Nie znaleziono"}, status_code=404)

    try:
        data = json.loads(fpath.read_text(encoding="utf-8"))
    except Exception as e:
        return JSONResponse({"status": "error", "detail": str(e)}, status_code=500)

    overlay_name = data.get("name", overlay_id)
    points = data.get("points", [])
    polygons = data.get("polygons", [])

    # Build KML XML
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<kml xmlns="http://www.opengis.net/kml/2.2">',
        "<Document>",
        f"  <name>{_kml_escape(overlay_name)}</name>",
    ]
    for pt in points:
        lat = pt.get("lat", 0)
        lon = pt.get("lon", 0)
        name = pt.get("name", "")
        desc = pt.get("desc", "")
        lines.append("  <Placemark>")
        if name:
            lines.append(f"    <name>{_kml_escape(name)}</name>")
        if desc:
            lines.append(f"    <description>{_kml_escape(desc)}</description>")
        lines.append("    <Point>")
        lines.append(f"      <coordinates>{lon},{lat},0</coordinates>")
        lines.append("    </Point>")
        lines.append("  </Placemark>")

    for i, pg in enumerate(polygons):
        coords = pg.get("coords", [])
        if len(coords) < 3:
            continue
        name = pg.get("name", "")
        desc = pg.get("desc", "")
        fill_color = pg.get("fillColor", "#4a6cf7")
        kml_color = _hex_to_kml_color(fill_color, alpha_hex="4D")
        style_id = f"poly_{i}"
        lines.append(f'  <Style id="{style_id}">')
        lines.append(f"    <PolyStyle><color>{kml_color}</color></PolyStyle>")
        lines.append(f"    <LineStyle><color>{_hex_to_kml_color(fill_color, alpha_hex='FF')}</color><width>2</width></LineStyle>")
        lines.append("  </Style>")
        lines.append("  <Placemark>")
        if name:
            lines.append(f"    <name>{_kml_escape(name)}</name>")
        if desc:
            lines.append(f"    <description>{_kml_escape(desc)}</description>")
        lines.append(f"    <styleUrl>#{style_id}</styleUrl>")
        lines.append("    <Polygon><outerBoundaryIs><LinearRing>")
        coord_strs = [f"{c[1]},{c[0]},0" for c in coords]
        coord_strs.append(coord_strs[0])
        lines.append(f"      <coordinates>{' '.join(coord_strs)}</coordinates>")
        lines.append("    </LinearRing></outerBoundaryIs></Polygon>")
        lines.append("  </Placemark>")

    lines.append("</Document>")
    lines.append("</kml>")

    kml_content = "\n".join(lines)
    safe_name = "".join(c if c.isalnum() or c in "._- " else "_" for c in overlay_name)

    from starlette.responses import Response
    return Response(
        content=kml_content,
        media_type="application/vnd.google-earth.kml+xml",
        headers={"Content-Disposition": f'attachment; filename="{safe_name}.kml"'},
    )


def _hex_to_kml_color(hex_color: str, alpha_hex: str = "FF") -> str:
    """Convert #RRGGBB hex color to KML aaBBGGRR format."""
    hex_color = hex_color.lstrip("#")
    if len(hex_color) != 6:
        hex_color = "4a6cf7"
    return f"{alpha_hex}{hex_color[4:6]}{hex_color[2:4]}{hex_color[0:2]}"


def _kml_escape(text: str) -> str:
    """Escape XML special characters for KML."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


@router.get("/api/gsm/map-icons")
async def map_icons_list():
    """List available map icons from static/icons/maps/ grouped by category."""
    icons_root = Path(__file__).resolve().parents[1] / "static" / "icons" / "maps"
    if not icons_root.is_dir():
        return JSONResponse({"status": "ok", "categories": []})

    categories = []
    for cat_dir in sorted(icons_root.iterdir()):
        if not cat_dir.is_dir():
            continue
        icons = []
        for svg in sorted(cat_dir.glob("*.svg")):
            icons.append({
                "name": svg.stem,
                "path": f"/static/icons/maps/{cat_dir.name}/{svg.name}",
            })
        if icons:
            categories.append({"category": cat_dir.name, "icons": icons})
    return JSONResponse({"status": "ok", "categories": categories})
