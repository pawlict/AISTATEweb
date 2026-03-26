from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger("aistate.auth.users")


@dataclass
class UserRecord:
    user_id: str = ""
    username: str = ""
    display_name: str = ""
    password_hash: str = ""
    role: Optional[str] = None          # user role (Transkryptor, Lingwista, …)
    is_admin: bool = False
    admin_roles: List[str] = field(default_factory=list)
    is_superadmin: bool = False
    banned: bool = False
    banned_until: Optional[str] = None  # ISO datetime or None
    ban_reason: Optional[str] = None
    show_ban_expiry: bool = True        # Whether to show ban expiry date to user
    language: str = "pl"                 # UI language preference (pl, en)
    theme: str = "light"                 # UI theme preference (light, dark)
    pending: bool = False               # True = waiting for admin approval
    pending_role: Optional[str] = None  # requested role (shown to admin for approval)
    created_at: str = ""
    created_by: str = ""                # user_id of creator or "system" or "self"
    last_login: Optional[str] = None
    password_reset_requested: bool = False
    password_reset_requested_at: Optional[str] = None
    # Account lockout (brute-force protection)
    failed_login_count: int = 0
    locked_until: Optional[str] = None       # ISO datetime — auto-unlock after
    # Password expiration
    password_changed_at: Optional[str] = None  # ISO datetime of last password change
    # Recovery phrase
    recovery_phrase_hash: Optional[str] = None   # PBKDF2 hash of 12-word recovery phrase
    recovery_phrase_hint: Optional[str] = None   # SHA256 hint (16 hex chars) for fast lookup
    recovery_phrase_pending: Optional[str] = None  # Temporary plaintext of new phrase (shown once at login, then cleared)


# Columns that exist in the original schema.sql 'users' table
_BASE_COLUMNS = {
    "id", "username", "password_hash", "role", "display_name", "email",
    "is_active", "settings", "created_at", "updated_at",
}

# Extended auth columns we add via ALTER TABLE
_AUTH_COLUMNS = [
    ("is_admin", "INTEGER NOT NULL DEFAULT 0"),
    ("admin_roles", "TEXT DEFAULT '[]'"),
    ("is_superadmin", "INTEGER NOT NULL DEFAULT 0"),
    ("banned", "INTEGER NOT NULL DEFAULT 0"),
    ("banned_until", "TEXT"),
    ("ban_reason", "TEXT"),
    ("show_ban_expiry", "INTEGER NOT NULL DEFAULT 1"),
    ("language", "TEXT DEFAULT 'pl'"),
    ("theme", "TEXT DEFAULT 'light'"),
    ("pending", "INTEGER NOT NULL DEFAULT 0"),
    ("pending_role", "TEXT"),
    ("created_by", "TEXT DEFAULT ''"),
    ("last_login", "TEXT"),
    ("password_reset_requested", "INTEGER NOT NULL DEFAULT 0"),
    ("password_reset_requested_at", "TEXT"),
    ("failed_login_count", "INTEGER NOT NULL DEFAULT 0"),
    ("locked_until", "TEXT"),
    ("password_changed_at", "TEXT"),
    ("recovery_phrase_hash", "TEXT"),
    ("recovery_phrase_hint", "TEXT"),
    ("recovery_phrase_pending", "TEXT"),
]


def _ensure_auth_columns(conn) -> None:
    """Add auth-specific columns to users table if they don't exist yet."""
    existing = {row[1] for row in conn.execute("PRAGMA table_info(users)").fetchall()}
    added = False
    for col_name, col_def in _AUTH_COLUMNS:
        if col_name not in existing:
            conn.execute(f"ALTER TABLE users ADD COLUMN {col_name} {col_def}")
            log.info("Added column users.%s", col_name)
            added = True
    if added:
        conn.commit()


class UserStore:
    """SQLite-backed user storage (drop-in replacement for JSON version)."""

    def __init__(self, config_dir: Path) -> None:
        # config_dir kept for API compatibility; DB path comes from engine
        self._config_dir = config_dir
        self._json_path = config_dir / "users.json"
        self._migrated = False

    def _conn(self):
        from backend.db.engine import get_conn
        return get_conn()

    def _ensure_schema(self, conn) -> None:
        """Ensure auth columns exist, run once per process."""
        if not self._migrated:
            _ensure_auth_columns(conn)
            self._migrated = True

    def _record_from_row(self, row: Dict[str, Any]) -> UserRecord:
        rec = UserRecord()
        rec.user_id = row.get("id", "")
        rec.username = row.get("username", "")
        rec.display_name = row.get("display_name", "")
        rec.password_hash = row.get("password_hash", "")
        raw_role = row.get("role", "")
        # Handle role='admin' from old schema (single-user default)
        if raw_role == "admin" and not row.get("is_admin"):
            raw_role = ""
        rec.role = raw_role or None
        rec.is_admin = bool(row.get("is_admin", 0))
        # admin_roles stored as JSON string
        ar = row.get("admin_roles", "[]")
        if isinstance(ar, str):
            try:
                rec.admin_roles = json.loads(ar)
            except (json.JSONDecodeError, TypeError):
                rec.admin_roles = []
        else:
            rec.admin_roles = ar or []
        rec.is_superadmin = bool(row.get("is_superadmin", 0))
        rec.banned = bool(row.get("banned", 0))
        rec.banned_until = row.get("banned_until")
        rec.ban_reason = row.get("ban_reason")
        rec.show_ban_expiry = bool(row.get("show_ban_expiry", 1))
        rec.language = row.get("language", "pl") or "pl"
        rec.theme = row.get("theme", "light") or "light"
        rec.pending = bool(row.get("pending", 0))
        rec.pending_role = row.get("pending_role")
        rec.created_at = row.get("created_at", "")
        rec.created_by = row.get("created_by", "")
        rec.last_login = row.get("last_login")
        rec.password_reset_requested = bool(row.get("password_reset_requested", 0))
        rec.password_reset_requested_at = row.get("password_reset_requested_at")
        rec.failed_login_count = int(row.get("failed_login_count", 0) or 0)
        rec.locked_until = row.get("locked_until")
        rec.password_changed_at = row.get("password_changed_at")
        rec.recovery_phrase_hash = row.get("recovery_phrase_hash")
        rec.recovery_phrase_hint = row.get("recovery_phrase_hint")
        rec.recovery_phrase_pending = row.get("recovery_phrase_pending")
        return rec

    # ---- CRUD ----

    def list_users(self) -> List[UserRecord]:
        with self._conn() as conn:
            self._ensure_schema(conn)
            rows = conn.execute("SELECT * FROM users ORDER BY created_at").fetchall()
            return [self._record_from_row(dict(r)) for r in rows]

    def get_user(self, user_id: str) -> Optional[UserRecord]:
        with self._conn() as conn:
            self._ensure_schema(conn)
            row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
            if row is None:
                return None
            return self._record_from_row(dict(row))

    def get_by_username(self, username: str) -> Optional[UserRecord]:
        username_lower = username.lower()
        with self._conn() as conn:
            self._ensure_schema(conn)
            # SQLite COLLATE NOCASE or manual lower()
            row = conn.execute(
                "SELECT * FROM users WHERE LOWER(username) = ?",
                (username_lower,),
            ).fetchone()
            if row is None:
                return None
            return self._record_from_row(dict(row))

    def create_user(self, rec: UserRecord) -> UserRecord:
        if not rec.user_id:
            rec.user_id = str(uuid.uuid4())
        if not rec.created_at:
            rec.created_at = datetime.now().isoformat()

        with self._conn() as conn:
            self._ensure_schema(conn)
            # Check username uniqueness (case-insensitive)
            existing = conn.execute(
                "SELECT id FROM users WHERE LOWER(username) = ?",
                (rec.username.lower(),),
            ).fetchone()
            if existing:
                raise ValueError(f"Username '{rec.username}' already exists")

            conn.execute(
                """INSERT INTO users (
                    id, username, password_hash, role, display_name,
                    is_admin, admin_roles, is_superadmin,
                    banned, banned_until, ban_reason, show_ban_expiry,
                    language, theme, pending, pending_role,
                    created_at, created_by, last_login,
                    password_reset_requested, password_reset_requested_at,
                    failed_login_count, locked_until, password_changed_at,
                    recovery_phrase_hash, recovery_phrase_hint, recovery_phrase_pending
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    rec.user_id,
                    rec.username,
                    rec.password_hash,
                    rec.role or "",
                    rec.display_name,
                    int(rec.is_admin),
                    json.dumps(rec.admin_roles, ensure_ascii=False),
                    int(rec.is_superadmin),
                    int(rec.banned),
                    rec.banned_until,
                    rec.ban_reason,
                    int(rec.show_ban_expiry),
                    rec.language,
                    rec.theme,
                    int(rec.pending),
                    rec.pending_role,
                    rec.created_at,
                    rec.created_by,
                    rec.last_login,
                    int(rec.password_reset_requested),
                    rec.password_reset_requested_at,
                    rec.failed_login_count,
                    rec.locked_until,
                    rec.password_changed_at,
                    rec.recovery_phrase_hash,
                    rec.recovery_phrase_hint,
                    rec.recovery_phrase_pending,
                ),
            )
        return rec

    def update_user(self, user_id: str, updates: Dict[str, Any]) -> Optional[UserRecord]:
        with self._conn() as conn:
            self._ensure_schema(conn)

            existing = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
            if existing is None:
                return None

            # If changing username, check uniqueness
            new_username = updates.get("username")
            if new_username:
                dup = conn.execute(
                    "SELECT id FROM users WHERE LOWER(username) = ? AND id != ?",
                    (new_username.lower(), user_id),
                ).fetchone()
                if dup:
                    raise ValueError(f"Username '{new_username}' already exists")

            # Map Python field names to SQL column names and convert types
            sql_updates = {}
            for key, value in updates.items():
                if key == "user_id":
                    continue
                if key == "admin_roles" and isinstance(value, list):
                    sql_updates["admin_roles"] = json.dumps(value, ensure_ascii=False)
                elif key in ("is_admin", "is_superadmin", "banned", "show_ban_expiry",
                             "pending", "password_reset_requested"):
                    sql_updates[key] = int(bool(value))
                elif key == "failed_login_count":
                    sql_updates[key] = int(value or 0)
                else:
                    sql_updates[key] = value

            if not sql_updates:
                return self._record_from_row(dict(existing))

            set_clause = ", ".join(f"{k} = ?" for k in sql_updates)
            values = list(sql_updates.values()) + [user_id]
            conn.execute(f"UPDATE users SET {set_clause} WHERE id = ?", values)

            row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
            return self._record_from_row(dict(row))

    def delete_user(self, user_id: str) -> bool:
        with self._conn() as conn:
            self._ensure_schema(conn)
            cursor = conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
            return cursor.rowcount > 0

    def get_by_phrase_hint(self, hint: str) -> Optional[UserRecord]:
        """Find a user by recovery phrase hint (SHA256 prefix)."""
        with self._conn() as conn:
            self._ensure_schema(conn)
            row = conn.execute(
                "SELECT * FROM users WHERE recovery_phrase_hint = ?",
                (hint,),
            ).fetchone()
            if row is None:
                return None
            return self._record_from_row(dict(row))

    def user_count(self) -> int:
        with self._conn() as conn:
            self._ensure_schema(conn)
            row = conn.execute("SELECT COUNT(*) as cnt FROM users").fetchone()
            return row["cnt"] if row else 0

    def has_users(self) -> bool:
        return self.user_count() > 0

    def has_approved_users(self) -> bool:
        """Return True if at least one non-pending user exists."""
        with self._conn() as conn:
            self._ensure_schema(conn)
            row = conn.execute(
                "SELECT COUNT(*) as cnt FROM users WHERE pending = 0"
            ).fetchone()
            return (row["cnt"] if row else 0) > 0

    def get_access_guard_names(self) -> List[str]:
        """Return distinct role labels of users who can approve accounts."""
        return ["Architekt Funkcji", "Strażnik Dostępu"]

    # ---- JSON → SQLite migration ----

    def migrate_from_json(self) -> int:
        """Import users from legacy users.json if it exists. Returns count migrated."""
        if not self._json_path.exists():
            return 0

        try:
            data = json.loads(self._json_path.read_text(encoding="utf-8"))
        except Exception:
            return 0

        if not data:
            return 0

        migrated = 0
        for uid, d in data.items():
            # Check if user already exists in DB
            existing = self.get_user(uid)
            if existing is not None:
                continue

            rec = UserRecord()
            rec.user_id = uid
            for k, v in d.items():
                if hasattr(rec, k):
                    setattr(rec, k, v)
            rec.user_id = uid

            try:
                self.create_user(rec)
                migrated += 1
            except ValueError:
                # Username conflict — skip
                log.warning("Skipping migration of user %s (%s): username conflict", uid, d.get("username", "?"))

        if migrated > 0:
            # Rename the old file so migration doesn't re-run
            backup = self._json_path.with_suffix(".json.bak")
            self._json_path.rename(backup)
            log.info("Migrated %d users from JSON; old file renamed to %s", migrated, backup.name)

        return migrated
