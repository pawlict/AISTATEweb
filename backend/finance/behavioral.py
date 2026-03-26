"""Multi-month behavioral analysis.

Aggregates parsed statements across time to detect trends,
behavioral patterns, and long-term financial dynamics.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .classifier import ClassifiedTransaction
from .scorer import ScoreBreakdown


@dataclass
class MonthSnapshot:
    """Financial snapshot for a single month."""

    period: str = ""  # YYYY-MM
    income: float = 0.0
    expense: float = 0.0
    net_flow: float = 0.0
    balance_start: Optional[float] = None
    balance_end: Optional[float] = None
    transaction_count: int = 0
    recurring_total: float = 0.0
    gambling_total: float = 0.0
    crypto_total: float = 0.0
    loans_total: float = 0.0
    score: int = 50
    bank: str = ""
    source_file: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Trend:
    """A detected trend across months."""

    metric: str  # e.g. "net_flow", "gambling_total"
    direction: str  # "increasing", "decreasing", "stable", "volatile"
    severity: str  # "low", "medium", "high"
    description: str = ""
    values: List[float] = field(default_factory=list)
    periods: List[str] = field(default_factory=list)
    change_pct: float = 0.0  # % change first→last

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class BehavioralReport:
    """Full multi-month behavioral analysis."""

    months: List[MonthSnapshot] = field(default_factory=list)
    trends: List[Trend] = field(default_factory=list)
    period_from: str = ""
    period_to: str = ""
    total_months: int = 0
    avg_income: float = 0.0
    avg_expense: float = 0.0
    avg_net: float = 0.0
    cumulative_net: float = 0.0
    debt_trajectory: str = ""  # "stable", "improving", "worsening"
    budget_discipline: str = ""  # "high", "medium", "low"
    risk_trajectory: str = ""  # "stable", "increasing", "decreasing"

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["months"] = [m.to_dict() if isinstance(m, MonthSnapshot) else m for m in self.months]
        d["trends"] = [t.to_dict() if isinstance(t, Trend) else t for t in self.trends]
        return d


def build_month_snapshot(
    classified: List[ClassifiedTransaction],
    score: ScoreBreakdown,
    period: str = "",
    bank: str = "",
    source_file: str = "",
) -> MonthSnapshot:
    """Build a MonthSnapshot from a single statement's classified transactions."""
    snap = MonthSnapshot(
        period=period,
        income=score.total_income,
        expense=score.total_expense,
        net_flow=score.net_flow,
        transaction_count=score.transaction_count,
        recurring_total=score.recurring_total,
        gambling_total=score.gambling_total,
        crypto_total=score.crypto_total,
        loans_total=score.loans_total,
        score=score.total_score,
        bank=bank,
        source_file=source_file,
    )

    # Find balance range
    balances = [ct.transaction.balance_after for ct in classified if ct.transaction.balance_after is not None]
    if balances:
        snap.balance_start = balances[0]
        snap.balance_end = balances[-1]

    # Auto-detect period if not provided
    if not snap.period and classified:
        dates = sorted(ct.transaction.date for ct in classified if ct.transaction.date)
        if dates:
            snap.period = dates[0][:7]  # YYYY-MM

    return snap


def analyze_trends(months: List[MonthSnapshot]) -> List[Trend]:
    """Detect trends across monthly snapshots."""
    if len(months) < 2:
        return []

    trends: List[Trend] = []
    sorted_months = sorted(months, key=lambda m: m.period)
    periods = [m.period for m in sorted_months]

    # Metrics to analyze
    metrics = [
        ("net_flow", "Bilans netto (wpływy - wydatki)", "high"),
        ("income", "Wpływy", "medium"),
        ("expense", "Wydatki", "medium"),
        ("recurring_total", "Zobowiązania cykliczne", "medium"),
        ("gambling_total", "Wydatki na hazard", "high"),
        ("crypto_total", "Wydatki na kryptowaluty", "medium"),
        ("loans_total", "Wydatki na pożyczki/raty", "high"),
        ("score", "Scoring finansowy", "high"),
    ]

    for metric_name, description, severity in metrics:
        values = [getattr(m, metric_name, 0) or 0 for m in sorted_months]
        if all(v == 0 for v in values):
            continue

        trend = _compute_trend(metric_name, description, severity, values, periods)
        if trend:
            trends.append(trend)

    return trends


def _compute_trend(
    metric: str,
    description: str,
    severity: str,
    values: List[float],
    periods: List[str],
) -> Optional[Trend]:
    """Compute trend direction and significance for a metric."""
    if not values or len(values) < 2:
        return None

    first = values[0]
    last = values[-1]

    # Percentage change
    if first != 0:
        change_pct = ((last - first) / abs(first)) * 100
    elif last != 0:
        change_pct = 100.0 if last > 0 else -100.0
    else:
        change_pct = 0.0

    # Determine direction
    if len(values) >= 3:
        # Linear regression slope (simple)
        n = len(values)
        x_mean = (n - 1) / 2
        y_mean = sum(values) / n
        num = sum((i - x_mean) * (v - y_mean) for i, v in enumerate(values))
        den = sum((i - x_mean) ** 2 for i in range(n))
        slope = num / den if den else 0

        # Volatility (coefficient of variation)
        if y_mean != 0:
            std = (sum((v - y_mean) ** 2 for v in values) / n) ** 0.5
            cv = abs(std / y_mean) if y_mean else 0
        else:
            cv = 0

        if cv > 0.5:
            direction = "volatile"
        elif abs(change_pct) < 10:
            direction = "stable"
        elif slope > 0:
            direction = "increasing"
        else:
            direction = "decreasing"
    else:
        # Only 2 months
        if abs(change_pct) < 10:
            direction = "stable"
        elif last > first:
            direction = "increasing"
        else:
            direction = "decreasing"

    # Skip stable trends for non-risk metrics
    if direction == "stable" and severity != "high":
        return None

    return Trend(
        metric=metric,
        direction=direction,
        severity=severity,
        description=description,
        values=values,
        periods=periods,
        change_pct=round(change_pct, 1),
    )


def compute_behavioral_report(months: List[MonthSnapshot]) -> BehavioralReport:
    """Compute full behavioral report from monthly snapshots."""
    report = BehavioralReport()

    if not months:
        return report

    sorted_months = sorted(months, key=lambda m: m.period)
    report.months = sorted_months
    report.total_months = len(sorted_months)
    report.period_from = sorted_months[0].period
    report.period_to = sorted_months[-1].period

    # Averages
    report.avg_income = sum(m.income for m in sorted_months) / len(sorted_months)
    report.avg_expense = sum(m.expense for m in sorted_months) / len(sorted_months)
    report.avg_net = sum(m.net_flow for m in sorted_months) / len(sorted_months)
    report.cumulative_net = sum(m.net_flow for m in sorted_months)

    # Trends
    report.trends = analyze_trends(sorted_months)

    # Debt trajectory
    nets = [m.net_flow for m in sorted_months]
    deficit_months = sum(1 for n in nets if n < 0)
    if deficit_months == 0:
        report.debt_trajectory = "stable"
    elif deficit_months <= len(nets) / 3:
        report.debt_trajectory = "occasional_deficit"
    elif len(nets) >= 3 and nets[-1] < nets[0]:
        report.debt_trajectory = "worsening"
    elif len(nets) >= 3 and nets[-1] > nets[0]:
        report.debt_trajectory = "improving"
    else:
        report.debt_trajectory = "chronic_deficit"

    # Budget discipline
    if report.avg_net > 0 and report.avg_expense < report.avg_income * 0.85:
        report.budget_discipline = "high"
    elif report.avg_net >= 0:
        report.budget_discipline = "medium"
    else:
        report.budget_discipline = "low"

    # Risk trajectory
    risk_metrics = []
    for t in report.trends:
        if t.metric in ("gambling_total", "loans_total", "crypto_total"):
            if t.direction == "increasing":
                risk_metrics.append("increasing")
            elif t.direction == "decreasing":
                risk_metrics.append("decreasing")
    if "increasing" in risk_metrics and "decreasing" not in risk_metrics:
        report.risk_trajectory = "increasing"
    elif "decreasing" in risk_metrics and "increasing" not in risk_metrics:
        report.risk_trajectory = "decreasing"
    else:
        report.risk_trajectory = "stable"

    return report


def load_scoring_history(finance_dir: Path) -> List[MonthSnapshot]:
    """Load previously saved month snapshots from scoring_history.json."""
    hist_file = finance_dir / "scoring_history.json"
    if not hist_file.exists():
        return []
    try:
        data = json.loads(hist_file.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            return []
        return [MonthSnapshot(**item) for item in data]
    except Exception:
        return []


def save_scoring_history(finance_dir: Path, months: List[MonthSnapshot]) -> None:
    """Persist month snapshots to scoring_history.json."""
    finance_dir.mkdir(parents=True, exist_ok=True)
    hist_file = finance_dir / "scoring_history.json"

    # Merge with existing (avoid duplicates by period)
    existing = load_scoring_history(finance_dir)
    by_period: Dict[str, MonthSnapshot] = {}
    for m in existing:
        by_period[m.period] = m
    for m in months:
        by_period[m.period] = m  # newer overwrites

    merged = sorted(by_period.values(), key=lambda m: m.period)
    hist_file.write_text(
        json.dumps([m.to_dict() for m in merged], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
