"""Drift reporter for GSM billing parser schema changes.

Detects, records, and manages schema drift events — situations where
an operator's billing format has changed from the expected column layout.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .schema_validator import SchemaValidationResult

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class DriftReport:
    """Record of a detected schema drift event."""

    report_id: str = ""
    timestamp: str = ""
    parser_id: str = ""
    parser_version: str = ""
    format_variant: str = ""
    filename: str = ""                        # original billing filename

    # What changed
    new_columns: List[str] = field(default_factory=list)      # headers not in schema
    removed_columns: List[str] = field(default_factory=list)  # expected but missing
    renamed_columns: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    # renamed_columns: { logical_name: { new_header, confidence, method } }

    # Validation result
    match_type: str = ""                      # exact/partial/drift/failed
    overall_confidence: float = 0.0

    # User action
    status: str = "pending"                   # pending / approved / rejected / auto_applied
    user_action_at: str = ""
    applied_changes: Dict[str, str] = field(default_factory=dict)  # what was applied

    # Full headers for debugging
    actual_headers: List[str] = field(default_factory=list)
    expected_columns: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> DriftReport:
        known = cls.__dataclass_fields__
        return cls(**{k: v for k, v in d.items() if k in known})


# ---------------------------------------------------------------------------
# Drift Reporter
# ---------------------------------------------------------------------------

class DriftReporter:
    """Manages drift report storage and retrieval."""

    def __init__(self, data_dir: Optional[Path] = None):
        if data_dir is None:
            env_dir = os.environ.get("AISTATEWEB_DATA_DIR")
            if env_dir:
                data_dir = Path(env_dir)
            else:
                data_dir = Path(__file__).resolve().parents[3] / "data_www"
        self._dir = data_dir / "gsm" / "drift_reports"
        self._dir.mkdir(parents=True, exist_ok=True)

    @property
    def reports_dir(self) -> Path:
        return self._dir

    def record_drift(
        self,
        validation: SchemaValidationResult,
        filename: str = "",
        actual_headers: Optional[List[str]] = None,
    ) -> DriftReport:
        """Create and store a drift report from a validation result.

        Only creates a report if there is actual drift (fuzzy matches,
        missing columns, or extra headers). Returns the report.
        """
        report = DriftReport(
            report_id=uuid.uuid4().hex[:12],
            timestamp=datetime.now(timezone.utc).isoformat(),
            parser_id=validation.parser_id,
            parser_version=validation.parser_version,
            format_variant=validation.format_variant,
            filename=filename,
            new_columns=validation.extra_headers[:50],  # cap for safety
            removed_columns=validation.missing_columns[:50],
            renamed_columns={
                k: {
                    "new_header": v.get("header_text", ""),
                    "confidence": v.get("confidence", 0.0),
                    "method": v.get("method", ""),
                }
                for k, v in validation.fuzzy_matches.items()
            },
            match_type=validation.match_type,
            overall_confidence=validation.confidence,
            actual_headers=actual_headers[:100] if actual_headers else [],
            expected_columns=[
                c for c in validation.matched_columns
            ],
        )

        self._save(report)
        log.info(
            "Drift report %s: parser=%s match=%s confidence=%.2f",
            report.report_id, report.parser_id,
            report.match_type, report.overall_confidence,
        )
        return report

    def get_report(self, report_id: str) -> Optional[DriftReport]:
        """Get a specific drift report by ID."""
        path = self._dir / f"{report_id}.json"
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return DriftReport.from_dict(data)
        except Exception as exc:
            log.warning("Failed to load drift report %s: %s", report_id, exc)
            return None

    def get_pending_reports(self) -> List[DriftReport]:
        """Get all drift reports awaiting user review."""
        return self.list_reports(status="pending")

    def list_reports(
        self,
        parser_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
    ) -> List[DriftReport]:
        """List drift reports, optionally filtered."""
        reports: List[DriftReport] = []

        if not self._dir.exists():
            return reports

        paths = sorted(self._dir.glob("*.json"), reverse=True)
        for path in paths:
            if len(reports) >= limit:
                break
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                report = DriftReport.from_dict(data)
                if parser_id and report.parser_id != parser_id:
                    continue
                if status and report.status != status:
                    continue
                reports.append(report)
            except Exception:
                continue

        return reports

    def update_status(
        self,
        report_id: str,
        status: str,
        applied_changes: Optional[Dict[str, str]] = None,
    ) -> Optional[DriftReport]:
        """Update the status of a drift report."""
        report = self.get_report(report_id)
        if report is None:
            return None

        report.status = status
        report.user_action_at = datetime.now(timezone.utc).isoformat()
        if applied_changes:
            report.applied_changes = applied_changes

        self._save(report)
        return report

    def delete_report(self, report_id: str) -> bool:
        """Delete a drift report."""
        path = self._dir / f"{report_id}.json"
        if path.exists():
            path.unlink()
            return True
        return False

    def _save(self, report: DriftReport) -> None:
        """Save report to disk."""
        path = self._dir / f"{report.report_id}.json"
        path.write_text(
            json.dumps(report.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
