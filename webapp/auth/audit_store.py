from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger("aistate.auth.audit")


class AuditStore:
    """SQLite-backed audit log for authentication events.

    Events: login, login_failed, logout, password_changed, password_reset,
            account_locked, account_unlocked, user_created, user_banned,
            user_unbanned, user_approved, user_rejected, user_deleted,
            password_expired_redirect.
    """

    def __init__(self, config_dir: Path, file_logger: Any = None) -> None:
        self._config_dir = config_dir
        self._json_path = config_dir / "audit_log.json"
        self._file_logger = file_logger

    def _conn(self):
        from backend.db.engine import get_conn
        return get_conn()

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
        fingerprint: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Append an audit event."""
        entry_id = str(uuid.uuid4())
        ts = datetime.now().isoformat()
        fp_str = json.dumps(fingerprint, ensure_ascii=False) if fingerprint else ""

        with self._conn() as conn:
            conn.execute(
                """INSERT INTO auth_audit_log
                   (id, timestamp, event, user_id, username, ip, detail, actor_id, actor_name, fingerprint)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (entry_id, ts, event, user_id, username, ip, detail, actor_id, actor_name, fp_str),
            )

        # Also write to file-based log (backend/logs/)
        if self._file_logger:
            try:
                parts = [f"event={event}"]
                if username:
                    parts.append(f"user={username}")
                if user_id:
                    parts.append(f"uid={user_id}")
                if ip:
                    parts.append(f"ip={ip}")
                if actor_name:
                    parts.append(f"actor={actor_name}")
                if detail:
                    parts.append(f"detail={detail}")
                if fingerprint:
                    fp_parts = " ".join(f"{k}={v}" for k, v in fingerprint.items() if v)
                    parts.append(f"device=[{fp_parts}]")
                self._file_logger.write_line(f"{ts} | {' '.join(parts)}")
            except Exception:
                pass

    def get_events(
        self,
        *,
        user_id: str = "",
        event_type: str = "",
        limit: int = 200,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """Return audit events (newest first), optionally filtered."""
        conditions = []
        params: list = []

        if user_id:
            conditions.append("user_id = ?")
            params.append(user_id)
        if event_type:
            conditions.append("event = ?")
            params.append(event_type)

        where = ""
        if conditions:
            where = "WHERE " + " AND ".join(conditions)

        params.extend([limit, offset])

        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT * FROM auth_audit_log {where} ORDER BY timestamp DESC LIMIT ? OFFSET ?",
                tuple(params),
            ).fetchall()

        result = []
        for row in rows:
            d = dict(row)
            # Parse fingerprint back to dict if present
            fp = d.get("fingerprint", "")
            if fp:
                try:
                    d["fingerprint"] = json.loads(fp)
                except (json.JSONDecodeError, TypeError):
                    d["fingerprint"] = {}
            else:
                d.pop("fingerprint", None)
            result.append(d)
        return result

    def count_events(self, *, user_id: str = "", event_type: str = "") -> int:
        conditions = []
        params: list = []

        if user_id:
            conditions.append("user_id = ?")
            params.append(user_id)
        if event_type:
            conditions.append("event = ?")
            params.append(event_type)

        where = ""
        if conditions:
            where = "WHERE " + " AND ".join(conditions)

        with self._conn() as conn:
            row = conn.execute(
                f"SELECT COUNT(*) as cnt FROM auth_audit_log {where}",
                tuple(params),
            ).fetchone()
            return row["cnt"] if row else 0

    def get_user_events(self, user_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        """Convenience: events for a single user (for their profile view)."""
        return self.get_events(user_id=user_id, limit=limit)

    # ---- JSON → SQLite migration ----

    def migrate_from_json(self) -> int:
        """Import audit events from legacy audit_log.json if it exists."""
        if not self._json_path.exists():
            return 0

        try:
            data = json.loads(self._json_path.read_text(encoding="utf-8"))
            if not isinstance(data, list):
                return 0
        except Exception:
            return 0

        if not data:
            return 0

        migrated = 0
        with self._conn() as conn:
            for entry in data:
                entry_id = entry.get("id", str(uuid.uuid4()))

                # Skip if already exists
                existing = conn.execute(
                    "SELECT id FROM auth_audit_log WHERE id = ?", (entry_id,)
                ).fetchone()
                if existing:
                    continue

                fp = entry.get("fingerprint")
                fp_str = json.dumps(fp, ensure_ascii=False) if fp else ""

                conn.execute(
                    """INSERT INTO auth_audit_log
                       (id, timestamp, event, user_id, username, ip, detail, actor_id, actor_name, fingerprint)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        entry_id,
                        entry.get("timestamp", ""),
                        entry.get("event", ""),
                        entry.get("user_id", ""),
                        entry.get("username", ""),
                        entry.get("ip", ""),
                        entry.get("detail", ""),
                        entry.get("actor_id", ""),
                        entry.get("actor_name", ""),
                        fp_str,
                    ),
                )
                migrated += 1

        if migrated > 0:
            backup = self._json_path.with_suffix(".json.bak")
            self._json_path.rename(backup)
            log.info("Migrated %d audit events from JSON; old file renamed to %s", migrated, backup.name)

        return migrated
