"""Crypto risk assessment rules — offline pattern detection."""
from __future__ import annotations

import json
import logging
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
# Address risk checks
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
# Transaction pattern detection
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
        # Check if amounts are mostly decreasing
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
    # Group by token and check if same amounts appear as send+receive
    sent: Dict[str, List[Tuple[str, CryptoTransaction]]] = {}
    received: Dict[str, List[Tuple[str, CryptoTransaction]]] = {}

    for tx in txs:
        key = f"{tx.token}:{float(tx.amount):.8f}"
        if tx.from_address:
            sent.setdefault(tx.from_address, []).append((key, tx))
        if tx.to_address:
            received.setdefault(tx.to_address, []).append((key, tx))

    # Find addresses that both sent and received same amounts
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
    # Simple heuristic: many txs with similar amounts close to threshold
    by_sender: Dict[str, List[CryptoTransaction]] = {}
    for tx in txs:
        if tx.from_address and float(tx.amount) > 0:
            by_sender.setdefault(tx.from_address, []).append(tx)

    for sender, sender_txs in by_sender.items():
        # Check for clustering of amounts
        if len(sender_txs) < 5:
            continue
        amounts = [float(t.amount) for t in sender_txs]
        # Check if many amounts are similar (within 10% of each other)
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
# Main risk scoring
# ---------------------------------------------------------------------------

def classify_transactions(txs: List[CryptoTransaction]) -> List[CryptoTransaction]:
    """Apply risk rules to classify all transactions."""
    sanctioned_db = _load_sanctioned()
    known_contracts = _load_known_contracts()
    sanctioned_addrs = set(sanctioned_db.get("addresses", {}).keys())
    mixer_addrs = {a for a, v in sanctioned_db.get("addresses", {}).items() if "mixer" in str(v.get("reason", "")).lower()}

    for tx in txs:
        tags: List[str] = []
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


def compute_overall_risk(txs: List[CryptoTransaction], alerts: List[Dict[str, Any]]) -> Tuple[float, List[str]]:
    """Compute overall risk score and list of reasons."""
    reasons: List[str] = []
    score = 0.0

    # Average transaction risk
    if txs:
        avg_risk = sum(tx.risk_score for tx in txs) / len(txs)
        score += avg_risk * 0.3

    # Pattern alerts
    pattern_scores = {
        "peel_chain": 30,
        "dust_attack": 15,
        "round_trip": 35,
        "smurfing": 40,
    }
    for alert in alerts:
        p = alert.get("pattern", "")
        score += pattern_scores.get(p, 10)
        reasons.append(alert.get("description", p))

    # Sanctioned addresses
    sanctioned_count = sum(1 for tx in txs if "sanctioned" in tx.risk_tags)
    if sanctioned_count:
        score += 50
        reasons.append(f"Transakcje z adresami objętymi sankcjami: {sanctioned_count}")

    # Mixer usage
    mixer_count = sum(1 for tx in txs if "mixer" in tx.risk_tags)
    if mixer_count:
        score += 40
        reasons.append(f"Transakcje z mikserami: {mixer_count}")

    # Privacy coins
    privacy_count = sum(1 for tx in txs if "privacy_coin" in tx.risk_tags)
    if privacy_count:
        score += 20
        reasons.append(f"Transakcje privacy coins: {privacy_count}")

    return min(score, 100), reasons
