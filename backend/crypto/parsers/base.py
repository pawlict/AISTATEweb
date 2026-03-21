"""Base data structures for crypto transaction analysis."""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Source-type classification
# ---------------------------------------------------------------------------

_SOURCE_TYPE_MAP: Dict[str, str] = {
    # Exchange / custodial account exports
    "binance": "exchange",
    "binance_trade": "exchange",
    "binance_pdf": "exchange",
    "binance_xlsx": "exchange",
    "coinbase": "exchange",
    "coinbase_pro": "exchange",
    "kraken": "exchange",
    "kraken_ledger": "exchange",
    "bybit": "exchange",
    "kucoin": "exchange",
    "ledger": "exchange",
    # Blockchain / on-chain explorer exports
    "etherscan": "blockchain",
    "etherscan_token": "blockchain",
    "etherscan_internal": "blockchain",
    "blockchair": "blockchain",
    "walletexplorer": "blockchain",
    "electrum": "blockchain",
    "metamask": "blockchain",
    "trezor": "blockchain",
}


def classify_source_type(source: str, txs: List["CryptoTransaction"]) -> str:
    """Determine source_type ('exchange' or 'blockchain') from format name.

    Falls back to a heuristic: if >50% of transactions have from/to address
    fields populated, treat as blockchain data.
    """
    mapped = _SOURCE_TYPE_MAP.get(source, "")
    if mapped:
        return mapped
    # Heuristic for unknown / generic sources
    if txs:
        has_addr = sum(1 for tx in txs if tx.from_address or tx.to_address)
        return "blockchain" if has_addr / len(txs) > 0.5 else "exchange"
    return "exchange"


@dataclass
class CryptoTransaction:
    """Single normalized crypto transaction."""

    tx_hash: str = ""
    timestamp: str = ""                 # ISO 8601
    from_address: str = ""
    to_address: str = ""
    amount: Decimal = Decimal("0")
    token: str = ""                     # BTC, ETH, USDT, etc.
    fee: Decimal = Decimal("0")
    fee_token: str = ""
    chain: str = ""                     # bitcoin, ethereum, polygon, bsc, etc.
    tx_type: str = "transfer"           # transfer, swap, contract_call, mint, burn, deposit, withdrawal
    status: str = "confirmed"           # confirmed, pending, failed
    block_number: Optional[int] = None
    contract_address: Optional[str] = None
    method_name: Optional[str] = None   # decoded contract method
    raw_input: Optional[str] = None     # calldata hex
    exchange: Optional[str] = None      # source exchange name
    counterparty: str = ""              # resolved label for the other party
    category: str = ""                  # classified category
    classification: str = ""            # neutral | legitimate | suspicious | monitoring
    classification_note: str = ""
    risk_score: float = 0.0
    risk_tags: List[str] = field(default_factory=list)
    raw: Dict[str, Any] = field(default_factory=dict)  # original row


@dataclass
class WalletInfo:
    """Aggregated info about a wallet address."""

    address: str = ""
    chain: str = ""
    label: Optional[str] = None         # known label (exchange, mixer, protocol)
    first_seen: Optional[str] = None
    last_seen: Optional[str] = None
    tx_count: int = 0
    total_received: Decimal = Decimal("0")
    total_sent: Decimal = Decimal("0")
    tokens: Dict[str, Decimal] = field(default_factory=dict)
    risk_level: str = "unknown"         # low, medium, high, critical
    risk_reasons: List[str] = field(default_factory=list)


@dataclass
class SmartContractInfo:
    """Info about a smart contract interaction."""

    address: str = ""
    chain: str = "ethereum"
    name: Optional[str] = None          # e.g. "Uniswap V3: Router"
    protocol: Optional[str] = None      # e.g. "uniswap", "aave"
    method_name: Optional[str] = None
    method_signature: Optional[str] = None  # e.g. "0x38ed1739"
    decoded_params: Dict[str, Any] = field(default_factory=dict)
    risk_level: str = "low"
    category: str = ""                  # defi, nft, bridge, mixer, unknown


@dataclass
class ParsedCryptoData:
    """Result of parsing a crypto file."""

    source: str = ""                    # "binance", "etherscan", "generic", etc.
    source_type: str = ""               # "exchange" or "blockchain"
    chain: str = ""                     # detected chain
    wallets: List[WalletInfo] = field(default_factory=list)
    transactions: List[CryptoTransaction] = field(default_factory=list)
    contracts: List[SmartContractInfo] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    raw_row_count: int = 0
