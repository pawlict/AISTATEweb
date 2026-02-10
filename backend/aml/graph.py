"""Flow graph builder for AML analysis.

Constructs a directed graph of money flows:
- Nodes: ACCOUNT (own), COUNTERPARTY, MERCHANT, CASH_NODE, PAYMENT_PROVIDER
- Edges: TRANSFER, CARD_PAYMENT, BLIK_P2P, BLIK_MERCHANT, CASH, REFUND, FEE
- Clusters: group nodes by risk category (crypto, gambling, loans, etc.)

Output: JSON structure suitable for Cytoscape.js or D3.
"""

from __future__ import annotations

import json
from collections import defaultdict
from typing import Any, Dict, List, Optional

from ..db.engine import get_conn, new_id
from .normalize import NormalizedTransaction

# Risk category → cluster mapping
RISK_CLUSTERS = {
    "crypto": "CRYPTO",
    "crypto:exchange_polish": "CRYPTO",
    "crypto:exchange_global": "CRYPTO",
    "crypto:payment_processor": "CRYPTO",
    "gambling": "GAMBLING",
    "gambling:bookmaker": "GAMBLING",
    "gambling:casino": "GAMBLING",
    "gambling:lottery": "GAMBLING",
    "loans": "LOANS",
    "loans:payday": "LOANS",
    "loans:installment": "LOANS",
    "loans:debt_collection": "LOANS",
    "risky": "RISKY",
    "risky:foreign_transfer": "RISKY",
    "risky:pawnshop": "RISKY",
}


def build_graph(
    transactions: List[NormalizedTransaction],
    case_id: str = "",
    account_label: str = "Moje konto",
    save_to_db: bool = True,
) -> Dict[str, Any]:
    """Build flow graph from normalized transactions.

    Returns:
        {
            "nodes": [{id, type, label, risk_level, cluster, metadata}],
            "edges": [{id, source, target, type, tx_count, total_amount, ...}],
            "stats": {total_nodes, total_edges, clusters, ...}
        }
    """
    nodes: Dict[str, Dict[str, Any]] = {}
    edges: Dict[str, Dict[str, Any]] = {}

    # Create account node (own account)
    account_node_id = "account_own"
    nodes[account_node_id] = {
        "id": account_node_id,
        "type": "ACCOUNT",
        "label": account_label,
        "risk_level": "none",
        "cluster": "ACCOUNT",
        "metadata": {},
    }

    for tx in transactions:
        # Determine counterparty node
        cp_name = tx.counterparty_raw or tx.title or "Nieznany"
        cp_key = tx.counterparty_clean.lower()[:80] if tx.counterparty_clean else "unknown"
        cp_node_id = f"cp_{cp_key}"

        # Determine node type from channel
        if tx.channel in ("CARD", "BLIK_MERCHANT"):
            node_type = "MERCHANT"
        elif tx.channel == "CASH":
            node_type = "CASH_NODE"
        elif tx.channel == "FEE":
            node_type = "PAYMENT_PROVIDER"
        else:
            node_type = "COUNTERPARTY"

        # Determine risk level from tags
        risk_level = "none"
        if any(t in ("crypto", "gambling", "BLACKLISTED") for t in tx.risk_tags):
            risk_level = "high"
        elif any(t in ("risky", "loans") for t in tx.risk_tags):
            risk_level = "medium"
        elif tx.risk_score > 0:
            risk_level = "low"

        # Determine cluster from risk tags
        cluster = "NORMAL"
        for tag in tx.risk_tags:
            cl = RISK_CLUSTERS.get(tag)
            if cl:
                cluster = cl
                break

        # Create/update counterparty node
        if cp_node_id not in nodes:
            nodes[cp_node_id] = {
                "id": cp_node_id,
                "type": node_type,
                "label": cp_name[:60],
                "risk_level": risk_level,
                "cluster": cluster,
                "entity_id": tx.counterparty_id,
                "metadata": {
                    "categories": list(set(tx.risk_tags)),
                    "channel": tx.channel,
                    "total_amount": float(abs(tx.amount)),
                    "tx_count": 1,
                },
            }
        else:
            # Escalate risk level and update metadata
            existing = nodes[cp_node_id]
            risk_priority = {"none": 0, "low": 1, "medium": 2, "high": 3}
            if risk_priority.get(risk_level, 0) > risk_priority.get(existing["risk_level"], 0):
                existing["risk_level"] = risk_level
            cluster_priority = {"NORMAL": 0, "LOANS": 1, "RISKY": 2, "GAMBLING": 3, "CRYPTO": 3}
            if cluster_priority.get(cluster, 0) > cluster_priority.get(existing.get("cluster", "NORMAL"), 0):
                existing["cluster"] = cluster
            existing["metadata"]["total_amount"] = existing["metadata"].get("total_amount", 0) + float(abs(tx.amount))
            existing["metadata"]["tx_count"] = existing["metadata"].get("tx_count", 0) + 1

        # Create edge
        edge_type = _channel_to_edge_type(tx.channel)
        if tx.direction == "DEBIT":
            source_id, target_id = account_node_id, cp_node_id
        else:
            source_id, target_id = cp_node_id, account_node_id

        edge_key = f"{source_id}->{target_id}|{edge_type}"

        if edge_key not in edges:
            edges[edge_key] = {
                "id": edge_key,
                "source": source_id,
                "target": target_id,
                "type": edge_type,
                "tx_count": 0,
                "total_amount": 0.0,
                "first_date": "",
                "last_date": "",
                "tx_ids": [],
                "metadata": {},
            }

        edge = edges[edge_key]
        edge["tx_count"] += 1
        edge["total_amount"] += float(abs(tx.amount))
        if tx.booking_date:
            if not edge["first_date"] or tx.booking_date < edge["first_date"]:
                edge["first_date"] = tx.booking_date
            if not edge["last_date"] or tx.booking_date > edge["last_date"]:
                edge["last_date"] = tx.booking_date
        edge["tx_ids"].append(tx.id)

    # Round amounts
    for edge in edges.values():
        edge["total_amount"] = round(edge["total_amount"], 2)
        # Limit tx_ids to prevent huge payloads
        if len(edge["tx_ids"]) > 20:
            edge["tx_ids"] = edge["tx_ids"][:20]

    # Compute cluster stats
    cluster_counts: Dict[str, int] = defaultdict(int)
    for node in nodes.values():
        cluster_counts[node.get("cluster", "NORMAL")] += 1

    graph = {
        "nodes": list(nodes.values()),
        "edges": list(edges.values()),
        "stats": {
            "total_nodes": len(nodes),
            "total_edges": len(edges),
            "total_transactions": len(transactions),
            "clusters": dict(cluster_counts),
        },
    }

    # Persist to DB if requested
    if save_to_db and case_id:
        _save_graph_to_db(case_id, graph)

    return graph


def _channel_to_edge_type(channel: str) -> str:
    """Map channel to edge type."""
    mapping = {
        "CARD": "CARD_PAYMENT",
        "TRANSFER": "TRANSFER",
        "BLIK_P2P": "BLIK_P2P",
        "BLIK_MERCHANT": "BLIK_MERCHANT",
        "CASH": "CASH",
        "REFUND": "REFUND",
        "FEE": "FEE",
    }
    return mapping.get(channel, "TRANSFER")


def _save_graph_to_db(case_id: str, graph: Dict[str, Any]) -> None:
    """Persist graph nodes and edges to database."""
    with get_conn() as conn:
        # Clear existing graph for this case
        conn.execute("DELETE FROM graph_edges WHERE case_id = ?", (case_id,))
        conn.execute("DELETE FROM graph_nodes WHERE case_id = ?", (case_id,))

        # Build mapping from graph-local IDs to DB-unique IDs
        node_id_map: Dict[str, str] = {}

        # Insert nodes
        for node in graph["nodes"]:
            db_id = f"{case_id}:{node['id']}"
            node_id_map[node["id"]] = db_id
            conn.execute(
                """INSERT INTO graph_nodes (id, case_id, node_type, label, entity_id, risk_level, metadata)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (db_id, case_id, node["type"], node["label"],
                 node.get("entity_id", ""), node["risk_level"],
                 json.dumps(node.get("metadata", {}), ensure_ascii=False)),
            )

        # Insert edges
        for edge in graph["edges"]:
            db_id = f"{case_id}:{edge['id']}"
            conn.execute(
                """INSERT INTO graph_edges
                   (id, case_id, source_id, target_id, edge_type,
                    tx_count, total_amount, first_date, last_date, tx_ids, metadata)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (db_id, case_id,
                 node_id_map.get(edge["source"], edge["source"]),
                 node_id_map.get(edge["target"], edge["target"]),
                 edge["type"], edge["tx_count"], edge["total_amount"],
                 edge["first_date"], edge["last_date"],
                 json.dumps(edge["tx_ids"], ensure_ascii=False),
                 json.dumps(edge.get("metadata", {}), ensure_ascii=False)),
            )


def get_graph_json(case_id: str) -> Dict[str, Any]:
    """Load graph from database for a case."""
    from ..db.engine import fetch_all

    raw_nodes = fetch_all("SELECT * FROM graph_nodes WHERE case_id = ?", (case_id,))
    raw_edges = fetch_all("SELECT * FROM graph_edges WHERE case_id = ?", (case_id,))

    nodes = []
    for row in raw_nodes:
        node = dict(row)
        if node.get("metadata"):
            try:
                node["metadata"] = json.loads(node["metadata"])
            except (json.JSONDecodeError, TypeError):
                node["metadata"] = {}
        nodes.append(node)

    edges = []
    for row in raw_edges:
        edge = dict(row)
        # Map DB column names to graph JSON names
        edge["source"] = edge.pop("source_id", "")
        edge["target"] = edge.pop("target_id", "")
        edge["type"] = edge.pop("edge_type", "TRANSFER")
        for field in ("tx_ids", "metadata"):
            if edge.get(field):
                try:
                    edge[field] = json.loads(edge[field])
                except (json.JSONDecodeError, TypeError):
                    edge[field] = [] if field == "tx_ids" else {}
        edges.append(edge)

    return {
        "nodes": nodes,
        "edges": edges,
        "stats": {"total_nodes": len(nodes), "total_edges": len(edges)},
    }


def filter_graph(
    graph: Dict[str, Any],
    date_from: str = "",
    date_to: str = "",
    channels: Optional[List[str]] = None,
    risk_levels: Optional[List[str]] = None,
    counterparty_query: str = "",
) -> Dict[str, Any]:
    """Filter an existing graph by criteria."""
    edges = graph.get("edges", [])
    nodes_by_id = {n["id"]: n for n in graph.get("nodes", [])}

    filtered_edges = []
    used_node_ids = set()

    for edge in edges:
        # Date filter
        if date_from and edge.get("last_date", "") < date_from:
            continue
        if date_to and edge.get("first_date", "") > date_to:
            continue

        # Channel filter
        if channels and edge.get("type") not in channels:
            continue

        # Risk filter (check both source and target nodes)
        if risk_levels:
            src_node = nodes_by_id.get(edge["source"], {})
            tgt_node = nodes_by_id.get(edge["target"], {})
            if (src_node.get("risk_level") not in risk_levels and
                    tgt_node.get("risk_level") not in risk_levels):
                continue

        # Counterparty name filter
        if counterparty_query:
            src_node = nodes_by_id.get(edge["source"], {})
            tgt_node = nodes_by_id.get(edge["target"], {})
            q = counterparty_query.lower()
            if q not in src_node.get("label", "").lower() and \
               q not in tgt_node.get("label", "").lower():
                continue

        filtered_edges.append(edge)
        used_node_ids.add(edge["source"])
        used_node_ids.add(edge["target"])

    filtered_nodes = [n for n in graph["nodes"] if n["id"] in used_node_ids]

    return {
        "nodes": filtered_nodes,
        "edges": filtered_edges,
        "stats": {
            "total_nodes": len(filtered_nodes),
            "total_edges": len(filtered_edges),
        },
    }
