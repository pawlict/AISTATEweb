"""ING Bank Śląski statement parser."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from .base import BankParser, ParseResult, RawTransaction, StatementInfo


# Transaction type codes used by ING in the "Szczegóły transakcji" column
_TYPE_CODE_RE = re.compile(
    r"^(TR\.KART|ST\.ZLEC|P\.BLIK|PRZELEW|OP[ŁL]ATA|ODSETKI|PROWIZJA|ZLECENIE)\s*(.*)",
    re.I,
)


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

    def _extract_info(self, text: str, header_words=None) -> StatementInfo:
        # Use common extractor that handles all Polish bank formats
        info = self.extract_info_common(text, bank_name=self.BANK_NAME)

        # ING-specific: "Data księgowania / Data transakcji" header
        # ING-specific: "KONTO Z LWEM" account type
        m = re.search(r"nazwa\s*rachunku\s*:?\s*\n?\s*(.+?)(?:\n|$)", text, re.I)
        if m:
            info.raw_header = m.group(1).strip()

        # Override with spatial extraction if header_words are available
        if header_words:
            spatial = self._extract_spatial_balances(header_words)
            if spatial.get("opening_balance") is not None:
                info.opening_balance = spatial["opening_balance"]
            if spatial.get("closing_balance") is not None:
                info.closing_balance = spatial["closing_balance"]
            if spatial.get("available_balance") is not None:
                info.available_balance = spatial["available_balance"]
            if spatial.get("credits_sum") is not None:
                info.declared_credits_sum = spatial["credits_sum"]
            if spatial.get("credits_sum_count") is not None:
                info.declared_credits_count = spatial["credits_sum_count"]
            if spatial.get("debits_sum") is not None:
                info.declared_debits_sum = spatial["debits_sum"]
            if spatial.get("debits_sum_count") is not None:
                info.declared_debits_count = spatial["debits_sum_count"]

        return info

    def _extract_spatial_balances(self, words: List[Dict]) -> Dict[str, Any]:
        """Extract balances from positioned words using spatial analysis.

        ING headers have a columnar layout — labels on top, values below.
        pdfplumber's extract_words() gives us word positions (x0, x1, top, bottom)
        so we can correctly associate labels with their values even across columns.
        """
        if not words:
            return {}

        # Cluster words into lines by 'top' coordinate (±3px tolerance)
        line_map: Dict[int, List[Dict]] = {}
        for w in words:
            top_key = round(w.get("top", 0) / 3) * 3
            if top_key not in line_map:
                line_map[top_key] = []
            line_map[top_key].append(w)

        sorted_tops = sorted(line_map.keys())

        # Sort words within each line by x0
        for top_key in sorted_tops:
            line_map[top_key].sort(key=lambda w: w.get("x0", 0))

        # Target labels to find — map label text to result field name
        targets = [
            ("saldo początkowe", "opening_balance"),
            ("saldo poczatkowe", "opening_balance"),
            ("saldo końcowe", "closing_balance"),
            ("saldo koncowe", "closing_balance"),
            ("suma uznań", "credits_sum"),
            ("suma uznan", "credits_sum"),
            ("suma obciążeń", "debits_sum"),
            ("suma obciazen", "debits_sum"),
            ("saldo dostępne", "available_balance"),
            ("saldo dostepne", "available_balance"),
        ]

        results: Dict[str, Any] = {}

        for target_text, field_name in targets:
            if field_name in results:
                continue

            target_words = target_text.split()

            for top_idx, top_key in enumerate(sorted_tops):
                line_words = line_map[top_key]
                line_text = " ".join(w.get("text", "") for w in line_words).lower()

                if target_text not in line_text:
                    continue

                # Find x-range of words that form the label
                label_x0 = float("inf")
                label_x1 = float("-inf")
                for w in line_words:
                    w_text = w.get("text", "").lower()
                    if any(tw in w_text for tw in target_words):
                        label_x0 = min(label_x0, w.get("x0", 0))
                        label_x1 = max(label_x1, w.get("x1", 0))

                if label_x0 == float("inf"):
                    continue

                # Also check for count in parentheses on label line (e.g. "Suma uznań (7):")
                count_match = re.search(r"\((\d+)\)", line_text)
                if count_match and field_name in ("credits_sum", "debits_sum"):
                    results[field_name + "_count"] = int(count_match.group(1))

                # Look at next 1-3 lines below for a numeric value overlapping x-range
                for next_idx in range(top_idx + 1, min(top_idx + 4, len(sorted_tops))):
                    next_top = sorted_tops[next_idx]
                    next_words = line_map[next_top]

                    # Filter words that overlap horizontally with the label
                    # Allow 30px tolerance for slight misalignment
                    overlapping = [
                        w for w in next_words
                        if w.get("x0", 0) < label_x1 + 30
                        and w.get("x1", 0) > label_x0 - 30
                    ]

                    if not overlapping:
                        continue

                    text_combined = " ".join(w.get("text", "") for w in overlapping)
                    # Remove currency suffix
                    text_combined = re.sub(r"\s*(PLN|EUR|USD|GBP|CHF)\s*$", "", text_combined, flags=re.I)
                    val = self.parse_amount(text_combined)
                    if val is not None:
                        results[field_name] = val
                        break
                break  # found the label line, move to next target

        return results

    def _is_header_row(self, row: List[str]) -> bool:
        """Check if a table row is the transaction header."""
        joined = " ".join(c.lower() for c in row if c)
        return ("data" in joined and ("kwota" in joined or "saldo" in joined or "obci" in joined or "uzna" in joined))

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
            elif re.search(r"szczeg[oó][łl]", cell_l):
                # "Szczegóły transakcji" — separate from generic title
                mapping["details"] = i
            elif re.search(r"opis|tytu[łl]|tre[śs][ćc]", cell_l):
                mapping["title"] = i
            elif re.search(r"nadawca|odbiorca|kontrahent|dane\s*kontrahenta|nazwa", cell_l):
                mapping["counterparty"] = i
            elif re.search(r"obci[ąa][żz]|wyp[łl]at|debit|wydatki", cell_l):
                mapping["debit"] = i
            elif re.search(r"uzna|wp[łl]at|credit|wp[łl]yw", cell_l):
                mapping["credit"] = i
            elif re.search(r"kwota|warto[śs][ćc]", cell_l) and "debit" not in mapping:
                mapping["amount"] = i
            elif re.search(r"saldo|bilans", cell_l):
                mapping["balance"] = i
            elif re.search(r"walut", cell_l) and "date_valuation" not in cell_l:
                mapping["currency"] = i
        return mapping

    def parse_tables(self, tables: List[List[List[str]]], full_text: str, header_words=None) -> ParseResult:
        info = self._extract_info(full_text, header_words=header_words)
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
            has_amount = "amount" in col_map or "debit" in col_map or "credit" in col_map
            if "date" not in col_map or not has_amount:
                continue

            for row in table[header_idx + 1 :]:
                if not row or all(not (c or "").strip() for c in row):
                    continue
                date_str = self.parse_date(row[col_map["date"]] if col_map.get("date") is not None and col_map["date"] < len(row) else "")
                if not date_str:
                    continue
                amount = self.resolve_amount_from_row(row, col_map)
                if amount is None:
                    continue

                # Read details column (ING: "Szczegóły transakcji" — contains type code + description)
                details_text = ""
                if col_map.get("details") is not None and col_map["details"] < len(row):
                    details_text = self.clean_text(row[col_map["details"]])

                # Extract type code from details (e.g. "TR.KART Sklep XYZ" → code="TR.KART", rest="Sklep XYZ")
                bank_category = ""
                title_from_details = ""
                if details_text:
                    code_match = _TYPE_CODE_RE.match(details_text)
                    if code_match:
                        bank_category = code_match.group(1).upper()
                        title_from_details = code_match.group(2).strip()
                    else:
                        title_from_details = details_text

                # Fallback: read standard "title" column if details didn't provide text
                title_text = self.clean_text(row[col_map["title"]] if col_map.get("title") is not None and col_map["title"] < len(row) else "")
                final_title = title_from_details or title_text

                txn = RawTransaction(
                    date=date_str,
                    date_valuation=self.parse_date(row[col_map["date_valuation"]] if col_map.get("date_valuation") is not None and col_map["date_valuation"] < len(row) else ""),
                    amount=amount,
                    balance_after=self.parse_amount(row[col_map["balance"]] if col_map.get("balance") is not None and col_map["balance"] < len(row) else ""),
                    counterparty=self.clean_text(row[col_map["counterparty"]] if col_map.get("counterparty") is not None and col_map["counterparty"] < len(row) else ""),
                    title=final_title,
                    currency=self.clean_text(row[col_map["currency"]] if col_map.get("currency") is not None and col_map["currency"] < len(row) else "PLN") or "PLN",
                    raw_text=" | ".join(c or "" for c in row),
                    bank_category=bank_category,
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
                        # Try to extract type code from title
                        bank_cat = ""
                        code_match = _TYPE_CODE_RE.match(title)
                        if code_match:
                            bank_cat = code_match.group(1).upper()
                            title = code_match.group(2).strip()
                        transactions.append(RawTransaction(
                            date=date_str,
                            amount=amount,
                            balance_after=balance,
                            title=title,
                            raw_text=line,
                            bank_category=bank_cat,
                        ))
                continue

            date_str = self.parse_date(m.group(1))
            amount = self.parse_amount(m.group(3))
            title = self.clean_text(m.group(2))
            if date_str and amount is not None:
                bank_cat = ""
                code_match = _TYPE_CODE_RE.match(title)
                if code_match:
                    bank_cat = code_match.group(1).upper()
                    title = code_match.group(2).strip()
                transactions.append(RawTransaction(
                    date=date_str,
                    amount=amount,
                    title=title,
                    raw_text=line,
                    bank_category=bank_cat,
                ))

        if not transactions:
            transactions = self.parse_text_multiline(text)
            if transactions:
                warnings.append("Użyto parsera wieloliniowego (fallback)")
            else:
                warnings.append("Nie udało się wyodrębnić transakcji z tekstu ING")

        return ParseResult(bank=self.BANK_ID, info=info, transactions=transactions, warnings=warnings)
