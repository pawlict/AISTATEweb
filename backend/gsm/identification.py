"""GSM subscriber identification file parsers.

Parses identification (subscriber data) files from Polish operators:
- Orange:  XLSX with "7. DANE OSOBOWE" header
- Play:    CSV (semicolon-delimited, cp1250 encoding, ="" quoting)
- Plus:    CSV (comma-delimited, utf-8-sig encoding)
- T-Mobile: (future — extend as needed)

Each parser normalises phone numbers and extracts:
  number, name, pesel, nip, regon, address, city, operator info, type,
  activation/deactivation dates, sim, imsi, document number.

Usage:
    store = IdentificationStore()
    store.load_file(path)                 # auto-detect and parse
    info = store.lookup("48501234567")    # lookup by MSISDN
    info_short = store.lookup_short("+48501234567")  # compact label
"""

from __future__ import annotations

import csv
import io
import logging
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger("aistate.gsm.identification")


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class SubscriberIdentification:
    """Identification data for a single phone number."""

    number: str = ""           # normalised MSISDN  e.g. "48501234567"
    name: str = ""             # imię i nazwisko / nazwa firmy
    pesel: str = ""
    nip: str = ""
    regon: str = ""
    address: str = ""          # full address string
    city: str = ""
    document_number: str = ""
    document_type: str = ""
    subscriber_type: str = ""  # I=indywidualny, B=biznesowy, post-paid, pre-paid etc.
    operator: str = ""         # operator name / code
    activation_date: str = ""
    deactivation_date: str = ""
    sim: str = ""              # SIM ICCID
    imsi: str = ""
    service_type: str = ""     # e.g. NUMERY HURTOWE, Telefonia mobilna
    tariff: str = ""
    status: str = ""           # Aktywna, Nie znaleziono, etc.
    notes: str = ""            # extra info / uwagi
    source_file: str = ""      # which file this came from
    source_operator: str = ""  # orange / play / plus / tmobile

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    # Phrases indicating "no data" / "not found" / "different operator"
    _NO_DATA_PHRASES = (
        "nie znaleziono", "nie był przydzielony", "nie obsługiwany",
        "numer nie obsługiwany", "brak danych", "brak informacji",
        "nie zidentyfikowano", "numer nieaktywny",
        "obsługiwany przez", "przeniesiony",
    )

    @property
    def has_owner_data(self) -> bool:
        """True if we have actual owner identification (not just 'not found')."""
        if not self.name:
            return False
        name_lower = self.name.lower().strip()
        return not any(ph in name_lower for ph in self._NO_DATA_PHRASES)

    @property
    def identification_type(self) -> str:
        """Type of identification result: 'person', 'company', 'other_operator', 'not_found', 'unknown'."""
        if not self.name:
            return "unknown"
        name_lower = self.name.lower().strip()

        # Check if it's a "different operator" message
        if "obsługiwany przez" in name_lower or "przeniesiony" in name_lower:
            return "other_operator"

        # Check for "not found" / "not assigned"
        if any(ph in name_lower for ph in self._NO_DATA_PHRASES):
            return "not_found"

        # Person vs company: companies have legal form indicators
        company_indicators = (
            "sp. z o.o", "spółka", "s.a.", "sp.j.", "sp.k.",
            "fundacja", "stowarzyszenie", "urząd", "szkoła",
            "zakład", "przedsiębiorstwo", "firma", "gospodarstwo",
        )
        if any(ind in name_lower for ind in company_indicators):
            return "company"

        # If has PESEL → person
        if self.pesel:
            return "person"

        # If has NIP/REGON → company
        if self.nip or self.regon:
            return "company"

        # Default: assume person if name looks like "Imie Nazwisko"
        words = self.name.strip().split()
        if 2 <= len(words) <= 4 and all(w[0].isupper() for w in words if w):
            return "person"

        return "unknown"

    @property
    def display_label(self) -> str:
        """Short display string for UI table column."""
        id_type = self.identification_type

        if id_type == "other_operator":
            # Extract operator name from message
            m = re.search(r'obsługiwany przez\s*[-–—]?\s*(.+)', self.name, re.IGNORECASE)
            if m:
                op_name = m.group(1).strip().rstrip(".")
                return f"[inny oper.: {op_name}]"
            if "przeniesiony" in self.name.lower():
                return "[przeniesiony do innego oper.]"
            return "[inny operator]"

        if id_type == "not_found":
            return f"[brak danych]"

        parts = []
        if self.name:
            parts.append(self.name)
        if self.city:
            parts.append(self.city)
        return ", ".join(parts) if parts else self.status or "[brak danych]"


# ---------------------------------------------------------------------------
# Phone number normalisation
# ---------------------------------------------------------------------------

_RE_NONDIGIT = re.compile(r"\D")

def normalise_msisdn(raw: str) -> str:
    """Normalise an MSISDN to digits-only, 11-digit (48xxx) format.

    Handles: +48XXXXXXXXX, 48XXXXXXXXX, 9-digit, ='48...' formats.
    """
    if not raw:
        return ""
    s = str(raw).strip()
    # Strip ="" quoting from Play CSVs
    s = s.strip("=").strip('"').strip("'")
    s = _RE_NONDIGIT.sub("", s)
    # Remove leading +
    if s.startswith("0048"):
        s = s[2:]
    if len(s) == 9:
        s = "48" + s
    return s


# ---------------------------------------------------------------------------
# Orange parser (XLSX)
# ---------------------------------------------------------------------------

def _parse_orange_xlsx(file_path: Path) -> List[SubscriberIdentification]:
    """Parse Orange '7. DANE OSOBOWE' identification XLSX.

    Structure:
        Row 1:  "7. DANE OSOBOWE"
        Row 7:  Header: LP | IDENTYFIKATOR USŁUGI | OPER | RU | RU2 |
                DATA AKT. | DATA DEZAKT. | TYP | ABONENT | PESEL/REGON/NIP |
                KOD | MIASTO | ULICA NR | KOD_2 | MIASTO_2 | ULICA NR_2 | NUMER GŁÓWNY
        Row 8+: Data rows until "KONIEC WYKAZU"
    """
    import openpyxl

    results: List[SubscriberIdentification] = []
    wb = openpyxl.load_workbook(file_path, data_only=True, read_only=True)

    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            continue

        # Find header row (contains "IDENTYFIKATOR USŁUGI")
        header_idx = None
        for i, row in enumerate(rows):
            cells = [str(c or "").strip().upper() for c in row]
            if any("IDENTYFIKATOR" in c for c in cells):
                header_idx = i
                break

        if header_idx is None:
            log.warning("Orange ID: header row not found in sheet %s", sheet_name)
            continue

        header = [str(c or "").strip().upper() for c in rows[header_idx]]

        # Map column indices
        col_map = {}
        for ci, h in enumerate(header):
            if "IDENTYFIKATOR" in h:
                col_map["msisdn"] = ci
            elif h == "OPER":
                col_map["oper"] = ci
            elif h == "RU":
                col_map["ru"] = ci
            elif h.startswith("DATA AKT"):
                col_map["activation"] = ci
            elif h.startswith("DATA DEZAKT"):
                col_map["deactivation"] = ci
            elif h == "TYP":
                col_map["type"] = ci
            elif h == "ABONENT":
                col_map["name"] = ci
            elif "PESEL" in h:
                col_map["pesel_nip"] = ci
            elif h == "KOD":
                col_map["zip"] = ci
            elif h == "MIASTO" and "miasto" not in col_map:
                col_map["miasto"] = ci
            elif h.startswith("ULICA"):
                if "street" not in col_map:
                    col_map["street"] = ci
            elif h == "NUMER G" or "GŁÓWNY" in h:
                col_map["main_number"] = ci

        def _cell(row, key):
            idx = col_map.get(key)
            if idx is None or idx >= len(row):
                return ""
            return str(row[idx] or "").strip()

        # Parse data rows
        for row in rows[header_idx + 1:]:
            cells_str = [str(c or "").strip() for c in row]
            # Stop at "KONIEC WYKAZU"
            if any("KONIEC" in c.upper() for c in cells_str[:3]):
                break
            # Skip empty rows
            msisdn_raw = _cell(row, "msisdn")
            if not msisdn_raw:
                continue

            msisdn = normalise_msisdn(msisdn_raw)
            if not msisdn:
                continue

            name = _cell(row, "name")
            pesel_nip = _cell(row, "pesel_nip")
            city = _cell(row, "miasto")
            street = _cell(row, "street")
            zipcode = _cell(row, "zip")

            # Build address
            addr_parts = []
            if street:
                addr_parts.append(street)
            if zipcode:
                addr_parts.append(zipcode)
            if city:
                addr_parts.append(city)
            address = ", ".join(addr_parts)

            # Parse PESEL/NIP/REGON
            pesel, nip, regon = "", "", ""
            if pesel_nip:
                pn = _RE_NONDIGIT.sub("", pesel_nip)
                if len(pn) == 11:
                    pesel = pn
                elif len(pn) == 10:
                    nip = pn
                elif len(pn) == 9 or len(pn) == 14:
                    regon = pn

            sub_type = _cell(row, "type")

            results.append(SubscriberIdentification(
                number=msisdn,
                name=name,
                pesel=pesel,
                nip=nip,
                regon=regon,
                address=address,
                city=city,
                subscriber_type=sub_type,
                operator=_cell(row, "oper"),
                activation_date=_cell(row, "activation"),
                deactivation_date=_cell(row, "deactivation"),
                source_file=file_path.name,
                source_operator="orange",
            ))

    wb.close()
    return results


# ---------------------------------------------------------------------------
# Play parser (CSV, semicolon, cp1250, ="" quoting)
# ---------------------------------------------------------------------------

def _parse_play_csv(file_path: Path) -> List[SubscriberIdentification]:
    """Parse Play identification CSV.

    - Semicolon-delimited
    - Encoding: cp1250 (Polish Windows)
    - Values wrapped in ="" quoting: ="value"
    - Header: DATA_OD;DATA_DO;MSISDN_PSTN;SIM_NUMER;IMSI;PESEL;REGON;NIP;
              IMIE;NAZWISKO;NAZWA;ADRES;PIERWSZE_LOGOWANIE;UWAGI;USLUGA;TARYFA;
              ID_USLUGI;ID_LACZA;NR_DOKUMENTU;TYP_DOKUMENTU;...
    """
    results: List[SubscriberIdentification] = []

    # Try encodings
    content = None
    for enc in ("utf-8-sig", "utf-8", "cp1250", "latin-1"):
        try:
            content = file_path.read_text(encoding=enc)
            break
        except (UnicodeDecodeError, UnicodeError):
            continue

    if content is None:
        log.error("Play ID: cannot decode %s", file_path)
        return results

    # Strip ="" quoting
    def strip_eq(val: str) -> str:
        v = val.strip()
        if v.startswith('="') and v.endswith('"'):
            return v[2:-1]
        if v.startswith("='") and v.endswith("'"):
            return v[2:-1]
        return v

    reader = csv.reader(io.StringIO(content), delimiter=";")
    header = None

    for row_idx, row in enumerate(reader):
        if not row:
            continue

        # Find header row
        if header is None:
            cleaned = [strip_eq(c).upper().strip() for c in row]
            if any("MSISDN" in c for c in cleaned):
                header = cleaned
                continue
            else:
                continue

        # Parse data row
        cells = [strip_eq(c) for c in row]

        def _col(name):
            """Get column value by header name (partial match)."""
            for i, h in enumerate(header):
                if name in h:
                    return cells[i] if i < len(cells) else ""
            return ""

        msisdn_raw = _col("MSISDN")
        if not msisdn_raw:
            continue
        msisdn = normalise_msisdn(msisdn_raw)
        if not msisdn:
            continue

        imie = _col("IMIE")
        nazwisko = _col("NAZWISKO")
        nazwa = _col("NAZWA")
        name = ""
        if imie or nazwisko:
            name = f"{imie} {nazwisko}".strip()
        elif nazwa:
            name = nazwa

        pesel = _col("PESEL")
        nip = _col("NIP")
        regon = _col("REGON")

        address_raw = _col("ADRES")
        # Play uses "Adres glowny: ... | Adres korespondencyjny: ..."
        address = address_raw.split("|")[0].strip()
        if address.lower().startswith("adres glowny:"):
            address = address[len("adres glowny:"):].strip()
        elif address.lower().startswith("adres główny:"):
            address = address[len("adres główny:"):].strip()

        # Extract city from address (last part after postal code)
        city = ""
        addr_match = re.search(r'\d{2}-\d{3}\s+(.+?)(?:\||$)', address_raw)
        if addr_match:
            city = addr_match.group(1).strip()

        sim = _col("SIM")
        imsi = _col("IMSI")
        service = _col("USLUGA")
        tariff = _col("TARYFA")
        doc_nr = _col("NR_DOKUMENTU")
        doc_type = _col("TYP_DOKUMENTU")
        uwagi = _col("UWAGI")
        data_od = _col("DATA_OD")
        data_do = _col("DATA_DO")

        results.append(SubscriberIdentification(
            number=msisdn,
            name=name,
            pesel=pesel,
            nip=nip,
            regon=regon,
            address=address,
            city=city,
            sim=sim,
            imsi=imsi,
            service_type=service,
            tariff=tariff,
            document_number=doc_nr,
            document_type=doc_type,
            notes=uwagi,
            activation_date=data_od,
            deactivation_date=data_do,
            source_file=file_path.name,
            source_operator="play",
        ))

    return results


# ---------------------------------------------------------------------------
# Plus parser (CSV, comma, utf-8-sig)
# ---------------------------------------------------------------------------

def _parse_plus_csv(file_path: Path) -> List[SubscriberIdentification]:
    """Parse Plus (Polkomtel) identification CSV.

    - Comma-delimited
    - Encoding: utf-8-sig
    - Header: Parametr,MSISDN,PESEL,SIM,Numer dokumentu,Typ dokumentu,NIP,
              Typ MSISDN,Ważne od,Ważne do,Imię i Nazwisko/Nazwa,Adres,Status
    """
    results: List[SubscriberIdentification] = []

    content = None
    for enc in ("utf-8-sig", "utf-8", "cp1250", "latin-1"):
        try:
            content = file_path.read_text(encoding=enc)
            break
        except (UnicodeDecodeError, UnicodeError):
            continue

    if content is None:
        log.error("Plus ID: cannot decode %s", file_path)
        return results

    reader = csv.reader(io.StringIO(content), delimiter=",")
    header = None

    for row_idx, row in enumerate(reader):
        if not row:
            continue

        # Find header row
        if header is None:
            cleaned = [c.strip().upper() for c in row]
            if any("MSISDN" in c for c in cleaned):
                header = cleaned
                continue
            else:
                continue

        cells = [c.strip() for c in row]

        # Handle Plus format quirk: first cell may contain comma-separated
        # list of MSISDNs (the "Parametr" column) when multiple numbers
        # were queried. Actual data starts from next rows with individual records.
        # In multi-number query files, Parametr column has the full request list
        # and MSISDN column has the resolved number.

        def _col(name):
            for i, h in enumerate(header):
                if name in h:
                    return cells[i] if i < len(cells) else ""
            return ""

        msisdn_raw = _col("MSISDN")
        if not msisdn_raw:
            # Try "Parametr" column
            msisdn_raw = _col("PARAMETR")
        if not msisdn_raw:
            continue
        msisdn = normalise_msisdn(msisdn_raw)
        if not msisdn:
            continue

        name = _col("NAZWISKO") or _col("NAZWA")
        if not name:
            # Try "Imię i Nazwisko" combined column
            for i, h in enumerate(header):
                if "NAZWISK" in h or "NAZWA" in h:
                    name = cells[i] if i < len(cells) else ""
                    break

        pesel = _col("PESEL")
        nip = _col("NIP")
        sim = _col("SIM")
        doc_nr = _col("NUMER DOKUMENTU") or _col("NR_DOKUMENTU")
        doc_type = _col("TYP DOKUMENTU") or _col("TYP_DOKUMENTU")
        msisdn_type = _col("TYP MSISDN") or _col("TYP")
        valid_from = _col("OD")
        valid_to = _col("DO")
        address = _col("ADRES")
        status = _col("STATUS")

        # Extract city from address (e.g. "UL. TRAKTOROWA 126 91-204 ŁÓDŹ POL")
        city = ""
        addr_match = re.search(r'\d{2}-\d{3}\s+(.+?)(?:\s+POL\s*$|\s*$)', address, re.IGNORECASE)
        if addr_match:
            city = addr_match.group(1).strip()
            # Remove trailing country code
            city = re.sub(r'\s+POL\s*$', '', city, flags=re.IGNORECASE).strip()

        results.append(SubscriberIdentification(
            number=msisdn,
            name=name,
            pesel=pesel,
            nip=nip,
            address=address,
            city=city,
            sim=sim,
            document_number=doc_nr,
            document_type=doc_type,
            subscriber_type=msisdn_type,
            activation_date=valid_from,
            deactivation_date=valid_to,
            status=status,
            source_file=file_path.name,
            source_operator="plus",
        ))

    return results


# ---------------------------------------------------------------------------
# Auto-detection and store
# ---------------------------------------------------------------------------

def detect_id_format(file_path: Path) -> Optional[str]:
    """Detect the operator format of an identification file.

    Returns: "orange", "play", "plus", or None.
    """
    suffix = file_path.suffix.lower()

    if suffix in (".xlsx", ".xls"):
        # Orange uses XLSX
        try:
            import openpyxl
            wb = openpyxl.load_workbook(file_path, data_only=True, read_only=True)
            for sheet_name in wb.sheetnames:
                ws = wb[sheet_name]
                for row in ws.iter_rows(max_row=10, values_only=True):
                    text = " ".join(str(c or "") for c in row).upper()
                    if "DANE OSOBOWE" in text or "IDENTYFIKATOR USŁUGI" in text:
                        wb.close()
                        return "orange"
            wb.close()
        except Exception as e:
            log.debug("detect_id_format XLSX error: %s", e)
        return None

    if suffix == ".csv":
        # Read first few lines to detect format
        content = None
        for enc in ("utf-8-sig", "utf-8", "cp1250", "latin-1"):
            try:
                content = file_path.read_text(encoding=enc, errors="replace")
                break
            except Exception:
                continue
        if not content:
            return None

        first_lines = content[:2000].upper()

        # Play: semicolon-delimited, has MSISDN_PSTN
        if "MSISDN_PSTN" in first_lines and ";" in first_lines[:500]:
            return "play"

        # Plus: comma-delimited, has "Typ MSISDN" or "Ważne od"
        if ("TYP MSISDN" in first_lines or "WAŻNE OD" in first_lines.upper()
                or "WAZNE OD" in first_lines):
            return "plus"

        # Fallback: check for MSISDN header with comma delimiter
        if "MSISDN" in first_lines and "," in first_lines[:500]:
            return "plus"

        # Fallback: check for semicolon-delimited with MSISDN
        if "MSISDN" in first_lines and ";" in first_lines[:500]:
            return "play"

    return None


def parse_identification_file(file_path: Path) -> List[SubscriberIdentification]:
    """Auto-detect format and parse an identification file.

    Returns list of SubscriberIdentification records.
    """
    fmt = detect_id_format(file_path)
    if fmt is None:
        log.warning("Cannot detect format of identification file: %s", file_path)
        return []

    log.info("Parsing identification file: %s (format: %s)", file_path.name, fmt)

    if fmt == "orange":
        return _parse_orange_xlsx(file_path)
    elif fmt == "play":
        return _parse_play_csv(file_path)
    elif fmt == "plus":
        return _parse_plus_csv(file_path)
    else:
        return []


class IdentificationStore:
    """In-memory store of identification data for phone number lookups.

    Usage:
        store = IdentificationStore()
        store.load_file(Path("orange_id.xlsx"))
        store.load_file(Path("play_id.csv"))
        info = store.lookup("48501234567")  # SubscriberIdentification or None
    """

    def __init__(self):
        self._records: Dict[str, SubscriberIdentification] = {}
        self._files_loaded: List[str] = []

    @property
    def count(self) -> int:
        return len(self._records)

    @property
    def files_loaded(self) -> List[str]:
        return list(self._files_loaded)

    def load_file(self, file_path: Path) -> int:
        """Parse and load an identification file. Returns number of records loaded."""
        records = parse_identification_file(file_path)
        count = 0
        for rec in records:
            if rec.number:
                # Keep the most informative record (prefer one with a name)
                existing = self._records.get(rec.number)
                if existing is None or (not existing.name and rec.name):
                    self._records[rec.number] = rec
                    count += 1
        self._files_loaded.append(file_path.name)
        log.info("Loaded %d identification records from %s (total: %d)",
                 count, file_path.name, len(self._records))
        return count

    def load_files(self, file_paths: List[Path]) -> int:
        """Load multiple identification files."""
        total = 0
        for fp in file_paths:
            total += self.load_file(fp)
        return total

    def lookup(self, number: str) -> Optional[SubscriberIdentification]:
        """Look up identification by phone number.

        Accepts various formats: +48XXXXXXXXX, 48XXXXXXXXX, 9-digit
        """
        msisdn = normalise_msisdn(number)
        return self._records.get(msisdn)

    def lookup_label(self, number: str) -> str:
        """Get a short display label for a phone number.

        Returns e.g. "Jan Kowalski, Warszawa" or "" if not found.
        """
        rec = self.lookup(number)
        if rec is None:
            return ""
        return rec.display_label

    def to_dict(self) -> Dict[str, Any]:
        """Export all records as a dict keyed by normalised MSISDN."""
        return {k: v.to_dict() for k, v in self._records.items()}

    def get_all(self) -> List[SubscriberIdentification]:
        """Get all loaded records."""
        return list(self._records.values())

    def clear(self):
        """Clear all loaded data."""
        self._records.clear()
        self._files_loaded.clear()
