"""Database backup & restore module for AISTATEweb.

Uses SQLite Online Backup API for safe, consistent backups even while
the application is running with WAL mode.  Also handles file-level
backup of uploads, configs, and logs.

Designed for:
  - Proxmox multi-user deployments (scheduled via cron or systemd timer)
  - WSL2 / bare-metal installs
  - Manual one-shot backups via API or CLI
"""

from __future__ import annotations

import gzip
import hashlib
import json
import logging
import os
import shutil
import sqlite3
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from .engine import get_db_path

log = logging.getLogger("aistate.backup")

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

_DEFAULT_BACKUP_DIR = "backups"  # relative to project root
_MAX_BACKUPS = 30                # keep last N backups (rotation)
_GZIP_LEVEL = 6                 # gzip compression level (1-9)


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _backup_dir() -> Path:
    env = os.environ.get("AISTATEWEB_BACKUP_DIR", "").strip()
    if env:
        d = Path(env).expanduser().resolve()
    else:
        d = _project_root() / _DEFAULT_BACKUP_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def _data_dir() -> Path:
    env = os.environ.get("AISTATEWEB_DATA_DIR", "").strip()
    if env:
        return Path(env).expanduser().resolve()
    return _project_root() / "data_www"


def _config_dir() -> Path:
    env = os.environ.get("AISTATE_CONFIG_DIR", "").strip()
    if env:
        return Path(env).expanduser().resolve()
    return _project_root() / "backend" / ".aistate"


# ---------------------------------------------------------------------------
# SQLite backup (online, WAL-safe)
# ---------------------------------------------------------------------------

def backup_database(dest_path: Optional[Path] = None, compress: bool = True) -> Path:
    """Create a consistent backup of the SQLite database.

    Uses sqlite3.Connection.backup() which safely copies even while
    writers are active (WAL mode).  Optionally gzip-compresses the result.

    Returns the path to the backup file.
    """
    src_path = get_db_path()
    if not src_path.exists():
        raise FileNotFoundError(f"Database not found: {src_path}")

    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    suffix = ".db.gz" if compress else ".db"
    if dest_path is None:
        dest_path = _backup_dir() / f"aistate_{ts}{suffix}"

    dest_path.parent.mkdir(parents=True, exist_ok=True)

    # Step 1: backup to a temp .db file
    tmp_db = dest_path.with_suffix(".tmp.db")
    try:
        src_conn = sqlite3.connect(str(src_path), timeout=30)
        dst_conn = sqlite3.connect(str(tmp_db))
        with dst_conn:
            src_conn.backup(dst_conn, pages=256, sleep=0.01)
        dst_conn.close()
        src_conn.close()

        # Step 2: verify the backup (integrity check)
        verify_conn = sqlite3.connect(str(tmp_db))
        result = verify_conn.execute("PRAGMA integrity_check").fetchone()
        verify_conn.close()
        if result[0] != "ok":
            raise RuntimeError(f"Backup integrity check failed: {result[0]}")

        # Step 3: compress if requested
        if compress:
            with open(tmp_db, "rb") as f_in:
                with gzip.open(str(dest_path), "wb", compresslevel=_GZIP_LEVEL) as f_out:
                    shutil.copyfileobj(f_in, f_out)
            tmp_db.unlink()
        else:
            tmp_db.rename(dest_path)

        size_mb = dest_path.stat().st_size / (1024 * 1024)
        log.info("Database backup created: %s (%.2f MB)", dest_path.name, size_mb)
        return dest_path

    except Exception:
        # Cleanup temp file on failure
        if tmp_db.exists():
            tmp_db.unlink(missing_ok=True)
        raise


def restore_database(backup_path: Path, target_path: Optional[Path] = None) -> Path:
    """Restore database from a backup file.

    Handles both plain .db and .gz compressed backups.
    Creates a safety copy of the current database before overwriting.
    """
    if not backup_path.exists():
        raise FileNotFoundError(f"Backup file not found: {backup_path}")

    target = target_path or get_db_path()

    # Safety: copy current DB before overwriting
    if target.exists():
        safety = target.with_suffix(f".pre_restore_{int(time.time())}.db")
        shutil.copy2(str(target), str(safety))
        log.info("Safety copy of current DB: %s", safety.name)

    # Decompress if needed
    if str(backup_path).endswith(".gz"):
        tmp_db = target.with_suffix(".restore_tmp.db")
        with gzip.open(str(backup_path), "rb") as f_in:
            with open(tmp_db, "wb") as f_out:
                shutil.copyfileobj(f_in, f_out)
    else:
        tmp_db = backup_path

    # Verify integrity before replacing
    verify_conn = sqlite3.connect(str(tmp_db))
    result = verify_conn.execute("PRAGMA integrity_check").fetchone()
    verify_conn.close()
    if result[0] != "ok":
        if tmp_db != backup_path:
            tmp_db.unlink(missing_ok=True)
        raise RuntimeError(f"Backup integrity check failed: {result[0]}")

    # Replace current database
    # Close any WAL/SHM files
    for ext in ["-wal", "-shm"]:
        wal_file = Path(str(target) + ext)
        if wal_file.exists():
            wal_file.unlink()

    if tmp_db != backup_path:
        shutil.move(str(tmp_db), str(target))
    else:
        shutil.copy2(str(backup_path), str(target))

    log.info("Database restored from: %s", backup_path.name)
    return target


# ---------------------------------------------------------------------------
# Full backup (DB + files + config)
# ---------------------------------------------------------------------------

def full_backup(compress: bool = True) -> Dict[str, Any]:
    """Create a full backup: database + uploads + config + rules.

    Returns a manifest dict with paths and checksums.
    """
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    backup_root = _backup_dir() / f"full_{ts}"
    backup_root.mkdir(parents=True, exist_ok=True)

    manifest: Dict[str, Any] = {
        "timestamp": ts,
        "created_at": datetime.utcnow().isoformat() + "Z",
        "components": {},
    }

    # 1. Database
    try:
        db_path = backup_database(
            dest_path=backup_root / ("aistate.db.gz" if compress else "aistate.db"),
            compress=compress,
        )
        manifest["components"]["database"] = {
            "path": db_path.name,
            "size": db_path.stat().st_size,
            "checksum": _sha256(db_path),
        }
    except Exception as e:
        manifest["components"]["database"] = {"error": str(e)}
        log.error("Database backup failed: %s", e)

    # 2. Uploads (PDFs, project files)
    data_dir = _data_dir()
    uploads_src = data_dir / "uploads"
    projects_src = data_dir / "projects"

    for label, src_dir in [("uploads", uploads_src), ("projects", projects_src)]:
        if src_dir.exists() and any(src_dir.rglob("*")):
            dest = backup_root / label
            try:
                shutil.copytree(str(src_dir), str(dest))
                file_count = sum(1 for _ in dest.rglob("*") if _.is_file())
                total_size = sum(f.stat().st_size for f in dest.rglob("*") if f.is_file())
                manifest["components"][label] = {
                    "path": label,
                    "files": file_count,
                    "total_size": total_size,
                }
            except Exception as e:
                manifest["components"][label] = {"error": str(e)}
                log.error("%s backup failed: %s", label, e)

    # 3. Config files
    config_dir = _config_dir()
    if config_dir.exists():
        dest = backup_root / "config"
        try:
            shutil.copytree(str(config_dir), str(dest))
            manifest["components"]["config"] = {"path": "config"}
        except Exception as e:
            manifest["components"]["config"] = {"error": str(e)}

    # 4. AML rules
    rules_file = _project_root() / "backend" / "aml" / "config" / "rules.yaml"
    if rules_file.exists():
        dest = backup_root / "rules.yaml"
        shutil.copy2(str(rules_file), str(dest))
        manifest["components"]["rules"] = {
            "path": "rules.yaml",
            "checksum": _sha256(dest),
        }

    # 5. Logs (last 7 days)
    logs_dir = _project_root() / "backend" / "logs"
    if logs_dir.exists():
        cutoff = datetime.utcnow() - timedelta(days=7)
        dest_logs = backup_root / "logs"
        dest_logs.mkdir(exist_ok=True)
        log_count = 0
        for log_file in logs_dir.rglob("*.log"):
            try:
                mtime = datetime.utcfromtimestamp(log_file.stat().st_mtime)
                if mtime >= cutoff:
                    rel = log_file.relative_to(logs_dir)
                    (dest_logs / rel.parent).mkdir(parents=True, exist_ok=True)
                    shutil.copy2(str(log_file), str(dest_logs / rel))
                    log_count += 1
            except Exception:
                pass
        manifest["components"]["logs"] = {"path": "logs", "files": log_count}

    # Write manifest
    manifest_path = backup_root / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # Compute total size
    total = sum(f.stat().st_size for f in backup_root.rglob("*") if f.is_file())
    manifest["total_size_mb"] = round(total / (1024 * 1024), 2)
    manifest["backup_dir"] = str(backup_root)

    log.info("Full backup created: %s (%.2f MB)", backup_root.name, manifest["total_size_mb"])
    return manifest


def full_restore(backup_dir: Path) -> Dict[str, Any]:
    """Restore from a full backup directory.

    Reads manifest.json, restores DB, uploads, config, rules.
    """
    manifest_path = backup_dir / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"No manifest.json in {backup_dir}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    result: Dict[str, Any] = {"restored": [], "errors": []}

    # 1. Database
    db_comp = manifest.get("components", {}).get("database", {})
    if "path" in db_comp:
        db_backup = backup_dir / db_comp["path"]
        try:
            restore_database(db_backup)
            result["restored"].append("database")
        except Exception as e:
            result["errors"].append(f"database: {e}")

    # 2. Uploads & projects
    data_dir = _data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    for label in ("uploads", "projects"):
        src = backup_dir / label
        if src.exists():
            dest = data_dir / label
            try:
                if dest.exists():
                    # Merge — don't delete existing files
                    shutil.copytree(str(src), str(dest), dirs_exist_ok=True)
                else:
                    shutil.copytree(str(src), str(dest))
                result["restored"].append(label)
            except Exception as e:
                result["errors"].append(f"{label}: {e}")

    # 3. Config
    cfg_src = backup_dir / "config"
    if cfg_src.exists():
        cfg_dest = _config_dir()
        try:
            cfg_dest.mkdir(parents=True, exist_ok=True)
            shutil.copytree(str(cfg_src), str(cfg_dest), dirs_exist_ok=True)
            result["restored"].append("config")
        except Exception as e:
            result["errors"].append(f"config: {e}")

    # 4. Rules
    rules_src = backup_dir / "rules.yaml"
    if rules_src.exists():
        rules_dest = _project_root() / "backend" / "aml" / "config" / "rules.yaml"
        try:
            shutil.copy2(str(rules_src), str(rules_dest))
            result["restored"].append("rules")
        except Exception as e:
            result["errors"].append(f"rules: {e}")

    log.info("Full restore completed: %s restored, %s errors",
             len(result["restored"]), len(result["errors"]))
    return result


# ---------------------------------------------------------------------------
# Rotation — keep only last N backups
# ---------------------------------------------------------------------------

def rotate_backups(max_backups: int = _MAX_BACKUPS) -> int:
    """Delete old backups, keeping the most recent *max_backups*.

    Handles both single-file DB backups and full backup directories.
    Returns the number of deleted items.
    """
    backup_dir = _backup_dir()
    if not backup_dir.exists():
        return 0

    # Collect all backup items (files + dirs) with timestamps
    items = []
    for entry in backup_dir.iterdir():
        if entry.name.startswith("."):
            continue
        items.append((entry.stat().st_mtime, entry))

    items.sort(key=lambda x: x[0], reverse=True)  # newest first

    deleted = 0
    for _, item in items[max_backups:]:
        try:
            if item.is_dir():
                shutil.rmtree(str(item))
            else:
                item.unlink()
            deleted += 1
        except Exception as e:
            log.warning("Failed to delete old backup %s: %s", item.name, e)

    if deleted:
        log.info("Rotated %d old backup(s), keeping %d", deleted, max_backups)
    return deleted


# ---------------------------------------------------------------------------
# List available backups
# ---------------------------------------------------------------------------

def list_backups() -> List[Dict[str, Any]]:
    """List all available backups with metadata."""
    backup_dir = _backup_dir()
    if not backup_dir.exists():
        return []

    backups = []
    for entry in sorted(backup_dir.iterdir(), key=lambda e: e.stat().st_mtime, reverse=True):
        if entry.name.startswith("."):
            continue

        info: Dict[str, Any] = {
            "name": entry.name,
            "path": str(entry),
            "created": datetime.utcfromtimestamp(entry.stat().st_mtime).isoformat() + "Z",
        }

        if entry.is_dir():
            # Full backup with manifest
            manifest_path = entry / "manifest.json"
            if manifest_path.exists():
                try:
                    m = json.loads(manifest_path.read_text(encoding="utf-8"))
                    info["type"] = "full"
                    info["components"] = list(m.get("components", {}).keys())
                    total = sum(f.stat().st_size for f in entry.rglob("*") if f.is_file())
                    info["size_mb"] = round(total / (1024 * 1024), 2)
                except Exception:
                    info["type"] = "full (corrupt manifest)"
        else:
            # Single DB backup
            info["type"] = "database"
            info["size_mb"] = round(entry.stat().st_size / (1024 * 1024), 2)

        backups.append(info)

    return backups


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    import sys

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    parser = argparse.ArgumentParser(description="AISTATEweb Backup Tool")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("db", help="Backup database only")
    sub.add_parser("full", help="Full backup (DB + files + config)")
    sub.add_parser("list", help="List available backups")

    p_restore = sub.add_parser("restore", help="Restore from backup")
    p_restore.add_argument("path", help="Path to backup file or directory")

    p_rotate = sub.add_parser("rotate", help="Delete old backups")
    p_rotate.add_argument("--keep", type=int, default=_MAX_BACKUPS, help="Number of backups to keep")

    args = parser.parse_args()

    if args.command == "db":
        path = backup_database()
        print(f"Database backup: {path}")
    elif args.command == "full":
        m = full_backup()
        print(json.dumps(m, indent=2))
    elif args.command == "list":
        for b in list_backups():
            print(f"  {b['type']:10s}  {b['name']:40s}  {b.get('size_mb', '?')} MB  {b['created']}")
    elif args.command == "restore":
        p = Path(args.path)
        if p.is_dir():
            r = full_restore(p)
        else:
            restore_database(p)
            r = {"restored": ["database"], "errors": []}
        print(json.dumps(r, indent=2))
    elif args.command == "rotate":
        n = rotate_backups(args.keep)
        print(f"Deleted {n} old backup(s)")
    else:
        parser.print_help()
        sys.exit(1)
