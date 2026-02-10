"""Chart data generators for AML analysis UI.

Produces JSON-serializable data for Chart.js rendering:
- Balance timeline (line chart)
- Category distribution (doughnut chart)
- Channel distribution (bar chart)
- Daily activity (bar chart by day of week)
- Monthly volume trend (bar chart)
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional

from .normalize import NormalizedTransaction


def generate_all_charts(
    transactions: List[NormalizedTransaction],
    opening_balance: Optional[float] = None,
) -> Dict[str, Any]:
    """Generate all chart datasets from transactions.

    Returns dict with keys: balance_timeline, category_distribution,
    channel_distribution, daily_activity, monthly_trend, top_counterparties
    """
    return {
        "balance_timeline": balance_timeline(transactions, opening_balance),
        "category_distribution": category_distribution(transactions),
        "channel_distribution": channel_distribution(transactions),
        "daily_activity": daily_activity(transactions),
        "monthly_trend": monthly_trend(transactions),
        "top_counterparties": top_counterparties(transactions, limit=15),
    }


def balance_timeline(
    transactions: List[NormalizedTransaction],
    opening_balance: Optional[float] = None,
) -> Dict[str, Any]:
    """Running balance over time (line chart data)."""
    sorted_tx = sorted(transactions, key=lambda t: (t.booking_date or "", t.id))

    balance = opening_balance if opening_balance is not None else 0
    labels = []
    data = []
    colors = []

    for tx in sorted_tx:
        amt = float(tx.amount)
        if tx.direction == "DEBIT":
            balance -= abs(amt)
        else:
            balance += abs(amt)

        labels.append(tx.booking_date or "")
        data.append(round(balance, 2))
        colors.append("#b91c1c" if balance < 0 else "#1f5aa6")

    return {
        "type": "line",
        "labels": labels,
        "datasets": [{
            "label": "Saldo",
            "data": data,
            "borderColor": "#1f5aa6",
            "backgroundColor": "rgba(31,90,166,0.1)",
            "fill": True,
            "tension": 0.2,
            "pointRadius": 1,
        }],
    }


def category_distribution(
    transactions: List[NormalizedTransaction],
) -> Dict[str, Any]:
    """Category breakdown by total amount (doughnut chart)."""
    cat_totals: Dict[str, float] = defaultdict(float)
    for tx in transactions:
        cat = tx.category or "brak_kategorii"
        cat_totals[cat] += float(abs(tx.amount))

    # Sort by total descending, keep top 10 + "inne"
    sorted_cats = sorted(cat_totals.items(), key=lambda x: -x[1])
    labels = []
    data = []
    other = 0.0
    for i, (cat, total) in enumerate(sorted_cats):
        if i < 10:
            labels.append(cat)
            data.append(round(total, 2))
        else:
            other += total
    if other > 0:
        labels.append("inne")
        data.append(round(other, 2))

    palette = [
        "#1f5aa6", "#d97706", "#b91c1c", "#15803d", "#7c3aed",
        "#0891b2", "#be185d", "#65a30d", "#c2410c", "#4338ca", "#6b7280"
    ]

    return {
        "type": "doughnut",
        "labels": labels,
        "datasets": [{
            "data": data,
            "backgroundColor": palette[:len(data)],
        }],
    }


def channel_distribution(
    transactions: List[NormalizedTransaction],
) -> Dict[str, Any]:
    """Channel breakdown (bar chart)."""
    ch_counts: Counter = Counter()
    ch_amounts: Dict[str, float] = defaultdict(float)
    for tx in transactions:
        ch = tx.channel or "OTHER"
        ch_counts[ch] += 1
        ch_amounts[ch] += float(abs(tx.amount))

    labels = sorted(ch_counts.keys())
    counts = [ch_counts[ch] for ch in labels]
    amounts = [round(ch_amounts[ch], 2) for ch in labels]

    return {
        "type": "bar",
        "labels": labels,
        "datasets": [
            {
                "label": "Liczba transakcji",
                "data": counts,
                "backgroundColor": "rgba(31,90,166,0.7)",
                "yAxisID": "y",
            },
            {
                "label": "Kwota (PLN)",
                "data": amounts,
                "backgroundColor": "rgba(217,119,6,0.5)",
                "yAxisID": "y1",
            },
        ],
    }


def daily_activity(
    transactions: List[NormalizedTransaction],
) -> Dict[str, Any]:
    """Transaction count by day of week (bar chart)."""
    day_names = ["Pon", "Wt", "Sr", "Czw", "Pt", "Sob", "Ndz"]
    day_counts = [0] * 7
    day_amounts = [0.0] * 7

    for tx in transactions:
        if tx.booking_date and len(tx.booking_date) >= 10:
            try:
                dt = datetime.strptime(tx.booking_date[:10], "%Y-%m-%d")
                dow = dt.weekday()
                day_counts[dow] += 1
                day_amounts[dow] += float(abs(tx.amount))
            except ValueError:
                pass

    return {
        "type": "bar",
        "labels": day_names,
        "datasets": [
            {
                "label": "Transakcje",
                "data": day_counts,
                "backgroundColor": "rgba(31,90,166,0.7)",
            },
        ],
    }


def monthly_trend(
    transactions: List[NormalizedTransaction],
) -> Dict[str, Any]:
    """Monthly credit vs debit trend (stacked bar chart)."""
    monthly_credit: Dict[str, float] = defaultdict(float)
    monthly_debit: Dict[str, float] = defaultdict(float)

    for tx in transactions:
        month = tx.booking_date[:7] if tx.booking_date and len(tx.booking_date) >= 7 else None
        if not month:
            continue
        amt = float(abs(tx.amount))
        if tx.direction == "CREDIT":
            monthly_credit[month] += amt
        else:
            monthly_debit[month] += amt

    months = sorted(set(list(monthly_credit.keys()) + list(monthly_debit.keys())))

    return {
        "type": "bar",
        "labels": months,
        "datasets": [
            {
                "label": "Wplywy",
                "data": [round(monthly_credit.get(m, 0), 2) for m in months],
                "backgroundColor": "rgba(21,128,61,0.7)",
            },
            {
                "label": "Wydatki",
                "data": [round(monthly_debit.get(m, 0), 2) for m in months],
                "backgroundColor": "rgba(185,28,28,0.6)",
            },
        ],
    }


def top_counterparties(
    transactions: List[NormalizedTransaction],
    limit: int = 15,
) -> Dict[str, Any]:
    """Top counterparties by total amount (horizontal bar chart)."""
    cp_totals: Dict[str, float] = defaultdict(float)
    cp_counts: Counter = Counter()

    for tx in transactions:
        name = (tx.counterparty_raw or tx.title or "Nieznany")[:40]
        cp_totals[name] += float(abs(tx.amount))
        cp_counts[name] += 1

    sorted_cps = sorted(cp_totals.items(), key=lambda x: -x[1])[:limit]
    labels = [cp[0] for cp in sorted_cps]
    amounts = [round(cp[1], 2) for cp in sorted_cps]

    return {
        "type": "bar",
        "labels": labels,
        "datasets": [{
            "label": "Kwota (PLN)",
            "data": amounts,
            "backgroundColor": "rgba(31,90,166,0.7)",
        }],
        "options": {"indexAxis": "y"},
    }
