"""Universal bank statement parser (PDF with text layer) using PyMuPDF.

Core idea:
* A stable core (PDF -> lines -> detect parser -> normalized ParseResult)
* Bank-specific plugins (parsers) that implement a state machine for the bank's layout

Currently supported banks:
* ING Bank Śląski (Poland)

Dependencies:
    pip install pymupdf
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import fitz  # PyMuPDF

from ..finance.parsers.base import ParseResult, RawTransaction, StatementInfo

log = logging.getLogger(__name__)

# ------------------------------------------------------------------ utils
NBSP = "\u00A0"


def _norm(s: str) -> str:
    s = s.replace(NBSP, " ")
    s = re.sub(r"[ \t]+", " ", s)
    return s.strip()


DATE_ONLY_RE = re.compile(r"^\d{2}\.\d{2}\.\d{4}$")
AMOUNT_LINE_RE = re.compile(
    r"^[+-]?(?:\d{1,3}(?:[ \u00A0]\d{3})*|\d+)(?:,\d{2})\s*[A-Z]{3}$"
)
AMT_CUR_RE = re.compile(
    r"([+-]?(?:\d{1,3}(?:[ \u00A0]\d{3})*|\d+)(?:,\d{2}))\s*([A-Z]{3})\b"
)
NRB_SPACED_RE = re.compile(r"^\d{2}(?:\s?\d{4}){6}$")
IBAN_RE = re.compile(r"^[A-Z]{2}\s?\d{2}(?:\s?\d{4}){6}(?:\s?\d{4})?$")
ING_INTERNAL_ID_RE = re.compile(r"^\d{8}-\d+/\d+$")
LONG_REF_RE = re.compile(r"^\d{12,20}$")
URL_RE = re.compile(r"^(https?://|www\.)\S+", re.IGNORECASE)
DOMAIN_RE = re.compile(r"^[a-z0-9.-]+\.[a-z]{2,}(/\S*)?$", re.IGNORECASE)
TITLE_START_RE = re.compile(
    r"^(Płatność|Przelew|Wypłata|Zwrot|Prowizja|Świadczenie|ŚW\b)", re.IGNORECASE
)
DETAIL_LINE_RE = re.compile(
    r"^(Nr karty|Nr transakcji|Zlecenie\d+|Dla\s+|Od\s+|Przelew na telefon\b)", re.IGNORECASE
)


def _parse_money_pl(s: str) -> Tuple[Optional[Decimal], Optional[str]]:
    s = _norm(s)
    m = AMT_CUR_RE.search(s)
    if not m:
        return None, None
    num_raw = m.group(1).replace(" ", "").replace(",", ".")
    ccy = m.group(2)
    try:
        return Decimal(num_raw), ccy
    except InvalidOperation:
        return None, None


def _parse_date_iso(d: str) -> Optional[str]:
    m = re.match(r"^(\d{2})\.(\d{2})\.(\d{4})$", d.strip())
    if not m:
        return None
    dd, mm, yyyy = m.group(1), m.group(2), m.group(3)
    return f"{yyyy}-{mm}-{dd}"


def _normalize_nrb_or_iban(s: str) -> str:
    return re.sub(r"\s+", "", s)


def _safe_decimal(s: Any) -> Optional[Decimal]:
    if s is None:
        return None
    try:
        return Decimal(str(s))
    except Exception:
        return None


def extract_lines_from_pdf(pdf_path: Path) -> List[str]:
    """Extract text lines from PDF using PyMuPDF."""
    doc = fitz.open(str(pdf_path))
    out: List[str] = []
    for page in doc:
        text = page.get_text("text") or ""
        for ln in text.splitlines():
            ln = _norm(ln)
            if ln:
                out.append(ln)
    page_count = len(doc)
    doc.close()
    return out, page_count


# --------------------------------------------------------- parser registry

@dataclass
class _Statement:
    meta: Dict[str, Any]
    transactions: List[Dict[str, Any]]
    source_file: str


class _BankParser:
    name: str = "base"

    def can_parse(self, lines: List[str]) -> bool:
        raise NotImplementedError

    def parse(self, lines: List[str], source_file: str) -> _Statement:
        raise NotImplementedError


_PARSERS: List[_BankParser] = []


def _register(parser: _BankParser) -> None:
    _PARSERS.append(parser)


def _detect_parser(lines: List[str]) -> _BankParser:
    for p in _PARSERS:
        if p.can_parse(lines):
            return p
    raise RuntimeError("Nie rozpoznano banku — brak pasującego parsera.")


# ----------------------------------------------------------- ING parser

class _INGStatementParser(_BankParser):
    name = "ING Bank Śląski (PL)"

    def can_parse(self, lines: List[str]) -> bool:
        head = " ".join(lines[:140]).lower()
        return ("wyciąg z rachunku" in head and "ing" in head) or ("ingbplpw" in head)

    def _parse_holder_block(self, lines: List[str]) -> Dict[str, Any]:
        meta: Dict[str, Any] = {}
        try:
            idx = lines.index("Dane posiadacza")
        except ValueError:
            return meta
        start = idx + 1
        if start < len(lines) and lines[start] == "Dane rachunku":
            start += 1
        holder_lines: List[str] = []
        country_code: Optional[str] = None
        for i in range(start, min(start + 30, len(lines))):
            l = lines[i]
            m = re.match(r"^Kod kraju:\s*([A-Z]{2})$", l)
            if m:
                country_code = m.group(1)
                break
            if l in {
                "Nazwa rachunku:", "Waluta rachunku:",
                "Nr rachunku/NRB:", "Nr rachunku IBAN:",
                "Nr BIC (SWIFT):",
            }:
                break
            holder_lines.append(l)
        holder_lines = [x for x in holder_lines if x not in {"Dane rachunku"}]
        if holder_lines:
            meta["holder_name"] = holder_lines[0]
            if len(holder_lines) > 1:
                meta["holder_address_lines"] = holder_lines[1:]
                meta["holder_address"] = ", ".join(holder_lines[1:])
        if country_code:
            meta["holder_country_code"] = country_code
        return meta

    def _parse_meta(self, lines: List[str]) -> Dict[str, Any]:
        meta: Dict[str, Any] = {}
        meta.update(self._parse_holder_block(lines))

        for l in lines:
            m = re.search(r"^Strona:\s*(\d+)\s+z\s+(\d+)\.", l)
            if m:
                meta["pages_total"] = int(m.group(2))
                break

        for i, l in enumerate(lines[:500]):
            m = re.match(
                r"^Nr\s+(\d+)\s*/\s*(\d{2}\.\d{2}\.\d{4})\s*-\s*(\d{2}\.\d{2}\.\d{4})$", l
            )
            if m:
                meta["statement_no"] = int(m.group(1))
                meta["period_from"] = _parse_date_iso(m.group(2))
                meta["period_to"] = _parse_date_iso(m.group(3))

            m = re.match(r"^Data wyciągu:\s*(\d{2}\.\d{2}\.\d{4})$", l)
            if m:
                meta["statement_date"] = _parse_date_iso(m.group(1))

            m = re.match(r"^Data poprzedniego wyciągu:\s*(\d{2}\.\d{2}\.\d{4})$", l)
            if m:
                meta["previous_statement_date"] = _parse_date_iso(m.group(1))

            if l in [
                "Nazwa rachunku:", "Waluta rachunku:",
                "Nr rachunku/NRB:", "Nr rachunku IBAN:",
                "Nr BIC (SWIFT):",
            ]:
                if i + 1 < len(lines):
                    key_map = {
                        "Nazwa rachunku:": "account_name",
                        "Waluta rachunku:": "currency",
                        "Nr rachunku/NRB:": "nrb",
                        "Nr rachunku IBAN:": "iban",
                        "Nr BIC (SWIFT):": "bic",
                    }
                    meta[key_map[l]] = lines[i + 1]

            if l.startswith("Saldo początkowe"):
                for j in range(i, min(i + 8, len(lines))):
                    if AMT_CUR_RE.search(lines[j]):
                        amt, ccy = _parse_money_pl(lines[j])
                        meta["opening_balance"] = float(amt) if amt is not None else None
                        meta["currency"] = meta.get("currency") or ccy
                        break

            if l.startswith("Saldo końcowe:"):
                if i + 1 < len(lines):
                    amt, ccy = _parse_money_pl(lines[i + 1])
                    meta["closing_balance"] = float(amt) if amt is not None else None
                    meta["currency"] = meta.get("currency") or ccy

            m = re.match(r"^Suma uznań\s*\((\d+)\):$", l)
            if m:
                meta["credits_count"] = int(m.group(1))
                if i + 1 < len(lines):
                    amt, ccy = _parse_money_pl(lines[i + 1])
                    meta["credits_total"] = float(amt) if amt is not None else None
                    meta["currency"] = meta.get("currency") or ccy

            m = re.match(r"^Suma obciążeń\s*\((\d+)\):$", l)
            if m:
                meta["debits_count"] = int(m.group(1))
                if i + 1 < len(lines):
                    amt, ccy = _parse_money_pl(lines[i + 1])
                    meta["debits_total"] = float(amt) if amt is not None else None
                    meta["currency"] = meta.get("currency") or ccy

            if l == "Limit zadłużenia:" and i + 1 < len(lines):
                amt, _ = _parse_money_pl(lines[i + 1])
                meta["debt_limit"] = float(amt) if amt is not None else None

            if l == "Kwota prowizji zaległej:" and i + 1 < len(lines):
                amt, _ = _parse_money_pl(lines[i + 1])
                meta["overdue_fee_amount"] = float(amt) if amt is not None else None

            if l == "Kwota zablokowana:" and i + 1 < len(lines):
                amt, _ = _parse_money_pl(lines[i + 1])
                meta["blocked_amount"] = float(amt) if amt is not None else None

            if l == "Saldo dostępne:" and i + 1 < len(lines):
                amt, _ = _parse_money_pl(lines[i + 1])
                meta["available_balance"] = float(amt) if amt is not None else None

        for k in ("nrb", "iban"):
            if k in meta and isinstance(meta[k], str):
                meta[f"{k}_normalized"] = _normalize_nrb_or_iban(meta[k])

        return meta

    def _find_table_start(self, lines: List[str]) -> int:
        for i in range(len(lines) - 3):
            if lines[i] == "Data księgowania" and "/ Data transakcji" in lines[i + 1]:
                return i
        raise RuntimeError("ING: nie znaleziono nagłówka tabeli transakcji.")

    def _extract_structured_details(
        self, raw_lines: List[str]
    ) -> Tuple[Dict[str, Any], List[str]]:
        details: Dict[str, Any] = {}
        free: List[str] = []
        for l in raw_lines:
            m = re.match(r"^Płatność kartą\s+(\d{2}\.\d{2}\.\d{4})$", l)
            if m:
                details["card_payment_date"] = _parse_date_iso(m.group(1))
                details["method"] = "card"
                continue
            m = re.match(r"^Nr karty\s+(.+)$", l)
            if m:
                details["card_number_masked"] = m.group(1).strip()
                continue
            m = re.match(r"^Płatność BLIK\s+(\d{2}\.\d{2}\.\d{4})$", l)
            if m:
                details["blik_payment_date"] = _parse_date_iso(m.group(1))
                details["method"] = "blik_payment"
                continue
            m = re.match(r"^Nr transakcji\s+(\d+)$", l)
            if m:
                details["blik_transaction_no"] = m.group(1)
                continue
            m = re.match(r"^Przelew na telefon\s+(.+)$", l)
            if m:
                details["phone_transfer_to"] = m.group(1).strip()
                details["method"] = "blik_phone_transfer"
                continue
            if l == "Przelew na telefon":
                details["method"] = details.get("method") or "blik_phone_transfer"
                continue
            m = re.match(r"^Dla\s+(.+)$", l)
            if m:
                details["transfer_to_name"] = m.group(1).strip()
                continue
            m = re.match(r"^Od\s+(.+)$", l)
            if m:
                details["transfer_from_name"] = m.group(1).strip()
                continue
            m = re.match(r"^Zlecenie(\d+)$", l)
            if m:
                details["order_id"] = m.group(1)
                continue
            if URL_RE.match(l) or DOMAIN_RE.match(l):
                details.setdefault("urls", []).append(l)
                continue
            free.append(l)
        return details, free

    def _split_counterparty_vs_title(
        self, channel: Optional[str], rest: List[str]
    ) -> Tuple[List[str], List[str]]:
        if not rest:
            return [], []
        markers: List[re.Pattern] = []
        if channel == "TR.KART":
            markers = [
                re.compile(r"^Płatność kartą\b", re.IGNORECASE),
                re.compile(r"^Nr karty\b", re.IGNORECASE),
            ]
        elif channel == "TR.BLIK":
            markers = [
                re.compile(r"^Płatność BLIK\b", re.IGNORECASE),
                re.compile(r"^Nr transakcji\b", re.IGNORECASE),
            ]
        elif channel == "P.BLIK":
            markers = [
                re.compile(r"^Przelew na telefon\b", re.IGNORECASE),
                re.compile(r"^Dla\b", re.IGNORECASE),
                re.compile(r"^Od\b", re.IGNORECASE),
            ]
        else:
            markers = [
                re.compile(r"^Zlecenie\d+\b", re.IGNORECASE),
                TITLE_START_RE,
                DETAIL_LINE_RE,
            ]
        split_idx: Optional[int] = None
        for idx, l in enumerate(rest):
            if any(p.match(l) for p in markers) or URL_RE.match(l) or DOMAIN_RE.match(l):
                split_idx = idx
                break
        if split_idx is None and channel in {"PRZELEW", "ST.ZLEC"}:
            if len(rest) >= 4:
                split_idx = 2
            else:
                split_idx = len(rest)
        if split_idx is None:
            split_idx = len(rest)
        return rest[:split_idx], rest[split_idx:]

    def _parse_transactions(self, lines: List[str]) -> List[Dict[str, Any]]:
        start = self._find_table_start(lines)
        i = start + 1
        while i < len(lines) and not DATE_ONLY_RE.match(lines[i]):
            i += 1
        txs: List[Dict[str, Any]] = []
        CHANNELS = {"TR.KART", "TR.BLIK", "P.BLIK", "PRZELEW", "ST.ZLEC"}
        while i < len(lines):
            if not DATE_ONLY_RE.match(lines[i]):
                i += 1
                continue
            posting = lines[i]
            i += 1
            trans = posting
            if i < len(lines) and DATE_ONLY_RE.match(lines[i]):
                trans = lines[i]
                i += 1

            contractor_raw: List[str] = []
            while i < len(lines):
                l = lines[i]
                if l.startswith("Nazwa i adres "):
                    break
                if l in CHANNELS or AMOUNT_LINE_RE.match(l) or DATE_ONLY_RE.match(l):
                    break
                if l.lower().startswith("strona:") or l.lower().startswith("wyciąg z rachunku"):
                    i += 1
                    continue
                contractor_raw.append(l)
                i += 1

            counterparty_account: Optional[str] = None
            ing_internal_id: Optional[str] = None
            contractor_ids_other: List[str] = []
            for cl in contractor_raw:
                if counterparty_account is None and (NRB_SPACED_RE.match(cl) or IBAN_RE.match(cl)):
                    counterparty_account = _normalize_nrb_or_iban(cl)
                elif ing_internal_id is None and ING_INTERNAL_ID_RE.match(cl):
                    ing_internal_id = cl
                else:
                    contractor_ids_other.append(cl)

            body_lines: List[str] = []
            channel: Optional[str] = None
            while i < len(lines):
                l = lines[i]
                if l.lower().startswith("strona:"):
                    i += 1
                    continue
                if l in CHANNELS:
                    channel = l
                    i += 1
                    break
                if AMOUNT_LINE_RE.match(l) or DATE_ONLY_RE.match(l):
                    break
                body_lines.append(l)
                i += 1

            refs: List[str] = []
            while i < len(lines):
                l = lines[i]
                if l.lower().startswith("strona:"):
                    i += 1
                    continue
                if AMOUNT_LINE_RE.match(l) or DATE_ONLY_RE.match(l):
                    break
                refs.append(l)
                i += 1

            txn_ref: Optional[str] = None
            for r in refs:
                rr = _norm(r).replace(" ", "")
                if LONG_REF_RE.match(rr):
                    txn_ref = rr
                    break

            amount: Optional[Decimal] = None
            currency: Optional[str] = None
            if i < len(lines) and AMOUNT_LINE_RE.match(lines[i]):
                amount, currency = _parse_money_pl(lines[i])
                i += 1
            else:
                amount, currency = _parse_money_pl(" ".join(refs + body_lines))

            counterparty: Dict[str, Any] = {}
            title_lines: List[str] = body_lines
            body_raw = body_lines[:]

            if body_lines and body_lines[0].startswith("Nazwa i adres "):
                label = body_lines[0]
                rest = body_lines[1:]
                role = "unknown"
                first = ""
                if label.startswith("Nazwa i adres odbiorcy:"):
                    role = "recipient"
                    first = label.split(":", 1)[1].strip()
                elif label.startswith("Nazwa i adres płatnika:"):
                    role = "payer"
                    first = label.split(":", 1)[1].strip()
                counterparty_lines, title_lines = self._split_counterparty_vs_title(channel, rest)
                name_addr_lines: List[str] = []
                if first:
                    name_addr_lines.append(first)
                name_addr_lines.extend(counterparty_lines)
                counterparty = {
                    "counterparty_role": role,
                    "counterparty_name_address_lines": name_addr_lines,
                    "counterparty_name_address": ", ".join([x for x in name_addr_lines if x]).strip(),
                }

            details, title_free = self._extract_structured_details(title_lines)
            txs.append({
                "posting_date": _parse_date_iso(posting),
                "transaction_date": _parse_date_iso(trans),
                "amount": float(amount) if amount is not None else None,
                "currency": currency,
                "direction": "credit" if (amount is not None and amount > 0) else "debit",
                "channel": channel,
                "transaction_ref": txn_ref,
                "refs_raw_lines": refs,
                "counterparty_account": counterparty_account,
                "ing_internal_counterparty_id": ing_internal_id,
                "contractor_ids_other": contractor_ids_other,
                "body_raw_lines": body_raw,
                **counterparty,
                "title_raw_lines": title_free,
                "title": " ".join(title_free).strip(),
                "details": details,
            })
        return txs

    def parse(self, lines: List[str], source_file: str) -> _Statement:
        meta = self._parse_meta(lines)
        txs = self._parse_transactions(lines)

        # Reconciliation check
        try:
            ob = _safe_decimal(meta.get("opening_balance")) or Decimal("0")
            cb = _safe_decimal(meta.get("closing_balance")) or Decimal("0")
            credits = sum(
                Decimal(str(t["amount"]))
                for t in txs if t.get("amount") is not None and t["amount"] > 0
            )
            debits = sum(
                Decimal(str(t["amount"]))
                for t in txs if t.get("amount") is not None and t["amount"] < 0
            )
            meta["reconciliation_calc"] = {
                "opening": float(ob),
                "credits_sum": float(credits),
                "debits_sum": float(debits),
                "closing_expected": float(ob + credits + debits),
                "closing_reported": float(cb),
            }
            meta["reconciliation_ok"] = (ob + credits + debits == cb)
        except Exception:
            meta["reconciliation_ok"] = None

        return _Statement(meta=meta, transactions=txs, source_file=source_file)


_register(_INGStatementParser())


# ------------------------------------------------ public API

def parse_bank_statement(pdf_path: Path) -> ParseResult:
    """Parse a bank statement PDF using PyMuPDF line-based extraction.

    Returns a ParseResult compatible with the existing AML pipeline.
    """
    lines, page_count = extract_lines_from_pdf(pdf_path)

    if not lines:
        raise RuntimeError("PDF nie zawiera warstwy tekstowej (brak tekstu).")

    parser = _detect_parser(lines)
    log.info("Universal parser: bank=%s, lines=%d, pages=%d", parser.name, len(lines), page_count)

    stmt = parser.parse(lines, source_file=str(pdf_path))
    meta = stmt.meta

    # Convert to standard ParseResult
    raw_transactions: List[RawTransaction] = []
    for tx in stmt.transactions:
        amt = tx.get("amount") or 0.0
        # Build counterparty string
        cp = tx.get("counterparty_name_address", "")
        if not cp and tx.get("counterparty_account"):
            cp = tx["counterparty_account"]

        raw_transactions.append(RawTransaction(
            date=tx.get("posting_date", ""),
            date_valuation=tx.get("transaction_date"),
            amount=float(amt),
            currency=tx.get("currency", "PLN"),
            balance_after=None,  # ING doesn't provide per-tx balance
            counterparty=cp,
            title=tx.get("title", ""),
            raw_text=str(tx.get("body_raw_lines", [])),
            direction="in" if amt >= 0 else "out",
            bank_category=tx.get("channel", ""),
        ))

    info = StatementInfo(
        bank=parser.name,
        account_number=meta.get("iban_normalized", meta.get("nrb_normalized", "")),
        account_holder=meta.get("holder_name", ""),
        period_from=meta.get("period_from"),
        period_to=meta.get("period_to"),
        opening_balance=meta.get("opening_balance"),
        closing_balance=meta.get("closing_balance"),
        available_balance=meta.get("available_balance"),
        currency=meta.get("currency", "PLN"),
        declared_credits_sum=meta.get("credits_total"),
        declared_credits_count=meta.get("credits_count"),
        declared_debits_sum=meta.get("debits_total"),
        declared_debits_count=meta.get("debits_count"),
        debt_limit=meta.get("debt_limit"),
        overdue_commission=meta.get("overdue_fee_amount"),
        blocked_amount=meta.get("blocked_amount"),
    )

    return ParseResult(
        bank=parser.name,
        info=info,
        transactions=raw_transactions,
        page_count=page_count,
        parse_method="pymupdf_lines",
    )
