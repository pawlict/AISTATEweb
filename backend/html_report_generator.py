"""
HTML Report Generator — self-contained offline analytical viewer.

Generates a single HTML file with:
- Embedded CSS (dark/light theme toggle)
- Inline JavaScript for table sorting, filtering, search
- Collapsible sections
- All data self-contained (no external dependencies)
"""
from __future__ import annotations

import html
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


def generate_html_report(
    report_data: dict,
    placeholders: Dict[str, str],
    output_path: Path,
    report_type: str = "gsm",
) -> Path:
    """Generate a self-contained HTML report.

    Args:
        report_data: Output from report_builder.build_report_data()
        placeholders: Header/footer field values
        output_path: Where to save the HTML file
        report_type: "gsm" or "aml"

    Returns:
        Path to saved HTML file.
    """
    title = report_data.get("title", "Raport")
    generated_at = report_data.get("generated_at", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    subscriber_label = report_data.get("subscriber_label", "")
    sections = report_data.get("sections", [])

    # Build sections HTML
    sections_html = []
    for i, sec in enumerate(sections):
        sec_html = _render_section_html(sec, i)
        sections_html.append(sec_html)

    # Build header from placeholders
    inst = html.escape(placeholders.get("INSTYTUCJA", ""))
    addr = html.escape(placeholders.get("ADRES_INSTYTUCJI", ""))
    sig = html.escape(placeholders.get("SYGNATURA", ""))
    date = html.escape(placeholders.get("DATA_RAPORTU", generated_at.split(" ")[0]))
    analyst = html.escape(placeholders.get("ANALITYK", ""))
    footer_text = html.escape(placeholders.get("STOPKA", "Wygenerowano w AISTATEweb"))

    report_type_label = "bilingu GSM" if report_type == "gsm" else "AML"

    page_html = _HTML_TEMPLATE.format(
        title=html.escape(title),
        report_type_label=report_type_label,
        institution=inst,
        address=addr,
        signature=sig,
        report_date=date,
        analyst=analyst,
        subscriber_label=html.escape(subscriber_label),
        generated_at=html.escape(generated_at),
        sections_html="\n".join(sections_html),
        footer_text=footer_text,
        sections_json=json.dumps([s.get("key", "") for s in sections], ensure_ascii=False),
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(page_html, encoding="utf-8")
    return output_path


def _render_section_html(section: dict, index: int) -> str:
    """Render a single section as HTML."""
    key = section.get("key", f"sec_{index}")
    title = html.escape(section.get("title", "Sekcja"))
    group = html.escape(section.get("group", ""))
    content_md = section.get("content_md", "")
    tables = section.get("tables", [])
    data = section.get("data")

    # Convert markdown to basic HTML
    content_html = _md_to_html(content_md) if content_md else ""

    # Render structured tables
    tables_html = ""
    for tbl in tables:
        tables_html += _render_table_html(tbl)

    # Data attribute for interactive features
    data_attr = ""
    if data:
        try:
            data_json = json.dumps(data, ensure_ascii=False, default=str)
            data_attr = f' data-raw=\'{html.escape(data_json)}\''
        except (TypeError, ValueError):
            pass

    return f"""
    <section class="report-section" id="sec-{html.escape(key)}"{data_attr}>
      <div class="section-header" onclick="toggleSection(this)">
        <span class="section-toggle">▼</span>
        <h2>{title}</h2>
        <span class="section-group">{group}</span>
      </div>
      <div class="section-content">
        {content_html}
        {tables_html}
      </div>
    </section>
    """


def _render_table_html(tbl: dict) -> str:
    """Render a structured table as sortable HTML table."""
    headers = tbl.get("headers", [])
    rows = tbl.get("rows", [])
    title = tbl.get("title", "")

    if not rows:
        return ""

    html_parts = []
    if title:
        html_parts.append(f'<h4 class="table-title">{html.escape(str(title))}</h4>')

    html_parts.append('<div class="table-wrapper"><table class="sortable">')

    # Header
    if headers:
        html_parts.append("<thead><tr>")
        for h in headers:
            html_parts.append(f'<th onclick="sortTable(this)">{html.escape(str(h))} <span class="sort-arrow">⇅</span></th>')
        html_parts.append("</tr></thead>")

    # Body
    html_parts.append("<tbody>")
    for row in rows:
        html_parts.append("<tr>")
        if isinstance(row, (list, tuple)):
            for cell in row:
                html_parts.append(f"<td>{html.escape(str(cell))}</td>")
        elif isinstance(row, dict):
            for h in headers:
                html_parts.append(f"<td>{html.escape(str(row.get(h, '')))}</td>")
        html_parts.append("</tr>")
    html_parts.append("</tbody></table></div>")

    return "\n".join(html_parts)


def _md_to_html(md: str) -> str:
    """Very basic markdown to HTML conversion."""
    lines = md.split("\n")
    result = []
    in_list = False

    for line in lines:
        stripped = line.strip()

        if not stripped:
            if in_list:
                result.append("</ul>")
                in_list = False
            result.append("<br>")
            continue

        # Skip markdown tables (handled separately)
        if stripped.startswith("|"):
            continue

        # Headers
        if stripped.startswith("####"):
            result.append(f"<h5>{_inline_md(stripped.lstrip('#').strip())}</h5>")
            continue
        if stripped.startswith("###"):
            result.append(f"<h4>{_inline_md(stripped.lstrip('#').strip())}</h4>")
            continue

        # Bullet list
        if stripped.startswith("- ") or stripped.startswith("* "):
            if not in_list:
                result.append("<ul>")
                in_list = True
            result.append(f"<li>{_inline_md(stripped[2:])}</li>")
            continue

        if in_list:
            result.append("</ul>")
            in_list = False

        # Numbered list
        import re
        m = re.match(r"^(\d+)\.\s+(.+)", stripped)
        if m:
            result.append(f"<p><strong>{m.group(1)}.</strong> {_inline_md(m.group(2))}</p>")
            continue

        # Regular paragraph
        result.append(f"<p>{_inline_md(stripped)}</p>")

    if in_list:
        result.append("</ul>")

    return "\n".join(result)


def _inline_md(text: str) -> str:
    """Convert inline markdown to HTML."""
    import re
    text = html.escape(text)
    # ***bold italic***
    text = re.sub(r'\*\*\*(.+?)\*\*\*', r'<strong><em>\1</em></strong>', text)
    # **bold**
    text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
    # *italic*
    text = re.sub(r'\*(.+?)\*', r'<em>\1</em>', text)
    # `code`
    text = re.sub(r'`(.+?)`', r'<code>\1</code>', text)
    return text


# ─── HTML template ────────────────────────────────────────────────────────────

_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="pl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<style>
:root {{
  --bg: #fff; --fg: #222; --bg2: #f5f5f5; --border: #ddd;
  --accent: #2563eb; --accent-light: #dbeafe;
  --header-bg: #1e293b; --header-fg: #fff;
  --section-bg: #fff; --section-border: #e2e8f0;
  --table-header: #f1f5f9; --table-stripe: #f8fafc;
  --success: #16a34a; --warning: #f59e0b; --danger: #dc2626;
}}
[data-theme="dark"] {{
  --bg: #0f172a; --fg: #e2e8f0; --bg2: #1e293b; --border: #334155;
  --accent: #3b82f6; --accent-light: #1e3a5f;
  --header-bg: #0f172a; --header-fg: #f1f5f9;
  --section-bg: #1e293b; --section-border: #334155;
  --table-header: #334155; --table-stripe: #1e293b;
}}
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ font-family: 'Segoe UI', Calibri, sans-serif; background: var(--bg); color: var(--fg); line-height: 1.6; }}
.container {{ max-width: 1200px; margin: 0 auto; padding: 20px; }}
.report-header {{
  background: var(--header-bg); color: var(--header-fg);
  padding: 30px; border-radius: 8px; margin-bottom: 20px;
}}
.report-header h1 {{ font-size: 1.5em; margin-bottom: 10px; }}
.report-header .meta {{ font-size: 0.9em; opacity: 0.8; }}
.report-header .institution {{ font-size: 1.2em; font-weight: bold; margin-bottom: 5px; }}
.toolbar {{
  display: flex; gap: 10px; align-items: center; padding: 12px 0;
  margin-bottom: 15px; border-bottom: 1px solid var(--border);
  flex-wrap: wrap;
}}
.toolbar input[type="search"] {{
  flex: 1; min-width: 200px; padding: 8px 12px;
  border: 1px solid var(--border); border-radius: 6px;
  background: var(--bg); color: var(--fg); font-size: 14px;
}}
.toolbar button {{
  padding: 8px 16px; border: 1px solid var(--border); border-radius: 6px;
  background: var(--bg2); color: var(--fg); cursor: pointer; font-size: 13px;
}}
.toolbar button:hover {{ background: var(--accent-light); }}
.report-section {{
  background: var(--section-bg); border: 1px solid var(--section-border);
  border-radius: 8px; margin-bottom: 12px; overflow: hidden;
}}
.section-header {{
  display: flex; align-items: center; gap: 10px; padding: 14px 18px;
  cursor: pointer; user-select: none; background: var(--bg2);
}}
.section-header:hover {{ background: var(--accent-light); }}
.section-header h2 {{ font-size: 1.1em; flex: 1; }}
.section-group {{ font-size: 0.8em; opacity: 0.6; }}
.section-toggle {{ font-size: 0.8em; transition: transform 0.2s; }}
.section-content {{ padding: 18px; }}
.section-content.collapsed {{ display: none; }}
.section-content p {{ margin-bottom: 8px; }}
.section-content ul {{ margin: 8px 0 8px 20px; }}
.section-content li {{ margin-bottom: 4px; }}
.table-wrapper {{ overflow-x: auto; margin: 12px 0; }}
table.sortable {{ width: 100%; border-collapse: collapse; font-size: 0.9em; }}
table.sortable th, table.sortable td {{
  padding: 8px 12px; border: 1px solid var(--border); text-align: left;
}}
table.sortable th {{
  background: var(--table-header); cursor: pointer; position: relative;
  white-space: nowrap;
}}
table.sortable th:hover {{ background: var(--accent-light); }}
table.sortable tbody tr:nth-child(even) {{ background: var(--table-stripe); }}
.sort-arrow {{ font-size: 0.7em; opacity: 0.4; }}
.table-title {{ margin: 12px 0 6px; font-size: 1em; }}
.footer {{ text-align: center; padding: 20px; opacity: 0.6; font-size: 0.85em; }}
code {{ background: var(--bg2); padding: 2px 5px; border-radius: 3px; font-family: Consolas, monospace; font-size: 0.9em; }}
strong {{ font-weight: 600; }}
@media print {{
  .toolbar {{ display: none; }}
  .section-content.collapsed {{ display: block !important; }}
}}
</style>
</head>
<body>
<div class="container">

<div class="report-header">
  <div class="institution">{institution}</div>
  <div class="meta">{address}</div>
  <h1>Raport z analizy {report_type_label}</h1>
  <div class="meta">
    Sygnatura: {signature} | Data: {report_date} | Analityk: {analyst}<br>
    Abonent: {subscriber_label} | Wygenerowano: {generated_at}
  </div>
</div>

<div class="toolbar">
  <input type="search" id="searchInput" placeholder="Szukaj w raporcie..." oninput="filterSections(this.value)">
  <button onclick="expandAll()">Rozwiń wszystko</button>
  <button onclick="collapseAll()">Zwiń wszystko</button>
  <button onclick="toggleTheme()">Motyw</button>
  <button onclick="window.print()">Drukuj</button>
</div>

{sections_html}

<div class="footer">{footer_text}</div>

</div>

<script>
// Theme toggle
function toggleTheme() {{
  const d = document.documentElement;
  d.setAttribute('data-theme', d.getAttribute('data-theme') === 'dark' ? 'light' : 'dark');
  localStorage.setItem('report-theme', d.getAttribute('data-theme'));
}}
(function() {{
  const saved = localStorage.getItem('report-theme');
  if (saved) document.documentElement.setAttribute('data-theme', saved);
}})();

// Section toggle
function toggleSection(header) {{
  const content = header.nextElementSibling;
  const toggle = header.querySelector('.section-toggle');
  content.classList.toggle('collapsed');
  toggle.textContent = content.classList.contains('collapsed') ? '▶' : '▼';
}}
function expandAll() {{
  document.querySelectorAll('.section-content').forEach(c => c.classList.remove('collapsed'));
  document.querySelectorAll('.section-toggle').forEach(t => t.textContent = '▼');
}}
function collapseAll() {{
  document.querySelectorAll('.section-content').forEach(c => c.classList.add('collapsed'));
  document.querySelectorAll('.section-toggle').forEach(t => t.textContent = '▶');
}}

// Search / filter
function filterSections(query) {{
  const q = query.toLowerCase();
  document.querySelectorAll('.report-section').forEach(sec => {{
    const text = sec.textContent.toLowerCase();
    sec.style.display = (!q || text.includes(q)) ? '' : 'none';
    if (q && text.includes(q)) {{
      sec.querySelector('.section-content').classList.remove('collapsed');
      sec.querySelector('.section-toggle').textContent = '▼';
    }}
  }});
}}

// Table sort
function sortTable(th) {{
  const table = th.closest('table');
  const tbody = table.querySelector('tbody');
  if (!tbody) return;
  const idx = Array.from(th.parentElement.children).indexOf(th);
  const rows = Array.from(tbody.querySelectorAll('tr'));
  const asc = th.dataset.sort !== 'asc';
  th.parentElement.querySelectorAll('th').forEach(h => delete h.dataset.sort);
  th.dataset.sort = asc ? 'asc' : 'desc';
  rows.sort((a, b) => {{
    let va = a.children[idx]?.textContent?.trim() || '';
    let vb = b.children[idx]?.textContent?.trim() || '';
    const na = parseFloat(va), nb = parseFloat(vb);
    if (!isNaN(na) && !isNaN(nb)) return asc ? na - nb : nb - na;
    return asc ? va.localeCompare(vb, 'pl') : vb.localeCompare(va, 'pl');
  }});
  rows.forEach(r => tbody.appendChild(r));
  th.querySelector('.sort-arrow').textContent = asc ? '▲' : '▼';
}}
</script>
</body>
</html>"""
