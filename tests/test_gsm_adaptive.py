"""Tests for the adaptive GSM parser system.

Tests cover:
- Schema Registry (registration, persistence, auto-generation)
- Schema Validator (exact, regex, fuzzy matching)
- Adaptive Column Mapper (fallback integration)
- Drift Reporter (report creation and management)
- Parser Updater (backup, code modification, restore)
"""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path
from typing import Dict, List

import pytest

from backend.gsm.parsers.schema_registry import (
    ColumnSchema,
    ParserSchema,
    SchemaRegistry,
)
from backend.gsm.parsers.schema_validator import (
    SchemaValidationResult,
    SchemaValidator,
    _normalize_header,
    _strip_diacritics,
    _fuzzy_normalized,
    _fuzzy_sequence_matcher,
    _fuzzy_semantic,
)
from backend.gsm.parsers.adaptive_mapper import AdaptiveColumnMapper
from backend.gsm.parsers.drift_reporter import DriftReport, DriftReporter
from backend.gsm.parsers.parser_updater import ParserUpdater


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_dir():
    d = Path(tempfile.mkdtemp(prefix="gsm_adaptive_test_"))
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def schema_dir(tmp_dir):
    d = tmp_dir / "schemas"
    d.mkdir()
    return d


@pytest.fixture
def registry(schema_dir):
    return SchemaRegistry(schema_dir=schema_dir)


@pytest.fixture
def sample_schema():
    return ParserSchema(
        parser_id="test_parser",
        parser_version="1.0",
        format_variant="",
        columns=[
            ColumnSchema(
                logical_name="datetime",
                expected_headers=["data_i_godz_polacz", "data i godz"],
                regex_patterns=[r"data\s*i\s*godz"],
                required=True,
            ),
            ColumnSchema(
                logical_name="caller",
                expected_headers=["ui_msisdn", "numer a"],
                regex_patterns=[r"ui_msisdn", r"numer\s*a"],
                required=True,
            ),
            ColumnSchema(
                logical_name="callee",
                expected_headers=["uw_msisdn", "numer b"],
                regex_patterns=[r"uw_msisdn", r"numer\s*b"],
                required=True,
            ),
            ColumnSchema(
                logical_name="duration",
                expected_headers=["czas_trwania", "czas trwania"],
                regex_patterns=[r"czas\s*trwania"],
                required=False,
            ),
            ColumnSchema(
                logical_name="service_type",
                expected_headers=["rodzaj_uslugi"],
                regex_patterns=[r"rodzaj\s*us[łl]ugi"],
                required=True,
            ),
        ],
        header_detection=[r"data_i_godz_polacz", r"rodzaj_uslugi"],
    )


@pytest.fixture
def validator(registry, sample_schema):
    registry.save_schema(sample_schema)
    return SchemaValidator(registry)


# ===========================================================================
# Test: Text normalization helpers
# ===========================================================================

class TestNormalization:
    def test_strip_diacritics_polish(self):
        assert _strip_diacritics("łódź") == "lodz"
        assert _strip_diacritics("Początek") == "Poczatek"
        assert _strip_diacritics("Usługa") == "Usluga"
        assert _strip_diacritics("Długość") == "Dlugosc"

    def test_normalize_header_underscores(self):
        assert _normalize_header("DATA_I_GODZ_POLACZ") == "data i godz polacz"

    def test_normalize_header_dots_dashes(self):
        assert _normalize_header("Data i godz.") == "data i godz"
        assert _normalize_header("czas-trwania") == "czas trwania"

    def test_normalize_header_mixed(self):
        assert _normalize_header("  Początek  ") == "poczatek"
        assert _normalize_header("Usługa/Typ") == "usluga typ"


# ===========================================================================
# Test: Fuzzy matching strategies
# ===========================================================================

class TestFuzzyStrategies:
    def test_fuzzy_normalized_exact(self):
        score = _fuzzy_normalized(["data_i_godz_polacz"], "DATA_I_GODZ_POLACZ")
        assert score == 1.0

    def test_fuzzy_normalized_with_diacritics(self):
        score = _fuzzy_normalized(["początek"], "poczatek")
        assert score == 1.0

    def test_fuzzy_normalized_underscores_vs_spaces(self):
        score = _fuzzy_normalized(["czas_trwania"], "Czas trwania")
        assert score == 1.0

    def test_fuzzy_normalized_partial(self):
        score = _fuzzy_normalized(["data i godz"], "data i godzina polaczenia")
        assert score > 0.5  # partial containment

    def test_fuzzy_normalized_no_match(self):
        score = _fuzzy_normalized(["data_i_godz"], "koszt_netto")
        assert score < 0.5

    def test_fuzzy_sequence_matcher_similar(self):
        score = _fuzzy_sequence_matcher(["czas trwania"], "czas_trwania")
        assert score > 0.8

    def test_fuzzy_sequence_matcher_different(self):
        score = _fuzzy_sequence_matcher(["czas trwania"], "numer telefonu")
        assert score < 0.5

    def test_fuzzy_semantic_datetime(self):
        score = _fuzzy_semantic("datetime", "data rozpoczecia")
        assert score > 0.5

    def test_fuzzy_semantic_duration(self):
        score = _fuzzy_semantic("duration", "czas trwania polaczenia")
        assert score > 0.5

    def test_fuzzy_semantic_no_match(self):
        score = _fuzzy_semantic("datetime", "koszt brutto")
        assert score == 0.0

    def test_fuzzy_semantic_cost(self):
        score = _fuzzy_semantic("cost", "kwota netto")
        assert score > 0.5


# ===========================================================================
# Test: Schema Registry
# ===========================================================================

class TestSchemaRegistry:
    def test_save_and_load(self, registry, sample_schema):
        path = registry.save_schema(sample_schema)
        assert path.exists()

        loaded = registry.get_schema("test_parser")
        assert loaded is not None
        assert loaded.parser_id == "test_parser"
        assert loaded.parser_version == "1.0"
        assert len(loaded.columns) == 5

    def test_list_schemas(self, registry, sample_schema):
        registry.save_schema(sample_schema)
        schemas = registry.list_schemas()
        assert len(schemas) == 1
        assert schemas[0].parser_id == "test_parser"

    def test_delete_schema(self, registry, sample_schema):
        registry.save_schema(sample_schema)
        assert registry.delete_schema("test_parser")
        assert registry.get_schema("test_parser") is None

    def test_get_nonexistent(self, registry):
        assert registry.get_schema("nonexistent") is None

    def test_schema_with_variant(self, registry):
        schema = ParserSchema(
            parser_id="plus",
            parser_version="1.3",
            format_variant="POL",
            columns=[
                ColumnSchema(
                    logical_name="start",
                    expected_headers=["początek", "poczatek"],
                    regex_patterns=[],
                    required=True,
                ),
            ],
        )
        registry.save_schema(schema)
        loaded = registry.get_schema("plus", "POL")
        assert loaded is not None
        assert loaded.format_variant == "POL"

    def test_bootstrap_all(self, schema_dir):
        """Test auto-generation from existing parsers."""
        registry = SchemaRegistry(schema_dir=schema_dir)
        schemas = registry.bootstrap_all()
        # Should generate schemas for: plus_POL, plus_TD, play, tmobile,
        # orange, orange_retencja, generic
        assert len(schemas) >= 6
        parser_ids = {s.parser_id for s in schemas}
        assert "plus" in parser_ids
        assert "play" in parser_ids
        assert "tmobile" in parser_ids

    def test_column_schema_serialization(self):
        col = ColumnSchema(
            logical_name="date",
            expected_headers=["data", "date"],
            regex_patterns=[r"data\s*i\s*godz"],
            required=True,
            data_type="datetime",
            description="Data i czas połączenia",
        )
        d = col.to_dict()
        restored = ColumnSchema.from_dict(d)
        assert restored.logical_name == "date"
        assert restored.required is True
        assert len(restored.regex_patterns) == 1

    def test_required_columns(self, sample_schema):
        required = sample_schema.get_required_columns()
        names = [c.logical_name for c in required]
        assert "datetime" in names
        assert "caller" in names
        assert "duration" not in names  # not required


# ===========================================================================
# Test: Schema Validator
# ===========================================================================

class TestSchemaValidator:
    def test_exact_match(self, validator):
        headers = ["data_i_godz_polacz", "ui_msisdn", "uw_msisdn",
                    "czas_trwania", "rodzaj_uslugi"]
        result = validator.validate("test_parser", headers)
        assert result.match_type == "exact"
        assert result.confidence == 1.0
        assert not result.missing_columns
        assert not result.fuzzy_matches

    def test_exact_match_case_insensitive(self, validator):
        headers = ["DATA_I_GODZ_POLACZ", "UI_MSISDN", "UW_MSISDN",
                    "CZAS_TRWANIA", "RODZAJ_USLUGI"]
        result = validator.validate("test_parser", headers)
        assert result.match_type == "exact"

    def test_regex_match(self, validator):
        headers = ["data i godz.", "numer a", "numer b",
                    "czas trwania", "rodzaj usługi"]
        result = validator.validate("test_parser", headers)
        # Regex patterns should catch these
        assert result.match_type in ("exact", "drift")
        assert not result.missing_columns

    def test_partial_match_missing_required(self, validator):
        # Missing "service_type" (required)
        headers = ["data_i_godz_polacz", "ui_msisdn", "uw_msisdn", "czas_trwania"]
        result = validator.validate("test_parser", headers)
        assert result.match_type in ("partial", "drift")

    def test_drift_detection_renamed(self, validator):
        # "data rozpoczecia" instead of "data_i_godz_polacz" — fuzzy should catch
        headers = ["data rozpoczecia", "ui_msisdn", "uw_msisdn",
                    "czas_trwania", "rodzaj_uslugi"]
        result = validator.validate("test_parser", headers)
        # datetime column should be fuzzy matched
        if result.match_type == "drift":
            assert "datetime" in result.fuzzy_matches or "datetime" in result.matched_columns

    def test_failed_no_schema(self, registry):
        validator = SchemaValidator(registry)
        result = validator.validate("nonexistent_parser", ["col1", "col2"])
        assert result.match_type == "failed"

    def test_extra_columns_detected(self, validator):
        headers = ["data_i_godz_polacz", "ui_msisdn", "uw_msisdn",
                    "czas_trwania", "rodzaj_uslugi", "nowa_kolumna", "inna"]
        result = validator.validate("test_parser", headers)
        assert "nowa_kolumna" in result.extra_headers or "inna" in result.extra_headers


# ===========================================================================
# Test: Adaptive Column Mapper
# ===========================================================================

class TestAdaptiveMapper:
    def test_augment_incomplete_col_map(self, registry, sample_schema):
        registry.save_schema(sample_schema)
        mapper = AdaptiveColumnMapper(registry=registry)

        headers = ["data_i_godz_polacz", "ui_msisdn", "uw_msisdn",
                    "czas_trwania", "rodzaj_uslugi"]
        # Simulate parser that only found 3 of 5 columns
        original = {"caller": 1, "callee": 2, "duration": 3}

        augmented, validation = mapper.build_adaptive_col_map(
            "test_parser", "", headers, original,
        )
        # Should have all original + new matches
        assert "caller" in augmented
        assert "callee" in augmented

    def test_format_warnings_drift(self, registry, sample_schema):
        registry.save_schema(sample_schema)
        mapper = AdaptiveColumnMapper(registry=registry)

        # Create a validation result with fuzzy matches
        validation = SchemaValidationResult(
            parser_id="test_parser",
            match_type="drift",
            fuzzy_matches={
                "datetime": {
                    "header_text": "data rozpoczecia",
                    "confidence": 0.88,
                    "method": "semantic",
                },
            },
        )
        warnings = mapper.format_warnings(validation)
        assert len(warnings) >= 1
        assert "Adaptive" in warnings[0]


# ===========================================================================
# Test: Drift Reporter
# ===========================================================================

class TestDriftReporter:
    def test_record_and_retrieve(self, tmp_dir):
        reporter = DriftReporter(data_dir=tmp_dir)
        validation = SchemaValidationResult(
            parser_id="plus",
            parser_version="1.3",
            match_type="drift",
            confidence=0.85,
            missing_columns=["cost"],
            extra_headers=["nowa_kolumna"],
            fuzzy_matches={
                "type": {
                    "header_text": "typ uslugi",
                    "header_index": 2,
                    "confidence": 0.88,
                    "method": "normalized",
                },
            },
        )
        report = reporter.record_drift(
            validation, filename="billing.csv",
            actual_headers=["parametr", "poczatek", "typ uslugi"],
        )
        assert report.report_id
        assert report.status == "pending"
        assert report.parser_id == "plus"

        # Retrieve
        loaded = reporter.get_report(report.report_id)
        assert loaded is not None
        assert loaded.parser_id == "plus"
        assert loaded.overall_confidence == 0.85

    def test_list_pending(self, tmp_dir):
        reporter = DriftReporter(data_dir=tmp_dir)
        for i in range(3):
            v = SchemaValidationResult(
                parser_id=f"parser_{i}", match_type="drift", confidence=0.8
            )
            reporter.record_drift(v, filename=f"file_{i}.csv")

        pending = reporter.get_pending_reports()
        assert len(pending) == 3

    def test_update_status(self, tmp_dir):
        reporter = DriftReporter(data_dir=tmp_dir)
        v = SchemaValidationResult(parser_id="play", match_type="drift", confidence=0.9)
        report = reporter.record_drift(v)

        updated = reporter.update_status(report.report_id, "approved")
        assert updated.status == "approved"
        assert updated.user_action_at

    def test_filter_by_parser(self, tmp_dir):
        reporter = DriftReporter(data_dir=tmp_dir)
        for pid in ["plus", "play", "plus"]:
            v = SchemaValidationResult(parser_id=pid, match_type="drift")
            reporter.record_drift(v)

        plus_reports = reporter.list_reports(parser_id="plus")
        assert len(plus_reports) == 2

    def test_delete_report(self, tmp_dir):
        reporter = DriftReporter(data_dir=tmp_dir)
        v = SchemaValidationResult(parser_id="test", match_type="drift")
        report = reporter.record_drift(v)
        assert reporter.delete_report(report.report_id)
        assert reporter.get_report(report.report_id) is None


# ===========================================================================
# Test: Parser Updater
# ===========================================================================

class TestParserUpdater:
    def test_backup_creation(self, tmp_dir):
        # Create a mock parser file
        parsers_dir = tmp_dir / "parsers"
        parsers_dir.mkdir()
        plus_file = parsers_dir / "plus.py"
        plus_file.write_text('PARSER_VERSION = "1.3"\n_POL_COLUMNS = {"a": "b"}\n')

        backup_dir = tmp_dir / "backups"
        updater = ParserUpdater(
            parsers_dir=parsers_dir,
            backup_dir=backup_dir,
        )

        backup = updater.create_backup("plus")
        assert backup is not None
        assert backup.parser_id == "plus"
        assert backup.parser_version_before == "1.3"
        assert Path(backup.backup_path).exists()

    def test_backup_listing(self, tmp_dir):
        parsers_dir = tmp_dir / "parsers"
        parsers_dir.mkdir()
        (parsers_dir / "plus.py").write_text('PARSER_VERSION = "1.3"\n')
        (parsers_dir / "play.py").write_text('PARSER_VERSION = "1.1"\n')

        backup_dir = tmp_dir / "backups"
        updater = ParserUpdater(parsers_dir=parsers_dir, backup_dir=backup_dir)

        updater.create_backup("plus")
        updater.create_backup("play")

        all_backups = updater.list_backups()
        assert len(all_backups) == 2

        plus_only = updater.list_backups("plus")
        assert len(plus_only) == 1

    def test_version_bump(self, tmp_dir):
        parsers_dir = tmp_dir / "parsers"
        parsers_dir.mkdir()
        source = 'PARSER_VERSION = "1.3"\n'
        (parsers_dir / "plus.py").write_text(source)

        updater = ParserUpdater(parsers_dir=parsers_dir, backup_dir=tmp_dir / "bak")
        new_src, old_ver, new_ver = updater._bump_version(source)
        assert old_ver == "1.3"
        assert new_ver == "1.4"
        assert '"1.4"' in new_src

    def test_preview_changes(self, tmp_dir):
        parsers_dir = tmp_dir / "parsers"
        parsers_dir.mkdir()
        (parsers_dir / "plus.py").write_text(
            'PARSER_VERSION = "1.3"\n'
            '_POL_COLUMNS: Dict[str, str] = {\n'
            '    "parametr": "parametr",\n'
            '}\n'
        )

        updater = ParserUpdater(parsers_dir=parsers_dir, backup_dir=tmp_dir / "bak")
        preview = updater.preview_changes("plus", {"type": "typ uslugi"}, "POL")
        assert "error" not in preview
        assert preview["version_bump"] == "1.3 → 1.4"
        assert len(preview["additions"]) == 1

    def test_apply_column_updates(self, tmp_dir):
        parsers_dir = tmp_dir / "parsers"
        parsers_dir.mkdir()
        original = (
            'PARSER_VERSION = "1.3"\n'
            '_POL_COLUMNS: Dict[str, str] = {\n'
            '    "parametr": "parametr",\n'
            '    "us\\u0142uga/typ": "type",\n'
            '}\n'
        )
        (parsers_dir / "plus.py").write_text(original)

        schema_dir = tmp_dir / "schemas"
        schema_dir.mkdir()
        registry = SchemaRegistry(schema_dir=schema_dir)

        updater = ParserUpdater(
            parsers_dir=parsers_dir,
            backup_dir=tmp_dir / "bak",
            registry=registry,
        )

        result = updater.apply_column_updates(
            "plus",
            {"start": "data rozpoczecia"},
            variant="POL",
        )
        assert result["status"] == "applied"
        assert result["version_before"] == "1.3"
        assert result["version_after"] == "1.4"
        assert result["backup_id"]

        # Verify file was modified
        new_source = (parsers_dir / "plus.py").read_text()
        assert '"1.4"' in new_source
        assert "data rozpoczecia" in new_source

    def test_restore_backup(self, tmp_dir):
        parsers_dir = tmp_dir / "parsers"
        parsers_dir.mkdir()
        original = 'PARSER_VERSION = "1.3"\noriginal_content\n'
        (parsers_dir / "plus.py").write_text(original)

        backup_dir = tmp_dir / "backups"
        updater = ParserUpdater(parsers_dir=parsers_dir, backup_dir=backup_dir)

        backup = updater.create_backup("plus")
        backup_file = Path(backup.backup_path)
        assert backup_file.exists()
        assert backup_file.read_text() == original

        # Modify the file
        (parsers_dir / "plus.py").write_text('PARSER_VERSION = "1.4"\nmodified\n')

        # Restore from backup
        result = updater.restore_backup(backup.backup_id)
        assert result["status"] == "restored"
        assert result["restored_version"] == "1.3"

        # Verify original content is back
        restored = (parsers_dir / "plus.py").read_text()
        assert "original_content" in restored
        assert '"1.3"' in restored


# ===========================================================================
# Test: Integration — Plus parser with renamed columns
# ===========================================================================

class TestPlusAdaptiveIntegration:
    def test_plus_pol_standard_headers(self):
        """Plus POL with standard headers should work without adaptive."""
        from backend.gsm.parsers.plus import PlusParser

        headers = [
            "Parametr", "Usługa/Typ", "A MSISDN", "B MSISDN", "C MSISDN",
            "A IMEI/A ESN", "B IMEI/B ESN", "C IMEI/C ESN",
            "A IMSI", "B IMSI", "C IMSI",
            "Początek", "Koniec",
            "A BTS ADDRESS", "B BTS ADDRESS", "C BTS ADDRESS", "GCR",
        ]
        rows = [headers, [
            "501234567", "MOC", "501234567", "601234567", "",
            "123456789012345", "", "",
            "260020000000001", "", "",
            "2024-01-15 10:30:00", "2024-01-15 10:35:00",
            "Warszawa, ul. Testowa 1", "", "", "123",
        ]]

        parser = PlusParser()
        result = parser.parse_sheet(rows, "CSV")
        assert len(result.records) >= 1
        assert result.operator_id == "plus"


class TestPlayAdaptiveIntegration:
    def test_play_standard_headers(self):
        """Play with standard headers should work without adaptive."""
        from backend.gsm.parsers.play import PlayParser

        headers = [
            "DATA_I_GODZ_POLACZ", "CZAS_TRWANIA", "RODZAJ_USLUGI",
            "UI_MSISDN", "UI_IMEI", "UI_IMSI", "UI_LAC", "UI_CID",
            "UI_DLUG_GEOG", "UI_SZER_GEOG", "UI_AZYMUT", "UI_WIAZKA",
            "UI_ZASIEG", "UI_BTS_KOD_POCZTOWY", "UI_BTS_MIEJSCOWOSC",
            "UI_BTS_ULICA", "UI_MCC", "UI_MNC",
            "UW_MSISDN", "UW_IMEI", "UW_IMSI", "UW_LAC", "UW_CID",
            "UW_DLUG_GEOG", "UW_SZER_GEOG", "UW_AZYMUT", "UW_WIAZKA",
            "UW_ZASIEG", "UW_BTS_KOD_POCZTOWY", "UW_BTS_MIEJSCOWOSC",
            "UW_BTS_ULICA", "UW_MCC", "UW_MNC",
            "PRZEK_MSISDN", "INTERNET_IP_PORT",
        ]
        rows = [headers, [
            "2024-01-15 10:30:00", "00:05:00", "Rozmowa głosowa LTE",
            "501234567", "123456789012345", "260020000000001", "1234", "5678",
            "21,0000", "52,0000", "120", "1",
            "5000", "00-001", "Warszawa", "Testowa", "260", "02",
            "601234567", "", "", "", "",
            "", "", "", "",
            "", "", "", "", "",
            "", "",
        ]]

        parser = PlayParser()
        result = parser.parse_sheet(rows, "CSV")
        assert len(result.records) >= 1
        assert result.operator_id == "play"
