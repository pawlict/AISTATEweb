from __future__ import annotations

import json
import threading
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


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
    created_at: str = ""
    created_by: str = ""                # user_id of creator or "system"
    last_login: Optional[str] = None


class UserStore:
    """Thread-safe JSON-based user storage."""

    def __init__(self, config_dir: Path) -> None:
        self._path = config_dir / "users.json"
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

    def _record_from_dict(self, uid: str, d: Dict[str, Any]) -> UserRecord:
        rec = UserRecord()
        rec.user_id = uid
        for k, v in d.items():
            if hasattr(rec, k):
                setattr(rec, k, v)
        rec.user_id = uid  # always enforce key
        return rec

    # ---- CRUD ----

    def list_users(self) -> List[UserRecord]:
        with self._lock:
            data = self._read()
        return [self._record_from_dict(uid, d) for uid, d in data.items()]

    def get_user(self, user_id: str) -> Optional[UserRecord]:
        with self._lock:
            data = self._read()
        d = data.get(user_id)
        if d is None:
            return None
        return self._record_from_dict(user_id, d)

    def get_by_username(self, username: str) -> Optional[UserRecord]:
        username_lower = username.lower()
        with self._lock:
            data = self._read()
        for uid, d in data.items():
            if d.get("username", "").lower() == username_lower:
                return self._record_from_dict(uid, d)
        return None

    def create_user(self, rec: UserRecord) -> UserRecord:
        if not rec.user_id:
            rec.user_id = str(uuid.uuid4())
        if not rec.created_at:
            rec.created_at = datetime.now().isoformat()
        with self._lock:
            data = self._read()
            # Check username uniqueness
            for uid, d in data.items():
                if d.get("username", "").lower() == rec.username.lower():
                    raise ValueError(f"Username '{rec.username}' already exists")
            d = asdict(rec)
            uid = d.pop("user_id")
            data[uid] = d
            self._write(data)
        return rec

    def update_user(self, user_id: str, updates: Dict[str, Any]) -> Optional[UserRecord]:
        with self._lock:
            data = self._read()
            if user_id not in data:
                return None
            # If changing username, check uniqueness
            new_username = updates.get("username")
            if new_username:
                for uid, d in data.items():
                    if uid != user_id and d.get("username", "").lower() == new_username.lower():
                        raise ValueError(f"Username '{new_username}' already exists")
            data[user_id].update(updates)
            self._write(data)
            return self._record_from_dict(user_id, data[user_id])

    def delete_user(self, user_id: str) -> bool:
        with self._lock:
            data = self._read()
            if user_id not in data:
                return False
            del data[user_id]
            self._write(data)
        return True

    def user_count(self) -> int:
        with self._lock:
            return len(self._read())

    def has_users(self) -> bool:
        return self.user_count() > 0
