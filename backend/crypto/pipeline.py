"""Crypto analysis pipeline — end-to-end orchestration.

Supports two analysis modes determined by ``source_type``:
  - ``"exchange"`` — centralised exchange statements (Binance PDF/CSV, Kraken, …)
  - ``"blockchain"`` — on-chain explorer data (WalletExplorer, Etherscan, …)

The pipeline automatically selects appropriate risk rules, charts, graph
building and LLM prompt style based on the detected source type.
"""
from __future__ import annotations

import json
import logging
import time
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional

from .parsers import parse_crypto_file, CryptoTransaction, WalletInfo, ParsedCryptoData
from .risk_rules import classify_transactions, compute_overall_risk, detect_all_patterns
from .charts import generate_all_charts
from .graph import build_crypto_graph
from .llm_analysis import build_crypto_prompt
from .behavior import profile_user_behavior

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

    source_type = parsed.source_type or "blockchain"

    # 2. Classify transactions (risk rules — mode-aware)
    txs = classify_transactions(txs, source_type=source_type)

    # 3. Detect patterns (mode-aware)
    alerts = detect_all_patterns(txs, source_type=source_type)

    # 4. Compute overall risk
    risk_score, risk_reasons = compute_overall_risk(txs, alerts, source_type=source_type)

    # 4b. User behavior profiling
    behavior_profile = profile_user_behavior(txs, source_type=source_type)

    # 5. Build wallet info
    wallets = parsed.wallets

    # 6. Generate charts (mode-aware)
    charts = generate_all_charts(txs, source_type=source_type)

    # 7. Build flow graph (blockchain only — exchange data has no addresses)
    graph: Dict[str, Any] = {"nodes": [], "edges": [], "stats": {"total_nodes": 0, "total_edges": 0}}
    if source_type == "blockchain":
        graph = build_crypto_graph(txs)

    # 8. Build LLM prompt (mode-aware)
    llm_prompt = build_crypto_prompt(
        txs=txs,
        wallets=wallets,
        alerts=alerts,
        risk_score=risk_score,
        risk_reasons=risk_reasons,
        source=parsed.source,
        chain=parsed.chain,
        source_type=source_type,
    )

    # 9. Summary statistics
    total_received = sum(
        float(tx.amount) for tx in txs
        if tx.tx_type in ("deposit", "transfer") and (tx.to_address or source_type == "exchange")
    )
    total_sent = sum(
        float(tx.amount) for tx in txs
        if tx.tx_type in ("withdrawal",) and (tx.from_address or source_type == "exchange")
    )

    # Token breakdown
    tokens: Dict[str, Dict[str, Any]] = {}
    for tx in txs:
        t = tx.token or "UNKNOWN"
        if t not in tokens:
            tokens[t] = {"received": 0.0, "sent": 0.0, "count": 0}
        tokens[t]["count"] += 1
        raw_change = tx.raw.get("change", "")
        if tx.tx_type in ("deposit",) or (raw_change and not str(raw_change).lstrip().startswith("-")):
            tokens[t]["received"] += float(tx.amount)
        elif tx.tx_type in ("withdrawal",) or (raw_change and str(raw_change).lstrip().startswith("-")):
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
        if tx.counterparty:
            counterparties.add(tx.counterparty)

    # Exchange-specific metadata
    _FIAT = {"PLN", "USD", "EUR", "GBP", "CHF", "CZK", "TRY", "BRL", "AUD", "CAD", "JPY", "KRW"}
    exchange_meta: Dict[str, Any] = {}
    if source_type == "exchange":
        exchange_meta = {
            "exchange_name": parsed.source.replace("_pdf", "").replace("_trade", "").replace("_xlsx", "").title(),
            "account_types": sorted({tx.raw.get("account", "") for tx in txs if tx.raw.get("account")}),
            "fiat_tokens": sorted({tx.token for tx in txs if tx.token in _FIAT}),
            "crypto_tokens": sorted({tx.token for tx in txs if tx.token not in _FIAT}),
        }

    # Binance XLSX — add rich summary and forensic report
    binance_summary: Dict[str, Any] = {}
    forensic_report: Dict[str, Any] = {}
    if parsed.source == "binance_xlsx":
        try:
            from .parsers.binance_xlsx import build_binance_summary, build_forensic_report
            binance_summary = build_binance_summary(parsed)
            forensic_report = build_forensic_report(path, parsed)
        except Exception as e:
            log.warning("Error building binance summary/forensic: %s", e)

    elapsed = time.time() - t0
    log.info(f"Crypto pipeline done: {len(txs)} txs, source_type={source_type}, {elapsed:.2f}s")

    return {
        "ok": True,
        "source": parsed.source,
        "source_type": source_type,
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
        "exchange_meta": exchange_meta,
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
            for w in wallets[:200]
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
                "category": tx.category,
                "counterparty": tx.counterparty,
                "risk_score": tx.risk_score,
                "risk_tags": tx.risk_tags,
                "raw": {k: str(v) for k, v in (tx.raw or {}).items()},
            }
            for tx in txs[:2000]
        ],
        "transactions_truncated": len(txs) > 2000,
        "transactions_total": len(txs),
        "llm_prompt": llm_prompt,
        "behavior_profile": behavior_profile,
        "binance_summary": binance_summary,
        "forensic_report": forensic_report,
        "elapsed_sec": round(elapsed, 2),
    }
