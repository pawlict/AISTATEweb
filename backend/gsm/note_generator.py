"""
GSM Note DOCX Generator — fills the professional note template with data.

Pipeline:
  1. docxtpl renders Jinja2 placeholders + chart InlineImages
  2. python-docx inserts optional data tables after section headings

Chart images are embedded via docxtpl InlineImage ({%p if chart_X %}).
Tables are inserted programmatically to avoid Jinja2 nesting issues.
"""
from __future__ import annotations

import io
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger("aistate.gsm.note_gen")


# ─── Table definitions ──────────────────────────────────────────────────────

TABLE_DEFS = {
    "stats": {
        "section_heading": "4.",
        "caption": "Tabela: Statystyki aktywności telekomunikacyjnej",
        "columns": ["Parametr", "Wartość"],
    },
    "contacts": {
        "section_heading": "5.",
        "caption": "Tabela: Najczęstsze kontakty",
        "columns": ["Numer", "Interakcje", "Poł. wych.", "Poł. przych."],
    },
    "anomalies": {
        "section_heading": "6.",
        "caption": "Tabela: Wykryte anomalie",
        "columns": ["Kategoria", "Opis", "Ważność"],
    },
    "locations": {
        "section_heading": "7.",
        "caption": "Tabela: Lokalizacje BTS",
        "columns": ["Lokalizacja", "Liczba rekordów", "Udział %"],
    },
}


# ─── Public API ─────────────────────────────────────────────────────────────

def generate_note_docx(
    template_path: Path,
    placeholders: Dict[str, Any],
    output_path: Path,
    *,
    chart_images: Optional[Dict[str, bytes]] = None,
    llm_overrides: Optional[Dict[str, str]] = None,
    table_data: Optional[Dict[str, List[List[str]]]] = None,
    selected_tables: Optional[List[str]] = None,
) -> Path:
    """Generate a professional analytical note DOCX from the template.

    Args:
        template_path: Path to the DOCX template (gsm_note_template.docx).
        placeholders: Dict from note_builder.build_note_placeholders().
        output_path: Where to save the generated DOCX.
        chart_images: Optional dict of chart_name → PNG bytes to embed.
            Keys: "activity", "top_contacts", "night_activity",
                  "weekend_activity", "map_bts"
        llm_overrides: Optional dict from note_llm.generate_note_sections_llm().
        table_data: Optional dict of table_name → list of row data (list of strings).
            Keys: "stats", "contacts", "anomalies", "locations"
        selected_tables: List of table names to include (e.g., ["stats", "contacts"]).
            If None, no tables are added.

    Returns:
        Path to the generated DOCX file.
    """
    from docxtpl import DocxTemplate, InlineImage
    from docx.shared import Mm

    # Merge LLM overrides into placeholders
    if llm_overrides:
        _apply_llm_overrides(placeholders, llm_overrides)

    # Open template
    tpl = DocxTemplate(str(template_path))

    # Prepare inline images for charts
    images = {}
    if chart_images:
        for name, img_bytes in chart_images.items():
            if img_bytes:
                try:
                    img_stream = io.BytesIO(img_bytes)
                    images[f"chart_{name}"] = InlineImage(
                        tpl, img_stream, width=Mm(150)
                    )
                except Exception as e:
                    log.warning("Failed to create InlineImage for %s: %s", name, e)

    # Build context — flatten nested dicts for docxtpl
    context = _flatten_for_template(placeholders)
    context.update(images)

    # Render with docxtpl (step 1: placeholders + charts)
    tpl.render(context)

    # Save intermediate result
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tpl.save(str(output_path))

    # Step 2: Insert tables programmatically using python-docx
    if selected_tables and table_data:
        _insert_tables(output_path, table_data, selected_tables)

    log.info("Generated GSM note: %s (%d bytes)", output_path.name, output_path.stat().st_size)
    return output_path


# ─── Table insertion (python-docx) ──────────────────────────────────────────

def _insert_tables(
    docx_path: Path,
    table_data: Dict[str, List[List[str]]],
    selected_tables: List[str],
) -> None:
    """Insert data tables into rendered DOCX at section positions."""
    from docx import Document
    from docx.shared import Pt, Cm, RGBColor
    from docx.enum.table import WD_TABLE_ALIGNMENT
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml.ns import qn

    doc = Document(str(docx_path))
    body = doc.element.body

    for table_name in selected_tables:
        tdef = TABLE_DEFS.get(table_name)
        rows = table_data.get(table_name)
        if not tdef or not rows:
            continue

        # Find section heading paragraph
        heading_prefix = tdef["section_heading"]
        insert_after = _find_section_last_element(doc, body, heading_prefix)
        if insert_after is None:
            log.warning("Section heading '%s' not found, skipping table '%s'",
                        heading_prefix, table_name)
            continue

        # Create caption paragraph
        caption_p = doc.add_paragraph()
        body.remove(caption_p._element)
        idx = _body_index(body, insert_after)
        body.insert(idx + 1, caption_p._element)
        run = caption_p.add_run(tdef["caption"])
        run.bold = True
        run.font.size = Pt(9)
        run.font.color.rgb = RGBColor(0, 0, 0)

        # Create table
        columns = tdef["columns"]
        n_rows = 1 + len(rows)  # header + data
        n_cols = len(columns)

        table = doc.add_table(rows=n_rows, cols=n_cols)
        table.style = 'Table Grid'
        table.alignment = WD_TABLE_ALIGNMENT.CENTER

        # Move table after caption
        body.remove(table._tbl)
        idx = _body_index(body, caption_p._element)
        body.insert(idx + 1, table._tbl)

        # Header row
        for i, col_name in enumerate(columns):
            cell = table.rows[0].cells[i]
            cell.text = col_name
            for p in cell.paragraphs:
                for r in p.runs:
                    r.bold = True
                    r.font.size = Pt(8)
                    r.font.color.rgb = RGBColor(0, 0, 0)

        # Data rows
        for row_idx, row_data in enumerate(rows):
            row = table.rows[row_idx + 1]
            for col_idx, cell_text in enumerate(row_data):
                if col_idx < n_cols:
                    cell = row.cells[col_idx]
                    cell.text = str(cell_text)
                    for p in cell.paragraphs:
                        for r in p.runs:
                            r.font.size = Pt(8)

        # Add empty paragraph after table for spacing
        spacer = doc.add_paragraph()
        body.remove(spacer._element)
        idx = _body_index(body, table._tbl)
        body.insert(idx + 1, spacer._element)
        spacer.add_run("").font.size = Pt(6)

        log.debug("Inserted table '%s' with %d rows", table_name, len(rows))

    doc.save(str(docx_path))


def _find_section_last_element(doc, body, heading_prefix: str):
    """Find the last body element in a section (before next heading)."""
    from docx.oxml.ns import qn

    found_heading = False
    last_elem = None

    for child in body:
        if child.tag == qn('w:p'):
            # Check if this is a heading
            pStyle = child.find(f'.//{qn("w:pStyle")}')
            is_heading = pStyle is not None and 'Heading' in pStyle.get(qn('w:val'), '')

            if is_heading:
                # Get text content
                texts = child.itertext()
                full_text = ''.join(texts).strip()
                if full_text.startswith(heading_prefix):
                    found_heading = True
                    last_elem = child
                    continue
                elif found_heading:
                    # Hit next heading — stop
                    break

        if found_heading:
            last_elem = child

    return last_elem


def _body_index(body, element) -> int:
    """Get index of element in body's children."""
    for i, child in enumerate(body):
        if child is element:
            return i
    return len(body) - 1


# ─── Table data builders ───────────────────────────────────────────────────

def build_table_data(gsm_data: dict) -> Dict[str, List[List[str]]]:
    """Build table row data from gsm_latest.json for all table types.

    Returns dict of table_name → list of rows (each row is list of strings).
    """
    billing = gsm_data.get("billing", {})
    summary = billing.get("summary", {})
    analysis = billing.get("analysis", {})

    tables: Dict[str, List[List[str]]] = {}

    # Stats table
    calls_out = summary.get("calls_out", 0) or 0
    calls_in = summary.get("calls_in", 0) or 0
    sms_out = summary.get("sms_out", 0) or 0
    sms_in = summary.get("sms_in", 0) or 0
    data_sessions = summary.get("data_sessions", 0) or 0
    total = summary.get("total_records", 0) or 0
    duration = summary.get("call_duration_seconds", 0) or 0
    unique = summary.get("unique_contacts", 0) or 0

    tables["stats"] = [
        ["Połączenia wychodzące", str(calls_out)],
        ["Połączenia przychodzące", str(calls_in)],
        ["SMS wychodzące", str(sms_out)],
        ["SMS przychodzące", str(sms_in)],
        ["Sesje transmisji danych", str(data_sessions)],
        ["Łączna liczba rekordów", str(total)],
        ["Czas połączeń (s)", str(duration)],
        ["Unikalne kontakty", str(unique)],
    ]

    # Top contacts table
    top_contacts = analysis.get("top_contacts", [])
    tables["contacts"] = []
    for c in top_contacts[:10]:
        number = c.get("number", "?")
        interactions = str(c.get("total_interactions", 0))
        c_out = str(c.get("calls_out", 0))
        c_in = str(c.get("calls_in", 0))
        tables["contacts"].append([number, interactions, c_out, c_in])

    # Anomalies table
    anomalies = analysis.get("anomalies", [])
    tables["anomalies"] = []
    for a in anomalies:
        label = a.get("label", a.get("type", "?"))
        desc = a.get("description", a.get("explain", ""))
        if len(desc) > 80:
            desc = desc[:77] + "..."
        severity = a.get("severity", "")
        tables["anomalies"].append([label, desc, severity])

    # Locations table
    locations = analysis.get("locations", [])
    total_loc_records = sum(loc.get("record_count", 0) for loc in locations) or 1
    tables["locations"] = []
    for loc in locations[:15]:
        location = loc.get("location", loc.get("address", "?"))
        records = str(loc.get("record_count", 0))
        pct = f"{loc.get('record_count', 0) / total_loc_records * 100:.1f}%"
        tables["locations"].append([location, records, pct])

    return tables


# ─── Helpers ────────────────────────────────────────────────────────────────

def _flatten_for_template(placeholders: Dict[str, Any]) -> Dict[str, Any]:
    """Flatten nested dicts into dot-notation keys for docxtpl.

    docxtpl supports both {{ key }} and {{ obj.key }} syntax.
    We keep both formats for compatibility.
    """
    context: Dict[str, Any] = {}

    for key, value in placeholders.items():
        if isinstance(value, dict):
            context[key] = value
            for sub_key, sub_value in value.items():
                context[f"{key}_{sub_key}"] = sub_value
        else:
            context[key] = value

    return context


def _apply_llm_overrides(placeholders: Dict[str, Any], overrides: Dict[str, str]) -> None:
    """Apply LLM-generated text overrides to placeholders dict."""
    for key, value in overrides.items():
        if key.startswith("_"):
            continue

        parts = key.split(".", 1)
        if len(parts) == 2:
            parent, child = parts
            if parent in placeholders and isinstance(placeholders[parent], dict):
                placeholders[parent][child] = value
            else:
                placeholders[parent] = {child: value}
        else:
            placeholders[key] = value


def get_default_template_path() -> Path:
    """Return path to the bundled GSM note template."""
    pkg_dir = Path(__file__).resolve().parent.parent.parent
    template = pkg_dir / "templates" / "gsm_note_template.docx"
    if template.exists():
        return template

    import os
    data_dir = Path(os.environ.get("AISTATEWEB_DATA_DIR", "data_www"))
    alt = data_dir / "templates" / "gsm_note_template.docx"
    if alt.exists():
        return alt

    raise FileNotFoundError(
        f"GSM note template not found. Expected at {template} or {alt}"
    )
