"""Parser for Revolut Digital Assets Europe Ltd crypto account statements (Polish PDF).

Handles the "Wyciąg z konta kryptowalutowego" PDF format containing:
- Portfolio positions (Zestawienie pozycji na koncie)
- Buy/sell/transfer transactions (Transakcje)
- Staking rewards (Nagrody za staking)

Provides dual output:
- ``parse_revolut_crypto_pdf(path)`` → ``ParsedCryptoData`` for the crypto pipeline
- ``parse_revolut_crypto_for_aml(path)`` → ``ParseResult`` for the AML pipeline
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .base import CryptoTransaction, ParsedCryptoData, WalletInfo, classify_source_type

log = logging.getLogger("aistate.crypto.revolut_crypto_pdf")

# ---------------------------------------------------------------------------
# Polish month abbreviations → month number
# ---------------------------------------------------------------------------

_PL_MONTHS: Dict[str, int] = {
    "sty": 1, "lut": 2, "mar": 3, "kwi": 4, "maj": 5, "cze": 6,
    "lip": 7, "sie": 8, "wrz": 9, "paź": 10, "paz": 10, "lis": 11, "gru": 12,
}

_RE_PL_DATETIME = re.compile(
    r"(\d{1,2})\s+"
    r"(sty|lut|mar|kwi|maj|cze|lip|sie|wrz|pa[źz]|lis|gru)\s+"
    r"(\d{4})"
    r"(?:,?\s*(\d{2}:\d{2}:\d{2}))?",
    re.IGNORECASE,
)

_RE_PERIOD = re.compile(
    r"(\d{1,2})\s+(sty|lut|mar|kwi|maj|cze|lip|sie|wrz|pa[źz]|lis|gru)\s+(\d{4})"
    r"\s*[-–]\s*"
    r"(\d{1,2})\s+(sty|lut|mar|kwi|maj|cze|lip|sie|wrz|pa[źz]|lis|gru)\s+(\d{4})",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Internal intermediate data
# ---------------------------------------------------------------------------

@dataclass
class _RawCryptoRow:
    """Single parsed row from the Revolut crypto PDF."""
    symbol: str = ""
    token_name: str = ""
    rodzaj: str = ""      # Kupno, Sprzedaż, Przelew wychodzący, Nagroda za staking, etc.
    ilosc: Decimal = field(default_factory=lambda: Decimal("0"))
    cena: Optional[Decimal] = None      # unit price (None for staking)
    wartosc: Optional[Decimal] = None   # fiat value (None for staking)
    oplaty: Decimal = field(default_factory=lambda: Decimal("0"))
    timestamp: str = ""   # ISO 8601
    date_str: str = ""    # YYYY-MM-DD
    currency: str = "PLN" # detected from value column
    section: str = "transactions"  # "transactions" or "staking"


@dataclass
class _PortfolioPosition:
    """Portfolio position from the summary table."""
    symbol: str = ""
    token_name: str = ""
    starting_value: Decimal = field(default_factory=lambda: Decimal("0"))
    withdrawals: Decimal = field(default_factory=lambda: Decimal("0"))
    deposits: Decimal = field(default_factory=lambda: Decimal("0"))
    ending_value: Decimal = field(default_factory=lambda: Decimal("0"))


@dataclass
class _ParsedMeta:
    """Metadata extracted from the PDF header."""
    account_holder: str = ""
    address: str = ""
    period_from: str = ""  # YYYY-MM-DD
    period_to: str = ""    # YYYY-MM-DD
    generated_date: str = ""
    entity: str = "Revolut Digital Assets Europe Ltd"


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

def is_revolut_crypto_pdf(path) -> bool:
    """Check whether *path* is a Revolut crypto account statement PDF.

    Accepts a ``Path`` or a list of text lines (already extracted).
    """
    if isinstance(path, (list, tuple)):
        lines = path
    else:
        lines = _extract_lines(Path(path))

    if not lines:
        return False

    head = "\n".join(lines[:40]).lower()
    has_revolut = "revolut" in head and ("digital assets" in head or "kryptowalut" in head)
    return has_revolut


# ---------------------------------------------------------------------------
# PDF text extraction
# ---------------------------------------------------------------------------

def _extract_lines(path: Path) -> List[str]:
    """Extract text lines from all PDF pages using PyMuPDF."""
    try:
        import fitz  # type: ignore[import-untyped]
    except ImportError:
        log.warning("PyMuPDF (fitz) not installed; cannot parse PDF")
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


# ---------------------------------------------------------------------------
# Value / amount helpers
# ---------------------------------------------------------------------------

def _parse_pl_datetime(text: str) -> Tuple[str, str]:
    """Parse Polish datetime like '20 cze 2020, 16:38:00'.

    Returns (ISO timestamp, YYYY-MM-DD date).
    """
    m = _RE_PL_DATETIME.search(text)
    if not m:
        return "", ""
    day = int(m.group(1))
    month = _PL_MONTHS.get(m.group(2).lower(), 0)
    year = int(m.group(3))
    time_part = m.group(4) or "00:00:00"
    if not month:
        return "", ""
    dt_str = f"{year}-{month:02d}-{day:02d}"
    iso = f"{dt_str}T{time_part}"
    return iso, dt_str


def _parse_amount_with_currency(text: str) -> Tuple[Decimal, str]:
    """Parse an amount string that may contain currency indicators.

    Handles:
    - "116,68 PLN", "1 000,00 PLN"
    - "40 119,47€", "29,64€"
    - "0,53$", "369,94$"
    - "0,00 PLN"

    Returns (amount, currency_code).
    """
    s = text.strip()
    currency = "PLN"

    # Detect currency from symbols/suffixes
    if "€" in s:
        currency = "EUR"
        s = s.replace("€", "")
    elif "$" in s:
        currency = "USD"
        s = s.replace("$", "")
    elif "£" in s:
        currency = "GBP"
        s = s.replace("£", "")
    elif s.upper().endswith("PLN"):
        currency = "PLN"
        s = s[:-3]
    elif s.upper().endswith("ZŁ") or s.upper().endswith("ZL"):
        currency = "PLN"
        s = re.sub(r"z[łl]$", "", s, flags=re.IGNORECASE)

    # Clean: remove thin/non-breaking spaces used as thousands separators
    s = s.replace("\xa0", " ").replace("\u202f", " ").strip()
    # Replace space-as-thousands-separator: "1 000,00" → "1000,00"
    s = re.sub(r"(\d)\s+(\d)", r"\1\2", s)
    # Polish decimal comma → dot
    s = s.replace(",", ".")

    try:
        return Decimal(s), currency
    except (InvalidOperation, ValueError):
        return Decimal("0"), currency


def _dec_simple(text: str) -> Decimal:
    """Parse a simple decimal number (no currency), Polish format."""
    s = text.strip().replace("\xa0", " ").replace("\u202f", " ")
    s = re.sub(r"(\d)\s+(\d)", r"\1\2", s)
    s = s.replace(",", ".")
    try:
        return Decimal(s)
    except (InvalidOperation, ValueError):
        return Decimal("0")


# ---------------------------------------------------------------------------
# Core parsing
# ---------------------------------------------------------------------------

def _extract_revolut_crypto_data(
    path: Path,
) -> Tuple[List[_RawCryptoRow], _ParsedMeta, List[_PortfolioPosition]]:
    """Parse the Revolut crypto PDF into intermediate representation.

    Returns (transactions, metadata, portfolio_positions).
    """
    lines = _extract_lines(path)
    if not lines:
        return [], _ParsedMeta(), []

    meta = _ParsedMeta()
    positions: List[_PortfolioPosition] = []
    transactions: List[_RawCryptoRow] = []

    # --- Extract metadata from header ---
    full_head = "\n".join(lines[:20])

    # Account holder: line after "Revolut Digital Assets Europe Ltd"
    for i, line in enumerate(lines[:15]):
        if "revolut digital assets" in line.lower():
            meta.entity = line
            # Next lines: holder name, address, city, postal, country
            if i + 1 < len(lines):
                meta.account_holder = lines[i + 1]
            if i + 2 < len(lines):
                meta.address = lines[i + 2]
            break

    # Period: "16 cze 2020 - 26 mar 2026"
    m = _RE_PERIOD.search(full_head)
    if m:
        d1, m1, y1 = int(m.group(1)), _PL_MONTHS.get(m.group(2).lower(), 1), int(m.group(3))
        d2, m2, y2 = int(m.group(4)), _PL_MONTHS.get(m.group(5).lower(), 1), int(m.group(6))
        meta.period_from = f"{y1}-{m1:02d}-{d1:02d}"
        meta.period_to = f"{y2}-{m2:02d}-{d2:02d}"

    # Generated date
    for line in lines[:5]:
        if "wygenerowano" in line.lower():
            ts, ds = _parse_pl_datetime(line)
            if ds:
                meta.generated_date = ds
            break

    # --- Identify sections by scanning lines ---
    section = "header"
    # Known tokens (uppercase, 2-5 chars) for detecting data rows
    _KNOWN_TOKENS = {
        "BTC", "ETH", "XRP", "ADA", "SHIB", "DOGE", "SOL", "DOT", "MATIC",
        "AVAX", "LINK", "UNI", "ATOM", "LTC", "BCH", "XLM", "FIL", "NEAR",
        "ALGO", "XTZ", "EOS", "AAVE", "MKR", "COMP", "SNX", "CRV", "BAT",
        "ZRX", "ENJ", "MANA", "SAND", "AXS", "FLR", "APE", "OP", "ARB",
        "PEPE", "BONK", "WIF", "FET", "RENDER", "INJ", "TIA", "SEI",
        "SUI", "APT", "STX", "IMX", "GALA", "LRC", "GRT", "1INCH",
    }

    _RODZAJ_TX = {"kupno", "sprzedaż", "sprzedaz", "przelew wychodzący", "przelew wychodzacy"}
    _RODZAJ_STAKING = {"nagroda za staking", "nagroda za ukończenie kursu", "nagroda za ukoncenie kursu"}

    i = 0
    while i < len(lines):
        line = lines[i]
        line_lower = line.lower().strip()

        # --- Section detection ---
        if "zestawienie pozycji na koncie" in line_lower:
            section = "portfolio_header"
            i += 1
            continue
        elif line_lower == "transakcje" or (
            section in ("portfolio", "portfolio_header", "portfolio_composition")
            and line_lower.startswith("transakcje")
            and "giełdowe" not in line_lower
        ):
            section = "tx_header"
            i += 1
            continue
        elif "nagrody za staking" in line_lower:
            section = "staking_header"
            i += 1
            continue
        elif "zestawienie składników portfela" in line_lower:
            section = "portfolio_composition"
            i += 1
            continue
        elif line_lower.startswith("uzyskaj pomoc") or line_lower.startswith("zeskanuj"):
            section = "footer"
            i += 1
            continue
        elif line_lower.startswith("strona") and "z" in line_lower:
            # Page number line — skip
            i += 1
            continue
        elif line_lower.startswith("©"):
            # Copyright line — skip
            i += 1
            continue

        # Skip repeated table headers on new pages
        if section in ("tx_data", "tx_header") and line_lower == "symbol":
            # This is a repeated header row — skip the full header block
            j = i
            while j < len(lines) and lines[j].strip().lower() in (
                "symbol", "rodzaj", "ilość", "ilosc", "cena", "wartość", "wartosc",
                "opłaty", "oplaty", "data",
            ):
                j += 1
            i = j
            section = "tx_data"
            continue

        if section in ("staking_data", "staking_header") and line_lower == "symbol":
            j = i
            while j < len(lines) and lines[j].strip().lower() in (
                "symbol", "rodzaj", "ilość", "ilosc", "data",
            ):
                j += 1
            i = j
            section = "staking_data"
            continue

        # --- Portfolio header → skip column header lines ---
        if section == "portfolio_header":
            if line_lower in ("symbol", "token", "wartość początkowa", "wypłaty",
                              "wpłaty", "wartość końcowa"):
                i += 1
                continue
            # Start reading portfolio data
            section = "portfolio"

        # --- Transaction header → skip column header lines ---
        if section == "tx_header":
            if line_lower in ("symbol", "rodzaj", "ilość", "ilosc", "cena",
                              "wartość", "wartosc", "opłaty", "oplaty", "data"):
                i += 1
                continue
            section = "tx_data"

        # --- Staking header → skip column header lines ---
        if section == "staking_header":
            if line_lower in ("symbol", "rodzaj", "ilość", "ilosc", "data"):
                i += 1
                continue
            section = "staking_data"

        # --- Parse portfolio positions ---
        if section == "portfolio":
            # End of portfolio: "Razem" line
            if line_lower.startswith("razem"):
                section = "portfolio_done"
                i += 1
                continue

            # A position starts with a known token symbol
            token_upper = line.strip().upper()
            if token_upper in _KNOWN_TOKENS:
                pos = _PortfolioPosition(symbol=token_upper)
                # Read the following lines for this position
                # Next line: token name (e.g., "Bitcoin")
                j = i + 1
                # Collect up to ~8 lines for this position's data
                pos_lines: List[str] = []
                while j < len(lines) and len(pos_lines) < 10:
                    next_line = lines[j].strip()
                    next_upper = next_line.upper()
                    # Stop if we hit another token or a section keyword
                    if next_upper in _KNOWN_TOKENS and len(pos_lines) >= 2:
                        break
                    if any(kw in next_line.lower() for kw in
                           ("razem", "zestawienie", "transakcje", "nagrody")):
                        break
                    pos_lines.append(next_line)
                    j += 1

                if pos_lines:
                    pos.token_name = pos_lines[0]
                positions.append(pos)
                i = j
                continue

            i += 1
            continue

        # --- Parse transaction rows ---
        if section == "tx_data":
            token_upper = line.strip().upper()
            if token_upper in _KNOWN_TOKENS:
                row = _RawCryptoRow(symbol=token_upper, section="transactions")
                j = i + 1
                # Next expected: Rodzaj, Ilość, Cena, Wartość, Opłaty, Data
                row_lines: List[str] = []
                while j < len(lines) and len(row_lines) < 8:
                    next_line = lines[j].strip()
                    next_upper = next_line.upper()
                    if next_upper in _KNOWN_TOKENS:
                        break
                    if any(kw in next_line.lower() for kw in
                           ("nagrody za staking", "zestawienie", "uzyskaj pomoc",
                            "strona ", "©")):
                        break
                    # Skip repeated header lines
                    if next_line.lower() in ("symbol", "rodzaj", "ilość", "cena",
                                             "wartość", "opłaty", "data"):
                        j += 1
                        continue
                    row_lines.append(next_line)
                    j += 1

                if row_lines:
                    _parse_tx_row_lines(row, row_lines)
                    if row.rodzaj:  # valid row
                        transactions.append(row)

                i = j
                continue

            i += 1
            continue

        # --- Parse staking rows ---
        if section == "staking_data":
            token_upper = line.strip().upper()
            if token_upper in _KNOWN_TOKENS:
                row = _RawCryptoRow(symbol=token_upper, section="staking")
                j = i + 1
                row_lines = []
                while j < len(lines) and len(row_lines) < 4:
                    next_line = lines[j].strip()
                    next_upper = next_line.upper()
                    if next_upper in _KNOWN_TOKENS:
                        break
                    if any(kw in next_line.lower() for kw in
                           ("uzyskaj pomoc", "strona ", "©", "zestawienie")):
                        break
                    if next_line.lower() in ("symbol", "rodzaj", "ilość", "data"):
                        j += 1
                        continue
                    row_lines.append(next_line)
                    j += 1

                if row_lines:
                    _parse_staking_row_lines(row, row_lines)
                    if row.rodzaj:
                        transactions.append(row)

                i = j
                continue

            i += 1
            continue

        # Default: skip line
        i += 1

    return transactions, meta, positions


def _parse_tx_row_lines(row: _RawCryptoRow, lines: List[str]) -> None:
    """Fill a transaction _RawCryptoRow from its sub-lines.

    Expected order: Rodzaj, Ilość, Cena, Wartość, Opłaty, Data
    """
    idx = 0

    # Rodzaj
    if idx < len(lines):
        rodzaj_lower = lines[idx].lower()
        if rodzaj_lower in ("kupno", "sprzedaż", "sprzedaz"):
            row.rodzaj = lines[idx]
            idx += 1
        elif rodzaj_lower.startswith("przelew wychodzący") or rodzaj_lower.startswith("przelew wychodzacy"):
            row.rodzaj = lines[idx]
            idx += 1
        else:
            # Might be a multi-word rodzaj — try to detect
            for known in ("kupno", "sprzedaż", "przelew wychodzący"):
                if known in rodzaj_lower:
                    row.rodzaj = lines[idx]
                    idx += 1
                    break
            else:
                return  # Can't identify rodzaj

    # Ilość
    if idx < len(lines):
        row.ilosc = _dec_simple(lines[idx])
        idx += 1

    # Cena (with currency)
    if idx < len(lines):
        val, cur = _parse_amount_with_currency(lines[idx])
        row.cena = val
        row.currency = cur
        idx += 1

    # Wartość (with currency)
    if idx < len(lines):
        val, cur = _parse_amount_with_currency(lines[idx])
        row.wartosc = val
        # If currency wasn't set from price, use from value
        if row.currency == "PLN" and cur != "PLN":
            row.currency = cur
        elif cur != "PLN":
            row.currency = cur
        idx += 1

    # Opłaty
    if idx < len(lines):
        val, _ = _parse_amount_with_currency(lines[idx])
        row.oplaty = val
        idx += 1

    # Data
    if idx < len(lines):
        ts, ds = _parse_pl_datetime(lines[idx])
        row.timestamp = ts
        row.date_str = ds


def _parse_staking_row_lines(row: _RawCryptoRow, lines: List[str]) -> None:
    """Fill a staking _RawCryptoRow from its sub-lines.

    Expected order: Rodzaj, Ilość, Data
    """
    idx = 0

    # Rodzaj
    if idx < len(lines):
        row.rodzaj = lines[idx]
        idx += 1

    # Ilość
    if idx < len(lines):
        row.ilosc = _dec_simple(lines[idx])
        idx += 1

    # Data
    if idx < len(lines):
        ts, ds = _parse_pl_datetime(lines[idx])
        row.timestamp = ts
        row.date_str = ds


# ---------------------------------------------------------------------------
# Crypto pipeline adapter
# ---------------------------------------------------------------------------

_RODZAJ_TO_TX_TYPE: Dict[str, str] = {
    "kupno": "buy",
    "sprzedaż": "sell",
    "sprzedaz": "sell",
    "przelew wychodzący": "withdrawal",
    "przelew wychodzacy": "withdrawal",
    "nagroda za staking": "staking_reward",
    "nagroda za ukończenie kursu": "learn_reward",
    "nagroda za ukoncenie kursu": "learn_reward",
}


def parse_revolut_crypto_pdf(path: Path) -> ParsedCryptoData:
    """Parse a Revolut crypto PDF into ``ParsedCryptoData`` for the crypto pipeline."""
    path = Path(path)
    transactions, meta, positions = _extract_revolut_crypto_data(path)

    result = ParsedCryptoData(
        source="revolut_crypto",
        source_type="exchange",
        chain="",
    )

    crypto_txs: List[CryptoTransaction] = []
    for row in transactions:
        rodzaj_key = row.rodzaj.lower().strip()
        tx_type = _RODZAJ_TO_TX_TYPE.get(rodzaj_key, "unknown")

        tx = CryptoTransaction(
            timestamp=row.timestamp,
            amount=row.ilosc,
            token=row.symbol,
            fee=row.oplaty,
            fee_token=row.currency,
            tx_type=tx_type,
            exchange="revolut",
            counterparty="Revolut Digital Assets Europe Ltd",
            raw={
                "symbol": row.symbol,
                "rodzaj": row.rodzaj,
                "ilosc": str(row.ilosc),
                "cena": str(row.cena) if row.cena is not None else None,
                "wartosc": str(row.wartosc) if row.wartosc is not None else None,
                "oplaty": str(row.oplaty),
                "currency": row.currency,
                "date": row.date_str,
                "section": row.section,
            },
        )

        # For buy/sell, the fiat value is the "cost"
        if row.wartosc is not None and row.wartosc != 0:
            tx.raw["fiat_value"] = str(row.wartosc)
            tx.raw["fiat_currency"] = row.currency

        crypto_txs.append(tx)

    result.transactions = crypto_txs
    result.raw_row_count = len(crypto_txs)

    # Build wallet info from portfolio positions
    wallets: List[WalletInfo] = []
    for pos in positions:
        w = WalletInfo(
            address=f"revolut:{pos.symbol.lower()}",
            chain="revolut",
            label=f"Revolut {pos.symbol}",
            tokens={pos.symbol: pos.ending_value},
        )
        wallets.append(w)

    # Also build wallet info from transactions
    token_stats: Dict[str, Dict[str, Any]] = {}
    for tx in crypto_txs:
        stats = token_stats.setdefault(tx.token, {
            "first_seen": tx.timestamp,
            "last_seen": tx.timestamp,
            "tx_count": 0,
            "total_received": Decimal("0"),
            "total_sent": Decimal("0"),
        })
        stats["tx_count"] += 1
        if tx.timestamp:
            if not stats["first_seen"] or tx.timestamp < stats["first_seen"]:
                stats["first_seen"] = tx.timestamp
            if not stats["last_seen"] or tx.timestamp > stats["last_seen"]:
                stats["last_seen"] = tx.timestamp
        if tx.tx_type in ("buy", "staking_reward", "learn_reward"):
            stats["total_received"] += tx.amount
        elif tx.tx_type in ("sell", "withdrawal"):
            stats["total_sent"] += tx.amount

    for token, stats in token_stats.items():
        # Check if already in wallets from portfolio
        existing = [w for w in wallets if w.address == f"revolut:{token.lower()}"]
        if existing:
            w = existing[0]
            w.first_seen = stats["first_seen"]
            w.last_seen = stats["last_seen"]
            w.tx_count = stats["tx_count"]
            w.total_received = stats["total_received"]
            w.total_sent = stats["total_sent"]
        else:
            wallets.append(WalletInfo(
                address=f"revolut:{token.lower()}",
                chain="revolut",
                label=f"Revolut {token}",
                first_seen=stats["first_seen"],
                last_seen=stats["last_seen"],
                tx_count=stats["tx_count"],
                total_received=stats["total_received"],
                total_sent=stats["total_sent"],
                tokens={token: Decimal("0")},
            ))

    result.wallets = wallets

    log.info(
        "Parsed Revolut crypto PDF: %d transactions, %d wallets (%s)",
        len(crypto_txs), len(wallets), path.name,
    )
    return result


# ---------------------------------------------------------------------------
# AML pipeline adapter
# ---------------------------------------------------------------------------

def parse_revolut_crypto_for_aml(path: Path):
    """Parse a Revolut crypto PDF into a ``ParseResult`` for the AML pipeline.

    Converts crypto transactions into fiat-equivalent RawTransactions so
    the AML pipeline can analyse money flows (PLN/EUR/USD in → crypto → out).
    """
    from backend.finance.parsers.base import ParseResult, RawTransaction, StatementInfo

    path = Path(path)
    transactions, meta, positions = _extract_revolut_crypto_data(path)

    info = StatementInfo(
        bank="Revolut Crypto",
        account_holder=meta.account_holder,
        period_from=meta.period_from,
        period_to=meta.period_to,
        currency="PLN",
    )

    raw_txs: List[RawTransaction] = []
    for row in transactions:
        rodzaj_lower = row.rodzaj.lower().strip()

        # Determine direction and amount sign
        if rodzaj_lower == "kupno":
            # Buying crypto = spending fiat → negative
            amount = -float(row.wartosc) if row.wartosc else 0.0
            title = f"Kupno {row.symbol} {row.ilosc}"
            bank_cat = "CRYPTO_BUY"
        elif rodzaj_lower in ("sprzedaż", "sprzedaz"):
            # Selling crypto = receiving fiat → positive
            amount = float(row.wartosc) if row.wartosc else 0.0
            title = f"Sprzedaż {row.symbol} {row.ilosc}"
            bank_cat = "CRYPTO_SELL"
        elif rodzaj_lower.startswith("przelew wychodzący") or rodzaj_lower.startswith("przelew wychodzacy"):
            # Crypto leaving Revolut = value leaving → negative
            amount = -float(row.wartosc) if row.wartosc else 0.0
            title = f"Przelew wychodzący {row.symbol} {row.ilosc}"
            bank_cat = "CRYPTO_TRANSFER_OUT"
        elif "staking" in rodzaj_lower:
            # Staking reward = income (but no fiat value in PDF, skip or use 0)
            amount = 0.0
            title = f"Nagroda za staking {row.symbol} {row.ilosc}"
            bank_cat = "CRYPTO_STAKING"
        elif "ukończenie kursu" in rodzaj_lower or "ukoncenie kursu" in rodzaj_lower:
            amount = 0.0
            title = f"Nagroda za kurs {row.symbol} {row.ilosc}"
            bank_cat = "CRYPTO_LEARN_REWARD"
        else:
            amount = 0.0
            title = f"{row.rodzaj} {row.symbol} {row.ilosc}"
            bank_cat = "CRYPTO_OTHER"

        # Include fee in the title if non-zero
        fee_note = ""
        if row.oplaty and row.oplaty > 0:
            fee_note = f" (opłata: {row.oplaty} {row.currency})"

        raw_txs.append(RawTransaction(
            date=row.date_str,
            amount=amount,
            currency=row.currency,
            counterparty="Revolut Crypto",
            title=title + fee_note,
            raw_text=f"{row.rodzaj} {row.symbol} qty={row.ilosc} price={row.cena} val={row.wartosc} fee={row.oplaty}",
            bank_category=bank_cat,
        ))

    result = ParseResult(
        bank="Revolut Crypto",
        info=info,
        transactions=raw_txs,
        parse_method="text",
    )

    log.info(
        "Parsed Revolut crypto PDF for AML: %d transactions (%s)",
        len(raw_txs), path.name,
    )
    return result
