from __future__ import annotations

import sys
import re
import math
import tempfile
import subprocess


def _apply_onelogger_stubs(log_cb=None) -> None:
    """Disable optional OneLogger integration used by NeMo/Lightning.

    In some environments (notably Python 3.13 + certain nv_one_logger/overrides combos),
    importing NeMo can crash at import-time inside:
      nv_one_logger.training_telemetry.integration.pytorch_lightning

    We do not need OneLogger for inference/diarization, so we install a *targeted* stub
    for `nemo.lightning.one_logger_callback` (and optionally the nv_one_logger hierarchy)
    to keep imports stable.

    IMPORTANT: we **do not** stub the top-level `nemo` package.
    """
    import types

    def log(msg: str) -> None:
        if log_cb:
            log_cb(msg)

    mname = 'nemo.lightning.one_logger_callback'
    existing = sys.modules.get(mname)
    if getattr(existing, '__AISTATE_STUB__', False):
        return

    # 1) Stub NeMo's OneLogger callback module so NeMo doesn't import nv_one_logger.
    m = types.ModuleType(mname)

    class OneLoggerNeMoCallback:  # noqa: D401
        """Stub callback used only to satisfy NeMo import paths."""

        def __init__(self, *args, **kwargs):
            pass

    m.OneLoggerNeMoCallback = OneLoggerNeMoCallback
    m.__AISTATE_STUB__ = True  # type: ignore[attr-defined]
    sys.modules[mname] = m

    # 2) (Optional) Stub nv_one_logger hierarchy too, in case something imports it directly.
    #    This is safe for inference and prevents import-time crashes.
    def _ensure_pkg(name: str) -> types.ModuleType:
        mod = sys.modules.get(name)
        if mod is None:
            mod = types.ModuleType(name)
            mod.__path__ = []  # type: ignore[attr-defined]
            sys.modules[name] = mod
        else:
            if not hasattr(mod, '__path__'):
                mod.__path__ = []  # type: ignore[attr-defined]
        return mod

    def _ensure_mod(name: str) -> types.ModuleType:
        mod = sys.modules.get(name)
        if mod is None:
            mod = types.ModuleType(name)
            sys.modules[name] = mod
        return mod

    # Purge any partially imported real modules (failed imports leave broken entries).
    for k in list(sys.modules.keys()):
        if k == 'nv_one_logger' or k.startswith('nv_one_logger.'):
            sys.modules.pop(k, None)

    _ensure_pkg('nv_one_logger')
    _ensure_pkg('nv_one_logger.api')
    cfg = _ensure_mod('nv_one_logger.api.config')

    if not hasattr(cfg, 'OneLoggerConfig'):
        class OneLoggerConfig:  # pragma: no cover
            def __init__(self, *args, **kwargs):
                pass
        cfg.OneLoggerConfig = OneLoggerConfig

    _ensure_pkg('nv_one_logger.training_telemetry')
    _ensure_pkg('nv_one_logger.training_telemetry.api')
    cb = _ensure_mod('nv_one_logger.training_telemetry.api.callbacks')

    if not hasattr(cb, 'on_app_start'):
        def on_app_start(*args, **kwargs):
            return None
        def on_app_end(*args, **kwargs):
            return None
        cb.on_app_start = on_app_start
        cb.on_app_end = on_app_end

    _ensure_pkg('nv_one_logger.training_telemetry.integration')
    ptl = _ensure_mod('nv_one_logger.training_telemetry.integration.pytorch_lightning')

    if not hasattr(ptl, 'TimeEventCallback'):
        class TimeEventCallback:  # pragma: no cover
            def __init__(self, *args, **kwargs):
                pass
        ptl.TimeEventCallback = TimeEventCallback

    log('compat: OneLogger disabled (stubbed nemo.lightning.one_logger_callback)')



def _mask_token(tok: str) -> str:
    if not tok:
        return ""
    if len(tok) <= 8:
        return "*" * len(tok)
    return tok[:4] + "…" + tok[-4:]

def _fmt_ts(seconds: float) -> str:
    if seconds < 0:
        seconds = 0.0
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}"


def _convert_to_pcm_wav_16k_mono(src_path: str, log_cb=None) -> str:
    """Convert any audio to stable PCM WAV 16kHz mono (ffmpeg required).

    Some formats (m4a/mp3/VBR) can cause slight sample-count mismatches when
    pyannote crops by time. Converting to PCM avoids this.
    Returns path to a temporary wav file; caller should delete it.
    """
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp.close()
    out_path = tmp.name

    cmd = [
        "ffmpeg", "-y",
        "-i", src_path,
        "-ac", "1",
        "-ar", "16000",
        "-c:a", "pcm_s16le",
        out_path,
    ]

    if log_cb:
        log_cb("ffmpeg: converting input to PCM WAV 16kHz mono (stabilize diarization)…")

    try:
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    except FileNotFoundError as e:
        raise RuntimeError("ffmpeg not found. Install it (e.g., sudo apt install ffmpeg).") from e

    if p.returncode != 0:
        tail = (p.stderr or "")[-1200:]
        raise RuntimeError(f"ffmpeg conversion failed (code={p.returncode}). stderr tail:\n{tail}")

    return out_path

def _load_pyannote_pipeline(Pipeline, hf_token: str, log_cb=None, preferred_id: str | None = None):
    """Load pyannote diarization pipeline in a version-compatible way.

    Tries multiple pipeline IDs because HF repo pointers / requirements evolve.
    Uses `token=` first (newer pyannote.audio) and falls back to legacy kwargs.
    """

    def log(msg: str) -> None:
        if log_cb:
            log_cb(msg)

    def _dedupe_keep_order(items):
        out = []
        seen = set()
        for it in items:
            s = str(it or '').strip()
            if not s or s in seen:
                continue
            seen.add(s)
            out.append(s)
        return out

    # Prefer newer/community pipelines first (more stable packaging).
    # If the UI selected a concrete pipeline (preferred_id), try it first.
    pipeline_ids = _dedupe_keep_order([
        preferred_id,
        "pyannote/speaker-diarization-community-1",
        "pyannote/speaker-diarization-3.1",
        "pyannote/speaker-diarization",
    ])

    kw_candidates = [
        ("token", hf_token),
        ("use_auth_token", hf_token),
        ("auth_token", hf_token),
        ("access_token", hf_token),
    ]

    last_exc = None

    log("pyannote: creating pipeline (compat loader)…")
    
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
        log("pyannote: patched torch.load to force weights_only=False (PyTorch 2.6+ compat)")
    except Exception as e:
        log(f"pyannote: could not patch torch.load (non-fatal): {e}")
    
    # Log versions to help debugging
    try:
        import pyannote.audio  # type: ignore
        log(f"pyannote.audio: {getattr(pyannote.audio, '__version__', 'unknown')}")
    except Exception:
        pass
    try:
        import huggingface_hub  # type: ignore
        log(f"huggingface_hub: {getattr(huggingface_hub, '__version__', 'unknown')}")
    except Exception:
        pass

    for pid in pipeline_ids:
        for kw, val in kw_candidates:
            try:
                log(f"pyannote: trying pipeline '{pid}' with {kw}=***")
                pipe = Pipeline.from_pretrained(pid, **{kw: val})
                log(f"pyannote: pipeline loaded OK: {pid} ({kw})")
                return pipe
            except TypeError as e:
                # kw not supported by this version
                last_exc = e
                continue
            except ValueError as e:
                # Common mismatch: revision handling / pipeline requirements
                last_exc = e
                msg = str(e)
                if "Revisions must be passed with `revision`" in msg:
                    log("pyannote: revision error detected for this pipeline/version combination.")
                    # Try next pipeline id
                    break
                # otherwise try next kw
                continue
            except Exception as e:
                last_exc = e
                # could be 401/403 gated or download errors
                continue

    # Last resort: try without token (works if user did `huggingface-cli login`)
    for pid in pipeline_ids:
        try:
            log(f"pyannote: trying pipeline '{pid}' without token (HF login/env)…")
            pipe = Pipeline.from_pretrained(pid)
            log(f"pyannote: pipeline loaded OK without token: {pid}")
            return pipe
        except Exception as e:
            last_exc = e
            continue

    log("pyannote: FAILED to load pipeline. Check: token, model access (gated), dependencies, or pyannote.audio version.")
    if last_exc:
        raise last_exc
    raise RuntimeError("pyannote pipeline load failed for unknown reason.")


def _pyannote_diarize_turns(
    audio_path: str,
    hf_token: str,
    diar_model: str | None = None,
    log_cb=None,
    progress_cb=None,
    keep_wav: bool = False,
):
    """Return (turns, wav_path_or_none).

    `turns` is a list of (start_s, end_s, speaker_label).

    When keep_wav=True, the stabilized PCM WAV path is returned and should be deleted by caller.
    """
    import os

    # pyannote.audio may import lightning/pytorch_lightning; if nv_one_logger PL integration
    # is installed but incompatible with the current Lightning version, imports can crash.
    # This stub installer makes diarization robust in such environments.
    _apply_onelogger_stubs(log_cb=log_cb)

    try:
        import torch
    except Exception as e:
        raise RuntimeError("Missing 'torch'. Install a torch build appropriate for your platform/GPU.") from e

    if not hf_token:
        raise RuntimeError("HF token missing. Set it in the app settings.")

    # Work around PyTorch 2.6+ weights_only=True default for trusted pyannote models
    # PyTorch 2.6 changed torch.load to use weights_only=True by default for security.
    # Pyannote models use many custom classes that aren't in safe globals.
    # Since we trust HuggingFace pyannote models, we force weights_only=False.
    # Note: HuggingFace Hub may explicitly pass weights_only=True, so we must override it.
    try:
        _original_torch_load = torch.load
        
        def _patched_torch_load(*args, **kwargs):
            # Force weights_only=False for pyannote models (override even explicit True)
            kwargs['weights_only'] = False
            return _original_torch_load(*args, **kwargs)
        
        torch.load = _patched_torch_load
        if log_cb:
            log_cb("pyannote: patched torch.load to force weights_only=False (PyTorch 2.6+ compat)")
    except Exception as e:
        if log_cb:
            log_cb(f"pyannote: could not patch torch.load (non-fatal): {e}")

    from pyannote.audio import Pipeline  # type: ignore

    if log_cb:
        log_cb("pyannote: load speaker-diarization pipeline (auto-download if missing)")
    pipeline = _load_pyannote_pipeline(Pipeline, hf_token, log_cb, preferred_id=diar_model)

    # Try to move to GPU (best-effort)
    pyannote_device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    if pyannote_device.type == "cuda":
        try:
            pipeline.to(pyannote_device)
            if log_cb:
                log_cb(f"pyannote: pipeline moved to {pyannote_device}")
        except Exception as e:
            pyannote_device = torch.device("cpu")
            if log_cb:
                log_cb(f"pyannote: pipeline.to(cuda) failed -> CPU fallback ({type(e).__name__}: {e})")

    if progress_cb:
        progress_cb(45)

    # Always stabilize input to avoid decoding issues.
    wav_path = _convert_to_pcm_wav_16k_mono(audio_path, log_cb=log_cb)

    try:
        try:
            import soundfile as sf  # type: ignore
        except Exception as e:
            raise RuntimeError("Missing 'soundfile'. Install: pip install soundfile") from e

        audio_np, sr = sf.read(wav_path, dtype="float32", always_2d=True)
        waveform = torch.from_numpy(audio_np.T)
        if getattr(pyannote_device, "type", None) == "cuda":
            waveform = waveform.to(pyannote_device)

        file_dict = {
            "waveform": waveform,
            "sample_rate": int(sr),
            "uri": os.path.basename(audio_path),
            "duration": float(waveform.shape[1]) / float(sr) if int(sr) > 0 else None,
        }

        if log_cb:
            try:
                dur = float(waveform.shape[1]) / float(sr) if int(sr) > 0 else 0.0
                log_cb(f"Audio: loaded waveform (channels={waveform.shape[0]}, sample_rate={sr}, duration_s={dur:.2f})")
            except Exception:
                pass

        diar = pipeline(file_dict)

    except Exception:
        # Ensure tmp file removed if we won't return it
        if not keep_wav:
            try:
                os.unlink(wav_path)
            except Exception:
                pass
        raise

    if progress_cb:
        progress_cb(80)

    def get_annotation(diar_output):
        if hasattr(diar_output, "exclusive_speaker_diarization"):
            if log_cb:
                log_cb("pyannote: using output.exclusive_speaker_diarization")
            return diar_output.exclusive_speaker_diarization
        if hasattr(diar_output, "speaker_diarization"):
            if log_cb:
                log_cb("pyannote: using output.speaker_diarization")
            return diar_output.speaker_diarization
        if hasattr(diar_output, "itertracks"):
            if log_cb:
                log_cb("pyannote: using output (Annotation)")
            return diar_output
        raise RuntimeError(f"Unknown pyannote output type: {type(diar_output)}")

    annotation = get_annotation(diar)
    turns = [(float(turn.start), float(turn.end), str(speaker)) for turn, _, speaker in annotation.itertracks(yield_label=True)]

    if log_cb:
        log_cb(f"pyannote: found {len(turns)} speaker turns")

    if not keep_wav:
        try:
            os.unlink(wav_path)
        except Exception:
            pass
        return turns, None

    return turns, wav_path


def diarize_voice_asr_pyannote(
    audio_path: str,
    asr_engine: str,
    model: str,
    language: str,
    hf_token: str,
    diar_model: str | None = None,
    log_cb=None,
    progress_cb=None,
):
    """Diarize + transcribe with selected ASR engine.

    asr_engine:
      - whisper (default): openai-whisper
      - nemo: NVIDIA NeMo ASR (per-speaker turns)
    """
    eng = str(asr_engine or "whisper").strip().lower()
    if eng in ("whisper", "openai", "openai-whisper"):
        return diarize_voice_whisper_pyannote(
            audio_path,
            model,
            language,
            hf_token,
            diar_model=diar_model,
            log_cb=log_cb,
            progress_cb=progress_cb,
        )
    if eng in ("nemo", "nvidia", "ne-mo"):
        return diarize_voice_nemo_pyannote(
            audio_path,
            model,
            language,
            hf_token,
            diar_model=diar_model,
            log_cb=log_cb,
            progress_cb=progress_cb,
        )
    raise RuntimeError(f"Unknown ASR engine: {asr_engine}")


def _nemo_msdd_diarize_turns(
    audio_path: str,
    diar_model: str,
    log_cb=None,
    progress_cb=None,
    keep_wav: bool = False,
):
    """Return speaker turns using NeMo MSDD diarization (e.g. diar_msdd_telephonic).

    Returns (turns, wav_path_or_none) where turns is a list of (start_s, end_s, speaker).
    If keep_wav=True, the stabilized PCM WAV path is returned (caller must delete it).

    We intentionally implement this as a best-effort wrapper because NeMo moved diarization
    classes/APIs between versions. We try the most common import paths and inference calls.
    """
    import os

    _apply_onelogger_stubs(log_cb=log_cb)

    if progress_cb:
        progress_cb(5)

    # NeMo diarization expects stable PCM WAV in many setups
    wav_path = _convert_to_pcm_wav_16k_mono(audio_path, log_cb=log_cb)

    try:
        try:
            import torch  # type: ignore
        except Exception as e:
            raise RuntimeError("Missing 'torch'. Install a torch build appropriate for your platform/GPU.") from e

        # Import NeuralDiarizer from likely modules
        NeuralDiarizer = None
        for mod_name, cls_name in [
            ("nemo.collections.asr.models", "NeuralDiarizer"),
            ("nemo.collections.asr.models.msdd_models", "NeuralDiarizer"),
            ("nemo.collections.asr.models.diarization_models", "NeuralDiarizer"),
        ]:
            try:
                mod = __import__(mod_name, fromlist=[cls_name])
                NeuralDiarizer = getattr(mod, cls_name)
                break
            except Exception:
                continue

        if NeuralDiarizer is None:
            raise RuntimeError("NeMo diarization: NeuralDiarizer class not found. Ensure nemo_toolkit[asr] is installed.")

        device = "cuda" if torch.cuda.is_available() else "cpu"
        if log_cb:
            log_cb(f"NeMo diar: loading model='{diar_model}' (device={device})")

        # Load model
        try:
            diarizer = NeuralDiarizer.from_pretrained(model_name=diar_model)
        except TypeError:
            diarizer = NeuralDiarizer.from_pretrained(diar_model)

        try:
            diarizer = diarizer.to(device)
        except Exception:
            pass
        try:
            diarizer.eval()
        except Exception:
            pass

        if progress_cb:
            progress_cb(20)

        # Run inference (several API variants exist in the wild)
        ann = None
        last_err = None
        try_calls = [
            lambda: diarizer(wav_path, num_workers=0, batch_size=16),
            lambda: diarizer(wav_path),
            lambda: diarizer.diarize(paths2audio_files=[wav_path], batch_size=16),
            lambda: diarizer.diarize(paths2audio_files=[wav_path]),
        ]
        for fn in try_calls:
            try:
                ann = fn()
                break
            except Exception as e:  # noqa: BLE001
                last_err = e
                continue

        if ann is None:
            raise RuntimeError(f"NeMo diarization failed: {type(last_err).__name__}: {last_err}")

        # Normalize output
        if isinstance(ann, list) and ann:
            ann0 = ann[0]
        else:
            ann0 = ann

        rttm_text = None
        # Some versions return an Annotation-like object
        if hasattr(ann0, "to_rttm"):
            try:
                rttm_text = ann0.to_rttm()
            except Exception:
                rttm_text = None
        # Some versions return rttm strings or paths
        if rttm_text is None and isinstance(ann0, str):
            if "SPEAKER" in ann0:
                rttm_text = ann0
            elif os.path.exists(ann0):
                try:
                    with open(ann0, "r", encoding="utf-8", errors="ignore") as f:
                        rttm_text = f.read()
                except Exception:
                    rttm_text = None

        # Some versions return list of rttm file paths
        if rttm_text is None and isinstance(ann, list) and ann and isinstance(ann[0], str) and os.path.exists(ann[0]):
            try:
                with open(ann[0], "r", encoding="utf-8", errors="ignore") as f:
                    rttm_text = f.read()
            except Exception:
                rttm_text = None

        if not rttm_text:
            raise RuntimeError(f"NeMo diarization returned unsupported output type: {type(ann0)}")

        # Parse RTTM -> turns
        turns = []
        for line in (rttm_text or "").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) < 8:
                continue
            if parts[0].upper() != "SPEAKER":
                continue
            try:
                start = float(parts[3])
                dur = float(parts[4])
                spk = str(parts[7])
                end = start + dur
            except Exception:
                continue
            if end <= start:
                continue
            turns.append((start, end, spk))

        if log_cb:
            log_cb(f"NeMo diar: turns={len(turns)}")

        if progress_cb:
            progress_cb(60)

        if not keep_wav:
            try:
                os.unlink(wav_path)
            except Exception:
                pass
            return turns, None

        return turns, wav_path

    except Exception:
        # Cleanup wav on errors
        try:
            os.unlink(wav_path)
        except Exception:
            pass
        raise


def diarize_voice_asr_nemo_diar(
    audio_path: str,
    asr_engine: str,
    model: str,
    language: str,
    diar_model: str | None = None,
    log_cb=None,
    progress_cb=None,
):
    """Diarize with NeMo diarization (MSDD) and transcribe with selected ASR engine.

    diar_model examples: diar_msdd_telephonic
    """
    eng = str(asr_engine or "whisper").strip().lower()
    dmodel = (diar_model or "").strip() or "diar_msdd_telephonic"

    if log_cb:
        log_cb(f"Start: NeMo diar (model={dmodel}) + ASR={eng}")

    # For NeMo ASR we need the stabilized wav for cropping; for Whisper we don't.
    need_wav = eng in ("nemo", "nvidia", "ne-mo")
    turns, wav_path = _nemo_msdd_diarize_turns(
        audio_path,
        dmodel,
        log_cb=log_cb,
        progress_cb=progress_cb,
        keep_wav=need_wav,
    )

    def overlap(a0, a1, b0, b1):
        return max(0.0, min(a1, b1) - max(a0, b0))

    if eng in ("whisper", "openai", "openai-whisper"):
        # Whisper segments + overlap mapping to NeMo turns
        def _p2(pct: int) -> None:
            if progress_cb:
                progress_cb(60 + int(0.4 * int(pct)))

        wres = whisper_transcribe(audio_path, model=model, language=language, log_cb=log_cb, progress_cb=_p2)
        segments = wres.get("segments") or []

        out_lines = []
        segments_out = []
        for seg in segments:
            s0 = float(seg.get("start", 0.0))
            s1 = float(seg.get("end", 0.0))
            txt = (seg.get("text") or "").strip()
            if not txt:
                continue

            best_spk = "UNKNOWN"
            best_ov = 0.0
            for t0, t1, spk in turns:
                ov = overlap(s0, s1, float(t0), float(t1))
                if ov > best_ov:
                    best_ov = ov
                    best_spk = spk

            out_lines.append(f"[{s0:.2f}-{s1:.2f}] {best_spk}: {txt}")
            seg_out = {"start": s0, "end": s1, "speaker": best_spk, "text": txt}
            # Preserve confidence from Whisper if available
            if "confidence" in seg:
                seg_out["confidence"] = seg["confidence"]
            if "no_speech" in seg:
                seg_out["no_speech"] = seg["no_speech"]
            segments_out.append(seg_out)

        if progress_cb:
            progress_cb(100)

        return {"kind": "diarized_voice", "text": "\n".join(out_lines).strip(), "segments": segments_out, "ok": True, "engine": "whisper"}

    if eng in ("nemo", "nvidia", "ne-mo"):
        # NeMo ASR per speaker turn (same strategy as diarize_voice_nemo_pyannote)
        import os
        import tempfile

        if wav_path is None:
            raise RuntimeError("Internal error: missing stabilized wav for NeMo ASR")

        _apply_onelogger_stubs(log_cb=log_cb)

        try:
            import torch  # type: ignore
        except Exception as e:
            try:
                os.unlink(wav_path)
            except Exception:
                pass
            raise RuntimeError("Missing 'torch'. Install a torch build appropriate for your platform/GPU.") from e

        try:
            from nemo.collections.asr.models import ASRModel  # type: ignore
        except Exception as e:
            try:
                os.unlink(wav_path)
            except Exception:
                pass
            raise RuntimeError("Missing 'nemo_toolkit'. Install from ASR Settings or: pip install nemo_toolkit[asr]") from e

        device = "cuda" if torch.cuda.is_available() else "cpu"
        if log_cb:
            log_cb(f"NeMo ASR: loading model='{model}' (device={device})")
        if progress_cb:
            progress_cb(65)

        asr = ASRModel.from_pretrained(model_name=model)
        try:
            if device == "cuda":
                asr = asr.cuda()
        except Exception:
            pass
        asr.eval()

        try:
            import soundfile as sf  # type: ignore
        except Exception as e:
            try:
                os.unlink(wav_path)
            except Exception:
                pass
            raise RuntimeError("Missing 'soundfile'. Install: pip install soundfile") from e

        segments_out = []
        out_lines = []
        n = max(1, len(turns))
        for idx, (t0, t1, spk) in enumerate(turns, start=1):
            start_f = int(max(0.0, float(t0)) * 16000)
            stop_f = int(max(0.0, float(t1)) * 16000)
            if stop_f <= start_f + 200:
                continue

            audio_np, sr = sf.read(wav_path, start=start_f, stop=stop_f, dtype="float32", always_2d=False)
            if int(sr) != 16000:
                pass

            tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
            tmp.close()
            try:
                sf.write(tmp.name, audio_np, 16000)
                hyp = asr.transcribe([tmp.name])
                txt = ""
                if isinstance(hyp, list) and hyp:
                    txt = str(hyp[0] or "").strip()
            finally:
                try:
                    os.unlink(tmp.name)
                except Exception:
                    pass

            if not txt:
                continue

            out_lines.append(f"[{float(t0):.2f}-{float(t1):.2f}] {spk}: {txt}")
            segments_out.append({"start": float(t0), "end": float(t1), "speaker": spk, "text": txt})

            if progress_cb:
                pct = 65 + int(35 * (idx / n))
                progress_cb(min(99, pct))

        try:
            os.unlink(wav_path)
        except Exception:
            pass

        if progress_cb:
            progress_cb(100)
        return {"kind": "diarized_voice", "text": "\n".join(out_lines).strip(), "segments": segments_out, "ok": True, "engine": "nemo"}

    raise RuntimeError(f"Unknown ASR engine: {asr_engine}")


def diarize_voice_nemo_pyannote(
    audio_path: str,
    model: str,
    language: str,
    hf_token: str,
    diar_model: str | None = None,
    log_cb=None,
    progress_cb=None,
):
    """NeMo ASR per speaker-turn + pyannote diarization.

    NOTE: NeMo models are often language-specific. The `language` arg is currently not enforced.
    """
    import os
    import tempfile

    if log_cb:
        log_cb("Start: NeMo + pyannote")
        log_cb(f"HF token: {'OK' if hf_token else 'MISSING'}")

    # pyannote first, keep stabilized wav for cropping
    if progress_cb:
        progress_cb(10)
    turns, wav_path = _pyannote_diarize_turns(
        audio_path,
        hf_token,
        diar_model=diar_model,
        log_cb=log_cb,
        progress_cb=progress_cb,
        keep_wav=True,
    )
    assert wav_path is not None

    # NeMo
    try:
        import torch  # type: ignore
    except Exception as e:
        raise RuntimeError("Missing 'torch'. Install a torch build appropriate for your platform/GPU.") from e

    try:
        from nemo.collections.asr.models import ASRModel  # type: ignore
    except Exception as e:
        try:
            os.unlink(wav_path)
        except Exception:
            pass
        raise RuntimeError("Missing 'nemo_toolkit'. Install from ASR Settings or: pip install nemo_toolkit[asr]") from e

    device = "cuda" if torch.cuda.is_available() else "cpu"
    if log_cb:
        log_cb(f"NeMo: loading model='{model}' (device={device})")
    if progress_cb:
        progress_cb(20)

    asr = ASRModel.from_pretrained(model_name=model)
    try:
        if device == "cuda":
            asr = asr.cuda()
    except Exception:
        pass
    asr.eval()

    if progress_cb:
        progress_cb(35)

    try:
        import soundfile as sf  # type: ignore
    except Exception as e:
        try:
            os.unlink(wav_path)
        except Exception:
            pass
        raise RuntimeError("Missing 'soundfile'. Install: pip install soundfile") from e

    # Transcribe each speaker turn
    segments_out = []
    out_lines = []
    n = max(1, len(turns))
    for idx, (t0, t1, spk) in enumerate(turns, start=1):
        start_f = int(max(0.0, t0) * 16000)
        stop_f = int(max(0.0, t1) * 16000)
        if stop_f <= start_f + 200:  # too short
            continue

        # Read slice and write to temp wav because NeMo expects a file path
        audio_np, sr = sf.read(wav_path, start=start_f, stop=stop_f, dtype="float32", always_2d=False)
        if int(sr) != 16000:
            # should not happen with stabilized wav, but handle gracefully
            pass

        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        tmp.close()
        try:
            sf.write(tmp.name, audio_np, 16000)
            hyp = asr.transcribe([tmp.name])
            txt = ""
            if isinstance(hyp, list) and hyp:
                txt = str(hyp[0] or "").strip()
        finally:
            try:
                os.unlink(tmp.name)
            except Exception:
                pass

        if not txt:
            continue

        out_lines.append(f"[{t0:.2f}-{t1:.2f}] {spk}: {txt}")
        segments_out.append({"start": float(t0), "end": float(t1), "speaker": spk, "text": txt})

        if progress_cb:
            # 35..95
            pct = 35 + int(60 * (idx / n))
            progress_cb(pct)

    try:
        os.unlink(wav_path)
    except Exception:
        pass

    if progress_cb:
        progress_cb(100)
    return {"kind": "diarized_voice", "text": "\n".join(out_lines).strip(), "segments": segments_out, "ok": True, "engine": "nemo"}




def nemo_transcribe(audio_path: str, model: str, language: str, log_cb=None, progress_cb=None):
    """NeMo ASR transcription (single segment output).

    We return a single segment spanning the whole recording so the web UI can still
    provide hover playback + inline editing.

    NOTE: The `language` parameter is currently not enforced (depends on model).
    """
    import os
    import tempfile
    import wave

    def _ensure_one_logger_stub():
        """Ensure nv_one_logger does not break NeMo imports.

        Strategy:
        1) Prefer the on-disk stub shipped with AISTATEweb under backend/models_cache/nemo/nv_one_logger
           by inserting its parent directory into sys.path (highest priority) and purging any previously
           imported nv_one_logger modules.
        2) If something still fails, inject a minimal in-memory stub (as packages) covering the symbols
           NeMo imports during startup.
        """
        # Prefer local stub shipped with AISTATEweb (kept under backend/models_cache/nemo)
        try:
            here = os.path.dirname(__file__)
            stub_parent = os.path.join(here, 'models_cache', 'nemo')
            stub_pkg = os.path.join(stub_parent, 'nv_one_logger')
            if os.path.isdir(stub_pkg):
                if stub_parent in sys.path:
                    sys.path.remove(stub_parent)
                sys.path.insert(0, stub_parent)

                # Purge partially imported modules so the stub is used
                for k in list(sys.modules.keys()):
                    if k == 'nv_one_logger' or k.startswith('nv_one_logger.'):
                        sys.modules.pop(k, None)

                # Try importing from the stub (or real package, if present and healthy)
                import importlib
                importlib.import_module('nv_one_logger.api.config')
                importlib.import_module('nv_one_logger.training_telemetry.api.config')
                importlib.import_module('nv_one_logger.training_telemetry.api.training_telemetry_provider')
                importlib.import_module('nv_one_logger.training_telemetry.api.callbacks')
                importlib.import_module('nv_one_logger.training_telemetry.integration.pytorch_lightning')
                if log_cb:
                    log_cb('NeMo: OneLogger stub active (inference-only).')
                return
        except Exception as e:
            if log_cb:
                log_cb(f"NeMo: OneLogger integration unavailable ({type(e).__name__}: {e}); using in-memory stubs (safe for inference).")

        # Fallback: in-memory stub (must behave like packages so nested imports work)
        import types

        # Purge partially imported modules
        for k in list(sys.modules.keys()):
            if k == 'nv_one_logger' or k.startswith('nv_one_logger.'):
                sys.modules.pop(k, None)

        root = types.ModuleType('nv_one_logger')
        root.__path__ = []

        api = types.ModuleType('nv_one_logger.api')
        api.__path__ = []
        cfg = types.ModuleType('nv_one_logger.api.config')

        class OneLoggerConfig:  # pragma: no cover
            def __init__(self, *args, **kwargs):
                pass

        cfg.OneLoggerConfig = OneLoggerConfig

        tt = types.ModuleType('nv_one_logger.training_telemetry')
        tt.__path__ = []

        tt_api = types.ModuleType('nv_one_logger.training_telemetry.api')
        tt_api.__path__ = []
        cb = types.ModuleType('nv_one_logger.training_telemetry.api.callbacks')

        def on_app_start(*args, **kwargs):
            return None

        def on_app_end(*args, **kwargs):
            return None

        cb.on_app_start = on_app_start
        cb.on_app_end = on_app_end

        # Add training_telemetry.api.config module (required by newer NeMo versions)
        tt_api_cfg = types.ModuleType('nv_one_logger.training_telemetry.api.config')

        class TrainingTelemetryConfig:  # pragma: no cover
            def __init__(self, *args, **kwargs):
                pass

        tt_api_cfg.TrainingTelemetryConfig = TrainingTelemetryConfig

        # Add training_telemetry.api.training_telemetry_provider module
        tt_api_provider = types.ModuleType('nv_one_logger.training_telemetry.api.training_telemetry_provider')

        class TrainingTelemetryProvider:  # pragma: no cover
            """Singleton stub for TrainingTelemetryProvider."""
            _instance = None

            def __init__(self, *args, **kwargs):
                pass

            @classmethod
            def instance(cls):
                """Return singleton instance."""
                if cls._instance is None:
                    cls._instance = cls()
                return cls._instance

            def with_base_config(self, *args, **kwargs):
                """Stub method for with_base_config."""
                return self

            def with_export_config(self, *args, **kwargs):
                """Stub method for with_export_config."""
                return self

            def configure_provider(self, *args, **kwargs):
                """Stub method for configure_provider."""
                return self

            def log_event(self, *args, **kwargs):
                """Stub method for log_event."""
                pass

            def log_metric(self, *args, **kwargs):
                """Stub method for log_metric."""
                pass

        tt_api_provider.TrainingTelemetryProvider = TrainingTelemetryProvider

        integ = types.ModuleType('nv_one_logger.training_telemetry.integration')
        integ.__path__ = []
        pl = types.ModuleType('nv_one_logger.training_telemetry.integration.pytorch_lightning')

        class TimeEventCallback:  # pragma: no cover
            def __init__(self, *args, **kwargs):
                pass

        pl.TimeEventCallback = TimeEventCallback

        # Wire module tree
        root.api = api
        root.training_telemetry = tt
        tt.api = tt_api
        tt.integration = integ

        sys.modules['nv_one_logger'] = root
        sys.modules['nv_one_logger.api'] = api
        sys.modules['nv_one_logger.api.config'] = cfg
        sys.modules['nv_one_logger.training_telemetry'] = tt
        sys.modules['nv_one_logger.training_telemetry.api'] = tt_api
        sys.modules['nv_one_logger.training_telemetry.api.config'] = tt_api_cfg
        sys.modules['nv_one_logger.training_telemetry.api.training_telemetry_provider'] = tt_api_provider
        sys.modules['nv_one_logger.training_telemetry.api.callbacks'] = cb
        sys.modules['nv_one_logger.training_telemetry.integration'] = integ
        sys.modules['nv_one_logger.training_telemetry.integration.pytorch_lightning'] = pl

    _ensure_one_logger_stub()

    if log_cb:
        log_cb(f"NeMo: load '{model}' (auto-download if missing)")
    if progress_cb:
        progress_cb(5)

    # Convert to stable 16kHz mono WAV (NeMo models expect this most of the time)
    wav_path = None
    try:
        wav_path = _convert_to_pcm_wav_16k_mono(audio_path, log_cb=log_cb)
    except Exception as e:
        # If conversion fails, try the original path
        if log_cb:
            log_cb(f"NeMo: ffmpeg conversion failed -> fallback to original audio ({type(e).__name__}: {e})")
        wav_path = audio_path

    # Duration (best-effort)
    dur_s = 0.0
    try:
        if isinstance(wav_path, str) and wav_path.lower().endswith('.wav') and os.path.exists(wav_path):
            with wave.open(wav_path, 'rb') as wf:
                fr = float(wf.getframerate() or 1)
                dur_s = float(wf.getnframes()) / fr
    except Exception:
        dur_s = 0.0

    try:
        import torch  # type: ignore
    except Exception as e:
        if wav_path and wav_path != audio_path:
            try:
                os.unlink(wav_path)
            except Exception:
                pass
        raise RuntimeError("Missing 'torch'. Install a torch build appropriate for your platform/GPU.") from e

    try:
        from nemo.collections.asr.models import ASRModel  # type: ignore
    except ModuleNotFoundError as e:
        if wav_path and wav_path != audio_path:
            try:
                os.unlink(wav_path)
            except Exception:
                pass
        _name = getattr(e, 'name', '') or str(e)
        if _name.startswith('nemo'):
            raise RuntimeError("Missing 'nemo_toolkit'. Install from ASR Settings or: pip install nemo_toolkit[asr]") from e
        if _name.startswith('nv_one_logger'):
            raise RuntimeError("NeMo import failed due to missing/broken 'nv_one_logger'. AISTATEweb ships an inference-safe stub under backend/models_cache/nemo/nv_one_logger. Ensure legacy_adapter.py is updated and retry.") from e
        raise RuntimeError(f"NeMo import failed due to missing module: {_name}.") from e
    except Exception as e:
        if wav_path and wav_path != audio_path:
            try:
                os.unlink(wav_path)
            except Exception:
                pass
        raise RuntimeError("NeMo import failed due to dependency mismatch (often nv_one_logger / lightning). Update packages or keep OneLogger stub enabled.") from e

    device = 'cuda' if torch.cuda.is_available() else 'cpu'
    if log_cb:
        log_cb(f"NeMo: using device={device}")
    if progress_cb:
        progress_cb(15)

    asr = ASRModel.from_pretrained(model_name=model)
    try:
        if device == 'cuda':
            asr = asr.cuda()
    except Exception:
        pass
    asr.eval()

    if progress_cb:
        progress_cb(35)

    txt = ''
    try:
        hyp = asr.transcribe([wav_path])
        if isinstance(hyp, list) and hyp:
            first = hyp[0]
            if isinstance(first, str):
                txt = first.strip()
            else:
                txt = str(getattr(first, 'text', first) or '').strip()
    finally:
        if wav_path and wav_path != audio_path:
            try:
                os.unlink(wav_path)
            except Exception:
                pass

    if progress_cb:
        progress_cb(100)
    if log_cb:
        log_cb(f"NeMo: done. chars={len(txt)}")

    if not txt:
        return {"kind": "transcript", "text": "", "text_ts": "", "segments": [], "engine": "nemo", "model": model, "lang": language}

    end_ts = _fmt_ts(dur_s) if dur_s > 0 else _fmt_ts(0.0)
    text_ts = f"[{_fmt_ts(0.0)} - {end_ts}] {txt}" if dur_s > 0 else txt
    segs = [{"start": 0.0, "end": float(dur_s) if dur_s > 0 else 0.0, "text": txt}]
    return {"kind": "transcript", "text": txt, "text_ts": text_ts, "segments": segs, "engine": "nemo", "model": model, "lang": language}

def whisper_transcribe(audio_path: str, model: str, language: str, log_cb=None, progress_cb=None):
    if log_cb: log_cb(f"Whisper: load '{model}' (auto-download if missing)")
    if progress_cb: progress_cb(5)
    try:
        import whisper
    except Exception as e:
        raise RuntimeError("Missing 'openai-whisper'. Install: pip install openai-whisper") from e

    wmodel = whisper.load_model(model)
    if log_cb: log_cb("Whisper: model loaded. Transcribing")
    if progress_cb: progress_cb(20)

    lang = None if language == "auto" else language
    result = wmodel.transcribe(audio_path, language=lang, verbose=False)
    if progress_cb: progress_cb(90)

    text = (result.get("text") or "").strip()
    segments = result.get("segments") or []
    detected_lang = result.get("language") or None  # Whisper's detected language code (e.g. "pl", "en")

    # Export structured segments for the web UI (hover playback + per-block editing)
    segments_out = []
    lines = []
    for seg in segments:
        s0 = float(seg.get("start", 0.0))
        s1 = float(seg.get("end", 0.0))
        t = (seg.get("text") or "").strip()
        if not t:
            continue
        # Confidence: convert avg_logprob to 0-100% (exp of log-prob, clamped)
        avg_logprob = seg.get("avg_logprob", 0.0)
        confidence = max(0, min(100, int(math.exp(avg_logprob) * 100)))
        no_speech = round(seg.get("no_speech_prob", 0.0) * 100)
        segments_out.append({
            "start": s0, "end": s1, "text": t,
            "confidence": confidence,
            "no_speech": no_speech
        })
        lines.append(f"[{_fmt_ts(s0)} - {_fmt_ts(s1)}] {t}")
    text_ts = "\n".join(lines).strip() if lines else text

    if progress_cb: progress_cb(100)
    if log_cb: log_cb(f"Whisper: done. segments={len(segments)}")
    return {"kind": "transcript", "text": text, "text_ts": text_ts, "segments": segments_out, "engine": "whisper", "model": model, "lang": language, "detected_lang": detected_lang}
def whisper_transcribe_safe(
    audio_path: str,
    model: str,
    language: str,
    log_cb=None,
    progress_cb=None,
):
    """Run Whisper transcription in a separate process and stream ALL stderr into GUI logs.

    This captures:
      - openai-whisper warnings (e.g. FP16 -> FP32 on CPU)
      - language detection lines
      - tqdm progress bar (\r updates)

    Stdout is reserved strictly for JSON result.
    """

    import json
    import os
    import subprocess
    import sys
    import threading
    import queue
    import re

    worker_py = sys.executable  # use same venv/interpreter as GUI
    if log_cb:
        log_cb(f"whisper(worker): using python: {worker_py}")

    cmd = [
        worker_py,
        "-u",  # unbuffered IO
        "-m",
        "backend.transcribe_worker",
        "--audio",
        audio_path,
        "--model",
        model,
        "--lang",
        language,
    ]

    if log_cb:
        log_cb("whisper(worker): starting separate process…")

    # NOTE: We must continuously drain BOTH stderr and stdout.
    # Otherwise, for long recordings the final JSON on stdout can exceed the OS pipe buffer
    # and the worker will block on write, making the GUI think the transcription "finished"
    # (progress=100%, last stderr lines visible) while the task never returns.
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=False,  # IMPORTANT: binary mode for live tqdm (\r) streaming
        bufsize=0,
        cwd=os.path.dirname(os.path.dirname(__file__)),  # project root
        env={**os.environ.copy(), "PYTHONUNBUFFERED": "1"},
    )

    stderr_q: "queue.Queue[str]" = queue.Queue()
    stderr_all: list[str] = []

    def _push_line(line: str) -> None:
        if not line:
            return
        stderr_all.append(line)
        if not log_cb:
            return

        # Optional progress hook: allow worker to emit explicit progress lines
        if line.startswith("PROGRESS:"):
            try:
                pct = int(line.split(":", 1)[1].strip())
                if progress_cb:
                    progress_cb(pct)
            except Exception:
                log_cb(line)
            return

        log_cb(line)

    def _stderr_reader(p: subprocess.Popen) -> None:
        # Read raw bytes; tqdm prints with '\r' and without '\n'
        while True:
            chunk = p.stderr.read(1024)  # type: ignore[union-attr]
            if not chunk:
                break
            txt = chunk.decode("utf-8", errors="replace")
            txt = txt.replace("\r", "\n")
            for ln in txt.splitlines():
                ln = ln.strip("\n")
                if ln.strip():
                    stderr_q.put(ln)

    t = threading.Thread(target=_stderr_reader, args=(proc,), daemon=True)
    t.start()

    # Drain stdout in parallel to avoid deadlocks on large JSON payloads.
    stdout_chunks: list[bytes] = []

    def _stdout_reader(p: subprocess.Popen) -> None:
        if not p.stdout:
            return
        while True:
            chunk = p.stdout.read(4096)  # type: ignore[union-attr]
            if not chunk:
                break
            stdout_chunks.append(chunk)

    t_out = threading.Thread(target=_stdout_reader, args=(proc,), daemon=True)
    t_out.start()

    # Pump stderr LIVE while process runs
    while proc.poll() is None:
        try:
            ln = stderr_q.get(timeout=0.2)
            _push_line(ln)
        except queue.Empty:
            pass

    # Flush remaining stderr lines
    while True:
        try:
            ln = stderr_q.get_nowait()
            _push_line(ln)
        except queue.Empty:
            break

    # Ensure reader threads are done and collect stdout.
    try:
        t.join(timeout=1.0)
    except Exception:
        pass
    try:
        t_out.join(timeout=1.0)
    except Exception:
        pass

    out_bytes = b"".join(stdout_chunks)
    out = out_bytes.decode("utf-8", errors="replace")
    err = "\n".join(stderr_all)

    if proc.returncode != 0:
        tail_txt = "\n".join((err or "").strip().splitlines()[-12:])
        fail_text = (
            "[Transcription failed]\n"
            "The worker process crashed or exited with an error.\n"
            f"Exit code: {proc.returncode}\n\n"
            f"Last logs:\n{tail_txt}\n"
        )
        return {"kind": "transcript", "text": fail_text, "text_ts": "", "ok": False}

    out_str = (out or "").strip()
    if not out_str:
        tail_txt = "\n".join((err or "").strip().splitlines()[-20:])
        fail_text = (
            "[Transcription exception]\n"
            "Worker returned no JSON on stdout.\n\n"
            f"Last logs:\n{tail_txt}\n"
        )
        return {"kind": "transcript", "text": fail_text, "text_ts": "", "ok": False}

    # Parse JSON (guard against any accidental pollution)
    try:
        data = json.loads(out_str)
    except Exception:
        m = list(re.finditer(r"\{[\s\S]*\}\s*$", out_str))
        if m:
            data = json.loads(m[-1].group(0))
        else:
            raise

    if not isinstance(data, dict):
        return {"kind": "transcript", "text": str(data), "text_ts": "", "ok": True}

    data.setdefault("kind", "transcript")
    data.setdefault("ok", True)
    data.setdefault("text", "")
    data.setdefault("text_ts", data.get("text", ""))
    return data

def diarize_text_simple(text: str, speakers: int, method: str, log_cb=None, progress_cb=None):
    """Lightweight text diarization heuristics (no external deps required)."""
    def log(x: str) -> None:
        if log_cb:
            log_cb(x)

    if progress_cb: progress_cb(5)
    raw = (text or "").strip()
    if not raw:
        return {"kind": "diarized_text", "text": ""}

    lines = [l.strip() for l in raw.splitlines() if l.strip()]
    if not lines:
        return {"kind": "diarized_text", "text": ""}

    m = (method or "").lower()
    log(f"Text diarization: method='{method}', speakers={speakers}, lines={len(lines)}")

    def label(i: int) -> str:
        spk = (i % max(1, speakers)) + 1
        return f"SPK{spk}"

    # Keep existing tags if present
    if "keep" in m or "zachow" in m:
        out = []
        for ln in lines:
            if re.match(r"^(spk|speaker)\s*\d+[:\-]\s*", ln, re.I):
                out.append(ln)
            else:
                out.append(f"{label(len(out))}: {ln}")
        if progress_cb: progress_cb(100)
        return {"kind": "diarized_text", "text": "\n".join(out)}

    def split_sentences(text_line: str):
        parts = re.split(r"(?<=[\.\?\!])\s+", text_line.strip())
        return [p.strip() for p in parts if p.strip()]

    # Units: lines or sentences
    units = []
    if "sentence" in m or "zdani" in m:
        for ln in lines:
            units.extend(split_sentences(ln))
    else:
        units = list(lines)

    # Merge short units
    if "merge" in m or "łącz" in m:
        merged = []
        buf = ""
        for u in units:
            if len(buf) < 40:
                buf = (buf + " " + u).strip()
            else:
                merged.append(buf)
                buf = u
        if buf:
            merged.append(buf)
        units = merged
        log(f"Text diarization: merged units -> {len(units)}")

    out = []

    if ("naprzem" in m) or ("alternate" in m):
        for i, u in enumerate(units):
            out.append(f"{label(i)}: {u}")

    elif ("blok" in m) or ("block" in m):
        block = max(1, len(units) // max(1, speakers))
        spk = 1
        count = 0
        for u in units:
            out.append(f"SPK{spk}: {u}")
            count += 1
            if count >= block and spk < speakers:
                spk += 1
                count = 0

    elif "paragraph" in m or "akapit" in m:
        i = 0
        spk = 1
        while i < len(units):
            chunk = units[i:i+2]
            for u in chunk:
                out.append(f"SPK{spk}: {u}")
            spk = (spk % max(1, speakers)) + 1
            i += 2

    else:
        for i, u in enumerate(units):
            out.append(f"{label(i)}: {u}")

    if progress_cb: progress_cb(100)
    return {"kind": "diarized_text", "text": "\n".join(out)}


def diarize_voice_whisper_pyannote(
    audio_path: str,
    model: str,
    language: str,
    hf_token: str,
    diar_model: str | None = None,
    log_cb=None,
    progress_cb=None,
):
    """Whisper transcription + pyannote speaker diarization (worker-safe).

    IMPORTANT (stability):
      - We **do not** pass file paths directly into pyannote when possible.
        On some systems pyannote >= 4.x may try to use torchcodec/AudioDecoder
        for metadata/decoding and crash with:
          NameError: name 'AudioDecoder' is not defined
      - Instead we convert the input to PCM WAV (16kHz mono) and feed an
        in-memory waveform dict: {"waveform": Tensor, "sample_rate": int}.

    Compatible with:
      - pyannote.audio < 4.x: Pipeline(...) returns Annotation (has itertracks)
      - pyannote.audio >= 4.x: Pipeline(...) returns DiarizeOutput with
        .exclusive_speaker_diarization / .speaker_diarization (both are Annotation)
    """
    import os

    if log_cb:
        log_cb("Start: Whisper + pyannote")
        log_cb(f"HF token: {'OK' if hf_token else 'MISSING'} (hf_...)")

    # --- Whisper (segments) ---
    try:
        import torch
    except Exception as e:
        raise RuntimeError("Missing 'torch'. Install a torch build appropriate for your platform/GPU.") from e

    try:
        import whisper  # openai-whisper
    except Exception as e:
        raise RuntimeError("Missing 'openai-whisper'. Install: pip install openai-whisper") from e

    whisper_device = "cuda" if torch.cuda.is_available() else "cpu"
    if log_cb:
        try:
            gpu_name = torch.cuda.get_device_name(0) if whisper_device == "cuda" else "-"
        except Exception:
            gpu_name = "?"
        log_cb(f"Torch: cuda_available={torch.cuda.is_available()} whisper_device={whisper_device} gpu={gpu_name}")

    if log_cb:
        log_cb(f"Whisper: load '{model}' (auto-download if missing)")
    # Explicit device selection (important for reproducibility + logs)
    wmodel = whisper.load_model(model, device=whisper_device)
    lang = None if language == "auto" else language
    if log_cb:
        log_cb(f"Whisper: transcribe with segments (language={lang or 'auto'})")
    if progress_cb:
        progress_cb(5)

    wres = wmodel.transcribe(audio_path, language=lang, verbose=False)
    segments = wres.get("segments") or []

    if log_cb:
        log_cb(f"Whisper: segments={len(segments)}")

    if progress_cb:
        progress_cb(35)

    # --- pyannote ---
    _apply_onelogger_stubs(log_cb=log_cb)
    from pyannote.audio import Pipeline

    if not hf_token:
        raise RuntimeError("HF token missing. Set it in the app settings.")

    if log_cb:
        log_cb("pyannote: load speaker-diarization pipeline (auto-download if missing)")
    pipeline = _load_pyannote_pipeline(Pipeline, hf_token, log_cb, preferred_id=diar_model)

    # Move pyannote models to GPU if available (and if the installed pyannote supports it).
    pyannote_device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    if pyannote_device.type == "cuda":
        try:
            pipeline.to(pyannote_device)
            if log_cb:
                log_cb(f"pyannote: pipeline moved to {pyannote_device}")
        except Exception as e:
            # Some versions / dependency combos may not support .to(); fall back to CPU gracefully.
            pyannote_device = torch.device("cpu")
            if log_cb:
                log_cb(f"pyannote: pipeline.to(cuda) failed -> CPU fallback ({type(e).__name__}: {e})")


    if progress_cb:
        progress_cb(45)

    if log_cb:
        log_cb("pyannote: diarizing file (PCM WAV -> in-memory waveform)")

    # Always stabilize input to avoid sample-count mismatch and pyannote internal decoding.
    wav_path = _convert_to_pcm_wav_16k_mono(audio_path, log_cb=log_cb)
    try:
        try:
            import torch
            import soundfile as sf
        except Exception as e:
            raise RuntimeError(
                "Missing deps for robust pyannote audio loading. "
                "Install: pip install soundfile (and ensure torch is installed)."
            ) from e

        audio_np, sr = sf.read(wav_path, dtype="float32", always_2d=True)  # (time, channels)
        waveform = torch.from_numpy(audio_np.T)  # -> (channels, time)

        # Keep waveform device consistent with pyannote models to avoid device-mismatch errors.
        if 'pyannote_device' in locals() and getattr(pyannote_device, 'type', None) == 'cuda':
            waveform = waveform.to(pyannote_device)


        if log_cb:
            try:
                dur = float(waveform.shape[1]) / float(sr) if int(sr) > 0 else 0.0
                log_cb(f"Audio: loaded waveform (channels={waveform.shape[0]}, sample_rate={sr}, duration_s={dur:.2f})")
            except Exception:
                pass

        file_dict = {
            "waveform": waveform,
            "sample_rate": int(sr),
            "uri": os.path.basename(audio_path),
            "duration": float(waveform.shape[1]) / float(sr) if int(sr) > 0 else None,
        }

        diar = pipeline(file_dict)

    finally:
        try:
            os.unlink(wav_path)
        except Exception:
            pass

    if progress_cb:
        progress_cb(80)

    def get_annotation(diar_output):
        if hasattr(diar_output, "exclusive_speaker_diarization"):
            if log_cb:
                log_cb("pyannote: using output.exclusive_speaker_diarization")
            return diar_output.exclusive_speaker_diarization
        if hasattr(diar_output, "speaker_diarization"):
            if log_cb:
                log_cb("pyannote: using output.speaker_diarization")
            return diar_output.speaker_diarization
        if hasattr(diar_output, "itertracks"):
            if log_cb:
                log_cb("pyannote: using output (Annotation)")
            return diar_output
        raise RuntimeError(
            f"Unknown pyannote output type: {type(diar_output)}. Expected DiarizeOutput or Annotation."
        )

    annotation = get_annotation(diar)

    turns = []
    for turn, _, speaker in annotation.itertracks(yield_label=True):
        turns.append((float(turn.start), float(turn.end), str(speaker)))

    if log_cb:
        log_cb(f"pyannote: found {len(turns)} speaker turns")

    def overlap(a0, a1, b0, b1):
        return max(0.0, min(a1, b1) - max(a0, b0))

    out_lines = []
    segments_out = []
    for seg in segments:
        s0 = float(seg.get("start", 0.0))
        s1 = float(seg.get("end", 0.0))
        txt = (seg.get("text") or "").strip()
        if not txt:
            continue

        best_spk = "UNKNOWN"
        best_ov = 0.0
        for t0, t1, spk in turns:
            ov = overlap(s0, s1, t0, t1)
            if ov > best_ov:
                best_ov = ov
                best_spk = spk

        out_lines.append(f"[{s0:.2f}-{s1:.2f}] {best_spk}: {txt}")
        seg_out = {"start": s0, "end": s1, "speaker": best_spk, "text": txt}
        # Calculate confidence from Whisper's avg_logprob (same as whisper_transcribe)
        avg_logprob = seg.get("avg_logprob", 0.0)
        confidence = max(0, min(100, int(math.exp(avg_logprob) * 100)))
        no_speech = round(seg.get("no_speech_prob", 0.0) * 100)
        seg_out["confidence"] = confidence
        seg_out["no_speech"] = no_speech
        segments_out.append(seg_out)

    # Join diarized segments into final text.
    text = "\n".join(out_lines) if out_lines else (wres.get("text") or "").strip()

    if progress_cb:
        progress_cb(100)

    return {"kind": "diarized_voice", "text": text, "segments": segments_out, "ok": True}


def diarize_voice_whisper_pyannote_safe(
    audio_path: str,
    model: str,
    language: str,
    hf_token: str,
    log_cb=None,
    progress_cb=None,
):
    """Run Whisper+pyannote diarization in a separate process.

    - Streams worker stderr LIVE into GUI logs (so you see progress)
    - Keeps stdout for JSON result (read after process ends)
    """
    import json
    import os
    import re
    import subprocess
    import sys
    import threading
    import queue

    worker_py = sys.executable  # always use the same venv/interpreter as GUI
    if log_cb:
        log_cb(f"pyannote(worker): using python: {worker_py}")

    cmd = [
        worker_py,
        "-m",
        "backend.voice_worker",
        "--audio",
        audio_path,
        "--model",
        model,
        "--lang",
        language,
        "--hf_token",
        hf_token,
    ]

    if log_cb:
        log_cb("pyannote(worker): starting separate process…")

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=False,  # IMPORTANT: binary mode for live tqdm (\r) streaming
            bufsize=0,
            cwd=os.path.dirname(os.path.dirname(__file__)),  # project root
            env=os.environ.copy(),
        )

        stderr_q: "queue.Queue[str]" = queue.Queue()
        stderr_all: list[str] = []

        def _push_line(line: str) -> None:
            if not line:
                return
            stderr_all.append(line)
            if not log_cb:
                return
            if line.startswith("PROGRESS:"):
                try:
                    pct = int(line.split(":", 1)[1].strip())
                    if progress_cb:
                        progress_cb(pct)
                except Exception:
                    log_cb(line)
            else:
                log_cb(line)

        def _stderr_reader(p: subprocess.Popen) -> None:
            # Read raw bytes; tqdm prints with '\r' (carriage return) and no '\n'
            while True:
                chunk = p.stderr.read(1024)  # type: ignore[union-attr]
                if not chunk:
                    break
                txt = chunk.decode("utf-8", errors="replace")
                # Make tqdm lines visible in GUI
                txt = txt.replace("\r", "\n")
                for ln in txt.splitlines():
                    if ln.strip():
                        stderr_q.put(ln)

        t = threading.Thread(target=_stderr_reader, args=(proc,), daemon=True)
        t.start()

        # Pump stderr lines LIVE while process runs
        while proc.poll() is None:
            try:
                ln = stderr_q.get(timeout=0.2)
                _push_line(ln)
            except queue.Empty:
                pass

        # Flush remaining stderr lines
        while True:
            try:
                ln = stderr_q.get_nowait()
                _push_line(ln)
            except queue.Empty:
                break

        # Now read stdout (JSON) after worker ends
        out_bytes = b""
        if proc.stdout:
            out_bytes = proc.stdout.read() or b""
        out = out_bytes.decode("utf-8", errors="replace")
        err = "\n".join(stderr_all)

        # If worker failed, return a helpful error
        if proc.returncode != 0:
            tail = (err or "").strip().splitlines()[-10:]
            tail_txt = "\n".join(tail)
            fail_text = (
                "[Voice diarization failed]\n"
                "The worker process crashed or exited with an error.\n"
                f"Exit code: {proc.returncode}\n\n"
                f"Last logs:\n{tail_txt}\n"
            )
            return {"kind": "diarized_voice", "text": fail_text, "ok": False}

        # Worker succeeded but stdout might be empty or contain non-JSON
        out_str = (out or "").strip()
        if not out_str:
            tail = (err or "").strip().splitlines()[-15:]
            tail_txt = "\n".join(tail)
            fail_text = (
                "[Voice diarization exception]\n"
                "Worker returned no JSON on stdout.\n\n"
                f"Last logs:\n{tail_txt}\n"
            )
            return {"kind": "diarized_voice", "text": fail_text, "ok": False}

        # Try parse JSON
        try:
            data = json.loads(out_str)
        except Exception:
            # Try to recover: find last JSON object in stdout (in case something polluted stdout)
            m = list(re.finditer(r"\{[\s\S]*\}\s*$", out_str))
            if m:
                data = json.loads(m[-1].group(0))
            else:
                raise

        if not isinstance(data, dict):
            return {"kind": "diarized_voice", "text": str(data), "ok": True}

        data.setdefault("kind", "diarized_voice")
        data.setdefault("ok", True)
        return data

    except Exception as e:
        if log_cb:
            log_cb("pyannote(worker): exception: " + str(e))
        fail_text = "[Voice diarization exception]\n" + str(e)
        return {"kind": "diarized_voice", "text": fail_text, "ok": False}
