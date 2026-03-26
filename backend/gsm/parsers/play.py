"""Play (P4) Poland GSM billing parser (CSV format).

Handles CSV billing files from Play / P4 Sp. z o.o.

Play CSV billing structure:
- Semicolon-delimited, cp1250 encoding
- 35 columns: DATA_I_GODZ_POLACZ, CZAS_TRWANIA, RODZAJ_USLUGI,
  UI_MSISDN/IMEI/IMSI/LAC/CID/coords/BTS, UW_MSISDN/IMEI/IMSI/LAC/CID/coords/BTS,
  PRZEK_MSISDN, INTERNET_IP_PORT
- UI = Użytkownik Inicjujący (initiating user), UW = Użytkownik Współny (other user)
- Direction: subscriber == UI_MSISDN → outgoing, subscriber == UW_MSISDN → incoming
- Coordinates use comma as decimal separator (Polish locale): 52,7518 → 52.7518
- MCC/MNC columns for roaming detection (260 = Poland)
"""

from __future__ import annotations

import csv
import re
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
# Play CSV column names (exact header values, case-insensitive match)
# ---------------------------------------------------------------------------

_PLAY_CSV_COLUMNS: Dict[str, str] = {
    "datetime": "DATA_I_GODZ_POLACZ",
    "duration": "CZAS_TRWANIA",
    "service_type": "RODZAJ_USLUGI",
    "ui_msisdn": "UI_MSISDN",
    "ui_imei": "UI_IMEI",
    "ui_imsi": "UI_IMSI",
    "ui_lac": "UI_LAC",
    "ui_cid": "UI_CID",
    "ui_lon": "UI_DLUG_GEOG",
    "ui_lat": "UI_SZER_GEOG",
    "ui_azimuth": "UI_AZYMUT",
    "ui_beam": "UI_WIAZKA",
    "ui_range": "UI_ZASIEG",
    "ui_postal": "UI_BTS_KOD_POCZTOWY",
    "ui_city": "UI_BTS_MIEJSCOWOSC",
    "ui_street": "UI_BTS_ULICA",
    "ui_mcc": "UI_MCC",
    "ui_mnc": "UI_MNC",
    "uw_msisdn": "UW_MSISDN",
    "uw_imei": "UW_IMEI",
    "uw_imsi": "UW_IMSI",
    "uw_lac": "UW_LAC",
    "uw_cid": "UW_CID",
    "uw_lon": "UW_DLUG_GEOG",
    "uw_lat": "UW_SZER_GEOG",
    "uw_azimuth": "UW_AZYMUT",
    "uw_beam": "UW_WIAZKA",
    "uw_range": "UW_ZASIEG",
    "uw_postal": "UW_BTS_KOD_POCZTOWY",
    "uw_city": "UW_BTS_MIEJSCOWOSC",
    "uw_street": "UW_BTS_ULICA",
    "uw_mcc": "UW_MCC",
    "uw_mnc": "UW_MNC",
    "forwarded": "PRZEK_MSISDN",
    "ip_port": "INTERNET_IP_PORT",
}


# ---------------------------------------------------------------------------
# RODZAJ_USLUGI → base record type (direction suffix applied later)
# ---------------------------------------------------------------------------

_SERVICE_TYPE_MAP: Dict[str, str] = {
    # Voice calls
    "rozmowa glosowa lte": "CALL",
    "rozmowa głosowa lte": "CALL",
    "rozmowa glosowa lub video": "CALL",
    "rozmowa głosowa lub video": "CALL",
    "proba polaczenia glosowego": "CALL",
    "próba połączenia głosowego": "CALL",
    "proba polaczenia glosowego volte": "CALL",
    "próba połączenia głosowego volte": "CALL",
    # SMS
    "wiadomosc sms": "SMS",
    "wiadomość sms": "SMS",
    "wiadomosc sms ip": "SMS",
    "wiadomość sms ip": "SMS",
    "wiadomosc sms w roamingu": "SMS",
    "wiadomość sms w roamingu": "SMS",
    "notyfikacja sms": "SMS",
    # MMS
    "wiadomosc mms": "MMS",
    "wiadomość mms": "MMS",
    # Data
    "polaczenie z internetem": "DATA",
    "połączenie z internetem": "DATA",
    "pakietowa transmisja danych": "DATA",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_coord(text: str) -> Optional[float]:
    """Parse coordinate with comma decimal separator. '52,7518' → 52.7518"""
    if not text:
        return None
    s = str(text).strip().replace(",", ".")
    try:
        val = float(s)
        if val == 0.0:
            return None
        return val
    except (ValueError, TypeError):
        return None


def _strip_eq(val: str) -> str:
    """Strip ="" quoting from Play CSV cells: ='value' or ="value" → value."""
    v = val.strip()
    if v.startswith('="') and v.endswith('"'):
        return v[2:-1]
    if v.startswith("='") and v.endswith("'"):
        return v[2:-1]
    return v


def _get(row: List[Any], idx: Optional[int]) -> str:
    """Get cell value as cleaned string, stripping ="" quoting."""
    if idx is None or idx >= len(row):
        return ""
    val = row[idx]
    if val is None:
        return ""
    return _strip_eq(str(val).strip())


def _is_phone(text: str) -> bool:
    """Check if text looks like a phone number (7+ digits)."""
    if not text:
        return False
    digits = re.sub(r"[\s\-\+\(\)\.]+", "", text)
    return bool(re.match(r"^\d{7,15}$", digits))


def _valid_imei(text: str) -> str:
    """Return IMEI only if it looks valid (14-15 digits). Otherwise empty."""
    if not text:
        return ""
    digits = re.sub(r"[^\d]", "", text)
    if 14 <= len(digits) <= 15:
        return digits
    return ""


def _valid_imsi(text: str) -> str:
    """Return IMSI only if it looks valid (15 digits, starts with MCC). Otherwise empty."""
    if not text:
        return ""
    digits = re.sub(r"[^\d]", "", text)
    if len(digits) == 15:
        return digits
    return ""


# ---------------------------------------------------------------------------
# CSV loading
# ---------------------------------------------------------------------------

def load_play_csv(
    path: Path,
    max_rows: int = 200_000,
) -> Dict[str, List[List[Any]]]:
    """Load a Play CSV file and return it in the sheets dict format.

    Tries cp1250 first (standard Polish encoding), then UTF-8, then latin-1.
    Semicolon-delimited.

    Returns:
        Dict with single key "CSV" → list of rows (list of cell values).
    """
    for encoding in ("cp1250", "utf-8-sig", "utf-8", "latin-1"):
        try:
            with open(path, "r", encoding=encoding, errors="strict") as f:
                reader = csv.reader(f, delimiter=";")
                rows: List[List[Any]] = []
                for i, row in enumerate(reader):
                    if i >= max_rows:
                        break
                    rows.append(row)
                return {"CSV": rows}
        except (UnicodeDecodeError, UnicodeError):
            continue

    # Last resort: read with errors='replace'
    with open(path, "r", encoding="cp1250", errors="replace") as f:
        reader = csv.reader(f, delimiter=";")
        rows = []
        for i, row in enumerate(reader):
            if i >= max_rows:
                break
            rows.append(row)
        return {"CSV": rows}


def is_play_csv(path: Path) -> bool:
    """Quick check if a CSV file is a Play billing.

    Reads only the first line and checks for distinctive Play CSV columns.
    """
    for encoding in ("cp1250", "utf-8-sig", "utf-8", "latin-1"):
        try:
            with open(path, "r", encoding=encoding, errors="strict") as f:
                first_line = f.readline()
            header_lower = first_line.lower()
            return (
                "data_i_godz_polacz" in header_lower
                and "rodzaj_uslugi" in header_lower
                and "ui_msisdn" in header_lower
            )
        except (UnicodeDecodeError, UnicodeError):
            continue
    return False


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

class PlayParser(BillingParser):
    """Parser for Play / P4 billing CSV files.

    Play CSV files have 35 columns with rich BTS data for both parties
    (initiating user UI_ and other user UW_). Direction is inferred by
    comparing UI_MSISDN to the subscriber's number.
    """

    OPERATOR_NAME = "Play (P4)"
    OPERATOR_ID = "play"
    PARSER_VERSION = "1.1"

    # CSV files don't have sheet names, but headers are distinctive
    DETECT_HEADER_PATTERNS = [
        r"data_i_godz_polacz",
        r"rodzaj_uslugi",
        r"ui_msisdn",
        r"uw_msisdn",
        r"ui_lac",
        r"ui_cid",
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

        # Find header row (should be first non-empty row)
        header_idx = None
        for i, row in enumerate(rows[:10]):
            row_text = "|".join(str(c).strip().lower() for c in row if c)
            if "data_i_godz_polacz" in row_text and "rodzaj_uslugi" in row_text:
                header_idx = i
                break

        if header_idx is None:
            result.warnings.append("Nie znaleziono nagłówka CSV Play")
            return result

        # Build column index map from header
        header_row = rows[header_idx]
        header_lower = [str(c).strip().lower() if c else "" for c in header_row]
        col_map: Dict[str, int] = {}

        for logical_name, csv_name in _PLAY_CSV_COLUMNS.items():
            csv_lower = csv_name.lower()
            for j, h in enumerate(header_lower):
                if h == csv_lower:
                    col_map[logical_name] = j
                    break

        # Adaptive fallback: try fuzzy matching if critical columns missing
        _required_play = {"datetime", "ui_msisdn", "uw_msisdn", "service_type"}
        if _required_play - set(col_map.keys()):
            try:
                from .adaptive_mapper import AdaptiveColumnMapper
                mapper = AdaptiveColumnMapper()
                col_map, validation = mapper.build_adaptive_col_map(
                    "play", "", header_lower, col_map,
                )
                result.warnings.extend(mapper.format_warnings(validation))
            except Exception:
                pass  # adaptive layer is optional — never block parsing

        if "datetime" not in col_map:
            result.warnings.append("Nie znaleziono kolumny DATA_I_GODZ_POLACZ")
            return result

        result.warnings.append(
            f"Play CSV — kolumny: {list(col_map.keys())} ({len(col_map)}/{len(_PLAY_CSV_COLUMNS)})"
        )

        # Detect subscriber MSISDN from data
        subscriber_msisdn = self._detect_subscriber(rows, header_idx, col_map)
        sub_digits = re.sub(r"[^\d]", "", subscriber_msisdn)

        subscriber = SubscriberInfo(
            operator=self.OPERATOR_NAME,
            msisdn=subscriber_msisdn,
        )

        # Parse data rows
        for row_idx, row in enumerate(
            rows[header_idx + 1:], start=header_idx + 2
        ):
            if not row or all(
                c is None or str(c).strip() == "" for c in row
            ):
                continue

            dt_val = _get(row, col_map.get("datetime"))
            if not dt_val:
                continue

            dt = self.parse_datetime(dt_val)
            if not dt:
                continue

            service_type = _get(row, col_map.get("service_type"))
            ui_msisdn = _get(row, col_map.get("ui_msisdn"))
            uw_msisdn = _get(row, col_map.get("uw_msisdn"))
            forwarded = _get(row, col_map.get("forwarded"))

            # Direction detection: UI = initiating user
            ui_digits = re.sub(r"[^\d]", "", ui_msisdn)
            is_outgoing = _is_subscriber(ui_digits, sub_digits)

            # Record type classification
            record_type = _classify_service(service_type, is_outgoing, forwarded)

            # Duration in seconds
            dur_str = _get(row, col_map.get("duration"))
            duration = 0
            if dur_str:
                try:
                    duration = int(float(dur_str))
                except (ValueError, TypeError):
                    pass

            # Caller/callee (always UI=caller, UW=callee in CDR sense)
            caller = self.normalize_phone(ui_msisdn)
            callee = self.normalize_phone(uw_msisdn)

            # Subscriber's BTS data (from the subscriber's side)
            if is_outgoing:
                # Subscriber is UI (initiator)
                sub_lac = _get(row, col_map.get("ui_lac"))
                sub_cid = _get(row, col_map.get("ui_cid"))
                sub_lat = _parse_coord(_get(row, col_map.get("ui_lat")))
                sub_lon = _parse_coord(_get(row, col_map.get("ui_lon")))
                sub_azimuth = _get(row, col_map.get("ui_azimuth"))
                sub_beam = _get(row, col_map.get("ui_beam"))
                sub_range = _get(row, col_map.get("ui_range"))
                sub_postal = _get(row, col_map.get("ui_postal"))
                sub_city = _get(row, col_map.get("ui_city"))
                sub_street = _get(row, col_map.get("ui_street"))
                sub_mcc = _get(row, col_map.get("ui_mcc"))
                sub_mnc = _get(row, col_map.get("ui_mnc"))
                sub_imsi = _valid_imsi(_get(row, col_map.get("ui_imsi")))
                sub_imei = _valid_imei(_get(row, col_map.get("ui_imei")))
            else:
                # Subscriber is UW (other party)
                sub_lac = _get(row, col_map.get("uw_lac"))
                sub_cid = _get(row, col_map.get("uw_cid"))
                sub_lat = _parse_coord(_get(row, col_map.get("uw_lat")))
                sub_lon = _parse_coord(_get(row, col_map.get("uw_lon")))
                sub_azimuth = _get(row, col_map.get("uw_azimuth"))
                sub_beam = _get(row, col_map.get("uw_beam"))
                sub_range = _get(row, col_map.get("uw_range"))
                sub_postal = _get(row, col_map.get("uw_postal"))
                sub_city = _get(row, col_map.get("uw_city"))
                sub_street = _get(row, col_map.get("uw_street"))
                sub_mcc = _get(row, col_map.get("uw_mcc"))
                sub_mnc = _get(row, col_map.get("uw_mnc"))
                sub_imsi = _valid_imsi(_get(row, col_map.get("uw_imsi")))
                sub_imei = _valid_imei(_get(row, col_map.get("uw_imei")))

            # Build location string
            location = ""
            if sub_city and sub_street:
                location = f"{sub_city}, {sub_street}"
            elif sub_city:
                location = sub_city
            elif sub_street:
                location = sub_street

            # Roaming detection via MCC (260 = Poland)
            roaming = False
            roaming_country = ""
            roaming_mcc_mnc = ""
            if sub_mcc:
                try:
                    mcc_val = str(int(float(sub_mcc)))
                    if mcc_val and mcc_val != "260":
                        roaming = True
                        from .orange_retencja import _MCC_TO_COUNTRY
                        iso_code = _MCC_TO_COUNTRY.get(mcc_val, "")
                        mnc_str = ""
                        if sub_mnc:
                            try:
                                mnc_str = str(int(float(sub_mnc)))
                            except (ValueError, TypeError):
                                mnc_str = sub_mnc
                        roaming_mcc_mnc = f"{mcc_val}:{mnc_str}"
                        roaming_country = iso_code or roaming_mcc_mnc
                except (ValueError, TypeError):
                    pass

            # Direction label for frontend "Kierunek" column
            direction_label = "wychodzące" if is_outgoing else "przychodzące"
            if forwarded:
                direction_label = "przekierowane"

            # IP/port for data sessions
            ip_port = _get(row, col_map.get("ip_port"))

            record = BillingRecord(
                datetime=dt,
                caller=caller,
                callee=callee,
                record_type=record_type,
                duration_seconds=duration,
                location=location,
                location_lac=sub_lac,
                location_cell_id=sub_cid,
                roaming=roaming,
                roaming_country=roaming_country,
                network="",
                imsi=sub_imsi,
                imei=sub_imei,
                raw_row=row_idx,
                extra={
                    "bts_lat": str(sub_lat) if sub_lat else "",
                    "bts_lon": str(sub_lon) if sub_lon else "",
                    "azimuth": sub_azimuth,
                    "beam": sub_beam,
                    "range_km": sub_range,
                    "bts_postal": sub_postal,
                    "bts_city": sub_city,
                    "bts_street": sub_street,
                    "bts_code": "",
                    "direction": direction_label,
                    "service_original": service_type,
                    "forwarded_msisdn": forwarded,
                    "ip_port": ip_port,
                    "roaming_mcc_mnc": roaming_mcc_mnc if roaming else "",
                },
            )
            result.records.append(record)

            # Populate subscriber info from first outgoing record
            if is_outgoing:
                if not subscriber.imsi and sub_imsi:
                    subscriber.imsi = sub_imsi
                if not subscriber.imei and sub_imei:
                    subscriber.imei = sub_imei

        result.subscriber = subscriber
        result.summary = compute_summary(result.records)
        return result

    # ------------------------------------------------------------------
    # Subscriber detection
    # ------------------------------------------------------------------

    def _detect_subscriber(
        self,
        rows: List[List[Any]],
        header_idx: int,
        col_map: Dict[str, int],
    ) -> str:
        """Detect subscriber MSISDN by frequency analysis.

        The subscriber's number appears most frequently across UI_MSISDN
        and UW_MSISDN columns (they are on one side of every record).
        """
        from collections import Counter

        counter: Counter = Counter()
        for row in rows[header_idx + 1: header_idx + 500]:
            if not row:
                continue
            ui = _get(row, col_map.get("ui_msisdn"))
            uw = _get(row, col_map.get("uw_msisdn"))
            if _is_phone(ui):
                counter[self.normalize_phone(ui)] += 1
            if _is_phone(uw):
                counter[self.normalize_phone(uw)] += 1

        if counter:
            return counter.most_common(1)[0][0]
        return ""


# ---------------------------------------------------------------------------
# Static helpers (used by parser and external callers)
# ---------------------------------------------------------------------------

def _is_subscriber(digits: str, sub_digits: str) -> bool:
    """Check if digits match subscriber's number (last 9 digits)."""
    if not digits or not sub_digits:
        return True  # default to outgoing when unknown
    if len(digits) >= 9 and len(sub_digits) >= 9:
        return digits[-9:] == sub_digits[-9:]
    return False


def _classify_service(
    service: str, is_outgoing: bool, forwarded: str
) -> str:
    """Map RODZAJ_USLUGI to standard record type with direction."""
    if not service:
        return "OTHER"

    s = service.lower().strip()

    # Direct lookup
    base = _SERVICE_TYPE_MAP.get(s)

    if base is None:
        # Fallback partial matching
        if "sms" in s:
            base = "SMS"
        elif "mms" in s:
            base = "MMS"
        elif any(
            k in s
            for k in ("rozmowa", "glosow", "polaczeni", "volte", "voice", "call")
        ):
            base = "CALL"
        elif any(
            k in s
            for k in ("internet", "dane", "data", "pakiet", "transmis")
        ):
            base = "DATA"
        else:
            return "OTHER"

    # DATA has no direction suffix
    if base == "DATA":
        return "DATA"

    # Call forwarding
    if forwarded and base == "CALL":
        return "CALL_FORWARDED"

    suffix = "_OUT" if is_outgoing else "_IN"
    return base + suffix
