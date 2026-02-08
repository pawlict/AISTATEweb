"""Bank statement detection — decides if a PDF is a bank statement."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# Keywords that strongly indicate a bank statement
_STRONG_INDICATORS = [
    r"wyci[ąa]g\s*(z\s*rachunku|bankow)",
    r"historia\s*(rachunku|operacji|transakcji)",
    r"zestawienie\s*operacji",
    r"wykaz\s*operacji",
    r"rachunek\s*(bieżący|oszczędn|osobist)",
    r"account\s*statement",
]

_MODERATE_INDICATORS = [
    r"saldo\s*(pocz[ąa]tkowe|ko[ńn]cowe|otwarcia|zamkni[ęe]cia)",
    r"data\s*(operacji|ksi[ęe]gowania|waluty|transakcji)",
    r"numer\s*rachunku",
    r"IBAN\s*:?\s*PL",
    r"\d{2}\s?\d{4}\s?\d{4}\s?\d{4}\s?\d{4}\s?\d{4}\s?\d{4}",  # IBAN
    r"kwota\s*(operacji|transakcji)?",
    r"przelew\s*(przychodz|wychodz|krajow|zagranicz)",
]


def is_bank_statement(text: str, min_score: int = 3) -> Tuple[bool, int, List[str]]:
    """Check if extracted text looks like a bank statement.

    Args:
        text: Extracted text from document (first 2-3 pages ideally).
        min_score: Minimum score to classify as bank statement.

    Returns:
        (is_statement, score, matched_indicators)
    """
    text_lower = text.lower()
    score = 0
    matched: List[str] = []

    for pattern in _STRONG_INDICATORS:
        if re.search(pattern, text_lower):
            score += 3
            matched.append(f"strong: {pattern}")

    for pattern in _MODERATE_INDICATORS:
        if re.search(pattern, text_lower):
            score += 1
            matched.append(f"moderate: {pattern}")

    return score >= min_score, score, matched


def detect_documents_for_finance(
    doc_dir: Path,
    doc_names: List[str],
    cache_dir: Optional[Path] = None,
) -> List[Tuple[str, str, int]]:
    """Scan project documents to find bank statements.

    Args:
        doc_dir: Path to documents directory
        doc_names: List of document filenames to check
        cache_dir: Optional .cache directory with extracted text

    Returns:
        List of (filename, extracted_text_preview, confidence_score) for detected statements.
    """
    results: List[Tuple[str, str, int]] = []

    for name in doc_names:
        fp = doc_dir / name
        if not fp.exists():
            continue
        # Only check PDFs (and maybe images)
        ext = fp.suffix.lower()
        if ext not in (".pdf", ".png", ".jpg", ".jpeg"):
            continue

        # Read cached extracted text
        text = ""
        if cache_dir:
            cache_txt = cache_dir / f"{name}.txt"
            if cache_txt.exists():
                try:
                    text = cache_txt.read_text(encoding="utf-8", errors="replace")[:10000]
                except Exception:
                    pass

        if not text:
            continue

        is_stmt, score, _ = is_bank_statement(text)
        if is_stmt:
            results.append((name, text, score))

    return results
