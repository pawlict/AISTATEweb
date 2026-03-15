"""
GSM Note DOCX Generator — fills the professional note template with data.

Pipeline:
  1. docxtpl renders Jinja2 placeholders
  2. python-docx inserts:
     - data tables after section headings
     - descriptive paragraphs (anomaly intro, contact graph text, etc.)
     - chart images with captions after relevant sections
     - dash-list items for locations and movement data

Chart images are embedded programmatically (not via docxtpl InlineImage)
to keep the template clean and allow watermarked screenshots.
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
        "columns": ["Kategoria", "Opis", "Dane"],
    },
    "locations": {
        "section_heading": "7.",
        "caption": "Tabela: Lokalizacje BTS",
        "columns": ["Lokalizacja", "Liczba rekordów", "Udział %"],
    },
}

# ─── Descriptive text blocks ────────────────────────────────────────────────

ANOMALY_INTRO_TEXT = (
    "W toku analizy materiału bilingowego zidentyfikowano zdarzenia oraz "
    "sekwencje aktywności odbiegające od typowego profilu korzystania z numeru. "
    "Za anomalie uznano zarówno pojedyncze incydenty o niestandardowych cechach, "
    "jak i powtarzalne wzorce czasowe, kontaktowe lub lokalizacyjne, które mogą "
    "wymagać pogłębionej weryfikacji analitycznej."
)

CONTACTS_GRAPH_TEXT = (
    "Graf \u201eNajczęstsze kontakty\u201d obrazuje strukturę relacji komunikacyjnych "
    "analizowanego numeru, wskazując podmioty występujące najczęściej w ruchu "
    "telekomunikacyjnym. Pozwala to określić krąg najaktywniejszych kontaktów, "
    "uchwycić powtarzalność komunikacji oraz wskazać numery, które mogą odgrywać "
    "istotną rolę w badanym modelu łączności."
)

ACTIVITY_DISTRIBUTION_TEXT = (
    "Mapa rozkładu aktywności przedstawia intensywność zdarzeń telekomunikacyjnych "
    "w zależności od dnia tygodnia i pory doby. Zestawienie to pozwala uchwycić "
    "dominujące przedziały aktywności, wskazać powtarzalne schematy czasowe oraz "
    "ocenić, czy komunikacja koncentrowała się w typowych godzinach dziennych, "
    "czy również w porach nietypowych."
)

# Chart insertion order after section 5 (contacts)
CHART_INSERTION_ORDER = [
    {
        "key": "top_contacts",
        "caption": "Graf: Najczęstsze kontakty",
        "pre_text": CONTACTS_GRAPH_TEXT,
        "section_heading": "5.",
    },
    {
        "key": "activity",
        "caption": "Rozkład aktywności",
        "pre_text": ACTIVITY_DISTRIBUTION_TEXT,
        "sub_heading": "Rodzaj aktywności",
        "section_heading": "5.",  # insert after contacts section
    },
    {
        "key": "night_activity",
        "caption": "Aktywność nocna",
        "section_heading": "5.",
    },
    {
        "key": "weekend_activity",
        "caption": "Aktywność weekendowa",
        "section_heading": "5.",
    },
    {
        "key": "map_bts",
        "caption": "Mapa lokalizacji BTS",
        "section_heading": "7.",
    },
]


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
        chart_images: Optional dict of chart_name -> PNG bytes to embed.
        llm_overrides: Optional dict from note_llm.generate_note_sections_llm().
        table_data: Optional dict of table_name -> list of row data.
        selected_tables: List of table names to include.

    Returns:
        Path to the generated DOCX file.
    """
    from docxtpl import DocxTemplate

    # Merge LLM overrides into placeholders
    if llm_overrides:
        _apply_llm_overrides(placeholders, llm_overrides)

    # Extract internal data (prefixed with _) before flattening
    anomaly_table_rows = placeholders.pop("_anomaly_table_rows", [])
    location_areas_list = placeholders.pop("_location_areas_list", [])
    location_movement_list = placeholders.pop("_location_movement_list", [])

    # Open template
    tpl = DocxTemplate(str(template_path))

    # Build context — flatten nested dicts for docxtpl
    context = _flatten_for_template(placeholders)

    # Render with docxtpl (step 1: placeholders only, no images)
    tpl.render(context)

    # Save intermediate result
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tpl.save(str(output_path))

    # Step 2: Programmatic insertions using python-docx
    _post_process_docx(
        output_path,
        table_data=table_data,
        selected_tables=selected_tables,
        anomaly_table_rows=anomaly_table_rows,
        chart_images=chart_images,
        location_areas_list=location_areas_list,
        location_movement_list=location_movement_list,
    )

    log.info("Generated GSM note: %s (%d bytes)", output_path.name, output_path.stat().st_size)
    return output_path


# ─── Post-processing (python-docx) ──────────────────────────────────────────

def _post_process_docx(
    docx_path: Path,
    *,
    table_data: Optional[Dict[str, List[List[str]]]] = None,
    selected_tables: Optional[List[str]] = None,
    anomaly_table_rows: Optional[List[List[str]]] = None,
    chart_images: Optional[Dict[str, bytes]] = None,
    location_areas_list: Optional[List[str]] = None,
    location_movement_list: Optional[List[str]] = None,
) -> None:
    """Insert tables, charts, descriptive texts, and dash-lists into DOCX."""
    from docx import Document

    doc = Document(str(docx_path))
    body = doc.element.body

    # 1. Insert anomaly intro text + table with Kategoria/Opis/Dane
    if anomaly_table_rows:
        _insert_anomaly_section(doc, body, anomaly_table_rows)

    # 2. Insert standard tables (stats, contacts, locations)
    if selected_tables and table_data:
        tables_to_insert = [t for t in selected_tables if t != "anomalies"]
        if tables_to_insert:
            _insert_tables(doc, body, table_data, tables_to_insert)

    # 3. Insert location dash-lists
    if location_areas_list:
        _insert_dash_list_after_text(
            doc, body,
            search_text="koncentrowała się w rejonach",
            items=location_areas_list,
        )
    if location_movement_list:
        _insert_dash_list_after_text(
            doc, body,
            search_text="przesłanki dotyczące przemieszczania",
            items=location_movement_list,
        )

    # 4. Insert chart images
    if chart_images:
        _insert_chart_images(doc, body, chart_images)

    doc.save(str(docx_path))


# ─── Anomaly section ────────────────────────────────────────────────────────

def _insert_anomaly_section(doc, body, anomaly_rows: List[List[str]]) -> None:
    """Insert anomaly intro text and Kategoria/Opis/Dane table in section 6."""
    from docx.shared import Pt, RGBColor
    from docx.enum.table import WD_TABLE_ALIGNMENT
    from docx.oxml.ns import qn

    # Find section 6 heading
    insert_after = _find_section_heading(body, "6.")
    if insert_after is None:
        log.warning("Section 6 heading not found, skipping anomaly section")
        return

    # Insert intro text paragraph
    intro_p = doc.add_paragraph()
    body.remove(intro_p._element)
    idx = _body_index(body, insert_after)
    body.insert(idx + 1, intro_p._element)
    run = intro_p.add_run(ANOMALY_INTRO_TEXT)
    run.font.size = Pt(10)
    run.font.color.rgb = RGBColor(0, 0, 0)

    # Insert caption
    caption_p = doc.add_paragraph()
    body.remove(caption_p._element)
    idx = _body_index(body, intro_p._element)
    body.insert(idx + 1, caption_p._element)
    run = caption_p.add_run("Tabela: Wykryte anomalie")
    run.bold = True
    run.font.size = Pt(9)
    run.font.color.rgb = RGBColor(0, 0, 0)

    # Create table: Kategoria | Opis | Dane
    columns = ["Kategoria", "Opis", "Dane"]
    n_rows = 1 + len(anomaly_rows)
    table = doc.add_table(rows=n_rows, cols=3)
    table.style = 'Table Grid'
    table.alignment = WD_TABLE_ALIGNMENT.CENTER

    body.remove(table._tbl)
    idx = _body_index(body, caption_p._element)
    body.insert(idx + 1, table._tbl)

    # Header
    for i, col_name in enumerate(columns):
        cell = table.rows[0].cells[i]
        cell.text = col_name
        for p in cell.paragraphs:
            for r in p.runs:
                r.bold = True
                r.font.size = Pt(8)
                r.font.color.rgb = RGBColor(0, 0, 0)

    # Data rows
    for row_idx, row_data in enumerate(anomaly_rows):
        row = table.rows[row_idx + 1]
        for col_idx, cell_text in enumerate(row_data):
            if col_idx < 3:
                cell = row.cells[col_idx]
                cell.text = str(cell_text)
                for p in cell.paragraphs:
                    for r in p.runs:
                        r.font.size = Pt(7)

    # Spacer
    _add_spacer(doc, body, table._tbl)
    log.debug("Inserted anomaly section with %d rows", len(anomaly_rows))


# ─── Table insertion ─────────────────────────────────────────────────────────

def _insert_tables(
    doc, body,
    table_data: Dict[str, List[List[str]]],
    selected_tables: List[str],
) -> None:
    """Insert data tables into rendered DOCX at section positions."""
    from docx.shared import Pt, RGBColor
    from docx.enum.table import WD_TABLE_ALIGNMENT

    for table_name in selected_tables:
        tdef = TABLE_DEFS.get(table_name)
        rows = table_data.get(table_name)
        if not tdef or not rows:
            continue

        heading_prefix = tdef["section_heading"]
        insert_after = _find_section_last_element(body, heading_prefix)
        if insert_after is None:
            log.warning("Section heading '%s' not found, skipping table '%s'",
                        heading_prefix, table_name)
            continue

        # Caption
        caption_p = doc.add_paragraph()
        body.remove(caption_p._element)
        idx = _body_index(body, insert_after)
        body.insert(idx + 1, caption_p._element)
        run = caption_p.add_run(tdef["caption"])
        run.bold = True
        run.font.size = Pt(9)
        run.font.color.rgb = RGBColor(0, 0, 0)

        # Table
        columns = tdef["columns"]
        n_cols = len(columns)
        table = doc.add_table(rows=1 + len(rows), cols=n_cols)
        table.style = 'Table Grid'
        table.alignment = WD_TABLE_ALIGNMENT.CENTER

        body.remove(table._tbl)
        idx = _body_index(body, caption_p._element)
        body.insert(idx + 1, table._tbl)

        # Header
        for i, col_name in enumerate(columns):
            cell = table.rows[0].cells[i]
            cell.text = col_name
            for p in cell.paragraphs:
                for r in p.runs:
                    r.bold = True
                    r.font.size = Pt(8)
                    r.font.color.rgb = RGBColor(0, 0, 0)

        # Data
        for row_idx, row_data in enumerate(rows):
            row = table.rows[row_idx + 1]
            for col_idx, cell_text in enumerate(row_data):
                if col_idx < n_cols:
                    cell = row.cells[col_idx]
                    cell.text = str(cell_text)
                    for p in cell.paragraphs:
                        for r in p.runs:
                            r.font.size = Pt(8)

        _add_spacer(doc, body, table._tbl)
        log.debug("Inserted table '%s' with %d rows", table_name, len(rows))


# ─── Chart image insertion ───────────────────────────────────────────────────

def _insert_chart_images(doc, body, chart_images: Dict[str, bytes]) -> None:
    """Insert chart PNG images into DOCX after relevant sections."""
    from docx.shared import Pt, Mm, RGBColor, Inches

    # Track last insertion point per section to chain multiple images
    # Insert charts in defined order, all after section 5 except map_bts
    last_section5_elem = _find_section_last_element(body, "5.")
    last_section7_elem = _find_section_last_element(body, "7.")

    # Current insertion cursor for section 5 content
    cursor_s5 = last_section5_elem
    cursor_s7 = last_section7_elem

    for chart_def in CHART_INSERTION_ORDER:
        key = chart_def["key"]
        img_bytes = chart_images.get(key)
        if not img_bytes:
            continue

        # Determine insertion cursor
        if chart_def["section_heading"] == "7.":
            cursor = cursor_s7
        else:
            cursor = cursor_s5

        if cursor is None:
            log.warning("No insertion point for chart '%s'", key)
            continue

        # Optional sub-heading
        if chart_def.get("sub_heading"):
            heading_p = doc.add_paragraph()
            body.remove(heading_p._element)
            idx = _body_index(body, cursor)
            body.insert(idx + 1, heading_p._element)
            run = heading_p.add_run(chart_def["sub_heading"])
            run.bold = True
            run.font.size = Pt(11)
            run.font.color.rgb = RGBColor(0, 0, 0)
            cursor = heading_p._element

        # Optional pre-text
        if chart_def.get("pre_text"):
            text_p = doc.add_paragraph()
            body.remove(text_p._element)
            idx = _body_index(body, cursor)
            body.insert(idx + 1, text_p._element)
            run = text_p.add_run(chart_def["pre_text"])
            run.font.size = Pt(10)
            run.font.color.rgb = RGBColor(0, 0, 0)
            cursor = text_p._element

        # Insert image
        try:
            img_stream = io.BytesIO(img_bytes)
            img_p = doc.add_paragraph()
            body.remove(img_p._element)
            idx = _body_index(body, cursor)
            body.insert(idx + 1, img_p._element)

            run = img_p.add_run()
            run.add_picture(img_stream, width=Mm(155))
            cursor = img_p._element

            # Caption under image
            cap_p = doc.add_paragraph()
            body.remove(cap_p._element)
            idx = _body_index(body, cursor)
            body.insert(idx + 1, cap_p._element)
            run = cap_p.add_run(chart_def["caption"])
            run.italic = True
            run.font.size = Pt(8)
            run.font.color.rgb = RGBColor(100, 100, 100)
            cursor = cap_p._element

            log.debug("Inserted chart image '%s'", key)
        except Exception as e:
            log.warning("Failed to insert chart image '%s': %s", key, e)

        # Update cursors
        if chart_def["section_heading"] == "7.":
            cursor_s7 = cursor
        else:
            cursor_s5 = cursor


# ─── Dash-list insertion ─────────────────────────────────────────────────────

def _insert_dash_list_after_text(
    doc, body,
    search_text: str,
    items: List[str],
) -> None:
    """Insert a dash-prefixed list after a paragraph containing search_text."""
    from docx.shared import Pt, RGBColor
    from docx.oxml.ns import qn

    target = None
    for child in body:
        if child.tag == qn('w:p'):
            full_text = ''.join(child.itertext()).strip()
            if search_text in full_text:
                target = child
                break

    if target is None:
        log.debug("Text '%s' not found for dash-list insertion", search_text[:40])
        return

    cursor = target
    for item_text in items:
        p = doc.add_paragraph()
        body.remove(p._element)
        idx = _body_index(body, cursor)
        body.insert(idx + 1, p._element)
        run = p.add_run(f"\u2013 {item_text}")  # en-dash
        run.font.size = Pt(10)
        run.font.color.rgb = RGBColor(0, 0, 0)
        cursor = p._element

    log.debug("Inserted %d dash-list items after '%s'", len(items), search_text[:40])


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _find_section_heading(body, heading_prefix: str):
    """Find the heading paragraph element for a section number."""
    from docx.oxml.ns import qn

    for child in body:
        if child.tag == qn('w:p'):
            pStyle = child.find(f'.//{qn("w:pStyle")}')
            is_heading = pStyle is not None and 'Heading' in pStyle.get(qn('w:val'), '')
            if is_heading:
                full_text = ''.join(child.itertext()).strip()
                if full_text.startswith(heading_prefix):
                    return child
    return None


def _find_section_last_element(body, heading_prefix: str):
    """Find the last body element in a section (before next heading)."""
    from docx.oxml.ns import qn

    found_heading = False
    last_elem = None

    for child in body:
        if child.tag == qn('w:p'):
            pStyle = child.find(f'.//{qn("w:pStyle")}')
            is_heading = pStyle is not None and 'Heading' in pStyle.get(qn('w:val'), '')

            if is_heading:
                full_text = ''.join(child.itertext()).strip()
                if full_text.startswith(heading_prefix):
                    found_heading = True
                    last_elem = child
                    continue
                elif found_heading:
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


def _add_spacer(doc, body, after_elem) -> None:
    """Add a small spacer paragraph after an element."""
    from docx.shared import Pt
    spacer = doc.add_paragraph()
    body.remove(spacer._element)
    idx = _body_index(body, after_elem)
    body.insert(idx + 1, spacer._element)
    spacer.add_run("").font.size = Pt(6)


# ─── Table data builders ───────────────────────────────────────────────────

def build_table_data(gsm_data: dict, placeholders: Optional[Dict[str, Any]] = None) -> Dict[str, List[List[str]]]:
    """Build table row data from gsm_latest.json for all table types.

    Returns dict of table_name -> list of rows (each row is list of strings).
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

    # Anomalies table — use pre-built rows from placeholders if available
    if placeholders and "_anomaly_table_rows" in placeholders:
        tables["anomalies"] = placeholders["_anomaly_table_rows"]
    else:
        # Fallback: build from raw data with Kategoria/Opis/Dane
        from backend.gsm.note_builder import _build_anomaly_table_rows
        anomalies = analysis.get("anomalies", [])
        tables["anomalies"] = _build_anomaly_table_rows(anomalies)

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


# ─── Template helpers ────────────────────────────────────────────────────────

def _flatten_for_template(placeholders: Dict[str, Any]) -> Dict[str, Any]:
    """Flatten nested dicts into dot-notation keys for docxtpl."""
    context: Dict[str, Any] = {}

    for key, value in placeholders.items():
        if key.startswith("_"):
            continue  # Skip internal keys
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
