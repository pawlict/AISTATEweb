"""Plus (Polkomtel) Poland GSM billing parser (CSV format).

Handles CSV billing files from Plus / Polkomtel Sp. z o.o.

Two file formats:
- POL (calls/SMS): 17 columns — Parametr, Usługa/Typ, A/B/C MSISDN,
  A/B/C IMEI, A/B/C IMSI, Początek, Koniec, A/B/C BTS ADDRESS, GCR
- TD (data sessions): 9 columns — Parametr, MSISDN, IMEI, IMSI, IP,
  Początek, Koniec, Czas trwania, BTS ADDRESS

Custom quoting format:
- Entire line wrapped in outer double-quotes
- Fields separated by commas
- Non-trivial fields wrapped in escaped double-quotes (two quotes each side)
- Empty fields are four consecutive double-quotes
- Fields may contain commas (e.g. BTS addresses) protected by quoting
- Comma delimiter, cp1250 encoding
"""

from __future__ import annotations

import re
from datetime import datetime as dt_class
from pathlib import Path
from typing import Any, Dict, List, Optional

from .base import (
    BillingParser,
    BillingParseResult,
    BillingRecord,
    SubscriberInfo,
    compute_summary,
)


# ---------------------------------------------------------------------------
# Type code → (base_type, expected_outgoing)
# expected_outgoing: True = subscriber should be party A (originated),
#                    False = subscriber should be party B (terminated),
#                    None = no direction / keep all
# ---------------------------------------------------------------------------

_TYPE_CODE_MAP: Dict[str, tuple] = {
    "MOC":    ("CALL", True),       # Mobile Originated Call
    "MTC":    ("CALL", False),      # Mobile Terminated Call
    "SMO":    ("SMS", True),        # SMS Originated
    "SMT":    ("SMS", False),       # SMS Terminated
    "FORW":   ("CALL_FORWARDED", None),  # Forwarded call
    "UCA":    ("CALL", True),       # Unsuccessful Call Attempt
    "POC":    ("DATA", None),       # Packet Originated Call
    "NGN_O":  ("CALL", True),       # NGN Originated
}


# ---------------------------------------------------------------------------
# POL column name → logical name mapping
# ---------------------------------------------------------------------------

_POL_COLUMNS: Dict[str, str] = {
    "parametr": "parametr",
    "us\u0142uga/typ": "type",        # Usługa/Typ
    "usluga/typ": "type",             # ASCII fallback
    "a msisdn": "a_msisdn",
    "b msisdn": "b_msisdn",
    "c msisdn": "c_msisdn",
    "a imei/a esn": "a_imei",
    "b imei/b esn": "b_imei",
    "c imei/c esn": "c_imei",
    "a imsi": "a_imsi",
    "b imsi": "b_imsi",
    "c imsi": "c_imsi",
    "pocz\u0105tek": "start",         # Początek
    "poczatek": "start",              # ASCII fallback
    "koniec": "end",
    "a bts address": "a_bts",
    "b bts address": "b_bts",
    "c bts address": "c_bts",
    "gcr": "gcr",
}

# TD column name → logical name mapping
_TD_COLUMNS: Dict[str, str] = {
    "parametr": "parametr",
    "msisdn": "msisdn",
    "imei": "imei",
    "imsi": "imsi",
    "ip": "ip",
    "pocz\u0105tek": "start",         # Początek
    "poczatek": "start",              # ASCII fallback
    "koniec": "end",
    "czas trwania": "duration",
    "bts address": "bts",
}


# ---------------------------------------------------------------------------
# Custom CSV line parser for Plus quoting format
# ---------------------------------------------------------------------------

def _parse_plus_line(line: str) -> List[str]:
    """Parse a Plus CSV line with custom quoting.

    Format: entire line wrapped in outer double-quotes, fields separated by
    commas, non-trivial fields wrapped in pairs of escaped double-quotes,
    empty fields are four consecutive double-quotes, fields may contain
    commas (e.g. BTS addresses) protected by quoting.
    """
    # Strip trailing whitespace/tabs
    line = line.rstrip("\t\r\n ")

    # Remove outer quotes
    if len(line) >= 2 and line[0] == '"' and line[-1] == '"':
        line = line[1:-1]

    # Strip trailing tabs/spaces inside outer quotes
    line = line.rstrip("\t ")

    if not line:
        return []

    fields: List[str] = []
    i = 0
    n = len(line)

    while i < n:
        if i < n - 1 and line[i] == '"' and line[i + 1] == '"':
            # Quoted field — skip opening ""
            i += 2
            start = i
            while i < n:
                if i < n - 1 and line[i] == '"' and line[i + 1] == '"':
                    # Potential closing "" — must be followed by comma or end
                    if i + 2 >= n or line[i + 2] == ",":
                        fields.append(line[start:i])
                        i += 2  # skip closing ""
                        if i < n and line[i] == ",":
                            i += 1  # skip comma separator
                        break
                    else:
                        # "" inside quoted field (rare) — skip
                        i += 2
                else:
                    i += 1
            else:
                # End of line without proper closing
                fields.append(line[start:])
        else:
            # Unquoted field — read until comma
            start = i
            while i < n and line[i] != ",":
                i += 1
            fields.append(line[start:i])
            if i < n:
                i += 1  # skip comma

    return fields


def _get(row: List[Any], idx: Optional[int]) -> str:
    """Get cell value as cleaned string."""
    if idx is None or idx >= len(row):
        return ""
    val = row[idx]
    if val is None:
        return ""
    return str(val).strip()


def _compute_duration_seconds(start_str: str, end_str: str) -> int:
    """Compute duration in seconds from start/end timestamps.

    Args:
        start_str: Start timestamp (YYYY-MM-DD HH:MM:SS)
        end_str: End timestamp (YYYY-MM-DD HH:MM:SS)

    Returns:
        Duration in seconds, or 0 if parsing fails.
    """
    if not start_str or not end_str:
        return 0
    try:
        fmt = "%Y-%m-%d %H:%M:%S"
        t_start = dt_class.strptime(start_str.strip(), fmt)
        t_end = dt_class.strptime(end_str.strip(), fmt)
        delta = (t_end - t_start).total_seconds()
        return max(0, int(delta))
    except (ValueError, TypeError):
        return 0


def _is_subscriber_match(digits: str, sub_digits: str) -> bool:
    """Check if digits match subscriber's number (last 9 digits)."""
    if not digits or not sub_digits:
        return False
    if len(digits) >= 9 and len(sub_digits) >= 9:
        return digits[-9:] == sub_digits[-9:]
    return digits == sub_digits


def _is_phone(text: str) -> bool:
    """Check if text looks like a phone number (7+ digits)."""
    if not text:
        return False
    digits = re.sub(r"[\s\-\+\(\)\.]+", "", text)
    return bool(re.match(r"^\d{7,15}$", digits))


def _parse_bts_address(bts: str) -> Dict[str, str]:
    """Parse Plus BTS ADDRESS into city/street components.

    Plus BTS ADDRESS formats:
    - "GDAŃSK, UL. GRUNWALDZKA 123"
    - "WARSZAWA MOKOTÓW, MARSZAŁKOWSKA 10"
    - plain text like "BTS-12345"

    Returns dict with bts_city and bts_street (may be empty).
    """
    if not bts:
        return {"bts_city": "", "bts_street": ""}
    parts = bts.split(",", 1)
    city = parts[0].strip()
    street = parts[1].strip() if len(parts) > 1 else ""
    # Don't treat BTS codes as city names
    if re.match(r"^[A-Z0-9\-_]+$", city) and len(city) < 5:
        return {"bts_city": "", "bts_street": ""}
    return {"bts_city": city, "bts_street": street}


# ---------------------------------------------------------------------------
# CSV loading
# ---------------------------------------------------------------------------

def load_plus_csv(
    path: Path,
    max_rows: int = 200_000,
) -> Dict[str, List[List[Any]]]:
    """Load a Plus CSV file and return it in the sheets dict format.

    Uses custom line parser for Plus quoting format.
    Tries cp1250 first (standard Polish encoding), then UTF-8, then latin-1.

    Returns:
        Dict with single key "CSV" -> list of rows (list of cell values).
    """
    for encoding in ("cp1250", "utf-8-sig", "utf-8", "latin-1"):
        try:
            with open(path, "r", encoding=encoding, errors="strict") as f:
                rows: List[List[Any]] = []
                for i, line in enumerate(f):
                    if i >= max_rows:
                        break
                    parsed = _parse_plus_line(line)
                    if parsed:
                        rows.append(parsed)
                return {"CSV": rows}
        except (UnicodeDecodeError, UnicodeError):
            continue

    # Last resort: read with errors='replace'
    with open(path, "r", encoding="cp1250", errors="replace") as f:
        rows = []
        for i, line in enumerate(f):
            if i >= max_rows:
                break
            parsed = _parse_plus_line(line)
            if parsed:
                rows.append(parsed)
        return {"CSV": rows}


def is_plus_csv(path: Path) -> bool:
    """Quick check if a CSV file is a Plus billing.

    Reads only the first line and checks for distinctive Plus CSV columns.
    Handles both POL format (Usługa/Typ) and TD format (Czas trwania).
    """
    for encoding in ("cp1250", "utf-8-sig", "utf-8", "latin-1"):
        try:
            with open(path, "r", encoding=encoding, errors="strict") as f:
                first_line = f.readline()

            # Parse the header with custom parser
            fields = _parse_plus_line(first_line)
            if not fields:
                return False

            header_lower = [f.strip().lower() for f in fields]

            # Must have "parametr" as first column
            if not header_lower or header_lower[0] != "parametr":
                return False

            # POL format: has "usługa/typ" or "usluga/typ"
            has_pol = any("uga/typ" in h for h in header_lower)
            # TD format: has "czas trwania"
            has_td = any("czas trwania" in h for h in header_lower)

            return has_pol or has_td
        except (UnicodeDecodeError, UnicodeError):
            continue
    return False


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

class PlusParser(BillingParser):
    """Parser for Plus / Polkomtel billing CSV files.

    Handles two CSV formats:
    - POL: calls and SMS (17 columns) with A/B/C party structure
    - TD: data sessions (9 columns) with single subscriber

    Custom CSV quoting with outer "..." wrapper and ""..."" field delimiters.
    """

    OPERATOR_NAME = "Plus (Polkomtel)"
    OPERATOR_ID = "plus"
    PARSER_VERSION = "1.3"

    # Detection patterns for both POL and TD formats
    DETECT_HEADER_PATTERNS = [
        r"us[łl]uga/typ",              # POL: "Usługa/Typ" — very distinctive
        r"\ba\s+msisdn\b",             # POL: "A MSISDN"
        r"\bb\s+msisdn\b",             # POL: "B MSISDN"
        r"\ba\s+bts\s+address\b",      # POL: "A BTS ADDRESS"
        r"\bgcr\b",                    # POL: "GCR"
        r"\bbts\s+address\b",          # Both: "BTS ADDRESS"
        r"\bczas\s+trwania\b",         # TD: "Czas trwania"
        r"\bparametr\b",               # Both: "Parametr"
    ]

    DETECT_SHEET_PATTERNS = []

    # ------------------------------------------------------------------
    # Main parse entry point
    # ------------------------------------------------------------------

    def parse_sheet(
        self,
        rows: List[List[Any]],
        sheet_name: str = "",
    ) -> BillingParseResult:
        result = BillingParseResult(
            operator=self.OPERATOR_NAME,
            operator_id=self.OPERATOR_ID,
            parser_version=self.PARSER_VERSION,
            sheet_name=sheet_name or "CSV",
            parse_method="csv",
        )

        if not rows:
            result.warnings.append("Pusty plik CSV")
            return result

        # Find header row (should be first row)
        header_idx = None
        for i, row in enumerate(rows[:10]):
            if not row:
                continue
            header_lower = [str(c).strip().lower() for c in row]
            if header_lower and header_lower[0] == "parametr":
                header_idx = i
                break

        if header_idx is None:
            result.warnings.append("Nie znaleziono nagłówka CSV Plus")
            return result

        # Build column index map
        header_row = rows[header_idx]
        header_lower = [str(c).strip().lower() if c else "" for c in header_row]

        # Determine format: POL or TD
        is_pol = any("uga/typ" in h for h in header_lower)
        is_td = any("czas trwania" in h for h in header_lower) and not is_pol

        if is_pol:
            return self._parse_pol(rows, header_idx, header_lower, result)
        elif is_td:
            return self._parse_td(rows, header_idx, header_lower, result)
        else:
            result.warnings.append(
                "Nie rozpoznano formatu CSV Plus (POL/TD)"
            )
            return result

    # ------------------------------------------------------------------
    # POL format (calls/SMS) — 17 columns
    # ------------------------------------------------------------------

    def _parse_pol(
        self,
        rows: List[List[Any]],
        header_idx: int,
        header_lower: List[str],
        result: BillingParseResult,
    ) -> BillingParseResult:
        """Parse Plus POL format (calls/SMS with A/B/C party structure)."""

        # Build column map by header name
        col_map: Dict[str, int] = {}
        for i, h in enumerate(header_lower):
            logical = _POL_COLUMNS.get(h)
            if logical and logical not in col_map:
                col_map[logical] = i

        # Adaptive fallback: try fuzzy matching if critical columns missing
        if "start" not in col_map or "type" not in col_map:
            try:
                from .adaptive_mapper import AdaptiveColumnMapper
                mapper = AdaptiveColumnMapper()
                col_map, validation = mapper.build_adaptive_col_map(
                    "plus", "POL", header_lower, col_map,
                )
                result.warnings.extend(mapper.format_warnings(validation))
            except Exception:
                pass  # adaptive layer is optional — never block parsing

        if "start" not in col_map:
            result.warnings.append("Nie znaleziono kolumny 'Początek'")
            return result

        result.warnings.append(
            f"Plus POL CSV — kolumny: {list(col_map.keys())} ({len(col_map)})"
        )

        # Detect subscriber from Parametr column
        subscriber_msisdn = ""
        for row in rows[header_idx + 1: header_idx + 10]:
            if not row:
                continue
            param = _get(row, col_map.get("parametr"))
            if param and re.match(r"^\d{6,15}$", param):
                subscriber_msisdn = self.normalize_phone(param)
                break

        sub_digits = re.sub(r"[^\d]", "", subscriber_msisdn)

        subscriber = SubscriberInfo(
            operator=self.OPERATOR_NAME,
            msisdn=subscriber_msisdn,
        )

        skipped_companion = 0

        # Parse data rows
        for row_idx, row in enumerate(
            rows[header_idx + 1:], start=header_idx + 2
        ):
            if not row or all(
                c is None or str(c).strip() == "" for c in row
            ):
                continue

            start_str = _get(row, col_map.get("start"))
            if not start_str:
                continue

            dt = self.parse_datetime(start_str)
            if not dt:
                continue

            type_code = _get(row, col_map.get("type")).strip().upper()
            a_msisdn = _get(row, col_map.get("a_msisdn"))
            b_msisdn = _get(row, col_map.get("b_msisdn"))
            c_msisdn = _get(row, col_map.get("c_msisdn"))

            a_digits = re.sub(r"[^\d]", "", a_msisdn)
            b_digits = re.sub(r"[^\d]", "", b_msisdn)

            # Get type info
            type_info = _TYPE_CODE_MAP.get(type_code, ("OTHER", None))
            base_type, expected_outgoing = type_info

            # Determine direction and validate subscriber position
            # Skip companion rows (duplicate perspective of same call)
            is_outgoing = None
            caller = ""
            callee = ""
            sub_bts = ""
            sub_imei = ""
            sub_imsi = ""

            if expected_outgoing is True:
                # Originated: subscriber should be party A
                if sub_digits and not _is_subscriber_match(a_digits, sub_digits):
                    # Companion row — skip
                    skipped_companion += 1
                    continue
                is_outgoing = True
                caller = a_msisdn
                callee = b_msisdn
                sub_bts = _get(row, col_map.get("a_bts"))
                sub_imei = _get(row, col_map.get("a_imei"))
                sub_imsi = _get(row, col_map.get("a_imsi"))

            elif expected_outgoing is False:
                # Terminated: subscriber should be party B
                if sub_digits and not _is_subscriber_match(b_digits, sub_digits):
                    # Companion row — skip
                    skipped_companion += 1
                    continue
                is_outgoing = False
                caller = a_msisdn
                callee = b_msisdn
                sub_bts = _get(row, col_map.get("b_bts"))
                sub_imei = _get(row, col_map.get("b_imei"))
                sub_imsi = _get(row, col_map.get("b_imsi"))

            elif base_type == "CALL_FORWARDED":
                # Forwarded: subscriber can be any party (A, B, or C)
                if _is_subscriber_match(a_digits, sub_digits):
                    is_outgoing = True
                    sub_bts = _get(row, col_map.get("a_bts"))
                    sub_imei = _get(row, col_map.get("a_imei"))
                    sub_imsi = _get(row, col_map.get("a_imsi"))
                elif _is_subscriber_match(b_digits, sub_digits):
                    is_outgoing = False
                    sub_bts = _get(row, col_map.get("b_bts"))
                    sub_imei = _get(row, col_map.get("b_imei"))
                    sub_imsi = _get(row, col_map.get("b_imsi"))
                else:
                    # C party or unknown — keep anyway
                    sub_bts = _get(row, col_map.get("c_bts"))
                    sub_imei = _get(row, col_map.get("c_imei"))
                    sub_imsi = _get(row, col_map.get("c_imsi"))
                caller = a_msisdn
                callee = b_msisdn

            elif base_type == "DATA":
                # Data: subscriber is party A
                is_outgoing = True
                caller = a_msisdn
                callee = b_msisdn
                sub_bts = _get(row, col_map.get("a_bts"))
                sub_imei = _get(row, col_map.get("a_imei"))
                sub_imsi = _get(row, col_map.get("a_imsi"))

            else:
                # Unknown type — determine direction from subscriber position
                if _is_subscriber_match(a_digits, sub_digits):
                    is_outgoing = True
                    sub_bts = _get(row, col_map.get("a_bts"))
                    sub_imei = _get(row, col_map.get("a_imei"))
                    sub_imsi = _get(row, col_map.get("a_imsi"))
                else:
                    is_outgoing = False
                    sub_bts = _get(row, col_map.get("b_bts"))
                    sub_imei = _get(row, col_map.get("b_imei"))
                    sub_imsi = _get(row, col_map.get("b_imsi"))
                caller = a_msisdn
                callee = b_msisdn

            # Build record type with direction suffix
            if base_type == "CALL_FORWARDED":
                record_type = "CALL_FORWARDED"
            elif base_type == "DATA":
                record_type = "DATA"
            elif base_type == "OTHER":
                record_type = "OTHER"
            else:
                suffix = "_OUT" if is_outgoing else "_IN"
                record_type = base_type + suffix

            # Compute duration from start-end timestamps
            end_str = _get(row, col_map.get("end"))
            duration = _compute_duration_seconds(start_str, end_str)

            # Direction label for frontend "Kierunek" column
            if base_type == "CALL_FORWARDED":
                direction_label = "przekierowane"
            elif is_outgoing:
                direction_label = "wychodz\u0105ce"  # wychodzące
            else:
                direction_label = "przychodz\u0105ce"  # przychodzące

            # Parse BTS address for city/street
            bts_parts = _parse_bts_address(sub_bts)

            record = BillingRecord(
                datetime=dt,
                caller=self.normalize_phone(caller),
                callee=self.normalize_phone(callee),
                record_type=record_type,
                duration_seconds=duration,
                location=sub_bts,
                roaming=False,
                network="",
                imsi=sub_imsi,
                imei=sub_imei,
                raw_row=row_idx,
                extra={
                    "direction": direction_label,
                    "type_code": type_code,
                    "a_bts": _get(row, col_map.get("a_bts")),
                    "b_bts": _get(row, col_map.get("b_bts")),
                    "c_bts": _get(row, col_map.get("c_bts")),
                    "c_msisdn": self.normalize_phone(c_msisdn)
                    if c_msisdn else "",
                    "gcr": _get(row, col_map.get("gcr")),
                    "end_time": end_str,
                    "bts_lat": "",
                    "bts_lon": "",
                    "bts_city": bts_parts["bts_city"],
                    "bts_street": bts_parts["bts_street"],
                    "azimuth": "",
                    "bts_code": "",
                },
            )
            result.records.append(record)

            # Populate subscriber info from first record with IMEI/IMSI
            if not subscriber.imsi and sub_imsi:
                subscriber.imsi = sub_imsi
            if not subscriber.imei and sub_imei:
                subscriber.imei = sub_imei

        if skipped_companion > 0:
            result.warnings.append(
                f"Pomini\u0119to {skipped_companion} zduplikowanych wierszy "
                "(companion rows)"
            )

        result.subscriber = subscriber
        result.summary = compute_summary(result.records)
        return result

    # ------------------------------------------------------------------
    # TD format (data sessions) — 9 columns
    # ------------------------------------------------------------------

    def _parse_td(
        self,
        rows: List[List[Any]],
        header_idx: int,
        header_lower: List[str],
        result: BillingParseResult,
    ) -> BillingParseResult:
        """Parse Plus TD format (data/internet sessions)."""

        # Build column map by header name
        col_map: Dict[str, int] = {}
        for i, h in enumerate(header_lower):
            logical = _TD_COLUMNS.get(h)
            if logical and logical not in col_map:
                col_map[logical] = i

        # Adaptive fallback: try fuzzy matching if critical columns missing
        if "start" not in col_map:
            try:
                from .adaptive_mapper import AdaptiveColumnMapper
                mapper = AdaptiveColumnMapper()
                col_map, validation = mapper.build_adaptive_col_map(
                    "plus", "TD", header_lower, col_map,
                )
                result.warnings.extend(mapper.format_warnings(validation))
            except Exception:
                pass  # adaptive layer is optional — never block parsing

        if "start" not in col_map:
            result.warnings.append("Nie znaleziono kolumny 'Pocz\u0105tek'")
            return result

        result.warnings.append(
            f"Plus TD CSV — kolumny: {list(col_map.keys())} ({len(col_map)})"
        )

        # Detect subscriber from first data rows
        subscriber_msisdn = ""
        subscriber_imei = ""
        subscriber_imsi = ""
        for row in rows[header_idx + 1: header_idx + 10]:
            if not row:
                continue
            param = _get(row, col_map.get("parametr"))
            msisdn = _get(row, col_map.get("msisdn"))
            if param and re.match(r"^\d{6,15}$", param):
                subscriber_msisdn = self.normalize_phone(msisdn or param)
            imei = _get(row, col_map.get("imei"))
            imsi = _get(row, col_map.get("imsi"))
            if imei and not subscriber_imei:
                subscriber_imei = imei
            if imsi and not subscriber_imsi:
                subscriber_imsi = imsi
            if subscriber_msisdn:
                break

        subscriber = SubscriberInfo(
            operator=self.OPERATOR_NAME,
            msisdn=subscriber_msisdn,
            imei=subscriber_imei,
            imsi=subscriber_imsi,
        )

        # Parse data rows
        for row_idx, row in enumerate(
            rows[header_idx + 1:], start=header_idx + 2
        ):
            if not row or all(
                c is None or str(c).strip() == "" for c in row
            ):
                continue

            start_str = _get(row, col_map.get("start"))
            if not start_str:
                continue

            dt = self.parse_datetime(start_str)
            if not dt:
                continue

            end_str = _get(row, col_map.get("end"))

            # Duration: use Czas trwania column (seconds) or compute
            dur_str = _get(row, col_map.get("duration"))
            duration = 0
            if dur_str:
                try:
                    duration = int(float(dur_str))
                except (ValueError, TypeError):
                    duration = _compute_duration_seconds(start_str, end_str)
            else:
                duration = _compute_duration_seconds(start_str, end_str)

            bts = _get(row, col_map.get("bts"))
            ip = _get(row, col_map.get("ip"))
            msisdn = _get(row, col_map.get("msisdn"))
            imei = _get(row, col_map.get("imei"))
            imsi = _get(row, col_map.get("imsi"))

            bts_parts = _parse_bts_address(bts)

            record = BillingRecord(
                datetime=dt,
                caller=self.normalize_phone(msisdn),
                callee="",
                record_type="DATA",
                duration_seconds=duration,
                location=bts,
                roaming=False,
                network="",
                imsi=imsi,
                imei=imei,
                raw_row=row_idx,
                extra={
                    "direction": "dane",
                    "type_code": "DATA",
                    "ip": ip,
                    "end_time": end_str,
                    "bts_lat": "",
                    "bts_lon": "",
                    "bts_city": bts_parts["bts_city"],
                    "bts_street": bts_parts["bts_street"],
                    "azimuth": "",
                    "bts_code": "",
                },
            )
            result.records.append(record)

        result.subscriber = subscriber
        result.summary = compute_summary(result.records)
        return result
