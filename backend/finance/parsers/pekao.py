"""Bank Pekao SA statement parser."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from .base import BankParser, ParseResult, RawTransaction, StatementInfo


_PEKAO_DATE_RE = re.compile(r"^\d{2}\.\d{2}\.\d{4}$")
_PEKAO_AMOUNT_RE = re.compile(r"^([+-]?\s*(?:\d{1,3}(?:\s\d{3})*|\d+),\d{2})\s+PLN$")


class PekaoParser(BankParser):
    BANK_NAME = "Bank Pekao SA"
    BANK_ID = "pekao"
    DETECT_PATTERNS = [
        r"bank\s*pekao",
        r"pekao\s*s\.?a\.?",
        r"pekao24",
        r"www\.pekao\.com",
        r"historia\s*operacji",
        r"lista\s*operacji",
        r"eurokonto",
    ]

    def _extract_info(self, text: str) -> StatementInfo:
        info = self.extract_info_common(text, bank_name=self.BANK_NAME)

        # "LISTA OPERACJI ZA OKRES OD DD.MM.YYYY DO DD.MM.YYYY"
        if not info.period_from:
            m = re.search(r"OKRES\s+OD\s+(\d{2}\.\d{2}\.\d{4})", text, re.I)
            if m:
                info.period_from = self.parse_date(m.group(1))
        if not info.period_to:
            m = re.search(r"DO\s+(\d{2}\.\d{2}\.\d{4})", text, re.I)
            if m:
                info.period_to = self.parse_date(m.group(1))

        # Account number
        if not info.account_number:
            m = re.search(r"Numer rachunku:\s*\n?\s*(\d{2}\s+\d{4}\s+\d{4}\s+\d{4}\s+\d{4}\s+\d{4}\s+\d{4})", text)
            if m:
                info.account_number = re.sub(r"\s+", "", m.group(1))

        # Holder
        if not info.account_holder:
            m = re.search(r"Klient:\s*\n?\s*([A-ZĄĆĘŁŃÓŚŹŻ][A-ZĄĆĘŁŃÓŚŹŻa-ząćęłńóśźż\s]+)", text)
            if m:
                info.account_holder = m.group(1).strip()

        return info

    def _is_header_row(self, row: List[str]) -> bool:
        joined = " ".join(c.lower() for c in row if c)
        return "data" in joined and ("kwota" in joined or "saldo" in joined or "obci" in joined or "uzna" in joined)

    def _find_column_mapping(self, header: List[str]) -> Dict[str, int]:
        mapping: Dict[str, int] = {}
        for i, cell in enumerate(header):
            cell_l = (cell or "").lower().strip()
            if re.search(r"data\s*(operacji|transakcji)", cell_l):
                mapping["date"] = i
            elif re.search(r"data\s*(waluty|ksi[ęe]g)", cell_l):
                mapping["date_valuation"] = i
            elif "data" in cell_l and "date" not in mapping:
                mapping["date"] = i
            elif re.search(r"opis|tytu[łl]|tre[śs][ćc]", cell_l):
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

        # Try multi-line "Historia operacji" format
        transactions = self._parse_historia_operacji(text)
        if transactions:
            return ParseResult(bank=self.BANK_ID, info=info, transactions=transactions, parse_method="text_historia")

        # Fallback: single-line format
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

    @staticmethod
    def _is_footer(line: str) -> bool:
        return bool(re.match(
            r"^(Potwierdzenie wygenerowane|TelePekao|Infolinia|\+48\s|E-mail|pekao24@|Strona\s+\d+\s+z\s+\d+)",
            line.strip(),
        ))

    def _parse_historia_operacji(self, text: str) -> List[RawTransaction]:
        """Parse Pekao 'Historia operacji' multi-line text format.

        Transaction blocks: DD.MM.YYYY -> type (multi-line) -> details -> amount PLN
        """
        lines = text.split("\n")
        transactions: List[RawTransaction] = []
        n = len(lines)
        i = 0

        _type_continuations = {
            "PŁATNICZĄ", "MIĘDZYBANKOWY", "DEPOZYTU", "PROWADZENIE",
            "RACHUNKU", "WEWNĘTRZNY", "ZEWNĘTRZNY", "AUT.",
            "PRZYCHODZĄCY", "WYCHODZĄCY",
        }

        while i < n:
            l = lines[i].strip()

            if self._is_footer(l):
                i += 1
                continue

            if not _PEKAO_DATE_RE.match(l):
                i += 1
                continue

            date_str = self.parse_date(l)
            i += 1

            # Read body until amount line
            body_lines: List[str] = []
            amount = None
            while i < n:
                cl = lines[i].strip()
                if self._is_footer(cl):
                    i += 1
                    continue
                m = _PEKAO_AMOUNT_RE.match(cl)
                if m:
                    amount = self.parse_amount(m.group(1))
                    i += 1
                    break
                if _PEKAO_DATE_RE.match(cl) and body_lines:
                    break
                if cl:
                    body_lines.append(cl)
                i += 1

            if amount is None or not date_str:
                continue

            # Split type vs details
            type_lines: List[str] = []
            detail_lines: List[str] = []
            known_starts = (
                "TRANSAKCJA KART", "PRZELEW", "PROWIZJE", "WYPŁATA KART",
                "OPŁATA ZA", "ODSETKI OD", "PODATEK POBRANY", "WYPŁATA",
                "KAPITALIZACJA", "ZLECENIE",
            )
            for j, bl in enumerate(body_lines):
                if j == 0 and any(bl.upper().startswith(t) for t in known_starts):
                    type_lines.append(bl)
                elif j > 0 and j < 3 and type_lines and bl.strip() in _type_continuations:
                    type_lines.append(bl)
                else:
                    detail_lines.append(bl)

            bank_category = " ".join(type_lines).strip()

            counterparty = ""
            title = ""
            for dl in detail_lines:
                if dl.startswith("*") and len(dl) > 5:
                    pass  # card number
                elif not counterparty and not dl.startswith(("KRW ", "ODSETKI", "OPŁATA")):
                    counterparty = dl
                else:
                    title = (title + " " + dl).strip() if title else dl

            if not title and not counterparty and bank_category:
                title = bank_category

            transactions.append(RawTransaction(
                date=date_str,
                amount=amount,
                counterparty=self.clean_text(counterparty),
                title=self.clean_text(title),
                raw_text=" | ".join(body_lines[:5]),
                bank_category=bank_category,
            ))

        return transactions
