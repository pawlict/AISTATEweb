"""Chart data generators for GSM billing visualization.

Produces data structures suitable for Chart.js rendering in the frontend.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional, Set

from .parsers.base import BillingRecord, BillingParseResult
from .analyzer import AnalysisResult


def generate_all_charts(
    result: BillingParseResult,
    analysis: AnalysisResult,
) -> Dict[str, Any]:
    """Generate all chart data from billing results and analysis.

    Returns:
        Dict with chart data ready for Chart.js frontend rendering.
    """
    records = result.records
    return {
        "activity_timeline": activity_timeline(records),
        "hourly_distribution": hourly_distribution(analysis),
        "record_type_breakdown": record_type_breakdown(records),
        "top_contacts": top_contacts_chart(analysis),
        "daily_volume": daily_volume(records),
        "call_duration_histogram": call_duration_histogram(records),
        "network_distribution": network_distribution(records),
        "cost_timeline": cost_timeline(records),
        "location_heatmap": location_heatmap_data(records),
    }


def activity_timeline(records: List[BillingRecord]) -> Dict[str, Any]:
    """Daily activity count over time (line chart)."""
    daily: Counter = Counter()
    for r in records:
        if r.date:
            daily[r.date] += 1

    sorted_dates = sorted(daily.keys())
    return {
        "type": "line",
        "labels": sorted_dates,
        "datasets": [{
            "label": "Aktywność dzienna",
            "data": [daily[d] for d in sorted_dates],
        }],
    }


def hourly_distribution(analysis: AnalysisResult) -> Dict[str, Any]:
    """Hourly activity distribution (bar chart)."""
    hours = list(range(24))
    dist = analysis.temporal.hourly_distribution
    return {
        "type": "bar",
        "labels": [f"{h:02d}:00" for h in hours],
        "datasets": [{
            "label": "Połączenia/SMS wg godziny",
            "data": [dist.get(h, 0) for h in hours],
        }],
    }


def record_type_breakdown(records: List[BillingRecord]) -> Dict[str, Any]:
    """Record type distribution (doughnut chart)."""
    type_labels = {
        "CALL_OUT": "Połączenia wychodzące",
        "CALL_IN": "Połączenia przychodzące",
        "SMS_OUT": "SMS wychodzące",
        "SMS_IN": "SMS przychodzące",
        "MMS_OUT": "MMS wychodzące",
        "MMS_IN": "MMS przychodzące",
        "DATA": "Transmisja danych",
        "USSD": "USSD",
        "VOICEMAIL": "Poczta głosowa",
        "OTHER": "Inne",
    }

    counts: Counter = Counter()
    for r in records:
        counts[r.record_type] += 1

    labels = []
    data = []
    for rt, count in counts.most_common():
        labels.append(type_labels.get(rt, rt))
        data.append(count)

    return {
        "type": "doughnut",
        "labels": labels,
        "datasets": [{"data": data}],
    }


def top_contacts_chart(
    analysis: AnalysisResult,
    top_n: int = 10,
) -> Dict[str, Any]:
    """Top contacts horizontal bar chart."""
    contacts = analysis.top_contacts[:top_n]
    labels = [c.number for c in contacts]
    calls = [c.calls_out + c.calls_in for c in contacts]
    sms = [c.sms_out + c.sms_in for c in contacts]

    return {
        "type": "bar",
        "indexAxis": "y",
        "labels": labels,
        "datasets": [
            {"label": "Połączenia", "data": calls},
            {"label": "SMS", "data": sms},
        ],
    }


def daily_volume(records: List[BillingRecord]) -> Dict[str, Any]:
    """Daily volume breakdown by type (stacked bar chart)."""
    daily_calls: Counter = Counter()
    daily_sms: Counter = Counter()
    daily_data: Counter = Counter()

    for r in records:
        if not r.date:
            continue
        if "CALL" in r.record_type:
            daily_calls[r.date] += 1
        elif "SMS" in r.record_type or "MMS" in r.record_type:
            daily_sms[r.date] += 1
        elif r.record_type == "DATA":
            daily_data[r.date] += 1

    all_dates = sorted(set(daily_calls.keys()) | set(daily_sms.keys()) | set(daily_data.keys()))

    return {
        "type": "bar",
        "stacked": True,
        "labels": all_dates,
        "datasets": [
            {"label": "Połączenia", "data": [daily_calls.get(d, 0) for d in all_dates]},
            {"label": "SMS/MMS", "data": [daily_sms.get(d, 0) for d in all_dates]},
            {"label": "Dane", "data": [daily_data.get(d, 0) for d in all_dates]},
        ],
    }


def call_duration_histogram(records: List[BillingRecord]) -> Dict[str, Any]:
    """Call duration distribution histogram."""
    buckets = [
        (0, 10, "0-10s"),
        (10, 30, "10-30s"),
        (30, 60, "30s-1min"),
        (60, 180, "1-3min"),
        (180, 600, "3-10min"),
        (600, 1800, "10-30min"),
        (1800, 3600, "30-60min"),
        (3600, float("inf"), ">1h"),
    ]

    counts = [0] * len(buckets)
    for r in records:
        if "CALL" not in r.record_type or r.duration_seconds <= 0:
            continue
        for i, (lo, hi, _) in enumerate(buckets):
            if lo <= r.duration_seconds < hi:
                counts[i] += 1
                break

    return {
        "type": "bar",
        "labels": [b[2] for b in buckets],
        "datasets": [{
            "label": "Liczba połączeń",
            "data": counts,
        }],
    }


def network_distribution(records: List[BillingRecord]) -> Dict[str, Any]:
    """Target network distribution (pie chart)."""
    networks: Counter = Counter()
    for r in records:
        if r.network:
            networks[r.network] += 1

    labels = []
    data = []
    for net, count in networks.most_common(10):
        labels.append(net)
        data.append(count)

    return {
        "type": "pie",
        "labels": labels,
        "datasets": [{"data": data}],
    }


def cost_timeline(records: List[BillingRecord]) -> Dict[str, Any]:
    """Daily cost timeline (line chart)."""
    daily_cost: Dict[str, float] = defaultdict(float)
    for r in records:
        if r.date and r.cost is not None:
            daily_cost[r.date] += r.cost

    sorted_dates = sorted(daily_cost.keys())
    return {
        "type": "line",
        "labels": sorted_dates,
        "datasets": [{
            "label": "Koszt dzienny (PLN)",
            "data": [round(daily_cost[d], 2) for d in sorted_dates],
        }],
    }


def location_heatmap_data(records: List[BillingRecord]) -> Dict[str, Any]:
    """Location activity data (for heatmap or table visualization)."""
    loc_hours: Dict[str, Counter] = defaultdict(Counter)

    for r in records:
        loc = r.location or r.location_cell_id
        if not loc or not r.time:
            continue
        try:
            hour = int(r.time.split(":")[0])
            loc_hours[loc][hour] += 1
        except (ValueError, IndexError):
            pass

    # Format as list for top locations
    top_locs = sorted(loc_hours.items(), key=lambda x: -sum(x[1].values()))[:20]

    return {
        "type": "heatmap",
        "locations": [
            {
                "name": loc,
                "total": sum(hours.values()),
                "hours": {h: c for h, c in sorted(hours.items())},
            }
            for loc, hours in top_locs
        ],
    }
