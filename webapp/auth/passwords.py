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


# ---------------------------------------------------------------------------
# Password strength validation
# ---------------------------------------------------------------------------

# Top common passwords (always rejected regardless of policy)
_COMMON_PASSWORDS = frozenset([
    "password", "123456", "12345678", "qwerty", "abc123", "monkey", "1234567",
    "letmein", "trustno1", "dragon", "baseball", "iloveyou", "master", "sunshine",
    "ashley", "bailey", "shadow", "123123", "654321", "superman", "qazwsx",
    "michael", "football", "password1", "password123", "welcome", "jesus",
    "ninja", "mustang", "password2", "amanda", "login", "admin", "princess",
    "starwars", "solo", "passw0rd", "hello", "charlie", "donald", "loveme",
    "zaq1zaq1", "qwerty123", "aa123456", "access", "flower", "696969",
    "hottie", "biteme", "222222", "ginger", "hunter", "hunter2",
    "abcdef", "qweasd", "1q2w3e", "1qaz2wsx", "zxcvbnm", "121212",
    "000000", "11111111", "asdf1234", "secret", "test", "azerty",
    "haslo", "haslo123", "zaq12wsx", "mojehaslo", "polska", "polska1",
])

import re as _re


def validate_password_strength(password: str, policy: str) -> str | None:
    """Validate password against the given policy level.

    Returns None if the password is acceptable, or an error message string.
    Policies:
        none   — only blacklist check (no min length enforced here)
        basic  — min 8 chars
        medium — min 8 chars + lowercase + uppercase + digit
        strong — min 12 chars + lowercase + uppercase + digit + special char
    """
    lower = password.lower()
    if lower in _COMMON_PASSWORDS:
        return "Password is too common"

    if policy == "none":
        return None

    if policy == "basic":
        if len(password) < 8:
            return "Password must be at least 8 characters"
        return None

    if policy == "medium":
        if len(password) < 8:
            return "Password must be at least 8 characters"
        if not _re.search(r"[a-z]", password):
            return "Password must contain a lowercase letter"
        if not _re.search(r"[A-Z]", password):
            return "Password must contain an uppercase letter"
        if not _re.search(r"\d", password):
            return "Password must contain a digit"
        return None

    # strong (default fallback)
    if len(password) < 12:
        return "Password must be at least 12 characters"
    if not _re.search(r"[a-z]", password):
        return "Password must contain a lowercase letter"
    if not _re.search(r"[A-Z]", password):
        return "Password must contain an uppercase letter"
    if not _re.search(r"\d", password):
        return "Password must contain a digit"
    if not _re.search(r"[^a-zA-Z0-9]", password):
        return "Password must contain a special character"
    return None
