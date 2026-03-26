"""Binance XLSX (full account statement) parser.

Parses the multi-sheet Excel export that Binance provides via law-enforcement
or user-requested data exports.  Sheets handled:

  - Customer Information  → account metadata (user ID, name, email)
  - Account Balance       → current balances per coin
  - Current Assets & Wallets → deposit wallet addresses per asset
  - Order History         → spot market orders (BUY/SELL)
  - Deposit History       → crypto deposits (with CounterParty ID for internal)
  - Fiat Deposit History  → fiat on-ramp
  - Withdrawal History    → crypto withdrawals (with CounterParty ID)
  - Fiat Withdrawal History → fiat off-ramp
  - Binance Pay           → C2C transfers, crypto boxes
  - Card Transaction      → Binance card spending
  - OTC Trading           → OTC convert trades
  - Margin Order          → margin trading orders
  - P2P                   → peer-to-peer marketplace
  - Access Logs           → login/device audit trail
  - Approved Devices      → device whitelist
"""
from __future__ import annotations

import logging
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .base import CryptoTransaction, ParsedCryptoData, WalletInfo, classify_source_type

log = logging.getLogger("aistate.crypto.parser.binance_xlsx")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FIAT_CURRENCIES = {
    "PLN", "USD", "EUR", "GBP", "CHF", "CZK", "TRY", "BRL", "AUD",
    "CAD", "JPY", "KRW", "RUB", "UAH", "INR", "NGN", "ARS", "ZAR",
}


def _dec(val: Any) -> Decimal:
    if val is None:
        return Decimal("0")
    s = str(val).strip().replace(",", ".").replace(" ", "")
    s = re.sub(r"[A-Za-z$€£¥₿]+$", "", s).strip()
    s = re.sub(r"^[A-Za-z$€£¥₿]+", "", s).strip()
    if not s or s in ("-", "nan", "NaN", "None"):
        return Decimal("0")
    try:
        return Decimal(s)
    except InvalidOperation:
        return Decimal("0")


def _ts(val: Any) -> str:
    if not val:
        return ""
    s = str(val).strip()
    # Strip trailing '(UTC)' from some columns
    s = re.sub(r"\s*\(UTC\)\s*$", "", s)
    for fmt in [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%SZ",
        "%d/%m/%Y %H:%M:%S",
    ]:
        try:
            dt = datetime.strptime(s, fmt)
            return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            continue
    return s


def _safe_str(val: Any) -> str:
    if val is None:
        return ""
    s = str(val).strip()
    if s in ("nan", "NaN", "None", ""):
        return ""
    return s


def _is_internal(counterparty_id: str) -> bool:
    """Check if a transaction is Binance-internal (has a numeric CounterParty ID)."""
    return bool(counterparty_id) and counterparty_id not in ("", "nan", "NaN", "None")


def _dedup_addr(raw: str) -> str:
    """Deduplicate comma-separated address field.

    Binance exports sometimes repeat the same address many times in a single
    cell (e.g. "addr1,addr1,addr1,...").  This extracts unique addresses and
    returns them joined by comma.  If there's only one unique address, returns
    it without commas.
    """
    if not raw or "," not in raw:
        return raw
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    seen = []
    seen_set = set()
    for p in parts:
        key = p.lower()
        if key not in seen_set:
            seen_set.add(key)
            seen.append(p)
    return ", ".join(seen) if len(seen) > 1 else (seen[0] if seen else raw)


# ---------------------------------------------------------------------------
# Sheet parsers
# ---------------------------------------------------------------------------

def _parse_customer_info(df) -> Dict[str, Any]:
    """Extract account metadata from Customer Information sheet.

    The Binance Customer Information sheet has a key-value layout where
    some rows contain labels and the next row (or adjacent column) has the
    corresponding values.  We scan for known label strings and capture
    everything available.
    """
    meta: Dict[str, Any] = {}

    # ---- 1. Header string often contains "User Basic Information(id: XXXXX ...)"
    first_col = str(df.columns[0]) if len(df.columns) > 0 else ""
    m = re.search(r"id:\s*(\d+)", first_col)
    if m:
        meta["user_id"] = m.group(1)
    m = re.search(r"email:\s*(\S+)", first_col)
    if m:
        meta["email"] = m.group(1)

    # ---- 2. Build a flat list of all cell values for label-based scanning
    all_rows = []
    for _, row in df.iterrows():
        all_rows.append([_safe_str(v) for v in row.values])

    # Also treat column names as a row (some sheets put labels in the header)
    col_row = [_safe_str(c) for c in df.columns]
    all_rows.insert(0, col_row)

    # Known label → meta key mapping (case-insensitive matching)
    _LABEL_MAP = {
        "user id": "user_id",
        "userid": "user_id",
        "uid": "user_id",
        "email": "email",
        "e-mail": "email",
        "phone": "phone",
        "phone number": "phone",
        "mobile": "phone",
        "mobile number": "phone",
        "contact number": "phone",
        "name": "holder_name",
        "full name": "holder_name",
        "real name": "holder_name",
        "account name": "holder_name",
        "first name": "first_name",
        "last name": "last_name",
        "country": "country",
        "country/region": "country",
        "residence country": "country",
        "nationality": "nationality",
        "kyc level": "kyc_level",
        "kyc": "kyc_level",
        "verification level": "kyc_level",
        "identity verification": "kyc_level",
        "vip level": "vip_level",
        "vip": "vip_level",
        "registration date": "registration_date",
        "register time": "registration_date",
        "register date": "registration_date",
        "created at": "registration_date",
        "account create time": "registration_date",
        "account status": "account_status",
        "status": "account_status",
        "id type": "id_type",
        "document type": "id_type",
        "identity type": "id_type",
        "id number": "id_number",
        "document number": "id_number",
        "identity number": "id_number",
        "address": "physical_address",
        "residential address": "physical_address",
        "city": "city",
        "state": "state",
        "province": "state",
        "zip code": "zip_code",
        "postal code": "zip_code",
        "date of birth": "date_of_birth",
        "birthday": "date_of_birth",
        "dob": "date_of_birth",
        "gender": "gender",
        "referral id": "referral_id",
        "referrer id": "referral_id",
        "agent id": "agent_id",
        "sub-account": "sub_account",
        "sub account": "sub_account",
        "margin enabled": "margin_enabled",
        "futures enabled": "futures_enabled",
        "api trading enabled": "api_trading",
        "anti-phishing code": "anti_phishing_code",
    }

    # Build set of all known labels for collision detection
    _ALL_LABELS = set(_LABEL_MAP.keys())

    # ---- 3. Scan rows: look for label-value pairs
    # The sheet typically has a header row with labels (User ID, Email, Mobile, ...)
    # and the next row has the corresponding values (12345, adam@..., +48...).
    # Strategy: first try value BELOW (same column, next row).
    #           Only use value to the RIGHT if it's NOT another known label.
    for ri, vals in enumerate(all_rows):
        for ci, cell in enumerate(vals):
            cell_lower = cell.lower().strip().rstrip(":")
            if cell_lower not in _LABEL_MAP:
                continue
            key = _LABEL_MAP[cell_lower]

            # Strategy A: value below (next row, same column) — preferred
            val_below = ""
            if ri + 1 < len(all_rows) and ci < len(all_rows[ri + 1]):
                val_below = all_rows[ri + 1][ci]

            # Strategy B: value to the right (same row, next column)
            val_right = ""
            if ci + 1 < len(vals):
                candidate = vals[ci + 1]
                # Only use if it's NOT another label name
                if candidate and candidate.lower().strip().rstrip(":") not in _ALL_LABELS:
                    val_right = candidate

            # Prefer below (header→data row pattern), fallback to right
            if val_below:
                meta.setdefault(key, val_below)
            elif val_right:
                meta.setdefault(key, val_right)

    # ---- 4. Fallback: row with numeric user ID (original heuristic)
    for vals in all_rows:
        if vals[0] and re.match(r"^\d{6,}$", vals[0]):
            meta.setdefault("user_id", vals[0])
            if len(vals) > 1 and "@" in str(vals[1]):
                meta.setdefault("email", vals[1])
            if len(vals) > 4 and vals[4]:
                meta.setdefault("holder_name", vals[4])

    # ---- 5. Compose full name from first + last if holder_name missing
    if not meta.get("holder_name") and (meta.get("first_name") or meta.get("last_name")):
        parts = [meta.get("first_name", ""), meta.get("last_name", "")]
        meta["holder_name"] = " ".join(p for p in parts if p)

    return meta


def _parse_deposit_history(df) -> List[CryptoTransaction]:
    """Parse Deposit History sheet."""
    txs = []
    for _, row in df.iterrows():
        currency = _safe_str(row.get("Currency", ""))
        if not currency:
            continue
        amount = _dec(row.get("Amount"))
        ts = _ts(row.get("Create Time"))
        dep_addr = _dedup_addr(_safe_str(row.get("Deposit Address", "")))
        src_addr = _dedup_addr(_safe_str(row.get("Source Address", "")))
        txid = _safe_str(row.get("TXID", ""))
        network = _safe_str(row.get("Network", ""))
        cp_id = _safe_str(row.get("CounterParty ID", "") or row.get("CounterPartyID", ""))
        status_raw = _safe_str(row.get("Status", ""))
        busd_val = _dec(row.get("BUSD"))

        is_int = _is_internal(cp_id)

        risk_tags = []
        if is_int:
            risk_tags.append("binance_internal")

        txs.append(CryptoTransaction(
            tx_hash=txid,
            timestamp=ts,
            from_address=src_addr.lower() if src_addr else "",
            to_address=dep_addr.lower() if dep_addr else "",
            amount=abs(amount),
            token=currency.upper(),
            chain=network.lower() if network else "binance",
            tx_type="deposit",
            status="confirmed" if "成功" in status_raw or "success" in status_raw.lower() else status_raw,
            exchange="binance",
            counterparty=f"binance_user:{cp_id}" if is_int else "",
            risk_tags=risk_tags,
            raw={
                "sheet": "Deposit History",
                "counterparty_id": cp_id,
                "network": network,
                "busd_value": str(busd_val),
                "is_internal": is_int,
            },
        ))
    return txs


def _parse_withdrawal_history(df) -> List[CryptoTransaction]:
    """Parse Withdrawal History sheet."""
    txs = []
    for _, row in df.iterrows():
        currency = _safe_str(row.get("Currency", ""))
        if not currency:
            continue
        amount = _dec(row.get("Amount"))
        ts = _ts(row.get("Apply Time"))
        # Note: column name has trailing space in real exports
        dest_addr = _dedup_addr(_safe_str(row.get("Destination Address ", "") or row.get("Destination Address", "")))
        txid = _safe_str(row.get("txId", "") or row.get("TXID", ""))
        network = _safe_str(row.get("Network", ""))
        cp_id = _safe_str(row.get("CounterParty ID", "") or row.get("CounterPartyID", ""))
        status_raw = _safe_str(row.get("Status", ""))
        busd_val = _dec(row.get("BUSD"))

        is_int = _is_internal(cp_id)

        risk_tags = []
        if is_int:
            risk_tags.append("binance_internal")

        txs.append(CryptoTransaction(
            tx_hash=txid,
            timestamp=ts,
            from_address="",
            to_address=dest_addr.lower() if dest_addr else "",
            amount=abs(amount),
            token=currency.upper(),
            chain=network.lower() if network else "binance",
            tx_type="withdrawal",
            status="confirmed" if "success" in status_raw.lower() else status_raw,
            exchange="binance",
            counterparty=f"binance_user:{cp_id}" if is_int else "",
            risk_tags=risk_tags,
            raw={
                "sheet": "Withdrawal History",
                "counterparty_id": cp_id,
                "network": network,
                "busd_value": str(busd_val),
                "is_internal": is_int,
            },
        ))
    return txs


def _parse_order_history(df, sheet_name: str = "Order History") -> List[CryptoTransaction]:
    """Parse Order History or Margin Order sheet (spot/margin trades)."""
    txs = []
    for _, row in df.iterrows():
        market = _safe_str(row.get("Market ID", ""))
        if not market:
            continue
        side = _safe_str(row.get("Side", "")).upper()
        status_raw = _safe_str(row.get("Status", "")).upper()
        if status_raw == "CANCELED":
            continue  # skip cancelled orders

        price = _dec(row.get("Average Price") or row.get("Price"))
        qty = _dec(row.get("Trade Qty") or row.get("Qty"))
        ts = _ts(row.get("Time"))
        order_type = _safe_str(row.get("Type", ""))
        price_unit = _safe_str(row.get("Price Unit", ""))
        amount_unit = _safe_str(row.get("Amount Unit", ""))

        # Derive base/quote from market ID or units
        base_token = amount_unit.upper() if amount_unit else ""
        quote_token = price_unit.upper() if price_unit else ""

        if not base_token and market:
            # Try to split market ID (e.g. ETHUSDT → ETH + USDT)
            for suffix in ["USDT", "USDC", "BUSD", "BTC", "ETH", "BNB"]:
                if market.endswith(suffix):
                    base_token = market[:-len(suffix)]
                    quote_token = suffix
                    break

        total_value = price * qty if price > 0 and qty > 0 else Decimal("0")

        txs.append(CryptoTransaction(
            timestamp=ts,
            amount=abs(qty),
            token=base_token,
            chain="binance",
            tx_type="swap",
            status="confirmed" if status_raw == "FILLED" else status_raw.lower(),
            exchange="binance",
            category=f"{side} {market}",
            raw={
                "sheet": sheet_name,
                "market": market,
                "side": side,
                "price": str(price),
                "qty": str(qty),
                "total_value": str(total_value),
                "quote_token": quote_token,
                "order_type": order_type,
            },
        ))
    return txs


def _parse_binance_pay(df) -> List[CryptoTransaction]:
    """Parse Binance Pay sheet (C2C transfers, crypto boxes)."""
    txs = []
    for _, row in df.iterrows():
        currency = _safe_str(row.get("Currency", ""))
        if not currency:
            continue
        amount = _dec(row.get("Amount"))
        ts = _ts(row.get("Transaction Time"))
        tx_type_raw = _safe_str(row.get("Transaction Type", ""))
        cp_binance_id = _safe_str(row.get("Counterparty Binance ID", ""))
        cp_wallet_id = _safe_str(row.get("Counterparty Wallet ID", ""))
        order_id = _safe_str(row.get("Order ID", ""))
        tx_id = _safe_str(row.get("Transaction ID", ""))

        # Negative amounts = outgoing transfer
        is_outgoing = amount < 0
        tx_type = "withdrawal" if is_outgoing else "deposit"
        if "CRYPTO_BOX" in tx_type_raw.upper():
            tx_type = "transfer"

        txs.append(CryptoTransaction(
            tx_hash=tx_id or order_id,
            timestamp=ts,
            amount=abs(amount),
            token=currency.upper(),
            chain="binance",
            tx_type=tx_type,
            exchange="binance",
            counterparty=f"binance_user:{cp_binance_id}" if cp_binance_id else "",
            risk_tags=["binance_internal", "binance_pay"],
            raw={
                "sheet": "Binance Pay",
                "transaction_type": tx_type_raw,
                "counterparty_binance_id": cp_binance_id,
                "counterparty_wallet_id": cp_wallet_id,
                "direction": "OUT" if is_outgoing else "IN",
            },
        ))
    return txs


def _parse_card_transactions(df) -> List[CryptoTransaction]:
    """Parse Card Transaction sheet (Binance card spending)."""
    txs = []
    for _, row in df.iterrows():
        merchant = _safe_str(row.get("Merchant Name", ""))
        if not merchant:
            continue
        currency = _safe_str(row.get("Currency", ""))
        total = _dec(row.get("Total") or row.get("Approved"))
        ts = _ts(row.get("Created date"))
        status_raw = _safe_str(row.get("Status", ""))
        tx_type_raw = _safe_str(row.get("Type", ""))

        txs.append(CryptoTransaction(
            timestamp=ts,
            amount=abs(total),
            token=currency.upper() if currency else "EUR",
            chain="binance",
            tx_type="payment",
            status="confirmed" if status_raw.lower() in ("settled", "completed") else status_raw.lower(),
            exchange="binance",
            counterparty=merchant,
            category=f"card_{tx_type_raw}",
            raw={
                "sheet": "Card Transaction",
                "merchant": merchant,
                "status": status_raw,
                "type": tx_type_raw,
            },
        ))
    return txs


def _parse_otc(df) -> List[CryptoTransaction]:
    """Parse OTC Trading sheet."""
    txs = []
    for _, row in df.iterrows():
        base_coin = _safe_str(row.get("BaseCoin", ""))
        quote_coin = _safe_str(row.get("QuoteCoin", ""))
        if not base_coin:
            continue
        base_amount = _dec(row.get("BaseCoinAmount"))
        quote_amount = _dec(row.get("QuoteCoinAmount"))
        ts = _ts(row.get("CreateTime"))
        pay_type = _safe_str(row.get("PayType", ""))
        status_raw = _safe_str(row.get("UserStatus", ""))

        txs.append(CryptoTransaction(
            timestamp=ts,
            amount=abs(base_amount),
            token=base_coin.upper(),
            chain="binance",
            tx_type="swap",
            status="confirmed" if "success" in status_raw.lower() else status_raw.lower(),
            exchange="binance",
            category=f"OTC {pay_type} {base_coin}/{quote_coin}",
            raw={
                "sheet": "OTC Trading",
                "base_coin": base_coin,
                "quote_coin": quote_coin,
                "base_amount": str(base_amount),
                "quote_amount": str(quote_amount),
                "pay_type": pay_type,
            },
        ))
    return txs


def _parse_fiat_deposit(df) -> List[CryptoTransaction]:
    """Parse Fiat Deposit History sheet."""
    txs = []
    for _, row in df.iterrows():
        amount = _dec(row.get("Amount"))
        if amount == 0:
            continue
        currency = _safe_str(row.get("Currency", ""))
        ts = _ts(row.get("Create Time") or row.get("Completed Time"))
        status_raw = _safe_str(row.get("Status", ""))
        method = _safe_str(row.get("Payment Method", ""))

        txs.append(CryptoTransaction(
            timestamp=ts,
            amount=abs(amount),
            token=currency.upper(),
            chain="fiat",
            tx_type="fiat_deposit",
            status="confirmed" if "success" in status_raw.lower() or "completed" in status_raw.lower() else status_raw.lower(),
            exchange="binance",
            category=f"fiat_deposit_{method}" if method else "fiat_deposit",
            raw={
                "sheet": "Fiat Deposit History",
                "currency": currency,
                "method": method,
                "status": status_raw,
            },
        ))
    return txs


def _parse_fiat_withdrawal(df) -> List[CryptoTransaction]:
    """Parse Fiat Withdrawal History sheet."""
    txs = []
    for _, row in df.iterrows():
        amount = _dec(row.get("Amount"))
        if amount == 0:
            continue
        currency = _safe_str(row.get("Currency", ""))
        ts = _ts(row.get("Create Time") or row.get("Completed Time"))
        status_raw = _safe_str(row.get("Status", ""))
        method = _safe_str(row.get("Payment Method", ""))
        target_name = _safe_str(row.get("Target Name", ""))

        txs.append(CryptoTransaction(
            timestamp=ts,
            amount=abs(amount),
            token=currency.upper(),
            chain="fiat",
            tx_type="fiat_withdrawal",
            status="confirmed" if "success" in status_raw.lower() or "completed" in status_raw.lower() else status_raw.lower(),
            exchange="binance",
            counterparty=target_name,
            category=f"fiat_withdrawal_{method}" if method else "fiat_withdrawal",
            raw={
                "sheet": "Fiat Withdrawal History",
                "currency": currency,
                "method": method,
                "target_name": target_name,
                "status": status_raw,
            },
        ))
    return txs


def _parse_p2p(df) -> List[CryptoTransaction]:
    """Parse P2P sheet."""
    txs = []
    for _, row in df.iterrows():
        crypto = _safe_str(row.get("Crypto", ""))
        if not crypto:
            continue
        amount = _dec(row.get("Amount"))
        fiat_amount = _dec(row.get("Total Amount"))
        fiat_currency = _safe_str(row.get("Fiat Currency", ""))
        side = _safe_str(row.get("Buy or Sell", "")).upper()
        ts = _ts(row.get("Create Time"))
        status_raw = _safe_str(row.get("Status", ""))
        ad_publisher = _safe_str(row.get("Ad publisher ID", ""))
        take_id = _safe_str(row.get("Take ID", ""))

        txs.append(CryptoTransaction(
            timestamp=ts,
            amount=abs(amount),
            token=crypto.upper(),
            chain="binance",
            tx_type="swap",
            status="confirmed" if "completed" in status_raw.lower() else status_raw.lower(),
            exchange="binance",
            counterparty=f"binance_user:{ad_publisher}" if ad_publisher else "",
            category=f"P2P {side} {crypto}/{fiat_currency}",
            risk_tags=["p2p"],
            raw={
                "sheet": "P2P",
                "side": side,
                "fiat_amount": str(fiat_amount),
                "fiat_currency": fiat_currency,
                "ad_publisher": ad_publisher,
                "take_id": take_id,
            },
        ))
    return txs


def _parse_wallet_addresses(df) -> List[WalletInfo]:
    """Parse Current Assets & Wallets → extract deposit addresses."""
    wallets: Dict[str, WalletInfo] = {}
    for _, row in df.iterrows():
        ticker = _safe_str(row.get("Asset Ticker", ""))
        addr_str = _safe_str(row.get("Deposit Wallet Address", ""))
        if not addr_str:
            continue

        # Multiple addresses comma-separated
        for addr in addr_str.split(","):
            addr = addr.strip()
            if not addr:
                continue

            chain = "unknown"
            al = addr.lower()
            if al.startswith("0x"):
                chain = "ethereum"
            elif al.startswith("bnb1"):
                chain = "bsc"
            elif al.startswith("t") and len(addr) == 34:
                chain = "tron"
            elif al.startswith("ckb1"):
                chain = "nervos"
            elif len(addr) >= 26 and len(addr) <= 35 and addr[0] in "13bc":
                chain = "bitcoin"
            elif len(addr) >= 32 and len(addr) <= 44 and not al.startswith("0x"):
                chain = "solana"

            key = addr.lower()
            if key not in wallets:
                wallets[key] = WalletInfo(
                    address=addr,
                    chain=chain,
                    label=f"binance_deposit_{ticker}",
                    risk_level="low",
                )
            w = wallets[key]
            if ticker:
                w.tokens[ticker] = w.tokens.get(ticker, Decimal("0"))

    return list(wallets.values())


def _parse_account_balance(df) -> Dict[str, Dict[str, Any]]:
    """Parse Account Balance sheet → current holdings."""
    balances: Dict[str, Dict[str, Any]] = {}
    # The sheet has a non-standard header (first few rows are descriptive).
    # Look for rows with recognizable coin data.
    for _, row in df.iterrows():
        vals = [_safe_str(v) for v in row.values]
        # Skip header rows, look for rows where column 1 is a currency code
        if len(vals) < 3:
            continue
        code = vals[1] if len(vals) > 1 else ""
        if not code or len(code) > 10 or " " in code:
            continue
        all_pos = _dec(vals[2]) if len(vals) > 2 else Decimal("0")
        if all_pos == 0:
            continue
        btc_eq = _dec(vals[6]) if len(vals) > 6 else Decimal("0")

        balances[code] = {
            "code": code,
            "name": vals[0],
            "total": float(all_pos),
            "btc_equivalent": float(btc_eq),
        }
    return balances


def _parse_access_logs(df) -> List[Dict[str, str]]:
    """Parse Access Logs → extract IP/geo info for analysis."""
    logs = []
    for _, row in df.iterrows():
        ip = _safe_str(row.get("Real IP", ""))
        if not ip:
            continue
        logs.append({
            "ip": ip,
            "geo": _safe_str(row.get("Geolocation", "")),
            "timestamp": _safe_str(row.get("Timestamp (UTC)", "")),
            "operation": _safe_str(row.get("Operation", "")),
            "client": _safe_str(row.get("Client", "")),
        })
    return logs


# ---------------------------------------------------------------------------
# Main detection & parsing
# ---------------------------------------------------------------------------

def is_binance_xlsx(path: Path) -> bool:
    """Check if an XLSX file is a Binance full account export."""
    try:
        import openpyxl
        wb = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
        sheets = set(wb.sheetnames)
        wb.close()
        # Must have at least 3 of these characteristic Binance sheets
        binance_sheets = {
            "Customer Information", "Account Balance", "Deposit History",
            "Withdrawal History", "Order History", "Current Assets & Wallets",
            "Binance Pay",
        }
        return len(sheets & binance_sheets) >= 3
    except Exception:
        return False


def parse_binance_xlsx(path: Path) -> ParsedCryptoData:
    """Parse a Binance full XLSX account export into normalized crypto data.

    Returns a ParsedCryptoData with all transactions, wallets, and metadata.
    """
    import pandas as pd

    result = ParsedCryptoData(source="binance_xlsx", source_type="exchange", chain="binance")

    try:
        xls = pd.ExcelFile(str(path))
    except Exception as e:
        result.errors.append(f"Nie udało się otworzyć pliku XLSX: {e}")
        return result

    sheets = set(xls.sheet_names)
    all_txs: List[CryptoTransaction] = []
    meta: Dict[str, Any] = {}

    # 1. Customer Information
    if "Customer Information" in sheets:
        try:
            df = pd.read_excel(xls, sheet_name="Customer Information")
            meta.update(_parse_customer_info(df))
        except Exception as e:
            log.warning("Error parsing Customer Information: %s", e)

    # 2. Deposit History
    if "Deposit History" in sheets:
        try:
            df = pd.read_excel(xls, sheet_name="Deposit History")
            txs = _parse_deposit_history(df)
            all_txs.extend(txs)
            log.info("Deposit History: %d transactions", len(txs))
        except Exception as e:
            log.warning("Error parsing Deposit History: %s", e)
            result.errors.append(f"Deposit History: {e}")

    # 3. Withdrawal History
    if "Withdrawal History" in sheets:
        try:
            df = pd.read_excel(xls, sheet_name="Withdrawal History")
            txs = _parse_withdrawal_history(df)
            all_txs.extend(txs)
            log.info("Withdrawal History: %d transactions", len(txs))
        except Exception as e:
            log.warning("Error parsing Withdrawal History: %s", e)
            result.errors.append(f"Withdrawal History: {e}")

    # 4. Order History (spot trades)
    if "Order History" in sheets:
        try:
            df = pd.read_excel(xls, sheet_name="Order History")
            txs = _parse_order_history(df, "Order History")
            all_txs.extend(txs)
            log.info("Order History: %d transactions", len(txs))
        except Exception as e:
            log.warning("Error parsing Order History: %s", e)
            result.errors.append(f"Order History: {e}")

    # 5. Margin Order
    if "Margin Order" in sheets:
        try:
            df = pd.read_excel(xls, sheet_name="Margin Order")
            txs = _parse_order_history(df, "Margin Order")
            all_txs.extend(txs)
            log.info("Margin Order: %d transactions", len(txs))
        except Exception as e:
            log.warning("Error parsing Margin Order: %s", e)
            result.errors.append(f"Margin Order: {e}")

    # 6. Binance Pay
    if "Binance Pay" in sheets:
        try:
            df = pd.read_excel(xls, sheet_name="Binance Pay")
            txs = _parse_binance_pay(df)
            all_txs.extend(txs)
            log.info("Binance Pay: %d transactions", len(txs))
        except Exception as e:
            log.warning("Error parsing Binance Pay: %s", e)
            result.errors.append(f"Binance Pay: {e}")

    # 7. Card Transaction
    if "Card Transaction" in sheets:
        try:
            df = pd.read_excel(xls, sheet_name="Card Transaction")
            txs = _parse_card_transactions(df)
            all_txs.extend(txs)
            log.info("Card Transaction: %d transactions", len(txs))
        except Exception as e:
            log.warning("Error parsing Card Transaction: %s", e)
            result.errors.append(f"Card Transaction: {e}")

    # 8. OTC Trading
    if "OTC Trading" in sheets:
        try:
            df = pd.read_excel(xls, sheet_name="OTC Trading")
            txs = _parse_otc(df)
            all_txs.extend(txs)
            log.info("OTC Trading: %d transactions", len(txs))
        except Exception as e:
            log.warning("Error parsing OTC Trading: %s", e)
            result.errors.append(f"OTC Trading: {e}")

    # 9. Fiat Deposit History
    if "Fiat Deposit History" in sheets:
        try:
            df = pd.read_excel(xls, sheet_name="Fiat Deposit History")
            if len(df) > 0:
                txs = _parse_fiat_deposit(df)
                all_txs.extend(txs)
                log.info("Fiat Deposit History: %d transactions", len(txs))
        except Exception as e:
            log.warning("Error parsing Fiat Deposit History: %s", e)

    # 10. Fiat Withdrawal History
    if "Fiat Withdrawal History" in sheets:
        try:
            df = pd.read_excel(xls, sheet_name="Fiat Withdrawal History")
            if len(df) > 0:
                txs = _parse_fiat_withdrawal(df)
                all_txs.extend(txs)
                log.info("Fiat Withdrawal History: %d transactions", len(txs))
        except Exception as e:
            log.warning("Error parsing Fiat Withdrawal History: %s", e)

    # 11. P2P
    if "P2P" in sheets:
        try:
            df = pd.read_excel(xls, sheet_name="P2P")
            if len(df) > 0:
                txs = _parse_p2p(df)
                all_txs.extend(txs)
                log.info("P2P: %d transactions", len(txs))
        except Exception as e:
            log.warning("Error parsing P2P: %s", e)

    # 12. Current Assets & Wallets → wallet addresses
    wallets: List[WalletInfo] = []
    if "Current Assets & Wallets" in sheets:
        try:
            df = pd.read_excel(xls, sheet_name="Current Assets & Wallets")
            wallets = _parse_wallet_addresses(df)
            log.info("Wallet addresses extracted: %d", len(wallets))
        except Exception as e:
            log.warning("Error parsing Current Assets & Wallets: %s", e)

    # 13. Account Balance
    balances: Dict[str, Dict[str, Any]] = {}
    if "Account Balance" in sheets:
        try:
            df = pd.read_excel(xls, sheet_name="Account Balance")
            balances = _parse_account_balance(df)
        except Exception as e:
            log.warning("Error parsing Account Balance: %s", e)

    # 14. Access Logs (for metadata, not transactions)
    access_logs: List[Dict[str, str]] = []
    if "Access Logs" in sheets:
        try:
            df = pd.read_excel(xls, sheet_name="Access Logs")
            access_logs = _parse_access_logs(df)
        except Exception as e:
            log.warning("Error parsing Access Logs: %s", e)

    # Sort all transactions by timestamp
    all_txs.sort(key=lambda tx: tx.timestamp or "")

    # Build wallet info from transactions (supplement deposit wallets)
    tx_wallets = _build_tx_wallets(all_txs)
    # Merge: deposit wallets first, then tx-derived wallets
    wallet_map = {w.address.lower(): w for w in wallets}
    for w in tx_wallets:
        key = w.address.lower()
        if key not in wallet_map:
            wallet_map[key] = w
        else:
            # Merge stats
            existing = wallet_map[key]
            existing.tx_count += w.tx_count
            existing.total_received += w.total_received
            existing.total_sent += w.total_sent

    result.transactions = all_txs
    result.wallets = list(wallet_map.values())
    result.raw_row_count = len(all_txs)

    log.info(
        "Binance XLSX parsed: %d transactions, %d wallets, user_id=%s",
        len(all_txs), len(result.wallets), meta.get("user_id", "?"),
    )

    return result


def _build_tx_wallets(txs: List[CryptoTransaction]) -> List[WalletInfo]:
    """Build wallet info from transaction addresses (deduplicated)."""
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
            if tx.token:
                w.tokens[tx.token] = w.tokens.get(tx.token, Decimal("0"))
            if tx.timestamp:
                if not w.first_seen or tx.timestamp < w.first_seen:
                    w.first_seen = tx.timestamp
                if not w.last_seen or tx.timestamp > w.last_seen:
                    w.last_seen = tx.timestamp
    return list(wallets.values())


# ---------------------------------------------------------------------------
# Summary generators (used by pipeline for reports)
# ---------------------------------------------------------------------------

def build_binance_summary(parsed: ParsedCryptoData) -> Dict[str, Any]:
    """Build a comprehensive summary of a Binance XLSX export.

    Returns dict with:
      - coins_bought / coins_sold: which cryptos were traded
      - fiat_in / fiat_out: fiat flow totals
      - deposit_addresses: user's deposit wallets
      - counterparties: unique Binance user IDs they interacted with
      - internal_transfers: count and volume of Binance-internal txs
      - trade_pairs: market pairs traded
      - card_spending: total card expenditure
    """
    txs = parsed.transactions

    # 1. Coins bought/sold (from order history)
    coins_bought: Dict[str, float] = {}
    coins_sold: Dict[str, float] = {}
    trade_pairs: Dict[str, Dict[str, Any]] = {}

    for tx in txs:
        if tx.tx_type != "swap":
            continue
        market = tx.raw.get("market", "")
        side = tx.raw.get("side", "")
        qty = float(tx.amount)
        quote = tx.raw.get("quote_token", "")
        total_val = float(_dec(tx.raw.get("total_value", "0")))

        if side == "BUY":
            coins_bought[tx.token] = coins_bought.get(tx.token, 0.0) + qty
        elif side == "SELL":
            coins_sold[tx.token] = coins_sold.get(tx.token, 0.0) + qty

        if market:
            if market not in trade_pairs:
                trade_pairs[market] = {"buys": 0, "sells": 0, "buy_volume": 0.0, "sell_volume": 0.0}
            if side == "BUY":
                trade_pairs[market]["buys"] += 1
                trade_pairs[market]["buy_volume"] += total_val
            else:
                trade_pairs[market]["sells"] += 1
                trade_pairs[market]["sell_volume"] += total_val

    # 2. Fiat in/out
    fiat_in: Dict[str, float] = {}
    fiat_out: Dict[str, float] = {}
    for tx in txs:
        if tx.tx_type == "fiat_deposit":
            fiat_in[tx.token] = fiat_in.get(tx.token, 0.0) + float(tx.amount)
        elif tx.tx_type == "fiat_withdrawal":
            fiat_out[tx.token] = fiat_out.get(tx.token, 0.0) + float(tx.amount)

    # 3. Deposit addresses
    deposit_addresses = [
        {"address": w.address, "chain": w.chain, "tokens": list(w.tokens.keys())}
        for w in parsed.wallets
        if w.label and "deposit" in w.label
    ]

    # 4. Counterparties (Binance users interacted with)
    counterparties: Dict[str, Dict[str, Any]] = {}
    for tx in txs:
        cp_id = tx.raw.get("counterparty_id", "")
        if not cp_id or cp_id in ("", "nan"):
            continue
        if cp_id not in counterparties:
            counterparties[cp_id] = {
                "user_id": cp_id,
                "tx_count": 0,
                "total_in": 0.0,
                "total_out": 0.0,
                "tokens": set(),
                "first_seen": "",
                "last_seen": "",
                "sources": set(),
            }
        cp = counterparties[cp_id]
        cp["tx_count"] += 1
        cp["tokens"].add(tx.token)
        cp["sources"].add(tx.raw.get("sheet", ""))
        if tx.tx_type == "deposit":
            cp["total_in"] += float(tx.amount)
        elif tx.tx_type == "withdrawal":
            cp["total_out"] += float(tx.amount)
        if tx.timestamp:
            if not cp["first_seen"] or tx.timestamp < cp["first_seen"]:
                cp["first_seen"] = tx.timestamp
            if not cp["last_seen"] or tx.timestamp > cp["last_seen"]:
                cp["last_seen"] = tx.timestamp

    # Convert sets to lists for JSON
    for cp in counterparties.values():
        cp["tokens"] = sorted(cp["tokens"])
        cp["sources"] = sorted(cp["sources"])

    # 5. Internal vs external transfer stats
    internal_count = sum(1 for tx in txs if "binance_internal" in tx.risk_tags)
    external_deposit_count = sum(1 for tx in txs if tx.tx_type == "deposit" and "binance_internal" not in tx.risk_tags)
    external_withdrawal_count = sum(1 for tx in txs if tx.tx_type == "withdrawal" and "binance_internal" not in tx.risk_tags)

    # 6. Card spending
    card_total: Dict[str, float] = {}
    card_merchants: Dict[str, float] = {}
    for tx in txs:
        if tx.raw.get("sheet") == "Card Transaction":
            card_total[tx.token] = card_total.get(tx.token, 0.0) + float(tx.amount)
            merchant = tx.counterparty
            if merchant:
                card_merchants[merchant] = card_merchants.get(merchant, 0.0) + float(tx.amount)

    return {
        "coins_bought": coins_bought,
        "coins_sold": coins_sold,
        "trade_pairs": trade_pairs,
        "fiat_in": fiat_in,
        "fiat_out": fiat_out,
        "deposit_addresses": deposit_addresses,
        "counterparties": counterparties,
        "internal_transfer_count": internal_count,
        "external_deposit_count": external_deposit_count,
        "external_withdrawal_count": external_withdrawal_count,
        "card_spending": card_total,
        "card_merchants": card_merchants,
    }


def build_forensic_report(path: Path, parsed: ParsedCryptoData) -> Dict[str, Any]:
    """Build a comprehensive forensic report from a Binance XLSX export.

    Extracts intelligence useful for law enforcement:
      - account_info: KYC data, user IDs, email, phone
      - user_ids_in_file: all distinct Binance user IDs found across sheets
      - access_log_analysis: IP addresses, geolocations, devices, foreign logins
      - device_fingerprints: approved devices with IP/geo/timestamps
      - card_info: Binance card numbers, types, statuses
      - card_geo_timeline: card spending locations with timestamps (travel trail)
      - external_source_addresses: on-chain addresses that deposited to this account
      - external_dest_addresses: on-chain addresses that received withdrawals
      - binance_pay_counterparties: C2C transfer partners with volumes
      - pass_through_detection: deposit→withdrawal chains within 24h (flow-through)
      - privacy_coin_usage: ZEC/XMR/DASH deposit/trade/withdrawal activity
      - mining_patterns: repeated small deposits from same address (mining pools)
      - margin_analysis: separate user ID on margin, markets, volumes
      - activity_timeline: hourly/daily activity patterns
      - foreign_logins: logins from non-primary country
      - multi_ip_days: days with suspiciously many unique IP addresses
    """
    import pandas as pd
    from collections import defaultdict

    report: Dict[str, Any] = {}
    txs = parsed.transactions

    try:
        xls = pd.ExcelFile(str(path))
    except Exception as e:
        return {"error": str(e)}

    sheets = set(xls.sheet_names)

    # -----------------------------------------------------------------------
    # 1. Account info (KYC)
    # -----------------------------------------------------------------------
    account_info: Dict[str, Any] = {}
    if "Customer Information" in sheets:
        try:
            df = pd.read_excel(xls, sheet_name="Customer Information")
            account_info = _parse_customer_info(df)
        except Exception:
            pass
    report["account_info"] = account_info

    # -----------------------------------------------------------------------
    # 2. All User IDs found in file (some sheets have different users!)
    # -----------------------------------------------------------------------
    user_ids_found: Dict[str, List[str]] = {}
    for sheet_name in ["Deposit History", "Withdrawal History", "Order History",
                       "Margin Order", "Binance Pay", "Card Transaction"]:
        if sheet_name not in sheets:
            continue
        try:
            df = pd.read_excel(xls, sheet_name=sheet_name)
            uid_col = None
            for c in df.columns:
                if "user" in str(c).lower() and "id" in str(c).lower():
                    uid_col = c
                    break
            if uid_col:
                uids = sorted(set(str(x) for x in df[uid_col].dropna().unique()
                                   if str(x) not in ("nan", "")))
                if uids:
                    user_ids_found[sheet_name] = uids
        except Exception:
            pass
    report["user_ids_in_file"] = user_ids_found

    # -----------------------------------------------------------------------
    # 3. Access log analysis
    # -----------------------------------------------------------------------
    access_analysis: Dict[str, Any] = {}
    if "Access Logs" in sheets:
        try:
            al = pd.read_excel(xls, sheet_name="Access Logs")
            al["ts"] = pd.to_datetime(al["Timestamp (UTC)"], errors="coerce")

            # Unique IPs
            ip_counts = al["Real IP"].value_counts()
            access_analysis["total_entries"] = len(al)
            access_analysis["unique_ips"] = len(ip_counts)
            access_analysis["top_ips"] = {str(k): int(v) for k, v in ip_counts.head(20).items()}

            # Geolocations
            geo_counts = al["Geolocation"].value_counts()
            access_analysis["geolocations"] = {str(k): int(v) for k, v in geo_counts.head(30).items()}

            # Clients/devices
            client_counts = al["Client"].value_counts()
            access_analysis["clients"] = {str(k): int(v) for k, v in client_counts.items()}

            # Date range
            dates = al["ts"].dropna()
            if len(dates) > 0:
                access_analysis["first_login"] = str(dates.min())[:19]
                access_analysis["last_login"] = str(dates.max())[:19]

            # Hourly activity pattern
            hours = al["ts"].dt.hour.value_counts().sort_index()
            access_analysis["hourly_pattern"] = {int(k): int(v) for k, v in hours.items()}

            # Foreign logins (non-primary country)
            all_geos = al["Geolocation"].dropna()
            if len(all_geos) > 0:
                # Determine primary country from most common geo
                primary_country = ""
                for geo in geo_counts.index:
                    geo_str = str(geo)
                    if " " in geo_str:
                        primary_country = geo_str.split()[0]
                        break

                if primary_country:
                    foreign = al[~al["Geolocation"].astype(str).str.startswith(primary_country)]
                    foreign_geos = foreign["Geolocation"].value_counts()
                    access_analysis["primary_country"] = primary_country
                    access_analysis["foreign_login_count"] = len(foreign)
                    access_analysis["foreign_locations"] = {
                        str(k): int(v) for k, v in foreign_geos.items()
                    }

                    # Foreign login details (for timeline)
                    foreign_details = []
                    for _, row in foreign.sort_values("ts").iterrows():
                        foreign_details.append({
                            "timestamp": str(row["ts"])[:19],
                            "geo": _safe_str(row.get("Geolocation", "")),
                            "ip": _safe_str(row.get("Real IP", "")),
                            "client": _safe_str(row.get("Client", "")),
                            "operation": _safe_str(row.get("Operation", "")),
                        })
                    access_analysis["foreign_login_timeline"] = foreign_details[:200]

            # Multi-IP days (suspicious concurrent usage)
            al["date"] = al["ts"].dt.date
            daily_ips = al.groupby("date")["Real IP"].nunique()
            multi_ip = daily_ips[daily_ips > 3]
            access_analysis["multi_ip_days"] = [
                {"date": str(d), "unique_ips": int(c)}
                for d, c in multi_ip.sort_values(ascending=False).head(20).items()
            ]

        except Exception as e:
            access_analysis["error"] = str(e)
    report["access_log_analysis"] = access_analysis

    # -----------------------------------------------------------------------
    # 4. Approved devices (fingerprints)
    # -----------------------------------------------------------------------
    devices: List[Dict[str, str]] = []
    if "Approved Devices" in sheets:
        try:
            ad = pd.read_excel(xls, sheet_name="Approved Devices")
            for _, row in ad.iterrows():
                dn = _safe_str(row.get("Device Name"))
                if not dn:
                    continue
                devices.append({
                    "device": dn,
                    "client": _safe_str(row.get("Client")),
                    "ip": _safe_str(row.get("IP Address")),
                    "geo": _safe_str(row.get("Geolocation")),
                    "last_used": _safe_str(row.get("Recent Usage Timestamp (UTC)")),
                    "status": _safe_str(row.get("Status")),
                })
        except Exception:
            pass
    report["device_fingerprints"] = devices

    # -----------------------------------------------------------------------
    # 5. Card info & geo-timeline
    # -----------------------------------------------------------------------
    cards: List[Dict[str, str]] = []
    if "Card Info" in sheets:
        try:
            ci = pd.read_excel(xls, sheet_name="Card Info")
            for _, row in ci.iterrows():
                cards.append({
                    "card_number": _safe_str(row.get("Card Number")),
                    "card_type": _safe_str(row.get("Card Type")),
                    "status": _safe_str(row.get("Card Status")),
                    "created": _safe_str(row.get("Create Date")),
                })
        except Exception:
            pass
    report["card_info"] = cards

    card_timeline: List[Dict[str, Any]] = []
    if "Card Transaction" in sheets:
        try:
            ct = pd.read_excel(xls, sheet_name="Card Transaction")
            ct["ts"] = pd.to_datetime(ct["Created date"], errors="coerce")
            for _, row in ct.sort_values("ts").iterrows():
                card_timeline.append({
                    "timestamp": str(row["ts"])[:19] if pd.notna(row["ts"]) else "",
                    "merchant": _safe_str(row.get("Merchant Name")),
                    "amount": float(row.get("Total", 0)),
                    "currency": _safe_str(row.get("Currency")),
                    "status": _safe_str(row.get("Status")),
                })
        except Exception:
            pass
    report["card_geo_timeline"] = card_timeline

    # -----------------------------------------------------------------------
    # 6. External source/dest addresses (on-chain)
    # -----------------------------------------------------------------------
    ext_sources: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {"total": 0.0, "tokens": set(), "count": 0, "networks": set(), "display": ""}
    )
    ext_dests: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {"total": 0.0, "tokens": set(), "count": 0, "networks": set(), "display": ""}
    )

    def _norm_addr(addr: str) -> str:
        """Normalize address for dedup — lowercase for EVM, strip whitespace."""
        a = addr.strip()
        if a.startswith("0x") or a.startswith("0X"):
            return a.lower()
        return a

    for tx in txs:
        is_int = "binance_internal" in (tx.risk_tags or [])
        if tx.tx_type == "deposit" and not is_int and tx.from_address:
            key = _norm_addr(tx.from_address)
            s = ext_sources[key]
            s["total"] += float(tx.amount)
            s["tokens"].add(tx.token)
            s["count"] += 1
            s["networks"].add(tx.chain)
            if not s["display"]:
                s["display"] = tx.from_address.strip()
        elif tx.tx_type == "withdrawal" and not is_int and tx.to_address:
            key = _norm_addr(tx.to_address)
            d = ext_dests[key]
            d["total"] += float(tx.amount)
            d["tokens"].add(tx.token)
            d["count"] += 1
            d["networks"].add(tx.chain)
            if not d["display"]:
                d["display"] = tx.to_address.strip()

    report["external_source_addresses"] = sorted(
        [{"address": v["display"] or k, "total": v["total"], "tokens": sorted(v["tokens"]),
          "count": v["count"], "networks": sorted(v["networks"])}
         for k, v in ext_sources.items()],
        key=lambda x: x["total"], reverse=True,
    )
    report["external_dest_addresses"] = sorted(
        [{"address": v["display"] or k, "total": v["total"], "tokens": sorted(v["tokens"]),
          "count": v["count"], "networks": sorted(v["networks"])}
         for k, v in ext_dests.items()],
        key=lambda x: x["total"], reverse=True,
    )

    # -----------------------------------------------------------------------
    # 7. Binance Pay counterparties (C2C)
    # -----------------------------------------------------------------------
    pay_cps: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {"in": 0.0, "out": 0.0, "tokens": set(), "count": 0,
                 "wallet_id": "", "first": "", "last": ""}
    )
    for tx in txs:
        if tx.raw.get("sheet") != "Binance Pay":
            continue
        cpid = tx.raw.get("counterparty_binance_id", "")
        if not cpid:
            continue
        p = pay_cps[cpid]
        p["count"] += 1
        p["tokens"].add(tx.token)
        p["wallet_id"] = tx.raw.get("counterparty_wallet_id", p["wallet_id"])
        if tx.raw.get("direction") == "IN":
            p["in"] += float(tx.amount)
        else:
            p["out"] += float(tx.amount)
        if tx.timestamp:
            if not p["first"] or tx.timestamp < p["first"]:
                p["first"] = tx.timestamp
            if not p["last"] or tx.timestamp > p["last"]:
                p["last"] = tx.timestamp

    report["binance_pay_counterparties"] = {
        k: {**v, "tokens": sorted(v["tokens"])} for k, v in pay_cps.items()
    }

    # -----------------------------------------------------------------------
    # 8. Pass-through detection (deposit→withdrawal within 24h)
    # -----------------------------------------------------------------------
    from datetime import timedelta

    int_deps = [tx for tx in txs if tx.tx_type == "deposit"
                and "binance_internal" in (tx.risk_tags or []) and tx.timestamp]
    int_wds = [tx for tx in txs if tx.tx_type == "withdrawal"
               and "binance_internal" in (tx.risk_tags or []) and tx.timestamp]

    pass_throughs: List[Dict[str, Any]] = []
    for dep_tx in int_deps:
        try:
            dep_dt = datetime.strptime(dep_tx.timestamp[:19], "%Y-%m-%dT%H:%M:%S")
        except Exception:
            continue
        for wd_tx in int_wds:
            try:
                wd_dt = datetime.strptime(wd_tx.timestamp[:19], "%Y-%m-%dT%H:%M:%S")
            except Exception:
                continue
            delta = (wd_dt - dep_dt).total_seconds()
            if 0 < delta <= 86400:  # within 24 hours
                pass_throughs.append({
                    "deposit_time": dep_tx.timestamp,
                    "deposit_amount": float(dep_tx.amount),
                    "deposit_token": dep_tx.token,
                    "deposit_from": dep_tx.counterparty,
                    "withdrawal_time": wd_tx.timestamp,
                    "withdrawal_amount": float(wd_tx.amount),
                    "withdrawal_token": wd_tx.token,
                    "withdrawal_to": wd_tx.counterparty,
                    "delay_hours": round(delta / 3600, 1),
                })
    report["pass_through_detection"] = pass_throughs[:100]
    report["pass_through_count"] = len(pass_throughs)

    # -----------------------------------------------------------------------
    # 9. Privacy coin usage
    # -----------------------------------------------------------------------
    _PRIVACY = {"XMR", "ZEC", "DASH", "SCRT", "BEAM", "GRIN", "FIRO"}
    priv_txs = [tx for tx in txs if tx.token in _PRIVACY]
    priv_summary: Dict[str, Dict[str, Any]] = {}
    for tx in priv_txs:
        if tx.token not in priv_summary:
            priv_summary[tx.token] = {
                "deposits": 0, "deposit_amount": 0.0,
                "withdrawals": 0, "withdrawal_amount": 0.0,
                "trades": 0, "trade_amount": 0.0,
                "unique_source_addresses": set(),
            }
        ps = priv_summary[tx.token]
        if tx.tx_type == "deposit":
            ps["deposits"] += 1
            ps["deposit_amount"] += float(tx.amount)
            if tx.from_address:
                ps["unique_source_addresses"].add(tx.from_address)
        elif tx.tx_type == "withdrawal":
            ps["withdrawals"] += 1
            ps["withdrawal_amount"] += float(tx.amount)
        elif tx.tx_type == "swap":
            ps["trades"] += 1
            ps["trade_amount"] += float(tx.amount)

    for ps in priv_summary.values():
        ps["unique_source_addresses"] = len(ps["unique_source_addresses"])

    report["privacy_coin_usage"] = priv_summary

    # -----------------------------------------------------------------------
    # 10. Mining patterns (repeated small deposits from same address)
    # -----------------------------------------------------------------------
    addr_stats: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {"count": 0, "total": 0.0, "token": ""}
    )
    for tx in txs:
        if tx.tx_type != "deposit" or not tx.from_address:
            continue
        if "binance_internal" in (tx.risk_tags or []):
            continue
        key = tx.from_address
        s = addr_stats[key]
        s["count"] += 1
        s["total"] += float(tx.amount)
        s["token"] = tx.token

    mining = [
        {"address": k, "count": v["count"], "total": round(v["total"], 8),
         "avg": round(v["total"] / v["count"], 8), "token": v["token"]}
        for k, v in addr_stats.items()
        if v["count"] >= 5 and (v["total"] / v["count"]) < 1.0
    ]
    mining.sort(key=lambda x: x["count"], reverse=True)
    report["mining_patterns"] = mining[:50]

    # -----------------------------------------------------------------------
    # 11. Margin trading analysis (often different user ID!)
    # -----------------------------------------------------------------------
    margin_info: Dict[str, Any] = {}
    if "Margin Order" in sheets:
        try:
            mo = pd.read_excel(xls, sheet_name="Margin Order")
            user_ids = [str(x) for x in mo["User ID"].unique() if str(x) != "nan"]
            filled = mo[mo["Status"] == "FILLED"]
            markets = filled["Market ID"].value_counts()
            buys = len(filled[filled["Side"] == "BUY"])
            sells = len(filled[filled["Side"] == "SELL"])
            margin_info = {
                "user_ids": user_ids,
                "total_orders": len(mo),
                "filled_orders": len(filled),
                "cancelled_orders": len(mo[mo["Status"] == "CANCELED"]),
                "buy_count": buys,
                "sell_count": sells,
                "top_markets": {str(k): int(v) for k, v in markets.head(15).items()},
            }
        except Exception as e:
            margin_info["error"] = str(e)
    report["margin_analysis"] = margin_info

    # -----------------------------------------------------------------------
    # 12. Temporal analysis — activity patterns
    # -----------------------------------------------------------------------
    temporal: Dict[str, Any] = {}
    # Hourly distribution (0-23)
    hour_dist: Dict[int, int] = defaultdict(int)
    # Day of week distribution (0=Mon, 6=Sun)
    dow_dist: Dict[int, int] = defaultdict(int)
    # Daily tx count for burst detection
    daily_counts: Dict[str, int] = defaultdict(int)
    # Weekend vs weekday
    weekend_count = 0
    weekday_count = 0
    # Dormancy — gaps between consecutive txs
    sorted_timestamps = []

    for tx in txs:
        if not tx.timestamp:
            continue
        try:
            dt = datetime.strptime(tx.timestamp[:19], "%Y-%m-%dT%H:%M:%S")
        except Exception:
            continue
        hour_dist[dt.hour] += 1
        dow_dist[dt.weekday()] += 1
        day_key = dt.strftime("%Y-%m-%d")
        daily_counts[day_key] += 1
        if dt.weekday() >= 5:
            weekend_count += 1
        else:
            weekday_count += 1
        sorted_timestamps.append(dt)

    sorted_timestamps.sort()

    temporal["hourly_distribution"] = {h: hour_dist.get(h, 0) for h in range(24)}
    temporal["dow_distribution"] = {d: dow_dist.get(d, 0) for d in range(7)}
    temporal["weekend_count"] = weekend_count
    temporal["weekday_count"] = weekday_count
    temporal["weekend_ratio"] = round(weekend_count / max(1, weekend_count + weekday_count) * 100, 1)

    # Peak hour
    if hour_dist:
        peak_hour = max(hour_dist, key=hour_dist.get)
        temporal["peak_hour"] = peak_hour
        temporal["peak_hour_count"] = hour_dist[peak_hour]

    # Night activity (0-5 AM)
    night_count = sum(hour_dist.get(h, 0) for h in range(0, 6))
    temporal["night_activity_count"] = night_count
    temporal["night_activity_ratio"] = round(night_count / max(1, sum(hour_dist.values())) * 100, 1)

    # Burst detection — days with > 50 transactions
    bursts = [{"date": d, "tx_count": c} for d, c in daily_counts.items() if c > 50]
    bursts.sort(key=lambda x: x["tx_count"], reverse=True)
    temporal["burst_days"] = bursts[:20]

    # Top active days
    top_days = sorted(daily_counts.items(), key=lambda x: x[1], reverse=True)[:10]
    temporal["top_active_days"] = [{"date": d, "tx_count": c} for d, c in top_days]

    # Dormancy periods (gaps > 7 days)
    dormancy_periods = []
    if len(sorted_timestamps) >= 2:
        for i in range(1, len(sorted_timestamps)):
            gap = (sorted_timestamps[i] - sorted_timestamps[i - 1]).total_seconds()
            if gap > 7 * 86400:  # > 7 days
                dormancy_periods.append({
                    "from": sorted_timestamps[i - 1].strftime("%Y-%m-%d"),
                    "to": sorted_timestamps[i].strftime("%Y-%m-%d"),
                    "days": round(gap / 86400, 1),
                })
        dormancy_periods.sort(key=lambda x: x["days"], reverse=True)
    temporal["dormancy_periods"] = dormancy_periods[:10]

    # Activity first/last
    if sorted_timestamps:
        temporal["first_activity"] = sorted_timestamps[0].strftime("%Y-%m-%dT%H:%M:%S")
        temporal["last_activity"] = sorted_timestamps[-1].strftime("%Y-%m-%dT%H:%M:%S")
        total_days = (sorted_timestamps[-1] - sorted_timestamps[0]).days + 1
        temporal["active_span_days"] = total_days
        active_days = len(daily_counts)
        temporal["active_days"] = active_days
        temporal["activity_density"] = round(active_days / max(1, total_days) * 100, 1)

    report["temporal_analysis"] = temporal

    # -----------------------------------------------------------------------
    # 13. Conversion chains — token flow paths
    # -----------------------------------------------------------------------
    # Track sequences: deposit token → swap chain → withdrawal token
    token_flows: Dict[str, Dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for tx in txs:
        if tx.tx_type == "swap":
            base = tx.token
            quote = tx.raw.get("quote_token", "")
            side = tx.raw.get("side", "")
            if base and quote:
                if side == "BUY":
                    token_flows[quote][base] += float(tx.amount)
                else:
                    token_flows[base][quote] += float(tx.amount)

    # Detect fiat→crypto→withdrawal chains
    fiat_to_crypto_chains = []
    fiat_deposit_tokens = set()
    withdrawal_tokens = set()
    for tx in txs:
        if tx.tx_type == "fiat_deposit":
            fiat_deposit_tokens.add(tx.token)
        elif tx.tx_type == "withdrawal" and "binance_internal" not in (tx.risk_tags or []):
            withdrawal_tokens.add(tx.token)

    # Build conversion edges
    conversion_edges = []
    for src, dests in token_flows.items():
        for dst, vol in sorted(dests.items(), key=lambda x: x[1], reverse=True):
            conversion_edges.append({"from": src, "to": dst, "volume": round(vol, 4)})
    conversion_edges.sort(key=lambda x: x["volume"], reverse=True)

    report["conversion_chains"] = {
        "edges": conversion_edges[:50],
        "fiat_entry_tokens": sorted(fiat_deposit_tokens),
        "withdrawal_tokens": sorted(withdrawal_tokens),
        "unique_swap_pairs": len(conversion_edges),
    }

    # -----------------------------------------------------------------------
    # 14. Structuring / smurfing detection
    # -----------------------------------------------------------------------
    structuring: Dict[str, Any] = {}
    # Thresholds (USD equivalent)
    _THRESHOLDS = [1000, 5000, 9000, 10000, 15000]

    # Group deposits by day and check for multiple just-below-threshold
    dep_by_day: Dict[str, List[float]] = defaultdict(list)
    wd_by_day: Dict[str, List[float]] = defaultdict(list)
    for tx in txs:
        if not tx.timestamp:
            continue
        day = tx.timestamp[:10]
        amt = float(tx.amount)
        if tx.tx_type in ("deposit", "fiat_deposit"):
            dep_by_day[day].append(amt)
        elif tx.tx_type in ("withdrawal", "fiat_withdrawal"):
            wd_by_day[day].append(amt)

    # Detect days with multiple txs just below threshold (within 10% below)
    structuring_alerts = []
    for threshold in _THRESHOLDS:
        low = threshold * 0.90
        for day, amounts in dep_by_day.items():
            near = [a for a in amounts if low <= a < threshold]
            if len(near) >= 2:
                structuring_alerts.append({
                    "date": day,
                    "type": "deposit",
                    "threshold": threshold,
                    "count": len(near),
                    "amounts": [round(a, 2) for a in near[:5]],
                    "daily_total": round(sum(near), 2),
                })
        for day, amounts in wd_by_day.items():
            near = [a for a in amounts if low <= a < threshold]
            if len(near) >= 2:
                structuring_alerts.append({
                    "date": day,
                    "type": "withdrawal",
                    "threshold": threshold,
                    "count": len(near),
                    "amounts": [round(a, 2) for a in near[:5]],
                    "daily_total": round(sum(near), 2),
                })

    structuring_alerts.sort(key=lambda x: x["daily_total"], reverse=True)

    # Amount clustering — find frequently used amounts (rounded)
    all_amounts = [float(tx.amount) for tx in txs if float(tx.amount) > 0]
    rounded_amounts: Dict[float, int] = defaultdict(int)
    for a in all_amounts:
        # Round to nearest 100
        ra = round(a / 100) * 100
        if ra > 0:
            rounded_amounts[ra] += 1
    frequent_amounts = sorted(
        [{"amount": a, "count": c} for a, c in rounded_amounts.items() if c >= 5],
        key=lambda x: x["count"], reverse=True
    )[:20]

    structuring["alerts"] = structuring_alerts[:30]
    structuring["alert_count"] = len(structuring_alerts)
    structuring["frequent_amounts"] = frequent_amounts
    report["structuring_detection"] = structuring

    # -----------------------------------------------------------------------
    # 15. Wash trading detection
    # -----------------------------------------------------------------------
    wash: Dict[str, Any] = {}

    # Find buy-sell pairs on same market within short time windows
    swap_txs = [(tx, datetime.strptime(tx.timestamp[:19], "%Y-%m-%dT%H:%M:%S"))
                for tx in txs if tx.tx_type == "swap" and tx.timestamp
                and tx.raw.get("market")]
    swap_txs.sort(key=lambda x: x[1])

    wash_suspects = []
    for i, (tx1, dt1) in enumerate(swap_txs):
        for j in range(i + 1, min(i + 20, len(swap_txs))):
            tx2, dt2 = swap_txs[j]
            delta = (dt2 - dt1).total_seconds()
            if delta > 300:  # 5 min window
                break
            if (tx1.raw.get("market") == tx2.raw.get("market")
                    and tx1.raw.get("side") != tx2.raw.get("side")):
                wash_suspects.append({
                    "market": tx1.raw.get("market", ""),
                    "time1": tx1.timestamp[:19],
                    "side1": tx1.raw.get("side", ""),
                    "amount1": round(float(tx1.amount), 6),
                    "time2": tx2.timestamp[:19],
                    "side2": tx2.raw.get("side", ""),
                    "amount2": round(float(tx2.amount), 6),
                    "delay_sec": round(delta),
                })
    wash_suspects = wash_suspects[:50]

    # Per-market net position analysis
    market_net: Dict[str, Dict[str, float]] = defaultdict(lambda: {"bought": 0.0, "sold": 0.0, "gross": 0.0})
    for tx in txs:
        if tx.tx_type != "swap":
            continue
        market = tx.raw.get("market", "")
        side = tx.raw.get("side", "")
        qty = float(tx.amount)
        if side == "BUY":
            market_net[market]["bought"] += qty
            market_net[market]["gross"] += qty
        elif side == "SELL":
            market_net[market]["sold"] += qty
            market_net[market]["gross"] += qty

    wash_markets = []
    for market, data in market_net.items():
        net = abs(data["bought"] - data["sold"])
        gross = data["gross"]
        if gross > 0:
            net_ratio = net / gross
            if net_ratio < 0.1 and gross > 0 and (data["bought"] > 0 and data["sold"] > 0):
                wash_markets.append({
                    "market": market,
                    "gross_volume": round(gross, 4),
                    "net_position": round(net, 4),
                    "net_ratio": round(net_ratio * 100, 1),
                    "buys": round(data["bought"], 4),
                    "sells": round(data["sold"], 4),
                })
    wash_markets.sort(key=lambda x: x["gross_volume"], reverse=True)

    wash["rapid_reversals"] = wash_suspects
    wash["zero_net_markets"] = wash_markets[:20]
    wash["rapid_reversal_count"] = len(wash_suspects)
    report["wash_trading"] = wash

    # -----------------------------------------------------------------------
    # 16. Fiat on/off ramp analysis
    # -----------------------------------------------------------------------
    fiat_analysis: Dict[str, Any] = {}

    fiat_deps = [tx for tx in txs if tx.tx_type == "fiat_deposit"]
    fiat_wds = [tx for tx in txs if tx.tx_type == "fiat_withdrawal"]

    fiat_in_total: Dict[str, float] = defaultdict(float)
    fiat_out_total: Dict[str, float] = defaultdict(float)
    for tx in fiat_deps:
        fiat_in_total[tx.token] += float(tx.amount)
    for tx in fiat_wds:
        fiat_out_total[tx.token] += float(tx.amount)

    fiat_analysis["currencies_in"] = {k: round(v, 2) for k, v in fiat_in_total.items()}
    fiat_analysis["currencies_out"] = {k: round(v, 2) for k, v in fiat_out_total.items()}
    fiat_analysis["total_fiat_in"] = round(sum(fiat_in_total.values()), 2)
    fiat_analysis["total_fiat_out"] = round(sum(fiat_out_total.values()), 2)
    fiat_analysis["net_fiat_flow"] = round(sum(fiat_in_total.values()) - sum(fiat_out_total.values()), 2)
    fiat_analysis["fiat_deposit_count"] = len(fiat_deps)
    fiat_analysis["fiat_withdrawal_count"] = len(fiat_wds)

    # Time from first fiat deposit to first crypto withdrawal
    fiat_dep_times = []
    crypto_wd_times = []
    for tx in fiat_deps:
        if tx.timestamp:
            try:
                fiat_dep_times.append(datetime.strptime(tx.timestamp[:19], "%Y-%m-%dT%H:%M:%S"))
            except Exception:
                pass
    for tx in txs:
        if tx.tx_type == "withdrawal" and "binance_internal" not in (tx.risk_tags or []) and tx.timestamp:
            try:
                crypto_wd_times.append(datetime.strptime(tx.timestamp[:19], "%Y-%m-%dT%H:%M:%S"))
            except Exception:
                pass

    if fiat_dep_times and crypto_wd_times:
        first_fiat = min(fiat_dep_times)
        first_crypto_wd = min(crypto_wd_times)
        delta = (first_crypto_wd - first_fiat).total_seconds()
        fiat_analysis["first_fiat_deposit"] = first_fiat.strftime("%Y-%m-%dT%H:%M:%S")
        fiat_analysis["first_crypto_withdrawal"] = first_crypto_wd.strftime("%Y-%m-%dT%H:%M:%S")
        fiat_analysis["fiat_to_crypto_wd_hours"] = round(delta / 3600, 1)

    # P2P as fiat ramp
    p2p_txs = [tx for tx in txs if tx.raw.get("sheet") == "P2P"]
    fiat_analysis["p2p_transaction_count"] = len(p2p_txs)
    fiat_analysis["p2p_as_ramp"] = len(p2p_txs) > 0

    report["fiat_ramp_analysis"] = fiat_analysis

    # -----------------------------------------------------------------------
    # 17. P2P trading analysis
    # -----------------------------------------------------------------------
    p2p_analysis: Dict[str, Any] = {}
    p2p_all = [tx for tx in txs if tx.raw.get("sheet") == "P2P"]

    if p2p_all:
        p2p_analysis["total_count"] = len(p2p_all)
        p2p_analysis["total_pct"] = round(len(p2p_all) / max(1, len(txs)) * 100, 1)

        # P2P counterparties
        p2p_cps: Dict[str, Dict[str, Any]] = defaultdict(
            lambda: {"count": 0, "volume": 0.0, "tokens": set()}
        )
        p2p_methods: Dict[str, int] = defaultdict(int)
        p2p_fiat: Dict[str, float] = defaultdict(float)
        p2p_volume = 0.0

        for tx in p2p_all:
            cp = tx.counterparty or tx.raw.get("counterparty_id", "")
            if cp:
                p2p_cps[cp]["count"] += 1
                p2p_cps[cp]["volume"] += float(tx.amount)
                p2p_cps[cp]["tokens"].add(tx.token)
            method = tx.raw.get("payment_method", "")
            if method:
                p2p_methods[method] += 1
            if tx.token in _FIAT_CURRENCIES:
                p2p_fiat[tx.token] += float(tx.amount)
            p2p_volume += float(tx.amount)

        p2p_analysis["total_volume"] = round(p2p_volume, 2)
        p2p_analysis["unique_counterparties"] = len(p2p_cps)
        p2p_analysis["payment_methods"] = dict(p2p_methods)
        p2p_analysis["fiat_currencies"] = {k: round(v, 2) for k, v in p2p_fiat.items()}
        p2p_analysis["top_counterparties"] = sorted(
            [{"id": k, "count": v["count"], "volume": round(v["volume"], 4),
              "tokens": sorted(v["tokens"])} for k, v in p2p_cps.items()],
            key=lambda x: x["count"], reverse=True
        )[:30]
    else:
        p2p_analysis["total_count"] = 0

    report["p2p_analysis"] = p2p_analysis

    # -----------------------------------------------------------------------
    # 18. Deposit-to-withdrawal velocity
    # -----------------------------------------------------------------------
    velocity: Dict[str, Any] = {}

    # For each token: average time between deposit and next withdrawal
    dep_times: Dict[str, List[datetime]] = defaultdict(list)
    wd_times: Dict[str, List[datetime]] = defaultdict(list)
    for tx in txs:
        if not tx.timestamp:
            continue
        try:
            dt = datetime.strptime(tx.timestamp[:19], "%Y-%m-%dT%H:%M:%S")
        except Exception:
            continue
        if tx.tx_type == "deposit":
            dep_times[tx.token].append(dt)
        elif tx.tx_type == "withdrawal":
            wd_times[tx.token].append(dt)

    token_velocities = []
    hot_wallet_indicators = []
    for token in set(list(dep_times.keys()) + list(wd_times.keys())):
        deps = sorted(dep_times.get(token, []))
        wds = sorted(wd_times.get(token, []))
        if not deps or not wds:
            continue
        # For each deposit, find closest subsequent withdrawal
        delays = []
        for d in deps:
            for w in wds:
                delta = (w - d).total_seconds()
                if delta > 0:
                    delays.append(delta)
                    break
        if delays:
            avg_delay_h = sum(delays) / len(delays) / 3600
            min_delay_h = min(delays) / 3600
            token_velocities.append({
                "token": token,
                "avg_hold_hours": round(avg_delay_h, 1),
                "min_hold_hours": round(min_delay_h, 2),
                "deposit_count": len(deps),
                "withdrawal_count": len(wds),
            })
            if avg_delay_h < 1:
                hot_wallet_indicators.append({
                    "token": token,
                    "avg_hold_hours": round(avg_delay_h, 2),
                })

    token_velocities.sort(key=lambda x: x["avg_hold_hours"])
    velocity["token_velocities"] = token_velocities[:30]
    velocity["hot_wallet_indicators"] = hot_wallet_indicators
    velocity["has_hot_wallet_behavior"] = len(hot_wallet_indicators) > 0

    # Overall deposit-to-withdrawal ratio
    total_dep = sum(1 for tx in txs if tx.tx_type == "deposit")
    total_wd = sum(1 for tx in txs if tx.tx_type == "withdrawal")
    velocity["deposit_count"] = total_dep
    velocity["withdrawal_count"] = total_wd
    velocity["dep_wd_ratio"] = round(total_dep / max(1, total_wd), 2)

    report["velocity_analysis"] = velocity

    # -----------------------------------------------------------------------
    # 19. Fee analysis
    # -----------------------------------------------------------------------
    fee_analysis: Dict[str, Any] = {}
    fee_by_token: Dict[str, float] = defaultdict(float)
    fee_total = 0.0
    fee_count = 0
    bnb_fee_count = 0

    for tx in txs:
        fee_str = tx.raw.get("fee", "")
        fee_coin = tx.raw.get("fee_coin", "")
        if fee_str:
            try:
                fee_val = float(str(fee_str).replace(",", "."))
                if fee_val > 0:
                    fee_by_token[fee_coin or "UNKNOWN"] += fee_val
                    fee_total += fee_val
                    fee_count += 1
                    if fee_coin == "BNB":
                        bnb_fee_count += 1
            except (ValueError, TypeError):
                pass

    fee_analysis["total_fees_by_token"] = {k: round(v, 8) for k, v in
                                           sorted(fee_by_token.items(), key=lambda x: x[1], reverse=True)}
    fee_analysis["fee_paying_tx_count"] = fee_count
    fee_analysis["bnb_fee_count"] = bnb_fee_count
    fee_analysis["bnb_fee_ratio"] = round(bnb_fee_count / max(1, fee_count) * 100, 1)

    report["fee_analysis"] = fee_analysis

    # -----------------------------------------------------------------------
    # 20. Network / blockchain analysis
    # -----------------------------------------------------------------------
    network_analysis: Dict[str, Any] = {}
    network_counts: Dict[str, Dict[str, int]] = defaultdict(lambda: {"deposits": 0, "withdrawals": 0})
    network_volumes: Dict[str, Dict[str, float]] = defaultdict(lambda: {"dep_volume": 0.0, "wd_volume": 0.0})

    for tx in txs:
        net = tx.chain or tx.raw.get("network", "")
        if not net:
            continue
        if tx.tx_type == "deposit":
            network_counts[net]["deposits"] += 1
            network_volumes[net]["dep_volume"] += float(tx.amount)
        elif tx.tx_type == "withdrawal":
            network_counts[net]["withdrawals"] += 1
            network_volumes[net]["wd_volume"] += float(tx.amount)

    networks = []
    for net in set(list(network_counts.keys()) + list(network_volumes.keys())):
        c = network_counts.get(net, {"deposits": 0, "withdrawals": 0})
        v = network_volumes.get(net, {"dep_volume": 0.0, "wd_volume": 0.0})
        networks.append({
            "network": net,
            "deposits": c["deposits"],
            "withdrawals": c["withdrawals"],
            "total_tx": c["deposits"] + c["withdrawals"],
            "dep_volume": round(v["dep_volume"], 4),
            "wd_volume": round(v["wd_volume"], 4),
        })
    networks.sort(key=lambda x: x["total_tx"], reverse=True)

    # Flag high-risk networks (commonly used for laundering)
    _HIGH_RISK_NETS = {"TRX", "TRON", "TRC20", "BSC", "BEP20", "BEP2"}
    high_risk_nets = [n for n in networks if n["network"].upper() in _HIGH_RISK_NETS]

    network_analysis["networks"] = networks
    network_analysis["unique_networks"] = len(networks)
    network_analysis["high_risk_networks"] = high_risk_nets

    report["network_analysis"] = network_analysis

    # -----------------------------------------------------------------------
    # 21. Extended account security analysis
    # -----------------------------------------------------------------------
    ext_security: Dict[str, Any] = {}

    # Correlate login countries with withdrawal activity
    login_countries = set()
    al_data = access_analysis  # reuse from section 3
    if al_data.get("geolocations"):
        for geo in al_data["geolocations"]:
            parts = str(geo).split()
            if parts:
                login_countries.add(parts[0])

    # Check for new-device + immediate large withdrawal pattern
    ext_security["login_countries"] = sorted(login_countries)
    ext_security["login_country_count"] = len(login_countries)

    # VPN detection: multiple countries within same day
    vpn_suspects = []
    if "Access Logs" in sheets:
        try:
            al = pd.read_excel(xls, sheet_name="Access Logs")
            al["ts"] = pd.to_datetime(al["Timestamp (UTC)"], errors="coerce")
            al["date"] = al["ts"].dt.date
            al["country"] = al["Geolocation"].astype(str).str.split().str[0]

            for day, group in al.groupby("date"):
                countries = group["country"].nunique()
                if countries >= 3:
                    vpn_suspects.append({
                        "date": str(day),
                        "countries": sorted(group["country"].unique().tolist()),
                        "country_count": countries,
                        "login_count": len(group),
                    })
        except Exception:
            pass

    vpn_suspects.sort(key=lambda x: x["country_count"], reverse=True)
    ext_security["vpn_suspects"] = vpn_suspects[:20]
    ext_security["vpn_suspect_days"] = len(vpn_suspects)

    # API trading indicator
    api_trading = account_info.get("api_trading", "")
    ext_security["api_trading_enabled"] = bool(api_trading and api_trading.lower() not in ("", "no", "false", "0", "disabled"))

    # Sub-account indicator
    sub = account_info.get("sub_account", "")
    ext_security["has_sub_account"] = bool(sub and sub.lower() not in ("", "no", "false", "0", "none"))

    report["extended_security"] = ext_security

    return report
