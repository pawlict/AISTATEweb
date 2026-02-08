"""Build enriched LLM prompt from parsed & classified financial data.

Takes the structured output of the finance pipeline and creates
a detailed prompt that guides the LLM to produce high-quality analysis.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List, Optional

from .classifier import ClassifiedTransaction
from .parsers.base import ParseResult, StatementInfo
from .scorer import ScoreBreakdown


def build_finance_prompt(
    parse_result: ParseResult,
    classified: List[ClassifiedTransaction],
    score: ScoreBreakdown,
    original_instruction: str = "",
    behavioral=None,
) -> str:
    """Build the full enriched prompt for financial analysis.

    Returns a prompt string that replaces the raw document text,
    feeding the LLM structured data instead of raw PDF text.
    """
    parts: List[str] = []

    # --- System context ---
    parts.append(_build_system_section())

    # --- Behavioral analysis (if multi-month) ---
    if behavioral is not None:
        parts.append(_build_behavioral_section(behavioral))

    # --- Statement metadata ---
    parts.append(_build_info_section(parse_result))

    # --- Transaction table ---
    parts.append(_build_transactions_table(classified))

    # --- Category summary ---
    parts.append(_build_category_summary(classified))

    # --- Recurring obligations ---
    parts.append(_build_recurring_section(classified))

    # --- Risk flags ---
    parts.append(_build_risk_flags(classified, score))

    # --- Pre-computed statistics ---
    parts.append(_build_statistics(score))

    # --- Scoring ---
    parts.append(_build_scoring_section(score))

    # --- Task instructions ---
    parts.append(_build_task_instructions(original_instruction, has_behavioral=behavioral is not None))

    return "\n\n".join(p for p in parts if p)


def _build_system_section() -> str:
    return """# KONTEKST: Analiza wyciągu bankowego

Poniżej znajdują się przetworzone dane z wyciągu bankowego. Dane zostały automatycznie:
- Wyodrębnione z PDF (parser dedykowany dla danego banku)
- Znormalizowane do jednolitego formatu
- Wstępnie sklasyfikowane przez silnik regułowy
- Ocenione algorytmicznie (scoring)

Twoim zadaniem jest przeprowadzenie POGŁĘBIONEJ analizy eksperckiej na podstawie tych danych."""


def _build_info_section(result: ParseResult) -> str:
    info = result.info
    lines = ["## Informacje o wyciągu\n"]
    if info.bank:
        lines.append(f"- **Bank**: {info.bank}")
    if info.account_number:
        # Mask middle digits for privacy
        acct = info.account_number
        if len(acct) > 10:
            acct = acct[:6] + "..." + acct[-4:]
        lines.append(f"- **Numer rachunku**: {acct}")
    if info.period_from or info.period_to:
        lines.append(f"- **Okres**: {info.period_from or '?'} — {info.period_to or '?'}")
    if info.opening_balance is not None:
        lines.append(f"- **Saldo początkowe**: {info.opening_balance:,.2f} {info.currency}")
    if info.closing_balance is not None:
        lines.append(f"- **Saldo końcowe**: {info.closing_balance:,.2f} {info.currency}")
    lines.append(f"- **Liczba transakcji**: {len(result.transactions)}")
    lines.append(f"- **Metoda parsowania**: {result.parse_method}")

    if result.warnings:
        lines.append(f"\n**Ostrzeżenia parsera**: {'; '.join(result.warnings)}")

    return "\n".join(lines)


def _build_transactions_table(classified: List[ClassifiedTransaction]) -> str:
    if not classified:
        return "## Transakcje\n\nBrak transakcji."

    lines = ["## Transakcje\n"]
    lines.append("| # | Data | Kierunek | Kwota | Saldo | Kontrahent / Tytuł | Kategorie |")
    lines.append("|---|------|----------|-------|-------|--------------------|-----------|")

    for i, ct in enumerate(classified, 1):
        txn = ct.transaction
        direction = "▲ IN" if txn.direction == "in" else "▼ OUT"
        amount_str = f"{txn.amount:+,.2f}"
        balance_str = f"{txn.balance_after:,.2f}" if txn.balance_after is not None else "—"
        # Combine counterparty and title
        desc = txn.counterparty
        if txn.title and txn.title != txn.counterparty:
            desc = f"{desc} — {txn.title}" if desc else txn.title
        desc = desc[:60] + "…" if len(desc) > 60 else desc
        cats = ", ".join(ct.subcategories) if ct.subcategories else "—"
        if ct.is_recurring:
            cats = f"🔄 {cats}" if cats != "—" else "🔄 cykliczna"
        if ct.entity_flagged:
            cats = f"🚩 OZNACZONY {cats}" if cats != "—" else "🚩 OZNACZONY"
        if ct.entity_notes:
            cats += f" [{ct.entity_notes[:30]}]"

        lines.append(f"| {i} | {txn.date} | {direction} | {amount_str} | {balance_str} | {desc} | {cats} |")

    return "\n".join(lines)


def _build_category_summary(classified: List[ClassifiedTransaction]) -> str:
    cat_totals: Dict[str, Dict[str, float]] = defaultdict(lambda: {"in": 0.0, "out": 0.0, "count": 0})

    for ct in classified:
        if ct.categories:
            for cat in ct.categories:
                d = ct.transaction.direction
                cat_totals[cat][d] += abs(ct.transaction.amount)
                cat_totals[cat]["count"] += 1
        else:
            d = ct.transaction.direction
            cat_totals["_unclassified"][d] += abs(ct.transaction.amount)
            cat_totals["_unclassified"]["count"] += 1

    if not cat_totals:
        return ""

    # Nice category names
    NAMES = {
        "crypto": "🪙 Kryptowaluty",
        "gambling": "🎰 Hazard",
        "loans": "💳 Pożyczki / Kredyty",
        "transfers": "📋 Przelewy (kategoryzowane)",
        "risky": "⚠️ Ryzykowne",
        "_unclassified": "📦 Nieskategoryzowane",
    }

    lines = ["## Podsumowanie kategorii\n"]
    lines.append("| Kategoria | Transakcji | Wpływy | Wydatki |")
    lines.append("|-----------|-----------|--------|---------|")

    for cat in ["crypto", "gambling", "loans", "risky", "transfers", "_unclassified"]:
        if cat not in cat_totals:
            continue
        d = cat_totals[cat]
        name = NAMES.get(cat, cat)
        lines.append(f"| {name} | {int(d['count'])} | {d['in']:,.2f} | {d['out']:,.2f} |")

    return "\n".join(lines)


def _build_recurring_section(classified: List[ClassifiedTransaction]) -> str:
    recurring = [ct for ct in classified if ct.is_recurring]
    if not recurring:
        return "## Zobowiązania cykliczne\n\nNie wykryto transakcji cyklicznych."

    # Group by recurring_group
    groups: Dict[str, List[ClassifiedTransaction]] = defaultdict(list)
    for ct in recurring:
        key = ct.recurring_group or "?"
        groups[key].append(ct)

    lines = ["## Zobowiązania cykliczne\n"]
    lines.append("| Odbiorca | Powtórzeń | Śr. kwota | Suma | Kategorie |")
    lines.append("|----------|-----------|-----------|------|-----------|")

    total_recurring = 0.0
    for group_name, txns in sorted(groups.items()):
        amounts = [abs(ct.transaction.amount) for ct in txns]
        avg_amt = sum(amounts) / len(amounts) if amounts else 0
        total = sum(amounts)
        total_recurring += total
        cats = set()
        for ct in txns:
            cats.update(ct.subcategories)
        cats_str = ", ".join(sorted(cats)) if cats else "—"
        lines.append(f"| {group_name[:40]} | {len(txns)} | {avg_amt:,.2f} | {total:,.2f} | {cats_str} |")

    lines.append(f"\n**Suma zobowiązań cyklicznych**: {total_recurring:,.2f} PLN")

    return "\n".join(lines)


def _build_risk_flags(classified: List[ClassifiedTransaction], score: ScoreBreakdown) -> str:
    flags: List[str] = []

    if score.gambling_total > 0:
        pct = (score.gambling_total / max(score.total_income, score.total_expense, 1)) * 100
        flags.append(f"🎰 **HAZARD**: {score.gambling_total:,.2f} PLN ({pct:.1f}% budżetu)")

    if score.crypto_total > 0:
        pct = (score.crypto_total / max(score.total_income, score.total_expense, 1)) * 100
        flags.append(f"🪙 **KRYPTOWALUTY**: {score.crypto_total:,.2f} PLN ({pct:.1f}% budżetu)")

    if score.loans_total > 0:
        pct = (score.loans_total / max(score.total_income, score.total_expense, 1)) * 100
        flags.append(f"💳 **POŻYCZKI/RATY**: {score.loans_total:,.2f} PLN ({pct:.1f}% budżetu)")

    if score.net_flow < 0:
        flags.append(f"📉 **DEFICYT**: wydatki przewyższają wpływy o {abs(score.net_flow):,.2f} PLN")

    if score.recurring_pct > 60:
        flags.append(f"🔄 **WYSOKIE ZOBOWIĄZANIA CYKLICZNE**: {score.recurring_pct:.1f}% wpływów")

    # Entity memory flags
    flagged_entities = [ct for ct in classified if ct.entity_flagged]
    if flagged_entities:
        names = set()
        total_flagged = 0.0
        for ct in flagged_entities:
            names.add(ct.transaction.counterparty or ct.transaction.title)
            total_flagged += abs(ct.transaction.amount)
        names_str = ", ".join(sorted(names)[:10])
        flags.append(f"🚩 **OZNACZONE PODMIOTY (z pamięci)**: {len(flagged_entities)} transakcji ({total_flagged:,.2f} PLN) — {names_str}")

    if not flags:
        return "## Flagi ryzyka\n\nNie wykryto istotnych flag ryzyka."

    lines = ["## Flagi ryzyka\n"]
    lines.extend(flags)
    return "\n".join(lines)


def _build_statistics(score: ScoreBreakdown) -> str:
    lines = ["## Statystyki\n"]
    lines.append(f"- **Wpływy łącznie**: {score.total_income:,.2f} PLN")
    lines.append(f"- **Wydatki łącznie**: {score.total_expense:,.2f} PLN")
    lines.append(f"- **Bilans netto**: {score.net_flow:+,.2f} PLN")
    lines.append(f"- **Zobowiązania cykliczne**: {score.recurring_total:,.2f} PLN ({score.recurring_pct:.1f}% wpływów)")
    lines.append(f"- **Źródła dochodu**: {score.income_sources}")
    lines.append(f"- **Okres analizy**: {score.period_days} dni")
    lines.append(f"- **Liczba transakcji**: {score.transaction_count}")
    return "\n".join(lines)


def _build_scoring_section(score: ScoreBreakdown) -> str:
    lines = ["## Scoring finansowy (algorytmiczny)\n"]
    lines.append(f"### Wynik końcowy: **{score.total_score}/100**\n")
    lines.append("| Komponent | Wynik | Waga |")
    lines.append("|-----------|-------|------|")

    NAMES = {
        "income_stability": ("Stabilność dochodów", 15),
        "balance_trend": ("Trend salda", 10),
        "expense_ratio": ("Bilans wpływy/wydatki", 20),
        "recurring_burden": ("Obciążenie cykliczne", 15),
        "risk_gambling": ("Ryzyko: hazard", 15),
        "risk_crypto": ("Ryzyko: kryptowaluty", 5),
        "risk_loans": ("Ryzyko: pożyczki/dług", 15),
        "risk_deficit": ("Ryzyko: deficyt", 5),
    }

    components = score.to_dict()["components"]
    for key, (name, weight) in NAMES.items():
        val = components.get(key, 50)
        bar = _score_bar(val)
        lines.append(f"| {name} | {bar} {val}/100 | {weight}% |")

    return "\n".join(lines)


def _score_bar(value: int, width: int = 10) -> str:
    """Visual bar: ████░░░░░░"""
    filled = round(value / 100 * width)
    return "█" * filled + "░" * (width - filled)


def _build_behavioral_section(behavioral) -> str:
    """Build multi-month behavioral analysis section."""
    if behavioral is None or behavioral.total_months < 2:
        return ""

    TRAJECTORY_PL = {
        "stable": "Stabilna",
        "improving": "Poprawa",
        "worsening": "Pogarszanie się",
        "occasional_deficit": "Sporadyczny deficyt",
        "chronic_deficit": "Chroniczny deficyt",
    }
    DISCIPLINE_PL = {"high": "Wysoka", "medium": "Średnia", "low": "Niska"}
    RISK_PL = {"stable": "Stabilne", "increasing": "Rosnące", "decreasing": "Malejące"}
    DIRECTION_PL = {
        "increasing": "↗ rośnie",
        "decreasing": "↘ maleje",
        "stable": "→ stabilny",
        "volatile": "↕ niestabilny",
    }

    lines = [f"## Analiza behawioralna ({behavioral.total_months} miesięcy: {behavioral.period_from} — {behavioral.period_to})\n"]

    # Monthly summary table
    lines.append("### Podsumowanie miesięczne\n")
    lines.append("| Okres | Wpływy | Wydatki | Bilans | Hazard | Krypto | Pożyczki | Score |")
    lines.append("|-------|--------|---------|--------|--------|--------|----------|-------|")
    for m in behavioral.months:
        lines.append(
            f"| {m.period} | {m.income:,.0f} | {m.expense:,.0f} | {m.net_flow:+,.0f} "
            f"| {m.gambling_total:,.0f} | {m.crypto_total:,.0f} | {m.loans_total:,.0f} | {m.score}/100 |"
        )

    # Averages
    lines.append(f"\n- **Średnie wpływy**: {behavioral.avg_income:,.0f} PLN/mies.")
    lines.append(f"- **Średnie wydatki**: {behavioral.avg_expense:,.0f} PLN/mies.")
    lines.append(f"- **Średni bilans**: {behavioral.avg_net:+,.0f} PLN/mies.")
    lines.append(f"- **Skumulowany bilans**: {behavioral.cumulative_net:+,.0f} PLN")

    # Trajectory assessments
    lines.append(f"\n### Ocena trajektorii\n")
    lines.append(f"- **Trajektoria zadłużenia**: {TRAJECTORY_PL.get(behavioral.debt_trajectory, behavioral.debt_trajectory)}")
    lines.append(f"- **Dyscyplina budżetowa**: {DISCIPLINE_PL.get(behavioral.budget_discipline, behavioral.budget_discipline)}")
    lines.append(f"- **Trajektoria ryzyka**: {RISK_PL.get(behavioral.risk_trajectory, behavioral.risk_trajectory)}")

    # Trends
    if behavioral.trends:
        lines.append(f"\n### Wykryte trendy\n")
        lines.append("| Metryka | Trend | Zmiana | Wartości |")
        lines.append("|---------|-------|--------|---------|")
        for t in behavioral.trends:
            dir_str = DIRECTION_PL.get(t.direction, t.direction)
            vals = " → ".join(f"{v:,.0f}" for v in t.values)
            severity_icon = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(t.severity, "")
            lines.append(f"| {severity_icon} {t.description} | {dir_str} | {t.change_pct:+.1f}% | {vals} |")

    return "\n".join(lines)


def _build_task_instructions(original_instruction: str, has_behavioral: bool = False) -> str:
    lines = ["""## ZADANIE DLA MODELU

Na podstawie powyższych danych przeprowadź **szczegółową analizę finansową**. Twój raport powinien zawierać:

### 1. Podsumowanie wykonawcze
Krótki paragraf z kluczowymi wnioskami.

### 2. Analiza przepływów finansowych
- Czy właściciel rachunku żyje w ramach swoich wpływów?
- Jaki jest trend — czy sytuacja się poprawia czy pogarsza?
- Czy wpływy są regularne i przewidywalne?

### 3. Zobowiązania i obciążenia
- Jaką część budżetu pochłaniają zobowiązania cykliczne?
- Czy występują symptomy zadłużania się?
- Identyfikacja rat, pożyczek, kosztów obsługi długu

### 4. Wykryte ryzyka
- Transakcje hazardowe (analiza częstotliwości i kwot)
- Kryptowaluty (bezpośrednie i pośrednie)
- Pożyczki chwilówkowe i pozabankowe
- Inne podejrzane podmioty lub wzorce

### 5. Ocena behawioralna
- Przewidywalność zachowań finansowych
- Impulsywność wydatków
- Stabilność wzorców

### 6. Scoring z komentarzem
Odnieś się do automatycznego scoringu — czy Twoim zdaniem jest adekwatny?
Uzasadnij ewentualne korekty.

### 7. Rekomendacje
Konkretne zalecenia dotyczące poprawy sytuacji finansowej.

**WAŻNE**:
- Zachowaj ostrożność interpretacyjną — nie nadinterpretuj
- Dla każdego wniosku podaj jawny **poziom pewności**: WYSOKI / ŚREDNI / NISKI
- Jeśli dane są niewystarczające do wniosku, napisz to wprost
- Pisz po polsku, profesjonalnie ale zrozumiale"""]

    if has_behavioral:
        lines.append("""
### 8. Analiza wielomiesięczna (DODATKOWA — dane behawioralne dostępne powyżej)
- Porównaj miesiące: czy sytuacja się poprawia, pogarsza czy jest stabilna?
- Zidentyfikuj trendy: rosnące wydatki, malejące dochody, nowe ryzyka
- Oceń przewidywalność: czy zachowania finansowe są regularne czy chaotyczne?
- Czy widać symptomy spirali zadłużenia lub poprawy dyscypliny?
- Odnieś się do trajektorii zadłużenia i ryzyka z danych behawioralnych""")

    if original_instruction and original_instruction.strip():
        lines.append(f"\n### Dodatkowe instrukcje użytkownika\n{original_instruction.strip()}")

    return "\n".join(lines)
