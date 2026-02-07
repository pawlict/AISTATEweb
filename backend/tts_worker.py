#!/usr/bin/env python3
"""TTS Worker - handles model installation, download, and speech synthesis.

Supports:
- Piper TTS  (VITS, fast, ~50 languages, MIT)
- MMS-TTS    (Meta, VITS, 1100+ languages, HuggingFace)
- Kokoro     (StyleTTS2, very fast, 9 languages, Apache 2.0)

All models are fully offline after initial download.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path


# ---------------------------------------------------------------------------
# Progress output for task tracking
# ---------------------------------------------------------------------------

def _progress(pct: int) -> None:
    print(f"PROGRESS: {max(0, min(100, int(pct)))}", file=sys.stderr, flush=True)


def _log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


# ---------------------------------------------------------------------------
# MODEL DEFINITIONS
# ---------------------------------------------------------------------------

TTS_ENGINES = {
    "piper": {
        "name": "Piper TTS",
        "packages": ["piper-tts", "pathvalidate"],
        "size_mb": 30,
        "description": "Szybki, lekki silnik TTS oparty na VITS. Dziala offline, zoptymalizowany pod CPU. Modele 15-60 MB na jezyk.",
        "description_en": "Fast, lightweight VITS-based TTS engine. Fully offline, optimized for CPU. Models 15-60 MB per language.",
        "languages": "~50",
        "quality": "good",
        "speed": "very_fast",
        "cpu_realtime_factor": "0.1x",
        "gpu_benefit": "minimal",
        "license": "MIT",
    },
    "mms": {
        "name": "MMS-TTS (Meta)",
        "packages": ["transformers", "torch", "scipy"],
        "size_mb": 30,
        "description": "Meta Massively Multilingual Speech - ponad 1100 jezykow. Jakość OK, najszersze pokrycie jezykowe.",
        "description_en": "Meta Massively Multilingual Speech - 1100+ languages. OK quality, widest language coverage available.",
        "languages": "1100+",
        "quality": "ok",
        "speed": "fast",
        "cpu_realtime_factor": "0.3x",
        "gpu_benefit": "moderate",
        "license": "CC-BY-NC-4.0",
    },
    "kokoro": {
        "name": "Kokoro TTS",
        "packages": ["kokoro>=0.3", "soundfile"],
        "size_mb": 82,
        "description": "Bardzo szybki, naturalny glos. 82 MB model obslugujacy 9 jezykow z wysoką jakoscia.",
        "description_en": "Very fast, natural sounding. 82 MB single model supporting 9 languages with high quality.",
        "languages": "9",
        "quality": "very_good",
        "speed": "very_fast",
        "cpu_realtime_factor": "0.15x",
        "gpu_benefit": "moderate",
        "license": "Apache 2.0",
    },
}

# Language -> voice mappings per engine
LANG_VOICE_MAP = {
    "polish": {
        "piper": "pl_PL-gosia-medium",
        "mms": "facebook/mms-tts-pol",
        "kokoro": None,
    },
    "english": {
        "piper": "en_US-amy-medium",
        "mms": "facebook/mms-tts-eng",
        "kokoro": "af_heart",
    },
    "russian": {
        "piper": "ru_RU-irina-medium",
        "mms": "facebook/mms-tts-rus",
        "kokoro": None,
    },
    "ukrainian": {
        "piper": "uk_UA-ukrainian_tts-medium",
        "mms": "facebook/mms-tts-ukr",
        "kokoro": None,
    },
    "belarusian": {
        "piper": None,
        "mms": "facebook/mms-tts-bel",
        "kokoro": None,
    },
    "german": {
        "piper": "de_DE-thorsten-medium",
        "mms": "facebook/mms-tts-deu",
        "kokoro": "bf_emma",
    },
    "french": {
        "piper": "fr_FR-siwis-medium",
        "mms": "facebook/mms-tts-fra",
        "kokoro": "ff_siwis",
    },
    "spanish": {
        "piper": "es_ES-sharvard-medium",
        "mms": "facebook/mms-tts-spa",
        "kokoro": "ef_dora",
    },
    "italian": {
        "piper": "it_IT-riccardo-x_low",
        "mms": "facebook/mms-tts-ita",
        "kokoro": "if_sara",
    },
    "portuguese": {
        "piper": "pt_BR-faber-medium",
        "mms": "facebook/mms-tts-por",
        "kokoro": None,
    },
    "chinese": {
        "piper": "zh_CN-huayan-medium",
        "mms": "facebook/mms-tts-cmn",
        "kokoro": "zf_xiaobei",
    },
    "japanese": {
        "piper": "ja_JP-kokoro-medium",
        "mms": "facebook/mms-tts-jpn",
        "kokoro": "jf_alpha",
    },
    "korean": {
        "piper": "ko_KR-korean-medium",
        "mms": "facebook/mms-tts-kor",
        "kokoro": "kf_yuha",
    },
    "turkish": {
        "piper": "tr_TR-dfki-medium",
        "mms": "facebook/mms-tts-tur",
        "kokoro": None,
    },
    "dutch": {
        "piper": "nl_NL-mls-medium",
        "mms": "facebook/mms-tts-nld",
        "kokoro": None,
    },
    "czech": {
        "piper": "cs_CZ-jirka-medium",
        "mms": "facebook/mms-tts-ces",
        "kokoro": None,
    },
    "swedish": {
        "piper": "sv_SE-nst-medium",
        "mms": "facebook/mms-tts-swe",
        "kokoro": None,
    },
    "arabic": {
        "piper": "ar_JO-kareem-medium",
        "mms": "facebook/mms-tts-arb",
        "kokoro": None,
    },
    "hindi": {
        "piper": "hi_IN-rohan-medium",
        "mms": "facebook/mms-tts-hin",
        "kokoro": "hf_alpha",
    },
}

# Cache directory
CACHE_DIR = Path(__file__).parent / "models_cache" / "tts"
CACHE_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# PACKAGE INSTALLATION
# ---------------------------------------------------------------------------

def pip_install(packages: list[str]) -> bool:
    """Install Python packages via pip."""
    import subprocess

    _log(f"Installing packages: {packages}")
    _progress(10)

    try:
        cmd = [sys.executable, "-m", "pip", "install", "--upgrade"] + packages
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )

        for line in process.stdout:
            line = line.rstrip()
            if line:
                _log(line)

        process.wait()

        if process.returncode != 0:
            _log(f"pip install failed with code {process.returncode}")
            return False

        _progress(90)
        _log("Packages installed successfully")
        return True
    except Exception as e:
        _log(f"Installation error: {e}")
        return False


def install_engine_deps(engine: str) -> bool:
    """Install dependencies for a specific TTS engine."""
    if engine not in TTS_ENGINES:
        _log(f"Unknown TTS engine: {engine}")
        return False

    info = TTS_ENGINES[engine]
    packages = info.get("packages", [])

    if not packages:
        _log("No packages to install")
        _progress(100)
        return True

    result = pip_install(packages)
    _progress(100)
    _log(f"Installation {'completed' if result else 'failed'}")
    return result


# ---------------------------------------------------------------------------
# MODEL DOWNLOAD / CACHE
# ---------------------------------------------------------------------------

def _piper_voice_url(voice_id: str) -> tuple[str, str]:
    """Build HuggingFace download URLs for a Piper voice.

    Voice ID format: {locale}-{name}-{quality}  e.g. pl_PL-gosia-medium
    Quality can be: x_low, low, medium, high
    Returns (onnx_url, json_url).
    """
    QUALITIES = ("x_low", "low", "medium", "high")

    # Split: locale = "pl_PL", remainder = "gosia-medium"
    first_dash = voice_id.index("-")
    locale = voice_id[:first_dash]              # "pl_PL"
    remainder = voice_id[first_dash + 1:]       # "gosia-medium"

    # Match quality from known suffixes (handles x_low which contains a dash-like _)
    quality = "medium"
    name = remainder
    for q in QUALITIES:
        if remainder.endswith("-" + q):
            quality = q
            name = remainder[:-(len(q) + 1)]
            break

    lang_short = locale.split("_")[0]           # "pl"

    base = (
        f"https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/"
        f"{lang_short}/{locale}/{name}/{quality}/{voice_id}"
    )
    return f"{base}.onnx", f"{base}.onnx.json"


def _piper_voice_path(voice_id: str) -> Path:
    """Return local path for a Piper voice .onnx file."""
    return CACHE_DIR / "piper_voices" / f"{voice_id}.onnx"


def predownload_piper(voice: str = "") -> bool:
    """Download and cache a Piper voice model from HuggingFace."""
    _log("=" * 50)
    _log("Downloading Piper TTS voice")
    _log("=" * 50)
    _progress(5)

    try:
        import urllib.request

        voice_id = voice or "en_US-amy-medium"
        _log(f"Voice: {voice_id}")

        voices_dir = CACHE_DIR / "piper_voices"
        voices_dir.mkdir(parents=True, exist_ok=True)

        onnx_path = voices_dir / f"{voice_id}.onnx"
        json_path = voices_dir / f"{voice_id}.onnx.json"

        onnx_url, json_url = _piper_voice_url(voice_id)

        # Download .onnx model
        if onnx_path.exists():
            _log(f"Model file already exists: {onnx_path.name}")
        else:
            _progress(10)
            _log(f"Downloading: {onnx_url}")
            _log("This may take a moment (~15-60 MB)...")
            tmp = onnx_path.with_suffix(".onnx.tmp")
            try:
                urllib.request.urlretrieve(onnx_url, str(tmp))
                tmp.rename(onnx_path)
            except Exception:
                tmp.unlink(missing_ok=True)
                raise
            _log(f"Downloaded: {onnx_path.name} ({onnx_path.stat().st_size // 1024} KB)")

        # Download .onnx.json config
        _progress(70)
        if json_path.exists():
            _log(f"Config file already exists: {json_path.name}")
        else:
            _log(f"Downloading config: {json_url}")
            urllib.request.urlretrieve(json_url, str(json_path))
            _log(f"Downloaded: {json_path.name}")

        _progress(85)

        # Verify files
        if not onnx_path.exists() or onnx_path.stat().st_size < 1000:
            _log("ERROR: ONNX model file is missing or too small")
            return False
        if not json_path.exists():
            _log("ERROR: Config JSON file is missing")
            return False

        _log("Voice files verified")

        # Write marker file
        marker = CACHE_DIR / f"piper_{voice_id}.json"
        marker.write_text(json.dumps({
            "engine": "piper",
            "voice": voice_id,
            "onnx_path": str(onnx_path),
            "downloaded_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "status": "ready",
        }))

        _progress(100)
        _log(f"Piper voice '{voice_id}' ready!")
        return True

    except Exception as e:
        _log(f"ERROR: Piper download failed: {e}")
        return False


def predownload_mms(lang_code: str = "") -> bool:
    """Download and cache an MMS-TTS model from HuggingFace."""
    _log("=" * 50)
    _log("Downloading MMS-TTS model (Meta / HuggingFace)")
    _log("Model size: ~30 MB per language")
    _log("=" * 50)
    _progress(5)

    try:
        _log("Importing transformers...")
        from transformers import VitsModel, AutoTokenizer

        _progress(10)
        model_id = lang_code or "facebook/mms-tts-eng"
        if not model_id.startswith("facebook/"):
            model_id = f"facebook/mms-tts-{model_id}"

        _log(f"Model: {model_id}")
        _log("Connecting to HuggingFace Hub...")

        _progress(20)
        _log("Downloading tokenizer...")
        AutoTokenizer.from_pretrained(model_id)

        _progress(50)
        _log("Downloading model weights...")
        VitsModel.from_pretrained(model_id)

        _progress(90)
        _log("MMS-TTS model downloaded successfully")

        # Extract short lang code for marker
        short = model_id.split("mms-tts-")[-1] if "mms-tts-" in model_id else model_id
        marker = CACHE_DIR / f"mms_{short}.json"
        marker.write_text(json.dumps({
            "engine": "mms",
            "model_id": model_id,
            "lang_code": short,
            "downloaded_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "status": "ready",
        }))

        _progress(100)
        _log(f"MMS-TTS '{model_id}' ready!")
        return True

    except Exception as e:
        _log(f"ERROR: MMS-TTS download failed: {e}")
        return False


def predownload_kokoro() -> bool:
    """Download and cache Kokoro TTS model."""
    _log("=" * 50)
    _log("Downloading Kokoro TTS model")
    _log("Model size: ~82 MB")
    _log("=" * 50)
    _progress(5)

    try:
        _log("Importing kokoro...")
        from kokoro import KPipeline

        _progress(10)
        _log("Initializing pipeline (this downloads the model)...")

        # Initialize with English to trigger model download
        pipeline = KPipeline(lang_code="a")

        _progress(85)
        _log("Kokoro model downloaded successfully")

        # Write marker file
        marker = CACHE_DIR / "kokoro.json"
        marker.write_text(json.dumps({
            "engine": "kokoro",
            "downloaded_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "status": "ready",
        }))

        _progress(100)
        _log("Kokoro TTS ready!")
        return True

    except Exception as e:
        _log(f"ERROR: Kokoro download failed: {e}")
        return False


def predownload_engine(engine: str, voice: str = "") -> bool:
    """Download and cache a model for the given engine."""
    if engine == "piper":
        return predownload_piper(voice)
    elif engine == "mms":
        return predownload_mms(voice)
    elif engine == "kokoro":
        return predownload_kokoro()
    else:
        _log(f"Unknown engine: {engine}")
        return False


# ---------------------------------------------------------------------------
# SPEECH SYNTHESIS
# ---------------------------------------------------------------------------

def synthesize_piper(text: str, voice: str, output_path: str) -> bool:
    """Generate speech using Piper TTS."""
    _log(f"Piper TTS: synthesizing ({len(text)} chars)...")
    _progress(10)

    try:
        from piper.voice import PiperVoice

        voices_dir = CACHE_DIR / "piper_voices"
        onnx_path = voices_dir / f"{voice}.onnx"

        if not onnx_path.exists():
            # Try downloading on-the-fly
            _log(f"Voice '{voice}' not found locally, attempting download...")
            if not predownload_piper(voice):
                _log(f"ERROR: Failed to download voice '{voice}'")
                return False

        if not onnx_path.exists():
            _log(f"ERROR: Voice model file not found at {onnx_path}")
            return False

        _log(f"Loading model: {onnx_path.name}")
        _progress(20)
        pv = PiperVoice.load(str(onnx_path))

        _progress(40)
        _log("Generating audio...")

        import wave
        with wave.open(output_path, "wb") as wav:
            # Pre-set WAV params before synthesize() writes frames.
            # Some piper-tts versions don't set them, causing
            # "# channels not specified" from the wave module.
            wav.setnchannels(1)
            wav.setsampwidth(2)  # 16-bit PCM
            wav.setframerate(pv.config.sample_rate)
            pv.synthesize(text, wav)

        _progress(90)
        _log(f"Audio saved to {output_path}")
        return True

    except Exception as e:
        _log(f"ERROR: Piper synthesis failed: {e}")
        return False


def synthesize_mms(text: str, model_id: str, output_path: str) -> bool:
    """Generate speech using MMS-TTS."""
    _log(f"MMS-TTS: synthesizing ({len(text)} chars)...")
    _progress(10)

    try:
        import torch
        import scipy.io.wavfile
        from transformers import VitsModel, AutoTokenizer

        if not model_id.startswith("facebook/"):
            model_id = f"facebook/mms-tts-{model_id}"

        _progress(15)
        _log(f"Loading model: {model_id}")

        # Use GPU if available
        device = "cuda" if torch.cuda.is_available() else "cpu"
        _log(f"Device: {device}")

        tokenizer = AutoTokenizer.from_pretrained(model_id)
        model = VitsModel.from_pretrained(model_id).to(device)

        _progress(40)
        _log("Generating speech...")

        inputs = tokenizer(text, return_tensors="pt").to(device)
        with torch.no_grad():
            output = model(**inputs).waveform

        _progress(80)
        waveform = output.squeeze().cpu().float().numpy()
        rate = model.config.sampling_rate

        scipy.io.wavfile.write(output_path, rate=rate, data=waveform)

        _progress(90)
        _log(f"Audio saved to {output_path} (rate={rate}Hz)")
        return True

    except Exception as e:
        _log(f"ERROR: MMS synthesis failed: {e}")
        return False


def synthesize_kokoro(text: str, voice: str, output_path: str, lang_code: str = "a") -> bool:
    """Generate speech using Kokoro TTS."""
    _log(f"Kokoro TTS: synthesizing ({len(text)} chars)...")
    _progress(10)

    try:
        import soundfile as sf
        from kokoro import KPipeline

        # Map language to Kokoro lang_code
        kokoro_lang_map = {
            "english": "a", "british": "b", "spanish": "e",
            "french": "f", "hindi": "h", "italian": "i",
            "japanese": "j", "korean": "k", "chinese": "z",
            "german": "b",  # uses British-adjacent voice set
        }

        code = kokoro_lang_map.get(lang_code, lang_code) if len(lang_code) > 1 else lang_code

        _progress(15)
        _log(f"Language code: {code}, Voice: {voice}")

        pipeline = KPipeline(lang_code=code)

        _progress(30)
        _log("Generating audio...")

        # Kokoro generates audio in chunks
        audio_chunks = []
        for i, (gs, ps, audio) in enumerate(pipeline(text, voice=voice)):
            audio_chunks.append(audio)

        _progress(80)

        if not audio_chunks:
            _log("ERROR: No audio generated")
            return False

        import numpy as np
        full_audio = np.concatenate(audio_chunks)
        sf.write(output_path, full_audio, 24000)

        _progress(90)
        _log(f"Audio saved to {output_path}")
        return True

    except Exception as e:
        _log(f"ERROR: Kokoro synthesis failed: {e}")
        return False


def synthesize(engine: str, text: str, voice: str, output_path: str, lang: str = "") -> bool:
    """Main synthesis entry point."""
    if engine == "piper":
        ok = synthesize_piper(text, voice, output_path)
    elif engine == "mms":
        ok = synthesize_mms(text, voice, output_path)
    elif engine == "kokoro":
        ok = synthesize_kokoro(text, voice, output_path, lang_code=lang)
    else:
        _log(f"Unknown engine: {engine}")
        return False

    _progress(100)
    return ok


# ---------------------------------------------------------------------------
# CLI ENTRY POINT
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="TTS Worker")
    parser.add_argument("--action", choices=["install", "predownload", "synthesize"], required=True)
    parser.add_argument("--engine", default="piper", help="TTS engine (piper, mms, kokoro)")
    parser.add_argument("--voice", default="", help="Voice/model identifier")
    parser.add_argument("--text", default="", help="Text to synthesize")
    parser.add_argument("--lang", default="", help="Language hint")
    parser.add_argument("--output", default="", help="Output audio file path")

    args = parser.parse_args()

    success = False

    if args.action == "install":
        success = install_engine_deps(args.engine)

    elif args.action == "predownload":
        success = predownload_engine(args.engine, args.voice)

    elif args.action == "synthesize":
        if not args.text:
            _log("--text required for synthesize action")
            sys.exit(1)
        if not args.output:
            _log("--output required for synthesize action")
            sys.exit(1)

        success = synthesize(args.engine, args.text, args.voice, args.output, args.lang)

        if success:
            result = {
                "engine": args.engine,
                "voice": args.voice,
                "output": args.output,
                "chars": len(args.text),
                "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
            print(json.dumps(result, ensure_ascii=False))

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
