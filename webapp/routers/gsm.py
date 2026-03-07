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
