from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path


def _stderr(msg: str) -> None:
    # Everything except final JSON must go to stderr.
    print(msg, file=sys.stderr, flush=True)


def _progress(pct: int) -> None:
    # Optional hook for UI progress parsing.
    print(f"PROGRESS: {pct}", file=sys.stderr, flush=True)


# When the worker is executed as a file (python backend/transcribe_worker.py)
# Python sets sys.path[0] to the backend/ directory. Add project root so
# imports like "from backend.legacy_adapter" work reliably.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audio", required=True)
    parser.add_argument("--engine", default="whisper")
    parser.add_argument("--model", required=True)
    parser.add_argument("--lang", required=True)
    args = parser.parse_args()

    _stderr(f"WORKER sys.executable: {sys.executable}")
    _stderr(f"WORKER cwd: {os.getcwd()}")
    _stderr(f"WORKER sys.path[0]: {sys.path[0] if sys.path else ''}")

    if shutil.which("ffmpeg") is None:
        _stderr("ERROR: ffmpeg not found. Install: sudo apt install -y ffmpeg")
        # Non-zero exit causes server to mark task as error.
        raise SystemExit(2)    # Import here to avoid importing heavy deps at startup.
    from backend.legacy_adapter import whisper_transcribe, nemo_transcribe

    eng = str(getattr(args, 'engine', 'whisper') or 'whisper').strip().lower()
    if eng in ('nemo','nvidia','ne-mo','nemo_asr','nemo-asr'):
        res = nemo_transcribe(args.audio, args.model, args.lang, log_cb=_stderr, progress_cb=_progress)
    else:
        res = whisper_transcribe(args.audio, args.model, args.lang, log_cb=_stderr, progress_cb=_progress)

    # JSON-only on stdout
    print(json.dumps(res, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
