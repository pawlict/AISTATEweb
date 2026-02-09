"""mBank statement parser."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from .base import BankParser, ParseResult, RawTransaction, StatementInfo


class MBankParser(BankParser):
    BANK_NAME = "mBank"
    BANK_ID = "mbank"
    DETECT_PATTERNS = [
        r"mbank\s*s\.?a\.?",
        r"mbank\.pl",
        r"bre\s*bank",  # historical name
        r"zestawienie\s*operacji",
        r"multibank",
    ]

    def _extract_info(self, text: str) -> StatementInfo:
        info = self.extract_info_common(text, bank_name=self.BANK_NAME)
        # mBank-specific: "saldo po operacji"
        if info.closing_balance is None:
            m = re.search(r"saldo\s*po\s*operacji\s*:?\s*([\d\s,.\-]+)", text, re.I)
            if m:
                info.closing_balance = self.parse_amount(m.group(1))
        return info

    def _is_header_row(self, row: List[str]) -> bool:
        joined = " ".join(c.lower() for c in row if c)
        return "data" in joined and ("kwota" in joined or "saldo" in joined or "operacji" in joined or "obci" in joined or "uzna" in joined)

    def _find_column_mapping(self, header: List[str]) -> Dict[str, int]:
        mapping: Dict[str, int] = {}
        for i, cell in enumerate(header):
            cell_l = (cell or "").lower().strip()
            if re.search(r"data\s*operacji", cell_l):
                mapping["date"] = i
            elif re.search(r"data\s*(ksi[ęe]g|waluty)", cell_l):
                mapping["date_valuation"] = i
            elif "data" in cell_l and "date" not in mapping:
                mapping["date"] = i
            elif re.search(r"opis|tytu[łl]", cell_l):
                mapping["title"] = i
            elif re.search(r"nadawca|odbiorca|kontrahent|nazwa", cell_l):
                mapping["counterparty"] = i
            elif re.search(r"obci[ąa][żz]|wyp[łl]at|debit|wydatki", cell_l):
                mapping["debit"] = i
            elif re.search(r"uzna|wp[łl]at|credit|wp[łl]yw", cell_l):
                mapping["credit"] = i
            elif re.search(r"kwota", cell_l) and "debit" not in mapping:
                mapping["amount"] = i
            elif re.search(r"saldo", cell_l):
                mapping["balance"] = i
        return mapping

    def parse_tables(self, tables: List[List[List[str]]], full_text: str, header_words=None) -> ParseResult:
        info = self._extract_info(full_text)
        transactions: List[RawTransaction] = []
        warnings: List[str] = []

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

            for row in table[header_idx + 1:]:
                if not row or all(not (c or "").strip() for c in row):
                    continue
                date_str = self.parse_date(row[col_map["date"]] if col_map["date"] < len(row) else "")
                if not date_str:
                    continue
                amount = self.resolve_amount_from_row(row, col_map)
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

        return ParseResult(bank=self.BANK_ID, info=info, transactions=transactions, warnings=warnings)

    def parse_text(self, text: str) -> ParseResult:
        info = self._extract_info(text)
        transactions: List[RawTransaction] = []
        warnings: List[str] = []

        for line in text.split("\n"):
            line = line.strip()
            if not line:
                continue
            m = re.match(r"(\d{2}[.\-/]\d{2}[.\-/]\d{4})\s+(.+?)\s+([\-+]?\d[\d\s]*[,\.]\d{2})\s+([\-+]?\d[\d\s]*[,\.]\d{2})\s*$", line)
            if not m:
                m = re.match(r"(\d{2}[.\-/]\d{2}[.\-/]\d{4})\s+(.+?)\s+([\-+]?\d[\d\s]*[,\.]\d{2})\s*$", line)
                if m:
                    date_str = self.parse_date(m.group(1))
                    amount = self.parse_amount(m.group(3))
                    if date_str and amount is not None:
                        transactions.append(RawTransaction(
                            date=date_str, amount=amount,
                            title=self.clean_text(m.group(2)), raw_text=line,
                        ))
                continue
            date_str = self.parse_date(m.group(1))
            amount = self.parse_amount(m.group(3))
            balance = self.parse_amount(m.group(4))
            if date_str and amount is not None:
                transactions.append(RawTransaction(
                    date=date_str, amount=amount, balance_after=balance,
                    title=self.clean_text(m.group(2)), raw_text=line,
                ))

        if not transactions:
            transactions = self.parse_text_multiline(text)
            if transactions:
                warnings.append("Użyto parsera wieloliniowego (fallback)")
            else:
                warnings.append("Nie udało się wyodrębnić transakcji z tekstu mBank")
        return ParseResult(bank=self.BANK_ID, info=info, transactions=transactions, warnings=warnings)
