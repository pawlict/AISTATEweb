"""LLM prompt builder for crypto transaction analysis."""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from .parsers.base import CryptoTransaction, WalletInfo

log = logging.getLogger("aistate.crypto.llm")


def build_crypto_prompt(
    txs: List[CryptoTransaction],
    wallets: List[WalletInfo],
    alerts: List[Dict[str, Any]],
    risk_score: float = 0,
    risk_reasons: Optional[List[str]] = None,
    source: str = "",
    chain: str = "",
    user_prompt: str = "",
) -> str:
    """Build a structured prompt for LLM analysis of crypto transactions."""
    lines: List[str] = []

    # System context
    lines.append("Jesteś ekspertem ds. analizy transakcji kryptowalutowych, blockchain forensics i przeciwdziałania praniu pieniędzy (AML).")
    lines.append("Przeanalizuj poniższe dane i sporządź raport w języku polskim.")
    lines.append("")

    # User prompt
    if user_prompt:
        lines.append(f"## Polecenie użytkownika")
        lines.append(user_prompt)
        lines.append("")

    # Data source
    lines.append("## Źródło danych")
    lines.append(f"- Format: {source}")
    lines.append(f"- Blockchain: {chain}")
    lines.append(f"- Liczba transakcji: {len(txs)}")
    lines.append("")

    # Date range
    dates = [tx.timestamp for tx in txs if tx.timestamp]
    if dates:
        lines.append(f"- Okres: {min(dates)[:10]} — {max(dates)[:10]}")

    # Total volumes
    total_in = sum(float(tx.amount) for tx in txs if tx.tx_type == "deposit")
    total_out = sum(float(tx.amount) for tx in txs if tx.tx_type == "withdrawal")
    token = txs[0].token if txs else "BTC"
    lines.append(f"- Suma wpłat: {total_in:.8f} {token}")
    lines.append(f"- Suma wypłat: {total_out:.8f} {token}")
    lines.append("")

    # Risk assessment
    lines.append("## Ocena ryzyka")
    lines.append(f"- Wynik ryzyka: {risk_score:.1f}/100")
    if risk_reasons:
        for r in risk_reasons:
            lines.append(f"  - {r}")
    lines.append("")

    # Alerts
    if alerts:
        lines.append("## Wykryte wzorce podejrzane")
        for a in alerts:
            lines.append(f"- **{a.get('pattern', '?')}**: {a.get('description', '')}")
        lines.append("")

    # Top counterparties
    from collections import Counter
    cp_volumes: Dict[str, float] = {}
    cp_counts: Dict[str, int] = Counter()
    for tx in txs:
        cp = tx.counterparty or tx.from_address or tx.to_address
        if cp:
            cp_volumes[cp] = cp_volumes.get(cp, 0) + float(tx.amount)
            cp_counts[cp] += 1

    top = sorted(cp_volumes.items(), key=lambda x: -x[1])[:15]
    if top:
        lines.append("## Najważniejsi kontrahenci (top 15 wg wolumenu)")
        lines.append("| Kontrahent | Wolumen | Liczba tx |")
        lines.append("|---|---|---|")
        for cp, vol in top:
            label = cp
            # Mark suspicious ones
            for tx in txs:
                if (tx.from_address == cp or tx.to_address == cp) and tx.risk_tags:
                    label += f" ⚠ [{', '.join(tx.risk_tags)}]"
                    break
            lines.append(f"| {label} | {vol:.8f} {token} | {cp_counts[cp]} |")
        lines.append("")

    # Mixer/CoinJoin usage
    mixer_txs = [tx for tx in txs if "mixer" in tx.risk_tags or "coinjoin" in tx.risk_tags]
    if mixer_txs:
        lines.append("## Transakcje z mikserami / CoinJoin")
        lines.append(f"Liczba: {len(mixer_txs)}")
        for tx in mixer_txs[:10]:
            lines.append(f"- {tx.timestamp[:10]} | {tx.counterparty or tx.from_address} → {float(tx.amount):.8f} {token} | TX: {tx.tx_hash[:16]}...")
        if len(mixer_txs) > 10:
            lines.append(f"  ... i {len(mixer_txs) - 10} więcej")
        lines.append("")

    # Instructions
    lines.append("## Instrukcje dla analizy")
    lines.append("1. Podsumuj profil portfela (aktywność, wolumen, okres)")
    lines.append("2. Oceń ryzyko prania pieniędzy (AML)")
    lines.append("3. Wskaż podejrzane wzorce transakcji")
    lines.append("4. Zidentyfikuj powiązania z mikserami, CoinJoin, adresami sankcionowanymi")
    lines.append("5. Opisz głównych kontrahentów i charakter powiązań")
    lines.append("6. Sformułuj rekomendacje dla analityka")

    return "\n".join(lines)
