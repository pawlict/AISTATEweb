"""MT940 (SWIFT) bank statement parser.

Parses MT940/STA files commonly exported by Polish banks (ING, mBank, etc.)
into the same transaction/statement format used by the PDF spatial parser,
enabling cross-validation between PDF and electronic statement data.

MT940 field reference:
  :20:  Transaction reference number
  :25:  Account identification (IBAN)
  :28C: Statement number / sequence number
  :60F: Opening balance  (F=first, M=intermediate)
  :61:  Statement line (transaction)
  :86:  Information to account owner (transaction details)
  :62F: Closing balance  (F=final, M=intermediate)
  :64:  Available balance
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger("aistate.aml.mt940_parser")

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class MT940Transaction:
    """Single parsed MT940 transaction."""
    value_date: str          # YYYY-MM-DD
    entry_date: str          # YYYY-MM-DD
    direction: str           # "DEBIT" or "CREDIT"
    amount: float            # always positive
    swift_code: str          # S-type code e.g. "073", "041"
    reference: str           # bank reference id
    counterparty: str        # from ~32/~33
    title: str               # from ~20-~25
    counterparty_account: str  # from ~38 (IBAN)
    counterparty_bank: str   # from ~30 (bank code)
    raw_86: str              # full :86: content
    row_index: int = 0


@dataclass
class MT940Statement:
    """Parsed MT940 statement."""
    account_number: str      # IBAN from :25:
    account_holder: str      # from trailing :86: NAME ACCOUNT OWNER
    statement_number: str    # from :28C:
    opening_balance: float
    closing_balance: float
    available_balance: Optional[float]
    currency: str
    balance_date: str        # YYYY-MM-DD
    transactions: List[MT940Transaction] = field(default_factory=list)
    # Computed
    total_debits: float = 0.0
    total_credits: float = 0.0
    debit_count: int = 0
    credit_count: int = 0


# ---------------------------------------------------------------------------
# Main parser
# ---------------------------------------------------------------------------

def parse_mt940(file_path: Path, encoding: str = "auto") -> MT940Statement:
    """Parse an MT940/STA file into structured statement data.

    Args:
        file_path: Path to .sta/.mt940 file
        encoding: File encoding ('auto' tries cp1250, utf-8, latin-1)

    Returns:
        MT940Statement with all transactions parsed.
    """
    text = _read_file(file_path, encoding)
    return _parse_mt940_text(text)


def parse_mt940_text(text: str) -> MT940Statement:
    """Parse MT940 content from a string."""
    return _parse_mt940_text(text)


def _read_file(file_path: Path, encoding: str = "auto") -> str:
    """Read MT940 file with encoding detection."""
    if encoding != "auto":
        return file_path.read_text(encoding=encoding)

    # Try common Polish encodings
    for enc in ["utf-8", "cp1250", "iso-8859-2", "latin-1"]:
        try:
            text = file_path.read_text(encoding=enc)
            # Quick sanity check — MT940 must start with :20: or have it early
            if ":20:" in text[:200] or ":25:" in text[:200]:
                return text
        except (UnicodeDecodeError, ValueError):
            continue

    # Fallback: read as latin-1 (never fails)
    return file_path.read_text(encoding="latin-1")


def _parse_mt940_text(text: str) -> MT940Statement:
    """Core MT940 parsing logic."""
    # Normalize line endings
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    # Extract tag blocks
    account_number = _extract_tag(text, "25") or ""
    # Clean account — remove leading / or country prefix duplication
    account_number = account_number.lstrip("/").strip()

    statement_number = _extract_tag(text, "28C") or ""

    # Opening balance :60F: or :60M:
    opening_raw = _extract_tag(text, "60F") or _extract_tag(text, "60M") or ""
    opening_balance, currency, balance_date = _parse_balance_field(opening_raw)

    # Closing balance :62F: or :62M:
    closing_raw = _extract_tag(text, "62F") or _extract_tag(text, "62M") or ""
    closing_balance, _, _ = _parse_balance_field(closing_raw)

    # Available balance :64:
    avail_raw = _extract_tag(text, "64") or ""
    available_balance = None
    if avail_raw:
        available_balance, _, _ = _parse_balance_field(avail_raw)

    # Account holder from trailing :86: tags
    account_holder = ""
    holder_m = re.search(r":86:NAME ACCOUNT OWNER:(.+?)(?:\n|$)", text)
    if holder_m:
        account_holder = holder_m.group(1).strip()

    # Parse transactions (:61: + :86: pairs)
    transactions = _parse_transactions(text)

    # Compute totals
    total_debits = sum(t.amount for t in transactions if t.direction == "DEBIT")
    total_credits = sum(t.amount for t in transactions if t.direction == "CREDIT")
    debit_count = sum(1 for t in transactions if t.direction == "DEBIT")
    credit_count = sum(1 for t in transactions if t.direction == "CREDIT")

    return MT940Statement(
        account_number=account_number,
        account_holder=account_holder,
        statement_number=statement_number,
        opening_balance=opening_balance,
        closing_balance=closing_balance,
        available_balance=available_balance,
        currency=currency or "PLN",
        balance_date=balance_date or "",
        transactions=transactions,
        total_debits=total_debits,
        total_credits=total_credits,
        debit_count=debit_count,
        credit_count=credit_count,
    )


# ---------------------------------------------------------------------------
# Transaction parsing
# ---------------------------------------------------------------------------

# :61: line format: YYMMDDMMDD[D|C|RD|RC]amount,decStype_ref
_RE_61 = re.compile(
    r":61:(\d{6})(\d{4})"       # value_date(YYMMDD) + entry_date(MMDD)
    r"(R?[DC])"                 # direction: D/C/RD/RC
    r"(\d+,\d{2})"             # amount with comma decimal
    r"S(\d+)"                  # S + swift type code
    r"(.*)"                     # reference (rest of line)
)


def _parse_transactions(text: str) -> List[MT940Transaction]:
    """Extract all :61:/:86: transaction pairs."""
    transactions = []
    lines = text.split("\n")
    i = 0
    tx_idx = 0

    while i < len(lines):
        line = lines[i].strip()

        if line.startswith(":61:"):
            # Parse :61: line
            m = _RE_61.match(line)
            if not m:
                log.warning("Could not parse :61: line: %s", line[:80])
                i += 1
                continue

            value_date_raw = m.group(1)  # YYMMDD
            entry_date_raw = m.group(2)  # MMDD
            direction_raw = m.group(3)   # D/C/RD/RC
            amount_raw = m.group(4)      # "123,45"
            swift_code = m.group(5)
            reference = m.group(6).strip()

            value_date = _parse_yymmdd(value_date_raw)
            entry_date = _parse_mmdd(entry_date_raw, value_date_raw[:2])

            # Direction: D=debit, C=credit, RD=reversal of debit, RC=reversal of credit
            if direction_raw in ("D", "RC"):
                direction = "DEBIT"
            else:
                direction = "CREDIT"

            amount = float(amount_raw.replace(",", "."))

            # Collect :86: lines (may be multiple)
            i += 1
            raw_86_lines = []
            while i < len(lines):
                l = lines[i].strip()
                if l.startswith(":86:"):
                    raw_86_lines.append(l[4:])  # content after :86:
                    i += 1
                elif l.startswith(":61:") or l.startswith(":62") or l.startswith(":64:"):
                    break  # next transaction or closing tag
                elif l.startswith("~") or (raw_86_lines and not l.startswith(":")):
                    # Continuation of :86: with ~XX subfields or plain text
                    raw_86_lines.append(l)
                    i += 1
                else:
                    i += 1
                    break

            raw_86 = "\n".join(raw_86_lines)

            # Parse ~XX subfields from :86:
            subfields = _parse_86_subfields(raw_86)
            counterparty = (subfields.get("32", "") + " " + subfields.get("33", "")).strip()
            title_parts = [subfields.get(f"{k}", "") for k in range(20, 26)]
            title = " ".join(p for p in title_parts if p).strip()
            counterparty_account = subfields.get("38", "")
            counterparty_bank = subfields.get("30", "")

            tx = MT940Transaction(
                value_date=value_date,
                entry_date=entry_date,
                direction=direction,
                amount=amount,
                swift_code=swift_code,
                reference=reference,
                counterparty=counterparty,
                title=title,
                counterparty_account=counterparty_account,
                counterparty_bank=counterparty_bank,
                raw_86=raw_86,
                row_index=tx_idx,
            )
            transactions.append(tx)
            tx_idx += 1
            continue

        i += 1

    return transactions


def _parse_86_subfields(raw: str) -> Dict[str, str]:
    """Parse ING-style ~XX subfield notation from :86: content.

    Format: ~00code~20line1~21line2~30bank_code~31account~32name~33address~38iban
    """
    result: Dict[str, str] = {}
    # Split by ~XX markers
    parts = re.split(r"~(\d{2})", raw)
    # parts[0] is text before first ~XX (usually the type code like "073")
    if parts[0].strip():
        result["type_prefix"] = parts[0].strip()

    for j in range(1, len(parts) - 1, 2):
        key = parts[j]
        value = parts[j + 1].strip() if j + 1 < len(parts) else ""
        if key in result:
            result[key] += " " + value
        else:
            result[key] = value

    return result


# ---------------------------------------------------------------------------
# Balance field parsing
# ---------------------------------------------------------------------------

def _parse_balance_field(raw: str) -> Tuple[float, str, str]:
    """Parse balance field like 'C260131PLN4200,82'.

    Returns: (amount, currency, date_iso)
    """
    if not raw:
        return 0.0, "", ""

    m = re.match(r"([CD])(\d{6})([A-Z]{3})(\d+,\d{2})", raw)
    if not m:
        return 0.0, "", ""

    sign = 1 if m.group(1) == "C" else -1
    date_iso = _parse_yymmdd(m.group(2))
    currency = m.group(3)
    amount = float(m.group(4).replace(",", ".")) * sign
    return amount, currency, date_iso


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------

def _parse_yymmdd(s: str) -> str:
    """Parse YYMMDD to YYYY-MM-DD."""
    if len(s) != 6:
        return ""
    yy, mm, dd = int(s[:2]), s[2:4], s[4:6]
    yyyy = 2000 + yy if yy < 80 else 1900 + yy
    return f"{yyyy}-{mm}-{dd}"


def _parse_mmdd(s: str, yy_prefix: str = "26") -> str:
    """Parse MMDD to YYYY-MM-DD using year prefix from value date."""
    if len(s) != 4:
        return ""
    mm, dd = s[:2], s[2:]
    yy = int(yy_prefix) if yy_prefix else 26
    yyyy = 2000 + yy if yy < 80 else 1900 + yy
    return f"{yyyy}-{mm}-{dd}"


# ---------------------------------------------------------------------------
# Tag extraction
# ---------------------------------------------------------------------------

def _extract_tag(text: str, tag: str) -> Optional[str]:
    """Extract the value of a :TAG: field from MT940 text."""
    pattern = rf":{re.escape(tag)}:(.*?)(?=\n:|$)"
    m = re.search(pattern, text, re.DOTALL)
    if m:
        return m.group(1).strip()
    return None


# ---------------------------------------------------------------------------
# Cross-validation with PDF parser
# ---------------------------------------------------------------------------

def cross_validate(
    mt940: MT940Statement,
    pdf_transactions: List[Dict[str, Any]],
    pdf_statement_info: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Compare MT940 data with PDF-parsed data for validation.

    Returns a report dict with match/mismatch details.
    """
    report: Dict[str, Any] = {
        "mt940_tx_count": len(mt940.transactions),
        "pdf_tx_count": len(pdf_transactions),
        "matches": [],
        "mt940_only": [],
        "pdf_only": [],
        "balance_check": {},
        "totals_check": {},
    }

    # Balance cross-check
    if pdf_statement_info:
        for field_name, mt940_val in [
            ("opening_balance", mt940.opening_balance),
            ("closing_balance", mt940.closing_balance),
        ]:
            pdf_val = pdf_statement_info.get(field_name)
            if pdf_val is not None:
                try:
                    pdf_float = float(pdf_val)
                    match = abs(pdf_float - mt940_val) < 0.01
                    report["balance_check"][field_name] = {
                        "mt940": mt940_val,
                        "pdf": pdf_float,
                        "match": match,
                    }
                except (ValueError, TypeError):
                    pass

        # Credits/debits totals
        for label, mt940_val in [
            ("total_credits", mt940.total_credits),
            ("total_debits", mt940.total_debits),
            ("credit_count", mt940.credit_count),
            ("debit_count", mt940.debit_count),
        ]:
            pdf_val = pdf_statement_info.get(f"declared_{label}")
            if pdf_val is not None:
                try:
                    pdf_float = float(pdf_val)
                    match = abs(pdf_float - mt940_val) < 0.01
                    report["totals_check"][label] = {
                        "mt940": mt940_val,
                        "pdf": pdf_float,
                        "match": match,
                    }
                except (ValueError, TypeError):
                    pass

    # Transaction matching by date + amount
    pdf_used = set()
    for mt_tx in mt940.transactions:
        mt_amount = mt_tx.amount if mt_tx.direction == "CREDIT" else -mt_tx.amount
        found = False
        for j, pdf_tx in enumerate(pdf_transactions):
            if j in pdf_used:
                continue
            pdf_amount = pdf_tx.get("amount", 0)
            pdf_date = pdf_tx.get("date", "")
            # Match on date + amount (within 0.01 tolerance)
            if pdf_date == mt_tx.entry_date and abs(pdf_amount - mt_amount) < 0.01:
                report["matches"].append({
                    "mt940_idx": mt_tx.row_index,
                    "pdf_idx": j,
                    "date": mt_tx.entry_date,
                    "amount": mt_amount,
                    "mt940_counterparty": mt_tx.counterparty,
                    "pdf_counterparty": pdf_tx.get("counterparty", ""),
                })
                pdf_used.add(j)
                found = True
                break
        if not found:
            report["mt940_only"].append({
                "idx": mt_tx.row_index,
                "date": mt_tx.entry_date,
                "amount": mt_amount,
                "counterparty": mt_tx.counterparty,
            })

    for j, pdf_tx in enumerate(pdf_transactions):
        if j not in pdf_used:
            report["pdf_only"].append({
                "idx": j,
                "date": pdf_tx.get("date", ""),
                "amount": pdf_tx.get("amount", 0),
                "counterparty": pdf_tx.get("counterparty", ""),
            })

    report["match_rate"] = (
        len(report["matches"]) / max(len(mt940.transactions), 1) * 100
    )

    return report


# ---------------------------------------------------------------------------
# Convenience: summary for display
# ---------------------------------------------------------------------------

def statement_summary(stmt: MT940Statement) -> Dict[str, Any]:
    """Return a summary dict suitable for UI display."""
    return {
        "account_number": stmt.account_number,
        "account_holder": stmt.account_holder,
        "currency": stmt.currency,
        "opening_balance": stmt.opening_balance,
        "closing_balance": stmt.closing_balance,
        "available_balance": stmt.available_balance,
        "balance_date": stmt.balance_date,
        "transaction_count": len(stmt.transactions),
        "total_debits": round(stmt.total_debits, 2),
        "total_credits": round(stmt.total_credits, 2),
        "debit_count": stmt.debit_count,
        "credit_count": stmt.credit_count,
        "net_change": round(stmt.total_credits - stmt.total_debits, 2),
        "balance_check": round(
            stmt.opening_balance + stmt.total_credits - stmt.total_debits, 2
        ),
        "balance_matches": abs(
            (stmt.opening_balance + stmt.total_credits - stmt.total_debits)
            - stmt.closing_balance
        ) < 0.01,
    }
