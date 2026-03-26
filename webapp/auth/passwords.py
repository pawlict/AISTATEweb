from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import threading
from pathlib import Path


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

# Top common passwords — loaded from text file (admin-editable).
# File path: webapp/auth/builtin_passwords.txt
_BUILTIN_FILE = Path(__file__).with_name("builtin_passwords.txt")


def _load_builtin_passwords() -> frozenset[str]:
    """Load built-in password list from text file next to this module."""
    passwords: set[str] = set()
    if _BUILTIN_FILE.exists():
        for line in _BUILTIN_FILE.read_text("utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                passwords.add(line.lower())
    return frozenset(passwords)


_COMMON_PASSWORDS: frozenset[str] = _load_builtin_passwords()

import re as _re


# ---------------------------------------------------------------------------
# Custom password blacklist (admin-managed, persisted to JSON)
# ---------------------------------------------------------------------------

class PasswordBlacklist:
    """Manages a custom password blacklist stored as a JSON file.

    The built-in ``_COMMON_PASSWORDS`` frozenset is always checked.
    This class adds an admin-editable layer on top.
    """

    def __init__(self, config_dir: Path) -> None:
        self._path = config_dir / "password_blacklist.json"
        self._lock = threading.Lock()
        self._custom: set[str] = set()
        self._load()

    def _load(self) -> None:
        if self._path.exists():
            try:
                data = json.loads(self._path.read_text("utf-8"))
                if isinstance(data, list):
                    self._custom = {s.lower().strip() for s in data if isinstance(s, str) and s.strip()}
            except Exception:
                self._custom = set()

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(sorted(self._custom), ensure_ascii=False, indent=2), "utf-8")

    def is_blacklisted(self, password: str) -> bool:
        lower = password.lower()
        if lower in _COMMON_PASSWORDS:
            return True
        with self._lock:
            return lower in self._custom

    def get_all(self) -> dict:
        """Return both built-in and custom lists."""
        with self._lock:
            return {
                "builtin": sorted(_COMMON_PASSWORDS),
                "custom": sorted(self._custom),
            }

    @staticmethod
    def reload_builtin() -> int:
        """Re-read builtin_passwords.txt. Returns new count."""
        global _COMMON_PASSWORDS
        _COMMON_PASSWORDS = _load_builtin_passwords()
        return len(_COMMON_PASSWORDS)

    def add(self, password: str) -> bool:
        """Add a password to the custom blacklist. Returns True if added."""
        lower = password.lower().strip()
        if not lower:
            return False
        with self._lock:
            if lower in self._custom:
                return False
            self._custom.add(lower)
            self._save()
            return True

    def remove(self, password: str) -> bool:
        """Remove a password from the custom blacklist. Returns True if removed."""
        lower = password.lower().strip()
        with self._lock:
            if lower not in self._custom:
                return False
            self._custom.discard(lower)
            self._save()
            return True

    def add_bulk(self, passwords: list[str]) -> int:
        """Add multiple passwords. Returns count of newly added."""
        added = 0
        with self._lock:
            for p in passwords:
                lower = p.lower().strip()
                if lower and lower not in self._custom:
                    self._custom.add(lower)
                    added += 1
            if added:
                self._save()
        return added


# Module-level instance (set via init_blacklist())
_blacklist: PasswordBlacklist | None = None


def init_blacklist(config_dir: Path) -> PasswordBlacklist:
    """Initialise the global blacklist instance. Call once at startup."""
    global _blacklist
    _blacklist = PasswordBlacklist(config_dir)
    return _blacklist


def get_blacklist() -> PasswordBlacklist | None:
    return _blacklist


def validate_password_strength(password: str, policy: str) -> str | None:
    """Validate password against the given policy level.

    Returns None if the password is acceptable, or an error message string.
    Policies:
        none   — only blacklist check (no min length enforced here)
        basic  — min 8 chars
        medium — min 8 chars + lowercase + uppercase + digit
        strong — min 12 chars + lowercase + uppercase + digit + special char
    """
    # Check both built-in and custom blacklist
    if _blacklist is not None:
        if _blacklist.is_blacklisted(password):
            return "Password is too common"
    else:
        if password.lower() in _COMMON_PASSWORDS:
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
