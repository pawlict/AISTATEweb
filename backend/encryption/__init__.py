"""
backend.encryption — Project encryption module for AISTATEweb.

Provides AES-GCM / ChaCha20-Poly1305 encryption, key management,
streaming file encryption, and dual-control recovery.
"""
from __future__ import annotations

from .primitives import (
    derive_key,
    encrypt_block,
    decrypt_block,
    wrap_key,
    unwrap_key,
)
from .keys import MasterKeyManager, ProjectKeyManager
from .stream import encrypt_file, decrypt_file, EncryptedFileWriter, EncryptedFileReader
from .recovery import RecoveryTokenManager
from .project_io import ProjectIO, project_read_text, project_write_text

__all__ = [
    "derive_key",
    "encrypt_block",
    "decrypt_block",
    "wrap_key",
    "unwrap_key",
    "MasterKeyManager",
    "ProjectKeyManager",
    "encrypt_file",
    "decrypt_file",
    "EncryptedFileWriter",
    "EncryptedFileReader",
    "RecoveryTokenManager",
    "ProjectIO",
    "project_read_text",
    "project_write_text",
]
