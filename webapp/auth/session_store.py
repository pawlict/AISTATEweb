from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from .passwords import generate_token

log = logging.getLogger("aistate.auth.sessions")


class SessionStore:
    """SQLite-backed session storage (drop-in replacement for JSON version)."""

    COOKIE_NAME = "aistate_session"

    def __init__(self, config_dir: Path) -> None:
        self._config_dir = config_dir
        self._json_path = config_dir / "sessions.json"

    def _conn(self):
        from backend.db.engine import get_conn
        return get_conn()

    def create_session(self, user_id: str, timeout_hours: int = 8, ip: str = "") -> str:
        """Create a new session and return the token."""
        token = generate_token()
        now = datetime.now()
        expires = now + timedelta(hours=timeout_hours)

        with self._conn() as conn:
            conn.execute(
                "INSERT INTO auth_sessions (token, user_id, created_at, expires_at, ip) VALUES (?, ?, ?, ?, ?)",
                (token, user_id, now.isoformat(), expires.isoformat(), ip),
            )
        return token

    def get_session(self, token: str) -> Optional[Dict[str, Any]]:
        """Look up a session by token. Returns None if not found or expired."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM auth_sessions WHERE token = ?", (token,)
            ).fetchone()

        if row is None:
            return None

        session = dict(row)
        # Check expiration
        try:
            expires = datetime.fromisoformat(session["expires_at"])
            if datetime.now() > expires:
                self.delete_session(token)
                return None
        except (KeyError, ValueError):
            return None

        return session

    def delete_session(self, token: str) -> bool:
        """Remove a session."""
        with self._conn() as conn:
            cursor = conn.execute("DELETE FROM auth_sessions WHERE token = ?", (token,))
            return cursor.rowcount > 0

    def delete_user_sessions(self, user_id: str) -> int:
        """Remove ALL sessions for a given user (e.g. on ban). Returns count."""
        with self._conn() as conn:
            cursor = conn.execute("DELETE FROM auth_sessions WHERE user_id = ?", (user_id,))
            return cursor.rowcount

    def count_user_sessions(self, user_id: str) -> int:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT COUNT(*) as cnt FROM auth_sessions WHERE user_id = ?",
                (user_id,),
            ).fetchone()
            return row["cnt"] if row else 0

    def cleanup_expired(self) -> int:
        """Remove all expired sessions. Returns count."""
        now = datetime.now().isoformat()
        with self._conn() as conn:
            cursor = conn.execute(
                "DELETE FROM auth_sessions WHERE expires_at < ?", (now,)
            )
            return cursor.rowcount

    # ---- JSON → SQLite migration ----

    def migrate_from_json(self) -> int:
        """Import sessions from legacy sessions.json if it exists."""
        if not self._json_path.exists():
            return 0

        try:
            data = json.loads(self._json_path.read_text(encoding="utf-8"))
        except Exception:
            return 0

        if not data:
            return 0

        migrated = 0
        now = datetime.now()

        with self._conn() as conn:
            for token, s in data.items():
                # Skip expired sessions
                try:
                    expires = datetime.fromisoformat(s.get("expires_at", ""))
                    if expires < now:
                        continue
                except (ValueError, TypeError):
                    continue

                # Skip if already exists
                existing = conn.execute(
                    "SELECT token FROM auth_sessions WHERE token = ?", (token,)
                ).fetchone()
                if existing:
                    continue

                conn.execute(
                    "INSERT INTO auth_sessions (token, user_id, created_at, expires_at, ip) VALUES (?, ?, ?, ?, ?)",
                    (
                        token,
                        s.get("user_id", ""),
                        s.get("created_at", now.isoformat()),
                        s.get("expires_at", ""),
                        s.get("ip", ""),
                    ),
                )
                migrated += 1

        if migrated > 0:
            backup = self._json_path.with_suffix(".json.bak")
            self._json_path.rename(backup)
            log.info("Migrated %d sessions from JSON; old file renamed to %s", migrated, backup.name)

        return migrated
