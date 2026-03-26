"""ASR worker

This worker is used by the Admin -> ASR Settings page.
It runs potentially long operations in a subprocess so the FastAPI server stays responsive.

Actions:
  - install: pip install/upgrade selected component
  - predownload: download/cache model assets for Whisper / NeMo / pyannote

The worker prints progress markers to STDERR in the format:
  PROGRESS: <0-100>
and prints a JSON dict to STDOUT when finished.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
import re
import datetime as _dt
from typing import Any, Dict


# --- NeMo install markers (deterministic "installed" state for the UI) ---
# NeMo caching is sometimes directory/hash-based, so simple filesystem heuristics may fail.
# After a successful from_pretrained(), we write a small marker JSON under:
#   backend/models_cache/nemo/<model>.json
# The FastAPI server reads these markers to label models as installed.

ROOT = Path(__file__).resolve().parents[1]
NEMO_MARKERS_DIR = (ROOT / 'backend' / 'models_cache' / 'nemo').resolve()
PYANNOTE_MARKERS_DIR = (ROOT / 'backend' / 'models_cache' / 'pyannote').resolve()


def _safe_marker_name(model_id: str) -> str:
    s = (model_id or '').strip()
    # Keep it filesystem-safe and reasonably readable
    return re.sub(r'[^a-zA-Z0-9._-]+', '_', s)[:180] or 'model'


def mark_nemo_installed(model_id: str, engine: str) -> None:
    try:
        NEMO_MARKERS_DIR.mkdir(parents=True, exist_ok=True)
        name = _safe_marker_name(model_id)
        p = NEMO_MARKERS_DIR / f"{name}.json"
        payload = {
            'model': str(model_id),
            'engine': str(engine),
            'installed_at': _dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'python': sys.executable,
        }
        p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    except Exception:
        # best effort only
        return


def mark_pyannote_installed(pipeline_id: str) -> None:
    """Mark pyannote pipeline as successfully installed."""
    try:
        PYANNOTE_MARKERS_DIR.mkdir(parents=True, exist_ok=True)
        name = _safe_marker_name(pipeline_id)
        p = PYANNOTE_MARKERS_DIR / f"{name}.json"
        payload = {
            'pipeline': str(pipeline_id),
            'engine': 'pyannote',
            'installed_at': _dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'python': sys.executable,
        }
        p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    except Exception:
        # best effort only
        return



def eprint(msg: str) -> None:
    sys.stderr.write(str(msg).rstrip("\n") + "\n")
    sys.stderr.flush()


def progress(pct: int) -> None:
    pct = max(0, min(100, int(pct)))
    eprint(f"PROGRESS: {pct}")


def pip_install(component: str) -> None:
    """Install/upgrade packages for the selected ASR component."""
    # Keep the mapping conservative; users can customize later.
    pkgs = {
        # OpenAI Whisper (classic)
        "whisper": ["openai-whisper"],
        # NeMo ASR (torch + nemo_toolkit)
        "nemo": ["nemo_toolkit[asr]", "nv-one-logger-core", "nv-one-logger-training-telemetry", "nv-one-logger-pytorch-lightning-integration"],
        # pyannote
        "pyannote": ["pyannote.audio"],
    }
    targets = pkgs.get(component)
    if not targets:
        raise SystemExit(f"Unknown component: {component}")

    cmd = [sys.executable, "-m", "pip", "install", "-U"] + targets
    eprint("pip: " + " ".join(cmd))
    progress(5)
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
    assert p.stdout is not None
    for line in p.stdout:
        s = line.rstrip("\n")
        if s:
            eprint(s)
    rc = p.wait()
    if rc != 0:
        raise SystemExit(f"pip failed with exit code {rc}")
    progress(100)



def _pip_install_pkgs(pkgs: list[str]) -> None:
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


def ensure_nemo_onelogger_deps() -> None:
    """Make NeMo import-safe by neutralizing optional OneLogger integration.

    On some environments (especially newer Python / lightning / overrides combos),
    NeMo's optional OneLogger integration can raise import-time errors.

    We don't need OneLogger for inference/predownload, so we inject lightweight stubs
    to satisfy NeMo imports and keep the worker functional.
    """
    import importlib
    import sys
    import types

    def _ensure_module(name: str) -> types.ModuleType:
        mod = sys.modules.get(name)
        if mod is None:
            mod = types.ModuleType(name)
            sys.modules[name] = mod
        return mod

    def _install_stubs(reason: str) -> None:
        # 1) Prevent NeMo from importing its real one_logger_callback implementation.
        # If this module exists in sys.modules, import will short-circuit and avoid
        # importing nv_one_logger.* entirely.
        m = _ensure_module('nemo.lightning.one_logger_callback')
        if not hasattr(m, 'OneLoggerNeMoCallback'):
            class OneLoggerNeMoCallback:  # noqa: D401
                """Stub callback used only to satisfy NeMo import paths."""

                def __init__(self, *args, **kwargs):
                    pass

            m.OneLoggerNeMoCallback = OneLoggerNeMoCallback

        # 2) Also provide a minimal nv_one_logger hierarchy because some NeMo versions
        # import it directly.
        _ensure_module('nv_one_logger')
        _ensure_module('nv_one_logger.api')
        cfg = _ensure_module('nv_one_logger.api.config')
        if not hasattr(cfg, 'OneLoggerConfig'):
            class OneLoggerConfig:  # pragma: no cover
                def __init__(self, *args, **kwargs):
                    pass
            cfg.OneLoggerConfig = OneLoggerConfig

        _ensure_module('nv_one_logger.training_telemetry')
        _ensure_module('nv_one_logger.training_telemetry.api')
        cb = _ensure_module('nv_one_logger.training_telemetry.api.callbacks')
        if not hasattr(cb, 'on_app_start'):
            def on_app_start(*args, **kwargs):
                return None
            def on_app_end(*args, **kwargs):
                return None
            cb.on_app_start = on_app_start
            cb.on_app_end = on_app_end

        _ensure_module('nv_one_logger.training_telemetry.integration')
        ptl = _ensure_module('nv_one_logger.training_telemetry.integration.pytorch_lightning')
        if not hasattr(ptl, 'TimeEventCallback'):
            class TimeEventCallback:  # pragma: no cover
                def __init__(self, *args, **kwargs):
                    pass
            ptl.TimeEventCallback = TimeEventCallback

        eprint(f"nemo: OneLogger integration unavailable ({reason}); using stubs (safe for inference).")

    # Fast path: if nv_one_logger seems healthy, do nothing.
    try:
        importlib.import_module('nv_one_logger.training_telemetry.integration.pytorch_lightning')
        importlib.import_module('nv_one_logger.api.config')
        importlib.import_module('nv_one_logger.training_telemetry.api.callbacks')
        return
    except Exception as e:  # noqa: BLE001
        # Clear partially imported nv_one_logger modules to avoid inconsistent state.
        for k in list(sys.modules.keys()):
            if k.startswith('nv_one_logger.'):
                sys.modules.pop(k, None)
        _install_stubs(f"{type(e).__name__}: {e}")



def predownload_whisper(model: str) -> None:
    """Download Whisper model weights into cache."""
    progress(5)
    try:
        import torch  # type: ignore

        device = "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        device = "cpu"

    eprint(f"whisper: loading model='{model}' on device={device}")
    progress(20)
    import whisper  # type: ignore

    _ = whisper.load_model(model, device=device)
    progress(100)


def predownload_nemo(model: str) -> None:
    progress(5)
    ensure_nemo_onelogger_deps()
    eprint(f"nemo: from_pretrained('{model}')")
    progress(20)
    from nemo.collections.asr.models import ASRModel  # type: ignore
    _ = ASRModel.from_pretrained(model_name=model)
    # Mark as installed for the UI (best-effort)
    mark_nemo_installed(model, engine='nemo')
    progress(100)


def _try_from_pretrained(candidates, model: str) -> None:
    """Best-effort loader for different NeMo model classes across versions.

    1) Try a curated list of known classes.
    2) If none work, do a dynamic scan for classes that expose from_pretrained and
       look related to diarization/speaker.
    """
    import importlib
    import inspect

    last_err = None

    def _call_from_pretrained(cls):
        nonlocal last_err
        try:
            _ = cls.from_pretrained(model_name=model)
            return True
        except TypeError:
            try:
                _ = cls.from_pretrained(model)
                return True
            except Exception as e:  # noqa: BLE001
                last_err = e
                return False
        except Exception as e:  # noqa: BLE001
            last_err = e
            return False

    # 1) Curated candidates
    for module_path, cls_name in candidates:
        try:
            mod = importlib.import_module(module_path)
            cls = getattr(mod, cls_name)
        except Exception as e:  # noqa: BLE001
            last_err = e
            continue

        if _call_from_pretrained(cls):
            eprint(f"nemo: loaded '{model}' via {module_path}.{cls_name}")
            return

    # 2) Dynamic scan fallback
    scan_modules = list(dict.fromkeys([
        'nemo.collections.asr.models',
        'nemo.collections.asr.models.diarization_models',
        'nemo.collections.asr.models.msdd_models',
        'nemo.collections.asr.models.speaker_label_models',
        'nemo.collections.asr.models.clustering_diarizer',
        'nemo.collections.asr.models.label_models',
    ]))

    scanned = 0
    for mp in scan_modules:
        try:
            mod = importlib.import_module(mp)
        except Exception as e:  # noqa: BLE001
            last_err = e
            continue

        for name, obj in vars(mod).items():
            if not inspect.isclass(obj):
                continue
            if not hasattr(obj, 'from_pretrained'):
                continue

            lname = name.lower()
            if not any(k in lname for k in ('diar', 'speaker', 'msdd', 'clustering', 'titanet', 'label')):
                continue

            scanned += 1
            if _call_from_pretrained(obj):
                eprint(f"nemo: loaded '{model}' via {mp}.{name} (dynamic)")
                return

            # Safety cap: avoid scanning too many classes
            if scanned > 80:
                break
        if scanned > 80:
            break

    raise RuntimeError(f"nemo: unable to load '{model}' via known classes") from last_err



def predownload_nemo_diarization(model: str) -> None:
    """Download/cache NeMo diarization assets.

    Supported presets:
      - diar_msdd_telephonic
      (Speaker-embedding presets like "titanet_large" were removed from the UI.)

    We intentionally implement this as a best-effort loader, because NeMo
    moved diarization classes between versions.
    """
    progress(5)
    ensure_nemo_onelogger_deps()
    eprint(f"nemo_diar: from_pretrained('{model}')")
    progress(20)

    m = (model or "").strip().lower()
    if not m:
        raise SystemExit("Missing model")

    # Backward-compat: the old UI exposed "titanet_large" as a preset, but it is no longer
    # maintained/available in the project. Keep the message explicit if someone still tries
    # to use it (e.g., old saved settings).
    if m == "titanet_large":
        raise SystemExit("Unsupported NeMo diarization preset: 'titanet_large'. Use 'diar_msdd_telephonic' instead.")

    # Backward-compat / legacy aliases (some IDs were never published as NeMo pretrained models)
    alias_map = {
        'nemo_msdd_5scl_5mparams': 'diar_msdd_telephonic',
        'msdd_5scl_5mparams': 'diar_msdd_telephonic',
    }

    canonical = alias_map.get(m)
    if canonical and canonical != model:
        eprint(f"nemo_diar: '{model}' is not a published pretrained ID; using '{canonical}' instead")
        model = canonical
        m = canonical

    # Speaker embeddings model
    if "titanet" in m:
        candidates = [
            ("nemo.collections.asr.models", "EncDecSpeakerLabelModel"),
            ("nemo.collections.asr.models.speaker_label_models", "EncDecSpeakerLabelModel"),
            ("nemo.collections.asr.models", "EncDecSpeakerModel"),
        ]
        _try_from_pretrained(candidates, model)
        mark_nemo_installed(model, engine='nemo_diar')
        progress(100)
        return

    # MSDD diarization models
    candidates = [
        ("nemo.collections.asr.models", "NeuralDiarizer"),
        ("nemo.collections.asr.models.msdd_models", "NeuralDiarizer"),
        ("nemo.collections.asr.models.diarization_models", "NeuralDiarizer"),
        ("nemo.collections.asr.models", "EncDecDiarLabelModel"),
        ("nemo.collections.asr.models.diarization_models", "EncDecDiarLabelModel"),
    ]
    _try_from_pretrained(candidates, model)
    mark_nemo_installed(model, engine='nemo_diar')
    progress(100)




def predownload_pyannote(pipeline: str, hf_token: str) -> None:
    """Download/cache pyannote pipeline assets.

    This is used by Admin -> ASR Settings.

    Compatibility notes:
      - pyannote.audio 4.x examples use `token=`
      - older pyannote.audio 3.x often used `use_auth_token=`
      - huggingface_hub also supports reading the token from the `HF_TOKEN` env var

    We therefore:
      1) set HF_TOKEN environment variable
      2) try common kwargs (token/use_auth_token/...)
      3) fall back to calling without kwargs

    Additionally, `pyannote/speaker-diarization-community-1` requires pyannote.audio >= 4.0.
    """
    import sys
    import os


    progress(5)

    # IMPORTANT:
    # pyannote.audio (and some of its dependencies) may import lightning/pytorch_lightning.
    # When NeMo / nv_one_logger PL integration is installed but incompatible with the
    # currently installed Lightning version, it can crash *any* code path that imports
    # lightning (including pyannote).
    #
    # We don't need OneLogger for inference/predownload, so we neutralize it here as well.
    ensure_nemo_onelogger_deps()
    eprint(f"pyannote: from_pretrained('{pipeline}')")
    progress(15)

    # Detect version (best effort) and fail fast with a helpful message for Community-1.
    try:
        import pyannote.audio as _pa  # type: ignore
        _ver = getattr(_pa, '__version__', '') or ''
    except Exception:
        _ver = ''

    def _ver_tuple(v: str):
        parts = []
        for x in (v or '').split('.'):
            try:
                parts.append(int(x))
            except Exception:
                break
        while len(parts) < 3:
            parts.append(0)
        return tuple(parts[:3])

    if 'speaker-diarization-community-1' in (pipeline or ''):
        if _ver and _ver_tuple(_ver) < (4, 0, 0):
            raise SystemExit(
                "pyannote/speaker-diarization-community-1 requires pyannote.audio >= 4.0. "
                f"Current pyannote.audio version: {_ver}. "
                f"Python: {sys.version.split()[0]}. "
                "If you are on Python 3.13 and pip cannot install pyannote.audio 4.x, "
                "create a new virtualenv with Python 3.11/3.12 and reinstall dependencies."
            )

    # Make token available via env var for huggingface_hub.
    if hf_token:
        os.environ['HF_TOKEN'] = hf_token
        # Legacy env var names seen in some setups (best-effort).
        os.environ.setdefault('HUGGINGFACE_HUB_TOKEN', hf_token)
        os.environ.setdefault('HUGGING_FACE_HUB_TOKEN', hf_token)

        # Optional: persist token in HF cache (won't crash if unavailable)
        try:
            from huggingface_hub import login  # type: ignore
            login(token=hf_token, add_to_git_credential=False)
        except Exception:
            pass

    progress(25)
    
    # Work around PyTorch 2.6+ weights_only=True default for trusted pyannote models
    # PyTorch 2.6 changed torch.load to use weights_only=True by default for security.
    # Pyannote models use many custom classes that aren't in safe globals.
    # Since we trust HuggingFace pyannote models, we force weights_only=False.
    # Note: HuggingFace Hub may explicitly pass weights_only=True, so we must override it.
    try:
        import torch
        _original_torch_load = torch.load
        
        def _patched_torch_load(*args, **kwargs):
            # Force weights_only=False for pyannote models (override even explicit True)
            kwargs['weights_only'] = False
            return _original_torch_load(*args, **kwargs)
        
        torch.load = _patched_torch_load
        eprint("pyannote: patched torch.load to force weights_only=False (PyTorch 2.6+ compat)")
    except Exception as e:
        eprint(f"pyannote: could not patch torch.load (non-fatal): {e}")
    
    from pyannote.audio import Pipeline  # type: ignore

    # Try common kw args for broad compatibility.
    tried = []
    last_non_typeerror = None
    for kw in ("token", "use_auth_token", "auth_token", "access_token"):
        if not hf_token:
            break
        try:
            _ = Pipeline.from_pretrained(pipeline, **{kw: hf_token})
            mark_pyannote_installed(pipeline)
            progress(100)
            return
        except TypeError as e:
            tried.append(kw)
            continue
        except Exception as e:
            # Any other error means the kw was accepted but something else failed (auth/gated/deps).
            last_non_typeerror = e
            break

    # Fallback: call without kwargs (HF_TOKEN env var may still authorize).
    try:
        _ = Pipeline.from_pretrained(pipeline)
        mark_pyannote_installed(pipeline)
        progress(100)
        return
    except Exception as e:
        if last_non_typeerror is not None:
            raise SystemExit(
                f"pyannote Pipeline.from_pretrained() failed while trying kw args {tried}. "
                f"Last error: {last_non_typeerror}"
            )
        raise SystemExit(
            f"pyannote Pipeline.from_pretrained() failed. Tried kwargs {tried} and fallback without kwargs. Error: {e}"
        )



def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--action", required=True, choices=["install", "predownload"])
    ap.add_argument("--component", default="")
    ap.add_argument("--engine", default="")
    ap.add_argument("--model", default="")
    ap.add_argument("--pipeline", default="")
    ap.add_argument("--hf_token", default="")
    args = ap.parse_args()

    try:
        if args.action == "install":
            comp = (args.component or "").strip().lower()
            if comp not in ("whisper", "nemo", "pyannote"):
                raise SystemExit("Invalid component")
            pip_install(comp)
            out: Dict[str, Any] = {"ok": True, "action": "install", "component": comp}
            print(json.dumps(out))
            return

        # predownload
        engine = (args.engine or "").strip().lower()
        if engine == "whisper":
            if not args.model:
                raise SystemExit("Missing --model")
            predownload_whisper(args.model)
            print(json.dumps({"ok": True, "action": "predownload", "engine": engine, "model": args.model}))
            return

        if engine == "nemo":
            if not args.model:
                raise SystemExit("Missing --model")
            predownload_nemo(args.model)
            print(json.dumps({"ok": True, "action": "predownload", "engine": engine, "model": args.model}))
            return

        if engine == "nemo_diar":
            if not args.model:
                raise SystemExit("Missing --model")
            predownload_nemo_diarization(args.model)
            print(json.dumps({"ok": True, "action": "predownload", "engine": engine, "model": args.model}))
            return

        if engine == "pyannote":
            if not args.pipeline:
                raise SystemExit("Missing --pipeline")
            if not args.hf_token:
                raise SystemExit("Missing --hf_token")
            predownload_pyannote(args.pipeline, args.hf_token)
            print(json.dumps({"ok": True, "action": "predownload", "engine": engine, "pipeline": args.pipeline}))
            return

        raise SystemExit("Invalid engine")
    except SystemExit:
        raise
    except Exception as e:
        eprint(f"ERROR: {e}")
        # Ensure non-zero exit for TaskManager
        raise


if __name__ == "__main__":
    main()
