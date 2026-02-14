from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from .passwords import generate_token


class SessionStore:
    """Thread-safe JSON-based session storage with token lookup."""

    COOKIE_NAME = "aistate_session"

    def __init__(self, config_dir: Path) -> None:
        self._path = config_dir / "sessions.json"
        self._lock = threading.Lock()

    def _read(self) -> Dict[str, Any]:
        try:
            return json.loads(self._path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except Exception:
            return {}

    def _write(self, data: Dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self._path)

    def create_session(self, user_id: str, timeout_hours: int = 8, ip: str = "") -> str:
        """Create a new session and return the token."""
        token = generate_token()
        now = datetime.now()
        expires = now + timedelta(hours=timeout_hours)

        with self._lock:
            data = self._read()
            data[token] = {
                "user_id": user_id,
                "created_at": now.isoformat(),
                "expires_at": expires.isoformat(),
                "ip": ip,
            }
            self._write(data)
        return token

    def get_session(self, token: str) -> Optional[Dict[str, Any]]:
        """Look up a session by token. Returns None if not found or expired."""
        with self._lock:
            data = self._read()
        session = data.get(token)
        if session is None:
            return None
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
        with self._lock:
            data = self._read()
            if token not in data:
                return False
            del data[token]
            self._write(data)
        return True

    def delete_user_sessions(self, user_id: str) -> int:
        """Remove ALL sessions for a given user (e.g. on ban). Returns count."""
        removed = 0
        with self._lock:
            data = self._read()
            to_remove = [tok for tok, s in data.items() if s.get("user_id") == user_id]
            for tok in to_remove:
                del data[tok]
                removed += 1
            if removed:
                self._write(data)
        return removed

    def count_user_sessions(self, user_id: str) -> int:
        with self._lock:
            data = self._read()
        return sum(1 for s in data.values() if s.get("user_id") == user_id)

    def cleanup_expired(self) -> int:
        """Remove all expired sessions. Returns count."""
        now = datetime.now()
        removed = 0
        with self._lock:
            data = self._read()
            expired = []
            for tok, s in data.items():
                try:
                    if datetime.fromisoformat(s["expires_at"]) < now:
                        expired.append(tok)
                except (KeyError, ValueError):
                    expired.append(tok)
            for tok in expired:
                del data[tok]
                removed += 1
            if removed:
                self._write(data)
        return removed
