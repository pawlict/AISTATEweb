"""Crypto risk assessment rules — offline pattern detection.

Supports two analysis modes:
  - blockchain: address-based OFAC/mixer/pattern detection
  - exchange: behavioural pattern detection (structuring, rapid conversion, layering)
"""
from __future__ import annotations

import json
import logging
from collections import defaultdict
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from .parsers.base import CryptoTransaction, WalletInfo

log = logging.getLogger("aistate.crypto.risk")

_CONFIG_DIR = Path(__file__).parent / "config"

# ---------------------------------------------------------------------------
# Known addresses database (loaded once)
# ---------------------------------------------------------------------------

_SANCTIONED: Optional[Dict[str, Any]] = None
_KNOWN_CONTRACTS: Optional[Dict[str, Any]] = None


def _load_sanctioned() -> Dict[str, Any]:
    global _SANCTIONED
    if _SANCTIONED is None:
        p = _CONFIG_DIR / "sanctioned.json"
        if p.exists():
            _SANCTIONED = json.loads(p.read_text(encoding="utf-8"))
        else:
            _SANCTIONED = {"addresses": {}, "entities": {}}
    return _SANCTIONED


def _load_known_contracts() -> Dict[str, Any]:
    global _KNOWN_CONTRACTS
    if _KNOWN_CONTRACTS is None:
        p = _CONFIG_DIR / "known_contracts.json"
        if p.exists():
            _KNOWN_CONTRACTS = json.loads(p.read_text(encoding="utf-8"))
        else:
            _KNOWN_CONTRACTS = {"contracts": {}, "protocols": {}}
    return _KNOWN_CONTRACTS


# ---------------------------------------------------------------------------
# Address risk checks (blockchain only)
# ---------------------------------------------------------------------------

def check_sanctioned(address: str) -> Optional[Dict[str, Any]]:
    """Check if an address is on the sanctioned list."""
    db = _load_sanctioned()
    addr = address.lower().strip()
    entry = db.get("addresses", {}).get(addr)
    if entry:
        return {"address": addr, "reason": entry.get("reason", "OFAC sanctioned"), "entity": entry.get("entity", ""), "risk": "critical"}
    return None


def check_known_contract(address: str) -> Optional[Dict[str, Any]]:
    """Look up a known smart contract."""
    db = _load_known_contracts()
    addr = address.lower().strip()
    return db.get("contracts", {}).get(addr)


# ---------------------------------------------------------------------------
# Blockchain pattern detection
# ---------------------------------------------------------------------------

def detect_peel_chain(txs: List[CryptoTransaction], threshold: int = 5) -> List[Dict[str, Any]]:
    """Detect peel chain pattern: series of txs with decreasing amounts from same source."""
    alerts = []
    by_sender: Dict[str, List[CryptoTransaction]] = {}
    for tx in txs:
        if tx.from_address:
            by_sender.setdefault(tx.from_address, []).append(tx)

    for sender, sender_txs in by_sender.items():
        sorted_txs = sorted(sender_txs, key=lambda t: t.timestamp)
        if len(sorted_txs) < threshold:
            continue
        amounts = [float(t.amount) for t in sorted_txs if float(t.amount) > 0]
        if len(amounts) < threshold:
            continue
        decreasing_count = sum(1 for i in range(1, len(amounts)) if amounts[i] < amounts[i - 1])
        if decreasing_count / max(1, len(amounts) - 1) > 0.7:
            alerts.append({
                "pattern": "peel_chain",
                "address": sender,
                "tx_count": len(sorted_txs),
                "risk": "high",
                "description": f"Peel chain: {len(sorted_txs)} transakcji z malejącymi kwotami z {sender[:12]}...",
            })
    return alerts


def detect_dust_attack(txs: List[CryptoTransaction], dust_threshold: float = 0.0001) -> List[Dict[str, Any]]:
    """Detect dust attack: many small incoming transactions."""
    alerts = []
    by_receiver: Dict[str, List[CryptoTransaction]] = {}
    for tx in txs:
        if tx.to_address and float(tx.amount) > 0 and float(tx.amount) < dust_threshold:
            by_receiver.setdefault(tx.to_address, []).append(tx)

    for receiver, dust_txs in by_receiver.items():
        if len(dust_txs) >= 10:
            alerts.append({
                "pattern": "dust_attack",
                "address": receiver,
                "tx_count": len(dust_txs),
                "risk": "medium",
                "description": f"Dust attack: {len(dust_txs)} mikrotransakcji do {receiver[:12]}...",
            })
    return alerts


def detect_round_trip(txs: List[CryptoTransaction]) -> List[Dict[str, Any]]:
    """Detect round-trip: funds go out and come back through different path."""
    alerts = []
    sent: Dict[str, List[Tuple[str, CryptoTransaction]]] = {}
    received: Dict[str, List[Tuple[str, CryptoTransaction]]] = {}

    for tx in txs:
        key = f"{tx.token}:{float(tx.amount):.8f}"
        if tx.from_address:
            sent.setdefault(tx.from_address, []).append((key, tx))
        if tx.to_address:
            received.setdefault(tx.to_address, []).append((key, tx))

    common_addrs = set(sent.keys()) & set(received.keys())
    for addr in common_addrs:
        sent_keys = {k for k, _ in sent[addr]}
        recv_keys = {k for k, _ in received[addr]}
        overlap = sent_keys & recv_keys
        if len(overlap) >= 3:
            alerts.append({
                "pattern": "round_trip",
                "address": addr,
                "matching_amounts": len(overlap),
                "risk": "high",
                "description": f"Round-trip: {len(overlap)} kwot wysłanych i zwróconych do {addr[:12]}...",
            })
    return alerts


def detect_smurfing(txs: List[CryptoTransaction], threshold_usd: float = 10000) -> List[Dict[str, Any]]:
    """Detect smurfing: many transactions just below reporting threshold."""
    alerts = []
    by_sender: Dict[str, List[CryptoTransaction]] = {}
    for tx in txs:
        if tx.from_address and float(tx.amount) > 0:
            by_sender.setdefault(tx.from_address, []).append(tx)

    for sender, sender_txs in by_sender.items():
        if len(sender_txs) < 5:
            continue
        amounts = [float(t.amount) for t in sender_txs]
        avg = sum(amounts) / len(amounts)
        similar_count = sum(1 for a in amounts if abs(a - avg) / max(avg, 0.01) < 0.1)
        if similar_count >= 5 and len(set(t.to_address for t in sender_txs)) >= 3:
            alerts.append({
                "pattern": "smurfing",
                "address": sender,
                "tx_count": similar_count,
                "avg_amount": f"{avg:.4f}",
                "risk": "high",
                "description": f"Smurfing: {similar_count} transakcji o podobnych kwotach (~{avg:.4f}) z {sender[:12]}...",
            })
    return alerts


# ---------------------------------------------------------------------------
# Exchange-specific pattern detection
# ---------------------------------------------------------------------------

def detect_rapid_conversion(txs: List[CryptoTransaction], window_minutes: int = 30) -> List[Dict[str, Any]]:
    """Detect rapid fiat->crypto->withdrawal pattern (layering indicator).

    Pattern: deposit fiat -> buy crypto -> withdraw crypto within short window.
    """
    from datetime import datetime, timedelta

    alerts = []
    deposits = [tx for tx in txs if tx.tx_type == "deposit"]
    withdrawals = [tx for tx in txs if tx.tx_type == "withdrawal"]

    if not deposits or not withdrawals:
        return alerts

    def _parse_ts(s: str) -> Optional[datetime]:
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ"):
            try:
                return datetime.strptime(s[:19], fmt)
            except ValueError:
                continue
        return None

    chains_found = []
    window = timedelta(minutes=window_minutes)

    for dep in deposits:
        dep_ts = _parse_ts(dep.timestamp)
        if not dep_ts:
            continue
        for wd in withdrawals:
            if wd.token == dep.token:
                continue  # same token isn't conversion
            wd_ts = _parse_ts(wd.timestamp)
            if not wd_ts:
                continue
            diff = wd_ts - dep_ts
            if timedelta(0) < diff <= window:
                chains_found.append({
                    "deposit": f"{dep.token} {float(dep.amount):.4f}",
                    "withdrawal": f"{wd.token} {float(wd.amount):.8f}",
                    "minutes": int(diff.total_seconds() / 60),
                })

    if len(chains_found) >= 2:
        alerts.append({
            "pattern": "rapid_conversion",
            "count": len(chains_found),
            "risk": "high",
            "description": f"Szybka konwersja: {len(chains_found)} cykli wpłata→kupno→wypłata w oknie {window_minutes} min",
            "details": chains_found[:10],
        })
    return alerts


def detect_structuring_deposits(txs: List[CryptoTransaction]) -> List[Dict[str, Any]]:
    """Detect structured deposits: multiple similar-amount fiat deposits (smurfing on-ramp)."""
    alerts = []
    _FIAT = {"PLN", "USD", "EUR", "GBP", "CHF"}
    fiat_deps = [tx for tx in txs if tx.tx_type == "deposit" and tx.token in _FIAT]

    if len(fiat_deps) < 3:
        return alerts

    amounts = [float(tx.amount) for tx in fiat_deps]
    avg = sum(amounts) / len(amounts)
    if avg <= 0:
        return alerts

    similar = sum(1 for a in amounts if abs(a - avg) / max(avg, 0.01) < 0.15)

    if similar >= 3:
        alerts.append({
            "pattern": "structuring_deposits",
            "count": similar,
            "avg_amount": f"{avg:.2f}",
            "currency": fiat_deps[0].token,
            "risk": "medium",
            "description": f"Strukturyzowane wpłaty: {similar}x ~ {avg:.2f} {fiat_deps[0].token}",
        })
    return alerts


def detect_meme_coin_concentration(txs: List[CryptoTransaction]) -> List[Dict[str, Any]]:
    """Flag high concentration of meme/speculative coins (risk indicator)."""
    _MEME_COINS = {"PEPE", "DOGE", "SHIB", "BONK", "FLOKI", "BABYDOGE", "ELON",
                   "WOJAK", "TURBO", "MEME", "WIF", "BOME", "SLERF", "BRETT"}
    alerts = []

    meme_count = sum(1 for tx in txs if tx.token in _MEME_COINS)
    total = len(txs)
    if total < 5:
        return alerts

    ratio = meme_count / total
    meme_tokens = {tx.token for tx in txs if tx.token in _MEME_COINS}

    if meme_count >= 3 and ratio > 0.2:
        alerts.append({
            "pattern": "meme_coin_concentration",
            "count": meme_count,
            "tokens": sorted(meme_tokens),
            "ratio": f"{ratio:.0%}",
            "risk": "low",
            "description": f"Koncentracja meme coins: {meme_count}/{total} tx ({ratio:.0%}) — {', '.join(sorted(meme_tokens))}",
        })
    return alerts


def detect_privacy_coin_usage(txs: List[CryptoTransaction]) -> List[Dict[str, Any]]:
    """Flag usage of privacy-focused coins."""
    _PRIVACY_COINS = {"XMR", "ZEC", "DASH", "SCRT", "BEAM", "GRIN", "FIRO", "ARRR", "OXEN"}
    alerts = []

    privacy_txs = [tx for tx in txs if tx.token in _PRIVACY_COINS]
    if not privacy_txs:
        return alerts

    tokens_used = {tx.token for tx in privacy_txs}
    total_volume = sum(float(tx.amount) for tx in privacy_txs)
    alerts.append({
        "pattern": "privacy_coin_usage",
        "count": len(privacy_txs),
        "tokens": sorted(tokens_used),
        "total_volume": f"{total_volume:.8f}",
        "risk": "medium",
        "description": f"Privacy coins: {len(privacy_txs)} tx z {', '.join(sorted(tokens_used))}",
    })
    return alerts


# ---------------------------------------------------------------------------
# Transaction classification (works for both modes)
# ---------------------------------------------------------------------------

def classify_transactions(
    txs: List[CryptoTransaction],
    source_type: str = "blockchain",
) -> List[CryptoTransaction]:
    """Apply risk rules to classify all transactions.

    For blockchain data: full address-based OFAC/mixer/contract checks.
    For exchange data: lighter rules (privacy coins, high value, meme coins).
    """
    if source_type == "blockchain":
        return _classify_blockchain(txs)
    return _classify_exchange(txs)


def _classify_blockchain(txs: List[CryptoTransaction]) -> List[CryptoTransaction]:
    """Full address-based risk classification for on-chain data."""
    sanctioned_db = _load_sanctioned()
    known_contracts = _load_known_contracts()
    sanctioned_addrs = set(sanctioned_db.get("addresses", {}).keys())
    mixer_addrs = {a for a, v in sanctioned_db.get("addresses", {}).items() if "mixer" in str(v.get("reason", "")).lower()}

    for tx in txs:
        tags: List[str] = list(tx.risk_tags or [])  # preserve parser-set tags
        score = 0.0

        # Check sanctioned
        for addr in (tx.from_address, tx.to_address):
            if addr and addr.lower() in sanctioned_addrs:
                tags.append("sanctioned")
                score += 100

        # Check mixer
        for addr in (tx.from_address, tx.to_address):
            if addr and addr.lower() in mixer_addrs:
                tags.append("mixer")
                score += 80

        # Check known contracts
        for addr in (tx.to_address, tx.contract_address):
            if addr:
                info = known_contracts.get("contracts", {}).get(addr.lower())
                if info:
                    tx.counterparty = info.get("name", "")
                    cat = info.get("category", "")
                    if cat == "mixer":
                        tags.append("mixer")
                        score += 80
                    elif cat == "bridge":
                        tags.append("bridge")
                        score += 20
                    elif cat == "defi":
                        tags.append("defi")
                        score += 5

        # High-value transaction
        if float(tx.amount) > 10:  # > 10 BTC/ETH is significant
            tags.append("high_value")
            score += 15

        # Privacy token
        if tx.token.upper() in ("XMR", "ZEC", "DASH", "SCRT"):
            tags.append("privacy_coin")
            score += 40

        tx.risk_tags = tags
        tx.risk_score = min(score, 100)

    return txs


def _classify_exchange(txs: List[CryptoTransaction]) -> List[CryptoTransaction]:
    """Lighter risk classification for exchange/custodial data.

    No address checks (exchange data doesn't have on-chain addresses).
    Focus on: privacy coins, high-value fiat movements, meme coins.
    """
    _FIAT = {"PLN", "USD", "EUR", "GBP", "CHF", "CZK", "TRY", "BRL", "AUD", "CAD", "JPY", "KRW"}
    _PRIVACY = {"XMR", "ZEC", "DASH", "SCRT", "BEAM", "GRIN", "FIRO"}
    _MEME = {"PEPE", "DOGE", "SHIB", "BONK", "FLOKI", "BABYDOGE", "WIF", "BOME", "MEME"}

    for tx in txs:
        tags: List[str] = list(tx.risk_tags or [])  # preserve parser-set tags
        score = 0.0

        # Privacy coins on exchange
        if tx.token.upper() in _PRIVACY:
            tags.append("privacy_coin")
            score += 30

        # Meme coins (lower risk, but flagged)
        if tx.token.upper() in _MEME:
            tags.append("meme_coin")
            score += 5

        # Large fiat movement
        if tx.token in _FIAT and float(tx.amount) > 5000:
            tags.append("high_value_fiat")
            score += 15

        # Withdrawal (funds leaving exchange = higher risk)
        if tx.tx_type == "withdrawal":
            score += 10
            tags.append("withdrawal")

        # Binance internal transfer (lower risk — within same exchange)
        if "binance_internal" in tags:
            score = max(score - 5, 0)

        tx.risk_tags = tags
        tx.risk_score = min(score, 100)

    return txs


# ---------------------------------------------------------------------------
# Overall risk scoring
# ---------------------------------------------------------------------------

def compute_overall_risk(
    txs: List[CryptoTransaction],
    alerts: List[Dict[str, Any]],
    source_type: str = "blockchain",
) -> Tuple[float, List[str]]:
    """Compute overall risk score and list of reasons."""
    reasons: List[str] = []
    score = 0.0

    # Average transaction risk
    if txs:
        avg_risk = sum(tx.risk_score for tx in txs) / len(txs)
        score += avg_risk * 0.3

    # Pattern alerts
    pattern_scores = {
        # Blockchain patterns
        "peel_chain": 30,
        "dust_attack": 15,
        "round_trip": 35,
        "smurfing": 40,
        # Exchange patterns
        "rapid_conversion": 35,
        "structuring_deposits": 25,
        "meme_coin_concentration": 5,
        "privacy_coin_usage": 20,
    }
    for alert in alerts:
        p = alert.get("pattern", "")
        score += pattern_scores.get(p, 10)
        reasons.append(alert.get("description", p))

    if source_type == "blockchain":
        sanctioned_count = sum(1 for tx in txs if "sanctioned" in tx.risk_tags)
        if sanctioned_count:
            score += 50
            reasons.append(f"Transakcje z adresami objętymi sankcjami: {sanctioned_count}")

        mixer_count = sum(1 for tx in txs if "mixer" in tx.risk_tags)
        if mixer_count:
            score += 40
            reasons.append(f"Transakcje z mikserami: {mixer_count}")

        privacy_count = sum(1 for tx in txs if "privacy_coin" in tx.risk_tags)
        if privacy_count:
            score += 20
            reasons.append(f"Transakcje privacy coins: {privacy_count}")
    else:
        withdrawal_count = sum(1 for tx in txs if tx.tx_type == "withdrawal")
        if withdrawal_count:
            reasons.append(f"Wypłaty z giełdy: {withdrawal_count}")

        high_fiat = sum(1 for tx in txs if "high_value_fiat" in tx.risk_tags)
        if high_fiat:
            score += 10
            reasons.append(f"Duże operacje fiatowe: {high_fiat}")

        privacy_count = sum(1 for tx in txs if "privacy_coin" in tx.risk_tags)
        if privacy_count:
            score += 15
            reasons.append(f"Operacje na privacy coins: {privacy_count}")

    return min(score, 100), reasons


# ---------------------------------------------------------------------------
# Convenience: run all pattern detections for a source type
# ---------------------------------------------------------------------------

def detect_all_patterns(
    txs: List[CryptoTransaction],
    source_type: str = "blockchain",
) -> List[Dict[str, Any]]:
    """Run all relevant pattern detections based on source type."""
    alerts: List[Dict[str, Any]] = []

    if source_type == "blockchain":
        alerts.extend(detect_peel_chain(txs))
        alerts.extend(detect_dust_attack(txs))
        alerts.extend(detect_round_trip(txs))
        alerts.extend(detect_smurfing(txs))
    else:
        alerts.extend(detect_rapid_conversion(txs))
        alerts.extend(detect_structuring_deposits(txs))
        alerts.extend(detect_meme_coin_concentration(txs))
        alerts.extend(detect_privacy_coin_usage(txs))

    return alerts
