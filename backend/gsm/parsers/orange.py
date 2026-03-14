"""Orange Poland GSM billing parser.

Handles XLSX billing files from Orange Polska (formerly TP SA / PTK Centertel).
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


_ORANGE_COLUMNS: Dict[str, List[str]] = {
    "date": [
        r"data\s*(?:i\s*czas)?(?:\s*po[łl][aą]czenia)?",
        r"data\s*(?:rozp|wykon|zdarz)",
    ],
    "time": [
        r"godzina",
        r"czas\s*rozp",
    ],
    "caller": [
        r"numer\s*a\b",
        r"numer\s*dzwoni[aą]cego",
        r"msisdn\s*a",
    ],
    "callee": [
        r"numer\s*b\b",
        r"numer\s*(?:wywo[łl]|docel|po[łl][aą]cz)",
        r"msisdn\s*b",
        r"numer\s*odbiorcy",
    ],
    "record_type": [
        r"typ\s*(?:po[łl][aą]czenia|zdarzenia|us[łl]ugi)",
        r"rodzaj",
        r"us[łl]uga",
        r"kierunek",
    ],
    "duration": [
        r"czas\s*trwania",
        r"d[łl]ugo[śs][ćc]",
    ],
    "cost": [
        r"koszt(?:\s*netto)?",
        r"kwota(?:\s*netto)?",
        r"op[łl]ata",
        r"nale[żz]no[śs][ćc]",
    ],
    "cost_gross": [
        r"brutto",
        r"z\s*vat",
    ],
    "location": [
        r"lokalizacja",
        r"adres\s*bts",
        r"bts",
        r"stacja\s*bazowa",
    ],
    "lac": [r"lac\b"],
    "cell_id": [r"cell\s*id", r"cid\b"],
    "network": [
        r"sie[ćc]",
        r"operator",
    ],
    "imsi": [r"imsi"],
    "imei": [r"imei"],
    "data_volume": [
        r"(?:obj[ęe]to[śs][ćc]|ilo[śs][ćc]|wolumen)\s*(?:danych)?",
        r"transfer",
    ],
    "roaming": [
        r"roaming",
        r"kraj",
    ],
}


class OrangeParser(BillingParser):
    """Parser for Orange Polska billing XLSX files."""

    OPERATOR_NAME = "Orange Polska"
    OPERATOR_ID = "orange"
    PARSER_VERSION = "1.0"

    DETECT_HEADER_PATTERNS = [
        r"orange",
        r"orange\s*polsk",
        r"ptk\s*centertel",
        r"tp\s*sa",
    ]

    DETECT_SHEET_PATTERNS = [
        r"orange",
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
            parser_version=self.PARSER_VERSION,
            sheet_name=sheet_name,
        )

        if not rows:
            result.warnings.append("Pusty arkusz")
            return result

        subscriber = self._extract_subscriber_info(rows)
        result.subscriber = subscriber

        header_idx = self.find_header_row(
            rows,
            required_keywords=[
                "data", "numer", "czas", "koszt", "typ", "połącz",
                "usług", "kierunek", "sms",
            ],
            max_scan=30,
        )
        if header_idx is None:
            result.warnings.append(
                f"Nie znaleziono wiersza nagłówka w arkuszu '{sheet_name}'"
            )
            return result

        header_row = rows[header_idx]
        col_map = self.build_column_map(header_row, _ORANGE_COLUMNS)

        if "date" not in col_map:
            result.warnings.append("Nie znaleziono kolumny z datą")
            return result

        result.warnings.append(f"Orange parser — kolumny: {list(col_map.keys())}")

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

            duration = self.parse_duration(
                self.get_cell(row, col_map.get("duration"))
            )
            cost = self.get_cell_float(row, col_map.get("cost"))
            cost_gross = self.get_cell_float(row, col_map.get("cost_gross"))

            callee = self.get_cell(row, col_map.get("callee"))
            caller = self.get_cell(row, col_map.get("caller"))
            location = self.get_cell(row, col_map.get("location"))
            network = self.get_cell(row, col_map.get("network"))

            roaming_val = self.get_cell(row, col_map.get("roaming"))
            roaming = bool(
                roaming_val and roaming_val.lower() not in ("", "nie", "no", "0", "-")
            )
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
                roaming_country=self.get_cell(row, col_map.get("roaming"))
                    if roaming else "",
                network=network,
                imsi=self.get_cell(row, col_map.get("imsi")),
                imei=self.get_cell(row, col_map.get("imei")),
                raw_row=row_idx,
            )
            result.records.append(record)

        result.summary = compute_summary(result.records)
        return result

    def _extract_subscriber_info(self, rows: List[List[Any]]) -> SubscriberInfo:
        """Extract subscriber info from header area of Orange billing."""
        import re
        info = SubscriberInfo(operator=self.OPERATOR_NAME)

        for row in rows[:20]:
            row_text = " ".join(str(c).strip() for c in row if c is not None)
            row_lower = row_text.lower()

            if not info.msisdn:
                m = re.search(
                    r"(?:msisdn|numer\s*telefonu|numer\s*abonenta|nr\s*tel)"
                    r"\s*:?\s*\+?(\d[\d\s\-]{7,})",
                    row_lower,
                )
                if m:
                    info.msisdn = self.normalize_phone(m.group(1))
                for cell in row:
                    cell_text = str(cell).strip() if cell else ""
                    if re.match(r"^\+?48?\d{9}$", cell_text.replace(" ", "").replace("-", "")):
                        info.msisdn = self.normalize_phone(cell_text)
                        break

            if not info.imsi:
                m = re.search(r"imsi\s*:?\s*(\d{15})", row_lower)
                if m:
                    info.imsi = m.group(1)

            if not info.owner_name:
                m = re.search(
                    r"(?:abonent|u[żz]ytkownik|nazwa)\s*:?\s*(.+)",
                    row_lower,
                )
                if m:
                    name = m.group(1).strip()
                    name = re.sub(r"\s*(?:msisdn|imsi|numer|plan).*$", "", name, flags=re.I)
                    if 2 < len(name) < 100:
                        info.owner_name = name.title()

            if not info.tariff:
                m = re.search(r"(?:plan|taryfa|oferta)\s*:?\s*(.+)", row_lower)
                if m:
                    info.tariff = m.group(1).strip()[:100]

        return info
