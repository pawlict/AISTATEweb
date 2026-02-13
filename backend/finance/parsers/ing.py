"""ING Bank Śląski statement parser — PyMuPDF line-based extraction.

Uses fitz (PyMuPDF) to extract text lines from PDF, then a state-machine
parser that walks through lines sequentially.  This replaces the previous
pdfplumber table-based approach for ING, giving more reliable extraction
of counterparty names, titles, structured details, and transaction channels.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .base import BankParser, ParseResult, RawTransaction, StatementInfo


class INGParser(BankParser):
    BANK_NAME = "ING Bank Śląski"
    BANK_ID = "ing"
    DETECT_PATTERNS = [
        r"ing\s*bank",
        r"ing\s*bank\s*[śs]l[ąa]ski",
        r"wyci[ąa]g\s*z\s*rachunku",
        r"konto\s*z\s*lwem",
        r"www\.ing\.pl",
        r"ingbplpw",
        r"ingbsk",
    ]

    # --- Regex constants ---

    NBSP = "\u00A0"
    DATE_ONLY_RE = re.compile(r"^\d{2}\.\d{2}\.\d{4}$")
    AMOUNT_LINE_RE = re.compile(
        r"^[+-]?(?:\d{1,3}(?:[ \u00A0]\d{3})*|\d+)(?:,\d{2})\s*[A-Z]{3}$"
    )
    AMT_CUR_RE = re.compile(
        r"([+-]?(?:\d{1,3}(?:[ \u00A0]\d{3})*|\d+)(?:,\d{2}))\s*([A-Z]{3})\b"
    )
    NRB_SPACED_RE = re.compile(r"^\d{2}(?:\s?\d{4}){6}$")
    IBAN_RE = re.compile(r"^[A-Z]{2}\s?\d{2}(?:\s?\d{4}){6}(?:\s?\d{4})?$")
    ING_INTERNAL_ID_RE = re.compile(r"^\d{8}-\d+/\d+$")
    LONG_REF_RE = re.compile(r"^\d{12,20}$")
    URL_RE = re.compile(r"^(https?://|www\.)\S+", re.IGNORECASE)
    DOMAIN_RE = re.compile(r"^[a-z0-9.-]+\.[a-z]{2,}(/\S*)?$", re.IGNORECASE)
    TITLE_START_RE = re.compile(
        r"^(Płatność|Przelew|Wypłata|Zwrot|Prowizja|Świadczenie|ŚW\b)",
        re.IGNORECASE,
    )
    DETAIL_LINE_RE = re.compile(
        r"^(Nr karty|Nr transakcji|Zlecenie\d+|Dla\s+|Od\s+|Przelew na telefon\b)",
        re.IGNORECASE,
    )
    CHANNELS = {"TR.KART", "TR.BLIK", "P.BLIK", "PRZELEW", "ST.ZLEC"}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _norm(s: str) -> str:
        s = s.replace("\u00A0", " ")
        s = re.sub(r"[ \t]+", " ", s)
        return s.strip()

    @classmethod
    def _parse_money_pl(cls, s: str) -> Tuple[Optional[float], Optional[str]]:
        s = cls._norm(s)
        m = cls.AMT_CUR_RE.search(s)
        if not m:
            return None, None
        num_raw = m.group(1).replace(" ", "").replace(",", ".")
        ccy = m.group(2)
        try:
            return float(Decimal(num_raw)), ccy
        except (InvalidOperation, ValueError):
            return None, None

    @staticmethod
    def _parse_date_iso(d: str) -> Optional[str]:
        m = re.match(r"^(\d{2})\.(\d{2})\.(\d{4})$", d.strip())
        if not m:
            return None
        return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"

    @staticmethod
    def _normalize_nrb_or_iban(s: str) -> str:
        return re.sub(r"\s+", "", s)

    @staticmethod
    def _extract_lines_from_pdf(pdf_path: Path) -> Tuple[List[str], int]:
        """Extract normalized text lines from PDF using PyMuPDF (fitz)."""
        import fitz  # PyMuPDF

        doc = fitz.open(str(pdf_path))
        page_count = len(doc)
        out: List[str] = []
        for page in doc:
            text = page.get_text("text") or ""
            for ln in text.splitlines():
                ln = INGParser._norm(ln)
                if ln:
                    out.append(ln)
        return out, page_count

    # ------------------------------------------------------------------
    # Direct PDF parsing (preferred path — uses PyMuPDF)
    # ------------------------------------------------------------------

    def supports_direct_pdf(self) -> bool:
        """Signal that this parser can read the PDF directly."""
        return True

    def parse_pdf(self, pdf_path: Path) -> ParseResult:
        """Parse ING bank statement directly from PDF using PyMuPDF lines."""
        lines, page_count = self._extract_lines_from_pdf(pdf_path)
        return self._parse_from_lines(lines, page_count)

    # ------------------------------------------------------------------
    # Core parsing logic (works on normalized text lines)
    # ------------------------------------------------------------------

    def _parse_from_lines(self, lines: List[str], page_count: int = 0) -> ParseResult:
        """Run the full parsing pipeline on pre-extracted text lines."""
        info = self._parse_meta(lines)
        transactions, warnings = self._parse_transactions(lines)

        # Compute running balance_after from opening_balance
        if info.opening_balance is not None and transactions:
            running = info.opening_balance
            for t in transactions:
                running = round(running + t.amount, 2)
                t.balance_after = running

        # Quick reconciliation check
        if (
            info.opening_balance is not None
            and info.closing_balance is not None
            and transactions
        ):
            computed = round(
                info.opening_balance + sum(t.amount for t in transactions), 2
            )
            if abs(computed - info.closing_balance) > 0.02:
                warnings.append(
                    f"Rekoncyliacja wewnętrzna: obliczone saldo końcowe = {computed:,.2f}, "
                    f"deklarowane = {info.closing_balance:,.2f}"
                )

        return ParseResult(
            bank=self.BANK_ID,
            info=info,
            transactions=transactions,
            warnings=warnings,
            page_count=page_count,
            parse_method="text_lines",
        )

    # ------------------------------------------------------------------
    # Meta extraction
    # ------------------------------------------------------------------

    def _parse_meta(self, lines: List[str]) -> StatementInfo:
        """Extract statement metadata (holder, account, balances, sums)."""
        info = StatementInfo(bank=self.BANK_NAME)

        # --- Holder block ---
        try:
            idx = lines.index("Dane posiadacza")
            start = idx + 1
            if start < len(lines) and lines[start] == "Dane rachunku":
                start += 1
            holder_lines: List[str] = []
            stop_labels = {
                "Nazwa rachunku:", "Waluta rachunku:",
                "Nr rachunku/NRB:", "Nr rachunku IBAN:",
                "Nr BIC (SWIFT):", "Dane rachunku",
            }
            for i in range(start, min(start + 30, len(lines))):
                l = lines[i]
                if re.match(r"^Kod kraju:\s*[A-Z]{2}$", l):
                    break
                if l in stop_labels:
                    break
                holder_lines.append(l)
            if holder_lines:
                info.account_holder = holder_lines[0]
        except ValueError:
            pass

        # --- Scan header area ---
        for i, l in enumerate(lines[:500]):
            # Period: "Nr 9 / 01.09.2025 - 30.09.2025"
            m = re.match(
                r"^Nr\s+(\d+)\s*/\s*(\d{2}\.\d{2}\.\d{4})\s*-\s*(\d{2}\.\d{2}\.\d{4})$",
                l,
            )
            if m:
                info.period_from = self._parse_date_iso(m.group(2))
                info.period_to = self._parse_date_iso(m.group(3))

            # Account number
            if l in ("Nr rachunku/NRB:", "Nr rachunku IBAN:"):
                if i + 1 < len(lines):
                    info.account_number = self._normalize_nrb_or_iban(lines[i + 1])

            # Currency
            if l == "Waluta rachunku:" and i + 1 < len(lines):
                info.currency = lines[i + 1].strip()

            # Opening balance
            if l.startswith("Saldo początkowe"):
                for j in range(i, min(i + 8, len(lines))):
                    if self.AMT_CUR_RE.search(lines[j]):
                        amt, ccy = self._parse_money_pl(lines[j])
                        if amt is not None:
                            info.opening_balance = amt
                            info.currency = info.currency or ccy
                        break

            # Closing balance
            if l.startswith("Saldo końcowe:"):
                if i + 1 < len(lines):
                    amt, ccy = self._parse_money_pl(lines[i + 1])
                    if amt is not None:
                        info.closing_balance = amt
                        info.currency = info.currency or ccy

            # Credits sum: "Suma uznań (11):"
            m = re.match(r"^Suma uznań\s*\((\d+)\):$", l)
            if m:
                info.declared_credits_count = int(m.group(1))
                if i + 1 < len(lines):
                    amt, _ = self._parse_money_pl(lines[i + 1])
                    info.declared_credits_sum = amt

            # Debits sum: "Suma obciążeń (182):"
            m = re.match(r"^Suma obciążeń\s*\((\d+)\):$", l)
            if m:
                info.declared_debits_count = int(m.group(1))
                if i + 1 < len(lines):
                    amt, _ = self._parse_money_pl(lines[i + 1])
                    info.declared_debits_sum = amt

            # Extra ING-specific fields
            if l == "Limit zadłużenia:" and i + 1 < len(lines):
                amt, _ = self._parse_money_pl(lines[i + 1])
                info.debt_limit = amt

            if l == "Kwota prowizji zaległej:" and i + 1 < len(lines):
                amt, _ = self._parse_money_pl(lines[i + 1])
                info.overdue_commission = amt

            if l == "Kwota zablokowana:" and i + 1 < len(lines):
                amt, _ = self._parse_money_pl(lines[i + 1])
                info.blocked_amount = amt

            if l == "Saldo dostępne:" and i + 1 < len(lines):
                amt, _ = self._parse_money_pl(lines[i + 1])
                info.available_balance = amt

        return info

    # ------------------------------------------------------------------
    # Transaction parsing — state machine walking through lines
    # ------------------------------------------------------------------

    def _find_table_start(self, lines: List[str]) -> int:
        """Find the first line of the transaction table header."""
        for i in range(len(lines) - 1):
            if lines[i] == "Data księgowania" and "/ Data transakcji" in lines[i + 1]:
                return i
        raise RuntimeError("ING: nie znaleziono nagłówka tabeli transakcji")

    def _extract_structured_details(
        self, raw_lines: List[str]
    ) -> Tuple[Dict[str, Any], List[str]]:
        """Pull structured info (card, BLIK, etc.) from detail lines.

        Returns (details_dict, remaining_free_lines).
        """
        details: Dict[str, Any] = {}
        free: List[str] = []

        for l in raw_lines:
            # Card payment
            if re.match(r"^Płatność kartą\s+\d{2}\.\d{2}\.\d{4}$", l):
                details["method"] = "card"
                continue
            if re.match(r"^Nr karty\s+.+$", l):
                continue

            # BLIK payment
            if re.match(r"^Płatność BLIK\s+\d{2}\.\d{2}\.\d{4}$", l):
                details["method"] = "blik_payment"
                continue
            if re.match(r"^Nr transakcji\s+\d+$", l):
                continue

            # Phone transfer
            if re.match(r"^Przelew na telefon\s+.+$", l):
                details["method"] = "blik_phone_transfer"
                continue
            if l == "Przelew na telefon":
                details["method"] = details.get("method") or "blik_phone_transfer"
                continue

            # Dla / Od
            if re.match(r"^(Dla|Od)\s+.+$", l):
                continue

            # Order ID
            if re.match(r"^Zlecenie\d+$", l):
                continue

            # URLs / domains — skip (noise for counterparty/title)
            if self.URL_RE.match(l) or self.DOMAIN_RE.match(l):
                continue

            free.append(l)

        return details, free

    def _split_counterparty_vs_title(
        self, channel: Optional[str], rest: List[str]
    ) -> Tuple[List[str], List[str]]:
        """Split body lines into counterparty name/address vs title/details.

        Uses channel-specific markers to decide where the name ends and
        the transaction description begins.
        """
        if not rest:
            return [], []

        markers: List[re.Pattern] = []
        if channel == "TR.KART":
            markers = [
                re.compile(r"^Płatność kartą\b", re.I),
                re.compile(r"^Nr karty\b", re.I),
            ]
        elif channel == "TR.BLIK":
            markers = [
                re.compile(r"^Płatność BLIK\b", re.I),
                re.compile(r"^Nr transakcji\b", re.I),
            ]
        elif channel == "P.BLIK":
            markers = [
                re.compile(r"^Przelew na telefon\b", re.I),
                re.compile(r"^Dla\b", re.I),
                re.compile(r"^Od\b", re.I),
            ]
        else:
            markers = [
                re.compile(r"^Zlecenie\d+\b", re.I),
                self.TITLE_START_RE,
                self.DETAIL_LINE_RE,
            ]

        split_idx: Optional[int] = None
        for idx, l in enumerate(rest):
            if (
                any(p.match(l) for p in markers)
                or self.URL_RE.match(l)
                or self.DOMAIN_RE.match(l)
            ):
                split_idx = idx
                break

        # Heuristic: for transfers, name is usually 1-2 lines; rest is title.
        # Keep at least 1 line for title when there are >= 2 lines.
        if split_idx is None and channel in {"PRZELEW", "ST.ZLEC"}:
            split_idx = min(2, len(rest) - 1) if len(rest) >= 2 else len(rest)

        if split_idx is None:
            split_idx = len(rest)

        return rest[:split_idx], rest[split_idx:]

    def _parse_transactions(
        self, lines: List[str]
    ) -> Tuple[List[RawTransaction], List[str]]:
        """Walk through lines and extract all transactions."""
        warnings: List[str] = []

        try:
            start = self._find_table_start(lines)
        except RuntimeError as e:
            return [], [str(e)]

        # Advance past header to first date line
        i = start + 1
        while i < len(lines) and not self.DATE_ONLY_RE.match(lines[i]):
            i += 1

        txs: List[RawTransaction] = []

        while i < len(lines):
            if not self.DATE_ONLY_RE.match(lines[i]):
                i += 1
                continue

            # --- Posting date ---
            posting = lines[i]
            i += 1

            # --- Transaction date (optional second date line) ---
            trans = posting
            if i < len(lines) and self.DATE_ONLY_RE.match(lines[i]):
                trans = lines[i]
                i += 1

            # --- Contractor block (account number, ING id) ---
            contractor_raw: List[str] = []
            while i < len(lines):
                l = lines[i]
                if l.startswith("Nazwa i adres "):
                    break
                if (
                    l in self.CHANNELS
                    or self.AMOUNT_LINE_RE.match(l)
                    or self.DATE_ONLY_RE.match(l)
                ):
                    break
                if l.lower().startswith("strona:") or l.lower().startswith(
                    "wyciąg z rachunku"
                ):
                    i += 1
                    continue
                contractor_raw.append(l)
                i += 1

            counterparty_account: Optional[str] = None
            for cl in contractor_raw:
                if counterparty_account is None and (
                    self.NRB_SPACED_RE.match(cl) or self.IBAN_RE.match(cl)
                ):
                    counterparty_account = self._normalize_nrb_or_iban(cl)

            # --- Body lines (until channel keyword) ---
            body_lines: List[str] = []
            channel: Optional[str] = None
            while i < len(lines):
                l = lines[i]
                if l.lower().startswith("strona:"):
                    i += 1
                    continue
                if l in self.CHANNELS:
                    channel = l
                    i += 1
                    break
                if self.AMOUNT_LINE_RE.match(l) or self.DATE_ONLY_RE.match(l):
                    break
                body_lines.append(l)
                i += 1

            # --- Reference lines (between channel and amount) ---
            refs: List[str] = []
            while i < len(lines):
                l = lines[i]
                if l.lower().startswith("strona:"):
                    i += 1
                    continue
                if self.AMOUNT_LINE_RE.match(l) or self.DATE_ONLY_RE.match(l):
                    break
                refs.append(l)
                i += 1

            # --- Amount ---
            amount: Optional[float] = None
            currency: Optional[str] = None
            if i < len(lines) and self.AMOUNT_LINE_RE.match(lines[i]):
                amount, currency = self._parse_money_pl(lines[i])
                i += 1
            else:
                amount, currency = self._parse_money_pl(
                    " ".join(refs + body_lines)
                )

            if amount is None:
                continue

            # --- Counterparty / title split ---
            counterparty_name = ""
            title_lines = body_lines

            if body_lines and body_lines[0].startswith("Nazwa i adres "):
                label = body_lines[0]
                rest = body_lines[1:]
                first = ""
                if ":" in label:
                    first = label.split(":", 1)[1].strip()

                cp_lines, title_lines = self._split_counterparty_vs_title(
                    channel, rest
                )
                name_parts: List[str] = []
                if first:
                    name_parts.append(first)
                name_parts.extend(cp_lines)
                counterparty_name = ", ".join(p for p in name_parts if p).strip()

            # --- Structured details from title lines ---
            _, title_free = self._extract_structured_details(title_lines)
            title = " ".join(title_free).strip()

            raw_text = " | ".join(body_lines[:5])

            txs.append(
                RawTransaction(
                    date=self._parse_date_iso(posting) or posting,
                    date_valuation=self._parse_date_iso(trans),
                    amount=amount,
                    currency=currency or "PLN",
                    balance_after=None,  # filled later from opening_balance
                    counterparty=counterparty_name,
                    title=title,
                    raw_text=raw_text,
                    bank_category=channel or "",
                )
            )

        return txs, warnings

    # ------------------------------------------------------------------
    # Standard BankParser interface (fallback when PyMuPDF unavailable)
    # ------------------------------------------------------------------

    def _is_header_row(self, row: List[str]) -> bool:
        joined = " ".join(c.lower() for c in row if c)
        return "data" in joined and ("kwota" in joined or "saldo" in joined)

    def _find_column_mapping(self, header: List[str]) -> Dict[str, int]:
        mapping: Dict[str, int] = {}
        for i, cell in enumerate(header):
            cell_l = (cell or "").lower().strip()
            if re.search(r"data\s*(ksi[ęe]g|operacji|transakcji)", cell_l):
                mapping["date"] = i
            elif re.search(r"data\s*waluty", cell_l):
                mapping["date_valuation"] = i
            elif "data" in cell_l and "date" not in mapping:
                mapping["date"] = i
            elif re.search(r"tytu[łl]", cell_l):
                mapping["title"] = i
            elif re.search(r"kontrahent|nadawca|odbiorca|nazwa", cell_l):
                mapping["counterparty"] = i
            elif re.search(r"kwota|warto[śs]", cell_l):
                mapping["amount"] = i
            elif re.search(r"saldo", cell_l):
                mapping["balance"] = i
        return mapping

    def parse_tables(
        self,
        tables: List[List[List[str]]],
        full_text: str,
        header_words=None,
    ) -> ParseResult:
        """Parse from pdfplumber tables (fallback when PyMuPDF unavailable)."""
        info = self._parse_meta(
            [self._norm(l) for l in full_text.split("\n") if self._norm(l)]
        )
        transactions: List[RawTransaction] = []

        for table in tables:
            if not table or len(table) < 2:
                continue
            header_idx = None
            for idx, row in enumerate(table):
                if self._is_header_row(row):
                    header_idx = idx
                    break
            if header_idx is None:
                continue
            col_map = self._find_column_mapping(table[header_idx])
            if "date" not in col_map or "amount" not in col_map:
                continue

            merged_rows = self.merge_continuation_rows(table, col_map, header_idx + 1)
            for row in merged_rows:
                # ING date cell may contain two dates: "01.03.2025\n01.03.2025"
                # or "01.03.2025 01.03.2025" — take the first valid date
                date_cell = (
                    row[col_map["date"]] if col_map["date"] < len(row) else ""
                )
                date_str = None
                date_valuation = None
                for token in re.split(r"[\n\s]+", date_cell):
                    d = self.parse_date(token.strip())
                    if d and date_str is None:
                        date_str = d
                    elif d and date_valuation is None:
                        date_valuation = d
                if not date_str:
                    continue
                amount = self.resolve_amount_from_row(row, col_map)
                if amount is None:
                    continue
                title = self.clean_text(
                    row[col_map["title"]]
                    if col_map.get("title") is not None
                    and col_map["title"] < len(row)
                    else ""
                )
                counterparty_raw = self.clean_text(
                    row[col_map["counterparty"]]
                    if col_map.get("counterparty") is not None
                    and col_map["counterparty"] < len(row)
                    else ""
                )
                # ING counterparty cell: "[account_nr] Nazwa i adres odbiorcy: NAME CITY"
                # Remove account number prefix and the label
                cp = re.sub(
                    r"^[\d\s\-/]+Nazwa i adres (?:odbiorcy|płatnika)\s*:\s*",
                    "",
                    counterparty_raw,
                )
                if cp == counterparty_raw:
                    # Try without account prefix
                    cp = re.sub(
                        r"Nazwa i adres (?:odbiorcy|płatnika)\s*:\s*",
                        "",
                        counterparty_raw,
                    )
                counterparty = cp.strip()
                extra = self.collect_unmapped_text(row, col_map)
                if extra:
                    if title:
                        title = title + " " + extra
                    else:
                        title = extra
                txn = RawTransaction(
                    date=date_str,
                    date_valuation=date_valuation,
                    amount=amount,
                    balance_after=self.parse_amount(
                        row[col_map["balance"]]
                        if col_map.get("balance") is not None
                        and col_map["balance"] < len(row)
                        else ""
                    ),
                    counterparty=counterparty,
                    title=title,
                    raw_text=" | ".join(c or "" for c in row),
                )
                transactions.append(txn)

        if transactions:
            # Compute balance_after from opening_balance if table didn't have it
            if info.opening_balance is not None and all(
                t.balance_after is None for t in transactions
            ):
                running = info.opening_balance
                for t in transactions:
                    running = round(running + t.amount, 2)
                    t.balance_after = running
            return ParseResult(
                bank=self.BANK_ID,
                info=info,
                transactions=transactions,
                parse_method="table",
            )

        # Tables didn't yield results — try text parsing
        return self.parse_text(full_text)

    # ING-specific text line regex — captures dates and full body (including amount)
    _ING_LINE_RE = re.compile(
        r"^(\d{2}\.\d{2}\.\d{4})\s+(\d{2}\.\d{2}\.\d{4})\s+"       # posting + transaction dates
        r"(.+?)\s*PLN\s*$"                                            # body + amount (before PLN)
    )
    # Reference-anchored amount extraction patterns.
    # ING reference numbers are 12-25 continuous digits (no spaces).
    # Negative amounts: sign directly after reference (e.g. ...269860-30,90)
    # Positive amounts: space after reference (e.g. ...238314 500,00)
    _ING_AMT_SIGNED_RE = re.compile(
        r"(\d{12,25})([+-](?:\d{1,3}(?:\s\d{3})*),\d{2})\s*$"
    )
    _ING_AMT_UNSIGNED_RE = re.compile(
        r"(\d{12,25})\s+((?:\d{1,3}(?:\s\d{3})*),\d{2})\s*$"
    )
    _ING_AMT_FALLBACK_RE = re.compile(
        r"([+-]?(?:\d{1,3}(?:\s\d{3})*),\d{2})\s*$"
    )
    _ING_COUNTERPARTY_RE = re.compile(
        r"Nazwa i adres (?:odbiorcy|płatnika)\s*:\s*(.+?)\s+(Płatność\b|Przelew\b|Wypłata\b|Prowizja\b|Zwrot\b|Świadczenie\b|ŚW\b|PRZELEW\b|ST\.ZLEC\b|P\.BLIK\b|TR\.)"
    )

    @classmethod
    def _extract_ing_amount(cls, body: str) -> Tuple[Optional[float], str]:
        """Extract amount from end of ING transaction body text.

        ING reference numbers (12-25 uninterrupted digits) always precede amounts.
        This anchoring prevents the regex from accidentally pulling trailing digits
        of the reference number into the amount (e.g. '...238314 500,00' parsed as
        314500.00 instead of 500.00).
        """
        # Try 1: Signed amount directly after reference (no space between ref and sign)
        m = cls._ING_AMT_SIGNED_RE.search(body)
        if m:
            amt = cls.parse_amount(m.group(2))
            if amt is not None:
                return amt, body[:m.start(2)].strip()

        # Try 2: Unsigned amount after reference + space
        m = cls._ING_AMT_UNSIGNED_RE.search(body)
        if m:
            amt = cls.parse_amount(m.group(2))
            if amt is not None:
                return amt, body[:m.start(2)].strip()

        # Try 3: Fallback — last amount pattern (no reference anchor)
        m = cls._ING_AMT_FALLBACK_RE.search(body)
        if m:
            amt = cls.parse_amount(m.group(1))
            if amt is not None:
                return amt, body[:m.start()].strip()

        return None, body

    def _parse_ing_text_lines(self, text: str) -> List[RawTransaction]:
        """Parse ING transactions from pdfplumber's flattened text lines.

        Each transaction is on one long line with the amount at the end.
        Amount extraction is anchored to the reference number (12-25 continuous
        digits) to prevent capturing trailing reference digits as part of the
        amount in the Polish thousands-separator format.
        """
        transactions: List[RawTransaction] = []
        for line in text.split("\n"):
            line = self._norm(line)
            if not line:
                continue
            m = self._ING_LINE_RE.match(line)
            if not m:
                continue
            posting = m.group(1)
            trans = m.group(2)
            body_with_amount = m.group(3)

            date_str = self._parse_date_iso(posting)
            date_val = self._parse_date_iso(trans)
            if not date_str:
                continue
            amount, body = self._extract_ing_amount(body_with_amount)
            if amount is None:
                continue

            # Extract counterparty and title from body
            counterparty = ""
            title = ""

            # Find "Nazwa i adres" label
            label_m = re.search(
                r"Nazwa i adres (?:odbiorcy|płatnika)\s*:\s*", body
            )
            if label_m:
                after_label = body[label_m.end():]

                # Strip channel keyword + reference at the end
                channel_m = re.search(
                    r"\s+(TR\.KART|TR\.BLIK|P\.BLIK|PRZELEW|ST\.ZLEC)\s+\S+\s*$",
                    after_label,
                )
                if channel_m:
                    name_and_title = after_label[: channel_m.start()].strip()
                else:
                    name_and_title = after_label.strip()

                # Remove trailing "Zlecenie..." reference
                name_and_title = re.sub(r"\s*Zlecenie\d+\s*$", "", name_and_title)

                # Split counterparty from title at first title keyword
                title_m = re.search(
                    r"(Płatność\s+\S+|Przelew\s+\S+|Wypłata\s+\S+|Prowizja\b|"
                    r"Zwrot\b|Świadczenie\b|ŚW\s+)",
                    name_and_title,
                )
                if title_m:
                    counterparty = name_and_title[: title_m.start()].strip()
                    title_raw = name_and_title[title_m.start() :].strip()
                    # Clean detail noise from title
                    title_raw = re.sub(r"\s*Nr karty\s+\S+", "", title_raw)
                    title_raw = re.sub(r"\s*Nr transakcji\s+\S+", "", title_raw)
                    title_raw = re.sub(r"\s*www\.\S+", "", title_raw)
                    title = self.clean_text(title_raw)
                else:
                    # No clear title keyword — everything is cp + title combined
                    counterparty = name_and_title
                    title = ""
            else:
                # No counterparty label at all — use whole body
                title = self.clean_text(body)

            transactions.append(RawTransaction(
                date=date_str,
                date_valuation=date_val,
                amount=amount,
                counterparty=counterparty,
                title=title,
                raw_text=line[:200],
            ))
        return transactions

    def parse_text(self, text: str) -> ParseResult:
        """Parse from pre-extracted text (e.g. pdfplumber extract_text)."""
        lines = [self._norm(l) for l in text.split("\n") if self._norm(l)]

        # Try PyMuPDF-style line parsing first
        result = self._parse_from_lines(lines)
        if result.transactions:
            return result

        # Try ING-specific flat-line parsing (pdfplumber extract_text format)
        info = self._parse_meta(lines)
        transactions = self._parse_ing_text_lines(text)
        if transactions:
            if info.opening_balance is not None:
                running = info.opening_balance
                for t in transactions:
                    running = round(running + t.amount, 2)
                    t.balance_after = running
            return ParseResult(
                bank=self.BANK_ID,
                info=info,
                transactions=transactions,
                warnings=["Użyto parsera ING tekstowego (PyMuPDF niedostępny)"],
                parse_method="text_ing_flat",
            )

        # Last resort: generic multiline parser
        transactions = self.parse_text_multiline(text)
        if transactions:
            if info.opening_balance is not None:
                running = info.opening_balance
                for t in transactions:
                    running = round(running + t.amount, 2)
                    t.balance_after = running
            return ParseResult(
                bank=self.BANK_ID,
                info=info,
                transactions=transactions,
                warnings=["Użyto parsera wieloliniowego (PyMuPDF niedostępny)"],
                parse_method="text_multiline",
            )

        return result
