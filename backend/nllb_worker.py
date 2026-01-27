"""NLLB worker

This worker is used by the Admin -> NLLB Settings page.

Actions:
  - install_deps: install/upgrade NLLB translation dependencies (Transformers + SentencePiece)
  - predownload: download/cache selected NLLB model weights into HuggingFace cache

The worker prints progress markers to STDERR in the format:
  PROGRESS: <0-100>
and prints a JSON dict to STDOUT when finished.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NLLB_MARKERS_DIR = (ROOT / "backend" / "models_cache" / "nllb").resolve()


def eprint(msg: str) -> None:
    sys.stderr.write(str(msg).rstrip("\n") + "\n")
    sys.stderr.flush()


def progress(pct: int) -> None:
    pct = max(0, min(100, int(pct)))
    eprint(f"PROGRESS: {pct}")


def _safe_marker_name(model_id: str) -> str:
    s = (model_id or "").strip()
    return re.sub(r"[^a-zA-Z0-9._-]+", "_", s)[:180] or "model"


def mark_nllb_installed(model_id: str, mode: str) -> None:
    """Write a deterministic marker for UI installed state."""
    try:
        NLLB_MARKERS_DIR.mkdir(parents=True, exist_ok=True)
        name = _safe_marker_name(model_id)
        p = NLLB_MARKERS_DIR / f"{name}.json"
        payload = {
            "model": str(model_id),
            "mode": str(mode),
            "engine": "nllb",
            "installed_at": _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "python": sys.executable,
        }
        p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        return


def _pip_install(pkgs: list[str]) -> None:
    if not pkgs:
        return
    cmd = [sys.executable, "-m", "pip", "install", "-U"] + list(pkgs)
    eprint("pip: " + " ".join(cmd))
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
    assert p.stdout is not None
    for line in p.stdout:
        s = line.rstrip("\n")
        if s:
            eprint(s)
    rc = p.wait()
    if rc != 0:
        raise SystemExit(f"pip failed with exit code {rc}")


def install_deps() -> None:
    """Install dependencies required for NLLB via transformers."""
    progress(5)
    pkgs = [
        "transformers",
        "sentencepiece",
        "sacremoses",
        "accelerate",
    ]
    _pip_install(pkgs)
    progress(100)


def predownload(model_id: str, mode: str) -> None:
    """Download/cache model weights into HF cache."""
    progress(5)
    if not model_id:
        raise SystemExit("Missing model")

    # Import lazily so the worker can install deps first.
    try:
        import torch  # type: ignore

        device = "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        device = "cpu"

    eprint(f"nllb: predownload model='{model_id}' (mode={mode}) device={device}")
    progress(20)

    from transformers import AutoModelForSeq2SeqLM, AutoTokenizer  # type: ignore

    # Download tokenizer + model.
    _ = AutoTokenizer.from_pretrained(model_id)
    progress(40)
    _ = AutoModelForSeq2SeqLM.from_pretrained(model_id)
    progress(90)

    # Marker for UI.
    mark_nllb_installed(model_id, mode=mode)
    progress(100)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--action", required=True, choices=["install_deps", "predownload"])
    ap.add_argument("--model", default="")
    ap.add_argument("--mode", default="fast")
    args = ap.parse_args()

    if args.action == "install_deps":
        install_deps()
        print(json.dumps({"ok": True, "action": "install_deps"}))
        return 0

    # predownload
    predownload(str(args.model), mode=str(args.mode or "fast"))
    print(json.dumps({"ok": True, "action": "predownload", "model": str(args.model), "mode": str(args.mode)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
