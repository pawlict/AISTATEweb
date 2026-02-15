from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger("aistate.auth.messages")


@dataclass
class Message:
    message_id: str = ""
    author_id: str = ""
    author_name: str = ""
    subject: str = ""
    content: str = ""           # HTML content (rich text)
    target_groups: List[str] = field(default_factory=list)  # role names to target
    created_at: str = ""
    read_by: List[str] = field(default_factory=list)        # user_ids who confirmed


class MessageStore:
    """SQLite-backed message storage for Call Center (drop-in replacement for JSON version)."""

    def __init__(self, config_dir: Path) -> None:
        self._config_dir = config_dir
        self._json_path = config_dir / "messages.json"

    def _conn(self):
        from backend.db.engine import get_conn
        return get_conn()

    def _msg_from_row(self, row: Dict[str, Any], read_by: List[str]) -> Message:
        msg = Message()
        msg.message_id = row.get("message_id", "")
        msg.author_id = row.get("author_id", "")
        msg.author_name = row.get("author_name", "")
        msg.subject = row.get("subject", "")
        msg.content = row.get("content", "")
        tg = row.get("target_groups", "[]")
        if isinstance(tg, str):
            try:
                msg.target_groups = json.loads(tg)
            except (json.JSONDecodeError, TypeError):
                msg.target_groups = []
        else:
            msg.target_groups = tg or []
        msg.created_at = row.get("created_at", "")
        msg.read_by = read_by
        return msg

    def _get_read_by(self, conn, message_id: str) -> List[str]:
        rows = conn.execute(
            "SELECT user_id FROM auth_message_reads WHERE message_id = ?",
            (message_id,),
        ).fetchall()
        return [r["user_id"] for r in rows]

    # ---- CRUD ----

    def list_messages(self) -> List[Message]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM auth_messages ORDER BY created_at DESC"
            ).fetchall()
            msgs = []
            for row in rows:
                d = dict(row)
                read_by = self._get_read_by(conn, d["message_id"])
                msgs.append(self._msg_from_row(d, read_by))
            return msgs

    def get_message(self, message_id: str) -> Optional[Message]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM auth_messages WHERE message_id = ?",
                (message_id,),
            ).fetchone()
            if row is None:
                return None
            d = dict(row)
            read_by = self._get_read_by(conn, message_id)
            return self._msg_from_row(d, read_by)

    def create_message(self, msg: Message) -> Message:
        if not msg.message_id:
            msg.message_id = str(uuid.uuid4())
        if not msg.created_at:
            msg.created_at = datetime.now().isoformat()

        with self._conn() as conn:
            conn.execute(
                """INSERT INTO auth_messages
                   (message_id, author_id, author_name, subject, content, target_groups, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    msg.message_id,
                    msg.author_id,
                    msg.author_name,
                    msg.subject,
                    msg.content,
                    json.dumps(msg.target_groups, ensure_ascii=False),
                    msg.created_at,
                ),
            )
        return msg

    def delete_message(self, message_id: str) -> bool:
        with self._conn() as conn:
            cursor = conn.execute(
                "DELETE FROM auth_messages WHERE message_id = ?", (message_id,)
            )
            return cursor.rowcount > 0

    def mark_read(self, message_id: str, user_id: str) -> bool:
        with self._conn() as conn:
            # Check message exists
            row = conn.execute(
                "SELECT message_id FROM auth_messages WHERE message_id = ?",
                (message_id,),
            ).fetchone()
            if row is None:
                return False

            # Insert read record (ignore if already exists)
            conn.execute(
                "INSERT OR IGNORE INTO auth_message_reads (message_id, user_id) VALUES (?, ?)",
                (message_id, user_id),
            )
        return True

    def get_unread_for_user(self, user_id: str, user_role: Optional[str],
                            is_admin: bool, admin_roles: Optional[List[str]],
                            is_superadmin: bool) -> List[Message]:
        """Return messages targeted at this user's groups that they haven't read."""
        # Build set of groups this user belongs to
        groups: set = set()
        if user_role:
            groups.add(user_role)
        if is_admin and admin_roles:
            for ar in admin_roles:
                groups.add(ar)
        if is_superadmin:
            groups.add("Główny Opiekun")
        # Always include "all" target
        groups.add("all")

        with self._conn() as conn:
            # Get all messages NOT read by this user
            rows = conn.execute(
                """SELECT m.* FROM auth_messages m
                   WHERE m.message_id NOT IN (
                       SELECT r.message_id FROM auth_message_reads r WHERE r.user_id = ?
                   )
                   ORDER BY m.created_at DESC""",
                (user_id,),
            ).fetchall()

        result: List[Message] = []
        for row in rows:
            d = dict(row)
            tg = d.get("target_groups", "[]")
            try:
                target = set(json.loads(tg) if isinstance(tg, str) else tg)
            except (json.JSONDecodeError, TypeError):
                target = set()

            # Check if any of user's groups match message targets
            if target & groups:
                result.append(self._msg_from_row(d, []))

        return result

    # ---- JSON → SQLite migration ----

    def migrate_from_json(self) -> int:
        """Import messages from legacy messages.json if it exists."""
        if not self._json_path.exists():
            return 0

        try:
            data = json.loads(self._json_path.read_text(encoding="utf-8"))
        except Exception:
            return 0

        if not data:
            return 0

        migrated = 0
        with self._conn() as conn:
            for mid, d in data.items():
                # Skip if already exists
                existing = conn.execute(
                    "SELECT message_id FROM auth_messages WHERE message_id = ?", (mid,)
                ).fetchone()
                if existing:
                    continue

                target_groups = d.get("target_groups", [])
                conn.execute(
                    """INSERT INTO auth_messages
                       (message_id, author_id, author_name, subject, content, target_groups, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        mid,
                        d.get("author_id", ""),
                        d.get("author_name", ""),
                        d.get("subject", ""),
                        d.get("content", ""),
                        json.dumps(target_groups, ensure_ascii=False),
                        d.get("created_at", ""),
                    ),
                )

                # Migrate read_by
                for uid in d.get("read_by", []):
                    conn.execute(
                        "INSERT OR IGNORE INTO auth_message_reads (message_id, user_id) VALUES (?, ?)",
                        (mid, uid),
                    )

                migrated += 1

        if migrated > 0:
            backup = self._json_path.with_suffix(".json.bak")
            self._json_path.rename(backup)
            log.info("Migrated %d messages from JSON; old file renamed to %s", migrated, backup.name)

        return migrated
