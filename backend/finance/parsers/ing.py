"""ING Bank Śląski statement parser."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from .base import BankParser, ParseResult, RawTransaction, StatementInfo


class INGParser(BankParser):
    BANK_NAME = "ING Bank Śląski"
    BANK_ID = "ing"
    DETECT_PATTERNS = [
        r"ing\s*bank",
        r"ing\s*bank\s*[śs]l[ąa]ski",
        r"historia\s*rachunku",
        r"www\.ing\.pl",
        r"ingbsk",
    ]

    def _extract_info(self, text: str) -> StatementInfo:
        info = StatementInfo(bank=self.BANK_NAME)

        # Account number: 26-digit IBAN or shorter
        m = re.search(r"(\d{2}\s?\d{4}\s?\d{4}\s?\d{4}\s?\d{4}\s?\d{4}\s?\d{4})", text)
        if m:
            info.account_number = m.group(1).replace(" ", "")

        # Period
        m = re.search(r"(?:okres|za\s*okres|od)\s*:?\s*(\d{2}[.\-/]\d{2}[.\-/]\d{4})\s*(?:-|do|–)\s*(\d{2}[.\-/]\d{2}[.\-/]\d{4})", text, re.I)
        if m:
            info.period_from = self.parse_date(m.group(1))
            info.period_to = self.parse_date(m.group(2))

        # Opening/closing balance
        m = re.search(r"(?:saldo\s*(?:pocz[ąa]tkowe|otwarcia))\s*:?\s*([\d\s,.\-]+)", text, re.I)
        if m:
            info.opening_balance = self.parse_amount(m.group(1))
        m = re.search(r"(?:saldo\s*(?:ko[ńn]cowe|zamkni[ęe]cia))\s*:?\s*([\d\s,.\-]+)", text, re.I)
        if m:
            info.closing_balance = self.parse_amount(m.group(1))

        return info

    def _is_header_row(self, row: List[str]) -> bool:
        """Check if a table row is the transaction header."""
        joined = " ".join(c.lower() for c in row if c)
        return ("data" in joined and ("kwota" in joined or "saldo" in joined))

    def _find_column_mapping(self, header: List[str]) -> Dict[str, int]:
        """Map column names to indices based on header row."""
        mapping: Dict[str, int] = {}
        for i, cell in enumerate(header):
            cell_l = (cell or "").lower().strip()
            if re.search(r"data\s*(ksi[ęe]g|transakcji|operacji)", cell_l):
                mapping["date"] = i
            elif "data" in cell_l and "waluty" in cell_l:
                mapping["date_valuation"] = i
            elif "data" in cell_l and "date" not in mapping:
                mapping["date"] = i
            elif re.search(r"opis|tytu[łl]|szczeg|treść", cell_l):
                mapping["title"] = i
            elif re.search(r"nadawca|odbiorca|kontrahent|nazwa", cell_l):
                mapping["counterparty"] = i
            elif re.search(r"kwota|warto[śs][ćc]", cell_l):
                mapping["amount"] = i
            elif re.search(r"saldo|bilans", cell_l):
                mapping["balance"] = i
            elif re.search(r"walut", cell_l) and "date_valuation" not in cell_l:
                mapping["currency"] = i
        return mapping

    def parse_tables(self, tables: List[List[List[str]]], full_text: str) -> ParseResult:
        info = self._extract_info(full_text)
        transactions: List[RawTransaction] = []
        warnings: List[str] = []

        for table in tables:
            if not table or len(table) < 2:
                continue
            # Find header row
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

            for row in table[header_idx + 1 :]:
                if not row or all(not (c or "").strip() for c in row):
                    continue
                date_str = self.parse_date(row[col_map["date"]] if col_map.get("date") is not None and col_map["date"] < len(row) else "")
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
                    currency=self.clean_text(row[col_map["currency"]] if col_map.get("currency") is not None and col_map["currency"] < len(row) else "PLN") or "PLN",
                    raw_text=" | ".join(c or "" for c in row),
                )
                transactions.append(txn)

        return ParseResult(bank=self.BANK_ID, info=info, transactions=transactions, warnings=warnings)

    def parse_text(self, text: str) -> ParseResult:
        info = self._extract_info(text)
        transactions: List[RawTransaction] = []
        warnings: List[str] = []

        # ING text format: lines with dates and amounts
        # Pattern: DD.MM.YYYY or DD-MM-YYYY ... amount (with comma)
        lines = text.split("\n")
        for line in lines:
            line = line.strip()
            if not line:
                continue
            # Match line starting with a date
            m = re.match(r"(\d{2}[.\-/]\d{2}[.\-/]\d{4})\s+(.+?)\s+([\-+]?\d[\d\s]*[,\.]\d{2})\s*$", line)
            if not m:
                # Try: date ... amount ... balance
                m = re.match(r"(\d{2}[.\-/]\d{2}[.\-/]\d{4})\s+(.+?)\s+([\-+]?\d[\d\s]*[,\.]\d{2})\s+([\-+]?\d[\d\s]*[,\.]\d{2})\s*$", line)
                if m:
                    date_str = self.parse_date(m.group(1))
                    amount = self.parse_amount(m.group(3))
                    balance = self.parse_amount(m.group(4))
                    title = self.clean_text(m.group(2))
                    if date_str and amount is not None:
                        transactions.append(RawTransaction(
                            date=date_str,
                            amount=amount,
                            balance_after=balance,
                            title=title,
                            raw_text=line,
                        ))
                continue

            date_str = self.parse_date(m.group(1))
            amount = self.parse_amount(m.group(3))
            title = self.clean_text(m.group(2))
            if date_str and amount is not None:
                transactions.append(RawTransaction(
                    date=date_str,
                    amount=amount,
                    title=title,
                    raw_text=line,
                ))

        if not transactions:
            warnings.append("Nie udało się wyodrębnić transakcji z tekstu ING")

        return ParseResult(bank=self.BANK_ID, info=info, transactions=transactions, warnings=warnings)
