"""Chat LLM router — conversational interface with Ollama models.

Background-job architecture routed through GPU Resource Manager:
  1. Client POSTs to /api/chat/send  → enqueues task in GPU RM queue
  2. GPU RM dispatches when a slot is free → runs Ollama streaming in a thread
  3. Client opens SSE  /api/chat/follow/{conv_id}  → follows chunks in real-time
  4. If the client disconnects (tab switch), the thread keeps running
  5. Client GETs  /api/chat/result/{conv_id}  → returns full content so far
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
_gpu_rm = None   # type: Any   (GPUResourceManager)
_tasks = None    # type: Any   (TaskManager)

# ---- Streaming buffer (shared between GPU RM thread and SSE follow endpoint) ----
_chat_jobs: Dict[str, Dict[str, Any]] = {}
_chat_lock = threading.Lock()
_MAX_JOBS = 200
_JOB_TTL = 600   # seconds to keep completed jobs


def init(ollama_client: Any, app_log_fn: Any = None, gpu_rm: Any = None, tasks: Any = None) -> None:
    """Called once from server.py to inject shared objects."""
    global _ollama, _app_log, _gpu_rm, _tasks
    _ollama = ollama_client
    _app_log = app_log_fn
    _gpu_rm = gpu_rm
    _tasks = tasks


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
    if len(_chat_jobs) > _MAX_JOBS:
        oldest = sorted(_chat_jobs.items(), key=lambda x: x[1].get("ts", 0))
        for cid, _ in oldest[: len(_chat_jobs) - _MAX_JOBS]:
            del _chat_jobs[cid]


# ---------- GPU RM task runner (runs in thread) ----------

def _chat_task_runner(conv_id: str, model: str, msgs: List[Dict[str, str]],
                      options: Dict[str, Any], log_cb=None, progress_cb=None) -> dict:
    """Sync task runner called by GPU RM / TaskManager thread.

    Streams Ollama chat and writes chunks to _chat_jobs buffer in real-time.
    """
    # Mark buffer as running (transition from queued → running)
    with _chat_lock:
        job = _chat_jobs.get(conv_id)
        if job:
            job["status"] = "running"

    if log_cb:
        log_cb(f"[chat] starting conv={conv_id} model={model} msgs={len(msgs)}")
    if progress_cb:
        progress_cb(5)

    ollama = _get_ollama()

    async def _stream() -> str:
        await ollama.ensure_model(model)
        content = ""
        async for chunk in ollama.stream_chat(model=model, messages=msgs, options=options):
            content += chunk
            with _chat_lock:
                job = _chat_jobs.get(conv_id)
                if job and job["status"] == "running":
                    job["content"] = content
        return content

    try:
        content = asyncio.run(_stream())
    except Exception as e:
        with _chat_lock:
            job = _chat_jobs.get(conv_id)
            if job:
                job["status"] = "error"
                job["error"] = str(e)
                job["finished_at"] = time.time()
        if log_cb:
            log_cb(f"[chat] error conv={conv_id}: {e}")
        raise

    with _chat_lock:
        job = _chat_jobs.get(conv_id)
        if job:
            job["status"] = "done"
            job["content"] = content
            job["finished_at"] = time.time()

    if progress_cb:
        progress_cb(100)
    if log_cb:
        log_cb(f"[chat] done conv={conv_id} len={len(content)}")

    return {"content": content, "model": model, "conv_id": conv_id}


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
    """Start a chat completion via GPU RM queue.  Returns immediately."""
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

    # Prepare streaming buffer
    with _chat_lock:
        _cleanup_old_jobs()
        _chat_jobs[conv_id] = {
            "status": "running",
            "content": "",
            "model": model,
            "error": None,
            "ts": time.time(),
            "finished_at": None,
            "task_id": None,
        }

    # Log
    user_preview = ""
    for m in reversed(msgs):
        if m.get("role") == "user":
            user_preview = str(m.get("content", ""))[:120]
            break
    if _app_log:
        try:
            _app_log(f"[chat] send conv={conv_id} model={model} msgs={len(msgs)} user=\"{user_preview}\"")
        except Exception:
            pass

    # Route through GPU RM if available
    task_id = None
    if _gpu_rm and _gpu_rm.enabled:
        t = _gpu_rm.enqueue_python_fn(
            "chat", conv_id, _chat_task_runner,
            conv_id, model, msgs, options,
        )
        task_id = t.task_id
        # Update buffer status to "queued" until GPU RM starts the job
        with _chat_lock:
            job = _chat_jobs.get(conv_id)
            if job:
                job["status"] = "queued"
                job["task_id"] = task_id
    elif _tasks:
        t = _tasks.start_python_fn(
            "chat", conv_id, _chat_task_runner,
            conv_id, model, msgs, options,
        )
        task_id = t.task_id
        with _chat_lock:
            job = _chat_jobs.get(conv_id)
            if job:
                job["task_id"] = task_id
    else:
        # Fallback: run directly in a thread (no queue management)
        def _run_direct():
            try:
                _chat_task_runner(conv_id, model, msgs, options)
            except Exception:
                pass
        threading.Thread(target=_run_direct, daemon=True).start()

    return JSONResponse({
        "status": "queued" if (_gpu_rm and _gpu_rm.enabled) else "started",
        "conv_id": conv_id,
        "task_id": task_id,
    })


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

            # While queued (waiting in GPU RM), just send keepalives
            if status == "queued":
                yield f"data: {json.dumps({'chunk': '', 'done': False, 'queued': True})}\n\n"
                await asyncio.sleep(0.5)
                continue

            # Emit new chunks
            if len(content) > last_len:
                new_chunk = content[last_len:]
                last_len = len(content)
                yield f"data: {json.dumps({'chunk': new_chunk, 'done': False}, ensure_ascii=False)}\n\n"

            if status == "done":
                if len(content) > last_len:
                    yield f"data: {json.dumps({'chunk': content[last_len:], 'done': False}, ensure_ascii=False)}\n\n"
                yield f"data: {json.dumps({'chunk': '', 'done': True})}\n\n"
                break
            elif status == "error":
                yield f"data: {json.dumps({'chunk': '', 'done': True, 'error': job.get('error', '')})}\n\n"
                break

            await asyncio.sleep(0.06)

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
        "task_id": job.get("task_id"),
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
