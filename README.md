# AISTATEweb (3.4.0 beta)

![Version](https://img.shields.io/badge/Version-3.3.0%20beta-orange)
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
- Export results to **TXT**, **HTML**, and **DOC**
- Structured reports combining transcription, diarization, and analysis
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
## beta 3.4.0 (translation update)
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
