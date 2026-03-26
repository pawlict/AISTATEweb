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
import re
import time
from collections import defaultdict
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

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


# ---------------------------------------------------------------------------
# Phone number extraction from transaction fields
# ---------------------------------------------------------------------------

_PHONE_RE = re.compile(r"(?<!\d)(?:\+?\d[\d\s\-]{7,16}\d)(?!\d)")


def _identify_phone_country(number: str) -> Optional[Tuple[str, str]]:
    """Identify country by phone prefix. Reuses GSM module if available."""
    try:
        from backend.gsm.analyzer import _identify_country_by_prefix
        return _identify_country_by_prefix(number)
    except ImportError:
        pass
    # Fallback: minimal prefix table
    _BASIC = [
        ("+48", "PL", "Polska"), ("+1", "US", "USA/Kanada"),
        ("+44", "GB", "Wielka Brytania"), ("+49", "DE", "Niemcy"),
        ("+33", "FR", "Francja"), ("+380", "UA", "Ukraina"),
        ("+7", "RU", "Rosja"), ("+86", "CN", "Chiny"),
        ("+90", "TR", "Turcja"), ("+971", "AE", "ZEA"),
        ("+234", "NG", "Nigeria"), ("+91", "IN", "Indie"),
    ]
    if not number.startswith("+"):
        return None
    for prefix, iso, name in _BASIC:
        if number.startswith(prefix):
            return (iso, name)
    return None


def _normalize_phone(raw: str) -> Optional[str]:
    """Normalize a candidate phone number to +CC format."""
    digits = re.sub(r"[^\d+]", "", raw.strip())
    if not digits:
        return None
    if digits.startswith("00") and len(digits) >= 10:
        digits = "+" + digits[2:]
    elif digits.startswith("+"):
        pass
    elif len(digits) == 9:
        digits = "+48" + digits
    elif len(digits) >= 10 and not digits.startswith("+"):
        digits = "+" + digits
    if not re.match(r"^\+\d{7,15}$", digits):
        return None
    return digits


def _extract_phone_numbers(txs: List[CryptoTransaction]) -> List[Dict[str, Any]]:
    """Scan transaction fields for phone number patterns.

    Only scans fields that could plausibly contain phone numbers.
    Skips numeric IDs (Binance User IDs, Order IDs, TX IDs etc.) that
    produce false-positive matches.

    Returns list of {number, country_iso, country_name, occurrences, contexts[]}.
    """
    phone_map: Dict[str, Dict[str, Any]] = {}

    # Raw fields that are NEVER phone numbers — numeric IDs, amounts, technical data
    _SKIP_RAW_KEYS = {
        "sheet", "account", "status", "side", "direction",
        "counterparty_id", "counterparty_binance_id", "counterparty_wallet_id",
        "order_id", "tx_id", "txId", "transaction_id",
        "market", "market_id", "pair",
        "total_value", "price", "quantity", "qty", "fee", "fee_coin",
        "network", "chain", "quote_token", "base_token",
        "change", "BUSD_value", "busd_value",
        "card_number", "card_type", "card_status",
        "operation", "type", "sub_type",
        "user_id", "uid",
    }

    for tx in txs:
        # Only scan raw fields that could plausibly contain phone numbers
        # (free-text fields like notes, descriptions, merchant names)
        fields = []
        for key, val in (tx.raw or {}).items():
            if key in _SKIP_RAW_KEYS:
                continue
            fields.append((key, str(val)))

        for field_name, field_val in fields:
            if not field_val:
                continue
            for match in _PHONE_RE.finditer(str(field_val)):
                raw_num = match.group(0).strip()

                # Must have explicit country code prefix (+XX or 00XX) to be a phone
                # Pure digit strings (like Binance IDs) are NOT phone numbers
                if not raw_num.startswith("+") and not raw_num.startswith("00"):
                    continue

                normalized = _normalize_phone(raw_num)
                if not normalized:
                    continue

                if normalized not in phone_map:
                    country = _identify_phone_country(normalized)
                    phone_map[normalized] = {
                        "number": normalized,
                        "country_iso": country[0] if country else "",
                        "country_name": country[1] if country else "",
                        "occurrences": 0,
                        "contexts": [],
                    }
                entry = phone_map[normalized]
                entry["occurrences"] += 1
                if len(entry["contexts"]) < 5:
                    entry["contexts"].append({
                        "field": field_name,
                        "tx_type": tx.tx_type,
                        "timestamp": tx.timestamp[:10] if tx.timestamp else "",
                        "token": tx.token,
                        "amount": _dec_to_float(tx.amount),
                    })

    return sorted(phone_map.values(), key=lambda x: x["occurrences"], reverse=True)


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

    # 4c. Phone number extraction from transaction data
    detected_phones = _extract_phone_numbers(txs)

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

    # Unique counterparties (normalized to avoid case-duplicates for EVM addresses)
    def _norm_addr(a: str) -> str:
        a = a.strip()
        return a.lower() if a.startswith("0x") or a.startswith("0X") else a

    counterparties = set()
    for tx in txs:
        if tx.from_address:
            counterparties.add(_norm_addr(tx.from_address))
        if tx.to_address:
            counterparties.add(_norm_addr(tx.to_address))
        if tx.counterparty:
            counterparties.add(_norm_addr(tx.counterparty))

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
            for w in wallets
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
            for tx in txs
        ],
        "transactions_total": len(txs),
        "llm_prompt": llm_prompt,
        "behavior_profile": behavior_profile,
        "detected_phones": detected_phones,
        "binance_summary": binance_summary,
        "forensic_report": forensic_report,
        "elapsed_sec": round(elapsed, 2),
    }
