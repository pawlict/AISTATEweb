"""
Transparent I/O layer for encrypted projects.

Provides helper functions that check whether a project is encrypted
and route reads/writes through the encryption layer automatically.
project.json itself is always plaintext (it holds the wrapped key).
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Optional, Union, BinaryIO

from .keys import MasterKeyManager, ProjectKeyManager
from .stream import (
    EncryptedFileWriter,
    EncryptedFileReader,
    encrypt_file,
    decrypt_file,
)
from .primitives import encrypt_block, decrypt_block

# ── Module-level singletons (set by init_encryption()) ────────────────
_master_key_mgr: Optional[MasterKeyManager] = None
_project_key_mgr: Optional[ProjectKeyManager] = None
_lock = threading.Lock()


def init_encryption(config_dir: Path) -> tuple:
    """Initialize the encryption subsystem. Called once at server startup.

    Returns (MasterKeyManager, ProjectKeyManager).
    """
    global _master_key_mgr, _project_key_mgr
    with _lock:
        if _master_key_mgr is None:
            _master_key_mgr = MasterKeyManager(config_dir)
            _project_key_mgr = ProjectKeyManager(_master_key_mgr)
    return _master_key_mgr, _project_key_mgr


def get_managers() -> tuple:
    """Return the initialized (MasterKeyManager, ProjectKeyManager) or raise."""
    if _master_key_mgr is None:
        raise RuntimeError("Encryption not initialized — call init_encryption() first")
    return _master_key_mgr, _project_key_mgr


class ProjectIO:
    """Transparent read/write for a single project's files.

    Usage:
        pio = ProjectIO(project_dir)
        if pio.is_encrypted:
            text = pio.read_text(some_file)
        else:
            text = some_file.read_text()
    """

    def __init__(self, project_dir: Path):
        self._dir = Path(project_dir)
        self._meta: Optional[dict] = None
        self._enc_meta: Optional[dict] = None
        self._project_key: Optional[bytes] = None
        self._load_meta()

    def _load_meta(self) -> None:
        meta_path = self._dir / "project.json"
        if meta_path.exists():
            try:
                self._meta = json.loads(meta_path.read_text(encoding="utf-8"))
                self._enc_meta = self._meta.get("encryption")
            except (json.JSONDecodeError, OSError):
                self._meta = {}

    @property
    def is_encrypted(self) -> bool:
        return bool(self._enc_meta and self._enc_meta.get("enabled"))

    @property
    def method(self) -> str:
        if self._enc_meta:
            return self._enc_meta.get("method", "standard")
        return "standard"

    def _get_key(self) -> bytes:
        if self._project_key is not None:
            return self._project_key
        _, pkm = get_managers()
        project_id = self._meta.get("project_id", self._dir.name)
        self._project_key = pkm.load_project_key(project_id, self._enc_meta)
        return self._project_key

    # ── Text I/O ──────────────────────────────────────────────────────
    def read_text(self, path: Path, encoding: str = "utf-8") -> str:
        """Read and decrypt a text file."""
        if not self.is_encrypted:
            return path.read_text(encoding=encoding)
        encrypted = path.read_bytes()
        plaintext = decrypt_block(self._get_key(), encrypted, method=self.method)
        return plaintext.decode(encoding)

    def write_text(self, path: Path, content: str, encoding: str = "utf-8") -> None:
        """Encrypt and write a text file."""
        if not self.is_encrypted:
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_text(content, encoding=encoding)
            tmp.replace(path)
            return
        data = content.encode(encoding)
        encrypted = encrypt_block(self._get_key(), data, method=self.method)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_bytes(encrypted)
        tmp.replace(path)

    # ── Binary I/O ────────────────────────────────────────────────────
    def read_bytes(self, path: Path) -> bytes:
        """Read and decrypt a binary file (small files only)."""
        if not self.is_encrypted:
            return path.read_bytes()
        encrypted = path.read_bytes()
        return decrypt_block(self._get_key(), encrypted, method=self.method)

    def write_bytes(self, path: Path, data: bytes) -> None:
        """Encrypt and write a binary file (small files only)."""
        if not self.is_encrypted:
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_bytes(data)
            tmp.replace(path)
            return
        encrypted = encrypt_block(self._get_key(), data, method=self.method)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_bytes(encrypted)
        tmp.replace(path)

    # ── Streaming I/O (large files) ───────────────────────────────────
    def write_stream(self, path: Path, source: BinaryIO) -> int:
        """Encrypt from a stream and write to path. Returns total plaintext bytes."""
        if not self.is_encrypted:
            with open(path, "wb") as f:
                import shutil
                return _copy_stream(source, f)
        with EncryptedFileWriter(self._get_key(), path, self.method) as writer:
            return writer.write_from_stream(source)

    def read_stream_to_file(self, src_path: Path, dst_path: Path) -> None:
        """Decrypt a streamed file to a plaintext destination (for worker handoff)."""
        if not self.is_encrypted:
            import shutil
            shutil.copy2(src_path, dst_path)
            return
        decrypt_file(self._get_key(), src_path, dst_path)

    def encrypt_existing_file(self, path: Path) -> None:
        """Encrypt an existing plaintext file in-place."""
        if not self.is_encrypted:
            return
        tmp = path.with_suffix(path.suffix + ".enc.tmp")
        encrypt_file(self._get_key(), path, tmp, self.method)
        tmp.replace(path)

    def decrypt_to_temp(self, path: Path, temp_dir: Path) -> Path:
        """Decrypt a file to a temporary location. Returns temp file path."""
        if not self.is_encrypted:
            return path  # no decryption needed
        temp_path = temp_dir / path.name
        decrypt_file(self._get_key(), path, temp_path)
        return temp_path


def _copy_stream(src: BinaryIO, dst: BinaryIO, chunk_size: int = 65536) -> int:
    total = 0
    while True:
        chunk = src.read(chunk_size)
        if not chunk:
            break
        dst.write(chunk)
        total += len(chunk)
    return total


# ── Convenience functions ──────────────────────────────────────────────
def project_read_text(project_dir: Path, file_path: Path) -> str:
    """Read a text file from a project, decrypting if necessary."""
    pio = ProjectIO(project_dir)
    return pio.read_text(file_path)


def project_write_text(project_dir: Path, file_path: Path, content: str) -> None:
    """Write a text file to a project, encrypting if necessary."""
    pio = ProjectIO(project_dir)
    pio.write_text(file_path, content)
