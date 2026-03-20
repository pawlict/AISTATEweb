"""BNP Paribas Bank Polska statement parser."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from .base import BankParser, ParseResult, RawTransaction, StatementInfo


_BNP_DATE_RE = re.compile(r"^\d{2}\.\d{2}\.\d{4}$")
_BNP_AMOUNT_RE = re.compile(r"^[+-]?\s*(?:\d{1,3}(?:\s\d{3})*|\d+),\d{2}$")
_BNP_REF_RE = re.compile(r"^(CEN|PSD|KUP|OPL|BOM)\d{10,}")


class BNPParibasParser(BankParser):
    BANK_NAME = "BNP Paribas Bank Polska"
    BANK_ID = "bnp_paribas"
    DETECT_PATTERNS = [
        r"bnp\s*paribas",
        r"ppabplpk",
        r"wyci[ąa]g\s*bankowy",
        r"www\.bnpparibas\.pl",
        r"1600\s*1",  # BNP sort code prefix
    ]

    def _extract_info(self, text: str) -> StatementInfo:
        info = self.extract_info_common(text, bank_name=self.BANK_NAME)

        # Period: "DD.MM.YYYY - DD.MM.YYYY"
        if not info.period_from:
            m = re.search(r"(\d{2}\.\d{2}\.\d{4})\s*-\s*(\d{2}\.\d{2}\.\d{4})", text)
            if m:
                info.period_from = self.parse_date(m.group(1))
                info.period_to = self.parse_date(m.group(2))

        # IBAN
        if not info.account_number:
            m = re.search(r"IBAN\s*\n?\s*(PL\s*\d{2}\s+\d{4}\s+\d{4}\s+\d{4}\s+\d{4}\s+\d{4}\s+\d{4})", text)
            if m:
                info.account_number = re.sub(r"[PL\s]+", "", m.group(1))
            else:
                m = re.search(r"NRB\s*\n?\s*(\d{2}\s+\d{4}\s+\d{4}\s+\d{4}\s+\d{4}\s+\d{4}\s+\d{4})", text)
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
            if re.search(r"data\s*(ksi[ęe]g|operacji|transakcji)", cell_l):
                mapping["date"] = i
            elif re.search(r"data\s*waluty", cell_l):
                mapping["date_valuation"] = i
            elif "data" in cell_l and "date" not in mapping:
                mapping["date"] = i
            elif re.search(r"rodzaj|opis|tytu[łl]|szczeg", cell_l):
                mapping["title"] = i
            elif re.search(r"nadawca|odbiorca|kontrahent", cell_l):
                mapping["counterparty"] = i
            elif re.search(r"kwota", cell_l) and "debit" not in mapping:
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

        # Try multi-line "Wyciąg bankowy" format
        transactions = self._parse_wyciag_bankowy(text)
        if transactions:
            return ParseResult(bank=self.BANK_ID, info=info, transactions=transactions, parse_method="text_wyciag")

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

    @staticmethod
    def _is_footer(line: str) -> bool:
        return bool(re.match(
            r"^(Strona\s+\d+\s+z\s+\d+|BNP Paribas Bank|przez S|zak.adowy)",
            line.strip(),
        ))

    @staticmethod
    def _is_page_header(line: str) -> bool:
        return bool(re.match(
            r"^(Data$|ksi.gowania$|Data waluty$|Rodzaj oraz|Kwota$|operacji$|Saldo$|po operacji$)",
            line.strip(),
        ))

    def _parse_wyciag_bankowy(self, text: str) -> List[RawTransaction]:
        """Parse BNP Paribas 'Wyciąg bankowy' multi-line text format.

        Format: date_book, date_value, amount, balance, then description lines.
        """
        lines = text.split("\n")
        transactions: List[RawTransaction] = []
        n = len(lines)
        i = 0

        while i < n - 3:
            l = lines[i].strip()

            if self._is_footer(l) or self._is_page_header(l) or not l:
                i += 1
                continue

            # Summary section
            if l.startswith("Obci") and "enia" in l:
                break

            if not _BNP_DATE_RE.match(l):
                i += 1
                continue

            l1 = lines[i + 1].strip() if i + 1 < n else ""
            l2 = lines[i + 2].strip() if i + 2 < n else ""
            l3 = lines[i + 3].strip() if i + 3 < n else ""

            if not _BNP_DATE_RE.match(l1) or not _BNP_AMOUNT_RE.match(l2) or not _BNP_AMOUNT_RE.match(l3):
                i += 1
                continue

            book_date = self.parse_date(l)
            value_date = self.parse_date(l1)
            amount = self.parse_amount(l2)
            balance_after = self.parse_amount(l3)
            i += 4

            if amount is None or not book_date:
                continue

            # Read detail lines
            detail_lines: List[str] = []
            while i < n:
                dl = lines[i].strip()
                if self._is_footer(dl) or self._is_page_header(dl) or not dl:
                    i += 1
                    continue
                if dl.startswith("Obci") and "enia" in dl:
                    break
                if _BNP_DATE_RE.match(dl) and i + 3 < n:
                    nl1 = lines[i + 1].strip()
                    nl2 = lines[i + 2].strip()
                    nl3 = lines[i + 3].strip()
                    if _BNP_DATE_RE.match(nl1) and _BNP_AMOUNT_RE.match(nl2) and _BNP_AMOUNT_RE.match(nl3):
                        break
                detail_lines.append(dl)
                i += 1

            if not detail_lines:
                continue

            tx_type = detail_lines[0]
            body = detail_lines[1:]

            # Simple extraction for fallback parser
            counterparty = ""
            title = ""
            for bl in body:
                if _BNP_REF_RE.match(bl):
                    pass  # reference
                elif re.match(r"\d{6}-+\d{4}", bl):
                    pass  # card number
                elif re.match(r"\d{2}\s?\d{4}\s?\d{4}\s?\d{4}\s?\d{4}\s?\d{4}\s?\d{4}$", bl):
                    pass  # account number
                elif re.match(r"[\d.,]+\s+PLN\s+\d{4}-\d{2}-\d{2}", bl):
                    pass  # card original amount
                elif not counterparty:
                    counterparty = bl
                else:
                    title = (title + " " + bl).strip() if title else bl

            transactions.append(RawTransaction(
                date=book_date,
                date_valuation=value_date,
                amount=amount,
                balance_after=balance_after,
                counterparty=self.clean_text(counterparty),
                title=self.clean_text(title),
                raw_text=" | ".join(detail_lines[:5]),
                bank_category=tx_type,
            ))

        return transactions
