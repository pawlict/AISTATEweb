"""Card identification module for AML analysis.

Extracts debit/credit card numbers from transaction data and computes
per-card statistics (spending, categories, locations, patterns).
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any, Dict, List, Optional

# ============================================================
# Card number extraction patterns
# ============================================================

# "Nr karty 4246xx9674" or "Nr karty 4246**9674" or "Nr karty 4246XX9674"
_CARD_NR_RE = re.compile(
    r"(?:Nr\s+karty|nr\.?\s*karty|numer\s+karty|karta\s+nr)\s*[:\s]*"
    r"(\d{4}[\s-]?[xX*]{2,8}[\s-]?\d{2,4})",
    re.IGNORECASE,
)

# Shorter pattern: "*1234" or "xxxx1234" at end of counterparty/title
_CARD_SHORT_RE = re.compile(
    r"[*xX]{4}\s?(\d{4})\b"
)

# Full masked PAN in raw text: "4246xxxxxxxx9674" or "4246 **** **** 9674"
_CARD_FULL_RE = re.compile(
    r"(\d{4})\s?[xX*]{4,}\s?[xX*]{0,4}\s?(\d{4})"
)

# Card brand detection from text
_BRAND_PATTERNS = [
    (re.compile(r"\bvisa\b", re.I), "VISA"),
    (re.compile(r"\bmastercard\b", re.I), "Mastercard"),
    (re.compile(r"\bmaestro\b", re.I), "Maestro"),
    (re.compile(r"\bmc\b", re.I), "Mastercard"),
]

# Card brand from first digit (BIN)
_BIN_BRANDS = {
    "4": "VISA",
    "5": "Mastercard",
    "2": "Mastercard",  # 2221-2720 range
    "3": "Maestro",     # or AmEx (34/37)
    "6": "Maestro",
}


def detect_cards(transactions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Detect unique cards and compute per-card statistics.

    Args:
        transactions: List of transaction dicts (from DB, must include
            raw_text, title, counterparty_raw, channel, category, amount,
            direction, booking_date).

    Returns:
        List of card info dicts, sorted by total_amount descending:
        [
            {
                "card_id": "4246**9674",
                "card_masked": "4246 ** 9674",
                "first_four": "4246",
                "last_four": "9674",
                "brand": "VISA",
                "tx_count": 85,
                "total_debit": 12500.00,
                "total_credit": 200.00,
                "avg_amount": 147.06,
                "max_amount": 1200.00,
                "first_date": "2025-01-05",
                "last_date": "2025-12-28",
                "top_categories": [("grocery", 4500), ("fuel", 2800), ...],
                "top_merchants": [("BIEDRONKA", 3200, 24), ...],
                "locations": [("Łódź", 45), ("Warszawa", 3), ...],
                "monthly": {"2025-01": 1200, "2025-02": 980, ...},
            },
            ...
        ]
    """
    # Map: normalized card_id → list of transactions
    card_txs: Dict[str, List[Dict]] = defaultdict(list)
    # Map: card_id → raw masked representation
    card_raw: Dict[str, str] = {}

    for tx in transactions:
        channel = (tx.get("channel") or "").upper()
        bank_cat = (tx.get("bank_category") or "").upper()

        # Primary: channel or bank_category marks it as a card tx
        is_card_certain = channel in ("CARD", "KARTA") or bank_cat in ("TR.KART",)

        if not is_card_certain:
            # Secondary: keyword hint — only accept if a card number is found
            title = (tx.get("title") or "").lower()
            raw = (tx.get("raw_text") or "").lower()
            has_hint = any(kw in f"{title} {raw}" for kw in ("kartą", "karta", "kart ", "card"))
            if not has_hint:
                continue
            # Keyword-matched: require extractable card number (avoid false positives)
            card_num = _extract_card_number(tx)
            if not card_num:
                continue
            card_txs[card_num].append(tx)
            if card_num not in card_raw:
                card_raw[card_num] = _format_masked(card_num)
            continue

        # Try to extract card number
        card_num = _extract_card_number(tx)
        if not card_num:
            # Certain card tx without extractable number — group under "unknown"
            card_num = "****"

        card_txs[card_num].append(tx)
        if card_num not in card_raw:
            card_raw[card_num] = _format_masked(card_num)

    if not card_txs:
        return []

    # Build per-card stats
    cards = []
    for card_id, txs in card_txs.items():
        card = _build_card_stats(card_id, txs)
        card["card_masked"] = card_raw.get(card_id, card_id)
        cards.append(card)

    # Sort by total transaction volume (debit + credit)
    cards.sort(key=lambda c: -(c["total_debit"] + c["total_credit"]))

    return cards


def _extract_card_number(tx: Dict[str, Any]) -> Optional[str]:
    """Extract masked card number from transaction fields."""
    # Try all text fields in order of specificity
    raw_text = tx.get("raw_text") or ""
    title = tx.get("title") or ""
    cp = tx.get("counterparty_raw") or ""
    search_text = f"{raw_text}\n{title}\n{cp}"

    # Try full "Nr karty" pattern first
    m = _CARD_NR_RE.search(search_text)
    if m:
        return _normalize_card_id(m.group(1))

    # Try full masked PAN (4246xxxxxxxx9674)
    m = _CARD_FULL_RE.search(search_text)
    if m:
        return f"{m.group(1)}**{m.group(2)}"

    # Try short pattern (*1234)
    m = _CARD_SHORT_RE.search(search_text)
    if m:
        return f"****{m.group(1)}"

    return None


def _normalize_card_id(raw: str) -> str:
    """Normalize card number to consistent format: '4246**9674'."""
    # Remove spaces and dashes
    clean = raw.replace(" ", "").replace("-", "")
    # Replace x/X/* sequences with **
    normalized = re.sub(r"[xX*]+", "**", clean)
    return normalized


def _format_masked(card_id: str) -> str:
    """Format card ID for display: '4246 ** 9674'."""
    if card_id == "****":
        return "**** **** **** ****"
    # Split into parts
    parts = card_id.split("**")
    if len(parts) == 2:
        first = parts[0]
        last = parts[1]
        return f"{first} **** **** {last}"
    return card_id


def _detect_brand(card_id: str, txs: List[Dict]) -> str:
    """Detect card brand from BIN or text mentions."""
    # Try BIN (first digit)
    if card_id and card_id[0].isdigit():
        brand = _BIN_BRANDS.get(card_id[0])
        if brand:
            return brand

    # Try text-based detection
    for tx in txs[:10]:
        search = f"{tx.get('raw_text', '')} {tx.get('title', '')} {tx.get('counterparty_raw', '')}"
        for pattern, brand in _BRAND_PATTERNS:
            if pattern.search(search):
                return brand

    return ""


def _detect_location_from_tx(tx: Dict[str, Any]) -> Optional[str]:
    """Try to detect location from merchant name or transaction details."""
    try:
        from .merchants import detect_merchant_location
        cp = tx.get("counterparty_raw") or tx.get("counterparty") or ""
        title = tx.get("title") or ""
        return detect_merchant_location(cp, title)
    except Exception:
        return None


def _build_card_stats(card_id: str, txs: List[Dict]) -> Dict[str, Any]:
    """Build statistics for a single card."""
    total_debit = 0.0
    total_credit = 0.0
    max_amount = 0.0
    dates = []
    category_amounts: Dict[str, float] = defaultdict(float)
    merchant_amounts: Dict[str, float] = defaultdict(float)
    merchant_counts: Dict[str, int] = defaultdict(int)
    location_counts: Dict[str, int] = defaultdict(int)
    monthly_amounts: Dict[str, float] = defaultdict(float)

    for tx in txs:
        amt = abs(float(tx.get("amount") or 0))
        direction = (tx.get("direction") or "").upper()
        date = tx.get("booking_date") or ""

        if direction == "CREDIT":
            total_credit += amt
        else:
            total_debit += amt

        if amt > max_amount:
            max_amount = amt

        if date:
            dates.append(date)
            if len(date) >= 7:
                monthly_amounts[date[:7]] += amt

        # Category
        cat = tx.get("subcategory") or tx.get("category") or ""
        if cat:
            category_amounts[cat] += amt

        # Merchant
        merchant = (tx.get("counterparty_raw") or "")[:50]
        if merchant:
            merchant_amounts[merchant] += amt
            merchant_counts[merchant] += 1

        # Location
        loc = _detect_location_from_tx(tx)
        if loc:
            location_counts[loc.strip().title()] += 1

    dates.sort()
    tx_count = len(txs)
    total_volume = total_debit + total_credit
    avg_amount = total_volume / max(tx_count, 1)

    # Top categories
    top_cats = sorted(category_amounts.items(), key=lambda x: -x[1])[:6]

    # Top merchants
    top_merchants = sorted(
        [(name, merchant_amounts[name], merchant_counts[name]) for name in merchant_amounts],
        key=lambda x: -x[1],
    )[:8]

    # Locations
    locations = sorted(location_counts.items(), key=lambda x: -x[1])[:8]

    # First/last digits for display
    parts = card_id.split("**")
    first_four = parts[0] if len(parts) >= 1 and parts[0] else "????"
    last_four = parts[1] if len(parts) >= 2 and parts[1] else "????"

    return {
        "card_id": card_id,
        "first_four": first_four,
        "last_four": last_four,
        "brand": _detect_brand(card_id, txs),
        "tx_count": tx_count,
        "total_debit": round(total_debit, 2),
        "total_credit": round(total_credit, 2),
        "avg_amount": round(avg_amount, 2),
        "max_amount": round(max_amount, 2),
        "first_date": dates[0] if dates else "",
        "last_date": dates[-1] if dates else "",
        "top_categories": top_cats,
        "top_merchants": top_merchants,
        "locations": locations,
        "monthly": dict(sorted(monthly_amounts.items())),
    }
