
from __future__ import annotations

import io
import json
import os
import shutil
import threading
import time
import tempfile
import uuid
import zipfile
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from collections import deque

from fastapi import FastAPI, File, Form, UploadFile, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from backend.settings import APP_NAME, APP_VERSION
from backend.settings_store import load_settings, save_settings
from backend.legacy_adapter import diarize_text_simple

from generators import generate_txt_report, generate_html_report, generate_pdf_report
from backend.settings import AUTHOR_EMAIL

try:
    from markdown import markdown as md_to_html  # type: ignore
except Exception:  # pragma: no cover
    md_to_html = None


ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))

DATA_DIR = Path(os.environ.get("AISTATEWEB_DATA_DIR") or os.environ.get("AISTATEWWW_DATA_DIR") or os.environ.get("AISTATE_DATA_DIR") or str(ROOT / "data_www")).resolve()
PROJECTS_DIR = DATA_DIR / "projects"
PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
# ---------- Helpers: default name + secure delete (best-effort) ----------
from datetime import datetime

def default_project_name() -> str:
    # Default name: AISTATE_YYYY-MM-DD (editable in UI)
    return f"AISTATE_{datetime.now().date().isoformat()}"

def _overwrite_path_bytes(path: Path, pattern: bytes, chunk_size: int = 1024 * 1024) -> None:
    size = path.stat().st_size
    if size <= 0:
        return
    with open(path, "r+b", buffering=0) as f:
        remaining = size
        if not pattern:
            raise ValueError("Empty overwrite pattern")
        buf = (pattern * (chunk_size // len(pattern) + 1))[:chunk_size]
        while remaining > 0:
            n = min(chunk_size, remaining)
            f.write(buf[:n])
            remaining -= n
        f.flush()
        os.fsync(f.fileno())

def _overwrite_path_random(path: Path, passes: int = 1, chunk_size: int = 1024 * 1024) -> None:
    size = path.stat().st_size
    if size <= 0:
        return
    for _ in range(passes):
        with open(path, "r+b", buffering=0) as f:
            remaining = size
            while remaining > 0:
                n = min(chunk_size, remaining)
                f.write(os.urandom(n))
                remaining -= n
            f.flush()
            os.fsync(f.fileno())

def _gutmann_patterns() -> List[bytes]:
    # Gutmann 35-pass sequence (classic). Patterns for passes 5-31 are based on Gutmann's table.
    # Passes 1-4 and 32-35 are random.
    # Source: Peter Gutmann, USENIX Security '96. citeturn0search2
    P: List[bytes] = []
    P.append(b"\x55")
    P.append(b"\xAA")
    P.append(bytes([0x92, 0x49, 0x24]))
    P.append(bytes([0x49, 0x24, 0x92]))
    P.append(bytes([0x24, 0x92, 0x49]))
    P.extend([bytes([x]) for x in [
        0x00, 0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77, 0x88, 0x99,
        0xAA, 0xBB, 0xCC, 0xDD, 0xEE, 0xFF
    ]])
    P.append(bytes([0x92, 0x49, 0x24]))
    P.append(bytes([0x49, 0x24, 0x92]))
    P.append(bytes([0x24, 0x92, 0x49]))
    P.append(bytes([0x6D, 0xB6, 0xDB]))
    P.append(bytes([0xB6, 0xDB, 0x6D]))
    P.append(bytes([0xDB, 0x6D, 0xB6]))
    return P  # 27 pattern passes

def secure_delete_project_dir(pdir: Path, method: str) -> None:
    # Best-effort file wiping inside project directory, then removal.
    # NOTE: On SSD/VM/CoW filesystems, overwriting may not guarantee secure erase.
    # For HMG IS5 Enhanced (0x00, 0xFF, Random) see e.g. LSoft KillDisk manual. citeturn0search31
    method = (method or "none").lower().strip()

    if method == "none":
        shutil.rmtree(pdir)
        return

    files = [fp for fp in pdir.rglob("*") if fp.is_file()]

    if method == "random1":
        for fp in files:
            try:
                _overwrite_path_random(fp, passes=1)
            except Exception:
                pass
            try:
                fp.unlink()
            except Exception:
                pass

    elif method == "hmg_is5":
        for fp in files:
            try:
                _overwrite_path_bytes(fp, b"\x00")
                _overwrite_path_bytes(fp, b"\xFF")
                _overwrite_path_random(fp, passes=1)
            except Exception:
                pass
            try:
                fp.unlink()
            except Exception:
                pass

    elif method == "gutmann":
        patterns = _gutmann_patterns()
        for fp in files:
            try:
                _overwrite_path_random(fp, passes=4)
                for pat in patterns:
                    _overwrite_path_bytes(fp, pat)
                _overwrite_path_random(fp, passes=4)
            except Exception:
                pass
            try:
                fp.unlink()
            except Exception:
                pass

    else:
        shutil.rmtree(pdir)
        return

    shutil.rmtree(pdir, ignore_errors=True)


WHISPER_MODELS = [
    "tiny", "base", "small", "medium", "large", "large-v2", "large-v3",
]


def now_iso() -> str:
    import datetime as _dt
    return _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def safe_filename(name: str) -> str:
    # best-effort sanitization for uploads
    name = name.replace("\\", "_").replace("/", "_")
    return "".join(c for c in name if c.isalnum() or c in "._- ").strip()[:180] or "audio"


@dataclass
class TaskState:
    task_id: str
    kind: str
    project_id: str
    status: str = "queued"  # queued|running|done|error
    progress: int = 0
    logs: List[str] = field(default_factory=list)
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    started_at: str = field(default_factory=now_iso)
    finished_at: Optional[str] = None

    def add_log(self, line: str) -> None:
        line = line.rstrip("\n")
        if not line:
            return
        self.logs.append(line)
        # keep last N lines to avoid memory blow-up
        if len(self.logs) > 2000:
            self.logs = self.logs[-2000:]


class TaskManager:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._tasks: Dict[str, TaskState] = {}

        # A persistent "system" task to collect server-side application events.
        # This lets the Logs tab show more than just worker stderr.
        sys_task = TaskState(
            task_id="system",
            kind="system",
            project_id="-",
            status="running",
            progress=0,
        )
        self._tasks[sys_task.task_id] = sys_task

    def system_log(self, msg: str) -> None:
        """Append an application-level log line (English only)."""
        try:
            t = self.get("system")
            t.add_log(f"{now_iso()} | {msg}")
        except Exception:
            # Best-effort: never break the request because of logging.
            pass

    def list_tasks(self) -> List[TaskState]:
        with self._lock:
            tasks = list(self._tasks.values())
            system = [t for t in tasks if t.task_id == "system"]
            rest = [t for t in tasks if t.task_id != "system"][::-1]
            return system + rest

    def get(self, task_id: str) -> TaskState:
        with self._lock:
            if task_id not in self._tasks:
                raise KeyError(task_id)
            return self._tasks[task_id]

    def clear(self) -> None:
        with self._lock:
            # Clear all tasks and reset the persistent system log task.
            self._tasks.clear()
            self._tasks["system"] = TaskState(
                task_id="system",
                kind="system",
                project_id="-",
                status="running",
                progress=0,
            )

    def _set(self, t: TaskState) -> None:
        with self._lock:
            self._tasks[t.task_id] = t

    def start_subprocess(
        self,
        kind: str,
        project_id: str,
        cmd: List[str],
        cwd: Path,
        env: Optional[Dict[str, str]] = None,
    ) -> TaskState:
        import subprocess

        task_id = uuid.uuid4().hex
        t = TaskState(task_id=task_id, kind=kind, project_id=project_id, status="running", progress=0)
        self._set(t)

        # Task header (always visible even if worker is quiet for a while)
        t.add_log(f"Task started: kind={kind}, project_id={project_id}, task_id={task_id}")
        try:
            self.system_log(f"Task started: {kind} (project_id={project_id}, task_id={task_id})")
        except Exception:
            pass

        proc_env = os.environ.copy()
        if env:
            proc_env.update(env)

        # Redact obvious secrets (HF token) from command line in logs.
        def _redact_cmd(argv: List[str]) -> str:
            out: List[str] = []
            skip_next = False
            for a in argv:
                if skip_next:
                    out.append("***")
                    skip_next = False
                    continue
                if a in ("--hf_token", "--token", "--api_key", "--apikey", "--key"):
                    out.append(a)
                    skip_next = True
                    continue
                out.append(a)
            return " ".join(out)

        t.add_log(f"Command: {_redact_cmd(cmd)}")

        p = subprocess.Popen(
            cmd,
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )

        stdout_buf: List[str] = []

        def read_stderr() -> None:
            assert p.stderr is not None
            for line in p.stderr:
                line = line.rstrip("\n")
                # Progress markers from workers:
                # transcribe_worker: "PROGRESS: 12"
                # voice_worker: "PROGRESS:12"
                if line.startswith("PROGRESS"):
                    try:
                        pct = int(line.split(":")[-1].strip())
                        t.progress = max(0, min(100, pct))
                    except Exception:
                        pass
                else:
                    t.add_log(line)
                    try:
                        if t.task_id != "system" and line.strip():
                            self.system_log(f"[{kind}:{task_id[:8]}] {line}")
                    except Exception:
                        pass

            # Always flush a final marker for readability.
            t.add_log("(stderr stream closed)")

        def read_stdout() -> None:
            assert p.stdout is not None
            for line in p.stdout:
                s = line.rstrip("\n")
                # Worker stdout should end with JSON. Any other stdout lines
                # are treated as logs (many libs print to stdout).
                if s.strip().startswith("{") or s.strip().startswith("["):
                    stdout_buf.append(line)
                else:
                    if s.strip():
                        t.add_log(f"STDOUT: {s}")
                        try:
                            if t.task_id != "system" and s.strip():
                                self.system_log(f"[{kind}:{task_id[:8]}] STDOUT: {s}")
                        except Exception:
                            pass

            t.add_log("(stdout stream closed)")

        th1 = threading.Thread(target=read_stderr, daemon=True)
        th2 = threading.Thread(target=read_stdout, daemon=True)
        th1.start()
        th2.start()

        def finalize() -> None:
            rc = p.wait()
            th1.join(timeout=1)
            th2.join(timeout=1)
            t.finished_at = now_iso()

            out = "".join(stdout_buf).strip()
            if rc != 0:
                t.status = "error"
                t.error = f"Process exited with code {rc}"
                if out:
                    t.add_log("STDOUT (last): " + out[-2000:])
                try:
                    self.system_log(f"Task finished: {kind} (task_id={task_id}) -> ERROR (rc={rc})")
                except Exception:
                    pass
                return
            # parse JSON result
            if not out:
                t.result = {}
                t.status = "done"
                t.progress = 100
                try:
                    self.system_log(f"Task finished: {kind} (task_id={task_id}) -> DONE")
                except Exception:
                    pass
                return

            # Be robust: if stdout contains any accidental extra output,
            # try to recover the last JSON object from the stream.
            try:
                t.result = json.loads(out)
                t.status = "done"
                t.progress = 100
                try:
                    _persist_task_outputs(t)
                except Exception as e:
                    t.add_log(f"PERSIST ERROR: {e}")
                try:
                    self.system_log(f"Task finished: {kind} (task_id={task_id}) -> DONE")
                except Exception:
                    pass
            except Exception as e:
                import re

                recovered = None
                try:
                    matches = list(re.finditer(r"\{[\s\S]*\}\s*$", out))
                    if matches:
                        recovered = json.loads(matches[-1].group(0))
                except Exception:
                    recovered = None

                if isinstance(recovered, dict):
                    t.result = recovered
                    t.status = "done"
                    t.progress = 100
                    try:
                        _persist_task_outputs(t)
                    except Exception as e:
                        t.add_log(f"PERSIST ERROR: {e}")
                    try:
                        self.system_log(f"Task finished: {kind} (task_id={task_id}) -> DONE (recovered JSON)")
                    except Exception:
                        pass
                else:
                    t.status = "error"
                    t.error = f"Invalid JSON from worker: {e}"
                    # Keep a tail for debugging (avoid huge payloads)
                    t.add_log("STDOUT (tail): " + out[-2000:])
                    try:
                        self.system_log(f"Task finished: {kind} (task_id={task_id}) -> ERROR (invalid JSON)")
                    except Exception:
                        pass

        threading.Thread(target=finalize, daemon=True).start()
        return t

    def start_python_fn(self, kind: str, project_id: str, fn, *args, **kwargs) -> TaskState:
        task_id = uuid.uuid4().hex
        t = TaskState(task_id=task_id, kind=kind, project_id=project_id, status="running", progress=0)
        self._set(t)

        # Task header
        t.add_log(f"Task started: kind={kind}, project_id={project_id}, task_id={task_id}")
        try:
            self.system_log(f"Task started: {kind} (project_id={project_id}, task_id={task_id})")
        except Exception:
            pass

        def run() -> None:
            try:
                def log_cb(msg: str) -> None:
                    t.add_log(str(msg))
                def progress_cb(pct: int) -> None:
                    t.progress = max(0, min(100, int(pct)))

                # Only pass callbacks if the function supports them.
                import inspect

                call_kwargs = dict(kwargs)
                try:
                    sig = inspect.signature(fn)
                    params = sig.parameters
                    accepts_varkw = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values())
                    if accepts_varkw or "log_cb" in params:
                        call_kwargs.setdefault("log_cb", log_cb)
                    if accepts_varkw or "progress_cb" in params:
                        call_kwargs.setdefault("progress_cb", progress_cb)
                except Exception:
                    # If introspection fails, try best-effort with callbacks.
                    call_kwargs.setdefault("log_cb", log_cb)
                    call_kwargs.setdefault("progress_cb", progress_cb)

                try:
                    res = fn(*args, **call_kwargs)
                except TypeError:
                    # Fallback: some callables reject unexpected kwargs.
                    res = fn(*args)
                t.result = res if isinstance(res, dict) else {"result": res}
                t.status = "done"
                t.progress = 100
                try:
                    self.system_log(f"Task finished: {kind} (task_id={task_id}) -> DONE")
                except Exception:
                    pass
            except Exception as e:
                import traceback
                t.status = "error"
                t.error = str(e)
                t.add_log(traceback.format_exc())
                try:
                    self.system_log(f"Task finished: {kind} (task_id={task_id}) -> ERROR: {e}")
                except Exception:
                    pass
            finally:
                t.finished_at = now_iso()

        threading.Thread(target=run, daemon=True).start()
        return t


TASKS = TaskManager()


def app_log(msg: str) -> None:
    """Server-side app log (English only). Visible in Logs tab as "system" task."""
    try:
        TASKS.system_log(msg)
    except Exception:
        pass


def project_path(project_id: str) -> Path:
    p = PROJECTS_DIR / project_id
    p.mkdir(parents=True, exist_ok=True)
    return p


def project_meta_path(project_id: str) -> Path:
    return project_path(project_id) / "project.json"


def read_project_meta(project_id: str) -> Dict[str, Any]:
    path = project_meta_path(project_id)
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def write_project_meta(project_id: str, meta: Dict[str, Any]) -> None:
    path = project_meta_path(project_id)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def ensure_project(project_id: Optional[str]) -> str:
    if project_id:
        project_path(project_id)
        meta = read_project_meta(project_id)
        if not meta:
            write_project_meta(project_id, {"project_id": project_id, "created_at": now_iso(), "name": "projekt"})
        return project_id
    new_id = uuid.uuid4().hex
    project_path(new_id)
    write_project_meta(new_id, {"project_id": new_id, "created_at": now_iso(), "name": "projekt"})
    return new_id


def save_upload(project_id: str, upload: UploadFile) -> Path:
    pdir = project_path(project_id)
    fname = safe_filename(upload.filename or "audio")
    dst = pdir / fname
    with dst.open("wb") as f:
        shutil.copyfileobj(upload.file, f)
    meta = read_project_meta(project_id)
    meta["audio_file"] = fname
    meta["updated_at"] = now_iso()
    write_project_meta(project_id, meta)
    return dst


def require_existing_file(path: Path, msg: str) -> None:
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=400, detail=msg)


app = FastAPI(title=f"{APP_NAME} Web", version=APP_VERSION)
app.mount("/static", StaticFiles(directory=str(Path(__file__).resolve().parent / "static")), name="static")


# --- Ensure UTF-8 across the app (templates + JSON + JS/CSS) ---
@app.middleware("http")
async def _force_utf8_charset(request: Request, call_next):
    response = await call_next(request)
    try:
        ct = response.headers.get("content-type") or ""
        ctl = ct.lower()
        # Only add charset when missing and it's a text-like response
        if ct and ("charset=" not in ctl) and (
            ctl.startswith("text/")
            or ctl.startswith("application/json")
            or ctl.startswith("application/javascript")
            or ctl.startswith("application/x-javascript")
        ):
            response.headers["content-type"] = f"{ct}; charset=utf-8"
    except Exception:
        pass
    return response


@app.get("/", response_class=HTMLResponse)
def home() -> Any:
    # Default route: play Intro (once per browser session) then go to the app.
    # We keep it client-side via sessionStorage so it doesn't require cookies.
    html = """<!doctype html>
<html lang=\"pl\"><head>
  <meta charset=\"utf-8\"/>
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\"/>
  <title>AI S.T.A.T.E Web</title>
  <meta http-equiv=\"cache-control\" content=\"no-cache\"/>
  <meta http-equiv=\"pragma\" content=\"no-cache\"/>
  <meta http-equiv=\"expires\" content=\"0\"/>
</head><body>
<script>
  (function(){
    var NEXT = '/transcription';
    try {
      if (sessionStorage.getItem('aistate_intro_seen') === '1') {
        location.replace(NEXT);
      } else {
        location.replace('/static/Intro.html?next=' + encodeURIComponent(NEXT));
      }
    } catch (e) {
      // If storage is blocked, just show Intro and then continue.
      location.replace('/static/Intro.html?next=' + encodeURIComponent(NEXT));
    }
  })();
</script>
</body></html>"""
    return HTMLResponse(html)


def render_page(request: Request, tpl: str, title: str, active: str, current_project: Optional[str] = None, **ctx: Any):
    settings = load_settings()
    return TEMPLATES.TemplateResponse(
        tpl,
        {
            "request": request,
            "title": title,
            "active": active,
            "app_name": APP_NAME,
            "app_fullname": "Artificial Intelligence Speech‑To‑Analysis‑Translation Engine",
            "app_version": APP_VERSION,
            "whisper_models": WHISPER_MODELS,
            "default_whisper_model": getattr(settings, "whisper_model", "large-v3") or "large-v3",
            "current_project": current_project,
            **ctx,
        },
    )




# --- Legacy Polish routes (compat) ---
@app.get("/transkrypcja", include_in_schema=False)
def legacy_transkrypcja():
    return RedirectResponse(url="/transcription")

@app.get("/nowy-projekt", include_in_schema=False)
def legacy_nowy_projekt():
    return RedirectResponse(url="/new-project")

@app.get("/diaryzacja", include_in_schema=False)
def legacy_diaryzacja():
    return RedirectResponse(url="/diarization")

@app.get("/ustawienia", include_in_schema=False)
def legacy_ustawienia():
    return RedirectResponse(url="/settings")

@app.get("/logi", include_in_schema=False)
def legacy_logi():
    return RedirectResponse(url="/logs")

@app.get("/zapis", include_in_schema=False)
def legacy_zapis():
    return RedirectResponse(url="/save")

@app.get("/transcription", response_class=HTMLResponse)
def page_transcribe(request: Request) -> Any:
    return render_page(request, "transcription.html", "Transkrypcja", "transcription")


@app.get("/new-project", response_class=HTMLResponse)
def page_new_project(request: Request) -> Any:
    return render_page(request, "new_project.html", "Nowy projekt", "new_project")


@app.get("/diarization", response_class=HTMLResponse)
def page_diarize(request: Request) -> Any:
    return render_page(request, "diarization.html", "Diaryzacja", "diarization")


@app.get("/settings", response_class=HTMLResponse)
def page_settings(request: Request) -> Any:
    s = load_settings()
    return render_page(request, "settings.html", "Ustawienia", "settings", settings=s, data_dir=str(DATA_DIR))


@app.get("/logs", response_class=HTMLResponse)
def page_logs(request: Request) -> Any:
    return render_page(request, "logs.html", "Logi", "logs")


@app.get("/save", response_class=HTMLResponse)
def page_save(request: Request) -> Any:
    return render_page(request, "save.html", "Zapis", "save")


@app.get("/info", response_class=HTMLResponse)
def page_info(request: Request) -> Any:
    # language priority:
    # 1) explicit ?lang=en|pl
    # 2) UI language from settings
    lang = (request.query_params.get("lang") or "").lower().strip()
    if not lang:
        try:
            s = load_settings()
            lang = (getattr(s, "ui_language", "") or "").lower().strip()
        except Exception:
            lang = ""
    if not lang:
        lang = "pl"

    static_root = ROOT / "webapp" / "static"
    md_path = static_root / ("info_en.md" if lang.startswith("en") else "info_pl.md")

    # safety fallback if file missing
    if not md_path.exists():
        md_path = static_root / "info_pl.md"

    source = str(md_path.relative_to(ROOT))
    text = md_path.read_text(encoding="utf-8", errors="ignore")

    # optional placeholders
    text = (text
        .replace("{APP_NAME}", APP_NAME)
        .replace("{APP_VERSION}", APP_VERSION)
    )

    if md_to_html:
        html = md_to_html(text, extensions=["fenced_code", "tables"])
    else:
        html = "<pre>" + text.replace("&", "&amp;").replace("<", "&lt;") + "</pre>"

    return render_page(request, "info.html", "Info", "info", content=html, source=source)

# ---------- API: settings ----------

@app.get("/api/settings")
def api_get_settings() -> Any:
    s = load_settings()
    return {"hf_token": getattr(s, "hf_token", ""), "whisper_model": getattr(s, "whisper_model", "large-v3")}


@app.post("/api/settings")
def api_save_settings(payload: Dict[str, Any]) -> Any:
    s = load_settings()
    if "hf_token" in payload:
        s.hf_token = str(payload.get("hf_token") or "")
    if "whisper_model" in payload:
        s.whisper_model = str(payload.get("whisper_model") or "large-v3")
    if "ui_language" in payload:
        s.ui_language = str(payload.get("ui_language") or "pl")
    save_settings(s)
    return {"ok": True}


# ---------- API: projects ----------

@app.post("/api/projects/create")
async def api_create_project(
    name: str = Form(...),
    audio: UploadFile = File(...),
) -> Any:
    # Always create a new project with user-provided name + source audio file.
    pid = ensure_project(None)
    pname = str(name or "").strip() or default_project_name()
    app_log(f"Project create: project_id={pid}, name='{pname}', upload='{audio.filename or ''}'")
    meta = read_project_meta(pid)
    meta["name"] = pname
    meta["created_at"] = meta.get("created_at") or now_iso()
    meta["updated_at"] = now_iso()
    write_project_meta(pid, meta)

    audio_path = save_upload(pid, audio)
    size_b = 0
    try:
        size_b = audio_path.stat().st_size
    except Exception:
        size_b = 0
    app_log(f"Project upload saved: project_id={pid}, file='{audio_path.name}', size_bytes={size_b}")
    meta = read_project_meta(pid)
    meta["updated_at"] = now_iso()
    write_project_meta(pid, meta)

    return {"project_id": pid, "name": meta.get("name"), "audio_file": meta.get("audio_file"), "audio_path": str(audio_path.name)}

@app.post("/api/projects/new")
def api_new_project() -> Any:
    pid = ensure_project(None)
    return {"project_id": pid}


@app.get("/api/projects")
def api_list_projects() -> Any:
    projects: List[Dict[str, Any]] = []
    for p in PROJECTS_DIR.glob("*"):
        if p.is_dir():
            pid = p.name
            meta = read_project_meta(pid)
            projects.append({
                "project_id": pid,
                "created_at": meta.get("created_at"),
                "name": meta.get("name"),
                "updated_at": meta.get("updated_at"),
            })
    projects.sort(key=lambda x: x.get("updated_at") or x.get("created_at") or "", reverse=True)
    return {"projects": projects}


@app.get("/api/projects/{project_id}/meta")
def api_project_meta(project_id: str) -> Any:
    # Ensure the project exists and return its current metadata
    project_path(project_id)
    meta = read_project_meta(project_id)
    # Return only JSON-serializable basic fields
    return {
        "project_id": project_id,
        "created_at": meta.get("created_at"),
        "updated_at": meta.get("updated_at"),
        "name": meta.get("name"),
        "audio_file": meta.get("audio_file") or "",
        "has_transcript": bool(meta.get("has_transcript")),
        "has_diarized": bool(meta.get("has_diarized")),
    }


@app.get("/api/projects/{project_id}/download/{filename}")
def api_download(project_id: str, filename: str) -> Any:
    path = project_path(project_id) / filename
    require_existing_file(path, "Plik nie istnieje.")
    return FileResponse(str(path), filename=filename)


@app.post("/api/projects/{project_id}/save_transcript")
def api_save_transcript(project_id: str, payload: Dict[str, Any]) -> Any:
    text = str(payload.get("text") or "")
    app_log(f"Project save transcript: project_id={project_id}, chars={len(text)}")
    path = project_path(project_id) / "transcript.txt"
    path.write_text(text, encoding="utf-8")
    meta = read_project_meta(project_id)
    meta["has_transcript"] = True
    meta["updated_at"] = now_iso()
    write_project_meta(project_id, meta)
    return {"ok": True}


@app.post("/api/projects/{project_id}/save_diarized")
def api_save_diarized(project_id: str, payload: Dict[str, Any]) -> Any:
    text = str(payload.get("text") or "")
    app_log(f"Project save diarized: project_id={project_id}, chars={len(text)}")
    path = project_path(project_id) / "diarized.txt"
    path.write_text(text, encoding="utf-8")
    meta = read_project_meta(project_id)
    meta["has_diarized"] = True
    meta["updated_at"] = now_iso()
    write_project_meta(project_id, meta)
    return {"ok": True}



@app.post("/api/projects/{project_id}/speaker_map")
def api_save_speaker_map(project_id: str, payload: Dict[str, Any]) -> Any:
    mapping = payload.get("mapping") or {}
    if not isinstance(mapping, dict):
        raise HTTPException(status_code=400, detail="mapping musi być obiektem JSON (dict).")
    # keep only str->str
    clean: Dict[str, str] = {}
    for k, v in mapping.items():
        if isinstance(k, str) and isinstance(v, str) and k.strip():
            clean[k.strip()] = v.strip()
    meta = read_project_meta(project_id)
    meta["speaker_map"] = clean
    app_log(f"Project save speaker map: project_id={project_id}, entries={len(clean)}")
    meta["updated_at"] = now_iso()
    write_project_meta(project_id, meta)
    return {"ok": True, "count": len(clean)}

@app.get("/api/projects/{project_id}/export.aistate")
@app.get("/api/projects/{project_id}/export.zip")
def api_export_project(project_id: str) -> Any:
    """Export the whole project folder as a portable package.

    NOTE: .aistate is a ZIP container with a custom extension.
    """
    pdir = (PROJECTS_DIR / project_id).resolve()
    root = PROJECTS_DIR.resolve()
    if root not in pdir.parents or not pdir.exists() or not pdir.is_dir():
        raise HTTPException(status_code=404, detail="Nie ma takiego projektu.")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for fp in pdir.rglob("*"):
            if fp.is_file():
                z.write(fp, arcname=str(fp.relative_to(pdir)))
    buf.seek(0)

    return StreamingResponse(
        buf,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="project-{project_id}.aistate"'},
    )


def _safe_extract_zip(zf: zipfile.ZipFile, dst: Path) -> None:
    """Protect against Zip Slip (path traversal)."""
    dst = dst.resolve()
    for member in zf.infolist():
        name = member.filename
        # Disallow absolute paths
        if name.startswith("/") or name.startswith("\\"):
            raise HTTPException(status_code=400, detail="Nieprawidłowa paczka (ścieżka absolutna).")
        target = (dst / name).resolve()
        if dst != target and dst not in target.parents:
            raise HTTPException(status_code=400, detail="Nieprawidłowa paczka (path traversal).")
    zf.extractall(dst)


def _pick_extracted_root(tmp_dir: Path) -> Path:
    # If archive contains a single top-level folder, use it; otherwise use tmp_dir.
    entries = [p for p in tmp_dir.iterdir() if p.name not in ("__MACOSX", ".DS_Store")]
    if len(entries) == 1 and entries[0].is_dir():
        return entries[0]
    return tmp_dir


@app.post("/api/projects/import")
async def api_import_project(file: UploadFile = File(...)) -> Any:
    fname = (file.filename or "").lower()
    if not fname.endswith(".aistate"):
        raise HTTPException(status_code=400, detail="Plik musi mieć rozszerzenie .aistate")

    tmp_dir = Path(tempfile.mkdtemp(prefix="aistate_import_"))
    tmp_file = tmp_dir / "upload.aistate"
    try:
        # Stream upload to disk (avoid keeping whole audio in RAM)
        with tmp_file.open("wb") as out:
            shutil.copyfileobj(file.file, out)

        extract_dir = tmp_dir / "extracted"
        extract_dir.mkdir(parents=True, exist_ok=True)

        with zipfile.ZipFile(str(tmp_file), "r") as zf:
            _safe_extract_zip(zf, extract_dir)

        extracted_root = _pick_extracted_root(extract_dir)

        # Determine preferred project id (if present and unused)
        preferred_id = None
        pj = extracted_root / "project.json"
        if pj.exists():
            try:
                meta = json.loads(pj.read_text(encoding="utf-8"))
                if isinstance(meta, dict) and isinstance(meta.get("project_id"), str):
                    preferred_id = meta.get("project_id").strip() or None
            except Exception:
                preferred_id = None

        final_id = preferred_id
        if not final_id or (PROJECTS_DIR / final_id).exists():
            final_id = uuid.uuid4().hex

        dest = (PROJECTS_DIR / final_id).resolve()
        root = PROJECTS_DIR.resolve()
        if root not in dest.parents:
            raise HTTPException(status_code=400, detail="Nieprawidłowy docelowy katalog projektu.")
        if dest.exists():
            raise HTTPException(status_code=409, detail="Projekt o takim ID już istnieje.")

        shutil.copytree(extracted_root, dest)

        # Normalize project.json
        meta = read_project_meta(final_id)
        meta["project_id"] = final_id
        meta["created_at"] = meta.get("created_at") or now_iso()
        meta["updated_at"] = now_iso()
        write_project_meta(final_id, meta)

        return {"ok": True, "project_id": final_id}

    except HTTPException:
        raise
    except zipfile.BadZipFile:
        raise HTTPException(status_code=400, detail="Nieprawidłowa paczka .aistate (uszkodzony ZIP).")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Błąd importu: {e}")
    finally:
        try:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        except Exception:
            pass


@app.delete("/api/projects/{project_id}")
def api_delete_project(project_id: str, wipe_method: str = "none") -> Any:
    pdir = (PROJECTS_DIR / project_id).resolve()
    root = PROJECTS_DIR.resolve()
    if root not in pdir.parents or not pdir.exists() or not pdir.is_dir():
        raise HTTPException(status_code=404, detail="Nie ma takiego projektu.")

    try:
        secure_delete_project_dir(pdir, wipe_method)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Błąd usuwania projektu: {e}")

    return {"ok": True}




# ---------- API: reports ----------

def _probe_audio_basic(path: Path) -> tuple[str, str]:
    """Best-effort: duration/specs for WAV via stdlib wave; otherwise file size only."""
    import wave
    size_b = 0
    try:
        size_b = path.stat().st_size
    except Exception:
        pass
    size_mb = f"{int(round(size_b / (1024*1024)))}MB" if size_b else ""

    duration = ""
    specs = size_mb

    try:
        with wave.open(str(path), "rb") as wf:
            fr = wf.getframerate()
            n = wf.getnframes()
            ch = wf.getnchannels()
            dur_s = (n / float(fr)) if fr else 0.0
            duration = f"{dur_s:.1f}s"
            specs2 = f"{ch}ch {fr}Hz"
            specs = (specs2 + ((" • " + size_mb) if size_mb else "")).strip(" •")
    except Exception:
        pass
    return duration, specs


def _collect_report_data(project_id: str, export_formats: List[str], include_logs: bool) -> Dict[str, Any]:
    meta = read_project_meta(project_id)
    pdir = project_path(project_id)

    audio_file = meta.get("audio_file") or ""
    audio_duration = ""
    audio_specs = ""
    if audio_file:
        ap = pdir / audio_file
        if ap.exists():
            audio_duration, audio_specs = _probe_audio_basic(ap)

    transcript_lines: List[str] = []
    diarized_lines: List[str] = []
    if (pdir / "transcript.txt").exists():
        transcript_lines = [ln.rstrip() for ln in (pdir / "transcript.txt").read_text(encoding="utf-8", errors="ignore").splitlines() if ln.strip()]
    if (pdir / "diarized.txt").exists():
        diarized_lines = [ln.rstrip() for ln in (pdir / "diarized.txt").read_text(encoding="utf-8", errors="ignore").splitlines() if ln.strip()]

    s = load_settings()
    logs_text = ""
    if include_logs:
        # best effort: concatenate last logs from tasks related to this project
        parts = []
        for t in TASKS.list_tasks():
            if t.project_id == project_id:
                parts.append(f"=== TASK {t.task_id} ({t.kind}) ===")
                parts.extend(t.logs[-400:])
                parts.append("")
        logs_text = "\n".join(parts).strip()

    data = {
        "program_name": APP_NAME,
        "program_version": APP_VERSION,
        "author_email": AUTHOR_EMAIL,
        "processed_at": now_iso(),
        "audio_file": audio_file,
        "audio_duration": audio_duration,
        "audio_specs": audio_specs,
        "whisper_model": getattr(s, "whisper_model", "") or "",
        "language": "auto",
        "pyannote_model": "pyannote.audio",
        "speakers_count": "",
        "segments_count": len(diarized_lines) if diarized_lines else len(transcript_lines),
        "speaker_times": {},
        "transcript": diarized_lines or transcript_lines,
        "raw_transcript": transcript_lines,
        "non_verbal": [],
        "export_formats": export_formats,
        "logs": logs_text,
        "ui_language": "pl",
        "theme": "",
        "speaker_name_map": (meta.get("speaker_map") or {}),
        "section_title": "Transkrypcja / Diaryzacja",
    }
    return data


@app.get("/api/projects/{project_id}/report")
def api_generate_report(project_id: str, format: str = "pdf", include_logs: int = 0) -> Any:
    project_path(project_id)  # ensure exists
    fmt = (format or "").lower()
    if fmt not in ("txt", "html", "pdf"):
        raise HTTPException(status_code=400, detail="format must be txt|html|pdf")

    pdir = project_path(project_id)
    ts = time.strftime("%Y%m%d_%H%M%S")
    out_name = f"report_{ts}.{fmt}"
    out_path = pdir / out_name

    app_log(f"Report requested: project_id={project_id}, format={fmt}, include_logs={bool(include_logs)}")

    data = _collect_report_data(project_id, export_formats=[fmt], include_logs=bool(include_logs))

    if fmt == "txt":
        generate_txt_report(data, logs=bool(include_logs), output_path=str(out_path))
        return FileResponse(str(out_path), filename=out_name)
    if fmt == "html":
        generate_html_report(data, logs=bool(include_logs), output_path=str(out_path))
        return FileResponse(str(out_path), filename=out_name)
    generate_pdf_report(data, logs=bool(include_logs), output_path=str(out_path))
    return FileResponse(str(out_path), filename=out_name)


# ---------- API: tasks ----------

@app.get("/api/tasks")
def api_tasks() -> Any:
    tasks = TASKS.list_tasks()
    return {"tasks": [{"task_id": t.task_id, "kind": t.kind, "status": t.status, "project_id": t.project_id} for t in tasks]}


@app.post("/api/tasks/clear")
def api_tasks_clear() -> Any:
    TASKS.clear()
    return {"ok": True}


@app.get("/api/tasks/{task_id}")
def api_task(task_id: str) -> Any:
    try:
        t = TASKS.get(task_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Nie ma takiego zadania.")
    data = asdict(t)
    # Limit payload size
    if len(data.get("logs") or []) > 400:
        data["logs"] = data["logs"][-400:]
    return data


# ---------- API: transcribe / diarize ----------

@app.post("/api/transcribe")
async def api_transcribe(
    project_id: str = Form(""),
    lang: str = Form("auto"),
    model: str = Form("large-v3"),
    audio: Optional[UploadFile] = File(None),
) -> Any:
    project_id = ensure_project(project_id or None)
    if audio is not None:
        audio_path = save_upload(project_id, audio)
    else:
        meta = read_project_meta(project_id)
        fname = str(meta.get("audio_file") or "")
        if not fname:
            raise HTTPException(status_code=400, detail="Brak pliku audio w projekcie. Wgraj plik.")
        audio_path = project_path(project_id) / fname
        require_existing_file(audio_path, "Plik audio z projektu nie istnieje.")

    # Use existing worker script (subprocess) to keep server responsive
    worker = ROOT / "backend" / "transcribe_worker.py"
    require_existing_file(worker, "Brak transcribe_worker.py")

    cmd = [
        os.environ.get("PYTHON", __import__("sys").executable),
        str(worker),
        "--audio", str(audio_path),
        "--model", model,
        "--lang", lang,
    ]
    app_log(f"Transcription requested: project_id={project_id}, audio='{audio_path.name}', model={model}, lang={lang}")
    t = TASKS.start_subprocess(kind="transcribe", project_id=project_id, cmd=cmd, cwd=ROOT)
    return {"task_id": t.task_id, "project_id": project_id}


@app.post("/api/diarize_voice")
async def api_diarize_voice(
    project_id: str = Form(""),
    lang: str = Form("auto"),
    model: str = Form("large-v3"),
    audio: Optional[UploadFile] = File(None),
) -> Any:
    project_id = ensure_project(project_id or None)
    if audio is not None:
        audio_path = save_upload(project_id, audio)
    else:
        meta = read_project_meta(project_id)
        fname = str(meta.get("audio_file") or "")
        if not fname:
            raise HTTPException(status_code=400, detail="Brak pliku audio w projekcie. Wgraj plik.")
        audio_path = project_path(project_id) / fname
        require_existing_file(audio_path, "Plik audio z projektu nie istnieje.")

    s = load_settings()
    hf_token = getattr(s, "hf_token", "") or ""
    if not hf_token:
        raise HTTPException(status_code=400, detail="Brak tokena HF. Ustaw go w Ustawieniach.")

    worker = ROOT / "backend" / "voice_worker.py"
    require_existing_file(worker, "Brak voice_worker.py")

    cmd = [
        os.environ.get("PYTHON", __import__("sys").executable),
        str(worker),
        "--audio", str(audio_path),
        "--model", model,
        "--lang", lang,
        "--hf_token", hf_token,
    ]
    app_log(f"Voice diarization requested: project_id={project_id}, audio='{audio_path.name}', model={model}, lang={lang}")
    t = TASKS.start_subprocess(kind="diarize_voice", project_id=project_id, cmd=cmd, cwd=ROOT)
    return {"task_id": t.task_id, "project_id": project_id}


@app.post("/api/diarize_text")
async def api_diarize_text(
    project_id: str = Form(""),
    text: str = Form(...),
    speakers: int = Form(2),
    method: str = Form("alternate"),
    mapping_json: str = Form(""),
) -> Any:
    project_id = ensure_project(project_id or None)
    mapping: Dict[str, str] = {}
    if mapping_json.strip():
        try:
            mapping = json.loads(mapping_json)
            if not isinstance(mapping, dict):
                mapping = {}
        except Exception:
            raise HTTPException(status_code=400, detail="Niepoprawny JSON mapowania mówców.")

    speakers = max(1, min(50, int(speakers or 2)))
    method = str(method or "alternate")

    app_log(f"Text diarization requested: project_id={project_id}, speakers={speakers}, method={method}, input_chars={len(text or '')}")

    def fn(txt: str, log_cb=None, progress_cb=None) -> Dict[str, Any]:
        res = diarize_text_simple(txt, speakers=speakers, method=method, log_cb=log_cb, progress_cb=progress_cb)
        out_text = str(res.get("text") or "")
        # Optional mapping: replace "SPK1:" -> "Jan:" etc
        if mapping:
            if log_cb:
                log_cb(f"Speaker mapping: applying {len(mapping)} replacements")
            for k, v in mapping.items():
                if not isinstance(k, str) or not isinstance(v, str):
                    continue
                # replace both "SPK1:" and "SPK1 " variants
                out_text = out_text.replace(f"{k}:", f"{v}:")
                out_text = out_text.replace(f"{k} ", f"{v} ")
        return {"kind": "diarized_text", "text": out_text}

    t = TASKS.start_python_fn("diarize_text", project_id, fn, text)
    return {"task_id": t.task_id, "project_id": project_id}



# ---------- post-processing: save default files when task done ----------
# lightweight background watcher: for finished tasks, persist outputs into project folder
# (keeps UI simple: download links point to stable filenames)
_persist_lock = threading.Lock()
_persisted: set[str] = set()


def _persist_task_outputs(t: "TaskState") -> None:
    """Persist finished task outputs into stable project files.
    We also update project.json flags so UI can show what exists.
    """
    pdir = project_path(t.project_id)
    meta = read_project_meta(t.project_id)
    wrote_any = False
    # Transcription
    if t.kind == "transcribe" and isinstance(t.result, dict):
        if ("text_ts" in t.result) or ("text" in t.result):
            out_txt = str(t.result.get("text_ts") or t.result.get("text") or "")
            (pdir / "transcript.txt").write_text(out_txt, encoding="utf-8")
            meta["has_transcript"] = True
            wrote_any = True
    # Diarization
    if t.kind in ("diarize_voice", "diarize_text") and isinstance(t.result, dict):
        if "text" in t.result:
            text_out = str(t.result.get("text") or "")
            # Apply speaker_map if present (best-effort)
            mapping = meta.get("speaker_map") or {}
            if isinstance(mapping, dict) and mapping:
                for k, v in mapping.items():
                    if isinstance(k, str) and isinstance(v, str):
                        text_out = text_out.replace(k, v)
            (pdir / "diarized.txt").write_text(text_out, encoding="utf-8")
            meta["has_diarized"] = True
            wrote_any = True
    if wrote_any:
        meta["updated_at"] = now_iso()
        write_project_meta(t.project_id, meta)
    else:
        # still bump timestamp for completed tasks
        meta["updated_at"] = now_iso()
        write_project_meta(t.project_id, meta)

def _persist_loop() -> None:
    while True:
        time.sleep(1.0)
        tasks = TASKS.list_tasks()
        for t in tasks:
            if t.status != "done":
                continue
            key = t.task_id
            with _persist_lock:
                if key in _persisted:
                    continue
                _persisted.add(key)
            try:
                _persist_task_outputs(t)
            except Exception as e:
                # keep server running but leave a breadcrumb in task logs
                try:
                    t.add_log(f"PERSIST ERROR: {e}")
                except Exception:
                    pass

threading.Thread(target=_persist_loop, daemon=True).start()
