"""Base class and data structures for GSM billing parsers."""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class BillingRecord:
    """Single CDR (Call Detail Record) from a billing file."""

    datetime: str = ""            # YYYY-MM-DD HH:MM:SS
    date: str = ""                # YYYY-MM-DD (convenience, derived from datetime)
    time: str = ""                # HH:MM:SS   (convenience, derived from datetime)
    caller: str = ""              # MSISDN A (numer dzwoniącego / nadawcy)
    callee: str = ""              # MSISDN B (numer wywoływany / odbiorca)
    record_type: str = ""         # CALL_OUT | CALL_IN | CALL_FORWARDED |
                                  # SMS_OUT | SMS_IN | MMS_OUT | MMS_IN |
                                  # DATA | USSD | VOICEMAIL | OTHER
    duration_seconds: int = 0     # czas trwania (sekundy) — 0 for SMS/data
    data_volume_kb: float = 0.0   # wolumen danych (KB) — only for DATA records
    cost: Optional[float] = None  # koszt netto (PLN)
    cost_gross: Optional[float] = None  # koszt brutto (PLN)
    location: str = ""            # lokalizacja BTS / Cell ID
    location_lac: str = ""        # LAC (Location Area Code)
    location_cell_id: str = ""    # Cell ID
    roaming: bool = False         # czy roaming
    roaming_country: str = ""     # kraj roamingu (jeśli dotyczy)
    network: str = ""             # sieć docelowa (np. Orange, Play)
    imsi: str = ""                # IMSI użyte w tej sesji
    imei: str = ""                # IMEI użyte w tej sesji
    raw_row: int = 0              # numer wiersza w XLSX (debugging)
    raw_text: str = ""            # oryginalny wiersz (debugging)
    extra: Dict[str, Any] = field(default_factory=dict)  # dodatkowe pola operatora

    def __post_init__(self):
        # Auto-derive date/time from datetime if not set
        if self.datetime and not self.date:
            parts = self.datetime.split(" ", 1)
            self.date = parts[0]
            if len(parts) > 1 and not self.time:
                self.time = parts[1]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SubscriberInfo:
    """Subscriber identification data (from billing header or separate ID file)."""

    msisdn: str = ""               # numer telefonu (np. +48501234567)
    imsi: str = ""                 # IMSI
    imei: str = ""                 # IMEI (lub lista IMEI)
    owner_name: str = ""           # imię i nazwisko / nazwa firmy
    owner_address: str = ""        # adres
    owner_pesel: str = ""          # PESEL (jeśli dostępny)
    owner_id_number: str = ""      # nr dowodu / paszportu
    activation_date: str = ""      # data aktywacji karty SIM
    tariff: str = ""               # plan taryfowy
    sim_iccid: str = ""            # numer karty SIM (ICCID)
    operator: str = ""             # operator
    contract_type: str = ""        # abonament / prepaid / mix
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class BillingSummary:
    """Aggregate statistics for a billing period."""

    total_records: int = 0
    calls_out: int = 0
    calls_in: int = 0
    sms_out: int = 0
    sms_in: int = 0
    mms_out: int = 0
    mms_in: int = 0
    data_sessions: int = 0
    total_duration_seconds: int = 0
    call_duration_seconds: int = 0
    total_data_kb: float = 0.0
    total_cost: float = 0.0
    total_cost_gross: float = 0.0
    unique_contacts: int = 0
    period_from: str = ""
    period_to: str = ""
    roaming_records: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class BillingParseResult:
    """Complete result of parsing a GSM billing file."""

    operator: str = ""
    operator_id: str = ""
    parser_version: str = "1.0"   # parser version tag
    subscriber: SubscriberInfo = field(default_factory=SubscriberInfo)
    records: List[BillingRecord] = field(default_factory=list)
    summary: BillingSummary = field(default_factory=BillingSummary)
    warnings: List[str] = field(default_factory=list)
    sheet_name: str = ""          # which XLSX sheet was parsed
    parse_method: str = "xlsx"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "operator": self.operator,
            "operator_id": self.operator_id,
            "parser_version": self.parser_version,
            "subscriber": self.subscriber.to_dict(),
            "records": [r.to_dict() for r in self.records],
            "summary": self.summary.to_dict(),
            "warnings": self.warnings,
            "sheet_name": self.sheet_name,
            "parse_method": self.parse_method,
        }


# ---------------------------------------------------------------------------
# Record type constants
# ---------------------------------------------------------------------------

RECORD_TYPES = {
    "CALL_OUT",
    "CALL_IN",
    "CALL_FORWARDED",
    "SMS_OUT",
    "SMS_IN",
    "MMS_OUT",
    "MMS_IN",
    "DATA",
    "USSD",
    "VOICEMAIL",
    "OTHER",
}

# Common Polish billing type labels → normalized record_type
TYPE_LABEL_MAP: Dict[str, str] = {
    # Calls
    "połączenie wychodzące": "CALL_OUT",
    "połączenie przychodzące": "CALL_IN",
    "pol. wychodzące": "CALL_OUT",
    "pol. przychodzące": "CALL_IN",
    "rozmowa wychodząca": "CALL_OUT",
    "rozmowa przychodząca": "CALL_IN",
    "połączenie przekierowane": "CALL_FORWARDED",
    "przekierowanie": "CALL_FORWARDED",
    "voice out": "CALL_OUT",
    "voice in": "CALL_IN",
    "call out": "CALL_OUT",
    "call in": "CALL_IN",
    "wychodzące głosowe": "CALL_OUT",
    "przychodzące głosowe": "CALL_IN",
    "połączenie telefoniczne": "CALL_OUT",
    "połączenie głosowe": "CALL_OUT",
    "próba połączenia": "CALL_OUT",
    "poczta głosowa": "VOICEMAIL",
    "voicemail": "VOICEMAIL",
    # SMS
    "sms wychodzący": "SMS_OUT",
    "sms przychodzący": "SMS_IN",
    "sms wychodz.": "SMS_OUT",
    "sms out": "SMS_OUT",
    "sms in": "SMS_IN",
    "sms": "SMS_OUT",
    "wiadomość sms": "SMS_OUT",
    "wiadomość tekstowa": "SMS_OUT",
    # MMS
    "mms wychodzący": "MMS_OUT",
    "mms przychodzący": "MMS_IN",
    "mms": "MMS_OUT",
    "mms out": "MMS_OUT",
    "mms in": "MMS_IN",
    # Data
    "transmisja danych": "DATA",
    "dane": "DATA",
    "data": "DATA",
    "internet": "DATA",
    "gprs": "DATA",
    "lte": "DATA",
    "pakiet danych": "DATA",
    "transfer danych": "DATA",
    # USSD
    "ussd": "USSD",
}


# ---------------------------------------------------------------------------
# Abstract parser base class
# ---------------------------------------------------------------------------

class BillingParser(ABC):
    """Abstract GSM billing parser for XLSX files.

    Each operator-specific parser inherits from this class and implements
    detection logic and row parsing.
    """

    # Subclass must set these
    OPERATOR_NAME: str = ""
    OPERATOR_ID: str = ""
    PARSER_VERSION: str = "1.0"  # version tag: 1.<sequential>, increment on changes

    # Column header patterns for auto-detection (case-insensitive regex)
    # Matched against header row cells joined with '|'
    DETECT_HEADER_PATTERNS: List[str] = []

    # Sheet name patterns (case-insensitive regex)
    DETECT_SHEET_PATTERNS: List[str] = []

    @classmethod
    def can_parse(cls, headers: List[str], sheet_names: List[str]) -> float:
        """Return confidence 0.0-1.0 that this parser handles the XLSX file.

        Args:
            headers: Lowercased header cells from first non-empty row.
            sheet_names: Lowercased sheet names in the workbook.
        """
        if not cls.DETECT_HEADER_PATTERNS and not cls.DETECT_SHEET_PATTERNS:
            return 0.0

        score = 0.0
        total_patterns = len(cls.DETECT_HEADER_PATTERNS) + len(cls.DETECT_SHEET_PATTERNS)
        if total_patterns == 0:
            return 0.0

        header_text = "|".join(headers)

        hits = 0
        for pat in cls.DETECT_HEADER_PATTERNS:
            if re.search(pat, header_text, re.I):
                hits += 1

        for pat in cls.DETECT_SHEET_PATTERNS:
            for sn in sheet_names:
                if re.search(pat, sn, re.I):
                    hits += 1
                    break

        return min(hits / total_patterns, 1.0)

    @abstractmethod
    def parse_sheet(
        self,
        rows: List[List[Any]],
        sheet_name: str = "",
    ) -> BillingParseResult:
        """Parse billing records from sheet rows.

        Args:
            rows: All rows from the sheet (list of lists, cell values).
                  First row(s) may be headers.
            sheet_name: Name of the sheet being parsed.

        Returns:
            BillingParseResult with parsed records and metadata.
        """
        ...

    def parse_workbook(
        self,
        sheets: Dict[str, List[List[Any]]],
    ) -> BillingParseResult:
        """Parse entire workbook. Default: parse each sheet and merge results.

        Args:
            sheets: Dict of sheet_name → rows.

        Returns:
            Merged BillingParseResult.
        """
        all_records: List[BillingRecord] = []
        all_warnings: List[str] = []
        subscriber = SubscriberInfo()
        parsed_sheets: List[str] = []

        for sheet_name, rows in sheets.items():
            if not rows:
                continue
            result = self.parse_sheet(rows, sheet_name)
            if result.records:
                all_records.extend(result.records)
                parsed_sheets.append(sheet_name)
            if result.warnings:
                all_warnings.extend(result.warnings)
            # Use subscriber info from first sheet that has it
            if result.subscriber.msisdn and not subscriber.msisdn:
                subscriber = result.subscriber

        # Sort records by datetime
        all_records.sort(key=lambda r: r.datetime)

        merged = BillingParseResult(
            operator=self.OPERATOR_NAME,
            operator_id=self.OPERATOR_ID,
            parser_version=self.PARSER_VERSION,
            subscriber=subscriber,
            records=all_records,
            warnings=all_warnings,
            sheet_name=", ".join(parsed_sheets),
        )
        merged.summary = compute_summary(all_records)
        return merged

    # --- Common helpers for subclasses ---

    @staticmethod
    def find_header_row(
        rows: List[List[Any]],
        required_keywords: List[str],
        max_scan: int = 20,
    ) -> Optional[int]:
        """Find the header row index by searching for required keywords.

        Args:
            rows: Sheet rows.
            required_keywords: Lowercased keywords that must appear in the header.
                At least 2 must match for a row to be considered a header.
            max_scan: Max rows to scan from the top.

        Returns:
            Row index of header, or None if not found.
        """
        min_matches = min(2, len(required_keywords))
        for i, row in enumerate(rows[:max_scan]):
            cells_text = "|".join(
                str(c).strip().lower() for c in row if c is not None
            )
            matches = sum(1 for kw in required_keywords if kw in cells_text)
            if matches >= min_matches:
                return i
        return None

    @staticmethod
    def build_column_map(
        header_row: List[Any],
        column_patterns: Dict[str, List[str]],
    ) -> Dict[str, int]:
        r"""Map logical field names to column indices using regex patterns.

        Args:
            header_row: The header row cells.
            column_patterns: Dict of field_name → list of regex patterns.
                E.g. {"date": [r"data", r"date"], "callee": [r"numer\s*b", r"called"]}

        Returns:
            Dict of field_name → column_index.
        """
        col_map: Dict[str, int] = {}
        for i, cell in enumerate(header_row):
            cell_text = str(cell).strip().lower() if cell is not None else ""
            if not cell_text:
                continue
            for field_name, patterns in column_patterns.items():
                if field_name in col_map:
                    continue  # already mapped
                for pat in patterns:
                    if re.search(pat, cell_text, re.I):
                        col_map[field_name] = i
                        break
        return col_map

    @staticmethod
    def get_cell(row: List[Any], idx: Optional[int], default: str = "") -> str:
        """Safely get a cell value as string."""
        if idx is None or idx >= len(row):
            return default
        val = row[idx]
        if val is None:
            return default
        return str(val).strip()

    @staticmethod
    def get_cell_float(row: List[Any], idx: Optional[int]) -> Optional[float]:
        """Safely get a cell value as float."""
        if idx is None or idx >= len(row):
            return None
        val = row[idx]
        if val is None:
            return None
        if isinstance(val, (int, float)):
            return float(val)
        s = str(val).strip().replace(",", ".").replace(" ", "")
        s = re.sub(r"[^\d.\-+]", "", s)
        try:
            return float(s)
        except ValueError:
            return None

    @staticmethod
    def normalize_phone(number: str) -> str:
        """Normalize phone number to consistent format.

        Strips whitespace, dashes, parentheses. Adds +48 prefix for 9-digit
        Polish numbers without country code.
        """
        if not number:
            return ""
        s = re.sub(r"[\s\-\(\)\.]+", "", number.strip())
        # Remove leading '00' international prefix
        if s.startswith("00") and len(s) > 10:
            s = "+" + s[2:]
        # Add +48 for bare 9-digit Polish numbers
        if re.match(r"^\d{9}$", s):
            s = "+48" + s
        # Ensure + prefix for country code
        if re.match(r"^48\d{9}$", s):
            s = "+" + s
        return s

    @staticmethod
    def parse_duration(text: str) -> int:
        """Parse duration string to seconds.

        Handles formats:
        - "01:23:45" (HH:MM:SS)
        - "23:45" (MM:SS)
        - "45" (seconds)
        - "1h 23m 45s"
        - "83s"
        """
        if not text:
            return 0
        s = str(text).strip()

        # Already numeric (seconds)
        if re.match(r"^\d+$", s):
            return int(s)

        # HH:MM:SS or MM:SS
        m = re.match(r"(\d+):(\d{2}):(\d{2})", s)
        if m:
            return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
        m = re.match(r"(\d+):(\d{2})", s)
        if m:
            return int(m.group(1)) * 60 + int(m.group(2))

        # "1h 23m 45s" format
        total = 0
        for val, unit in re.findall(r"(\d+)\s*(h|m|s|godz|min|sek)", s, re.I):
            n = int(val)
            u = unit.lower()
            if u in ("h", "godz"):
                total += n * 3600
            elif u in ("m", "min"):
                total += n * 60
            else:
                total += n
        return total

    @staticmethod
    def parse_datetime(date_str: str, time_str: str = "") -> str:
        """Parse date and optional time to 'YYYY-MM-DD HH:MM:SS'.

        Handles:
        - date: DD.MM.YYYY, DD-MM-YYYY, DD/MM/YYYY, YYYY-MM-DD
        - time: HH:MM:SS, HH:MM, or empty (defaults to 00:00:00)
        - combined: "DD.MM.YYYY HH:MM:SS"
        """
        if not date_str:
            return ""
        s = str(date_str).strip()

        # If date_str already contains time
        parts = re.split(r"[\sT]+", s, maxsplit=1)
        date_part = parts[0]
        time_part = parts[1] if len(parts) > 1 else str(time_str).strip()

        # Parse date
        dt = None
        # YYYY-MM-DD
        m = re.match(r"(\d{4})-(\d{1,2})-(\d{1,2})", date_part)
        if m:
            dt = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
        else:
            # DD.MM.YYYY or DD-MM-YYYY or DD/MM/YYYY
            m = re.match(r"(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{4})", date_part)
            if m:
                dt = f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
            else:
                # DD.MM.YY
                m = re.match(r"(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{2})$", date_part)
                if m:
                    yy = int(m.group(3))
                    year = 2000 + yy if yy < 80 else 1900 + yy
                    dt = f"{year}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"

        if not dt:
            return ""

        # Parse time
        tm = "00:00:00"
        if time_part:
            m = re.match(r"(\d{1,2}):(\d{2})(?::(\d{2}))?", time_part)
            if m:
                hh = int(m.group(1))
                mm = int(m.group(2))
                ss = int(m.group(3)) if m.group(3) else 0
                tm = f"{hh:02d}:{mm:02d}:{ss:02d}"

        return f"{dt} {tm}"

    @staticmethod
    def classify_record_type(type_label: str) -> str:
        """Classify a billing record type from operator-specific label.

        Performs fuzzy matching against TYPE_LABEL_MAP.
        """
        if not type_label:
            return "OTHER"
        label = type_label.strip().lower()

        # Exact match
        if label in TYPE_LABEL_MAP:
            return TYPE_LABEL_MAP[label]

        # Substring/partial match
        for key, val in TYPE_LABEL_MAP.items():
            if key in label or label in key:
                return val

        # Keyword fallback
        if any(kw in label for kw in ("sms",)):
            return "SMS_OUT"
        if any(kw in label for kw in ("mms",)):
            return "MMS_OUT"
        if any(kw in label for kw in ("dane", "data", "internet", "gprs", "lte")):
            return "DATA"
        if any(kw in label for kw in ("połącz", "rozmow", "voice", "call", "głos")):
            return "CALL_OUT"
        if any(kw in label for kw in ("ussd",)):
            return "USSD"

        return "OTHER"


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------

def compute_summary(records: List[BillingRecord]) -> BillingSummary:
    """Compute aggregate statistics from parsed billing records."""
    summary = BillingSummary()
    summary.total_records = len(records)

    contacts = set()
    for r in records:
        rt = r.record_type
        if rt == "CALL_OUT":
            summary.calls_out += 1
        elif rt == "CALL_IN":
            summary.calls_in += 1
        elif rt == "SMS_OUT":
            summary.sms_out += 1
        elif rt == "SMS_IN":
            summary.sms_in += 1
        elif rt == "MMS_OUT":
            summary.mms_out += 1
        elif rt == "MMS_IN":
            summary.mms_in += 1
        elif rt == "DATA":
            summary.data_sessions += 1

        summary.total_duration_seconds += r.duration_seconds
        if rt in ("CALL_OUT", "CALL_IN"):
            summary.call_duration_seconds += r.duration_seconds
        summary.total_data_kb += r.data_volume_kb

        if r.cost is not None:
            summary.total_cost += r.cost
        if r.cost_gross is not None:
            summary.total_cost_gross += r.cost_gross

        if r.roaming:
            summary.roaming_records += 1

        # Track unique contacts (both caller and callee, excluding own number)
        if r.callee:
            contacts.add(r.callee)
        if r.caller:
            contacts.add(r.caller)

    summary.unique_contacts = len(contacts)

    # Period
    dates = [r.date for r in records if r.date]
    if dates:
        summary.period_from = min(dates)
        summary.period_to = max(dates)

    return summary
