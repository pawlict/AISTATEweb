"""Santander Bank Polska statement parser."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from .base import BankParser, ParseResult, RawTransaction, StatementInfo


class SantanderParser(BankParser):
    BANK_NAME = "Santander Bank Polska"
    BANK_ID = "santander"
    DETECT_PATTERNS = [
        r"santander\s*bank",
        r"santander\.pl",
        r"wyci[ąa]g\s*z\s*rachunku.*santander",
        r"bzwbk",  # historical: Bank Zachodni WBK
        r"bank\s*zachodni\s*wbk",
    ]

    def _extract_info(self, text: str) -> StatementInfo:
        info = StatementInfo(bank=self.BANK_NAME)
        m = re.search(r"(\d{2}\s?\d{4}\s?\d{4}\s?\d{4}\s?\d{4}\s?\d{4}\s?\d{4})", text)
        if m:
            info.account_number = m.group(1).replace(" ", "")
        m = re.search(r"(?:okres|za\s*okres|od)\s*:?\s*(\d{2}[.\-/]\d{2}[.\-/]\d{4})\s*(?:-|do|–)\s*(\d{2}[.\-/]\d{2}[.\-/]\d{4})", text, re.I)
        if m:
            info.period_from = self.parse_date(m.group(1))
            info.period_to = self.parse_date(m.group(2))
        m = re.search(r"saldo\s*(?:pocz[ąa]tkowe|otwarcia)\s*:?\s*([\d\s,.\-]+)", text, re.I)
        if m:
            info.opening_balance = self.parse_amount(m.group(1))
        m = re.search(r"saldo\s*(?:ko[ńn]cowe|zamkni[ęe]cia)\s*:?\s*([\d\s,.\-]+)", text, re.I)
        if m:
            info.closing_balance = self.parse_amount(m.group(1))
        return info

    def _is_header_row(self, row: List[str]) -> bool:
        joined = " ".join(c.lower() for c in row if c)
        return "data" in joined and ("kwota" in joined or "saldo" in joined)

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
            elif re.search(r"kwota|warto[śs]", cell_l):
                mapping["amount"] = i
            elif re.search(r"saldo", cell_l):
                mapping["balance"] = i
        return mapping

    def parse_tables(self, tables: List[List[List[str]]], full_text: str) -> ParseResult:
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
            if "date" not in col_map or "amount" not in col_map:
                continue
            for row in table[header_idx + 1:]:
                if not row or all(not (c or "").strip() for c in row):
                    continue
                date_str = self.parse_date(row[col_map["date"]] if col_map["date"] < len(row) else "")
                if not date_str:
                    continue
                amount = self.parse_amount(row[col_map["amount"]] if col_map["amount"] < len(row) else "")
                if amount is None:
                    continue
                txn = RawTransaction(
                    date=date_str,
                    date_valuation=self.parse_date(row[col_map["date_valuation"]] if col_map.get("date_valuation") is not None and col_map["date_valuation"] < len(row) else ""),
                    amount=amount,
                    balance_after=self.parse_amount(row[col_map["balance"]] if col_map.get("balance") is not None and col_map["balance"] < len(row) else ""),
                    counterparty=self.clean_text(row[col_map["counterparty"]] if col_map.get("counterparty") is not None and col_map["counterparty"] < len(row) else ""),
                    title=self.clean_text(row[col_map["title"]] if col_map.get("title") is not None and col_map["title"] < len(row) else ""),
                    raw_text=" | ".join(c or "" for c in row),
                )
                transactions.append(txn)

        return ParseResult(bank=self.BANK_ID, info=info, transactions=transactions)

    def parse_text(self, text: str) -> ParseResult:
        info = self._extract_info(text)
        transactions: List[RawTransaction] = []
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
