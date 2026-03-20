"""
Dual-control recovery mechanism for encrypted projects.

Recovery flow:
  1. Admin generates a one-time recovery token (valid 24h)
  2. User provides: token + recovery phrase + new password
  3. System re-wraps project keys under the new password

For Scenario 3 (lost password + lost phrase):
  Admin uses Master Key → system decrypts project keys →
  generates new recovery phrase → user sets new password.
"""
from __future__ import annotations

import json
import os
import base64
import hashlib
import hmac
import secrets
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, Dict, List, Tuple

TOKEN_TTL_HOURS = 24
TOKEN_LENGTH = 32  # bytes → 43 chars in urlsafe base64


class RecoveryTokenManager:
    """Manages one-time recovery tokens for encrypted project access."""

    def __init__(self, config_dir: Path):
        self._config_dir = Path(config_dir)
        self._tokens_file = self._config_dir / "recovery_tokens.json"

    def _load_tokens(self) -> List[dict]:
        if not self._tokens_file.exists():
            return []
        try:
            return json.loads(self._tokens_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []

    def _save_tokens(self, tokens: List[dict]) -> None:
        self._config_dir.mkdir(parents=True, exist_ok=True)
        tmp = self._tokens_file.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(tokens, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        tmp.replace(self._tokens_file)

    def _purge_expired(self, tokens: List[dict]) -> List[dict]:
        now = datetime.now(timezone.utc)
        return [
            t for t in tokens
            if datetime.fromisoformat(t["expires_at"]) > now and not t.get("used")
        ]

    def generate_token(
        self,
        admin_id: str,
        target_user_id: str,
        ttl_hours: int = TOKEN_TTL_HOURS,
    ) -> Tuple[str, dict]:
        """Generate a one-time recovery token.

        Returns (token_plaintext, token_record).
        """
        token = secrets.token_urlsafe(TOKEN_LENGTH)
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        now = datetime.now(timezone.utc)
        expires = now + timedelta(hours=ttl_hours)

        record = {
            "token_hash": token_hash,
            "admin_id": admin_id,
            "target_user_id": target_user_id,
            "created_at": now.isoformat(),
            "expires_at": expires.isoformat(),
            "used": False,
        }

        tokens = self._load_tokens()
        tokens = self._purge_expired(tokens)
        tokens.append(record)
        self._save_tokens(tokens)

        return token, record

    def validate_token(self, token: str, target_user_id: str) -> Optional[dict]:
        """Validate a recovery token.

        Returns the token record if valid, None otherwise.
        """
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        tokens = self._load_tokens()
        now = datetime.now(timezone.utc)

        for t in tokens:
            if (
                hmac.compare_digest(t["token_hash"], token_hash)
                and t["target_user_id"] == target_user_id
                and not t.get("used")
                and datetime.fromisoformat(t["expires_at"]) > now
            ):
                return t
        return None

    def invalidate_token(self, token: str) -> bool:
        """Mark a token as used (one-time use)."""
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        tokens = self._load_tokens()
        found = False

        for t in tokens:
            if hmac.compare_digest(t["token_hash"], token_hash):
                t["used"] = True
                t["used_at"] = datetime.now(timezone.utc).isoformat()
                found = True
                break

        if found:
            self._save_tokens(tokens)
        return found

    def list_active_tokens(self, admin_id: Optional[str] = None) -> List[dict]:
        """List active (unused, non-expired) tokens."""
        tokens = self._load_tokens()
        tokens = self._purge_expired(tokens)
        if admin_id:
            tokens = [t for t in tokens if t["admin_id"] == admin_id]
        # Strip token_hash for security — only return metadata
        return [
            {k: v for k, v in t.items() if k != "token_hash"}
            for t in tokens
        ]
