from __future__ import annotations

import json
import threading
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


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
    """Thread-safe JSON-based message storage for Call Center."""

    def __init__(self, config_dir: Path) -> None:
        self._path = config_dir / "messages.json"
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

    def _msg_from_dict(self, mid: str, d: Dict[str, Any]) -> Message:
        msg = Message()
        msg.message_id = mid
        for k, v in d.items():
            if hasattr(msg, k):
                setattr(msg, k, v)
        msg.message_id = mid
        return msg

    # ---- CRUD ----

    def list_messages(self) -> List[Message]:
        with self._lock:
            data = self._read()
        msgs = [self._msg_from_dict(mid, d) for mid, d in data.items()]
        msgs.sort(key=lambda m: m.created_at, reverse=True)
        return msgs

    def get_message(self, message_id: str) -> Optional[Message]:
        with self._lock:
            data = self._read()
        d = data.get(message_id)
        if d is None:
            return None
        return self._msg_from_dict(message_id, d)

    def create_message(self, msg: Message) -> Message:
        if not msg.message_id:
            msg.message_id = str(uuid.uuid4())
        if not msg.created_at:
            msg.created_at = datetime.now().isoformat()
        with self._lock:
            data = self._read()
            d = asdict(msg)
            mid = d.pop("message_id")
            data[mid] = d
            self._write(data)
        return msg

    def delete_message(self, message_id: str) -> bool:
        with self._lock:
            data = self._read()
            if message_id not in data:
                return False
            del data[message_id]
            self._write(data)
        return True

    def mark_read(self, message_id: str, user_id: str) -> bool:
        with self._lock:
            data = self._read()
            if message_id not in data:
                return False
            read_by = data[message_id].get("read_by", [])
            if user_id not in read_by:
                read_by.append(user_id)
                data[message_id]["read_by"] = read_by
                self._write(data)
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

        with self._lock:
            data = self._read()

        result: List[Message] = []
        for mid, d in data.items():
            target = set(d.get("target_groups", []))
            read_by = d.get("read_by", [])
            if user_id in read_by:
                continue
            # Check if any of user's groups match message targets
            if target & groups:
                result.append(self._msg_from_dict(mid, d))

        result.sort(key=lambda m: m.created_at, reverse=True)
        return result
