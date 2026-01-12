"""Minimal async Ollama HTTP client with auto-pull.

We intentionally use Ollama's REST API directly so the server works even
without the optional `ollama` Python package.

Default base URL: http://127.0.0.1:11434
Override via env: OLLAMA_HOST or AISTATE_OLLAMA_URL
"""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from typing import Any, AsyncGenerator, Dict, List, Optional


class OllamaError(RuntimeError):
    pass


@dataclass
class OllamaStatus:
    status: str
    version: str = ""
    models: List[str] | None = None

    def to_dict(self) -> Dict[str, Any]:
        return {"status": self.status, "version": self.version, "models": self.models or []}


class OllamaClient:
    def __init__(self, base_url: Optional[str] = None) -> None:
        self.base_url = (base_url or os.environ.get("AISTATE_OLLAMA_URL") or os.environ.get("OLLAMA_HOST") or "http://127.0.0.1:11434").rstrip("/")

    # ------------- low-level HTTP (httpx preferred, stdlib fallback) -------------
    async def _request_json(self, method: str, path: str, payload: Optional[Dict[str, Any]] = None, timeout: Optional[float] = None) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        try:
            import httpx  # type: ignore

            async with httpx.AsyncClient(timeout=timeout) as client:
                r = await client.request(method, url, json=payload)
                r.raise_for_status()
                return r.json()
        except Exception as e:
            # Fallback to urllib (sync) in a thread
            return await asyncio.to_thread(self._urllib_request_json, method, url, payload, timeout, e)

    def _urllib_request_json(self, method: str, url: str, payload: Optional[Dict[str, Any]], timeout: Optional[float], first_exc: Exception) -> Dict[str, Any]:
        import urllib.request
        import urllib.error

        data = None
        headers = {"Content-Type": "application/json"}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                return json.loads(raw) if raw.strip() else {}
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", errors="replace")
            except Exception:
                pass
            raise OllamaError(f"Ollama HTTP {e.code}: {body or e.reason}")
        except Exception as e:
            raise OllamaError(f"Ollama request failed: {e} (first: {first_exc})")

    async def _stream_lines(self, path: str, payload: Dict[str, Any]) -> AsyncGenerator[Dict[str, Any], None]:
        url = f"{self.base_url}{path}"
        try:
            import httpx  # type: ignore

            async with httpx.AsyncClient(timeout=None) as client:
                async with client.stream("POST", url, json=payload) as r:
                    r.raise_for_status()
                    async for line in r.aiter_lines():
                        if not line:
                            continue
                        try:
                            yield json.loads(line)
                        except Exception:
                            continue
        except Exception as e:
            raise OllamaError(f"Ollama stream failed: {e}")

    # ------------- public API -------------
    async def status(self) -> OllamaStatus:
        try:
            v = await self._request_json("GET", "/api/version", None, timeout=2.0)
            version = str(v.get("version") or "")
            models = await self.list_model_names()
            return OllamaStatus(status="online", version=version, models=models)
        except Exception:
            return OllamaStatus(status="offline", version="", models=[])

    async def list_model_names(self) -> List[str]:
        data = await self._request_json("GET", "/api/tags", None, timeout=5.0)
        out: List[str] = []
        for m in data.get("models", []) or []:
            name = m.get("name")
            if isinstance(name, str) and name:
                out.append(name)
        return sorted(set(out))

    async def list_models(self) -> List[Dict[str, Any]]:
        """Return raw model entries from /api/tags (best-effort)."""
        data = await self._request_json("GET", "/api/tags", None, timeout=5.0)
        models = data.get("models", [])
        return models if isinstance(models, list) else []

    async def ensure_model(self, model: str) -> Dict[str, Any]:
        """Ensure a model is available locally; if not, auto-pull it.

        Returns a small dict with status and (optional) pull details.
        """
        model = (model or "").strip()
        if not model:
            raise OllamaError("Model name is empty")

        try:
            models = await self.list_model_names()
        except Exception as e:
            raise OllamaError(f"Cannot list Ollama models: {e}")

        if model in models:
            return {"status": "present", "model": model}

        # Pull missing model (may take time).
        pull_payload = {"name": model, "stream": True}
        last: Dict[str, Any] = {}
        async for obj in self._stream_lines("/api/pull", pull_payload):
            last = obj
            if obj.get("error"):
                raise OllamaError(str(obj.get("error")))
            # Ollama typically ends with {"status":"success"}
            if str(obj.get("status") or "").lower() in ("success", "done"):
                break

        return {"status": "pulled", "model": model, "last": last}

    async def chat(self, model: str, messages: List[Dict[str, str]], *, format: Optional[str] = None, options: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"model": model, "messages": messages, "stream": False}
        if format:
            payload["format"] = format
        if options:
            payload["options"] = options
        return await self._request_json("POST", "/api/chat", payload, timeout=None)

    async def stream_chat(self, model: str, messages: List[Dict[str, str]], *, options: Optional[Dict[str, Any]] = None) -> AsyncGenerator[str, None]:
        payload: Dict[str, Any] = {"model": model, "messages": messages, "stream": True}
        if options:
            payload["options"] = options
        async for obj in self._stream_lines("/api/chat", payload):
            msg = obj.get("message") or {}
            chunk = msg.get("content")
            if isinstance(chunk, str) and chunk:
                yield chunk
            if obj.get("done") is True:
                break


def _parse_json_best_effort(s: str) -> Dict[str, Any]:
    """Try to parse JSON from a model response.

    Some models may wrap JSON in text; we try to locate the first {...} block.
    """
    s = (s or "").strip()
    if not s:
        raise OllamaError("Empty JSON response")
    try:
        obj = json.loads(s)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass

    # Locate first JSON object
    start = s.find("{")
    end = s.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            obj = json.loads(s[start : end + 1])
            if isinstance(obj, dict):
                return obj
        except Exception:
            pass
    raise OllamaError("Model did not return valid JSON")


async def quick_analyze(client: OllamaClient, text: str, *, model: str = "mistral:7b-instruct") -> Dict[str, Any]:
    """Quick analysis: returns a dict matching the expected JSON schema."""
    await client.ensure_model(model)
    snippet = (text or "")[:3000]
    prompt = (
        "Przeanalizuj poniższy materiał i zwróć WYŁĄCZNIE poprawny JSON (bez preambuły, bez markdown).\n\n"
        "Wymagany format:\n"
        "{\n"
        '  "kluczowe_tematy": ["temat1", "temat2"],\n'
        '  "uczestnicy": ["Osoba 1", "Osoba 2"],\n'
        '  "decyzje": 0,\n'
        '  "zadania": 0,\n'
        '  "terminy": ["YYYY-MM-DD"],\n'
        '  "miejsca": ["Miejscowość"],\n'
        '  "status": "completed"\n'
        "}\n\n"
        "Materiał:\n" + snippet
    )
    resp = await client.chat(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        format="json",
        options={"temperature": 0.2},
    )
    content = str((resp.get("message") or {}).get("content") or "")
    return _parse_json_best_effort(content)


async def deep_analyze(client: OllamaClient, prompt: str, *, model: str = "llama3.1:70b", system: Optional[str] = None, options: Optional[Dict[str, Any]] = None) -> str:
    """Deep analysis (non-stream)."""
    await client.ensure_model(model)
    msgs: List[Dict[str, str]] = []
    if system:
        msgs.append({"role": "system", "content": system})
    msgs.append({"role": "user", "content": prompt})
    resp = await client.chat(model=model, messages=msgs, options=options or {"temperature": 0.7})
    return str((resp.get("message") or {}).get("content") or "")


async def stream_analyze(client: OllamaClient, prompt: str, *, model: str, system: Optional[str] = None, options: Optional[Dict[str, Any]] = None) -> AsyncGenerator[str, None]:
    """Deep analysis (stream)."""
    await client.ensure_model(model)
    msgs: List[Dict[str, str]] = []
    if system:
        msgs.append({"role": "system", "content": system})
    msgs.append({"role": "user", "content": prompt})
    async for chunk in client.stream_chat(model=model, messages=msgs, options=options):
        yield chunk
