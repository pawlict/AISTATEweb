"""Parser registry: bank auto-detection and parser lookup."""

from __future__ import annotations

from typing import List, Optional, Tuple, Type

from .base import BankParser
from .ing import INGParser
from .pko import PKOParser
from .mbank import MBankParser
from .santander import SantanderParser
from .pekao import PekaoParser
from .millennium import MillenniumParser
from .generic import GenericParser


# Ordered list of all bank parsers (checked in order during detection)
PARSERS: List[Type[BankParser]] = [
    INGParser,
    PKOParser,
    MBankParser,
    SantanderParser,
    PekaoParser,
    MillenniumParser,
]


def detect_bank(header_text: str, min_confidence: float = 0.3) -> Tuple[Optional[Type[BankParser]], float]:
    """Detect which bank the statement belongs to.

    Args:
        header_text: Extracted text from first 2 pages of PDF.
        min_confidence: Minimum confidence to accept a match.

    Returns:
        (ParserClass, confidence) or (None, 0.0) if no match above threshold.
    """
    best: Optional[Type[BankParser]] = None
    best_score = 0.0

    for parser_cls in PARSERS:
        score = parser_cls.can_parse(header_text)
        if score > best_score:
            best_score = score
            best = parser_cls

    if best_score >= min_confidence and best is not None:
        return best, best_score
    return None, 0.0


def get_parser(header_text: str) -> BankParser:
    """Get the best parser for the document, falling back to GenericParser."""
    parser_cls, confidence = detect_bank(header_text)
    if parser_cls is not None:
        return parser_cls()
    return GenericParser()
