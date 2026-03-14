"""Parser updater for GSM billing parsers.

Safely modifies parser source code to incorporate confirmed column mappings.
Creates timestamped backups before any modification and supports rollback.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .schema_registry import SchemaRegistry

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class ParserBackup:
    """Record of a parser file backup."""

    backup_id: str = ""
    original_path: str = ""
    backup_path: str = ""
    parser_id: str = ""
    parser_version_before: str = ""
    parser_version_after: str = ""
    timestamp: str = ""
    changes_description: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> ParserBackup:
        known = cls.__dataclass_fields__
        return cls(**{k: v for k, v in d.items() if k in known})


# ---------------------------------------------------------------------------
# Parser file mapping
# ---------------------------------------------------------------------------

_PARSER_FILES: Dict[str, str] = {
    "plus": "plus.py",
    "play": "play.py",
    "tmobile": "tmobile.py",
    "orange": "orange.py",
    "orange_retencja": "orange_retencja.py",
    "generic": "generic.py",
}

# Column dict variable names in parser source files
_COLUMN_DICT_NAMES: Dict[str, List[str]] = {
    "plus": ["_POL_COLUMNS", "_TD_COLUMNS"],
    "play": ["_PLAY_CSV_COLUMNS"],
    "tmobile": ["_TMOBILE_COLUMNS"],
    "orange": ["_ORANGE_COLUMNS"],
    "orange_retencja": ["_RETENCJA_COLUMNS", "_BTS_COLUMNS"],
    "generic": ["_COMMON_COLUMN_PATTERNS"],
}


# ---------------------------------------------------------------------------
# Parser Updater
# ---------------------------------------------------------------------------

class ParserUpdater:
    """Safely updates parser source code with confirmed column mappings.

    This class handles:
    1. Creating file backups before any modification
    2. Updating column mapping dictionaries in parser source
    3. Bumping parser version numbers
    4. Updating schema registry with new version
    """

    def __init__(
        self,
        parsers_dir: Optional[Path] = None,
        backup_dir: Optional[Path] = None,
        registry: Optional[SchemaRegistry] = None,
    ):
        if parsers_dir is None:
            parsers_dir = Path(__file__).parent
        if backup_dir is None:
            backup_dir = parsers_dir.parent.parent.parent / "backups" / "parsers"
        if registry is None:
            registry = SchemaRegistry()

        self._parsers_dir = parsers_dir
        self._backup_dir = backup_dir
        self._backup_dir.mkdir(parents=True, exist_ok=True)
        self._registry = registry

    @property
    def backup_dir(self) -> Path:
        return self._backup_dir

    def _parser_path(self, parser_id: str) -> Optional[Path]:
        """Get the source file path for a parser."""
        filename = _PARSER_FILES.get(parser_id)
        if not filename:
            return None
        return self._parsers_dir / filename

    def _read_source(self, parser_id: str) -> Optional[str]:
        """Read parser source code."""
        path = self._parser_path(parser_id)
        if path is None or not path.exists():
            return None
        return path.read_text(encoding="utf-8")

    def _get_current_version(self, source: str) -> str:
        """Extract current PARSER_VERSION from source."""
        m = re.search(r'PARSER_VERSION\s*=\s*["\'](\d+\.\d+)["\']', source)
        return m.group(1) if m else "1.0"

    def _bump_version(self, source: str) -> Tuple[str, str, str]:
        """Increment PARSER_VERSION in source code.

        Returns (new_source, old_version, new_version).
        """
        m = re.search(r'(PARSER_VERSION\s*=\s*["\'])(\d+)\.(\d+)(["\'])', source)
        if not m:
            return source, "1.0", "1.0"

        major = int(m.group(2))
        minor = int(m.group(3))
        new_minor = minor + 1
        old_ver = f"{major}.{minor}"
        new_ver = f"{major}.{new_minor}"

        new_source = (
            source[:m.start()]
            + f'{m.group(1)}{major}.{new_minor}{m.group(4)}'
            + source[m.end():]
        )
        return new_source, old_ver, new_ver

    # ------------------------------------------------------------------
    # Backup
    # ------------------------------------------------------------------

    def create_backup(self, parser_id: str) -> Optional[ParserBackup]:
        """Create a timestamped backup of the parser file.

        Backup location: backups/parsers/{parser_id}/{timestamp}_{parser_id}.py
        Also stores a metadata JSON alongside.
        """
        source = self._read_source(parser_id)
        if source is None:
            log.warning("Cannot backup %s: file not found", parser_id)
            return None

        parser_path = self._parser_path(parser_id)
        version = self._get_current_version(source)
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        # Include microseconds to avoid collisions when multiple backups
        # are created in the same second (e.g. safety backup before restore)
        us = datetime.now(timezone.utc).strftime("%f")[:4]
        backup_id = f"{ts}_{us}_{parser_id}"

        # Create backup directory
        bak_dir = self._backup_dir / parser_id
        bak_dir.mkdir(parents=True, exist_ok=True)

        bak_py = bak_dir / f"{backup_id}.py"
        bak_json = bak_dir / f"{backup_id}.json"

        # Write backup file
        bak_py.write_text(source, encoding="utf-8")

        backup = ParserBackup(
            backup_id=backup_id,
            original_path=str(parser_path),
            backup_path=str(bak_py),
            parser_id=parser_id,
            parser_version_before=version,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        bak_json.write_text(
            json.dumps(backup.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        log.info("Backup created: %s (v%s)", backup_id, version)
        return backup

    def list_backups(self, parser_id: Optional[str] = None) -> List[ParserBackup]:
        """List all parser backups, optionally filtered by parser_id."""
        backups: List[ParserBackup] = []
        if not self._backup_dir.exists():
            return backups

        search_dirs = [self._backup_dir / parser_id] if parser_id else list(self._backup_dir.iterdir())

        for bak_dir in search_dirs:
            if not bak_dir.is_dir():
                continue
            for path in sorted(bak_dir.glob("*.json"), reverse=True):
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    backups.append(ParserBackup.from_dict(data))
                except Exception:
                    continue

        return backups

    def restore_backup(self, backup_id: str) -> Dict[str, Any]:
        """Restore a parser from backup.

        Creates a new backup of the current state before restoring.
        """
        # Find backup
        backup_meta = None
        for bak_dir in self._backup_dir.iterdir():
            if not bak_dir.is_dir():
                continue
            meta_path = bak_dir / f"{backup_id}.json"
            if meta_path.exists():
                backup_meta = json.loads(meta_path.read_text(encoding="utf-8"))
                break

        if backup_meta is None:
            return {"error": f"Backup {backup_id} not found"}

        parser_id = backup_meta.get("parser_id", "")
        backup_path = Path(backup_meta.get("backup_path", ""))
        if not backup_path.exists():
            return {"error": f"Backup file missing: {backup_path}"}

        # Create safety backup of current state before restoring
        safety = self.create_backup(parser_id)

        # Restore
        parser_path = self._parser_path(parser_id)
        if parser_path is None:
            return {"error": f"Unknown parser: {parser_id}"}

        backup_source = backup_path.read_text(encoding="utf-8")

        # Atomic write
        tmp = parser_path.with_suffix(".py.tmp")
        tmp.write_text(backup_source, encoding="utf-8")
        tmp.replace(parser_path)

        log.info("Restored %s from backup %s", parser_id, backup_id)
        return {
            "status": "restored",
            "parser_id": parser_id,
            "backup_id": backup_id,
            "safety_backup": safety.backup_id if safety else None,
            "restored_version": backup_meta.get("parser_version_before", "?"),
        }

    # ------------------------------------------------------------------
    # Preview changes
    # ------------------------------------------------------------------

    def preview_changes(
        self,
        parser_id: str,
        column_updates: Dict[str, str],
        variant: str = "",
    ) -> Dict[str, Any]:
        """Preview what changes would be made to the parser file.

        Args:
            parser_id: Parser to update ("plus", "play", etc.)
            column_updates: Dict of logical_name → new_header_string
            variant: Format variant (for Plus: "POL" or "TD")

        Returns:
            Dict with file, diff_lines, version_bump, etc.
        """
        source = self._read_source(parser_id)
        if source is None:
            return {"error": f"Parser file not found: {parser_id}"}

        old_version = self._get_current_version(source)

        # Determine target dict name
        dict_names = _COLUMN_DICT_NAMES.get(parser_id, [])
        if not dict_names:
            return {"error": f"No column dicts known for {parser_id}"}

        target_dict = dict_names[0]
        if parser_id == "plus" and variant == "TD" and len(dict_names) > 1:
            target_dict = dict_names[1]  # _TD_COLUMNS

        # Generate diff preview
        additions: List[str] = []
        for logical, new_header in column_updates.items():
            new_header_lower = new_header.strip().lower()
            if parser_id in ("plus",):
                # Plus style: header → logical
                additions.append(f'    "{new_header_lower}": "{logical}",')
            elif parser_id in ("play",):
                # Play style: logical → CSV_HEADER
                additions.append(f'    "{logical}": "{new_header.strip().upper()}",')
            else:
                # Regex style: add pattern to existing list
                pattern = re.escape(new_header_lower)
                additions.append(f'        r"{pattern}",')

        major, minor = old_version.split(".")
        new_version = f"{major}.{int(minor) + 1}"

        return {
            "parser_id": parser_id,
            "file": str(self._parser_path(parser_id)),
            "target_dict": target_dict,
            "additions": additions,
            "version_bump": f"{old_version} → {new_version}",
            "column_updates": column_updates,
        }

    # ------------------------------------------------------------------
    # Apply changes
    # ------------------------------------------------------------------

    def apply_column_updates(
        self,
        parser_id: str,
        column_updates: Dict[str, str],
        variant: str = "",
        drift_report_id: str = "",
    ) -> Dict[str, Any]:
        """Apply confirmed column mapping changes to parser source code.

        Steps:
        1. Create backup
        2. Read parser source
        3. Add new entries to column dict
        4. Bump PARSER_VERSION
        5. Atomic write
        6. Update schema registry

        Args:
            parser_id: Parser to update
            column_updates: Dict of logical_name → new_header_string
            variant: Format variant
            drift_report_id: Optional drift report ID to mark as applied

        Returns:
            Operation result dict.
        """
        source = self._read_source(parser_id)
        if source is None:
            return {"error": f"Parser file not found: {parser_id}"}

        # 1. Create backup
        backup = self.create_backup(parser_id)
        if backup is None:
            return {"error": f"Failed to create backup for {parser_id}"}

        # 2. Determine target dict
        dict_names = _COLUMN_DICT_NAMES.get(parser_id, [])
        if not dict_names:
            return {"error": f"No column dicts known for {parser_id}"}

        target_dict = dict_names[0]
        if parser_id == "plus" and variant == "TD" and len(dict_names) > 1:
            target_dict = dict_names[1]

        # 3. Add entries to column dict
        if parser_id in ("plus",):
            source = self._add_to_exact_dict(
                source, target_dict, column_updates, style="plus"
            )
        elif parser_id in ("play",):
            source = self._add_to_exact_dict(
                source, target_dict, column_updates, style="play"
            )
        else:
            source = self._add_to_regex_dict(
                source, target_dict, column_updates
            )

        # 4. Bump version
        source, old_ver, new_ver = self._bump_version(source)
        backup.parser_version_after = new_ver

        # Update backup metadata with after version
        bak_meta_path = Path(backup.backup_path).with_suffix(".json")
        if bak_meta_path.exists():
            backup.changes_description = (
                f"Added columns: {list(column_updates.keys())}"
            )
            bak_meta_path.write_text(
                json.dumps(backup.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

        # 5. Atomic write
        parser_path = self._parser_path(parser_id)
        if parser_path is None:
            return {"error": "Parser path not found"}

        tmp = parser_path.with_suffix(".py.tmp")
        tmp.write_text(source, encoding="utf-8")
        tmp.replace(parser_path)

        log.info(
            "Updated %s: v%s → v%s, added %d columns",
            parser_id, old_ver, new_ver, len(column_updates),
        )

        # 6. Mark drift report as applied
        if drift_report_id:
            try:
                from .drift_reporter import DriftReporter
                reporter = DriftReporter()
                reporter.update_status(
                    drift_report_id,
                    "auto_applied",
                    applied_changes=column_updates,
                )
            except Exception as exc:
                log.warning("Failed to update drift report: %s", exc)

        return {
            "status": "applied",
            "parser_id": parser_id,
            "version_before": old_ver,
            "version_after": new_ver,
            "columns_added": list(column_updates.keys()),
            "backup_id": backup.backup_id,
            "note": "Restart serwera wymagany, aby zmiany weszly w zycie",
        }

    # ------------------------------------------------------------------
    # Source code modification helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _add_to_exact_dict(
        source: str,
        dict_name: str,
        updates: Dict[str, str],
        style: str = "plus",
    ) -> str:
        """Add new entries to an exact-match column dict (Plus/Play style).

        For Plus: adds 'new_header_lower': 'logical_name' entries.
        For Play: adds 'logical_name': 'CSV_HEADER' entries.
        """
        # Find the closing brace of the target dict
        pattern = re.compile(
            rf"({re.escape(dict_name)}\s*:\s*Dict\[str,\s*str\]\s*=\s*\{{)"
            r"(.*?)"
            r"(\})",
            re.DOTALL,
        )
        match = pattern.search(source)
        if not match:
            # Try simpler pattern
            pattern = re.compile(
                rf"({re.escape(dict_name)}\s*=\s*\{{)"
                r"(.*?)"
                r"(\})",
                re.DOTALL,
            )
            match = pattern.search(source)

        if not match:
            log.warning("Could not find dict %s in source", dict_name)
            return source

        # Build new entries
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        entries: List[str] = []
        for logical, new_header in updates.items():
            if style == "plus":
                # Plus: header → logical
                header_lower = new_header.strip().lower()
                entries.append(
                    f'    "{header_lower}": "{logical}",'
                    f"              # Added by adaptive parser ({ts})"
                )
            elif style == "play":
                # Play: logical → CSV_HEADER
                csv_upper = new_header.strip().upper()
                entries.append(
                    f'    "{logical}": "{csv_upper}",'
                    f"              # Added by adaptive parser ({ts})"
                )

        if not entries:
            return source

        # Insert before closing brace
        insertion = "\n" + "\n".join(entries) + "\n"
        new_source = (
            source[:match.end(2)]
            + insertion
            + source[match.start(3):]
        )
        return new_source

    @staticmethod
    def _add_to_regex_dict(
        source: str,
        dict_name: str,
        updates: Dict[str, str],
    ) -> str:
        """Add new regex patterns to a regex-based column dict (T-Mobile/Orange style).

        For existing logical names: appends a new pattern to the list.
        For new logical names: adds a new entry to the dict.
        """
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        for logical, new_header in updates.items():
            pattern_str = re.escape(new_header.strip().lower())

            # Check if logical name already exists in the dict
            existing_pattern = re.compile(
                rf'("{re.escape(logical)}"\s*:\s*\[)'
                r"(.*?)"
                r"(\])",
                re.DOTALL,
            )
            existing_match = existing_pattern.search(source)

            if existing_match:
                # Append new pattern to existing list
                new_entry = (
                    f'\n        r"{pattern_str}",'
                    f"  # Added by adaptive parser ({ts})"
                )
                source = (
                    source[:existing_match.end(2)]
                    + new_entry
                    + source[existing_match.start(3):]
                )
            else:
                # Add new entry to the dict — find closing brace
                dict_pattern = re.compile(
                    rf"({re.escape(dict_name)}\s*(?::\s*Dict\[.*?\]\s*)?=\s*\{{)"
                    r"(.*?)"
                    r"(\})",
                    re.DOTALL,
                )
                dict_match = dict_pattern.search(source)
                if dict_match:
                    new_entry = (
                        f'\n    "{logical}": ['
                        f'\n        r"{pattern_str}",'
                        f"  # Added by adaptive parser ({ts})"
                        f"\n    ],"
                    )
                    source = (
                        source[:dict_match.end(2)]
                        + new_entry
                        + source[dict_match.start(3):]
                    )

        return source
