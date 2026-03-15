"""
TXT Report Generator — plain text report with ASCII tables.

Generates clean, readable text without graphics or formatting.
Tables rendered as ASCII-art (simple column alignment).
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


def generate_txt_report(
    report_data: dict,
    placeholders: Dict[str, str],
    output_path: Path,
    report_type: str = "gsm",
) -> Path:
    """Generate a plain text report.

    Args:
        report_data: Output from report_builder.build_report_data()
        placeholders: Header/footer field values
        output_path: Where to save the TXT file
        report_type: "gsm" or "aml"

    Returns:
        Path to saved TXT file.
    """
    lines: List[str] = []

    # ── Header ──
    inst = placeholders.get("INSTYTUCJA", "")
    addr = placeholders.get("ADRES_INSTYTUCJI", "")
    sig = placeholders.get("SYGNATURA", "")
    date = placeholders.get("DATA_RAPORTU", datetime.now().strftime("%Y-%m-%d"))
    analyst = placeholders.get("ANALITYK", "")
    footer = placeholders.get("STOPKA", "Wygenerowano w AISTATEweb")

    if inst:
        lines.append(inst)
    if addr:
        lines.append(addr)
    lines.append("")

    title = report_data.get("title", "Raport")
    lines.append("=" * 70)
    lines.append(f"  {title}")
    lines.append("=" * 70)
    lines.append("")

    if sig:
        lines.append(f"Sygnatura: {sig}")
    lines.append(f"Data sporządzenia: {date}")
    if analyst:
        lines.append(f"Analityk: {analyst}")

    subscriber = report_data.get("subscriber_label", "")
    if subscriber:
        lines.append(f"Abonent: {subscriber}")

    generated_at = report_data.get("generated_at", "")
    if generated_at:
        lines.append(f"Wygenerowano: {generated_at}")

    lines.append("")
    lines.append("═" * 70)
    lines.append("")

    # ── Sections ──
    for sec in report_data.get("sections", []):
        sec_lines = _render_section_txt(sec)
        lines.extend(sec_lines)

    # ── Footer ──
    lines.append("═" * 70)
    lines.append(footer)
    lines.append("")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")
    return output_path


def _render_section_txt(section: dict) -> List[str]:
    """Render a single section as plain text lines."""
    lines: List[str] = []
    title = section.get("title", "Sekcja")
    content_md = section.get("content_md", "")
    tables = section.get("tables", [])

    # Section title
    lines.append(f"── {title} {'─' * max(0, 66 - len(title))}")
    lines.append("")

    # Content (strip markdown formatting)
    if content_md:
        clean_lines = _strip_markdown(content_md)
        lines.extend(clean_lines)
        lines.append("")

    # Structured tables (ASCII-art)
    for tbl in tables:
        tbl_lines = _render_ascii_table(tbl)
        lines.extend(tbl_lines)
        lines.append("")

    lines.append("")
    return lines


def _strip_markdown(md: str) -> List[str]:
    """Strip markdown formatting, keeping plain text structure."""
    import re
    lines = md.split("\n")
    result = []

    for line in lines:
        stripped = line.strip()

        # Skip empty
        if not stripped:
            result.append("")
            continue

        # Remove markdown table formatting (tables handled separately)
        if stripped.startswith("|") and stripped.endswith("|"):
            # Convert markdown table to plain text
            cells = [c.strip() for c in stripped.split("|")[1:-1]]
            # Skip separator rows
            if all(c.replace("-", "").replace(":", "").strip() == "" for c in cells):
                continue
            result.append("  " + "  |  ".join(cells))
            continue

        # Strip heading markers
        if stripped.startswith("#"):
            text = stripped.lstrip("#").strip()
            result.append(text)
            result.append("-" * len(text))
            continue

        # Strip bold/italic markers
        text = stripped
        text = re.sub(r'\*\*\*(.+?)\*\*\*', r'\1', text)
        text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
        text = re.sub(r'\*(.+?)\*', r'\1', text)
        text = re.sub(r'`(.+?)`', r'\1', text)

        result.append(text)

    return result


def _render_ascii_table(tbl: dict) -> List[str]:
    """Render a structured table as ASCII-art."""
    headers = tbl.get("headers", [])
    rows = tbl.get("rows", [])
    title = tbl.get("title", "")

    if not rows and not headers:
        return []

    lines: List[str] = []
    if title:
        lines.append(f"  {title}:")
        lines.append("")

    # Calculate column widths
    all_rows = []
    if headers:
        all_rows.append([str(h) for h in headers])
    for row in rows:
        if isinstance(row, (list, tuple)):
            all_rows.append([str(c) for c in row])
        elif isinstance(row, dict):
            all_rows.append([str(row.get(h, "")) for h in headers])

    if not all_rows:
        return lines

    num_cols = max(len(r) for r in all_rows)
    col_widths = [0] * num_cols
    for row in all_rows:
        for i, cell in enumerate(row):
            if i < num_cols:
                col_widths[i] = max(col_widths[i], len(cell))

    # Cap column widths
    col_widths = [min(w, 40) for w in col_widths]

    def format_row(cells: List[str]) -> str:
        parts = []
        for i in range(num_cols):
            val = cells[i] if i < len(cells) else ""
            width = col_widths[i] if i < len(col_widths) else 10
            parts.append(val[:width].ljust(width))
        return "  " + "  │  ".join(parts)

    separator = "  " + "──┼──".join("─" * w for w in col_widths)

    if headers:
        lines.append(format_row([str(h) for h in headers]))
        lines.append(separator)
        start = 0
    else:
        start = 0

    for row in all_rows[1 if headers else 0:]:
        lines.append(format_row(row))

    return lines
