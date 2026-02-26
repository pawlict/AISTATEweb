"""LLM-powered narrative AML analysis.

Builds a structured prompt from enriched AML pipeline results and sends it
to Ollama for a written expert analysis in Polish.
"""

from __future__ import annotations

import logging
import re as _re
from collections import Counter, defaultdict
from datetime import datetime, timedelta
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


# ============================================================
# Keywords for pre-analysis detection
# ============================================================

_LOAN_KEYWORDS = [
    "kredyt", "rata", "pożyczka", "pozyczka", "bank", "leasing",
    "splata", "spłata", "hipoteczny", "ratalny", "rrso",
    "prowizja", "odsetki", "ubezpieczenie kredytu",
    "santander", "ing bank", "mbank", "pko", "bnp paribas",
    "alior", "millennium", "getin", "nest bank", "credit agricole",
]

_ATM_KEYWORDS = [
    "bankomat", "atm", "wyplata gotowk", "wypłata gotówk",
    "wplata gotowk", "wpłata gotówk", "wplata wlasna", "wpłata własna",
    "cash", "gotówka", "gotowka",
]


def build_aml_prompt(
    statement_info: Dict[str, Any],
    transactions: list,
    alerts: Optional[List[Dict[str, Any]]] = None,
    risk_score: float = 0,
    risk_reasons: Optional[list] = None,
    ml_anomalies: Optional[List[Dict[str, Any]]] = None,
    enriched: Optional[Any] = None,
    cross_validation: Optional[Dict[str, Any]] = None,
    user_prompt: str = "",
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
        user_prompt: Optional user question or instruction

    Returns a prompt string ready to send to Ollama.
    """
    parts: List[str] = []

    # --- System context (with proper Polish diacritics) ---
    parts.append("""# KONTEKST: Analiza AML wyciągu bankowego

Jesteś ekspertem ds. przeciwdziałania praniu pieniędzy (AML) i analityki finansowej.
Przygotuj profesjonalny raport z analizy rachunku bankowego na podstawie poniższych danych.
Dane zostały automatycznie wyodrębnione z plików bankowych i wzbogacone o klasyfikację.

WAŻNE:
- Pisz profesjonalnie ale zrozumiale
- Odwołuj się do konkretnych kwot, dat i kontrahentów
- Wskazuj wzorce zachowań finansowych
- Oceń ryzyko AML na podstawie danych
- Zaproponuj rekomendacje
- Dla każdego wniosku podaj poziom pewności: WYSOKI / ŚREDNI / NISKI""")

    # --- Task section FIRST (so LLM knows what to look for) ---
    parts.append(_build_task_section(
        has_cross_validation=cross_validation is not None,
        has_enriched=enriched is not None,
    ))

    # --- User prompt (if provided) ---
    if user_prompt and user_prompt.strip():
        parts.append(f"""## PYTANIE / INSTRUKCJA UŻYTKOWNIKA

{user_prompt.strip()}

WAŻNE: Uwzględnij powyższe pytanie/instrukcję w swojej analizie. Jeśli użytkownik pyta o konkretny aspekt, poświęć mu szczególną uwagę w raporcie.""")

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
        level = "NISKI" if risk_score < 30 else ("ŚREDNI" if risk_score < 60 else "WYSOKI")
        risk_text = f"## OCENA RYZYKA\n\nRisk score: **{risk_score:.0f}/100** ({level})"
        if risk_reasons:
            risk_text += "\n\nSkładowe ryzyka:"
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

    # --- NEW: Monthly income/expense breakdown ---
    parts.append(_build_monthly_breakdown(transactions))

    # --- NEW: Loan/installment detection ---
    parts.append(_build_loan_detection(transactions))

    # --- NEW: ATM patterns ---
    parts.append(_build_atm_patterns(transactions))

    # --- NEW: Geographic analysis ---
    parts.append(_build_geographic_analysis(transactions))

    # --- Temporal patterns ---
    parts.append(_build_temporal_patterns(transactions))

    # --- P2P transfers ---
    parts.append(_build_p2p_transfers(transactions))

    # --- Counterparty profiles from memory ---
    parts.append(_build_counterparty_profiles(transactions))

    # --- Flagged transactions ---
    parts.append(_build_flagged_transactions(transactions))

    # --- Transaction table: smart aggregation for large datasets ---
    parts.append(_build_transaction_table(transactions))

    return "\n\n".join(p for p in parts if p)


# ============================================================
# Statement section
# ============================================================

def _build_statement_section(info: Dict[str, Any], transactions: list) -> str:
    rows = [
        ("Bank", info.get("bank_name", "?")),
        ("Właściciel", info.get("account_holder", "?")),
        ("IBAN", info.get("account_number", "?")),
        ("Okres", f"{info.get('period_from', '?')} — {info.get('period_to', '?')}"),
        ("Saldo początkowe", f"{info.get('opening_balance', '?')} {info.get('currency', 'PLN')}"),
        ("Saldo końcowe", f"{info.get('closing_balance', '?')} {info.get('currency', 'PLN')}"),
        ("Liczba transakcji", str(len(transactions))),
    ]
    lines = ["## DANE WYCIĄGU\n", "| Pole | Wartość |", "|------|---------|"]
    for label, val in rows:
        lines.append(f"| {label} | {val} |")
    return "\n".join(lines)


def _build_header_extras(info: Dict[str, Any]) -> str:
    """Build section for additional header fields (limits, commissions, etc.)."""
    extras = []
    field_map = [
        ("previous_closing_balance", "Saldo końcowe poprzedniego wyciągu"),
        ("declared_credits_sum", "Suma uznań (kwota)"),
        ("declared_credits_count", "Suma uznań (liczba)"),
        ("declared_debits_sum", "Suma obciążeń (kwota)"),
        ("declared_debits_count", "Suma obciążeń (liczba)"),
        ("debt_limit", "Limit zadłużenia"),
        ("overdue_commission", "Kwota prowizji zaległej"),
        ("blocked_amount", "Kwota zablokowana"),
        ("available_balance", "Saldo dostępne"),
    ]
    for key, label in field_map:
        val = info.get(key)
        if val is not None and val != "":
            extras.append(f"| {label} | {val} |")

    if not extras:
        return ""

    lines = ["## DODATKOWE POLA NAGŁÓWKA\n", "| Pole | Wartość |", "|------|---------|"]
    lines.extend(extras)
    return "\n".join(lines)


# ============================================================
# Cross-validation section
# ============================================================

def _build_cross_validation_section(cv: Dict[str, Any]) -> str:
    """Build MT940 vs PDF cross-validation section."""
    lines = ["## WALIDACJA KRZYŻOWA (MT940 vs PDF)\n"]

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
            status = "OK" if check.get("match") else "ROZBIEŻNOŚĆ"
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

| Metryka | Wartość |
|---------|---------|
| Łączne wpływy | {s['total_credits']:,.2f} PLN ({s['credit_count']} transakcji) |
| Łączne wydatki | {s['total_debits']:,.2f} PLN ({s['debit_count']} transakcji) |
| Bilans netto | {s['net_flow']:+,.2f} PLN |
| Średnia transakcja | {s['avg_transaction']:,.2f} PLN |
| Największa transakcja | {s['max_transaction']:,.2f} PLN |"""


def _build_channels_from_enriched(enriched) -> str:
    lines = ["## KANAŁY TRANSAKCJI\n",
             "| Kanał | Liczba | Kwota |",
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
             "| Kontrahent | Powtórzeń | Średnia kwota | Łącznie |",
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
# NEW: Monthly income/expense breakdown
# ============================================================

def _build_monthly_breakdown(transactions: list) -> str:
    """Monthly income vs expenses breakdown with totals."""
    if not transactions:
        return ""

    monthly_credit: Dict[str, float] = defaultdict(float)
    monthly_debit: Dict[str, float] = defaultdict(float)
    monthly_credit_cnt: Dict[str, int] = defaultdict(int)
    monthly_debit_cnt: Dict[str, int] = defaultdict(int)

    for tx in transactions:
        date_str = _get(tx, "booking_date") or _get(tx, "date") or ""
        if not date_str or len(date_str) < 7:
            continue
        month = date_str[:7]  # YYYY-MM
        amt = float(abs(_get(tx, "amount") or 0))
        direction = _get(tx, "direction") or ""
        if direction == "CREDIT":
            monthly_credit[month] += amt
            monthly_credit_cnt[month] += 1
        else:
            monthly_debit[month] += amt
            monthly_debit_cnt[month] += 1

    if not monthly_credit and not monthly_debit:
        return ""

    months = sorted(set(list(monthly_credit.keys()) + list(monthly_debit.keys())))

    lines = ["## MIESIĘCZNE ZESTAWIENIE WPŁYWÓW I WYDATKÓW\n"]
    lines.append("| Miesiąc | Wpływy | Ilość | Wydatki | Ilość | Bilans |")
    lines.append("|---------|--------|-------|---------|-------|--------|")

    total_credit = 0.0
    total_debit = 0.0
    total_credit_cnt = 0
    total_debit_cnt = 0

    for m in months:
        cr = monthly_credit.get(m, 0)
        db = monthly_debit.get(m, 0)
        cr_cnt = monthly_credit_cnt.get(m, 0)
        db_cnt = monthly_debit_cnt.get(m, 0)
        balance = cr - db
        total_credit += cr
        total_debit += db
        total_credit_cnt += cr_cnt
        total_debit_cnt += db_cnt
        sign = "+" if balance >= 0 else ""
        lines.append(f"| {m} | {cr:,.2f} PLN | {cr_cnt} | {db:,.2f} PLN | {db_cnt} | {sign}{balance:,.2f} PLN |")

    # Totals row
    total_balance = total_credit - total_debit
    sign = "+" if total_balance >= 0 else ""
    lines.append(f"| **SUMA** | **{total_credit:,.2f} PLN** | **{total_credit_cnt}** | **{total_debit:,.2f} PLN** | **{total_debit_cnt}** | **{sign}{total_balance:,.2f} PLN** |")

    # Average monthly
    if len(months) > 0:
        avg_cr = total_credit / len(months)
        avg_db = total_debit / len(months)
        lines.append(f"\n- Średnie miesięczne wpływy: {avg_cr:,.2f} PLN")
        lines.append(f"- Średnie miesięczne wydatki: {avg_db:,.2f} PLN")
        if avg_cr > 0:
            expense_ratio = avg_db / avg_cr * 100
            lines.append(f"- Wskaźnik wydatków do wpływów: {expense_ratio:.1f}%")
            if expense_ratio > 100:
                lines.append("- ⚠ Wydatki przekraczają wpływy — możliwe problemy finansowe")
            elif expense_ratio > 90:
                lines.append("- ⚠ Wydatki bliskie wpływom — niska zdolność oszczędzania")

    return "\n".join(lines)


# ============================================================
# NEW: Loan/installment detection
# ============================================================

def _build_loan_detection(transactions: list) -> str:
    """Detect recurring loan/credit payments based on keywords."""
    if not transactions:
        return ""

    loan_txs = []
    for tx in transactions:
        title = (_get(tx, "title") or "").lower()
        cp = (_get(tx, "counterparty_raw") or _get(tx, "counterparty") or "").lower()
        search_text = f"{title} {cp}"

        for kw in _LOAN_KEYWORDS:
            if kw in search_text:
                loan_txs.append(tx)
                break

    if not loan_txs:
        return ""

    # Group by counterparty to find recurring patterns
    cp_groups: Dict[str, List] = defaultdict(list)
    for tx in loan_txs:
        cp = (_get(tx, "counterparty_raw") or _get(tx, "counterparty") or "Nieznany")[:50]
        cp_groups[cp].append(tx)

    lines = [f"## WYKRYTE RATY / KREDYTY / ZOBOWIĄZANIA BANKOWE ({len(loan_txs)} transakcji)\n"]

    total_loan_amount = 0.0
    lines.append("| Kontrahent / Tytuł | Powtórzeń | Kwota pojedyncza | Łącznie | Regularność |")
    lines.append("|---------------------|-----------|------------------|---------|-------------|")

    sorted_groups = sorted(cp_groups.items(), key=lambda x: -len(x[1]))
    for cp, txs in sorted_groups[:20]:
        count = len(txs)
        amounts = [float(abs(_get(tx, "amount") or 0)) for tx in txs]
        total = sum(amounts)
        total_loan_amount += total

        # Check if amounts are consistent (recurring installment)
        if count >= 2 and amounts:
            avg = sum(amounts) / len(amounts)
            variance = sum((a - avg) ** 2 for a in amounts) / len(amounts)
            is_regular = variance < (avg * 0.1) ** 2 if avg > 0 else False
            regularity = "STAŁA RATA" if is_regular else "ZMIENNA"
        else:
            regularity = "JEDNORAZOWA" if count == 1 else "?"

        # Representative title
        title = (_get(txs[0], "title") or "")[:40]
        display = f"{cp[:35]}"
        if title and title.lower() != cp.lower():
            display += f" ({title})"

        lines.append(
            f"| {display[:55]} | {count} | {amounts[0]:,.2f} PLN | {total:,.2f} PLN | {regularity} |"
        )

    lines.append(f"\n- Łączna kwota zobowiązań w badanym okresie: **{total_loan_amount:,.2f} PLN**")

    # Monthly distribution of loan payments
    monthly_loans: Dict[str, float] = defaultdict(float)
    for tx in loan_txs:
        date_str = _get(tx, "booking_date") or _get(tx, "date") or ""
        if date_str and len(date_str) >= 7:
            monthly_loans[date_str[:7]] += float(abs(_get(tx, "amount") or 0))

    if monthly_loans:
        avg_monthly = sum(monthly_loans.values()) / len(monthly_loans)
        lines.append(f"- Średnie miesięczne obciążenie ratami: **{avg_monthly:,.2f} PLN**")

    return "\n".join(lines)


# ============================================================
# NEW: ATM patterns
# ============================================================

def _build_atm_patterns(transactions: list) -> str:
    """Analyze ATM withdrawal and cash deposit patterns."""
    if not transactions:
        return ""

    atm_withdrawals = []
    atm_deposits = []

    for tx in transactions:
        title = (_get(tx, "title") or "").lower()
        cp = (_get(tx, "counterparty_raw") or _get(tx, "counterparty") or "").lower()
        channel = (_get(tx, "channel") or "").lower()
        cat = (_get(tx, "category") or "").lower()
        search_text = f"{title} {cp} {channel} {cat}"

        is_atm = False
        for kw in _ATM_KEYWORDS:
            if kw in search_text:
                is_atm = True
                break

        if is_atm or channel in ("atm", "cash"):
            direction = _get(tx, "direction") or ""
            if direction == "DEBIT":
                atm_withdrawals.append(tx)
            else:
                atm_deposits.append(tx)

    if not atm_withdrawals and not atm_deposits:
        return ""

    lines = [f"## OPERACJE GOTÓWKOWE / BANKOMATOWE\n"]

    # Withdrawals
    if atm_withdrawals:
        w_amounts = [float(abs(_get(tx, "amount") or 0)) for tx in atm_withdrawals]
        w_total = sum(w_amounts)
        w_avg = w_total / len(w_amounts) if w_amounts else 0
        w_max = max(w_amounts) if w_amounts else 0

        lines.append(f"### Wypłaty gotówkowe ({len(atm_withdrawals)} operacji)")
        lines.append(f"- Łączna kwota wypłat: **{w_total:,.2f} PLN**")
        lines.append(f"- Średnia wypłata: {w_avg:,.2f} PLN")
        lines.append(f"- Największa wypłata: {w_max:,.2f} PLN")

        # Frequency analysis
        w_dates = []
        for tx in atm_withdrawals:
            ds = _get(tx, "booking_date") or _get(tx, "date") or ""
            if ds and len(ds) >= 10:
                try:
                    w_dates.append(datetime.strptime(ds[:10], "%Y-%m-%d"))
                except ValueError:
                    pass

        if len(w_dates) >= 2:
            w_dates.sort()
            gaps = [(w_dates[i+1] - w_dates[i]).days for i in range(len(w_dates)-1)]
            avg_gap = sum(gaps) / len(gaps)
            if avg_gap <= 7:
                lines.append(f"- Częstotliwość: co ~{avg_gap:.0f} dni (WYSOKA — cotygodniowa)")
            elif avg_gap <= 14:
                lines.append(f"- Częstotliwość: co ~{avg_gap:.0f} dni (co 2 tygodnie)")
            elif avg_gap <= 35:
                lines.append(f"- Częstotliwość: co ~{avg_gap:.0f} dni (comiesięczna)")
            else:
                lines.append(f"- Częstotliwość: co ~{avg_gap:.0f} dni (nieregularna)")

        # Round amounts check (suspicious pattern)
        round_count = sum(1 for a in w_amounts if a % 100 == 0)
        if round_count > len(w_amounts) * 0.5 and len(w_amounts) >= 3:
            lines.append(f"- ⚠ {round_count}/{len(w_amounts)} wypłat to okrągłe kwoty (wzorzec)")

        # Monthly distribution
        w_monthly: Dict[str, float] = defaultdict(float)
        for tx in atm_withdrawals:
            ds = _get(tx, "booking_date") or _get(tx, "date") or ""
            if ds and len(ds) >= 7:
                w_monthly[ds[:7]] += float(abs(_get(tx, "amount") or 0))

        if w_monthly:
            lines.append("\n| Miesiąc | Kwota wypłat |")
            lines.append("|---------|-------------|")
            for m in sorted(w_monthly.keys()):
                lines.append(f"| {m} | {w_monthly[m]:,.2f} PLN |")

    # Deposits
    if atm_deposits:
        d_amounts = [float(abs(_get(tx, "amount") or 0)) for tx in atm_deposits]
        d_total = sum(d_amounts)
        d_avg = d_total / len(d_amounts) if d_amounts else 0

        lines.append(f"\n### Wpłaty gotówkowe ({len(atm_deposits)} operacji)")
        lines.append(f"- Łączna kwota wpłat: **{d_total:,.2f} PLN**")
        lines.append(f"- Średnia wpłata: {d_avg:,.2f} PLN")

        # Large cash deposits are AML red flag
        large_deposits = [a for a in d_amounts if a >= 10000]
        if large_deposits:
            lines.append(f"- ⚠ **{len(large_deposits)} wpłat >= 10 000 PLN** — próg raportowania GIIF")
        structuring = [a for a in d_amounts if 9000 <= a < 10000]
        if structuring:
            lines.append(f"- ⚠ **{len(structuring)} wpłat w przedziale 9 000–9 999 PLN** — możliwe strukturyzowanie (smurfing)")

    return "\n".join(lines)


# ============================================================
# NEW: Geographic analysis
# ============================================================

def _build_geographic_analysis(transactions: list) -> str:
    """Analyze transaction locations for out-of-area purchases."""
    if not transactions:
        return ""

    location_amounts: Dict[str, float] = defaultdict(float)
    location_counts: Dict[str, int] = defaultdict(int)
    location_txs: Dict[str, List] = defaultdict(list)

    for tx in transactions:
        loc = _detect_location(tx)
        if loc:
            loc_clean = loc.strip().title()
            location_amounts[loc_clean] += float(abs(_get(tx, "amount") or 0))
            location_counts[loc_clean] += 1
            location_txs[loc_clean].append(tx)

    if not location_amounts:
        return ""

    # Sort by frequency
    sorted_locs = sorted(location_counts.items(), key=lambda x: -x[1])
    primary_city = sorted_locs[0][0] if sorted_locs else None

    lines = [f"## ANALIZA GEOGRAFICZNA TRANSAKCJI\n"]
    lines.append(f"Wykryto transakcje w **{len(location_amounts)}** lokalizacjach.")
    if primary_city:
        lines.append(f"Główna lokalizacja (najprawdopodobniej miejsce zamieszkania): **{primary_city}** ({location_counts[primary_city]} transakcji)")

    lines.append("\n| Miasto | Transakcje | Kwota | Udział |")
    lines.append("|--------|-----------|-------|--------|")

    total_loc_amount = sum(location_amounts.values())
    for loc, cnt in sorted_locs[:15]:
        amt = location_amounts[loc]
        pct = (amt / total_loc_amount * 100) if total_loc_amount > 0 else 0
        marker = " ← główna" if loc == primary_city else ""
        lines.append(f"| {loc}{marker} | {cnt} | {amt:,.2f} PLN | {pct:.1f}% |")

    # Flag out-of-area transactions
    if primary_city and len(sorted_locs) > 1:
        other_locs = [(loc, cnt) for loc, cnt in sorted_locs if loc != primary_city]
        if other_locs:
            lines.append(f"\n### Transakcje poza główną lokalizacją ({primary_city})")
            for loc, cnt in other_locs[:10]:
                amt = location_amounts[loc]
                # Show sample transactions from that location
                sample_txs = location_txs[loc][:3]
                samples = ", ".join(
                    f"{_get(tx, 'booking_date') or '?'}: {(_get(tx, 'counterparty_raw') or '')[:25]}"
                    for tx in sample_txs
                )
                lines.append(f"- **{loc}**: {cnt} tx, {amt:,.2f} PLN ({samples})")

    return "\n".join(lines)


# ============================================================
# Transaction table — smart aggregation for large datasets
# ============================================================

def _build_transaction_table(transactions: list) -> str:
    """Smart transaction listing: full list for small datasets, aggregated for large ones."""
    if not transactions:
        return ""

    tx_count = len(transactions)

    # For small datasets (< 200 TX), show full list
    if tx_count <= 200:
        return _build_full_transaction_table(transactions, limit=200)

    # For large datasets (200+ TX), show aggregated summary + flagged/notable transactions
    lines = [f"## TRANSAKCJE — PODSUMOWANIE ({tx_count} szt.)\n"]
    lines.append(f"Ze względu na dużą liczbę transakcji ({tx_count}), poniżej przedstawiono "
                 f"zagregowane dane oraz wyróżnione transakcje.\n")

    # --- Top 30 largest transactions ---
    sorted_by_amount = sorted(transactions, key=lambda tx: -float(abs(_get(tx, "amount") or 0)))
    large_txs = sorted_by_amount[:30]

    lines.append(f"### Największe transakcje (top 30)\n")
    lines.append("| # | Data | Kwota | Kierunek | Kontrahent | Tytuł | Lokalizacja |")
    lines.append("|---|------|-------|----------|------------|-------|-------------|")
    for i, tx in enumerate(large_txs):
        date = _get(tx, "date") or _get(tx, "booking_date") or "?"
        amt = float(_get(tx, "amount") or 0)
        direction = _get(tx, "direction") or ""
        cp = _get(tx, "counterparty") or _get(tx, "counterparty_raw") or "?"
        title = (_get(tx, "title") or "")[:45]
        location = _detect_location(tx) or ""
        sign = "-" if direction == "DEBIT" else "+"
        lines.append(
            f"| {i+1} | {date} | {sign}{abs(amt):,.2f} | {direction[:5]} | {cp[:35]} | {title} | {location} |"
        )

    # --- Flagged/risk transactions ---
    risk_txs = [tx for tx in transactions if _get(tx, "risk_tags")]
    if risk_txs:
        lines.append(f"\n### Transakcje z flagami ryzyka ({len(risk_txs)} szt.)\n")
        lines.append("| Data | Kwota | Kontrahent | Tytuł | Tagi ryzyka |")
        lines.append("|------|-------|------------|-------|-------------|")
        for tx in risk_txs[:20]:
            date = _get(tx, "date") or _get(tx, "booking_date") or "?"
            amt = float(_get(tx, "amount") or 0)
            cp = (_get(tx, "counterparty_raw") or _get(tx, "counterparty") or "?")[:30]
            title = (_get(tx, "title") or "")[:35]
            tags = _get(tx, "risk_tags") or []
            if isinstance(tags, str):
                import json as _json
                try:
                    tags = _json.loads(tags)
                except Exception:
                    tags = [tags]
            tags_str = ", ".join(tags) if isinstance(tags, list) else str(tags)
            lines.append(f"| {date} | {amt:+,.2f} | {cp} | {title} | {tags_str} |")

    # --- Amount distribution ---
    amounts = [float(abs(_get(tx, "amount") or 0)) for tx in transactions]
    if amounts:
        lines.append("\n### Rozkład kwot transakcji\n")
        brackets = [
            (0, 50, "0–50 PLN"),
            (50, 200, "50–200 PLN"),
            (200, 500, "200–500 PLN"),
            (500, 1000, "500–1 000 PLN"),
            (1000, 5000, "1 000–5 000 PLN"),
            (5000, 15000, "5 000–15 000 PLN"),
            (15000, float("inf"), "15 000+ PLN"),
        ]
        lines.append("| Przedział | Transakcje | Łączna kwota |")
        lines.append("|-----------|-----------|-------------|")
        for lo, hi, label in brackets:
            in_bracket = [a for a in amounts if lo <= a < hi]
            if in_bracket:
                lines.append(f"| {label} | {len(in_bracket)} | {sum(in_bracket):,.2f} PLN |")

    return "\n".join(lines)


def _build_full_transaction_table(transactions: list, limit: int = 200) -> str:
    """Full transaction table for smaller datasets."""
    lines = [f"## LISTA TRANSAKCJI ({len(transactions)} szt.)\n",
             "| # | Data | Kwota | Kanał | Kategoria | Kontrahent | Tytuł | Lokalizacja |",
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

| Metryka | Wartość |
|---------|---------|
| Łączne wpływy | {total_credit:,.2f} PLN |
| Łączne wydatki | {total_debit:,.2f} PLN |
| Bilans | {total_credit - total_debit:,.2f} PLN |
| Średnia transakcja | {avg:,.2f} PLN |
| Największa transakcja | {max_single:,.2f} PLN |"""


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
    lines = ["## KANAŁY TRANSAKCJI\n",
             "| Kanał | Liczba | Kwota |",
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
             "| Data | Kontrahent | Tytuł | Kwota | Kanał | Kategoria | Tagi |",
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

    lines = [f"## PRZELEWY P2P ({len(p2p_list)} szt.)\n"]
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
# Task section (instructions for the LLM)
# ============================================================

def _build_task_section(has_cross_validation: bool = False, has_enriched: bool = False) -> str:
    sections = """## ZADANIE — STRUKTURA RAPORTU

Na podstawie poniższych danych napisz profesjonalny raport z analizy rachunku bankowego.
Raport musi zawierać następujące sekcje:

### 1. Dane identyfikacyjne
- Właściciel rachunku (imię i nazwisko / nazwa firmy)
- Numer rachunku (IBAN)
- Bank prowadzący
- Analizowany czasookres (od–do)
- Saldo początkowe i końcowe

### 2. Podsumowanie finansowe
- Łączne wpływy vs łączne wydatki
- Czy właściciel żyje w ramach swoich wpływów?
- Główne źródła dochodów i ich regularność
- Bilans netto — trend pozytywny czy negatywny?

### 3. Miesięczne zestawienie wydatków
- Wykorzystaj dane z sekcji MIESIĘCZNE ZESTAWIENIE
- Wskaż miesiące z najwyższymi/najniższymi wydatkami
- Oceń stabilność wydatków — czy są przewidywalne?
- Suma badanego czasookresu

### 4. Raty i zobowiązania kredytowe
- Wykorzystaj dane z sekcji WYKRYTE RATY / KREDYTY
- Ile rat/kredytów jest spłacanych? Jakie kwoty?
- Czy raty są regularne (stała kwota)?
- Jaki procent wydatków stanowią zobowiązania kredytowe?
- Oceń obciążenie ratami względem wpływów

### 5. Operacje gotówkowe i bankomatowe
- Wykorzystaj dane z sekcji OPERACJE GOTÓWKOWE
- Częstotliwość wypłat — jak często, czy regularnie?
- Czy są wpłaty gotówkowe? Jakie kwoty?
- Czy kwoty wypłat są okrągłe (wzorzec)?
- Flagi AML: wpłaty >= 10 000 PLN, strukturyzowanie

### 6. Profil finansowy i przyzwyczajenia
- Główne kategorie wydatków (spożywcze, paliwo, gastronomia etc.)
- Kanały płatności (karta, BLIK, przelew, gotówka)
- Transakcje cykliczne / subskrypcje
- Dni tygodnia i pory miesiąca z największą aktywnością

### 7. Analiza geograficzna
- Wykorzystaj dane z sekcji ANALIZA GEOGRAFICZNA
- Główne miejsce zamieszkania / aktywności
- Czy zdarzają się zakupy poza główną lokalizacją?
- Jeśli tak — gdzie, jak często, jakie kwoty?

### 8. Wskaźniki problemów finansowych
- Czy wydatki przewyższają wpływy w jakimś miesiącu?
- Czy widać narastające zadłużenie?
- Czy pojawiają się windykacje, komornik, opłaty za opóźnienia?
- Czy są duże jednorazowe wypłaty sugerujące nagłą potrzebę?
- Trend salda — malejący czy rosnący?

### 9. Analiza ryzyka AML
- Strukturyzowanie (smurfing) — rozbijanie kwot na mniejsze
- Transakcje zagraniczne — kontrahenci, kwoty, cel
- Przelewy P2P — wykorzystaj sekcję PRZELEWY P2P
- Przelewy własne — między kontami
- Kontrahenci z czarnej/białej listy — wykorzystaj sekcję PROFILE KONTRAHENTÓW

### 10. Podejrzane transakcje
Wskaż konkretne transakcje (z datami, kwotami i TYTUŁAMI) które budzą wątpliwości i dlaczego.

### 11. Rekomendacje
Konkretne zalecenia — co należy dalej zweryfikować i jakie działania podjąć."""

    if has_cross_validation:
        sections += """

### 12. Ocena walidacji krzyżowej
Odwołaj się do wyników porównania MT940 vs PDF. Czy dane są spójne?
Jeśli są rozbieżności — co mogą oznaczać?"""

    sections += """

**WAŻNE**:
- Zachowaj ostrożność interpretacyjną — nie nadinterpretuj
- Dla każdego wniosku podaj jawny **poziom pewności**: WYSOKI / ŚREDNI / NISKI
- Jeśli dane są niewystarczające do wniosku, napisz to wprost
- Pisz po polsku, profesjonalnie ale zrozumiale
- Używaj konkretnych danych z wyciągu — nie wymyślaj danych których nie ma
- Przy dużej liczbie transakcji opieraj się na zagregowanych danych, nie wymieniaj każdej transakcji"""

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
        raise RuntimeError("Ollama nie jest dostępny. Uruchom Ollama aby uzyskać analizę LLM.")

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
        "Jesteś ekspertem ds. AML (Anti-Money Laundering) i analityki finansowej. "
        "Piszesz profesjonalne raporty analityczne po polsku. "
        "Bazujesz wyłącznie na dostarczonych danych — nie wymyślasz informacji. "
        "Używasz konkretnych kwot, dat i nazw kontrahentów w swoich analizach. "
        "Tworzysz ustrukturyzowane raporty z wyraźnymi sekcjami i wnioskami."
    )

    result = await deep_analyze(
        client,
        prompt,
        model=model,
        system=system,
        options={"temperature": 0.3, "num_ctx": 16384},
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
        raise RuntimeError("Ollama nie jest dostępny. Uruchom Ollama aby uzyskać analizę LLM.")

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
        "Jesteś ekspertem ds. AML (Anti-Money Laundering) i analityki finansowej. "
        "Piszesz profesjonalne raporty analityczne po polsku. "
        "Bazujesz wyłącznie na dostarczonych danych — nie wymyślasz informacji. "
        "Używasz konkretnych kwot, dat i nazw kontrahentów w swoich analizach. "
        "Tworzysz ustrukturyzowane raporty z wyraźnymi sekcjami i wnioskami."
    )

    async for chunk in stream_analyze(
        client, prompt, model=model, system=system,
        options={"temperature": 0.3, "num_ctx": 16384},
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
