"""Crypto transaction analysis API router.

Endpoints:
- POST /api/crypto/analyze        — upload CSV/JSON file and run full pipeline
- GET  /api/crypto/detail         — get saved analysis detail for project
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
from fastapi.responses import JSONResponse
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
    """Upload a crypto CSV/JSON file and run the full analysis pipeline."""
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
