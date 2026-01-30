"""Chat LLM router — conversational interface with Ollama models."""

from __future__ import annotations

import json
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

router = APIRouter(prefix="/api/chat", tags=["chat"])

# Injected at mount time from server.py
_ollama = None  # type: Any


def init(ollama_client: Any) -> None:
    """Called once from server.py to inject the shared OllamaClient."""
    global _ollama
    _ollama = ollama_client


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


@router.get("/stream")
async def api_chat_stream(request: Request) -> Any:
    """Stream a chat response via SSE."""
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

    try:
        await ollama.ensure_model(model)
        resp = await ollama.chat(model=model, messages=msgs, options={"temperature": temperature})
        content = str((resp.get("message") or {}).get("content") or "")
        return JSONResponse({"content": content, "model": model})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
