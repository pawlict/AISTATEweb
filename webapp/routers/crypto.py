"""Crypto transaction analysis API router.

Endpoints:
- POST /api/crypto/analyze        — upload CSV/JSON/XLSX file and run full pipeline
- GET  /api/crypto/detail         — get saved analysis detail for project
- GET  /api/crypto/report         — generate HTML report for project
- GET  /api/crypto/llm-stream     — SSE streaming LLM narrative analysis
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import traceback
from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter, File, Form, Query, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, JSONResponse
from starlette.responses import StreamingResponse

log = logging.getLogger("aistate.api.crypto")

router = APIRouter()


def _data_dir() -> Path:
    return Path(os.environ.get("AISTATEWEB_DATA_DIR", "data_www"))


def _app_log(msg: str) -> None:
    try:
        from webapp.server import app_log
        app_log(msg)
    except Exception:
        pass


def _project_path(project_id: str) -> Path:
    return _data_dir() / "projects" / project_id


def _crypto_save_path(project_id: str) -> Path:
    p = _project_path(project_id) / "analysis"
    p.mkdir(parents=True, exist_ok=True)
    return p / "crypto_latest.json"


# ---------------------------------------------------------------------------
#  Upload & analyze
# ---------------------------------------------------------------------------

@router.post("/api/crypto/analyze")
async def crypto_analyze(
    request: Request,
    file: UploadFile = File(...),
    project_id: str = Form(""),
):
    """Upload a crypto CSV/JSON/XLSX file and run the full analysis pipeline."""
    try:
        filename = file.filename or "upload.csv"
        content = await file.read()
        file_size = len(content)
        _app_log(f"[Crypto] Upload: {filename} ({file_size} bytes)")
        log.info("Crypto analyze request: file=%s size=%d project=%s", filename, file_size, project_id or "(none)")

        # Save to temp file
        suffix = Path(filename).suffix or ".csv"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(content)
            tmp_path = tmp.name

        # Run pipeline in threadpool (CPU-bound)
        from backend.crypto.pipeline import run_crypto_pipeline
        result = await run_in_threadpool(
            run_crypto_pipeline, tmp_path, project_id, filename
        )

        # Cleanup temp file
        try:
            os.unlink(tmp_path)
        except Exception:
            pass

        if not result.get("ok"):
            errors = result.get("errors", ["Nieznany błąd parsowania"])
            _app_log(f"[Crypto] Parse FAILED: {filename} — {'; '.join(errors)}")
            log.warning("Crypto parse failed: file=%s errors=%s", filename, errors)
            return JSONResponse({
                "status": "error",
                "errors": errors,
            }, status_code=400)

        # Save result to project
        if project_id:
            try:
                save_path = _crypto_save_path(project_id)
                save_path.write_text(
                    json.dumps(result, ensure_ascii=False, indent=1),
                    encoding="utf-8",
                )
                _app_log(f"[Crypto] Saved analysis to {save_path.name}")
            except Exception as e:
                log.warning("Failed to save crypto analysis: %s", e)
                _app_log(f"[Crypto] Save ERROR: {e}")

        tx_count = result.get('tx_count', 0)
        risk = result.get('risk_score', 0)
        elapsed = result.get('elapsed_sec', 0)
        source = result.get('source', '?')
        chain = result.get('chain', '?')
        wallets = result.get('wallet_count', 0)
        alerts_count = len(result.get('alerts', []))

        _app_log(
            f"[Crypto] Done: {filename} — {source}/{chain}, "
            f"{tx_count} txs, {wallets} wallets, "
            f"risk={risk:.1f}/100, alerts={alerts_count}, "
            f"{elapsed:.1f}s"
        )
        log.info(
            "Crypto analyze done: file=%s source=%s chain=%s txs=%d wallets=%d "
            "risk=%.1f alerts=%d elapsed=%.2fs",
            filename, source, chain, tx_count, wallets, risk, alerts_count, elapsed,
        )

        return JSONResponse({"status": "ok", "result": result})

    except Exception as e:
        log.exception("Crypto analyze error")
        _app_log(f"[Crypto] ERROR: {type(e).__name__}: {e}")
        return JSONResponse({
            "status": "error",
            "errors": [str(e)],
        }, status_code=500)


# ---------------------------------------------------------------------------
#  Load saved analysis
# ---------------------------------------------------------------------------

@router.get("/api/crypto/detail")
async def crypto_detail(project_id: str = Query("")):
    """Load the last saved crypto analysis for a project."""
    if not project_id:
        return JSONResponse({"status": "error", "detail": "project_id required"}, status_code=400)

    save_path = _crypto_save_path(project_id)
    if not save_path.exists():
        log.debug("Crypto detail: no saved analysis for project=%s", project_id)
        return JSONResponse({"status": "ok", "result": None})

    try:
        data = json.loads(save_path.read_text(encoding="utf-8"))
        log.info("Crypto detail loaded: project=%s txs=%s", project_id, data.get("tx_count", "?"))
        return JSONResponse({"status": "ok", "result": data})
    except Exception as e:
        log.error("Crypto detail load error: project=%s error=%s", project_id, e)
        return JSONResponse({"status": "error", "detail": str(e)}, status_code=500)


# ---------------------------------------------------------------------------
#  LLM Narrative Analysis (SSE streaming)
# ---------------------------------------------------------------------------

@router.get("/api/crypto/config-stats")
async def crypto_config_stats():
    """Return counts of sanctioned addresses and known contracts."""
    import json as _json
    config_dir = Path(__file__).resolve().parent.parent.parent / "backend" / "crypto" / "config"
    ofac_count = 0
    contracts_count = 0
    try:
        sanc_path = config_dir / "sanctioned.json"
        if sanc_path.exists():
            data = _json.loads(sanc_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                ofac_count = sum(len(v) if isinstance(v, list) else 1 for v in data.values())
            elif isinstance(data, list):
                ofac_count = len(data)
    except Exception as e:
        log.warning("Failed to load sanctioned.json: %s", e)
    try:
        cont_path = config_dir / "known_contracts.json"
        if cont_path.exists():
            data = _json.loads(cont_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                contracts_count = sum(len(v) if isinstance(v, list) else 1 for v in data.values())
            elif isinstance(data, list):
                contracts_count = len(data)
    except Exception as e:
        log.warning("Failed to load known_contracts.json: %s", e)
    log.debug("Crypto config-stats: ofac=%d contracts=%d", ofac_count, contracts_count)
    return JSONResponse({
        "ofac_count": ofac_count,
        "contracts_count": contracts_count,
    })


# ---------------------------------------------------------------------------
#  OFAC Sanctioned Addresses management
# ---------------------------------------------------------------------------

@router.get("/api/crypto/ofac/stats")
async def crypto_ofac_stats():
    """Get detailed OFAC sanctioned addresses statistics."""
    try:
        from backend.crypto.ofac_importer import get_ofac_stats
        stats = await run_in_threadpool(get_ofac_stats)
        return JSONResponse({"status": "ok", **stats})
    except Exception as e:
        log.exception("OFAC stats error")
        return JSONResponse({"status": "error", "detail": str(e)}, status_code=500)


@router.post("/api/crypto/ofac/download")
async def crypto_ofac_download(request: Request):
    """Download OFAC SDN_ADVANCED.XML and import sanctioned crypto addresses."""
    try:
        body: Dict[str, Any] = {}
        try:
            body = await request.json()
        except Exception:
            pass

        url = body.get("url", "").strip()
        replace = body.get("replace", True)

        _app_log("[Crypto/OFAC] Starting online download...")
        log.info("OFAC download: url=%s replace=%s", url or "(default)", replace)

        from backend.crypto.ofac_importer import download_and_import, DEFAULT_SOURCE_URL
        result = await run_in_threadpool(
            download_and_import,
            url=url or DEFAULT_SOURCE_URL,
            replace=replace,
        )

        _app_log(
            f"[Crypto/OFAC] Download done: {result.get('total_addresses', 0)} addresses, "
            f"{result.get('entities', 0)} entities"
        )
        log.info("OFAC download done: %s", result)
        return JSONResponse(result)

    except Exception as e:
        log.exception("OFAC download error")
        _app_log(f"[Crypto/OFAC] Download ERROR: {type(e).__name__}: {e}")
        return JSONResponse({
            "status": "error",
            "detail": str(e),
        }, status_code=500)


@router.post("/api/crypto/ofac/import")
async def crypto_ofac_import(
    file: UploadFile = File(...),
):
    """Import OFAC sanctioned addresses from an uploaded XML file."""
    try:
        filename = file.filename or "sdn_advanced.xml"
        content = await file.read()
        file_size = len(content)
        _app_log(f"[Crypto/OFAC] Offline import: {filename} ({file_size} bytes)")
        log.info("OFAC import: file=%s size=%d", filename, file_size)

        # Save to temp
        import tempfile as _tempfile
        suffix = Path(filename).suffix or ".xml"
        with _tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(content)
            tmp_path = Path(tmp.name)

        try:
            from backend.crypto.ofac_importer import import_from_file
            result = await run_in_threadpool(import_from_file, tmp_path, True)
        finally:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass

        _app_log(
            f"[Crypto/OFAC] Import done: {result.get('total_addresses', 0)} addresses, "
            f"{result.get('entities', 0)} entities"
        )
        log.info("OFAC import done: %s", result)
        return JSONResponse(result)

    except Exception as e:
        log.exception("OFAC import error")
        _app_log(f"[Crypto/OFAC] Import ERROR: {type(e).__name__}: {e}")
        return JSONResponse({
            "status": "error",
            "detail": str(e),
        }, status_code=500)


@router.post("/api/crypto/ofac/clear")
async def crypto_ofac_clear():
    """Clear all OFAC-sourced addresses from sanctioned.json."""
    try:
        config_path = Path(__file__).resolve().parent.parent.parent / "backend" / "crypto" / "config" / "sanctioned.json"

        if config_path.exists():
            data = json.loads(config_path.read_text(encoding="utf-8"))
            # Remove OFAC-sourced addresses
            addresses = data.get("addresses", {})
            kept = {k: v for k, v in addresses.items()
                    if not (isinstance(v, dict) and "OFAC" in str(v.get("reason", "")))}
            data["addresses"] = kept
            data["_ofac_records"] = 0
            data["_last_update"] = None
            config_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            # Invalidate cache
            try:
                from backend.crypto.ofac_importer import _invalidate_cache
                _invalidate_cache()
            except Exception:
                pass

            removed = len(addresses) - len(kept)
            _app_log(f"[Crypto/OFAC] Cleared {removed} OFAC addresses, kept {len(kept)} manual")
            return JSONResponse({"status": "ok", "removed": removed, "kept": len(kept)})
        else:
            return JSONResponse({"status": "ok", "removed": 0, "kept": 0})
    except Exception as e:
        log.exception("OFAC clear error")
        return JSONResponse({"status": "error", "detail": str(e)}, status_code=500)


# ---------------------------------------------------------------------------
#  Transaction classifications (save/load per project)
# ---------------------------------------------------------------------------

def _classifications_path(project_id: str) -> Path:
    p = _project_path(project_id) / "analysis"
    p.mkdir(parents=True, exist_ok=True)
    return p / "crypto_classifications.json"


def _load_classifications(project_id: str) -> Dict[str, str]:
    path = _classifications_path(project_id)
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_classifications(project_id: str, cls_map: Dict[str, str]) -> None:
    path = _classifications_path(project_id)
    path.write_text(
        json.dumps(cls_map, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )


@router.get("/api/crypto/classifications")
async def crypto_get_classifications(project_id: str = Query("")):
    """Load saved transaction classifications for a project."""
    if not project_id:
        return JSONResponse({"classifications": {}})
    try:
        cls_map = _load_classifications(project_id)
        return JSONResponse({"classifications": cls_map})
    except Exception as e:
        log.warning("Failed to load crypto classifications: %s", e)
        return JSONResponse({"classifications": {}})


@router.post("/api/crypto/classify")
async def crypto_classify(request: Request):
    """Save a single transaction classification."""
    try:
        body = await request.json()
        project_id = body.get("project_id", "")
        tx_id = body.get("tx_id", "")
        classification = body.get("classification", "")

        if not project_id or not tx_id or not classification:
            return JSONResponse(
                {"status": "error", "detail": "project_id, tx_id, classification required"},
                status_code=400,
            )

        cls_map = _load_classifications(project_id)
        cls_map[tx_id] = classification
        await run_in_threadpool(_save_classifications, project_id, cls_map)

        log.debug("Crypto classify: project=%s tx=%s cls=%s", project_id, tx_id[:16], classification)
        return JSONResponse({"status": "ok"})
    except Exception as e:
        log.exception("Crypto classify error")
        return JSONResponse({"status": "error", "detail": str(e)}, status_code=500)


@router.post("/api/crypto/classify-batch")
async def crypto_classify_batch(request: Request):
    """Save multiple transaction classifications at once."""
    try:
        body = await request.json()
        project_id = body.get("project_id", "")
        classifications = body.get("classifications", {})

        if not project_id or not classifications:
            return JSONResponse(
                {"status": "error", "detail": "project_id and classifications required"},
                status_code=400,
            )

        cls_map = _load_classifications(project_id)
        # Only add new classifications, don't override existing manual ones
        for tx_id, cls in classifications.items():
            if tx_id not in cls_map:
                cls_map[tx_id] = cls
        await run_in_threadpool(_save_classifications, project_id, cls_map)

        log.info("Crypto classify-batch: project=%s count=%d total=%d",
                 project_id, len(classifications), len(cls_map))
        return JSONResponse({"status": "ok", "saved": len(cls_map)})
    except Exception as e:
        log.exception("Crypto classify-batch error")
        return JSONResponse({"status": "error", "detail": str(e)}, status_code=500)


# ---------------------------------------------------------------------------
#  LLM Narrative Analysis (SSE streaming)
# ---------------------------------------------------------------------------

@router.get("/api/crypto/llm-stream")
async def crypto_llm_stream(
    model: str = Query(""),
    user_prompt: str = Query(""),
    project_id: str = Query(""),
):
    """SSE streaming LLM analysis for crypto transaction data."""

    # Load saved crypto analysis
    crypto_data: dict = {}
    if project_id:
        try:
            save_path = _crypto_save_path(project_id)
            if save_path.exists():
                crypto_data = json.loads(save_path.read_text(encoding="utf-8"))
        except Exception as e:
            log.warning("Crypto LLM: failed to load data: %s", e)

    llm_prompt = crypto_data.get("llm_prompt", "")
    if not llm_prompt:
        log.info("Crypto LLM: no data for project=%s", project_id)
        _app_log(f"[Crypto] LLM: brak danych do analizy (project={project_id})")
        async def err_gen():
            yield f"data: {json.dumps({'error': 'Brak danych kryptowalutowych do analizy. Najpierw zaimportuj plik CSV.', 'done': True})}\n\n"
        return StreamingResponse(err_gen(), media_type="text/event-stream")

    # Append user prompt if provided
    if user_prompt.strip():
        llm_prompt += f"\n\n## Dodatkowe polecenie użytkownika\n{user_prompt.strip()}"

    chosen_model = model.strip()
    _app_log(f"[Crypto] LLM stream start: model={chosen_model or '(default)'}, project={project_id}")
    log.info("Crypto LLM stream: model=%s project=%s prompt_len=%d", chosen_model or "(default)", project_id, len(llm_prompt))

    async def generate():
        try:
            from backend.ollama_client import OllamaClient, stream_analyze
            client = OllamaClient()
            system_msg = (
                "Jesteś ekspertem ds. analizy transakcji kryptowalutowych, "
                "blockchain forensics i przeciwdziałania praniu pieniędzy (AML). "
                "Odpowiadaj po polsku, profesjonalnym językiem. "
                "Formatuj odpowiedź używając nagłówków markdown (##, ###). "
                "Bądź precyzyjny, wskazuj konkretne adresy i kwoty."
            )
            chunk_count = 0
            async for chunk in stream_analyze(
                client, llm_prompt, model=chosen_model,
                system=system_msg,
                options={"temperature": 0.3, "num_ctx": 8192},
            ):
                chunk_count += 1
                yield f"data: {json.dumps({'chunk': chunk, 'done': False}, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'chunk': '', 'done': True, 'chunks': chunk_count})}\n\n"
            _app_log(f"[Crypto] LLM stream done: {chunk_count} chunks")
            log.info("Crypto LLM stream done: chunks=%d", chunk_count)
        except Exception as e:
            log.exception("Crypto LLM stream error")
            _app_log(f"[Crypto] LLM ERROR: {type(e).__name__}: {e}")
            yield f"data: {json.dumps({'error': str(e), 'done': True})}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


# ---------------------------------------------------------------------------
#  Report generation (HTML / TXT / DOCX)
# ---------------------------------------------------------------------------

@router.get("/api/crypto/report")
async def crypto_report(
    project_id: str = Query(""),
    formats: str = Query("html"),
):
    """Generate a report for the project's crypto analysis.

    Supported formats (comma-separated): html, txt, docx.
    Returns the first selected format inline; if DOCX, returns as download.
    """
    if not project_id:
        return JSONResponse({"status": "error", "detail": "project_id required"}, status_code=400)

    save_path = _crypto_save_path(project_id)
    if not save_path.exists():
        return JSONResponse({"status": "error", "detail": "No saved crypto analysis"}, status_code=404)

    try:
        result = json.loads(save_path.read_text(encoding="utf-8"))
    except Exception as e:
        return JSONResponse({"status": "error", "detail": str(e)}, status_code=500)

    fmt_list = [f.strip().lower() for f in formats.split(",") if f.strip()]
    if not fmt_list:
        fmt_list = ["html"]

    primary = fmt_list[0]

    if primary == "txt":
        txt = _build_crypto_report_txt(result)
        return StreamingResponse(
            iter([txt.encode("utf-8")]),
            media_type="text/plain; charset=utf-8",
            headers={"Content-Disposition": f"attachment; filename=crypto_report.txt"},
        )

    if primary == "docx":
        try:
            from backend.report_generator import generate_crypto_docx
            docx_bytes = generate_crypto_docx(result)
            return StreamingResponse(
                iter([docx_bytes]),
                media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                headers={"Content-Disposition": f"attachment; filename=crypto_report.docx"},
            )
        except ImportError:
            # Fallback: generate TXT if DOCX module unavailable
            txt = _build_crypto_report_txt(result)
            return StreamingResponse(
                iter([txt.encode("utf-8")]),
                media_type="text/plain; charset=utf-8",
                headers={"Content-Disposition": f"attachment; filename=crypto_report.txt"},
            )

    # Default: HTML
    html = _build_crypto_report_html(result)
    return HTMLResponse(html)


def _resc(s) -> str:
    """HTML-escape a string."""
    return (str(s)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;"))


def _build_crypto_report_html(r: Dict[str, Any]) -> str:
    """Build a standalone HTML report with logical section ordering.

    Sections:
      I.   Identyfikacja — account info, user IDs
      II.  Podsumowanie ogólne — stats, tokens, date range
      III. Profil zachowania — user behavior profiling
      IV.  Ocena ryzyka AML — risk score, reasons, alerts
      V.   Portfel tokenów — token breakdown
      VI.  Kontrahenci i transfery — counterparties, pay C2C, phones
      VII. Adresy on-chain — external src/dst, wallets, deposit addresses
      VIII.Analiza kryminalistyczna — pass-through, privacy coins, mining
      IX.  Bezpieczeństwo konta — access logs, devices, card timeline
      X.   Transakcje — full transaction list
    """
    from datetime import datetime

    filename = r.get("filename", "")
    date_from = (r.get("date_from", "") or "")[:10]
    date_to = (r.get("date_to", "") or "")[:10]
    risk_score = r.get("risk_score", 0)
    tx_count = r.get("tx_count", 0)
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    em = r.get("exchange_meta", {})
    fr = r.get("forensic_report", {}) or {}
    ai = fr.get("account_info", {}) or {}
    bs = r.get("binance_summary", {}) or {}
    source = r.get("source", "?")

    if risk_score >= 70:
        rl, rc = "KRYTYCZNE", "#dc2626"
    elif risk_score >= 50:
        rl, rc = "WYSOKIE", "#f97316"
    elif risk_score >= 25:
        rl, rc = "SREDNIE", "#eab308"
    else:
        rl, rc = "NISKIE", "#22c55e"

    sn = 0  # section number
    sections = []

    # ── I. Identyfikacja ──
    sn += 1
    id_rows = []
    for label, val in [
        ("Właściciel konta", ai.get("holder_name")),
        ("User ID", ai.get("user_id")),
        ("Email", ai.get("email")),
        ("Telefon", ai.get("phone")),
        ("Kraj", ai.get("country")),
        ("Narodowość", ai.get("nationality")),
        ("KYC Level", ai.get("kyc_level")),
        ("Data rejestracji", ai.get("registration_date")),
        ("Status konta", ai.get("account_status")),
        ("Typ dokumentu", ai.get("id_type")),
        ("Nr dokumentu", ai.get("id_number")),
        ("Platforma", em.get("exchange_name") or source),
        ("Plik źródłowy", filename),
    ]:
        if val:
            id_rows.append(f"<tr><th>{_resc(label)}</th><td>{_resc(val)}</td></tr>")

    # User IDs across sheets
    uids = fr.get("user_ids_in_file", {})
    uid_html = ""
    if uids:
        uid_rows = "".join(f"<tr><td>{_resc(sh)}</td><td><code>{_resc(', '.join(ids))}</code></td></tr>"
                           for sh, ids in uids.items())
        uid_html = f'<h3>User IDs w poszczególnych arkuszach</h3><table class="data-table"><thead><tr><th>Arkusz</th><th>User ID</th></tr></thead><tbody>{uid_rows}</tbody></table>'

    sections.append(f'<h2>{sn}. Identyfikacja podmiotu</h2><table class="info-table">{"".join(id_rows)}</table>{uid_html}')

    # ── II. Podsumowanie ogólne ──
    sn += 1
    sum_rows = [
        f"<tr><th>Okres analizy</th><td>{_resc(date_from)} — {_resc(date_to)}</td></tr>",
        f"<tr><th>Łączna liczba transakcji</th><td>{tx_count}</td></tr>",
        f"<tr><th>Portfele / adresy</th><td>{r.get('wallet_count', 0)}</td></tr>",
        f"<tr><th>Kontrahenci</th><td>{r.get('counterparty_count', 0)}</td></tr>",
        f"<tr><th>Unikalne tokeny</th><td>{len(r.get('tokens', {}))}</td></tr>",
        f"<tr><th>Ryzyko AML</th><td style='color:{rc};font-weight:bold'>{risk_score:.1f}/100 ({rl})</td></tr>",
    ]
    if em.get("crypto_tokens"):
        sum_rows.append(f"<tr><th>Tokeny krypto</th><td>{_resc(', '.join(em['crypto_tokens']))}</td></tr>")
    if em.get("fiat_tokens"):
        sum_rows.append(f"<tr><th>Waluty fiat</th><td>{_resc(', '.join(em['fiat_tokens']))}</td></tr>")
    if em.get("account_types"):
        sum_rows.append(f"<tr><th>Typy kont</th><td>{_resc(', '.join(em['account_types']))}</td></tr>")

    # Fiat in/out
    fiat_in = bs.get("fiat_in", {})
    fiat_out = bs.get("fiat_out", {})
    for cur, amt in fiat_in.items():
        sum_rows.append(f"<tr><th>Wpłaty fiat ({_resc(cur)})</th><td>{amt:,.2f}</td></tr>")
    for cur, amt in fiat_out.items():
        sum_rows.append(f"<tr><th>Wypłaty fiat ({_resc(cur)})</th><td>{amt:,.2f}</td></tr>")

    sections.append(f'<h2>{sn}. Podsumowanie ogólne</h2><table class="info-table">{"".join(sum_rows)}</table>')

    # ── III. Profil zachowania ──
    bp = r.get("behavior_profile", {})
    if bp and bp.get("profiles"):
        sn += 1
        ph = ""
        for p in bp["profiles"][:5]:
            if p["score"] < 15:
                continue
            reasons = ""
            if p.get("reasons"):
                reasons = "<ul>" + "".join(f"<li>{_resc(rr)}</li>" for rr in p["reasons"]) + "</ul>"
            bc = '#22c55e' if p['score'] >= 50 else '#eab308' if p['score'] >= 30 else '#94a3b8'
            ph += f'<div class="profile-card" style="border-left:4px solid {bc}"><strong>{_resc(p["icon"])} {_resc(p["label"])}</strong> — {p["score"]}%<div class="desc">{_resc(p["desc"])}</div>{reasons}</div>'
        sections.append(f"<h2>{sn}. Profil zachowania użytkownika</h2>{ph}")

    # ── IV. Ocena ryzyka AML ──
    sn += 1
    risk_html = f'<div style="font-size:18px;font-weight:bold;color:{rc};margin-bottom:12px">{risk_score:.1f}/100 — {rl}</div>'
    risk_reasons = r.get("risk_reasons", [])
    if risk_reasons:
        risk_html += "<h3>Czynniki ryzyka</h3><ul>" + "".join(f"<li>{_resc(rr)}</li>" for rr in risk_reasons) + "</ul>"
    alerts = r.get("alerts", [])
    if alerts:
        alert_items = "".join(f"<li><strong>{_resc(a.get('type', ''))}</strong>: {_resc(a.get('message', ''))}</li>" for a in alerts[:50])
        risk_html += f"<h3>Alerty ({len(alerts)})</h3><ul>{alert_items}</ul>"
    sections.append(f"<h2>{sn}. Ocena ryzyka AML</h2>{risk_html}")

    # ── V. Portfel tokenów ──
    tokens = r.get("tokens", {})
    if tokens:
        sn += 1
        rows = ""
        for tok, s in sorted(tokens.items(), key=lambda x: x[1].get("count", 0), reverse=True):
            net = (s.get("received", 0) or 0) - (s.get("sent", 0) or 0)
            nc = "#22c55e" if net >= 0 else "#dc2626"
            rows += f"<tr><td style='font-weight:600'>{_resc(tok)}</td><td class='num'>{s.get('received', 0):.4f}</td><td class='num'>{s.get('sent', 0):.4f}</td><td class='num' style='color:{nc}'>{net:.4f}</td><td>{s.get('count', 0)}</td></tr>"
        sections.append(f'<h2>{sn}. Portfel tokenów</h2><table class="data-table"><thead><tr><th>Token</th><th>Wpływy</th><th>Wypływy</th><th>Saldo netto</th><th>TX</th></tr></thead><tbody>{rows}</tbody></table>')

    # ── VI. Kontrahenci i transfery ──
    cps = bs.get("counterparties", {})
    pay_cps = fr.get("binance_pay_counterparties", {})
    phones = r.get("detected_phones", [])
    if cps or pay_cps or phones:
        sn += 1
        ct_html = ""
        if cps:
            rows = ""
            for uid, c in sorted(cps.items(), key=lambda x: x[1].get("tx_count", 0), reverse=True)[:50]:
                period = f"{(c.get('first_seen', '') or '')[:10]} — {(c.get('last_seen', '') or '')[:10]}"
                rows += f"<tr><td><code>{_resc(uid)}</code></td><td>{c.get('tx_count', 0)}</td><td class='num'>{c.get('total_in', 0):.4f}</td><td class='num'>{c.get('total_out', 0):.4f}</td><td>{_resc(', '.join(c.get('tokens', [])))}</td><td>{_resc(', '.join(c.get('sources', [])))}</td><td style='font-size:11px'>{_resc(period)}</td></tr>"
            ct_html += f'<h3>Kontrahenci wewnętrzni Binance</h3><table class="data-table"><thead><tr><th>User ID</th><th>TX</th><th>Wpływy</th><th>Wypływy</th><th>Tokeny</th><th>Źródło</th><th>Okres</th></tr></thead><tbody>{rows}</tbody></table>'
            ct_html += f'<p>Transfery wewnętrzne: <b>{bs.get("internal_transfer_count", 0)}</b> | Depozyty zewnętrzne: <b>{bs.get("external_deposit_count", 0)}</b> | Wypłaty zewnętrzne: <b>{bs.get("external_withdrawal_count", 0)}</b></p>'

        if pay_cps:
            rows = ""
            for k, c in sorted(pay_cps.items(), key=lambda x: x[1].get("count", 0), reverse=True)[:30]:
                rows += f"<tr><td><code>{_resc(k)}</code></td><td>{_resc(c.get('wallet_id', ''))}</td><td>{c.get('count', 0)}</td><td class='num'>{c.get('in', 0):.4f}</td><td class='num'>{c.get('out', 0):.4f}</td><td>{_resc(', '.join(c.get('tokens', [])))}</td></tr>"
            ct_html += f'<h3>Binance Pay (C2C)</h3><table class="data-table"><thead><tr><th>Binance ID</th><th>Wallet ID</th><th>TX</th><th>Wpływy</th><th>Wypływy</th><th>Tokeny</th></tr></thead><tbody>{rows}</tbody></table>'

        if phones:
            rows = ""
            for p in phones:
                ctx_text = ""
                if p.get("contexts"):
                    c0 = p["contexts"][0]
                    ctx_text = f"{c0.get('tx_type', '')} {c0.get('token', '')} {c0.get('timestamp', '')} (pole: {c0.get('field', '')})"
                rows += f"<tr><td style='font-family:monospace;font-weight:600'>{_resc(p['number'])}</td><td>{_resc(p.get('country_name', ''))}</td><td>{_resc(p.get('country_iso', ''))}</td><td>{p.get('occurrences', 0)}</td><td style='font-size:11px'>{_resc(ctx_text)}</td></tr>"
            ct_html += f'<h3>Zidentyfikowane numery telefonów</h3><table class="data-table"><thead><tr><th>Numer</th><th>Kraj</th><th>ISO</th><th>Wystąpienia</th><th>Kontekst</th></tr></thead><tbody>{rows}</tbody></table>'

        sections.append(f"<h2>{sn}. Kontrahenci i transfery</h2>{ct_html}")

    # ── VII. Adresy on-chain ──
    ext_src = fr.get("external_source_addresses", [])
    ext_dst = fr.get("external_dest_addresses", [])
    wallets = r.get("wallets", [])
    dep_addrs = bs.get("deposit_addresses", [])
    if ext_src or ext_dst or wallets or dep_addrs:
        sn += 1
        addr_html = ""

        if dep_addrs:
            rows = "".join(f"<tr><td><code style='word-break:break-all'>{_resc(a['address'])}</code></td><td>{_resc(a.get('chain', ''))}</td><td>{_resc(', '.join(a.get('tokens', [])))}</td></tr>" for a in dep_addrs[:50])
            addr_html += f'<h3>Adresy depozytowe (portfele użytkownika)</h3><table class="data-table"><thead><tr><th>Adres</th><th>Sieć</th><th>Tokeny</th></tr></thead><tbody>{rows}</tbody></table>'

        # Merge external source + dest addresses (deduplicate)
        if ext_src or ext_dst:
            addr_merged: Dict[str, Dict[str, Any]] = {}
            for a in ext_src:
                addr_merged[a["address"]] = {
                    "dep_count": a["count"], "dep_total": a["total"],
                    "wd_count": 0, "wd_total": 0.0,
                    "tokens": set(a.get("tokens", [])),
                    "networks": set(a.get("networks", [])),
                }
            for a in ext_dst:
                if a["address"] in addr_merged:
                    m = addr_merged[a["address"]]
                    m["wd_count"] = a["count"]
                    m["wd_total"] = a["total"]
                    m["tokens"].update(a.get("tokens", []))
                    m["networks"].update(a.get("networks", []))
                else:
                    addr_merged[a["address"]] = {
                        "dep_count": 0, "dep_total": 0.0,
                        "wd_count": a["count"], "wd_total": a["total"],
                        "tokens": set(a.get("tokens", [])),
                        "networks": set(a.get("networks", [])),
                    }
            sorted_addrs = sorted(addr_merged.items(),
                                  key=lambda x: x[1]["dep_total"] + x[1]["wd_total"], reverse=True)
            rows = ""
            for addr, m in sorted_addrs[:60]:
                direction = "dep+wd" if m["dep_count"] > 0 and m["wd_count"] > 0 else ("dep" if m["dep_count"] > 0 else "wd")
                dir_label = {"dep+wd": "&#x1F4E5;&#x1F4E4;", "dep": "&#x1F4E5;", "wd": "&#x1F4E4;"}[direction]
                dc = m["dep_count"] or "—"
                dt = f"{m['dep_total']:.4f}" if m["dep_count"] else "—"
                wc = m["wd_count"] or "—"
                wt = f"{m['wd_total']:.4f}" if m["wd_count"] else "—"
                rows += f"<tr><td><code style='word-break:break-all'>{_resc(addr)}</code></td><td style='text-align:center'>{dir_label}</td><td>{dc}</td><td class='num'>{dt}</td><td>{wc}</td><td class='num'>{wt}</td><td>{_resc(', '.join(sorted(m['tokens'])))}</td><td>{_resc(', '.join(sorted(m['networks'])))}</td></tr>"
            both_count = sum(1 for _, m in sorted_addrs if m["dep_count"] > 0 and m["wd_count"] > 0)
            note = f" (w tym <b>{both_count}</b> dwukierunkowych)" if both_count else ""
            addr_html += f'<h3>Adresy zewnętrzne ({len(sorted_addrs)} unikalnych{note})</h3><table class="data-table"><thead><tr><th>Adres</th><th>Kier.</th><th>Dep.TX</th><th>Dep.suma</th><th>Wyp.TX</th><th>Wyp.suma</th><th>Tokeny</th><th>Sieci</th></tr></thead><tbody>{rows}</tbody></table>'

        if wallets:
            rows = "".join(f"<tr><td><code style='word-break:break-all'>{_resc(w['address'])}</code></td><td>{_resc(w.get('label', ''))}</td><td>{w.get('tx_count', 0)}</td><td class='num'>{w.get('total_received', 0):.4f}</td><td class='num'>{w.get('total_sent', 0):.4f}</td><td>{_resc(w.get('risk_level', ''))}</td></tr>" for w in wallets[:100])
            addr_html += f'<h3>Portfele</h3><table class="data-table"><thead><tr><th>Adres</th><th>Etykieta</th><th>TX</th><th>Otrzymane</th><th>Wysłane</th><th>Ryzyko</th></tr></thead><tbody>{rows}</tbody></table>'

        sections.append(f"<h2>{sn}. Adresy on-chain</h2>{addr_html}")

    # ── VIII. Analiza kryminalistyczna ──
    pts = fr.get("pass_through_detection", [])
    priv = fr.get("privacy_coin_usage", {})
    mining = fr.get("mining_patterns", [])
    margin = fr.get("margin_analysis", {})
    if pts or priv or mining or margin:
        sn += 1
        forens_html = ""

        if pts:
            pt_count = fr.get("pass_through_count", len(pts))
            rows = "".join(
                f"<tr><td>{_resc(p['deposit_time'][:16])}</td><td class='num'>{p['deposit_amount']:.4f}</td><td>{_resc(p['deposit_token'])}</td><td>{_resc(p.get('deposit_from', ''))}</td>"
                f"<td>{_resc(p['withdrawal_time'][:16])}</td><td class='num'>{p['withdrawal_amount']:.4f}</td><td>{_resc(p['withdrawal_token'])}</td><td>{_resc(p.get('withdrawal_to', ''))}</td>"
                f"<td>{p['delay_hours']}h</td></tr>"
                for p in pts[:30]
            )
            forens_html += f'<h3>Przeloty tranzytowe (pass-through)</h3><p>Wykryto {pt_count} potencjalnych przepływów (depozyt → wypłata w ciągu 24h).</p><table class="data-table"><thead><tr><th>Dep. czas</th><th>Dep. kwota</th><th>Token</th><th>Od</th><th>Wyp. czas</th><th>Wyp. kwota</th><th>Token</th><th>Do</th><th>Opóźn.</th></tr></thead><tbody>{rows}</tbody></table>'

        if priv:
            rows = ""
            for coin, p in priv.items():
                rows += f"<tr><td style='color:#f59e0b;font-weight:bold'>{_resc(coin)}</td><td>{p.get('deposits', 0)}</td><td class='num'>{p.get('deposit_amount', 0):.4f}</td><td>{p.get('withdrawals', 0)}</td><td class='num'>{p.get('withdrawal_amount', 0):.4f}</td><td>{p.get('trades', 0)}</td><td>{p.get('unique_source_addresses', 0)}</td></tr>"
            forens_html += f'<h3>Kryptowaluty prywatności</h3><table class="data-table"><thead><tr><th>Moneta</th><th>Dep.</th><th>Kwota dep.</th><th>Wyp.</th><th>Kwota wyp.</th><th>Transakcje</th><th>Unik. adresy</th></tr></thead><tbody>{rows}</tbody></table>'

        if mining:
            rows = "".join(f"<tr><td><code style='word-break:break-all'>{_resc(m['address'])}</code></td><td>{_resc(m['token'])}</td><td>{m['count']}</td><td class='num'>{m['total']:.8f}</td><td class='num'>{m['avg']:.8f}</td></tr>" for m in mining[:30])
            forens_html += f'<h3>Wzorce górnicze</h3><table class="data-table"><thead><tr><th>Adres</th><th>Token</th><th>TX</th><th>Suma</th><th>Średnia</th></tr></thead><tbody>{rows}</tbody></table>'

        if margin and margin.get("total_orders"):
            forens_html += f'<h3>Handel z dźwignią (margin)</h3><table class="info-table">'
            for lbl, val in [("User IDs", ", ".join(margin.get("user_ids", []))),
                             ("Łącznie zleceń", margin.get("total_orders")),
                             ("Zrealizowane", margin.get("filled_orders")),
                             ("Anulowane", margin.get("cancelled_orders")),
                             ("Kupno", margin.get("buy_count")),
                             ("Sprzedaż", margin.get("sell_count"))]:
                if val:
                    forens_html += f"<tr><th>{_resc(lbl)}</th><td>{_resc(str(val))}</td></tr>"
            forens_html += "</table>"
            if margin.get("top_markets"):
                mk = "".join(f"<tr><td>{_resc(m)}</td><td>{c}</td></tr>" for m, c in margin["top_markets"].items())
                forens_html += f'<h4>Top rynki margin</h4><table class="data-table"><thead><tr><th>Rynek</th><th>Zlecenia</th></tr></thead><tbody>{mk}</tbody></table>'

        sections.append(f"<h2>{sn}. Analiza kryminalistyczna</h2>{forens_html}")

    # ── IX. Bezpieczeństwo konta ──
    al = fr.get("access_log_analysis", {})
    devs = fr.get("device_fingerprints", [])
    cards = fr.get("card_info", [])
    card_tl = fr.get("card_geo_timeline", [])
    if al.get("total_entries") or devs or cards or card_tl:
        sn += 1
        sec_html = ""

        if al.get("total_entries"):
            sec_html += f'<h3>Logi dostępu</h3><p>Łącznie wpisów: <b>{al["total_entries"]}</b>, unikalne IP: <b>{al.get("unique_ips", 0)}</b>, okres: {_resc(al.get("first_login", "")[:10])} — {_resc(al.get("last_login", "")[:10])}</p>'
            if al.get("foreign_login_count"):
                sec_html += f'<p style="color:#dc2626"><b>Zagraniczne loginy: {al["foreign_login_count"]}</b> (poza {_resc(al.get("primary_country", "?"))})</p>'
            geos = al.get("geolocations", {})
            if geos:
                rows = "".join(f"<tr><td>{_resc(g)}</td><td>{c}</td></tr>" for g, c in list(geos.items())[:20])
                sec_html += f'<h4>Geolokalizacje</h4><table class="data-table"><thead><tr><th>Lokalizacja</th><th>Loginy</th></tr></thead><tbody>{rows}</tbody></table>'
            ips = al.get("top_ips", {})
            if ips:
                rows = "".join(f"<tr><td><code>{_resc(ip)}</code></td><td>{c}</td></tr>" for ip, c in list(ips.items())[:15])
                sec_html += f'<h4>Najczęstsze IP</h4><table class="data-table"><thead><tr><th>IP</th><th>Loginy</th></tr></thead><tbody>{rows}</tbody></table>'

        if devs:
            rows = "".join(f"<tr><td>{_resc(d.get('device', ''))}</td><td>{_resc(d.get('client', ''))}</td><td><code>{_resc(d.get('ip', ''))}</code></td><td>{_resc(d.get('geo', ''))}</td><td>{_resc((d.get('last_used', '') or '')[:10])}</td><td>{_resc(d.get('status', ''))}</td></tr>" for d in devs)
            sec_html += f'<h3>Zatwierdzone urządzenia</h3><table class="data-table"><thead><tr><th>Urządzenie</th><th>Klient</th><th>IP</th><th>Geo</th><th>Ostatnie użycie</th><th>Status</th></tr></thead><tbody>{rows}</tbody></table>'

        if cards:
            rows = "".join(f"<tr><td><code>{_resc(c.get('card_number', ''))}</code></td><td>{_resc(c.get('card_type', ''))}</td><td>{_resc(c.get('status', ''))}</td><td>{_resc((c.get('created', '') or '')[:10])}</td></tr>" for c in cards)
            sec_html += f'<h3>Karty Binance</h3><table class="data-table"><thead><tr><th>Numer</th><th>Typ</th><th>Status</th><th>Utworzono</th></tr></thead><tbody>{rows}</tbody></table>'

        card_spending = bs.get("card_spending", {})
        card_merchants = bs.get("card_merchants", {})
        if card_spending:
            sec_html += '<h4>Wydatki kartą</h4><p>' + ", ".join(f"{_resc(k)}: <b>{v:.2f}</b>" for k, v in card_spending.items()) + '</p>'
        if card_merchants:
            rows = "".join(f"<tr><td>{_resc(m)}</td><td class='num'>{v:.2f}</td></tr>" for m, v in sorted(card_merchants.items(), key=lambda x: x[1], reverse=True)[:20])
            sec_html += f'<h4>Merchants</h4><table class="data-table"><thead><tr><th>Merchant</th><th>Kwota</th></tr></thead><tbody>{rows}</tbody></table>'

        if card_tl:
            rows = "".join(f"<tr><td>{_resc(t.get('timestamp', '')[:16])}</td><td>{_resc(t.get('merchant', ''))}</td><td class='num'>{t.get('amount', 0):.2f}</td><td>{_resc(t.get('currency', ''))}</td><td>{_resc(t.get('status', ''))}</td></tr>" for t in card_tl[:50])
            sec_html += f'<h3>Oś czasu transakcji kartą</h3><table class="data-table"><thead><tr><th>Data</th><th>Merchant</th><th>Kwota</th><th>Waluta</th><th>Status</th></tr></thead><tbody>{rows}</tbody></table>'

        sections.append(f"<h2>{sn}. Bezpieczeństwo konta</h2>{sec_html}")

    # ── X. Transakcje ──
    txs = r.get("transactions", [])
    if txs:
        sn += 1
        rows = ""
        for tx in txs[:500]:
            rs = tx.get("risk_score", 0) or 0
            risk_style = f"color:#dc2626;font-weight:bold" if rs >= 50 else ""
            to_addr = tx.get("counterparty", "") or tx.get("to", "") or ""
            from_addr = tx.get("from", "") or ""
            rows += f"<tr><td>{_resc((tx.get('timestamp', '') or '')[:16])}</td><td>{_resc(tx.get('tx_type', ''))}</td><td>{_resc(tx.get('token', ''))}</td><td class='num'>{tx.get('amount', 0):.4f}</td><td style='word-break:break-all;font-size:10px'>{_resc(from_addr)}</td><td style='word-break:break-all;font-size:10px'>{_resc(to_addr)}</td><td style='{risk_style}'>{rs:.0f}</td><td>{_resc(', '.join(tx.get('risk_tags', [])))}</td></tr>"
        total = r.get("transactions_total", len(txs))
        note = f'<p class="muted">Wyświetlono {min(len(txs), 500)} z {total} transakcji.</p>' if total > 500 else ""
        sections.append(f'<h2>{sn}. Transakcje</h2><table class="data-table"><thead><tr><th>Data</th><th>Typ</th><th>Token</th><th>Kwota</th><th>Od</th><th>Do/Kontrahent</th><th>Ryzyko</th><th>Tagi</th></tr></thead><tbody>{rows}</tbody></table>{note}')

    body = "\n".join(sections)

    return f"""<!DOCTYPE html>
<html lang="pl">
<head>
<meta charset="utf-8">
<title>Raport Crypto — {_resc(filename)}</title>
<style>
body {{ font-family: 'Segoe UI', Tahoma, sans-serif; max-width: 1100px; margin: 0 auto; padding: 20px; color: #1e293b; font-size: 14px; }}
h1 {{ border-bottom: 3px solid #2563eb; padding-bottom: 8px; color: #1e293b; }}
h2 {{ color: #2563eb; border-bottom: 1px solid #e2e8f0; padding-bottom: 4px; margin-top: 32px; page-break-after: avoid; }}
h3 {{ color: #475569; margin-top: 20px; page-break-after: avoid; }}
h4 {{ color: #64748b; margin-top: 14px; }}
.info-table {{ border-collapse: collapse; margin: 12px 0; }}
.info-table th {{ text-align: left; padding: 6px 16px 6px 0; color: #64748b; font-weight: 600; white-space: nowrap; }}
.info-table td {{ padding: 6px 0; }}
.data-table {{ border-collapse: collapse; width: 100%; margin: 8px 0; font-size: 12px; }}
.data-table th {{ background: #f1f5f9; padding: 6px 8px; text-align: left; border: 1px solid #e2e8f0; font-weight: 600; }}
.data-table td {{ padding: 5px 8px; border: 1px solid #e2e8f0; }}
.data-table .num {{ text-align: right; font-variant-numeric: tabular-nums; }}
.data-table tr:nth-child(even) {{ background: #f8fafc; }}
code {{ background: #f1f5f9; padding: 1px 4px; border-radius: 3px; font-size: 11px; word-break: break-all; }}
.muted {{ color: #94a3b8; font-size: 12px; }}
.profile-card {{ padding: 10px 14px; margin: 8px 0; background: #f8fafc; border-radius: 6px; }}
.profile-card .desc {{ color: #64748b; font-size: 12px; margin-top: 2px; }}
.profile-card ul {{ margin: 6px 0 0; padding-left: 18px; font-size: 12px; }}
.footer {{ margin-top: 40px; padding-top: 12px; border-top: 1px solid #e2e8f0; color: #94a3b8; font-size: 11px; text-align: center; }}
@media print {{ body {{ font-size: 11px; }} h1 {{ font-size: 18px; }} h2 {{ font-size: 15px; break-inside: avoid; }} table {{ break-inside: auto; }} tr {{ break-inside: avoid; }} }}
</style>
</head>
<body>
<h1>Raport analizy kryptowalutowej</h1>
{body}
<div class="footer">
Wygenerowano: {now} &middot; AISTATE Crypto Analysis Module &middot; Plik: {_resc(filename)}
</div>
</body>
</html>"""


def _build_crypto_report_txt(r: Dict[str, Any]) -> str:
    """Build a plain-text report from crypto analysis results."""
    from datetime import datetime

    lines = []
    lines.append("=" * 70)
    lines.append("RAPORT ANALIZY KRYPTOWALUTOWEJ")
    lines.append("=" * 70)
    lines.append(f"Data wygenerowania: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append("")

    # Identification
    fr = r.get("forensic_report", {}) or {}
    ai = fr.get("account_info", {}) or {}
    em = r.get("exchange_meta", {}) or {}
    bs = r.get("binance_summary", {}) or {}

    lines.append("--- IDENTYFIKACJA ---")
    for label, val in [("Właściciel", ai.get("holder_name")), ("User ID", ai.get("user_id")),
                        ("Email", ai.get("email")), ("Telefon", ai.get("phone")),
                        ("Platforma", em.get("exchange_name", r.get("source", ""))),
                        ("Plik", r.get("filename"))]:
        if val:
            lines.append(f"  {label}: {val}")
    lines.append("")

    # Summary
    lines.append("--- PODSUMOWANIE ---")
    lines.append(f"  Okres: {(r.get('date_from', '') or '')[:10]} — {(r.get('date_to', '') or '')[:10]}")
    lines.append(f"  Transakcje: {r.get('tx_count', 0)}")
    lines.append(f"  Ryzyko AML: {r.get('risk_score', 0):.1f}/100")
    lines.append("")

    # Behavior
    bp = r.get("behavior_profile", {})
    if bp and bp.get("profiles"):
        lines.append("--- PROFIL ZACHOWANIA ---")
        for p in bp["profiles"][:3]:
            if p["score"] < 15:
                continue
            lines.append(f"  {p.get('icon', '')} {p['label']} — {p['score']}%")
            for rr in p.get("reasons", []):
                lines.append(f"    - {rr}")
        lines.append("")

    # Risk
    risk_reasons = r.get("risk_reasons", [])
    if risk_reasons:
        lines.append("--- CZYNNIKI RYZYKA ---")
        for rr in risk_reasons:
            lines.append(f"  - {rr}")
        lines.append("")

    # Tokens
    tokens = r.get("tokens", {})
    if tokens:
        lines.append("--- PORTFEL TOKENÓW ---")
        lines.append(f"  {'Token':<10} {'Wpływy':>14} {'Wypływy':>14} {'Saldo':>14} {'TX':>6}")
        for tok, s in sorted(tokens.items(), key=lambda x: x[1].get("count", 0), reverse=True):
            net = (s.get("received", 0) or 0) - (s.get("sent", 0) or 0)
            lines.append(f"  {tok:<10} {s.get('received', 0):>14.4f} {s.get('sent', 0):>14.4f} {net:>14.4f} {s.get('count', 0):>6}")
        lines.append("")

    # Phone numbers
    phones = r.get("detected_phones", [])
    if phones:
        lines.append("--- ZIDENTYFIKOWANE NUMERY TELEFONÓW ---")
        for p in phones:
            lines.append(f"  {p['number']:<18} {p.get('country_name', '?'):<20} ({p.get('country_iso', '?')}) x{p.get('occurrences', 0)}")
        lines.append("")

    # Counterparties
    cps = bs.get("counterparties", {})
    if cps:
        lines.append("--- KONTRAHENCI ---")
        for uid, c in sorted(cps.items(), key=lambda x: x[1].get("tx_count", 0), reverse=True)[:30]:
            lines.append(f"  UID: {uid}  TX: {c.get('tx_count', 0)}  IN: {c.get('total_in', 0):.4f}  OUT: {c.get('total_out', 0):.4f}  Tokeny: {', '.join(c.get('tokens', []))}")
        lines.append("")

    # Addresses — merged, deduplicated
    ext_src = fr.get("external_source_addresses", [])
    ext_dst = fr.get("external_dest_addresses", [])
    if ext_src or ext_dst:
        addr_m: Dict[str, Dict[str, Any]] = {}
        for a in ext_src:
            addr_m[a["address"]] = {"dc": a["count"], "dt": a["total"], "wc": 0, "wt": 0.0, "tok": set(a.get("tokens", []))}
        for a in ext_dst:
            if a["address"] in addr_m:
                addr_m[a["address"]]["wc"] = a["count"]
                addr_m[a["address"]]["wt"] = a["total"]
                addr_m[a["address"]]["tok"].update(a.get("tokens", []))
            else:
                addr_m[a["address"]] = {"dc": 0, "dt": 0.0, "wc": a["count"], "wt": a["total"], "tok": set(a.get("tokens", []))}
        lines.append("--- ADRESY ZEWNĘTRZNE (zjednoczone) ---")
        for addr, m in sorted(addr_m.items(), key=lambda x: x[1]["dt"] + x[1]["wt"], reverse=True)[:40]:
            d = "DEP+WD" if m["dc"] > 0 and m["wc"] > 0 else ("DEP" if m["dc"] > 0 else "WD")
            lines.append(f"  {addr}")
            lines.append(f"    Kier: {d}  Dep TX: {m['dc']}  Dep suma: {m['dt']:.4f}  Wyp TX: {m['wc']}  Wyp suma: {m['wt']:.4f}  Tokeny: {', '.join(sorted(m['tok']))}")
        lines.append("")

    # Transactions
    txs = r.get("transactions", [])
    if txs:
        lines.append(f"--- TRANSAKCJE (próbka {min(len(txs), 200)}/{r.get('transactions_total', len(txs))}) ---")
        for tx in txs[:200]:
            ts = (tx.get("timestamp", "") or "")[:16]
            lines.append(f"  {ts}  {tx.get('tx_type', ''):<12} {tx.get('token', ''):<6} {tx.get('amount', 0):>14.4f}  {tx.get('counterparty', '') or tx.get('to', '') or ''}")
        lines.append("")

    lines.append("=" * 70)
    lines.append("Wygenerowano przez AISTATE Crypto Analysis Module")
    lines.append("=" * 70)

    return "\n".join(lines)
