"""mBank statement parser (fallback path via pdfplumber/text).

Primary parsing is handled by ``backend.aml.universal_parser._MBankStatementParser``
which uses PyMuPDF line-based extraction.  This module serves as a **fallback**
when the universal parser raises ``RuntimeError`` and the pipeline falls back to
the pdfplumber + registry-based path.

It also supports direct PDF parsing via ``parse_pdf()`` (uses PyMuPDF) so it can
be called by the pipeline's ``supports_direct_pdf`` check.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .base import BankParser, ParseResult, RawTransaction, StatementInfo


class MBankParser(BankParser):
    BANK_NAME = "mBank"
    BANK_ID = "mbank"
    DETECT_PATTERNS = [
        r"mbank\s*s\.?a\.?",
        r"mbank\.pl",
        r"bre\s*bank",       # historical name
        r"mkonto",
        r"mLinia",
        r"elektroniczne\s*zestawienie",
    ]

    # ------------------------------------------------------------------ meta

    def _extract_info(self, text: str) -> StatementInfo:
        info = self.extract_info_common(text, bank_name=self.BANK_NAME)

        # mBank-specific period format: "za okres od YYYY-MM-DD do YYYY-MM-DD"
        if info.period_from is None:
            m = re.search(
                r"za\s+okres\s+od\s+(\d{4}-\d{2}-\d{2})\s+do\s+(\d{4}-\d{2}-\d{2})",
                text,
            )
            if m:
                info.period_from = m.group(1)
                info.period_to = m.group(2)

        # mBank-specific: "saldo po operacji" as closing balance
        if info.closing_balance is None:
            m = re.search(
                r"saldo\s*(?:po\s*operacji|końcowe)\s*:?\s*([\d\s,.\-]+)", text, re.I
            )
            if m:
                info.closing_balance = self.parse_amount(m.group(1))

        # mBank: holder name — UPPERCASE line before "Elektroniczne zestawienie"
        if not info.account_holder:
            m = re.search(
                r"([A-ZĄĆĘŁŃÓŚŹŻ][A-ZĄĆĘŁŃÓŚŹŻ\s\-]{4,})\n\s*Elektroniczne\s+zestawienie",
                text,
            )
            if m:
                name = m.group(1).strip()
                words = name.split()
                if 2 <= len(words) <= 4:
                    info.account_holder = name

        # mBank: declared sums — "Uznania 18 11 867,12"
        if info.declared_credits_sum is None:
            m = re.search(r"Uznania\s+(\d+)\s+([\d\s]+,\d{2})", text)
            if m:
                info.declared_credits_count = int(m.group(1))
                info.declared_credits_sum = self.parse_amount(m.group(2))
        if info.declared_debits_sum is None:
            m = re.search(r"Obciążenia\s+(\d+)\s+([\d\s]+,\d{2})", text)
            if m:
                info.declared_debits_count = int(m.group(1))
                info.declared_debits_sum = self.parse_amount(m.group(2))

        return info

    # --------------------------------------------------------- column mapping

    def _is_header_row(self, row: List[str]) -> bool:
        joined = " ".join(c.lower() for c in row if c)
        return "data" in joined and (
            "kwota" in joined
            or "saldo" in joined
            or "operacji" in joined
            or "obci" in joined
            or "uzna" in joined
        )

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

    # --------------------------------------------------- pdfplumber fallback

    def parse_tables(
        self,
        tables: List[List[List[str]]],
        full_text: str,
        header_words=None,
    ) -> ParseResult:
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
            has_amount = (
                "amount" in col_map or "debit" in col_map or "credit" in col_map
            )
            if "date" not in col_map or not has_amount:
                continue

            merged_rows = self.merge_continuation_rows(
                table, col_map, header_idx + 1
            )
            for row in merged_rows:
                date_str = self.parse_date(
                    row[col_map["date"]] if col_map["date"] < len(row) else ""
                )
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
                counterparty = self.clean_text(
                    row[col_map["counterparty"]]
                    if col_map.get("counterparty") is not None
                    and col_map["counterparty"] < len(row)
                    else ""
                )
                extra = self.collect_unmapped_text(row, col_map)
                if extra:
                    title = (title + " " + extra) if title else extra
                txn = RawTransaction(
                    date=date_str,
                    date_valuation=self.parse_date(
                        row[col_map["date_valuation"]]
                        if col_map.get("date_valuation") is not None
                        and col_map["date_valuation"] < len(row)
                        else ""
                    ),
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

        return ParseResult(
            bank=self.BANK_ID,
            info=info,
            transactions=transactions,
            warnings=warnings,
        )

    # --------------------------------------------------------- text fallback

    def parse_text(self, text: str) -> ParseResult:
        info = self._extract_info(text)
        transactions: List[RawTransaction] = []
        warnings: List[str] = []

        for line in text.split("\n"):
            line = line.strip()
            if not line:
                continue
            m = re.match(
                r"(\d{2}[.\-/]\d{2}[.\-/]\d{4})\s+(.+?)\s+"
                r"([\-+]?\d[\d\s]*[,\.]\d{2})\s+([\-+]?\d[\d\s]*[,\.]\d{2})\s*$",
                line,
            )
            if not m:
                m = re.match(
                    r"(\d{2}[.\-/]\d{2}[.\-/]\d{4})\s+(.+?)\s+"
                    r"([\-+]?\d[\d\s]*[,\.]\d{2})\s*$",
                    line,
                )
                if m:
                    date_str = self.parse_date(m.group(1))
                    amount = self.parse_amount(m.group(3))
                    if date_str and amount is not None:
                        transactions.append(
                            RawTransaction(
                                date=date_str,
                                amount=amount,
                                title=self.clean_text(m.group(2)),
                                raw_text=line,
                            )
                        )
                continue
            date_str = self.parse_date(m.group(1))
            amount = self.parse_amount(m.group(3))
            balance = self.parse_amount(m.group(4))
            if date_str and amount is not None:
                transactions.append(
                    RawTransaction(
                        date=date_str,
                        amount=amount,
                        balance_after=balance,
                        title=self.clean_text(m.group(2)),
                        raw_text=line,
                    )
                )

        if not transactions:
            transactions = self.parse_text_multiline(text)
            if transactions:
                warnings.append("Użyto parsera wieloliniowego (fallback)")
            else:
                warnings.append(
                    "Nie udało się wyodrębnić transakcji z tekstu mBank"
                )
        return ParseResult(
            bank=self.BANK_ID,
            info=info,
            transactions=transactions,
            warnings=warnings,
        )

    # ------------------------------------------------- direct PDF (PyMuPDF)

    @staticmethod
    def supports_direct_pdf() -> bool:  # noqa: D102
        return True

    def parse_pdf(self, pdf_path: Path) -> ParseResult:
        """Parse mBank PDF directly using PyMuPDF via universal_parser logic."""
        from backend.aml.universal_parser import (
            extract_lines_from_pdf,
            _MBankStatementParser as _UP,
        )

        lines, page_count = extract_lines_from_pdf(pdf_path)
        up = _UP()
        meta = up._parse_meta(lines)
        txs = up._parse_transactions(lines)

        info = StatementInfo(
            bank=self.BANK_NAME,
            account_number=meta.get("account_number", ""),
            account_holder=meta.get("holder_name", ""),
            period_from=meta.get("period_from"),
            period_to=meta.get("period_to"),
            opening_balance=meta.get("opening_balance"),
            closing_balance=meta.get("closing_balance"),
            currency=meta.get("currency", "PLN"),
            declared_credits_sum=meta.get("credits_total"),
            declared_credits_count=meta.get("credits_count"),
            declared_debits_sum=meta.get("debits_total"),
            declared_debits_count=meta.get("debits_count"),
            debt_limit=meta.get("debt_limit"),
        )

        transactions: List[RawTransaction] = []
        for tx in txs:
            amt = tx.get("amount") or 0.0
            cp = tx.get("counterparty_name_address", "")
            body = tx.get("body_raw_lines", [])
            raw_parts = list(body) if isinstance(body, list) else [str(body)]
            cp_acct = tx.get("counterparty_account")
            if cp_acct:
                raw_parts.append(f"Nr rachunku {cp_acct}")

            transactions.append(
                RawTransaction(
                    date=tx.get("posting_date", ""),
                    date_valuation=tx.get("transaction_date"),
                    amount=float(amt),
                    currency=tx.get("currency", "PLN"),
                    balance_after=tx.get("balance_after"),
                    counterparty=cp,
                    title=tx.get("title", ""),
                    raw_text=" | ".join(raw_parts),
                    bank_category=tx.get("channel", ""),
                )
            )

        return ParseResult(
            bank=self.BANK_ID,
            info=info,
            transactions=transactions,
            page_count=page_count,
            parse_method="pymupdf_lines_mbank",
        )
