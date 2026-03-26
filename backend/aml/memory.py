"""SQL-backed counterparty memory with entity resolution.

Global knowledge base of known counterparties shared across all
bank statements and cases. Supports whitelist/blacklist, aliases,
user notes, and fuzzy matching.
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from typing import Any, Dict, List, Optional, Tuple

from ..db.engine import fetch_all, fetch_one, get_conn, new_id

log = logging.getLogger("aistate.aml.memory")


def _normalize(name: str) -> str:
    """Normalize name for matching: lowercase, strip, collapse whitespace, remove account refs."""
    if not name:
        return ""
    s = name.lower().strip()
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"\d{10,}", "", s)  # remove long numbers
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _strip_diacritics(text: str) -> str:
    """Remove Polish diacritics."""
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def _fuzzy_score(a: str, b: str) -> float:
    """Simple fuzzy similarity score (0-1). Uses token overlap."""
    if not a or not b:
        return 0.0
    tokens_a = set(a.split())
    tokens_b = set(b.split())
    if not tokens_a or not tokens_b:
        return 0.0
    overlap = len(tokens_a & tokens_b)
    return overlap / max(len(tokens_a), len(tokens_b))


def _try_rapidfuzz(a: str, b: str) -> Optional[float]:
    """Use rapidfuzz if available, return normalized score 0-1."""
    try:
        from rapidfuzz import fuzz
        return fuzz.token_sort_ratio(a, b) / 100.0
    except ImportError:
        return None


# ============================================================
# CRUD Operations
# ============================================================

def create_counterparty(
    canonical_name: str,
    label: str = "neutral",
    note: str = "",
    tags: Optional[List[str]] = None,
    auto_category: str = "",
    source_bank: str = "",
) -> Dict[str, Any]:
    """Create a new counterparty entry."""
    cp_id = new_id()
    sources = [source_bank] if source_bank else []

    with get_conn() as conn:
        conn.execute(
            """INSERT INTO counterparties
               (id, canonical_name, label, note, tags, auto_category, sources, confidence)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (cp_id, canonical_name, label, note,
             json.dumps(tags or [], ensure_ascii=False),
             auto_category,
             json.dumps(sources, ensure_ascii=False),
             0.5),
        )
        # Add normalized alias
        norm = _normalize(canonical_name)
        if norm:
            conn.execute(
                """INSERT INTO counterparty_aliases
                   (id, counterparty_id, alias, alias_normalized, source)
                   VALUES (?, ?, ?, ?, ?)""",
                (new_id(), cp_id, canonical_name, norm, source_bank or "auto"),
            )

    return get_counterparty(cp_id)  # type: ignore


def get_counterparty(cp_id: str) -> Optional[Dict[str, Any]]:
    """Get counterparty by ID with aliases."""
    cp = fetch_one("SELECT * FROM counterparties WHERE id = ?", (cp_id,))
    if not cp:
        return None

    # Parse JSON fields
    for field in ("tags", "sources"):
        if cp.get(field):
            try:
                cp[field] = json.loads(cp[field])
            except (json.JSONDecodeError, TypeError):
                cp[field] = []

    # Load aliases
    aliases = fetch_all(
        "SELECT alias, source FROM counterparty_aliases WHERE counterparty_id = ?",
        (cp_id,),
    )
    cp["aliases"] = [a["alias"] for a in aliases]
    return cp


def update_counterparty(
    cp_id: str,
    label: Optional[str] = None,
    note: Optional[str] = None,
    tags: Optional[List[str]] = None,
) -> Optional[Dict[str, Any]]:
    """Update counterparty label, note, or tags."""
    updates = []
    params = []

    if label is not None:
        updates.append("label = ?")
        params.append(label)
    if note is not None:
        updates.append("note = ?")
        params.append(note)
    if tags is not None:
        updates.append("tags = ?")
        params.append(json.dumps(tags, ensure_ascii=False))

    if not updates:
        return get_counterparty(cp_id)

    params.append(cp_id)
    with get_conn() as conn:
        conn.execute(
            f"UPDATE counterparties SET {', '.join(updates)}, "
            f"updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE id = ?",
            params,
        )
    return get_counterparty(cp_id)


def add_alias(cp_id: str, alias: str, source: str = "manual") -> None:
    """Add an alias to a counterparty."""
    norm = _normalize(alias)
    if not norm:
        return

    # Check if alias already exists
    existing = fetch_one(
        "SELECT id FROM counterparty_aliases WHERE counterparty_id = ? AND alias_normalized = ?",
        (cp_id, norm),
    )
    if existing:
        return

    with get_conn() as conn:
        conn.execute(
            """INSERT INTO counterparty_aliases
               (id, counterparty_id, alias, alias_normalized, source)
               VALUES (?, ?, ?, ?, ?)""",
            (new_id(), cp_id, alias, norm, source),
        )


def search_counterparties(
    query: str = "",
    label: Optional[str] = None,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """Search counterparties by name/alias with optional label filter."""
    if query:
        norm_query = _normalize(query)
        sql = """
            SELECT DISTINCT c.* FROM counterparties c
            LEFT JOIN counterparty_aliases a ON c.id = a.counterparty_id
            WHERE (c.canonical_name LIKE ? OR a.alias_normalized LIKE ?)
        """
        params: list = [f"%{norm_query}%", f"%{norm_query}%"]
        if label:
            sql += " AND c.label = ?"
            params.append(label)
        sql += " ORDER BY c.times_seen DESC LIMIT ?"
        params.append(limit)
    else:
        sql = "SELECT * FROM counterparties"
        params = []
        if label:
            sql += " WHERE label = ?"
            params.append(label)
        sql += " ORDER BY times_seen DESC LIMIT ?"
        params.append(limit)

    rows = fetch_all(sql, tuple(params))
    for row in rows:
        for field in ("tags", "sources"):
            if row.get(field):
                try:
                    row[field] = json.loads(row[field])
                except (json.JSONDecodeError, TypeError):
                    row[field] = []
    return rows


def list_blacklisted() -> List[Dict[str, Any]]:
    """Get all blacklisted counterparties."""
    return search_counterparties(label="blacklist", limit=1000)


def list_whitelisted() -> List[Dict[str, Any]]:
    """Get all whitelisted counterparties."""
    return search_counterparties(label="whitelist", limit=1000)


# ============================================================
# Entity Resolution
# ============================================================

def resolve_entity(
    name: str,
    account_number: str = "",
    source_bank: str = "",
    amount: float = 0.0,
    date: str = "",
) -> Tuple[str, float]:
    """Resolve a counterparty name to an entity ID.

    Priority:
    1. Exact alias match (normalized)
    2. Account number match (if available)
    3. Fuzzy name match (token overlap or rapidfuzz)
    4. Create new entity

    Returns:
        (counterparty_id, confidence)
    """
    norm = _normalize(name)
    if not norm:
        return "", 0.0

    # 1. Exact alias match
    row = fetch_one(
        """SELECT c.id, c.canonical_name FROM counterparties c
           JOIN counterparty_aliases a ON c.id = a.counterparty_id
           WHERE a.alias_normalized = ?""",
        (norm,),
    )
    if row:
        _touch_counterparty(row["id"], amount, date, source_bank)
        return row["id"], 1.0

    # 2. Substring match (for partial names)
    rows = fetch_all(
        """SELECT c.id, c.canonical_name, a.alias_normalized
           FROM counterparties c
           JOIN counterparty_aliases a ON c.id = a.counterparty_id
           WHERE ? LIKE '%' || a.alias_normalized || '%'
              OR a.alias_normalized LIKE '%' || ? || '%'
           LIMIT 5""",
        (norm, norm),
    )
    if rows:
        # Pick best match
        best_id = ""
        best_score = 0.0
        for r in rows:
            score = _try_rapidfuzz(norm, r["alias_normalized"])
            if score is None:
                score = _fuzzy_score(norm, r["alias_normalized"])
            if score > best_score:
                best_score = score
                best_id = r["id"]
        if best_score >= 0.7:
            _touch_counterparty(best_id, amount, date, source_bank)
            # Add this variation as alias
            add_alias(best_id, name, source=source_bank or "auto")
            return best_id, best_score

    # 3. Fuzzy match against all (limited for performance)
    all_aliases = fetch_all(
        "SELECT counterparty_id, alias_normalized FROM counterparty_aliases LIMIT 5000"
    )
    norm_ascii = _strip_diacritics(norm)
    best_id = ""
    best_score = 0.0
    for alias_row in all_aliases:
        alias_norm = alias_row["alias_normalized"]
        score = _try_rapidfuzz(norm, alias_norm)
        if score is None:
            alias_ascii = _strip_diacritics(alias_norm)
            score = _fuzzy_score(norm_ascii, alias_ascii)
        if score > best_score:
            best_score = score
            best_id = alias_row["counterparty_id"]

    if best_score >= 0.8:
        _touch_counterparty(best_id, amount, date, source_bank)
        add_alias(best_id, name, source=source_bank or "auto")
        return best_id, best_score

    # 4. Create new entity
    cp = create_counterparty(
        canonical_name=name.strip(),
        source_bank=source_bank,
    )
    _touch_counterparty(cp["id"], amount, date, source_bank)
    return cp["id"], 0.5


def _touch_counterparty(
    cp_id: str,
    amount: float = 0,
    date: str = "",
    source_bank: str = "",
) -> None:
    """Update counterparty stats (times_seen, total_amount, dates, sources)."""
    with get_conn() as conn:
        conn.execute(
            """UPDATE counterparties SET
               times_seen = times_seen + 1,
               total_amount = total_amount + ?,
               last_seen = CASE WHEN ? > COALESCE(last_seen, '') THEN ? ELSE last_seen END,
               first_seen = CASE WHEN first_seen IS NULL OR ? < first_seen THEN ? ELSE first_seen END,
               updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
               WHERE id = ?""",
            (abs(amount), date, date, date, date, cp_id),
        )

        # Add source bank if not already present
        if source_bank:
            row = conn.execute(
                "SELECT sources FROM counterparties WHERE id = ?", (cp_id,)
            ).fetchone()
            if row:
                try:
                    sources = json.loads(row["sources"] or "[]")
                except (json.JSONDecodeError, TypeError):
                    sources = []
                if source_bank not in sources:
                    sources.append(source_bank)
                    conn.execute(
                        "UPDATE counterparties SET sources = ? WHERE id = ?",
                        (json.dumps(sources), cp_id),
                    )


# ============================================================
# Learning Queue
# ============================================================

def add_to_learning_queue(
    name: str,
    suggested_category: str = "",
    tx_ids: Optional[List[str]] = None,
    counterparty_id: str = "",
) -> str:
    """Add an uncategorized counterparty to the learning queue."""
    item_id = new_id()
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO learning_queue
               (id, counterparty_id, suggested_name, suggested_category, tx_sample_ids)
               VALUES (?, ?, ?, ?, ?)""",
            (item_id, counterparty_id or None, name,
             suggested_category,
             json.dumps(tx_ids or [], ensure_ascii=False)),
        )
    return item_id


def get_learning_queue(status: str = "pending", limit: int = 50) -> List[Dict[str, Any]]:
    """Get items from the learning queue."""
    rows = fetch_all(
        "SELECT * FROM learning_queue WHERE status = ? ORDER BY created_at DESC LIMIT ?",
        (status, limit),
    )
    for row in rows:
        if row.get("tx_sample_ids"):
            try:
                row["tx_sample_ids"] = json.loads(row["tx_sample_ids"])
            except (json.JSONDecodeError, TypeError):
                row["tx_sample_ids"] = []
    return rows


def resolve_learning_item(
    item_id: str,
    decision: str,
    label: str = "neutral",
    note: str = "",
) -> bool:
    """Resolve a learning queue item: approve/reject and update memory."""
    with get_conn() as conn:
        conn.execute(
            """UPDATE learning_queue SET
               status = ?, user_decision = ?, user_note = ?,
               resolved_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
               WHERE id = ?""",
            (decision, label, note, item_id),
        )

        if decision == "approved":
            row = conn.execute(
                "SELECT * FROM learning_queue WHERE id = ?", (item_id,)
            ).fetchone()
            if row and row["counterparty_id"]:
                conn.execute(
                    """UPDATE counterparties SET
                       label = ?, note = ?,
                       updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
                       WHERE id = ?""",
                    (label, note, row["counterparty_id"]),
                )
    return True


def get_counterparty_labels() -> Dict[str, str]:
    """Get all counterparty labels as {normalized_name: label} dict.

    Used by the rules engine for fast lookup.
    """
    rows = fetch_all(
        """SELECT a.alias_normalized, c.label
           FROM counterparties c
           JOIN counterparty_aliases a ON c.id = a.counterparty_id
           WHERE c.label != 'neutral'"""
    )
    return {r["alias_normalized"]: r["label"] for r in rows}


def get_counterparty_notes() -> Dict[str, str]:
    """Get all counterparty notes as {normalized_name: note} dict."""
    rows = fetch_all(
        """SELECT a.alias_normalized, c.note
           FROM counterparties c
           JOIN counterparty_aliases a ON c.id = a.counterparty_id
           WHERE c.note != ''"""
    )
    return {r["alias_normalized"]: r["note"] for r in rows}
