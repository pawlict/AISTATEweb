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
from backend.gsm.imei_db import (
    lookup_imei, extract_tac, lookup_imeis, get_db_stats, DeviceInfo,
    normalize_imei, validate_imei, _luhn_check_digit,
)


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


def _make_tmobile_billing_rows() -> List[List[Any]]:
    """Build synthetic T-Mobile billing rows matching real column layout.

    Real T-Mobile columns:
    MSISDN | IMEI | IMSI | Data i godz. | Rozmówca | Nr powiązany |
    Długość | Kierunek | Dane wysłane | Usługa |
    System obsługujacy połaczenie | Publiczne Ip |
    BTS X | BTS Y | CI | LAC | Azymut | Wiązka |
    BTS R | BTS kod | BTS Miasto | BTS Ulica | Kraj | Operator
    """
    rows: List[List[Any]] = []

    # Header row (24 columns)
    rows.append([
        "MSISDN", "IMEI", "IMSI", "Data i godz.", "Rozmówca", "Nr powiązany",
        "Długość", "Kierunek", "Dane wysłane", "Usługa",
        "System obsługujacy połaczenie", "Publiczne Ip",
        "BTS X", "BTS Y", "CI", "LAC", "Azymut", "Wiązka",
        "BTS R", "BTS kod", "BTS Miasto", "BTS Ulica", "Kraj", "Operator",
    ])

    # Data rows
    rows.append([
        "501234567", "351234567890123", "260010012345678",
        "01.03.2026 08:15:30", "601234567", "",
        "02:35", "wychodzące", "", "Rozmowa telefoniczna",
        "GSM", "",
        "21.0123", "52.2345", "12345", "4567", "120", "A",
        "R1", "BTS001", "Warszawa", "ul. Testowa 1", "Polska", "Orange",
    ])
    rows.append([
        "501234567", "351234567890123", "260010012345678",
        "01.03.2026 09:00:00", "602345678", "",
        "", "wychodzące", "", "SMS",
        "GSM", "",
        "21.0123", "52.2345", "12345", "4567", "120", "A",
        "R1", "BTS001", "Warszawa", "ul. Testowa 1", "Polska", "Play",
    ])
    rows.append([
        "501234567", "351234567890123", "260010012345678",
        "01.03.2026 12:30:45", "603456789", "",
        "05:12", "przychodzące", "", "Rozmowa telefoniczna",
        "GSM", "",
        "20.5678", "50.1234", "23456", "5678", "240", "B",
        "R2", "BTS002", "Kraków", "ul. Inna 5", "Polska", "T-Mobile",
    ])
    rows.append([
        "501234567", "351234567890123", "260010012345678",
        "02.03.2026 14:20:00", "", "",
        "", "", "1024", "Internet",
        "LTE", "10.0.0.1",
        "20.5678", "50.1234", "23456", "5678", "240", "B",
        "R2", "BTS002", "Kraków", "ul. Inna 5", "Polska", "",
    ])
    rows.append([
        "501234567", "351234567890123", "260010012345678",
        "02.03.2026 18:45:10", "604567890", "",
        "15:00", "wychodzące", "", "Rozmowa telefoniczna",
        "GSM", "",
        "21.0123", "52.2345", "12346", "4567", "60", "C",
        "R1", "BTS003", "Warszawa", "ul. Nowa 3", "Polska", "Plus",
    ])
    rows.append([
        "501234567", "351234567890123", "260010012345678",
        "03.03.2026 23:15:00", "605678901", "",
        "", "wychodzące", "", "SMS",
        "GSM", "",
        "18.6789", "54.3456", "34567", "6789", "0", "A",
        "R3", "BTS004", "Gdańsk", "ul. Morska 10", "Polska", "Orange",
    ])
    rows.append([
        "501234567", "351234567890123", "260010012345678",
        "03.03.2026 02:30:00", "606789012", "",
        "01:05", "wychodzące", "", "Rozmowa telefoniczna",
        "GSM", "",
        "18.6789", "54.3456", "34567", "6789", "0", "A",
        "R3", "BTS004", "Gdańsk", "ul. Morska 10", "Polska", "Play",
    ])

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
        # Play CSV format uses distinctive column headers
        headers = [
            "data_i_godz_polacz", "czas_trwania", "rodzaj_uslugi",
            "ui_msisdn", "ui_imei", "ui_imsi", "ui_lac", "ui_cid",
        ]
        parser_cls, score = detect_operator(headers, ["csv"])
        assert parser_cls is not None
        assert parser_cls.OPERATOR_ID == "play"

    def test_detect_orange(self):
        headers = ["orange polska", "ptk centertel", "numer b", "typ połączenia"]
        parser_cls, score = detect_operator(headers, ["orange biling", "połączenia"])
        assert parser_cls is not None
        assert parser_cls.OPERATOR_ID == "orange"

    def test_detect_plus(self):
        # Plus CSV POL format uses distinctive column headers
        headers = [
            "parametr", "usługa/typ", "a msisdn", "b msisdn", "c msisdn",
            "a imei/a esn", "b imei/b esn", "c imei/c esn",
            "a imsi", "b imsi", "c imsi",
            "początek", "koniec",
            "a bts address", "b bts address", "c bts address", "gcr",
        ]
        parser_cls, score = detect_operator(headers, ["csv"])
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
    def test_parse_real_format(self):
        """Test T-Mobile parser with real column layout."""
        parser = TMobileParser()
        rows = _make_tmobile_billing_rows()
        result = parser.parse_sheet(rows, "T-Mobile Biling")

        assert result.operator_id == "tmobile"
        assert len(result.records) == 7

        # Check first record (outgoing call)
        r0 = result.records[0]
        assert r0.datetime == "2026-03-01 08:15:30"
        assert r0.record_type == "CALL_OUT"
        assert r0.duration_seconds == 155  # 02:35
        assert r0.caller == "+48501234567"
        assert r0.callee == "+48601234567"
        assert r0.network == "Orange"
        assert "Warszawa" in r0.location

        # Check SMS record
        r1 = result.records[1]
        assert r1.record_type == "SMS_OUT"

        # Check incoming call
        r2 = result.records[2]
        assert r2.record_type == "CALL_IN"
        assert r2.duration_seconds == 312  # 05:12

        # Check data record
        r3 = result.records[3]
        assert r3.record_type == "DATA"
        assert r3.data_volume_kb == 1024.0

        # Check BTS extra fields
        assert r0.extra.get("bts_x") == "21.0123"
        assert r0.extra.get("azimuth") == "120"

    def test_subscriber_from_data_rows(self):
        """T-Mobile parser extracts subscriber MSISDN from data rows."""
        parser = TMobileParser()
        rows = _make_tmobile_billing_rows()
        result = parser.parse_sheet(rows, "Biling")

        assert result.subscriber.msisdn == "+48501234567"
        assert result.subscriber.imsi == "260010012345678"
        assert result.subscriber.imei == "351234567890123"

    def test_detect_tmobile_by_headers(self):
        """T-Mobile detection by distinctive column names."""
        rows = _make_tmobile_billing_rows()
        headers = [str(c).strip().lower() for c in rows[0] if c is not None]
        sheet_names = ["biling"]
        parser_cls, score = detect_operator(headers, sheet_names)
        assert parser_cls is not None
        assert parser_cls.OPERATOR_ID == "tmobile"

    def test_roaming_detection(self):
        """Records with non-Polish country should be marked as roaming."""
        parser = TMobileParser()
        rows = _make_tmobile_billing_rows()
        # Change last row's country to Germany
        rows[-1][22] = "Niemcy"
        result = parser.parse_sheet(rows, "Biling")
        roaming_records = [r for r in result.records if r.roaming]
        assert len(roaming_records) == 1
        assert roaming_records[0].roaming_country == "Niemcy"

    def test_record_type_classification(self):
        """Test T-Mobile specific record type classification."""
        classify = TMobileParser._classify_tmobile_record
        assert classify("wychodzące", "Rozmowa telefoniczna") == "CALL_OUT"
        assert classify("przychodzące", "Rozmowa telefoniczna") == "CALL_IN"
        assert classify("wychodzące", "SMS") == "SMS_OUT"
        assert classify("przychodzące", "SMS") == "SMS_IN"
        assert classify("", "Internet") == "DATA"
        assert classify("wychodzące", "MMS") == "MMS_OUT"
        assert classify("przekierowanie", "Rozmowa telefoniczna") == "CALL_FORWARDED"


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

# ---------------------------------------------------------------------------
# Tests: IMEI / TAC device identification
# ---------------------------------------------------------------------------

class TestImeiDb:
    def test_extract_tac_basic(self):
        assert extract_tac("354236140123456") == "35423614"

    def test_extract_tac_with_separators(self):
        assert extract_tac("35-4236-14-012345-6") == "35423614"

    def test_extract_tac_short(self):
        assert extract_tac("12345") == ""

    def test_extract_tac_empty(self):
        assert extract_tac("") == ""

    def test_lookup_known_imei(self):
        # iPhone 14 — TAC 35423614
        result = lookup_imei("354236140123456")
        assert result is not None
        assert result.brand == "Apple"
        assert "iPhone 14" in result.model
        assert result.device_type == "smartphone"
        assert result.display_name == "Apple iPhone 14"

    def test_lookup_unknown_imei(self):
        result = lookup_imei("999999990000000")
        assert result is None

    def test_lookup_samsung(self):
        # Galaxy S23 Ultra — TAC 35387723
        result = lookup_imei("353877230000000")
        assert result is not None
        assert result.brand == "Samsung"
        assert "S23 Ultra" in result.model

    def test_lookup_xiaomi(self):
        # Redmi Note 12 — TAC 86459007
        result = lookup_imei("864590070000000")
        assert result is not None
        assert result.brand == "Xiaomi"

    def test_lookup_imeis_batch(self):
        results = lookup_imeis([
            "354236140123456",  # iPhone 14
            "353877230000000",  # Galaxy S23 Ultra
            "999999990000000",  # unknown
        ])
        assert len(results) == 2
        assert "354236140123456" in results
        assert "999999990000000" not in results

    def test_db_stats(self):
        stats = get_db_stats()
        assert stats["total_entries"] > 50
        assert "Apple" in stats["brands"]
        assert "Samsung" in stats["brands"]
        assert "smartphone" in stats["types"]

    def test_device_info_display_name(self):
        d = DeviceInfo(brand="Apple", model="iPhone 15 Pro")
        assert d.display_name == "Apple iPhone 15 Pro"

    def test_device_info_empty(self):
        d = DeviceInfo()
        assert d.display_name == ""

    def test_analyzer_identifies_devices(self):
        """Analyzer should populate devices list from record IMEIs."""
        records = [
            BillingRecord(
                datetime="2026-03-01 08:00:00",
                record_type="CALL_OUT",
                callee="+48601234567",
                imei="354236140123456",  # iPhone 14
                duration_seconds=60,
            ),
            BillingRecord(
                datetime="2026-03-02 09:00:00",
                record_type="SMS_OUT",
                callee="+48601234567",
                imei="354236140123456",  # same iPhone 14
            ),
        ]
        result = BillingParseResult(
            operator="Test",
            records=records,
            subscriber=SubscriberInfo(msisdn="+48501234567", imei="354236140123456"),
        )
        result.summary = compute_summary(records)
        analysis = analyze_billing(result)
        assert len(analysis.devices) >= 1
        dev = analysis.devices[0]
        assert dev["brand"] == "Apple"
        assert dev["known"] is True
        assert dev["record_count"] == 2

    def test_analyzer_imei_changes_with_device_names(self):
        """IMEI changes should include device names when available."""
        records = [
            BillingRecord(
                datetime="2026-03-01 08:00:00",
                record_type="CALL_OUT",
                callee="+48601234567",
                imei="354236140123456",  # iPhone 14
                duration_seconds=60,
            ),
            BillingRecord(
                datetime="2026-03-10 09:00:00",
                record_type="CALL_OUT",
                callee="+48601234567",
                imei="353877230000000",  # Galaxy S23 Ultra
                duration_seconds=120,
            ),
        ]
        result = BillingParseResult(
            operator="Test",
            records=records,
            subscriber=SubscriberInfo(msisdn="+48501234567"),
        )
        result.summary = compute_summary(records)
        analysis = analyze_billing(result)
        assert len(analysis.imei_changes) == 1
        ch = analysis.imei_changes[0]
        assert "old_device" in ch
        assert "Apple" in ch["old_device"]
        assert "new_device" in ch
        assert "Samsung" in ch["new_device"]

    # --- IMEI normalization & validation (Luhn) ---

    def test_luhn_check_digit(self):
        # Known IMEI: 490154203237518 → check digit = 8
        assert _luhn_check_digit("49015420323751") == "8"

    def test_normalize_14_to_15(self):
        """14-digit IMEI should get Luhn check digit appended."""
        result = normalize_imei("49015420323751")
        assert len(result) == 15
        assert result == "490154203237518"

    def test_normalize_15_passthrough(self):
        """15-digit IMEI should pass through unchanged."""
        assert normalize_imei("490154203237518") == "490154203237518"

    def test_normalize_16_imeisv(self):
        """16-digit IMEISV should be truncated to 15 with check digit."""
        result = normalize_imei("4901542032375199")  # 16 digits
        assert len(result) == 15
        assert result[:14] == "49015420323751"

    def test_normalize_with_separators(self):
        result = normalize_imei("49-0154-2032-3751")
        assert result == "490154203237518"

    def test_normalize_empty(self):
        assert normalize_imei("") == ""

    def test_validate_valid_imei(self):
        assert validate_imei("490154203237518") is True

    def test_validate_invalid_imei(self):
        assert validate_imei("490154203237519") is False  # wrong check digit

    def test_validate_short(self):
        assert validate_imei("12345") is False

    def test_normalize_in_records(self):
        """normalize_records should normalize 14-digit IMEIs to 15."""
        records = [
            BillingRecord(
                datetime="2026-03-01 08:00:00",
                record_type="CALL_OUT",
                callee="+48601234567",
                imei="49015420323751",  # 14 digits
                duration_seconds=60,
            ),
        ]
        result = BillingParseResult(
            operator="Test",
            records=records,
            subscriber=SubscriberInfo(
                msisdn="+48501234567",
                imei="49015420323751",
            ),
        )
        result.summary = compute_summary(records)
        from backend.gsm.normalize import normalize_records
        normalized = normalize_records(result)
        assert len(normalized.records[0].imei) == 15
        assert len(normalized.subscriber.imei) == 15


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
