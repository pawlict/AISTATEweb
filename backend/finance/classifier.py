"""Rule-based transaction classifier.

Classifies transactions into risk categories using regex patterns.
LLM is used only as fallback for ambiguous transactions (Etap 2).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from .parsers.base import RawTransaction


# --- Classification rules ---
# Each rule: (category, subcategory, patterns_on_counterparty_or_title)

CATEGORY_RULES: Dict[str, Dict[str, List[str]]] = {
    "crypto": {
        "exchange": [
            r"binance", r"coinbase", r"bitbay", r"zonda\.exchange",
            r"bybit", r"kraken", r"bitget", r"kucoin", r"gate\.io",
            r"crypto\.com", r"bitstamp", r"gemini", r"okx",
            r"kanga\s*exchange", r"coinflex", r"bitfinex",
        ],
        "payment": [
            r"simplex", r"moonpay", r"transak", r"ramp\s*network",
            r"wyre", r"banxa",
        ],
        "keyword": [
            r"kryptowalut", r"bitcoin", r"\bbtc\b", r"\beth\b",
            r"blockchain", r"token", r"wallet.*crypto",
        ],
    },
    "gambling": {
        "bookmaker": [
            r"\bsts\b", r"sts\.pl", r"betclic", r"fortuna",
            r"superbet", r"lvbet", r"betfan", r"totalbet",
            r"betsson", r"unibet", r"bet365", r"noblebet",
            r"ewinner", r"fuksiarz", r"betters",
        ],
        "casino": [
            r"casino", r"kasyno", r"slot", r"poker",
            r"total\s*casino", r"goplusbet",
        ],
        "lottery": [
            r"lotto", r"toto.*lotek", r"eurojackpot", r"multi\s*multi",
            r"zdrapk", r"los.*loteri", r"mini\s*lotto",
        ],
        "keyword": [
            r"bukmacher", r"zak[łl]ad.*sport", r"hazard",
            r"gra.*online", r"gambling",
        ],
    },
    "loans": {
        "payday": [
            r"vivus", r"wonga", r"provident", r"incredit",
            r"lendon", r"smartney", r"aasa", r"ferratum",
            r"zaplo", r"netcredit", r"filarum", r"solcredit",
            r"alegotowka", r"pozyczkomat", r"chwil[oó]wk",
            r"kuki\.pl", r"hapipozyczki", r"Extra Portfel",
        ],
        "installment": [
            r"\brata\b", r"rat[ay]\s*(kredyt|po[żz]yczk)",
            r"sp[łl]ata\s*(kredyt|po[żz]yczk|rat)",
            r"leasing", r"alior.*rata", r"santander.*rata",
        ],
        "mortgage": [
            r"kredyt\s*mieszk", r"kredyt\s*hipotecz",
            r"hipoteka", r"mortgage",
        ],
        "keyword": [
            r"po[żz]yczk", r"kredyt", r"debt.*collect",
            r"windykac", r"komorni",
        ],
    },
    "transfers": {
        "salary": [
            r"wynagrodzeni", r"pensj[aę]", r"wyp[łl]ata",
            r"premia", r"zasi[łl]ek", r"zleceni.*umow",
        ],
        "benefits": [
            r"zus", r"krus", r"500\s*plus", r"800\s*plus",
            r"rodzinn", r"alimenty", r"stypend",
            r"zasi[łl]ek.*bezrobot",
        ],
        "rent": [
            r"czynsz", r"najem", r"wynaj[eę]", r"op[łl]ata.*mieszk",
            r"wsp[oó]lnota\s*mieszk", r"sp[oó][łl]dzielni",
        ],
        "utilities": [
            r"energia|energa|tauron|pge|enea|innogy",
            r"gaz.*pgnig|pgnig|polsk.*gaz",
            r"wod.*kan|wodoci[ąa]g|mpwik",
            r"ogrze|ciep[łl]o",
        ],
        "telecom": [
            r"orange|t-mobile|plus.*gsm|play|vectra",
            r"upc|polsat.*box|canal.*plus|netflix|spotify",
            r"hbo|disney|amazon.*prime|youtube.*prem",
        ],
        "insurance": [
            r"ubezpiecz|polisa|pzu|warta|ergo\s*hestia",
            r"allianz|aviva|generali|compensa|uniqa",
            r"oc\s.*pojazd|ac\s.*pojazd|nnw",
        ],
    },
    "risky": {
        "unknown_foreign": [
            r"western\s*union", r"moneygram", r"ria\s*money",
            r"remitly", r"wise.*transfer", r"transferwise",
        ],
        "pawnshop": [
            r"lombard", r"zastaw", r"skup\s*z[łl]ota",
        ],
    },
}

# Flattened for fast lookup
_COMPILED_RULES: List[tuple] = []


def _ensure_compiled():
    global _COMPILED_RULES
    if _COMPILED_RULES:
        return
    for category, subcats in CATEGORY_RULES.items():
        for subcat, patterns in subcats.items():
            for pat in patterns:
                _COMPILED_RULES.append((
                    category,
                    subcat,
                    re.compile(pat, re.IGNORECASE),
                ))


@dataclass
class ClassifiedTransaction:
    """Transaction with classification tags."""

    transaction: RawTransaction
    categories: List[str] = field(default_factory=list)  # e.g. ["crypto"]
    subcategories: List[str] = field(default_factory=list)  # e.g. ["crypto:exchange"]
    confidence: float = 1.0  # 1.0 for rule-based, lower for LLM-based
    is_recurring: bool = False
    recurring_group: Optional[str] = None  # group key for recurring detection

    def to_dict(self) -> Dict[str, Any]:
        d = self.transaction.to_dict()
        d["categories"] = self.categories
        d["subcategories"] = self.subcategories
        d["confidence"] = self.confidence
        d["is_recurring"] = self.is_recurring
        d["recurring_group"] = self.recurring_group
        return d


def classify_transaction(txn: RawTransaction) -> ClassifiedTransaction:
    """Classify a single transaction using rules."""
    _ensure_compiled()

    search_text = f"{txn.counterparty} {txn.title} {txn.raw_text}".lower()
    cats: Set[str] = set()
    subcats: Set[str] = set()

    for category, subcat, pattern in _COMPILED_RULES:
        if pattern.search(search_text):
            cats.add(category)
            subcats.add(f"{category}:{subcat}")

    return ClassifiedTransaction(
        transaction=txn,
        categories=sorted(cats),
        subcategories=sorted(subcats),
        confidence=1.0 if cats else 0.0,
    )


def classify_all(transactions: List[RawTransaction]) -> List[ClassifiedTransaction]:
    """Classify all transactions and detect recurring patterns."""
    classified = [classify_transaction(txn) for txn in transactions]
    _detect_recurring(classified)
    return classified


def _normalize_counterparty(name: str) -> str:
    """Normalize counterparty name for recurring detection."""
    s = name.lower().strip()
    s = re.sub(r"\s+", " ", s)
    # Remove account numbers and references
    s = re.sub(r"\d{10,}", "", s)
    s = re.sub(r"ref\s*:.*", "", s)
    return s.strip()


def _detect_recurring(classified: List[ClassifiedTransaction], tolerance_days: int = 5) -> None:
    """Detect recurring transactions (same counterparty, similar amount, monthly).

    Marks transactions as recurring if the same counterparty appears
    at roughly monthly intervals (±tolerance_days).
    """
    from collections import defaultdict
    from datetime import datetime

    # Group by normalized counterparty + rough amount
    groups: Dict[str, List[ClassifiedTransaction]] = defaultdict(list)
    for ct in classified:
        if ct.transaction.direction != "out":
            continue
        cp = _normalize_counterparty(ct.transaction.counterparty or ct.transaction.title)
        if not cp or len(cp) < 3:
            continue
        # Round amount to nearest 10 for grouping
        amt_bucket = round(abs(ct.transaction.amount) / 10) * 10
        key = f"{cp}|{amt_bucket}"
        groups[key].append(ct)

    for key, txns in groups.items():
        if len(txns) < 2:
            continue

        # Check if transactions are roughly monthly apart
        dates = []
        for ct in txns:
            try:
                dates.append(datetime.strptime(ct.transaction.date, "%Y-%m-%d"))
            except ValueError:
                continue

        if len(dates) < 2:
            continue

        dates.sort()
        intervals = [(dates[i + 1] - dates[i]).days for i in range(len(dates) - 1)]

        # Monthly: 25-35 days apart on average
        avg_interval = sum(intervals) / len(intervals)
        if 25 - tolerance_days <= avg_interval <= 35 + tolerance_days:
            for ct in txns:
                ct.is_recurring = True
                ct.recurring_group = key.split("|")[0]
