"""Generic crypto CSV/JSON parser with auto-detection of exchange format."""
from __future__ import annotations

import csv
import io
import json
import logging
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .base import CryptoTransaction, ParsedCryptoData, WalletInfo

log = logging.getLogger("aistate.crypto.parser")

# ---------------------------------------------------------------------------
# Column signature → exchange detection
# ---------------------------------------------------------------------------

_EXCHANGE_SIGNATURES: Dict[str, List[str]] = {
    "binance": ["user_id", "utc_time", "account", "operation", "coin", "change"],
    "binance_trade": ["date(utc)", "market", "type", "price", "amount", "total", "fee"],
    "coinbase": ["timestamp", "transaction type", "asset", "quantity purchased", "spot price"],
    "coinbase_pro": ["portfolio", "trade id", "product", "side", "created at", "size", "price", "fee"],
    "kraken": ["txid", "refid", "time", "type", "subtype", "aclass", "asset", "amount", "fee"],
    "kraken_ledger": ["txid", "refid", "time", "type", "subtype", "aclass", "asset", "amount", "fee", "balance"],
    "bybit": ["user id", "date(utc)", "coin", "type", "amount", "wallet balance"],
    "kucoin": ["uid", "account type", "time", "symbol", "direction", "amount", "fee"],
    "etherscan": ["txhash", "blockno", "unixtime", "datetime (utc)", "from", "to", "value"],
    "etherscan_token": ["txhash", "blockno", "unixtime", "datetime (utc)", "from", "to", "tokenvalue"],
    "etherscan_internal": ["txhash", "blockno", "unixtime", "datetime (utc)", "parenttxfrom", "parenttxto"],
    "blockchair": ["block_id", "hash", "time", "sender", "recipient", "value"],
    "electrum": ["transaction_hash", "label", "confirmations", "value", "fiat_value", "fee", "timestamp"],
    "metamask": ["date", "status", "type", "from", "to", "amount", "token"],
    "ledger": ["operation date", "currency ticker", "operation type", "operation amount", "operation fees"],
    "trezor": ["date & time", "type", "transaction id", "fee", "address"],
}


def _normalize_columns(headers: List[str]) -> List[str]:
    """Lowercase + strip column names for matching."""
    return [h.strip().lower().replace("_", " ").replace("-", " ") for h in headers]


def detect_format(headers: List[str]) -> str:
    """Detect exchange format from CSV column names."""
    norm = set(_normalize_columns(headers))
    best_match = ""
    best_score = 0

    for exchange, sig_cols in _EXCHANGE_SIGNATURES.items():
        sig_norm = set(_normalize_columns(sig_cols))
        overlap = len(sig_norm & norm)
        if overlap >= 3 and overlap > best_score:
            best_score = overlap
            best_match = exchange

    return best_match or "generic"


# ---------------------------------------------------------------------------
# Safe value helpers
# ---------------------------------------------------------------------------

def _dec(val: Any) -> Decimal:
    """Parse a value to Decimal, handling commas and currency symbols."""
    if val is None:
        return Decimal("0")
    s = str(val).strip().replace(",", ".").replace(" ", "")
    # Remove currency symbols/suffixes
    s = re.sub(r"[A-Za-z$€£¥₿]+$", "", s).strip()
    s = re.sub(r"^[A-Za-z$€£¥₿]+", "", s).strip()
    if not s or s == "-":
        return Decimal("0")
    try:
        return Decimal(s)
    except InvalidOperation:
        return Decimal("0")


def _ts(val: Any) -> str:
    """Normalize a timestamp to ISO 8601 string."""
    if not val:
        return ""
    s = str(val).strip()
    # Try common formats
    for fmt in [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%d/%m/%Y %H:%M:%S",
        "%d/%m/%Y %H:%M",
        "%m/%d/%Y %H:%M:%S",
    ]:
        try:
            dt = datetime.strptime(s, fmt)
            return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            continue
    # Unix timestamp
    try:
        ts_val = float(s)
        if ts_val > 1e12:
            ts_val /= 1000  # ms → s
        dt = datetime.utcfromtimestamp(ts_val)
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    except (ValueError, OSError):
        pass
    return s


# ---------------------------------------------------------------------------
# Exchange-specific parsers
# ---------------------------------------------------------------------------

def _parse_binance(rows: List[Dict[str, str]]) -> List[CryptoTransaction]:
    """Parse Binance trade/transaction history CSV."""
    txs = []
    for row in rows:
        # Binance has two CSV formats: trade history and transaction history
        ts = row.get("UTC_Time") or row.get("Date(UTC)") or row.get("utc_time", "")
        coin = row.get("Coin") or row.get("coin") or row.get("Asset", "")
        amount = _dec(row.get("Change") or row.get("change") or row.get("Amount") or row.get("Total", "0"))
        op = (row.get("Operation") or row.get("operation") or row.get("Type") or row.get("type") or "").lower()

        tx_type = "transfer"
        if "deposit" in op:
            tx_type = "deposit"
        elif "withdraw" in op:
            tx_type = "withdrawal"
        elif "buy" in op or "sell" in op or "trade" in op:
            tx_type = "swap"
        elif "fee" in op:
            tx_type = "fee"

        txs.append(CryptoTransaction(
            timestamp=_ts(ts),
            amount=abs(amount),
            token=coin.upper(),
            chain="binance",
            tx_type=tx_type,
            exchange="binance",
            raw=dict(row),
        ))
    return txs


def _parse_etherscan(rows: List[Dict[str, str]]) -> List[CryptoTransaction]:
    """Parse Etherscan CSV export (normal/internal/token transactions)."""
    txs = []
    for row in rows:
        tx_hash = row.get("Txhash") or row.get("txhash") or row.get("Transaction Hash", "")
        ts = row.get("DateTime (UTC)") or row.get("datetime (utc)") or row.get("UnixTimestamp") or ""
        from_addr = row.get("From") or row.get("from") or ""
        to_addr = row.get("To") or row.get("to") or ""
        value = _dec(row.get("Value_IN(ETH)") or row.get("Value_OUT(ETH)") or
                     row.get("Value") or row.get("value") or row.get("TokenValue") or "0")
        fee = _dec(row.get("TxnFee(ETH)") or row.get("txnfee(eth)") or "0")
        token = row.get("TokenSymbol") or row.get("tokensymbol") or "ETH"
        method = row.get("Method") or row.get("method") or ""
        block = row.get("Blockno") or row.get("blockno") or ""
        status = row.get("Status") or ""
        contract = row.get("ContractAddress") or row.get("contractaddress") or ""

        tx_type = "transfer"
        if method:
            ml = method.lower()
            if "swap" in ml:
                tx_type = "swap"
            elif "approve" in ml:
                tx_type = "contract_call"
            elif "mint" in ml:
                tx_type = "mint"
            elif "burn" in ml:
                tx_type = "burn"

        txs.append(CryptoTransaction(
            tx_hash=tx_hash,
            timestamp=_ts(ts),
            from_address=from_addr.lower(),
            to_address=to_addr.lower(),
            amount=abs(value),
            token=token.upper(),
            fee=fee,
            fee_token="ETH",
            chain="ethereum",
            tx_type=tx_type,
            status="confirmed" if status != "Error" else "failed",
            block_number=int(block) if block and block.isdigit() else None,
            contract_address=contract.lower() if contract else None,
            method_name=method if method else None,
            exchange="etherscan_export",
            raw=dict(row),
        ))
    return txs


def _parse_kraken(rows: List[Dict[str, str]]) -> List[CryptoTransaction]:
    """Parse Kraken ledger/trade CSV."""
    txs = []
    for row in rows:
        txid = row.get("txid") or row.get("refid") or ""
        ts = row.get("time") or ""
        tx_type_raw = (row.get("type") or "").lower()
        asset = row.get("asset") or ""
        amount = _dec(row.get("amount") or "0")
        fee = _dec(row.get("fee") or "0")

        tx_type = "transfer"
        if tx_type_raw in ("deposit",):
            tx_type = "deposit"
        elif tx_type_raw in ("withdrawal",):
            tx_type = "withdrawal"
        elif tx_type_raw in ("trade",):
            tx_type = "swap"
        elif tx_type_raw in ("staking",):
            tx_type = "staking"

        # Kraken asset codes: XXBT → BTC, XETH → ETH, ZUSD → USD
        token = asset.upper()
        if token.startswith("X") or token.startswith("Z"):
            token = token[1:]
        token = token.replace("XBT", "BTC")

        txs.append(CryptoTransaction(
            tx_hash=txid,
            timestamp=_ts(ts),
            amount=abs(amount),
            token=token,
            fee=fee,
            fee_token=token,
            chain="kraken",
            tx_type=tx_type,
            exchange="kraken",
            raw=dict(row),
        ))
    return txs


def _parse_generic(rows: List[Dict[str, str]]) -> List[CryptoTransaction]:
    """Best-effort generic CSV parser."""
    txs = []
    for row in rows:
        # Try to find common column names
        norm = {k.lower().strip(): v for k, v in row.items()}

        tx_hash = norm.get("hash") or norm.get("txhash") or norm.get("tx_hash") or norm.get("transaction_hash") or ""
        ts = (norm.get("timestamp") or norm.get("date") or norm.get("time") or
              norm.get("datetime") or norm.get("date(utc)") or norm.get("created at") or "")
        from_addr = norm.get("from") or norm.get("sender") or norm.get("from_address") or ""
        to_addr = norm.get("to") or norm.get("recipient") or norm.get("to_address") or ""
        amount = _dec(norm.get("amount") or norm.get("value") or norm.get("quantity") or
                      norm.get("size") or norm.get("total") or "0")
        token = (norm.get("token") or norm.get("coin") or norm.get("asset") or
                 norm.get("currency") or norm.get("symbol") or "").upper()
        fee = _dec(norm.get("fee") or norm.get("fees") or norm.get("commission") or "0")
        tx_type_raw = (norm.get("type") or norm.get("operation") or norm.get("side") or
                       norm.get("transaction type") or "").lower()

        tx_type = "transfer"
        if "deposit" in tx_type_raw:
            tx_type = "deposit"
        elif "withdraw" in tx_type_raw:
            tx_type = "withdrawal"
        elif "swap" in tx_type_raw or "trade" in tx_type_raw or "buy" in tx_type_raw or "sell" in tx_type_raw:
            tx_type = "swap"

        txs.append(CryptoTransaction(
            tx_hash=tx_hash,
            timestamp=_ts(ts),
            from_address=from_addr,
            to_address=to_addr,
            amount=abs(amount),
            token=token or "UNKNOWN",
            fee=fee,
            chain="unknown",
            tx_type=tx_type,
            raw=dict(row),
        ))
    return txs


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

_PARSER_MAP = {
    "binance": _parse_binance,
    "binance_trade": _parse_binance,
    "etherscan": _parse_etherscan,
    "etherscan_token": _parse_etherscan,
    "etherscan_internal": _parse_etherscan,
    "kraken": _parse_kraken,
    "kraken_ledger": _parse_kraken,
}


def _read_csv(path: Path) -> Tuple[List[str], List[Dict[str, str]]]:
    """Read CSV, auto-detect delimiter."""
    text = path.read_text(encoding="utf-8", errors="replace")
    # Skip BOM
    if text.startswith("\ufeff"):
        text = text[1:]
    # Detect delimiter
    sample = text[:4096]
    sniffer = csv.Sniffer()
    try:
        dialect = sniffer.sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    headers = reader.fieldnames or []
    rows = list(reader)
    return headers, rows


def _read_json(path: Path) -> Tuple[str, List[Dict[str, str]]]:
    """Read JSON array of transactions."""
    data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    if isinstance(data, list):
        return "generic", data
    if isinstance(data, dict):
        # Some exports wrap in {"data": [...]} or {"transactions": [...]}
        for key in ("data", "transactions", "records", "trades", "history"):
            if key in data and isinstance(data[key], list):
                return "generic", data[key]
        return "generic", [data]
    return "generic", []


def parse_crypto_file(path: Path) -> ParsedCryptoData:
    """Parse a crypto transaction file (CSV or JSON). Auto-detects format."""
    result = ParsedCryptoData()
    path = Path(path)
    ext = path.suffix.lower()

    try:
        if ext == ".json":
            fmt, rows = _read_json(path)
            result.source = fmt
        elif ext in (".csv", ".tsv", ".txt"):
            headers, rows = _read_csv(path)
            fmt = detect_format(headers)
            result.source = fmt
        else:
            result.errors.append(f"Nieobsługiwany format pliku: {ext}")
            return result

        result.raw_row_count = len(rows)

        if not rows:
            result.errors.append("Plik nie zawiera danych.")
            return result

        # Pick parser
        parser_fn = _PARSER_MAP.get(fmt, _parse_generic)
        txs = parser_fn(rows)
        result.transactions = txs

        # Build wallet info from transactions
        result.wallets = _build_wallets(txs)

        # Detect chain from transactions
        chains = {tx.chain for tx in txs if tx.chain and tx.chain != "unknown"}
        if len(chains) == 1:
            result.chain = chains.pop()
        elif chains:
            result.chain = ",".join(sorted(chains))

        log.info(f"Parsed {len(txs)} transactions from {fmt} ({path.name})")

    except Exception as e:
        log.error(f"Error parsing {path}: {e}")
        result.errors.append(f"Błąd parsowania: {e}")

    return result


def _build_wallets(txs: List[CryptoTransaction]) -> List[WalletInfo]:
    """Aggregate wallet info from transactions."""
    wallets: Dict[str, WalletInfo] = {}

    for tx in txs:
        for addr, direction in [(tx.from_address, "sent"), (tx.to_address, "received")]:
            if not addr:
                continue
            if addr not in wallets:
                wallets[addr] = WalletInfo(address=addr, chain=tx.chain)
            w = wallets[addr]
            w.tx_count += 1
            if direction == "sent":
                w.total_sent += tx.amount
            else:
                w.total_received += tx.amount
            # Track token balances
            if tx.token:
                w.tokens[tx.token] = w.tokens.get(tx.token, Decimal("0"))
            # Update time range
            if tx.timestamp:
                if not w.first_seen or tx.timestamp < w.first_seen:
                    w.first_seen = tx.timestamp
                if not w.last_seen or tx.timestamp > w.last_seen:
                    w.last_seen = tx.timestamp

    return list(wallets.values())
