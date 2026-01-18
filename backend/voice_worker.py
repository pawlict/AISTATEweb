from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# Ensure project root is on sys.path when executed as a script
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD", "1")

def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--audio", required=True)
    p.add_argument("--model", required=True)
    p.add_argument("--lang", required=True)
    p.add_argument("--asr_engine", default="whisper")
    # diarization engine/model are passed by the webapp (Diaryzacja -> Diarize voice)
    # Keep them optional for backward compatibility.
    p.add_argument("--diar_engine", default="pyannote")
    p.add_argument("--diar_model", default="")
    # HF token is required only for pyannote; for other engines it can be empty.
    p.add_argument("--hf_token", default="")
    args = p.parse_args()

    # Diagnostics: show which interpreter is running the worker
    print(f"WORKER sys.executable: {sys.executable}", file=sys.stderr, flush=True)
    print(f"WORKER sys.path[0]: {sys.path[0] if sys.path else ''}", file=sys.stderr, flush=True)

    # Heavy deps inside worker process
    from backend.legacy_adapter import diarize_voice_asr_pyannote, diarize_voice_asr_nemo_diar

    def log(line: str) -> None:
        print(line, file=sys.stderr, flush=True)

    def progress(pct: int) -> None:
        print(f"PROGRESS:{int(pct)}", file=sys.stderr, flush=True)

    diar_engine = str(getattr(args, "diar_engine", "pyannote") or "pyannote").strip().lower()
    diar_model = str(getattr(args, "diar_model", "") or "").strip()

    if diar_engine in ("pyannote", "pynnote", "pyannote_audio"):
        res = diarize_voice_asr_pyannote(
            args.audio,
            args.asr_engine,
            args.model,
            args.lang,
            args.hf_token,
            diar_model=diar_model or None,
            log_cb=log,
            progress_cb=progress,
        )
    elif diar_engine in ("nemo_diar", "nemo-diar", "nemo_diarization"):
        res = diarize_voice_asr_nemo_diar(
            args.audio,
            args.asr_engine,
            args.model,
            args.lang,
            diar_model=diar_model or None,
            log_cb=log,
            progress_cb=progress,
        )
    else:
        raise SystemExit(f"Unknown diarization engine: {diar_engine}")

    print(json.dumps(res, ensure_ascii=False), flush=True)

if __name__ == "__main__":
    main()
