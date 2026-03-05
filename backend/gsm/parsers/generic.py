"""Generic (fallback) GSM billing parser.

Used when no operator-specific parser matches the XLSX structure.
Attempts to auto-detect columns by common Polish billing header keywords.
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


# Common column header keywords across Polish operators
_COMMON_COLUMN_PATTERNS: Dict[str, List[str]] = {
    "date": [
        r"data",
        r"date",
        r"czas\s*po[łl]",
        r"data\s*po[łl][aą]czenia",
        r"data\s*i\s*czas",
        r"data\s*rozm",
        r"data\s*rozpocz",
    ],
    "time": [
        r"godzina",
        r"czas\s*rozp",
        r"time",
        r"godz",
    ],
    "caller": [
        r"numer\s*a\b",
        r"numer\s*dzwoni[aą]cego",
        r"calling",
        r"msisdn\s*a",
        r"numer\s*nadawcy",
    ],
    "callee": [
        r"numer\s*b\b",
        r"numer\s*wywo[łl]",
        r"called",
        r"msisdn\s*b",
        r"numer\s*odbiorcy",
        r"numer\s*docelowy",
        r"numer\s*po[łl][aą]czenia",
    ],
    "record_type": [
        r"typ\s*po[łl][aą]czenia",
        r"typ\s*zdarzenia",
        r"rodzaj",
        r"us[łl]uga",
        r"type",
        r"kierunek",
    ],
    "duration": [
        r"czas\s*trwania",
        r"duration",
        r"d[łl]ugo[śs][ćc]",
        r"czas\s*po[łl]",
    ],
    "cost": [
        r"koszt",
        r"op[łl]ata",
        r"kwota",
        r"netto",
        r"cena",
        r"nale[żz]no",
        r"warto[śs][ćc]",
    ],
    "cost_gross": [
        r"brutto",
        r"z\s*vat",
        r"gross",
    ],
    "location": [
        r"lokalizacja",
        r"location",
        r"bts",
        r"stacja",
        r"cell",
        r"adres\s*bts",
    ],
    "network": [
        r"sie[ćc]\s*docelowa",
        r"sie[ćc]",
        r"operator",
        r"network",
    ],
    "imsi": [
        r"imsi",
    ],
    "imei": [
        r"imei",
    ],
    "data_volume": [
        r"(?:ilo[śs][ćc]|obj[ęe]to[śs][ćc]|wolumen)\s*(?:danych|kb|mb|gb)",
        r"transfer",
        r"volume",
        r"dane\s*\(",
    ],
    "roaming": [
        r"roaming",
        r"kraj",
        r"country",
    ],
    "lac": [
        r"lac\b",
        r"location\s*area",
    ],
    "cell_id": [
        r"cell\s*id",
        r"cid\b",
    ],
}


class GenericBillingParser(BillingParser):
    """Fallback parser that auto-detects columns from common Polish billing headers."""

    OPERATOR_NAME = "Nieznany operator"
    OPERATOR_ID = "generic"
    DETECT_HEADER_PATTERNS: List[str] = []
    DETECT_SHEET_PATTERNS: List[str] = []

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

        # Find header row
        header_idx = self.find_header_row(
            rows,
            required_keywords=["data", "numer", "typ", "czas", "koszt", "połącz",
                               "sms", "rozmow", "usług", "duration"],
            max_scan=20,
        )
        if header_idx is None:
            result.warnings.append(
                f"Nie znaleziono wiersza nagłówka w arkuszu '{sheet_name}'"
            )
            return result

        header_row = rows[header_idx]

        # Build column map
        col_map = self.build_column_map(header_row, _COMMON_COLUMN_PATTERNS)
        if "date" not in col_map:
            result.warnings.append("Nie znaleziono kolumny z datą")
            return result

        result.warnings.append(
            f"Generyczny parser — rozpoznane kolumny: {list(col_map.keys())}"
        )

        # Parse data rows
        for row_idx, row in enumerate(rows[header_idx + 1:], start=header_idx + 2):
            if not row or all(c is None or str(c).strip() == "" for c in row):
                continue

            date_val = self.get_cell(row, col_map.get("date"))
            if not date_val:
                continue

            time_val = self.get_cell(row, col_map.get("time"))
            dt = self.parse_datetime(date_val, time_val)
            if not dt:
                continue

            type_label = self.get_cell(row, col_map.get("record_type"))
            record_type = self.classify_record_type(type_label)

            duration_str = self.get_cell(row, col_map.get("duration"))
            duration = self.parse_duration(duration_str)

            cost = self.get_cell_float(row, col_map.get("cost"))
            cost_gross = self.get_cell_float(row, col_map.get("cost_gross"))

            callee = self.get_cell(row, col_map.get("callee"))
            caller = self.get_cell(row, col_map.get("caller"))

            location = self.get_cell(row, col_map.get("location"))
            network = self.get_cell(row, col_map.get("network"))

            roaming_val = self.get_cell(row, col_map.get("roaming"))
            roaming = bool(roaming_val and roaming_val.lower() not in ("", "nie", "no", "0", "-"))

            data_vol = self.get_cell_float(row, col_map.get("data_volume"))

            record = BillingRecord(
                datetime=dt,
                caller=self.normalize_phone(caller),
                callee=self.normalize_phone(callee),
                record_type=record_type,
                duration_seconds=duration,
                data_volume_kb=data_vol or 0.0,
                cost=cost,
                cost_gross=cost_gross,
                location=location,
                location_lac=self.get_cell(row, col_map.get("lac")),
                location_cell_id=self.get_cell(row, col_map.get("cell_id")),
                roaming=roaming,
                network=network,
                imsi=self.get_cell(row, col_map.get("imsi")),
                imei=self.get_cell(row, col_map.get("imei")),
                raw_row=row_idx,
            )
            result.records.append(record)

        result.summary = compute_summary(result.records)
        return result
