"""Credit Agricole Bank Polska statement parser."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from .base import BankParser, ParseResult, RawTransaction, StatementInfo


_CA_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class CreditAgricoleParser(BankParser):
    BANK_NAME = "Credit Agricole Bank Polska"
    BANK_ID = "credit_agricole"
    DETECT_PATTERNS = [
        r"credit\s*agricole",
        r"ca-bp",
        r"historia\s*transakcji",
        r"credit\s*agricole\s*bank\s*polska",
        r"ca\s*consumer\s*finance",
    ]

    def _extract_info(self, text: str) -> StatementInfo:
        info = self.extract_info_common(text, bank_name=self.BANK_NAME)

        # Period: "Okres od YYYY-MM-DD do YYYY-MM-DD"
        if not info.period_from:
            m = re.search(r"Okres\s+od\s+(\d{4}-\d{2}-\d{2})", text, re.I)
            if m:
                info.period_from = m.group(1)
        if not info.period_to:
            m = re.search(r"Okres\s+od\s+\d{4}-\d{2}-\d{2}\s+do\s+(\d{4}-\d{2}-\d{2})", text, re.I)
            if m:
                info.period_to = m.group(1)

        # Account number with (PLN)
        if not info.account_number:
            m = re.search(r"(\d{2}\s+\d{4}\s+\d{4}\s+\d{4}\s+\d{4}\s+\d{4}\s+\d{4})\s*\(PLN\)", text)
            if m:
                info.account_number = re.sub(r"\s+", "", m.group(1))

        return info

    def _is_header_row(self, row: List[str]) -> bool:
        joined = " ".join(c.lower() for c in row if c)
        return "data" in joined and ("kwota" in joined or "saldo" in joined)

    def _find_column_mapping(self, header: List[str]) -> Dict[str, int]:
        mapping: Dict[str, int] = {}
        for i, cell in enumerate(header):
            cell_l = (cell or "").lower().strip()
            if re.search(r"data\s*(operacji|transakcji)", cell_l):
                mapping["date"] = i
            elif re.search(r"data\s*(ksi[ęe]g|waluty)", cell_l):
                mapping["date_valuation"] = i
            elif "data" in cell_l and "date" not in mapping:
                mapping["date"] = i
            elif re.search(r"opis|tytu[łl]|szczeg|rodzaj", cell_l):
                mapping["title"] = i
            elif re.search(r"nadawca|odbiorca|kontrahent", cell_l):
                mapping["counterparty"] = i
            elif re.search(r"obci[ąa][żz]|wyp[łl]at|debit|wydatki", cell_l):
                mapping["debit"] = i
            elif re.search(r"uzna|wp[łl]at|credit|wp[łl]yw", cell_l):
                mapping["credit"] = i
            elif re.search(r"kwota|warto[śs]", cell_l) and "debit" not in mapping:
                mapping["amount"] = i
            elif re.search(r"saldo", cell_l):
                mapping["balance"] = i
        return mapping

    def parse_tables(self, tables: List[List[List[str]]], full_text: str, header_words=None) -> ParseResult:
        info = self._extract_info(full_text)
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
            has_amount = "amount" in col_map or "debit" in col_map or "credit" in col_map
            if "date" not in col_map or not has_amount:
                continue
            merged_rows = self.merge_continuation_rows(table, col_map, header_idx + 1)
            for row in merged_rows:
                date_str = self.parse_date(row[col_map["date"]] if col_map["date"] < len(row) else "")
                if not date_str:
                    continue
                amount = self.resolve_amount_from_row(row, col_map)
                if amount is None:
                    continue
                title = self.clean_text(row[col_map["title"]] if col_map.get("title") is not None and col_map["title"] < len(row) else "")
                counterparty = self.clean_text(row[col_map["counterparty"]] if col_map.get("counterparty") is not None and col_map["counterparty"] < len(row) else "")
                extra = self.collect_unmapped_text(row, col_map)
                if extra:
                    title = (title + " " + extra) if title else extra
                txn = RawTransaction(
                    date=date_str,
                    date_valuation=self.parse_date(row[col_map["date_valuation"]] if col_map.get("date_valuation") is not None and col_map["date_valuation"] < len(row) else ""),
                    amount=amount,
                    balance_after=self.parse_amount(row[col_map["balance"]] if col_map.get("balance") is not None and col_map["balance"] < len(row) else ""),
                    counterparty=counterparty,
                    title=title,
                    raw_text=" | ".join(c or "" for c in row),
                )
                transactions.append(txn)

        return ParseResult(bank=self.BANK_ID, info=info, transactions=transactions)

    def parse_text(self, text: str) -> ParseResult:
        info = self._extract_info(text)

        # Try multi-line "Historia transakcji" format
        transactions = self._parse_historia_transakcji(text)
        if transactions:
            return ParseResult(bank=self.BANK_ID, info=info, transactions=transactions, parse_method="text_historia")

        # Fallback: single-line format
        transactions = []
        for line in text.split("\n"):
            line = line.strip()
            m = re.match(r"(\d{2}[.\-/]\d{2}[.\-/]\d{4})\s+(.+?)\s+([\-+]?\d[\d\s]*[,.]\d{2})\s*", line)
            if m:
                date_str = self.parse_date(m.group(1))
                amount = self.parse_amount(m.group(3))
                if date_str and amount is not None:
                    transactions.append(RawTransaction(
                        date=date_str, amount=amount,
                        title=self.clean_text(m.group(2)), raw_text=line,
                    ))
        return ParseResult(bank=self.BANK_ID, info=info, transactions=transactions)

    def _parse_historia_transakcji(self, text: str) -> List[RawTransaction]:
        """Parse Credit Agricole 'Historia transakcji' multi-line text format.

        Transaction blocks:
          Data operacji: YYYY-MM-DD
          Data księgowania: YYYY-MM-DD
          TX_TYPE
          body lines (counterparty, title, etc.)
          Kwota: ±X,XX PLN
          Saldo po operacji: X,XX PLN
        """
        lines = text.split("\n")
        transactions: List[RawTransaction] = []
        i = 0
        n = len(lines)

        _OP_RE = re.compile(r"Data operacji:\s*(\S+)")
        _BOOK_RE = re.compile(r"Data ksi[ęe]gowania:\s*(\S+)")
        _AMOUNT_RE = re.compile(r"Kwota:\s*([+-]?\s*[\d\s]+,\d{2})\s*PLN")
        _BALANCE_RE = re.compile(r"Saldo po operacji:\s*([+-]?\s*[\d\s]+,\d{2})\s*PLN")

        while i < n:
            stripped = lines[i].strip()

            m = _OP_RE.match(stripped)
            if not m:
                i += 1
                continue

            op_date_raw = m.group(1)
            op_date = op_date_raw if _CA_DATE_RE.match(op_date_raw) else None
            i += 1

            # Booking date (optional)
            book_date = None
            if i < n:
                m = _BOOK_RE.match(lines[i].strip())
                if m:
                    bd = m.group(1)
                    if _CA_DATE_RE.match(bd):
                        book_date = bd
                    i += 1

            if not book_date:
                book_date = op_date or ""

            # Read body until Kwota: line
            body_lines: List[str] = []
            amount = None
            balance_after = None
            while i < n:
                l = lines[i].strip()
                m = _AMOUNT_RE.match(l)
                if m:
                    amount = self.parse_amount(m.group(1))
                    i += 1
                    # Check for Saldo po operacji
                    if i < n:
                        m2 = _BALANCE_RE.match(lines[i].strip())
                        if m2:
                            balance_after = self.parse_amount(m2.group(1))
                            i += 1
                    break
                if _OP_RE.match(l):
                    break  # next transaction, no amount found
                if l:
                    body_lines.append(l)
                i += 1

            if amount is None:
                continue

            # Extract type, counterparty, title from body
            bank_category = ""
            counterparty = ""
            title = ""

            for bl in body_lines:
                if bl.startswith("Tytuł:"):
                    title = bl[len("Tytuł:"):].strip()
                elif bl.startswith("Dodatkowe informacje:"):
                    extra = bl[len("Dodatkowe informacje:"):].strip()
                    title = (title + " " + extra) if title else extra
                elif bl.startswith("Na rachunek:") or bl.startswith("Z rachunku:"):
                    pass  # account info
                elif bl.startswith("Numer karty:"):
                    if not bank_category:
                        bank_category = "TRANSAKCJA KARTĄ"
                elif not bank_category and bl in (
                    "TRANSAKCJA KARTĄ", "UZNANIE", "OBCIĄŻENIE",
                    "PRZELEW ZEWNĘTRZNY PRZYCHODZĄCY", "PRZELEW ZEWNĘTRZNY WYCHODZĄCY",
                    "PRZELEW WEWNĘTRZNY", "PRZELEW NA RACHUNEK WŁASNY",
                    "SPŁATA", "OPŁATA", "PROWIZJA", "ZLECENIE STAŁE",
                    "TRANSAKCJA BLIK",
                ):
                    bank_category = bl

            # Counterparty extraction
            for j, bl in enumerate(body_lines):
                if bl.startswith("Na rachunek:") and amount < 0:
                    if j + 1 < len(body_lines):
                        candidate = body_lines[j + 1]
                        if not candidate.startswith(("Tytuł:", "Numer karty:", "Dodatkowe")):
                            counterparty = candidate
                    break
                if bl.startswith("Z rachunku:") and amount > 0:
                    if j + 1 < len(body_lines):
                        candidate = body_lines[j + 1]
                        if not candidate.startswith(("Na rachunek:", "Tytuł:", "Numer karty:")):
                            counterparty = candidate
                    break

            transactions.append(RawTransaction(
                date=book_date,
                date_valuation=op_date,
                amount=amount,
                balance_after=balance_after,
                counterparty=self.clean_text(counterparty),
                title=self.clean_text(title),
                raw_text=" | ".join(body_lines[:5]),
                bank_category=bank_category,
            ))

        return transactions
