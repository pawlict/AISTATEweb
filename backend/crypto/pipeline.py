"""Crypto analysis pipeline — end-to-end orchestration."""
from __future__ import annotations

import json
import logging
import time
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional

from .parsers import parse_crypto_file, CryptoTransaction, WalletInfo, ParsedCryptoData
from .risk_rules import classify_transactions, compute_overall_risk
from .risk_rules import detect_peel_chain, detect_dust_attack, detect_round_trip, detect_smurfing
from .charts import generate_all_charts
from .graph import build_crypto_graph
from .llm_analysis import build_crypto_prompt

log = logging.getLogger("aistate.crypto.pipeline")


def _dec_to_float(val: Any) -> float:
    if isinstance(val, Decimal):
        return float(val)
    return val


def run_crypto_pipeline(
    file_path: str,
    project_id: str = "",
    filename: str = "",
) -> Dict[str, Any]:
    """Run full crypto analysis pipeline on an uploaded file.

    Returns a JSON-serializable dict with all analysis results.
    """
    t0 = time.time()
    path = Path(file_path)
    log.info(f"Crypto pipeline: {path.name}")

    # 1. Parse file
    parsed: ParsedCryptoData = parse_crypto_file(path)

    if parsed.errors:
        return {"ok": False, "errors": parsed.errors}

    txs = parsed.transactions
    if not txs:
        return {"ok": False, "errors": ["Brak transakcji w pliku."]}

    # 2. Classify transactions (risk rules)
    txs = classify_transactions(txs)

    # 3. Detect patterns
    alerts: List[Dict[str, Any]] = []
    alerts.extend(detect_peel_chain(txs))
    alerts.extend(detect_dust_attack(txs))
    alerts.extend(detect_round_trip(txs))
    alerts.extend(detect_smurfing(txs))

    # 4. Compute overall risk
    risk_score, risk_reasons = compute_overall_risk(txs, alerts)

    # 5. Build wallet info
    wallets = parsed.wallets

    # 6. Generate charts
    charts = generate_all_charts(txs)

    # 7. Build flow graph
    graph = build_crypto_graph(txs)

    # 8. Build LLM prompt
    llm_prompt = build_crypto_prompt(
        txs=txs,
        wallets=wallets,
        alerts=alerts,
        risk_score=risk_score,
        risk_reasons=risk_reasons,
        source=parsed.source,
        chain=parsed.chain,
    )

    # 9. Summary statistics
    total_received = sum(float(tx.amount) for tx in txs if tx.tx_type in ("deposit", "transfer") and tx.to_address)
    total_sent = sum(float(tx.amount) for tx in txs if tx.tx_type in ("withdrawal",) and tx.from_address)
    tokens = {}
    for tx in txs:
        t = tx.token or "UNKNOWN"
        if t not in tokens:
            tokens[t] = {"received": 0.0, "sent": 0.0, "count": 0}
        tokens[t]["count"] += 1
        if tx.tx_type in ("deposit",):
            tokens[t]["received"] += float(tx.amount)
        elif tx.tx_type in ("withdrawal",):
            tokens[t]["sent"] += float(tx.amount)

    # Date range
    dates = [tx.timestamp for tx in txs if tx.timestamp]
    date_from = min(dates) if dates else ""
    date_to = max(dates) if dates else ""

    # Unique counterparties
    counterparties = set()
    for tx in txs:
        if tx.from_address:
            counterparties.add(tx.from_address)
        if tx.to_address:
            counterparties.add(tx.to_address)

    elapsed = time.time() - t0
    log.info(f"Crypto pipeline done: {len(txs)} txs, {elapsed:.2f}s")

    return {
        "ok": True,
        "source": parsed.source,
        "chain": parsed.chain,
        "filename": filename or path.name,
        "tx_count": len(txs),
        "wallet_count": len(wallets),
        "counterparty_count": len(counterparties),
        "date_from": date_from,
        "date_to": date_to,
        "total_received": round(total_received, 8),
        "total_sent": round(total_sent, 8),
        "tokens": tokens,
        "risk_score": round(risk_score, 1),
        "risk_reasons": risk_reasons,
        "alerts": alerts,
        "charts": charts,
        "graph": graph,
        "wallets": [
            {
                "address": w.address,
                "chain": w.chain,
                "label": w.label,
                "tx_count": w.tx_count,
                "total_received": _dec_to_float(w.total_received),
                "total_sent": _dec_to_float(w.total_sent),
                "risk_level": w.risk_level,
                "risk_reasons": w.risk_reasons,
            }
            for w in wallets[:200]  # limit for JSON size
        ],
        "transactions": [
            {
                "tx_hash": tx.tx_hash,
                "timestamp": tx.timestamp,
                "from": tx.from_address,
                "to": tx.to_address,
                "amount": _dec_to_float(tx.amount),
                "token": tx.token,
                "tx_type": tx.tx_type,
                "counterparty": tx.counterparty,
                "risk_score": tx.risk_score,
                "risk_tags": tx.risk_tags,
            }
            for tx in txs
        ],
        "llm_prompt": llm_prompt,
        "elapsed_sec": round(elapsed, 2),
    }
