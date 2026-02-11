"""Transaction enrichment for AML analysis.

Takes raw transactions from spatial_parser or mt940_parser and adds:
- Channel detection (karta, BLIK, przelew, gotówka, zlecenie stałe)
- Category classification (grocery, fuel, online, P2P, loan, fee, salary, etc.)
- Counterparty normalization
- Recurring pattern detection
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger("aistate.aml.enrich")


# ============================================================
# Channel detection from MT940 ~00 codes and swift codes
# ============================================================

_CHANNEL_BY_CODE_00 = {
    "VE02": "KARTA",
    "VE03": "GOTOWKA_ATM",
    "VE09": "PROWIZJA",
    "IK01": "BLIK",
    "IKZ1": "BLIK_ZWROT",
    "IBCG": "PRZELEW",
    "IBCB": "PRZELEW_WLASNY",
    "ZKCG": "ZLECENIE_STALE",
    "EXGC": "PRZELEW_PRZYCHODZACY",
    "DECC": "WPLATOMAT",
    "WDW5": "PRZELEW_TELEFON",
}

_CHANNEL_BY_SWIFT = {
    "073": "KARTA",
    "041": "BLIK",
    "020": "PRZELEW",
    "034": "PRZELEW_PRZYCHODZACY",
    "074": "ZLECENIE_STALE",
    "042": "GOTOWKA_ATM",
    "036": "PROWIZJA",
    "076": "PRZELEW_TELEFON",
}

CHANNEL_LABELS_PL = {
    "KARTA": "Platnosc karta",
    "BLIK": "Platnosc BLIK",
    "BLIK_ZWROT": "Zwrot BLIK",
    "PRZELEW": "Przelew",
    "PRZELEW_WLASNY": "Przelew wlasny",
    "PRZELEW_PRZYCHODZACY": "Przelew przychodzacy",
    "ZLECENIE_STALE": "Zlecenie stale",
    "GOTOWKA_ATM": "Wyplata z bankomatu",
    "WPLATOMAT": "Wplatomat",
    "PRZELEW_TELEFON": "Przelew na telefon",
    "PROWIZJA": "Prowizja/oplata",
    "INNE": "Inne",
}


# ============================================================
# Category detection from counterparty names
# ============================================================

_CATEGORY_PATTERNS: List[Tuple[str, str, List[str]]] = [
    # (category_id, label_pl, [regex patterns matching counterparty name])
    ("grocery", "Spozywcze", [
        r"biedronka", r"lidl", r"aldi", r"netto", r"leclerc",
        r"zabka", r"lewiatan", r"stokrotka", r"dino", r"intermarche",
        r"delikatesy", r"grot\b", r"spolem", r"jas\s*i\s*malgosia",
    ]),
    ("bakery", "Piekarnia", [
        r"piekar", r"cukiernia", r"oskroba",
    ]),
    ("fuel", "Paliwo", [
        r"orlen", r"bp\b", r"shell", r"circle\s*k", r"lotos", r"amic",
        r"moya", r"stacja\s*nr",
    ]),
    ("pharmacy", "Apteka", [
        r"apteka", r"apteczka", r"rossmann", r"dm-drogerie",
    ]),
    ("clothing", "Odziez", [
        r"ccc\b", r"pepco", r"reserved", r"h&m", r"zara",
        r"sinsay", r"house\b", r"cropp",
    ]),
    ("diy", "Dom/ogrod", [
        r"leroy\s*merlin", r"castorama", r"obi\b", r"bricomarche",
        r"ikea", r"action\b",
    ]),
    ("children", "Dzieci", [
        r"bananovo", r"sala\s*zabaw", r"smyk", r"toys",
        r"zlobek", r"przedszkol",
    ]),
    ("online_shop", "Zakupy online", [
        r"allegro", r"amazon", r"aliexpress", r"alipay",
        r"temu", r"shein",
    ]),
    ("food_service", "Gastronomia", [
        r"chilli\s*bar", r"mcdonald", r"kfc\b", r"pizza",
        r"uber\s*eat", r"pyszne", r"stolowka", r"z\s*pieca\s*rodem",
    ]),
    ("transport", "Transport", [
        r"uber\b(?!\s*eat)", r"bolt\b", r"taxi", r"mpk\b",
    ]),
    ("medical", "Medyczne", [
        r"praktykalekars", r"apteka", r"dentyst", r"medycyn",
        r"lekarz", r"klinik",
    ]),
    ("salary", "Wynagrodzenie", [
        r"uposaz", r"wynagrodzeni", r"swiadczeni", r"pensj",
        r"jw\s*\d+",  # JW 1406 = military unit
    ]),
    ("loan_payment", "Rata/kredyt", [
        r"umowa\s*na\s*kredyt", r"ikanobank", r"rata\b",
        r"provident", r"wonga", r"vivus",
    ]),
    ("insurance", "Ubezpieczenie", [
        r"warta", r"pzu\b", r"ergo\s*hestia", r"allianz",
        r"eagent", r"ubezpiecz",
    ]),
    ("utility", "Rachunki", [
        r"pgnig", r"pge\b", r"enea", r"tauron",
        r"wod.*kan", r"mpo\b", r"gospodar.*odpad",
    ]),
    ("rent_housing", "Mieszkanie", [
        r"czynsz", r"mieszk", r"solid\s*group",
    ]),
    ("telecom", "Telekomunikacja", [
        r"orange", r"play\b", r"plus\b", r"t-mobile",
        r"google.*play", r"apple",
    ]),
    ("delivery", "Kurier/przesylki", [
        r"furgonetka", r"inpost", r"dpd\b", r"ups\b",
        r"poczt", r"paczkomat",
    ]),
    ("own_transfer", "Przelew wlasny", [
        r"przelew\s*wlasn", r"przelew\s*wasn", r"lokata",
    ]),
    ("fee", "Prowizja/oplata", [
        r"prowizj", r"oplat",
    ]),
    ("cash", "Gotowka", [
        r"wyplat.*got", r"wplatomat", r"bankomat",
        r"planet\s*cash",
    ]),
    ("car_wash", "Myjnia", [
        r"myjnia",
    ]),
    ("auto_service", "Serwis auto", [
        r"skp\b", r"auto\s*complex", r"mechanik", r"wulkaniz",
    ]),
]


def detect_channel(tx: Dict[str, Any]) -> str:
    """Detect transaction channel from MT940 codes or title patterns."""
    # From MT940 ~00 code (stored in raw_86)
    raw_86 = tx.get("raw_86", "")
    if raw_86:
        for code, channel in _CHANNEL_BY_CODE_00.items():
            if code in raw_86:
                return channel

    # From swift code
    swift = tx.get("swift_code", "")
    if swift and swift in _CHANNEL_BY_SWIFT:
        return _CHANNEL_BY_SWIFT[swift]

    # From title patterns (PDF-parsed)
    title = (tx.get("title", "") + " " + tx.get("counterparty", "")).lower()
    if re.search(r"p[lł]atno[sś][cć]\s*kart[aą]|nr\s*karty", title):
        return "KARTA"
    if re.search(r"blik|nr\s*transakcji", title):
        return "BLIK"
    if re.search(r"przelew\s*na\s*telefon", title):
        return "PRZELEW_TELEFON"
    if re.search(r"wyp[lł]at.*got[oó]wk", title):
        return "GOTOWKA_ATM"
    if re.search(r"wp[lł]atomat", title):
        return "WPLATOMAT"
    if re.search(r"zleceni|umowa\s*na\s*kredyt", title):
        return "ZLECENIE_STALE"
    if re.search(r"prowizj", title):
        return "PROWIZJA"

    return "INNE"


def detect_category(tx: Dict[str, Any]) -> Tuple[str, str]:
    """Detect transaction category from counterparty name and title.

    Returns (category_id, category_label_pl).
    """
    text = (
        tx.get("counterparty", "") + " " +
        tx.get("title", "") + " " +
        tx.get("counterparty_account", "")
    ).lower()

    for cat_id, label, patterns in _CATEGORY_PATTERNS:
        for pat in patterns:
            if re.search(pat, text):
                return cat_id, label

    return "unclassified", "Nieskategoryzowane"


# ============================================================
# Recurring transaction detection
# ============================================================

@dataclass
class RecurringGroup:
    """A group of recurring transactions to the same counterparty."""
    counterparty: str
    category: str
    count: int
    total_amount: float
    avg_amount: float
    amounts: List[float]
    dates: List[str]
    channel: str = ""


def detect_recurring(transactions: List[Dict[str, Any]], min_count: int = 2) -> List[RecurringGroup]:
    """Detect recurring transactions (same counterparty, similar amounts)."""
    # Group by normalized counterparty
    groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for tx in transactions:
        cp = _normalize_counterparty(tx.get("counterparty", ""))
        if cp and len(cp) > 2:
            groups[cp].append(tx)

    recurring = []
    for cp, txs in groups.items():
        if len(txs) < min_count:
            continue

        amounts = [abs(tx.get("amount", 0)) for tx in txs]
        dates = [tx.get("date", "") for tx in txs]
        total = sum(amounts)
        avg = total / len(amounts)

        cat_id = txs[0].get("category", "unclassified")
        channel = txs[0].get("channel", "INNE")

        recurring.append(RecurringGroup(
            counterparty=cp,
            category=cat_id,
            count=len(txs),
            total_amount=round(total, 2),
            avg_amount=round(avg, 2),
            amounts=amounts,
            dates=dates,
            channel=channel,
        ))

    # Sort by total amount descending
    recurring.sort(key=lambda g: -g.total_amount)
    return recurring


def _normalize_counterparty(name: str) -> str:
    """Normalize counterparty name for grouping."""
    name = name.strip().upper()
    # Remove trailing whitespace and location
    name = re.sub(r"\s{2,}.*$", "", name)
    # Remove common suffixes
    name = re.sub(r"\s*(SP\.?\s*Z\s*O\.?O\.?|S\.?A\.?|SPO[LŁ]KA)\s*$", "", name, flags=re.IGNORECASE)
    return name.strip()


# ============================================================
# Full enrichment pipeline
# ============================================================

@dataclass
class EnrichedResult:
    """Result of transaction enrichment."""
    transactions: List[Dict[str, Any]]
    channel_summary: Dict[str, Dict[str, Any]]  # channel -> {count, total, label}
    category_summary: Dict[str, Dict[str, Any]]  # category -> {count, total, label}
    recurring: List[RecurringGroup]
    top_counterparties: List[Dict[str, Any]]
    stats: Dict[str, Any]


def enrich_transactions(
    transactions: List[Dict[str, Any]],
    statement_info: Optional[Dict[str, Any]] = None,
) -> EnrichedResult:
    """Enrich a list of raw transactions with channel, category, and patterns.

    Works with both spatial_parser and mt940_parser output format.
    """
    enriched_txs = []
    channel_counts: Dict[str, int] = defaultdict(int)
    channel_amounts: Dict[str, float] = defaultdict(float)
    cat_counts: Dict[str, int] = defaultdict(int)
    cat_amounts: Dict[str, float] = defaultdict(float)
    cat_labels: Dict[str, str] = {}

    total_credits = 0.0
    total_debits = 0.0
    credit_count = 0
    debit_count = 0
    max_tx = 0.0

    for tx in transactions:
        etx = dict(tx)  # copy

        # Channel
        channel = detect_channel(tx)
        etx["channel"] = channel
        amt = abs(tx.get("amount", 0))
        channel_counts[channel] += 1
        channel_amounts[channel] += amt

        # Category
        cat_id, cat_label = detect_category(tx)
        etx["category"] = cat_id
        etx["category_label"] = cat_label
        cat_counts[cat_id] += 1
        cat_amounts[cat_id] += amt
        cat_labels[cat_id] = cat_label

        # Stats
        direction = tx.get("direction", "")
        if not direction:
            direction = "CREDIT" if tx.get("amount", 0) >= 0 else "DEBIT"
            etx["direction"] = direction

        if direction == "CREDIT":
            total_credits += amt
            credit_count += 1
        else:
            total_debits += amt
            debit_count += 1

        if amt > max_tx:
            max_tx = amt

        enriched_txs.append(etx)

    # Channel summary
    channel_summary = {}
    for ch, cnt in sorted(channel_counts.items(), key=lambda x: -x[1]):
        channel_summary[ch] = {
            "count": cnt,
            "total": round(channel_amounts[ch], 2),
            "label": CHANNEL_LABELS_PL.get(ch, ch),
        }

    # Category summary
    category_summary = {}
    for cat, cnt in sorted(cat_counts.items(), key=lambda x: -cat_amounts[x[0]]):
        category_summary[cat] = {
            "count": cnt,
            "total": round(cat_amounts[cat], 2),
            "label": cat_labels.get(cat, cat),
        }

    # Recurring detection
    recurring = detect_recurring(enriched_txs)

    # Top counterparties
    cp_totals: Dict[str, float] = defaultdict(float)
    cp_counts: Dict[str, int] = defaultdict(int)
    for tx in enriched_txs:
        cp = tx.get("counterparty", "Nieznany")[:50]
        cp_totals[cp] += abs(tx.get("amount", 0))
        cp_counts[cp] += 1

    top_cps = sorted(cp_totals.items(), key=lambda x: -x[1])[:20]
    top_counterparties = [
        {"name": name, "total": round(total, 2), "count": cp_counts[name]}
        for name, total in top_cps
    ]

    # Stats
    tx_count = len(enriched_txs)
    stats = {
        "transaction_count": tx_count,
        "total_credits": round(total_credits, 2),
        "total_debits": round(total_debits, 2),
        "credit_count": credit_count,
        "debit_count": debit_count,
        "net_flow": round(total_credits - total_debits, 2),
        "avg_transaction": round((total_credits + total_debits) / max(tx_count, 1), 2),
        "max_transaction": round(max_tx, 2),
    }

    return EnrichedResult(
        transactions=enriched_txs,
        channel_summary=channel_summary,
        category_summary=category_summary,
        recurring=recurring,
        top_counterparties=top_counterparties,
        stats=stats,
    )
