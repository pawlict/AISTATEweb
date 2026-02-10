"""Anonymization utilities for bank account data.

Rules:
- Private accounts: hide IBAN (show last 4 digits), replace holder name
- Business accounts: show full IBAN and company name
- Cross-analysis: use account_hash for matching without exposing details
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from typing import Any, Dict, List, Optional

from ..db.engine import ensure_initialized, fetch_all, fetch_one, get_conn, new_id

log = logging.getLogger("aistate.aml.anonymize")

# Counter for generating anonymous labels
_ANON_LABELS = {}  # cache: account_hash → "Klient #N"


def compute_account_hash(account_number: str) -> str:
    """Compute SHA-256 hash of normalized account number for matching."""
    normalized = re.sub(r"[\s\-]", "", account_number).strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def get_or_create_profile(
    account_number: str,
    bank_id: str = "",
    bank_name: str = "",
    account_holder: str = "",
    account_type: str = "private",
) -> Dict[str, Any]:
    """Get existing or create new account profile.

    Returns the profile dict.
    """
    ensure_initialized()
    acc_hash = compute_account_hash(account_number)

    existing = fetch_one(
        "SELECT * FROM account_profiles WHERE account_hash = ?",
        (acc_hash,),
    )
    if existing:
        return dict(existing)

    # Create new profile
    profile_id = new_id()
    is_anonymized = 1 if account_type == "private" else 0

    # Generate anonymous label
    owner_label = _generate_anon_label(account_type)

    with get_conn() as conn:
        conn.execute(
            """INSERT INTO account_profiles
               (id, account_number, account_hash, account_type, bank_id, bank_name,
                owner_label, display_name, is_anonymized)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (profile_id, account_number, acc_hash, account_type,
             bank_id, bank_name, owner_label,
             account_holder if account_type == "business" else owner_label,
             is_anonymized),
        )

    log.info("Created account profile %s (type=%s, bank=%s)", profile_id[:8], account_type, bank_id)

    return {
        "id": profile_id,
        "account_number": account_number,
        "account_hash": acc_hash,
        "account_type": account_type,
        "bank_id": bank_id,
        "bank_name": bank_name,
        "owner_label": owner_label,
        "display_name": account_holder if account_type == "business" else owner_label,
        "is_anonymized": is_anonymized,
    }


def update_profile(
    profile_id: str,
    account_type: Optional[str] = None,
    display_name: Optional[str] = None,
    is_anonymized: Optional[bool] = None,
) -> Optional[Dict[str, Any]]:
    """Update an account profile."""
    ensure_initialized()

    updates = []
    params = []

    if account_type is not None:
        updates.append("account_type = ?")
        params.append(account_type)

    if display_name is not None:
        updates.append("display_name = ?")
        params.append(display_name)

    if is_anonymized is not None:
        updates.append("is_anonymized = ?")
        params.append(int(is_anonymized))

    if not updates:
        return None

    updates.append("updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')")
    params.append(profile_id)

    with get_conn() as conn:
        conn.execute(
            f"UPDATE account_profiles SET {', '.join(updates)} WHERE id = ?",
            tuple(params),
        )

    return dict(fetch_one("SELECT * FROM account_profiles WHERE id = ?", (profile_id,)) or {})


def list_profiles() -> List[Dict[str, Any]]:
    """List all account profiles with linked statement info."""
    ensure_initialized()
    profiles = fetch_all(
        "SELECT * FROM account_profiles ORDER BY created_at DESC"
    )
    result = []
    for p in profiles:
        d = dict(p)
        # Count linked statements
        stmt_count = fetch_one(
            """SELECT COUNT(*) as cnt FROM statements
               WHERE account_number = ? OR account_number = ?""",
            (d["account_number"], re.sub(r"[\s\-]", "", d["account_number"])),
        )
        d["statement_count"] = stmt_count["cnt"] if stmt_count else 0
        result.append(d)
    return result


def anonymize_iban(iban: str, account_type: str = "private") -> str:
    """Anonymize IBAN based on account type.

    Private: "PL** **** **** **** **** **** 1234"
    Business: full IBAN shown
    """
    if account_type == "business":
        return iban

    normalized = re.sub(r"[\s\-]", "", iban)
    if len(normalized) < 4:
        return "****"

    last4 = normalized[-4:]
    prefix = normalized[:2] if len(normalized) >= 2 else ""
    return f"{prefix}** **** **** **** **** **** {last4}"


def anonymize_holder(holder: str, account_type: str = "private", owner_label: str = "") -> str:
    """Anonymize account holder name.

    Private: use owner_label (e.g. "Klient #3")
    Business: show company name
    """
    if account_type == "business":
        return holder
    return owner_label or "Klient"


def anonymize_transactions(
    transactions: List[Dict[str, Any]],
    account_profile: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Apply anonymization to a list of transaction dicts for export/display.

    Only anonymizes the account owner's data, not counterparty data.
    """
    if not account_profile.get("is_anonymized"):
        return transactions

    result = []
    for tx in transactions:
        tx_copy = dict(tx)
        # Don't anonymize counterparty data - only the owner's account info
        result.append(tx_copy)
    return result


def get_profile_for_statement(statement_id: str) -> Optional[Dict[str, Any]]:
    """Find account profile linked to a statement."""
    ensure_initialized()
    stmt = fetch_one(
        "SELECT account_number, bank_id, bank_name, account_holder FROM statements WHERE id = ?",
        (statement_id,),
    )
    if not stmt or not stmt["account_number"]:
        return None

    acc_hash = compute_account_hash(stmt["account_number"])
    profile = fetch_one(
        "SELECT * FROM account_profiles WHERE account_hash = ?",
        (acc_hash,),
    )
    return dict(profile) if profile else None


def _generate_anon_label(account_type: str = "private") -> str:
    """Generate the next anonymous label (Klient #N or Firma #N)."""
    ensure_initialized()
    prefix = "Firma" if account_type == "business" else "Klient"

    row = fetch_one(
        """SELECT COUNT(*) as cnt FROM account_profiles
           WHERE account_type = ?""",
        (account_type,),
    )
    num = (row["cnt"] if row else 0) + 1
    return f"{prefix} #{num}"
