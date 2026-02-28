"""Card identification module for AML analysis.

Extracts debit/credit card numbers from transaction data and computes
per-card statistics (spending, categories, locations, patterns).
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

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

# Keywords that confirm a transaction is card-related
_CARD_EVIDENCE_KEYWORDS = (
    "płatność kartą", "platnosc karta", "płatnosc kartą",
    "nr karty", "numer karty", "karta nr",
    "card payment", "wypłata z bankomatu", "wyplata z bankomatu",
    "atm", "bankomat",
)

# ============================================================
# Counterparty / merchant name cleanup
# ============================================================

# Label prefixes that should be stripped from counterparty_raw
_LABEL_PREFIXES = (
    "Nazwa i adres odbiorcy:",
    "Nazwa i adres płatnika:",
    "Nazwa i adres nadawcy:",
    "Nazwa i adres odbiorcy",
    "Nazwa i adres płatnika",
    "Nazwa i adres nadawcy",
)

# ING internal counterparty ID pattern (e.g., "10500031-1915031/19730")
_ING_INTERNAL_ID_RE = re.compile(r"\b\d{7,10}-\d{7,10}/\d{3,6}\b")

# NRB account number (26 digits with optional spaces)
_NRB_RE = re.compile(r"\b\d{2}\s?\d{4}\s?\d{4}\s?\d{4}\s?\d{4}\s?\d{4}\s?\d{4}\b")

# Address-like fragments at start of a name part
_ADDRESS_PREFIX_RE = re.compile(
    r"^(UL\.?|AL\.?|PL\.?|OS\.?|RYNEK|PLAC)\s",
    re.IGNORECASE,
)

# Postal code at start
_POSTAL_CODE_RE = re.compile(r"^\d{2}-\d{3}\b")


def _clean_merchant_name(raw: str) -> str:
    """Clean up raw counterparty text to extract merchant name.

    Handles ING-specific artifacts:
    - "Nazwa i adres odbiorcy: MERCHANT_NAME" labels
    - ING internal IDs (10500031-1915031/19730)
    - Account numbers (NRB)
    - Semicolon-separated name+address → extract just the name
    """
    if not raw:
        return ""

    # Strip common label prefixes
    for prefix in _LABEL_PREFIXES:
        if raw.startswith(prefix):
            raw = raw[len(prefix):].strip()

    # Remove ING internal IDs
    raw = _ING_INTERNAL_ID_RE.sub("", raw).strip()

    # Remove NRB account numbers
    raw = _NRB_RE.sub("", raw).strip()

    # Handle semicolon-separated parts (name; address; city)
    if ";" in raw:
        parts = [p.strip() for p in raw.split(";") if p.strip()]
        # Separate name parts from address parts
        names = []
        for p in parts:
            if _ADDRESS_PREFIX_RE.match(p) or _POSTAL_CODE_RE.match(p):
                continue  # skip address fragments
            if len(p) <= 2:
                continue  # skip tiny fragments
            names.append(p)
        if names:
            raw = "; ".join(names[:2])  # keep max 2 name parts

    # Collapse whitespace
    raw = re.sub(r"\s+", " ", raw).strip()

    # Strip trailing semicolons and whitespace
    raw = raw.strip("; ").strip()

    return raw[:50] if raw else ""


def detect_cards(transactions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Detect unique cards and compute per-card statistics.

    Args:
        transactions: List of transaction dicts (from DB, must include
            raw_text, title, counterparty_raw, channel, category, amount,
            direction, booking_date).

    Returns:
        List of card info dicts, sorted by total_amount descending.
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
            # Channel says it's a card tx but no card number found.
            # Verify with secondary evidence to avoid false positives.
            title = (tx.get("title") or "").lower()
            raw = (tx.get("raw_text") or "").lower()
            combined = f"{title} {raw}"

            has_card_evidence = any(kw in combined for kw in _CARD_EVIDENCE_KEYWORDS)
            if not has_card_evidence:
                # No card-specific keywords → skip (likely false positive)
                continue

            # Has card keywords but can't read the number — group under "unknown"
            card_num = "****"

        card_txs[card_num].append(tx)
        if card_num not in card_raw:
            card_raw[card_num] = _format_masked(card_num)

    if not card_txs:
        return []

    # Try to re-assign "****" transactions to known cards if possible
    if "****" in card_txs and len(card_txs) > 1:
        known_cards = {cid for cid in card_txs if cid != "****"}
        reassigned = []
        remaining = []
        for tx in card_txs["****"]:
            # Try harder: search title for any known card's last 4 digits
            title = (tx.get("title") or "") + " " + (tx.get("raw_text") or "")
            matched = False
            for known_id in known_cards:
                last4 = known_id.split("**")[-1] if "**" in known_id else ""
                if last4 and last4 in title:
                    card_txs[known_id].append(tx)
                    reassigned.append(tx)
                    matched = True
                    break
            if not matched:
                remaining.append(tx)

        if remaining:
            card_txs["****"] = remaining
        else:
            del card_txs["****"]

    # Drop "****" card entirely if it has very few transactions
    # and mostly credits (likely false positives)
    if "****" in card_txs:
        unknown_txs = card_txs["****"]
        credits = sum(1 for t in unknown_txs if (t.get("direction") or "").upper() == "CREDIT")
        debits = len(unknown_txs) - credits
        if debits <= 2 or credits > debits:
            # Mostly credits or very few debits → likely not a real card
            del card_txs["****"]

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
    """Format card ID for display: '4246 **** **** 9674'."""
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

        # Merchant — clean up counterparty_raw before using
        raw_cp = tx.get("counterparty_raw") or ""
        merchant = _clean_merchant_name(raw_cp)
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

    # Top merchants (top 5 as requested)
    top_merchants = sorted(
        [(name, merchant_amounts[name], merchant_counts[name]) for name in merchant_amounts],
        key=lambda x: -x[1],
    )[:5]

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
