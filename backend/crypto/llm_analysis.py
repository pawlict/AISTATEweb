"""LLM prompt builder for crypto transaction analysis.

Produces different prompt structures depending on ``source_type``:
  - ``"exchange"`` – focuses on fiat flow, token portfolio, operations review
  - ``"blockchain"`` – focuses on addresses, counterparties, mixer/sanctioned checks
"""
from __future__ import annotations

import logging
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional

from .parsers.base import CryptoTransaction, WalletInfo

log = logging.getLogger("aistate.crypto.llm")

_FIAT = {"PLN", "USD", "EUR", "GBP", "CHF", "CZK", "TRY", "BRL", "AUD", "CAD", "JPY", "KRW"}


def build_crypto_prompt(
    txs: List[CryptoTransaction],
    wallets: List[WalletInfo],
    alerts: List[Dict[str, Any]],
    risk_score: float = 0,
    risk_reasons: Optional[List[str]] = None,
    source: str = "",
    chain: str = "",
    user_prompt: str = "",
    source_type: str = "blockchain",
    metadata: Optional[Dict[str, Any]] = None,
    token_classification: Optional[Dict[str, Dict[str, Any]]] = None,
) -> str:
    """Build a structured prompt for LLM analysis of crypto transactions."""
    if source_type == "exchange":
        return _build_exchange_prompt(
            txs, alerts, risk_score, risk_reasons, source, user_prompt,
            metadata=metadata,
            token_classification=token_classification,
        )
    return _build_blockchain_prompt(
        txs, wallets, alerts, risk_score, risk_reasons, source, chain, user_prompt,
    )


# ── exchange prompt ───────────────────────────────────────────────────────

def _build_exchange_prompt(
    txs: List[CryptoTransaction],
    alerts: List[Dict[str, Any]],
    risk_score: float,
    risk_reasons: Optional[List[str]],
    source: str,
    user_prompt: str,
    metadata: Optional[Dict[str, Any]] = None,
    token_classification: Optional[Dict[str, Dict[str, Any]]] = None,
) -> str:
    lines: List[str] = []

    lines.append("Jesteś ekspertem ds. analizy transakcji giełd kryptowalutowych oraz przeciwdziałania praniu pieniędzy (AML).")
    lines.append("Przeanalizuj poniższy wyciąg z giełdy kryptowalutowej i sporządź raport w języku polskim.")
    lines.append("")

    if user_prompt:
        lines.append("## Polecenie użytkownika")
        lines.append(user_prompt)
        lines.append("")

    # Source info
    exchange_name = source.replace("_pdf", "").replace("_trade", "").title()
    lines.append("## Źródło danych")
    lines.append(f"- Giełda: {exchange_name}")
    lines.append(f"- Liczba transakcji: {len(txs)}")

    dates = [tx.timestamp for tx in txs if tx.timestamp]
    if dates:
        lines.append(f"- Okres: {min(dates)[:10]} — {max(dates)[:10]}")
    lines.append("")

    # Account holder info (from parser metadata)
    meta = metadata or {}
    holder = meta.get("account_holder")
    if holder:
        lines.append("## Dane właściciela konta")
        lines.append(f"- Imię i nazwisko: {holder}")
        if meta.get("street"):
            lines.append(f"- Ulica: {meta['street']}")
        if meta.get("city"):
            lines.append(f"- Miejscowość: {meta['city']}")
        if meta.get("postal_code"):
            lines.append(f"- Kod pocztowy: {meta['postal_code']}")
        if meta.get("country"):
            lines.append(f"- Kraj: {meta['country']}")
        lines.append("")

    # Token portfolio
    token_stats: Dict[str, Dict[str, Any]] = {}
    for tx in txs:
        t = tx.token or "UNKNOWN"
        if t not in token_stats:
            token_stats[t] = {"in": 0.0, "out": 0.0, "count": 0}
        token_stats[t]["count"] += 1
        raw_change = tx.raw.get("change", "")
        if raw_change and str(raw_change).lstrip().startswith("-"):
            token_stats[t]["out"] += float(tx.amount)
        else:
            token_stats[t]["in"] += float(tx.amount)

    lines.append("## Portfel tokenów")
    lines.append("| Token | Wpływy | Wypływy | Saldo netto | Liczba tx |")
    lines.append("|---|---|---|---|---|")
    for tok in sorted(token_stats.keys()):
        s = token_stats[tok]
        net = s["in"] - s["out"]
        lines.append(f"| {tok} | {s['in']:.4f} | {s['out']:.4f} | {net:+.4f} | {s['count']} |")
    lines.append("")

    # Token classification (known vs unknown from database)
    tc = token_classification or {}
    if tc:
        # Compute per-token fiat volume and tx count
        per_token_fiat: Dict[str, float] = defaultdict(float)
        per_token_count: Dict[str, int] = defaultdict(int)
        for tx in txs:
            sym = (tx.token or "").upper()
            if not sym:
                continue
            per_token_count[sym] += 1
            fv_str = tx.raw.get("fiat_value") or tx.raw.get("wartosc")
            if fv_str:
                try:
                    per_token_fiat[sym] += abs(float(fv_str))
                except (ValueError, TypeError):
                    pass

        unknown = {sym: info for sym, info in tc.items() if not info.get("known")}
        known_flagged = {sym: info for sym, info in tc.items()
                         if info.get("known") and info.get("alert_level") in ("HIGH", "MEDIUM")}

        if unknown:
            lines.append("## Nowe / nieznane tokeny (spoza bazy TOP 200)")
            lines.append("| Token | Nazwa | Liczba tx | Wolumen (szt.) | Wartość fiat |")
            lines.append("|---|---|---|---|---|")
            for sym, info in sorted(unknown.items()):
                cnt = per_token_count.get(sym, 0)
                vol = token_stats.get(sym, {}).get("in", 0) + token_stats.get(sym, {}).get("out", 0)
                fiat = per_token_fiat.get(sym, 0)
                fiat_str = f"{fiat:,.2f} PLN" if fiat else "—"
                lines.append(f"| {sym} | {info['name']} | {cnt} | {vol:.4f} | {fiat_str} |")
            lines.append("")

        lines.append("## Klasyfikacja tokenów z bazy")
        lines.append("| Token | Nazwa | Rank | Kategoria | Alert | Liczba tx | Wartość fiat |")
        lines.append("|---|---|---|---|---|---|---|")
        for sym in sorted(tc.keys()):
            info = tc[sym]
            cnt = per_token_count.get(sym, 0)
            fiat = per_token_fiat.get(sym, 0)
            fiat_str = f"{fiat:,.2f} PLN" if fiat else "—"
            rank = info.get("rank", 0)
            rank_str = f"#{rank}" if rank and rank < 999 else "—"
            status = "ZNANY" if info.get("known") else "NOWY"
            lines.append(
                f"| {sym} | {info['name']} | {rank_str} | "
                f"{info.get('category', '—')} | {info.get('alert_level', '—')} | "
                f"{cnt} | {fiat_str} |"
            )
        lines.append("")

    # Fiat summary
    fiat_in = sum(s["in"] for t, s in token_stats.items() if t in _FIAT)
    fiat_out = sum(s["out"] for t, s in token_stats.items() if t in _FIAT)
    if fiat_in or fiat_out:
        lines.append("## Przepływy fiatowe (on/off-ramp)")
        lines.append(f"- Łącznie wpłacono fiat: {fiat_in:.2f}")
        lines.append(f"- Łącznie wypłacono fiat: {fiat_out:.2f}")
        lines.append(f"- Saldo fiat: {fiat_in - fiat_out:+.2f}")
        lines.append("")

    # Operation types
    op_counts: Dict[str, int] = Counter()
    for tx in txs:
        op = tx.category or tx.raw.get("operation", "") or tx.tx_type
        op_counts[op] += 1

    lines.append("## Klasyfikacja operacji")
    for op, cnt in op_counts.most_common(15):
        lines.append(f"- {op}: {cnt}")
    lines.append("")

    # Account types
    accounts = {tx.raw.get("account", "") for tx in txs if tx.raw.get("account")}
    if accounts:
        lines.append(f"## Konta: {', '.join(sorted(accounts))}")
        lines.append("")

    # Fiat flow summary (from parser-provided fiat values)
    _buy_fiat_total = 0.0
    _sell_fiat_total = 0.0
    _transfer_fiat_total = 0.0
    for tx in txs:
        fv_str = tx.raw.get("fiat_value") or tx.raw.get("wartosc")
        if not fv_str:
            continue
        try:
            fv = abs(float(fv_str))
        except (ValueError, TypeError):
            continue
        tt = tx.tx_type.lower()
        if tt == "buy":
            _buy_fiat_total += fv
        elif tt == "sell":
            _sell_fiat_total += fv
        elif tt == "withdrawal":
            _transfer_fiat_total += fv

    if _buy_fiat_total or _sell_fiat_total or _transfer_fiat_total:
        net = _sell_fiat_total - _buy_fiat_total - _transfer_fiat_total
        lines.append("## Podsumowanie przepływów fiatowych")
        lines.append(f"- Kupno krypto za fiat: {_buy_fiat_total:,.2f} PLN")
        lines.append(f"- Sprzedaż krypto na fiat: {_sell_fiat_total:,.2f} PLN")
        lines.append(f"- Transfery na zewnątrz (wartość fiat): {_transfer_fiat_total:,.2f} PLN")
        lines.append(f"- **Bilans netto: {net:+,.2f} PLN**")
        lines.append("")

    # Deposits / Buys (fiat entering crypto)
    deposits = [tx for tx in txs if tx.tx_type in ("buy", "deposit")]
    if deposits:
        lines.append("## Wpłaty / Zakupy krypto")
        lines.append("| Data | Token | Ilość | Wartość fiat | Opłata |")
        lines.append("|---|---|---|---|---|")
        for tx in deposits[:30]:
            fv = tx.raw.get("fiat_value", tx.raw.get("wartosc", "?"))
            fc = tx.raw.get("fiat_currency", tx.raw.get("currency", ""))
            fee = tx.raw.get("oplaty", "0")
            lines.append(f"| {tx.timestamp[:10]} | {tx.token} | {float(tx.amount):.6f} | {fv} {fc} | {fee} |")
        if len(deposits) > 30:
            lines.append(f"  ... i {len(deposits) - 30} więcej")
        lines.append("")

    # Withdrawals (crypto leaving exchange)
    withdrawals = [tx for tx in txs if tx.tx_type == "withdrawal"]
    if withdrawals:
        lines.append("## Wypłaty krypto z giełdy")
        lines.append("| Data | Token | Kwota | Wartość fiat | Uwagi |")
        lines.append("|---|---|---|---|---|")
        for tx in withdrawals[:30]:
            fv = tx.raw.get("fiat_value", tx.raw.get("wartosc", "?"))
            fc = tx.raw.get("fiat_currency", tx.raw.get("currency", ""))
            notes = tx.raw.get("notes", "")
            lines.append(f"| {tx.timestamp[:10]} | {tx.token} | {float(tx.amount):.8f} | {fv} {fc} | {notes} |")
        if len(withdrawals) > 30:
            lines.append(f"  ... i {len(withdrawals) - 30} więcej")
        lines.append("")

    # Risk
    lines.append("## Ocena ryzyka")
    lines.append(f"- Wynik ryzyka: {risk_score:.1f}/100")
    if risk_reasons:
        for r in risk_reasons:
            lines.append(f"  - {r}")
    lines.append("")

    # Alerts
    if alerts:
        lines.append("## Wykryte wzorce")
        for a in alerts:
            lines.append(f"- **{a.get('pattern', '?')}**: {a.get('description', '')}")
        lines.append("")

    # Instructions
    lines.append("## Instrukcje dla analizy")
    lines.append("1. Podsumuj profil klienta giełdy (aktywność, wolumen, okres, tokeny)")
    lines.append("2. Przeanalizuj przepływy fiatowe (wpłaty/wypłaty) — czy wskazują na pranie pieniędzy?")
    lines.append("3. Oceń wzorce konwersji fiat→krypto→wypłata (szybka konwersja, strukturyzowanie)")
    lines.append("4. Sklasyfikuj każdy typ operacji (neutralna / do monitorowania / podejrzana)")
    lines.append("5. Zwróć uwagę na wypłaty krypto — dokąd trafiają środki?")
    lines.append("6. Oceń portfel tokenów — obecność privacy coins, meme coins, wysokospeculacyjnych aktywów")
    lines.append("7. Sformułuj rekomendacje dla analityka")

    return "\n".join(lines)


# ── blockchain prompt ─────────────────────────────────────────────────────

def _build_blockchain_prompt(
    txs: List[CryptoTransaction],
    wallets: List[WalletInfo],
    alerts: List[Dict[str, Any]],
    risk_score: float,
    risk_reasons: Optional[List[str]],
    source: str,
    chain: str,
    user_prompt: str,
) -> str:
    lines: List[str] = []

    lines.append("Jesteś ekspertem ds. analizy transakcji kryptowalutowych, blockchain forensics i przeciwdziałania praniu pieniędzy (AML).")
    lines.append("Przeanalizuj poniższe dane i sporządź raport w języku polskim.")
    lines.append("")

    if user_prompt:
        lines.append("## Polecenie użytkownika")
        lines.append(user_prompt)
        lines.append("")

    # Data source
    lines.append("## Źródło danych")
    lines.append(f"- Format: {source}")
    lines.append(f"- Blockchain: {chain}")
    lines.append(f"- Liczba transakcji: {len(txs)}")
    lines.append("")

    dates = [tx.timestamp for tx in txs if tx.timestamp]
    if dates:
        lines.append(f"- Okres: {min(dates)[:10]} — {max(dates)[:10]}")

    total_in = sum(float(tx.amount) for tx in txs if tx.tx_type == "deposit")
    total_out = sum(float(tx.amount) for tx in txs if tx.tx_type == "withdrawal")
    token = txs[0].token if txs else "BTC"
    lines.append(f"- Suma wpłat: {total_in:.8f} {token}")
    lines.append(f"- Suma wypłat: {total_out:.8f} {token}")
    lines.append("")

    lines.append("## Ocena ryzyka")
    lines.append(f"- Wynik ryzyka: {risk_score:.1f}/100")
    if risk_reasons:
        for r in risk_reasons:
            lines.append(f"  - {r}")
    lines.append("")

    if alerts:
        lines.append("## Wykryte wzorce podejrzane")
        for a in alerts:
            lines.append(f"- **{a.get('pattern', '?')}**: {a.get('description', '')}")
        lines.append("")

    # Top counterparties
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
            for tx in txs:
                if (tx.from_address == cp or tx.to_address == cp) and tx.risk_tags:
                    label += f" ⚠ [{', '.join(tx.risk_tags)}]"
                    break
            lines.append(f"| {label} | {vol:.8f} {token} | {cp_counts[cp]} |")
        lines.append("")

    mixer_txs = [tx for tx in txs if "mixer" in tx.risk_tags or "coinjoin" in tx.risk_tags]
    if mixer_txs:
        lines.append("## Transakcje z mikserami / CoinJoin")
        lines.append(f"Liczba: {len(mixer_txs)}")
        for tx in mixer_txs[:10]:
            lines.append(f"- {tx.timestamp[:10]} | {tx.counterparty or tx.from_address} → {float(tx.amount):.8f} {token} | TX: {tx.tx_hash[:16]}...")
        if len(mixer_txs) > 10:
            lines.append(f"  ... i {len(mixer_txs) - 10} więcej")
        lines.append("")

    lines.append("## Instrukcje dla analizy")
    lines.append("1. Podsumuj profil portfela (aktywność, wolumen, okres)")
    lines.append("2. Oceń ryzyko prania pieniędzy (AML)")
    lines.append("3. Wskaż podejrzane wzorce transakcji")
    lines.append("4. Zidentyfikuj powiązania z mikserami, CoinJoin, adresami sankcionowanymi")
    lines.append("5. Opisz głównych kontrahentów i charakter powiązań")
    lines.append("6. Sformułuj rekomendacje dla analityka")

    return "\n".join(lines)
