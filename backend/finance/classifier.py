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
        "exchange_polish": [
            # Polish crypto exchanges
            r"\bzonda\b", r"zonda\.exchange", r"zonda\s*sp",
            r"\bbitbay\b",  # old name of Zonda
            r"\bkanga\b", r"kanga\s*exchange",
            r"\bcoindeal\b",
            r"\begera\b",  # Polish exchange
        ],
        "exchange_global": [
            r"\bbinance\b", r"\bcoinbase\b",
            r"\bbybit\b", r"\bkraken\b", r"\bbitget\b", r"\bkucoin\b",
            r"gate\.io", r"crypto\.com", r"\bbitstamp\b", r"\bgemini\b",
            r"\bokx\b", r"\bhtx\b", r"\bhuobi\b",
            r"\bbitfinex\b", r"\bcoinflex\b",
            r"\bbitpanda\b", r"\bcoinmate\b",
            r"\buphold\b", r"\bnexo\b",
        ],
        "payment": [
            r"\bsimplex\b", r"\bmoonpay\b", r"\btransak\b",
            r"ramp\s*network", r"\bwyre\b", r"\bbanxa\b",
            r"\bpaybis\b", r"\bchangelly\b",
        ],
        "keyword": [
            r"kryptowalut", r"bitcoin", r"\bbtc\b", r"\beth\b",
            r"\busdt\b", r"\busdc\b", r"blockchain", r"token",
            r"wallet.*crypto", r"crypto.*wallet",
            r"exchange.*crypto", r"crypto.*exchange",
            r"\bdefi\b", r"\bnft\b",
        ],
    },
    "gambling": {
        "bookmaker": [
            r"\bsts\b", r"sts\.pl", r"\bbetclic\b", r"\bfortuna\b",
            r"\bsuperbet\b", r"\blvbet\b", r"\bbetfan\b", r"\btotalbet\b",
            r"\bbetsson\b", r"\bunibet\b", r"\bbet365\b", r"\bnoblebet\b",
            r"\bewinner\b", r"\bfuksiarz\b", r"\bbetters\b",
            r"\bbetx\b", r"\bpzbuk\b", r"\btotolotek\b",
            r"\bforbet\b", r"\bgoplusbet\b",
            r"\bbetway\b", r"\b1xbet\b", r"\bpinnacle\b",
            r"\bbwin\b", r"\bwilliamhill\b", r"william\s*hill",
        ],
        "casino": [
            r"casino", r"kasyno", r"\bslot[sy]?\b", r"\bpoker\b",
            r"total\s*casino", r"\bruleta\b", r"\broulette\b",
            r"\bicebet\b", r"\bvulkan\b", r"\b22bet\b",
        ],
        "lottery": [
            r"\blotto\b", r"toto.*lotek", r"eurojackpot",
            r"multi\s*multi", r"\bzdrapk", r"los.*loteri",
            r"mini\s*lotto", r"\bkeno\b",
        ],
        "keyword": [
            r"bukmacher", r"zak[łl]ad.*sport", r"hazard",
            r"gra.*online", r"gambling", r"obstawianie",
        ],
    },
    "loans": {
        "payday": [
            r"\bvivus\b", r"\bwonga\b", r"\bprovident\b", r"\bincredit\b",
            r"\blendon\b", r"\bsmartney\b", r"\baasa\b", r"\bferratum\b",
            r"\bzaplo\b", r"\bnetcredit\b", r"\bfilarum\b", r"\bsolcredit\b",
            r"\balegotowka\b", r"pozyczkomat", r"chwil[oó]wk",
            r"kuki\.pl", r"\bhapipozyczki\b", r"extra\s*portfel",
            r"\bcashper\b", r"\bwandoo\b", r"\bkredito24\b",
            r"\bmonedo\b", r"\btengo\b",
        ],
        "installment": [
            r"\brata\b", r"rat[ay]\s*(kredyt|po[żz]yczk)",
            r"sp[łl]ata\s*(kredyt|po[żz]yczk|rat)",
            r"\bleasing\b", r"alior.*rata", r"santander.*rata",
        ],
        "mortgage": [
            r"kredyt\s*mieszk", r"kredyt\s*hipotecz",
            r"hipoteka", r"mortgage",
        ],
        "debt_collection": [
            r"windykac", r"komorni", r"egzekuc",
            r"kruk\s*s\.?a", r"\bbest\s*s\.?a\b",
            r"ultimo", r"intrum", r"hoist\s*finance",
            r"debt.*collect",
        ],
        "keyword": [
            r"po[żz]yczk", r"kredyt(?!\s*mieszk|\s*hipotecz)",
        ],
    },
    "transfers": {
        "salary": [
            r"wynagrodzeni", r"pensj[aę]", r"wyp[łl]ata",
            r"premia", r"zasi[łl]ek", r"zleceni.*umow",
        ],
        "benefits": [
            r"\bzus\b", r"\bkrus\b", r"500\s*plus", r"800\s*plus",
            r"rodzinn", r"alimenty", r"stypend",
            r"zasi[łl]ek.*bezrobot",
        ],
        "rent": [
            r"czynsz", r"najem", r"wynaj[eę]", r"op[łl]ata.*mieszk",
            r"wsp[oó]lnota\s*mieszk", r"sp[oó][łl]dzielni",
        ],
        "utilities": [
            r"energi[ae]|energa|tauron|\bpge\b|enea|innogy|e\.?on",
            r"gaz.*pgnig|pgnig|polsk.*gaz",
            r"wod.*kan|wodoci[ąa]g|mpwik",
            r"ogrze|ciep[łl]o",
        ],
        "telecom": [
            r"\borange\b|t-mobile|plus.*gsm|\bplay\b|vectra",
            r"\bupc\b|polsat.*box|canal.*plus|netflix|spotify",
            r"\bhbo\b|disney|amazon.*prime|youtube.*prem",
        ],
        "insurance": [
            r"ubezpiecz|polisa|\bpzu\b|warta|ergo\s*hestia",
            r"allianz|aviva|generali|compensa|uniqa",
            r"\boc\s.*pojazd|\bac\s.*pojazd|\bnnw\b",
        ],
    },
    "risky": {
        "foreign_transfer": [
            r"western\s*union", r"moneygram", r"ria\s*money",
            r"remitly", r"wise.*transfer", r"transferwise",
            r"\bswift\b.*przelew|przelew.*\bswift\b",
            r"przelew\s*zagraniczny|zagraniczny\s*przelew",
        ],
        "pawnshop": [
            r"lombard", r"zastaw", r"skup\s*z[łl]ota",
            r"skup.*srebr", r"komis\s*z[łl]ota",
        ],
        "p2p_lending": [
            r"\bmintos\b", r"\bbondora\b", r"\btwino\b",
            r"\bpeerberry\b", r"\bestateguru\b",
            r"\brobocash\b",
        ],
        "suspicious_pattern": [
            # Services commonly used for money movement
            r"\brevolut\b.*przelew|przelew.*\brevolut\b",
            r"\bskrill\b", r"\bneteller\b",
            r"\bpaysera\b", r"\bpaypal\b.*przelew",
        ],
    },
}

# --- URL extraction and domain classification ---

_URL_RE = re.compile(r"https?://[^\s,;\"'<>]+", re.I)

# Map known domains to (category, subcategory)
_DOMAIN_CATEGORIES: Dict[str, tuple] = {
    # Gambling
    "lotto.pl": ("gambling", "lottery"),
    "www.lotto.pl": ("gambling", "lottery"),
    "sts.pl": ("gambling", "bookmaker"),
    "www.sts.pl": ("gambling", "bookmaker"),
    "betclic.pl": ("gambling", "bookmaker"),
    "www.betclic.pl": ("gambling", "bookmaker"),
    "fortuna.pl": ("gambling", "bookmaker"),
    "www.fortuna.pl": ("gambling", "bookmaker"),
    "superbet.pl": ("gambling", "bookmaker"),
    "totalbet.pl": ("gambling", "bookmaker"),
    "betfan.pl": ("gambling", "bookmaker"),
    "lvbet.pl": ("gambling", "bookmaker"),
    "totalcasino.pl": ("gambling", "casino"),
    # Crypto
    "zonda.exchange": ("crypto", "exchange_polish"),
    "www.zonda.exchange": ("crypto", "exchange_polish"),
    "bitbay.net": ("crypto", "exchange_polish"),
    "kanga.exchange": ("crypto", "exchange_polish"),
    "binance.com": ("crypto", "exchange_global"),
    "www.binance.com": ("crypto", "exchange_global"),
    "coinbase.com": ("crypto", "exchange_global"),
    "bybit.com": ("crypto", "exchange_global"),
    "kraken.com": ("crypto", "exchange_global"),
    "crypto.com": ("crypto", "exchange_global"),
    # Risky / suspicious
    "skrill.com": ("risky", "suspicious_pattern"),
    "neteller.com": ("risky", "suspicious_pattern"),
    "paysera.com": ("risky", "suspicious_pattern"),
}


def _extract_domain(url: str) -> str:
    """Extract domain from URL."""
    url = url.lower().rstrip("/")
    # Remove protocol
    if "://" in url:
        url = url.split("://", 1)[1]
    # Remove path
    domain = url.split("/")[0]
    # Remove port
    domain = domain.split(":")[0]
    return domain


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
    entity_flagged: bool = False  # flagged in entity memory
    entity_type: str = ""  # type from entity memory
    entity_notes: str = ""  # user notes from entity memory
    urls: List[str] = field(default_factory=list)  # all URLs found in transaction text
    unclassified_urls: List[str] = field(default_factory=list)  # URLs not matching known domains

    def to_dict(self) -> Dict[str, Any]:
        d = self.transaction.to_dict()
        d["categories"] = self.categories
        d["subcategories"] = self.subcategories
        d["confidence"] = self.confidence
        d["is_recurring"] = self.is_recurring
        d["recurring_group"] = self.recurring_group
        d["entity_flagged"] = self.entity_flagged
        d["entity_type"] = self.entity_type
        d["entity_notes"] = self.entity_notes
        d["urls"] = self.urls
        d["unclassified_urls"] = self.unclassified_urls
        return d


def classify_transaction(txn: RawTransaction, entity_memory=None) -> ClassifiedTransaction:
    """Classify a single transaction using rules + entity memory + URL analysis."""
    _ensure_compiled()

    search_text = f"{txn.counterparty} {txn.title} {txn.raw_text}".lower()
    cats: Set[str] = set()
    subcats: Set[str] = set()

    for category, subcat, pattern in _COMPILED_RULES:
        if pattern.search(search_text):
            cats.add(category)
            subcats.add(f"{category}:{subcat}")

    # Extract and classify URLs from transaction text
    found_urls: List[str] = _URL_RE.findall(f"{txn.counterparty} {txn.title} {txn.raw_text}")
    unclassified_urls: List[str] = []
    for url in found_urls:
        domain = _extract_domain(url)
        if domain in _DOMAIN_CATEGORIES:
            cat, subcat = _DOMAIN_CATEGORIES[domain]
            cats.add(cat)
            subcats.add(f"{cat}:{subcat}")
        else:
            unclassified_urls.append(url)

    # Check entity memory
    entity_flagged = False
    entity_type = ""
    entity_notes = ""
    if entity_memory is not None:
        cp_name = txn.counterparty or txn.title
        ent = entity_memory.lookup(cp_name)
        if ent is not None:
            entity_flagged = ent.flagged
            entity_type = ent.entity_type
            entity_notes = ent.notes
            # If entity has a known type, add it as category
            if ent.entity_type and ent.entity_type not in ("legitimate", "unknown"):
                cats.add(ent.entity_type)
                subcats.add(f"{ent.entity_type}:memory")

    return ClassifiedTransaction(
        transaction=txn,
        categories=sorted(cats),
        subcategories=sorted(subcats),
        confidence=1.0 if cats else 0.0,
        entity_flagged=entity_flagged,
        entity_type=entity_type,
        entity_notes=entity_notes,
        urls=found_urls,
        unclassified_urls=unclassified_urls,
    )


def classify_all(transactions: List[RawTransaction], entity_memory=None) -> List[ClassifiedTransaction]:
    """Classify all transactions and detect recurring patterns."""
    classified = [classify_transaction(txn, entity_memory) for txn in transactions]
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
