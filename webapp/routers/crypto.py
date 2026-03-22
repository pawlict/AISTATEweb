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
#  HTML Report generation
# ---------------------------------------------------------------------------

@router.get("/api/crypto/report")
async def crypto_report(project_id: str = Query("")):
    """Generate an HTML report for the project's crypto analysis."""
    if not project_id:
        return JSONResponse({"status": "error", "detail": "project_id required"}, status_code=400)

    save_path = _crypto_save_path(project_id)
    if not save_path.exists():
        return JSONResponse({"status": "error", "detail": "No saved crypto analysis"}, status_code=404)

    try:
        result = json.loads(save_path.read_text(encoding="utf-8"))
    except Exception as e:
        return JSONResponse({"status": "error", "detail": str(e)}, status_code=500)

    html = _build_crypto_report_html(result)
    return HTMLResponse(html)


def _esc(s: str) -> str:
    """HTML-escape a string."""
    return (str(s)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;"))


def _build_crypto_report_html(r: Dict[str, Any]) -> str:
    """Build a standalone HTML report from crypto analysis results."""
    from datetime import datetime

    source = r.get("source", "?")
    source_type = r.get("source_type", "?")
    filename = r.get("filename", "")
    date_from = (r.get("date_from", "") or "")[:10]
    date_to = (r.get("date_to", "") or "")[:10]
    risk_score = r.get("risk_score", 0)
    tx_count = r.get("tx_count", 0)
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    # Risk label
    if risk_score >= 70:
        risk_label, risk_color = "KRYTYCZNE", "#dc2626"
    elif risk_score >= 50:
        risk_label, risk_color = "WYSOKIE", "#f97316"
    elif risk_score >= 25:
        risk_label, risk_color = "SREDNIE", "#eab308"
    else:
        risk_label, risk_color = "NISKIE", "#22c55e"

    sections = []

    # ── 1. Header / Summary ──
    em = r.get("exchange_meta", {})
    fr = r.get("forensic_report", {})
    ai = fr.get("account_info", {}) if fr else {}

    header_rows = []
    if ai.get("holder_name"):
        header_rows.append(f"<tr><th>Właściciel</th><td>{_esc(ai['holder_name'])}</td></tr>")
    if ai.get("user_id"):
        header_rows.append(f"<tr><th>User ID</th><td>{_esc(ai['user_id'])}</td></tr>")
    if ai.get("email"):
        header_rows.append(f"<tr><th>Email</th><td>{_esc(ai['email'])}</td></tr>")
    if em.get("exchange_name") or source:
        header_rows.append(f"<tr><th>Platforma</th><td>{_esc(em.get('exchange_name', source))}</td></tr>")
    if filename:
        header_rows.append(f"<tr><th>Plik</th><td>{_esc(filename)}</td></tr>")
    if date_from or date_to:
        header_rows.append(f"<tr><th>Okres</th><td>{_esc(date_from)} — {_esc(date_to)}</td></tr>")
    header_rows.append(f"<tr><th>Transakcje</th><td>{tx_count}</td></tr>")
    header_rows.append(f"<tr><th>Ryzyko AML</th><td style='color:{risk_color};font-weight:bold'>{risk_score:.1f}/100 ({risk_label})</td></tr>")

    sections.append(f"""
    <h2>1. Podsumowanie</h2>
    <table class="info-table">{''.join(header_rows)}</table>
    """)

    # ── 2. Behavior Profile ──
    bp = r.get("behavior_profile", {})
    if bp and bp.get("profiles"):
        profiles_html = ""
        for p in bp["profiles"][:5]:
            if p["score"] < 15:
                continue
            reasons_html = ""
            if p.get("reasons"):
                reasons_html = "<ul>" + "".join(f"<li>{_esc(rr)}</li>" for rr in p["reasons"]) + "</ul>"
            profiles_html += f"""
            <div class="profile-card" style="border-left:4px solid {'#22c55e' if p['score'] >= 50 else '#eab308' if p['score'] >= 30 else '#94a3b8'}">
                <strong>{_esc(p['icon'])} {_esc(p['label'])}</strong> — {p['score']}%
                <div class="desc">{_esc(p['desc'])}</div>
                {reasons_html}
            </div>"""
        sections.append(f"""
        <h2>2. Profil zachowania użytkownika</h2>
        {profiles_html}
        """)

    # ── 3. Risk reasons ──
    risk_reasons = r.get("risk_reasons", [])
    if risk_reasons:
        items = "".join(f"<li>{_esc(rr)}</li>" for rr in risk_reasons)
        sections.append(f"""
        <h2>3. Czynniki ryzyka AML</h2>
        <ul>{items}</ul>
        """)

    # ── 4. Alerts ──
    alerts = r.get("alerts", [])
    if alerts:
        alert_items = "".join(f"<li><strong>{_esc(a.get('type', ''))}</strong>: {_esc(a.get('message', ''))}</li>" for a in alerts[:30])
        sections.append(f"""
        <h2>4. Alerty</h2>
        <ul>{alert_items}</ul>
        """)

    # ── 5. Token breakdown ──
    tokens = r.get("tokens", {})
    if tokens:
        rows = ""
        for tok, s in sorted(tokens.items(), key=lambda x: x[1].get("count", 0), reverse=True):
            net = (s.get("received", 0) or 0) - (s.get("sent", 0) or 0)
            rows += f"<tr><td>{_esc(tok)}</td><td class='num'>{s.get('received', 0):.4f}</td><td class='num'>{s.get('sent', 0):.4f}</td><td class='num'>{net:.4f}</td><td>{s.get('count', 0)}</td></tr>"
        sections.append(f"""
        <h2>5. Podział tokenów</h2>
        <table class="data-table"><thead><tr><th>Token</th><th>Wpływy</th><th>Wypływy</th><th>Saldo</th><th>TX</th></tr></thead><tbody>{rows}</tbody></table>
        """)

    # ── 6. Forensic sections (Binance XLSX) ──
    if fr:
        forensic_parts = []

        # Counterparties
        bs = r.get("binance_summary", {})
        cps = bs.get("counterparties", {})
        if cps:
            rows = ""
            for uid, c in sorted(cps.items(), key=lambda x: x[1].get("tx_count", 0), reverse=True)[:30]:
                rows += f"<tr><td><code>{_esc(uid)}</code></td><td>{c.get('tx_count', 0)}</td><td class='num'>{c.get('total_in', 0):.4f}</td><td class='num'>{c.get('total_out', 0):.4f}</td><td>{_esc(', '.join(c.get('tokens', [])))}</td></tr>"
            forensic_parts.append(f"""
            <h3>Kontrahenci wewnętrzni Binance</h3>
            <table class="data-table"><thead><tr><th>User ID</th><th>TX</th><th>Wpływy</th><th>Wypływy</th><th>Tokeny</th></tr></thead><tbody>{rows}</tbody></table>
            """)

        # External addresses
        ext_src = fr.get("external_source_addresses", [])
        ext_dst = fr.get("external_dest_addresses", [])
        if ext_src or ext_dst:
            addr_html = ""
            if ext_src:
                rows = "".join(f"<tr><td><code>{_esc(a['address'][:16])}…</code></td><td>{a['count']}</td><td class='num'>{a['total']:.4f}</td><td>{_esc(', '.join(a.get('tokens', [])))}</td></tr>" for a in ext_src[:20])
                addr_html += f"<h4>Adresy źródłowe depozytów</h4><table class='data-table'><thead><tr><th>Adres</th><th>TX</th><th>Suma</th><th>Tokeny</th></tr></thead><tbody>{rows}</tbody></table>"
            if ext_dst:
                rows = "".join(f"<tr><td><code>{_esc(a['address'][:16])}…</code></td><td>{a['count']}</td><td class='num'>{a['total']:.4f}</td><td>{_esc(', '.join(a.get('tokens', [])))}</td></tr>" for a in ext_dst[:20])
                addr_html += f"<h4>Adresy docelowe wypłat</h4><table class='data-table'><thead><tr><th>Adres</th><th>TX</th><th>Suma</th><th>Tokeny</th></tr></thead><tbody>{rows}</tbody></table>"
            forensic_parts.append(addr_html)

        # Pass-through
        pts = fr.get("pass_through_detection", [])
        if pts:
            rows = "".join(
                f"<tr><td>{_esc(p['deposit_time'][:16])}</td><td class='num'>{p['deposit_amount']:.4f}</td><td>{_esc(p['deposit_token'])}</td>"
                f"<td>{_esc(p['withdrawal_time'][:16])}</td><td class='num'>{p['withdrawal_amount']:.4f}</td><td>{_esc(p['withdrawal_token'])}</td>"
                f"<td>{p['delay_hours']}h</td></tr>"
                for p in pts[:20]
            )
            forensic_parts.append(f"""
            <h3>Wykryte przeloty (pass-through)</h3>
            <p>Znaleziono {fr.get('pass_through_count', len(pts))} potencjalnych przepływów tranzytowych.</p>
            <table class="data-table"><thead><tr><th>Dep. czas</th><th>Dep. kwota</th><th>Token</th><th>Wyp. czas</th><th>Wyp. kwota</th><th>Token</th><th>Opóźn.</th></tr></thead><tbody>{rows}</tbody></table>
            """)

        # Privacy coins
        priv = fr.get("privacy_coin_usage", {})
        if priv:
            rows = ""
            for coin, p in priv.items():
                rows += f"<tr><td style='color:#f59e0b;font-weight:bold'>{_esc(coin)}</td><td>{p.get('deposits', 0)}</td><td class='num'>{p.get('deposit_amount', 0):.4f}</td><td>{p.get('withdrawals', 0)}</td><td class='num'>{p.get('withdrawal_amount', 0):.4f}</td><td>{p.get('unique_source_addresses', 0)}</td></tr>"
            forensic_parts.append(f"""
            <h3>Kryptowaluty prywatności</h3>
            <table class="data-table"><thead><tr><th>Moneta</th><th>Depozyty</th><th>Kwota dep.</th><th>Wypłaty</th><th>Kwota wyp.</th><th>Unik. adresy</th></tr></thead><tbody>{rows}</tbody></table>
            """)

        # Access logs
        al = fr.get("access_log_analysis", {})
        if al.get("total_entries"):
            forensic_parts.append(f"""
            <h3>Logi dostępu</h3>
            <p>Łącznie wpisów: <b>{al['total_entries']}</b>, unikalne IP: <b>{al.get('unique_ips', 0)}</b>,
            okres: {_esc(al.get('first_login', '')[:10])} — {_esc(al.get('last_login', '')[:10])}</p>
            """)
            if al.get("foreign_login_count"):
                forensic_parts.append(f"<p style='color:#dc2626'><b>Zagraniczne loginy: {al['foreign_login_count']}</b></p>")

        # Card timeline
        card_tl = fr.get("card_geo_timeline", [])
        if card_tl:
            rows = "".join(
                f"<tr><td>{_esc(t.get('timestamp', '')[:16])}</td><td>{_esc(t.get('merchant', ''))}</td><td class='num'>{t.get('amount', 0):.2f}</td><td>{_esc(t.get('currency', ''))}</td></tr>"
                for t in card_tl[:30]
            )
            forensic_parts.append(f"""
            <h3>Transakcje kartą</h3>
            <table class="data-table"><thead><tr><th>Data</th><th>Merchant</th><th>Kwota</th><th>Waluta</th></tr></thead><tbody>{rows}</tbody></table>
            """)

        if forensic_parts:
            sections.append(f"<h2>6. Raport kryminalistyczny</h2>{''.join(forensic_parts)}")

    # ── 7. Transaction sample ──
    txs = r.get("transactions", [])
    if txs:
        rows = ""
        for tx in txs[:100]:
            risk_style = f"color:#dc2626;font-weight:bold" if (tx.get("risk_score", 0) or 0) >= 50 else ""
            rows += f"<tr><td>{_esc((tx.get('timestamp', '') or '')[:16])}</td><td>{_esc(tx.get('tx_type', ''))}</td><td>{_esc(tx.get('token', ''))}</td><td class='num'>{tx.get('amount', 0):.4f}</td><td>{_esc(tx.get('counterparty', '') or tx.get('to', '') or '')}</td><td style='{risk_style}'>{tx.get('risk_score', 0):.0f}</td></tr>"
        sections.append(f"""
        <h2>{'7' if fr else '6'}. Transakcje (próbka, max 100)</h2>
        <table class="data-table"><thead><tr><th>Data</th><th>Typ</th><th>Token</th><th>Kwota</th><th>Kontrahent</th><th>Ryzyko</th></tr></thead><tbody>{rows}</tbody></table>
        {'<p class="muted">Wyświetlono 100 z ' + str(r.get("transactions_total", len(txs))) + '</p>' if r.get("transactions_truncated") or len(txs) > 100 else ''}
        """)

    body = "\n".join(sections)

    return f"""<!DOCTYPE html>
<html lang="pl">
<head>
<meta charset="utf-8">
<title>Raport Crypto — {_esc(filename)}</title>
<style>
body {{ font-family: 'Segoe UI', Tahoma, sans-serif; max-width: 1000px; margin: 0 auto; padding: 20px; color: #1e293b; font-size: 14px; }}
h1 {{ border-bottom: 3px solid #2563eb; padding-bottom: 8px; color: #1e293b; }}
h2 {{ color: #2563eb; border-bottom: 1px solid #e2e8f0; padding-bottom: 4px; margin-top: 28px; }}
h3 {{ color: #475569; margin-top: 20px; }}
h4 {{ color: #64748b; margin-top: 14px; }}
.info-table {{ border-collapse: collapse; margin: 12px 0; }}
.info-table th {{ text-align: left; padding: 6px 16px 6px 0; color: #64748b; font-weight: 600; white-space: nowrap; }}
.info-table td {{ padding: 6px 0; }}
.data-table {{ border-collapse: collapse; width: 100%; margin: 8px 0; font-size: 12px; }}
.data-table th {{ background: #f1f5f9; padding: 6px 8px; text-align: left; border: 1px solid #e2e8f0; font-weight: 600; }}
.data-table td {{ padding: 5px 8px; border: 1px solid #e2e8f0; }}
.data-table .num {{ text-align: right; font-variant-numeric: tabular-nums; }}
.data-table tr:nth-child(even) {{ background: #f8fafc; }}
code {{ background: #f1f5f9; padding: 1px 4px; border-radius: 3px; font-size: 11px; }}
.muted {{ color: #94a3b8; font-size: 12px; }}
.profile-card {{ padding: 10px 14px; margin: 8px 0; background: #f8fafc; border-radius: 6px; }}
.profile-card .desc {{ color: #64748b; font-size: 12px; margin-top: 2px; }}
.profile-card ul {{ margin: 6px 0 0; padding-left: 18px; font-size: 12px; }}
.footer {{ margin-top: 40px; padding-top: 12px; border-top: 1px solid #e2e8f0; color: #94a3b8; font-size: 11px; text-align: center; }}
@media print {{ body {{ font-size: 11px; }} h1 {{ font-size: 18px; }} h2 {{ font-size: 15px; }} }}
</style>
</head>
<body>
<h1>Raport analizy kryptowalutowej</h1>
{body}
<div class="footer">
Wygenerowano: {now} &middot; AISTATE Crypto Analysis Module &middot; Plik: {_esc(filename)}
</div>
</body>
</html>"""
