"""GSM billing parsers for Polish mobile operators."""

from .base import BillingParser, BillingRecord, SubscriberInfo, BillingParseResult
from .registry import detect_operator, get_parser

__all__ = [
    "BillingParser",
    "BillingRecord",
    "SubscriberInfo",
    "BillingParseResult",
    "detect_operator",
    "get_parser",
    # Adaptive parser system
    "SchemaRegistry",
    "SchemaValidator",
    "AdaptiveColumnMapper",
    "DriftReporter",
    "ParserUpdater",
]

# Lazy imports for adaptive parser system (avoid import overhead at module load)
def __getattr__(name):
    if name == "SchemaRegistry":
        from .schema_registry import SchemaRegistry
        return SchemaRegistry
    if name == "SchemaValidator":
        from .schema_validator import SchemaValidator
        return SchemaValidator
    if name == "AdaptiveColumnMapper":
        from .adaptive_mapper import AdaptiveColumnMapper
        return AdaptiveColumnMapper
    if name == "DriftReporter":
        from .drift_reporter import DriftReporter
        return DriftReporter
    if name == "ParserUpdater":
        from .parser_updater import ParserUpdater
        return ParserUpdater
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
