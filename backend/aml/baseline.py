"""Baseline profiling and anomaly detection.

Builds per-account monthly baselines and detects anomalies:
- Amount outliers (z-score based)
- New counterparty + large amount
- P2P burst (many transfers in short window)
- Cash cluster
- Spending > income
- Missing expected payment (cyclicity break)
"""

from __future__ import annotations

import logging
import math
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from .normalize import NormalizedTransaction
from .rules import load_rules

log = logging.getLogger("aistate.aml.baseline")


class AnomalyAlert:
    """A detected anomaly."""
    __slots__ = ("alert_type", "severity", "score_delta", "explain", "evidence_tx_ids")

    def __init__(
        self,
        alert_type: str,
        severity: str = "medium",
        score_delta: float = 0,
        explain: str = "",
        evidence_tx_ids: Optional[List[str]] = None,
    ):
        self.alert_type = alert_type
        self.severity = severity  # low | medium | high | critical
        self.score_delta = score_delta
        self.explain = explain
        self.evidence_tx_ids = evidence_tx_ids or []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "alert_type": self.alert_type,
            "severity": self.severity,
            "score_delta": self.score_delta,
            "explain": self.explain,
            "evidence_tx_ids": self.evidence_tx_ids,
        }


class MonthlyProfile:
    """Monthly statistics for baseline."""

    def __init__(self):
        self.tx_count: int = 0
        self.total_credit: float = 0
        self.total_debit: float = 0
        self.amounts: List[float] = []
        self.counterparties: set = set()
        self.channels: Dict[str, int] = defaultdict(int)
        self.categories: Dict[str, float] = defaultdict(float)

    @property
    def median(self) -> float:
        if not self.amounts:
            return 0
        s = sorted(self.amounts)
        n = len(s)
        if n % 2 == 0:
            return (s[n // 2 - 1] + s[n // 2]) / 2
        return s[n // 2]

    @property
    def mean(self) -> float:
        return sum(self.amounts) / len(self.amounts) if self.amounts else 0

    @property
    def std(self) -> float:
        if len(self.amounts) < 2:
            return 0
        m = self.mean
        return math.sqrt(sum((x - m) ** 2 for x in self.amounts) / (len(self.amounts) - 1))

    @property
    def p95(self) -> float:
        if not self.amounts:
            return 0
        s = sorted(self.amounts)
        idx = int(0.95 * len(s))
        return s[min(idx, len(s) - 1)]


def build_baseline(
    transactions: List[NormalizedTransaction],
) -> Dict[str, MonthlyProfile]:
    """Build monthly profiles from transactions.

    Returns:
        Dict[month_str, MonthlyProfile] e.g. {"2024-01": profile, ...}
    """
    profiles: Dict[str, MonthlyProfile] = {}

    for tx in transactions:
        month = tx.booking_date[:7] if tx.booking_date and len(tx.booking_date) >= 7 else "unknown"
        if month not in profiles:
            profiles[month] = MonthlyProfile()

        p = profiles[month]
        p.tx_count += 1
        amt = float(abs(tx.amount))
        p.amounts.append(amt)

        if tx.direction == "CREDIT":
            p.total_credit += amt
        else:
            p.total_debit += amt

        if tx.counterparty_clean:
            p.counterparties.add(tx.counterparty_clean.lower()[:50])
        p.channels[tx.channel] += 1
        if tx.category:
            p.categories[tx.category] += amt

    return profiles


def detect_anomalies(
    transactions: List[NormalizedTransaction],
    baseline: Optional[Dict[str, MonthlyProfile]] = None,
    known_counterparties: Optional[set] = None,
) -> List[AnomalyAlert]:
    """Detect anomalies against baseline.

    Args:
        transactions: Current transactions to analyze
        baseline: Historical profiles (if available; if None, uses current data)
        known_counterparties: Set of previously seen counterparty names

    Returns:
        List of AnomalyAlert objects
    """
    rules = load_rules()
    thresholds = rules.get("anomaly", {})
    scoring = rules.get("scoring", {})
    alerts: List[AnomalyAlert] = []

    if known_counterparties is None:
        known_counterparties = set()

    # Build current profile
    current = build_baseline(transactions)

    # If no historical baseline, use current data as its own baseline
    if baseline is None or not baseline:
        baseline = current

    # Aggregate baseline stats
    all_amounts = []
    total_credit = 0
    total_debit = 0
    all_counterparties = set()
    for p in baseline.values():
        all_amounts.extend(p.amounts)
        total_credit += p.total_credit
        total_debit += p.total_debit
        all_counterparties.update(p.counterparties)

    if not all_amounts:
        return alerts

    global_mean = sum(all_amounts) / len(all_amounts)
    global_std = math.sqrt(sum((x - global_mean) ** 2 for x in all_amounts) / max(len(all_amounts) - 1, 1))
    zscore_threshold = thresholds.get("outlier_zscore", 2.5)

    # --- 1. Amount outliers ---
    for tx in transactions:
        amt = float(abs(tx.amount))
        if global_std > 0:
            zscore = (amt - global_mean) / global_std
            if zscore > zscore_threshold:
                alerts.append(AnomalyAlert(
                    alert_type="LARGE_OUTLIER",
                    severity="high" if zscore > 4 else "medium",
                    score_delta=scoring.get("LARGE_OUTLIER", 20),
                    explain=(
                        f"Kwota {amt:,.2f} PLN znacząco odbiega od średniej "
                        f"({global_mean:,.2f} ± {global_std:,.2f}), z-score={zscore:.1f}"
                    ),
                    evidence_tx_ids=[tx.id],
                ))

    # --- 2. New counterparty + large amount ---
    new_cp_threshold = thresholds.get("new_cp_large_pct", 0.3)
    monthly_avg = (total_debit / max(len(baseline), 1))

    for tx in transactions:
        cp = tx.counterparty_clean.lower()[:50]
        if not cp:
            continue
        if cp not in all_counterparties and cp not in known_counterparties:
            amt = float(abs(tx.amount))
            if monthly_avg > 0 and amt > monthly_avg * new_cp_threshold:
                alerts.append(AnomalyAlert(
                    alert_type="NEW_COUNTERPARTY_LARGE",
                    severity="medium",
                    score_delta=scoring.get("NEW_COUNTERPARTY_LARGE", 15),
                    explain=(
                        f"Nowy kontrahent '{tx.counterparty_raw[:40]}' z kwotą "
                        f"{amt:,.2f} PLN ({amt / monthly_avg * 100:.0f}% "
                        f"średnich miesięcznych wydatków)"
                    ),
                    evidence_tx_ids=[tx.id],
                ))

    # --- 3. P2P burst ---
    p2p_burst_count = thresholds.get("p2p_burst_count", 5)
    p2p_txns = [tx for tx in transactions if tx.channel == "BLIK_P2P"]

    if len(p2p_txns) >= p2p_burst_count:
        # Check 7-day windows
        p2p_by_date = defaultdict(list)
        for tx in p2p_txns:
            p2p_by_date[tx.booking_date].append(tx)

        dates = sorted(p2p_by_date.keys())
        for i, start_date in enumerate(dates):
            try:
                d0 = datetime.strptime(start_date, "%Y-%m-%d")
            except ValueError:
                continue
            window_txns = []
            for d_str in dates[i:]:
                try:
                    d = datetime.strptime(d_str, "%Y-%m-%d")
                except ValueError:
                    continue
                if (d - d0).days <= 7:
                    window_txns.extend(p2p_by_date[d_str])
                else:
                    break
            if len(window_txns) >= p2p_burst_count:
                total = sum(float(abs(t.amount)) for t in window_txns)
                alerts.append(AnomalyAlert(
                    alert_type="P2P_BURST",
                    severity="medium",
                    score_delta=scoring.get("P2P_BURST", 15),
                    explain=(
                        f"{len(window_txns)} przelewów P2P w 7 dni "
                        f"(od {start_date}), łącznie {total:,.2f} PLN"
                    ),
                    evidence_tx_ids=[t.id for t in window_txns[:10]],
                ))
                break  # Report once

    # --- 4. Cash cluster ---
    cash_cluster_count = thresholds.get("cash_cluster_count", 3)
    cash_txns = [tx for tx in transactions if tx.channel == "CASH"]

    if len(cash_txns) >= cash_cluster_count:
        cash_by_date = defaultdict(list)
        for tx in cash_txns:
            cash_by_date[tx.booking_date].append(tx)

        dates = sorted(cash_by_date.keys())
        for i, start_date in enumerate(dates):
            try:
                d0 = datetime.strptime(start_date, "%Y-%m-%d")
            except ValueError:
                continue
            window = []
            for d_str in dates[i:]:
                try:
                    d = datetime.strptime(d_str, "%Y-%m-%d")
                except ValueError:
                    continue
                if (d - d0).days <= 3:
                    window.extend(cash_by_date[d_str])
                else:
                    break
            if len(window) >= cash_cluster_count:
                total = sum(float(abs(t.amount)) for t in window)
                alerts.append(AnomalyAlert(
                    alert_type="CASH_CLUSTER",
                    severity="medium",
                    score_delta=scoring.get("CASH_CLUSTER", 10),
                    explain=(
                        f"{len(window)} operacji gotówkowych w 3 dni "
                        f"(od {start_date}), łącznie {total:,.2f} PLN"
                    ),
                    evidence_tx_ids=[t.id for t in window[:10]],
                ))
                break

    # --- 5. Spending over income ---
    spending_threshold = thresholds.get("spending_over_income_pct", 1.2)
    for month, profile in current.items():
        if month == "unknown":
            continue
        if profile.total_credit > 0:
            ratio = profile.total_debit / profile.total_credit
            if ratio > spending_threshold:
                alerts.append(AnomalyAlert(
                    alert_type="SPENDING_OVER_INCOME",
                    severity="high" if ratio > 1.5 else "medium",
                    score_delta=scoring.get("SPENDING_OVER_INCOME", 10),
                    explain=(
                        f"Miesiąc {month}: wydatki ({profile.total_debit:,.2f}) "
                        f"przekraczają wpływy ({profile.total_credit:,.2f}) "
                        f"— stosunek {ratio:.1%}"
                    ),
                ))

    return alerts
