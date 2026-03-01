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
    parse_method: str = "pymupdf_lines"


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
    supported = ", ".join(p.name for p in _PARSERS)
    raise RuntimeError(
        f"Nie rozpoznano banku w przesłanym dokumencie. "
        f"Obsługiwane banki: {supported}. "
        f"Jeśli to wyciąg bankowy — zostanie użyty parser generyczny (fallback)."
    )


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

    def _parse_transactions_coord(self, pdf_path: str) -> List[Dict[str, Any]]:
        """Parse ING transactions using coordinate-based column detection.

        Uses the INGParser's coordinate-aware extraction (get_text("dict"))
        which correctly separates counterparty, title, details, and amount
        columns.  Falls back gracefully if import or parsing fails.

        The plain get_text("text") approach flattens columns and scrambles
        the order for ING statements — this method solves that problem.
        """
        try:
            from ..finance.parsers.ing import INGParser
            ing = INGParser()
            raw_txs, warnings = ing._parse_transactions_from_pdf(Path(pdf_path))

            if not raw_txs:
                return []

            result: List[Dict[str, Any]] = []
            for rt in raw_txs:
                # Convert dates from DD.MM.YYYY → YYYY-MM-DD
                posting = _parse_date_iso(rt.date) if rt.date and "." in rt.date else rt.date
                trans = None
                if rt.date_valuation:
                    trans = _parse_date_iso(rt.date_valuation) if "." in rt.date_valuation else rt.date_valuation

                amount = rt.amount
                currency = rt.currency or "PLN"
                counterparty_name = rt.counterparty or ""
                title = rt.title or ""
                channel = rt.bank_category or ""

                # Get extra details if available (INGParser attaches these)
                details = getattr(rt, "details", {}) or {}
                refs = getattr(rt, "refs", []) or []
                txn_ref = refs[0] if refs else None
                cp_role = getattr(rt, "counterparty_role", None)

                tx_dict: Dict[str, Any] = {
                    "posting_date": posting,
                    "transaction_date": trans or posting,
                    "amount": float(amount) if amount is not None else None,
                    "currency": currency,
                    "direction": "credit" if (amount is not None and amount > 0) else "debit",
                    "channel": channel,
                    "transaction_ref": txn_ref,
                    "refs_raw_lines": refs,
                    "counterparty_account": None,
                    "ing_internal_counterparty_id": None,
                    "contractor_ids_other": [],
                    "body_raw_lines": [rt.raw_text] if rt.raw_text else [],
                    "counterparty_role": cp_role,
                    "counterparty_name_address_lines": [counterparty_name] if counterparty_name else [],
                    "counterparty_name_address": counterparty_name,
                    "title_raw_lines": [title] if title else [],
                    "title": title,
                    "details": details,
                }
                result.append(tx_dict)

            if result:
                log.info("ING coordinate parser: %d transactions extracted", len(result))
            return result

        except ImportError:
            log.debug("INGParser not available for coordinate parsing")
            return []
        except Exception as e:
            log.warning("Coordinate-based ING parsing failed: %s", e)
            return []

    def parse(self, lines: List[str], source_file: str) -> _Statement:
        meta = self._parse_meta(lines)

        # Try coordinate-based parsing first (much more reliable for columnar ING PDFs).
        # Falls back to text-based sequential parsing if coordinate approach fails.
        parse_method = "pymupdf_lines"
        txs = self._parse_transactions_coord(source_file)
        if txs:
            parse_method = "pymupdf_coord_ing"
        else:
            log.info("ING: coordinate parser returned 0 txs, falling back to text-based parsing")
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

        return _Statement(meta=meta, transactions=txs, source_file=source_file, parse_method=parse_method)


_register(_INGStatementParser())


# ----------------------------------------------------------- mBank parser

class _MBankStatementParser(_BankParser):
    """Parser for mBank (Poland) 'Elektroniczne zestawienie operacji' statements."""

    name = "mBank"

    # Standalone date line: just YYYY-MM-DD (PyMuPDF extracts each cell separately)
    _SOLE_DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})$")
    # Standalone money value on its own line: -353,39 or 18 835,28
    _MONEY_LINE_RE = re.compile(r"^([\-+]?\d[\d ]*,\d{2})$")
    # 26-digit NRB (Polish bank account)
    _NRB_RE = re.compile(r"^\d{26}$")

    # Page noise lines to skip
    _NOISE_PATS = [
        re.compile(r"^Strona\s*:", re.I),
        re.compile(r"^mBank", re.I),
        re.compile(r"^Skrytka", re.I),
        re.compile(r"^www\.mbank", re.I),
        re.compile(r"^mLinia", re.I),
        re.compile(r"^\+?\d{2}\s*\(\d{2}\)"),
        re.compile(r"^Niniejszy\s+dokument", re.I),
        re.compile(r"^Nie\s+wymaga\s+podpisu", re.I),
        re.compile(r"^W\s+przypadku\s+wyst", re.I),
        re.compile(r"^kontakt\s+z\s+mLini", re.I),
    ]

    # Exact header fragments to skip (column headers repeated per page)
    _SKIP_EXACT = frozenset({
        "data", "księgowania", "operacji", "opis operacji",
        "kwota", "saldo po", "saldo po operacji", "operacje",
    })

    # Operation type → standardised channel
    _CHANNEL_MAP = {
        "BLIK ZAKUP E-COMMERCE": "BLIK_MERCHANT",
        "BLIK KOR. ZAKUPU E-COMMERCE": "BLIK_MERCHANT",
        "BLIK P2P-WYCHODZĄCY": "BLIK_P2P",
        "BLIK P2P-PRZYCHODZĄCY": "BLIK_P2P",
        "ZAKUP PRZY UŻYCIU KARTY": "CARD",
        "PRZELEW WEWNĘTRZNY PRZYCHODZĄCY": "TRANSFER",
        "PRZELEW WEWNĘTRZNY WYCHODZĄCY": "TRANSFER",
        "PRZELEW ZEWNĘTRZNY PRZYCHODZĄCY": "TRANSFER",
        "PRZELEW ZEWNĘTRZNY WYCHODZĄCY": "TRANSFER",
        "PRZELEW WŁASNY": "TRANSFER",
        "PRZELEW NA TWOJE CELE": "TRANSFER",
        "WYPŁATA Z CELU": "TRANSFER",
        "WPŁATA WE WPŁATOMACIE": "CASH",
        "WYPŁATA Z BANKOMATU": "CASH",
    }

    # ---- detection ----

    def can_parse(self, lines: List[str]) -> bool:
        head = " ".join(lines[:120]).lower()
        return "mbank" in head and (
            "zestawienie operacji" in head or "mkonto" in head
        )

    # ---- helpers ----

    def _parse_money(self, s: str) -> Optional[float]:
        """Parse Polish amount: '1 234,56' → 1234.56, '-20 000,00' → -20000.0"""
        if not s:
            return None
        s = s.strip().replace("\xa0", " ").replace(" ", "").replace(",", ".")
        try:
            return float(s)
        except ValueError:
            return None

    def _is_noise(self, line: str) -> bool:
        for p in self._NOISE_PATS:
            if p.match(line):
                return True
        if line.strip().lower() in self._SKIP_EXACT:
            return True
        if re.match(r"^Data\s+(księgowania|operacji)", line, re.I):
            return True
        return False

    def _infer_channel(self, op_type: str) -> str:
        upper = op_type.strip().upper()
        for key, ch in self._CHANNEL_MAP.items():
            if upper.startswith(key):
                return ch
        return ""

    def _extract_counterparty(
        self, desc_lines: List[str], op_type: str
    ) -> Tuple[str, Optional[str], str]:
        """Return (counterparty, counterparty_account, title)."""
        upper = (op_type or "").upper()

        # --- BLIK E-COMMERCE: next line = merchant ---
        if upper.startswith("BLIK ZAKUP") or upper.startswith("BLIK KOR."):
            cp = desc_lines[0] if desc_lines else ""
            return cp.strip(), None, op_type

        # --- CARD purchase: merchant DATA TRANSAKCJI: date ---
        if upper.startswith("ZAKUP PRZY UŻYCIU KARTY"):
            if desc_lines:
                m = re.match(
                    r"(.+?)\s+DATA TRANSAKCJI:\s*\S+", desc_lines[0]
                )
                cp = m.group(1).strip() if m else desc_lines[0]
            else:
                cp = ""
            return cp.strip(), None, op_type

        # --- Transfers: split on 26-digit NRB ---
        if any(k in upper for k in ("PRZELEW", "WPŁATA", "WYPŁATA")):
            name_parts: List[str] = []
            title_parts: List[str] = []
            cp_account: Optional[str] = None
            found_acct = False
            for ln in desc_lines:
                stripped = re.sub(r"\s+", "", ln)
                if not found_acct and self._NRB_RE.match(stripped):
                    cp_account = stripped
                    found_acct = True
                elif not found_acct:
                    name_parts.append(ln)
                else:
                    title_parts.append(ln)
            cp = " ".join(name_parts).strip()
            title = " ".join(title_parts).strip() if title_parts else op_type
            return cp, cp_account, title

        # --- BLIK P2P ---
        if upper.startswith("BLIK P2P"):
            title = " ".join(desc_lines).strip() if desc_lines else op_type
            return "", None, title

        # --- Default ---
        if desc_lines:
            return desc_lines[0].strip(), None, " ".join(desc_lines[1:]).strip() or op_type
        return "", None, op_type

    # ---- meta parsing ----

    def _parse_meta(self, lines: List[str]) -> Dict[str, Any]:
        meta: Dict[str, Any] = {}

        def _next_non_empty(idx: int, max_ahead: int = 3) -> str:
            """Get next non-empty stripped line after *idx*."""
            for j in range(idx + 1, min(idx + 1 + max_ahead, len(lines))):
                s = lines[j].strip()
                if s:
                    return s
            return ""

        scan_limit = min(len(lines), 500)

        for i, l in enumerate(lines[:scan_limit]):
            # Period: "... za okres od YYYY-MM-DD do YYYY-MM-DD"
            m = re.search(
                r"za\s+okres\s+od\s+(\d{4}-\d{2}-\d{2})\s+do\s+(\d{4}-\d{2}-\d{2})",
                l,
            )
            if m:
                meta["period_from"] = m.group(1)
                meta["period_to"] = m.group(2)
                # Holder name: UPPERCASE line just before period line
                for j in range(i - 1, max(i - 5, -1), -1):
                    cand = lines[j].strip()
                    if cand and re.match(
                        r"^[A-ZĄĆĘŁŃÓŚŹŻ][A-ZĄĆĘŁŃÓŚŹŻ\s\-]+$", cand
                    ):
                        meta["holder_name"] = cand
                        break

            # --- Account number ---
            # Multi-line: "Nr rachunku" alone, number on next line
            if re.match(r"^Nr\s+rachunku$", l, re.I) and "account_number" not in meta:
                nxt = _next_non_empty(i)
                digits = nxt.replace(" ", "")
                if re.match(r"^\d{26}$", digits):
                    meta["account_number"] = digits
            # Inline: "Nr rachunku 51 1140 2004 ..."
            m = re.match(
                r"Nr\s+rachunku\s+(\d[\d\s]+\d)", l
            )
            if m and "account_number" not in meta:
                digits = m.group(1).replace(" ", "")
                if len(digits) == 26:
                    meta["account_number"] = digits

            # --- Currency ---
            # Multi-line: "Waluta" alone, "PLN" on next line
            if re.match(r"^Waluta$", l, re.I) and "currency" not in meta:
                nxt = _next_non_empty(i)
                if re.match(r"^[A-Z]{3}$", nxt):
                    meta["currency"] = nxt
            # Inline: "Waluta PLN"
            m = re.match(r"Waluta\s+([A-Z]{3})", l)
            if m and "currency" not in meta:
                meta["currency"] = m.group(1)

            # --- Opening balance: "Saldo początkowe: 19 188,67" ---
            m = re.match(r"Saldo\s+pocz[aą]tkowe:\s*([\d\s]+,\d{2})", l)
            if m:
                meta["opening_balance"] = self._parse_money(m.group(1))

            # --- Closing balance (scans full file, not just first 300 lines) ---
            m = re.match(r"Saldo\s+ko[nń]cowe:\s*([\d\s]+,\d{2})", l)
            if m:
                meta["closing_balance"] = self._parse_money(m.group(1))

            # --- Summary: Uznania / Obciążenia ---
            # Multi-line: "Uznania" alone, count on next, sum after that
            if re.match(r"^Uznania$", l, re.I) and "credits_count" not in meta:
                j = i + 1
                while j < len(lines) and not lines[j].strip():
                    j += 1
                if j < len(lines) and re.match(r"^\d+$", lines[j].strip()):
                    meta["credits_count"] = int(lines[j].strip())
                    j += 1
                    while j < len(lines) and not lines[j].strip():
                        j += 1
                    if j < len(lines):
                        val = self._parse_money(lines[j].strip())
                        if val is not None:
                            meta["credits_total"] = abs(val)
            # Inline: "Uznania 18 11 867,12"
            m = re.match(r"Uznania\s+(\d+)\s+([\d\s]+,\d{2})", l)
            if m and "credits_count" not in meta:
                meta["credits_count"] = int(m.group(1))
                meta["credits_total"] = self._parse_money(m.group(2))

            # Multi-line: "Obciążenia" alone
            if re.match(r"^Obci[aą][żz]enia$", l, re.I) and "debits_count" not in meta:
                j = i + 1
                while j < len(lines) and not lines[j].strip():
                    j += 1
                if j < len(lines) and re.match(r"^\d+$", lines[j].strip()):
                    meta["debits_count"] = int(lines[j].strip())
                    j += 1
                    while j < len(lines) and not lines[j].strip():
                        j += 1
                    if j < len(lines):
                        val = self._parse_money(lines[j].strip())
                        if val is not None:
                            meta["debits_total"] = abs(val)
            # Inline: "Obciążenia 38 29 569,86"
            m = re.match(r"Obci[aą][żz]enia\s+(\d+)\s+([\d\s]+,\d{2})", l)
            if m and "debits_count" not in meta:
                meta["debits_count"] = int(m.group(1))
                meta["debits_total"] = self._parse_money(m.group(2))

            # --- Credit limit ---
            # Multi-line: "Limit kredytu" alone, "0,00 PLN" on next
            if re.match(r"^Limit\s+kredytu$", l, re.I) and "debt_limit" not in meta:
                nxt = _next_non_empty(i)
                m2 = re.match(r"([\d\s]+,\d{2})", nxt)
                if m2:
                    meta["debt_limit"] = self._parse_money(m2.group(1))
            # Inline: "Limit kredytu 0,00 PLN"
            m = re.match(r"Limit\s+kredytu\s+([\d\s]+,\d{2})", l)
            if m and "debt_limit" not in meta:
                meta["debt_limit"] = self._parse_money(m.group(1))

        return meta

    # ---- transaction parsing ----

    def _parse_transactions(self, lines: List[str]) -> List[Dict[str, Any]]:
        """Parse transactions using a state machine for cell-per-line format.

        PyMuPDF extracts mBank table cells as separate lines:
          [i  ] 2025-11-02          ← booking date (alone)
          [i+1] 2025-11-02          ← operation date (alone)
          [i+2] BLIK ZAKUP E-COMMERCE  ← operation type
          [i+3] LEK24.PL             ← description line(s)
          [i+4] -353,39              ← amount (alone)
          [i+5] 18 835,28            ← balance after (alone)
        """
        txs: List[Dict[str, Any]] = []

        # Find table start (after "Saldo początkowe:")
        start_idx: Optional[int] = None
        for i, l in enumerate(lines):
            if re.match(r"Saldo\s+pocz[aą]tkowe:", l):
                start_idx = i + 1
                break
        if start_idx is None:
            return txs

        # --- State machine ---
        SCAN, GOT_BOOKING, DESC, GOT_AMOUNT = 0, 1, 2, 3
        state = SCAN
        booking = ""
        op_date = ""
        op_type = ""
        desc: List[str] = []
        amount: Optional[float] = None
        balance: Optional[float] = None

        def _finalize() -> None:
            nonlocal state
            if amount is not None:
                cp, cp_acct, title = self._extract_counterparty(desc, op_type)
                channel = self._infer_channel(op_type)
                txs.append({
                    "posting_date": booking,
                    "transaction_date": op_date,
                    "amount": amount,
                    "currency": "PLN",
                    "balance_after": balance,
                    "direction": "credit" if amount > 0 else "debit",
                    "channel": channel,
                    "counterparty_name_address": cp,
                    "counterparty_account": cp_acct,
                    "title": title or op_type,
                    "body_raw_lines": [
                        f"{booking} {op_date} {op_type}"
                    ] + list(desc),
                    "details": {},
                })
            state = SCAN

        for i in range(start_idx, len(lines)):
            l = lines[i].strip()

            # End of transaction table
            if re.match(r"Saldo\s+ko[nń]cowe:", l):
                if state in (GOT_AMOUNT, DESC):
                    _finalize()
                break

            # Skip empty lines and page noise at all states
            if not l or self._is_noise(l):
                continue

            date_m = self._SOLE_DATE_RE.match(l)
            money_m = self._MONEY_LINE_RE.match(l)

            if state == SCAN:
                if date_m:
                    booking = date_m.group(1)
                    state = GOT_BOOKING

            elif state == GOT_BOOKING:
                if date_m:
                    # Second date = operation date → start reading description
                    op_date = date_m.group(1)
                    op_type = ""
                    desc = []
                    amount = None
                    balance = None
                    state = DESC
                else:
                    # Not a date — false positive, go back to scanning
                    state = SCAN

            elif state == DESC:
                if money_m:
                    amount = self._parse_money(money_m.group(1))
                    state = GOT_AMOUNT
                elif date_m:
                    # New transaction started before we found amount
                    # (shouldn't normally happen — finalize incomplete tx)
                    _finalize()
                    booking = date_m.group(1)
                    state = GOT_BOOKING
                else:
                    # First non-empty text = operation type, rest = details
                    if not op_type:
                        op_type = l
                    else:
                        desc.append(l)

            elif state == GOT_AMOUNT:
                if money_m:
                    # This is the balance-after line
                    balance = self._parse_money(money_m.group(1))
                    _finalize()
                elif date_m:
                    # Balance line was missing — new tx starting
                    _finalize()
                    booking = date_m.group(1)
                    state = GOT_BOOKING
                else:
                    # Unexpected text — try to parse as money anyway
                    val = self._parse_money(l)
                    if val is not None:
                        balance = val
                        _finalize()

        # Finalize last pending transaction (if file ends without "Saldo końcowe")
        if state in (GOT_AMOUNT, DESC):
            _finalize()
        return txs

    # ---- public API ----

    def parse(self, lines: List[str], source_file: str) -> _Statement:
        meta = self._parse_meta(lines)
        txs = self._parse_transactions(lines)

        # Reconciliation check
        try:
            ob = _safe_decimal(meta.get("opening_balance")) or Decimal("0")
            cb = _safe_decimal(meta.get("closing_balance")) or Decimal("0")
            credits = sum(
                Decimal(str(t["amount"]))
                for t in txs
                if t.get("amount") is not None and t["amount"] > 0
            )
            debits = sum(
                Decimal(str(t["amount"]))
                for t in txs
                if t.get("amount") is not None and t["amount"] < 0
            )
            meta["reconciliation_calc"] = {
                "opening": float(ob),
                "credits_sum": float(credits),
                "debits_sum": float(debits),
                "closing_expected": float(ob + credits + debits),
                "closing_reported": float(cb),
            }
            meta["reconciliation_ok"] = ob + credits + debits == cb
        except Exception:
            meta["reconciliation_ok"] = None

        return _Statement(
            meta=meta,
            transactions=txs,
            source_file=source_file,
            parse_method="pymupdf_lines_mbank",
        )


_register(_MBankStatementParser())


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

        # Build raw_text including structured details (card numbers, BLIK refs, etc.)
        body_lines = tx.get("body_raw_lines", [])
        details = tx.get("details") or {}
        raw_parts = list(body_lines) if isinstance(body_lines, list) else [str(body_lines)]
        # Re-inject structured details so card numbers etc. are searchable
        if details.get("card_number_masked"):
            raw_parts.append(f"Nr karty {details['card_number_masked']}")
        if details.get("card_payment_date"):
            raw_parts.append(f"Płatność kartą {details['card_payment_date']}")
        if details.get("blik_transaction_no"):
            raw_parts.append(f"Nr transakcji {details['blik_transaction_no']}")
        if details.get("phone_transfer_to"):
            raw_parts.append(f"Przelew na telefon {details['phone_transfer_to']}")
        # Preserve counterparty account number in raw_text for account detection
        cp_account = tx.get("counterparty_account")
        if cp_account:
            # Format with spaces for reliable extraction: XX XXXX XXXX XXXX XXXX XXXX XXXX
            ca = re.sub(r"[\s\-]", "", cp_account)
            if len(ca) == 26 and ca.isdigit():
                spaced = f"{ca[:2]} {ca[2:6]} {ca[6:10]} {ca[10:14]} {ca[14:18]} {ca[18:22]} {ca[22:26]}"
                raw_parts.append(f"Nr rachunku {spaced}")
            else:
                raw_parts.append(f"Nr rachunku {cp_account}")

        raw_transactions.append(RawTransaction(
            date=tx.get("posting_date", ""),
            date_valuation=tx.get("transaction_date"),
            amount=float(amt),
            currency=tx.get("currency", "PLN"),
            balance_after=tx.get("balance_after"),
            counterparty=cp,
            title=tx.get("title", ""),
            raw_text=" | ".join(raw_parts),
            direction="in" if amt >= 0 else "out",
            bank_category=tx.get("channel", ""),
        ))

    info = StatementInfo(
        bank=parser.name,
        account_number=meta.get("iban_normalized", meta.get("nrb_normalized", meta.get("account_number", ""))),
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

    parse_method = getattr(stmt, "parse_method", "pymupdf_lines")

    return ParseResult(
        bank=parser.name,
        info=info,
        transactions=raw_transactions,
        page_count=page_count,
        parse_method=parse_method,
    )
