
from __future__ import annotations

import io
import json
import os
import shutil
import threading
import time
import uuid
import zipfile
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Any, Dict, List, Optional

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

    def list_tasks(self) -> List[TaskState]:
        with self._lock:
            return list(self._tasks.values())[::-1]

    def get(self, task_id: str) -> TaskState:
        with self._lock:
            if task_id not in self._tasks:
                raise KeyError(task_id)
            return self._tasks[task_id]

    def clear(self) -> None:
        with self._lock:
            self._tasks.clear()

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

        proc_env = os.environ.copy()
        if env:
            proc_env.update(env)

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

        def read_stdout() -> None:
            assert p.stdout is not None
            for line in p.stdout:
                stdout_buf.append(line)

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
                return
            # parse JSON result
            if not out:
                t.result = {}
                t.status = "done"
                t.progress = 100
                return

            # Be robust: if stdout contains any accidental extra output,
            # try to recover the last JSON object from the stream.
            try:
                t.result = json.loads(out)
                t.status = "done"
                t.progress = 100
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
                else:
                    t.status = "error"
                    t.error = f"Invalid JSON from worker: {e}"
                    # Keep a tail for debugging (avoid huge payloads)
                    t.add_log("STDOUT (tail): " + out[-2000:])

        threading.Thread(target=finalize, daemon=True).start()
        return t

    def start_python_fn(self, kind: str, project_id: str, fn, *args, **kwargs) -> TaskState:
        task_id = uuid.uuid4().hex
        t = TaskState(task_id=task_id, kind=kind, project_id=project_id, status="running", progress=0)
        self._set(t)

        def run() -> None:
            try:
                def log_cb(msg: str) -> None:
                    t.add_log(str(msg))
                def progress_cb(pct: int) -> None:
                    t.progress = max(0, min(100, int(pct)))
                kwargs.setdefault("log_cb", log_cb)
                kwargs.setdefault("progress_cb", progress_cb)
                res = fn(*args, **kwargs)
                t.result = res if isinstance(res, dict) else {"result": res}
                t.status = "done"
                t.progress = 100
            except Exception as e:
                import traceback
                t.status = "error"
                t.error = str(e)
                t.add_log(traceback.format_exc())
            finally:
                t.finished_at = now_iso()

        threading.Thread(target=run, daemon=True).start()
        return t


TASKS = TaskManager()


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


@app.get("/", response_class=HTMLResponse)
def home() -> Any:
    # default route
    return HTMLResponse('<meta http-equiv="refresh" content="0; url=/transcription">')


def render_page(request: Request, tpl: str, title: str, active: str, current_project: Optional[str] = None, **ctx: Any):
    settings = load_settings()
    return TEMPLATES.TemplateResponse(
        tpl,
        {
            "request": request,
            "title": title,
            "active": active,
            "app_name": APP_NAME,
            "app_fullname": "Artificial Intelligence Speech‑To‑Analysis‑Translation Engine (Light)",
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
    # prefer Polish; add ?lang=en to switch
    lang = (request.query_params.get("lang") or "").lower()
    md_path = ROOT / "docs" / ("info_en.md" if lang.startswith("en") else "info_pl.md")
    source = str(md_path.relative_to(ROOT))
    text = md_path.read_text(encoding="utf-8", errors="ignore")
    if md_to_html:
        html = md_to_html(text, extensions=["fenced_code", "tables"])
    else:
        # fallback: very naive
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
    meta = read_project_meta(pid)
    meta["name"] = str(name or "projekt").strip() or "projekt"
    meta["created_at"] = meta.get("created_at") or now_iso()
    meta["updated_at"] = now_iso()
    write_project_meta(pid, meta)

    audio_path = save_upload(pid, audio)
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
    meta["updated_at"] = now_iso()
    write_project_meta(project_id, meta)
    return {"ok": True, "count": len(clean)}

@app.get("/api/projects/{project_id}/export.zip")
def api_export_project(project_id: str) -> Any:
    pdir = project_path(project_id)
    if not pdir.exists():
        raise HTTPException(status_code=404, detail="Nie ma takiego projektu.")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for fp in pdir.rglob("*"):
            if fp.is_file():
                z.write(fp, arcname=str(fp.relative_to(pdir)))
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="project-{project_id}.zip"'},
    )




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

    def fn(txt: str) -> Dict[str, Any]:
        res = diarize_text_simple(txt, speakers=speakers, method=method)
        out_text = str(res.get("text") or "")
        # Optional mapping: replace "SPK1:" -> "Jan:" etc
        if mapping:
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
                pdir = project_path(t.project_id)
                if t.kind == "transcribe" and t.result and "text" in t.result:
                    (pdir / "transcript.txt").write_text(str(t.result.get("text") or ""), encoding="utf-8")
                if t.kind in ("diarize_voice", "diarize_text") and t.result and "text" in t.result:
                    text_out = str(t.result.get("text") or "")
                    meta0 = read_project_meta(t.project_id)
                    mapping = meta0.get("speaker_map") or {}
                    if isinstance(mapping, dict) and mapping:
                        for k, v in mapping.items():
                            if isinstance(k, str) and isinstance(v, str):
                                text_out = text_out.replace(k, v)
                    (pdir / "diarized.txt").write_text(text_out, encoding="utf-8")
                meta = read_project_meta(t.project_id)
                meta["updated_at"] = now_iso()
                write_project_meta(t.project_id, meta)
            except Exception:
                pass

threading.Thread(target=_persist_loop, daemon=True).start()
