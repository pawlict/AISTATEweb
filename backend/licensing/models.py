"""License data models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Dict, List, Optional


ALL_FEATURES: List[str] = [
    "transcription",
    "diarization",
    "translation",
    "analysis",
    "chat",
    "tts",
    "tts_kokoro",
    "sound_detection",
    "batch_processing",
    "advanced_reports",
    "update_panel",
]

PRO_ONLY_FEATURES: List[Dict[str, str]] = [
    {
        "key": "video_processing",
        "name_pl": "Przetwarzanie wideo",
        "name_en": "Video processing",
        "desc_pl": "Transkrypcja i diaryzacja z plik\u00f3w wideo (14 format\u00f3w)",
        "desc_en": "Transcription and diarization from video files (14 formats)",
    },
    {
        "key": "audio_enhancement",
        "name_pl": "Poprawa jako\u015bci d\u017awi\u0119ku",
        "name_en": "Audio enhancement",
        "desc_pl": "Normalizacja g\u0142o\u015bno\u015bci, inteligentna redukcja szumu",
        "desc_en": "Loudness normalization, smart noise reduction",
    },
    {
        "key": "source_separation",
        "name_pl": "Separacja \u017ar\u00f3de\u0142 d\u017awi\u0119ku",
        "name_en": "Source separation",
        "desc_pl": "Izolacja g\u0142os\u00f3w od muzyki i szum\u00f3w t\u0142a (Demucs)",
        "desc_en": "Isolate vocals from music and background noise (Demucs)",
    },
    {
        "key": "emotion_detection",
        "name_pl": "Detekcja emocji m\u00f3wcy",
        "name_en": "Speaker emotion detection",
        "desc_pl": "Rozpoznawanie emocji w g\u0142osie: z\u0142o\u015b\u0107, strach, rado\u015b\u0107, smutek",
        "desc_en": "Emotion recognition: anger, fear, happiness, sadness",
    },
    {
        "key": "scene_classification",
        "name_pl": "Klasyfikacja sceny akustycznej",
        "name_en": "Acoustic scene classification",
        "desc_pl": "Rozpoznawanie kontekstu nagrania (biuro, ulica, pojazd, telefon)",
        "desc_en": "Detect recording context (office, street, vehicle, phone)",
    },
]

PLAN_FEATURES = {
    "community": ALL_FEATURES.copy(),
    "pro": ALL_FEATURES.copy(),
    "enterprise": ALL_FEATURES.copy(),
}


@dataclass
class LicenseInfo:
    license_id: str = ""
    name: str = ""
    email: str = ""
    plan: str = "community"
    issued: Optional[date] = None
    expires: Optional[date] = None
    updates_until: Optional[date] = None
    features: List[str] = field(default_factory=lambda: ALL_FEATURES.copy())
    raw_key: str = ""

    @property
    def is_perpetual(self) -> bool:
        return self.expires is None

    @property
    def is_expired(self) -> bool:
        if self.expires is None:
            return False
        return date.today() > self.expires

    @property
    def updates_expired(self) -> bool:
        if self.updates_until is None:
            return False
        return date.today() > self.updates_until

    @property
    def days_remaining(self) -> Optional[int]:
        if self.expires is None:
            return None
        delta = self.expires - date.today()
        return max(0, delta.days)

    @property
    def updates_days_remaining(self) -> Optional[int]:
        if self.updates_until is None:
            return None
        delta = self.updates_until - date.today()
        return max(0, delta.days)

    def has_feature(self, feature: str) -> bool:
        return feature in self.features or "all" in self.features

    def to_dict(self) -> dict:
        return {
            "license_id": self.license_id,
            "name": self.name,
            "email": self.email,
            "plan": self.plan,
            "issued": self.issued.isoformat() if self.issued else None,
            "expires": self.expires.isoformat() if self.expires else None,
            "updates_until": self.updates_until.isoformat() if self.updates_until else None,
            "features": self.features,
            "is_perpetual": self.is_perpetual,
            "is_expired": self.is_expired,
            "updates_expired": self.updates_expired,
            "days_remaining": self.days_remaining,
            "updates_days_remaining": self.updates_days_remaining,
        }


def default_community_license() -> LicenseInfo:
    return LicenseInfo(
        license_id="COMMUNITY",
        email="",
        plan="community",
        issued=date.today(),
        expires=None,
        updates_until=None,
        features=ALL_FEATURES.copy(),
    )
