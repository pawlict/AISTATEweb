from __future__ import annotations

import hashlib
import hmac
import os
import secrets


def _pbkdf2_hash(password: str, salt: bytes | None = None, iterations: int = 260_000) -> str:
    """Hash a password using PBKDF2-HMAC-SHA256 (stdlib, no external deps).

    Returns a string in the format: pbkdf2:iterations:hex_salt:hex_hash
    """
    if salt is None:
        salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations, dklen=32)
    return f"pbkdf2:{iterations}:{salt.hex()}:{dk.hex()}"


def hash_password(password: str) -> str:
    """Create a secure password hash."""
    return _pbkdf2_hash(password)


def verify_password(password: str, stored_hash: str) -> bool:
    """Verify a password against a stored hash."""
    try:
        parts = stored_hash.split(":")
        if parts[0] == "pbkdf2" and len(parts) == 4:
            iterations = int(parts[1])
            salt = bytes.fromhex(parts[2])
            expected = _pbkdf2_hash(password, salt=salt, iterations=iterations)
            return hmac.compare_digest(expected, stored_hash)
    except Exception:
        pass
    return False


def generate_token() -> str:
    """Generate a cryptographically secure session token."""
    return secrets.token_urlsafe(32)
