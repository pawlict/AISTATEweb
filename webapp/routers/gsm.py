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

        content_type = resp.headers.get("content-type", "")
        raw = resp.content
        size_mb = len(raw) / 1048576
        _app_log(f"[GSM] Downloaded {size_mb:.1f} MB from OpenCelliD")

        # Decompress if gzipped
        csv_path = tmp_dir / "cell_towers.csv"
        if raw[:2] == b"\x1f\x8b" or url.endswith(".gz"):
            decompressed = gzip.decompress(raw)
            csv_path.write_bytes(decompressed)
            _app_log(f"[GSM] Decompressed to {len(decompressed)/1048576:.1f} MB")
        else:
            csv_path.write_bytes(raw)

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
    """Download UKE (Polish regulator) BTS database."""
    import httpx

    _app_log("[GSM] Downloading UKE BTS database...")

    # UKE publishes BTS data at their BIP site.
    # The CSV export of radio permits is at a known URL pattern.
    uke_url = "https://bip.uke.gov.pl/pozwolenia-radiowe/wykorzystywane-czestotliwosci-702-703-713-MHz/stacje.csv"

    # Fallback URLs to try
    uke_urls = [
        uke_url,
        "https://bip.uke.gov.pl/pozwolenia-radiowe/stacje-bazowe-702-703-713/stacje.csv",
    ]

    tmp_dir = Path(tempfile.mkdtemp(prefix="bts_uke_"))
    try:
        raw = None
        last_error = None
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(300.0, connect=30.0),
            follow_redirects=True,
        ) as client:
            for url in uke_urls:
                try:
                    resp = await client.get(url)
                    if resp.status_code == 200 and len(resp.content) > 1000:
                        raw = resp.content
                        _app_log(f"[GSM] Downloaded {len(raw)/1048576:.1f} MB from UKE ({url})")
                        break
                except Exception as e:
                    last_error = e
                    continue

        if raw is None:
            detail = "Nie udało się pobrać danych z BIP UKE. Wgraj plik CSV ręcznie."
            if last_error:
                detail += f" ({last_error})"
            return JSONResponse({"status": "error", "detail": detail}, status_code=500)

        csv_path = tmp_dir / "uke_stacje.csv"
        csv_path.write_bytes(raw)

        from backend.gsm.bts_db import get_bts_db
        db = get_bts_db(_data_dir())
        count = await run_in_threadpool(db.import_uke_csv, csv_path)

        _app_log(f"[GSM] Imported {count} stations from UKE")
        stats = await run_in_threadpool(db.get_stats)
        return JSONResponse({"status": "ok", "imported": count, **stats})

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
