"""Parser registry: operator auto-detection and parser lookup for GSM billings."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple, Type

from .base import BillingParser


def _get_all_parsers() -> List[Type[BillingParser]]:
    """Import all operator parsers (lazy to avoid circular imports)."""
    from .play import PlayParser
    from .tmobile import TMobileParser
    from .orange import OrangeParser
    from .orange_retencja import OrangeRetencjaParser
    from .plus import PlusParser
    from .generic import GenericBillingParser

    return [
        OrangeRetencjaParser,  # before OrangeParser (more specific format)
        TMobileParser,
        PlayParser,
        OrangeParser,
        PlusParser,
        # GenericBillingParser is the fallback — not included in detection
    ]


def detect_operator(
    headers: List[str],
    sheet_names: List[str],
    min_confidence: float = 0.3,
) -> Tuple[Optional[Type[BillingParser]], float]:
    """Detect which operator the billing belongs to.

    Args:
        headers: Lowercased header cells from first non-empty row of the billing sheet.
        sheet_names: Lowercased sheet names in the workbook.
        min_confidence: Minimum confidence to accept a match.

    Returns:
        (ParserClass, confidence) or (None, 0.0) if no match.
    """
    best: Optional[Type[BillingParser]] = None
    best_score = 0.0

    for parser_cls in _get_all_parsers():
        score = parser_cls.can_parse(headers, sheet_names)
        if score > best_score:
            best_score = score
            best = parser_cls

    if best_score >= min_confidence and best is not None:
        return best, best_score
    return None, 0.0


def get_parser(
    headers: List[str],
    sheet_names: List[str],
) -> BillingParser:
    """Get the best parser for the XLSX file, falling back to GenericBillingParser."""
    from .generic import GenericBillingParser

    parser_cls, confidence = detect_operator(headers, sheet_names)
    if parser_cls is not None:
        return parser_cls()
    return GenericBillingParser()
