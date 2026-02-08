"""LLM-based fallback classifier for ambiguous transactions.

Uses a local LLM (via Ollama) to classify transactions that the
rule-based classifier couldn't categorize. Called only for
unclassified transactions to minimize LLM calls.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from .classifier import ClassifiedTransaction

log = logging.getLogger("aistate.finance.llm")

# Compact prompt for batch classification
_CLASSIFY_PROMPT = """Sklasyfikuj poniższe transakcje bankowe do kategorii. Odpowiedz TYLKO w formacie JSON.

Kategorie:
- crypto (kryptowaluty, giełdy, portfele)
- gambling (hazard, bukmacher, kasyno, loterie)
- loans (pożyczki, kredyty, raty, windykacja)
- transfers:salary (wynagrodzenie, pensja)
- transfers:rent (czynsz, najem)
- transfers:utilities (media: prąd, gaz, woda, internet)
- transfers:insurance (ubezpieczenia)
- risky (podejrzane, lombard, skup złota)
- unknown (nie da się określić)

Transakcje:
{transactions}

Odpowiedz jako JSON array, po jednym obiekcie na transakcję:
[{{"idx": 0, "category": "...", "confidence": 0.8, "reason": "krótkie uzasadnienie"}}]
Tylko JSON, bez dodatkowego tekstu."""


def build_classify_batch(
    unclassified: List[Tuple[int, ClassifiedTransaction]],
    max_items: int = 30,
) -> str:
    """Build a batch classification prompt for unclassified transactions."""
    items = []
    for idx, (orig_idx, ct) in enumerate(unclassified[:max_items]):
        txn = ct.transaction
        desc = f"{txn.counterparty} | {txn.title}" if txn.counterparty else txn.title
        items.append(f"[{idx}] {txn.date} | {txn.amount:+.2f} PLN | {desc}")

    return _CLASSIFY_PROMPT.format(transactions="\n".join(items))


def parse_llm_response(response_text: str) -> List[Dict[str, Any]]:
    """Parse LLM JSON response, handling common formatting issues."""
    text = response_text.strip()

    # Try to extract JSON array from response
    # LLMs sometimes wrap in markdown code blocks
    m = re.search(r"\[[\s\S]*\]", text)
    if m:
        text = m.group(0)

    try:
        result = json.loads(text)
        if isinstance(result, list):
            return result
    except json.JSONDecodeError:
        pass

    # Try line-by-line JSON objects
    results = []
    for line in text.split("\n"):
        line = line.strip().rstrip(",")
        if line.startswith("{") and line.endswith("}"):
            try:
                results.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return results


async def classify_with_llm(
    classified: List[ClassifiedTransaction],
    ollama_client,
    model: str = "mistral:7b-instruct",
    max_batch: int = 30,
    log_cb=None,
) -> int:
    """Classify untagged transactions using LLM.

    Modifies classified list in-place, adding categories to unclassified items.

    Args:
        classified: List of ClassifiedTransaction (modified in-place)
        ollama_client: OllamaClient instance
        model: Model to use for classification
        max_batch: Max transactions per LLM call
        log_cb: Optional logging callback

    Returns:
        Number of transactions classified by LLM.
    """
    def _log(msg: str):
        log.info(msg)
        if log_cb:
            try:
                log_cb(msg)
            except Exception:
                pass

    # Find unclassified transactions
    unclassified: List[Tuple[int, ClassifiedTransaction]] = []
    for i, ct in enumerate(classified):
        if not ct.categories and ct.transaction.direction == "out":
            # Only classify outflows that aren't tagged
            unclassified.append((i, ct))

    if not unclassified:
        _log("LLM fallback: brak niesklasyfikowanych transakcji")
        return 0

    if len(unclassified) > max_batch:
        # Sort by amount (largest first) and take top batch
        unclassified.sort(key=lambda x: abs(x[1].transaction.amount), reverse=True)
        unclassified = unclassified[:max_batch]

    _log(f"LLM fallback: klasyfikuję {len(unclassified)} transakcji modelem {model}...")

    prompt = build_classify_batch(unclassified)

    try:
        messages = [
            {"role": "system", "content": "Jesteś klasyfikatorem transakcji bankowych. Odpowiadaj TYLKO w formacie JSON."},
            {"role": "user", "content": prompt},
        ]
        response = ""
        async for chunk in ollama_client.stream_chat(
            model=model,
            messages=messages,
            options={"temperature": 0.1, "num_ctx": 4096},
        ):
            response += chunk

        results = parse_llm_response(response)
        updated = 0

        for item in results:
            idx = item.get("idx")
            category = str(item.get("category", "")).strip().lower()
            confidence = float(item.get("confidence", 0.5))

            if idx is None or not category or category == "unknown":
                continue
            if idx < 0 or idx >= len(unclassified):
                continue

            orig_idx, ct = unclassified[idx]

            # Parse category (may be "transfers:salary" format)
            main_cat = category.split(":")[0]
            if main_cat in ("crypto", "gambling", "loans", "transfers", "risky"):
                ct.categories = sorted(set(ct.categories + [main_cat]))
                ct.subcategories = sorted(set(ct.subcategories + [f"{category}:llm"]))
                ct.confidence = min(confidence, 0.8)  # Cap LLM confidence
                updated += 1

        _log(f"LLM fallback: sklasyfikowano {updated}/{len(unclassified)} transakcji")
        return updated

    except Exception as e:
        _log(f"LLM fallback: błąd — {e}")
        return 0
