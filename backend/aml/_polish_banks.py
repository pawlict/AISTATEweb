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

    # --- Banki spółdzielcze (wybrane zakresy) ---
    # Banki spółdzielcze zrzeszone w BPS mają numery z zakresu 8000-9999
    # Banki spółdzielcze zrzeszone w SGB mają numery z zakresu 9000-9999
    # Przykładowe prefiksy (nie wyczerpujące):
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
    "US": "USA",
    "CN": "Chiny",
    "JP": "Japonia",
}


# ============================================================
# IBAN PATTERNS
# ============================================================

# Polish NRB (26 digits, no country prefix)
_NRB_RE = re.compile(r"\b(\d{2})(\d{4})(\d{4})(\d{4})(\d{4})(\d{4})(\d{4})\b")

# Polish IBAN with PL prefix
_IBAN_PL_RE = re.compile(
    r"\bPL\s?(\d{2})\s?(\d{4})\s?(\d{4})\s?(\d{4})\s?(\d{4})\s?(\d{4})\s?(\d{4})\b",
    re.IGNORECASE,
)

# International IBAN (2 letter country code + 2 check + up to 30 alphanumeric)
_IBAN_INTL_RE = re.compile(
    r"\b([A-Z]{2})\s?(\d{2})\s?([\d\s]{10,30})\b"
)

# Spaced NRB pattern used in ING statements
_NRB_SPACED_RE = re.compile(r"\b\d{2}(?:\s\d{4}){6}\b")


def identify_bank(account_number: str) -> Optional[Tuple[str, str]]:
    """Identify a Polish bank from an account number (NRB or IBAN PL).

    Args:
        account_number: Polish IBAN or NRB (26 digits, with or without PL prefix)

    Returns:
        Tuple of (short_name, full_name) or None if not identified.
    """
    # Normalize: remove spaces, dashes, PL prefix
    clean = re.sub(r"[\s\-]", "", account_number).upper()
    if clean.startswith("PL"):
        clean = clean[2:]

    if len(clean) != 26 or not clean.isdigit():
        return None

    # Sort code = digits 3-10 (positions 2-9, 0-indexed)
    # First 2 digits are check digits
    sort_code = clean[2:10]  # 8-digit sort code
    prefix_4 = sort_code[:4]

    # Try 4-digit prefix match
    if prefix_4 in BANK_SORT_CODES:
        return BANK_SORT_CODES[prefix_4]

    # Try cooperative bank detection (sort codes 8000-9999)
    first_digit = int(sort_code[0])
    if first_digit >= 8:
        return ("Bank Spółdzielczy", "Bank Spółdzielczy")

    return None


def classify_account(account_number: str) -> dict:
    """Classify an account number (Polish or international IBAN).

    Returns:
        Dict with:
        - account_normalized: cleaned account number
        - country_code: 2-letter code (PL, DE, etc.)
        - country_name: Polish name of the country
        - is_polish: bool
        - is_foreign: bool
        - bank_short: short bank name (Polish accounts only)
        - bank_full: full bank name (Polish accounts only)
        - sort_code: 8-digit sort code (Polish accounts only)
        - display: formatted for display
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
        # No country prefix — assume Polish NRB
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
        # Format international IBAN
        result["display"] = f"{cc} {' '.join(digits[i:i+4] for i in range(0, len(digits), 4))}"

    if not result["display"]:
        result["display"] = account_number

    return result


def extract_accounts_from_text(text: str) -> list[str]:
    """Extract all IBAN/NRB account numbers from text.

    Returns list of normalized account numbers (digits only, without PL prefix).
    """
    if not text:
        return []

    accounts: list[str] = []

    # Match PL IBAN first
    for m in _IBAN_PL_RE.finditer(text):
        digits = "".join(m.groups())
        digits = re.sub(r"\s", "", digits)
        if len(digits) == 26:
            accounts.append(digits)

    # Match spaced NRB (common in ING statements)
    for m in _NRB_SPACED_RE.finditer(text):
        digits = m.group().replace(" ", "")
        if len(digits) == 26 and digits not in accounts:
            accounts.append(digits)

    # Match compact NRB (26 consecutive digits)
    for m in _NRB_RE.finditer(text):
        digits = "".join(m.groups())
        if digits not in accounts:
            accounts.append(digits)

    # Match international IBAN
    for m in _IBAN_INTL_RE.finditer(text):
        cc = m.group(1)
        if cc == "PL":
            continue  # already handled
        check = m.group(2)
        rest = re.sub(r"\s", "", m.group(3))
        full = f"{cc}{check}{rest}"
        if full not in accounts:
            accounts.append(full)

    return accounts
