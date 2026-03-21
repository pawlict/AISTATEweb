"""ARIA HUD — Analytical Response & Intelligence Assistant.

FastAPI router providing:
- POST /api/aria/chat      — LLM chat via Ollama (JSON response)
- POST /api/aria/chat/stream — LLM chat via Ollama (SSE streaming)
- POST /api/aria/tts        — Text-to-speech via Piper CLI
- GET  /api/aria/status     — Subsystem health check
"""

from __future__ import annotations

import asyncio
import json
import re
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

router = APIRouter(prefix="/api/aria", tags=["aria"])

# ---------------------------------------------------------------------------
# Globals (injected via init())
# ---------------------------------------------------------------------------
_ollama = None          # OllamaClient
_app_log = None         # app_log function
_settings_fn = None     # get_settings callable
_manual_text: str = ""  # cached manual text

# ---------------------------------------------------------------------------
# System prompt — ARIA persona + full AISTATEweb manual
# ---------------------------------------------------------------------------

ARIA_PERSONA = """
Jesteś A.R.I.A. (Analytical Response & Intelligence Assistant) — wbudowanym asystentem
analitycznym platformy AISTATEweb (AI S.T.A.T.E. = Artificial Intelligence
Speech-To-Analysis-Translation Engine).

Twój charakter:
- Precyzyjny analityk — zwięzłe, rzeczowe odpowiedzi (max 4 zdania lub lista 5 punktów)
- Odpowiadaj TYLKO po polsku
- Masz świadomość kontekstu: wiesz w jakim module pracuje użytkownik i jaki plik przetwarza
- Jeśli pytanie dotyczy obsługi programu, odpowiadaj na podstawie poniższej instrukcji
- Jeśli pytanie jest poza zakresem AISTATEweb, grzecznie skieruj z powrotem do tematu
- Styl: profesjonalny, bez zbędnych uprzejmości, jak briefing analityczny
""".strip()

# TTS cache directory (reuse the existing tts_worker cache)
_TTS_CACHE_DIR = Path(__file__).resolve().parents[1].parent / "backend" / "models_cache" / "tts"
_PIPER_VOICES_DIR = _TTS_CACHE_DIR / "piper_voices"

# Default voice for ARIA
ARIA_VOICE = "pl_PL-gosia-medium"


def init(
    *,
    ollama_client: Any = None,
    app_log_fn: Any = None,
    get_settings: Any = None,
) -> None:
    global _ollama, _app_log, _settings_fn, _manual_text
    _ollama = ollama_client
    _app_log = app_log_fn
    _settings_fn = get_settings
    # Load the user manual once at startup
    _manual_text = _load_manual()


def _log(msg: str) -> None:
    if _app_log:
        _app_log(msg)


def _load_manual() -> str:
    """Load the AISTATEweb user manual (PL) from static files."""
    manual_path = Path(__file__).resolve().parents[1] / "static" / "info_manual_pl.md"
    try:
        text = manual_path.read_text(encoding="utf-8")
        # Strip HTML color spans to reduce tokens — keep text content only
        text = re.sub(r'<span[^>]*>', '', text)
        text = re.sub(r'</span>', '', text)
        return text.strip()
    except Exception as e:
        _log(f"ARIA: failed to load manual: {e}")
        return ""


def _build_system_prompt(context: Dict[str, Any]) -> str:
    """Build the full system prompt with persona + manual + current context."""
    parts = [ARIA_PERSONA]

    # Inject full manual
    if _manual_text:
        parts.append("\n\n--- INSTRUKCJA OBSŁUGI AISTATEWEB (używaj do odpowiedzi na pytania użytkownika) ---\n")
        parts.append(_manual_text)
        parts.append("\n--- KONIEC INSTRUKCJI ---")

    # Inject current page context
    ctx_lines = []
    if context.get("module"):
        ctx_lines.append(f"Aktywny moduł: {context['module']}")
    if context.get("filename"):
        ctx_lines.append(f"Plik: {context['filename']}")
    if context.get("speakers"):
        ctx_lines.append(f"Wykryci mówcy: {context['speakers']}")
    if context.get("segments"):
        ctx_lines.append(f"Segmenty: {context['segments']}")

    if ctx_lines:
        parts.append("\n\nAktualny kontekst użytkownika:\n" + "\n".join(ctx_lines))

    return "\n".join(parts)


def _get_model() -> str:
    """Get the LLM model to use for ARIA.

    Uses a dedicated aria_model setting (defaults to mistral:7b-instruct).
    This is separate from the main analysis model so ARIA can use a smaller,
    faster model while heavy models handle transcription/analysis.
    """
    model = "qwen2.5:3b"
    if _settings_fn:
        try:
            s = _settings_fn()
            # Use dedicated ARIA model if set, otherwise fall back to quick_model
            aria_model = getattr(s, "aria_model", None)
            if aria_model:
                model = aria_model
            elif hasattr(s, "ollama_model_quick") and s.ollama_model_quick:
                model = s.ollama_model_quick
        except Exception:
            pass
    return model


def _build_ollama_messages(
    system_prompt: str,
    user_messages: List[Dict[str, str]],
) -> List[Dict[str, str]]:
    """Build the Ollama messages list."""
    msgs: List[Dict[str, str]] = [
        {"role": "system", "content": system_prompt}
    ]
    # Add user conversation history (last 20 messages)
    for msg in user_messages[-20:]:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if role in ("user", "assistant") and content:
            msgs.append({"role": role, "content": content})
    return msgs


# ---------------------------------------------------------------------------
# Chat endpoint (non-streaming, JSON response)
# ---------------------------------------------------------------------------

@router.post("/chat")
async def aria_chat(request: Request) -> JSONResponse:
    """Chat with ARIA using Ollama LLM — full response."""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    user_messages: List[Dict[str, str]] = body.get("messages", [])
    context: Dict[str, Any] = body.get("context", {})
    session_id: str = body.get("session_id") or str(uuid.uuid4())[:8].upper()

    if not user_messages:
        return JSONResponse({"error": "No messages provided"}, status_code=400)

    if _ollama is None:
        return JSONResponse({"error": "Ollama not available"}, status_code=503)

    system_prompt = _build_system_prompt(context)
    ollama_messages = _build_ollama_messages(system_prompt, user_messages)
    model = _get_model()

    try:
        # Force CPU inference: num_gpu=0 to avoid competing with Whisper/pyannote
        result = await _ollama.chat(
            model, ollama_messages,
            options={"num_predict": 400},
        )
        reply = (result.get("message") or {}).get("content", "")
        if not reply:
            reply = "Brak odpowiedzi z modelu. Sprawdź, czy Ollama działa i model jest załadowany."

        return JSONResponse({
            "reply": reply,
            "session_id": session_id,
            "model": model,
        })
    except Exception as e:
        _log(f"ARIA chat error: {e}")
        return JSONResponse({
            "reply": f"Błąd komunikacji z modelem: {str(e)[:200]}",
            "session_id": session_id,
            "error": True,
        })


# ---------------------------------------------------------------------------
# Streaming chat endpoint (SSE)
# ---------------------------------------------------------------------------

@router.post("/chat/stream")
async def aria_chat_stream(request: Request) -> StreamingResponse:
    """Chat with ARIA using Ollama LLM — Server-Sent Events streaming."""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    user_messages: List[Dict[str, str]] = body.get("messages", [])
    context: Dict[str, Any] = body.get("context", {})
    session_id: str = body.get("session_id") or str(uuid.uuid4())[:8].upper()

    if not user_messages:
        return JSONResponse({"error": "No messages provided"}, status_code=400)

    if _ollama is None:
        return JSONResponse({"error": "Ollama not available"}, status_code=503)

    system_prompt = _build_system_prompt(context)
    ollama_messages = _build_ollama_messages(system_prompt, user_messages)
    model = _get_model()

    async def event_generator() -> AsyncGenerator[str, None]:
        try:
            # Force CPU inference: num_gpu=0
            async for chunk in _ollama.stream_chat(
                model, ollama_messages,
                options={"num_predict": 400},
            ):
                data = json.dumps({"token": chunk, "session_id": session_id, "model": model})
                yield f"data: {data}\n\n"
            # End signal
            yield f"data: {json.dumps({'done': True, 'session_id': session_id, 'model': model})}\n\n"
        except Exception as e:
            _log(f"ARIA stream error: {e}")
            error_data = json.dumps({"error": str(e)[:200], "session_id": session_id})
            yield f"data: {error_data}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# TTS endpoint (Piper CLI)
# ---------------------------------------------------------------------------

def _find_piper_exe() -> Optional[str]:
    """Find the piper executable."""
    exe = shutil.which("piper")
    if exe:
        return exe
    # Try venv bin directory
    import sys
    venv_piper = Path(sys.executable).parent / "piper"
    if venv_piper.exists():
        return str(venv_piper)
    return None


def _piper_synthesize_sync(text: str, voice: str = ARIA_VOICE, speed: float = 1.0) -> Optional[bytes]:
    """Synthesize text to WAV bytes using Piper CLI (blocking)."""
    piper_exe = _find_piper_exe()
    if not piper_exe:
        return None

    onnx_path = _PIPER_VOICES_DIR / f"{voice}.onnx"
    if not onnx_path.exists():
        return None

    # Truncate long text for TTS (max ~300 chars, up to 2 sentences)
    tts_text = text
    if len(tts_text) > 300:
        # Try to cut at sentence boundary
        for sep in [". ", "! ", "? ", ".\n"]:
            idx = tts_text.find(sep, 80)
            if 80 < idx < 300:
                tts_text = tts_text[:idx + 1]
                break
        else:
            tts_text = tts_text[:300]

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        cmd = [piper_exe, "--model", str(onnx_path), "--output_file", tmp_path]
        if speed != 1.0:
            cmd.extend(["--length-scale", str(round(1.0 / speed, 2))])

        result = subprocess.run(
            cmd,
            input=tts_text,
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode != 0:
            return None

        out = Path(tmp_path)
        if not out.exists() or out.stat().st_size < 50:
            return None

        return out.read_bytes()
    except Exception:
        return None
    finally:
        try:
            Path(tmp_path).unlink(missing_ok=True)
        except Exception:
            pass


@router.post("/tts")
async def aria_tts(request: Request) -> Response:
    """Generate TTS audio from text using Piper."""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    text = body.get("text", "").strip()
    speed = body.get("speed", 1.0)

    if not text:
        return JSONResponse({"error": "No text provided"}, status_code=400)

    # Use admin-configured voice
    voice = ARIA_VOICE
    if _settings_fn:
        try:
            s = _settings_fn()
            voice = getattr(s, "aria_voice", ARIA_VOICE) or ARIA_VOICE
        except Exception:
            pass

    wav_bytes = await asyncio.to_thread(_piper_synthesize_sync, text, voice, speed)

    if wav_bytes is None:
        return JSONResponse(
            {"error": "TTS unavailable — Piper not installed or voice model missing"},
            status_code=503,
        )

    return Response(content=wav_bytes, media_type="audio/wav")


# ---------------------------------------------------------------------------
# Status endpoint
# ---------------------------------------------------------------------------

@router.get("/status")
async def aria_status() -> JSONResponse:
    """Check ARIA subsystem status."""
    piper_ok = _find_piper_exe() is not None
    voice_ok = (_PIPER_VOICES_DIR / f"{ARIA_VOICE}.onnx").exists()
    ollama_ok = _ollama is not None

    return JSONResponse({
        "ollama": ollama_ok,
        "piper_installed": piper_ok,
        "voice_model": voice_ok,
        "voice": ARIA_VOICE,
        "manual_loaded": bool(_manual_text),
        "manual_size": len(_manual_text),
    })
