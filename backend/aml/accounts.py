"""Account identification module for AML analysis.

Extracts counterparty bank account numbers (IBAN/NRB) from transaction data,
identifies banks, classifies as own/third-party and Polish/foreign,
and computes per-account statistics (inflows, outflows).

Works similarly to cards.py — scans transaction text at analysis time.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any, Dict, List, Optional

from ._polish_banks import classify_account, extract_accounts_from_text


# ============================================================
# Own account detection keywords
# ============================================================

_OWN_ACCOUNT_KEYWORDS = [
    r"przelew\s+w[łl]asny",
    r"przelew\s+wewn[ęe]trzny",
    r"przelew\s+mi[ęe]dzy\s+rachunkami",
    r"przelew\s+na\s+rachunek\s+w[łl]asny",
    r"na\s+rachunek\s+w[łl]asny",
    r"z\s+rachunku\s+w[łl]asnego",
    r"own\s+transfer",
    r"rachunek\s+w[łl]asny",
    r"lokata",
    r"za[łl]o[żz]enie\s+lokaty",
    r"likwidacja\s+lokaty",
    r"konto\s+oszcz[ęe]dno[śs]ciowe",
    r"rachunek\s+oszcz[ęe]dno[śs]ciowy",
]

_OWN_ACCOUNT_RE = re.compile(
    "|".join(f"(?:{p})" for p in _OWN_ACCOUNT_KEYWORDS),
    re.IGNORECASE,
)


def detect_accounts(
    transactions: List[Dict[str, Any]],
    statement_account: str = "",
) -> List[Dict[str, Any]]:
    """Detect unique bank accounts and compute per-account statistics.

    Args:
        transactions: List of transaction dicts (from DB, must include
            raw_text, title, counterparty_raw, direction, amount, booking_date).
        statement_account: The statement owner's own account number (for detection).

    Returns:
        List of account info dicts, sorted by total volume descending:
        [
            {
                "account_number": "12345678901234567890123456",
                "account_display": "12 3456 7890 1234 5678 9012 3456",
                "country_code": "PL",
                "country_name": "Polska",
                "is_polish": True,
                "is_foreign": False,
                "bank_short": "ING",
                "bank_full": "ING Bank Śląski",
                "sort_code": "10501012",
                "is_own_account": True,
                "ownership": "own" | "third_party" | "unknown",
                "tx_count": 15,
                "total_credit": 50000.00,
                "total_debit": 12000.00,
                "credit_count": 8,
                "debit_count": 7,
                "first_date": "2025-01-05",
                "last_date": "2025-06-28",
                "top_counterparties": [("JAN KOWALSKI", 3), ...],
            },
            ...
        ]
    """
    # Normalize statement's own account
    own_account_norm = _normalize_account(statement_account)

    # Map: normalized account → list of (tx, direction relative to this account)
    account_txs: Dict[str, List[Dict]] = defaultdict(list)

    for tx in transactions:
        raw_text = tx.get("raw_text") or ""
        counterparty = tx.get("counterparty_raw") or ""
        title = tx.get("title") or ""
        search_text = f"{counterparty}\n{title}\n{raw_text}"

        # Extract all account numbers from this transaction
        found_accounts = extract_accounts_from_text(search_text)

        for acc in found_accounts:
            norm = _normalize_account(acc)
            if not norm:
                continue
            # Skip the statement's own account when it appears in own transactions
            # (we still want to track it if it's a counterparty account)
            if norm == own_account_norm:
                # This is the owner's own account appearing as counterparty
                # It might be an "own transfer" — still track it
                pass
            account_txs[norm].append(tx)

    if not account_txs:
        return []

    # Build per-account statistics
    accounts = []
    for account_num, txs in account_txs.items():
        info = _build_account_stats(
            account_num, txs, own_account_norm,
        )
        accounts.append(info)

    # Sort by total volume (credit + debit), descending
    accounts.sort(key=lambda a: -(a["total_credit"] + a["total_debit"]))

    return accounts


def _normalize_account(account: str) -> str:
    """Normalize account number: remove spaces, dashes, PL prefix."""
    if not account:
        return ""
    clean = re.sub(r"[\s\-]", "", account).upper()
    if clean.startswith("PL"):
        clean = clean[2:]
    # Must be at least 15 digits for IBAN, 26 for Polish
    if len(clean) < 15:
        return ""
    return clean


def _is_own_account_tx(tx: Dict[str, Any]) -> bool:
    """Check if transaction text suggests an own-account transfer."""
    raw = tx.get("raw_text") or ""
    title = tx.get("title") or ""
    cp = tx.get("counterparty_raw") or ""
    channel = tx.get("channel") or ""
    category = tx.get("category") or ""

    search = f"{title} {cp} {raw}"

    # Channel/category hints
    if category == "own_transfer":
        return True
    if channel == "OWN_TRANSFER":
        return True

    # Keyword matching
    if _OWN_ACCOUNT_RE.search(search):
        return True

    return False


def _build_account_stats(
    account_num: str,
    txs: List[Dict],
    own_account_norm: str,
) -> Dict[str, Any]:
    """Build statistics for a single account."""

    # Classify the account
    classification = classify_account(account_num)

    total_credit = 0.0
    total_debit = 0.0
    credit_count = 0
    debit_count = 0
    dates = []
    counterparty_counts: Dict[str, int] = defaultdict(int)
    own_tx_count = 0

    for tx in txs:
        amt = abs(float(tx.get("amount") or 0))
        direction = (tx.get("direction") or "").upper()
        date = tx.get("booking_date") or ""

        if direction == "CREDIT":
            total_credit += amt
            credit_count += 1
        else:
            total_debit += amt
            debit_count += 1

        if date:
            dates.append(date)

        # Track counterparty names
        cp = (tx.get("counterparty_raw") or "")[:60]
        if cp:
            counterparty_counts[cp] += 1

        # Check for own-account indicators
        if _is_own_account_tx(tx):
            own_tx_count += 1

    dates.sort()
    tx_count = len(txs)

    # Determine ownership
    is_own = False
    if account_num == own_account_norm:
        is_own = True
    elif own_tx_count > 0 and own_tx_count >= tx_count * 0.5:
        # More than half of transactions on this account are "own transfers"
        is_own = True

    if is_own:
        ownership = "own"
    else:
        ownership = "third_party"

    # Top counterparties (by frequency)
    top_cp = sorted(counterparty_counts.items(), key=lambda x: -x[1])[:5]

    return {
        "account_number": account_num,
        "account_display": classification["display"],
        "country_code": classification["country_code"],
        "country_name": classification["country_name"],
        "is_polish": classification["is_polish"],
        "is_foreign": classification["is_foreign"],
        "bank_short": classification["bank_short"],
        "bank_full": classification["bank_full"],
        "sort_code": classification["sort_code"],
        "is_own_account": is_own,
        "ownership": ownership,
        "tx_count": tx_count,
        "total_credit": round(total_credit, 2),
        "total_debit": round(total_debit, 2),
        "credit_count": credit_count,
        "debit_count": debit_count,
        "first_date": dates[0] if dates else "",
        "last_date": dates[-1] if dates else "",
        "top_counterparties": top_cp,
    }
