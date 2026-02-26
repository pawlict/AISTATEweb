"""Polish bank identification database.

Identifies Polish banks from IBAN sort codes (numer rozliczeniowy).
The sort code is the 8-digit number at positions 3-10 of a Polish IBAN
(after the 2-digit check digits).

The first 4 digits identify the bank, digits 5-8 identify the branch.

Source: NBP - Wykaz numerów rozliczeniowych
"""

from __future__ import annotations

import re
from typing import Optional, Tuple

# ============================================================
# BANK IDENTIFICATION BY SORT CODE PREFIX (first 3-4 digits)
# ============================================================

# Map: sort code prefix → (short_name, full_name)
BANK_SORT_CODES: dict[str, Tuple[str, str]] = {
    # --- Banki komercyjne ---
    "1010": ("NBP",             "Narodowy Bank Polski"),
    "1020": ("PKO BP",          "PKO Bank Polski"),
    "1030": ("Citi Handlowy",   "Bank Handlowy w Warszawie (Citi Handlowy)"),
    "1050": ("ING",             "ING Bank Śląski"),
    "1060": ("BPH",             "Bank BPH (Alior)"),
    "1090": ("Santander",       "Santander Bank Polska"),
    "1130": ("BGK",             "Bank Gospodarstwa Krajowego"),
    "1140": ("mBank",           "mBank"),
    "1160": ("Millennium",      "Bank Millennium"),
    "1240": ("Pekao SA",        "Bank Pekao SA"),
    "1280": ("HSBC",            "HSBC Bank Polska"),
    "1320": ("Pocztowy",        "Bank Pocztowy"),
    "1540": ("BOŚ",             "Bank Ochrony Środowiska"),
    "1560": ("VeloBank",        "VeloBank (dawniej Getin Noble Bank)"),
    "1580": ("Mercedes Bank",   "Mercedes-Benz Bank Polska"),
    "1610": ("SGB-Bank",        "SGB-Bank SA"),
    "1680": ("Nest Bank",       "Nest Bank (dawniej Plus Bank)"),
    "1750": ("Raiffeisen",      "Raiffeisen Bank Polska (teraz BNP Paribas)"),
    "1840": ("Societe Generale", "Societe Generale SA Oddział w Polsce"),
    "1870": ("Nest Bank",       "Nest Bank"),
    "1880": ("Deutsche Bank",   "Deutsche Bank Polska"),
    "1930": ("BPS",             "Bank Polskiej Spółdzielczości"),
    "1940": ("Credit Agricole", "Credit Agricole Bank Polska"),
    "2030": ("BNP Paribas",     "BNP Paribas Bank Polska"),
    "2120": ("Santander Consumer", "Santander Consumer Bank"),
    "2130": ("VW Bank",         "Volkswagen Bank"),
    "2160": ("Toyota Bank",     "Toyota Bank Polska"),
    "2190": ("DNB",             "DNB Bank Polska"),
    "2350": ("BPS SA",          "Bank Polskiej Spółdzielczości SA"),
    "2360": ("BPS SA",          "Bank Polskiej Spółdzielczości SA"),
    "2490": ("Alior Bank",      "Alior Bank"),
    "2710": ("FCE Bank",        "FCE Bank (Ford Credit Europe)"),
    "2720": ("Inbank",          "Inbank AS SA Oddział w Polsce"),
    "2770": ("Aion Bank",       "Aion Bank SA/NV Oddział w Polsce"),
    "2800": ("HSBC Continental", "HSBC Continental Europe (Oddział w Polsce)"),
    "2850": ("Citi Handlowy",   "Citibank Europe plc (Oddział w Polsce)"),
    "2910": ("PKO BP",          "PKO Bank Polski (Oddział Korporacyjny)"),
}

# Country codes for IBAN classification
IBAN_COUNTRY_NAMES: dict[str, str] = {
    "PL": "Polska",
    "DE": "Niemcy",
    "GB": "Wielka Brytania",
    "FR": "Francja",
    "NL": "Holandia",
    "BE": "Belgia",
    "AT": "Austria",
    "CH": "Szwajcaria",
    "IT": "Włochy",
    "ES": "Hiszpania",
    "CZ": "Czechy",
    "SK": "Słowacja",
    "LT": "Litwa",
    "LV": "Łotwa",
    "EE": "Estonia",
    "SE": "Szwecja",
    "DK": "Dania",
    "NO": "Norwegia",
    "FI": "Finlandia",
    "IE": "Irlandia",
    "PT": "Portugalia",
    "LU": "Luksemburg",
    "HR": "Chorwacja",
    "RO": "Rumunia",
    "BG": "Bułgaria",
    "HU": "Węgry",
    "SI": "Słowenia",
    "MT": "Malta",
    "CY": "Cypr",
    "GR": "Grecja",
    "UA": "Ukraina",
}

# Official IBAN country codes (ISO 13616) — used to reject false positives.
# Only these 2-letter prefixes are valid IBAN country codes.
_VALID_IBAN_COUNTRIES = {
    "AD", "AE", "AL", "AT", "AZ", "BA", "BE", "BG", "BH", "BR", "BY",
    "CH", "CR", "CY", "CZ", "DE", "DK", "DO", "EE", "EG", "ES", "FI",
    "FO", "FR", "GB", "GE", "GI", "GL", "GR", "GT", "HR", "HU", "IE",
    "IL", "IQ", "IS", "IT", "JO", "KW", "KZ", "LB", "LC", "LI", "LT",
    "LU", "LV", "MC", "MD", "ME", "MK", "MR", "MT", "MU", "NL", "NO",
    "PK", "PL", "PS", "PT", "QA", "RO", "RS", "SA", "SC", "SE", "SI",
    "SK", "SM", "ST", "SV", "TL", "TN", "TR", "UA", "VA", "VG", "XK",
}

# IBAN lengths per country (ISO 13616)
_IBAN_LENGTHS: dict[str, int] = {
    "AL": 28, "AD": 24, "AT": 20, "AZ": 28, "BH": 22, "BY": 28, "BE": 16,
    "BA": 20, "BR": 29, "BG": 22, "CR": 22, "HR": 21, "CY": 28, "CZ": 24,
    "DK": 18, "DO": 28, "EG": 29, "EE": 20, "FO": 18, "FI": 18, "FR": 27,
    "GE": 22, "DE": 22, "GI": 23, "GR": 27, "GL": 18, "GT": 28, "HU": 28,
    "IS": 26, "IQ": 23, "IE": 22, "IL": 23, "IT": 27, "JO": 30, "KZ": 20,
    "XK": 20, "KW": 30, "LV": 21, "LB": 28, "LC": 32, "LI": 21, "LT": 20,
    "LU": 20, "MK": 19, "MT": 31, "MR": 27, "MU": 30, "MC": 27, "MD": 24,
    "ME": 22, "NL": 18, "NO": 15, "PK": 24, "PS": 29, "PL": 28, "PT": 25,
    "QA": 29, "RO": 24, "SM": 27, "SA": 24, "RS": 22, "SC": 31, "SK": 24,
    "SI": 19, "ES": 24, "SE": 24, "CH": 21, "TL": 23, "TN": 24, "TR": 26,
    "UA": 29, "AE": 23, "GB": 22, "VA": 22, "VG": 24, "SV": 28, "ST": 25,
}


# ============================================================
# IBAN VALIDATION (MOD 97 check digit)
# ============================================================

def validate_iban(iban: str) -> bool:
    """Validate an IBAN using the MOD 97 check digit algorithm.

    Args:
        iban: Full IBAN string (with country prefix, e.g. "PL12105010121234...")
              or 26-digit Polish NRB (auto-prefixed with PL).

    Returns True if the check digit is valid.
    """
    clean = re.sub(r"[\s\-]", "", iban).upper()

    # If pure digits (no country prefix), assume Polish NRB
    if clean.isdigit():
        if len(clean) != 26:
            return False
        clean = "PL" + clean

    if len(clean) < 5:
        return False

    cc = clean[:2]
    if not cc.isalpha():
        return False

    # Check country code is valid
    if cc not in _VALID_IBAN_COUNTRIES:
        return False

    # Check length matches expected for country
    expected_len = _IBAN_LENGTHS.get(cc)
    if expected_len and len(clean) != expected_len:
        return False

    # MOD 97 algorithm: move first 4 chars to end, convert letters to numbers
    rearranged = clean[4:] + clean[:4]
    numeric_str = ""
    for ch in rearranged:
        if ch.isdigit():
            numeric_str += ch
        elif ch.isalpha():
            numeric_str += str(ord(ch) - ord("A") + 10)
        else:
            return False

    try:
        return int(numeric_str) % 97 == 1
    except (ValueError, OverflowError):
        return False


def _is_known_polish_bank(nrb_26: str) -> bool:
    """Check if a 26-digit NRB corresponds to a known Polish bank."""
    if len(nrb_26) != 26 or not nrb_26.isdigit():
        return False
    sort_code = nrb_26[2:10]
    prefix_4 = sort_code[:4]
    if prefix_4 in BANK_SORT_CODES:
        return True
    # Cooperative banks: sort codes starting with 8 or 9
    if sort_code[0] in ("8", "9"):
        return True
    return False


# ============================================================
# IBAN PATTERNS (extraction)
# ============================================================

# Polish IBAN with PL prefix (strict: requires PL + 26 digits)
_IBAN_PL_RE = re.compile(
    r"\bPL\s?(\d{2})\s?(\d{4})\s?(\d{4})\s?(\d{4})\s?(\d{4})\s?(\d{4})\s?(\d{4})\b",
    re.IGNORECASE,
)

# Spaced NRB pattern: XX XXXX XXXX XXXX XXXX XXXX XXXX (strict spacing)
_NRB_SPACED_RE = re.compile(r"\b(\d{2})\s(\d{4})\s(\d{4})\s(\d{4})\s(\d{4})\s(\d{4})\s(\d{4})\b")

# Compact NRB (26 consecutive digits) only after a keyword context.
# Matches: "Nr rachunku 12105010121234567890123456"
#          "rachunek: 12105010121234567890123456"
#          "IBAN 12105010121234567890123456"
#          "konto 12105010121234567890123456"
_NRB_CONTEXTUAL_RE = re.compile(
    r"(?:Nr\s+rachunku|rachunk\w*|kont[oa]|IBAN|NRB)[:\s]+(\d{26})\b",
    re.IGNORECASE,
)


def identify_bank(account_number: str) -> Optional[Tuple[str, str]]:
    """Identify a Polish bank from an account number (NRB or IBAN PL).

    Args:
        account_number: Polish IBAN or NRB (26 digits, with or without PL prefix)

    Returns:
        Tuple of (short_name, full_name) or None if not identified.
    """
    clean = re.sub(r"[\s\-]", "", account_number).upper()
    if clean.startswith("PL"):
        clean = clean[2:]

    if len(clean) != 26 or not clean.isdigit():
        return None

    sort_code = clean[2:10]
    prefix_4 = sort_code[:4]

    if prefix_4 in BANK_SORT_CODES:
        return BANK_SORT_CODES[prefix_4]

    # Cooperative bank detection (sort codes 8xxx-9xxx)
    if sort_code[0] in ("8", "9"):
        return ("Bank Spółdzielczy", "Bank Spółdzielczy")

    return None


def classify_account(account_number: str) -> dict:
    """Classify an account number (Polish or international IBAN).

    Returns dict with: account_normalized, country_code, country_name,
    is_polish, is_foreign, bank_short, bank_full, sort_code, display.
    """
    clean = re.sub(r"[\s\-]", "", account_number).upper()

    result = {
        "account_normalized": clean,
        "country_code": "",
        "country_name": "",
        "is_polish": False,
        "is_foreign": False,
        "bank_short": "",
        "bank_full": "",
        "sort_code": "",
        "display": "",
    }

    # Detect country code
    if clean[:2].isalpha():
        cc = clean[:2]
        result["country_code"] = cc
        result["country_name"] = IBAN_COUNTRY_NAMES.get(cc, cc)
        digits = clean[2:]
    else:
        cc = "PL"
        result["country_code"] = "PL"
        result["country_name"] = "Polska"
        digits = clean

    if cc == "PL":
        result["is_polish"] = True
        if len(digits) == 26 and digits.isdigit():
            result["sort_code"] = digits[2:10]
            bank = identify_bank(digits)
            if bank:
                result["bank_short"] = bank[0]
                result["bank_full"] = bank[1]
            # Format: XX XXXX XXXX XXXX XXXX XXXX XXXX
            result["display"] = (
                f"{digits[:2]} {digits[2:6]} {digits[6:10]} {digits[10:14]} "
                f"{digits[14:18]} {digits[18:22]} {digits[22:26]}"
            )
    else:
        result["is_foreign"] = True
        result["display"] = f"{cc} {' '.join(digits[i:i+4] for i in range(0, len(digits), 4))}"

    if not result["display"]:
        result["display"] = account_number

    return result


def extract_accounts_from_text(text: str) -> list[str]:
    """Extract validated IBAN/NRB account numbers from text.

    Only returns accounts that pass IBAN check digit validation
    or match a known Polish bank sort code.

    Returns list of normalized account numbers (digits only for Polish,
    with country prefix for foreign).
    """
    if not text:
        return []

    accounts: list[str] = []
    seen: set[str] = set()

    def _add(acc: str):
        if acc not in seen:
            seen.add(acc)
            accounts.append(acc)

    # 1. Match PL IBAN (explicit PL prefix — most reliable)
    for m in _IBAN_PL_RE.finditer(text):
        digits = re.sub(r"\s", "", "".join(m.groups()))
        if len(digits) == 26 and validate_iban("PL" + digits):
            _add(digits)

    # 2. Match spaced NRB: XX XXXX XXXX XXXX XXXX XXXX XXXX
    for m in _NRB_SPACED_RE.finditer(text):
        digits = re.sub(r"\s", "", m.group())
        if len(digits) == 26 and digits not in seen:
            # Validate: must pass check digit OR match known bank
            if validate_iban(digits) or _is_known_polish_bank(digits):
                _add(digits)

    # 3. Match compact NRB (26 consecutive digits) ONLY when preceded by
    #    a keyword indicating it's an account number. Without context,
    #    26-digit sequences are usually transaction references.
    for m in _NRB_CONTEXTUAL_RE.finditer(text):
        digits = m.group(1)
        if len(digits) == 26 and digits not in seen:
            if validate_iban(digits) or _is_known_polish_bank(digits):
                _add(digits)

    return accounts
