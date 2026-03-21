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


# ---------------------------------------------------------------------------
# Sheet parsers
# ---------------------------------------------------------------------------

def _parse_customer_info(df) -> Dict[str, Any]:
    """Extract account metadata from Customer Information sheet."""
    meta: Dict[str, Any] = {}
    # The sheet has a complex layout: first row is a header string,
    # actual data starts around row 3-4 with specific column positions.
    # Header string often contains: "User Basic Information(id: XXXXX ...)"
    first_col = str(df.columns[0]) if len(df.columns) > 0 else ""
    m = re.search(r"id:\s*(\d+)", first_col)
    if m:
        meta["user_id"] = m.group(1)
    m = re.search(r"email:\s*(\S+)", first_col)
    if m:
        meta["email"] = m.group(1)

    # Search rows for user ID, email, name
    for _, row in df.iterrows():
        vals = [_safe_str(v) for v in row.values]
        if "User ID" in vals:
            idx = vals.index("User ID")
            # Next row typically has the values
            continue
        # Look for numeric user ID in first column
        if vals[0] and re.match(r"^\d{6,}$", vals[0]):
            meta.setdefault("user_id", vals[0])
            if len(vals) > 1 and "@" in str(vals[1]):
                meta["email"] = vals[1]
            if len(vals) > 4 and vals[4]:
                meta["holder_name"] = vals[4]

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
        dep_addr = _safe_str(row.get("Deposit Address", ""))
        src_addr = _safe_str(row.get("Source Address", ""))
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
        dest_addr = _safe_str(row.get("Destination Address ", "") or row.get("Destination Address", ""))
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
    """Build wallet info from transaction addresses."""
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
