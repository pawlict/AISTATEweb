"""Quick regex-based extraction of bank statement header data.

Used by quick analysis to extract key fields WITHOUT LLM — pure regex.
Returns a dict ready for JSON serialization and UI display.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional


def _parse_amount(text: str) -> Optional[float]:
    """Parse Polish-format amount: '1 234,56' or '-1234.56'."""
    if not text or not text.strip():
        return None
    s = text.strip().replace("\xa0", " ").replace(" ", "")
    s = re.sub(r"[^\d,.\-+]", "", s)
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def _format_iban(raw: str) -> str:
    """Format raw IBAN digits to PL XX XXXX XXXX ... format."""
    digits = raw.replace(" ", "")
    if len(digits) == 26:
        return f"PL {digits[:2]} {digits[2:6]} {digits[6:10]} {digits[10:14]} {digits[14:18]} {digits[18:22]} {digits[22:26]}"
    return digits


def _detect_bank_name(text: str) -> str:
    """Detect bank name from text."""
    tl = text.lower()
    banks = [
        (r"ing\s*bank\s*[śs]l[ąa]ski|ing\s*bank|www\.ing\.pl|ingbsk", "ING Bank Śląski"),
        (r"pko\s*b(?:ank\s*)?p(?:olski)?|ipko|www\.pkobp\.pl", "PKO Bank Polski"),
        (r"mbank|www\.mbank\.pl|bre\s*bank", "mBank"),
        (r"santander\s*bank\s*pol|www\.santander\.pl", "Santander Bank Polska"),
        (r"bank\s*pekao|pekao\s*s\.?a|www\.pekao\.com", "Bank Pekao SA"),
        (r"millennium|www\.bankmillennium\.pl", "Bank Millennium"),
        (r"bnp\s*paribas|www\.bnpparibas\.pl", "BNP Paribas"),
        (r"credit\s*agricole|www\.credit-agricole\.pl", "Credit Agricole"),
        (r"alior\s*bank|www\.aliorbank\.pl", "Alior Bank"),
        (r"nest\s*bank|www\.nestbank\.pl", "Nest Bank"),
    ]
    for pattern, name in banks:
        if re.search(pattern, tl):
            return name
    return ""


def _extract_account_holder(text: str) -> str:
    """Try to extract account holder name from statement text."""
    # Common patterns in Polish bank statements
    patterns = [
        # "Właściciel: Jan Kowalski" / "Posiadacz rachunku: ..."
        r"(?:w[łl]a[śs]ciciel|posiadacz)\s*(?:rachunku)?\s*:?\s*([A-ZĄĆĘŁŃÓŚŹŻ][a-ząćęłńóśźż]+(?:\s+[A-ZĄĆĘŁŃÓŚŹŻ][a-ząćęłńóśźż\-]+){1,3})",
        # "Rachunek: ... \n Imię Nazwisko" — name after account type line
        r"(?:rachunek\s+(?:bież|osobi|oszczę)[^\n]*\n\s*)([A-ZĄĆĘŁŃÓŚŹŻ][a-ząćęłńóśźż]+\s+[A-ZĄĆĘŁŃÓŚŹŻ][a-ząćęłńóśźż\-]+)",
        # ING "KONTO Z LWEM" style — name is usually nearby
        r"(?:konto\s+[^\n]+\n\s*)([A-ZĄĆĘŁŃÓŚŹŻ][a-ząćęłńóśźż]+\s+[A-ZĄĆĘŁŃÓŚŹŻ][a-ząćęłńóśźż\-]+)",
        # "Pan/Pani Imię Nazwisko"
        r"(?:pan|pani)\s+([A-ZĄĆĘŁŃÓŚŹŻ][a-ząćęłńóśźż]+\s+[A-ZĄĆĘŁŃÓŚŹŻ][a-ząćęłńóśźż\-]+)",
        # "Imię i Nazwisko" after "dla" or "na rzecz"
        r"(?:dla|na\s+rzecz)\s+([A-ZĄĆĘŁŃÓŚŹŻ][a-ząćęłńóśźż]+\s+[A-ZĄĆĘŁŃÓŚŹŻ][a-ząćęłńóśźż\-]+)",
    ]
    for p in patterns:
        m = re.search(p, text, re.I)
        if m:
            name = m.group(1).strip()
            # Validate: at least 2 words, not too long
            words = name.split()
            if 2 <= len(words) <= 4 and len(name) < 60:
                return name
    return ""


def extract_bank_statement_quick(text: str) -> Dict[str, Any]:
    """Extract key bank statement fields using regex only (no LLM).

    Uses the common extractor from parsers.base for robust multi-format
    pattern matching (handles ING "Nr X /" period, multi-line saldo, etc.)

    Args:
        text: Extracted text from PDF (full or first few pages).

    Returns:
        Dict with fields for quick analysis UI display.
    """
    # Use the common extractor for robust multi-format parsing
    try:
        from .parsers.base import BankParser
        info = BankParser.extract_info_common(text)
    except Exception:
        info = None

    result: Dict[str, Any] = {
        "typ_dokumentu": "wyciąg bankowy",
        "wlasciciel_rachunku": None,
        "bank": None,
        "nr_rachunku_iban": None,
        "okres": None,
        "waluta": "PLN",
        "saldo_poczatkowe": None,
        "saldo_koncowe": None,
        "saldo_dostepne": None,
        "suma_uznan": None,
        "suma_obciazen": None,
        "liczba_transakcji": None,
        "status": "completed",
    }

    # Use first ~8000 chars for header extraction (avoid transaction noise)
    header = text[:8000] if text else ""

    # Bank name
    bank = _detect_bank_name(header)
    if bank:
        result["bank"] = bank

    # Account holder
    holder = _extract_account_holder(header)
    if not holder and info and info.account_holder:
        holder = info.account_holder
    if holder:
        result["wlasciciel_rachunku"] = holder

    # IBAN
    if info and info.account_number:
        result["nr_rachunku_iban"] = _format_iban(info.account_number)
    else:
        m = re.search(r"(\d{2}\s?\d{4}\s?\d{4}\s?\d{4}\s?\d{4}\s?\d{4}\s?\d{4})", header)
        if m:
            result["nr_rachunku_iban"] = _format_iban(m.group(1))

    # Period — use common extractor result
    if info and info.period_from and info.period_to:
        result["okres"] = f"{info.period_from} – {info.period_to}"
    else:
        # Fallback: direct regex
        for pat in [
            r"Nr\s*\d+\s*/\s*(\d{2}[.\-/]\d{2}[.\-/]\d{4})\s*[-–]\s*(\d{2}[.\-/]\d{2}[.\-/]\d{4})",
            r"(?:okres|za\s*okres|od)\s*:?\s*(\d{2}[.\-/]\d{2}[.\-/]\d{4})\s*(?:[-–]|do)\s*(\d{2}[.\-/]\d{2}[.\-/]\d{4})",
        ]:
            m = re.search(pat, header, re.I)
            if m:
                result["okres"] = f"{m.group(1)} – {m.group(2)}"
                break

    # Balances — prefer common extractor (handles multi-line)
    if info and info.opening_balance is not None:
        result["saldo_poczatkowe"] = info.opening_balance
    else:
        for pat in [
            r"saldo\s*pocz[ąa]tkowe[^\n]*(?:\n[^\n]*){0,2}?\s*([\d\s]+[,\.]\d{2})\s*(?:PLN|EUR|USD)?",
            r"saldo\s*(?:pocz[ąa]tkowe|otwarcia)\s*:?\s*([\d\s,.\-]+)",
        ]:
            m = re.search(pat, header, re.I)
            if m:
                result["saldo_poczatkowe"] = _parse_amount(m.group(1))
                break

    if info and info.closing_balance is not None:
        result["saldo_koncowe"] = info.closing_balance
    else:
        for pat in [
            r"saldo\s*ko[ńn]cowe[^\n]*(?:\n[^\n]*){0,2}?\s*([\d\s]+[,\.]\d{2})\s*(?:PLN|EUR|USD)?",
            r"saldo\s*(?:ko[ńn]cowe|zamkni[ęe]cia)\s*:?\s*([\d\s,.\-]+)",
        ]:
            m = re.search(pat, header, re.I)
            if m:
                result["saldo_koncowe"] = _parse_amount(m.group(1))
                break

    # Available balance
    if info and info.available_balance is not None:
        result["saldo_dostepne"] = info.available_balance
    else:
        avail_patterns = [
            r"saldo\s*dost[ęe]pn[eay]\s*:?\s*([\d\s,.\-]+)",
            r"(?:dost[ęe]pne\s*[śs]rodki)\s*:?\s*([\d\s,.\-]+)",
            r"(?:kwota\s*dost[ęe]pna)\s*:?\s*([\d\s,.\-]+)",
        ]
        for pattern in avail_patterns:
            m = re.search(pattern, text, re.I)
            if m:
                result["saldo_dostepne"] = _parse_amount(m.group(1))
                break

    # Cross-validation sums
    if info and info.declared_credits_sum is not None:
        result["suma_uznan"] = info.declared_credits_sum
    if info and info.declared_debits_sum is not None:
        result["suma_obciazen"] = info.declared_debits_sum

    # Currency
    if info and info.currency and info.currency != "PLN":
        result["waluta"] = info.currency
    else:
        m = re.search(r"waluta\s*(?:rachunku)?\s*:?\s*([A-Z]{3})", header, re.I)
        if m:
            result["waluta"] = m.group(1).upper()
        elif "EUR" in header:
            result["waluta"] = "EUR"
        elif "USD" in header:
            result["waluta"] = "USD"

    # Count transaction-like lines (rough estimate)
    # Use declared count if available
    if info and info.declared_debits_count and info.declared_credits_count:
        result["liczba_transakcji"] = info.declared_debits_count + info.declared_credits_count
    else:
        tx_lines = re.findall(r"^\s*\d{2}[.\-/]\d{2}[.\-/]\d{2,4}", text, re.MULTILINE)
        if tx_lines:
            result["liczba_transakcji"] = len(tx_lines)

    return result
