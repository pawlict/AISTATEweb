"""Santander Bank Polska statement parser."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from .base import BankParser, ParseResult, RawTransaction, StatementInfo


# Amount pattern for Santander "Historia Rachunku" format: "±X XXX,XX PLN"
_SAN_AMOUNT_RE = re.compile(
    r"^([+-]?\s*(?:\d{1,3}(?:\s\d{3})*|\d+),\d{2})\s+PLN$"
)
_SAN_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class SantanderParser(BankParser):
    BANK_NAME = "Santander Bank Polska"
    BANK_ID = "santander"
    DETECT_PATTERNS = [
        r"santander\s*bank",
        r"santander\.pl",
        r"wyci[ąa]g\s*z\s*rachunku.*santander",
        r"bzwbk",  # historical: Bank Zachodni WBK
        r"bank\s*zachodni\s*wbk",
        r"historia\s*rachunku",
        r"konto\s*santander",
    ]

    def _extract_info(self, text: str) -> StatementInfo:
        info = self.extract_info_common(text, bank_name=self.BANK_NAME)

        # Santander "Historia Rachunku" uses YYYY-MM-DD dates (ISO)
        # and "od dnia YYYY-MM-DD do dnia YYYY-MM-DD" period format
        if not info.period_from:
            m = re.search(r"od\s+dnia\s+(\d{4}-\d{2}-\d{2})", text, re.I)
            if m:
                info.period_from = m.group(1)
        if not info.period_to:
            m = re.search(r"do\s+dnia\s+(\d{4}-\d{2}-\d{2})", text, re.I)
            if m:
                info.period_to = m.group(1)

        # Santander summary: "Suma wpływów: +124 246,69 PLN"
        m = re.search(r"Suma\s+wp[łl]yw[óo]w\s*:?\s*([+-]?\s*[\d\s]+,\d{2})", text, re.I)
        if m and info.declared_credits_sum is None:
            val = self.parse_amount(m.group(1))
            if val is not None:
                info.declared_credits_sum = abs(val)

        m = re.search(r"Suma\s+wydatk[óo]w\s*:?\s*([+-]?\s*[\d\s]+,\d{2})", text, re.I)
        if m and info.declared_debits_sum is None:
            val = self.parse_amount(m.group(1))
            if val is not None:
                info.declared_debits_sum = abs(val)

        return info

    def _is_header_row(self, row: List[str]) -> bool:
        joined = " ".join(c.lower() for c in row if c)
        return "data" in joined and ("kwota" in joined or "saldo" in joined or "obci" in joined or "uzna" in joined)

    def _find_column_mapping(self, header: List[str]) -> Dict[str, int]:
        mapping: Dict[str, int] = {}
        for i, cell in enumerate(header):
            cell_l = (cell or "").lower().strip()
            if re.search(r"data\s*(operacji|transakcji|ksi[ęe]g)", cell_l):
                mapping["date"] = i
            elif re.search(r"data\s*waluty", cell_l):
                mapping["date_valuation"] = i
            elif "data" in cell_l and "date" not in mapping:
                mapping["date"] = i
            elif re.search(r"opis|tytu[łl]|szczeg", cell_l):
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
                    if title:
                        title = title + " " + extra
                    else:
                        title = extra
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

        # Try multi-line "Historia Rachunku" format first
        transactions = self._parse_historia_rachunku(text)
        if transactions:
            return ParseResult(bank=self.BANK_ID, info=info, transactions=transactions, parse_method="text_historia")

        # Fallback: single-line format (DD.MM.YYYY description amount)
        transactions = []
        for line in text.split("\n"):
            line = line.strip()
            m = re.match(r"(\d{2}[.\-/]\d{2}[.\-/]\d{4})\s+(.+?)\s+([\-+]?\d[\d\s]*[,\.]\d{2})\s*", line)
            if m:
                date_str = self.parse_date(m.group(1))
                amount = self.parse_amount(m.group(3))
                if date_str and amount is not None:
                    transactions.append(RawTransaction(
                        date=date_str, amount=amount,
                        title=self.clean_text(m.group(2)), raw_text=line,
                    ))
        return ParseResult(bank=self.BANK_ID, info=info, transactions=transactions)

    def _parse_historia_rachunku(self, text: str) -> List[RawTransaction]:
        """Parse Santander 'Historia Rachunku' multi-line text format.

        Transaction blocks start with 'Data operacji\\nYYYY-MM-DD' and end
        with an amount line like '±X XXX,XX PLN'.
        """
        lines = text.split("\n")
        transactions: List[RawTransaction] = []
        i = 0
        n = len(lines)

        # Find "Zestawienie operacji" to start
        while i < n:
            if lines[i].strip() == "Zestawienie operacji":
                i += 1
                break
            i += 1
        if i >= n:
            return []

        while i < n:
            stripped = lines[i].strip()

            if stripped != "Data operacji":
                i += 1
                continue

            i += 1
            if i >= n:
                break

            # Operation date
            op_date = lines[i].strip()
            if not _SAN_DATE_RE.match(op_date):
                continue
            i += 1

            # "Data księgowania"
            while i < n and not lines[i].strip():
                i += 1
            if i >= n:
                break
            if lines[i].strip() != "Data księgowania":
                continue
            i += 1

            # Booking date
            if i >= n:
                break
            book_date = lines[i].strip()
            if not _SAN_DATE_RE.match(book_date):
                continue
            i += 1

            # Read body until amount line
            body_lines: List[str] = []
            amount = None
            while i < n:
                l = lines[i].strip()
                m = _SAN_AMOUNT_RE.match(l)
                if m:
                    amount = self.parse_amount(m.group(1))
                    i += 1
                    break
                if l == "Data operacji":
                    break
                if l:
                    body_lines.append(l)
                i += 1

            if amount is None:
                continue

            # Extract counterparty and title from body
            counterparty = ""
            title = ""
            bank_category = ""

            for bl in body_lines:
                if bl.startswith("Tytuł:"):
                    title = bl[len("Tytuł:"):].strip()
                elif bl.startswith("Dodatkowe informacje:"):
                    if title:
                        title += " " + bl[len("Dodatkowe informacje:"):].strip()
                elif bl.startswith("Na rachunek:") or bl.startswith("Z rachunku:"):
                    pass  # account info
                elif bl.startswith("Numer karty:"):
                    bank_category = "TR.KART"
                elif not bank_category and bl in (
                    "TRANSAKCJA KARTĄ", "UZNANIE", "OBCIĄŻENIE",
                    "PRZELEW EXPRESS ELIXIR", "PRZELEW NA RACHUNEK W SAN PL - ONLINE",
                    "SPŁATA", "OPŁATA", "PROWIZJA", "ZLECENIE STAŁE",
                ):
                    bank_category = bl

            # Counterparty: for transfers, pick the name line after Na/Z rachunku
            # that is NOT the account holder
            for j, bl in enumerate(body_lines):
                if bl.startswith("Na rachunek:") and amount < 0:
                    # Next non-account line is counterparty
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
                counterparty=self.clean_text(counterparty),
                title=self.clean_text(title),
                raw_text=" | ".join(body_lines[:5]),
                bank_category=bank_category,
            ))

        return transactions
