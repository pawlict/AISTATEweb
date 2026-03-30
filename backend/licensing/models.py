"""License data models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Dict, List, Optional


# All known features that can be gated
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

# Features available ONLY in the Pro version.
# This list is served to the Community UI so users can see what Pro offers.
PRO_ONLY_FEATURES: List[Dict[str, str]] = [
    {
        "key": "video_processing",
        "name_pl": "Przetwarzanie wideo",
        "name_en": "Video processing",
        "desc_pl": "Transkrypcja i diaryzacja z plik\u00f3w wideo (14 format\u00f3w: MP4, AVI, MKV, MOV, WEBM, WMV, FLV, M4V, MPG, MPEG, 3GP, TS, MTS, VOB)",
        "desc_en": "Transcription and diarization from video files (14 formats)",
    },
    {
        "key": "audio_enhancement",
        "name_pl": "Poprawa jako\u015bci d\u017awi\u0119ku",
        "name_en": "Audio enhancement",
        "desc_pl": "Automatyczna normalizacja g\u0142o\u015bno\u015bci, redukcja szumu, analiza jako\u015bci audio (SNR, dBFS, clipping)",
        "desc_en": "Auto loudness normalization, noise reduction, audio quality analysis (SNR, dBFS, clipping)",
    },
]

# Plans and their default feature sets
PLAN_FEATURES = {
    "community": ALL_FEATURES.copy(),
    "pro": ALL_FEATURES.copy(),
    "enterprise": ALL_FEATURES.copy(),
}


@dataclass
class LicenseInfo:
    """Parsed and validated license information."""

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
    """Return a default 'community' license with everything unlocked."""
    return LicenseInfo(
        license_id="COMMUNITY",
        email="",
        plan="community",
        issued=date.today(),
        expires=None,
        updates_until=None,
        features=ALL_FEATURES.copy(),
    )
