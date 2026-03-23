# AISTATEweb - Technical Documentation v1.2

## Project Overview

AISTATEweb is a Python/FastAPI web application for audio transcription, speaker diarization, translation, LLM-powered analysis, financial/AML intelligence, cryptocurrency analysis, GSM billing analysis, and text-to-speech. It uses Whisper for ASR, pyannote.audio for diarization, NLLB-200 for translation, Ollama for LLM chat/analysis, and Piper/MMS/Kokoro for TTS. Structured data is stored in SQLite (`aistate.db`); project files live on disk.

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
│   ├── server.py              # Main app: routes, TaskManager, GPUResourceManager, middleware
│   ├── routers/               # Extracted API route modules
│   │   ├── auth.py            # /api/auth/* — login, logout, register, audit, password mgmt
│   │   ├── users.py           # /api/users/* — user CRUD, ban/unban, approve/reject, lockout
│   │   ├── setup.py           # /api/setup/* — deployment mode, first admin creation, migration
│   │   ├── messages.py        # /api/messages/* — Call Center messaging (unread, create, delete)
│   │   ├── chat.py            # POST /api/chat/send, GET /api/chat/follow/{id} (SSE streaming)
│   │   ├── admin.py           # /api/admin/gpu/* — GPU Resource Manager endpoints
│   │   ├── updates.py         # /api/admin/update/* — software update upload/install/rollback
│   │   ├── licensing.py       # /api/admin/license/* — license status, activation, removal
│   │   ├── tasks.py           # /api/tasks/* — background task management
│   │   ├── aml.py             # /api/aml/* — AML analysis, SQL-backed project management
│   │   ├── gsm.py             # /api/gsm/* — GSM billing analysis
│   │   ├── crypto.py          # /api/crypto/* — cryptocurrency analysis
│   │   ├── aria.py            # /api/aria/* — ARIA HUD intelligence assistant
│   │   ├── workspaces.py      # /api/workspaces/* — project workspaces & collaboration
│   │   └── report_profiles.py # /api/report-profiles/* — report template management
│   ├── auth/                  # Multi-user authentication module (SQLite-backed)
│   │   ├── user_store.py      # UserStore — SQLite CRUD, UserRecord dataclass, JSON→SQLite migration
│   │   ├── session_store.py   # SessionStore — SQLite sessions (cookie: aistate_session)
│   │   ├── audit_store.py     # AuditStore — SQLite auth event log (login, ban, etc.)
│   │   ├── deployment_store.py# DeploymentStore — single/multi-user mode (deployment_config table)
│   │   ├── message_store.py   # MessageStore — Call Center messaging (auth_messages + auth_message_reads)
│   │   ├── passwords.py       # PBKDF2-SHA256 hashing, password policy, blacklist management
│   │   ├── permissions.py     # Role-based module access (roles, admin_roles, route checks)
│   │   └── builtin_passwords.txt # Common password blacklist
│   ├── templates/             # Jinja2 HTML templates (22+ files)
│   │   ├── base.html          # Base layout template
│   │   ├── login.html, register.html, setup.html, pending.html, banned.html  # Auth pages
│   │   ├── users.html         # Settings panel (users, security, system, license)
│   │   ├── transcription.html, diarization.html, translation.html  # Core features
│   │   ├── analysis.html, chat.html  # LLM features
│   │   ├── projects.html, save.html  # Project management
│   │   ├── settings.html, llm_settings.html, asr_settings.html  # Settings pages
│   │   ├── nllb_settings.html, tts_settings.html  # Model settings
│   │   ├── admin.html, logs.html, info.html  # Admin/system pages
│   │   └── ...
│   └── static/                # JS, CSS, fonts, images
│       ├── app.js             # Main frontend logic
│       ├── app.css            # Global styles
│       ├── users.js           # User management panel JS
│       ├── admin_update.js    # Software update panel JS
│       ├── admin_license.js   # License panel JS
│       ├── admin_gpu.js       # GPU Resource Manager JS
│       ├── lang/              # UI i18n files (pl, en, ko)
│       └── (feature).js       # Per-feature JS modules
│
├── backend/                   # Core backend logic and workers
│   ├── settings.py            # APP_NAME, APP_VERSION, Settings dataclass
│   ├── settings_store.py      # JSON-based settings persistence (backend/.aistate/settings.json)
│   ├── legacy_adapter.py      # Whisper/NeMo/pyannote wrappers
│   ├── ollama_client.py       # Async Ollama HTTP client (httpx)
│   ├── document_processor.py  # Multi-format text extraction (TXT/PDF/DOCX/XLSX/PPTX/images)
│   ├── report_generator.py    # Report export (HTML/TXT/DOCX)
│   ├── models_info.py         # Curated LLM model catalog
│   ├── tasks.py               # Task/job infrastructure
│   ├── prompts/               # LLM prompt management (manager.py, templates.py)
│   │
│   ├── db/                    # SQLite database layer
│   │   ├── engine.py          # Connection pool, init_db(), get_conn(), WAL mode
│   │   ├── schema.sql         # Full schema (users, sessions, audit, projects, AML, etc.)
│   │   ├── migrate.py         # Schema migration utilities
│   │   ├── backup.py          # Database backup/restore
│   │   └── projects.py        # SQL-based project queries
│   │
│   ├── licensing/             # License management module
│   │   ├── __init__.py        # LICENSING_ENABLED flag (master switch, default: False)
│   │   ├── models.py          # LicenseInfo dataclass, plan definitions, feature lists
│   │   ├── validator.py       # Ed25519 signature verification, key parsing, clock check
│   │   ├── feature_gate.py    # @require_feature() decorator for endpoint gating
│   │   └── public_key.py      # Ed25519 public key (placeholder until production)
│   │
│   ├── updater/               # Software update system
│   │   ├── models.py          # UpdateInfo, UpdateState, UpdateStatus, UpdateHistoryEntry
│   │   ├── package_parser.py  # .zip package validation, UPDATE_INFO.json parsing
│   │   ├── installer.py       # Backup, code replacement, dependency install, migrations
│   │   ├── rollback.py        # Version rollback from backups
│   │   └── restart_manager.py # Graceful restart scheduling (countdown, cancel, restart-now)
│   │
│   ├── encryption/            # Project data encryption module
│   │   └── ...                # AES encryption for project files
│   │
│   ├── finance/               # Financial statement parsing pipeline
│   │   ├── pipeline.py        # Main finance pipeline orchestrator
│   │   ├── classifier.py      # Transaction classification rules
│   │   ├── detector.py        # Anomaly detection
│   │   ├── behavioral.py      # Behavioral analysis patterns
│   │   ├── scorer.py          # Risk scoring
│   │   ├── entity_memory.py   # Counterparty memory / entity recognition
│   │   ├── llm_classifier.py  # LLM-based classification fallback
│   │   ├── prompt_builder.py  # Finance-specific LLM prompt construction
│   │   ├── quick_extract.py   # Quick data extraction
│   │   ├── spending_analysis.py # Spending category analysis
│   │   └── parsers/           # Bank statement parsers
│   │       ├── base.py        # RawTransaction, StatementInfo dataclasses
│   │       ├── registry.py    # Auto-detect bank format
│   │       ├── generic.py     # Generic CSV/XLSX parser
│   │       ├── ing.py, pko.py, mbank.py, pekao.py  # Bank-specific parsers
│   │       ├── millennium.py, santander.py
│   │       └── ...
│   │
│   ├── aml/                   # AML (Anti-Money Laundering) analysis engine
│   │   ├── pipeline.py        # AML analysis pipeline orchestrator
│   │   ├── normalize.py       # Transaction normalization
│   │   ├── rules.py           # Risk rule engine
│   │   ├── enrich.py          # Transaction enrichment
│   │   ├── graph.py           # Flow graph builder (nodes + edges)
│   │   ├── baseline.py        # Statistical baseline computation
│   │   ├── ml_anomaly.py      # ML-based anomaly detection
│   │   ├── memory.py          # Counterparty memory integration
│   │   ├── anonymize.py       # Data anonymization
│   │   ├── charts.py          # Chart/visualization data
│   │   ├── column_mapper.py   # Column mapping logic
│   │   ├── llm_analysis.py    # LLM-powered AML analysis
│   │   ├── report.py          # AML report generation
│   │   ├── review.py          # Transaction review workflow
│   │   ├── spatial_parser.py  # Spatial data extraction
│   │   ├── universal_parser.py# Universal statement parser
│   │   └── mt940_parser.py    # MT940/SWIFT format parser
│   │
│   ├── crypto/                # Cryptocurrency analysis module
│   │   └── ...                # Blockchain transaction analysis
│   │
│   ├── gsm/                   # GSM billing analysis module
│   │   └── ...                # Mobile/telecom call record analysis
│   │
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
├── scripts/                   # Developer tools
│   ├── keygen.py              # License key generator (Ed25519, developer-only)
│   └── pre-commit             # Git pre-commit hook
│
└── tests/                     # Pytest test suite (7+ files, 160+ tests)
    ├── conftest.py            # Fixtures: temp dirs, env overrides, sample files
    ├── test_multiuser.py      # Auth: passwords, users, sessions, audit, messages, deployment,
    │                          #   permissions, roles, JSON→SQLite migration, cross-store integration
    ├── test_db.py             # SQLite engine and schema tests
    ├── test_aml.py            # AML pipeline / normalization tests
    ├── test_api_integration.py    # FastAPI TestClient integration tests
    ├── test_document_processor.py # Document extraction tests
    ├── test_routers_chat.py       # Chat router tests
    └── test_settings.py           # Settings persistence tests
```

## Architecture

### Server (`webapp/server.py`)

This is the main application file. It contains:
- The FastAPI `app` instance and all middleware (UTF-8, auth, security headers, route access control)
- ~17 HTML page routes (transcription, diarization, chat, analysis, translation, settings, admin, etc.)
- 100+ JSON API endpoints under `/api/`
- `TaskManager` — in-process task queue that runs heavy work in subprocesses
- `GPUResourceManager` — priority-based GPU/CPU job scheduler to prevent VRAM exhaustion
- Model cache scanning and registry persistence
- Startup hooks: license validation, update notifications, encryption init, model scanning, backup scheduling

### Workers (subprocess-based)

Heavy ML tasks run as separate Python subprocesses. Workers communicate results via:
- JSON printed to stdout (parsed by TaskManager)
- Progress reported via `PROGRESS: <0-100>` on stderr
- HF tokens are redacted in subprocess command logs

### Data Storage

**SQLite database** (`data_www/aistate.db`) for structured data:
- **Users:** `users` table — accounts with UUID `user_id`, roles, password hashes, ban/lockout state, admin flags
- **Sessions:** `auth_sessions` table — active login sessions (token → user_id, expiry)
- **Auth audit log:** `auth_audit_log` table — auth events with browser fingerprints
- **Deployment config:** `deployment_config` table — single/multi-user mode
- **Messages:** `auth_messages` + `auth_message_reads` tables — Call Center messaging
- **AML data:** `projects`, `cases`, `statements`, `transactions`, `counterparties`, `risk_assessments`, `graph_nodes`, `graph_edges`, `baselines`, etc.
- **System config:** `system_config` table — key-value system settings (license state, update flags, etc.)

**Flat files** for non-structured data:
- **Projects:** `data_www/projects/{project_id}/project.json` + associated files (audio, transcript, diarized text, translations)
- **Settings:** `backend/.aistate/settings.json` (contains HF token — never commit)
- **License key:** `backend/.aistate/license.key` (signed license key file)
- **Model registries:** `data_www/projects/_global/asr_models.json`, `nllb_models.json`
- **Admin logs:** `backend/logs/YYYY-MM-DD/aistateHH-HH.log` (system), `aistate_userHH-HH.log` (auth events)
- **Password blacklist:** `backend/.aistate/password_blacklist.json` (custom admin-editable list)
- **Update backups:** `_backups/v{version}_{date}/` — full code backups before each update

### Frontend

Server-rendered HTML (Jinja2 templates) with vanilla JavaScript. No build step, no bundler, no npm. JS/CSS files are served directly from `webapp/static/`.

## Security

### Overview

AISTATEweb implements a multi-layered security model designed for deployment in trusted networks (LAN/VPN). The application does not require external internet access during operation.

### Authentication & Session Management

| Mechanism | Implementation | Details |
|---|---|---|
| **Password hashing** | PBKDF2-SHA256 | 600,000 iterations, 16-byte salt, via `webapp/auth/passwords.py` |
| **Session tokens** | UUID4 | Stored in SQLite `auth_sessions`, linked to `user_id`, with configurable expiry (default: 8h) |
| **Session cookie** | `aistate_session` | HttpOnly, SameSite=Lax |
| **Deployment modes** | Single-user / Multi-user | Single-user: no login required; Multi-user: full auth stack |

### Access Control

**Role hierarchy (3 tiers):**

```
Superadmin (Główny Opiekun)
  └── Full access to everything: users, system, license, updates, all modules
      Only this role can: manage licenses, install updates, rollback versions,
      manage backups, configure security policies, send Call Center messages

Admin (is_admin=True) + admin roles:
  ├── Architekt Funkcji — admin_settings module (server config, models, etc.)
  └── Strażnik Dostępu — user_mgmt module (user CRUD, bans, approvals)

Regular users + user roles:
  ├── Transkryptor — transcription, diarization, projects
  ├── Lingwista — translation, projects
  ├── Analityk — analysis (finance, AML, crypto, GSM), projects
  ├── Dialogista — chat, projects
  ├── Strateg — analysis, chat, projects
  └── Mistrz Sesji — transcription, diarization, translation, analysis, chat, projects
```

**Route-level access control** (`webapp/auth/permissions.py`):
- Each module defines allowed page routes and API prefixes
- Middleware (`_check_auth()`) verifies the user's role against the requested path
- Unauthorized requests receive HTTP 403

### Brute-Force Protection

| Feature | Configuration | Default |
|---|---|---|
| **Account lockout** | Auto-lock after N failed logins | 5 attempts |
| **Lockout duration** | Minutes before auto-unlock | 15 min |
| **Admin manual unlock** | Superadmin/Strażnik Dostępu can unlock | Always available |
| **Audit logging** | Every failed login recorded with IP + fingerprint | Enabled |

### Password Policy

Configurable strength levels in Settings → Security:

| Level | Requirements |
|---|---|
| `none` | No restrictions |
| `basic` | Min. 6 characters |
| `medium` | Min. 8 characters, uppercase + lowercase + digit |
| `strong` | Min. 12 characters, uppercase + lowercase + digit + special character |

Additional protections:
- **Built-in blacklist** — 1000+ common passwords (`builtin_passwords.txt`)
- **Custom blacklist** — admin-editable via UI (`password_blacklist.json`)
- **Password expiration** — configurable (0 = disabled, N = days until forced change)

### Security Headers

Applied via middleware to every HTTP response:

```
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
X-XSS-Protection: 1; mode=block
```

### Audit Trail

Every security-relevant event is logged to both SQLite and flat files:

| Event | Logged data |
|---|---|
| `login` | user_id, IP, browser fingerprint |
| `login_failed` | username (attempted), IP, fingerprint |
| `logout` | user_id, IP |
| `password_changed` | user_id, actor_id (if admin-initiated) |
| `account_locked` | user_id, reason (failed_attempts / admin_action) |
| `account_unlocked` | user_id, actor_id |
| `user_created` | new user_id, actor_id |
| `user_banned` | user_id, actor_id, reason |
| `user_unbanned` | user_id, actor_id |
| `user_deleted` | user_id, actor_id |
| `role_changed` | user_id, old_role, new_role, actor_id |

**Browser fingerprint** collected at login:
```json
{
  "browser": "Chrome 120",
  "os": "Windows 10",
  "screen": "1920x1080",
  "timezone": "Europe/Warsaw",
  "language": "pl-PL",
  "platform": "Win32"
}
```

Audit entry structure (in `auth_audit_log` table):
```json
{
  "id": "uuid",
  "timestamp": "ISO datetime",
  "event": "login|login_failed|logout|user_created|user_banned|...",
  "user_id": "user UUID",
  "username": "...",
  "ip": "...",
  "detail": "...",
  "actor_id": "admin UUID (for admin actions)",
  "actor_name": "admin username",
  "fingerprint": "{\"browser\": \"Chrome 120\", \"os\": \"Windows 10\", ...}"
}
```

### Data Encryption

Optional per-project encryption (`backend/encryption/`):

| Setting | Options |
|---|---|
| **Global toggle** | `encryption_enabled` (default: False) |
| **Encryption method** | `light` / `standard` / `maximum` |
| **Force on new projects** | `encryption_force_new_projects` |
| **Master key** | Initialized once, stored securely |

### Licensing & Feature Gating

The licensing module (`backend/licensing/`) provides cryptographic license validation:

| Component | Description |
|---|---|
| **Key format** | `AIST-<base64_json>.<base64_ed25519_signature>` |
| **Signature** | Ed25519 (asymmetric) — private key held only by developer |
| **Validation** | Public key embedded in application verifies signature |
| **Clock protection** | Last-seen-date tracking detects system clock rollback |
| **Kill switch** | `LICENSING_ENABLED` flag (default: `False` — all features unlocked) |
| **Feature gating** | `@require_feature()` decorator on API endpoints |
| **Storage** | `backend/.aistate/license.key` (signed key file) |

**License key payload:**
```json
{
  "lid": "PRO-ABC12345",
  "email": "client@company.com",
  "plan": "pro",
  "issued": "2026-03-22",
  "expires": "perpetual",
  "updates_until": "perpetual",
  "features": ["all"]
}
```

**Plans:**
- **Community** — all current features unlocked, perpetual (default when `LICENSING_ENABLED=False`)
- **Pro** — all features + future premium features
- **Enterprise** — all features + priority support

**Current state:** `LICENSING_ENABLED = False` — no restrictions enforced. The license panel is visible in Settings → License for informational purposes. When licensing is activated, `@require_feature()` decorators gate access to premium features.

### Software Update Security

Updates are distributed as signed `.zip` packages:

| Feature | Description |
|---|---|
| **Package format** | `.zip` containing code + `UPDATE_INFO.json` manifest |
| **Version control** | `min_version` check prevents incompatible updates |
| **Automatic backup** | Full code backup created before each update (`_backups/`) |
| **Rollback** | One-click restore to any previous version |
| **Data isolation** | Updates never modify `data_www/` or `backend/.aistate/` |
| **Graceful restart** | Configurable countdown (default: 5 min), cancel, restart-now |
| **Notification** | Call Center message sent to all users after update |

### Network Security Model

AISTATEweb is designed for **trusted network deployment** (LAN/VPN):

- **No external internet required** during normal operation
- **No TLS/HTTPS built-in** — expected to run behind a reverse proxy (nginx/Caddy) for HTTPS
- **No authentication on API** in single-user mode — trusted environment assumed
- **Ollama communication** — local HTTP (127.0.0.1:11434 by default)
- **HuggingFace tokens** — redacted in subprocess logs, stored in settings (not in code)
- **Bind address** — defaults to `127.0.0.1` (localhost only), configurable via `AISTATEWEB_HOST`

### Sensitive Files (do not commit)

| File | Contains |
|---|---|
| `backend/.aistate/settings.json` | HuggingFace token, application settings |
| `backend/.aistate/license.key` | Signed license key |
| `backend/.aistate/password_blacklist.json` | Custom password blacklist |
| `data_www/aistate.db` | SQLite database (users, password hashes, sessions, audit log) |
| `data_www/` | User project data (audio, transcripts, translations) |
| `.env` | Environment variables / credentials |
| `~/.aistate_private_key.pem` | Ed25519 private key (developer only, never in repo) |

## Environment Variables

| Variable | Purpose | Default |
|---|---|---|
| `AISTATEWEB_HOST` | Server bind address | `127.0.0.1` |
| `AISTATEWEB_PORT` | Server bind port | `8000` |
| `AISTATEWEB_DATA_DIR` | Project data + DB directory | `ROOT/data_www` |
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
- Auth store tests use per-test temporary SQLite databases via `set_db_path()` + `init_db()`
- No external services required for basic tests (Ollama, GPU, etc. are mocked or skipped)

## Key Conventions

- **Python 3.11+** with `from __future__ import annotations`
- **Type hints** used throughout (`typing` module: `Dict`, `List`, `Optional`, `Any`)
- **Dataclasses** for structured data (`Settings`, `UserRecord`, `Message`, `LicenseInfo`, task metadata, etc.)
- **Async endpoints** where appropriate; heavy sync work uses `run_in_threadpool` or subprocess workers
- **SQLite** for auth and AML data — WAL mode, `get_conn()` context manager, auto-commit/rollback
- **Multi-user authentication** — optional mode with role-based access, session cookies, rate limiting, account lockout, browser fingerprint logging, and audit trail (see `webapp/auth/`)
- **UI languages:** Polish (pl), English (en), Korean (ko); UI strings are in `webapp/static/lang/`
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

### Feature gating (licensing)

Use the `@require_feature()` decorator to gate endpoints behind a license:
```python
from backend.licensing.feature_gate import require_feature

@app.post("/api/tts/kokoro/generate")
@require_feature("tts_kokoro")
async def generate_kokoro(...):
    ...
```

When `LICENSING_ENABLED = False`, the decorator is a no-op (passes through).

### Authentication & Audit

Multi-user mode (`webapp/auth/`) provides:
- **Login/Logout/Register** via `webapp/routers/auth.py` (`/api/auth/*`)
- **User management** via `webapp/routers/users.py` (`/api/users/*`) — create, update, delete, ban/unban, approve/reject, lockout, password reset
- **Setup wizard** via `webapp/routers/setup.py` (`/api/setup/*`) — deployment mode selection, first admin creation
- **Call Center messaging** via `webapp/routers/messages.py` (`/api/messages/*`)
- **Roles:** user roles (Transkryptor, Lingwista, Analityk, Dialogista, Strateg, Mistrz Sesji) + admin roles (Architekt Funkcji, Strażnik Dostępu) + superadmin (Główny Opiekun)
- **Audit log** (`AuditStore`): records events (login, login_failed, logout, password_changed, account_locked, user_created, user_banned, etc.) to both SQLite (`auth_audit_log` table) and flat file logs (`backend/logs/`)
- **Browser fingerprint** collected at login: `browser`, `os`, `screen`, `timezone`, `language`, `platform` — stored as JSON in audit entries
- **Password policy** — configurable strength levels (none/basic/medium/strong), custom blacklist, built-in common password list
- **Account lockout** — auto-lock after N failed attempts, admin manual unlock
- **JSON→SQLite auto-migration** — on first startup after upgrade, legacy JSON files (`users.json`, `sessions.json`, `audit_log.json`, `deployment.json`, `messages.json`) are imported into SQLite and renamed to `.bak`

## License

MIT (main project). NLLB-200 models are CC-BY-NC 4.0 (non-commercial only). See `THIRD_PARTY_NOTICES.md` for full dependency licensing.

---
*Document version: 1.2 — Last updated: 2026-03-23*
