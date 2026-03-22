from __future__ import annotations

import json
import logging
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from backend.updater.models import UpdateInfo, UpdateHistoryEntry

log = logging.getLogger("aistate.updater")

ROOT = Path(__file__).resolve().parents[2]

# Directories/files that constitute "the application code"
_CODE_DIRS = ["webapp", "backend", "generators"]
_CODE_FILES = ["AISTATEweb.py", "requirements.txt"]

# Directories that must NEVER be touched during update
_PROTECTED = {
    "data_www", "_backups", "_updates", ".git",
    "backend/.aistate", "tests", "venv", ".venv",
}

BACKUPS_DIR = ROOT / "_backups"


def create_backup(version: str) -> Path:
    """Create a backup of current code directories.

    Returns the backup directory path.
    """
    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    backup_dir = BACKUPS_DIR / f"v{version}_{ts}"
    backup_dir.mkdir(parents=True, exist_ok=True)

    for d in _CODE_DIRS:
        src = ROOT / d
        if src.is_dir():
            # For backend, skip .aistate subdirectory
            if d == "backend":
                _copy_backend_safe(src, backup_dir / d)
            else:
                shutil.copytree(src, backup_dir / d, dirs_exist_ok=True)

    for f in _CODE_FILES:
        src = ROOT / f
        if src.is_file():
            shutil.copy2(src, backup_dir / f)

    log.info("Backup created: %s", backup_dir)
    return backup_dir


def _copy_backend_safe(src: Path, dst: Path) -> None:
    """Copy backend directory, skipping .aistate and other protected subdirs."""
    def _ignore(directory: str, contents: list) -> list:
        ignored = []
        for item in contents:
            rel = Path(directory) / item
            try:
                rel_to_root = rel.relative_to(ROOT)
                if str(rel_to_root) in _PROTECTED or any(
                    str(rel_to_root).startswith(p) for p in _PROTECTED
                ):
                    ignored.append(item)
            except ValueError:
                pass
            if item in (".aistate", "__pycache__", ".pyc"):
                ignored.append(item)
        return ignored

    shutil.copytree(src, dst, ignore=_ignore, dirs_exist_ok=True)


def install_update(staging_dir: Path, info: UpdateInfo) -> None:
    """Replace application code from staging directory."""
    for d in _CODE_DIRS:
        src = staging_dir / d
        dst = ROOT / d
        if src.is_dir():
            if d == "backend":
                _install_backend_safe(src, dst)
            else:
                if dst.exists():
                    shutil.rmtree(dst)
                shutil.copytree(src, dst)

    for f in _CODE_FILES:
        src = staging_dir / f
        dst = ROOT / f
        if src.is_file():
            shutil.copy2(src, dst)

    log.info("Update installed: v%s", info.version)


def _install_backend_safe(src: Path, dst: Path) -> None:
    """Install backend update, preserving .aistate and other protected data."""
    # Save protected subdirectories
    protected_saves = {}
    for pdir in (".aistate", "logs"):
        p = dst / pdir
        if p.exists():
            temp = dst.parent / f"_protected_{pdir}"
            if temp.exists():
                shutil.rmtree(temp)
            shutil.copytree(p, temp)
            protected_saves[pdir] = temp

    # Remove old backend (except db which may have active connections)
    if dst.exists():
        shutil.rmtree(dst)

    # Copy new backend
    shutil.copytree(src, dst)

    # Restore protected subdirectories
    for pdir, temp in protected_saves.items():
        target = dst / pdir
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(temp, target)
        shutil.rmtree(temp)


def install_vendored_deps(staging_dir: Path) -> Optional[str]:
    """Install vendored .whl dependencies from the update package.

    Returns None on success or error message on failure.
    """
    wheels_dir = staging_dir / "wheels"
    if not wheels_dir.is_dir():
        return None  # No vendored dependencies — OK

    whl_files = list(wheels_dir.glob("*.whl"))
    if not whl_files:
        return None

    try:
        result = subprocess.run(
            [
                sys.executable, "-m", "pip", "install",
                "--no-index",
                f"--find-links={wheels_dir}",
            ] + [str(w) for w in whl_files],
            capture_output=True,
            text=True,
            timeout=300,
        )
        if result.returncode != 0:
            return f"pip install failed: {result.stderr[:500]}"
    except subprocess.TimeoutExpired:
        return "pip install timed out after 5 minutes"
    except Exception as e:
        return f"pip install error: {e}"

    return None


def run_migrations(staging_dir: Path, info: UpdateInfo) -> Optional[str]:
    """Execute migration scripts from the update package.

    Returns None on success or error message on failure.
    """
    if not info.migrations:
        return None

    migrations_dir = staging_dir / "migrations"
    if not migrations_dir.is_dir():
        return None

    for migration_name in info.migrations:
        script = migrations_dir / f"{migration_name}.py"
        if not script.exists():
            log.warning("Migration script not found: %s", script)
            continue

        try:
            result = subprocess.run(
                [sys.executable, str(script)],
                capture_output=True,
                text=True,
                timeout=120,
                cwd=str(ROOT),
            )
            if result.returncode != 0:
                return f"Migration '{migration_name}' failed: {result.stderr[:500]}"
            log.info("Migration '%s' completed", migration_name)
        except subprocess.TimeoutExpired:
            return f"Migration '{migration_name}' timed out"
        except Exception as e:
            return f"Migration '{migration_name}' error: {e}"

    return None


def record_history(entry: UpdateHistoryEntry) -> None:
    """Save an update history entry to system_config."""
    from backend.db.engine import get_system_config, set_system_config

    raw = get_system_config("update_history", "[]")
    try:
        history = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        history = []

    history.insert(0, {
        "version": entry.version,
        "installed_at": entry.installed_at,
        "previous_version": entry.previous_version,
        "backup_path": entry.backup_path,
        "status": entry.status,
        "changelog": entry.changelog,
    })

    # Keep last 20 entries
    history = history[:20]

    set_system_config("update_history", json.dumps(history, ensure_ascii=False))
    set_system_config("last_update_version", entry.version)
    set_system_config("last_update_at", entry.installed_at)


def get_history() -> list:
    """Read update history from system_config."""
    from backend.db.engine import get_system_config

    raw = get_system_config("update_history", "[]")
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []
