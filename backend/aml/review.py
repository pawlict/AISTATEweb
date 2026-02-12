"""Transaction review and classification for self-learning.

Users classify transactions as: neutral | legitimate | suspicious | monitoring
Classifications feed back into counterparty memory for future analyses.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from ..db.engine import ensure_initialized, fetch_all, fetch_one, get_conn, new_id

log = logging.getLogger("aistate.aml.review")


# Classification labels with metadata
CLASSIFICATIONS = {
    "neutral": {"label": "Neutralny", "color": "#60a5fa", "icon": "○", "description": "Brak opinii"},
    "legitimate": {"label": "Poprawny", "color": "#15803d", "icon": "✓", "description": "Potwierdzona transakcja"},
    "suspicious": {"label": "Podejrzany", "color": "#dc2626", "icon": "⚠", "description": "Podejrzana transakcja"},
    "monitoring": {"label": "Obserwacja", "color": "#ea580c", "icon": "👁", "description": "Wymaga monitoringu"},
}


def get_classifications_meta() -> Dict[str, Any]:
    """Return classification labels and their metadata."""
    return CLASSIFICATIONS


def classify_transaction(
    tx_id: str,
    statement_id: str,
    classification: str,
    note: str = "",
    user_id: str = "",
) -> Dict[str, Any]:
    """Classify a single transaction.

    Returns the saved classification record.
    """
    ensure_initialized()
    if classification not in CLASSIFICATIONS:
        raise ValueError(f"Invalid classification: {classification}. Must be one of: {list(CLASSIFICATIONS.keys())}")

    record_id = new_id()
    with get_conn() as conn:
        # Upsert: one classification per tx
        conn.execute(
            """INSERT INTO tx_classifications (id, tx_id, statement_id, classification, note, created_by)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(tx_id) DO UPDATE SET
                 classification = excluded.classification,
                 note = excluded.note,
                 updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')""",
            (record_id, tx_id, statement_id, classification, note, user_id),
        )

    # Feed back into counterparty memory
    _propagate_to_memory(tx_id, classification, note)

    return {
        "tx_id": tx_id,
        "classification": classification,
        "note": note,
    }


def classify_batch(
    items: List[Dict[str, str]],
    statement_id: str,
    user_id: str = "",
) -> Dict[str, Any]:
    """Classify multiple transactions at once.

    items: list of {tx_id, classification, note?}
    Returns summary.
    """
    ensure_initialized()
    classified = 0
    errors = []

    with get_conn() as conn:
        for item in items:
            tx_id = item.get("tx_id", "")
            cls = item.get("classification", "neutral")
            note = item.get("note", "")

            if cls not in CLASSIFICATIONS:
                errors.append(f"Invalid classification '{cls}' for tx {tx_id}")
                continue

            record_id = new_id()
            conn.execute(
                """INSERT INTO tx_classifications (id, tx_id, statement_id, classification, note, created_by)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(tx_id) DO UPDATE SET
                     classification = excluded.classification,
                     note = excluded.note,
                     updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')""",
                (record_id, tx_id, statement_id, cls, note, user_id),
            )
            classified += 1

    # Propagate to memory in bulk
    for item in items:
        tx_id = item.get("tx_id", "")
        cls = item.get("classification", "neutral")
        note = item.get("note", "")
        if cls in CLASSIFICATIONS:
            _propagate_to_memory(tx_id, cls, note)

    return {
        "classified": classified,
        "errors": errors,
        "total": len(items),
    }


def get_classifications(statement_id: str) -> Dict[str, Dict[str, str]]:
    """Get all classifications for a statement.

    Returns: {tx_id: {classification, note, updated_at}}
    """
    ensure_initialized()
    rows = fetch_all(
        """SELECT tx_id, classification, note, updated_at
           FROM tx_classifications WHERE statement_id = ?""",
        (statement_id,),
    )
    return {
        row["tx_id"]: {
            "classification": row["classification"],
            "note": row["note"] or "",
            "updated_at": row["updated_at"] or "",
        }
        for row in rows
    }


def get_classification_stats(statement_id: str) -> Dict[str, int]:
    """Get classification counts for a statement."""
    ensure_initialized()
    rows = fetch_all(
        """SELECT classification, COUNT(*) as cnt
           FROM tx_classifications WHERE statement_id = ?
           GROUP BY classification""",
        (statement_id,),
    )
    stats = {k: 0 for k in CLASSIFICATIONS}
    for row in rows:
        stats[row["classification"]] = row["cnt"]
    return stats


def get_global_classification_stats() -> Dict[str, Any]:
    """Get global classification stats across all statements."""
    ensure_initialized()
    rows = fetch_all(
        """SELECT classification, COUNT(*) as cnt
           FROM tx_classifications GROUP BY classification"""
    )
    stats = {k: 0 for k in CLASSIFICATIONS}
    for row in rows:
        stats[row["classification"]] = row["cnt"]

    total = sum(stats.values())
    return {"stats": stats, "total": total}


def _propagate_to_memory(tx_id: str, classification: str, note: str = ""):
    """Feed classification back into counterparty memory.

    Maps user classifications to counterparty labels:
    - suspicious → blacklist
    - legitimate → whitelist
    - monitoring → neutral (with note)
    - neutral → no change
    """
    if classification == "neutral":
        return

    # Get the transaction's counterparty
    tx = fetch_one(
        "SELECT counterparty_id, counterparty_raw FROM transactions WHERE id = ?",
        (tx_id,),
    )
    if not tx or not tx["counterparty_id"]:
        return

    cp_id = tx["counterparty_id"]

    # Map classification to counterparty label
    label_map = {
        "suspicious": "blacklist",
        "legitimate": "whitelist",
        "monitoring": "neutral",
    }
    new_label = label_map.get(classification)
    if not new_label:
        return

    with get_conn() as conn:
        if new_label != "neutral":
            conn.execute(
                """UPDATE counterparties SET label = ?, updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
                   WHERE id = ?""",
                (new_label, cp_id),
            )

        if note:
            conn.execute(
                """UPDATE counterparties SET note = ?,
                   updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
                   WHERE id = ?""",
                (note, cp_id),
            )

    log.info("Propagated classification %s → %s for counterparty %s", classification, new_label, cp_id)


def get_review_transactions(
    statement_id: str,
    include_raw: bool = True,
) -> List[Dict[str, Any]]:
    """Get full transaction data for review, with existing classifications.

    Returns transactions in bank-statement columnar format with all fields
    needed for the review UI.
    """
    ensure_initialized()

    rows = fetch_all(
        """SELECT t.id, t.booking_date, t.tx_date, t.amount, t.currency,
                  t.direction, t.balance_after,
                  t.channel, t.category, t.subcategory,
                  t.risk_tags, t.risk_score,
                  t.title, t.counterparty_raw, t.counterparty_id,
                  t.bank_category, t.raw_text,
                  t.rule_explains, t.is_recurring, t.recurring_group,
                  t.is_anomaly, t.anomaly_score,
                  tc.classification, tc.note AS class_note, tc.updated_at AS class_date
           FROM transactions t
           LEFT JOIN tx_classifications tc ON tc.tx_id = t.id
           WHERE t.statement_id = ?
           ORDER BY t.booking_date, t.id""",
        (statement_id,),
    )

    result = []
    for row in rows:
        tx = dict(row)
        # Parse JSON fields
        for jf in ("risk_tags", "rule_explains"):
            if tx.get(jf):
                try:
                    tx[jf] = json.loads(tx[jf])
                except (json.JSONDecodeError, TypeError):
                    tx[jf] = []
            else:
                tx[jf] = []

        # Default classification
        if not tx.get("classification"):
            tx["classification"] = "neutral"
        if not tx.get("class_note"):
            tx["class_note"] = ""

        if not include_raw:
            tx.pop("raw_text", None)

        result.append(tx)

    return result


def get_statement_header(statement_id: str) -> Dict[str, Any]:
    """Get statement header info in block format for review.

    Returns structured header fields that can be displayed as editable blocks.
    """
    ensure_initialized()

    stmt = fetch_one("SELECT * FROM statements WHERE id = ?", (statement_id,))
    if not stmt:
        return {}

    stmt_dict = dict(stmt)

    # Parse warnings
    if stmt_dict.get("warnings"):
        try:
            stmt_dict["warnings"] = json.loads(stmt_dict["warnings"])
        except (json.JSONDecodeError, TypeError):
            stmt_dict["warnings"] = []

    # Structure as blocks for UI
    blocks = [
        {"field": "bank_name", "label": "Bank", "value": stmt_dict.get("bank_name", ""), "type": "text", "editable": False},
        {"field": "bank_id", "label": "ID banku", "value": stmt_dict.get("bank_id", ""), "type": "text", "editable": False},
        {"field": "account_number", "label": "Numer konta", "value": stmt_dict.get("account_number", ""), "type": "iban", "editable": True},
        {"field": "account_holder", "label": "Właściciel", "value": stmt_dict.get("account_holder", ""), "type": "text", "editable": True},
        {"field": "period_from", "label": "Okres od", "value": stmt_dict.get("period_from", ""), "type": "date", "editable": True},
        {"field": "period_to", "label": "Okres do", "value": stmt_dict.get("period_to", ""), "type": "date", "editable": True},
        {"field": "opening_balance", "label": "Saldo początkowe", "value": stmt_dict.get("opening_balance", ""), "type": "amount", "editable": True},
        {"field": "closing_balance", "label": "Saldo końcowe", "value": stmt_dict.get("closing_balance", ""), "type": "amount", "editable": True},
        {"field": "available_balance", "label": "Saldo dostępne", "value": stmt_dict.get("available_balance", ""), "type": "amount", "editable": True},
        {"field": "currency", "label": "Waluta", "value": stmt_dict.get("currency", "PLN"), "type": "text", "editable": True},
        {"field": "declared_credits_sum", "label": "Suma uznań", "value": stmt_dict.get("declared_credits_sum", ""), "type": "amount", "editable": True},
        {"field": "declared_credits_count", "label": "Liczba uznań", "value": stmt_dict.get("declared_credits_count", ""), "type": "number", "editable": True},
        {"field": "declared_debits_sum", "label": "Suma obciążeń", "value": stmt_dict.get("declared_debits_sum", ""), "type": "amount", "editable": True},
        {"field": "declared_debits_count", "label": "Liczba obciążeń", "value": stmt_dict.get("declared_debits_count", ""), "type": "number", "editable": True},
        {"field": "previous_closing_balance", "label": "Saldo końc. poprz. wyciągu", "value": stmt_dict.get("previous_closing_balance", ""), "type": "amount", "editable": True},
        {"field": "debt_limit", "label": "Limit zadłużenia", "value": stmt_dict.get("debt_limit", ""), "type": "amount", "editable": True},
        {"field": "overdue_commission", "label": "Prowizja zaległa", "value": stmt_dict.get("overdue_commission", ""), "type": "amount", "editable": True},
        {"field": "blocked_amount", "label": "Kwota zablokowana", "value": stmt_dict.get("blocked_amount", ""), "type": "amount", "editable": True},
        {"field": "parse_method", "label": "Metoda parsowania", "value": stmt_dict.get("parse_method", ""), "type": "text", "editable": False},
        {"field": "ocr_used", "label": "OCR", "value": "Tak" if stmt_dict.get("ocr_used") else "Nie", "type": "text", "editable": False},
        {"field": "parser_version", "label": "Wersja parsera", "value": stmt_dict.get("parser_version", ""), "type": "text", "editable": False},
    ]

    return {
        "statement_id": statement_id,
        "case_id": stmt_dict.get("case_id", ""),
        "blocks": blocks,
        "warnings": stmt_dict.get("warnings", []),
    }


def update_statement_field(statement_id: str, field: str, value: str) -> bool:
    """Update a single statement header field (user correction).

    Only allows updating known editable fields.
    """
    editable_fields = {
        "account_number", "account_holder",
        "period_from", "period_to",
        "opening_balance", "closing_balance", "available_balance",
        "currency",
        "declared_credits_sum", "declared_credits_count",
        "declared_debits_sum", "declared_debits_count",
        "previous_closing_balance", "debt_limit",
        "overdue_commission", "blocked_amount",
    }

    if field not in editable_fields:
        log.warning("Attempted to update non-editable field: %s", field)
        return False

    ensure_initialized()
    with get_conn() as conn:
        conn.execute(
            f"UPDATE statements SET {field} = ? WHERE id = ?",
            (value, statement_id),
        )
    log.info("Updated statement %s field %s = %s", statement_id[:8], field, value[:50] if value else "")
    return True


def save_field_rule(
    bank_id: str,
    rule_type: str,
    source_field: str,
    target_field: str,
    condition: Optional[Dict] = None,
    note: str = "",
) -> str:
    """Save a field mapping rule for a bank format.

    Returns the rule ID.
    """
    ensure_initialized()
    rule_id = new_id()
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO field_rules (id, bank_id, rule_type, source_field, target_field, condition_json, note)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (rule_id, bank_id, rule_type, source_field, target_field,
             json.dumps(condition or {}, ensure_ascii=False), note),
        )
    return rule_id


def get_field_rules(bank_id: str = "") -> List[Dict[str, Any]]:
    """Get all field mapping rules, optionally filtered by bank."""
    ensure_initialized()
    if bank_id:
        rows = fetch_all(
            """SELECT * FROM field_rules WHERE bank_id = ? AND is_active = 1
               ORDER BY priority DESC, created_at""",
            (bank_id,),
        )
    else:
        rows = fetch_all(
            "SELECT * FROM field_rules WHERE is_active = 1 ORDER BY bank_id, priority DESC"
        )
    result = []
    for row in rows:
        d = dict(row)
        if d.get("condition_json"):
            try:
                d["condition"] = json.loads(d["condition_json"])
            except (json.JSONDecodeError, TypeError):
                d["condition"] = {}
        else:
            d["condition"] = {}
        result.append(d)
    return result


def delete_field_rule(rule_id: str) -> bool:
    """Deactivate a field rule."""
    ensure_initialized()
    with get_conn() as conn:
        conn.execute(
            "UPDATE field_rules SET is_active = 0 WHERE id = ?",
            (rule_id,),
        )
    return True
