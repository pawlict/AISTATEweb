"""Recovery phrase generation and verification using BIP-39 English word list.

Generates 12-word mnemonic phrases for account recovery.
Stores PBKDF2 hash for verification and SHA256 hint for fast user lookup.
"""
from __future__ import annotations

import hashlib
import secrets
from pathlib import Path
from typing import Optional, Tuple

from webapp.auth.passwords import _pbkdf2_hash

# Load BIP-39 English word list (2048 words)
_WORDLIST_PATH = Path(__file__).with_name("bip39_english.txt")
_WORDLIST: list[str] = []


def _load_wordlist() -> list[str]:
    global _WORDLIST
    if _WORDLIST:
        return _WORDLIST
    if _WORDLIST_PATH.exists():
        words = []
        for line in _WORDLIST_PATH.read_text("utf-8").splitlines():
            w = line.strip()
            if w and not w.startswith("#"):
                words.append(w)
        _WORDLIST = words
    return _WORDLIST


def generate_phrase(word_count: int = 12) -> str:
    """Generate a random recovery phrase of `word_count` words from BIP-39 list.

    Returns a space-separated lowercase string of words.
    12 words from 2048 = ~132 bits of entropy.
    """
    words = _load_wordlist()
    if len(words) < 2048:
        raise RuntimeError(f"BIP-39 word list incomplete: {len(words)} words found, expected 2048")
    chosen = [secrets.choice(words) for _ in range(word_count)]
    return " ".join(chosen)


def _normalize_phrase(phrase: str) -> str:
    """Normalize a phrase for consistent hashing: lowercase, single spaces, stripped."""
    return " ".join(phrase.lower().split())


def compute_hint(phrase: str) -> str:
    """Compute a SHA256-based hint (first 16 hex chars) for fast user lookup.

    This allows finding the right user without iterating PBKDF2 over all users.
    With 64 bits of hint, collision probability is negligible for small user bases.
    """
    normalized = _normalize_phrase(phrase)
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return digest[:16]


def hash_phrase(phrase: str) -> str:
    """Hash a recovery phrase using PBKDF2-HMAC-SHA256 (same format as passwords).

    Returns the hash string in format: pbkdf2:iterations:hex_salt:hex_hash
    """
    normalized = _normalize_phrase(phrase)
    return _pbkdf2_hash(normalized)


def verify_phrase(phrase: str, stored_hash: str) -> bool:
    """Verify a recovery phrase against a stored PBKDF2 hash."""
    import hmac as _hmac

    normalized = _normalize_phrase(phrase)
    try:
        parts = stored_hash.split(":")
        if parts[0] == "pbkdf2" and len(parts) == 4:
            iterations = int(parts[1])
            salt = bytes.fromhex(parts[2])
            expected = _pbkdf2_hash(normalized, salt=salt, iterations=iterations)
            return _hmac.compare_digest(expected, stored_hash)
    except Exception:
        pass
    return False


def generate_and_hash() -> Tuple[str, str, str]:
    """Generate a new recovery phrase and return (plaintext, hash, hint).

    Returns:
        phrase: The 12-word plaintext phrase (show once, never store)
        phrase_hash: PBKDF2 hash to store in DB
        phrase_hint: SHA256 hint for fast lookup
    """
    phrase = generate_phrase()
    return phrase, hash_phrase(phrase), compute_hint(phrase)
