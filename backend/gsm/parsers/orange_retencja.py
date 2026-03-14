"""Orange Polska retencja (data retention) GSM billing parser.

Handles XLSX billing files in the Orange retencja format, which has three sheets:
- WYKAZ: call/SMS/data records (CDRs)
- BTS: cell tower locations with DMS coordinates
- IMEI: subscriber device info

This is a different format from regular Orange billing (handled by OrangeParser).
Retencja billings have a distinctive structure with columns like
"IDENTYFIKATOR UŻYTKOWNIKA", "BTS A", "NUMER B", etc.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .base import (
    BillingParser,
    BillingParseResult,
    BillingRecord,
    BillingSummary,
    SubscriberInfo,
    compute_summary,
)


# ---------------------------------------------------------------------------
# BTS sector info (from BTS sheet)
# ---------------------------------------------------------------------------

@dataclass
class _BtsSector:
    """Parsed BTS sector data from the BTS sheet."""
    code: str = ""
    lat: float = 0.0
    lon: float = 0.0
    azimuth: str = ""
    range_km: str = ""
    city: str = ""
    street: str = ""


# ---------------------------------------------------------------------------
# Column patterns
# ---------------------------------------------------------------------------

_RETENCJA_COLUMNS: Dict[str, List[str]] = {
    "date": [r"^data$"],
    "duration": [r"^czas$"],
    "rp": [r"^rp$"],
    "ident": [r"identyfikator\s*u[żz]ytkownika"],
    "bts_a": [r"^bts\s*a$"],
    "imei_a": [r"^imei\s*a$"],
    "imsi_a": [r"^imsi\s*a$"],
    "number_b": [r"^numer\s*b$"],
    "bts_b": [r"^bts\s*b$"],
    "imei_b": [r"^imei\s*b$"],
    "imsi_b": [r"^imsi\s*b$"],
}

_BTS_COLUMNS: Dict[str, List[str]] = {
    "sector": [r"^sektor$", r"kod\s*sektora"],
    "city": [r"miejscowo[śs][ćc]"],
    "street": [r"ulica"],
    "azimuth": [r"azym"],
    "tilt": [r"k[aą]t\s*ant"],
    "longitude": [r"d[łl]ugo[śs][ćc]\s*(?:geograf)?"],
    "latitude": [r"szeroko[śs][ćc]\s*(?:geograf)?"],
    "range_km": [r"zasi[eę]g"],
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_dms(text: str) -> Optional[float]:
    """Parse DMS coordinate string to decimal degrees.

    Handles: 52°13'11"  or  20°55'15"
    The degree sign is 0xB0, minute is apostrophe ('), second is quote (").
    """
    if not text:
        return None
    s = str(text).strip()
    m = re.match(
        r"(\d+)\s*[°\xb0]\s*(\d+)\s*['\u2019]\s*(\d+)\s*[\"″\u201d]?",
        s,
    )
    if not m:
        return None
    deg = int(m.group(1))
    mins = int(m.group(2))
    secs = int(m.group(3))
    return deg + mins / 60.0 + secs / 3600.0


def _is_phone_number(val: Any) -> bool:
    """Check if value looks like a phone number (numeric, 7+ digits)."""
    if val is None:
        return False
    if isinstance(val, (int, float)):
        return len(str(int(val))) >= 7
    s = re.sub(r"[\s\-\+\(\)\.]+", "", str(val).strip())
    return bool(re.match(r"^\d{7,15}$", s))


def _to_str(val: Any) -> str:
    """Convert cell value to clean string."""
    if val is None:
        return ""
    if isinstance(val, float):
        if val == int(val):
            return str(int(val))
        return str(val)
    if isinstance(val, int):
        return str(val)
    return str(val).strip()


# MCC (Mobile Country Code) → ISO 3166-1 alpha-2 country code mapping
# Comprehensive database covering all ITU-assigned MCC codes worldwide.
# MCC = 3-digit Mobile Country Code (identifies country)
# MNC = 2-3 digit Mobile Network Code (identifies operator within country)
# Together MCC:MNC uniquely identifies a mobile network (e.g. 260:06 = Play PL)
_MCC_TO_COUNTRY: Dict[str, str] = {
    # ── Europe ──
    "202": "GR", "204": "NL", "206": "BE", "208": "FR",
    "212": "MC", "213": "AD", "214": "ES", "216": "HU",
    "218": "BA", "219": "HR", "220": "RS", "221": "XK",
    "222": "IT", "225": "VA", "226": "RO", "228": "CH",
    "230": "CZ", "231": "SK", "232": "AT",
    "234": "GB", "235": "GB", "236": "GB",
    "238": "DK", "240": "SE", "242": "NO", "244": "FI",
    "246": "LT", "247": "LV", "248": "EE",
    "250": "RU", "255": "UA", "257": "BY",
    "259": "MD", "260": "PL", "262": "DE",
    "266": "GI", "268": "PT", "270": "LU",
    "272": "IE", "274": "IS", "276": "AL",
    "278": "MT", "280": "CY", "282": "GE",
    "283": "AM", "284": "BG", "286": "TR",
    "288": "FO", "290": "GL", "292": "SM",
    "293": "SI", "294": "MK", "295": "LI", "297": "ME",
    # ── North America ──
    "302": "CA",
    "308": "PM",  # Saint Pierre and Miquelon
    "310": "US", "311": "US", "312": "US", "313": "US", "314": "US", "316": "US",
    "330": "PR", "332": "VI",  # Puerto Rico, US Virgin Islands
    "334": "MX", "338": "JM",
    "340": "GP",  # Guadeloupe (FR)
    "342": "BB",  # Barbados
    "344": "AG",  # Antigua and Barbuda
    "346": "KY",  # Cayman Islands
    "348": "VG",  # British Virgin Islands
    "350": "BM",  # Bermuda
    "352": "GD",  # Grenada
    "354": "MS",  # Montserrat
    "356": "KN",  # Saint Kitts and Nevis
    "358": "LC",  # Saint Lucia
    "360": "VC",  # Saint Vincent and the Grenadines
    "362": "CW",  # Curaçao
    "363": "AW",  # Aruba
    "364": "BS",  # Bahamas
    "365": "AI",  # Anguilla
    "366": "DM",  # Dominica
    "368": "CU",  # Cuba
    "370": "DO",  # Dominican Republic
    "372": "HT",  # Haiti
    "374": "TT",  # Trinidad and Tobago
    "376": "TC",  # Turks and Caicos
    # ── Central & South America ──
    "702": "BZ", "704": "GT", "706": "SV",
    "708": "HN", "710": "NI", "712": "CR", "714": "PA",
    "716": "PE", "722": "AR", "724": "BR", "730": "CL",
    "732": "CO", "734": "VE", "736": "BO", "738": "GY",
    "740": "EC", "744": "PY", "746": "SR", "748": "UY",
    # ── Middle East ──
    "400": "AZ",  # Azerbaijan
    "401": "KZ",  # Kazakhstan
    "402": "BT",  # Bhutan
    "404": "IN", "405": "IN",  # India (oba MCC)
    "410": "PK",  # Pakistan
    "412": "AF",  # Afghanistan
    "413": "LK",  # Sri Lanka
    "414": "MM",  # Myanmar
    "415": "LB",  # Lebanon
    "416": "JO",  # Jordan
    "417": "SY",  # Syria
    "418": "IQ",  # Iraq
    "419": "KW",  # Kuwait
    "420": "SA",  # Saudi Arabia
    "421": "YE",  # Yemen
    "422": "OM",  # Oman
    "424": "AE",  # United Arab Emirates
    "425": "IL",  # Israel
    "426": "BH",  # Bahrain
    "427": "QA",  # Qatar
    "428": "MN",  # Mongolia
    "429": "NP",  # Nepal
    "430": "AE",  # UAE (alternatywny)
    "431": "AE",  # UAE (alternatywny)
    "432": "IR",  # Iran
    "434": "UZ",  # Uzbekistan
    "436": "TJ",  # Tajikistan
    "437": "KG",  # Kyrgyzstan
    "438": "TM",  # Turkmenistan
    # ── East & Southeast Asia ──
    "440": "JP", "441": "JP",  # Japan
    "450": "KR",  # South Korea
    "452": "VN",  # Vietnam
    "454": "HK",  # Hong Kong
    "455": "MO",  # Macau
    "456": "KH",  # Cambodia
    "457": "LA",  # Laos
    "460": "CN", "461": "CN",  # China
    "466": "TW",  # Taiwan
    "467": "KP",  # North Korea
    "470": "BD",  # Bangladesh
    "472": "MV",  # Maldives
    # ── Southeast Asia & Oceania ──
    "502": "MY",  # Malaysia
    "505": "AU",  # Australia
    "510": "ID",  # Indonesia
    "514": "TL",  # Timor-Leste
    "515": "PH",  # Philippines
    "520": "TH",  # Thailand
    "525": "SG",  # Singapore
    "528": "BN",  # Brunei
    "530": "NZ",  # New Zealand
    "536": "NR",  # Nauru
    "537": "PG",  # Papua New Guinea
    "539": "TO",  # Tonga
    "540": "SB",  # Solomon Islands
    "541": "VU",  # Vanuatu
    "542": "FJ",  # Fiji
    "544": "AS",  # American Samoa
    "545": "KI",  # Kiribati
    "546": "NC",  # New Caledonia (FR)
    "547": "PF",  # French Polynesia
    "548": "CK",  # Cook Islands
    "549": "WS",  # Samoa
    "550": "FM",  # Micronesia
    "551": "MH",  # Marshall Islands
    "552": "PW",  # Palau
    "553": "TV",  # Tuvalu
    "555": "NU",  # Niue
    # ── Africa ──
    "602": "EG",  # Egypt
    "603": "DZ",  # Algeria
    "604": "MA",  # Morocco
    "605": "TN",  # Tunisia
    "606": "LY",  # Libya
    "607": "GM",  # Gambia
    "608": "SN",  # Senegal
    "609": "MR",  # Mauritania
    "610": "ML",  # Mali
    "611": "GN",  # Guinea
    "612": "CI",  # Côte d'Ivoire
    "613": "BF",  # Burkina Faso
    "614": "NE",  # Niger
    "615": "TG",  # Togo
    "616": "BJ",  # Benin
    "617": "MU",  # Mauritius
    "618": "LR",  # Liberia
    "619": "SL",  # Sierra Leone
    "620": "GH",  # Ghana
    "621": "NG",  # Nigeria
    "622": "TD",  # Chad
    "623": "CF",  # Central African Republic
    "624": "CM",  # Cameroon
    "625": "CV",  # Cape Verde
    "626": "ST",  # São Tomé and Príncipe
    "627": "GQ",  # Equatorial Guinea
    "628": "GA",  # Gabon
    "629": "CG",  # Congo (Republic)
    "630": "CD",  # Congo (DR)
    "631": "AO",  # Angola
    "632": "GW",  # Guinea-Bissau
    "633": "SC",  # Seychelles
    "634": "SD",  # Sudan
    "635": "RW",  # Rwanda
    "636": "ET",  # Ethiopia
    "637": "SO",  # Somalia
    "638": "DJ",  # Djibouti
    "639": "KE",  # Kenya
    "640": "TZ",  # Tanzania
    "641": "UG",  # Uganda
    "642": "BI",  # Burundi
    "643": "MZ",  # Mozambique
    "645": "ZM",  # Zambia
    "646": "MG",  # Madagascar
    "647": "RE",  # Réunion (FR)
    "648": "ZW",  # Zimbabwe
    "649": "NA",  # Namibia
    "650": "MW",  # Malawi
    "651": "LS",  # Lesotho
    "652": "BW",  # Botswana
    "653": "SZ",  # Eswatini (Swaziland)
    "654": "KM",  # Comoros
    "655": "ZA",  # South Africa
    "657": "ER",  # Eritrea
    "658": "SH",  # Saint Helena
    "659": "SS",  # South Sudan
}


def _mcc_to_country(bts_code: str) -> str:
    """Convert MCC:MNC code to ISO country code.

    Returns ISO 2-letter code or the raw bts_code if unknown.
    """
    m = re.match(r"^(\d{3}):(\d{1,3})$", bts_code.strip())
    if not m:
        return bts_code
    mcc = m.group(1)
    return _MCC_TO_COUNTRY.get(mcc, bts_code)


def _is_roaming_bts(bts_code: str) -> bool:
    """Check if BTS code indicates roaming (MCC:MNC format, non-Polish).

    Polish MCC = 260. Roaming codes look like "246:01", "257:02".
    """
    if not bts_code:
        return False
    m = re.match(r"^(\d{3}):(\d{1,3})$", bts_code.strip())
    if not m:
        return False
    mcc = m.group(1)
    return mcc != "260"


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

class OrangeRetencjaParser(BillingParser):
    """Parser for Orange Polska retencja (data retention) billing XLSX files.

    Retencja format has 3 sheets (WYKAZ, BTS, IMEI) with distinctive columns.
    Overrides parse_workbook() to coordinate cross-sheet data (BTS lookup).
    """

    OPERATOR_NAME = "Orange Polska (retencja)"
    OPERATOR_ID = "orange_retencja"

    DETECT_HEADER_PATTERNS = [
        r"identyfikator\s*u[żz]ytkownika",
        r"bts\s*a",
        r"numer\s*b",
    ]

    DETECT_SHEET_PATTERNS = [
        r"^wykaz$",
        r"^bts$",
        r"^imei$",
    ]

    # Metadata key patterns in header area (before column headers)
    _META_PATTERNS: Dict[str, str] = {
        r"msisdn": "msisdn",
        r"okres\s*od": "period_from",
        r"okres\s*do": "period_to",
        r"kierunek": "direction_filter",
        r"rodzaje?\s*po[łl][aą]cze[ńn]": "record_types_filter",
    }

    # ------------------------------------------------------------------
    # Main entry: override parse_workbook for cross-sheet parsing
    # ------------------------------------------------------------------

    def parse_workbook(
        self,
        sheets: Dict[str, List[List[Any]]],
    ) -> BillingParseResult:
        result = BillingParseResult(
            operator=self.OPERATOR_NAME,
            operator_id=self.OPERATOR_ID,
        )

        # 1) Find sheets (case-insensitive)
        wykaz_rows = None
        bts_rows = None
        imei_rows = None
        for name, rows in sheets.items():
            nl = name.lower().strip()
            if nl == "wykaz":
                wykaz_rows = rows
            elif nl == "bts":
                bts_rows = rows
            elif nl == "imei":
                imei_rows = rows

        if wykaz_rows is None:
            result.warnings.append("Nie znaleziono arkusza WYKAZ")
            return result

        # 2) Parse BTS sheet → sector lookup
        bts_lookup: Dict[str, _BtsSector] = {}
        if bts_rows:
            bts_lookup = self._parse_bts_sheet(bts_rows, result)

        # 3) Parse IMEI sheet → device info
        device_imei = ""
        device_brand = ""
        device_model = ""
        if imei_rows:
            device_imei, device_brand, device_model = self._parse_imei_sheet(
                imei_rows
            )

        # 4) Collect MSISDN from all sheets' metadata
        msisdn_candidates: List[str] = []
        for name, rows in sheets.items():
            meta = self._extract_metadata(rows)
            if meta.get("msisdn"):
                msisdn_candidates.append(
                    self.normalize_phone(meta["msisdn"])
                )
        # Also grab period metadata from WYKAZ
        wykaz_meta = self._extract_metadata(wykaz_rows)

        # 5) Parse WYKAZ data rows
        header_idx = self.find_header_row(
            wykaz_rows,
            required_keywords=[
                "data", "czas", "rp", "identyfikator", "numer",
                "bts", "imei", "imsi",
            ],
            max_scan=30,
        )
        if header_idx is None:
            result.warnings.append(
                "Nie znaleziono wiersza nagłówka w arkuszu WYKAZ"
            )
            return result

        header_row = wykaz_rows[header_idx]
        col_map = self.build_column_map(header_row, _RETENCJA_COLUMNS)

        if "date" not in col_map:
            result.warnings.append("Nie znaleziono kolumny DATA w WYKAZ")
            return result

        result.warnings.append(
            f"Orange retencja — kolumny: {list(col_map.keys())}"
        )

        # Determine subscriber MSISDN from data
        subscriber_msisdn = self._detect_subscriber_msisdn(
            wykaz_rows, header_idx, col_map, msisdn_candidates
        )

        # Build subscriber info
        subscriber = SubscriberInfo(
            operator=self.OPERATOR_NAME,
            msisdn=subscriber_msisdn,
            imei=device_imei,
        )
        if device_brand or device_model:
            subscriber.extra["device_brand"] = device_brand
            subscriber.extra["device_model"] = device_model
        if wykaz_meta.get("period_from"):
            subscriber.extra["period_from"] = wykaz_meta["period_from"]
        if wykaz_meta.get("period_to"):
            subscriber.extra["period_to"] = wykaz_meta["period_to"]

        # Normalized subscriber number for direction comparison
        sub_digits = re.sub(r"[^\d]", "", subscriber_msisdn)

        # Parse data rows
        for row_idx, row in enumerate(
            wykaz_rows[header_idx + 1 :], start=header_idx + 2
        ):
            if not row or all(
                c is None or str(c).strip() == "" for c in row
            ):
                continue

            date_val = self.get_cell(row, col_map.get("date"))
            if not date_val or date_val.lower().startswith("koniec"):
                continue

            dt = self.parse_datetime(date_val)
            if not dt:
                continue

            rp = self.get_cell(row, col_map.get("rp")).upper()
            ident_raw = row[col_map["ident"]] if "ident" in col_map else None
            ident = _to_str(ident_raw)
            number_b_raw = (
                row[col_map["number_b"]] if "number_b" in col_map else None
            )
            number_b = _to_str(number_b_raw)

            bts_a = self.get_cell(row, col_map.get("bts_a"))
            bts_b = self.get_cell(row, col_map.get("bts_b"))
            imei_a = self.get_cell(row, col_map.get("imei_a"))
            imsi_a = self.get_cell(row, col_map.get("imsi_a"))
            imei_b = self.get_cell(row, col_map.get("imei_b"))
            imsi_b = self.get_cell(row, col_map.get("imsi_b"))

            # Duration from CZAS column (seconds)
            dur_str = self.get_cell(row, col_map.get("duration"))
            duration = 0
            if dur_str:
                try:
                    duration = int(float(dur_str))
                except (ValueError, TypeError):
                    duration = 0

            # Direction detection
            is_outgoing = self._is_outgoing(ident, sub_digits)

            # Record type classification
            record_type = self._classify_rp(rp, is_outgoing)

            # Caller / callee
            if is_outgoing:
                caller = self.normalize_phone(ident)
                callee = self.normalize_phone(number_b)
                sub_bts = bts_a
                sub_imei = imei_a
                sub_imsi = imsi_a
            else:
                caller = self.normalize_phone(ident)
                callee = self.normalize_phone(number_b)
                sub_bts = bts_b
                sub_imei = imei_b
                sub_imsi = imsi_b

            # BTS lookup for subscriber location
            location = ""
            bts_lat = ""
            bts_lon = ""
            bts_azimuth = ""
            bts_range = ""
            bts_city = ""
            bts_street = ""

            if sub_bts and sub_bts != "-":
                sector = bts_lookup.get(sub_bts)
                if sector:
                    bts_lat = str(sector.lat) if sector.lat else ""
                    bts_lon = str(sector.lon) if sector.lon else ""
                    bts_azimuth = sector.azimuth
                    bts_range = sector.range_km
                    bts_city = sector.city
                    bts_street = sector.street
                    if bts_city and bts_street:
                        location = f"{bts_city}, {bts_street}"
                    elif bts_city:
                        location = bts_city
                    elif bts_street:
                        location = bts_street

            # Roaming detection — convert MCC:MNC to ISO country code
            roaming = _is_roaming_bts(sub_bts)
            roaming_country = _mcc_to_country(sub_bts) if roaming else ""

            # Direction label for frontend "Kierunek" column
            direction_label = "wychodzące" if is_outgoing else "przychodzące"

            record = BillingRecord(
                datetime=dt,
                caller=caller,
                callee=callee,
                record_type=record_type,
                duration_seconds=duration,
                location=location,
                location_lac="",
                location_cell_id="",
                roaming=roaming,
                roaming_country=roaming_country,
                network="",
                imsi=sub_imsi if sub_imsi != "-" else "",
                imei=sub_imei if sub_imei != "-" else "",
                raw_row=row_idx,
                extra={
                    "bts_a": bts_a if bts_a != "-" else "",
                    "bts_b": bts_b if bts_b != "-" else "",
                    "bts_x": bts_lat,
                    "bts_y": bts_lon,
                    "azimuth": bts_azimuth,
                    "range_km": bts_range,
                    "bts_city": bts_city,
                    "bts_street": bts_street,
                    "imei_b": imei_b if imei_b != "-" else "",
                    "imsi_b": imsi_b if imsi_b != "-" else "",
                    "rp_original": rp,
                    "direction": direction_label,
                    "roaming_mcc_mnc": sub_bts if roaming else "",
                },
            )
            result.records.append(record)

            # Populate subscriber IMSI/IMEI from first outgoing data row
            if is_outgoing:
                if not subscriber.imsi and imsi_a and imsi_a != "-":
                    subscriber.imsi = imsi_a
                if not subscriber.imei and imei_a and imei_a != "-":
                    subscriber.imei = imei_a

        result.subscriber = subscriber
        result.summary = compute_summary(result.records)

        # Override summary period from metadata
        if wykaz_meta.get("period_from"):
            parsed_from = self.parse_datetime(wykaz_meta["period_from"])
            if parsed_from:
                result.summary.period_from = parsed_from.split(" ")[0]
        if wykaz_meta.get("period_to"):
            parsed_to = self.parse_datetime(wykaz_meta["period_to"])
            if parsed_to:
                result.summary.period_to = parsed_to.split(" ")[0]

        return result

    def parse_sheet(
        self,
        rows: List[List[Any]],
        sheet_name: str = "",
    ) -> BillingParseResult:
        """Not used directly — parse_workbook handles cross-sheet logic."""
        return BillingParseResult(
            operator=self.OPERATOR_NAME,
            operator_id=self.OPERATOR_ID,
            sheet_name=sheet_name,
            warnings=[
                "OrangeRetencjaParser wymaga parse_workbook() zamiast parse_sheet()"
            ],
        )

    # ------------------------------------------------------------------
    # BTS sheet parsing
    # ------------------------------------------------------------------

    def _parse_bts_sheet(
        self,
        rows: List[List[Any]],
        result: BillingParseResult,
    ) -> Dict[str, _BtsSector]:
        """Parse BTS sheet into sector code → location lookup."""
        header_idx = self.find_header_row(
            rows,
            required_keywords=[
                "sektor", "kod", "miejscow", "ulica", "azym",
                "szerok", "długoś", "dlugosc", "zasięg", "zasieg",
            ],
            max_scan=30,
        )
        if header_idx is None:
            result.warnings.append(
                "Nie znaleziono nagłówka w arkuszu BTS"
            )
            return {}

        header_row = rows[header_idx]
        col_map = self.build_column_map(header_row, _BTS_COLUMNS)

        if "sector" not in col_map:
            result.warnings.append(
                "Nie znaleziono kolumny SEKTOR w arkuszu BTS"
            )
            return {}

        lookup: Dict[str, _BtsSector] = {}

        for row in rows[header_idx + 1 :]:
            if not row or all(
                c is None or str(c).strip() == "" for c in row
            ):
                continue

            sector_code = self.get_cell(row, col_map.get("sector"))
            if not sector_code or sector_code.lower().startswith("koniec"):
                continue

            lat_dms = self.get_cell(row, col_map.get("latitude"))
            lon_dms = self.get_cell(row, col_map.get("longitude"))
            lat = _parse_dms(lat_dms)
            lon = _parse_dms(lon_dms)

            sector = _BtsSector(
                code=sector_code,
                lat=lat or 0.0,
                lon=lon or 0.0,
                azimuth=self.get_cell(row, col_map.get("azimuth")),
                range_km=self.get_cell(row, col_map.get("range_km")),
                city=self.get_cell(row, col_map.get("city")),
                street=self.get_cell(row, col_map.get("street")),
            )
            lookup[sector_code] = sector

        result.warnings.append(
            f"BTS: załadowano {len(lookup)} sektorów"
        )
        return lookup

    # ------------------------------------------------------------------
    # IMEI sheet parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_imei_sheet(
        rows: List[List[Any]],
    ) -> tuple:
        """Parse IMEI sheet. Returns (imei, brand, model)."""
        header_idx = None
        for i, row in enumerate(rows[:20]):
            cells_lower = [
                str(c).strip().lower() if c else "" for c in row
            ]
            # Look for a row where one cell is exactly 'imei' (column header),
            # not a title row like "ANALIZA NUMERÓW IMEI WYSTĘPUJĄCYCH..."
            if any(c == "imei" for c in cells_lower):
                header_idx = i
                break

        if header_idx is None:
            return "", "", ""

        # Check if header has brand/model columns
        header_row = rows[header_idx]
        header_lower = [
            str(c).strip().lower() if c else "" for c in header_row
        ]

        imei_col = None
        brand_col = None
        model_col = None
        for j, h in enumerate(header_lower):
            if h == "imei" and imei_col is None:
                imei_col = j
            if "marka" in h:
                brand_col = j
            if "model" in h:
                model_col = j

        if imei_col is None:
            return "", "", ""

        # Read first data row
        for row in rows[header_idx + 1 :]:
            if not row:
                continue
            cells = [str(c).strip() if c else "" for c in row]
            if not cells[0] or cells[0].lower().startswith("koniec"):
                continue

            imei = _to_str(row[imei_col]) if imei_col < len(row) else ""
            # Skip the LP (ordinal) column — IMEI is the value column
            if imei and len(imei) < 10 and imei_col + 1 < len(row):
                imei = _to_str(row[imei_col + 1])
            brand = (
                _to_str(row[brand_col]) if brand_col and brand_col < len(row) else ""
            )
            model = (
                _to_str(row[model_col]) if model_col and model_col < len(row) else ""
            )
            return imei, brand, model

        return "", "", ""

    # ------------------------------------------------------------------
    # Metadata extraction
    # ------------------------------------------------------------------

    def _extract_metadata(
        self, rows: List[List[Any]]
    ) -> Dict[str, str]:
        """Extract metadata from header area (before column headers)."""
        meta: Dict[str, str] = {}
        for row in rows[:20]:
            text = " ".join(
                str(c).strip() for c in row if c is not None and str(c).strip()
            )
            if not text:
                continue
            for pattern, key in self._META_PATTERNS.items():
                if key in meta:
                    continue
                m = re.search(
                    pattern + r"\s*[:\-]?\s*(.+)",
                    text,
                    re.I,
                )
                if m:
                    val = m.group(1).strip()
                    if val:
                        meta[key] = val
            # Also handle "MSISDN" as a cell label followed by value in next cell
            if len(row) >= 2:
                first = str(row[0]).strip().upper() if row[0] else ""
                if first == "MSISDN" and row[1] is not None:
                    if "msisdn" not in meta:
                        meta["msisdn"] = _to_str(row[1])
        return meta

    # ------------------------------------------------------------------
    # Subscriber detection
    # ------------------------------------------------------------------

    def _detect_subscriber_msisdn(
        self,
        rows: List[List[Any]],
        header_idx: int,
        col_map: Dict[str, int],
        candidates: List[str],
    ) -> str:
        """Detect subscriber MSISDN by analyzing data rows.

        The subscriber's number appears in IDENT (outgoing) or NUMER_B (incoming).
        We count frequency and pick the most common phone number.
        """
        from collections import Counter

        counter: Counter = Counter()
        for row in rows[header_idx + 1 : header_idx + 200]:
            if not row:
                continue
            ident_raw = row[col_map["ident"]] if "ident" in col_map else None
            nb_raw = row[col_map["number_b"]] if "number_b" in col_map else None

            if _is_phone_number(ident_raw):
                num = self.normalize_phone(_to_str(ident_raw))
                counter[num] += 1
            if _is_phone_number(nb_raw):
                num = self.normalize_phone(_to_str(nb_raw))
                counter[num] += 1

        if not counter:
            return candidates[0] if candidates else ""

        # Pick most common number
        most_common = counter.most_common(1)[0][0]

        # Check if any metadata candidate matches
        for cand in candidates:
            cand_digits = re.sub(r"[^\d]", "", cand)
            mc_digits = re.sub(r"[^\d]", "", most_common)
            if cand_digits and mc_digits and cand_digits in mc_digits:
                return most_common

        return most_common

    # ------------------------------------------------------------------
    # Direction & record type
    # ------------------------------------------------------------------

    @staticmethod
    def _is_outgoing(ident: str, subscriber_digits: str) -> bool:
        """Determine if the record is outgoing (subscriber is party A)."""
        if not ident or not subscriber_digits:
            return True  # default to outgoing
        # Check if IDENT is the subscriber's number
        ident_digits = re.sub(r"[^\d]", "", ident)
        if ident_digits and subscriber_digits:
            # Compare last 9 digits (ignoring country code differences)
            if len(ident_digits) >= 9 and len(subscriber_digits) >= 9:
                if ident_digits[-9:] == subscriber_digits[-9:]:
                    return True
        # If IDENT is not a phone number (alphanumeric sender) → incoming
        if not _is_phone_number(ident):
            return False
        # IDENT is a phone number but not the subscriber → incoming
        return False

    @staticmethod
    def _classify_rp(rp: str, is_outgoing: bool) -> str:
        """Map Orange retencja RP value to standard record type.

        RP values: VOICE, SMS, DATA, VoIP, PRÓBA, PRÓBA_SMSD, PRÓBA_SMSW, ROAMING
        """
        rp_upper = rp.upper().strip()

        if rp_upper == "VOICE":
            return "CALL_OUT" if is_outgoing else "CALL_IN"

        if rp_upper == "SMS":
            return "SMS_OUT" if is_outgoing else "SMS_IN"

        if rp_upper == "DATA":
            return "DATA"

        if rp_upper == "VOIP":
            return "CALL_OUT" if is_outgoing else "CALL_IN"

        # PRÓBA = call attempt (no answer / failed)
        if rp_upper in ("PRÓBA", "PROBA", "PR\xd3BA"):
            return "CALL_OUT" if is_outgoing else "CALL_IN"

        # PRÓBA_SMSD = SMS delivery attempt (incoming SMS that failed)
        if rp_upper in ("PRÓBA_SMSD", "PROBA_SMSD", "PR\xd3BA_SMSD"):
            return "SMS_IN"

        # PRÓBA_SMSW = SMS send attempt (outgoing SMS that failed)
        if rp_upper in ("PRÓBA_SMSW", "PROBA_SMSW", "PR\xd3BA_SMSW"):
            return "SMS_OUT"

        if rp_upper == "ROAMING":
            return "CALL_OUT" if is_outgoing else "CALL_IN"

        if rp_upper == "MMS":
            return "MMS_OUT" if is_outgoing else "MMS_IN"

        return "OTHER"
