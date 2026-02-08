"""Deterministic financial health scorer.

Produces a score 0-100 based on objective metrics extracted from transactions.
Higher = healthier finances.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .classifier import ClassifiedTransaction


@dataclass
class ScoreBreakdown:
    """Detailed breakdown of the financial score."""

    # Component scores (0-100 each)
    income_stability: int = 50
    balance_trend: int = 50
    expense_ratio: int = 50
    recurring_burden: int = 50
    risk_gambling: int = 100  # 100 = no risk, 0 = high risk
    risk_crypto: int = 100
    risk_loans: int = 100
    risk_deficit: int = 50

    # Computed totals
    total_score: int = 50

    # Raw data behind the scores
    total_income: float = 0.0
    total_expense: float = 0.0
    net_flow: float = 0.0
    recurring_total: float = 0.0
    recurring_pct: float = 0.0
    gambling_total: float = 0.0
    crypto_total: float = 0.0
    loans_total: float = 0.0
    income_sources: int = 0
    expense_categories: int = 0
    transaction_count: int = 0
    period_days: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_score": self.total_score,
            "components": {
                "income_stability": self.income_stability,
                "balance_trend": self.balance_trend,
                "expense_ratio": self.expense_ratio,
                "recurring_burden": self.recurring_burden,
                "risk_gambling": self.risk_gambling,
                "risk_crypto": self.risk_crypto,
                "risk_loans": self.risk_loans,
                "risk_deficit": self.risk_deficit,
            },
            "data": {
                "total_income": round(self.total_income, 2),
                "total_expense": round(self.total_expense, 2),
                "net_flow": round(self.net_flow, 2),
                "recurring_total": round(self.recurring_total, 2),
                "recurring_pct": round(self.recurring_pct, 1),
                "gambling_total": round(self.gambling_total, 2),
                "crypto_total": round(self.crypto_total, 2),
                "loans_total": round(self.loans_total, 2),
                "income_sources": self.income_sources,
                "transaction_count": self.transaction_count,
                "period_days": self.period_days,
            },
        }


def compute_score(classified: List[ClassifiedTransaction]) -> ScoreBreakdown:
    """Compute financial health score from classified transactions."""
    s = ScoreBreakdown()

    if not classified:
        return s

    # --- Collect raw data ---
    incomes: List[float] = []
    expenses: List[float] = []
    recurring_expenses: List[float] = []
    gambling_amounts: List[float] = []
    crypto_amounts: List[float] = []
    loan_amounts: List[float] = []
    balances: List[float] = []
    dates: List[str] = []
    income_counterparties: set = set()

    for ct in classified:
        txn = ct.transaction
        dates.append(txn.date)
        if txn.balance_after is not None:
            balances.append(txn.balance_after)

        if txn.direction == "in":
            incomes.append(txn.amount)
            cp = (txn.counterparty or txn.title or "").strip()
            if cp:
                income_counterparties.add(cp.lower()[:30])
        else:
            expenses.append(abs(txn.amount))

        if ct.is_recurring and txn.direction == "out":
            recurring_expenses.append(abs(txn.amount))

        if "gambling" in ct.categories:
            gambling_amounts.append(abs(txn.amount))
        if "crypto" in ct.categories:
            crypto_amounts.append(abs(txn.amount))
        if "loans" in ct.categories:
            loan_amounts.append(abs(txn.amount))

    s.total_income = sum(incomes)
    s.total_expense = sum(expenses)
    s.net_flow = s.total_income - s.total_expense
    s.recurring_total = sum(recurring_expenses)
    s.gambling_total = sum(gambling_amounts)
    s.crypto_total = sum(crypto_amounts)
    s.loans_total = sum(loan_amounts)
    s.income_sources = len(income_counterparties)
    s.transaction_count = len(classified)

    # Period in days
    if dates:
        sorted_dates = sorted(dates)
        try:
            from datetime import datetime
            d0 = datetime.strptime(sorted_dates[0], "%Y-%m-%d")
            d1 = datetime.strptime(sorted_dates[-1], "%Y-%m-%d")
            s.period_days = max((d1 - d0).days, 1)
        except ValueError:
            s.period_days = 30

    # Recurring as % of income
    if s.total_income > 0:
        s.recurring_pct = (s.recurring_total / s.total_income) * 100
    elif s.total_expense > 0:
        s.recurring_pct = (s.recurring_total / s.total_expense) * 100

    # --- Compute component scores ---

    # 1. Income stability (0-100)
    # Reward: regular income, multiple sources
    if not incomes:
        s.income_stability = 10
    else:
        # Regularity: how many income events?
        monthly_income_count = len(incomes) / max(s.period_days / 30, 1)
        if monthly_income_count >= 2:
            s.income_stability = 80
        elif monthly_income_count >= 1:
            s.income_stability = 60
        else:
            s.income_stability = 30
        # Bonus for multiple sources
        if s.income_sources >= 2:
            s.income_stability = min(100, s.income_stability + 10)

    # 2. Balance trend (0-100)
    if len(balances) >= 2:
        trend = balances[-1] - balances[0]
        if trend > 0:
            s.balance_trend = min(100, 60 + int(min(trend / 500, 1.0) * 40))
        elif trend == 0:
            s.balance_trend = 50
        else:
            s.balance_trend = max(0, 50 - int(min(abs(trend) / 1000, 1.0) * 50))
    else:
        s.balance_trend = 50  # neutral if no data

    # 3. Expense ratio (income vs expenses)
    if s.total_income > 0:
        ratio = s.total_expense / s.total_income
        if ratio <= 0.7:
            s.expense_ratio = 100
        elif ratio <= 0.9:
            s.expense_ratio = 70
        elif ratio <= 1.0:
            s.expense_ratio = 40
        elif ratio <= 1.2:
            s.expense_ratio = 20
        else:
            s.expense_ratio = 0
    else:
        s.expense_ratio = 10 if expenses else 50

    # 4. Recurring burden (% of income going to fixed costs)
    if s.recurring_pct <= 30:
        s.recurring_burden = 90
    elif s.recurring_pct <= 50:
        s.recurring_burden = 60
    elif s.recurring_pct <= 70:
        s.recurring_burden = 30
    else:
        s.recurring_burden = 10

    # 5. Risk: gambling
    if not gambling_amounts:
        s.risk_gambling = 100
    else:
        pct = (s.gambling_total / max(s.total_income, s.total_expense, 1)) * 100
        if pct <= 1:
            s.risk_gambling = 80
        elif pct <= 5:
            s.risk_gambling = 50
        elif pct <= 15:
            s.risk_gambling = 20
        else:
            s.risk_gambling = 0

    # 6. Risk: crypto
    if not crypto_amounts:
        s.risk_crypto = 100
    else:
        pct = (s.crypto_total / max(s.total_income, s.total_expense, 1)) * 100
        if pct <= 5:
            s.risk_crypto = 80
        elif pct <= 15:
            s.risk_crypto = 50
        elif pct <= 30:
            s.risk_crypto = 25
        else:
            s.risk_crypto = 10

    # 7. Risk: loans / debt
    if not loan_amounts:
        s.risk_loans = 100
    else:
        pct = (s.loans_total / max(s.total_income, s.total_expense, 1)) * 100
        if pct <= 10:
            s.risk_loans = 70
        elif pct <= 25:
            s.risk_loans = 40
        elif pct <= 50:
            s.risk_loans = 15
        else:
            s.risk_loans = 0

    # 8. Deficit risk
    if s.net_flow > 0:
        s.risk_deficit = min(100, 60 + int(min(s.net_flow / 1000, 1.0) * 40))
    elif s.net_flow == 0:
        s.risk_deficit = 50
    else:
        s.risk_deficit = max(0, 40 - int(min(abs(s.net_flow) / 2000, 1.0) * 40))

    # --- Weighted total ---
    weights = {
        "income_stability": 15,
        "balance_trend": 10,
        "expense_ratio": 20,
        "recurring_burden": 15,
        "risk_gambling": 15,
        "risk_crypto": 5,
        "risk_loans": 15,
        "risk_deficit": 5,
    }
    total_weight = sum(weights.values())
    weighted_sum = (
        s.income_stability * weights["income_stability"]
        + s.balance_trend * weights["balance_trend"]
        + s.expense_ratio * weights["expense_ratio"]
        + s.recurring_burden * weights["recurring_burden"]
        + s.risk_gambling * weights["risk_gambling"]
        + s.risk_crypto * weights["risk_crypto"]
        + s.risk_loans * weights["risk_loans"]
        + s.risk_deficit * weights["risk_deficit"]
    )
    s.total_score = round(weighted_sum / total_weight)

    return s
