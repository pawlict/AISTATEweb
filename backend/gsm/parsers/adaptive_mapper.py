"""Adaptive column mapper for GSM billing parsers.

Wraps existing parser column-mapping logic with fuzzy fallback.
When a parser's standard (exact/regex) mapping fails to find required columns,
the adaptive mapper uses schema validation to try fuzzy matching.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Set, Tuple

from .schema_registry import SchemaRegistry
from .schema_validator import SchemaValidationResult, SchemaValidator
from .drift_reporter import DriftReporter

log = logging.getLogger(__name__)


class AdaptiveColumnMapper:
    """Wraps existing parser column mapping with fuzzy fallback.

    Usage in a parser's parse_sheet() method::

        # After standard column mapping fails:
        mapper = AdaptiveColumnMapper()
        col_map, validation = mapper.build_adaptive_col_map(
            "plus", "POL", header_lower, col_map, filename="billing.csv"
        )
    """

    def __init__(
        self,
        registry: Optional[SchemaRegistry] = None,
        reporter: Optional[DriftReporter] = None,
    ):
        if registry is None:
            registry = SchemaRegistry()
        if reporter is None:
            reporter = DriftReporter()
        self._registry = registry
        self._validator = SchemaValidator(registry)
        self._reporter = reporter

    def build_adaptive_col_map(
        self,
        parser_id: str,
        variant: str,
        actual_headers: List[str],
        original_col_map: Dict[str, int],
        filename: str = "",
        auto_accept_threshold: float = 0.85,
    ) -> Tuple[Dict[str, int], SchemaValidationResult]:
        """Build a column map, augmenting the original with fuzzy matches.

        This is the main entry point for existing parsers. It:
        1. Validates actual headers against the schema
        2. If validation finds fuzzy matches, augments the original col_map
        3. Creates a drift report if format changes are detected
        4. Returns the augmented col_map + validation report

        Args:
            parser_id: Parser identifier (e.g. "plus", "play")
            variant: Format variant (e.g. "POL", "TD")
            actual_headers: Lowercased header cells from the billing file
            original_col_map: The col_map built by the parser's own logic
            filename: Original billing filename (for drift report)
            auto_accept_threshold: Confidence above which fuzzy matches
                are auto-applied to col_map

        Returns:
            (augmented_col_map, SchemaValidationResult)
        """
        # Run schema validation
        validation = self._validator.validate(parser_id, actual_headers, variant)

        if validation.match_type == "failed":
            # Schema not found — try to bootstrap
            schema = self._registry.get_schema(parser_id, variant)
            if schema is None:
                log.info(
                    "No schema for %s/%s — attempting bootstrap",
                    parser_id, variant,
                )
                self._try_bootstrap(parser_id)
                # Retry validation after bootstrap
                validation = self._validator.validate(
                    parser_id, actual_headers, variant
                )

        # Start with original col_map
        augmented = dict(original_col_map)

        if validation.match_type in ("drift", "partial"):
            # Apply fuzzy matches above threshold
            applied_count = 0
            for logical, info in validation.fuzzy_matches.items():
                confidence = info.get("confidence", 0.0)
                header_idx = info.get("header_index")
                if (
                    confidence >= auto_accept_threshold
                    and header_idx is not None
                    and logical not in augmented
                ):
                    augmented[logical] = header_idx
                    applied_count += 1
                    log.info(
                        "Adaptive: %s → col[%d] '%s' (%.2f, %s)",
                        logical, header_idx,
                        info.get("header_text", "?"),
                        confidence, info.get("method", "?"),
                    )

            # Create drift report if something changed
            if validation.fuzzy_matches or validation.missing_columns:
                try:
                    self._reporter.record_drift(
                        validation,
                        filename=filename,
                        actual_headers=actual_headers,
                    )
                except Exception as exc:
                    log.warning("Failed to record drift report: %s", exc)

        return augmented, validation

    def _try_bootstrap(self, parser_id: str) -> None:
        """Attempt to bootstrap schema from parser class if not registered."""
        try:
            self._registry.bootstrap_all()
        except Exception as exc:
            log.warning("Schema bootstrap failed: %s", exc)

    def format_warnings(
        self,
        validation: SchemaValidationResult,
        parser_id: str = "",
    ) -> List[str]:
        """Format validation result as human-readable warning strings.

        Useful for appending to BillingParseResult.warnings.
        """
        warnings: List[str] = []
        pid = parser_id or validation.parser_id

        if validation.match_type == "drift":
            warnings.append(
                f"Adaptive mapping ({pid}): wykryto zmiane formatu"
            )
            for logical, info in validation.fuzzy_matches.items():
                header = info.get("header_text", "?")
                conf = info.get("confidence", 0.0)
                method = info.get("method", "?")
                warnings.append(
                    f"  {header} -> {logical} (pewnosc: {conf:.0%}, metoda: {method})"
                )
        elif validation.match_type == "partial":
            missing = ", ".join(validation.missing_columns[:5])
            warnings.append(
                f"Adaptive mapping ({pid}): brakujace kolumny: {missing}"
            )
            if validation.fuzzy_matches:
                for logical, info in validation.fuzzy_matches.items():
                    header = info.get("header_text", "?")
                    conf = info.get("confidence", 0.0)
                    warnings.append(
                        f"  {header} -> {logical} (pewnosc: {conf:.0%})"
                    )

        return warnings
