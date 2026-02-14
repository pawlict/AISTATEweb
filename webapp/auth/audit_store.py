from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


class AuditStore:
    """Thread-safe JSON-based audit log for authentication events.

    Events: login, login_failed, logout, password_changed, password_reset,
            account_locked, account_unlocked, user_created, user_banned,
            user_unbanned, user_approved, user_rejected, user_deleted,
            password_expired_redirect.
    """

    def __init__(self, config_dir: Path) -> None:
        self._path = config_dir / "audit_log.json"
        self._lock = threading.Lock()

    def _read(self) -> List[Dict[str, Any]]:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return data
            return []
        except FileNotFoundError:
            return []
        except Exception:
            return []

    def _write(self, data: List[Dict[str, Any]]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        # Keep max 5000 entries to prevent unbounded growth
        if len(data) > 5000:
            data = data[-5000:]
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self._path)

    def log_event(
        self,
        event: str,
        *,
        user_id: str = "",
        username: str = "",
        ip: str = "",
        detail: str = "",
        actor_id: str = "",
        actor_name: str = "",
    ) -> None:
        """Append an audit event."""
        entry: Dict[str, Any] = {
            "id": str(uuid.uuid4()),
            "timestamp": datetime.now().isoformat(),
            "event": event,
            "user_id": user_id,
            "username": username,
            "ip": ip,
            "detail": detail,
        }
        if actor_id:
            entry["actor_id"] = actor_id
            entry["actor_name"] = actor_name
        with self._lock:
            data = self._read()
            data.append(entry)
            self._write(data)

    def get_events(
        self,
        *,
        user_id: str = "",
        event_type: str = "",
        limit: int = 200,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """Return audit events (newest first), optionally filtered."""
        with self._lock:
            data = self._read()
        # Filter
        if user_id:
            data = [e for e in data if e.get("user_id") == user_id]
        if event_type:
            data = [e for e in data if e.get("event") == event_type]
        # Sort newest first
        data.sort(key=lambda e: e.get("timestamp", ""), reverse=True)
        return data[offset : offset + limit]

    def count_events(self, *, user_id: str = "", event_type: str = "") -> int:
        with self._lock:
            data = self._read()
        if user_id:
            data = [e for e in data if e.get("user_id") == user_id]
        if event_type:
            data = [e for e in data if e.get("event") == event_type]
        return len(data)

    def get_user_events(self, user_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        """Convenience: events for a single user (for their profile view)."""
        return self.get_events(user_id=user_id, limit=limit)
