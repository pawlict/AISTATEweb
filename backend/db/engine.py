"""SQLite database engine for AISTATEweb.

Single-file database with WAL mode for concurrent reads.
Thread-safe connection pool for FastAPI async context.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional

log = logging.getLogger("aistate.db")

_SCHEMA_FILE = Path(__file__).parent / "schema.sql"
_DB_VERSION = "1.0.0"

# Global connection reference (singleton per process)
_db_path: Optional[Path] = None
_initialized: bool = False


def _get_db_path() -> Path:
    """Resolve database file path from environment or default."""
    data_dir = os.environ.get("AISTATEWEB_DATA_DIR", "")
    if data_dir:
        return Path(data_dir) / "aistate.db"
    return Path(__file__).resolve().parents[2] / "data_www" / "aistate.db"


def get_db_path() -> Path:
    """Public accessor for the resolved DB path."""
    global _db_path
    if _db_path is None:
        _db_path = _get_db_path()
    return _db_path


def set_db_path(path: Path) -> None:
    """Override DB path (for testing)."""
    global _db_path, _initialized
    _db_path = path
    _initialized = False


def new_id() -> str:
    """Generate a new UUID hex ID."""
    return uuid.uuid4().hex


def _connect(path: Path) -> sqlite3.Connection:
    """Create a new connection with proper settings."""
    conn = sqlite3.connect(str(path), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def init_db(path: Optional[Path] = None) -> None:
    """Initialize the database: create tables if they don't exist.

    Safe to call multiple times — uses IF NOT EXISTS.
    """
    global _initialized, _db_path
    if path:
        _db_path = path
    db_path = get_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)

    log.info("Initializing database at %s", db_path)
    conn = _connect(db_path)
    try:
        schema_sql = _SCHEMA_FILE.read_text(encoding="utf-8")
        conn.executescript(schema_sql)

        # Store schema version
        conn.execute(
            "INSERT OR REPLACE INTO system_config (key, value) VALUES (?, ?)",
            ("db_version", _DB_VERSION),
        )
        conn.commit()
        _initialized = True
        log.info("Database initialized (version %s)", _DB_VERSION)
    finally:
        conn.close()


def ensure_initialized() -> None:
    """Ensure DB is initialized (call from app startup).

    Also re-initializes if the DB file was deleted after first init.
    """
    global _initialized
    if _initialized and not get_db_path().exists():
        _initialized = False
    if not _initialized:
        init_db()


@contextmanager
def get_conn() -> Generator[sqlite3.Connection, None, None]:
    """Get a database connection (context manager).

    Usage:
        with get_conn() as conn:
            conn.execute("SELECT ...")
    """
    ensure_initialized()
    conn = _connect(get_db_path())
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def execute(sql: str, params: tuple = ()) -> sqlite3.Cursor:
    """Execute a single SQL statement and return cursor."""
    with get_conn() as conn:
        return conn.execute(sql, params)


def fetch_one(sql: str, params: tuple = ()) -> Optional[Dict[str, Any]]:
    """Execute and fetch one row as dict."""
    with get_conn() as conn:
        row = conn.execute(sql, params).fetchone()
        return dict(row) if row else None


def fetch_all(sql: str, params: tuple = ()) -> List[Dict[str, Any]]:
    """Execute and fetch all rows as list of dicts."""
    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]


# ============================================================
# First-Run / Setup
# ============================================================

def is_first_run() -> bool:
    """Check if this is a fresh database (no users exist)."""
    ensure_initialized()
    row = fetch_one("SELECT COUNT(*) as cnt FROM users")
    return row is None or row["cnt"] == 0


def create_default_admin() -> str:
    """Create the default admin user for single-user mode.

    Returns the user ID.
    """
    user_id = new_id()
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO users (id, username, role, display_name, settings)
               VALUES (?, ?, ?, ?, ?)""",
            (user_id, "admin", "admin", "Administrator", "{}"),
        )
    log.info("Created default admin user: %s", user_id)
    return user_id


def get_default_user_id() -> str:
    """Get the first admin user ID (for single-user mode)."""
    row = fetch_one("SELECT id FROM users WHERE role = 'admin' LIMIT 1")
    if row:
        return row["id"]
    return create_default_admin()


def get_system_config(key: str, default: str = "") -> str:
    """Get a system config value."""
    row = fetch_one("SELECT value FROM system_config WHERE key = ?", (key,))
    return row["value"] if row else default


def set_system_config(key: str, value: str) -> None:
    """Set a system config value."""
    with get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO system_config (key, value) VALUES (?, ?)",
            (key, value),
        )
