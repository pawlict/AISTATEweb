"""LLM-powered narrative AML analysis.

Builds a structured prompt from enriched AML pipeline results and sends it
to Ollama for a written expert analysis in Polish.
"""

from __future__ import annotations

import logging
from collections import Counter, defaultdict
from typing import Any, AsyncGenerator, Dict, List, Optional

log = logging.getLogger("aistate.aml.llm_analysis")


# Human-readable category labels (PL) used in prompts
_CAT_LABELS_PL: Dict[str, str] = {
    "grocery": "Spożywcze",
    "drugstore": "Drogeria",
    "fuel": "Paliwo",
    "hardware": "Budowlane",
    "gastronomy": "Gastronomia",
    "clothing": "Odzież",
    "health": "Zdrowie/Apteka",
    "transport": "Transport",
    "education": "Edukacja",
    "electronics": "Elektronika",
    "home_garden": "Dom i ogród",
    "pets": "Zwierzęta",
    "children": "Dzieci",
    "digital_store": "Sklep cyfrowy",
    "payment_operator": "Operator płatności",
    "p2p_transfer": "Przelew P2P",
    "everyday": "Codzienne",
    # Risk categories
    "gambling": "Gry hazardowe",
    "crypto": "Kryptowaluty",
    "crypto_exchange": "Giełda krypto",
    "stock_exchange": "Giełda",
    "risky": "Ryzykowne",
    "foreign": "Zagraniczne",
    "cash": "Gotówka",
    "own_transfer": "Przelew własny",
}


def _cat_label(raw: str) -> str:
    """Resolve raw category/subcategory to a human-readable PL label."""
    if not raw:
        return "Brak kategorii"
    # Try subcategory part (e.g. "everyday:grocery" → "grocery")
    leaf = raw.split(":")[-1] if ":" in raw else raw
    return _CAT_LABELS_PL.get(leaf, _CAT_LABELS_PL.get(raw, raw))


def build_aml_prompt(
    statement_info: Dict[str, Any],
    transactions: list,
    alerts: Optional[List[Dict[str, Any]]] = None,
    risk_score: float = 0,
    risk_reasons: Optional[list] = None,
    ml_anomalies: Optional[List[Dict[str, Any]]] = None,
    enriched: Optional[Any] = None,
    cross_validation: Optional[Dict[str, Any]] = None,
) -> str:
    """Build comprehensive AML analysis prompt for LLM.

    Args:
        statement_info: Statement metadata (bank, IBAN, balances, etc.)
        transactions: Raw or enriched transaction list
        alerts: Rule-based alerts
        risk_score: Computed risk score 0-100
        risk_reasons: Risk score breakdown
        ml_anomalies: Isolation Forest results
        enriched: EnrichedResult from enrich.py (channels, categories, recurring)
        cross_validation: MT940 vs PDF comparison report

    Returns a prompt string ready to send to Ollama.
    """
    parts: List[str] = []

    # --- System context ---
    parts.append("""# KONTEKST: Analiza AML wyciagu bankowego

Jestes ekspertem ds. przeciwdzialania praniu pieniedzy (AML) i analityki finansowej.
Przygotuj profesjonalna analize wyciagu bankowego na podstawie ponizszych danych.
Dane zostaly automatycznie wyodrebnione z pliku bankowego i wzbogacone o klasyfikacje.

WAZNE:
- Pisz profesjonalnie ale zrozumiale
- Odwoluj sie do konkretnych kwot, dat i kontrahentow
- Wskazuj wzorce zachowan finansowych
- Ocen ryzyko AML na podstawie danych
- Zaproponuj rekomendacje
- Dla kazdego wniosku podaj poziom pewnosci: WYSOKI / SREDNI / NISKI""")

    # --- Statement info ---
    info = statement_info
    parts.append(_build_statement_section(info, transactions))

    # --- Header fields (limits, commissions, blocked amounts) ---
    header_extra = _build_header_extras(info)
    if header_extra:
        parts.append(header_extra)

    # --- Cross-validation (MT940 vs PDF) ---
    if cross_validation:
        parts.append(_build_cross_validation_section(cross_validation))

    # --- Risk score ---
    if risk_score > 0:
        level = "NISKI" if risk_score < 30 else ("SREDNI" if risk_score < 60 else "WYSOKI")
        risk_text = f"## OCENA RYZYKA\n\nRisk score: **{risk_score:.0f}/100** ({level})"
        if risk_reasons:
            risk_text += "\n\nSkladowe ryzyka:"
            for reason in (risk_reasons or [])[:15]:
                if isinstance(reason, dict):
                    risk_text += f"\n- {reason.get('tag', '?')}: +{reason.get('score', 0)} pkt — {reason.get('count', '?')} transakcji"
                else:
                    risk_text += f"\n- {reason}"
        parts.append(risk_text)

    # --- Alerts ---
    if alerts:
        alert_lines = [f"## ALERTY ({len(alerts)})"]
        for alert in alerts[:10]:
            if isinstance(alert, dict):
                alert_lines.append(f"- [{alert.get('severity', '?').upper()}] {alert.get('alert_type', '?')}: {alert.get('explain', '')}")
            else:
                alert_lines.append(f"- {alert}")
        parts.append("\n".join(alert_lines))

    # --- ML anomalies ---
    if ml_anomalies:
        anomaly_count = sum(1 for a in ml_anomalies if a.get("is_anomaly"))
        if anomaly_count > 0:
            anom_lines = [f"## ANOMALIE ML (Isolation Forest): {anomaly_count} wykrytych"]
            top_anomalies = sorted(
                [a for a in ml_anomalies if a.get("is_anomaly")],
                key=lambda x: -x.get("anomaly_score", 0)
            )[:10]
            for a in top_anomalies:
                anom_lines.append(f"- TX {a.get('tx_id', '?')[:8]}... score={a.get('anomaly_score', 0):.2f}")
            parts.append("\n".join(anom_lines))

    # --- Use enriched data if available, otherwise fallback to raw ---
    if enriched:
        parts.append(_build_stats_from_enriched(enriched))
        parts.append(_build_channels_from_enriched(enriched))
        parts.append(_build_categories_from_enriched(enriched))
        parts.append(_build_recurring_from_enriched(enriched))
        parts.append(_build_top_counterparties_from_enriched(enriched))
    else:
        parts.append(_build_transaction_summary(transactions))
        parts.append(_build_category_breakdown(transactions))
        parts.append(_build_channel_breakdown(transactions))
        parts.append(_build_top_counterparties(transactions))

    # --- NEW: Temporal patterns ---
    parts.append(_build_temporal_patterns(transactions))

    # --- NEW: P2P transfers ---
    parts.append(_build_p2p_transfers(transactions))

    # --- NEW: Counterparty profiles from memory ---
    parts.append(_build_counterparty_profiles(transactions))

    # --- Flagged transactions ---
    parts.append(_build_flagged_transactions(transactions))

    # --- Full transaction list (compact, with titles) ---
    parts.append(_build_transaction_table(transactions))

    # --- Task ---
    parts.append(_build_task_section(
        has_cross_validation=cross_validation is not None,
        has_enriched=enriched is not None,
    ))

    return "\n\n".join(p for p in parts if p)


# ============================================================
# Statement section
# ============================================================

def _build_statement_section(info: Dict[str, Any], transactions: list) -> str:
    rows = [
        ("Bank", info.get("bank_name", "?")),
        ("Wlasciciel", info.get("account_holder", "?")),
        ("IBAN", info.get("account_number", "?")),
        ("Okres", f"{info.get('period_from', '?')} — {info.get('period_to', '?')}"),
        ("Saldo poczatkowe", f"{info.get('opening_balance', '?')} {info.get('currency', 'PLN')}"),
        ("Saldo koncowe", f"{info.get('closing_balance', '?')} {info.get('currency', 'PLN')}"),
        ("Liczba transakcji", str(len(transactions))),
    ]
    lines = ["## DANE WYCIAGU\n", "| Pole | Wartosc |", "|------|---------|"]
    for label, val in rows:
        lines.append(f"| {label} | {val} |")
    return "\n".join(lines)


def _build_header_extras(info: Dict[str, Any]) -> str:
    """Build section for additional header fields (limits, commissions, etc.)."""
    extras = []
    field_map = [
        ("previous_closing_balance", "Saldo konc. poprz. wyciagu"),
        ("declared_credits_sum", "Suma uznan (kwota)"),
        ("declared_credits_count", "Suma uznan (liczba)"),
        ("declared_debits_sum", "Suma obciazen (kwota)"),
        ("declared_debits_count", "Suma obciazen (liczba)"),
        ("debt_limit", "Limit zadluzenia"),
        ("overdue_commission", "Kwota prowizji zaleglej"),
        ("blocked_amount", "Kwota zablokowana"),
        ("available_balance", "Saldo dostepne"),
    ]
    for key, label in field_map:
        val = info.get(key)
        if val is not None and val != "":
            extras.append(f"| {label} | {val} |")

    if not extras:
        return ""

    lines = ["## DODATKOWE POLA NAGLOWKA\n", "| Pole | Wartosc |", "|------|---------|"]
    lines.extend(extras)
    return "\n".join(lines)


# ============================================================
# Cross-validation section
# ============================================================

def _build_cross_validation_section(cv: Dict[str, Any]) -> str:
    """Build MT940 vs PDF cross-validation section."""
    lines = ["## WALIDACJA KRZYZOWA (MT940 vs PDF)\n"]

    mt940_count = cv.get("mt940_tx_count", 0)
    pdf_count = cv.get("pdf_tx_count", 0)
    match_rate = cv.get("match_rate", 0)

    lines.append(f"- Transakcje MT940: {mt940_count}")
    lines.append(f"- Transakcje PDF: {pdf_count}")
    lines.append(f"- Dopasowane: {len(cv.get('matches', []))} ({match_rate:.1f}%)")

    # Balance checks
    balance_check = cv.get("balance_check", {})
    if balance_check:
        lines.append("\n### Sprawdzenie sald")
        for field_name, check in balance_check.items():
            status = "OK" if check.get("match") else "ROZBIEZNOSC"
            lines.append(f"- {field_name}: MT940={check.get('mt940', '?')}, PDF={check.get('pdf', '?')} — **{status}**")

    # Unmatched
    mt940_only = cv.get("mt940_only", [])
    pdf_only = cv.get("pdf_only", [])
    if mt940_only:
        lines.append(f"\n### Transakcje tylko w MT940 ({len(mt940_only)})")
        for tx in mt940_only[:5]:
            lines.append(f"- {tx.get('date', '?')} {tx.get('amount', 0):+,.2f} {tx.get('counterparty', '?')[:40]}")
    if pdf_only:
        lines.append(f"\n### Transakcje tylko w PDF ({len(pdf_only)})")
        for tx in pdf_only[:5]:
            lines.append(f"- {tx.get('date', '?')} {tx.get('amount', 0):+,.2f} {tx.get('counterparty', '?')[:40]}")

    return "\n".join(lines)


# ============================================================
# Enriched data sections
# ============================================================

def _build_stats_from_enriched(enriched) -> str:
    s = enriched.stats
    return f"""## STATYSTYKI

| Metryka | Wartosc |
|---------|---------|
| Laczne wplywy | {s['total_credits']:,.2f} PLN ({s['credit_count']} transakcji) |
| Laczne wydatki | {s['total_debits']:,.2f} PLN ({s['debit_count']} transakcji) |
| Bilans netto | {s['net_flow']:+,.2f} PLN |
| Srednia transakcja | {s['avg_transaction']:,.2f} PLN |
| Najwieksza transakcja | {s['max_transaction']:,.2f} PLN |"""


def _build_channels_from_enriched(enriched) -> str:
    lines = ["## KANALY TRANSAKCJI\n",
             "| Kanal | Liczba | Kwota |",
             "|-------|--------|-------|"]
    for ch, info in enriched.channel_summary.items():
        lines.append(f"| {info['label']} | {info['count']} | {info['total']:,.2f} PLN |")
    return "\n".join(lines)


def _build_categories_from_enriched(enriched) -> str:
    lines = ["## KATEGORIE TRANSAKCJI\n",
             "| Kategoria | Liczba | Kwota |",
             "|-----------|--------|-------|"]
    for cat, info in enriched.category_summary.items():
        label = _cat_label(cat) if _cat_label(cat) != cat else info.get("label", cat)
        lines.append(f"| {label} | {info['count']} | {info['total']:,.2f} PLN |")
    return "\n".join(lines)


def _build_recurring_from_enriched(enriched) -> str:
    recurring = enriched.recurring
    if not recurring:
        return ""
    lines = ["## TRANSAKCJE CYKLICZNE / POWTARZALNE\n",
             "| Kontrahent | Powtorzen | Srednia kwota | Lacznie |",
             "|------------|-----------|---------------|---------|"]
    for r in recurring[:15]:
        lines.append(f"| {r.counterparty[:40]} | {r.count} | {r.avg_amount:,.2f} PLN | {r.total_amount:,.2f} PLN |")
    return "\n".join(lines)


def _build_top_counterparties_from_enriched(enriched) -> str:
    lines = ["## TOP KONTRAHENCI\n",
             "| Kontrahent | Kwota | Transakcje |",
             "|------------|-------|-----------|"]
    for cp in enriched.top_counterparties[:15]:
        lines.append(f"| {cp['name'][:45]} | {cp['total']:,.2f} PLN | {cp['count']} |")
    return "\n".join(lines)


# ============================================================
# Transaction table (compact, all transactions)
# ============================================================

def _build_transaction_table(transactions: list, limit: int = 50) -> str:
    """Compact table of all transactions for LLM context — includes title and location."""
    if not transactions:
        return ""

    lines = [f"## LISTA TRANSAKCJI ({len(transactions)} szt, pokazano max {limit})\n",
             "| # | Data | Kwota | Kanal | Kategoria | Kontrahent | Tytul | Lokalizacja |",
             "|---|------|-------|-------|-----------|------------|-------|-------------|"]

    for i, tx in enumerate(transactions[:limit]):
        date = _get(tx, "date") or _get(tx, "booking_date") or "?"
        amt = float(_get(tx, "amount") or 0)
        ch = _get(tx, "channel") or ""
        raw_cat = _get(tx, "subcategory") or _get(tx, "category") or ""
        cat = _cat_label(raw_cat)
        cp = _get(tx, "counterparty") or _get(tx, "counterparty_raw") or "?"
        title = (_get(tx, "title") or "")[:50]
        location = _detect_location(tx) or ""
        lines.append(
            f"| {i+1} | {date} | {amt:+,.2f} | {ch[:12]} | {cat[:18]} | {cp[:35]} | {title} | {location} |"
        )

    if len(transactions) > limit:
        lines.append(f"\n*...i jeszcze {len(transactions) - limit} transakcji niepokazanych.*")

    return "\n".join(lines)


# ============================================================
# Fallback sections (when enriched data not available)
# ============================================================

def _build_transaction_summary(transactions: list) -> str:
    total_credit = 0.0
    total_debit = 0.0
    max_single = 0.0
    for tx in transactions:
        amt = float(abs(_get(tx, "amount") or 0))
        direction = _get(tx, "direction") or ""
        if direction == "CREDIT":
            total_credit += amt
        else:
            total_debit += amt
        if amt > max_single:
            max_single = amt
    avg = (total_credit + total_debit) / max(len(transactions), 1)
    return f"""## STATYSTYKI

| Metryka | Wartosc |
|---------|---------|
| Laczne wplywy | {total_credit:,.2f} PLN |
| Laczne wydatki | {total_debit:,.2f} PLN |
| Bilans | {total_credit - total_debit:,.2f} PLN |
| Srednia transakcja | {avg:,.2f} PLN |
| Najwieksza transakcja | {max_single:,.2f} PLN |"""


def _build_category_breakdown(transactions: list) -> str:
    cats: Dict[str, float] = defaultdict(float)
    cat_counts: Dict[str, int] = defaultdict(int)
    for tx in transactions:
        raw = _get(tx, "subcategory") or _get(tx, "category") or "brak_kategorii"
        label = _cat_label(raw)
        amt = float(abs(_get(tx, "amount") or 0))
        cats[label] += amt
        cat_counts[label] += 1
    sorted_cats = sorted(cats.items(), key=lambda x: -x[1])[:12]
    lines = ["## KATEGORIE TRANSAKCJI\n",
             "| Kategoria | Kwota | Liczba |",
             "|-----------|-------|--------|"]
    for cat, total in sorted_cats:
        lines.append(f"| {cat} | {total:,.2f} PLN | {cat_counts[cat]} |")
    return "\n".join(lines)


def _build_channel_breakdown(transactions: list) -> str:
    ch_counts: Counter = Counter()
    ch_amounts: Dict[str, float] = defaultdict(float)
    for tx in transactions:
        ch = _get(tx, "channel") or "OTHER"
        amt = float(abs(_get(tx, "amount") or 0))
        ch_counts[ch] += 1
        ch_amounts[ch] += amt
    lines = ["## KANALY TRANSAKCJI\n",
             "| Kanal | Liczba | Kwota |",
             "|-------|--------|-------|"]
    for ch, cnt in ch_counts.most_common():
        lines.append(f"| {ch} | {cnt} | {ch_amounts[ch]:,.2f} PLN |")
    return "\n".join(lines)


def _build_top_counterparties(transactions: list, limit: int = 15) -> str:
    cp_totals: Dict[str, float] = defaultdict(float)
    cp_counts: Dict[str, int] = defaultdict(int)
    for tx in transactions:
        name = (_get(tx, "counterparty_raw") or _get(tx, "counterparty") or "Nieznany")[:50]
        amt = float(abs(_get(tx, "amount") or 0))
        cp_totals[name] += amt
        cp_counts[name] += 1
    sorted_cps = sorted(cp_totals.items(), key=lambda x: -x[1])[:limit]
    lines = ["## TOP KONTRAHENCI\n",
             "| Kontrahent | Kwota | Transakcje |",
             "|------------|-------|-----------|"]
    for name, total in sorted_cps:
        lines.append(f"| {name} | {total:,.2f} PLN | {cp_counts[name]} |")
    return "\n".join(lines)


def _build_flagged_transactions(transactions: list, limit: int = 20) -> str:
    flagged = []
    for tx in transactions:
        tags = _get(tx, "risk_tags") or []
        if isinstance(tags, str):
            import json as _json
            try:
                tags = _json.loads(tags)
            except Exception:
                tags = []
        if tags:
            flagged.append(tx)
    if not flagged:
        return ""
    lines = [f"## TRANSAKCJE Z FLAGAMI RYZYKA ({len(flagged)})\n",
             "| Data | Kontrahent | Tytul | Kwota | Kanal | Kategoria | Tagi |",
             "|------|-----------|-------|-------|-------|-----------|------|"]
    for tx in flagged[:limit]:
        date = _get(tx, "date") or _get(tx, "booking_date") or "?"
        cp = (_get(tx, "counterparty_raw") or _get(tx, "counterparty") or "?")[:30]
        title = (_get(tx, "title") or "")[:35]
        amt = float(abs(_get(tx, "amount") or 0))
        direction = _get(tx, "direction") or ""
        ch = _get(tx, "channel") or ""
        raw_cat = _get(tx, "subcategory") or _get(tx, "category") or ""
        cat = _cat_label(raw_cat)
        tags = _get(tx, "risk_tags") or []
        tags_str = ", ".join(tags) if isinstance(tags, list) else str(tags)
        sign = "-" if direction == "DEBIT" else "+"
        lines.append(f"| {date} | {cp} | {title} | {sign}{amt:,.2f} | {ch} | {cat[:15]} | {tags_str} |")
    return "\n".join(lines)


# ============================================================
# Location detection helper
# ============================================================

def _detect_location(tx) -> Optional[str]:
    """Try to extract location from a transaction using merchant DB."""
    try:
        from .merchants import detect_merchant_location
        cp = _get(tx, "counterparty_raw") or _get(tx, "counterparty") or ""
        title = _get(tx, "title") or ""
        return detect_merchant_location(cp, title)
    except Exception:
        return None


# ============================================================
# Temporal patterns section
# ============================================================

def _build_temporal_patterns(transactions: list) -> str:
    """Analyze day-of-week and time-of-month spending patterns."""
    if not transactions:
        return ""

    from datetime import datetime

    # Day-of-week
    _DOW_PL = ["Poniedziałek", "Wtorek", "Środa", "Czwartek", "Piątek", "Sobota", "Niedziela"]
    dow_amounts: Dict[int, float] = defaultdict(float)
    dow_counts: Dict[int, int] = defaultdict(int)

    # Time-of-month (1-10, 11-20, 21-31)
    period_amounts: Dict[str, float] = defaultdict(float)
    period_counts: Dict[str, int] = defaultdict(int)

    parsed = 0
    for tx in transactions:
        date_str = _get(tx, "booking_date") or _get(tx, "date") or ""
        if not date_str:
            continue
        try:
            dt = datetime.fromisoformat(date_str.replace("Z", "+00:00") if "T" in date_str else date_str)
        except (ValueError, TypeError):
            try:
                dt = datetime.strptime(date_str[:10], "%Y-%m-%d")
            except (ValueError, TypeError):
                continue

        amt = float(abs(_get(tx, "amount") or 0))
        dow = dt.weekday()
        dow_amounts[dow] += amt
        dow_counts[dow] += 1

        day = dt.day
        if day <= 10:
            period = "1-10"
        elif day <= 20:
            period = "11-20"
        else:
            period = "21-31"
        period_amounts[period] += amt
        period_counts[period] += 1
        parsed += 1

    if parsed < 5:
        return ""

    lines = ["## WZORCE CZASOWE\n"]

    # Day of week table
    lines.append("### Aktywność wg dnia tygodnia\n")
    lines.append("| Dzień | Transakcje | Kwota | Śr. kwota |")
    lines.append("|-------|-----------|-------|-----------|")
    for dow in range(7):
        cnt = dow_counts.get(dow, 0)
        total = dow_amounts.get(dow, 0)
        avg = total / cnt if cnt > 0 else 0
        marker = " ⬆" if cnt > 0 and cnt == max(dow_counts.values()) else ""
        lines.append(f"| {_DOW_PL[dow]} | {cnt}{marker} | {total:,.2f} PLN | {avg:,.2f} PLN |")

    # Time of month
    lines.append("\n### Aktywność wg okresu miesiąca\n")
    lines.append("| Okres | Transakcje | Kwota |")
    lines.append("|-------|-----------|-------|")
    for period in ["1-10", "11-20", "21-31"]:
        cnt = period_counts.get(period, 0)
        total = period_amounts.get(period, 0)
        lines.append(f"| Dni {period} | {cnt} | {total:,.2f} PLN |")

    # Highlight weekend vs weekday
    weekday_cnt = sum(dow_counts.get(d, 0) for d in range(5))
    weekend_cnt = sum(dow_counts.get(d, 0) for d in (5, 6))
    weekday_amt = sum(dow_amounts.get(d, 0) for d in range(5))
    weekend_amt = sum(dow_amounts.get(d, 0) for d in (5, 6))
    if weekday_cnt > 0 and weekend_cnt > 0:
        lines.append(f"\n- Dni robocze: {weekday_cnt} tx ({weekday_amt:,.2f} PLN)")
        lines.append(f"- Weekend: {weekend_cnt} tx ({weekend_amt:,.2f} PLN)")
        if weekend_cnt > 0:
            ratio = weekend_amt / weekday_amt if weekday_amt > 0 else 0
            if ratio > 0.5:
                lines.append("- ⚠ Znaczna aktywność weekendowa")

    return "\n".join(lines)


# ============================================================
# P2P Transfers section
# ============================================================

def _build_p2p_transfers(transactions: list) -> str:
    """Dedicated P2P transfer listing — BLIK P2P, transfers to phone numbers, etc."""
    if not transactions:
        return ""

    import re as _re

    p2p_patterns = [
        _re.compile(r"blik\s*p2p", _re.I),
        _re.compile(r"p\.blik", _re.I),
        _re.compile(r"przelew\s*na\s*telefon", _re.I),
        _re.compile(r"blik.*(?:na\s*telefon|p2p|prywat)", _re.I),
        _re.compile(r"transfer.*(?:na\s*numer|na\s*tel)", _re.I),
        _re.compile(r"przelew\s*p2p", _re.I),
    ]

    p2p_list = []
    for tx in transactions:
        cat = (_get(tx, "subcategory") or _get(tx, "category") or "").lower()
        title = (_get(tx, "title") or "").lower()
        cp = (_get(tx, "counterparty_raw") or _get(tx, "counterparty") or "").lower()
        ch = (_get(tx, "channel") or "").lower()
        search_text = f"{title} {cp} {ch} {cat}"

        is_p2p = "p2p" in cat or "p2p_transfer" in cat
        if not is_p2p:
            for pat in p2p_patterns:
                if pat.search(search_text):
                    is_p2p = True
                    break

        if is_p2p:
            p2p_list.append(tx)

    if not p2p_list:
        return ""

    total_out = sum(float(abs(_get(tx, "amount") or 0)) for tx in p2p_list if (_get(tx, "direction") or "") == "DEBIT")
    total_in = sum(float(abs(_get(tx, "amount") or 0)) for tx in p2p_list if (_get(tx, "direction") or "") == "CREDIT")

    lines = [f"## PRZELEWY P2P ({len(p2p_list)} szt)\n"]
    lines.append(f"- Wysłane: {total_out:,.2f} PLN")
    lines.append(f"- Otrzymane: {total_in:,.2f} PLN")
    lines.append(f"- Bilans P2P: {total_in - total_out:+,.2f} PLN\n")

    # Counterparty breakdown
    cp_summary: Dict[str, Dict[str, Any]] = {}
    for tx in p2p_list:
        cp = (_get(tx, "counterparty_raw") or _get(tx, "counterparty") or "Nieznany")[:50]
        if cp not in cp_summary:
            cp_summary[cp] = {"count": 0, "total": 0.0, "directions": []}
        cp_summary[cp]["count"] += 1
        amt = float(_get(tx, "amount") or 0)
        cp_summary[cp]["total"] += amt
        direction = _get(tx, "direction") or ""
        cp_summary[cp]["directions"].append(direction)

    lines.append("| Odbiorca/Nadawca | Transakcje | Kwota netto | Kierunek |")
    lines.append("|-----------------|-----------|-------------|----------|")
    sorted_cps = sorted(cp_summary.items(), key=lambda x: -abs(x[1]["total"]))[:15]
    for cp, info in sorted_cps:
        dirs = info["directions"]
        if all(d == "DEBIT" for d in dirs):
            direction = "→ wychodzące"
        elif all(d == "CREDIT" for d in dirs):
            direction = "← przychodzące"
        else:
            direction = "↔ obustronne"
        lines.append(f"| {cp[:40]} | {info['count']} | {info['total']:+,.2f} PLN | {direction} |")

    return "\n".join(lines)


# ============================================================
# Counterparty memory profiles section
# ============================================================

def _build_counterparty_profiles(transactions: list) -> str:
    """Include counterparty memory profiles (whitelist/blacklist/notes)."""
    try:
        from .memory import search_counterparties
    except ImportError:
        return ""

    # Get non-neutral counterparties
    profiles = []
    for label in ("whitelist", "blacklist"):
        try:
            cps = search_counterparties(label=label, limit=100)
            for cp in cps:
                profiles.append(cp)
        except Exception:
            pass

    if not profiles:
        return ""

    # Also collect counterparties with notes
    try:
        noted = search_counterparties(limit=200)
        for cp in noted:
            note = cp.get("note", "")
            if note and cp.get("label", "") == "neutral" and cp not in profiles:
                profiles.append(cp)
    except Exception:
        pass

    if not profiles:
        return ""

    lines = [f"## PROFILE KONTRAHENTÓW Z PAMIĘCI ({len(profiles)})\n"]
    lines.append("| Kontrahent | Status | Notatka | Widziany | Kwota łączna |")
    lines.append("|------------|--------|---------|----------|--------------|")

    label_pl = {"whitelist": "✅ Zaufany", "blacklist": "🚫 Czarna lista", "neutral": "📝 Z notatką"}

    for cp in profiles[:25]:
        name = (cp.get("canonical_name") or "?")[:35]
        label = cp.get("label", "neutral")
        status = label_pl.get(label, label)
        note = (cp.get("note") or "")[:40]
        times = cp.get("times_seen", 0)
        total = float(cp.get("total_amount", 0))
        lines.append(f"| {name} | {status} | {note} | {times}x | {total:,.2f} PLN |")

    return "\n".join(lines)


# ============================================================
# Task section
# ============================================================

def _build_task_section(has_cross_validation: bool = False, has_enriched: bool = False) -> str:
    sections = """## ZADANIE

Na podstawie powyzszych danych napisz profesjonalny raport AML zawierajacy:

### 1. Podsumowanie
2-3 zdania: kto, jaki bank, jaki okres, ogolna ocena ryzyka.

### 2. Profil finansowy
- Wplywy vs wydatki — czy wlasciciel zyje w ramach wplywow?
- Glowne zrodla dochodow i ich regularnosc
- Glowne kategorie wydatkow (uzyj danych z sekcji KATEGORIE)
- Zobowiazania cykliczne (uzyj danych z sekcji TRANSAKCJE CYKLICZNE)

### 3. Analiza kanalow platnosci
- Rozklad platnosci wg kanalow (karta, BLIK, przelew, gotowka)
- Czy widac nietypowe preferencje kanalowe?
- Wyplaty gotowkowe — kwoty, czestotliwosc, lokalizacje

### 4. Analiza ryzyka AML
- Strukturyzowanie (smurfing) — czy widac rozbijanie duzych kwot na mniejsze?
- Transakcje zagraniczne — kontrahenci, kwoty, cel
- Przelewy P2P i na telefon — uzyj sekcji PRZELEWY P2P: regularne transfery, kwoty, odbiorcy
- Przelewy wlasne — miedzy kontami wlasciciela, ewentualne lokaty
- Duze jednorazowe transakcje vs wzorzec codziennych wydatkow
- Kontrahenci z czarnej/bialej listy — uzyj sekcji PROFILE KONTRAHENTOW

### 5. Podejrzane transakcje
Wskaz konkretne transakcje (z datami, kwotami i TYTULAMI) ktore budza watpliwosci i dlaczego.
Uzyj tytulu transakcji jako dodatkowego kontekstu.

### 6. Wzorce behawioralne
- Uzyj sekcji WZORCE CZASOWE — porownaj dni tygodnia, pory miesiaca
- Czy zachowania finansowe sa przewidywalne i stabilne?
- Czy widac impulsy lub anomalie?
- Lokalizacje — czy transakcje sa skoncentrowane geograficznie czy rozproszone?

### 7. Rekomendacje
Konkretne zalecenia — co nalezy dalej zweryfikowac i jakie dzialania podjac."""

    if has_cross_validation:
        sections += """

### 8. Ocena walidacji krzyzowej
Odwolaj sie do wynikow porownania MT940 vs PDF. Czy dane sa spojne?
Jesli sa rozbieznosci — co moga oznaczac?"""

    sections += """

**WAZNE**:
- Zachowaj ostroznosc interpretacyjna — nie nadinterpretuj
- Dla kazdego wniosku podaj jawny **poziom pewnosci**: WYSOKI / SREDNI / NISKI
- Jesli dane sa niewystarczajace do wniosku, napisz to wprost
- Pisz po polsku, profesjonalnie ale zrozumiale
- Uzywaj konkretnych danych z wyciagu — nie wymyslaj danych ktorych nie ma"""

    return sections


# ============================================================
# LLM execution
# ============================================================

async def run_llm_analysis(
    prompt: str,
    model: str = "",
    system_prompt: Optional[str] = None,
) -> str:
    """Send the AML prompt to Ollama and get narrative analysis.

    Returns the LLM's response text.
    """
    from ..ollama_client import OllamaClient, deep_analyze

    client = OllamaClient()

    # Check if Ollama is available
    status = await client.status()
    if status.status != "online":
        raise RuntimeError("Ollama nie jest dostepny. Uruchom Ollama aby uzyskac analize LLM.")

    # Pick model: use provided or find first available
    if not model:
        models = status.models or []
        # Prefer larger models for analysis
        preferred = ["llama3.1", "mistral", "qwen", "gemma"]
        for pref in preferred:
            for m in models:
                if pref in m.lower():
                    model = m
                    break
            if model:
                break
        if not model and models:
            model = models[0]
        if not model:
            raise RuntimeError("Brak modeli LLM w Ollama. Pobierz model: ollama pull llama3.1")

    log.info("Running LLM AML analysis with model: %s", model)

    system = system_prompt or (
        "Jestes ekspertem ds. AML (Anti-Money Laundering) i analityki finansowej. "
        "Piszesz profesjonalne raporty analityczne po polsku. "
        "Bazujesz wylacznie na dostarczonych danych — nie wymyslasz informacji. "
        "Uzywasz konkretnych kwot, dat i nazw kontrahentow w swoich analizach."
    )

    result = await deep_analyze(
        client,
        prompt,
        model=model,
        system=system,
        options={"temperature": 0.3, "num_ctx": 8192},
    )

    return result


async def stream_llm_analysis(
    prompt: str,
    model: str = "",
    system_prompt: Optional[str] = None,
) -> AsyncGenerator[str, None]:
    """Stream AML analysis from Ollama — yields text chunks as they arrive."""
    from ..ollama_client import OllamaClient, stream_analyze

    client = OllamaClient()

    status = await client.status()
    if status.status != "online":
        raise RuntimeError("Ollama nie jest dostepny. Uruchom Ollama aby uzyskac analize LLM.")

    if not model:
        models = status.models or []
        preferred = ["llama3.1", "mistral", "qwen", "gemma"]
        for pref in preferred:
            for m in models:
                if pref in m.lower():
                    model = m
                    break
            if model:
                break
        if not model and models:
            model = models[0]
        if not model:
            raise RuntimeError("Brak modeli LLM w Ollama. Pobierz model: ollama pull llama3.1")

    log.info("Streaming LLM AML analysis with model: %s", model)

    system = system_prompt or (
        "Jestes ekspertem ds. AML (Anti-Money Laundering) i analityki finansowej. "
        "Piszesz profesjonalne raporty analityczne po polsku. "
        "Bazujesz wylacznie na dostarczonych danych — nie wymyslasz informacji. "
        "Uzywasz konkretnych kwot, dat i nazw kontrahentow w swoich analizach."
    )

    async for chunk in stream_analyze(
        client, prompt, model=model, system=system,
        options={"temperature": 0.3, "num_ctx": 8192},
    ):
        yield chunk


# ============================================================
# Helper
# ============================================================

def _get(obj: Any, key: str) -> Any:
    """Get attribute or dict key, handling both objects and dicts."""
    if hasattr(obj, key):
        return getattr(obj, key)
    if isinstance(obj, dict):
        return obj.get(key)
    return None
