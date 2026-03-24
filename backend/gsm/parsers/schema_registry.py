"""Schema registry for GSM billing parsers.

Stores "known good" column schemas per parser version in external JSON files.
Auto-generates schemas from existing parser column definitions on first use.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Type

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class ColumnSchema:
    """Schema definition for a single logical column."""

    logical_name: str                 # e.g. "datetime", "caller", "duration"
    expected_headers: List[str]       # Known exact header strings (lowercased)
    regex_patterns: List[str]         # Regex patterns for flexible matching
    required: bool = True             # If True, parser fails without this column
    data_type: str = "str"            # "str", "int", "float", "datetime"
    description: str = ""             # Human-readable description

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> ColumnSchema:
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class ParserSchema:
    """Complete schema for a parser version."""

    parser_id: str                    # e.g. "plus", "play", "tmobile"
    parser_version: str               # e.g. "1.3"
    format_variant: str = ""          # e.g. "POL", "TD" for Plus sub-formats
    columns: List[ColumnSchema] = field(default_factory=list)
    header_detection: List[str] = field(default_factory=list)
    notes: str = ""
    created_at: str = ""              # ISO timestamp

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["columns"] = [c.to_dict() for c in self.columns]
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> ParserSchema:
        cols = [ColumnSchema.from_dict(c) for c in d.get("columns", [])]
        return cls(
            parser_id=d.get("parser_id", ""),
            parser_version=d.get("parser_version", ""),
            format_variant=d.get("format_variant", ""),
            columns=cols,
            header_detection=d.get("header_detection", []),
            notes=d.get("notes", ""),
            created_at=d.get("created_at", ""),
        )

    def get_required_columns(self) -> List[ColumnSchema]:
        """Return list of columns marked as required."""
        return [c for c in self.columns if c.required]

    def get_column(self, logical_name: str) -> Optional[ColumnSchema]:
        """Look up a column by its logical name."""
        for c in self.columns:
            if c.logical_name == logical_name:
                return c
        return None


# ---------------------------------------------------------------------------
# Critical columns per parser (columns without which parsing fails)
# ---------------------------------------------------------------------------

_CRITICAL_COLUMNS: Dict[str, List[str]] = {
    "plus_POL": ["start", "type"],
    "plus_TD": ["start"],
    "play": ["datetime", "ui_msisdn", "uw_msisdn", "service_type"],
    "tmobile": ["date", "callee"],
    "orange": ["date"],
    "orange_retencja": ["date", "ident"],
    "generic": ["date"],
    # Identification parsers
    "ident_orange": ["msisdn", "name"],
    "ident_play": ["msisdn"],
    "ident_plus": ["msisdn"],
    "ident_tmobile": ["msisdn", "name"],
}


# ---------------------------------------------------------------------------
# Schema Registry
# ---------------------------------------------------------------------------

class SchemaRegistry:
    """Manages parser column schemas on disk (JSON files)."""

    def __init__(self, schema_dir: Optional[Path] = None):
        if schema_dir is None:
            schema_dir = Path(__file__).parent / "schemas"
        self._dir = schema_dir
        self._dir.mkdir(parents=True, exist_ok=True)
        self._cache: Dict[str, ParserSchema] = {}

    @property
    def schema_dir(self) -> Path:
        return self._dir

    def _cache_key(self, parser_id: str, variant: str = "") -> str:
        return f"{parser_id}_{variant}" if variant else parser_id

    def _schema_path(self, parser_id: str, variant: str = "") -> Path:
        key = self._cache_key(parser_id, variant)
        return self._dir / f"{key}.json"

    def get_schema(self, parser_id: str, variant: str = "") -> Optional[ParserSchema]:
        """Load schema from cache or disk."""
        key = self._cache_key(parser_id, variant)
        if key in self._cache:
            return self._cache[key]

        path = self._schema_path(parser_id, variant)
        if not path.exists():
            return None

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            schema = ParserSchema.from_dict(data)
            self._cache[key] = schema
            return schema
        except Exception as exc:
            log.warning("Failed to load schema %s: %s", path.name, exc)
            return None

    def save_schema(self, schema: ParserSchema) -> Path:
        """Save schema to disk and update cache."""
        if not schema.created_at:
            schema.created_at = datetime.now(timezone.utc).isoformat()

        path = self._schema_path(schema.parser_id, schema.format_variant)
        path.write_text(
            json.dumps(schema.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        key = self._cache_key(schema.parser_id, schema.format_variant)
        self._cache[key] = schema
        log.info("Saved schema: %s (v%s)", key, schema.parser_version)
        return path

    def list_schemas(self) -> List[ParserSchema]:
        """List all registered schemas from disk."""
        schemas: List[ParserSchema] = []
        if not self._dir.exists():
            return schemas
        for path in sorted(self._dir.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                schemas.append(ParserSchema.from_dict(data))
            except Exception as exc:
                log.warning("Skipping invalid schema %s: %s", path.name, exc)
        return schemas

    def delete_schema(self, parser_id: str, variant: str = "") -> bool:
        """Delete schema file from disk and cache."""
        key = self._cache_key(parser_id, variant)
        self._cache.pop(key, None)
        path = self._schema_path(parser_id, variant)
        if path.exists():
            path.unlink()
            return True
        return False

    # ------------------------------------------------------------------
    # Auto-generation from existing parsers
    # ------------------------------------------------------------------

    def register_from_parser(
        self,
        parser_cls: Type,
        variant: str = "",
        column_dict: Optional[Dict] = None,
        column_format: str = "auto",
    ) -> ParserSchema:
        """Auto-generate a schema from an existing parser's column definitions.

        Args:
            parser_cls: The parser class (must have OPERATOR_ID, PARSER_VERSION, etc.)
            variant: Format variant (e.g. "POL", "TD" for Plus)
            column_dict: The parser's column dictionary. If None, tries to detect.
            column_format: "exact" for Dict[str, str] (Plus/Play), "regex" for
                           Dict[str, List[str]] (T-Mobile/Orange), or "auto".

        Returns:
            Generated and saved ParserSchema.
        """
        parser_id = getattr(parser_cls, "OPERATOR_ID", "unknown")
        parser_version = getattr(parser_cls, "PARSER_VERSION", "1.0")
        detection_patterns = list(getattr(parser_cls, "DETECT_HEADER_PATTERNS", []))

        # Determine critical columns for this parser+variant
        crit_key = f"{parser_id}_{variant}" if variant else parser_id
        critical = set(_CRITICAL_COLUMNS.get(crit_key, []))

        columns: List[ColumnSchema] = []

        if column_dict is None:
            log.warning("No column_dict provided for %s — empty schema", parser_id)
        elif column_format == "auto":
            # Detect format from first value
            sample = next(iter(column_dict.values()), None)
            if isinstance(sample, list):
                column_format = "regex"
            else:
                column_format = "exact"

        if column_dict is not None:
            if column_format == "exact":
                # Plus/Play style: Dict[header_name_lower, logical_name]
                # or Dict[logical_name, csv_header] (Play is inverted)
                # Group by logical name → collect all known header strings
                by_logical: Dict[str, List[str]] = {}
                for key, val in column_dict.items():
                    # For Plus: key=header, val=logical
                    # For Play: key=logical, val=csv_header
                    # We detect by checking if the value looks like a logical name
                    if val.isupper() or "_" in val and val == val.upper():
                        # Play style: key=logical_name, val=CSV_HEADER
                        logical = key
                        header = val.lower()
                    else:
                        # Plus style: key=header, val=logical_name
                        logical = val
                        header = key

                    if logical not in by_logical:
                        by_logical[logical] = []
                    if header not in by_logical[logical]:
                        by_logical[logical].append(header)

                for logical, headers in by_logical.items():
                    columns.append(ColumnSchema(
                        logical_name=logical,
                        expected_headers=headers,
                        regex_patterns=[],  # exact-match parsers don't have regex
                        required=logical in critical,
                        description="",
                    ))
            else:
                # T-Mobile/Orange style: Dict[logical_name, List[regex_pattern]]
                for logical, patterns in column_dict.items():
                    columns.append(ColumnSchema(
                        logical_name=logical,
                        expected_headers=[],
                        regex_patterns=list(patterns),
                        required=logical in critical,
                        description="",
                    ))

        schema = ParserSchema(
            parser_id=parser_id,
            parser_version=parser_version,
            format_variant=variant,
            columns=columns,
            header_detection=detection_patterns,
            notes=f"Auto-generated from {parser_cls.__name__}",
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        self.save_schema(schema)
        return schema

    def bootstrap_all(self) -> List[ParserSchema]:
        """Auto-generate schemas for all known parsers.

        Imports each parser, reads its column dicts, and creates schemas.
        Safe to call multiple times (overwrites existing schemas).
        """
        schemas: List[ParserSchema] = []

        try:
            from .plus import PlusParser, _POL_COLUMNS, _TD_COLUMNS
            schemas.append(self.register_from_parser(
                PlusParser, variant="POL", column_dict=_POL_COLUMNS, column_format="exact",
            ))
            schemas.append(self.register_from_parser(
                PlusParser, variant="TD", column_dict=_TD_COLUMNS, column_format="exact",
            ))
        except ImportError as e:
            log.warning("Cannot import PlusParser: %s", e)

        try:
            from .play import PlayParser, _PLAY_CSV_COLUMNS
            schemas.append(self.register_from_parser(
                PlayParser, column_dict=_PLAY_CSV_COLUMNS, column_format="exact",
            ))
        except ImportError as e:
            log.warning("Cannot import PlayParser: %s", e)

        try:
            from .tmobile import TMobileParser, _TMOBILE_COLUMNS
            schemas.append(self.register_from_parser(
                TMobileParser, column_dict=_TMOBILE_COLUMNS, column_format="regex",
            ))
        except ImportError as e:
            log.warning("Cannot import TMobileParser: %s", e)

        try:
            from .orange import OrangeParser, _ORANGE_COLUMNS
            schemas.append(self.register_from_parser(
                OrangeParser, column_dict=_ORANGE_COLUMNS, column_format="regex",
            ))
        except ImportError as e:
            log.warning("Cannot import OrangeParser: %s", e)

        try:
            from .orange_retencja import OrangeRetencjaParser, _RETENCJA_COLUMNS
            schemas.append(self.register_from_parser(
                OrangeRetencjaParser, column_dict=_RETENCJA_COLUMNS, column_format="regex",
            ))
        except ImportError as e:
            log.warning("Cannot import OrangeRetencjaParser: %s", e)

        try:
            from .generic import GenericBillingParser, _COMMON_COLUMN_PATTERNS
            schemas.append(self.register_from_parser(
                GenericBillingParser, column_dict=_COMMON_COLUMN_PATTERNS, column_format="regex",
            ))
        except ImportError as e:
            log.warning("Cannot import GenericBillingParser: %s", e)

        # ── Identification parsers ──
        try:
            from ..identification import (
                _ORANGE_ID_COLUMNS, _PLAY_ID_COLUMNS,
                _PLUS_ID_COLUMNS, _TMOBILE_ID_COLUMNS,
            )
            for pid, col_dict in [
                ("ident_orange", _ORANGE_ID_COLUMNS),
                ("ident_play", _PLAY_ID_COLUMNS),
                ("ident_plus", _PLUS_ID_COLUMNS),
                ("ident_tmobile", _TMOBILE_ID_COLUMNS),
            ]:
                crit = set(_CRITICAL_COLUMNS.get(pid, []))
                cols = []
                for logical, expected_list in col_dict.items():
                    cols.append(ColumnSchema(
                        logical_name=logical,
                        expected_headers=[h.lower() for h in expected_list],
                        regex_patterns=[],
                        required=logical in crit,
                    ))
                schema = ParserSchema(
                    parser_id=pid,
                    parser_version="1.0",
                    columns=cols,
                    notes=f"Auto-generated from identification.py ({pid})",
                )
                self.save_schema(schema)
                schemas.append(schema)
        except ImportError as e:
            log.warning("Cannot import identification columns: %s", e)

        log.info("Bootstrapped %d parser schemas", len(schemas))
        return schemas
