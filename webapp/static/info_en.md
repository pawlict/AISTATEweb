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

## 🔐 Privacy & security

- Designed primarily for **local / self-hosted** workflows.
- Treat tokens (e.g., Hugging Face) like passwords — **never** commit them to GitHub.
- Respect legal requirements and model/provider terms (HF/NGC/Meta/Google).

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
