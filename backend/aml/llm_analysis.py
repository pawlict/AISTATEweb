"""LLM-powered narrative AML analysis.

Builds a structured prompt from AML pipeline results and sends it
to Ollama for a written expert analysis in Polish.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

log = logging.getLogger("aistate.aml.llm_analysis")


def build_aml_prompt(
    statement_info: Dict[str, Any],
    transactions: list,
    alerts: List[Dict[str, Any]],
    risk_score: float,
    risk_reasons: list,
    ml_anomalies: Optional[List[Dict[str, Any]]] = None,
    chart_summary: Optional[Dict[str, Any]] = None,
) -> str:
    """Build comprehensive AML analysis prompt for LLM.

    Returns a prompt string ready to send to Ollama.
    """
    parts: List[str] = []

    # --- System context ---
    parts.append("""# KONTEKST: Analiza AML wyciagu bankowego

Jestes ekspertem ds. przeciwdzialania praniu pieniedzy (AML) i analityki finansowej.
Przygotuj profesjonalna analize wyciagu bankowego na podstawie ponizszych danych.
Analiza powinna byc w jezyku polskim, merytoryczna i konkretna.

WAZNE:
- Pisz profesjonalnie ale zrozumiale
- Odwoluj sie do konkretnych kwot, dat i kontrahentow
- Wskazuj wzorce zachowan finansowych
- Ocen ryzyko AML na podstawie danych
- Zaproponuj rekomendacje""")

    # --- Statement info ---
    info = statement_info
    parts.append(f"""## DANE WYCIAGU

| Pole | Wartosc |
|------|---------|
| Bank | {info.get('bank_name', '?')} |
| Wlasciciel | {info.get('account_holder', '?')} |
| IBAN | {info.get('account_number', '?')} |
| Okres | {info.get('period_from', '?')} — {info.get('period_to', '?')} |
| Saldo poczatkowe | {info.get('opening_balance', '?')} {info.get('currency', 'PLN')} |
| Saldo koncowe | {info.get('closing_balance', '?')} {info.get('currency', 'PLN')} |
| Liczba transakcji | {len(transactions)} |""")

    # --- Risk score ---
    level = "NISKI" if risk_score < 30 else ("SREDNI" if risk_score < 60 else "WYSOKI")
    parts.append(f"""## OCENA RYZYKA

Risk score: **{risk_score:.0f}/100** ({level})""")

    if risk_reasons:
        parts.append("Skladowe ryzyka:")
        for reason in risk_reasons[:15]:
            if isinstance(reason, dict):
                parts.append(f"- {reason.get('tag', '?')}: +{reason.get('score', 0)} pkt — {reason.get('count', '?')} transakcji")
            else:
                parts.append(f"- {reason}")

    # --- Alerts ---
    if alerts:
        parts.append(f"\n## ALERTY ({len(alerts)})")
        for alert in alerts[:10]:
            if isinstance(alert, dict):
                parts.append(f"- [{alert.get('severity', '?').upper()}] {alert.get('alert_type', '?')}: {alert.get('explain', '')}")
            else:
                parts.append(f"- {alert}")

    # --- ML anomalies ---
    if ml_anomalies:
        anomaly_count = sum(1 for a in ml_anomalies if a.get("is_anomaly"))
        if anomaly_count > 0:
            parts.append(f"\n## ANOMALIE ML (Isolation Forest): {anomaly_count} wykrytych")
            top_anomalies = sorted(
                [a for a in ml_anomalies if a.get("is_anomaly")],
                key=lambda x: -x.get("anomaly_score", 0)
            )[:10]
            for a in top_anomalies:
                parts.append(f"- TX {a.get('tx_id', '?')[:8]}... score={a.get('anomaly_score', 0):.2f}")

    # --- Transaction summary ---
    parts.append(_build_transaction_summary(transactions))

    # --- Category breakdown ---
    parts.append(_build_category_breakdown(transactions))

    # --- Channel breakdown ---
    parts.append(_build_channel_breakdown(transactions))

    # --- Top counterparties ---
    parts.append(_build_top_counterparties(transactions))

    # --- Flagged transactions ---
    parts.append(_build_flagged_transactions(transactions))

    # --- Task ---
    parts.append("""## ZADANIE

Na podstawie powyzszych danych napisz profesjonalny raport AML zawierajacy:

1. **Podsumowanie** (2-3 zdania: kto, jaki bank, jaki okres, ogolna ocena)
2. **Profil finansowy** (wplywy vs wydatki, glowne kategorie, regularne zobowiazania)
3. **Analiza ryzyka** (jakie wzorce budzace watpliwosci zostaly wykryte, dlaczego)
4. **Podejrzane transakcje** (konkretne transakcje z kwotami i datami)
5. **Wzorce behawioralne** (czy widac nietypowe zachowania, strukturyzowanie, smurfing)
6. **Rekomendacje** (co nalezy dalej zweryfikowac, jakie dzialania podjac)

Pisz po polsku. Uzywaj konkretnych danych z wyciagu. Nie wymyslaj danych ktorych nie ma.""")

    return "\n\n".join(p for p in parts if p)


def _build_transaction_summary(transactions: list) -> str:
    """Aggregate stats for the prompt."""
    total_credit = 0.0
    total_debit = 0.0
    max_single = 0.0
    for tx in transactions:
        amt = float(abs(getattr(tx, 'amount', 0) if hasattr(tx, 'amount') else tx.get('amount', 0)))
        direction = getattr(tx, 'direction', '') if hasattr(tx, 'direction') else tx.get('direction', '')
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
    """Category totals for the prompt."""
    from collections import defaultdict
    cats: Dict[str, float] = defaultdict(float)
    cat_counts: Dict[str, int] = defaultdict(int)

    for tx in transactions:
        cat = getattr(tx, 'category', '') if hasattr(tx, 'category') else tx.get('category', '')
        amt = float(abs(getattr(tx, 'amount', 0) if hasattr(tx, 'amount') else tx.get('amount', 0)))
        cat = cat or "brak_kategorii"
        cats[cat] += amt
        cat_counts[cat] += 1

    sorted_cats = sorted(cats.items(), key=lambda x: -x[1])[:12]

    lines = ["## KATEGORIE TRANSAKCJI", ""]
    lines.append("| Kategoria | Kwota | Liczba |")
    lines.append("|-----------|-------|--------|")
    for cat, total in sorted_cats:
        lines.append(f"| {cat} | {total:,.2f} PLN | {cat_counts[cat]} |")

    return "\n".join(lines)


def _build_channel_breakdown(transactions: list) -> str:
    """Channel stats for the prompt."""
    from collections import Counter, defaultdict
    ch_counts: Counter = Counter()
    ch_amounts: Dict[str, float] = defaultdict(float)

    for tx in transactions:
        ch = getattr(tx, 'channel', '') if hasattr(tx, 'channel') else tx.get('channel', '')
        amt = float(abs(getattr(tx, 'amount', 0) if hasattr(tx, 'amount') else tx.get('amount', 0)))
        ch = ch or "OTHER"
        ch_counts[ch] += 1
        ch_amounts[ch] += amt

    lines = ["## KANALY TRANSAKCJI", ""]
    lines.append("| Kanal | Liczba | Kwota |")
    lines.append("|-------|--------|-------|")
    for ch, cnt in ch_counts.most_common():
        lines.append(f"| {ch} | {cnt} | {ch_amounts[ch]:,.2f} PLN |")

    return "\n".join(lines)


def _build_top_counterparties(transactions: list, limit: int = 15) -> str:
    """Top counterparties for the prompt."""
    from collections import defaultdict
    cp_totals: Dict[str, float] = defaultdict(float)
    cp_counts: Dict[str, int] = defaultdict(int)

    for tx in transactions:
        name = getattr(tx, 'counterparty_raw', '') if hasattr(tx, 'counterparty_raw') else tx.get('counterparty_raw', '')
        amt = float(abs(getattr(tx, 'amount', 0) if hasattr(tx, 'amount') else tx.get('amount', 0)))
        name = (name or "Nieznany")[:50]
        cp_totals[name] += amt
        cp_counts[name] += 1

    sorted_cps = sorted(cp_totals.items(), key=lambda x: -x[1])[:limit]

    lines = ["## TOP KONTRAHENCI", ""]
    lines.append("| Kontrahent | Kwota | Transakcje |")
    lines.append("|------------|-------|-----------|")
    for name, total in sorted_cps:
        lines.append(f"| {name} | {total:,.2f} PLN | {cp_counts[name]} |")

    return "\n".join(lines)


def _build_flagged_transactions(transactions: list, limit: int = 20) -> str:
    """Transactions with risk tags for the prompt."""
    flagged = []
    for tx in transactions:
        tags = getattr(tx, 'risk_tags', []) if hasattr(tx, 'risk_tags') else tx.get('risk_tags', [])
        if isinstance(tags, str):
            import json
            try:
                tags = json.loads(tags)
            except Exception:
                tags = []
        if tags:
            flagged.append(tx)

    if not flagged:
        return ""

    lines = [f"## TRANSAKCJE Z FLAGAMI RYZYKA ({len(flagged)})", ""]
    lines.append("| Data | Kontrahent | Kwota | Kanal | Tagi |")
    lines.append("|------|-----------|-------|-------|------|")
    for tx in flagged[:limit]:
        date = getattr(tx, 'booking_date', '') if hasattr(tx, 'booking_date') else tx.get('booking_date', '')
        cp = getattr(tx, 'counterparty_raw', '') if hasattr(tx, 'counterparty_raw') else tx.get('counterparty_raw', '')
        amt = float(abs(getattr(tx, 'amount', 0) if hasattr(tx, 'amount') else tx.get('amount', 0)))
        direction = getattr(tx, 'direction', '') if hasattr(tx, 'direction') else tx.get('direction', '')
        ch = getattr(tx, 'channel', '') if hasattr(tx, 'channel') else tx.get('channel', '')
        tags = getattr(tx, 'risk_tags', []) if hasattr(tx, 'risk_tags') else tx.get('risk_tags', [])
        if isinstance(tags, list):
            tags_str = ", ".join(tags)
        else:
            tags_str = str(tags)
        sign = "-" if direction == "DEBIT" else "+"
        lines.append(f"| {date} | {(cp or '?')[:35]} | {sign}{amt:,.2f} | {ch} | {tags_str} |")

    return "\n".join(lines)


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
        "Bazujesz wylacznie na dostarczonych danych — nie wymyslasz informacji."
    )

    result = await deep_analyze(
        client,
        prompt,
        model=model,
        system=system,
        options={"temperature": 0.3, "num_ctx": 8192},
    )

    return result
