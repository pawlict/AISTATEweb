# AISTATEweb (2.0 beta)

![Version](https://img.shields.io/badge/Version-2.0%20beta-orange)
![Python](https://img.shields.io/badge/Python-3.11%2B-blue)
![Platform](https://img.shields.io/badge/Platform-Web-lightgrey)
![License](https://img.shields.io/badge/License-MIT-green)

* * *

AISTATE Web is a web-based transcription and diarization tool with a project workflow.

#### Feedback / Support

If you have any issues, suggestions, or feature requests, please contact me at: **pawlict@proton.me**

* * *

## ✨ Main functionalities

  * Audio → text transcription (Whisper-based workflow).
  * Speaker diarization (who spoke when).
  * Project mode: store outputs and metadata inside a project directory.
  * Automatic save after processing:
    * transcription → `transcript.txt`
    * diarization → `diarized.txt`
  * Secure delete / wipe modes for project files (in progress):
    * Fast: delete (no overwrite)
    * Normal: pseudorandom wipe (x1)
    * Thorough: British HMG IS5 (x3)
    * Very thorough: Gutmann (x35)

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

### Security note

Never commit your Hugging Face token to GitHub. Treat it like a password.

* * *
## Program installation

```bash
sudo apt update
sudo apt install -y ffmpeg
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

Example (uvicorn):
    python -m uvicorn webapp.server:app --host 0.0.0.0 --port 8000

Open in browser:
    http://127.0.0.1:8000

* * *

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

## beta 2.1 Fix: Logging overhaul (Whisper + pyannote) + Export to file

This update focuses on improving observability and usability of application logs.
