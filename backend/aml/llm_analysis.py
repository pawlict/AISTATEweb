"""LLM-powered narrative AML analysis.

Builds a structured prompt from enriched AML pipeline results and sends it
to Ollama for a written expert analysis in Polish.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

log = logging.getLogger("aistate.aml.llm_analysis")


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

    # --- Flagged transactions ---
    parts.append(_build_flagged_transactions(transactions))

    # --- Full transaction list (compact) ---
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
        lines.append(f"| {info['label']} | {info['count']} | {info['total']:,.2f} PLN |")
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
    """Compact table of all transactions for LLM context."""
    if not transactions:
        return ""

    lines = [f"## LISTA TRANSAKCJI ({len(transactions)} szt, pokazano max {limit})\n",
             "| # | Data | Kwota | Kanal | Kategoria | Kontrahent |",
             "|---|------|-------|-------|-----------|------------|"]

    for i, tx in enumerate(transactions[:limit]):
        date = _get(tx, "date") or _get(tx, "booking_date") or "?"
        amt = float(_get(tx, "amount") or 0)
        ch = _get(tx, "channel") or ""
        cat = _get(tx, "category_label") or _get(tx, "category") or ""
        cp = _get(tx, "counterparty") or _get(tx, "counterparty_raw") or "?"
        lines.append(f"| {i+1} | {date} | {amt:+,.2f} | {ch[:12]} | {cat[:15]} | {cp[:40]} |")

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
    from collections import defaultdict
    cats: Dict[str, float] = defaultdict(float)
    cat_counts: Dict[str, int] = defaultdict(int)
    for tx in transactions:
        cat = _get(tx, "category") or "brak_kategorii"
        amt = float(abs(_get(tx, "amount") or 0))
        cats[cat] += amt
        cat_counts[cat] += 1
    sorted_cats = sorted(cats.items(), key=lambda x: -x[1])[:12]
    lines = ["## KATEGORIE TRANSAKCJI\n",
             "| Kategoria | Kwota | Liczba |",
             "|-----------|-------|--------|"]
    for cat, total in sorted_cats:
        lines.append(f"| {cat} | {total:,.2f} PLN | {cat_counts[cat]} |")
    return "\n".join(lines)


def _build_channel_breakdown(transactions: list) -> str:
    from collections import Counter, defaultdict
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
    from collections import defaultdict
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
             "| Data | Kontrahent | Kwota | Kanal | Tagi |",
             "|------|-----------|-------|-------|------|"]
    for tx in flagged[:limit]:
        date = _get(tx, "date") or _get(tx, "booking_date") or "?"
        cp = (_get(tx, "counterparty_raw") or _get(tx, "counterparty") or "?")[:35]
        amt = float(abs(_get(tx, "amount") or 0))
        direction = _get(tx, "direction") or ""
        ch = _get(tx, "channel") or ""
        tags = _get(tx, "risk_tags") or []
        tags_str = ", ".join(tags) if isinstance(tags, list) else str(tags)
        sign = "-" if direction == "DEBIT" else "+"
        lines.append(f"| {date} | {cp} | {sign}{amt:,.2f} | {ch} | {tags_str} |")
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
- Przelewy P2P i na telefon — regularne transfery do osob prywatnych
- Przelewy wlasne — miedzy kontami wlasciciela, ewentualne lokaty
- Duze jednorazowe transakcje vs wzorzec codziennych wydatkow

### 5. Podejrzane transakcje
Wskaz konkretne transakcje (z datami i kwotami) ktore budza watpliwosci i dlaczego.

### 6. Wzorce behawioralne
- Czy zachowania finansowe sa przewidywalne i stabilne?
- Czy widac impulsy lub anomalie?
- Porownaj dni tygodnia, pory miesiaca

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
