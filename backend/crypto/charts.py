"""Chart data generation for crypto analysis (consumed by Chart.js on frontend)."""
from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any, Dict, List

from .parsers.base import CryptoTransaction

log = logging.getLogger("aistate.crypto.charts")


def generate_all_charts(txs: List[CryptoTransaction]) -> Dict[str, Any]:
    """Generate all chart datasets from transactions."""
    return {
        "balance_timeline": _balance_timeline(txs),
        "monthly_volume": _monthly_volume(txs),
        "top_counterparties": _top_counterparties(txs),
        "tx_type_distribution": _tx_type_distribution(txs),
        "daily_tx_count": _daily_tx_count(txs),
    }


def _balance_timeline(txs: List[CryptoTransaction]) -> Dict[str, Any]:
    """Running balance over time (from walletexplorer balance column or calculated)."""
    # Try to get balance from raw data (walletexplorer has it)
    points = []
    for tx in sorted(txs, key=lambda t: t.timestamp):
        raw_balance = tx.raw.get("balance")
        if raw_balance is not None:
            try:
                bal = float(str(raw_balance).replace(",", "."))
                points.append({"x": tx.timestamp[:10], "y": bal})
            except (ValueError, TypeError):
                pass

    if points:
        # Deduplicate by date (keep last)
        by_date: Dict[str, float] = {}
        for p in points:
            by_date[p["x"]] = p["y"]
        labels = sorted(by_date.keys())
        return {
            "labels": labels,
            "data": [by_date[d] for d in labels],
            "label": "Saldo BTC",
        }

    # Fallback: calculate running balance from amounts
    sorted_txs = sorted(txs, key=lambda t: t.timestamp)
    balance = 0.0
    by_date: Dict[str, float] = {}
    for tx in sorted_txs:
        if tx.tx_type in ("deposit",):
            balance += float(tx.amount)
        elif tx.tx_type in ("withdrawal",):
            balance -= float(tx.amount)
        by_date[tx.timestamp[:10]] = balance

    labels = sorted(by_date.keys())
    return {
        "labels": labels,
        "data": [round(by_date[d], 8) for d in labels],
        "label": "Saldo (obliczone)",
    }


def _monthly_volume(txs: List[CryptoTransaction]) -> Dict[str, Any]:
    """Monthly incoming vs outgoing volume."""
    received: Dict[str, float] = defaultdict(float)
    sent: Dict[str, float] = defaultdict(float)

    for tx in txs:
        if not tx.timestamp:
            continue
        month = tx.timestamp[:7]  # YYYY-MM
        if tx.tx_type in ("deposit",):
            received[month] += float(tx.amount)
        elif tx.tx_type in ("withdrawal",):
            sent[month] += float(tx.amount)

    months = sorted(set(list(received.keys()) + list(sent.keys())))
    return {
        "labels": months,
        "received": [round(received.get(m, 0), 8) for m in months],
        "sent": [round(sent.get(m, 0), 8) for m in months],
    }


def _top_counterparties(txs: List[CryptoTransaction], limit: int = 20) -> Dict[str, Any]:
    """Top counterparties by total volume."""
    volumes: Dict[str, float] = defaultdict(float)
    counts: Dict[str, int] = defaultdict(int)

    for tx in txs:
        cp = tx.counterparty or tx.from_address or tx.to_address
        if not cp:
            continue
        volumes[cp] += float(tx.amount)
        counts[cp] += 1

    top = sorted(volumes.items(), key=lambda x: -x[1])[:limit]
    return {
        "labels": [_shorten_addr(a) for a, _ in top],
        "full_labels": [a for a, _ in top],
        "data": [round(v, 8) for _, v in top],
        "counts": [counts[a] for a, _ in top],
    }


def _tx_type_distribution(txs: List[CryptoTransaction]) -> Dict[str, Any]:
    """Distribution by transaction type."""
    dist: Dict[str, int] = defaultdict(int)
    for tx in txs:
        dist[tx.tx_type] += 1
    labels = sorted(dist.keys())
    return {
        "labels": labels,
        "data": [dist[l] for l in labels],
    }


def _daily_tx_count(txs: List[CryptoTransaction]) -> Dict[str, Any]:
    """Daily transaction count."""
    counts: Dict[str, int] = defaultdict(int)
    for tx in txs:
        if tx.timestamp:
            counts[tx.timestamp[:10]] += 1
    dates = sorted(counts.keys())
    return {
        "labels": dates,
        "data": [counts[d] for d in dates],
    }


def _shorten_addr(addr: str) -> str:
    """Shorten a long address/wallet ID for display."""
    if len(addr) > 20:
        return addr[:8] + "..." + addr[-6:]
    return addr
