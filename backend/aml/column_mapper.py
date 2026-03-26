"""Interactive column mapping for bank statement PDFs.

Uses spatial (coordinate-based) parsing to extract words with positions,
auto-detect column boundaries from headers, and segment multi-line
transactions by date markers.  The user confirms/adjusts column types
on a visual PDF overlay, then the confirmed mapping drives the full parse.
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
from .spatial_parser import (
    ColumnZone,
    SpatialParseResult,
    spatial_parse_pdf,
    result_to_api_response,
)

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
    image_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """Parse PDF spatially and return preview data for visual overlay.

    Uses coordinate-based word extraction to detect columns and
    segment multi-line transactions.  Returns page images + detected
    column boundaries for the frontend SVG mask.
    """
    result = spatial_parse_pdf(
        pdf_path,
        max_preview_pages=5,
        render_images=True,
        image_dir=image_dir,
    )

    # Store the result for later use by parse_with_mapping
    _last_spatial_result[str(pdf_path)] = result

    api = result_to_api_response(result)

    # Build auto_mapping in {col_index_str: col_type} format for JS
    auto_mapping = {}
    for i, col in enumerate(result.columns):
        if col.col_type and col.col_type != "skip":
            auto_mapping[str(i)] = col.col_type

    api["auto_mapping"] = auto_mapping
    api["header_cells"] = [col.label for col in result.columns]

    # Check for saved template
    template = _find_matching_template(
        result.bank_id,
        [col.label for col in result.columns],
    )
    api["template"] = template

    # Return all templates for this bank (for selector UI)
    all_bank_templates = _list_bank_templates(result.bank_id)
    api["bank_templates"] = all_bank_templates

    api["column_types"] = get_column_types_meta()

    return api


# Cache for spatial parse results (avoid re-parsing on confirm)
_last_spatial_result: Dict[str, SpatialParseResult] = {}



# Column type auto-detection is now handled by spatial_parser._classify_column()


def _deserialize_template(td: Dict[str, Any]) -> Dict[str, Any]:
    """Deserialize JSON fields in a template dict."""
    for jf in ("column_mapping", "sample_headers", "column_bounds"):
        val = td.get(jf)
        if isinstance(val, str):
            try:
                td[jf] = json.loads(val)
            except (json.JSONDecodeError, TypeError):
                td[jf] = {} if jf == "column_mapping" else []
        elif val is None:
            td[jf] = {} if jf == "column_mapping" else []
    # header_fields is a dict (not a list)
    hf = td.get("header_fields")
    if isinstance(hf, str):
        try:
            td["header_fields"] = json.loads(hf)
        except (json.JSONDecodeError, TypeError):
            td["header_fields"] = {}
    elif hf is None:
        td["header_fields"] = {}
    return td


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
        td = _deserialize_template(dict(t))
        sample = td.get("sample_headers", [])

        # Check if headers match (fuzzy)
        if sample:
            sample_norm = [str(s or "").strip().lower() for s in sample]
            if sample_norm == normalized_headers:
                return td

    # Return default template for bank even if headers differ
    for t in templates:
        td = _deserialize_template(dict(t))
        if td.get("is_default"):
            td["_partial_match"] = True
            return td

    # Fallback: return most-used template (already sorted by times_used DESC)
    if templates:
        td = _deserialize_template(dict(templates[0]))
        td["_partial_match"] = True
        return td

    return None


def _list_bank_templates(bank_id: str) -> List[Dict[str, Any]]:
    """Return all active templates for a given bank (for selector UI)."""
    if not bank_id:
        return []
    ensure_initialized()
    # Ensure column_bounds column exists
    with get_conn() as conn:
        _ensure_template_columns(conn)

    rows = fetch_all(
        """SELECT id, bank_id, bank_name, name, is_default, times_used,
                  sample_headers, column_mapping, column_bounds, header_fields,
                  created_at
           FROM parse_templates
           WHERE bank_id = ? AND is_active != 0
           ORDER BY is_default DESC, times_used DESC""",
        (bank_id,),
    )
    result = []
    for r in rows:
        d = _deserialize_template(dict(r))
        result.append(d)
    return result


def parse_with_mapping(
    pdf_path: Path,
    column_mapping: Dict[str, str],
    column_bounds: Optional[List[Dict[str, Any]]] = None,
    full_parse: bool = False,
    **_kwargs,
) -> Dict[str, Any]:
    """Re-parse a PDF using user-confirmed column mapping.

    column_mapping: {col_index_str: column_type}
    column_bounds: optional [{x_min, x_max}] from dragged UI boundaries
    full_parse: if True, re-parse ALL pages (not just cached 5-page preview)

    When full_parse=True (used by pipeline), ignores the 5-page cache and
    parses the entire PDF to ensure all transactions are captured.
    """
    from .spatial_parser import (
        spatial_parse_pdf,
        _extract_transactions,
        _segment_transactions,
    )

    # For full pipeline: always re-parse ALL pages (ignore 5-page preview cache)
    # For preview: use cached result if available
    cached = None
    if not full_parse:
        cached = _last_spatial_result.get(str(pdf_path))
    if cached is None:
        max_pages = 9999 if full_parse else 5
        log.info("Parsing PDF with max_pages=%s (full_parse=%s)", max_pages, full_parse)
        cached = spatial_parse_pdf(pdf_path, max_preview_pages=max_pages, render_images=False)

    # Rebuild columns from user-provided bounds (authoritative source)
    # column_bounds carries full info: x_min, x_max, label, col_type, header_y
    columns = list(cached.columns)
    default_header_y = columns[0].header_y if columns else 50.0

    if column_bounds and len(column_bounds) > 0:
        # Prefer header_y from user bounds (frontend knows the correct value
        # from the initial preview; auto-detection on full_parse may differ)
        bounds_header_y = None
        for b in column_bounds:
            if b and b.get("header_y") is not None:
                try:
                    bounds_header_y = float(b["header_y"])
                except (ValueError, TypeError):
                    pass
                break
        if bounds_header_y is not None and bounds_header_y > 0:
            default_header_y = bounds_header_y

        # User may have added/removed columns — rebuild entirely from bounds
        columns = []
        for i, bounds in enumerate(column_bounds):
            if not bounds:
                continue
            col_type = bounds.get("col_type", "skip")
            label = bounds.get("label", f"Kolumna {i + 1}")
            hy = default_header_y
            if bounds.get("header_y") is not None:
                try:
                    hy = float(bounds["header_y"])
                except (ValueError, TypeError):
                    pass
            columns.append(ColumnZone(
                label=label,
                col_type=col_type,
                x_min=float(bounds.get("x_min", 0)),
                x_max=float(bounds.get("x_max", 0)),
                header_y=hy,
            ))

    # Apply column_mapping type overrides on top
    if column_mapping:
        for idx_str, col_type in column_mapping.items():
            idx = int(idx_str)
            if idx < len(columns):
                columns[idx] = ColumnZone(
                    label=columns[idx].label,
                    col_type=col_type,
                    x_min=columns[idx].x_min,
                    x_max=columns[idx].x_max,
                    header_y=columns[idx].header_y,
                )

    # Collect all words
    all_words = []
    for pg in cached.pages:
        all_words.extend(pg.words)

    # Find header end Y
    header_y_end = max(c.header_y for c in columns) + 20 if columns else 0

    log.info("parse_with_mapping: %d columns, header_y_end=%.1f, words=%d, pages=%d (full_parse=%s)",
             len(columns), header_y_end, len(all_words), len(cached.pages), full_parse)
    if columns:
        for i, c in enumerate(columns):
            log.debug("  col[%d]: type=%s x=%.1f..%.1f header_y=%.1f label=%s",
                       i, c.col_type, c.x_min, c.x_max, c.header_y, c.label[:30])

    # Re-segment and re-extract with updated columns
    bands, page_header_y, page_footer_y = _segment_transactions(all_words, columns, header_y_end)
    transactions = _extract_transactions(all_words, columns, bands, page_header_y, page_footer_y)

    if not transactions and all_words:
        log.warning("parse_with_mapping: 0 transactions from %d words! "
                     "header_y_end=%.1f, %d columns, %d bands",
                     len(all_words), header_y_end, len(columns), len(bands))
        # Diagnostic: find date column and show sample words in its area
        date_col = None
        for c in columns:
            if c.col_type == "date":
                date_col = c
                break
        if not date_col and columns:
            date_col = columns[0]
        if date_col:
            import re
            _dt_re = re.compile(r"\d{2}[./\-]\d{2}[./\-]\d{4}")
            data_words = [w for w in all_words if w.top >= header_y_end]
            date_words = [w for w in data_words
                          if date_col.x_min - 10 <= (w.x0 + w.x1) / 2 <= date_col.x_max + 10]
            date_matches = [w for w in date_words if _dt_re.match(w.text.strip())]
            log.warning("  Date col: x=%.1f..%.1f  data_words=%d  in_date_col=%d  date_matches=%d",
                        date_col.x_min, date_col.x_max, len(data_words), len(date_words), len(date_matches))
            for w in date_words[:10]:
                log.warning("    word: '%s' x=%.1f..%.1f y=%.1f page=%d", w.text, w.x0, w.x1, w.top, w.page)

    # Header region info
    header_info = cached.header_region or {}

    pages_parsed = len(cached.pages)
    log.info("parse_with_mapping: %d transactions from %d/%d pages",
             len(transactions), pages_parsed, cached.page_count)

    # Build info dict with ALL detected header fields
    info_dict: Dict[str, Any] = {
        "bank": cached.bank_name,
        "bank_name": cached.bank_name,
        "account_number": header_info.get("account_number", ""),
        "account_holder": header_info.get("account_holder", ""),
        "period_from": header_info.get("period_from", ""),
        "period_to": header_info.get("period_to", ""),
        "opening_balance": header_info.get("opening_balance"),
        "closing_balance": header_info.get("closing_balance"),
        "available_balance": header_info.get("available_balance"),
        "currency": header_info.get("currency", "PLN"),
        "previous_closing_balance": header_info.get("previous_closing_balance"),
        "declared_credits_count": header_info.get("declared_credits_count"),
        "declared_credits_sum": header_info.get("declared_credits_sum"),
        "declared_debits_count": header_info.get("declared_debits_count"),
        "declared_debits_sum": header_info.get("declared_debits_sum"),
        "debt_limit": header_info.get("debt_limit"),
        "overdue_commission": header_info.get("overdue_commission"),
        "blocked_amount": header_info.get("blocked_amount"),
    }

    return {
        "status": "ok",
        "bank_id": cached.bank_id,
        "bank_name": cached.bank_name,
        "transactions": transactions,
        "transaction_count": len(transactions),
        "pages_parsed": pages_parsed,
        "info": info_dict,
        "page_count": cached.page_count,
    }



# Transaction extraction is now handled by spatial_parser._extract_transactions()


# ============================================================
# TEMPLATE CRUD
# ============================================================

def _ensure_template_columns(conn):
    """Add column_bounds and header_fields columns to parse_templates if they don't exist."""
    try:
        conn.execute("SELECT column_bounds FROM parse_templates LIMIT 0")
    except Exception:
        conn.execute("ALTER TABLE parse_templates ADD COLUMN column_bounds TEXT DEFAULT '[]'")
        log.info("Added column_bounds column to parse_templates")
    try:
        conn.execute("SELECT header_fields FROM parse_templates LIMIT 0")
    except Exception:
        conn.execute("ALTER TABLE parse_templates ADD COLUMN header_fields TEXT DEFAULT '{}'")
        log.info("Added header_fields column to parse_templates")


def save_template(
    bank_id: str,
    bank_name: str,
    column_mapping: Dict[str, str],
    header_cells: List[str],
    header_row: int = 0,
    data_start_row: int = 1,
    name: str = "",
    is_default: bool = False,
    column_bounds: Optional[List[Dict[str, Any]]] = None,
    header_fields: Optional[Dict[str, str]] = None,
) -> str:
    """Save a column mapping template (includes header fields like saldo/IBAN).

    Uses UPSERT: if a template with the same bank_id and name exists,
    it is updated instead of creating a duplicate.
    """
    ensure_initialized()

    if not name:
        name = f"{bank_name} — szablon"

    bounds_json = json.dumps(column_bounds or [], ensure_ascii=False)
    hf_json = json.dumps(header_fields or {}, ensure_ascii=False)
    mapping_json = json.dumps(column_mapping, ensure_ascii=False)
    headers_json = json.dumps(header_cells, ensure_ascii=False)

    with get_conn() as conn:
        _ensure_template_columns(conn)

        # Check for existing template with same bank_id + name
        existing = conn.execute(
            "SELECT id FROM parse_templates WHERE bank_id = ? AND name = ?",
            (bank_id, name),
        ).fetchone()

        if existing:
            # Update existing template instead of creating a duplicate
            template_id = existing[0] if isinstance(existing, (tuple, list)) else existing["id"]
            conn.execute(
                """UPDATE parse_templates
                   SET column_mapping = ?, header_row = ?, data_start_row = ?,
                       sample_headers = ?, is_default = ?, column_bounds = ?,
                       header_fields = ?, bank_name = ?
                   WHERE id = ?""",
                (mapping_json, header_row, data_start_row,
                 headers_json, int(is_default), bounds_json,
                 hf_json, bank_name, template_id),
            )
            log.info("Updated template %s for bank %s (bounds: %d cols, header_fields: %d)",
                     template_id[:8], bank_id, len(column_bounds or []), len(header_fields or {}))
        else:
            # Create new template
            template_id = new_id()

            conn.execute(
                """INSERT INTO parse_templates
                   (id, bank_id, bank_name, name, column_mapping, header_row,
                    data_start_row, sample_headers, is_default, column_bounds,
                    header_fields)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (template_id, bank_id, bank_name, name,
                 mapping_json, header_row, data_start_row,
                 headers_json, int(is_default),
                 bounds_json, hf_json),
            )
            log.info("Saved new template %s for bank %s (bounds: %d cols, header_fields: %d)",
                     template_id[:8], bank_id, len(column_bounds or []), len(header_fields or {}))

        # If setting as default, unset other defaults
        if is_default:
            conn.execute(
                "UPDATE parse_templates SET is_default = 0 WHERE bank_id = ? AND id != ?",
                (bank_id, template_id),
            )

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
