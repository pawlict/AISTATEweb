"""Tests for GSM billing parsers and pipeline."""

from __future__ import annotations

import pytest
from pathlib import Path
from typing import Any, Dict, List

from backend.gsm.parsers.base import (
    BillingParser,
    BillingRecord,
    BillingParseResult,
    SubscriberInfo,
    BillingSummary,
    compute_summary,
)
from backend.gsm.parsers.registry import detect_operator, get_parser
from backend.gsm.parsers.tmobile import TMobileParser
from backend.gsm.parsers.play import PlayParser
from backend.gsm.parsers.orange import OrangeParser
from backend.gsm.parsers.plus import PlusParser
from backend.gsm.parsers.generic import GenericBillingParser
from backend.gsm.normalize import normalize_records, extract_contact_numbers
from backend.gsm.subscriber import parse_subscriber_file
from backend.gsm.analyzer import analyze_billing


# ---------------------------------------------------------------------------
# Helper: build fake billing sheet rows
# ---------------------------------------------------------------------------

def _make_billing_rows(
    operator_hint: str = "",
    include_header_meta: bool = True,
) -> List[List[Any]]:
    """Build synthetic billing sheet rows for testing."""
    rows: List[List[Any]] = []

    if include_header_meta:
        rows.append([f"Biling {operator_hint}", None, None, None, None, None, None])
        rows.append(["Numer telefonu:", "501234567", None, None, None, None, None])
        rows.append(["IMSI:", "260010012345678", None, None, None, None, None])
        rows.append(["Abonent:", "Jan Kowalski", None, None, None, None, None])
        rows.append([None, None, None, None, None, None, None])

    # Header row
    rows.append([
        "Data i czas", "Numer B", "Typ połączenia", "Czas trwania",
        "Koszt netto", "Lokalizacja", "Sieć docelowa",
    ])

    # Data rows
    rows.append(["01.03.2026 08:15:30", "601234567", "Połączenie wychodzące", "02:35", 0.50, "Warszawa BTS-001", "Orange"])
    rows.append(["01.03.2026 09:00:00", "602345678", "SMS wychodzący", "00:00", 0.10, "Warszawa BTS-001", "Play"])
    rows.append(["01.03.2026 12:30:45", "501234567", "Połączenie przychodzące", "05:12", 0.00, "Kraków BTS-002", "T-Mobile"])
    rows.append(["02.03.2026 14:20:00", "603456789", "Transmisja danych", "00:00", 0.00, "Kraków BTS-002", ""])
    rows.append(["02.03.2026 18:45:10", "604567890", "Połączenie wychodzące", "15:00", 1.20, "Warszawa BTS-003", "Plus"])
    rows.append(["03.03.2026 23:15:00", "605678901", "SMS wychodzący", "00:00", 0.08, "Gdańsk BTS-004", "Orange"])
    rows.append(["03.03.2026 02:30:00", "606789012", "Połączenie wychodzące", "01:05", 0.15, "Gdańsk BTS-004", "Play"])

    return rows


def _make_subscriber_rows_tabular() -> List[List[Any]]:
    """Build synthetic subscriber ID file rows (tabular format)."""
    return [
        ["Dane abonenta", None, None, None, None],
        ["MSISDN", "IMSI", "IMEI", "Nazwisko", "Adres"],
        ["501234567", "260010012345678", "351234567890123", "Jan Kowalski", "ul. Testowa 1, Warszawa"],
    ]


def _make_subscriber_rows_kv() -> List[List[Any]]:
    """Build synthetic subscriber ID file rows (key-value format)."""
    return [
        ["Numer telefonu:", "501234567"],
        ["IMSI:", "260010012345678"],
        ["IMEI:", "351234567890123"],
        ["Abonent:", "Jan Kowalski"],
        ["Adres:", "ul. Testowa 1, Warszawa"],
        ["Plan taryfowy:", "Bez Limitu 100"],
        ["Data aktywacji:", "01.01.2020"],
    ]


# ---------------------------------------------------------------------------
# Tests: Base utilities
# ---------------------------------------------------------------------------

class TestBillingParserHelpers:
    def test_normalize_phone_9digits(self):
        assert BillingParser.normalize_phone("501234567") == "+48501234567"

    def test_normalize_phone_with_prefix(self):
        assert BillingParser.normalize_phone("+48501234567") == "+48501234567"

    def test_normalize_phone_48_prefix(self):
        assert BillingParser.normalize_phone("48501234567") == "+48501234567"

    def test_normalize_phone_00_prefix(self):
        assert BillingParser.normalize_phone("0048501234567") == "+48501234567"

    def test_normalize_phone_with_spaces(self):
        assert BillingParser.normalize_phone("501 234 567") == "+48501234567"

    def test_normalize_phone_with_dashes(self):
        assert BillingParser.normalize_phone("501-234-567") == "+48501234567"

    def test_normalize_phone_empty(self):
        assert BillingParser.normalize_phone("") == ""

    def test_parse_duration_hhmmss(self):
        assert BillingParser.parse_duration("01:23:45") == 5025

    def test_parse_duration_mmss(self):
        assert BillingParser.parse_duration("02:35") == 155

    def test_parse_duration_seconds(self):
        assert BillingParser.parse_duration("45") == 45

    def test_parse_duration_polish(self):
        assert BillingParser.parse_duration("1godz 23min 45sek") == 5025

    def test_parse_duration_empty(self):
        assert BillingParser.parse_duration("") == 0

    def test_parse_datetime_ddmmyyyy(self):
        assert BillingParser.parse_datetime("01.03.2026", "08:15:30") == "2026-03-01 08:15:30"

    def test_parse_datetime_combined(self):
        assert BillingParser.parse_datetime("01.03.2026 08:15:30") == "2026-03-01 08:15:30"

    def test_parse_datetime_iso(self):
        assert BillingParser.parse_datetime("2026-03-01", "08:15") == "2026-03-01 08:15:00"

    def test_parse_datetime_no_time(self):
        assert BillingParser.parse_datetime("01.03.2026") == "2026-03-01 00:00:00"

    def test_parse_datetime_yy(self):
        assert BillingParser.parse_datetime("01.03.26") == "2026-03-01 00:00:00"

    def test_classify_record_type_polish(self):
        assert BillingParser.classify_record_type("Połączenie wychodzące") == "CALL_OUT"
        assert BillingParser.classify_record_type("SMS wychodzący") == "SMS_OUT"
        assert BillingParser.classify_record_type("Transmisja danych") == "DATA"
        assert BillingParser.classify_record_type("Połączenie przychodzące") == "CALL_IN"

    def test_classify_record_type_unknown(self):
        assert BillingParser.classify_record_type("XYZABC") == "OTHER"

    def test_classify_record_type_empty(self):
        assert BillingParser.classify_record_type("") == "OTHER"

    def test_get_cell_safe(self):
        row = ["a", "b", None, "d"]
        assert BillingParser.get_cell(row, 0) == "a"
        assert BillingParser.get_cell(row, 2) == ""
        assert BillingParser.get_cell(row, 10) == ""
        assert BillingParser.get_cell(row, None) == ""

    def test_get_cell_float(self):
        row = [1.5, "2,50", None, "abc"]
        assert BillingParser.get_cell_float(row, 0) == 1.5
        assert BillingParser.get_cell_float(row, 1) == 2.5
        assert BillingParser.get_cell_float(row, 2) is None
        assert BillingParser.get_cell_float(row, 3) is None

    def test_find_header_row(self):
        rows = _make_billing_rows()
        idx = BillingParser.find_header_row(
            rows,
            required_keywords=["data", "numer", "typ"],
        )
        assert idx is not None
        # Header should be at index 5 (after 5 meta rows)
        assert idx == 5

    def test_build_column_map(self):
        header = ["Data i czas", "Numer B", "Typ połączenia", "Czas trwania", "Koszt netto"]
        patterns = {
            "date": [r"data"],
            "callee": [r"numer\s*b"],
            "record_type": [r"typ"],
            "duration": [r"czas\s*trwania"],
            "cost": [r"koszt"],
        }
        col_map = BillingParser.build_column_map(header, patterns)
        assert col_map["date"] == 0
        assert col_map["callee"] == 1
        assert col_map["record_type"] == 2
        assert col_map["duration"] == 3
        assert col_map["cost"] == 4


# ---------------------------------------------------------------------------
# Tests: Data models
# ---------------------------------------------------------------------------

class TestDataModels:
    def test_billing_record_auto_date(self):
        r = BillingRecord(datetime="2026-03-01 08:15:30")
        assert r.date == "2026-03-01"
        assert r.time == "08:15:30"

    def test_billing_record_to_dict(self):
        r = BillingRecord(datetime="2026-03-01 08:15:30", caller="+48501234567")
        d = r.to_dict()
        assert d["datetime"] == "2026-03-01 08:15:30"
        assert d["caller"] == "+48501234567"

    def test_subscriber_info_to_dict(self):
        s = SubscriberInfo(msisdn="+48501234567", owner_name="Jan Kowalski")
        d = s.to_dict()
        assert d["msisdn"] == "+48501234567"
        assert d["owner_name"] == "Jan Kowalski"

    def test_compute_summary(self):
        records = [
            BillingRecord(datetime="2026-03-01 08:15:30", callee="+48601234567",
                          record_type="CALL_OUT", duration_seconds=155, cost=0.50),
            BillingRecord(datetime="2026-03-01 09:00:00", callee="+48602345678",
                          record_type="SMS_OUT", cost=0.10),
            BillingRecord(datetime="2026-03-01 12:30:45", caller="+48601234567",
                          record_type="CALL_IN", duration_seconds=312),
            BillingRecord(datetime="2026-03-02 14:20:00", record_type="DATA",
                          data_volume_kb=1024.0),
        ]
        s = compute_summary(records)
        assert s.total_records == 4
        assert s.calls_out == 1
        assert s.calls_in == 1
        assert s.sms_out == 1
        assert s.data_sessions == 1
        assert s.total_duration_seconds == 467
        assert s.total_data_kb == 1024.0
        assert s.total_cost == pytest.approx(0.60)
        assert s.period_from == "2026-03-01"
        assert s.period_to == "2026-03-02"


# ---------------------------------------------------------------------------
# Tests: Operator detection
# ---------------------------------------------------------------------------

class TestOperatorDetection:
    def test_detect_tmobile(self):
        headers = ["t-mobile polska", "ptc", "numer b", "typ połączenia"]
        parser_cls, score = detect_operator(headers, ["t-mobile biling", "połączenia"])
        assert parser_cls is not None
        assert parser_cls.OPERATOR_ID == "tmobile"

    def test_detect_play(self):
        headers = ["play mobile", "p4 sp", "numer b", "typ połączenia"]
        parser_cls, score = detect_operator(headers, ["play biling", "połączenia"])
        assert parser_cls is not None
        assert parser_cls.OPERATOR_ID == "play"

    def test_detect_orange(self):
        headers = ["orange polska", "ptk centertel", "numer b", "typ połączenia"]
        parser_cls, score = detect_operator(headers, ["orange biling", "połączenia"])
        assert parser_cls is not None
        assert parser_cls.OPERATOR_ID == "orange"

    def test_detect_plus(self):
        headers = ["plus gsm", "polkomtel", "numer b", "typ połączenia"]
        parser_cls, score = detect_operator(headers, ["plus biling", "połączenia"])
        assert parser_cls is not None
        assert parser_cls.OPERATOR_ID == "plus"

    def test_detect_unknown_falls_back(self):
        parser = get_parser(["data", "col2"], ["sheet1"])
        assert parser.OPERATOR_ID == "generic"


# ---------------------------------------------------------------------------
# Tests: Generic parser
# ---------------------------------------------------------------------------

class TestGenericParser:
    def test_parse_synthetic_billing(self):
        parser = GenericBillingParser()
        rows = _make_billing_rows()
        result = parser.parse_sheet(rows, "Arkusz1")

        assert result.operator_id == "generic"
        assert len(result.records) == 7
        assert result.records[0].datetime == "2026-03-01 08:15:30"
        assert result.records[0].record_type == "CALL_OUT"
        assert result.records[0].duration_seconds == 155
        assert result.records[0].cost == pytest.approx(0.50)

    def test_parse_empty_sheet(self):
        parser = GenericBillingParser()
        result = parser.parse_sheet([], "Empty")
        assert len(result.records) == 0
        assert "Pusty arkusz" in result.warnings[0]

    def test_parse_no_header(self):
        parser = GenericBillingParser()
        rows = [["abc", "def"], ["ghi", "jkl"]]
        result = parser.parse_sheet(rows, "NoHeader")
        assert len(result.records) == 0


# ---------------------------------------------------------------------------
# Tests: T-Mobile parser
# ---------------------------------------------------------------------------

class TestTMobileParser:
    def test_parse_synthetic(self):
        parser = TMobileParser()
        rows = _make_billing_rows("T-Mobile")
        result = parser.parse_sheet(rows, "T-Mobile Biling")

        assert result.operator_id == "tmobile"
        assert len(result.records) == 7

    def test_subscriber_extraction(self):
        parser = TMobileParser()
        rows = _make_billing_rows("T-Mobile")
        result = parser.parse_sheet(rows, "Biling")

        assert result.subscriber.msisdn == "+48501234567"
        assert "kowalski" in result.subscriber.owner_name.lower()


# ---------------------------------------------------------------------------
# Tests: Normalization
# ---------------------------------------------------------------------------

class TestNormalization:
    def test_normalize_records(self):
        result = BillingParseResult(
            subscriber=SubscriberInfo(msisdn="+48501234567"),
            records=[
                BillingRecord(datetime="2026-03-01 08:15:30",
                              caller="501234567", callee="601234567",
                              record_type="CALL_OUT", duration_seconds=155),
                BillingRecord(datetime="2026-03-01 09:00:00",
                              caller="501234567", callee="601234567",
                              record_type="SMS_OUT"),
            ],
        )
        normalized = normalize_records(result)
        assert normalized.records[0].caller == "+48501234567"
        assert normalized.records[0].callee == "+48601234567"

    def test_deduplicate(self):
        result = BillingParseResult(
            records=[
                BillingRecord(datetime="2026-03-01 08:15:30",
                              caller="+48501234567", callee="+48601234567",
                              record_type="CALL_OUT", duration_seconds=155),
                BillingRecord(datetime="2026-03-01 08:15:30",
                              caller="+48501234567", callee="+48601234567",
                              record_type="CALL_OUT", duration_seconds=155),
            ],
        )
        normalized = normalize_records(result)
        assert len(normalized.records) == 1

    def test_extract_contacts(self):
        records = [
            BillingRecord(datetime="2026-03-01 08:15:30",
                          caller="+48501234567", callee="+48601234567",
                          record_type="CALL_OUT"),
            BillingRecord(datetime="2026-03-01 09:00:00",
                          caller="+48501234567", callee="+48601234567",
                          record_type="SMS_OUT"),
            BillingRecord(datetime="2026-03-01 10:00:00",
                          caller="+48501234567", callee="+48602345678",
                          record_type="CALL_OUT"),
        ]
        contacts = extract_contact_numbers(records, {"+48501234567"})
        assert contacts["+48601234567"] == 2
        assert contacts["+48602345678"] == 1


# ---------------------------------------------------------------------------
# Tests: Subscriber file parsing
# ---------------------------------------------------------------------------

class TestSubscriberParsing:
    def test_tabular_format(self):
        rows = _make_subscriber_rows_tabular()
        subs = parse_subscriber_file(rows)
        assert len(subs) == 1
        assert subs[0].msisdn == "+48501234567"

    def test_key_value_format(self):
        rows = _make_subscriber_rows_kv()
        subs = parse_subscriber_file(rows)
        assert len(subs) == 1
        assert subs[0].msisdn == "+48501234567"
        assert subs[0].owner_name == "Jan Kowalski"

    def test_empty_file(self):
        subs = parse_subscriber_file([])
        assert len(subs) == 0


# ---------------------------------------------------------------------------
# Tests: Analyzer
# ---------------------------------------------------------------------------

class TestAnalyzer:
    def test_analyze_billing(self):
        result = BillingParseResult(
            subscriber=SubscriberInfo(msisdn="+48501234567"),
            records=[
                BillingRecord(datetime="2026-03-01 08:15:30",
                              callee="+48601234567", record_type="CALL_OUT",
                              duration_seconds=155, cost=0.50,
                              location="Warszawa BTS-001"),
                BillingRecord(datetime="2026-03-01 09:00:00",
                              callee="+48602345678", record_type="SMS_OUT",
                              cost=0.10),
                BillingRecord(datetime="2026-03-01 23:30:00",
                              callee="+48601234567", record_type="CALL_OUT",
                              duration_seconds=65, cost=0.15,
                              location="Warszawa BTS-001"),
                BillingRecord(datetime="2026-03-02 14:20:00",
                              callee="+48603456789", record_type="DATA",
                              data_volume_kb=1024.0),
            ],
        )

        analysis = analyze_billing(result)

        assert len(analysis.top_contacts) > 0
        assert analysis.top_contacts[0].number == "+48601234567"
        assert analysis.top_contacts[0].total_interactions == 2

        assert analysis.temporal.hourly_distribution.get(8) == 1
        assert analysis.temporal.hourly_distribution.get(23) == 1

        assert analysis.avg_call_duration > 0
        assert analysis.busiest_date == "2026-03-01"

    def test_analyze_empty(self):
        result = BillingParseResult()
        analysis = analyze_billing(result)
        assert analysis.top_contacts == []
        assert analysis.busiest_date == ""


# ---------------------------------------------------------------------------
# Tests: BillingParseResult serialization
# ---------------------------------------------------------------------------

class TestSerialization:
    def test_full_result_to_dict(self):
        result = BillingParseResult(
            operator="T-Mobile Polska",
            operator_id="tmobile",
            subscriber=SubscriberInfo(msisdn="+48501234567"),
            records=[
                BillingRecord(datetime="2026-03-01 08:15:30",
                              record_type="CALL_OUT", duration_seconds=155),
            ],
            summary=BillingSummary(total_records=1, calls_out=1),
            warnings=["Test warning"],
        )
        d = result.to_dict()
        assert d["operator"] == "T-Mobile Polska"
        assert len(d["records"]) == 1
        assert d["summary"]["total_records"] == 1
        assert "Test warning" in d["warnings"]
