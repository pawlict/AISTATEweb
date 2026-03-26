"""Cross-account matching for multi-bank AML analysis.

Finds connections between multiple bank accounts within a case:
- Own transfers (account A -> account B of the same person)
- Shared counterparties (same merchant/person paid from multiple accounts)
- Consolidated cash-flow (total in/out across all accounts)
- Transfer chains (A -> B -> C patterns)

Works on case-level, aggregating data from all statements/accounts in a case.
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional, Set, Tuple

from ..db.engine import ensure_initialized, fetch_all, fetch_one, get_conn

log = logging.getLogger("aistate.aml.cross_account")


# ============================================================
# Data structures
# ============================================================

@dataclass
class InternalTransfer:
    """A matched transfer between two accounts within the case."""
    from_account: str          # account_number or account_id
    to_account: str
    from_statement_id: str
    to_statement_id: str
    from_tx_id: str            # transaction ID (debit side)
    to_tx_id: str              # transaction ID (credit side)
    amount: float
    date: str                  # YYYY-MM-DD
    date_delta_days: int       # days between debit and credit (0 = same day)
    confidence: float          # 0-1, how sure we are this is a match
    match_method: str          # "iban_match" | "amount_date" | "title_match"
    title: str                 # transaction title (for display)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SharedCounterparty:
    """A counterparty that appears across multiple accounts."""
    counterparty_name: str
    counterparty_id: str       # FK to counterparties table (if resolved)
    accounts: List[str]        # list of account_numbers where this cp appears
    total_amount: float
    tx_count: int
    categories: List[str]      # collected categories
    first_date: str
    last_date: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AccountSummary:
    """Consolidated summary for one account across all its statements."""
    account_number: str
    account_id: str            # FK to account_profiles
    bank_name: str
    bank_id: str
    holder: str
    statement_count: int
    period_from: str
    period_to: str
    total_credit: float
    total_debit: float
    tx_count: int
    opening_balance: Optional[float]
    closing_balance: Optional[float]
    # Per-statement currency breakdown (populated for multi-currency accounts)
    sub_statements: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class CrossAccountResult:
    """Full result of cross-account analysis."""
    case_id: str
    account_count: int
    accounts: List[AccountSummary]
    internal_transfers: List[InternalTransfer]
    shared_counterparties: List[SharedCounterparty]
    # Consolidated totals
    total_credit: float
    total_debit: float
    total_tx_count: int
    # Warnings
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "case_id": self.case_id,
            "account_count": self.account_count,
            "accounts": [a.to_dict() for a in self.accounts],
            "internal_transfers": [t.to_dict() for t in self.internal_transfers],
            "internal_transfers_count": len(self.internal_transfers),
            "internal_transfers_total": sum(t.amount for t in self.internal_transfers),
            "shared_counterparties": [c.to_dict() for c in self.shared_counterparties],
            "shared_counterparties_count": len(self.shared_counterparties),
            "total_credit": self.total_credit,
            "total_debit": self.total_debit,
            "total_tx_count": self.total_tx_count,
            "warnings": self.warnings,
        }


# ============================================================
# Main entry point
# ============================================================

def analyze_cross_account(case_id: str) -> CrossAccountResult:
    """Run cross-account analysis for all statements in a case.

    Args:
        case_id: The case ID to analyze.

    Returns:
        CrossAccountResult with all findings.
    """
    ensure_initialized()

    # 1. Gather all statements & their accounts
    statements = fetch_all(
        """SELECT s.id, s.account_id, s.account_number, s.account_holder,
                  s.bank_id, s.bank_name, s.period_from, s.period_to,
                  s.opening_balance, s.closing_balance, s.currency
           FROM statements s
           WHERE s.case_id = ?
           ORDER BY s.account_number, s.period_from""",
        (case_id,),
    )
    statements = [dict(s) for s in statements]

    if not statements:
        return CrossAccountResult(
            case_id=case_id, account_count=0, accounts=[],
            internal_transfers=[], shared_counterparties=[],
            total_credit=0, total_debit=0, total_tx_count=0,
            warnings=["Brak wyciagow w tej sprawie"],
        )

    # 2. Build per-account summaries
    account_map: Dict[str, List[dict]] = defaultdict(list)
    for s in statements:
        acc_key = _normalize_account(s["account_number"]) or s.get("account_id") or s["id"]
        account_map[acc_key].append(s)

    account_summaries = []
    all_statement_ids = [s["id"] for s in statements]

    for acc_key, stmts in account_map.items():
        stmt_ids = [s["id"] for s in stmts]
        summary = _build_account_summary(acc_key, stmts, stmt_ids)
        account_summaries.append(summary)

    # 3. Detect internal transfers (cross-account)
    internal_transfers = []
    if len(account_map) >= 2:
        internal_transfers = _find_internal_transfers(case_id, account_map)

    # 4. Find shared counterparties
    shared_cps = []
    if len(account_map) >= 2:
        shared_cps = _find_shared_counterparties(case_id, account_map)

    # 5. Consolidated totals
    total_credit = sum(a.total_credit for a in account_summaries)
    total_debit = sum(a.total_debit for a in account_summaries)
    total_tx = sum(a.tx_count for a in account_summaries)

    # Subtract internal transfers from net flow (they cancel out)
    internal_total = sum(t.amount for t in internal_transfers)

    warnings = []
    if len(account_map) == 1:
        warnings.append("Tylko jeden rachunek w sprawie - analiza cross-account niedostepna")
    if internal_transfers:
        warnings.append(
            f"Wykryto {len(internal_transfers)} przelewow wlasnych "
            f"na laczna kwote {internal_total:,.2f} PLN"
        )

    return CrossAccountResult(
        case_id=case_id,
        account_count=len(account_map),
        accounts=account_summaries,
        internal_transfers=internal_transfers,
        shared_counterparties=shared_cps,
        total_credit=round(total_credit, 2),
        total_debit=round(total_debit, 2),
        total_tx_count=total_tx,
        warnings=warnings,
    )


# ============================================================
# Account summary builder
# ============================================================

def _build_account_summary(
    acc_key: str,
    stmts: List[dict],
    stmt_ids: List[str],
) -> AccountSummary:
    """Build consolidated summary for one account across its statements."""

    # Get transaction totals from DB
    placeholders = ",".join("?" for _ in stmt_ids)
    row = fetch_one(
        f"""SELECT
                COUNT(*) as tx_count,
                COALESCE(SUM(CASE WHEN direction='CREDIT' THEN CAST(amount AS REAL) ELSE 0 END), 0) as total_credit,
                COALESCE(SUM(CASE WHEN direction='DEBIT' THEN ABS(CAST(amount AS REAL)) ELSE 0 END), 0) as total_debit
            FROM transactions
            WHERE statement_id IN ({placeholders})""",
        tuple(stmt_ids),
    )

    # Period span
    periods_from = [s["period_from"] for s in stmts if s.get("period_from")]
    periods_to = [s["period_to"] for s in stmts if s.get("period_to")]

    # Opening/closing balance: first statement's opening, last statement's closing
    sorted_stmts = sorted(stmts, key=lambda s: s.get("period_from") or "")
    opening = _safe_float(sorted_stmts[0].get("opening_balance"))
    closing = _safe_float(sorted_stmts[-1].get("closing_balance"))

    # Per-statement currency breakdown (useful for multi-currency accounts)
    sub_stmts: List[Dict[str, Any]] = []
    if len(stmts) > 1:
        for s in sorted_stmts:
            sid = s["id"]
            sub_row = fetch_one(
                """SELECT
                      COUNT(*) as tx_count,
                      COALESCE(SUM(CASE WHEN direction='CREDIT' THEN CAST(amount AS REAL) ELSE 0 END), 0) as total_credit,
                      COALESCE(SUM(CASE WHEN direction='DEBIT' THEN ABS(CAST(amount AS REAL)) ELSE 0 END), 0) as total_debit
                   FROM transactions WHERE statement_id = ?""",
                (sid,),
            )
            sub_stmts.append({
                "statement_id": sid,
                "currency": s.get("currency") or "",
                "period_from": s.get("period_from") or "",
                "period_to": s.get("period_to") or "",
                "total_credit": round(sub_row["total_credit"], 2) if sub_row else 0,
                "total_debit": round(sub_row["total_debit"], 2) if sub_row else 0,
                "tx_count": sub_row["tx_count"] if sub_row else 0,
            })

    first_stmt = stmts[0]
    return AccountSummary(
        account_number=first_stmt.get("account_number") or acc_key,
        account_id=first_stmt.get("account_id") or "",
        bank_name=first_stmt.get("bank_name") or "",
        bank_id=first_stmt.get("bank_id") or "",
        holder=first_stmt.get("account_holder") or "",
        statement_count=len(stmts),
        period_from=min(periods_from) if periods_from else "",
        period_to=max(periods_to) if periods_to else "",
        total_credit=round(row["total_credit"], 2) if row else 0,
        total_debit=round(row["total_debit"], 2) if row else 0,
        tx_count=row["tx_count"] if row else 0,
        opening_balance=opening,
        closing_balance=closing,
        sub_statements=sub_stmts,
    )


# ============================================================
# Internal transfer detection
# ============================================================

def _find_internal_transfers(
    case_id: str,
    account_map: Dict[str, List[dict]],
) -> List[InternalTransfer]:
    """Find transfers between accounts within the case.

    Strategy:
    1. IBAN match: transaction counterparty account number matches another
       account in the case.
    2. Amount+date match: same absolute amount on same/adjacent day, one DEBIT
       and one CREDIT, across different accounts.
    3. Title match: transaction title contains "przelew wlasny" or similar.
    """
    matches: List[InternalTransfer] = []
    seen_tx_pairs: Set[Tuple[str, str]] = set()

    # Get all account numbers in case
    case_accounts = set(account_map.keys())
    case_account_numbers_norm = {_normalize_account(a) for a in case_accounts if _normalize_account(a)}

    # Collect all statement IDs per account
    acc_stmt_ids: Dict[str, List[str]] = {}
    for acc_key, stmts in account_map.items():
        acc_stmt_ids[acc_key] = [s["id"] for s in stmts]

    # Strategy 1 & 3: IBAN match + title match
    # For each account, find outgoing transactions where counterparty IBAN is another case account
    for acc_key, stmt_ids in acc_stmt_ids.items():
        placeholders = ",".join("?" for _ in stmt_ids)
        txs = fetch_all(
            f"""SELECT id, statement_id, booking_date, amount, direction,
                       counterparty_raw, title, raw_text, tx_hash
                FROM transactions
                WHERE statement_id IN ({placeholders})
                  AND direction = 'DEBIT'
                ORDER BY booking_date""",
            tuple(stmt_ids),
        )

        for tx in txs:
            tx = dict(tx)
            # Extract counterparty account from transaction text
            cp_accounts = _extract_accounts_from_tx(tx)

            for cp_acc in cp_accounts:
                cp_norm = _normalize_account(cp_acc)
                if cp_norm and cp_norm in case_account_numbers_norm and cp_norm != _normalize_account(acc_key):
                    # Found: this debit goes to another account in the case
                    # Try to find matching credit
                    target_acc = cp_norm
                    target_stmt_ids = acc_stmt_ids.get(target_acc, [])
                    if not target_stmt_ids:
                        # Find by normalized match
                        for ak, sids in acc_stmt_ids.items():
                            if _normalize_account(ak) == cp_norm:
                                target_stmt_ids = sids
                                target_acc = ak
                                break

                    credit_tx = _find_matching_credit(
                        tx, target_stmt_ids,
                        max_date_delta=3,
                    )

                    pair_key = (tx["id"], credit_tx["id"]) if credit_tx else (tx["id"], "")
                    if credit_tx and pair_key not in seen_tx_pairs:
                        seen_tx_pairs.add(pair_key)
                        seen_tx_pairs.add((credit_tx["id"], tx["id"]))
                        matches.append(InternalTransfer(
                            from_account=acc_key,
                            to_account=target_acc,
                            from_statement_id=tx["statement_id"],
                            to_statement_id=credit_tx["statement_id"],
                            from_tx_id=tx["id"],
                            to_tx_id=credit_tx["id"],
                            amount=abs(float(tx["amount"])),
                            date=tx["booking_date"],
                            date_delta_days=_date_delta(tx["booking_date"], credit_tx["booking_date"]),
                            confidence=0.95,
                            match_method="iban_match",
                            title=tx.get("title") or "",
                        ))

    # Strategy 2: Amount+date match for unmatched transactions
    # (catches transfers where IBAN is not visible in text)
    all_accounts = list(acc_stmt_ids.keys())
    for i in range(len(all_accounts)):
        for j in range(i + 1, len(all_accounts)):
            acc_a = all_accounts[i]
            acc_b = all_accounts[j]
            _find_amount_date_matches(
                acc_a, acc_stmt_ids[acc_a],
                acc_b, acc_stmt_ids[acc_b],
                matches, seen_tx_pairs,
            )

    matches.sort(key=lambda m: m.date)
    return matches


def _find_matching_credit(
    debit_tx: dict,
    target_stmt_ids: List[str],
    max_date_delta: int = 3,
) -> Optional[dict]:
    """Find a matching CREDIT transaction in target statements."""
    if not target_stmt_ids:
        return None

    debit_amount = abs(float(debit_tx["amount"]))
    debit_date = debit_tx["booking_date"]

    placeholders = ",".join("?" for _ in target_stmt_ids)
    candidates = fetch_all(
        f"""SELECT id, statement_id, booking_date, amount, direction,
                   counterparty_raw, title
            FROM transactions
            WHERE statement_id IN ({placeholders})
              AND direction = 'CREDIT'
              AND ABS(CAST(amount AS REAL) - ?) < 0.02
            ORDER BY ABS(julianday(booking_date) - julianday(?))
            LIMIT 5""",
        tuple(target_stmt_ids) + (debit_amount, debit_date),
    )

    for c in candidates:
        c = dict(c)
        delta = _date_delta(debit_date, c["booking_date"])
        if delta <= max_date_delta:
            return c

    return None


def _find_amount_date_matches(
    acc_a: str, stmt_ids_a: List[str],
    acc_b: str, stmt_ids_b: List[str],
    matches: List[InternalTransfer],
    seen_tx_pairs: Set[Tuple[str, str]],
) -> None:
    """Find transfers by matching amount+date between two accounts."""
    if not stmt_ids_a or not stmt_ids_b:
        return

    ph_a = ",".join("?" for _ in stmt_ids_a)
    ph_b = ",".join("?" for _ in stmt_ids_b)

    # Get debits from A
    debits_a = fetch_all(
        f"""SELECT id, statement_id, booking_date, amount, title, counterparty_raw, raw_text
            FROM transactions
            WHERE statement_id IN ({ph_a}) AND direction = 'DEBIT'
            ORDER BY booking_date""",
        tuple(stmt_ids_a),
    )

    # Get credits to B
    credits_b = fetch_all(
        f"""SELECT id, statement_id, booking_date, amount, title, counterparty_raw
            FROM transactions
            WHERE statement_id IN ({ph_b}) AND direction = 'CREDIT'
            ORDER BY booking_date""",
        tuple(stmt_ids_b),
    )

    # Index credits by (rounded_amount, date) for quick lookup
    credit_index: Dict[Tuple[float, str], List[dict]] = defaultdict(list)
    for c in credits_b:
        c = dict(c)
        amt = round(abs(float(c["amount"])), 2)
        credit_index[(amt, c["booking_date"])].append(c)
        # Also index +/- 1 day
        for delta in (1, -1):
            try:
                d = datetime.strptime(c["booking_date"], "%Y-%m-%d") + timedelta(days=delta)
                credit_index[(amt, d.strftime("%Y-%m-%d"))].append(c)
            except (ValueError, TypeError):
                pass

    for deb in debits_a:
        deb = dict(deb)
        amt = round(abs(float(deb["amount"])), 2)
        date = deb["booking_date"]

        # Check if this looks like an own transfer (title hints)
        is_own_hint = bool(re.search(
            r"przelew\s+w[łl]asny|przelew\s+wewn|mi[ęe]dzy\s+rach|rachunek\s+w[łl]asny",
            f"{deb.get('title','')} {deb.get('raw_text','')}",
            re.IGNORECASE,
        ))

        candidates = credit_index.get((amt, date), [])
        for cred in candidates:
            pair_key = (deb["id"], cred["id"])
            if pair_key in seen_tx_pairs:
                continue

            # Confirm: amount matches, date within 1 day
            delta = _date_delta(date, cred["booking_date"])
            if delta > 1:
                continue

            confidence = 0.6  # base confidence for amount+date match
            if is_own_hint:
                confidence = 0.85
            if delta == 0:
                confidence += 0.1

            if confidence >= 0.6:
                seen_tx_pairs.add(pair_key)
                seen_tx_pairs.add((cred["id"], deb["id"]))
                matches.append(InternalTransfer(
                    from_account=acc_a,
                    to_account=acc_b,
                    from_statement_id=deb["statement_id"],
                    to_statement_id=cred["statement_id"],
                    from_tx_id=deb["id"],
                    to_tx_id=cred["id"],
                    amount=amt,
                    date=date,
                    date_delta_days=delta,
                    confidence=round(confidence, 2),
                    match_method="amount_date" if not is_own_hint else "title_match",
                    title=deb.get("title") or "",
                ))
                break  # one match per debit


# ============================================================
# Shared counterparty detection
# ============================================================

def _find_shared_counterparties(
    case_id: str,
    account_map: Dict[str, List[dict]],
) -> List[SharedCounterparty]:
    """Find counterparties that appear across multiple accounts."""

    # Collect all statement IDs
    all_stmt_ids = []
    stmt_to_account: Dict[str, str] = {}
    for acc_key, stmts in account_map.items():
        for s in stmts:
            all_stmt_ids.append(s["id"])
            stmt_to_account[s["id"]] = acc_key

    if not all_stmt_ids:
        return []

    placeholders = ",".join("?" for _ in all_stmt_ids)

    # Group by counterparty_id (resolved entities)
    rows = fetch_all(
        f"""SELECT counterparty_id, counterparty_raw,
                   statement_id, category,
                   COUNT(*) as tx_count,
                   SUM(ABS(CAST(amount AS REAL))) as total_amount,
                   MIN(booking_date) as first_date,
                   MAX(booking_date) as last_date
            FROM transactions
            WHERE statement_id IN ({placeholders})
              AND counterparty_id IS NOT NULL
              AND counterparty_id != ''
            GROUP BY counterparty_id, statement_id""",
        tuple(all_stmt_ids),
    )

    # Group by counterparty across accounts
    cp_data: Dict[str, Dict] = defaultdict(lambda: {
        "counterparty_id": "",
        "name": "",
        "accounts": set(),
        "total_amount": 0.0,
        "tx_count": 0,
        "categories": set(),
        "first_date": "",
        "last_date": "",
    })

    for r in rows:
        r = dict(r)
        cp_id = r["counterparty_id"]
        acc = stmt_to_account.get(r["statement_id"], "")

        entry = cp_data[cp_id]
        entry["counterparty_id"] = cp_id
        if not entry["name"]:
            entry["name"] = r.get("counterparty_raw") or cp_id
        entry["accounts"].add(acc)
        entry["total_amount"] += float(r.get("total_amount") or 0)
        entry["tx_count"] += r.get("tx_count") or 0
        if r.get("category"):
            entry["categories"].add(r["category"])
        if r.get("first_date"):
            if not entry["first_date"] or r["first_date"] < entry["first_date"]:
                entry["first_date"] = r["first_date"]
        if r.get("last_date"):
            if not entry["last_date"] or r["last_date"] > entry["last_date"]:
                entry["last_date"] = r["last_date"]

    # Filter: only counterparties appearing in 2+ accounts
    shared = []
    for cp_id, data in cp_data.items():
        if len(data["accounts"]) >= 2:
            shared.append(SharedCounterparty(
                counterparty_name=data["name"],
                counterparty_id=data["counterparty_id"],
                accounts=sorted(data["accounts"]),
                total_amount=round(data["total_amount"], 2),
                tx_count=data["tx_count"],
                categories=sorted(data["categories"]),
                first_date=data["first_date"],
                last_date=data["last_date"],
            ))

    # Sort by total amount desc
    shared.sort(key=lambda c: -c.total_amount)
    return shared


# ============================================================
# Helpers
# ============================================================

def _normalize_account(account: str) -> str:
    """Normalize account number for matching."""
    if not account:
        return ""
    clean = re.sub(r"[\s\-]", "", account).upper()
    if clean.startswith("PL"):
        clean = clean[2:]
    if len(clean) < 15:
        return ""
    return clean


def _extract_accounts_from_tx(tx: dict) -> List[str]:
    """Extract IBAN-like account numbers from transaction text."""
    search = f"{tx.get('counterparty_raw', '')} {tx.get('title', '')} {tx.get('raw_text', '')}"
    # Polish IBAN: 26 digits (optionally with PL prefix)
    matches = re.findall(r"(?:PL)?\s*(\d{2}[\s]?\d{4}[\s]?\d{4}[\s]?\d{4}[\s]?\d{4}[\s]?\d{4}[\s]?\d{4})", search)
    result = []
    for m in matches:
        clean = re.sub(r"\s", "", m)
        if len(clean) == 26:
            result.append(clean)
    return result


def _date_delta(date1: str, date2: str) -> int:
    """Calculate absolute difference in days between two date strings."""
    try:
        d1 = datetime.strptime(date1, "%Y-%m-%d")
        d2 = datetime.strptime(date2, "%Y-%m-%d")
        return abs((d1 - d2).days)
    except (ValueError, TypeError):
        return 999


def _safe_float(val) -> Optional[float]:
    """Convert to float safely."""
    if val is None:
        return None
    try:
        return float(str(val).replace(",", ".").replace(" ", ""))
    except (ValueError, TypeError):
        return None
