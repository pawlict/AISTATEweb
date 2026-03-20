"""
Key management: Master Key and per-project key lifecycle.

Master Key hierarchy:
  admin password → KDF → wrapping key → unwraps Master Key
  Master Key → wraps each Project Key
  Project Key → encrypts project files
"""
from __future__ import annotations

import json
import os
import base64
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Tuple

from .primitives import (
    derive_key,
    generate_key,
    generate_salt,
    wrap_key,
    unwrap_key,
    encrypt_block,
    decrypt_block,
    SALT_SIZE,
)

# ── Constants ──────────────────────────────────────────────────────────
_MASTER_KEY_FILE = "master_key.enc"
_ENCRYPTION_META_FILE = "encryption_meta.json"


class MasterKeyManager:
    """Manages the server-wide Master Key.

    The Master Key is a random 256-bit key stored encrypted on disk.
    It is encrypted using a wrapping key derived from the admin's password.
    """

    def __init__(self, config_dir: Path):
        self._config_dir = Path(config_dir)
        self._lock = threading.Lock()
        self._cached_master_key: Optional[bytes] = None

    @property
    def key_file(self) -> Path:
        return self._config_dir / _MASTER_KEY_FILE

    @property
    def meta_file(self) -> Path:
        return self._config_dir / _ENCRYPTION_META_FILE

    @property
    def is_initialized(self) -> bool:
        return self.key_file.exists() and self.meta_file.exists()

    def initialize(self, admin_password: str, method: str = "standard") -> bytes:
        """Generate a new Master Key and store it encrypted.

        Returns the raw Master Key (caller should NOT store it).
        """
        with self._lock:
            if self.is_initialized:
                raise RuntimeError("Master Key already initialized")

            master_key = generate_key(32)  # always 256-bit
            salt = generate_salt()

            # Derive wrapping key from admin password
            wrapping_key = derive_key(admin_password, salt, method, key_length=32)

            # Wrap the master key
            wrapped = wrap_key(wrapping_key, master_key)

            # Store wrapped key
            self._config_dir.mkdir(parents=True, exist_ok=True)
            self.key_file.write_bytes(wrapped)

            # Store metadata
            meta = {
                "key_id": base64.b16encode(os.urandom(8)).decode().lower(),
                "kdf_method": method,
                "kdf_salt": base64.b64encode(salt).decode(),
                "created_at": datetime.now(timezone.utc).isoformat(),
                "version": 1,
            }
            self.meta_file.write_text(
                json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
            )

            self._cached_master_key = master_key
            return master_key

    def load(self, admin_password: str) -> bytes:
        """Load and unwrap the Master Key using the admin's password.

        Caches the key in memory for the process lifetime.
        """
        with self._lock:
            if self._cached_master_key is not None:
                return self._cached_master_key

            if not self.is_initialized:
                raise RuntimeError("Master Key not initialized")

            meta = json.loads(self.meta_file.read_text(encoding="utf-8"))
            salt = base64.b64decode(meta["kdf_salt"])
            method = meta.get("kdf_method", "standard")

            wrapping_key = derive_key(admin_password, salt, method, key_length=32)
            wrapped = self.key_file.read_bytes()

            try:
                master_key = unwrap_key(wrapping_key, wrapped)
            except Exception:
                raise ValueError("Invalid admin password — cannot unlock Master Key")

            self._cached_master_key = master_key
            return master_key

    def verify(self, admin_password: str) -> bool:
        """Verify that the admin password can unlock the Master Key."""
        try:
            self.load(admin_password)
            return True
        except (ValueError, RuntimeError):
            return False

    def export_backup(self, admin_password: str) -> str:
        """Export the Master Key as a base64 string for offline backup.

        The caller should display this to the admin for manual backup.
        """
        master_key = self.load(admin_password)
        return base64.b64encode(master_key).decode()

    def get_cached(self) -> Optional[bytes]:
        """Return the cached Master Key or None if not loaded."""
        return self._cached_master_key

    def clear_cache(self) -> None:
        """Clear the cached Master Key from memory."""
        with self._lock:
            self._cached_master_key = None

    def get_metadata(self) -> Optional[dict]:
        """Return Master Key metadata (kdf method, creation date, etc.)."""
        if not self.meta_file.exists():
            return None
        return json.loads(self.meta_file.read_text(encoding="utf-8"))


class ProjectKeyManager:
    """Manages per-project encryption keys.

    Each project gets a random 256-bit key, wrapped by the Master Key.
    The wrapped key is stored in project.json under the "encryption" field.
    """

    def __init__(self, master_key_manager: MasterKeyManager):
        self._mkm = master_key_manager
        self._cache: Dict[str, bytes] = {}
        self._lock = threading.Lock()

    def create_project_key(
        self, project_id: str, method: str = "standard"
    ) -> Tuple[bytes, dict]:
        """Generate a new project key and wrap it with the Master Key.

        Returns (raw_project_key, encryption_metadata_dict).
        The metadata dict should be stored in project.json["encryption"].
        """
        master_key = self._mkm.get_cached()
        if master_key is None:
            raise RuntimeError("Master Key not loaded — admin must authenticate first")

        key_length = 16 if method == "light" else 32
        project_key = generate_key(key_length)

        # Pad to 16 bytes minimum for AES Key Wrap if needed (AES-128 key is 16B, OK)
        wrapped = wrap_key(master_key, project_key)

        meta = {
            "enabled": True,
            "key_id": base64.b16encode(os.urandom(8)).decode().lower(),
            "wrapped_key": base64.b64encode(wrapped).decode(),
            "method": method,
            "key_length": key_length,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "version": 1,
        }

        with self._lock:
            self._cache[project_id] = project_key

        return project_key, meta

    def load_project_key(self, project_id: str, encryption_meta: dict) -> bytes:
        """Load a project key from its encryption metadata.

        Uses cache if available, otherwise unwraps using Master Key.
        """
        with self._lock:
            if project_id in self._cache:
                return self._cache[project_id]

        master_key = self._mkm.get_cached()
        if master_key is None:
            raise RuntimeError("Master Key not loaded — admin must authenticate first")

        wrapped = base64.b64decode(encryption_meta["wrapped_key"])
        project_key = unwrap_key(master_key, wrapped)

        with self._lock:
            self._cache[project_id] = project_key

        return project_key

    def rewrap_project_key(
        self,
        project_id: str,
        encryption_meta: dict,
        new_master_key: Optional[bytes] = None,
    ) -> dict:
        """Re-wrap a project key with a (possibly new) master key.

        Returns updated encryption metadata dict.
        """
        # Load the raw project key first
        project_key = self.load_project_key(project_id, encryption_meta)

        mk = new_master_key or self._mkm.get_cached()
        if mk is None:
            raise RuntimeError("Master Key not available")

        wrapped = wrap_key(mk, project_key)

        updated = dict(encryption_meta)
        updated["wrapped_key"] = base64.b64encode(wrapped).decode()
        updated["rewrapped_at"] = datetime.now(timezone.utc).isoformat()

        return updated

    def clear_cache(self, project_id: Optional[str] = None) -> None:
        """Clear cached project key(s)."""
        with self._lock:
            if project_id:
                self._cache.pop(project_id, None)
            else:
                self._cache.clear()
