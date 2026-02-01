"""Chat LLM router — conversational interface with Ollama models.

Background-job architecture:
  1. Client POSTs to /api/chat/send  → starts async Ollama streaming in background
  2. Client opens SSE  /api/chat/follow/{conv_id}  → follows chunks in real-time
  3. If the client disconnects (tab switch), the background task keeps running
  4. Client GETs  /api/chat/result/{conv_id}  → returns full content so far
  5. Old /api/chat/stream endpoint is kept for backward compat (direct SSE).
"""

from __future__ import annotations

import asyncio
import json
import time
import threading
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

router = APIRouter(prefix="/api/chat", tags=["chat"])

# Injected at mount time from server.py
_ollama = None  # type: Any
_app_log = None  # type: Any

# ---- Background chat jobs ----
_chat_jobs: Dict[str, Dict[str, Any]] = {}
_chat_lock = threading.Lock()
_MAX_JOBS = 200  # max kept in memory
_JOB_TTL = 600   # seconds to keep completed jobs


def init(ollama_client: Any, app_log_fn: Any = None) -> None:
    """Called once from server.py to inject the shared OllamaClient."""
    global _ollama, _app_log
    _ollama = ollama_client
    _app_log = app_log_fn


def _get_ollama() -> Any:
    if _ollama is None:
        raise RuntimeError("Chat router not initialised (call init())")
    return _ollama


# ---------- helpers ----------

def _parse_messages(
    raw_messages: list,
    system_prompt: str = "",
) -> List[Dict[str, str]]:
    msgs: List[Dict[str, str]] = []
    if system_prompt:
        msgs.append({"role": "system", "content": system_prompt})
    for m in raw_messages:
        if isinstance(m, dict) and "role" in m and "content" in m:
            msgs.append({"role": str(m["role"]), "content": str(m["content"])})
    return msgs


def _cleanup_old_jobs() -> None:
    """Remove finished jobs older than _JOB_TTL (called under lock)."""
    now = time.time()
    to_remove = []
    for cid, job in _chat_jobs.items():
        if job["status"] in ("done", "error") and now - job.get("finished_at", now) > _JOB_TTL:
            to_remove.append(cid)
    for cid in to_remove:
        del _chat_jobs[cid]
    # Hard cap
    if len(_chat_jobs) > _MAX_JOBS:
        oldest = sorted(_chat_jobs.items(), key=lambda x: x[1].get("ts", 0))
        for cid, _ in oldest[: len(_chat_jobs) - _MAX_JOBS]:
            del _chat_jobs[cid]


# ---------- Background runner ----------

async def _run_chat_bg(conv_id: str, model: str, msgs: List[Dict[str, str]], options: Dict[str, Any]) -> None:
    """Async background task: streams Ollama response and buffers it."""
    ollama = _get_ollama()
    try:
        await ollama.ensure_model(model)
        async for chunk in ollama.stream_chat(model=model, messages=msgs, options=options):
            with _chat_lock:
                job = _chat_jobs.get(conv_id)
                if job and job["status"] == "running":
                    job["content"] += chunk
        with _chat_lock:
            job = _chat_jobs.get(conv_id)
            if job:
                job["status"] = "done"
                job["finished_at"] = time.time()
        if _app_log:
            try:
                _app_log(f"[chat] bg done conv={conv_id} model={model}")
            except Exception:
                pass
    except Exception as e:
        with _chat_lock:
            job = _chat_jobs.get(conv_id)
            if job:
                job["status"] = "error"
                job["error"] = str(e)
                job["finished_at"] = time.time()
        if _app_log:
            try:
                _app_log(f"[chat] bg error conv={conv_id} model={model}: {e}")
            except Exception:
                pass


# ---------- endpoints ----------

@router.get("/models")
async def api_chat_models() -> Any:
    """Return installed Ollama models available for chat."""
    ollama = _get_ollama()
    try:
        status = await ollama.status()
        if status.status != "online":
            return JSONResponse({"status": "offline", "models": []})
        models = status.models or []
        return JSONResponse({"status": "online", "models": models})
    except Exception as e:
        return JSONResponse({"status": "error", "models": [], "error": str(e)})


@router.post("/send")
async def api_chat_send(request: Request) -> Any:
    """Start a background chat completion.  Returns immediately."""
    ollama = _get_ollama()
    body = await request.json()

    conv_id = str(body.get("conv_id") or "").strip()
    if not conv_id:
        raise HTTPException(status_code=400, detail="conv_id required")

    model = str(body.get("model") or "").strip()
    if not model:
        raise HTTPException(status_code=400, detail="model required")

    messages = body.get("messages", [])
    system_prompt = str(body.get("system") or "").strip()

    try:
        temperature = float(body.get("temperature", 0.7))
    except (TypeError, ValueError):
        temperature = 0.7

    msgs = _parse_messages(messages, system_prompt)
    if not msgs:
        raise HTTPException(status_code=400, detail="No messages provided")

    options = {"temperature": temperature}

    with _chat_lock:
        _cleanup_old_jobs()
        _chat_jobs[conv_id] = {
            "status": "running",
            "content": "",
            "model": model,
            "error": None,
            "ts": time.time(),
            "finished_at": None,
        }

    # Log
    user_preview = ""
    for m in reversed(msgs):
        if m.get("role") == "user":
            user_preview = str(m.get("content", ""))[:120]
            break
    if _app_log:
        try:
            _app_log(f"[chat] bg start conv={conv_id} model={model} msgs={len(msgs)} user=\"{user_preview}\"")
        except Exception:
            pass

    # Fire-and-forget background task
    asyncio.ensure_future(_run_chat_bg(conv_id, model, msgs, options))

    return JSONResponse({"status": "started", "conv_id": conv_id})


@router.get("/follow/{conv_id}")
async def api_chat_follow(conv_id: str) -> Any:
    """SSE stream that follows a background chat job (live chunks)."""

    async def generate() -> Any:
        last_len = 0
        while True:
            with _chat_lock:
                job = _chat_jobs.get(conv_id)

            if not job:
                yield f"data: {json.dumps({'chunk': '', 'done': True, 'error': 'not_found'})}\n\n"
                break

            content = job["content"]
            status = job["status"]

            # Emit new chunks
            if len(content) > last_len:
                new_chunk = content[last_len:]
                last_len = len(content)
                yield f"data: {json.dumps({'chunk': new_chunk, 'done': False}, ensure_ascii=False)}\n\n"

            if status == "done":
                # Flush any remaining
                if len(content) > last_len:
                    yield f"data: {json.dumps({'chunk': content[last_len:], 'done': False}, ensure_ascii=False)}\n\n"
                yield f"data: {json.dumps({'chunk': '', 'done': True})}\n\n"
                break
            elif status == "error":
                yield f"data: {json.dumps({'chunk': '', 'done': True, 'error': job.get('error', '')})}\n\n"
                break

            await asyncio.sleep(0.06)  # ~16 fps polling

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.get("/result/{conv_id}")
async def api_chat_result(conv_id: str) -> Any:
    """Return current state of a background chat job (polling fallback)."""
    with _chat_lock:
        job = _chat_jobs.get(conv_id)
    if not job:
        return JSONResponse({"status": "not_found", "content": "", "error": None})
    return JSONResponse({
        "status": job["status"],
        "content": job["content"],
        "model": job.get("model", ""),
        "error": job.get("error"),
    })


# ---------- Legacy direct-stream endpoint (kept for backward compat) ----------

@router.get("/stream")
async def api_chat_stream(request: Request) -> Any:
    """Stream a chat response via SSE (direct, no background job)."""
    ollama = _get_ollama()
    qp = request.query_params
    model = str(qp.get("model") or "").strip()
    if not model:
        raise HTTPException(status_code=400, detail="model required")

    messages_raw = str(qp.get("messages") or "[]").strip()
    try:
        messages = json.loads(messages_raw)
        if not isinstance(messages, list):
            raise ValueError("messages must be a list")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid messages JSON: {e}")

    system_prompt = str(qp.get("system") or "").strip()

    try:
        temperature = float(qp.get("temperature") or 0.7)
    except (TypeError, ValueError):
        temperature = 0.7

    msgs = _parse_messages(messages, system_prompt)
    if not msgs:
        raise HTTPException(status_code=400, detail="No messages provided")

    options = {"temperature": temperature}

    async def generate() -> Any:
        try:
            await ollama.ensure_model(model)
            async for chunk in ollama.stream_chat(model=model, messages=msgs, options=options):
                payload = json.dumps({"chunk": chunk, "done": False}, ensure_ascii=False)
                yield f"data: {payload}\n\n"
            yield f"data: {json.dumps({'chunk': '', 'done': True})}\n\n"
        except Exception as e:
            err = json.dumps({"chunk": f"\n\n[ERROR] {e}", "done": True, "error": str(e)}, ensure_ascii=False)
            yield f"data: {err}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.post("/complete")
async def api_chat_complete(request: Request) -> Any:
    """Non-streaming chat completion."""
    ollama = _get_ollama()
    body = await request.json()
    model = str(body.get("model") or "").strip()
    if not model:
        raise HTTPException(status_code=400, detail="model required")

    messages = body.get("messages", [])
    system_prompt = str(body.get("system") or "").strip()

    try:
        temperature = float(body.get("temperature", 0.7))
    except (TypeError, ValueError):
        temperature = 0.7

    msgs = _parse_messages(messages, system_prompt)
    if not msgs:
        raise HTTPException(status_code=400, detail="No messages provided")

    if _app_log:
        try:
            _app_log(f"[chat] complete model={model} msgs={len(msgs)}")
        except Exception:
            pass

    try:
        await ollama.ensure_model(model)
        resp = await ollama.chat(model=model, messages=msgs, options={"temperature": temperature})
        content = str((resp.get("message") or {}).get("content") or "")
        if _app_log:
            try:
                _app_log(f"[chat] complete done model={model} len={len(content)}")
            except Exception:
                pass
        return JSONResponse({"content": content, "model": model})
    except Exception as e:
        if _app_log:
            try:
                _app_log(f"[chat] complete error model={model}: {e}")
            except Exception:
                pass
        raise HTTPException(status_code=500, detail=str(e))
