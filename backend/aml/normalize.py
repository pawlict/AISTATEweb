"""Transaction normalization and entity resolution.

Converts RawTransaction from bank parsers into NormalizedTransaction
with consistent fields, deduplication, and counterparty entity linking.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Tuple

from ..finance.parsers.base import RawTransaction, StatementInfo


@dataclass
class NormalizedTransaction:
    """Fully normalized transaction ready for rules engine."""

    id: str = ""
    statement_id: str = ""
    booking_date: str = ""        # YYYY-MM-DD
    tx_date: str = ""             # YYYY-MM-DD (data waluty)
    amount: Decimal = Decimal("0")
    currency: str = "PLN"
    direction: str = ""           # CREDIT | DEBIT
    balance_after: Optional[Decimal] = None
    # Counterparty
    counterparty_raw: str = ""
    counterparty_clean: str = ""  # normalized for matching
    counterparty_id: str = ""     # linked entity ID
    # Content
    title: str = ""
    title_clean: str = ""         # normalized
    bank_category: str = ""       # TR.KART, ST.ZLEC, P.BLIK, etc.
    raw_text: str = ""
    # Classification (filled by rules engine)
    channel: str = ""             # CARD | TRANSFER | BLIK_P2P | BLIK_MERCHANT | CASH | FEE | OTHER
    category: str = ""
    subcategory: str = ""
    risk_tags: List[str] = field(default_factory=list)
    risk_score: float = 0.0
    rule_explains: List[Dict[str, str]] = field(default_factory=list)
    # Flags
    is_recurring: bool = False
    recurring_group: str = ""
    urls: List[str] = field(default_factory=list)
    # Dedup
    tx_hash: str = ""

    def to_db_dict(self) -> Dict[str, Any]:
        """Convert to dict for SQL INSERT."""
        import json
        return {
            "id": self.id,
            "statement_id": self.statement_id,
            "booking_date": self.booking_date,
            "tx_date": self.tx_date,
            "amount": str(self.amount),
            "currency": self.currency,
            "direction": self.direction,
            "balance_after": str(self.balance_after) if self.balance_after is not None else None,
            "counterparty_raw": self.counterparty_raw,
            "counterparty_id": self.counterparty_id,
            "title": self.title,
            "bank_category": self.bank_category,
            "raw_text": self.raw_text[:500],
            "channel": self.channel,
            "category": self.category,
            "subcategory": self.subcategory,
            "risk_tags": json.dumps(self.risk_tags, ensure_ascii=False),
            "risk_score": self.risk_score,
            "rule_explains": json.dumps(self.rule_explains, ensure_ascii=False),
            "is_recurring": int(self.is_recurring),
            "recurring_group": self.recurring_group,
            "tx_hash": self.tx_hash,
        }


def clean_text(text: str) -> str:
    """Normalize text: uppercase, collapse whitespace, strip."""
    if not text:
        return ""
    s = text.upper().strip()
    s = re.sub(r"\s+", " ", s)
    return s


def strip_diacritics(text: str) -> str:
    """Remove Polish diacritics for fuzzy matching."""
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def to_decimal(value: float) -> Decimal:
    """Convert float to Decimal with 2 decimal places."""
    try:
        return Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return Decimal("0.00")


def compute_tx_hash(date: str, amount: str, counterparty: str, title: str) -> str:
    """Compute dedup hash for a transaction."""
    key = f"{date}|{amount}|{counterparty[:50]}|{title[:100]}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


_URL_RE = re.compile(r"https?://[^\s,;\"'<>]+", re.I)


def extract_urls(text: str) -> List[str]:
    """Extract all URLs from transaction text."""
    return _URL_RE.findall(text)


def detect_channel(bank_category: str, title: str, counterparty: str) -> str:
    """Detect transaction channel from bank code and text."""
    bc = bank_category.upper()

    # Direct bank codes (ING-specific)
    channel_map = {
        "TR.KART": "CARD",
        "PRZELEW": "TRANSFER",
        "P.BLIK": "BLIK_P2P",  # refined below
        "TR.BLIK": "BLIK_MERCHANT",
        "ST.ZLEC": "TRANSFER",
        "OPŁATA": "FEE",
        "OPLATA": "FEE",
        "PROWIZJA": "FEE",
        "ODSETKI": "FEE",
    }

    for code, channel in channel_map.items():
        if code in bc:
            # Refine BLIK: P2P vs merchant
            if channel == "BLIK_P2P":
                text = f"{title} {counterparty}".lower()
                if re.search(r"przelew\s*(na|z)\s*telefon", text):
                    return "BLIK_P2P"
                return "BLIK_MERCHANT"
            return channel

    # Text-based detection
    text = f"{title} {counterparty}".lower()

    if re.search(r"blik", text):
        if re.search(r"przelew\s*(na|z)\s*telefon", text):
            return "BLIK_P2P"
        return "BLIK_MERCHANT"

    if re.search(r"kart[aąy]|card|visa|mastercard|maestro", text):
        return "CARD"

    if re.search(r"bankomat|atm|wyp[łl]ata\s*got[oó]wk|wp[łl]ata\s*got[oó]wk", text):
        return "CASH"

    if re.search(r"zwrot|refund|korekta", text):
        return "REFUND"

    if re.search(r"op[łl]ata|prowizja|odsetki|fee|commission", text):
        return "FEE"

    if re.search(r"przelew|transfer|zleceni", text):
        return "TRANSFER"

    return "OTHER"


def normalize_transactions(
    raw_transactions: List[RawTransaction],
    statement_id: str = "",
) -> List[NormalizedTransaction]:
    """Convert raw parser output to normalized transactions.

    Args:
        raw_transactions: From bank parser
        statement_id: Reference to statement record

    Returns:
        List of NormalizedTransaction with hashes, channels, cleaned text.
    """
    from ..db.engine import new_id

    results: List[NormalizedTransaction] = []
    seen_hashes: set = set()

    for raw in raw_transactions:
        amount = to_decimal(raw.amount)
        direction = "CREDIT" if raw.amount >= 0 else "DEBIT"

        cp_clean = clean_text(raw.counterparty)
        title_clean = clean_text(raw.title)

        tx_hash = compute_tx_hash(
            raw.date, str(amount), cp_clean, title_clean,
        )

        # Dedup
        if tx_hash in seen_hashes:
            continue
        seen_hashes.add(tx_hash)

        channel = detect_channel(raw.bank_category, raw.title, raw.counterparty)
        urls = extract_urls(f"{raw.counterparty} {raw.title} {raw.raw_text}")

        balance = to_decimal(raw.balance_after) if raw.balance_after is not None else None

        ntx = NormalizedTransaction(
            id=new_id(),
            statement_id=statement_id,
            booking_date=raw.date or "",
            tx_date=raw.date_valuation or raw.date or "",
            amount=amount,
            currency=raw.currency,
            direction=direction,
            balance_after=balance,
            counterparty_raw=raw.counterparty,
            counterparty_clean=cp_clean,
            title=raw.title,
            title_clean=title_clean,
            bank_category=raw.bank_category,
            raw_text=raw.raw_text,
            channel=channel,
            urls=urls,
            tx_hash=tx_hash,
        )
        results.append(ntx)

    return results
