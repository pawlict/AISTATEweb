from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from backend.updater.installer import ROOT, BACKUPS_DIR, _CODE_DIRS, _CODE_FILES
from backend.updater.installer import _install_backend_safe, record_history
from backend.updater.models import UpdateHistoryEntry

log = logging.getLogger("aistate.updater")


def list_backups() -> List[Dict]:
    """List available backups, newest first."""
    if not BACKUPS_DIR.exists():
        return []

    backups = []
    for d in sorted(BACKUPS_DIR.iterdir(), reverse=True):
        if not d.is_dir():
            continue
        name = d.name
        # Expected format: vX.Y.Z_YYYY-MM-DD_HHMMSS
        version = ""
        date = ""
        if name.startswith("v"):
            parts = name.split("_", 1)
            version = parts[0][1:]  # strip leading 'v'
            if len(parts) > 1:
                date = parts[1].replace("_", " ")

        # Verify backup has at least some code dirs
        has_code = any((d / cd).is_dir() for cd in _CODE_DIRS)
        if not has_code:
            continue

        backups.append({
            "version": version,
            "date": date,
            "path": str(d),
            "name": name,
        })

    return backups


def rollback_to(backup_path: Path) -> None:
    """Restore application code from a backup directory.

    Raises ValueError if backup is invalid.
    """
    if not backup_path.exists() or not backup_path.is_dir():
        raise ValueError("Katalog backupu nie istnieje")

    has_code = any((backup_path / cd).is_dir() for cd in _CODE_DIRS)
    if not has_code:
        raise ValueError("Backup nie zawiera katalogów z kodem")

    from backend.settings import APP_VERSION

    # Replace code dirs
    for d in _CODE_DIRS:
        src = backup_path / d
        dst = ROOT / d
        if src.is_dir():
            if d == "backend":
                _install_backend_safe(src, dst)
            else:
                if dst.exists():
                    shutil.rmtree(dst)
                shutil.copytree(src, dst)

    # Replace code files
    for f in _CODE_FILES:
        src = backup_path / f
        dst = ROOT / f
        if src.is_file():
            shutil.copy2(src, dst)

    # Extract version from backup dir name
    backup_version = ""
    name = backup_path.name
    if name.startswith("v"):
        parts = name.split("_", 1)
        backup_version = parts[0][1:]

    record_history(UpdateHistoryEntry(
        version=backup_version or "unknown",
        installed_at=datetime.now().isoformat(),
        previous_version=APP_VERSION,
        backup_path=str(backup_path),
        status="rollback",
        changelog=f"Rollback to v{backup_version}",
    ))

    log.info("Rollback completed to: %s", backup_path)
