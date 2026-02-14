"""
ING Bank Śląski (PL) statement parser — robust column-aware extraction.

Why this version:
- ING statements are visually tabular (Date / Counterparty / Title / Details / Amount).
- Plain `page.get_text("text")` flattens columns and scrambles the order, so "Tytuł" and
  "Dane kontrahenta" end up mixed or lost.
- This parser uses PyMuPDF (`fitz`) "dict" extraction with coordinates, classifies text
  into table columns by X position, then segments transactions by paired date rows.

Key outputs (per transaction):
- booking_date (Data księgowania)
- transaction_date (Data transakcji)
- counterparty (parsed from "Nazwa i adres ...")
- title (the "Tytuł" column, preserved)
- bank_category/channel (TR.KART / TR.BLIK / P.BLIK / PRZELEW / ST.ZLEC / EXPRESS / BLUECASH / FX / etc.)
- amount, currency
- refs (transaction reference numbers like 2025....)
- raw column arrays attached in `tx.details` if the dataclass allows it

This file is designed as a drop-in replacement for your existing `ing.py` module
(imports `.base` as in your project).

NOTE: No anonymization is performed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import fitz  # PyMuPDF

from .base import BankParser, ParseResult, RawTransaction, StatementInfo


@dataclass
class _Line:
    text: str
    x0: float
    y0: float


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

    NBSP = "\u00A0"

    # Basic patterns
    DATE_ONLY_RE = re.compile(r"^\d{2}\.\d{2}\.\d{4}$")
    AMOUNT_LINE_RE = re.compile(r"^([+-]?\d[\d \u00A0]*,\d{2})\s*([A-Z]{3})$")
    REF_RE = re.compile(r"\b(20\d{12,22})\b")
    # IDs / accounts
    NRB_SPACED_RE = re.compile(r"^\d{2}(?:\s?\d{4}){6}$")
    IBAN_RE = re.compile(r"^[A-Z]{2}\s?\d{2}(?:\s?\d{4}){6}(?:\s?\d{4})?$")
    ING_INTERNAL_ID_RE = re.compile(r"^\d{7,10}-\d{7,10}/\d{3,6}$")
    LONG_REF_RE = re.compile(r"^\d{14,25}$")

    # Meta patterns
    STATEMENT_PERIOD_RE = re.compile(
        r"^Nr\s+(\d+)\s*/\s*(\d{2}\.\d{2}\.\d{4})\s*-\s*(\d{2}\.\d{2}\.\d{4})$"
    )
    STATEMENT_DATE_RE = re.compile(r"^Data\s+wyci[ąa]gu:\s*(\d{2}\.\d{2}\.\d{4})$")
    PREV_STATEMENT_DATE_RE = re.compile(
        r"^Data\s+poprzedniego\s+wyci[ąa]gu:\s*(\d{2}\.\d{2}\.\d{4})$"
    )

    # Known "channel-ish" tokens that appear in the Details column
    KNOWN_CHANNELS = {
        "TR.KART",
        "TR.BLIK",
        "P.BLIK",
        "PRZELEW",
        "ST.ZLEC",
        "EXPRESS",
        "ELIXIR",
        "BLUECAS",
        "BLUECASH",
        "FX",
    }
    CHANNEL_ALIASES = {
        "KART": "TR.KART",
        "BLIK": "TR.BLIK",  # can be re-mapped to P.BLIK via title heuristic
        "BLUECAS": "BLUECASH",
    }

    # Column noise (table headers, page footers)
    NOISE_PREFIXES = (
        "Strona:",
        "Wyciąg z rachunku",
        "Dokument sporządzony",
        "ING Bank Śląski",
        "Data księgowania",
        "/ Data transakcji",
        "Dane kontrahenta",
        "Tytuł",
        "Szczegóły",
        "Kwota",
        "<PARSED TEXT",
        "<IMAGE",
    )

    # ------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------

    def parse_pdf(self, pdf_path: Path) -> ParseResult:
        """
        Parse statement:
        - meta from plain text lines (reliable in header area)
        - transactions from column-aware extraction (reliable in table area)
        """
        # 1) meta
        lines, page_count = self._extract_lines_from_pdf(pdf_path)
        info = self._parse_meta(lines)

        # 2) transactions (column-aware)
        transactions, warnings = self._parse_transactions_from_pdf(pdf_path)

        # 3) running balance_after (same logic as your previous file)
        if getattr(info, "opening_balance", None) is not None and transactions:
            running = info.opening_balance
            for t in transactions:
                try:
                    running += t.amount
                except Exception:
                    # don't block if amount is missing/bad
                    continue
                try:
                    t.balance_after = running
                except Exception:
                    pass

        return ParseResult(
            bank_id=self.BANK_ID,
            bank_name=self.BANK_NAME,
            info=info,
            transactions=transactions,
            warnings=warnings,
            page_count=page_count,
        )

    # ------------------------------------------------------------
    # Meta parsing (header / summary section)
    # ------------------------------------------------------------

    def _extract_lines_from_pdf(self, pdf_path: Path) -> Tuple[List[str], int]:
        doc = fitz.open(str(pdf_path))
        lines: List[str] = []
        for page in doc:
            txt = page.get_text("text") or ""
            for raw in txt.splitlines():
                s = raw.replace(self.NBSP, " ").strip()
                if s:
                    lines.append(s)
        return lines, doc.page_count

    def _parse_meta(self, lines: List[str]) -> StatementInfo:
        info = StatementInfo(bank_name=self.BANK_NAME, currency="PLN")

        # statement number + period
        for ln in lines[:250]:
            m = self.STATEMENT_PERIOD_RE.match(ln)
            if m:
                stmt_no = m.group(1)
                period_from = m.group(2)
                period_to = m.group(3)
                for attr, val in (
                    ("statement_no", stmt_no),
                    ("period_from", period_from),
                    ("period_to", period_to),
                ):
                    try:
                        setattr(info, attr, val)
                    except Exception:
                        pass

            m = self.STATEMENT_DATE_RE.match(ln)
            if m:
                try:
                    setattr(info, "statement_date", m.group(1))
                except Exception:
                    pass

            m = self.PREV_STATEMENT_DATE_RE.match(ln)
            if m:
                try:
                    setattr(info, "prev_statement_date", m.group(1))
                except Exception:
                    pass

        # account details
        def _after(prefix: str) -> Optional[str]:
            for i, ln in enumerate(lines[:400]):
                if ln.startswith(prefix):
                    # typically: "Nr rachunku IBAN:" then next line is the value
                    if i + 1 < len(lines):
                        return lines[i + 1].strip()
            return None

        # these are present on the first page header
        iban = _after("Nr rachunku IBAN:")
        if iban:
            try:
                info.account_iban = iban.replace(" ", "")
            except Exception:
                pass

        nrb = _after("Nr rachunku/NRB:")
        if nrb:
            try:
                info.account_nrb = nrb.replace(" ", "")
            except Exception:
                pass

        bic = _after("Nr BIC (SWIFT):")
        if bic:
            try:
                info.account_bic = bic.strip()
            except Exception:
                pass

        # account name + currency
        for i, ln in enumerate(lines[:400]):
            if ln.startswith("Nazwa rachunku:") and i + 1 < len(lines):
                try:
                    info.account_name = lines[i + 1].strip()
                except Exception:
                    pass
            if ln.startswith("Waluta rachunku:") and i + 1 < len(lines):
                try:
                    info.currency = lines[i + 1].strip()
                except Exception:
                    pass

        # balances (if StatementInfo defines fields; otherwise ignored)
        # match patterns like: "Saldo początkowe ... 5 808,76 PLN"
        bal_re = re.compile(r"^(Saldo początkowe|Saldo końcowe):?\s*([+-]?\d[\d \u00A0]*,\d{2})\s*([A-Z]{3})$")
        for ln in lines:
            m = bal_re.match(ln.replace(self.NBSP, " "))
            if not m:
                continue
            kind = m.group(1)
            num = float(m.group(2).replace(" ", "").replace(",", "."))
            if kind.startswith("Saldo początkowe"):
                try:
                    info.opening_balance = num
                except Exception:
                    pass
            elif kind.startswith("Saldo końcowe"):
                try:
                    info.closing_balance = num
                except Exception:
                    pass

        return info

    # ------------------------------------------------------------
    # Column-aware transaction parsing
    # ------------------------------------------------------------

    def _parse_transactions_from_pdf(self, pdf_path: Path) -> Tuple[List[RawTransaction], List[str]]:
        warnings: List[str] = []
        doc = fitz.open(str(pdf_path))

        # Build a global list of table line-items (page,y,x,col,text)
        items: List[Dict] = []
        for pno in range(doc.page_count):
            page = doc[pno]
            page_lines = self._extract_positioned_lines(page)
            y_start = self._find_table_y_start(page_lines)
            if y_start is None:
                continue

            table_lines = [ln for ln in page_lines if ln.y0 >= y_start + 1]
            thr = self._detect_column_thresholds(table_lines)

            for ln in table_lines:
                if self._is_noise_line(ln.text):
                    continue
                col = self._classify_col(ln.x0, thr)
                items.append(
                    {"page": pno, "y0": ln.y0, "x0": ln.x0, "col": col, "text": ln.text.strip()}
                )

        items.sort(key=lambda it: (it["page"], it["y0"], it["x0"]))

        if not items:
            return [], ["No table items detected (statement may be scanned/OCR-only)."]

        # Segment transactions by pairing date rows (booking+transaction date)
        segments = self._segment_transactions(items, y_lookbehind=8.0)

        transactions: List[RawTransaction] = []
        for seg in segments:
            try:
                tx_data = self._parse_segment(seg)
                if tx_data is None:
                    continue
                rt = RawTransaction(
                    date=tx_data["booking_date"],
                    date_valuation=tx_data["transaction_date"],
                    amount=tx_data["amount"],
                    currency=tx_data["currency"],
                    balance_after=None,
                    counterparty=tx_data["counterparty"],
                    title=tx_data["title"],
                    raw_text=tx_data["raw_text"],
                    bank_category=tx_data["channel"],
                )
                # attach rich details if possible
                for attr, val in (
                    ("details", tx_data["details"]),
                    ("refs", tx_data["refs"]),
                    ("transaction_ref", tx_data["refs"][0] if tx_data["refs"] else None),
                    ("counterparty_role", tx_data.get("counterparty_role")),
                ):
                    try:
                        setattr(rt, attr, val)
                    except Exception:
                        pass

                transactions.append(rt)
            except Exception as e:
                warnings.append(f"Failed to parse transaction segment: {e!r}")

        return transactions, warnings

    # --- low-level: positioned lines and column detection ---

    def _extract_positioned_lines(self, page: fitz.Page) -> List[_Line]:
        """
        Extract text lines with coordinates using page.get_text('dict').
        """
        d = page.get_text("dict")
        out: List[_Line] = []
        for b in d.get("blocks", []):
            if b.get("type") != 0:
                continue
            for l in b.get("lines", []):
                spans = l.get("spans", [])
                if not spans:
                    continue
                spans_sorted = sorted(spans, key=lambda s: s["bbox"][0])
                txt = "".join(s.get("text", "") for s in spans_sorted).strip()
                if not txt:
                    continue
                x0 = min(s["bbox"][0] for s in spans_sorted)
                y0 = min(s["bbox"][1] for s in spans_sorted)
                out.append(_Line(txt, x0, y0))
        out.sort(key=lambda ln: (ln.y0, ln.x0))
        return out

    def _find_table_y_start(self, lines: List[_Line]) -> Optional[float]:
        for ln in lines:
            t = ln.text.strip()
            if "Data księgowania" in t and "Data transakcji" in t:
                return ln.y0
            if t.startswith("Data księgowania"):
                return ln.y0
        return None

    def _is_noise_line(self, text: str) -> bool:
        t = text.strip()
        if not t:
            return True
        for p in self.NOISE_PREFIXES:
            if t.startswith(p):
                return True
        if "Data księgowania" in t and "Kwota" in t:
            return True
        # page header line like: "Nr 2 / 01.02.2025 - 28.02.2025"
        if t.startswith("Nr ") and " / " in t and "-" in t:
            return True
        return False

    def _detect_column_thresholds(self, lines: List[_Line]) -> Dict[str, float]:
        """
        Determine X thresholds between columns.
        ING layout is stable; we still attempt a light-weight adaptive heuristic.
        """
        xs = [ln.x0 for ln in lines if not self._is_noise_line(ln.text)]
        # defaults from observed template:
        date_c, contr_c, title_c, det_c, amt_c = 40.0, 108.0, 238.0, 354.0, 491.0

        if len(xs) >= 20:
            # take a few most common rounded x0 values as "centers"
            from collections import Counter

            c = Counter(round(x, 1) for x in xs)
            common = [x for x, _ in c.most_common(15)]
            common.sort()
            centers: List[float] = []
            for x in common:
                if not centers:
                    centers.append(x)
                    continue
                if x - centers[-1] > 40:
                    centers.append(x)
                if len(centers) >= 5:
                    break
            if len(centers) >= 5:
                date_c, contr_c, title_c, det_c, amt_c = centers[:5]

        return {
            "b_date": (date_c + contr_c) / 2,
            "b_contractor": (contr_c + title_c) / 2,
            "b_title": (title_c + det_c) / 2,
            "b_details": (det_c + amt_c) / 2,
        }

    def _classify_col(self, x0: float, thr: Dict[str, float]) -> str:
        if x0 < thr["b_date"]:
            return "date"
        if x0 < thr["b_contractor"]:
            return "contractor"
        if x0 < thr["b_title"]:
            return "title"
        if x0 < thr["b_details"]:
            return "details"
        return "amount"

    # --- segmentation + parsing of a single segment ---

    def _segment_transactions(self, items: List[Dict], y_lookbehind: float = 8.0) -> List[List[Dict]]:
        date_idx = [i for i, it in enumerate(items) if it["col"] == "date" and self.DATE_ONLY_RE.match(it["text"])]
        # pair sequentially: (booking, transaction date)
        pairs: List[Tuple[int, int]] = []
        for k in range(0, len(date_idx) - 1, 2):
            pairs.append((date_idx[k], date_idx[k + 1]))

        segments: List[List[Dict]] = []
        prev_end = 0

        for pi, (i1, i2) in enumerate(pairs):
            # compute start with lookbehind (capture "10500031-.../..." and channel that appear slightly above booking date)
            start = i1
            start_page = items[i1]["page"]
            start_y = items[i1]["y0"]
            j = i1 - 1
            while j >= prev_end and items[j]["page"] == start_page and items[j]["y0"] >= start_y - y_lookbehind:
                start = j
                j -= 1

            # end at next segment start (also with lookbehind) to prevent grabbing next tx's pre-date lines
            if pi + 1 < len(pairs):
                next_i1 = pairs[pi + 1][0]
                next_page = items[next_i1]["page"]
                next_y = items[next_i1]["y0"]
                ns = next_i1
                jj = next_i1 - 1
                while jj >= i2 + 1 and items[jj]["page"] == next_page and items[jj]["y0"] >= next_y - y_lookbehind:
                    ns = jj
                    jj -= 1
                end = ns
            else:
                end = len(items)

            segments.append(items[start:end])
            prev_end = end

        return segments

    def _parse_amount(self, text: str) -> Optional[Tuple[float, str]]:
        m = self.AMOUNT_LINE_RE.match(text.replace(self.NBSP, " "))
        if not m:
            return None
        num = float(m.group(1).replace(" ", "").replace(",", "."))
        return num, m.group(2)

    def _infer_channel(self, title_lines: List[str], details_lines: List[str]) -> Optional[str]:
        # explicit tokens
        for l in details_lines + title_lines:
            tok = l.strip()
            if tok in self.CHANNEL_ALIASES:
                tok = self.CHANNEL_ALIASES[tok]
            if tok in self.KNOWN_CHANNELS:
                # disambiguate BLIK vs P.BLIK using title
                if tok == "TR.BLIK" and any("Przelew na telefon" in t for t in title_lines):
                    return "P.BLIK"
                return tok
            m = re.search(r"\b(TR\.KART|TR\.BLIK|P\.BLIK|PRZELEW|ST\.ZLEC)\b", tok)
            if m:
                return m.group(1)

        # title heuristics
        for l in title_lines:
            if l.startswith("Płatność kartą"):
                return "TR.KART"
            if l.startswith("Płatność BLIK"):
                return "TR.BLIK"
            if l.startswith("Przelew na telefon"):
                return "P.BLIK"
            if l.startswith("Przelew") or l.startswith("Świadczenie") or l.startswith("ŚW"):
                return "PRZELEW"

        # details heuristics (system keywords)
        for l in details_lines:
            tok = l.strip()
            if tok.startswith("Kurs/Data"):
                return "FX"
            if re.fullmatch(r"[A-ZĄĆĘŁŃÓŚŹŻ\.]{3,12}", tok):
                return self.CHANNEL_ALIASES.get(tok, tok)

        return None

    def _parse_segment(self, seg_items: List[Dict]) -> Optional[Dict]:
        # dates
        dates = [it["text"] for it in seg_items if it["col"] == "date" and self.DATE_ONLY_RE.match(it["text"])]
        if len(dates) < 2:
            return None
        booking_date, transaction_date = dates[0], dates[1]

        # amount
        amount = None
        currency = None
        for it in seg_items:
            if it["col"] == "amount":
                parsed = self._parse_amount(it["text"])
                if parsed:
                    amount, currency = parsed
                    break
        if amount is None or currency is None:
            # if amount missing, ignore segment
            return None

        contractor_lines = [it["text"] for it in seg_items if it["col"] == "contractor"]
        title_lines = [it["text"] for it in seg_items if it["col"] == "title"]
        details_lines = [it["text"] for it in seg_items if it["col"] == "details"]

        # refs
        refs: List[str] = []
        for l in details_lines + title_lines:
            m = self.REF_RE.search(l.replace(self.NBSP, " "))
            if m:
                refs.append(m.group(1))
        # de-dup preserving order
        seen = set()
        refs = [r for r in refs if not (r in seen or seen.add(r))]

        channel = self._infer_channel(title_lines, details_lines)

        # counterparty
        counterparty_role: Optional[str] = None
        cp_parts: List[str] = []
        for l in contractor_lines:
            if l.startswith("Nazwa i adres"):
                if ":" in l:
                    label, rest = l.split(":", 1)
                    counterparty_role = label.replace("Nazwa i adres", "").strip()
                    rest = rest.strip()
                    if rest:
                        cp_parts.append(rest)
                continue

            ls = l.replace(self.NBSP, " ").strip()
            if self.NRB_SPACED_RE.match(ls) or self.ING_INTERNAL_ID_RE.match(ls) or self.LONG_REF_RE.match(ls.replace(" ", "")):
                continue
            cp_parts.append(l.strip())

        counterparty = "; ".join([p for p in cp_parts if p]).strip("; ").strip() if cp_parts else None
        title = "; ".join([t.strip() for t in title_lines if t.strip()]).strip("; ")

        # raw_text: keep deterministic order (page,y,x)
        raw_text = "\n".join([it["text"] for it in seg_items if it.get("text")])

        details = {
            "channel": channel,
            "refs": refs,
            "contractor_raw": contractor_lines,
            "title_raw": title_lines,
            "details_raw": details_lines,
        }

        return {
            "booking_date": booking_date,
            "transaction_date": transaction_date,
            "amount": amount,
            "currency": currency,
            "channel": channel,
            "counterparty": counterparty,
            "counterparty_role": counterparty_role,
            "title": title,
            "refs": refs,
            "raw_text": raw_text,
            "details": details,
        }
