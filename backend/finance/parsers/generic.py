"""Generic / fallback bank statement parser.

Attempts to parse any bank statement by looking for common patterns
in tables and text without relying on bank-specific signatures.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from .base import BankParser, ParseResult, RawTransaction, StatementInfo


class GenericParser(BankParser):
    BANK_NAME = "Nierozpoznany bank"
    BANK_ID = "generic"
    DETECT_PATTERNS = []  # never auto-detected; used as fallback

    def _extract_info(self, text: str) -> StatementInfo:
        info = StatementInfo(bank=self.BANK_NAME)
        m = re.search(r"(\d{2}\s?\d{4}\s?\d{4}\s?\d{4}\s?\d{4}\s?\d{4}\s?\d{4})", text)
        if m:
            info.account_number = m.group(1).replace(" ", "")
        m = re.search(r"saldo\s*(?:pocz[ąa]tkowe|otwarcia)\s*:?\s*([\d\s,.\-]+)", text, re.I)
        if m:
            info.opening_balance = self.parse_amount(m.group(1))
        m = re.search(r"saldo\s*(?:ko[ńn]cowe|zamkni[ęe]cia)\s*:?\s*([\d\s,.\-]+)", text, re.I)
        if m:
            info.closing_balance = self.parse_amount(m.group(1))
        return info

    def _score_table_as_transactions(self, table: List[List[str]]) -> int:
        """Heuristic: how likely is this table to contain transactions?"""
        if not table or len(table) < 3:
            return 0
        score = 0
        header = " ".join(c.lower() for c in table[0] if c)
        if "data" in header:
            score += 2
        if re.search(r"kwota|warto[śs]|suma", header):
            score += 2
        if re.search(r"saldo", header):
            score += 1
        if re.search(r"opis|tytu[łl]", header):
            score += 1
        # Check if data rows contain dates
        date_rows = 0
        for row in table[1:min(6, len(table))]:
            for cell in row:
                if cell and re.match(r"\d{2}[.\-/]\d{2}[.\-/]\d{2,4}", cell.strip()):
                    date_rows += 1
                    break
        score += min(date_rows, 3)
        return score

    def _find_date_and_amount_cols(self, table: List[List[str]]) -> Optional[Dict[str, int]]:
        """Try to identify date and amount columns by content analysis."""
        if not table or len(table) < 3:
            return None

        ncols = max(len(r) for r in table)
        date_scores = [0] * ncols
        amount_scores = [0] * ncols

        for row in table[1:min(10, len(table))]:
            for i, cell in enumerate(row):
                if i >= ncols:
                    break
                c = (cell or "").strip()
                if re.match(r"\d{2}[.\-/]\d{2}[.\-/]\d{2,4}$", c):
                    date_scores[i] += 1
                if re.match(r"[\-+]?\d[\d\s]*[,\.]\d{2}$", c.replace("\xa0", "")):
                    amount_scores[i] += 1

        date_col = max(range(ncols), key=lambda i: date_scores[i]) if any(date_scores) else None
        if date_col is not None and date_scores[date_col] < 2:
            date_col = None

        # Find amount column(s) - pick the one with most numeric values
        # that isn't the date column
        amount_col = None
        best = 0
        for i in range(ncols):
            if i == date_col:
                continue
            if amount_scores[i] > best:
                best = amount_scores[i]
                amount_col = i

        if date_col is None or amount_col is None:
            return None

        # Guess title column: widest text column that's not date/amount
        title_col = None
        best_width = 0
        for i in range(ncols):
            if i in (date_col, amount_col):
                continue
            total_len = sum(len((row[i] if i < len(row) else "") or "") for row in table[1:])
            if total_len > best_width:
                best_width = total_len
                title_col = i

        return {"date": date_col, "amount": amount_col, "title": title_col}

    def parse_tables(self, tables: List[List[List[str]]], full_text: str) -> ParseResult:
        info = self._extract_info(full_text)
        transactions: List[RawTransaction] = []
        warnings: List[str] = []

        # Pick the table most likely to contain transactions
        best_table = None
        best_score = 0
        for table in tables:
            s = self._score_table_as_transactions(table)
            if s > best_score:
                best_score = s
                best_table = table

        if best_table is None or best_score < 3:
            return ParseResult(bank=self.BANK_ID, info=info, transactions=[], warnings=["Nie znaleziono tabeli transakcji"])

        cols = self._find_date_and_amount_cols(best_table)
        if not cols:
            return ParseResult(bank=self.BANK_ID, info=info, transactions=[], warnings=["Nie udało się rozpoznać kolumn"])

        # Skip header row(s) - first row or rows without valid dates
        start_idx = 0
        for idx, row in enumerate(best_table):
            c = (row[cols["date"]] if cols["date"] < len(row) else "") or ""
            if self.parse_date(c.strip()):
                start_idx = idx
                break

        for row in best_table[start_idx:]:
            if not row or all(not (c or "").strip() for c in row):
                continue
            date_str = self.parse_date(row[cols["date"]] if cols["date"] < len(row) else "")
            if not date_str:
                continue
            amount = self.parse_amount(row[cols["amount"]] if cols["amount"] < len(row) else "")
            if amount is None:
                continue
            title = self.clean_text(row[cols["title"]] if cols.get("title") is not None and cols["title"] < len(row) else "")
            txn = RawTransaction(
                date=date_str, amount=amount, title=title,
                raw_text=" | ".join(c or "" for c in row),
            )
            transactions.append(txn)

        if transactions:
            warnings.append(f"Użyto parser generyczny (heurystyczny) — {len(transactions)} transakcji")
        return ParseResult(bank=self.BANK_ID, info=info, transactions=transactions, warnings=warnings)

    def parse_text(self, text: str) -> ParseResult:
        info = self._extract_info(text)
        transactions: List[RawTransaction] = []
        warnings: List[str] = []

        for line in text.split("\n"):
            line = line.strip()
            if not line:
                continue
            # Generic: date ... amount (possibly balance)
            m = re.match(r"(\d{2}[.\-/]\d{2}[.\-/]\d{2,4})\s+(.+?)\s+([\-+]?\d[\d\s]*[,\.]\d{2})\s*(?:([\-+]?\d[\d\s]*[,\.]\d{2}))?\s*$", line)
            if m:
                date_str = self.parse_date(m.group(1))
                amount = self.parse_amount(m.group(3))
                balance = self.parse_amount(m.group(4)) if m.group(4) else None
                if date_str and amount is not None:
                    transactions.append(RawTransaction(
                        date=date_str, amount=amount, balance_after=balance,
                        title=self.clean_text(m.group(2)), raw_text=line,
                    ))

        if transactions:
            warnings.append(f"Użyto parser generyczny (tekstowy) — {len(transactions)} transakcji")
        return ParseResult(bank=self.BANK_ID, info=info, transactions=transactions, warnings=warnings)
