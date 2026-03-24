"""License data models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import List, Optional


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

# Community features — current modules, always free
COMMUNITY_FEATURES: List[str] = [
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

# Plans and their default feature sets
PLAN_FEATURES = {
    "community": COMMUNITY_FEATURES.copy(),
    "pro": ["all"],       # all current + future features
    "enterprise": ["all"],  # all current + future + priority support
}


@dataclass
class LicenseInfo:
    """Parsed and validated license information."""

    license_id: str = ""
    name: str = ""
    email: str = ""
    plan: str = "community"
    issued: Optional[date] = None
    expires: Optional[date] = None          # None = perpetual
    updates_until: Optional[date] = None    # None = perpetual
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
    """Return a default 'community' license with current modules unlocked."""
    return LicenseInfo(
        license_id="COMMUNITY",
        email="",
        plan="community",
        issued=date.today(),
        expires=None,         # perpetual
        updates_until=None,   # perpetual
        features=COMMUNITY_FEATURES.copy(),
    )
