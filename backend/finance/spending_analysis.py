"""Spending pattern analysis for enriched finance prompt.

Analyzes classified transactions to extract:
- Top shopping destinations with frequency %
- Fuel/gas station analysis (city, home vs travel)
- BLIK transaction classification (phone transfer vs online purchase)
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .classifier import ClassifiedTransaction


# --- Shop/merchant detection ---

# Known retail chains in Poland (name -> canonical name)
_RETAIL_CHAINS: Dict[str, str] = {
    r"biedronka": "Biedronka",
    r"lidl": "Lidl",
    r"kaufland": "Kaufland",
    r"auchan": "Auchan",
    r"carrefour": "Carrefour",
    r"tesco": "Tesco",
    r"netto": "Netto",
    r"dino": "Dino",
    r"\.zabka|żabka|zabka": "Żabka",
    r"stokrotka": "Stokrotka",
    r"lewiatan": "Lewiatan",
    r"spar\b": "Spar",
    r"polo\s*market": "Polo Market",
    r"intermarche|intermarch[eé]": "Intermarché",
    r"makro": "Makro",
    r"selgros": "Selgros",
    r"pepco": "Pepco",
    r"action\b": "Action",
    r"rossmann": "Rossmann",
    r"hebe\b": "Hebe",
    r"dm\s*drogerie|dm\.de": "dm",
    r"media\s*markt": "Media Markt",
    r"media\s*expert": "Media Expert",
    r"rtv\s*euro\s*agd": "RTV Euro AGD",
    r"x-?kom|x\s*kom": "x-kom",
    r"komputronik": "Komputronik",
    r"empik": "Empik",
    r"ikea": "IKEA",
    r"leroy\s*merlin": "Leroy Merlin",
    r"castorama": "Castorama",
    r"obi\b": "OBI",
    r"bricomarche|bricoman": "Bricomarché",
    r"decathlon": "Decathlon",
    r"h\s*&\s*m\b|h\s*and\s*m": "H&M",
    r"zara\b": "Zara",
    r"reserved\b": "Reserved",
    r"ccc\b": "CCC",
    r"deichmann": "Deichmann",
    r"smyk": "Smyk",
    r"allegro": "Allegro",
    r"amazon": "Amazon",
    r"aliexpress|ali\s*express": "AliExpress",
    r"temu\b": "Temu",
    r"shein": "Shein",
    r"zalando": "Zalando",
    r"morele\.net|morele": "Morele.net",
    r"ceneo": "Ceneo",
    r"inpost": "InPost",
    r"mcdonalds|mcdonald|mcd\b": "McDonald's",
    r"kfc\b": "KFC",
    r"burger\s*king": "Burger King",
    r"starbucks": "Starbucks",
    r"costa\s*coffee": "Costa Coffee",
    r"subway\b": "Subway",
}

# Fuel station chains
_FUEL_STATIONS: Dict[str, str] = {
    r"orlen|pkn\s*orlen|blisko": "Orlen",
    r"bp\b|bp\s+": "BP",
    r"shell\b": "Shell",
    r"circle\s*k|statoil": "Circle K",
    r"lotos|lotos\s*paliwa": "Lotos",
    r"moya\b": "MOYA",
    r"amic\s*energy|amic": "Amic Energy",
    r"total\s*energies|total\b": "TotalEnergies",
    r"intermarche.*paliw|intermarch.*fuel": "Intermarché (paliwo)",
    r"auchan.*paliw|auchan.*fuel": "Auchan (paliwo)",
    r"tesco.*paliw|tesco.*fuel": "Tesco (paliwo)",
    r"carrefour.*paliw": "Carrefour (paliwo)",
    r"paliw|fuel|tankow|benzyn|diesel|stacja\s*benzynowa": "Stacja paliw (inna)",
}

# BLIK patterns
_BLIK_PHONE_PATTERNS = [
    r"przelew\s*(na|z)\s*telefon",
    r"blik\s*(przelew|transfer|na\s*telefon|z\s*telefonu)",
    r"przelew\s*blik\s*(na|z)\s*tel",
    r"przelew\s*mobilny",
]

_BLIK_PURCHASE_PATTERNS = [
    r"blik\s*(zakup|platnosc|płatność|p[łl]atno[śs][ćc])",
    r"zakup\s*blik",
    r"transakcja\s*blik",
    r"p[łl]atno[śs][ćc]\s*blik",
    r"blik\s*(?:w\s+)?(?:sklepie|internecie|online)",
]

# City extraction from transaction text
_CITY_PATTERNS = [
    # "STACJA ORLEN WARSZAWA" or "BP KRAKÓW UL. ..."
    r"(?:stacja|sklep|market|punkt)?\s*(?:\w+)\s+([A-ZĄĆĘŁŃÓŚŹŻ][a-ząćęłńóśźż]{2,}(?:\s+[A-ZĄĆĘŁŃÓŚŹŻ][a-ząćęłńóśźż]{2,})?)\s*(?:ul\.?|al\.?|pl\.?|os\.?|$)",
    # City after station name: "ORLEN WARSZAWA" "BP KRAKOW"
    r"(?:orlen|bp|shell|circle\s*k|lotos|moya|amic)\s+([A-ZĄĆĘŁŃÓŚŹŻ][a-ząćęłńóśźż]{2,}(?:\s+[A-ZĄĆĘŁŃÓŚŹŻ][a-ząćęłńóśźż]{2,})?)",
    # "ADRES: MIASTO"
    r"(?:adres|miasto|lokalizacja)\s*:?\s*([A-ZĄĆĘŁŃÓŚŹŻ][a-ząćęłńóśźż]{2,})",
]

# Known Polish cities for validation
_KNOWN_CITIES = {
    "warszawa", "kraków", "krakow", "łódź", "lodz", "wrocław", "wroclaw",
    "poznań", "poznan", "gdańsk", "gdansk", "szczecin", "bydgoszcz",
    "lublin", "białystok", "bialystok", "katowice", "gdynia", "częstochowa",
    "czestochowa", "radom", "sosnowiec", "toruń", "torun", "kielce",
    "rzeszów", "rzeszow", "gliwice", "zabrze", "olsztyn", "bielsko",
    "bytom", "zielona góra", "zielona gora", "rybnik", "ruda śląska",
    "tychy", "opole", "gorzów", "gorzow", "dąbrowa", "dabrowa",
    "elbląg", "elblag", "płock", "plock", "wałbrzych", "walbrzych",
    "włocławek", "wloclawek", "tarnów", "tarnow", "chorzów", "chorzow",
    "koszalin", "legnica", "kalisz", "grudziądz", "grudziadz",
    "jaworzno", "słupsk", "slupsk", "jastrzębie", "nowy sącz",
    "jelenia góra", "siedlce", "mysłowice", "konin", "piła", "pila",
    "ostrów", "ostrow", "stargard", "gniezno", "ostrołęka", "siemianowice",
    "suwałki", "suwalki", "chełm", "chelm", "piotrków", "piotrkow",
    "zamość", "zamosc", "pruszków", "pruszkow",
}


@dataclass
class ShopFrequency:
    """Single shop with purchase frequency."""
    name: str
    count: int
    percentage: float  # % of all shopping transactions
    total_amount: float = 0.0


@dataclass
class FuelAnalysis:
    """Fuel station visit analysis."""
    station: str
    city: str = ""
    count: int = 0
    total_amount: float = 0.0
    is_home_city: bool = False  # True if city matches most-frequent shopping city


@dataclass
class BlikTransaction:
    """Classified BLIK transaction."""
    date: str
    amount: float
    counterparty: str
    blik_type: str  # "phone_transfer" or "online_purchase" or "payment"
    title: str = ""


@dataclass
class BlikPersonSummary:
    """Aggregated BLIK P2P transfer summary per person."""
    name: str
    transfer_count: int = 0
    total_amount: float = 0.0
    last_date: str = ""


@dataclass
class StandingOrderSummary:
    """Aggregated standing order (ST.ZLEC) summary per recipient."""
    recipient: str
    count: int = 0
    total_amount: float = 0.0
    avg_amount: float = 0.0
    categories: List[str] = field(default_factory=list)
    is_classified: bool = False


@dataclass
class SpendingReport:
    """Complete spending analysis report."""
    top_shops: List[ShopFrequency] = field(default_factory=list)
    fuel_visits: List[FuelAnalysis] = field(default_factory=list)
    fuel_home_city: str = ""
    fuel_travel_cities: List[str] = field(default_factory=list)
    blik_transactions: List[BlikTransaction] = field(default_factory=list)
    blik_phone_transfers: int = 0
    blik_online_purchases: int = 0
    blik_other_payments: int = 0
    blik_p2p_persons: List[BlikPersonSummary] = field(default_factory=list)
    standing_orders: List[StandingOrderSummary] = field(default_factory=list)
    total_shopping_txns: int = 0


def _match_merchant(search_text: str, patterns: Dict[str, str]) -> Optional[str]:
    """Match text against pattern dict, return canonical name or None."""
    for pattern, name in patterns.items():
        if re.search(pattern, search_text, re.I):
            return name
    return None


def _extract_city(text: str) -> str:
    """Try to extract city name from transaction text."""
    text_upper = text.strip()
    # Try specific patterns first
    for pattern in _CITY_PATTERNS:
        m = re.search(pattern, text_upper, re.I)
        if m:
            candidate = m.group(1).strip()
            if candidate.lower() in _KNOWN_CITIES:
                return candidate.title()
            # Check 2-word cities
            words = candidate.lower().split()
            if len(words) >= 1 and words[0] in _KNOWN_CITIES:
                return words[0].title()

    # Brute force: check if any known city appears in text
    text_lower = text.lower()
    for city in _KNOWN_CITIES:
        if re.search(r"\b" + re.escape(city) + r"\b", text_lower):
            return city.title()

    return ""


def _classify_blik(txn: ClassifiedTransaction) -> Optional[BlikTransaction]:
    """Classify a BLIK transaction. Returns None if not BLIK."""
    search_text = f"{txn.transaction.counterparty} {txn.transaction.title} {txn.transaction.raw_text}".lower()

    # Check bank_category first (more reliable than text matching for ING)
    is_blik_by_code = txn.transaction.bank_category.upper() == "P.BLIK" if txn.transaction.bank_category else False

    # Must contain "blik" keyword or have P.BLIK bank_category
    if not is_blik_by_code and "blik" not in search_text:
        return None

    # Check phone transfer patterns
    for p in _BLIK_PHONE_PATTERNS:
        if re.search(p, search_text, re.I):
            return BlikTransaction(
                date=txn.transaction.date,
                amount=txn.transaction.amount,
                counterparty=txn.transaction.counterparty or txn.transaction.title,
                blik_type="phone_transfer",
                title=txn.transaction.title,
            )

    # P.BLIK with "Przelew na telefon" in title → phone transfer
    if is_blik_by_code and re.search(r"przelew\s*(na|z)\s*telefon", search_text, re.I):
        return BlikTransaction(
            date=txn.transaction.date,
            amount=txn.transaction.amount,
            counterparty=txn.transaction.counterparty or txn.transaction.title,
            blik_type="phone_transfer",
            title=txn.transaction.title,
        )

    # Check purchase patterns
    for p in _BLIK_PURCHASE_PATTERNS:
        if re.search(p, search_text, re.I):
            return BlikTransaction(
                date=txn.transaction.date,
                amount=txn.transaction.amount,
                counterparty=txn.transaction.counterparty or txn.transaction.title,
                blik_type="online_purchase",
                title=txn.transaction.title,
            )

    # Generic BLIK — classify by context
    # If counterparty looks like a shop, it's purchase; otherwise payment
    merchant = _match_merchant(search_text, _RETAIL_CHAINS)
    if merchant:
        return BlikTransaction(
            date=txn.transaction.date,
            amount=txn.transaction.amount,
            counterparty=merchant,
            blik_type="online_purchase",
            title=txn.transaction.title,
        )

    return BlikTransaction(
        date=txn.transaction.date,
        amount=txn.transaction.amount,
        counterparty=txn.transaction.counterparty or txn.transaction.title,
        blik_type="payment",
        title=txn.transaction.title,
    )


def analyze_spending(classified: List[ClassifiedTransaction]) -> SpendingReport:
    """Analyze spending patterns from classified transactions.

    Returns:
        SpendingReport with top shops, fuel analysis, BLIK classification.
    """
    report = SpendingReport()

    # --- Collect shopping data ---
    shop_counter: Counter = Counter()
    shop_amounts: Dict[str, float] = {}
    fuel_data: Dict[str, Dict[str, Any]] = {}  # key: "station|city"
    all_shopping_cities: Counter = Counter()  # city -> purchase count

    outflow_txns = [ct for ct in classified if ct.transaction.direction == "out"]

    for ct in outflow_txns:
        search_text = f"{ct.transaction.counterparty} {ct.transaction.title} {ct.transaction.raw_text}".lower()

        # --- Fuel stations ---
        fuel_station = _match_merchant(search_text, _FUEL_STATIONS)
        if fuel_station:
            city = _extract_city(f"{ct.transaction.counterparty} {ct.transaction.title} {ct.transaction.raw_text}")
            key = f"{fuel_station}|{city}" if city else fuel_station
            if key not in fuel_data:
                fuel_data[key] = {"station": fuel_station, "city": city, "count": 0, "total": 0.0}
            fuel_data[key]["count"] += 1
            fuel_data[key]["total"] += abs(ct.transaction.amount)
            if city:
                all_shopping_cities[city] += 1
            continue  # Don't count fuel as shopping

        # --- BLIK (check before retail to properly classify BLIK purchases) ---
        blik = _classify_blik(ct)
        if blik:
            report.blik_transactions.append(blik)
            if blik.blik_type == "phone_transfer":
                report.blik_phone_transfers += 1
            elif blik.blik_type == "online_purchase":
                report.blik_online_purchases += 1
                # Also count BLIK online purchases in shop stats
                merchant = _match_merchant(search_text, _RETAIL_CHAINS)
                if merchant:
                    shop_counter[merchant] += 1
                    shop_amounts[merchant] = shop_amounts.get(merchant, 0.0) + abs(ct.transaction.amount)
            else:
                report.blik_other_payments += 1
            continue

        # --- Shopping / retail ---
        merchant = _match_merchant(search_text, _RETAIL_CHAINS)
        if merchant:
            shop_counter[merchant] += 1
            shop_amounts[merchant] = shop_amounts.get(merchant, 0.0) + abs(ct.transaction.amount)
            # Try to extract city for home-city detection
            city = _extract_city(f"{ct.transaction.counterparty} {ct.transaction.title} {ct.transaction.raw_text}")
            if city:
                all_shopping_cities[city] += 1
            continue

    # --- Build top shops ---
    total_shop_count = sum(shop_counter.values())
    report.total_shopping_txns = total_shop_count

    for name, count in shop_counter.most_common(5):
        pct = (count / total_shop_count * 100) if total_shop_count > 0 else 0.0
        report.top_shops.append(ShopFrequency(
            name=name,
            count=count,
            percentage=round(pct, 1),
            total_amount=round(shop_amounts.get(name, 0.0), 2),
        ))

    # --- Build fuel analysis ---
    # Determine home city (most frequent shopping city)
    home_city = ""
    if all_shopping_cities:
        home_city = all_shopping_cities.most_common(1)[0][0]
    report.fuel_home_city = home_city

    travel_cities: set = set()
    for key, data in sorted(fuel_data.items(), key=lambda x: -x[1]["count"]):
        city = data["city"]
        is_home = (city.lower() == home_city.lower()) if city and home_city else False
        fa = FuelAnalysis(
            station=data["station"],
            city=city,
            count=data["count"],
            total_amount=round(data["total"], 2),
            is_home_city=is_home,
        )
        report.fuel_visits.append(fa)
        if city and not is_home:
            travel_cities.add(city)

    report.fuel_travel_cities = sorted(travel_cities)

    # --- BLIK P2P person aggregation ---
    p2p_persons: Dict[str, Dict[str, Any]] = {}
    for bt in report.blik_transactions:
        if bt.blik_type == "phone_transfer":
            name = bt.counterparty.strip()
            if not name or len(name) < 2:
                continue
            key = name.lower()
            if key not in p2p_persons:
                p2p_persons[key] = {"name": name, "count": 0, "total": 0.0, "last_date": ""}
            p2p_persons[key]["count"] += 1
            p2p_persons[key]["total"] += abs(bt.amount)
            if bt.date > p2p_persons[key]["last_date"]:
                p2p_persons[key]["last_date"] = bt.date

    for data in sorted(p2p_persons.values(), key=lambda d: -d["total"]):
        report.blik_p2p_persons.append(BlikPersonSummary(
            name=data["name"],
            transfer_count=data["count"],
            total_amount=round(data["total"], 2),
            last_date=data["last_date"],
        ))

    # --- Standing order (ST.ZLEC) aggregation ---
    st_groups: Dict[str, Dict[str, Any]] = {}
    for ct in classified:
        if ct.transaction.bank_category and ct.transaction.bank_category.upper() == "ST.ZLEC":
            recipient = (ct.transaction.counterparty or ct.transaction.title).strip()
            if not recipient or len(recipient) < 2:
                continue
            key = recipient.lower()
            if key not in st_groups:
                st_groups[key] = {
                    "recipient": recipient,
                    "count": 0,
                    "total": 0.0,
                    "cats": set(),
                }
            st_groups[key]["count"] += 1
            st_groups[key]["total"] += abs(ct.transaction.amount)
            for cat in ct.categories:
                st_groups[key]["cats"].add(cat)

    for data in sorted(st_groups.values(), key=lambda d: -d["total"]):
        cats_list = sorted(data["cats"])
        report.standing_orders.append(StandingOrderSummary(
            recipient=data["recipient"],
            count=data["count"],
            total_amount=round(data["total"], 2),
            avg_amount=round(data["total"] / data["count"], 2) if data["count"] > 0 else 0.0,
            categories=cats_list,
            is_classified=bool(cats_list),
        ))

    return report
