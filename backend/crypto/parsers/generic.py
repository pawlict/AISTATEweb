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

from .base import CryptoTransaction, ParsedCryptoData, WalletInfo, classify_source_type

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
    "walletexplorer": ["date", "received from", "received amount", "sent amount", "sent to", "balance", "transaction"],
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

def _parse_walletexplorer(rows: List[Dict[str, str]], wallet_id: str = "") -> List[CryptoTransaction]:
    """Parse WalletExplorer.com CSV export.

    Columns: date, received from, received amount, sent amount, sent to, balance, transaction
    Each row is either a receive (received from + received amount) or a send (sent to + sent amount).
    """
    txs = []
    for row in rows:
        ts = row.get("date") or ""
        recv_from = (row.get("received from") or "").strip()
        recv_amount = _dec(row.get("received amount") or "0")
        sent_amount = _dec(row.get("sent amount") or "0")
        sent_to = (row.get("sent to") or "").strip()
        balance = _dec(row.get("balance") or "0")
        tx_hash = (row.get("transaction") or "").strip()

        if recv_from and recv_amount > 0:
            # Incoming transaction
            # Check if sender is a known tagged wallet (e.g. "CoinJoinMess (xxx)")
            counterparty = recv_from
            risk_tags: List[str] = []
            if "coinjoin" in recv_from.lower():
                risk_tags.append("coinjoin")
                risk_tags.append("mixer")

            txs.append(CryptoTransaction(
                tx_hash=tx_hash,
                timestamp=_ts(ts),
                from_address=recv_from,
                to_address=wallet_id,
                amount=recv_amount,
                token="BTC",
                chain="bitcoin",
                tx_type="deposit",
                counterparty=counterparty,
                risk_tags=risk_tags,
                raw=dict(row),
            ))

        if sent_to and sent_amount > 0:
            # Outgoing transaction
            counterparty = sent_to
            risk_tags_out: List[str] = []
            if "coinjoin" in sent_to.lower():
                risk_tags_out.append("coinjoin")
                risk_tags_out.append("mixer")

            txs.append(CryptoTransaction(
                tx_hash=tx_hash,
                timestamp=_ts(ts),
                from_address=wallet_id,
                to_address=sent_to,
                amount=sent_amount,
                token="BTC",
                chain="bitcoin",
                tx_type="withdrawal",
                counterparty=counterparty,
                risk_tags=risk_tags_out,
                raw=dict(row),
            ))

    return txs


_PARSER_MAP = {
    "binance": _parse_binance,
    "binance_trade": _parse_binance,
    "etherscan": _parse_etherscan,
    "etherscan_token": _parse_etherscan,
    "etherscan_internal": _parse_etherscan,
    "kraken": _parse_kraken,
    "kraken_ledger": _parse_kraken,
    "walletexplorer": None,  # handled specially (needs wallet_id from header)
}


# ---------------------------------------------------------------------------
# PDF parsing for crypto exchanges
# ---------------------------------------------------------------------------

def _extract_pdf_lines(path: Path) -> List[str]:
    """Extract text lines from a PDF using PyMuPDF."""
    try:
        import fitz  # PyMuPDF
    except ImportError:
        log.warning("PyMuPDF (fitz) not installed; cannot parse PDF files")
        return []

    lines: List[str] = []
    doc = fitz.open(str(path))
    for page in doc:
        text = page.get_text("text")
        for line in text.split("\n"):
            stripped = line.strip()
            if stripped:
                lines.append(stripped)
    doc.close()
    return lines


def _detect_crypto_pdf_format(lines: List[str]) -> str:
    """Detect crypto exchange from PDF text lines."""
    head = "\n".join(lines[:50]).lower()
    if "binance" in head:
        return "binance_pdf"
    if "revolut" in head and (
        "digital assets" in head
        or "kryptowalut" in head
        or "crypto account" in head
        or "crypto statement" in head
        or "wyciąg z konta" in head
        or "wyciag z konta" in head
    ):
        return "revolut_crypto"
    return ""


def _parse_binance_pdf(lines: List[str]) -> Tuple[List[CryptoTransaction], Dict[str, str]]:
    """Parse Binance 'Historia transakcji' PDF format.

    Each transaction is a block of lines:
      user_id (e.g. 849227679)
      YY-MM-DD HH:MM:SS  (timestamp)
      Account (Spot/Funding)
      Operation (Deposit, Withdraw, Buy Crypto With Fiat, etc.)
      Coin (PLN, BTC, ETH, ...)
      Change (numeric, positive or negative)
      [Notes] (optional, e.g. 'Withdraw fee is included')

    Page headers repeat: www.binance.com, Page X/Y, column header lines.
    """
    txs: List[CryptoTransaction] = []
    meta: Dict[str, str] = {}
    n = len(lines)

    # Extract metadata from header
    for i in range(min(n, 15)):
        l = lines[i]
        if l.startswith("Nazwa:"):
            meta["holder_name"] = l[len("Nazwa:"):].strip()
        elif l.startswith("Adres:"):
            meta["address"] = l[len("Adres:"):].strip()
        elif l.startswith("ID u"):
            m = re.match(r"ID\s+u.ytkownika:\s*(\d+)", l)
            if m:
                meta["user_id"] = m.group(1)
        elif l.startswith("Okres"):
            m = re.search(r"(\d{4}-\d{2}-\d{2})\s+to\s+(\d{4}-\d{2}-\d{2})", l)
            if m:
                meta["period_from"] = m.group(1)
                meta["period_to"] = m.group(2)
        elif l.startswith("E-mail:"):
            meta["email"] = l[len("E-mail:"):].strip()

    # Detect user_id for transaction block detection
    user_id = meta.get("user_id", "")
    if not user_id:
        # Try to find it from first numeric-only line
        for l in lines[:20]:
            if re.match(r"^\d{6,}$", l):
                user_id = l
                break

    if not user_id:
        return [], meta

    # Page header/footer lines to skip
    _skip_patterns = {
        "www.binance.com", "Identyfikator", "ownika", "Czas",
        "Konto", "Operacja", "Moneta", "Zmie","Uwagi",
    }

    i = 0
    while i < n:
        l = lines[i]

        # Skip page headers
        if l.startswith("Page ") or l.startswith("www.binance") or l in _skip_patterns:
            i += 1
            continue

        # Transaction block starts with user_id
        if l != user_id:
            i += 1
            continue

        i += 1
        if i >= n:
            break

        # Timestamp: YY-MM-DD HH:MM:SS
        ts_line = lines[i] if i < n else ""
        ts_match = re.match(r"(\d{2}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})", ts_line)
        if not ts_match:
            continue
        ts_raw = ts_match.group(1)
        # Convert YY-MM-DD to 20YY-MM-DD
        ts_iso = f"20{ts_raw[:2]}-{ts_raw[3:5]}-{ts_raw[6:8]}T{ts_raw[9:]}"
        i += 1

        # Account (Spot, Funding)
        account = lines[i].strip() if i < n else ""
        i += 1

        # Operation
        operation = lines[i].strip() if i < n else ""
        i += 1

        # Coin
        coin = lines[i].strip() if i < n else ""
        i += 1

        # Change (amount)
        change_str = lines[i].strip() if i < n else "0"
        i += 1

        # Optional notes line (not a user_id, not a page header, not a timestamp)
        notes = ""
        if i < n:
            next_l = lines[i].strip()
            if (next_l != user_id
                    and not next_l.startswith("Page ")
                    and not next_l.startswith("www.")
                    and next_l not in _skip_patterns
                    and not re.match(r"\d{2}-\d{2}-\d{2}\s", next_l)):
                notes = next_l
                i += 1

        # Parse amount
        amount = _dec(change_str)

        # Determine tx_type
        op_lower = operation.lower()
        tx_type = "transfer"
        if "deposit" in op_lower:
            tx_type = "deposit"
        elif "withdraw" in op_lower:
            tx_type = "withdrawal"
        elif "buy" in op_lower or "sell" in op_lower:
            tx_type = "swap"
        elif "convert" in op_lower:
            tx_type = "swap"
        elif "crypto box" in op_lower:
            tx_type = "transfer"
        elif "transfer between" in op_lower:
            tx_type = "transfer"

        raw = {
            "user_id": user_id,
            "utc_time": ts_raw,
            "account": account,
            "operation": operation,
            "coin": coin,
            "change": change_str,
            "notes": notes,
        }

        txs.append(CryptoTransaction(
            timestamp=ts_iso,
            amount=abs(amount),
            token=coin.upper(),
            chain="binance",
            tx_type=tx_type,
            exchange="binance",
            category=operation,
            raw=raw,
        ))

    return txs, meta


def _read_csv(path: Path) -> Tuple[List[str], List[Dict[str, str]], str]:
    """Read CSV, auto-detect delimiter. Returns (headers, rows, metadata_line)."""
    text = path.read_text(encoding="utf-8", errors="replace")
    # Skip BOM
    if text.startswith("\ufeff"):
        text = text[1:]

    # WalletExplorer and similar tools put a comment/metadata line before the header.
    # Detect and strip it: lines starting with # or " that don't look like CSV headers.
    metadata = ""
    lines = text.split("\n", 2)
    if lines and lines[0].strip().startswith(("#", '"#')):
        metadata = lines[0].strip().strip('"').strip("#").strip()
        # Rejoin without the first line
        text = "\n".join(lines[1:]) if len(lines) > 1 else ""

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
    return headers, rows, metadata


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
    """Parse a crypto transaction file (CSV, JSON, PDF, or XLSX). Auto-detects format."""
    result = ParsedCryptoData()
    path = Path(path)
    ext = path.suffix.lower()
    metadata = ""

    try:
        # --- XLSX path (Binance full account export) ---
        if ext in (".xlsx", ".xls"):
            from .binance_xlsx import is_binance_xlsx, parse_binance_xlsx
            if is_binance_xlsx(path):
                return parse_binance_xlsx(path)
            else:
                result.errors.append("Nierozpoznany format XLSX giełdy kryptowalutowej.")
                return result

        # --- PDF path (crypto exchange statements) ---
        if ext == ".pdf":
            lines = _extract_pdf_lines(path)
            if not lines:
                result.errors.append("Nie udało się wyodrębnić tekstu z pliku PDF.")
                return result
            pdf_fmt = _detect_crypto_pdf_format(lines)
            if pdf_fmt == "binance_pdf":
                txs, pdf_meta = _parse_binance_pdf(lines)
                result.source = "binance_pdf"
                result.source_type = classify_source_type("binance_pdf", txs)
                result.raw_row_count = len(txs)
                result.transactions = txs
                result.chain = "binance"
                result.wallets = _build_wallets(txs)
                log.info(f"Parsed {len(txs)} transactions from binance_pdf ({path.name})")
                return result
            elif pdf_fmt == "revolut_crypto":
                from .revolut_crypto_pdf import parse_revolut_crypto_pdf
                return parse_revolut_crypto_pdf(path)
            else:
                # Fallback: try dedicated Revolut detector (scans more broadly)
                try:
                    from .revolut_crypto_pdf import is_revolut_crypto_pdf, parse_revolut_crypto_pdf
                    if is_revolut_crypto_pdf(lines):
                        log.info("Revolut crypto PDF detected via fallback (is_revolut_crypto_pdf)")
                        return parse_revolut_crypto_pdf(path)
                except Exception as e:
                    log.warning("Revolut fallback detection failed: %s", e)
                log.warning("Unrecognized crypto PDF. First 10 lines: %s", lines[:10])
                result.errors.append("Nierozpoznany format PDF giełdy kryptowalutowej.")
                return result

        # --- JSON path ---
        if ext == ".json":
            fmt, rows = _read_json(path)
            result.source = fmt
        elif ext in (".csv", ".tsv", ".txt"):
            headers, rows, metadata = _read_csv(path)
            fmt = detect_format(headers)
            result.source = fmt
        else:
            result.errors.append(f"Nieobsługiwany format pliku: {ext}")
            return result

        result.raw_row_count = len(rows)

        if not rows:
            result.errors.append("Plik nie zawiera danych.")
            return result

        # WalletExplorer: extract wallet ID from metadata line
        if fmt == "walletexplorer":
            wallet_id = ""
            if metadata:
                # "Wallet 0006d08ed79d30f3. Updated to block ..."
                m = re.search(r"Wallet\s+([a-f0-9]+)", metadata)
                if m:
                    wallet_id = m.group(1)
            txs = _parse_walletexplorer(rows, wallet_id=wallet_id)
            result.source = "walletexplorer"
            result.chain = "bitcoin"
        else:
            # Pick parser
            parser_fn = _PARSER_MAP.get(fmt, _parse_generic)
            if parser_fn is None:
                parser_fn = _parse_generic
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

    # Classify source type (exchange vs blockchain)
    if not result.source_type:
        result.source_type = classify_source_type(result.source, result.transactions)

    return result


def _build_wallets(txs: List[CryptoTransaction]) -> List[WalletInfo]:
    """Aggregate wallet info from transactions."""
    wallets: Dict[str, WalletInfo] = {}

    for tx in txs:
        for addr_raw, direction in [(tx.from_address, "sent"), (tx.to_address, "received")]:
            if not addr_raw:
                continue
            addr = addr_raw.strip()
            # Normalize key: lowercase for EVM addresses to avoid duplicates
            key = addr.lower() if addr.startswith("0x") or addr.startswith("0X") else addr
            if key not in wallets:
                wallets[key] = WalletInfo(address=addr, chain=tx.chain)
            w = wallets[key]
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
