"""Crypto user behavior profiling — classify user trading personality.

Analyzes transaction patterns to determine the most likely user profile:
  - retail_hodler     — long-term holder, few trades, spot only
  - scalper           — high-frequency, many small trades, high cancel rate
  - day_trader        — active daily trader, leverage, same-day buy/sell
  - swing_trader      — mid-term positions (days–weeks), moderate frequency
  - staker_validator  — staking rewards, low trading, stable portfolio
  - whale             — very large transaction values, multi-wallet
  - institutional     — systematic/algorithmic patterns, hedging, arbitrage
  - alpha_hunter      — many different tokens, early-stage, airdrops
  - meme_trader       — panic sells after drops, buys after pumps, volatile
  - bagholder         — long hold below entry, no sells, inactive

Each detected profile includes a confidence score (0–100) and reasons.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from .parsers.base import CryptoTransaction

log = logging.getLogger("aistate.crypto.behavior")


# ---------------------------------------------------------------------------
# Profile definitions
# ---------------------------------------------------------------------------

_PROFILES = {
    "retail_hodler": {
        "label": "Retail HODLer",
        "icon": "💎",
        "desc": "Długoterminowy posiadacz — kupuje i trzyma, mało handluje, brak dźwigni.",
    },
    "scalper": {
        "label": "Scalper",
        "icon": "⚡",
        "desc": "Ekstremalnie krótkoterminowy trader — wiele małych transakcji, szybkie wejścia/wyjścia.",
    },
    "day_trader": {
        "label": "Day Trader",
        "icon": "📊",
        "desc": "Aktywny handlarz dzienny — kilka-kilkadziesiąt transakcji dziennie, dźwignia, cel intraday.",
    },
    "swing_trader": {
        "label": "Swing Trader",
        "icon": "🔄",
        "desc": "Pozycje w skali dni–tygodni, celuje w większe ruchy cenowe (trendy).",
    },
    "staker_validator": {
        "label": "Staker / Validator",
        "icon": "🔒",
        "desc": "Blokuje tokeny w stakingu/delegacji, regularne nagrody, mało handlu.",
    },
    "whale": {
        "label": "Whale",
        "icon": "🐋",
        "desc": "Wielki gracz — bardzo duże transakcje, może wpływać na rynek.",
    },
    "institutional": {
        "label": "Instytucjonalny / Systemowy",
        "icon": "🏦",
        "desc": "Systematyczny trading, duży wolumen, hedging, arbitraż, algorytmy.",
    },
    "alpha_hunter": {
        "label": "Alpha Hunter",
        "icon": "🎯",
        "desc": "Poszukiwacz okazji — wiele różnych tokenów, early-stage, airdrops, testnety.",
    },
    "meme_trader": {
        "label": "Meme / Paper Hands",
        "icon": "🧻",
        "desc": "Impulsywny trader — panika po spadkach, kupuje w euforii, reaktywny.",
    },
    "bagholder": {
        "label": "Bagholder",
        "icon": "🎒",
        "desc": "Trzyma pozycje długo bez aktywności, prawdopodobnie poniżej ceny wejścia.",
    },
}


def _parse_ts(ts_str: str) -> Optional[datetime]:
    """Parse an ISO timestamp string to datetime."""
    if not ts_str:
        return None
    try:
        return datetime.strptime(ts_str[:19], "%Y-%m-%dT%H:%M:%S")
    except Exception:
        try:
            return datetime.strptime(ts_str[:10], "%Y-%m-%d")
        except Exception:
            return None


def _compute_metrics(txs: List[CryptoTransaction]) -> Dict[str, Any]:
    """Compute aggregate metrics from transactions for profiling."""
    m: Dict[str, Any] = {}

    if not txs:
        return m

    # Parse all timestamps
    timestamps = []
    for tx in txs:
        dt = _parse_ts(tx.timestamp)
        if dt:
            timestamps.append(dt)
    timestamps.sort()

    m["total_tx_count"] = len(txs)
    m["has_timestamps"] = len(timestamps) > 0

    if not timestamps:
        return m

    m["first_date"] = timestamps[0]
    m["last_date"] = timestamps[-1]
    span_days = max((timestamps[-1] - timestamps[0]).days, 1)
    m["span_days"] = span_days

    # ── Trading frequency ──
    m["tx_per_day"] = len(txs) / span_days
    m["tx_per_week"] = m["tx_per_day"] * 7

    # ── Type breakdown ──
    type_counts: Dict[str, int] = defaultdict(int)
    for tx in txs:
        type_counts[tx.tx_type] += 1
    m["type_counts"] = dict(type_counts)

    swap_count = type_counts.get("swap", 0)
    deposit_count = type_counts.get("deposit", 0) + type_counts.get("fiat_deposit", 0)
    withdrawal_count = type_counts.get("withdrawal", 0) + type_counts.get("fiat_withdrawal", 0)
    m["swap_count"] = swap_count
    m["deposit_count"] = deposit_count
    m["withdrawal_count"] = withdrawal_count

    # ── Token diversity ──
    unique_tokens = set()
    for tx in txs:
        if tx.token:
            unique_tokens.add(tx.token)
    m["unique_tokens"] = len(unique_tokens)

    # ── Amount statistics ──
    amounts = [float(tx.amount) for tx in txs if tx.amount > 0]
    if amounts:
        m["avg_amount"] = sum(amounts) / len(amounts)
        m["max_amount"] = max(amounts)
        m["total_volume"] = sum(amounts)
        large_threshold = m["avg_amount"] * 10
        m["large_tx_count"] = sum(1 for a in amounts if a > large_threshold)
    else:
        m["avg_amount"] = 0
        m["max_amount"] = 0
        m["total_volume"] = 0
        m["large_tx_count"] = 0

    # ── Daily activity ──
    daily_tx: Dict[str, int] = defaultdict(int)
    for dt in timestamps:
        daily_tx[dt.strftime("%Y-%m-%d")] += 1
    m["active_days"] = len(daily_tx)
    m["avg_tx_per_active_day"] = sum(daily_tx.values()) / max(len(daily_tx), 1)
    m["max_tx_per_day"] = max(daily_tx.values()) if daily_tx else 0
    m["activity_ratio"] = len(daily_tx) / span_days  # what fraction of days are active

    # ── Holding period estimation (time between buy and sell of same token) ──
    # Simplified: average time between deposits/buys and withdrawals/sells
    buy_times: Dict[str, List[datetime]] = defaultdict(list)
    sell_times: Dict[str, List[datetime]] = defaultdict(list)
    for tx in txs:
        dt = _parse_ts(tx.timestamp)
        if not dt or not tx.token:
            continue
        if tx.tx_type in ("deposit", "swap") and tx.raw.get("side", "") in ("BUY", ""):
            buy_times[tx.token].append(dt)
        elif tx.tx_type in ("withdrawal", "swap") and tx.raw.get("side", "") == "SELL":
            sell_times[tx.token].append(dt)

    holding_periods = []
    for token in buy_times:
        if token not in sell_times:
            continue
        for bt in buy_times[token]:
            for st in sell_times[token]:
                if st > bt:
                    holding_periods.append((st - bt).total_seconds() / 3600)
                    break

    if holding_periods:
        m["avg_holding_hours"] = sum(holding_periods) / len(holding_periods)
        m["median_holding_hours"] = sorted(holding_periods)[len(holding_periods) // 2]
    else:
        m["avg_holding_hours"] = span_days * 24  # assume held entire period
        m["median_holding_hours"] = span_days * 24

    # ── Leverage / margin / futures usage ──
    has_margin = any(tx.raw.get("sheet") == "Margin Order" or tx.raw.get("account", "").lower() == "margin"
                     for tx in txs)
    m["uses_leverage"] = has_margin

    # ── Staking / rewards ──
    staking_count = sum(1 for tx in txs if tx.category in ("staking_reward", "earn", "savings_interest",
                                                            "interest", "cashback", "referral_bonus"))
    m["staking_reward_count"] = staking_count

    # ── Card / spending ──
    card_count = sum(1 for tx in txs if tx.raw.get("sheet") == "Card Transaction")
    m["card_tx_count"] = card_count

    # ── Privacy coins ──
    _PRIVACY = {"XMR", "ZEC", "DASH", "SCRT", "BEAM", "GRIN", "FIRO"}
    privacy_count = sum(1 for tx in txs if tx.token in _PRIVACY)
    m["privacy_coin_tx_count"] = privacy_count

    # ── Airdrop detection ──
    airdrop_count = sum(1 for tx in txs if tx.category in ("airdrop",) or
                        "airdrop" in (tx.raw.get("category", "").lower()))
    m["airdrop_count"] = airdrop_count

    # ── Rapid sequences (trades within minutes) ──
    rapid_pairs = 0
    for i in range(1, len(timestamps)):
        delta = (timestamps[i] - timestamps[i - 1]).total_seconds()
        if delta < 300:  # within 5 minutes
            rapid_pairs += 1
    m["rapid_sequence_count"] = rapid_pairs

    # ── Same-day buy-sell patterns ──
    buy_days: Dict[str, set] = defaultdict(set)
    sell_days: Dict[str, set] = defaultdict(set)
    for tx in txs:
        dt = _parse_ts(tx.timestamp)
        if not dt or not tx.token:
            continue
        day = dt.strftime("%Y-%m-%d")
        if tx.tx_type == "swap" and tx.raw.get("side") == "BUY":
            buy_days[tx.token].add(day)
        elif tx.tx_type == "swap" and tx.raw.get("side") == "SELL":
            sell_days[tx.token].add(day)
    same_day_count = 0
    for token in buy_days:
        same_day_count += len(buy_days[token] & sell_days.get(token, set()))
    m["same_day_buy_sell_count"] = same_day_count

    # ── Internal transfers ──
    internal_count = sum(1 for tx in txs if "binance_internal" in (tx.risk_tags or []))
    m["internal_transfer_count"] = internal_count

    return m


# ---------------------------------------------------------------------------
# Scoring functions for each profile
# ---------------------------------------------------------------------------

def _score_retail_hodler(m: Dict[str, Any]) -> Tuple[float, List[str]]:
    score = 0.0
    reasons = []

    tx_per_day = m.get("tx_per_day", 0)
    swap_count = m.get("swap_count", 0)
    span_days = m.get("span_days", 0)
    hold_h = m.get("median_holding_hours", 0)

    if tx_per_day < 0.5:
        score += 25
        reasons.append(f"Niska częstotliwość handlu ({tx_per_day:.2f} tx/dzień)")
    elif tx_per_day < 1:
        score += 10

    if span_days > 180 and swap_count < 50:
        score += 20
        reasons.append(f"Długi okres obserwacji ({span_days} dni) z małą liczbą transakcji handlowych ({swap_count})")

    if hold_h > 24 * 30:
        score += 20
        reasons.append(f"Długi średni okres trzymania (~{hold_h / 24:.0f} dni)")
    elif hold_h > 24 * 7:
        score += 10

    if not m.get("uses_leverage"):
        score += 10
        reasons.append("Brak użycia dźwigni (margin)")

    large_count = m.get("large_tx_count", 0)
    if large_count > 0 and large_count <= 10:
        score += 10
        reasons.append(f"Kilka dużych zakupów jednorazowych ({large_count})")

    activity_ratio = m.get("activity_ratio", 0)
    if activity_ratio < 0.1:
        score += 15
        reasons.append(f"Aktywność w tylko {activity_ratio * 100:.1f}% dni")

    return min(score, 100), reasons


def _score_scalper(m: Dict[str, Any]) -> Tuple[float, List[str]]:
    score = 0.0
    reasons = []

    rapid = m.get("rapid_sequence_count", 0)
    tx_per_day = m.get("tx_per_day", 0)
    max_per_day = m.get("max_tx_per_day", 0)

    if rapid > 50:
        score += 30
        reasons.append(f"Wiele szybkich sekwencji transakcji ({rapid} par w ciągu 5 min)")
    elif rapid > 10:
        score += 15
        reasons.append(f"Częste szybkie transakcje ({rapid} par)")

    if max_per_day > 50:
        score += 25
        reasons.append(f"Maksymalnie {max_per_day} transakcji w jednym dniu")
    elif max_per_day > 20:
        score += 10

    if tx_per_day > 10:
        score += 20
        reasons.append(f"Bardzo wysoka średnia częstotliwość ({tx_per_day:.1f} tx/dzień)")

    avg_amount = m.get("avg_amount", 0)
    max_amount = m.get("max_amount", 0)
    if avg_amount > 0 and max_amount / max(avg_amount, 0.01) < 5:
        score += 10
        reasons.append("Jednolite, małe wielkości transakcji (typowe dla scalpingu)")

    return min(score, 100), reasons


def _score_day_trader(m: Dict[str, Any]) -> Tuple[float, List[str]]:
    score = 0.0
    reasons = []

    tx_per_day = m.get("tx_per_day", 0)
    same_day = m.get("same_day_buy_sell_count", 0)
    hold_h = m.get("median_holding_hours", 0)

    if tx_per_day >= 3:
        score += 20
        reasons.append(f"Średnio {tx_per_day:.1f} transakcji/dzień")

    if same_day > 5:
        score += 25
        reasons.append(f"Kupno i sprzedaż tego samego tokena w tym samym dniu ({same_day}x)")
    elif same_day > 0:
        score += 10

    if hold_h < 24:
        score += 20
        reasons.append(f"Krótki średni czas trzymania (~{hold_h:.1f}h)")

    if m.get("uses_leverage"):
        score += 15
        reasons.append("Korzysta z dźwigni (margin)")

    activity_ratio = m.get("activity_ratio", 0)
    if activity_ratio > 0.3:
        score += 10
        reasons.append(f"Aktywny w {activity_ratio * 100:.0f}% dni")

    return min(score, 100), reasons


def _score_swing_trader(m: Dict[str, Any]) -> Tuple[float, List[str]]:
    score = 0.0
    reasons = []

    hold_h = m.get("median_holding_hours", 0)
    tx_per_week = m.get("tx_per_week", 0)
    swap_count = m.get("swap_count", 0)

    if 48 <= hold_h <= 336:  # 2–14 days
        score += 30
        reasons.append(f"Średni czas trzymania {hold_h / 24:.1f} dni (typowy swing)")
    elif 24 <= hold_h < 48:
        score += 10

    if 2 <= tx_per_week <= 20:
        score += 20
        reasons.append(f"Umiarkowana częstotliwość ({tx_per_week:.1f} tx/tydzień)")

    if swap_count > 10 and not m.get("uses_leverage"):
        score += 10
        reasons.append("Regularne transakcje bez dźwigni")
    elif swap_count > 10 and m.get("uses_leverage"):
        score += 15
        reasons.append("Regularne transakcje z umiarkowaną dźwignią")

    return min(score, 100), reasons


def _score_staker(m: Dict[str, Any]) -> Tuple[float, List[str]]:
    score = 0.0
    reasons = []

    staking = m.get("staking_reward_count", 0)
    swap_count = m.get("swap_count", 0)
    total = m.get("total_tx_count", 1)

    if staking > 5:
        score += 35
        reasons.append(f"Regularne nagrody stakingowe ({staking} transakcji)")
    elif staking > 0:
        score += 15
        reasons.append(f"Obecne nagrody stakingowe ({staking})")

    if staking > 0 and swap_count / max(total, 1) < 0.2:
        score += 25
        reasons.append(f"Mało transakcji handlowych ({swap_count}) vs nagrody ({staking})")

    tx_per_day = m.get("tx_per_day", 0)
    if tx_per_day < 1 and staking > 0:
        score += 15
        reasons.append("Niska aktywność handlowa + staking")

    return min(score, 100), reasons


def _score_whale(m: Dict[str, Any]) -> Tuple[float, List[str]]:
    score = 0.0
    reasons = []

    max_amount = m.get("max_amount", 0)
    avg_amount = m.get("avg_amount", 0)
    large_count = m.get("large_tx_count", 0)
    total_volume = m.get("total_volume", 0)

    # These thresholds are relative — whale detection works for both BTC and stablecoins
    if max_amount > 100000:
        score += 30
        reasons.append(f"Bardzo duża transakcja: {max_amount:,.2f}")
    elif max_amount > 10000:
        score += 15
        reasons.append(f"Duża transakcja: {max_amount:,.2f}")

    if large_count > 5:
        score += 20
        reasons.append(f"Wiele dużych transakcji ({large_count})")

    if total_volume > 1000000:
        score += 25
        reasons.append(f"Całkowity wolumen: {total_volume:,.2f}")
    elif total_volume > 100000:
        score += 10

    tx_per_day = m.get("tx_per_day", 0)
    if tx_per_day < 2 and large_count > 3:
        score += 10
        reasons.append("Rzadkie, ale duże transakcje")

    return min(score, 100), reasons


def _score_institutional(m: Dict[str, Any]) -> Tuple[float, List[str]]:
    score = 0.0
    reasons = []

    total_volume = m.get("total_volume", 0)
    activity_ratio = m.get("activity_ratio", 0)
    tx_per_day = m.get("tx_per_day", 0)
    swap_count = m.get("swap_count", 0)

    if total_volume > 500000 and activity_ratio > 0.5:
        score += 30
        reasons.append(f"Wysoki wolumen ({total_volume:,.0f}) z regularną aktywnością ({activity_ratio * 100:.0f}% dni)")

    if m.get("uses_leverage") and swap_count > 100:
        score += 20
        reasons.append(f"Systematyczny handel z dźwignią ({swap_count} transakcji)")

    if tx_per_day > 5 and activity_ratio > 0.6:
        score += 20
        reasons.append("Algorytmiczny wzorzec: wysoka i regularna częstotliwość")

    # Hedging hint: both buys and sells in same market
    same_day = m.get("same_day_buy_sell_count", 0)
    if same_day > 20:
        score += 15
        reasons.append(f"Częste pary kupno-sprzedaż w tym samym dniu ({same_day}x) — możliwy hedging/arbitraż")

    return min(score, 100), reasons


def _score_alpha_hunter(m: Dict[str, Any]) -> Tuple[float, List[str]]:
    score = 0.0
    reasons = []

    unique_tokens = m.get("unique_tokens", 0)
    airdrop_count = m.get("airdrop_count", 0)
    total = m.get("total_tx_count", 1)

    if unique_tokens > 30:
        score += 30
        reasons.append(f"Bardzo duża różnorodność tokenów ({unique_tokens} różnych)")
    elif unique_tokens > 15:
        score += 15
        reasons.append(f"Duża różnorodność tokenów ({unique_tokens})")

    if airdrop_count > 3:
        score += 25
        reasons.append(f"Uczestniczy w airdropach ({airdrop_count} transakcji)")
    elif airdrop_count > 0:
        score += 10

    # Many small positions
    avg_amount = m.get("avg_amount", 0)
    if avg_amount > 0 and avg_amount < 100 and unique_tokens > 10:
        score += 20
        reasons.append("Wiele małych pozycji w różnych tokenach")

    return min(score, 100), reasons


def _score_meme_trader(m: Dict[str, Any]) -> Tuple[float, List[str]]:
    score = 0.0
    reasons = []

    # Impulsive patterns: sudden sells after receiving (short hold)
    hold_h = m.get("median_holding_hours", 0)
    rapid = m.get("rapid_sequence_count", 0)
    unique_tokens = m.get("unique_tokens", 0)
    swap_count = m.get("swap_count", 0)
    tx_per_day = m.get("tx_per_day", 0)

    # Bursts of activity with long pauses (sporadic)
    activity_ratio = m.get("activity_ratio", 0)
    avg_per_active = m.get("avg_tx_per_active_day", 0)

    if activity_ratio < 0.2 and avg_per_active > 5:
        score += 25
        reasons.append(f"Sporadyczna aktywność ({activity_ratio * 100:.0f}% dni), ale gdy aktywny: {avg_per_active:.1f} tx/dzień — wzorzec impulsywny")

    if hold_h < 12 and swap_count > 5:
        score += 20
        reasons.append(f"Bardzo krótki czas trzymania (~{hold_h:.1f}h) — szybkie wejście/wyjście")

    if unique_tokens > 10 and swap_count < unique_tokens * 3:
        score += 15
        reasons.append("Handel wieloma tokenami z małą liczbą transakcji na każdy — eksperymentowanie")

    return min(score, 100), reasons


def _score_bagholder(m: Dict[str, Any]) -> Tuple[float, List[str]]:
    score = 0.0
    reasons = []

    swap_count = m.get("swap_count", 0)
    span_days = m.get("span_days", 0)
    deposit_count = m.get("deposit_count", 0)
    withdrawal_count = m.get("withdrawal_count", 0)
    tx_per_day = m.get("tx_per_day", 0)
    activity_ratio = m.get("activity_ratio", 0)

    if span_days > 90 and swap_count == 0:
        score += 35
        reasons.append(f"Okres {span_days} dni bez żadnych transakcji handlowych")
    elif span_days > 180 and swap_count < 5:
        score += 20
        reasons.append(f"Bardzo mało transakcji handlowych ({swap_count}) w ciągu {span_days} dni")

    if deposit_count > 0 and withdrawal_count == 0:
        score += 25
        reasons.append(f"Depozyty ({deposit_count}) bez wypłat — środki zatrzymane na koncie")

    if tx_per_day < 0.1 and span_days > 60:
        score += 20
        reasons.append(f"Minimalna aktywność ({tx_per_day:.3f} tx/dzień)")

    if activity_ratio < 0.05 and span_days > 90:
        score += 15
        reasons.append(f"Aktywność w zaledwie {activity_ratio * 100:.1f}% dni")

    return min(score, 100), reasons


# ---------------------------------------------------------------------------
# Main profiling function
# ---------------------------------------------------------------------------

_SCORERS = {
    "retail_hodler": _score_retail_hodler,
    "scalper": _score_scalper,
    "day_trader": _score_day_trader,
    "swing_trader": _score_swing_trader,
    "staker_validator": _score_staker,
    "whale": _score_whale,
    "institutional": _score_institutional,
    "alpha_hunter": _score_alpha_hunter,
    "meme_trader": _score_meme_trader,
    "bagholder": _score_bagholder,
}


def profile_user_behavior(
    txs: List[CryptoTransaction],
    source_type: str = "exchange",
) -> Dict[str, Any]:
    """Analyze transactions and return user behavior profile(s).

    Returns dict with:
      - primary_profile: str — most likely profile type
      - profiles: list of {type, label, icon, desc, score, reasons} sorted by score
      - metrics: dict of computed metrics (for debugging/display)
      - summary: str — human-readable summary
    """
    if not txs:
        return {
            "primary_profile": "unknown",
            "profiles": [],
            "metrics": {},
            "summary": "Brak transakcji do analizy.",
        }

    metrics = _compute_metrics(txs)

    profiles = []
    for prof_type, scorer in _SCORERS.items():
        try:
            score, reasons = scorer(metrics)
        except Exception as e:
            log.warning("Error scoring %s: %s", prof_type, e)
            score, reasons = 0, []

        if score > 0:
            meta = _PROFILES[prof_type]
            profiles.append({
                "type": prof_type,
                "label": meta["label"],
                "icon": meta["icon"],
                "desc": meta["desc"],
                "score": round(score, 1),
                "reasons": reasons,
            })

    profiles.sort(key=lambda p: p["score"], reverse=True)

    primary = profiles[0]["type"] if profiles else "unknown"

    # Build summary
    summary_parts = []
    if profiles:
        top = profiles[0]
        summary_parts.append(
            f"Profil najbardziej prawdopodobny: {top['icon']} {top['label']} "
            f"(pewność: {top['score']}%)."
        )
        if len(profiles) > 1 and profiles[1]["score"] >= 30:
            alt = profiles[1]
            summary_parts.append(
                f"Alternatywny profil: {alt['icon']} {alt['label']} ({alt['score']}%)."
            )
        if top["reasons"]:
            summary_parts.append("Główne wskaźniki: " + "; ".join(top["reasons"][:3]) + ".")
    else:
        summary_parts.append("Nie udało się określić profilu zachowania użytkownika.")

    # Expose key metrics for display
    display_metrics = {}
    for key in ["tx_per_day", "span_days", "active_days", "unique_tokens",
                 "swap_count", "total_volume", "avg_holding_hours",
                 "uses_leverage", "staking_reward_count", "large_tx_count",
                 "rapid_sequence_count", "same_day_buy_sell_count",
                 "privacy_coin_tx_count", "internal_transfer_count"]:
        if key in metrics:
            display_metrics[key] = metrics[key]

    return {
        "primary_profile": primary,
        "profiles": profiles,
        "metrics": display_metrics,
        "summary": " ".join(summary_parts),
    }
