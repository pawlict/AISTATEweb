"""
License key validation.

Key format:  AIST-<base64_json>.<base64_signature>

The JSON payload contains license metadata (plan, features, dates).
The signature is an Ed25519 signature over the raw base64 JSON part.

When LICENSING_ENABLED is False, validation is skipped and a default
community license is returned.
"""

from __future__ import annotations

import base64
import json
import logging
from datetime import date
from pathlib import Path
from typing import Optional

from backend.licensing import LICENSING_ENABLED
from backend.licensing.models import LicenseInfo, ALL_FEATURES, default_community_license

log = logging.getLogger("aistate.licensing")

# Prefix for license keys
KEY_PREFIX = "AIST-"

# Cached license (loaded once at startup, refreshed on activation)
_cached_license: Optional[LicenseInfo] = None


def _get_license_path() -> Path:
    """Return path to stored license file."""
    import os
    config_dir = Path(os.environ.get("AISTATE_CONFIG_DIR", "backend/.aistate"))
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir / "license.key"


def _verify_signature(data_b64: str, signature_b64: str) -> bool:
    """Verify Ed25519 signature.  Returns True if valid."""
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        from backend.licensing.public_key import PUBLIC_KEY_B64

        if "PLACEHOLDER" in PUBLIC_KEY_B64:
            # No real key configured — accept any signature in dev mode
            log.warning("License public key is placeholder — signature check skipped")
            return True

        pub_bytes = base64.b64decode(PUBLIC_KEY_B64)
        public_key = Ed25519PublicKey.from_public_bytes(pub_bytes)
        sig_bytes = base64.b64decode(signature_b64)
        data_bytes = data_b64.encode("utf-8")
        public_key.verify(sig_bytes, data_bytes)
        return True
    except ImportError:
        # cryptography not installed — skip signature check
        log.warning("cryptography library not installed — signature check skipped")
        return True
    except Exception as exc:
        log.error("License signature verification failed: %s", exc)
        return False


def _check_clock_manipulation() -> bool:
    """Check if system clock has been set backwards.  Returns True if OK."""
    try:
        from backend.db.engine import get_system_config, set_system_config
        last_seen = get_system_config("license_last_seen_date", "")
        today_str = date.today().isoformat()

        if last_seen and today_str < last_seen:
            log.warning("Clock manipulation detected: today=%s, last_seen=%s", today_str, last_seen)
            return False

        set_system_config("license_last_seen_date", today_str)
        return True
    except Exception:
        return True  # be lenient on DB errors


def parse_license_key(key_string: str) -> LicenseInfo:
    """Parse and validate a license key string.

    Raises ValueError if the key is invalid.
    """
    key_string = key_string.strip()

    if key_string.startswith(KEY_PREFIX):
        key_string = key_string[len(KEY_PREFIX):]

    parts = key_string.split(".")
    if len(parts) != 2:
        raise ValueError("Nieprawid\u0142owy format klucza licencyjnego")

    data_b64, signature_b64 = parts

    # Verify signature
    if not _verify_signature(data_b64, signature_b64):
        raise ValueError("Podpis klucza licencyjnego jest nieprawid\u0142owy")

    # Decode payload
    try:
        payload = json.loads(base64.b64decode(data_b64))
    except Exception:
        raise ValueError("Nie mo\u017cna odczyta\u0107 danych klucza licencyjnego")

    # Parse dates
    def _parse_date(val: Optional[str]) -> Optional[date]:
        if not val or val == "perpetual":
            return None
        return date.fromisoformat(val)

    info = LicenseInfo(
        license_id=payload.get("lid", ""),
        email=payload.get("email", ""),
        plan=payload.get("plan", "community"),
        issued=_parse_date(payload.get("issued")),
        expires=_parse_date(payload.get("expires")),
        updates_until=_parse_date(payload.get("updates_until")),
        features=payload.get("features", ALL_FEATURES.copy()),
        raw_key=KEY_PREFIX + data_b64 + "." + signature_b64,
    )

    return info


def activate_license(key_string: str) -> LicenseInfo:
    """Validate and store a license key.

    Returns LicenseInfo on success.
    Raises ValueError on invalid key.
    """
    global _cached_license

    info = parse_license_key(key_string)

    # Check expiration
    if info.is_expired:
        raise ValueError(
            f"Klucz licencyjny wygas\u0142 ({info.expires.isoformat()}). "
            "Skontaktuj si\u0119 z dostawc\u0105 w celu odnowienia."
        )

    # Clock manipulation check
    if not _check_clock_manipulation():
        raise ValueError(
            "Wykryto anomali\u0119 zegara systemowego. "
            "Sprawd\u017a dat\u0119 i godzin\u0119 systemu."
        )

    # Store the key
    path = _get_license_path()
    path.write_text(info.raw_key, encoding="utf-8")
    log.info("License activated: id=%s plan=%s", info.license_id, info.plan)

    _cached_license = info
    return info


def load_license() -> LicenseInfo:
    """Load stored license from disk.  Returns community license if none found."""
    global _cached_license

    if not LICENSING_ENABLED:
        _cached_license = default_community_license()
        return _cached_license

    path = _get_license_path()
    if not path.exists():
        _cached_license = default_community_license()
        return _cached_license

    try:
        key_string = path.read_text(encoding="utf-8").strip()
        if not key_string:
            _cached_license = default_community_license()
            return _cached_license

        info = parse_license_key(key_string)

        # Clock check
        if not _check_clock_manipulation():
            log.warning("Clock anomaly — license marked as suspect")

        _cached_license = info
        return info
    except (ValueError, Exception) as exc:
        log.warning("Failed to load license: %s", exc)
        _cached_license = default_community_license()
        return _cached_license


def get_cached_license() -> LicenseInfo:
    """Return the cached license (or load it if not yet loaded)."""
    if _cached_license is None:
        return load_license()
    return _cached_license


def remove_license() -> None:
    """Remove stored license key and revert to community."""
    global _cached_license
    path = _get_license_path()
    if path.exists():
        path.unlink()
    _cached_license = default_community_license()
    log.info("License removed — reverted to community")
