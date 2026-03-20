"""
Low-level cryptographic primitives for project encryption.

Supports three encryption methods:
  - light:    AES-128-GCM  (PBKDF2 key derivation)
  - standard: AES-256-GCM  (Argon2id key derivation)
  - maximum:  AES-256-GCM + ChaCha20-Poly1305 double layer (Argon2id)
"""
from __future__ import annotations

import os
import struct
import hashlib
import hmac as _hmac
from typing import Optional, Tuple

from cryptography.hazmat.primitives.ciphers.aead import AESGCM, ChaCha20Poly1305
from cryptography.hazmat.primitives.keywrap import aes_key_wrap, aes_key_unwrap
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes

try:
    from argon2.low_level import hash_secret_raw, Type
    _HAS_ARGON2 = True
except ImportError:
    _HAS_ARGON2 = False

# ── Constants ──────────────────────────────────────────────────────────
NONCE_SIZE = 12          # bytes, standard for AES-GCM and ChaCha20
TAG_SIZE = 16            # bytes, GCM / Poly1305 tag
SALT_SIZE = 16           # bytes for KDF salt
PBKDF2_ITERATIONS = 310_000  # OWASP 2024 recommendation for SHA-256

# Argon2id parameters (OWASP recommendation)
ARGON2_TIME_COST = 3
ARGON2_MEMORY_COST = 65536   # 64 MiB
ARGON2_PARALLELISM = 4

# Method → key length mapping
_KEY_LENGTHS = {
    "light": 16,      # AES-128
    "standard": 32,   # AES-256
    "maximum": 32,    # AES-256 (first layer)
}


# ── Key Derivation ────────────────────────────────────────────────────
def derive_key(
    password: str,
    salt: bytes,
    method: str = "standard",
    *,
    key_length: Optional[int] = None,
) -> bytes:
    """Derive an encryption key from a password.

    For 'light' method: uses PBKDF2-HMAC-SHA256.
    For 'standard' / 'maximum': uses Argon2id if available, PBKDF2 fallback.

    Returns raw key bytes of appropriate length for the method.
    """
    length = key_length or _KEY_LENGTHS.get(method, 32)

    if method == "light":
        return _derive_pbkdf2(password, salt, length)

    # standard / maximum → prefer Argon2id
    if _HAS_ARGON2:
        return _derive_argon2id(password, salt, length)
    return _derive_pbkdf2(password, salt, length)


def _derive_pbkdf2(password: str, salt: bytes, length: int) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=length,
        salt=salt,
        iterations=PBKDF2_ITERATIONS,
    )
    return kdf.derive(password.encode("utf-8"))


def _derive_argon2id(password: str, salt: bytes, length: int) -> bytes:
    return hash_secret_raw(
        secret=password.encode("utf-8"),
        salt=salt,
        time_cost=ARGON2_TIME_COST,
        memory_cost=ARGON2_MEMORY_COST,
        parallelism=ARGON2_PARALLELISM,
        hash_len=length,
        type=Type.ID,
    )


def generate_salt() -> bytes:
    """Generate a random salt for key derivation."""
    return os.urandom(SALT_SIZE)


def has_argon2() -> bool:
    """Check if argon2-cffi is available."""
    return _HAS_ARGON2


# ── Symmetric Encryption ──────────────────────────────────────────────
def encrypt_block(
    key: bytes,
    plaintext: bytes,
    aad: Optional[bytes] = None,
    method: str = "standard",
) -> bytes:
    """Encrypt a block of data.

    Returns: nonce (12B) || ciphertext || tag (16B)

    For 'maximum' method: applies AES-256-GCM then ChaCha20-Poly1305.
    """
    if method == "maximum":
        # Layer 1: AES-256-GCM
        inner = _aes_gcm_encrypt(key, plaintext, aad)
        # Layer 2: ChaCha20-Poly1305 with same key (different nonce)
        return _chacha_encrypt(key, inner, aad)
    # light / standard: AES-GCM only
    return _aes_gcm_encrypt(key, plaintext, aad)


def decrypt_block(
    key: bytes,
    ciphertext: bytes,
    aad: Optional[bytes] = None,
    method: str = "standard",
) -> bytes:
    """Decrypt a block of data produced by encrypt_block()."""
    if method == "maximum":
        # Reverse order: unwrap ChaCha first, then AES-GCM
        inner = _chacha_decrypt(key, ciphertext, aad)
        return _aes_gcm_decrypt(key, inner, aad)
    return _aes_gcm_decrypt(key, ciphertext, aad)


def _aes_gcm_encrypt(key: bytes, plaintext: bytes, aad: Optional[bytes]) -> bytes:
    nonce = os.urandom(NONCE_SIZE)
    aesgcm = AESGCM(key)
    ct = aesgcm.encrypt(nonce, plaintext, aad)  # ct includes tag
    return nonce + ct


def _aes_gcm_decrypt(key: bytes, blob: bytes, aad: Optional[bytes]) -> bytes:
    nonce = blob[:NONCE_SIZE]
    ct = blob[NONCE_SIZE:]
    aesgcm = AESGCM(key)
    return aesgcm.decrypt(nonce, ct, aad)


def _chacha_encrypt(key: bytes, plaintext: bytes, aad: Optional[bytes]) -> bytes:
    nonce = os.urandom(NONCE_SIZE)
    chacha = ChaCha20Poly1305(key)
    ct = chacha.encrypt(nonce, plaintext, aad)
    return nonce + ct


def _chacha_decrypt(key: bytes, blob: bytes, aad: Optional[bytes]) -> bytes:
    nonce = blob[:NONCE_SIZE]
    ct = blob[NONCE_SIZE:]
    chacha = ChaCha20Poly1305(key)
    return chacha.decrypt(nonce, ct, aad)


# ── Key Wrapping (AES Key Wrap — RFC 3394) ─────────────────────────
def wrap_key(wrapping_key: bytes, key_to_wrap: bytes) -> bytes:
    """Wrap (encrypt) a key using AES Key Wrap (RFC 3394).

    wrapping_key must be 16, 24, or 32 bytes.
    key_to_wrap must be a multiple of 8 bytes and >= 16 bytes.
    """
    return aes_key_wrap(wrapping_key, key_to_wrap)


def unwrap_key(wrapping_key: bytes, wrapped_key: bytes) -> bytes:
    """Unwrap (decrypt) a key using AES Key Unwrap (RFC 3394)."""
    return aes_key_unwrap(wrapping_key, wrapped_key)


# ── Utility ────────────────────────────────────────────────────────────
def generate_key(length: int = 32) -> bytes:
    """Generate a cryptographically random key."""
    return os.urandom(length)


def constant_time_compare(a: bytes, b: bytes) -> bool:
    """Timing-safe comparison of two byte strings."""
    return _hmac.compare_digest(a, b)
