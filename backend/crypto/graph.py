"""Flow graph builder for crypto transactions (Cytoscape.js format)."""
from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any, Dict, List, Set

from .parsers.base import CryptoTransaction

log = logging.getLogger("aistate.crypto.graph")

# Known labels for risk coloring
_RISK_LABELS = {"coinjoin", "mixer", "sanctioned", "privacy_coin", "high_value"}


def build_crypto_graph(
    txs: List[CryptoTransaction],
    max_nodes: int = 200,
    max_edges: int = 500,
) -> Dict[str, Any]:
    """Build a Cytoscape.js-compatible graph from transactions.

    Returns {"nodes": [...], "edges": [...]} where each node/edge has
    the structure expected by Cytoscape.js elements format.
    """
    # Aggregate edges: (from, to) → {total_amount, count, risk_tags}
    edge_agg: Dict[tuple, Dict[str, Any]] = {}
    node_set: Set[str] = set()

    for tx in txs:
        src = tx.from_address or "(unknown)"
        tgt = tx.to_address or "(unknown)"
        if src == tgt:
            continue

        node_set.add(src)
        node_set.add(tgt)

        key = (src, tgt)
        if key not in edge_agg:
            edge_agg[key] = {"amount": 0.0, "count": 0, "risk_tags": set(), "token": tx.token}
        edge_agg[key]["amount"] += float(tx.amount)
        edge_agg[key]["count"] += 1
        edge_agg[key]["risk_tags"].update(tx.risk_tags)

    # Compute node properties
    node_in: Dict[str, float] = defaultdict(float)
    node_out: Dict[str, float] = defaultdict(float)
    node_risk: Dict[str, Set[str]] = defaultdict(set)
    node_tx_count: Dict[str, int] = defaultdict(int)

    for (src, tgt), info in edge_agg.items():
        node_out[src] += info["amount"]
        node_in[tgt] += info["amount"]
        node_risk[src].update(info["risk_tags"])
        node_risk[tgt].update(info["risk_tags"])
        node_tx_count[src] += info["count"]
        node_tx_count[tgt] += info["count"]

    # Limit nodes by tx count (keep most active)
    if len(node_set) > max_nodes:
        ranked = sorted(node_set, key=lambda n: -node_tx_count.get(n, 0))
        node_set = set(ranked[:max_nodes])

    # Build Cytoscape nodes
    nodes = []
    for addr in node_set:
        risk_tags = node_risk.get(addr, set())
        risk_level = "low"
        if risk_tags & {"sanctioned"}:
            risk_level = "critical"
        elif risk_tags & {"mixer", "coinjoin"}:
            risk_level = "high"
        elif risk_tags & {"high_value", "privacy_coin"}:
            risk_level = "medium"

        # Determine node type
        node_type = "wallet"
        label = _shorten(addr)
        if "coinjoin" in addr.lower() or "mixer" in str(risk_tags):
            node_type = "mixer"
        elif any(ex in addr.lower() for ex in ("binance", "coinbase", "kraken", "bitfinex")):
            node_type = "exchange"

        # Counterparty label from transactions
        for tx in txs:
            if tx.counterparty and (tx.from_address == addr or tx.to_address == addr):
                if tx.counterparty != addr:
                    label = _shorten(tx.counterparty)
                break

        nodes.append({
            "data": {
                "id": addr,
                "label": label,
                "type": node_type,
                "risk_level": risk_level,
                "total_in": round(node_in.get(addr, 0), 8),
                "total_out": round(node_out.get(addr, 0), 8),
                "tx_count": node_tx_count.get(addr, 0),
                "risk_tags": list(risk_tags),
            }
        })

    # Build Cytoscape edges (filter to only included nodes)
    edges = []
    sorted_edges = sorted(edge_agg.items(), key=lambda x: -x[1]["amount"])
    for (src, tgt), info in sorted_edges:
        if src not in node_set or tgt not in node_set:
            continue
        if len(edges) >= max_edges:
            break
        has_risk = bool(info["risk_tags"] & _RISK_LABELS)
        edges.append({
            "data": {
                "source": src,
                "target": tgt,
                "amount": round(info["amount"], 8),
                "count": info["count"],
                "token": info["token"],
                "risk": has_risk,
                "risk_tags": list(info["risk_tags"]),
            }
        })

    return {
        "nodes": nodes,
        "edges": edges,
        "stats": {
            "total_nodes": len(nodes),
            "total_edges": len(edges),
            "filtered_from_nodes": len(node_set),
        },
    }


def build_exchange_flow_graph(
    txs: List[CryptoTransaction],
) -> Dict[str, Any]:
    """Build a flow graph for exchange/custodial data (Cytoscape.js format).

    Unlike blockchain graphs (address→address), exchange data shows logical
    flows: FIAT → TOKEN → EXTERNAL, with fiat values on edges.

    Node types:
    - ``fiat``  — fiat currency pool (PLN, EUR, USD)
    - ``token`` — crypto token pool (BTC, ETH, XRP…)
    - ``external`` — funds leaving the exchange (withdrawals)
    - ``staking`` — staking/reward income
    """
    edge_agg: Dict[tuple, Dict[str, Any]] = {}
    node_meta: Dict[str, Dict[str, Any]] = {}

    def _ensure_node(nid: str, ntype: str, label: str) -> None:
        if nid not in node_meta:
            node_meta[nid] = {"type": ntype, "label": label, "total_in": 0.0, "total_out": 0.0, "count": 0}

    for tx in txs:
        tt = tx.tx_type.lower()
        token = tx.token or "UNKNOWN"
        fv_str = tx.raw.get("fiat_value") or tx.raw.get("wartosc")
        fc = tx.raw.get("fiat_currency") or tx.raw.get("currency", "PLN")
        try:
            fiat_val = abs(float(fv_str)) if fv_str else 0.0
        except (ValueError, TypeError):
            fiat_val = 0.0

        token_id = f"TOKEN:{token}"
        fiat_id = f"FIAT:{fc}"

        if tt == "buy":
            # FIAT → TOKEN
            _ensure_node(fiat_id, "fiat", fc)
            _ensure_node(token_id, "token", token)
            key = (fiat_id, token_id)
            edge_label = f"Kupno {token}"
        elif tt == "sell":
            # TOKEN → FIAT
            _ensure_node(token_id, "token", token)
            _ensure_node(fiat_id, "fiat", fc)
            key = (token_id, fiat_id)
            edge_label = f"Sprzedaż {token}"
        elif tt == "withdrawal":
            # TOKEN → EXTERNAL
            _ensure_node(token_id, "token", token)
            _ensure_node("EXTERNAL", "external", "Portfele zewnętrzne")
            key = (token_id, "EXTERNAL")
            edge_label = f"Wypłata {token}"
        elif tt in ("staking_reward", "learn_reward"):
            # STAKING → TOKEN
            _ensure_node("STAKING", "staking", "Staking / Nagrody")
            _ensure_node(token_id, "token", token)
            key = ("STAKING", token_id)
            edge_label = f"Nagroda {token}"
        else:
            continue

        if key not in edge_agg:
            edge_agg[key] = {"amount": 0.0, "count": 0, "label": edge_label, "risk_tags": set()}
        edge_agg[key]["amount"] += fiat_val
        edge_agg[key]["count"] += 1
        edge_agg[key]["risk_tags"].update(tx.risk_tags or [])

        # Update node totals
        node_meta[key[0]]["total_out"] += fiat_val
        node_meta[key[0]]["count"] += 1
        node_meta[key[1]]["total_in"] += fiat_val
        node_meta[key[1]]["count"] += 1

    # Build Cytoscape nodes
    nodes = []
    for nid, meta in node_meta.items():
        nodes.append({
            "data": {
                "id": nid,
                "label": meta["label"],
                "type": meta["type"],
                "risk_level": "low",
                "total_in": round(meta["total_in"], 2),
                "total_out": round(meta["total_out"], 2),
                "tx_count": meta["count"],
                "risk_tags": [],
            }
        })

    # Build Cytoscape edges
    edges = []
    for (src, tgt), info in sorted(edge_agg.items(), key=lambda x: -x[1]["amount"]):
        has_risk = bool(info["risk_tags"] & _RISK_LABELS)
        edges.append({
            "data": {
                "source": src,
                "target": tgt,
                "amount": round(info["amount"], 2),
                "count": info["count"],
                "token": info["label"],
                "risk": has_risk,
                "risk_tags": list(info["risk_tags"]),
            }
        })

    return {
        "nodes": nodes,
        "edges": edges,
        "stats": {
            "total_nodes": len(nodes),
            "total_edges": len(edges),
        },
    }


def _shorten(addr: str) -> str:
    if len(addr) > 18:
        return addr[:8] + "…" + addr[-6:]
    return addr
