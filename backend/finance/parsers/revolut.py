"""Revolut bank statement parser.

Handles multi-entity (Revolut Ltd, Revolut Payments UAB, Revolut Bank UAB)
and multi-currency (EUR, PLN, GBP, USD, RON, HRK) statements from a single PDF.

Returns one ParseResult per currency (entities merged chronologically).
Empty sections (no transactions) are skipped.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

from .base import BankParser, ParseResult, RawTransaction, StatementInfo

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SUPPORTED_CURRENCIES = {"EUR", "PLN", "GBP", "USD", "RON", "HRK"}

# Polish month names → month number (abbreviated + full + genitive)
PL_MONTHS: Dict[str, int] = {
    # Abbreviated (used in transaction dates)
    "sty": 1, "lut": 2, "mar": 3, "kwi": 4, "maj": 5, "cze": 6,
    "lip": 7, "sie": 8, "wrz": 9,
    "paź": 10, "pa\u017a": 10, "paz": 10,
    "lis": 11, "gru": 12,
    # Full nominative
    "styczeń": 1, "luty": 2, "marzec": 3, "kwiecień": 4,
    "czerwiec": 6, "lipiec": 7, "sierpień": 8,
    "wrzesień": 9, "październik": 10, "listopad": 11, "grudzień": 12,
    # Genitive (used in period lines: "od 29 sierpnia 2018")
    "stycznia": 1, "lutego": 2, "marca": 3, "kwietnia": 4,
    "maja": 5, "czerwca": 6, "lipca": 7, "sierpnia": 8,
    "września": 9, "października": 10, "listopada": 11, "grudnia": 12,
}

# Build month name alternation for regex (sorted longest-first to avoid partial matches)
_MONTH_NAMES_RE = "|".join(
    sorted(PL_MONTHS.keys(), key=len, reverse=True)
)

# Currency symbols → ISO codes
SYMBOL_TO_CUR: Dict[str, str] = {
    "€": "EUR",
    "£": "GBP",
    "$": "USD",
    "zł": "PLN",
}

# Regex for the page header (present on every page)
_RE_PAGE_HEADER = re.compile(
    r"Wyci[ąa]g\s+(EUR|PLN|GBP|USD|RON|HRK)",
    re.IGNORECASE,
)

# Regex for date in Polish format: "DD MMM YYYY" (abbreviated months in tx lines)
_RE_PL_DATE = re.compile(
    r"^(\d{1,2})\s+"
    r"(" + _MONTH_NAMES_RE + r")\s+"
    r"(\d{4})\b",
    re.IGNORECASE,
)

# Regex for extracting amounts with currency symbol prefix: €15.97, $1,000.00, -$0.61
_RE_AMOUNT_SYMBOL = re.compile(
    r"(-?\s*[€£$])\s*(\d[\d,]*\.\d{2})"
)

# Regex for extracting amounts with currency text suffix: 1,000.00 PLN, 87.84 RON
_RE_AMOUNT_TEXT = re.compile(
    r"(-?\d[\d,]*\.\d{2})\s*(PLN|RON|HRK|EUR|GBP|USD|zł)",
    re.IGNORECASE,
)

# Footer start pattern (strip everything after this on each page)
_RE_FOOTER = re.compile(
    r"Zgłoś\s+kradzież\s+lub\s+utratę\s+karty",
    re.IGNORECASE,
)

# Transaction period: "Transakcje na koncie od DD month YYYY do DD month YYYY"
_RE_PERIOD = re.compile(
    r"Transakcje\s+(?:na\s+koncie|giełdowe)\s+od\s+"
    r"(\d{1,2})\s+(" + _MONTH_NAMES_RE + r")\s+(\d{4})\s+"
    r"do\s+(\d{1,2})\s+(" + _MONTH_NAMES_RE + r")\s+(\d{4})",
    re.IGNORECASE,
)

# Balance summary: "Saldo początkowe ... Saldo końcowe"
_RE_BALANCE_ROW = re.compile(
    r"(?:Konto|Razem)\s.*?(?:Saldo końcowe|$)",
    re.IGNORECASE,
)

# IBAN pattern
_RE_IBAN = re.compile(
    r"IBAN\s+([A-Z]{2}\d{2}[A-Z0-9]{10,30})",
    re.IGNORECASE,
)

# Entity detection
_RE_ENTITY = re.compile(
    r"(Revolut\s+(?:Ltd|Bank\s+UAB|Payments\s+UAB))",
    re.IGNORECASE,
)

# "Reversed" section header
_RE_REVERSED = re.compile(
    r"Cofni[eę]te\s+mi[eę]dzy",
    re.IGNORECASE,
)

# "Exchange transactions" section header
_RE_EXCHANGE_TX = re.compile(
    r"Transakcje\s+giełdowe",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_revolut_date(text: str) -> Optional[str]:
    """Parse Polish abbreviated date 'DD MMM YYYY' → 'YYYY-MM-DD'."""
    m = _RE_PL_DATE.match(text.strip())
    if not m:
        return None
    day, month_str, year = int(m.group(1)), m.group(2).lower(), int(m.group(3))
    month = PL_MONTHS.get(month_str)
    if not month:
        return None
    return f"{year:04d}-{month:02d}-{day:02d}"


def _parse_revolut_date_inline(day: int, month_str: str, year: int) -> str:
    """Convert already-extracted date parts to 'YYYY-MM-DD'."""
    month = PL_MONTHS.get(month_str.lower(), 1)
    return f"{year:04d}-{month:02d}-{day:02d}"


def _extract_amounts_from_line(line: str, section_currency: str) -> List[Tuple[float, str]]:
    """Extract all (amount, currency) pairs from a line.

    Handles both symbol-prefix (€15.97) and text-suffix (1,000.00 PLN) formats.
    Returns amounts in order of appearance (left to right).
    """
    results: List[Tuple[float, str, int]] = []  # (amount, currency, position)

    # Symbol-prefix amounts: €15.97, $1,000.00, -$0.61
    for m in _RE_AMOUNT_SYMBOL.finditer(line):
        sign_and_symbol = m.group(1).replace(" ", "")
        negative = sign_and_symbol.startswith("-")
        symbol = sign_and_symbol.lstrip("-")
        cur = SYMBOL_TO_CUR.get(symbol, section_currency)
        val = float(m.group(2).replace(",", ""))
        if negative:
            val = -val
        results.append((val, cur, m.start()))

    # Text-suffix amounts: 1,000.00 PLN, 87.84 RON
    for m in _RE_AMOUNT_TEXT.finditer(line):
        val_str = m.group(1)
        cur = m.group(2).upper()
        if cur == "ZŁ":
            cur = "PLN"
        val = float(val_str.replace(",", ""))
        # Check for leading minus
        prefix_start = max(0, m.start() - 2)
        prefix = line[prefix_start:m.start()].strip()
        if prefix.endswith("-"):
            val = -val
        # Avoid duplicates (same position already captured by symbol regex)
        if not any(abs(pos - m.start()) < 3 for _, _, pos in results):
            results.append((val, cur, m.start()))

    # Sort by position in line
    results.sort(key=lambda x: x[2])
    return [(amt, cur) for amt, cur, _ in results]


def _strip_footer(text: str) -> str:
    """Remove Revolut page footer text."""
    m = _RE_FOOTER.search(text)
    if m:
        return text[:m.start()].rstrip()
    return text


def _parse_balance_summary(text: str, currency: str) -> Tuple[Optional[float], Optional[float], Optional[float], Optional[float]]:
    """Extract opening_balance, expenses, income, closing_balance from the balance summary.

    Returns: (opening_balance, total_expenses, total_income, closing_balance)
    """
    # Find the summary table line (Konto or Razem)
    lines = text.split("\n")
    for line in lines:
        if not re.search(r"(?:Konto|Razem)", line, re.IGNORECASE):
            continue
        amounts = _extract_amounts_from_line(line, currency)
        if len(amounts) >= 4:
            # Order: opening, expenses, income, closing
            return (
                abs(amounts[0][0]),
                abs(amounts[1][0]),
                abs(amounts[2][0]),
                abs(amounts[3][0]),
            )
        elif len(amounts) >= 2:
            # At least opening and closing
            return (abs(amounts[0][0]), None, None, abs(amounts[-1][0]))
    return (None, None, None, None)


# ---------------------------------------------------------------------------
# Section / page data structures
# ---------------------------------------------------------------------------


class _PageInfo:
    """Info extracted from a single PDF page."""
    __slots__ = ("page_num", "currency", "entity", "text", "is_header",
                 "ibans", "period_from", "period_to",
                 "opening_balance", "closing_balance",
                 "total_expenses", "total_income",
                 "account_holder", "has_reversed", "has_exchange_tx")

    def __init__(self) -> None:
        self.page_num: int = 0
        self.currency: str = ""
        self.entity: str = ""
        self.text: str = ""
        self.is_header: bool = False
        self.ibans: List[str] = []
        self.period_from: Optional[str] = None
        self.period_to: Optional[str] = None
        self.opening_balance: Optional[float] = None
        self.closing_balance: Optional[float] = None
        self.total_expenses: Optional[float] = None
        self.total_income: Optional[float] = None
        self.account_holder: str = ""
        self.has_reversed: bool = False
        self.has_exchange_tx: bool = False


class _Section:
    """A logical section: one (currency, entity) group spanning multiple pages."""
    __slots__ = ("currency", "entity", "ibans", "period_from", "period_to",
                 "opening_balance", "closing_balance",
                 "total_expenses", "total_income",
                 "account_holder", "tx_text")

    def __init__(self) -> None:
        self.currency: str = ""
        self.entity: str = ""
        self.ibans: List[str] = []
        self.period_from: Optional[str] = None
        self.period_to: Optional[str] = None
        self.opening_balance: Optional[float] = None
        self.closing_balance: Optional[float] = None
        self.total_expenses: Optional[float] = None
        self.total_income: Optional[float] = None
        self.account_holder: str = ""
        self.tx_text: str = ""  # concatenated transaction text


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


class RevolutParser(BankParser):
    """Parser for Revolut bank statements (Polish locale).

    Supports multi-entity, multi-currency PDFs.  Returns one ``ParseResult``
    per currency via ``parse_multi()``.
    """

    BANK_NAME = "Revolut"
    BANK_ID = "revolut"

    DETECT_PATTERNS = [
        r"revolut",
        r"revolut\s*(bank|ltd|payments)",
        r"revolut\s*(bank\s*uab|payments\s*uab)",
        r"wyci[ąa]g\s+(eur|pln|gbp|usd|ron|hrk)",
    ]

    # ------------------------------------------------------------------ API

    def parse_tables(
        self,
        tables: List[List[List[str]]],
        full_text: str,
        header_words: Any = None,
    ) -> ParseResult:
        """Revolut doesn't use pdfplumber tables — delegate to text."""
        return self.parse_text(full_text)

    def parse_text(self, text: str) -> ParseResult:
        """Return the single largest-currency result (backward compat)."""
        results = self.parse_multi_text(text)
        if results:
            best = max(results, key=lambda r: len(r.transactions))
            return best
        return ParseResult(bank=self.BANK_NAME)

    def parse_multi(
        self,
        tables: List[List[List[str]]],
        full_text: str,
        header_words: Any = None,
    ) -> List[ParseResult]:
        """Return one ParseResult per currency with transactions."""
        return self.parse_multi_text(full_text)

    # ------------------------------------------------------------ internals

    def parse_multi_text(self, text: str) -> List[ParseResult]:
        """Core multi-currency text parser.

        Parses each entity section independently (with correct opening balance
        for balance-chain direction detection), then merges by currency.
        """
        pages = self._split_into_pages(text)
        if not pages:
            return []

        page_infos = [self._parse_page_info(i, p) for i, p in enumerate(pages)]
        sections = self._group_into_sections(page_infos)

        # Track which currencies had exchange transaction sections
        currencies_with_exchange: set = set()
        for pi in page_infos:
            if pi.has_exchange_tx and pi.currency:
                currencies_with_exchange.add(pi.currency)

        # Parse transactions per-section with opening_balance as initial prev_balance
        section_txns: Dict[str, List[RawTransaction]] = defaultdict(list)
        for sec in sections:
            if not sec.tx_text.strip():
                continue
            txns = self._parse_transactions(
                sec.tx_text, sec.currency, opening_balance=sec.opening_balance,
            )
            section_txns[sec.currency].extend(txns)

        # Merge metadata by currency
        by_currency = self._merge_sections_by_currency(sections)

        results: List[ParseResult] = []
        for currency, merged in sorted(by_currency.items()):
            txns = section_txns.get(currency, [])
            if not txns:
                continue  # skip empty currencies

            # Sort merged transactions chronologically
            txns.sort(key=lambda t: (t.date, 0 if t.amount >= 0 else 1))

            info = StatementInfo(
                bank=self.BANK_NAME,
                account_number=merged["primary_iban"],
                account_holder=merged["account_holder"],
                period_from=merged["period_from"],
                period_to=merged["period_to"],
                opening_balance=merged["opening_balance"],
                closing_balance=merged["closing_balance"],
                currency=currency,
                declared_debits_sum=merged.get("total_expenses"),
                declared_credits_sum=merged.get("total_income"),
            )

            cur_warnings: List[str] = []
            if currency in currencies_with_exchange:
                cur_warnings.append(
                    "INFO: Pominięto transakcje giełdowe/wymiany walut "
                    "— mogą wystąpić przerwania w łańcuchu sald"
                )

            result = ParseResult(
                bank=self.BANK_NAME,
                info=info,
                transactions=txns,
                warnings=cur_warnings,
                parse_method="text_revolut",
            )
            results.append(result)

        return results

    # ------------------------------------------------- page splitting

    @staticmethod
    def _split_into_pages(text: str) -> List[str]:
        """Split full_text into per-page chunks using Revolut page headers."""
        # pdfplumber joins pages with \n\n, but pages themselves may contain \n\n
        # Use the repeating "Wyciąg {CUR}\nWygenerowano" header as boundary
        pattern = re.compile(
            r"(?=Wyci[ąa]g\s+(?:EUR|PLN|GBP|USD|RON|HRK)\s*\n\s*Wygenerowano)",
            re.IGNORECASE,
        )
        parts = pattern.split(text)
        # First element may be empty or preamble
        pages = [p.strip() for p in parts if p.strip()]
        # Filter: each page should start with "Wyciąg"
        return [p for p in pages if _RE_PAGE_HEADER.match(p)]

    @staticmethod
    def _parse_page_info(idx: int, page_text: str) -> _PageInfo:
        """Extract metadata from a single page."""
        pi = _PageInfo()
        pi.page_num = idx
        pi.text = page_text

        lines = page_text.split("\n")

        # Currency from first line
        m = _RE_PAGE_HEADER.match(lines[0] if lines else "")
        if m:
            pi.currency = m.group(1).upper()

        # Entity from early lines (usually line 3)
        for line in lines[:5]:
            em = _RE_ENTITY.search(line)
            if em:
                pi.entity = em.group(1).strip()
                break

        # IBANs
        pi.ibans = _RE_IBAN.findall(page_text)

        # Account holder (name after entity, before IBAN block)
        # Usually the line after "Wygenerowano..." and entity
        if len(lines) > 3:
            for i in range(3, min(6, len(lines))):
                candidate = lines[i].strip()
                if candidate and not candidate.startswith("IBAN") and not candidate.startswith("Podwodna") and not re.match(r"^\d", candidate):
                    # Check it's a name (contains uppercase letters, no keywords)
                    if re.match(r"^[A-ZĄĆĘŁŃÓŚŹŻ ]+$", candidate):
                        pi.account_holder = candidate
                        break

        # Is this a header page? (has "Zestawienie sald")
        pi.is_header = "Zestawienie sald" in page_text

        # Balance summary
        if pi.is_header:
            opening, expenses, income, closing = _parse_balance_summary(page_text, pi.currency)
            pi.opening_balance = opening
            pi.closing_balance = closing
            pi.total_expenses = expenses
            pi.total_income = income

        # Period
        pm = _RE_PERIOD.search(page_text)
        if pm:
            pi.period_from = _parse_revolut_date_inline(
                int(pm.group(1)), pm.group(2), int(pm.group(3))
            )
            pi.period_to = _parse_revolut_date_inline(
                int(pm.group(4)), pm.group(5), int(pm.group(6))
            )

        # Special sections
        pi.has_reversed = bool(_RE_REVERSED.search(page_text))
        pi.has_exchange_tx = bool(_RE_EXCHANGE_TX.search(page_text))

        return pi

    @staticmethod
    def _group_into_sections(page_infos: List[_PageInfo]) -> List[_Section]:
        """Group consecutive pages with same (currency, entity) into sections."""
        sections: List[_Section] = []
        current: Optional[_Section] = None

        for pi in page_infos:
            key = (pi.currency, pi.entity)

            if current is None or (pi.currency, pi.entity) != (current.currency, current.entity):
                # New section
                if pi.is_header or current is None or pi.currency != (current.currency if current else ""):
                    current = _Section()
                    current.currency = pi.currency
                    current.entity = pi.entity
                    sections.append(current)

            # Merge page data into current section
            if pi.ibans and not current.ibans:
                current.ibans = pi.ibans
            if pi.account_holder and not current.account_holder:
                current.account_holder = pi.account_holder
            if pi.period_from and not current.period_from:
                current.period_from = pi.period_from
            if pi.period_to and not current.period_to:
                current.period_to = pi.period_to
            if pi.is_header:
                current.opening_balance = pi.opening_balance
                current.closing_balance = pi.closing_balance
                current.total_expenses = pi.total_expenses
                current.total_income = pi.total_income

            # Extract transaction text (strip header and footer)
            tx_text = _strip_footer(pi.text)
            # Find "Data Opis" table header — everything after it is transaction data
            tx_start = re.search(r"(?:^|\n)(Data\s+(?:Opis|rozpoczęcia)\s)", tx_text)
            if tx_start:
                # Check if "Cofnięte" (reversed) marker appears before
                # the "Data Opis" header on this page.  If so we must
                # re-inject the marker so _parse_transactions can skip
                # the reversed block — the header search would otherwise
                # strip it out.
                pre_text = tx_text[:tx_start.start()]
                has_cofniete_before = bool(_RE_REVERSED.search(pre_text))

                # Skip the "Data Opis Wydatki Wpływy Saldo" header line itself
                header_end = tx_text.find("\n", tx_start.start() + 1)
                if header_end > 0:
                    tx_text = tx_text[header_end + 1:]
                else:
                    tx_text = ""

                # Prepend the reversed marker if it was above the header
                if has_cofniete_before and tx_text.strip():
                    tx_text = "Cofnięte między\n" + tx_text
            else:
                # No transaction table on this page
                tx_text = ""

            if tx_text.strip():
                current.tx_text += tx_text + "\n"

        return sections

    @staticmethod
    def _merge_sections_by_currency(
        sections: List[_Section],
    ) -> Dict[str, Dict[str, Any]]:
        """Merge sections with the same currency (from different entities)."""
        by_cur: Dict[str, Dict[str, Any]] = {}

        for sec in sections:
            cur = sec.currency
            if cur not in by_cur:
                by_cur[cur] = {
                    "primary_iban": "",
                    "all_ibans": [],
                    "account_holder": "",
                    "period_from": None,
                    "period_to": None,
                    "opening_balance": None,
                    "closing_balance": None,
                    "total_expenses": 0.0,
                    "total_income": 0.0,
                    "tx_text": "",
                    "entities": [],
                }

            merged = by_cur[cur]
            merged["entities"].append(sec.entity)

            # Collect IBANs — prefer currency-specific prefix (PL for PLN, etc.)
            if sec.ibans:
                merged["all_ibans"].extend(sec.ibans)
                if not merged["primary_iban"]:
                    # First pass: currency-specific IBAN
                    _cur_prefix = {"PLN": "PL", "RON": "RO", "GBP": "GB",
                                   "EUR": "LT", "USD": "LT", "HRK": "LT"}
                    prefix = _cur_prefix.get(cur, "")
                    for iban in sec.ibans:
                        iban_upper = iban.upper()
                        # Skip IBANs with "nie można używać" warning (GB IBAN in non-GBP)
                        if prefix and iban_upper.startswith(prefix):
                            merged["primary_iban"] = iban
                            break
                    # Fallback: LT IBAN (always present)
                    if not merged["primary_iban"]:
                        for iban in sec.ibans:
                            if iban.upper().startswith("LT"):
                                merged["primary_iban"] = iban
                                break
                    if not merged["primary_iban"]:
                        merged["primary_iban"] = sec.ibans[0]

            if sec.account_holder:
                merged["account_holder"] = sec.account_holder

            # Period: earliest from, latest to
            if sec.period_from:
                if merged["period_from"] is None or sec.period_from < merged["period_from"]:
                    merged["period_from"] = sec.period_from
            if sec.period_to:
                if merged["period_to"] is None or sec.period_to > merged["period_to"]:
                    merged["period_to"] = sec.period_to

            # Balance: opening from first entity with transactions, closing from last
            if sec.opening_balance is not None:
                if merged["opening_balance"] is None:
                    merged["opening_balance"] = sec.opening_balance
            if sec.closing_balance is not None:
                merged["closing_balance"] = sec.closing_balance

            # Accumulate totals
            if sec.total_expenses is not None:
                merged["total_expenses"] = (merged.get("total_expenses") or 0) + sec.total_expenses
            if sec.total_income is not None:
                merged["total_income"] = (merged.get("total_income") or 0) + sec.total_income

            # Concatenate transaction text
            if sec.tx_text.strip():
                merged["tx_text"] += sec.tx_text + "\n"

        return by_cur

    def _parse_transactions(
        self,
        tx_text: str,
        section_currency: str,
        opening_balance: Optional[float] = None,
    ) -> List[RawTransaction]:
        """Parse transaction lines into RawTransaction objects.

        Args:
            tx_text: Transaction text to parse.
            section_currency: Currency code (EUR, PLN, etc.).
            opening_balance: Section's opening balance for direction detection.

        Handles:
        - Date lines: "DD MMM YYYY  Description  AMOUNT  BALANCE"
        - Continuation lines: "Do:", "Karta:", "Od:", "Kurs Revolut:", etc.
        - Reversed sections (no balance column)
        - Exchange transaction sections
        """
        if not tx_text.strip():
            return []

        lines = tx_text.split("\n")
        raw_blocks: List[Dict[str, Any]] = []
        current_block: Optional[Dict[str, Any]] = None
        in_reversed_section = False

        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue

            # Check for reversed section header
            if _RE_REVERSED.search(stripped):
                in_reversed_section = True
                continue

            # "Transakcje giełdowe" (exchange/investment transactions) are
            # tracked in a separate balance chain and are NOT included in
            # the declared "Konto" totals — stop parsing here.
            if _RE_EXCHANGE_TX.match(stripped):
                break

            # Check for normal transaction section header (resets reversed mode)
            if re.match(r"Transakcje\s+na\s+koncie", stripped, re.IGNORECASE):
                in_reversed_section = False
                continue

            # Skip "Data Opis" / "Data rozpoczęcia" table headers
            if re.match(r"Data\s+(?:Opis|rozpoczęcia)\s", stripped):
                continue

            # Skip balance summary / disclaimer lines
            if any(kw in stripped for kw in [
                "Zestawienie sald", "Saldo początkowe",
                "Gdzie przekazywane", "Saldo na wyciągu",
                "\u00a9 20",
            ]):
                continue
            # "Produkt" and "Razem" can appear in counterparty names — only
            # skip when at line start (balance summary context)
            if re.match(r"(Produkt\s|Razem\s)", stripped):
                continue

            # Skip reversed section transactions entirely (they are
            # already reflected in the balance and declared totals)
            if in_reversed_section:
                continue

            # Try to match date line
            dm = _RE_PL_DATE.match(stripped)
            if dm:
                # Start a new transaction block
                date_str = _parse_revolut_date_inline(
                    int(dm.group(1)), dm.group(2), int(dm.group(3))
                )
                rest = stripped[dm.end():].strip()

                # Extract amounts from the rest of the line
                amounts = _extract_amounts_from_line(rest, section_currency)

                # Separate description from amounts
                # Description is the text before the first amount
                desc = rest
                if amounts:
                    # Find first amount position in the rest string
                    first_amt_patterns = []
                    for amt_val, amt_cur in amounts:
                        # Build patterns to find the first amount
                        if amt_cur in SYMBOL_TO_CUR.values():
                            for sym, c in SYMBOL_TO_CUR.items():
                                if c == amt_cur:
                                    first_amt_patterns.append(re.escape(sym))
                        first_amt_patterns.append(
                            re.escape(f"{abs(amt_val):,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
                        )
                        first_amt_patterns.append(
                            re.escape(f"{abs(amt_val):,.2f}")
                        )

                    # Find where amounts start in the rest string
                    # Use simpler approach: find first numeric amount pattern
                    amt_match = re.search(
                        r"[-]?\s*[€£$]\s*\d|[-]?\d[\d,]*\.\d{2}\s*(?:PLN|RON|HRK|EUR|GBP|USD|zł)",
                        rest,
                        re.IGNORECASE,
                    )
                    if amt_match:
                        desc = rest[:amt_match.start()].strip()

                current_block = {
                    "date": date_str,
                    "description": desc,
                    "amounts": amounts,
                    "continuation": [],
                    "reversed": in_reversed_section,
                    "raw_text": stripped,
                }
                raw_blocks.append(current_block)

            elif current_block is not None:
                # Continuation line
                current_block["continuation"].append(stripped)
                current_block["raw_text"] += "\n" + stripped
            # else: orphan line before first transaction — skip

        # Convert blocks to RawTransaction objects
        transactions: List[RawTransaction] = []
        prev_balance: Optional[float] = opening_balance

        for block in raw_blocks:
            tx = self._block_to_transaction(
                block, section_currency, prev_balance
            )
            if tx is not None:
                transactions.append(tx)
                if tx.balance_after is not None:
                    prev_balance = tx.balance_after

        return transactions

    def _block_to_transaction(
        self,
        block: Dict[str, Any],
        section_currency: str,
        prev_balance: Optional[float],
    ) -> Optional[RawTransaction]:
        """Convert a parsed block into a RawTransaction."""
        amounts = block["amounts"]
        is_reversed = block["reversed"]

        if not amounts:
            return None

        # Parse continuation lines for counterparty and card info
        counterparty = ""
        title_parts = [block["description"]]
        card_info = ""
        exchange_info = ""
        fee_amount: float = 0.0  # fee from "Opłata:" lines

        for cont in block["continuation"]:
            # "Do: Name, City" or "Od: *6172"
            m_do = re.match(r"Do:\s*(.+)", cont, re.IGNORECASE)
            m_od = re.match(r"Od:\s*(.+)", cont, re.IGNORECASE)
            m_card = re.match(r"Karta:\s*(.+)", cont, re.IGNORECASE)
            m_kurs = re.match(r"Kurs\s+Revolut:\s*(.+)", cont, re.IGNORECASE)
            m_dane = re.match(r"Dane\s+referencyjne:\s*(.+)", cont, re.IGNORECASE)
            m_fee = re.match(r"Op[łl]ata:\s*(.+)", cont, re.IGNORECASE)

            if m_do:
                counterparty = m_do.group(1).strip()
            elif m_od:
                counterparty = m_od.group(1).strip()
            elif m_card:
                card_info = m_card.group(1).strip()
            elif m_kurs:
                exchange_info = m_kurs.group(1).strip()
            elif m_dane:
                title_parts.append(f"Ref: {m_dane.group(1).strip()}")
            elif m_fee:
                # "Opłata: $0.15 $15.02" → fee = first amount
                fee_parts = _extract_amounts_from_line(m_fee.group(1), section_currency)
                if fee_parts:
                    fee_amount = abs(fee_parts[0][0])
            else:
                # Other continuation (e.g., "Purchase of BTC", "Sell of FLR",
                # exchange amount like "68.18 PLN", "€15.97")
                # Check if it's just an amount line (from exchange)
                cont_amounts = _extract_amounts_from_line(cont, section_currency)
                if cont_amounts:
                    # Exchange amount — add to title for context
                    title_parts.append(cont.strip())
                elif cont.strip():
                    title_parts.append(cont.strip())

        # Determine amount and balance
        if is_reversed:
            # Reversed transactions: no balance column
            # amounts[0] = the transaction amount (always positive in the table)
            amount = -abs(amounts[0][0])  # reversed = negative
            balance_after = None
        elif len(amounts) >= 2:
            # Normal: last amount = balance, second-to-last = transaction amount
            balance_after = amounts[-1][0]
            tx_amount = amounts[-2][0]

            # Determine direction from balance change
            if prev_balance is not None:
                diff = balance_after - prev_balance
                if diff > 0:
                    # Income
                    amount = abs(tx_amount)
                else:
                    # Expense
                    amount = -abs(tx_amount)
            else:
                # First transaction — if only one amount before balance,
                # check if balance equals the amount (income) or not
                if abs(balance_after - abs(tx_amount)) < 0.01:
                    amount = abs(tx_amount)  # income (first tx = opening + amount)
                elif abs(balance_after + abs(tx_amount)) < 0.01:
                    amount = -abs(tx_amount)  # expense
                else:
                    # Heuristic: if balance is positive and similar to amount → income
                    amount = abs(tx_amount) if balance_after > 0 else -abs(tx_amount)
        elif len(amounts) == 1:
            # Single amount — likely reversed or special
            amount = amounts[0][0]
            balance_after = None
        else:
            return None

        title = " | ".join(t for t in title_parts if t)
        if fee_amount > 0:
            title += f" [Opłata: {fee_amount:.2f}]"
        if card_info:
            title += f" [Karta: {card_info}]"
        if exchange_info:
            title += f" [Kurs: {exchange_info}]"

        return RawTransaction(
            date=block["date"],
            amount=round(amount, 2),
            currency=section_currency,
            balance_after=round(balance_after, 2) if balance_after is not None else None,
            counterparty=counterparty or block["description"],
            title=title,
            raw_text=block["raw_text"],
            direction="in" if amount >= 0 else "out",
            bank_category="",
        )
