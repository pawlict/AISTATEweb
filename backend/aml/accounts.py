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

# ============================================================
# Phone transfer detection — suggests personal (friend/family) transfer
# ============================================================

_PHONE_TRANSFER_KEYWORDS = [
    r"przelew\s+na\s+telefon",
    r"przelew\s+na\s+numer",
    r"przelew\s+blik",
    r"blik",
    r"przelew\s+mobilny",
    r"przelew\s+telefoniczny",
]

_PHONE_TRANSFER_RE = re.compile(
    "|".join(f"(?:{p})" for p in _PHONE_TRANSFER_KEYWORDS),
    re.IGNORECASE,
)

# Simple heuristic: counterparty looks like a person name (2-3 capitalized words)
_PERSON_NAME_RE = re.compile(
    r"^[A-ZŻŹĆĄŚĘŁÓŃ][a-zżźćąśęłóń]+"
    r"\s+[A-ZŻŹĆĄŚĘŁÓŃ][a-zżźćąśęłóń]+"
    r"(?:\s+[A-ZŻŹĆĄŚĘŁÓŃ][a-zżźćąśęłóń]+)?$"
)

# ============================================================
# Account ownership categories
# ============================================================
# own          — statement owner's own account
# third_party  — business counterparty (Kontrahent)
# friend       — personal transfer to a person (Znajomy)
# family       — family member, same last name (Rodzina)
# employer     — employer account, credit-only (Pracodawca)
VALID_CATEGORIES = {"own", "third_party", "friend", "family", "employer"}


# ============================================================
# Name-based ownership matching
# ============================================================

def _normalize_name(name: str) -> str:
    """Lowercase, strip, collapse whitespace."""
    s = (name or "").lower().strip()
    s = re.sub(r"\s+", " ", s)
    return s


def _surname_stem(name: str) -> str:
    """Normalize Polish surname gender suffix for comparison.

    Pawlicki/Pawlicka → pawlick
    Kowalski/Kowalska → kowalsk
    Nowak/Nowak       → nowak
    Wiśniewski/Wiśniewska → wiśniewsk
    """
    n = name.lower()
    # -ski/-ska, -cki/-cka, -dzki/-dzka, -ński/-ńska → strip last gender letter
    if re.search(r"(?:sk|ck|dzk|ńsk)[ia]$", n):
        return n[:-1]
    return n


def _extract_name_parts(name: str) -> list:
    """Extract name words from a string, stripping address parts.

    Handles formats:
      "IMIĘ NAZWISKO"
      "NAZWISKO IMIĘ"
      "PAWLICKI; TOMASZ; PODWODNA 44"  → only first 2 semicolon-parts

    Returns list of lowercase name words (order preserved).
    """
    n = _normalize_name(name)
    if not n:
        return []

    # If semicolons present: "NAZWISKO; IMIĘ; ADRES..." → take only first 2 parts
    if ";" in n:
        parts = [p.strip() for p in n.split(";")]
        # First 2 parts are name, rest is address
        n = " ".join(parts[:2])

    # Split into words, filter out address fragments
    words = n.split()
    name_words = []
    for w in words:
        if re.search(r"\d", w):
            continue
        if w.rstrip(".") in ("ul", "al", "os", "pl", "m", "nr", "lok", "kl"):
            continue
        if len(w) < 2:
            continue
        name_words.append(w)

    return name_words


def _match_name_ownership(
    counterparty_name: str,
    account_holder: str,
) -> Optional[str]:
    """Compare counterparty name to account holder and return ownership hint.

    Returns:
        "own"    — same first + last name (the account holder themselves)
        "family" — different first name, same last name (incl. gender forms)
        None     — no name-based match (use other rules)
    """
    if not counterparty_name or not account_holder:
        return None

    holder_words = _extract_name_parts(account_holder)
    cp_words = _extract_name_parts(counterparty_name)

    if len(holder_words) < 2 or len(cp_words) < 2:
        return None

    holder_stems = {_surname_stem(w) for w in holder_words}
    cp_stems = {_surname_stem(w) for w in cp_words}

    # Also keep exact words for first-name comparison
    holder_set = set(holder_words)
    cp_set = set(cp_words)

    # Check: all stem-normalized words match → same person (handles name order + gender)
    if holder_stems == cp_stems:
        return "own"

    # Check: exact word match for >=2 words (e.g. reversed order)
    common_exact = holder_set & cp_set
    if len(common_exact) >= 2:
        return "own"

    # Check: at least one surname stem matches
    common_stems = holder_stems & cp_stems
    if common_stems:
        # Some stems overlap → check if first names differ
        # The overlapping stem is likely the last name
        non_common_holder = holder_set - {w for w in holder_words if _surname_stem(w) in common_stems}
        non_common_cp = cp_set - {w for w in cp_words if _surname_stem(w) in common_stems}

        if non_common_holder and non_common_cp and non_common_holder != non_common_cp:
            # Different first names, same last name stem → family
            return "family"
        elif not non_common_holder and not non_common_cp:
            # All words matched via stems → same person
            return "own"

    return None


# ============================================================
# Employer / salary detection keywords
# ============================================================

_SALARY_KEYWORDS = [
    r"wynagrodzenie",
    r"wynagrodz",
    r"pensja",
    r"premia",
    r"zap[łl]ata",
    r"wyp[łl]ata",
    r"salary",
    r"za\s+prac[ęe]",
    r"umowa\s+o\s+prac[ęe]",
    r"umowa\s+zleceni[ae]",
    r"umowa\s+o\s+dzie[łl]o",
]

_SALARY_RE = re.compile(
    "|".join(f"(?:{p})" for p in _SALARY_KEYWORDS),
    re.IGNORECASE,
)


def _is_salary_tx(tx: Dict[str, Any]) -> bool:
    """Check if transaction looks like a salary/wage payment."""
    title = tx.get("title") or ""
    raw = tx.get("raw_text") or ""
    search = f"{title} {raw}"
    return bool(_SALARY_RE.search(search))


def _is_phone_transfer_tx(tx: Dict[str, Any]) -> bool:
    """Check if transaction looks like a phone/BLIK transfer."""
    title = tx.get("title") or ""
    raw = tx.get("raw_text") or ""
    search = f"{title} {raw}"
    return bool(_PHONE_TRANSFER_RE.search(search))


def _is_person_name(counterparty: str) -> bool:
    """Check if counterparty looks like a person name (not a company)."""
    cp = counterparty.strip()
    if not cp or len(cp) < 4:
        return False
    # Companies tend to have keywords
    company_markers = [
        "sp.", "s.a.", "s.a", "sp.z", "sp. z", "z o.o", "zoo", "ltd",
        "gmbh", "inc", "corp", "sklep", "market", "urząd", "zakład",
        "firma", "bank", "ubezpiecz", "fundusz", "stowarzysz",
    ]
    lower = cp.lower()
    if any(m in lower for m in company_markers):
        return False
    return bool(_PERSON_NAME_RE.match(cp))


def detect_accounts(
    transactions: List[Dict[str, Any]],
    statement_account: str = "",
    account_holder: str = "",
) -> List[Dict[str, Any]]:
    """Detect unique bank accounts and compute per-account statistics.

    Args:
        transactions: List of transaction dicts (from DB, must include
            raw_text, title, counterparty_raw, direction, amount, booking_date).
        statement_account: The statement owner's own account number (for detection).
        account_holder: The statement owner's name (e.g. "Tomasz Pawlicki")
            — used for name-based ownership matching.

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
            account_num, txs, own_account_norm, account_holder,
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
    account_holder: str = "",
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
    phone_tx_count = 0
    salary_tx_count = 0

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

        # Check for phone/BLIK transfers
        if _is_phone_transfer_tx(tx):
            phone_tx_count += 1

        # Check for salary/employer payments
        if _is_salary_tx(tx):
            salary_tx_count += 1

    dates.sort()
    tx_count = len(txs)

    # Determine ownership category
    # Priority:
    #   1. Exact account number match → own
    #   2. Name-based matching (counterparty vs account holder):
    #      - same first+last name → own
    #      - same last name, different first name → family
    #   3. Own-transfer keywords (>50% of tx) → own
    #   4. Credit-only + salary keywords → employer
    #   5. Phone/BLIK transfer to person → friend
    #   6. Default → third_party

    is_own = False
    ownership = "third_party"

    # (1) Exact account number match
    if account_num == own_account_norm:
        is_own = True
        ownership = "own"
    else:
        # (2) Name-based matching: compare top counterparty name with account holder
        name_hint = None
        if account_holder:
            top_cp_name = max(counterparty_counts, key=counterparty_counts.get) if counterparty_counts else ""
            if top_cp_name:
                name_hint = _match_name_ownership(top_cp_name, account_holder)
                if not name_hint:
                    # Also try other counterparty names (not just the top one)
                    for cp_name in counterparty_counts:
                        name_hint = _match_name_ownership(cp_name, account_holder)
                        if name_hint:
                            break

        if name_hint == "own":
            is_own = True
            ownership = "own"
        elif name_hint == "family":
            ownership = "family"
        elif own_tx_count > 0 and own_tx_count >= tx_count * 0.5:
            # (3) Own-transfer keywords heuristic
            if phone_tx_count > 0 and phone_tx_count >= own_tx_count:
                is_own = False
            else:
                is_own = True
                ownership = "own"

        if not is_own and ownership not in ("family",):
            if debit_count == 0 and credit_count > 0 and salary_tx_count > 0:
                # (4) Credit-only account with salary keywords → employer
                ownership = "employer"
            elif phone_tx_count > 0:
                # (5) Phone/BLIK transfer to a person → friend
                cp_name = max(counterparty_counts, key=counterparty_counts.get) if counterparty_counts else ""
                if _is_person_name(cp_name):
                    ownership = "friend"
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
