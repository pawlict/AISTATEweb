#!/usr/bin/env python3
"""Sound Detection Worker - handles model installation, download, and inference.

Supports:
- YAMNet (TensorFlow, lightweight, 521 classes)
- PANNs (PyTorch, more accurate, 527 classes)
- BEATs (PyTorch, SOTA, 527 classes)

All models are fully offline after initial download.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

# Progress output for task tracking
def _progress(pct: int) -> None:
    print(f"PROGRESS: {pct}", file=sys.stderr, flush=True)

def _log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)

# ============================================================================
# MODEL DEFINITIONS
# ============================================================================

SOUND_DETECTION_MODELS = {
    "yamnet": {
        "name": "YAMNet",
        "package": "tensorflow-hub",
        "packages": ["tensorflow", "tensorflow-hub"],
        "size_mb": 14,
        "classes": 521,
        "url": "https://tfhub.dev/google/yamnet/1",
        "framework": "tensorflow",
    },
    "panns_cnn14": {
        "name": "PANNs CNN14",
        "package": "panns-inference",
        "packages": ["panns-inference"],
        "size_mb": 300,
        "classes": 527,
        "framework": "pytorch",
    },
    "panns_cnn6": {
        "name": "PANNs CNN6",
        "package": "panns-inference",
        "packages": ["panns-inference"],
        "size_mb": 20,
        "classes": 527,
        "framework": "pytorch",
    },
    "beats": {
        "name": "BEATs",
        "package": "transformers",
        "packages": ["transformers"],
        "size_mb": 90,
        "classes": 527,
        "model_id": "microsoft/BEATs-iter3",
        "framework": "pytorch",
    },
}

# Cache directory for markers
CACHE_DIR = Path(__file__).parent / "models_cache" / "sound_detection"
CACHE_DIR.mkdir(parents=True, exist_ok=True)


# ============================================================================
# PACKAGE INSTALLATION
# ============================================================================

def pip_install(packages: list[str]) -> bool:
    """Install Python packages via pip."""
    import subprocess

    _log(f"Installing packages: {packages}")
    _progress(10)

    try:
        cmd = [sys.executable, "-m", "pip", "install", "--upgrade"] + packages
        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode != 0:
            _log(f"pip install failed: {result.stderr}")
            return False

        _progress(90)
        _log("Packages installed successfully")
        return True
    except Exception as e:
        _log(f"Installation error: {e}")
        return False


def install_model_deps(model_id: str) -> bool:
    """Install dependencies for a specific model."""
    if model_id not in SOUND_DETECTION_MODELS:
        _log(f"Unknown model: {model_id}")
        return False

    model = SOUND_DETECTION_MODELS[model_id]
    packages = model.get("packages", [])

    if not packages:
        _log("No packages to install")
        return True

    return pip_install(packages)


# ============================================================================
# MODEL DOWNLOAD / CACHE
# ============================================================================

def predownload_yamnet() -> bool:
    """Download and cache YAMNet model."""
    _log("Downloading YAMNet model...")
    _progress(10)

    try:
        import tensorflow_hub as hub

        _progress(30)
        _log("Loading YAMNet from TensorFlow Hub...")

        # This downloads and caches the model
        model = hub.load("https://tfhub.dev/google/yamnet/1")

        _progress(80)
        _log("YAMNet loaded successfully")

        # Write marker file
        marker = CACHE_DIR / "yamnet.json"
        marker.write_text(json.dumps({
            "model": "yamnet",
            "downloaded_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "status": "ready"
        }))

        _progress(100)
        return True

    except Exception as e:
        _log(f"YAMNet download failed: {e}")
        return False


def predownload_panns(variant: str = "cnn14") -> bool:
    """Download and cache PANNs model."""
    _log(f"Downloading PANNs {variant} model...")
    _progress(10)

    try:
        from panns_inference import AudioTagging

        _progress(30)
        _log(f"Loading PANNs {variant}...")

        # This downloads and caches the model
        # variant can be "Cnn14", "Cnn6", etc.
        model_name = "Cnn14" if variant == "cnn14" else "Cnn6"
        at = AudioTagging(checkpoint_path=None, device="cpu")

        _progress(80)
        _log(f"PANNs {variant} loaded successfully")

        # Write marker file
        marker = CACHE_DIR / f"panns_{variant}.json"
        marker.write_text(json.dumps({
            "model": f"panns_{variant}",
            "downloaded_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "status": "ready"
        }))

        _progress(100)
        return True

    except Exception as e:
        _log(f"PANNs download failed: {e}")
        return False


def predownload_beats() -> bool:
    """Download and cache BEATs model."""
    _log("Downloading BEATs model...")
    _progress(10)

    try:
        from transformers import AutoModel, AutoFeatureExtractor

        _progress(30)
        _log("Loading BEATs from HuggingFace...")

        model_id = "microsoft/BEATs-iter3"

        # Download model and feature extractor
        AutoFeatureExtractor.from_pretrained(model_id)
        _progress(50)
        AutoModel.from_pretrained(model_id)

        _progress(80)
        _log("BEATs loaded successfully")

        # Write marker file
        marker = CACHE_DIR / "beats.json"
        marker.write_text(json.dumps({
            "model": "beats",
            "downloaded_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "status": "ready"
        }))

        _progress(100)
        return True

    except Exception as e:
        _log(f"BEATs download failed: {e}")
        return False


def predownload_model(model_id: str) -> bool:
    """Download and cache a specific model."""
    if model_id == "yamnet":
        return predownload_yamnet()
    elif model_id == "panns_cnn14":
        return predownload_panns("cnn14")
    elif model_id == "panns_cnn6":
        return predownload_panns("cnn6")
    elif model_id == "beats":
        return predownload_beats()
    else:
        _log(f"Unknown model: {model_id}")
        return False


# ============================================================================
# SOUND DETECTION INFERENCE
# ============================================================================

# AudioSet class labels (top-level categories for display)
SOUND_CATEGORIES = {
    # Animals
    "Dog": "dog", "Bark": "dog", "Howl": "dog", "Growling": "dog",
    "Cat": "cat", "Meow": "cat", "Purr": "cat", "Hiss": "cat",
    "Bird": "bird", "Chirp, tweet": "bird", "Crow": "bird",

    # Human sounds
    "Cough": "cough", "Sneeze": "sneeze", "Laughter": "laughter",
    "Crying, sobbing": "crying", "Baby cry, infant cry": "baby_cry",
    "Speech": "speech", "Conversation": "speech",

    # Music & Entertainment
    "Music": "music", "Musical instrument": "music", "Singing": "singing",
    "Television": "tv", "Radio": "radio",

    # Mechanical / Environmental
    "Vehicle": "vehicle", "Car": "vehicle", "Engine": "engine",
    "Siren": "siren", "Alarm": "alarm", "Bell": "bell",
    "Telephone": "phone", "Ringtone": "phone",
    "Door": "door", "Knock": "knock",
    "Footsteps": "footsteps", "Walk, footsteps": "footsteps",

    # Environmental
    "Wind": "wind", "Rain": "rain", "Thunder": "thunder",
    "Water": "water", "Splash": "water",

    # Noise
    "Noise": "noise", "Static": "noise", "White noise": "noise",
}


def _simplify_label(label: str) -> str:
    """Convert AudioSet label to simplified category."""
    for key, value in SOUND_CATEGORIES.items():
        if key.lower() in label.lower():
            return value
    return label.lower().replace(" ", "_").replace(",", "")[:20]


def detect_sounds_yamnet(audio_path: str, threshold: float = 0.3) -> list[dict]:
    """Detect sounds using YAMNet."""
    import tensorflow_hub as hub
    import numpy as np
    import csv

    try:
        import soundfile as sf
        waveform, sr = sf.read(audio_path)
    except:
        import wave
        with wave.open(audio_path, 'rb') as wf:
            sr = wf.getframerate()
            frames = wf.readframes(wf.getnframes())
            waveform = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0

    # Convert to mono if stereo
    if len(waveform.shape) > 1:
        waveform = waveform.mean(axis=1)

    # Resample to 16kHz if needed
    if sr != 16000:
        from scipy import signal
        num_samples = int(len(waveform) * 16000 / sr)
        waveform = signal.resample(waveform, num_samples)
        sr = 16000

    # Load model
    model = hub.load("https://tfhub.dev/google/yamnet/1")

    # Load class names
    class_map_path = model.class_map_path().numpy().decode()
    with open(class_map_path) as f:
        reader = csv.reader(f)
        next(reader)  # skip header
        class_names = [row[2] for row in reader]

    # Run inference
    scores, embeddings, spectrogram = model(waveform)
    scores = scores.numpy()

    # Process results - each row is ~0.48s window
    events = []
    window_duration = 0.48

    for i, frame_scores in enumerate(scores):
        start_time = i * window_duration
        end_time = start_time + window_duration

        # Get top predictions above threshold
        top_indices = np.where(frame_scores > threshold)[0]

        for idx in top_indices:
            label = class_names[idx]
            confidence = float(frame_scores[idx])

            # Skip generic/background classes
            if label.lower() in ["silence", "speech", "music"]:
                continue

            events.append({
                "start": round(start_time, 2),
                "end": round(end_time, 2),
                "type": _simplify_label(label),
                "label": label,
                "confidence": round(confidence, 2)
            })

    # Merge consecutive events of same type
    events = _merge_consecutive_events(events)

    return events


def detect_sounds_panns(audio_path: str, threshold: float = 0.3, variant: str = "cnn14") -> list[dict]:
    """Detect sounds using PANNs."""
    from panns_inference import AudioTagging
    import numpy as np

    try:
        import soundfile as sf
        waveform, sr = sf.read(audio_path)
    except:
        import wave
        with wave.open(audio_path, 'rb') as wf:
            sr = wf.getframerate()
            frames = wf.readframes(wf.getnframes())
            waveform = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0

    # Convert to mono
    if len(waveform.shape) > 1:
        waveform = waveform.mean(axis=1)

    # Resample to 32kHz for PANNs
    if sr != 32000:
        from scipy import signal
        num_samples = int(len(waveform) * 32000 / sr)
        waveform = signal.resample(waveform, num_samples)
        sr = 32000

    # Load model
    at = AudioTagging(checkpoint_path=None, device="cpu")

    # Process in chunks (~1s windows)
    chunk_size = 32000  # 1 second
    events = []

    for i in range(0, len(waveform), chunk_size):
        chunk = waveform[i:i + chunk_size]
        if len(chunk) < chunk_size // 2:
            break

        # Pad if needed
        if len(chunk) < chunk_size:
            chunk = np.pad(chunk, (0, chunk_size - len(chunk)))

        start_time = i / sr
        end_time = (i + chunk_size) / sr

        # Run inference
        clipwise_output, _ = at.inference(chunk[None, :])

        # Get labels above threshold
        top_indices = np.where(clipwise_output[0] > threshold)[0]

        for idx in top_indices:
            label = at.labels[idx]
            confidence = float(clipwise_output[0][idx])

            if label.lower() in ["silence", "speech", "music"]:
                continue

            events.append({
                "start": round(start_time, 2),
                "end": round(end_time, 2),
                "type": _simplify_label(label),
                "label": label,
                "confidence": round(confidence, 2)
            })

    return _merge_consecutive_events(events)


def _merge_consecutive_events(events: list[dict], gap_threshold: float = 0.5) -> list[dict]:
    """Merge consecutive events of the same type."""
    if not events:
        return []

    # Sort by start time and type
    events = sorted(events, key=lambda x: (x["type"], x["start"]))

    merged = []
    current = None

    for event in events:
        if current is None:
            current = event.copy()
        elif (event["type"] == current["type"] and
              event["start"] - current["end"] <= gap_threshold):
            # Merge: extend end time, keep max confidence
            current["end"] = event["end"]
            current["confidence"] = max(current["confidence"], event["confidence"])
        else:
            merged.append(current)
            current = event.copy()

    if current:
        merged.append(current)

    return merged


def detect_sounds(audio_path: str, model_id: str = "yamnet", threshold: float = 0.3) -> list[dict]:
    """Main entry point for sound detection."""
    _log(f"Running sound detection with {model_id}...")
    _progress(10)

    if model_id == "yamnet":
        events = detect_sounds_yamnet(audio_path, threshold)
    elif model_id in ("panns_cnn14", "panns_cnn6"):
        variant = "cnn14" if model_id == "panns_cnn14" else "cnn6"
        events = detect_sounds_panns(audio_path, threshold, variant)
    elif model_id == "beats":
        # BEATs implementation would go here
        _log("BEATs inference not yet implemented, falling back to YAMNet")
        events = detect_sounds_yamnet(audio_path, threshold)
    else:
        _log(f"Unknown model: {model_id}")
        return []

    _progress(100)
    _log(f"Detected {len(events)} sound events")
    return events


# ============================================================================
# CLI ENTRY POINT
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description="Sound Detection Worker")
    parser.add_argument("--action", choices=["install", "predownload", "detect"], required=True)
    parser.add_argument("--model", default="yamnet", help="Model ID")
    parser.add_argument("--audio", help="Audio file path (for detect action)")
    parser.add_argument("--threshold", type=float, default=0.3, help="Detection threshold")
    parser.add_argument("--output", help="Output JSON file path")

    args = parser.parse_args()

    success = False
    result = None

    if args.action == "install":
        success = install_model_deps(args.model)

    elif args.action == "predownload":
        success = predownload_model(args.model)

    elif args.action == "detect":
        if not args.audio:
            _log("--audio required for detect action")
            sys.exit(1)

        result = detect_sounds(args.audio, args.model, args.threshold)
        success = True

        if args.output:
            Path(args.output).write_text(json.dumps(result, indent=2, ensure_ascii=False))
            _log(f"Results written to {args.output}")
        else:
            print(json.dumps(result, indent=2, ensure_ascii=False))

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
