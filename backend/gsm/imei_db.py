"""IMEI/TAC device identification database.

Maps the TAC (Type Allocation Code — first 8 digits of IMEI) to device
brand, model, and type.  The built-in database is loaded from
``tac_database.json`` alongside this module; users can extend it by
placing a ``tac_custom.json`` file in the same directory.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

log = logging.getLogger(__name__)

_DB_DIR = Path(__file__).resolve().parent
_BUILTIN_DB = _DB_DIR / "tac_database.json"
_CUSTOM_DB = _DB_DIR / "tac_custom.json"

# Singleton cache
_tac_cache: Optional[Dict[str, dict]] = None


@dataclass
class DeviceInfo:
    """Device identification result."""

    brand: str = ""
    model: str = ""
    device_type: str = ""  # smartphone, tablet, modem, feature_phone, smartwatch
    tac: str = ""

    @property
    def display_name(self) -> str:
        """Human-friendly name, e.g. 'Apple iPhone 14 Pro'."""
        parts = [p for p in (self.brand, self.model) if p]
        return " ".join(parts) if parts else ""

    def to_dict(self) -> dict:
        return {
            "brand": self.brand,
            "model": self.model,
            "type": self.device_type,
            "tac": self.tac,
            "display_name": self.display_name,
        }


def _load_db() -> Dict[str, dict]:
    """Load and merge TAC databases (cached)."""
    global _tac_cache
    if _tac_cache is not None:
        return _tac_cache

    db: Dict[str, dict] = {}

    # Built-in database
    if _BUILTIN_DB.exists():
        try:
            raw = json.loads(_BUILTIN_DB.read_text(encoding="utf-8"))
            for tac, info in raw.items():
                if tac.startswith("_"):
                    continue  # skip metadata keys
                db[tac] = info
            log.debug("Loaded %d TAC entries from built-in database", len(db))
        except Exception as e:
            log.warning("Failed to load TAC database: %s", e)

    # Custom overrides / additions
    if _CUSTOM_DB.exists():
        try:
            custom = json.loads(_CUSTOM_DB.read_text(encoding="utf-8"))
            count = 0
            for tac, info in custom.items():
                if tac.startswith("_"):
                    continue
                db[tac] = info
                count += 1
            log.debug("Loaded %d TAC entries from custom database", count)
        except Exception as e:
            log.warning("Failed to load custom TAC database: %s", e)

    _tac_cache = db
    return db


def extract_tac(imei: str) -> str:
    """Extract the 8-digit TAC from an IMEI string.

    Handles IMEI (15 digits), IMEISV (16 digits), and IMEI with
    separators (dashes, spaces).
    """
    if not imei:
        return ""
    digits = re.sub(r"[^0-9]", "", str(imei).strip())
    if len(digits) >= 8:
        return digits[:8]
    return ""


def lookup_imei(imei: str) -> Optional[DeviceInfo]:
    """Look up device info by IMEI number.

    Args:
        imei: IMEI string (15 or 16 digits, may contain separators).

    Returns:
        DeviceInfo if TAC is found in database, None otherwise.
    """
    tac = extract_tac(imei)
    if not tac:
        return None

    db = _load_db()
    entry = db.get(tac)
    if not entry:
        return None

    return DeviceInfo(
        brand=entry.get("brand", ""),
        model=entry.get("model", ""),
        device_type=entry.get("type", ""),
        tac=tac,
    )


def lookup_imeis(imeis: List[str]) -> Dict[str, DeviceInfo]:
    """Batch lookup — returns {imei: DeviceInfo} for found entries only."""
    results: Dict[str, DeviceInfo] = {}
    db = _load_db()

    for imei in imeis:
        tac = extract_tac(imei)
        if not tac:
            continue
        entry = db.get(tac)
        if entry:
            results[imei] = DeviceInfo(
                brand=entry.get("brand", ""),
                model=entry.get("model", ""),
                device_type=entry.get("type", ""),
                tac=tac,
            )
    return results


def get_db_stats() -> dict:
    """Return database statistics."""
    db = _load_db()
    brands = set()
    types = set()
    for entry in db.values():
        if entry.get("brand"):
            brands.add(entry["brand"])
        if entry.get("type"):
            types.add(entry["type"])
    return {
        "total_entries": len(db),
        "brands": sorted(brands),
        "types": sorted(types),
        "custom_db_exists": _CUSTOM_DB.exists(),
    }


def reload_db() -> int:
    """Force-reload the TAC database. Returns entry count."""
    global _tac_cache
    _tac_cache = None
    return len(_load_db())
