"""Chart data generation for crypto analysis (consumed by Chart.js on frontend).

Supports two analysis modes:
  - exchange: statements from centralised exchanges (Binance, Kraken, …)
  - blockchain: on-chain data (WalletExplorer, Etherscan, …)
"""
from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any, Dict, List

from .parsers.base import CryptoTransaction

log = logging.getLogger("aistate.crypto.charts")


# ── public API ────────────────────────────────────────────────────────────

def generate_all_charts(
    txs: List[CryptoTransaction],
    source_type: str = "blockchain",
) -> Dict[str, Any]:
    """Generate all chart datasets from transactions.

    ``source_type`` controls which chart set is produced:
      * ``"exchange"``   – per-token balance timeline, fiat flow, operation breakdown
      * ``"blockchain"`` – running BTC/ETH balance, monthly volume, counterparties
    """
    common = {
        "monthly_volume": _monthly_volume(txs),
        "daily_tx_count": _daily_tx_count(txs),
        "tx_type_distribution": _tx_type_distribution(txs),
    }

    if source_type == "exchange":
        common.update({
            "balance_timeline": _exchange_balance_timeline(txs),
            "token_breakdown": _token_breakdown(txs),
            "fiat_flow": _fiat_flow(txs),
            "fiat_value_timeline": _fiat_value_timeline(txs),
            "top_operations": _top_operations(txs),
        })
    else:
        common.update({
            "balance_timeline": _blockchain_balance_timeline(txs),
            "top_counterparties": _top_counterparties(txs),
        })

    return common


# ── exchange-specific charts ──────────────────────────────────────────────

_FIAT_TOKENS = {"PLN", "USD", "EUR", "GBP", "CHF", "CZK", "TRY", "BRL", "AUD", "CAD", "JPY", "KRW"}


def _exchange_balance_timeline(txs: List[CryptoTransaction]) -> Dict[str, Any]:
    """Per-token running balance over time for exchange statements.

    Returns datasets keyed by token so the frontend can render multi-line chart.
    """
    sorted_txs = sorted(txs, key=lambda t: t.timestamp)
    # token → date → running balance
    balances: Dict[str, Dict[str, float]] = defaultdict(dict)
    running: Dict[str, float] = defaultdict(float)

    for tx in sorted_txs:
        token = tx.token or "UNKNOWN"
        amt = float(tx.amount)
        # Determine sign from raw change field or tx_type
        raw_change = tx.raw.get("change", "")
        if raw_change and str(raw_change).lstrip().startswith("-"):
            running[token] -= amt
        elif tx.tx_type in ("withdrawal",):
            running[token] -= amt
        else:
            running[token] += amt
        date = tx.timestamp[:10]
        balances[token][date] = round(running[token], 8)

    # Build multi-dataset structure
    all_dates = sorted({d for tok_dates in balances.values() for d in tok_dates})
    datasets = []
    for token in sorted(balances.keys()):
        vals = balances[token]
        # Forward-fill missing dates
        data = []
        last = 0.0
        for d in all_dates:
            if d in vals:
                last = vals[d]
            data.append(round(last, 8))
        datasets.append({"token": token, "data": data})

    return {"labels": all_dates, "datasets": datasets}


def _token_breakdown(txs: List[CryptoTransaction]) -> Dict[str, Any]:
    """Volume per token (total absolute movement)."""
    volumes: Dict[str, float] = defaultdict(float)
    counts: Dict[str, int] = defaultdict(int)
    for tx in txs:
        token = tx.token or "UNKNOWN"
        volumes[token] += float(tx.amount)
        counts[token] += 1
    tokens_sorted = sorted(volumes.keys(), key=lambda t: -volumes[t])
    return {
        "labels": tokens_sorted,
        "data": [round(volumes[t], 8) for t in tokens_sorted],
        "counts": [counts[t] for t in tokens_sorted],
    }


def _fiat_flow(txs: List[CryptoTransaction]) -> Dict[str, Any]:
    """Monthly fiat on-ramp (deposits) vs off-ramp (withdrawals).

    Shows only fiat tokens (PLN, USD, EUR, …).
    """
    deposits: Dict[str, float] = defaultdict(float)
    withdrawals: Dict[str, float] = defaultdict(float)

    for tx in txs:
        if tx.token not in _FIAT_TOKENS:
            continue
        month = tx.timestamp[:7] if tx.timestamp else "?"
        raw_change = tx.raw.get("change", "")
        if tx.tx_type == "deposit" or (raw_change and not str(raw_change).lstrip().startswith("-")):
            deposits[month] += float(tx.amount)
        else:
            withdrawals[month] += float(tx.amount)

    months = sorted(set(list(deposits.keys()) + list(withdrawals.keys())))
    return {
        "labels": months,
        "deposits": [round(deposits.get(m, 0), 2) for m in months],
        "withdrawals": [round(withdrawals.get(m, 0), 2) for m in months],
    }


def _fiat_value_timeline(txs: List[CryptoTransaction]) -> Dict[str, Any]:
    """Monthly cumulative fiat value of buy/sell/transfer operations.

    Uses ``fiat_value``/``wartosc`` from ``tx.raw`` (set by parsers like
    Revolut Crypto) to show money flows in PLN/USD/EUR over time.
    Falls back to an empty chart when no fiat values are available.
    """
    monthly_buy: Dict[str, float] = defaultdict(float)
    monthly_sell: Dict[str, float] = defaultdict(float)
    monthly_transfer: Dict[str, float] = defaultdict(float)

    for tx in txs:
        fv_str = tx.raw.get("fiat_value") or tx.raw.get("wartosc")
        if not fv_str:
            continue
        try:
            fv = abs(float(fv_str))
        except (ValueError, TypeError):
            continue
        month = tx.timestamp[:7] if tx.timestamp else "?"
        tt = tx.tx_type.lower()
        if tt == "buy":
            monthly_buy[month] += fv
        elif tt == "sell":
            monthly_sell[month] += fv
        elif tt == "withdrawal":
            monthly_transfer[month] += fv

    months = sorted(set(list(monthly_buy.keys()) + list(monthly_sell.keys()) + list(monthly_transfer.keys())))
    if not months:
        return {"labels": [], "buy": [], "sell": [], "transfer_out": []}

    return {
        "labels": months,
        "buy": [round(monthly_buy.get(m, 0), 2) for m in months],
        "sell": [round(monthly_sell.get(m, 0), 2) for m in months],
        "transfer_out": [round(monthly_transfer.get(m, 0), 2) for m in months],
    }


def _top_operations(txs: List[CryptoTransaction], limit: int = 15) -> Dict[str, Any]:
    """Distribution of operation types (raw operation strings from exchange)."""
    ops: Dict[str, int] = defaultdict(int)
    for tx in txs:
        op = tx.category or tx.raw.get("operation", "") or tx.tx_type
        ops[op] += 1
    sorted_ops = sorted(ops.items(), key=lambda x: -x[1])[:limit]
    return {
        "labels": [o for o, _ in sorted_ops],
        "data": [c for _, c in sorted_ops],
    }


# ── blockchain-specific charts ────────────────────────────────────────────

def _blockchain_balance_timeline(txs: List[CryptoTransaction]) -> Dict[str, Any]:
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
    by_date2: Dict[str, float] = {}
    for tx in sorted_txs:
        if tx.tx_type in ("deposit",):
            balance += float(tx.amount)
        elif tx.tx_type in ("withdrawal",):
            balance -= float(tx.amount)
        by_date2[tx.timestamp[:10]] = balance

    labels = sorted(by_date2.keys())
    return {
        "labels": labels,
        "data": [round(by_date2[d], 8) for d in labels],
        "label": "Saldo (obliczone)",
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


# ── common charts ─────────────────────────────────────────────────────────

def _monthly_volume(txs: List[CryptoTransaction]) -> Dict[str, Any]:
    """Monthly incoming vs outgoing volume."""
    received: Dict[str, float] = defaultdict(float)
    sent: Dict[str, float] = defaultdict(float)

    for tx in txs:
        if not tx.timestamp:
            continue
        month = tx.timestamp[:7]  # YYYY-MM
        raw_change = tx.raw.get("change", "")
        if tx.tx_type in ("deposit",) or (raw_change and not str(raw_change).lstrip().startswith("-")):
            received[month] += float(tx.amount)
        elif tx.tx_type in ("withdrawal",) or (raw_change and str(raw_change).lstrip().startswith("-")):
            sent[month] += float(tx.amount)

    months = sorted(set(list(received.keys()) + list(sent.keys())))
    return {
        "labels": months,
        "received": [round(received.get(m, 0), 8) for m in months],
        "sent": [round(sent.get(m, 0), 8) for m in months],
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
