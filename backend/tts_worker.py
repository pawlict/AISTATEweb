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
        "packages": ["piper-tts"],
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
        "piper": "hi-mya-medium",
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

def predownload_piper(voice: str = "") -> bool:
    """Download and cache a Piper voice model."""
    _log("=" * 50)
    _log("Downloading Piper TTS voice")
    _log("=" * 50)
    _progress(5)

    try:
        _log("Importing piper...")
        # piper-tts downloads voices on first use to ~/.local/share/piper_tts/
        # We trigger the download by listing/downloading the voice
        import subprocess

        _progress(10)
        voice_id = voice or "en_US-amy-medium"
        _log(f"Voice: {voice_id}")
        _log("Downloading voice data (onnx model + config)...")

        # Use piper CLI to download the voice
        cmd = [
            sys.executable, "-m", "piper",
            "--model", voice_id,
            "--download-dir", str(CACHE_DIR / "piper_voices"),
            "--update-voices",
            "--output_file", "/dev/null",
        ]

        _progress(20)

        # Feed empty stdin to just trigger the download, then exit
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        # Send empty input to produce no audio, just download
        out, _ = proc.communicate(input="", timeout=300)
        if out:
            for line in out.strip().split("\n"):
                if line.strip():
                    _log(line.strip())

        _progress(85)
        _log("Voice downloaded")

        # Write marker file
        marker = CACHE_DIR / f"piper_{voice_id}.json"
        marker.write_text(json.dumps({
            "engine": "piper",
            "voice": voice_id,
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
        from piper import PiperVoice

        voices_dir = CACHE_DIR / "piper_voices"
        # Find the model file
        onnx_files = list(voices_dir.rglob(f"{voice}*.onnx"))
        if not onnx_files:
            # Try downloading on-the-fly
            _log(f"Voice '{voice}' not found locally, attempting download...")
            predownload_piper(voice)
            onnx_files = list(voices_dir.rglob(f"{voice}*.onnx"))

        if not onnx_files:
            _log(f"ERROR: Voice model file not found for '{voice}'")
            return False

        model_path = str(onnx_files[0])
        _log(f"Using model: {model_path}")

        _progress(20)
        pv = PiperVoice.load(model_path)

        _progress(40)
        import wave
        with wave.open(output_path, "wb") as wav:
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
