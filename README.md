# AISTATEweb (3.7.1 beta)

![Version](https://img.shields.io/badge/Version-3.7.1%20beta-orange)
![Python](https://img.shields.io/badge/Python-3.11%2B-blue)
![Platform](https://img.shields.io/badge/Platform-Web-lightgrey)
![License](https://img.shields.io/badge/License-MIT-green)

* * *

AISTATE Web is a web-based transcription and diarization tool with a project workflow.

#### Feedback / Support

If you have any issues, suggestions, or feature requests, please contact me at: **pawlict@proton.me**

* * *

## 🚀 Main Functionalities

### 🎙️ Speech Processing
- Automatic speech recognition (ASR) using **Whisper**, **WhisperX**, and **NVIDIA NeMo**
- Support for multilingual audio (PL / EN / UA / RU / BY and more)
- Offline and local model execution (no cloud dependency)
- High-quality transcription optimized for long recordings

### 🧩 Speaker Diarization
- Advanced speaker diarization using **pyannote** and **NeMo Diarization**
- Automatic speaker detection and segmentation
- Support for multi-speaker conversations (meetings, interviews, calls)
- Configurable diarization engines and models

### 🌍 Multilingual Translation
- Neural machine translation powered by **NLLB-200**
- Fully offline translation pipeline
- Flexible source and target language selection
- Designed for OSINT and multilingual analysis workflows

### 🧠 Intelligence & Analysis
- AI-assisted content analysis using local **LLM models**
- Transformation of raw speech and text into structured insights
- Support for analytical reports and intelligence-oriented workflows

### 📱 GSM / BTS Analysis (NEW)
- Import and analysis of **GSM billing data** (CSV, XLSX, PDF)
- Interactive **map visualization** of BTS locations (Leaflet + OpenStreetMap)
- **Offline maps** support via MBTiles (raster PNG/JPG/WebP + vector PBF via MapLibre GL)
- Multiple map views: all points, path, clusters, trips, BTS coverage, heatmap, timeline
- **Area selection** (circle / rectangle) for spatial queries
- **Overlay layers**: military bases, civilian airports, diplomatic posts (built-in data)
- **KML/KMZ import** — custom overlay layers from Google Earth and other GIS tools
- Map screenshots with watermark (online & offline maps + all overlay layers)
- Contact graph, activity heatmap, top contacts analysis
- Timeline player with month/day animation

### 💰 AML — Financial Analysis (NEW)
- **Anti-Money Laundering** analysis pipeline for bank statements
- Automatic bank detection and PDF parsing for Polish banks:
  PKO BP, ING, mBank, Pekao SA, Santander, Millennium, Revolut (+ generic fallback)
- MT940 (SWIFT) statement format support
- Transaction normalization, rule-based classification, and risk scoring
- **Anomaly detection**: statistical baseline + ML-based (Isolation Forest)
- **Graph analysis** — counterparty network visualization
- Cross-account analysis for multi-account investigations
- Entity resolution and counterparty memory (persistent labels/notes)
- Spending analysis, behavioral patterns, merchant categorization
- LLM-assisted analysis (prompt builder for Ollama models)
- HTML report generation with charts
- Data anonymization profiles for safe sharing

### 🔗 Crypto — Blockchain Transaction Analysis *(experimental)*
- Offline analysis of **BTC** and **ETH** cryptocurrency transactions
- Import from **WalletExplorer.com** CSV and multiple exchange formats (Binance, Etherscan, Kraken, Coinbase, and more)
- Automatic format detection from CSV column signatures
- Risk scoring with pattern detection: peel chain, dust attack, round-trip, smurfing
- OFAC sanctioned address database and known DeFi contract lookup
- Interactive **transaction flow graph** (Cytoscape.js)
- Charts: balance timeline, monthly volume, daily activity, counterparty ranking (Chart.js)
- LLM-assisted narrative analysis via Ollama
- *This module is currently in early testing phase — features and data formats may change*

### ⚙️ GPU & Resource Management
- Integrated **GPU Resource Manager**
- Automatic task scheduling and prioritization (ASR, diarization, analysis)
- Safe execution of concurrent tasks without GPU overload
- CPU fallback when GPU resources are unavailable

### 📂 Project-Based Workflow
- Project-oriented data organization
- Persistent storage of audio, transcripts, translations, and analyses
- Reproducible analytical workflows
- Separation of user data and system processes

### 📄 Reporting & Export
- Export results to **TXT**, **HTML**, **DOC**, and **PDF**
- Structured reports combining transcription, diarization, and analysis
- AML financial reports with charts and risk indicators
- Ready-to-use outputs for research, documentation, and investigations

### 🌐 Web-Based Interface
- Modern web UI (**AISTATEweb**)
- Real-time task status and logs
- Multi-language interface (PL / EN)
- Designed for both standalone and multi-user environments (soon)


* * *

## Requirements

### System (Linux)

Install base packages (example):
    sudo apt update -y
    sudo apt install -y python3 python3-venv python3-pip git

### Python

Recommended: Python 3.11+.

* * *
## pyannote / Hugging Face (required for diarization)

Diarization uses **pyannote.audio** pipelines hosted on the **Hugging Face Hub**. Some pyannote models are **gated**, which means you must:
  * have a Hugging Face account,
  * accept the user conditions on the model pages,
  * generate a **READ** access token and provide it to the app.

### Step-by-step (token + permissions)

  1. Create / sign in to your Hugging Face account.
  2. Open the required pyannote model pages and click **“Agree / Accept”** (user conditions).  
     Typical models you may need to accept (depending on version):
     * `pyannote/segmentation` (or `pyannote/segmentation-3.0`)
     * `pyannote/speaker-diarization` (or `pyannote/speaker-diarization-3.1`)
  3. Go to your Hugging Face **Settings → Access Tokens** and create a new token with role **READ**.
  4. Paste the token into AISTATE Web settings (or provide it as an environment variable — depending on your setup).
* * *
## Program installation linuks 

```bash
sudo apt update
sudo apt install -y ffmpeg
curl -fsSL https://ollama.com/install.sh | sh

```
```
mkdir -p ~/projects
cd ~/projects
git clone https://github.com/pawlict/AISTATEweb.git
cd AISTATEweb

python3 -m venv .venv
source .venv/bin/activate

python -m pip install --upgrade pip wheel setuptools
pip install -r requirements.txt
```
* * *

## Run
```
python3 AISTATEweb.py
```
Example (uvicorn):
    python -m uvicorn webapp.server:app --host 0.0.0.0 --port 8000

Open in browser:
    http://127.0.0.1:8000

* * *
# AISTATEweb — Windows (WSL2 + NVIDIA GPU) Setup

Important: in WSL2 the **NVIDIA driver is installed on Windows**, not inside the Linux distribution. Installing Linux `nvidia-driver-*` packages in WSL2 can cause CUDA/NVML mismatches and unstable behavior. 

---
## 1. Windows prerequisites

1. Enable WSL2 (Windows Features / PowerShell).
2. Update WSL and reboot the WSL VM:
   ```powershell
   wsl --update
   wsl --shutdown
   ```
3. Install the **NVIDIA Windows driver** that supports WSL2 (Game Ready / Studio) and reboot Windows.

---

## 2. Create / update your WSL distro

Use Ubuntu/Debian/Kali (Ubuntu LTS is usually the easiest for packages).

Inside WSL:
```bash
sudo apt update && sudo apt upgrade -y
```

---

## 3. GPU sanity check inside WSL2 (critical)

### 3.1 Confirm you are really on WSL2
```bash
uname -a
grep -i microsoft /proc/version || true
```

### 3.2 `nvidia-smi` should come from the WSL stub
In WSL2 the expected `nvidia-smi` is typically located at:
`/usr/lib/wsl/lib/nvidia-smi`

Check:
```bash
which nvidia-smi
ls -l /usr/lib/wsl/lib/nvidia-smi || true
nvidia-smi
```

If `which nvidia-smi` points to `/usr/bin/nvidia-smi` via `update-alternatives`, you likely installed NVIDIA user-space packages inside the distro (not recommended for WSL2).

### 3.3 Recommended fix: remove NVIDIA packages from the Linux distro
> WSL2 uses the Windows driver; keeping Linux `nvidia-*` packages often creates mismatched NVML/CUDA tooling.

```bash
sudo apt purge -y 'nvidia-*' 'libnvidia-*'
sudo apt autoremove --purge -y
```

Ensure the WSL stub path is visible:
```bash
echo 'export PATH=/usr/lib/wsl/lib:$PATH' | sudo tee /etc/profile.d/wsl-gpu.sh >/dev/null
echo 'export LD_LIBRARY_PATH=/usr/lib/wsl/lib:${LD_LIBRARY_PATH}' | sudo tee -a /etc/profile.d/wsl-gpu.sh >/dev/null
source /etc/profile.d/wsl-gpu.sh
```

Re-check:
```bash
which nvidia-smi
nvidia-smi
```

---

## 4. System dependencies (WSL)

```bash
sudo apt update
sudo apt install -y git python3 python3-venv python3-pip ffmpeg
```

---

## 5. Get the code

```bash
mkdir -p ~/projects
cd ~/projects
git clone https://github.com/pawlict/AISTATEweb.git
cd AISTATEweb
```

---

## 6. Python venv

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip setuptools wheel
```

---

## 7. Install PyTorch (CUDA build)

Install the CUDA-enabled PyTorch wheels from the official PyTorch index (example uses **cu128**):
```bash
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128
```

Verify GPU access:
```bash
python -c "import torch; print('cuda:', torch.cuda.is_available()); print('gpu:', torch.cuda.get_device_name(0) if torch.cuda.is_available() else None)"
```

---

## 8. Install AISTATEweb requirements

```bash
pip install -r requirements.txt
```

---

## 9. Run AISTATEweb

```bash
python3 AISTATEweb.py
```
Open in browser: http://127.0.0.1:8000

---

## References

- NVIDIA: CUDA on WSL User Guide  
  https://docs.nvidia.com/cuda/wsl-user-guide/index.html
- Microsoft Learn: CUDA in WSL  
  https://learn.microsoft.com/windows/ai/directml/gpu-cuda-in-wsl
- PyTorch: Get Started (installation selector)  
  https://pytorch.org/get-started/locally/





## Project structure (important files)

  * `webapp/server.py` — backend (API, project handling, wipe implementation)
  * `webapp/static/app.js` — frontend logic
  * `webapp/templates/` — HTML templates
  * `projects/` (or your configured project dir) — created projects with:
    * `project.json`
    * `transcript.txt`
    * `diarized.txt`

* * *
“This project is MIT licensed (AS IS). Third-party components are licensed separately — see THIRD_PARTY_NOTICES.md.”

## beta 3.7.1
- **Cryptocurrency Analysis — Binance** — extended analysis of Binance exchange data
- User behavior profiling (10 patterns: HODLer, Scalper, Day Trader, Swing Trader, Staker, Whale, Institutional, Alpha Hunter, Meme Trader, Bagholder)
- 18 forensic analysis cards: internal counterparties, Pay C2C, on-chain addresses, pass-through flows, privacy coins, access logs, payment cards + **NEW:** temporal analysis, token conversion chains, structuring/smurfing detection, wash trading, fiat on/off ramp, P2P analysis, deposit-to-withdrawal velocity, fee analysis, blockchain network analysis, extended security (VPN/proxy)
- All record limits removed — full data with scrollable tables
- Reports download as files (HTML, TXT, DOCX)

## beta 3.7
- **Crypto Analysis** *(experimental)* — offline blockchain transaction analysis module (BTC/ETH), CSV import (WalletExplorer + 16 exchange formats), risk scoring, pattern detection, flow graph, Chart.js charts, LLM narrative — currently in deep testing phase
- Auto-detect source language on file upload and text paste (translation module)
- Multi-language export (all translated languages at once)
- Fixed DOCX export filenames (underscores issue)
- Fixed MMS TTS waveform synthesis error
- Fixed Korean language missing from translation results

## beta 3.6
- **GSM / BTS Analysis** — full GSM billing analysis module with interactive maps, timeline, clusters, trips, heatmap, contact graph
- **AML Financial Analysis** — anti-money laundering pipeline: PDF parsing (7 Polish banks + MT940), rule-based + ML anomaly detection, graph analysis, risk scoring, LLM-assisted reports
- **Map overlays** — military bases, airports, diplomatic posts + custom KML/KMZ import
- **Offline maps** — MBTiles support (raster + PBF vector via MapLibre GL)
- **Map screenshots** — full map capture including all tile layers, overlays, and KML markers
- Fixed KML/KMZ parser (ElementTree falsy element bug)
- Fixed MapLibre GL canvas screenshot (preserveDrawingBuffer)
- Fixed info page language switching

## beta 3.5.1/3
- Fixed project saving/assignment.
- Improved parser for ING banking

## beta 3.5.0 (SQLite)
- JSON -> SQLite migration
 
## beta 3.4.0 
- Added multiuser

## beta 3.2.3 (translation update)
- Added Translation module 
- Added NLLB Settings page
- Added the ability to change task priorities
- Added Chat LLM
- Background sound analysis

## beta 3.0 - 3.1
- LLM Ollama modules for data analysis introduced
- GPU Assignment / Scheduling (Update)

This update introduces a **GPU Resource Manager** concept in the UI and internal flow to reduce the risk of **overlapping GPU-heavy workloads** (e.g., running diarization + transcription + LLM analysis at the same time).

### What problem this solves
When multiple GPU tasks start concurrently, it can lead to:
- sudden VRAM exhaustion (OOM),
- driver resets / CUDA errors,
- extremely slow processing due to contention,
- unstable behavior when multiple users trigger jobs at the same time.

### Backwards compatibility
- No changes in the functional layout of existing tabs.
- Only GPU admission/coordination and admin labeling were updated.

## beta 2.1 -2.2 

- Change of block editing methodology
- This update focuses on improving observability and usability of application logs.
- Fix: Logging overhaul (Whisper + pyannote) + Export to file
