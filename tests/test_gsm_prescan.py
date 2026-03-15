"""Tests for backend.gsm.subscriber_prescan — multi-subscriber detection."""

from __future__ import annotations

import csv
import io
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

import pytest

from backend.gsm.subscriber_prescan import (
    FileSubscriberInfo,
    SubscriberGrouping,
    _canonical,
    _normalize_phone,
    _prescan_play,
    _prescan_plus_pol,
    _prescan_plus_td,
    _prescan_xlsx_metadata,
    group_by_subscriber,
    is_same_subscriber,
    prescan_subscriber,
)


# ---------------------------------------------------------------------------
# Fixtures — helpers to create temp billing files
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_dir(tmp_path):
    return tmp_path


def _write_csv(tmp_dir: Path, name: str, content: str, encoding: str = "cp1250") -> Path:
    p = tmp_dir / name
    p.write_bytes(content.encode(encoding))
    return p


def _write_xlsx(tmp_dir: Path, name: str, rows: List[List[Any]]) -> Path:
    """Create a minimal XLSX file with given rows."""
    try:
        from openpyxl import Workbook
    except ImportError:
        pytest.skip("openpyxl not installed")
    p = tmp_dir / name
    wb = Workbook()
    ws = wb.active
    for row in rows:
        ws.append(row)
    wb.save(p)
    wb.close()
    return p


# Fake ScannedFile for group_by_subscriber
@dataclass
class FakeScannedFile:
    filename: str
    path: Path
    operator_id: str = ""
    operator: str = ""
    confidence: float = 0.9


# ===========================================================================
# Phone number helpers
# ===========================================================================

class TestNormalizePhone:
    def test_bare_9_digits(self):
        assert _normalize_phone("501234567") == "+48501234567"

    def test_with_country_code(self):
        assert _normalize_phone("48501234567") == "+48501234567"

    def test_with_plus(self):
        assert _normalize_phone("+48501234567") == "+48501234567"

    def test_with_spaces(self):
        assert _normalize_phone("501 234 567") == "+48501234567"

    def test_empty(self):
        assert _normalize_phone("") == ""

    def test_international(self):
        result = _normalize_phone("0049170123456")
        assert result.startswith("+")


class TestIsSameSubscriber:
    def test_same_9_digits(self):
        assert is_same_subscriber("+48501234567", "48501234567") is True

    def test_different_numbers(self):
        assert is_same_subscriber("+48501234567", "+48609876543") is False

    def test_bare_9_digits(self):
        assert is_same_subscriber("501234567", "+48501234567") is True

    def test_empty_a(self):
        assert is_same_subscriber("", "+48501234567") is False

    def test_empty_both(self):
        assert is_same_subscriber("", "") is False


class TestCanonical:
    def test_normalizes_to_plus48(self):
        assert _canonical("+48501234567") == "+48501234567"

    def test_bare_digits(self):
        assert _canonical("501234567") == "+48501234567"

    def test_with_48_prefix(self):
        assert _canonical("48501234567") == "+48501234567"


# ===========================================================================
# Plus POL prescan
# ===========================================================================

class TestPrescanPlusPol:
    def test_detects_msisdn_from_parametr(self, tmp_dir):
        content = (
            '"Nr","Poc","Kon","Czas","Typ","Nr A","Nr B","Nr C","Parametr"\n'
            '"1","2024-01-01 10:00:00","2024-01-01 10:05:00","300","MOC","501234567","609876543","","501234567"\n'
            '"2","2024-01-01 11:00:00","2024-01-01 11:02:00","120","MOC","501234567","601111111","","501234567"\n'
        )
        p = _write_csv(tmp_dir, "plus_pol.csv", content)
        result = _prescan_plus_pol(p)
        assert result is not None
        assert "501234567" in result

    def test_returns_none_without_parametr(self, tmp_dir):
        content = '"Nr","Poc","Kon","Czas","Typ"\n"1","2024-01-01","2024-01-01","300","MOC"\n'
        p = _write_csv(tmp_dir, "no_param.csv", content)
        result = _prescan_plus_pol(p)
        assert result is None

    def test_empty_file(self, tmp_dir):
        p = _write_csv(tmp_dir, "empty.csv", "")
        result = _prescan_plus_pol(p)
        assert result is None


# ===========================================================================
# Plus TD prescan
# ===========================================================================

class TestPrescanPlusTd:
    def test_detects_msisdn_from_column(self, tmp_dir):
        content = (
            '"Parametr","Start","Koniec","Czas","Wolumen","KB","MSISDN","IMEI","IMSI"\n'
            '"501234567","2024-01-01 10:00:00","2024-01-01 10:05:00","300","5","1024","501234567","123456789012345","260011234567890"\n'
        )
        p = _write_csv(tmp_dir, "plus_td.csv", content)
        result = _prescan_plus_td(p)
        assert result is not None
        assert "501234567" in result

    def test_returns_none_no_msisdn_col(self, tmp_dir):
        content = '"Col1","Col2","Col3"\n"a","b","c"\n'
        p = _write_csv(tmp_dir, "no_msisdn.csv", content)
        result = _prescan_plus_td(p)
        assert result is None


# ===========================================================================
# Play prescan
# ===========================================================================

class TestPrescanPlay:
    def test_frequency_analysis(self, tmp_dir):
        header = "DATA_I_GODZ_POLACZ;CZAS_TRWANIA;RODZAJ_USLUGI;UI_MSISDN;UW_MSISDN\n"
        rows = ""
        # Subscriber 501234567 appears most often (as UI_MSISDN in outgoing)
        for i in range(50):
            rows += f"2024-01-01 10:{i:02d}:00;120;MOC;501234567;60{i:07d}\n"
        # A few other numbers
        for i in range(5):
            rows += f"2024-01-01 11:{i:02d}:00;60;MTC;60{i:07d};501234567\n"

        content = header + rows
        p = _write_csv(tmp_dir, "play.csv", content, encoding="cp1250")
        result = _prescan_play(p)
        assert result is not None
        assert "501234567" in result

    def test_empty_csv(self, tmp_dir):
        p = _write_csv(tmp_dir, "empty_play.csv", "")
        result = _prescan_play(p)
        assert result is None

    def test_no_phone_columns(self, tmp_dir):
        content = "COL_A;COL_B;COL_C\na;b;c\n"
        p = _write_csv(tmp_dir, "nophone.csv", content, encoding="cp1250")
        result = _prescan_play(p)
        assert result is None


# ===========================================================================
# XLSX metadata prescan (T-Mobile / Orange)
# ===========================================================================

class TestPrescanXlsxMetadata:
    def test_detects_msisdn_from_metadata(self, tmp_dir):
        rows = [
            ["Identyfikator zlecenia:", "10222118"],
            ["MSISDN:", "48697890632"],
            ["Data od:", "2023-10-14 12:00:00"],
            [],
            ["MSISDN", "Data", "Rozmówca", "Kierunek"],
            ["48697890632", "2024-01-01", "601234567", "Wychodzące"],
        ]
        p = _write_xlsx(tmp_dir, "tmobile.xlsx", rows)
        result = _prescan_xlsx_metadata(p, max_rows=10)
        assert result is not None
        assert "697890632" in result

    def test_detects_phone_in_cell(self, tmp_dir):
        rows = [
            ["Abonent:", "Jan Kowalski"],
            ["+48501234567", None, None],
            [],
            ["Nr", "Data", "Rozmówca"],
        ]
        p = _write_xlsx(tmp_dir, "orange.xlsx", rows)
        result = _prescan_xlsx_metadata(p, max_rows=10)
        assert result is not None
        assert "501234567" in result

    def test_no_msisdn_in_metadata(self, tmp_dir):
        rows = [
            ["Header1", "Header2"],
            ["val1", "val2"],
        ]
        p = _write_xlsx(tmp_dir, "no_msisdn.xlsx", rows)
        result = _prescan_xlsx_metadata(p, max_rows=10)
        assert result is None


# ===========================================================================
# prescan_subscriber dispatcher
# ===========================================================================

class TestPrescanSubscriber:
    def test_plus_operator(self, tmp_dir):
        content = (
            '"Nr","Poc","Kon","Czas","Typ","Nr A","Nr B","Nr C","Parametr"\n'
            '"1","2024-01-01 10:00:00","2024-01-01 10:05:00","300","MOC","501234567","609876543","","501234567"\n'
        )
        p = _write_csv(tmp_dir, "plus.csv", content)
        fsi = prescan_subscriber("plus.csv", p, "plus")
        assert fsi.msisdn != ""
        assert fsi.confidence > 0.5
        assert "501234567" in fsi.msisdn

    def test_unknown_operator_csv(self, tmp_dir):
        # Should try Play-style frequency as fallback for unknown CSV
        header = "DATA_I_GODZ_POLACZ;CZAS_TRWANIA;RODZAJ_USLUGI;UI_MSISDN;UW_MSISDN\n"
        rows = "2024-01-01 10:00:00;120;MOC;501234567;609876543\n" * 20
        p = _write_csv(tmp_dir, "unknown.csv", header + rows, encoding="cp1250")
        fsi = prescan_subscriber("unknown.csv", p, "")
        assert fsi.msisdn != ""
        assert "501234567" in fsi.msisdn

    def test_corrupt_file_returns_zero_confidence(self, tmp_dir):
        p = tmp_dir / "corrupt.xlsx"
        p.write_bytes(b"\x00\x01\x02\x03invalid")
        fsi = prescan_subscriber("corrupt.xlsx", p, "tmobile")
        assert fsi.confidence == 0.0

    def test_nonexistent_file(self, tmp_dir):
        p = tmp_dir / "nonexistent.csv"
        fsi = prescan_subscriber("nonexistent.csv", p, "plus")
        assert fsi.confidence == 0.0


# ===========================================================================
# group_by_subscriber
# ===========================================================================

class TestGroupBySubscriber:
    def test_single_file_always_single(self, tmp_dir):
        p = tmp_dir / "single.csv"
        p.write_text("dummy", encoding="utf-8")
        files = [FakeScannedFile("single.csv", p, "plus")]
        result = group_by_subscriber(files)
        assert result.is_single_subscriber is True

    def test_same_subscriber_two_files(self, tmp_dir):
        # Both files have same MSISDN in Parametr column
        content1 = (
            '"Nr","Poc","Kon","Czas","Typ","Nr A","Nr B","Nr C","Parametr"\n'
            '"1","2024-01-01","2024-01-01","300","MOC","501234567","609876543","","501234567"\n'
        )
        content2 = (
            '"Parametr","Start","Koniec","Czas","Wolumen","KB","MSISDN","IMEI","IMSI"\n'
            '"501234567","2024-01-01","2024-01-01","300","5","1024","501234567","123456789012345","260011234567890"\n'
        )
        p1 = _write_csv(tmp_dir, "pol.csv", content1)
        p2 = _write_csv(tmp_dir, "td.csv", content2)
        files = [
            FakeScannedFile("pol.csv", p1, "plus"),
            FakeScannedFile("td.csv", p2, "plus"),
        ]
        result = group_by_subscriber(files)
        assert result.is_single_subscriber is True
        assert len(result.subscribers) == 1

    def test_different_subscribers(self, tmp_dir):
        content1 = (
            '"Nr","Poc","Kon","Czas","Typ","Nr A","Nr B","Nr C","Parametr"\n'
            '"1","2024-01-01","2024-01-01","300","MOC","501234567","609876543","","501234567"\n'
        )
        content2 = (
            '"Nr","Poc","Kon","Czas","Typ","Nr A","Nr B","Nr C","Parametr"\n'
            '"1","2024-01-01","2024-01-01","300","MOC","609876543","501234567","","609876543"\n'
        )
        p1 = _write_csv(tmp_dir, "person1.csv", content1)
        p2 = _write_csv(tmp_dir, "person2.csv", content2)
        files = [
            FakeScannedFile("person1.csv", p1, "plus"),
            FakeScannedFile("person2.csv", p2, "plus"),
        ]
        result = group_by_subscriber(files)
        assert result.is_single_subscriber is False
        assert len(result.subscribers) == 2

    def test_undetectable_files_fallback(self, tmp_dir):
        # Both files have no recognisable subscriber data
        p1 = _write_csv(tmp_dir, "a.csv", "col1,col2\nval1,val2\n")
        p2 = _write_csv(tmp_dir, "b.csv", "col1,col2\nval1,val2\n")
        files = [
            FakeScannedFile("a.csv", p1, "plus"),
            FakeScannedFile("b.csv", p2, "plus"),
        ]
        result = group_by_subscriber(files)
        # All undetectable → treat as single subscriber (fallback)
        assert result.is_single_subscriber is True
        assert len(result.undetected_files) == 2

    def test_mixed_detected_and_undetected(self, tmp_dir):
        content1 = (
            '"Nr","Poc","Kon","Czas","Typ","Nr A","Nr B","Nr C","Parametr"\n'
            '"1","2024-01-01","2024-01-01","300","MOC","501234567","609876543","","501234567"\n'
        )
        p1 = _write_csv(tmp_dir, "detected.csv", content1)
        p2 = _write_csv(tmp_dir, "unknown.csv", "col1,col2\nval1,val2\n")
        files = [
            FakeScannedFile("detected.csv", p1, "plus"),
            FakeScannedFile("unknown.csv", p2, "plus"),
        ]
        result = group_by_subscriber(files)
        # One detected subscriber + one undetected → single subscriber
        assert result.is_single_subscriber is True
        assert len(result.subscribers) == 1
        assert len(result.undetected_files) == 1

    def test_three_subscribers(self, tmp_dir):
        numbers = ["501234567", "609876543", "781112233"]
        files = []
        for i, num in enumerate(numbers):
            content = (
                f'"Nr","Poc","Kon","Czas","Typ","Nr A","Nr B","Nr C","Parametr"\n'
                f'"1","2024-01-01","2024-01-01","300","MOC","{num}","600000000","","{num}"\n'
            )
            p = _write_csv(tmp_dir, f"person{i}.csv", content)
            files.append(FakeScannedFile(f"person{i}.csv", p, "plus"))
        result = group_by_subscriber(files)
        assert result.is_single_subscriber is False
        assert len(result.subscribers) == 3


# ===========================================================================
# Serialisation
# ===========================================================================

class TestSerialisation:
    def test_file_subscriber_info_to_dict(self):
        fsi = FileSubscriberInfo(
            filename="test.csv",
            path=Path("/tmp/test.csv"),
            operator_id="plus",
            msisdn="+48501234567",
            confidence=0.9,
            detail="Parametr column",
        )
        d = fsi.to_dict()
        assert d["filename"] == "test.csv"
        assert d["msisdn"] == "+48501234567"
        assert d["confidence"] == 0.9

    def test_subscriber_grouping_to_dict(self):
        fsi = FileSubscriberInfo(
            filename="test.csv",
            path=Path("/tmp/test.csv"),
            operator_id="plus",
            msisdn="+48501234567",
            confidence=0.9,
        )
        g = SubscriberGrouping(
            is_single_subscriber=False,
            subscribers={"+48501234567": [fsi]},
            undetected_files=[],
        )
        d = g.to_dict()
        assert d["is_single_subscriber"] is False
        assert "+48501234567" in d["subscribers"]
        assert len(d["subscribers"]["+48501234567"]) == 1
        assert d["undetected_files"] == []


# ===========================================================================
# Play with XLSX (T-Mobile style) — cross-format test
# ===========================================================================

class TestCrossFormat:
    def test_tmobile_xlsx_and_plus_csv_same_subscriber(self, tmp_dir):
        """T-Mobile XLSX + Plus CSV for same person → single subscriber."""
        # Plus CSV
        csv_content = (
            '"Nr","Poc","Kon","Czas","Typ","Nr A","Nr B","Nr C","Parametr"\n'
            '"1","2024-01-01","2024-01-01","300","MOC","697890632","601234567","","697890632"\n'
        )
        p_csv = _write_csv(tmp_dir, "plus.csv", csv_content)

        # T-Mobile XLSX
        xlsx_rows = [
            ["MSISDN:", "48697890632"],
            [],
            ["MSISDN", "Data", "Rozmówca"],
            ["48697890632", "2024-01-01", "601234567"],
        ]
        p_xlsx = _write_xlsx(tmp_dir, "tmobile.xlsx", xlsx_rows)

        files = [
            FakeScannedFile("plus.csv", p_csv, "plus"),
            FakeScannedFile("tmobile.xlsx", p_xlsx, "tmobile"),
        ]
        result = group_by_subscriber(files)
        assert result.is_single_subscriber is True

    def test_tmobile_xlsx_and_plus_csv_different_subscribers(self, tmp_dir):
        """T-Mobile XLSX + Plus CSV for different people → multi subscriber."""
        csv_content = (
            '"Nr","Poc","Kon","Czas","Typ","Nr A","Nr B","Nr C","Parametr"\n'
            '"1","2024-01-01","2024-01-01","300","MOC","501234567","601234567","","501234567"\n'
        )
        p_csv = _write_csv(tmp_dir, "plus.csv", csv_content)

        xlsx_rows = [
            ["MSISDN:", "48697890632"],
            [],
            ["MSISDN", "Data", "Rozmówca"],
            ["48697890632", "2024-01-01", "601234567"],
        ]
        p_xlsx = _write_xlsx(tmp_dir, "tmobile.xlsx", xlsx_rows)

        files = [
            FakeScannedFile("plus.csv", p_csv, "plus"),
            FakeScannedFile("tmobile.xlsx", p_xlsx, "tmobile"),
        ]
        result = group_by_subscriber(files)
        assert result.is_single_subscriber is False
        assert len(result.subscribers) == 2
