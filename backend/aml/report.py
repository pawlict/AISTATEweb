"""AML HTML report generator.

Produces a self-contained HTML file with:
1. Executive Summary
2. Top Alerts
3. Risk Categories (crypto, gambling, cash, etc.)
4. New counterparties + large amounts
5. Flow graph (embedded JSON for Cytoscape.js)
6. Transaction table with filters
7. Audit trail
"""

from __future__ import annotations

import html
import json
import logging
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

from .baseline import AnomalyAlert
from .normalize import NormalizedTransaction

log = logging.getLogger("aistate.aml.report")

# Minimal embedded CSS + JS for self-contained report
_REPORT_CSS = """
<style>
:root{--bg:#f8f9fa;--card:#fff;--border:#dee2e6;--text:#212529;--muted:#6c757d;
--danger:#dc3545;--warning:#ffc107;--success:#198754;--info:#0dcaf0;--primary:#0d6efd}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Segoe UI',system-ui,-apple-system,sans-serif;background:var(--bg);color:var(--text);line-height:1.5;padding:20px;max-width:1400px;margin:0 auto}
h1{font-size:1.8em;margin-bottom:5px}h2{font-size:1.4em;margin:25px 0 10px;border-bottom:2px solid var(--primary);padding-bottom:5px}
h3{font-size:1.1em;margin:15px 0 8px;color:var(--muted)}
.meta{color:var(--muted);font-size:.85em;margin-bottom:15px}
.card{background:var(--card);border:1px solid var(--border);border-radius:8px;padding:15px;margin-bottom:15px}
.grid{display:grid;gap:15px}.grid-2{grid-template-columns:1fr 1fr}.grid-3{grid-template-columns:1fr 1fr 1fr}.grid-4{grid-template-columns:1fr 1fr 1fr 1fr}
@media(max-width:900px){.grid-2,.grid-3,.grid-4{grid-template-columns:1fr}}
.badge{display:inline-block;padding:2px 8px;border-radius:12px;font-size:.75em;font-weight:600;margin:1px}
.badge-danger{background:#f8d7da;color:#842029}.badge-warning{background:#fff3cd;color:#664d03}
.badge-success{background:#d1e7dd;color:#0f5132}.badge-info{background:#cff4fc;color:#055160}
.badge-secondary{background:#e2e3e5;color:#41464b}
.score-box{text-align:center;padding:20px;border-radius:8px;font-size:2em;font-weight:700}
.score-low{background:#d1e7dd;color:#0f5132}.score-med{background:#fff3cd;color:#664d03}.score-high{background:#f8d7da;color:#842029}
table{width:100%;border-collapse:collapse;font-size:.85em}
th{background:#e9ecef;text-align:left;padding:8px;border-bottom:2px solid var(--border);position:sticky;top:0}
td{padding:6px 8px;border-bottom:1px solid var(--border)}
tr:hover{background:#f0f4ff}
.amount-in{color:var(--success)}.amount-out{color:var(--danger)}
.risk-tag{font-size:.7em;padding:1px 5px;border-radius:4px;margin:1px}
.alert-card{border-left:4px solid var(--warning);padding:10px 15px;margin:8px 0;background:#fffdf5}
.alert-card.critical{border-left-color:var(--danger);background:#fff5f5}
.alert-card.high{border-left-color:#fd7e14;background:#fff8f0}
.filter-bar{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:10px}
.filter-bar select,.filter-bar input{padding:5px 10px;border:1px solid var(--border);border-radius:4px;font-size:.85em}
.graph-container{width:100%;height:500px;border:1px solid var(--border);border-radius:8px;background:#fff;position:relative}
.graph-placeholder{display:flex;align-items:center;justify-content:center;height:100%;color:var(--muted)}
.audit{font-size:.8em;color:var(--muted)}
.collapsible>summary{cursor:pointer;font-weight:600;padding:5px 0}
.footer{text-align:center;color:var(--muted);font-size:.75em;margin-top:30px;padding-top:15px;border-top:1px solid var(--border)}
</style>
"""

_GRAPH_JS = """
<script>
function initGraph(data){
  var container=document.getElementById('graph-cy');
  if(!container||!data||!data.nodes)return;
  if(typeof cytoscape==='undefined'){
    container.innerHTML='<div class="graph-placeholder">Cytoscape.js nie załadowany. Graf dostępny jako JSON w źródle strony.</div>';
    return;
  }
  var elements=[];
  data.nodes.forEach(function(n){
    elements.push({data:{id:n.id,label:n.label,type:n.type,risk:n.risk_level}});
  });
  data.edges.forEach(function(e){
    elements.push({data:{id:e.id,source:e.source,target:e.target,type:e.type,
      amount:e.total_amount,count:e.tx_count,label:e.total_amount.toFixed(0)+' PLN ('+e.tx_count+'x)'}});
  });
  var cy=cytoscape({
    container:container,
    elements:elements,
    style:[
      {selector:'node',style:{'label':'data(label)','text-wrap':'wrap','text-max-width':'120px',
        'font-size':'10px','background-color':'#6c757d','color':'#212529','text-valign':'bottom',
        'text-halign':'center','width':'40px','height':'40px'}},
      {selector:'node[type="ACCOUNT"]',style:{'background-color':'#0d6efd','shape':'diamond','width':'50px','height':'50px'}},
      {selector:'node[type="MERCHANT"]',style:{'background-color':'#198754','shape':'round-rectangle'}},
      {selector:'node[type="CASH_NODE"]',style:{'background-color':'#ffc107','shape':'triangle'}},
      {selector:'node[risk="high"]',style:{'background-color':'#dc3545','border-width':'3px','border-color':'#842029'}},
      {selector:'node[risk="medium"]',style:{'background-color':'#fd7e14'}},
      {selector:'edge',style:{'width':2,'line-color':'#adb5bd','target-arrow-color':'#adb5bd',
        'target-arrow-shape':'triangle','curve-style':'bezier','label':'data(label)',
        'font-size':'8px','text-rotation':'autorotate','text-margin-y':'-8px'}},
      {selector:'edge[type="BLIK_P2P"]',style:{'line-color':'#6f42c1','target-arrow-color':'#6f42c1'}},
      {selector:'edge[type="CARD_PAYMENT"]',style:{'line-color':'#0dcaf0','target-arrow-color':'#0dcaf0'}},
      {selector:'edge[type="CASH"]',style:{'line-color':'#ffc107','target-arrow-color':'#ffc107','line-style':'dashed'}},
    ],
    layout:{name:'cose',idealEdgeLength:150,nodeOverlap:20,animate:false}
  });
}
document.addEventListener('DOMContentLoaded',function(){
  var el=document.getElementById('graph-data');
  if(el){try{initGraph(JSON.parse(el.textContent));}catch(e){console.error(e);}}
});
function filterTable(){
  var ch=document.getElementById('f-channel').value;
  var cat=document.getElementById('f-category').value;
  var q=document.getElementById('f-search').value.toLowerCase();
  var rows=document.querySelectorAll('#tx-table tbody tr');
  rows.forEach(function(r){
    var show=true;
    if(ch&&r.dataset.channel!==ch)show=false;
    if(cat&&r.dataset.category!==cat)show=false;
    if(q&&r.textContent.toLowerCase().indexOf(q)===-1)show=false;
    r.style.display=show?'':'none';
  });
}
</script>
"""


def generate_report(
    transactions: List[NormalizedTransaction],
    alerts: List[AnomalyAlert],
    graph_data: Dict[str, Any],
    risk_score: float = 0,
    risk_reasons: Optional[List[Dict[str, Any]]] = None,
    statement_info: Optional[Dict[str, Any]] = None,
    audit_info: Optional[Dict[str, Any]] = None,
    title: str = "Raport AML",
) -> str:
    """Generate self-contained HTML report.

    Returns:
        Complete HTML string.
    """
    info = statement_info or {}
    audit = audit_info or {}
    reasons = risk_reasons or []

    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    parts = [
        "<!DOCTYPE html>",
        '<html lang="pl">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>{html.escape(title)}</title>",
        _REPORT_CSS,
        # Cytoscape.js CDN (optional — works without it)
        '<script src="https://cdnjs.cloudflare.com/ajax/libs/cytoscape/3.28.1/cytoscape.min.js" '
        'integrity="sha512-PfNJOFVVw3nVGEqC/HEQTh1UXvpDI7jHMr/Fh4MJdqp2Lm+FE3Z7LcPq2bKJSCS98vU4bnYwV4L+YSjTA/eBw==" '
        'crossorigin="anonymous" onerror=""></script>',
        "</head>",
        "<body>",
    ]

    # --- Header ---
    parts.append(f"<h1>{html.escape(title)}</h1>")
    bank = info.get("bank_name", info.get("bank", ""))
    period = ""
    if info.get("period_from") and info.get("period_to"):
        period = f"{info['period_from']} — {info['period_to']}"
    parts.append(f'<p class="meta">Bank: {html.escape(bank)} | Okres: {html.escape(period)} | '
                 f'Wygenerowano: {now}</p>')

    # --- Executive Summary ---
    parts.append('<h2>1. Podsumowanie</h2>')
    parts.append('<div class="grid grid-4">')

    # Score box
    score_class = "score-low" if risk_score < 30 else ("score-med" if risk_score < 60 else "score-high")
    parts.append(f'<div class="card score-box {score_class}">{risk_score:.0f}<br>'
                 f'<span style="font-size:.4em">RISK SCORE</span></div>')

    # Key metrics
    total_credit = sum(float(tx.amount) for tx in transactions if tx.direction == "CREDIT")
    total_debit = sum(float(abs(tx.amount)) for tx in transactions if tx.direction == "DEBIT")
    opening = info.get("opening_balance", "—")
    closing = info.get("closing_balance", "—")

    parts.append(f'<div class="card"><h3>Transakcje</h3>{len(transactions)}<br>'
                 f'<span style="font-size:.85em;color:var(--muted)">'
                 f'Wpływy: {total_credit:,.2f} PLN<br>'
                 f'Wydatki: {total_debit:,.2f} PLN</span></div>')

    parts.append(f'<div class="card"><h3>Saldo</h3>'
                 f'Początkowe: {_fmt_amount(opening)}<br>'
                 f'Końcowe: {_fmt_amount(closing)}</div>')

    parts.append(f'<div class="card"><h3>Alerty</h3>{len(alerts)}<br>'
                 f'<span style="font-size:.85em;color:var(--muted)">'
                 f'Krytyczne: {sum(1 for a in alerts if a.severity == "critical")}, '
                 f'Wysokie: {sum(1 for a in alerts if a.severity == "high")}, '
                 f'Średnie: {sum(1 for a in alerts if a.severity == "medium")}'
                 f'</span></div>')
    parts.append('</div>')

    # --- Top Alerts ---
    if alerts:
        parts.append('<h2>2. Alerty</h2>')
        sorted_alerts = sorted(alerts, key=lambda a: {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(a.severity, 4))
        for alert in sorted_alerts[:20]:
            sev_class = "critical" if alert.severity == "critical" else ("high" if alert.severity == "high" else "")
            badge_cls = "badge-danger" if alert.severity in ("critical", "high") else "badge-warning"
            parts.append(
                f'<div class="alert-card {sev_class}">'
                f'<span class="badge {badge_cls}">{alert.severity.upper()}</span> '
                f'<strong>{html.escape(alert.alert_type)}</strong> '
                f'(+{alert.score_delta:.0f} pkt)<br>'
                f'{html.escape(alert.explain)}'
                f'</div>'
            )

    # --- Risk Reasons ---
    if reasons:
        parts.append('<h2>3. Składowe ryzyka</h2>')
        parts.append('<table><thead><tr><th>Kategoria</th><th>Ile transakcji</th>'
                     '<th>Kwota</th><th>% całości</th><th>Wpływ na score</th></tr></thead><tbody>')
        for r in reasons:
            parts.append(f'<tr><td>{html.escape(r.get("tag", ""))}</td>'
                         f'<td>{r.get("count", 0)}</td>'
                         f'<td>{r.get("amount", 0):,.2f} PLN</td>'
                         f'<td>{r.get("pct_of_total", 0):.1f}%</td>'
                         f'<td>+{r.get("score_delta", 0):.0f}</td></tr>')
        parts.append('</tbody></table>')

    # --- Flow Graph ---
    parts.append('<h2>4. Graf przepływów</h2>')
    parts.append(f'<script type="application/json" id="graph-data">{json.dumps(graph_data, ensure_ascii=False)}</script>')
    parts.append('<div id="graph-cy" class="graph-container">'
                 '<div class="graph-placeholder">Ładowanie grafu...</div></div>')

    # --- Transaction Table ---
    parts.append('<h2>5. Transakcje</h2>')

    # Filters
    channels = sorted(set(tx.channel for tx in transactions if tx.channel))
    categories = sorted(set(tx.category for tx in transactions if tx.category))

    parts.append('<div class="filter-bar">')
    parts.append('<select id="f-channel" onchange="filterTable()"><option value="">Kanał: wszystkie</option>')
    for ch in channels:
        parts.append(f'<option value="{html.escape(ch)}">{html.escape(ch)}</option>')
    parts.append('</select>')
    parts.append('<select id="f-category" onchange="filterTable()"><option value="">Kategoria: wszystkie</option>')
    for cat in categories:
        parts.append(f'<option value="{html.escape(cat)}">{html.escape(cat)}</option>')
    parts.append('</select>')
    parts.append('<input id="f-search" type="text" placeholder="Szukaj..." oninput="filterTable()">')
    parts.append('</div>')

    parts.append('<div style="max-height:600px;overflow:auto">')
    parts.append('<table id="tx-table"><thead><tr>'
                 '<th>Data</th><th>Kwota</th><th>Kanał</th><th>Kontrahent</th>'
                 '<th>Tytuł</th><th>Kategoria</th><th>Ryzyko</th><th>Reguły</th>'
                 '</tr></thead><tbody>')

    for tx in sorted(transactions, key=lambda t: t.booking_date):
        amt_class = "amount-in" if tx.direction == "CREDIT" else "amount-out"
        amt_sign = "+" if tx.direction == "CREDIT" else "-"
        risk_badges = " ".join(
            f'<span class="risk-tag badge-danger">{html.escape(t)}</span>'
            for t in tx.risk_tags
        )
        rule_text = "; ".join(
            e.get("rule", "") for e in tx.rule_explains[:3]
        ) if tx.rule_explains else ""

        parts.append(
            f'<tr data-channel="{html.escape(tx.channel)}" '
            f'data-category="{html.escape(tx.category)}">'
            f'<td>{html.escape(tx.booking_date)}</td>'
            f'<td class="{amt_class}">{amt_sign}{float(abs(tx.amount)):,.2f}</td>'
            f'<td>{html.escape(tx.channel)}</td>'
            f'<td>{html.escape(tx.counterparty_raw[:40])}</td>'
            f'<td>{html.escape(tx.title[:60])}</td>'
            f'<td>{html.escape(tx.category)}</td>'
            f'<td>{risk_badges}</td>'
            f'<td style="font-size:.7em">{html.escape(rule_text[:80])}</td>'
            f'</tr>'
        )

    parts.append('</tbody></table></div>')

    # --- Audit Trail ---
    parts.append('<h2>6. Audit Trail</h2>')
    parts.append('<div class="audit">')
    parts.append(f'<p>Data raportu: {now}</p>')
    if audit.get("ocr_used"):
        parts.append('<p>OCR: TAK (brak warstwy tekstowej w PDF)</p>')
    else:
        parts.append('<p>OCR: NIE (warstwa tekstowa obecna)</p>')
    if audit.get("parser_version"):
        parts.append(f'<p>Parser: {html.escape(audit["parser_version"])}</p>')
    if audit.get("rules_version"):
        parts.append(f'<p>Reguły: v{html.escape(audit["rules_version"])}</p>')
    if audit.get("pdf_hash"):
        parts.append(f'<p>Hash PDF: {html.escape(audit["pdf_hash"][:16])}...</p>')

    warnings = audit.get("warnings", [])
    if warnings:
        parts.append('<h3>Ostrzeżenia parsowania</h3><ul>')
        for w in warnings[:20]:
            parts.append(f'<li>{html.escape(str(w))}</li>')
        parts.append('</ul>')
    parts.append('</div>')

    # Footer
    parts.append(f'<div class="footer">AISTATEweb AML Report | Wygenerowano: {now} | '
                 f'Deterministic engine v{audit.get("rules_version", "1.0")}</div>')

    parts.append(_GRAPH_JS)
    parts.append("</body></html>")

    return "\n".join(parts)


def _fmt_amount(val: Any) -> str:
    """Format amount for display."""
    if val is None or val == "—":
        return "—"
    try:
        return f"{float(val):,.2f} PLN"
    except (ValueError, TypeError):
        return str(val)
