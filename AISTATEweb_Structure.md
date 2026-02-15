# AISTATEweb - Structure

## Project Overview

AISTATEweb is a Python/FastAPI web application for audio transcription, speaker diarization, translation, LLM-powered analysis, and text-to-speech. It uses Whisper for ASR, pyannote.audio for diarization, NLLB-200 for translation, Ollama for LLM chat/analysis, and Piper/MMS/Kokoro for TTS. Data is stored as flat JSON files (no database).

## Quick Reference

```bash
# Run the server (development, with hot-reload)
python AISTATEweb.py
# OR
python -m uvicorn webapp.server:app --host 127.0.0.1 --port 8000 --reload

# Run tests
pytest tests/ -v --tb=short

# Install dependencies
pip install -r requirements.txt
```

## Repository Structure

```
AISTATEweb/
├── AISTATEweb.py              # Entry point — runs uvicorn with webapp.server:app
├── requirements.txt           # All Python dependencies
├── pytest.ini                 # Pytest configuration
│
├── webapp/                    # FastAPI web application
│   ├── server.py              # Main app (6600+ lines): routes, TaskManager, GPUResourceManager
│   ├── routers/               # Extracted API route modules
│   │   ├── auth.py            # /api/auth/* — login, logout, register, audit, password mgmt
│   │   ├── chat.py            # POST /api/chat/send, GET /api/chat/follow/{id} (SSE streaming)
│   │   ├── admin.py           # /api/admin/gpu/* — GPU Resource Manager endpoints
│   │   └── tasks.py           # /api/tasks/* — background task management
│   ├── auth/                  # Multi-user authentication module
│   │   ├── audit_store.py     # JSON-based audit log (login events, fingerprints, max 5000 entries)
│   │   ├── user_store.py      # User CRUD, UserRecord dataclass (UUID-based user_id)
│   │   ├── session_store.py   # Session management (cookie: aistate_session)
│   │   ├── deployment_store.py# Single/multi-user mode configuration
│   │   ├── message_store.py   # Call Center inter-user messaging
│   │   ├── passwords.py       # PBKDF2-SHA256 hashing, password policy validation
│   │   └── permissions.py     # Role-based module access (roles, admin_roles)
│   ├── templates/             # Jinja2 HTML templates (16 files)
│   └── static/                # JS, CSS, fonts, images
│       ├── app.js             # Main frontend logic
│       ├── app.css            # Global styles
│       ├── lang/              # UI i18n files (pl, en)
│       └── (feature).js       # Per-feature JS modules
│
├── backend/                   # Core backend logic and workers
│   ├── settings.py            # APP_NAME, APP_VERSION, Settings dataclass
│   ├── settings_store.py      # JSON-based settings persistence (backend/.aistate/settings.json)
│   ├── legacy_adapter.py      # Whisper/NeMo/pyannote wrappers (1800+ lines)
│   ├── ollama_client.py       # Async Ollama HTTP client (httpx)
│   ├── document_processor.py  # Multi-format text extraction (TXT/PDF/DOCX/XLSX/PPTX/images)
│   ├── report_generator.py    # Report export (HTML/TXT/DOCX)
│   ├── models_info.py         # Curated LLM model catalog
│   ├── tasks.py               # Task/job infrastructure
│   ├── prompts/               # LLM prompt management (manager.py, templates.py)
│   ├── translation/           # Translation module
│   │   ├── hybrid_translator.py   # Main translator (NLLB-based)
│   │   ├── document_handlers.py   # Format-specific handlers
│   │   ├── summarizer.py          # Text summarization
│   │   ├── language_detector.py   # Language detection
│   │   └── glossary_manager.py    # Domain glossaries
│   │
│   ├── transcribe_worker.py       # Subprocess: transcription
│   ├── asr_worker.py              # Subprocess: ASR model install/download
│   ├── translation_worker.py      # Subprocess: NLLB translation
│   ├── nllb_worker.py             # Subprocess: NLLB model management
│   ├── tts_worker.py              # Subprocess: text-to-speech
│   ├── voice_worker.py            # Subprocess: voice processing
│   └── sound_detection_worker.py  # Subprocess: YAMNet/PANNs/BEATs sound detection
│
├── generators/                # Report generators
│   ├── txt_report.py
│   ├── html_report.py
│   └── pdf_report.py
│
└── tests/                     # Pytest test suite
    ├── conftest.py            # Fixtures: temp dirs, env overrides, sample files
    ├── test_api_integration.py    # FastAPI TestClient integration tests
    ├── test_document_processor.py # Document extraction tests
    ├── test_routers_chat.py       # Chat router tests
    ├── test_multiuser.py          # Auth: passwords, users, sessions, permissions, roles
    └── test_settings.py           # Settings persistence tests
```

## Architecture

### Server (`webapp/server.py`)

This is the main application file. It contains:
- The FastAPI `app` instance and all middleware
- ~17 HTML page routes (transcription, diarization, chat, analysis, translation, settings, admin, etc.)
- 100+ JSON API endpoints under `/api/`
- `TaskManager` — in-process task queue that runs heavy work in subprocesses
- `GPUResourceManager` — priority-based GPU/CPU job scheduler to prevent VRAM exhaustion
- Model cache scanning and registry persistence

### Workers (subprocess-based)

Heavy ML tasks run as separate Python subprocesses. Workers communicate results via:
- JSON printed to stdout (parsed by TaskManager)
- Progress reported via `PROGRESS: <0-100>` on stderr
- HF tokens are redacted in subprocess command logs

### Data Storage

No database. All state is file-based:
- **Projects:** `data_www/projects/{project_id}/project.json` + associated files (audio, transcript, diarized text, translations)
- **Settings:** `backend/.aistate/settings.json` (contains HF token — never commit)
- **Users:** `backend/.aistate/users.json` — user accounts (UUID `user_id`, roles, password hashes)
- **Sessions:** `backend/.aistate/sessions.json` — active login sessions
- **Audit log:** `backend/.aistate/audit_log.json` — auth events with browser fingerprints (max 5000 entries)
- **Model registries:** `data_www/projects/_global/asr_models.json`, `nllb_models.json`
- **Admin logs:** `backend/logs/YYYY-MM-DD/aistateHH-HH.log` (system), `aistate_userHH-HH.log` (auth events)

### Frontend

Server-rendered HTML (Jinja2 templates) with vanilla JavaScript. No build step, no bundler, no npm. JS/CSS files are served directly from `webapp/static/`.

## Environment Variables

| Variable | Purpose | Default |
|---|---|---|
| `AISTATEWEB_HOST` | Server bind address | `127.0.0.1` |
| `AISTATEWEB_PORT` | Server bind port | `8000` |
| `AISTATEWEB_DATA_DIR` | Project data directory | `ROOT/data_www` |
| `AISTATE_CONFIG_DIR` | Settings storage location | `backend/.aistate/` |
| `AISTATEWEB_ADMIN_LOG_DIR` | Admin logs location | `backend/logs/` |
| `HF_TOKEN` / `HF_HUB_TOKEN` | HuggingFace API token (for gated models) | — |
| `OLLAMA_HOST` | Ollama server URL | `http://127.0.0.1:11434` |
| `PYTHON` | Python interpreter for subprocess workers | system default |

## Testing

```bash
pytest tests/ -v --tb=short
```

- Tests use `FastAPI TestClient` for integration testing
- `conftest.py` overrides `AISTATEWEB_DATA_DIR`, `AISTATE_CONFIG_DIR`, and `AISTATEWEB_ADMIN_LOG_DIR` to temp directories so tests never touch production data
- No external services required for basic tests (Ollama, GPU, etc. are mocked or skipped)

## Key Conventions

- **Python 3.11+** with `from __future__ import annotations`
- **Type hints** used throughout (`typing` module: `Dict`, `List`, `Optional`, `Any`)
- **Dataclasses** for structured data (`Settings`, task metadata, etc.)
- **Async endpoints** where appropriate; heavy sync work uses `run_in_threadpool` or subprocess workers
- **No ORM** — direct `Path.read_text()` / `Path.write_text()` with `json.loads()` / `json.dumps()`
- **Multi-user authentication** — optional mode with role-based access, session cookies, rate limiting, account lockout, browser fingerprint logging, and audit trail (see `webapp/auth/`)
- **UI languages:** Polish (pl) and English (en); UI strings are in `webapp/static/lang/`
- **No linter or formatter configured** in the repo (no flake8, black, ruff, etc.)
- **No CI/CD pipeline** configured

## Common Patterns

### Adding a new API endpoint

Add it to `webapp/server.py` or the appropriate router in `webapp/routers/`. Endpoints follow the pattern:
```python
@app.post("/api/feature/action")
async def feature_action(request: Request, ...):
    ...
    return JSONResponse({"status": "ok", ...})
```

### Adding a new page route

1. Create a template in `webapp/templates/`
2. Add a route in `webapp/server.py` that renders it via `TEMPLATES.TemplateResponse()`
3. Add corresponding JS in `webapp/static/` if needed

### Running GPU-heavy tasks

Use the `GPUResourceManager` to queue work:
```python
gpu_rm.submit(task_id, priority, callable, *args)
```

### Worker subprocess pattern

Workers are invoked by `TaskManager` as separate Python processes. They:
1. Parse arguments from the command line
2. Do the heavy computation
3. Print JSON results to stdout
4. Report progress via `PROGRESS: N` on stderr

### Authentication & Audit

Multi-user mode (`webapp/auth/`) provides:
- **Login/Logout/Register** via `webapp/routers/auth.py` (`/api/auth/*`)
- **Roles:** user roles (Transkryptor, Lingwista, Analityk, Dialogista, Strateg, Mistrz Sesji) + admin roles (Architekt Funkcji, Strażnik Dostępu, Główny Opiekun) + superadmin
- **Audit log** (`AuditStore`): records events (login, login_failed, logout, password_changed, account_locked, etc.) to both JSON (`audit_log.json`) and flat file logs (`backend/logs/`)
- **Browser fingerprint** collected at login: `browser`, `os`, `screen`, `timezone`, `language`, `platform` — stored in audit entries and written to file logs as `device=[browser=Chrome 120 os=Windows 10 ...]`
- **Audit history panel** in admin UI (Users → Security tab): searchable by username or UID, filterable by event type, shows UID column + Device column

Audit entry structure:
```json
{
  "id": "uuid",
  "timestamp": "ISO datetime",
  "event": "login|login_failed|...",
  "user_id": "user UUID",
  "username": "...",
  "ip": "...",
  "detail": "...",
  "fingerprint": {"browser": "Chrome 120", "os": "Windows 10", "screen": "1920x1080", "timezone": "Europe/Warsaw", "language": "pl-PL", "platform": "Win32"}
}
```

## Sensitive Files (do not commit)

- `backend/.aistate/settings.json` — contains HuggingFace token
- `backend/.aistate/users.json` — password hashes, user data
- `backend/.aistate/sessions.json` — active session tokens
- `backend/.aistate/audit_log.json` — login history with IPs and fingerprints
- `.env` or any credentials files
- `data_www/` — user project data

## License

MIT (main project). NLLB-200 models are CC-BY-NC 4.0 (non-commercial only). See `THIRD_PARTY_NOTICES.md` for full dependency licensing.
