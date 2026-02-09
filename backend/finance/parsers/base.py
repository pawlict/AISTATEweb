"""Base class and data structures for bank statement parsers."""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class RawTransaction:
    """Single normalized transaction from a bank statement."""

    date: str  # YYYY-MM-DD
    date_valuation: Optional[str] = None  # YYYY-MM-DD (data waluty)
    amount: float = 0.0  # negative = outflow, positive = inflow
    currency: str = "PLN"
    balance_after: Optional[float] = None
    counterparty: str = ""
    title: str = ""
    raw_text: str = ""  # original row text for debugging
    direction: str = ""  # "in" or "out" (auto-filled if empty)
    bank_category: str = ""  # category from bank if available

    def __post_init__(self):
        if not self.direction:
            self.direction = "in" if self.amount >= 0 else "out"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class StatementInfo:
    """Metadata about the bank statement."""

    bank: str = ""
    account_number: str = ""
    account_holder: str = ""
    period_from: Optional[str] = None  # YYYY-MM-DD
    period_to: Optional[str] = None
    opening_balance: Optional[float] = None
    closing_balance: Optional[float] = None
    available_balance: Optional[float] = None
    currency: str = "PLN"
    raw_header: str = ""
    # Cross-validation fields (from header summary)
    declared_credits_sum: Optional[float] = None  # Suma uznań
    declared_credits_count: Optional[int] = None
    declared_debits_sum: Optional[float] = None   # Suma obciążeń
    declared_debits_count: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ParseResult:
    """Complete result of parsing a bank statement."""

    bank: str = ""
    info: StatementInfo = field(default_factory=StatementInfo)
    transactions: List[RawTransaction] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    page_count: int = 0
    parse_method: str = ""  # "table" or "text" or "ocr"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "bank": self.bank,
            "info": self.info.to_dict(),
            "transactions": [t.to_dict() for t in self.transactions],
            "warnings": self.warnings,
            "page_count": self.page_count,
            "parse_method": self.parse_method,
        }


class BankParser(ABC):
    """Abstract bank statement parser."""

    # Subclass must set these
    BANK_NAME: str = ""
    BANK_ID: str = ""
    # Regex patterns matched against first 2 pages of text (case-insensitive)
    DETECT_PATTERNS: List[str] = []

    @classmethod
    def can_parse(cls, header_text: str) -> float:
        """Return confidence 0.0-1.0 that this parser handles the document.

        header_text is extracted text from first 2 pages.
        """
        if not cls.DETECT_PATTERNS:
            return 0.0
        text = header_text.lower()
        hits = sum(1 for p in cls.DETECT_PATTERNS if re.search(p, text))
        return min(hits / max(len(cls.DETECT_PATTERNS), 1), 1.0)

    @abstractmethod
    def parse_tables(self, tables: List[List[List[str]]], full_text: str) -> ParseResult:
        """Parse from pdfplumber tables (preferred path)."""
        ...

    @abstractmethod
    def parse_text(self, text: str) -> ParseResult:
        """Fallback: parse from raw extracted text."""
        ...

    def parse(self, tables: List[List[List[str]]], full_text: str) -> ParseResult:
        """Try table parse first, fall back to text."""
        result = self.parse_tables(tables, full_text)
        if result.transactions:
            result.parse_method = "table"
            return result
        result = self.parse_text(full_text)
        if not result.parse_method:
            result.parse_method = "text"
        return result

    # --- Common header extraction (works for all Polish banks) ---

    @staticmethod
    def extract_info_common(text: str, bank_name: str = "") -> StatementInfo:
        """Extract statement metadata using broad patterns that work across banks.

        This handles multiple formats:
        - "Nr 9 / 01.09.2025 - 30.09.2025" (ING)
        - "Okres: 01.09.2025 - 30.09.2025"
        - "od 01.09.2025 do 30.09.2025"
        - Multi-line saldo labels
        - Suma uznań/obciążeń for cross-validation
        """
        info = StatementInfo(bank=bank_name)

        # --- Account number (26-digit IBAN) ---
        m = re.search(r"(\d{2}\s?\d{4}\s?\d{4}\s?\d{4}\s?\d{4}\s?\d{4}\s?\d{4})", text)
        if m:
            info.account_number = m.group(1).replace(" ", "")

        # --- Period: multiple formats ---
        period_patterns = [
            # "Nr X / DD.MM.YYYY - DD.MM.YYYY" (ING style)
            r"Nr\s*\d+\s*/\s*(\d{2}[.\-/]\d{2}[.\-/]\d{4})\s*[-–]\s*(\d{2}[.\-/]\d{2}[.\-/]\d{4})",
            # "okres: DD.MM.YYYY - DD.MM.YYYY" or "za okres DD.MM.YYYY do DD.MM.YYYY"
            r"(?:okres|za\s*okres|od)\s*:?\s*(\d{2}[.\-/]\d{2}[.\-/]\d{4})\s*(?:[-–]|do)\s*(\d{2}[.\-/]\d{2}[.\-/]\d{4})",
            # "wyciąg za DD.MM.YYYY - DD.MM.YYYY"
            r"wyci[ąa]g\s*(?:za|nr[^/]*/)?\s*(\d{2}[.\-/]\d{2}[.\-/]\d{4})\s*[-–]\s*(\d{2}[.\-/]\d{2}[.\-/]\d{4})",
        ]
        for pat in period_patterns:
            m = re.search(pat, text, re.I)
            if m:
                info.period_from = BankParser.parse_date(m.group(1))
                info.period_to = BankParser.parse_date(m.group(2))
                break

        # --- Opening balance: multiple patterns ---
        # Simple patterns first (label + amount on same or next line via \s* crossing newlines),
        # then multi-line fallback with [^\n\d]* to avoid consuming digits from the label line.
        opening_patterns = [
            # Simple: "Saldo początkowe: 5 000,00" or "Saldo początkowe:\n5 000,00"
            r"saldo\s*(?:pocz[ąa]tkowe|otwarcia)\s*:?\s*([\d\s,.\-]+)",
            # ING: "Saldo końcowe poprzedniego wyciągu...\n...\n1 053,83 PLN"
            r"saldo\s*ko[ńn]cowe\s*poprzedniego\s*wyci[ąa]gu[^\n\d]*(?:\n[^\n\d]*){0,2}?\s*([\d\s]+[,\.]\d{2})\s*(?:PLN|EUR|USD)?",
            # Multi-line fallback: label on one line, amount 1-2 lines later
            r"saldo\s*pocz[ąa]tkowe[^\n\d]*(?:\n[^\n\d]*){0,2}?\s*([\d\s]+[,\.]\d{2})\s*(?:PLN|EUR|USD)?",
        ]
        for pat in opening_patterns:
            m = re.search(pat, text, re.I)
            if m:
                val = BankParser.parse_amount(m.group(1))
                if val is not None:
                    info.opening_balance = val
                    break

        # --- Closing balance ---
        # IMPORTANT: exclude "saldo końcowe poprzedniego wyciągu" — that's the opening balance!
        closing_patterns = [
            # Simple: "Saldo końcowe: 3 245,50" or "Saldo końcowe:\n138,49"
            r"saldo\s*(?:ko[ńn]cowe(?!\s*poprzedniego)|zamkni[ęe]cia)\s*:?\s*([\d\s,.\-]+)",
            # Multi-line fallback (no digit consumption in filler)
            r"saldo\s*ko[ńn]cowe(?!\s*poprzedniego)[^\n\d]*(?:\n[^\n\d]*){0,2}?\s*([\d\s]+[,\.]\d{2})\s*(?:PLN|EUR|USD)?",
        ]
        for pat in closing_patterns:
            m = re.search(pat, text, re.I)
            if m:
                val = BankParser.parse_amount(m.group(1))
                if val is not None:
                    info.closing_balance = val
                    break

        # --- Available balance ---
        avail_patterns = [
            r"saldo\s*dost[ęe]pn[eay]\s*:?\s*([\d\s,.\-]+)",
            r"(?:dost[ęe]pne\s*[śs]rodki)\s*:?\s*([\d\s,.\-]+)",
            r"(?:kwota\s*dost[ęe]pna)\s*:?\s*([\d\s,.\-]+)",
        ]
        for pat in avail_patterns:
            m = re.search(pat, text, re.I)
            if m:
                val = BankParser.parse_amount(m.group(1))
                if val is not None:
                    info.available_balance = val
                    break

        # --- Cross-validation: Suma uznań / Suma obciążeń ---
        # "Suma uznań (11): 20 934,74 PLN"
        m = re.search(r"suma\s*uzna[ńn]\s*\((\d+)\)\s*:?\s*([\d\s,.\-]+)", text, re.I)
        if m:
            info.declared_credits_count = int(m.group(1))
            info.declared_credits_sum = BankParser.parse_amount(m.group(2))

        # "Suma obciążeń (182): 21 850,08 PLN"
        m = re.search(r"suma\s*obci[ąa][żz]e[ńn]\s*\((\d+)\)\s*:?\s*([\d\s,.\-]+)", text, re.I)
        if m:
            info.declared_debits_count = int(m.group(1))
            info.declared_debits_sum = BankParser.parse_amount(m.group(2))

        # --- Currency ---
        m = re.search(r"waluta\s*(?:rachunku)?\s*:?\s*([A-Z]{3})", text, re.I)
        if m:
            info.currency = m.group(1).upper()

        # --- Account holder ---
        holder_patterns = [
            r"(?:w[łl]a[śs]ciciel|posiadacz)\s*(?:rachunku)?\s*:?\s*([A-ZĄĆĘŁŃÓŚŹŻ][a-ząćęłńóśźż]+(?:\s+[A-ZĄĆĘŁŃÓŚŹŻ][a-ząćęłńóśźż\-]+){1,3})",
            # "Dane posiadacza\nIMIĘ NAZWISKO\nULICA..." — capture only first line after label
            r"(?:dane\s*posiadacza)[^\n]*\n\s*([^\n]+)",
        ]
        for pat in holder_patterns:
            m = re.search(pat, text, re.I)
            if m:
                name = m.group(1).strip()
                # Remove trailing digits/postal codes that might be address fragments
                name = re.sub(r"\s*\d{2}[-\s]?\d{3}\s*.*$", "", name).strip()
                words = name.split()
                if 2 <= len(words) <= 4 and len(name) < 60:
                    # Ensure each word looks like a name (starts with uppercase letter)
                    if all(w[0].isupper() for w in words if w):
                        info.account_holder = name
                        break

        return info

    # --- Helpers for subclasses ---

    @staticmethod
    def resolve_amount_from_row(
        row: List[str],
        col_map: Dict[str, int],
    ) -> Optional[float]:
        """Resolve transaction amount from a row, handling dual debit/credit columns.

        Checks for separate 'debit' and 'credit' columns first.  Falls back to
        a single 'amount' column.  Returns negative for debits, positive for credits.
        """
        debit_idx = col_map.get("debit")
        credit_idx = col_map.get("credit")

        if debit_idx is not None or credit_idx is not None:
            debit_val = None
            credit_val = None
            if debit_idx is not None and debit_idx < len(row):
                debit_val = BankParser.parse_amount(row[debit_idx])
            if credit_idx is not None and credit_idx < len(row):
                credit_val = BankParser.parse_amount(row[credit_idx])

            if credit_val is not None and credit_val != 0:
                return abs(credit_val)
            if debit_val is not None and debit_val != 0:
                return -abs(debit_val)
            # Both columns present but empty/zero — try single amount column as fallback
            if col_map.get("amount") is not None and col_map["amount"] < len(row):
                return BankParser.parse_amount(row[col_map["amount"]])
            return None

        # Single amount column
        if col_map.get("amount") is not None and col_map["amount"] < len(row):
            return BankParser.parse_amount(row[col_map["amount"]])
        return None

    @staticmethod
    def find_debit_credit_columns(header: List[str]) -> Dict[str, int]:
        """Detect separate debit and credit columns in a table header.

        Returns dict with 'debit' and/or 'credit' keys mapped to column indices.
        """
        result: Dict[str, int] = {}
        for i, cell in enumerate(header):
            cell_l = (cell or "").lower().strip()
            if re.search(r"obci[ąa][żz]|wyp[łl]at|debit|wydatki|ma$", cell_l):
                result["debit"] = i
            elif re.search(r"uzna|wp[łl]at|credit|wp[łl]yw|wn$", cell_l):
                result["credit"] = i
        return result

    @staticmethod
    def parse_amount(text: str) -> Optional[float]:
        """Parse Polish-format amount: '1 234,56' or '-1234.56' etc."""
        if not text or not text.strip():
            return None
        s = text.strip().replace("\xa0", " ").replace(" ", "")
        # Handle Polish notation: comma as decimal separator
        s = re.sub(r"[^\d,.\-+]", "", s)
        if "," in s and "." in s:
            # 1.234,56 -> 1234.56
            s = s.replace(".", "").replace(",", ".")
        elif "," in s:
            s = s.replace(",", ".")
        try:
            return float(s)
        except ValueError:
            return None

    @staticmethod
    def parse_date(text: str, year_hint: Optional[int] = None) -> Optional[str]:
        """Parse date from various Polish formats to YYYY-MM-DD."""
        if not text or not text.strip():
            return None
        s = text.strip()

        # YYYY-MM-DD
        m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
        if m:
            return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"

        # DD.MM.YYYY or DD-MM-YYYY or DD/MM/YYYY
        m = re.match(r"(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{4})", s)
        if m:
            return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"

        # DD.MM.YY
        m = re.match(r"(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{2})$", s)
        if m:
            yy = int(m.group(3))
            year = 2000 + yy if yy < 80 else 1900 + yy
            return f"{year}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"

        # DD.MM (no year)
        m = re.match(r"(\d{1,2})[.\-/](\d{1,2})$", s)
        if m and year_hint:
            return f"{year_hint}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"

        return None

    @staticmethod
    def clean_text(text: str) -> str:
        """Normalize whitespace in transaction text."""
        if not text:
            return ""
        return re.sub(r"\s+", " ", text).strip()

    @staticmethod
    def parse_text_multiline(text: str) -> List[RawTransaction]:
        """Parse transactions from raw text, handling multi-line descriptions.

        Splits text into logical transaction blocks: a block starts with a line
        beginning with a date, and includes all subsequent non-date lines as
        continuation of the description.  Amounts are extracted from the last
        numeric values on any line in the block.
        """
        DATE_RE = re.compile(r"^(\d{2}[.\-/]\d{2}[.\-/]\d{2,4})")
        AMOUNT_RE = re.compile(r"([\-+]?\d[\d\s]*[,\.]\d{2})")

        lines = text.split("\n")
        blocks: List[List[str]] = []
        current: List[str] = []

        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            if DATE_RE.match(stripped):
                if current:
                    blocks.append(current)
                current = [stripped]
            elif current:
                current.append(stripped)
        if current:
            blocks.append(current)

        transactions: List[RawTransaction] = []
        for block in blocks:
            first_line = block[0]
            dm = DATE_RE.match(first_line)
            if not dm:
                continue
            date_str = BankParser.parse_date(dm.group(1))
            if not date_str:
                continue

            # Collect all text and find amounts
            full_block = " ".join(block)
            amounts_found = AMOUNT_RE.findall(full_block)
            if not amounts_found:
                continue

            # Last numeric value(s) are amount and possibly balance
            amount = BankParser.parse_amount(amounts_found[-1])
            balance = None
            if len(amounts_found) >= 2:
                # Could be: amount + balance or just multiple amounts
                candidate_amount = BankParser.parse_amount(amounts_found[-2])
                candidate_balance = amount
                # If the last value is larger (looks like a balance), swap
                if candidate_amount is not None and candidate_balance is not None:
                    if abs(candidate_balance) > abs(candidate_amount) * 2:
                        amount = candidate_amount
                        balance = candidate_balance

            if amount is None:
                continue

            # Everything between date and amounts is the description
            desc_text = full_block[dm.end():]
            # Remove the amount strings from description
            for a in amounts_found:
                desc_text = desc_text.replace(a, "", 1)
            desc_text = BankParser.clean_text(desc_text)

            transactions.append(RawTransaction(
                date=date_str,
                amount=amount,
                balance_after=balance,
                title=desc_text,
                raw_text=full_block[:200],
            ))

        return transactions


def validate_balance_chain(
    transactions: List[RawTransaction],
    opening_balance: Optional[float],
    closing_balance: Optional[float],
    tolerance: float = 0.02,
    declared_credits_sum: Optional[float] = None,
    declared_debits_sum: Optional[float] = None,
    declared_credits_count: Optional[int] = None,
    declared_debits_count: Optional[int] = None,
) -> Tuple[bool, List[str]]:
    """Verify parsed data against declared statement values.

    Checks:
    1. opening_balance + sum(amounts) ≈ closing_balance
    2. Per-transaction balance_after chain consistency
    3. Sum of credits vs declared suma uznań
    4. Sum of debits vs declared suma obciążeń
    5. Transaction count vs declared count

    Returns:
        (is_valid, list_of_warnings)
    """
    warnings: List[str] = []
    is_valid = True

    if opening_balance is None or closing_balance is None:
        warnings.append("Brak salda początkowego lub końcowego — walidacja niemożliwa")
        return True, warnings

    computed_closing = opening_balance + sum(t.amount for t in transactions)
    diff = abs(computed_closing - closing_balance)

    if diff > tolerance:
        warnings.append(
            f"ROZBIEŻNOŚĆ SALD: obliczone saldo końcowe = {computed_closing:,.2f}, "
            f"deklarowane = {closing_balance:,.2f}, "
            f"różnica = {diff:,.2f} PLN"
        )
        is_valid = False

    # Per-transaction balance_after chain check
    prev_balance = opening_balance
    chain_breaks = 0
    for i, t in enumerate(transactions):
        if t.balance_after is not None and prev_balance is not None:
            expected = prev_balance + t.amount
            txn_diff = abs(expected - t.balance_after)
            if txn_diff > tolerance:
                chain_breaks += 1
                if chain_breaks <= 5:
                    warnings.append(
                        f"Transakcja #{i+1} ({t.date}): oczekiwane saldo "
                        f"{expected:,.2f}, odczytane {t.balance_after:,.2f} "
                        f"(różnica {txn_diff:,.2f})"
                    )
            prev_balance = t.balance_after
        elif t.balance_after is not None:
            prev_balance = t.balance_after

    if chain_breaks > 5:
        warnings.append(f"...i {chain_breaks - 5} kolejnych rozbieżności w łańcuchu sald")

    if chain_breaks > 0:
        is_valid = False
        warnings.insert(0, f"Wykryto {chain_breaks} przerwań w łańcuchu sald transakcji")

    # Cross-validation: suma uznań / suma obciążeń
    parsed_credits = sum(t.amount for t in transactions if t.amount > 0)
    parsed_debits = sum(abs(t.amount) for t in transactions if t.amount < 0)
    parsed_credits_count = sum(1 for t in transactions if t.amount > 0)
    parsed_debits_count = sum(1 for t in transactions if t.amount < 0)

    if declared_credits_sum is not None:
        credits_diff = abs(parsed_credits - declared_credits_sum)
        if credits_diff > tolerance:
            warnings.append(
                f"SUMA UZNAŃ: sparsowano {parsed_credits:,.2f}, "
                f"deklarowane {declared_credits_sum:,.2f}, "
                f"różnica {credits_diff:,.2f} PLN"
            )
            is_valid = False
        else:
            warnings.append(f"Suma uznań: OK ({parsed_credits:,.2f} ✓)")

    if declared_debits_sum is not None:
        debits_diff = abs(parsed_debits - declared_debits_sum)
        if debits_diff > tolerance:
            warnings.append(
                f"SUMA OBCIĄŻEŃ: sparsowano {parsed_debits:,.2f}, "
                f"deklarowane {declared_debits_sum:,.2f}, "
                f"różnica {debits_diff:,.2f} PLN"
            )
            is_valid = False
        else:
            warnings.append(f"Suma obciążeń: OK ({parsed_debits:,.2f} ✓)")

    if declared_credits_count is not None:
        if parsed_credits_count != declared_credits_count:
            warnings.append(
                f"LICZBA UZNAŃ: sparsowano {parsed_credits_count}, "
                f"deklarowane {declared_credits_count}"
            )
            is_valid = False

    if declared_debits_count is not None:
        if parsed_debits_count != declared_debits_count:
            warnings.append(
                f"LICZBA OBCIĄŻEŃ: sparsowano {parsed_debits_count}, "
                f"deklarowane {declared_debits_count}"
            )
            is_valid = False

    return is_valid, warnings
