# AISTATE Web — Information

**AISTATE Web** (*Artificial Intelligence Speech‑To‑Analysis‑Translation‑Engine*) is a web app for **transcription**, **speaker diarization**, **translation**, **GSM/BTS analysis**, and **AML financial analysis**.

---

## 🚀 What it does

- **Transcription** — Audio → text (Whisper, WhisperX, NeMo)
- **Diarization** — “who spoke when” + speaker segments (pyannote, NeMo)
- **Translation** — Text → other languages (NLLB‑200, fully offline)
- **Analysis (LLM / Ollama)** — summaries, insights, reports
- **GSM / BTS Analysis** — billing import, BTS map, routes, clusters, timeline
- **Financial Analysis (AML)** — bank statement parsing, risk scoring, anomaly detection
- **Logs & progress** — task monitoring + diagnostics

---

## 🆕 What's new in 3.7.1 beta

### 🔐 Cryptocurrency Analysis — Binance XLSX
- Extended analysis of Binance exchange data
- User behavior profiling (10 patterns: HODLer, Scalper, Day Trader, Swing Trader, Staker, Whale, Institutional, Alpha Hunter, Meme Trader, Bagholder)
- 18 forensic analysis cards:
  - Internal counterparties, Pay C2C, on-chain addresses, pass-through flows, privacy coins, access logs, payment cards
  - **NEW:** Temporal analysis (hourly distribution, bursts, dormancy), token conversion chains, structuring/smurfing detection, wash trading, fiat on/off ramp analysis, P2P analysis, deposit-to-withdrawal velocity, fee analysis, blockchain network analysis, extended security analysis (VPN/proxy detection)

---

## 🆕 What's new in 3.6 beta

### 📱 GSM / BTS Analysis
- Import billing data (CSV, XLSX, PDF)
- Interactive **BTS map** with multiple views: points, path, clusters, trips, BTS coverage, heatmap, timeline
- **Offline maps** — MBTiles support (raster PNG/JPG/WebP + vector PBF via MapLibre GL)
- **Overlay layers**: military bases, civilian airports, diplomatic posts (built-in data)
- **KML/KMZ import** — custom layers from Google Earth and other GIS tools
- Area selection (circle / rectangle) for spatial queries
- Contact graph, activity heatmap, top contacts analysis
- Map screenshots with watermark (online & offline maps + all overlay layers)

### 💰 Financial Analysis (AML)
- **Anti‑Money Laundering** pipeline for bank statements
- Automatic bank detection and PDF parsing: PKO BP, ING, mBank, Pekao SA, Santander, Millennium, Revolut (+ generic fallback)
- MT940 (SWIFT) statement format support
- Transaction normalization, rule-based classification, and risk scoring
- **Anomaly detection**: statistical baseline + ML (Isolation Forest)
- **Graph analysis** — counterparty network visualization
- Cross-account analysis for multi-account investigations
- Spending analysis, behavioral patterns, merchant categorization
- LLM-assisted analysis (prompt builder for Ollama models)
- HTML reports with charts
- Data anonymization profiles for safe sharing

---

## 🆕 What's new in 3.5.1 beta

- **Text proofreading** — side-by-side diff of original vs. corrected text, model picker (Bielik, PLLuM, Qwen3), expanded mode.
- **Redesigned project view** — card grid layout, team info, per-card invitations.
- Minor UI and stability fixes.

---

## 🆕 What's new in 3.2 beta

- **Translation module (NLLB)** – local multilingual translation (incl. PL/EN/ZH and more).
- **NLLB settings** – model selection, runtime options, model cache visibility.

---

## 📦 Where models are downloaded from

AISTATE web does **not** ship model weights in the repository. Models are downloaded on-demand and cached locally (depending on the module):

- **Hugging Face Hub**: pyannote + NLLB (standard HF cache).
- **NVIDIA NGC / NeMo**: NeMo ASR/diarization models (NeMo/NGC caching behavior).
- **Ollama**: LLM models pulled by the Ollama service.
---

## 🔐 Security & user management

AISTATE Web supports two deployment modes:

- **Single-user mode** — simplified, no login required (local / self-hosted).
- **Multi-user mode** — full authentication, authorization, and account management (designed for 50–100 concurrent users).

### 👥 Roles & permissions

**User roles** (module access):
- Transkryptor, Lingwista, Analityk, Dialogista, Strateg, Mistrz Sesji

**Administrative roles:**
- **Architekt Funkcji** — application settings management
- **Strażnik Dostępu** — user account management (create, approve, ban, reset passwords)
- **Główny Opiekun (superadmin)** — full access to all modules and admin functions

### 🔑 Security mechanisms

- **Password hashing**: PBKDF2-HMAC-SHA256 (260,000 iterations)
- **Password policy**: configurable (none / basic / medium / strong); admins always require strong passwords (12+ chars, mixed case, digit, special char)
- **Password blacklist**: built-in + admin-managed custom list
- **Password expiry**: configurable (force change after X days)
- **Account lockout**: after configurable failed attempts (default 5), auto-unlock after 15 min
- **Rate limiting**: login and registration throttled (5 per minute per IP)
- **Sessions**: secure tokens (secrets module), HTTPOnly + SameSite=Lax cookies, configurable timeout (default 8h)
- **Recovery phrase**: 12-word BIP-39 mnemonic (~132 bits of entropy) for self-service password recovery
- **User banning**: permanent or temporary, with reason
- **Security headers**: X-Content-Type-Options, X-Frame-Options, X-XSS-Protection, Referrer-Policy

### 📝 Audit & logging

- Full event log: logins, failed attempts, password changes, account creation/deletion, bans, unlocks
- IP address and browser fingerprint recording
- File-based logs with hourly rotation + SQLite database
- User login history + full audit trail for administrators

### 📋 Registration & approval

- Self-registration with mandatory admin approval (Strażnik Dostępu role)
- Mandatory password change on first login
- Recovery phrase generated and displayed once

---

## ⚖️ Licensing

### App license

- **AISTATE Web**: **MIT License** (AS IS).

### Engines / libraries (code licenses)

- **OpenAI Whisper**: **MIT**.  
- **pyannote.audio**: **MIT**.  
- **WhisperX**: **MIT** (wrapper/aligner – package-version dependent).  
- **NVIDIA NeMo Toolkit**: **Apache 2.0**.  
- **Ollama (server/CLI repository)**: **MIT**.

### Model licenses (weights / checkpoints)

> Model weights are licensed **separately** from the code. Always verify the model card / provider terms.

- **Meta NLLB‑200 (NLLB)**: **CC‑BY‑NC 4.0** (non-commercial restrictions).  
- **pyannote pipelines (HF)**: model-dependent; some are **gated** and require accepting terms on the model page.  
- **NeMo models (NGC/HF)**: model-dependent; some checkpoints are published under licenses such as **CC‑BY‑4.0**, while some NGC models state coverage under the NeMo Toolkit license — check each model page.  
- **LLMs via Ollama**: model-dependent, for example:
  - **Meta Llama 3**: **Meta Llama 3 Community License** (redistribution/attribution + AUP).  
  - **Mistral 7B**: **Apache 2.0**.  
  - **Google Gemma**: **Gemma Terms of Use** (contractual terms + policy).

### Maps & geographic data

- **Leaflet** (map engine): **BSD‑2‑Clause** — https://leafletjs.com
- **MapLibre GL JS** (PBF vector rendering): **BSD‑3‑Clause** — https://maplibre.org
- **OpenStreetMap** (online map tiles): map data © OpenStreetMap contributors, **ODbL 1.0** — attribution required
- **OpenMapTiles** (PBF tile schema): **BSD‑3‑Clause** (schema); data under ODbL
- **html2canvas** (screenshots): **MIT**

### Important

- This page is a summary. See **THIRD_PARTY_NOTICES.md** in the repository for a complete list.
- For commercial / organizational use, pay special attention to **NLLB (CC‑BY‑NC)** and your chosen LLM model licenses.

---

## 💬 Feedback / support

Issues, suggestions, feature requests: **pawlict@proton.me**
