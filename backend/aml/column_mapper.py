"""Interactive column mapping for bank statement PDFs.

Extracts raw tables from PDF, auto-detects column types,
lets user confirm/adjust mapping, and re-parses with the confirmed mapping.
Saves templates for reuse with future statements from the same bank.
"""

from __future__ import annotations

import json
import logging
import re
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..db.engine import ensure_initialized, fetch_all, fetch_one, get_conn, new_id
from ..finance.pipeline import extract_pdf_tables

log = logging.getLogger("aistate.aml.column_mapper")

# Known column types with detection patterns and labels
COLUMN_TYPES = {
    "date":         {"label": "Data księgowania", "icon": "📅", "patterns": [
        r"data\s*(operacji|księg|trans|zlec)", r"^data$", r"data\s*ob",
    ]},
    "value_date":   {"label": "Data waluty", "icon": "📅", "patterns": [
        r"data\s*walut", r"waluta\s*data", r"data\s*wart",
    ]},
    "description":  {"label": "Opis / Tytuł", "icon": "📝", "patterns": [
        r"opis\s*(operacji)?", r"tytu[łl]", r"tre[śs][ćc]", r"szczeg[óo][łl]",
    ]},
    "counterparty": {"label": "Kontrahent", "icon": "👤", "patterns": [
        r"nadawca|odbiorca", r"kontrahent", r"nazwa\s*(nadawcy|odbiorcy)",
        r"strona\s*transakcji",
    ]},
    "amount":       {"label": "Kwota", "icon": "💰", "patterns": [
        r"^kwota$", r"kwota\s*(operacji|transakcji|pln|eur)",
    ]},
    "debit":        {"label": "Obciążenia (wydatki)", "icon": "🔴", "patterns": [
        r"obci[ąa][żz]eni[ae]", r"wydatk", r"wyp[łl]at", r"debet",
        r"kwota\s*obci", r"ma$",
    ]},
    "credit":       {"label": "Uznania (wpływy)", "icon": "🟢", "patterns": [
        r"uznani[ae]", r"wp[łl]y(w|at)", r"przych", r"kredyt",
        r"kwota\s*uzna", r"^wn$",
    ]},
    "balance":      {"label": "Saldo", "icon": "📊", "patterns": [
        r"saldo", r"stan\s*rachunku", r"balance",
    ]},
    "bank_type":    {"label": "Typ operacji", "icon": "🏷️", "patterns": [
        r"typ\s*(operacji|transakcji)", r"rodzaj", r"kod\s*operacji",
    ]},
    "reference":    {"label": "Nr referencyjny", "icon": "#️⃣", "patterns": [
        r"referen", r"nr\s*(operacji|transakcji)", r"numer",
    ]},
    "skip":         {"label": "Pomiń", "icon": "⏭️", "patterns": []},
}


def get_column_types_meta() -> Dict[str, Any]:
    """Return column type definitions for UI."""
    return {k: {"label": v["label"], "icon": v["icon"]} for k, v in COLUMN_TYPES.items()}


def extract_raw_preview(
    pdf_path: Path,
    max_rows: int = 30,
) -> Dict[str, Any]:
    """Extract raw tables from PDF and auto-detect column mapping.

    Returns raw table data + suggested column mapping for user confirmation.
    """
    tables, full_text, page_count = extract_pdf_tables(pdf_path)

    if not tables:
        return {
            "status": "no_tables",
            "page_count": page_count,
            "tables": [],
            "bank_id": "",
            "bank_name": "",
        }

    # Detect bank
    from ..finance.parsers import get_parser
    parser = get_parser(full_text[:5000])

    # Find the main transaction table (largest by row count)
    main_table_idx = 0
    max_rows_count = 0
    for i, t in enumerate(tables):
        if len(t) > max_rows_count:
            max_rows_count = len(t)
            main_table_idx = i

    main_table = tables[main_table_idx]

    # Find header row
    header_row_idx = _detect_header_row(main_table)

    # Auto-detect column mapping
    header_cells = main_table[header_row_idx] if header_row_idx < len(main_table) else []
    auto_mapping = _auto_detect_columns(header_cells, main_table, header_row_idx)

    # Prepare preview rows (limit for UI)
    preview_rows = []
    for i, row in enumerate(main_table[:max_rows]):
        preview_rows.append({
            "index": i,
            "cells": [str(cell or "").strip() for cell in row],
            "is_header": i == header_row_idx,
        })

    # Check for saved template
    template = _find_matching_template(parser.BANK_ID, header_cells)

    # Build all tables summary
    all_tables = []
    for i, t in enumerate(tables):
        all_tables.append({
            "index": i,
            "rows": len(t),
            "cols": max(len(r) for r in t) if t else 0,
            "is_main": i == main_table_idx,
            "preview": [[str(c or "").strip() for c in r] for r in t[:5]],
        })

    return {
        "status": "ok",
        "page_count": page_count,
        "bank_id": parser.BANK_ID,
        "bank_name": parser.BANK_NAME,
        "tables_count": len(tables),
        "tables_summary": all_tables,
        "main_table_index": main_table_idx,
        "header_row": header_row_idx,
        "data_start_row": header_row_idx + 1,
        "column_count": len(header_cells),
        "header_cells": [str(c or "").strip() for c in header_cells],
        "auto_mapping": auto_mapping,
        "rows": preview_rows,
        "total_rows": len(main_table),
        "template": template,
    }


def _detect_header_row(table: List[List[str]]) -> int:
    """Find which row is the table header by content analysis."""
    date_pattern = re.compile(r"\d{2}[.\-/]\d{2}[.\-/]\d{2,4}")
    amount_pattern = re.compile(r"-?\d[\d\s]*[,\.]\d{2}")

    for i, row in enumerate(table[:10]):
        cells = [str(c or "").strip().lower() for c in row]
        text = " ".join(cells)

        # Header rows contain keywords like "data", "kwota", "saldo"
        has_keywords = any(kw in text for kw in [
            "data", "kwota", "saldo", "opis", "tytuł", "tytul",
            "obciążeni", "obciazeni", "uznani", "kontrahent",
            "nadawca", "odbiorca", "operacj",
        ])

        # Header rows typically don't contain dates or amounts
        has_date = bool(date_pattern.search(text))
        has_amount = bool(amount_pattern.search(text))

        if has_keywords and not has_date:
            return i

    return 0


def _auto_detect_columns(
    header_cells: List[str],
    table: List[List[str]],
    header_row: int,
) -> Dict[str, str]:
    """Auto-detect column types from header text and data patterns.

    Returns: {col_index_str: column_type}
    """
    mapping = {}

    # Phase 1: Match by header text
    for i, cell in enumerate(header_cells):
        cell_lower = str(cell or "").strip().lower()
        if not cell_lower:
            continue

        best_type = None
        best_score = 0

        for col_type, meta in COLUMN_TYPES.items():
            if col_type == "skip":
                continue
            for pattern in meta["patterns"]:
                if re.search(pattern, cell_lower):
                    score = len(pattern)
                    if score > best_score:
                        best_score = score
                        best_type = col_type

        if best_type:
            mapping[str(i)] = best_type

    # Phase 2: Analyze data content for unmapped columns
    data_rows = table[header_row + 1:header_row + 11]  # Sample up to 10 data rows
    if data_rows:
        for i in range(len(header_cells)):
            if str(i) in mapping:
                continue

            col_values = [str(row[i] or "").strip() for row in data_rows if i < len(row)]
            detected = _detect_column_from_data(col_values)
            if detected:
                mapping[str(i)] = detected

    return mapping


def _detect_column_from_data(values: List[str]) -> Optional[str]:
    """Detect column type from actual cell values."""
    if not values:
        return None

    non_empty = [v for v in values if v]
    if not non_empty:
        return "skip"

    date_re = re.compile(r"^\d{2}[.\-/]\d{2}[.\-/]\d{2,4}$")
    amount_re = re.compile(r"^-?\s*\d[\d\s]*[,\.]\d{2}$")

    date_matches = sum(1 for v in non_empty if date_re.match(v.strip()))
    amount_matches = sum(1 for v in non_empty if amount_re.match(v.strip().replace(" ", "")))

    ratio = len(non_empty) or 1

    if date_matches / ratio > 0.6:
        return "date"
    if amount_matches / ratio > 0.6:
        return "amount"

    # Long text → likely description
    avg_len = sum(len(v) for v in non_empty) / ratio
    if avg_len > 30:
        return "description"

    return None


def _find_matching_template(
    bank_id: str,
    header_cells: List[str],
) -> Optional[Dict[str, Any]]:
    """Find a saved template matching this bank and header structure."""
    ensure_initialized()

    templates = fetch_all(
        """SELECT * FROM parse_templates
           WHERE bank_id = ? AND is_active != 0
           ORDER BY is_default DESC, times_used DESC""",
        (bank_id,),
    )

    normalized_headers = [str(c or "").strip().lower() for c in header_cells]

    for t in templates:
        td = dict(t)
        try:
            sample = json.loads(td.get("sample_headers", "[]"))
        except (json.JSONDecodeError, TypeError):
            sample = []

        # Check if headers match (fuzzy)
        if sample:
            sample_norm = [str(s or "").strip().lower() for s in sample]
            if sample_norm == normalized_headers:
                td["column_mapping"] = json.loads(td.get("column_mapping", "{}"))
                return td

    # Return default template for bank even if headers differ
    for t in templates:
        td = dict(t)
        if td.get("is_default"):
            td["column_mapping"] = json.loads(td.get("column_mapping", "{}"))
            td["_partial_match"] = True
            return td

    return None


def parse_with_mapping(
    pdf_path: Path,
    column_mapping: Dict[str, str],
    header_row: int = 0,
    data_start_row: int = 1,
    main_table_index: int = 0,
) -> Dict[str, Any]:
    """Re-parse a PDF using user-provided column mapping.

    column_mapping: {col_index_str: column_type}
    Returns dict with transactions and info.
    """
    from ..finance.parsers.base import RawTransaction, StatementInfo

    tables, full_text, page_count = extract_pdf_tables(pdf_path)
    if not tables or main_table_index >= len(tables):
        return {"status": "error", "error": "no_tables"}

    table = tables[main_table_index]

    # Detect bank for metadata
    from ..finance.parsers import get_parser
    parser = get_parser(full_text[:5000])

    # Build reverse mapping: type → col_index
    type_to_col = {}
    for col_idx_str, col_type in column_mapping.items():
        if col_type != "skip":
            type_to_col[col_type] = int(col_idx_str)

    # Extract statement info from header area
    info = parser._extract_info(full_text) if hasattr(parser, "_extract_info") else StatementInfo(bank=parser.BANK_NAME)

    # Parse data rows
    transactions = []
    for row_idx in range(data_start_row, len(table)):
        row = table[row_idx]
        cells = [str(c or "").strip() for c in row]

        # Skip empty rows
        if not any(cells):
            continue

        tx = _row_to_transaction(cells, type_to_col)
        if tx:
            transactions.append(tx)

    return {
        "status": "ok",
        "bank_id": parser.BANK_ID,
        "bank_name": parser.BANK_NAME,
        "transactions": [_tx_to_dict(t) for t in transactions],
        "transaction_count": len(transactions),
        "info": {
            "bank": parser.BANK_NAME,
            "account_number": info.account_number if hasattr(info, "account_number") else "",
            "account_holder": info.account_holder if hasattr(info, "account_holder") else "",
            "period_from": info.period_from if hasattr(info, "period_from") else "",
            "period_to": info.period_to if hasattr(info, "period_to") else "",
            "opening_balance": info.opening_balance if hasattr(info, "opening_balance") else None,
            "closing_balance": info.closing_balance if hasattr(info, "closing_balance") else None,
        },
        "page_count": page_count,
    }


def _row_to_transaction(cells: List[str], type_to_col: Dict[str, int]):
    """Convert a row + column mapping into a RawTransaction-like dict."""
    from ..finance.parsers.base import RawTransaction

    def _get(col_type: str) -> str:
        idx = type_to_col.get(col_type)
        if idx is not None and idx < len(cells):
            return cells[idx]
        return ""

    date_str = _get("date")
    if not date_str:
        return None

    # Normalize date
    date_str = _normalize_date(date_str)
    if not date_str:
        return None

    # Parse amount
    amount = 0.0
    debit_str = _get("debit")
    credit_str = _get("credit")
    amount_str = _get("amount")

    if debit_str and _parse_amount(debit_str) is not None:
        amount = -abs(_parse_amount(debit_str))
    elif credit_str and _parse_amount(credit_str) is not None:
        amount = abs(_parse_amount(credit_str))
    elif amount_str and _parse_amount(amount_str) is not None:
        amount = _parse_amount(amount_str)
    else:
        return None  # No amount = not a valid transaction row

    balance = _parse_amount(_get("balance"))

    return RawTransaction(
        date=date_str,
        date_valuation=_normalize_date(_get("value_date")) or date_str,
        amount=amount,
        balance_after=balance,
        counterparty=_get("counterparty"),
        title=_get("description"),
        raw_text=" | ".join(cells),
        direction="in" if amount >= 0 else "out",
        bank_category=_get("bank_type"),
    )


def _normalize_date(s: str) -> Optional[str]:
    """Try to parse date string to YYYY-MM-DD."""
    s = s.strip()
    if not s:
        return None

    # DD.MM.YYYY or DD-MM-YYYY or DD/MM/YYYY
    m = re.match(r"(\d{2})[.\-/](\d{2})[.\-/](\d{4})", s)
    if m:
        return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"

    # DD.MM.YY
    m = re.match(r"(\d{2})[.\-/](\d{2})[.\-/](\d{2})", s)
    if m:
        year = int(m.group(3))
        year = year + 2000 if year < 100 else year
        return f"{year}-{m.group(2)}-{m.group(1)}"

    # YYYY-MM-DD (already ISO)
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return s

    return None


def _parse_amount(s: str) -> Optional[float]:
    """Parse Polish-format amount string to float."""
    if not s or not s.strip():
        return None
    s = s.strip().replace("\xa0", "").replace(" ", "")
    # Remove currency suffix
    s = re.sub(r"[A-Za-z]+$", "", s).strip()
    if not s:
        return None
    # Handle Polish decimal: "1.234,56" or "1 234,56"
    s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def _tx_to_dict(tx) -> Dict[str, Any]:
    """Convert RawTransaction to display dict."""
    return {
        "date": tx.date,
        "value_date": tx.date_valuation,
        "amount": tx.amount,
        "balance_after": tx.balance_after,
        "counterparty": tx.counterparty,
        "title": tx.title,
        "direction": tx.direction,
        "bank_category": tx.bank_category,
        "raw_text": tx.raw_text,
    }


# ============================================================
# TEMPLATE CRUD
# ============================================================

def save_template(
    bank_id: str,
    bank_name: str,
    column_mapping: Dict[str, str],
    header_cells: List[str],
    header_row: int = 0,
    data_start_row: int = 1,
    name: str = "",
    is_default: bool = False,
) -> str:
    """Save a column mapping template."""
    ensure_initialized()
    template_id = new_id()

    if not name:
        name = f"{bank_name} — szablon"

    with get_conn() as conn:
        # If setting as default, unset previous defaults
        if is_default:
            conn.execute(
                "UPDATE parse_templates SET is_default = 0 WHERE bank_id = ?",
                (bank_id,),
            )

        conn.execute(
            """INSERT INTO parse_templates
               (id, bank_id, bank_name, name, column_mapping, header_row,
                data_start_row, sample_headers, is_default)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (template_id, bank_id, bank_name, name,
             json.dumps(column_mapping, ensure_ascii=False),
             header_row, data_start_row,
             json.dumps(header_cells, ensure_ascii=False),
             int(is_default)),
        )

    log.info("Saved template %s for bank %s", template_id[:8], bank_id)
    return template_id


def list_templates(bank_id: str = "") -> List[Dict[str, Any]]:
    """List all templates, optionally for a specific bank."""
    ensure_initialized()
    if bank_id:
        rows = fetch_all(
            "SELECT * FROM parse_templates WHERE bank_id = ? ORDER BY is_default DESC, times_used DESC",
            (bank_id,),
        )
    else:
        rows = fetch_all(
            "SELECT * FROM parse_templates ORDER BY bank_id, is_default DESC, times_used DESC"
        )

    result = []
    for r in rows:
        d = dict(r)
        for jf in ("column_mapping", "sample_headers"):
            if d.get(jf):
                try:
                    d[jf] = json.loads(d[jf])
                except (json.JSONDecodeError, TypeError):
                    d[jf] = {} if jf == "column_mapping" else []
        result.append(d)
    return result


def increment_template_usage(template_id: str):
    """Increment times_used counter for a template."""
    ensure_initialized()
    with get_conn() as conn:
        conn.execute(
            "UPDATE parse_templates SET times_used = times_used + 1 WHERE id = ?",
            (template_id,),
        )


def delete_template(template_id: str):
    """Delete a template."""
    ensure_initialized()
    with get_conn() as conn:
        conn.execute("DELETE FROM parse_templates WHERE id = ?", (template_id,))
