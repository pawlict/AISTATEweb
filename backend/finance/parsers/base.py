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

    # --- Helpers for subclasses ---

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
