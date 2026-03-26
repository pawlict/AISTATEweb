"""Parser for subscriber identification files.

Operators provide separate XLSX/CSV files with subscriber identification data
(dane identyfikujące abonenta) alongside billing files. This module extracts
subscriber metadata from those files.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from .parsers.base import SubscriberInfo


# Common label patterns for subscriber fields (Polish)
_FIELD_PATTERNS: Dict[str, List[str]] = {
    "msisdn": [
        r"msisdn",
        r"numer\s*(?:telefonu|abonenta|sim)",
        r"nr\s*tel",
        r"numer\s*kierunkowy",
    ],
    "imsi": [
        r"imsi",
    ],
    "imei": [
        r"imei",
    ],
    "sim_iccid": [
        r"iccid",
        r"numer\s*(?:karty\s*)?sim",
        r"nr\s*sim",
    ],
    "owner_name": [
        r"(?:imi[ęe]\s*i\s*)?nazwisko",
        r"nazwa\s*(?:abonenta|u[żz]ytkownika|firmy|klienta)",
        r"abonent",
        r"u[żz]ytkownik",
        r"w[łl]a[śs]ciciel",
        r"dane\s*osobowe",
    ],
    "owner_address": [
        r"adres",
        r"ulica",
        r"miejscowo[śs][ćc]",
        r"kod\s*pocztowy",
    ],
    "owner_pesel": [
        r"pesel",
    ],
    "owner_id_number": [
        r"(?:nr|numer)\s*(?:dowodu|paszportu|dokumentu)",
        r"dokument\s*to[żz]samo[śs]ci",
        r"seria\s*(?:i\s*)?nr",
    ],
    "activation_date": [
        r"data\s*aktywacji",
        r"data\s*(?:w[łl][aą]czenia|uruchomienia)",
        r"aktywacja",
    ],
    "tariff": [
        r"(?:plan|taryfa|oferta)",
        r"pakiet",
    ],
    "operator": [
        r"operator",
        r"sie[ćc]",
    ],
    "contract_type": [
        r"typ\s*(?:umowy|kontraktu)",
        r"(?:abonament|prepaid|mix)",
        r"rodzaj\s*(?:umowy|us[łl]ugi)",
    ],
}


def parse_subscriber_file(
    rows: List[List[Any]],
    sheet_name: str = "",
) -> List[SubscriberInfo]:
    """Parse subscriber identification data from XLSX rows.

    Handles two common formats:
    1. Tabular: header row + data rows (one subscriber per row)
    2. Key-value pairs: label in column A, value in column B

    Args:
        rows: All rows from the sheet.
        sheet_name: Sheet name (for diagnostics).

    Returns:
        List of SubscriberInfo objects (usually 1 per file, but can be multiple).
    """
    if not rows:
        return []

    # Try tabular format first (header + data rows)
    result = _try_tabular_parse(rows)
    if result:
        return result

    # Try key-value format
    result = _try_key_value_parse(rows)
    if result:
        return result

    return []


def _try_tabular_parse(rows: List[List[Any]]) -> List[SubscriberInfo]:
    """Try to parse as a table with header row + data rows."""
    # Find header row
    header_idx = None
    for i, row in enumerate(rows[:15]):
        cells = [str(c).strip().lower() for c in row if c is not None]
        cells_text = "|".join(cells)
        # Need at least 2 subscriber-related keywords
        matches = 0
        for patterns in _FIELD_PATTERNS.values():
            for pat in patterns:
                if re.search(pat, cells_text, re.I):
                    matches += 1
                    break
        if matches >= 2:
            header_idx = i
            break

    if header_idx is None:
        return []

    header_row = rows[header_idx]

    # Map columns
    col_map: Dict[str, int] = {}
    for col_idx, cell in enumerate(header_row):
        cell_text = str(cell).strip().lower() if cell else ""
        if not cell_text:
            continue
        for field_name, patterns in _FIELD_PATTERNS.items():
            if field_name in col_map:
                continue
            for pat in patterns:
                if re.search(pat, cell_text, re.I):
                    col_map[field_name] = col_idx
                    break

    if not col_map:
        return []

    # Parse data rows
    subscribers: List[SubscriberInfo] = []
    for row in rows[header_idx + 1:]:
        if not row or all(c is None or str(c).strip() == "" for c in row):
            continue

        info = SubscriberInfo()
        for field_name, col_idx in col_map.items():
            if col_idx >= len(row):
                continue
            val = str(row[col_idx]).strip() if row[col_idx] is not None else ""
            if not val:
                continue
            if hasattr(info, field_name):
                setattr(info, field_name, val)

        # Normalize phone number
        if info.msisdn:
            from .parsers.base import BillingParser
            info.msisdn = BillingParser.normalize_phone(info.msisdn)

        if info.msisdn or info.owner_name:
            subscribers.append(info)

    return subscribers


def _try_key_value_parse(rows: List[List[Any]]) -> List[SubscriberInfo]:
    """Try to parse as key-value pairs (label in col A, value in col B)."""
    info = SubscriberInfo()
    found_any = False

    for row in rows:
        if not row or len(row) < 2:
            continue

        label = str(row[0]).strip().lower() if row[0] is not None else ""
        value = str(row[1]).strip() if row[1] is not None else ""

        if not label or not value:
            continue

        for field_name, patterns in _FIELD_PATTERNS.items():
            for pat in patterns:
                if re.search(pat, label, re.I):
                    if hasattr(info, field_name):
                        # For address, append rather than overwrite
                        if field_name == "owner_address" and getattr(info, field_name):
                            setattr(info, field_name,
                                    getattr(info, field_name) + ", " + value)
                        else:
                            setattr(info, field_name, value)
                        found_any = True
                    break

    if not found_any:
        return []

    # Normalize phone
    if info.msisdn:
        from .parsers.base import BillingParser
        info.msisdn = BillingParser.normalize_phone(info.msisdn)

    return [info]
