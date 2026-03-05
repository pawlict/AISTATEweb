"""T-Mobile Poland GSM billing parser.

Handles XLSX billing files from T-Mobile Polska (formerly Era, PTC).

Real T-Mobile billing column layout (from actual billing XLSX):
  MSISDN | IMEI | IMSI | Data i godz. | Rozmówca | Nr powiązany |
  Długość | Kierunek | Dane wysłane | Usługa |
  System obsługujacy połaczenie | Publiczne Ip |
  BTS X | BTS Y | CI | LAC | Azymut | Wiązka |
  BTS R | BTS kod | BTS Miasto | BTS Ulica | Kraj | Operator
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .base import (
    BillingParser,
    BillingParseResult,
    BillingRecord,
    SubscriberInfo,
    compute_summary,
)


# T-Mobile specific column patterns — based on REAL billing headers
_TMOBILE_COLUMNS: Dict[str, List[str]] = {
    # --- Identity ---
    "msisdn": [
        r"^msisdn$",
    ],
    "imei": [
        r"^imei$",
    ],
    "imsi": [
        r"^imsi$",
    ],
    # --- Date/Time ---
    "date": [
        r"data\s*i\s*godz",          # "Data i godz."  ← actual T-Mobile header
        r"data\s*(?:i\s*czas)?(?:\s*po[łl][aą]czenia)?",
        r"data\s*(?:rozp|wykon|zdarz)",
    ],
    # --- Numbers ---
    "callee": [
        r"^rozm[óo]wca$",            # "Rozmówca" ← actual T-Mobile header
        r"numer\s*b\b",
        r"numer\s*(?:wywo[łl]|docel|po[łl][aą]cz)",
        r"msisdn\s*b",
        r"numer\s*odbiorcy",
    ],
    "related_number": [
        r"nr\s*powi[aą]zany",        # "Nr powiązany" ← actual T-Mobile header
    ],
    # --- Call details ---
    "duration": [
        r"^d[łl]ugo[śs][ćc]$",      # "Długość" ← actual T-Mobile header
        r"czas\s*trwania",
    ],
    "direction": [
        r"^kierunek$",               # "Kierunek" ← actual T-Mobile header
    ],
    "data_sent": [
        r"dane\s*wys[łl]ane",        # "Dane wysłane" ← actual T-Mobile header
    ],
    "service": [
        r"^us[łl]uga$",             # "Usługa" ← actual T-Mobile header
    ],
    "system": [
        r"system\s*obs[łl]uguj",     # "System obsługujacy połaczenie" ← actual
    ],
    # --- Network ---
    "public_ip": [
        r"publiczne\s*ip",           # "Publiczne Ip" ← actual T-Mobile header
    ],
    # --- BTS Location ---
    "bts_x": [r"bts\s*x"],
    "bts_y": [r"bts\s*y"],
    "ci": [r"^ci$"],                 # Cell ID
    "lac": [r"^lac$"],               # Location Area Code
    "azimuth": [r"^azymut$"],
    "beam": [r"^wi[aą]zka$"],        # "Wiązka"
    "bts_r": [r"bts\s*r"],
    "bts_code": [r"bts\s*kod"],
    "bts_city": [r"bts\s*miasto"],
    "bts_street": [r"bts\s*ulica"],
    # --- Country / Operator ---
    "country": [
        r"^kraj$",                   # "Kraj" ← actual T-Mobile header
    ],
    "operator": [
        r"^operator$",              # "Operator" ← actual T-Mobile header
    ],
}


class TMobileParser(BillingParser):
    """Parser for T-Mobile Poland billing XLSX files."""

    OPERATOR_NAME = "T-Mobile Polska"
    OPERATOR_ID = "tmobile"

    # Detection: T-Mobile has distinctive columns like "Rozmówca", "Nr powiązany",
    # "System obsługujacy połaczenie", "BTS Miasto" etc.
    DETECT_HEADER_PATTERNS = [
        r"rozm[óo]wca",           # unique T-Mobile column
        r"nr\s*powi[aą]zany",     # unique T-Mobile column
        r"system\s*obs[łl]uguj",  # unique T-Mobile column
        r"bts\s*miasto",          # T-Mobile BTS location style
        r"t-mobile",
        r"tmobile",
        r"ptc\b",
    ]

    DETECT_SHEET_PATTERNS = [
        r"t-mobile",
        r"tmobile",
        r"biling",
        r"po[łl][aą]czenia",
        r"billing",
    ]

    def parse_sheet(
        self,
        rows: List[List[Any]],
        sheet_name: str = "",
    ) -> BillingParseResult:
        result = BillingParseResult(
            operator=self.OPERATOR_NAME,
            operator_id=self.OPERATOR_ID,
            sheet_name=sheet_name,
        )

        if not rows:
            result.warnings.append("Pusty arkusz")
            return result

        # Find header row using T-Mobile specific keywords
        header_idx = self.find_header_row(
            rows,
            required_keywords=[
                "msisdn", "data", "rozmów", "rozmow", "kierunek",
                "długość", "dlugosc", "usług", "uslug", "operator",
                "bts", "imei", "imsi", "lac",
            ],
            max_scan=30,
        )
        if header_idx is None:
            result.warnings.append(
                f"Nie znaleziono wiersza nagłówka w arkuszu '{sheet_name}'"
            )
            return result

        header_row = rows[header_idx]

        # Build column map with T-Mobile specific patterns
        col_map = self.build_column_map(header_row, _TMOBILE_COLUMNS)

        if "date" not in col_map:
            result.warnings.append("Nie znaleziono kolumny 'Data i godz.'")
            return result

        mapped = list(col_map.keys())
        result.warnings.append(f"T-Mobile parser — kolumny: {mapped}")

        # Extract subscriber info from first data row's MSISDN column
        subscriber = SubscriberInfo(operator=self.OPERATOR_NAME)

        # Parse data rows
        for row_idx, row in enumerate(rows[header_idx + 1:], start=header_idx + 2):
            if not row or all(c is None or str(c).strip() == "" for c in row):
                continue

            date_val = self.get_cell(row, col_map.get("date"))
            if not date_val:
                continue

            dt = self.parse_datetime(date_val)
            if not dt:
                continue

            # T-Mobile uses "Kierunek" for call direction and "Usługa" for service type
            direction_label = self.get_cell(row, col_map.get("direction"))
            service_label = self.get_cell(row, col_map.get("service"))

            # Combine direction + service for record type classification
            record_type = self._classify_tmobile_record(direction_label, service_label)

            duration_str = self.get_cell(row, col_map.get("duration"))
            duration = self.parse_duration(duration_str)

            # MSISDN is the subscriber's own number (column A)
            msisdn = self.get_cell(row, col_map.get("msisdn"))
            callee = self.get_cell(row, col_map.get("callee"))  # "Rozmówca"
            related = self.get_cell(row, col_map.get("related_number"))  # "Nr powiązany"

            # Data volume from "Dane wysłane"
            data_vol = self.get_cell_float(row, col_map.get("data_sent"))

            # Build location from BTS columns
            bts_city = self.get_cell(row, col_map.get("bts_city"))
            bts_street = self.get_cell(row, col_map.get("bts_street"))
            location = ""
            if bts_city and bts_street:
                location = f"{bts_city}, {bts_street}"
            elif bts_city:
                location = bts_city
            elif bts_street:
                location = bts_street

            # Roaming detection from "Kraj"
            country = self.get_cell(row, col_map.get("country"))
            roaming = bool(
                country and country.lower() not in ("", "polska", "pl", "poland", "-")
            )

            network = self.get_cell(row, col_map.get("operator"))

            record = BillingRecord(
                datetime=dt,
                caller=self.normalize_phone(msisdn),
                callee=self.normalize_phone(callee),
                record_type=record_type,
                duration_seconds=duration,
                data_volume_kb=data_vol or 0.0,
                location=location,
                location_lac=self.get_cell(row, col_map.get("lac")),
                location_cell_id=self.get_cell(row, col_map.get("ci")),
                roaming=roaming,
                roaming_country=country if roaming else "",
                network=network,
                imsi=self.get_cell(row, col_map.get("imsi")),
                imei=self.get_cell(row, col_map.get("imei")),
                raw_row=row_idx,
                extra={
                    "nr_powiazany": related,
                    "system": self.get_cell(row, col_map.get("system")),
                    "public_ip": self.get_cell(row, col_map.get("public_ip")),
                    "bts_x": self.get_cell(row, col_map.get("bts_x")),
                    "bts_y": self.get_cell(row, col_map.get("bts_y")),
                    "azimuth": self.get_cell(row, col_map.get("azimuth")),
                    "beam": self.get_cell(row, col_map.get("beam")),
                    "bts_r": self.get_cell(row, col_map.get("bts_r")),
                    "bts_code": self.get_cell(row, col_map.get("bts_code")),
                    "service": service_label,
                    "direction": direction_label,
                },
            )
            result.records.append(record)

            # Grab subscriber MSISDN from first data row
            if not subscriber.msisdn and msisdn:
                subscriber.msisdn = self.normalize_phone(msisdn)
            if not subscriber.imsi:
                imsi_val = self.get_cell(row, col_map.get("imsi"))
                if imsi_val:
                    subscriber.imsi = imsi_val
            if not subscriber.imei:
                imei_val = self.get_cell(row, col_map.get("imei"))
                if imei_val:
                    subscriber.imei = imei_val

        result.subscriber = subscriber
        result.summary = compute_summary(result.records)
        return result

    @staticmethod
    def _classify_tmobile_record(direction: str, service: str) -> str:
        """Classify record type from T-Mobile 'Kierunek' + 'Usługa' columns.

        T-Mobile uses two columns:
        - Kierunek: "przychodzące", "wychodzące", etc.
        - Usługa: "Rozmowa telefoniczna", "SMS", "MMS", "Internet", etc.
        """
        d = direction.lower().strip() if direction else ""
        s = service.lower().strip() if service else ""

        is_in = any(k in d for k in ("przychod", "incoming", "odebran"))
        is_out = any(k in d for k in ("wychod", "outgoing", "wykonan", "wysłan", "wyslan"))
        is_forwarded = any(k in d for k in ("przekierow", "forward"))

        # Service type
        if any(k in s for k in ("sms",)):
            return "SMS_IN" if is_in else "SMS_OUT"
        if any(k in s for k in ("mms",)):
            return "MMS_IN" if is_in else "MMS_OUT"
        if any(k in s for k in ("internet", "dane", "data", "gprs", "lte", "transmisja")):
            return "DATA"
        if any(k in s for k in ("ussd",)):
            return "USSD"
        if any(k in s for k in ("poczta głosowa", "voicemail", "poczta glosowa")):
            return "VOICEMAIL"
        if any(k in s for k in ("rozmow", "połącz", "polacz", "call", "voice", "głos", "glos", "telefon")):
            if is_forwarded:
                return "CALL_FORWARDED"
            return "CALL_IN" if is_in else "CALL_OUT"

        # Fallback: use direction alone
        if is_forwarded:
            return "CALL_FORWARDED"
        if is_in:
            return "CALL_IN"
        if is_out:
            return "CALL_OUT"

        # Last resort: use base classify
        combined = f"{direction} {service}".strip()
        return BillingParser.classify_record_type(combined)
