"""GSM billing processing pipeline.

Orchestrates: XLSX upload → operator detection → parse → normalize → analyze → store.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import openpyxl

from .parsers.base import BillingParseResult, SubscriberInfo
from .parsers.registry import get_parser, detect_operator
from .normalize import normalize_records, extract_contact_numbers
from .subscriber import parse_subscriber_file

log = logging.getLogger(__name__)


def load_xlsx_sheets(
    path: Path,
    max_rows: int = 100_000,
    max_cols: int = 100,
) -> Dict[str, List[List[Any]]]:
    """Load all sheets from an XLSX file.

    Args:
        path: Path to the XLSX file.
        max_rows: Maximum rows per sheet (safety limit).
        max_cols: Maximum columns per sheet.

    Returns:
        Dict of sheet_name → rows (list of lists).
    """
    wb = openpyxl.load_workbook(str(path), data_only=True, read_only=True)
    sheets: Dict[str, List[List[Any]]] = {}

    try:
        for sheet_name in wb.sheetnames:
            ws = wb[sheet_name]
            rows: List[List[Any]] = []
            for i, row in enumerate(ws.iter_rows(values_only=True)):
                if i >= max_rows:
                    log.warning(
                        "Sheet '%s' truncated at %d rows", sheet_name, max_rows
                    )
                    break
                # Truncate columns
                cells = list(row[:max_cols])
                rows.append(cells)
            sheets[sheet_name] = rows
    finally:
        wb.close()

    return sheets


def _get_first_header(sheets: Dict[str, List[List[Any]]]) -> List[str]:
    """Extract first non-empty row (header candidate) from the first sheet."""
    for sheet_name, rows in sheets.items():
        for row in rows[:20]:
            cells = [str(c).strip().lower() for c in row if c is not None]
            non_empty = [c for c in cells if c]
            if len(non_empty) >= 3:
                return cells
    return []


def process_billing(
    billing_path: Path,
    subscriber_path: Optional[Path] = None,
    own_numbers: Optional[Set[str]] = None,
) -> BillingParseResult:
    """Full processing pipeline for a GSM billing XLSX file.

    Steps:
    1. Load XLSX sheets
    2. Auto-detect operator from headers/sheet names
    3. Parse billing records with operator-specific parser
    4. Optionally parse subscriber identification file
    5. Normalize records (phones, directions, dedup)
    6. Compute summary statistics

    Args:
        billing_path: Path to the billing XLSX file.
        subscriber_path: Optional path to subscriber identification XLSX.
        own_numbers: Optional set of own phone numbers for direction detection.

    Returns:
        BillingParseResult with all parsed and normalized data.
    """
    log.info("Processing billing: %s", billing_path.name)

    # 1. Load XLSX
    sheets = load_xlsx_sheets(billing_path)
    if not sheets:
        return BillingParseResult(
            warnings=["Nie udało się wczytać pliku XLSX (brak arkuszy)"]
        )

    # 2. Detect operator
    headers = _get_first_header(sheets)
    sheet_names = [s.lower() for s in sheets.keys()]
    parser = get_parser(headers, sheet_names)

    log.info("Detected operator: %s (parser: %s)", parser.OPERATOR_NAME, parser.OPERATOR_ID)

    # 3. Parse billing
    result = parser.parse_workbook(sheets)

    # 4. Parse subscriber file if provided
    if subscriber_path and subscriber_path.exists():
        try:
            sub_sheets = load_xlsx_sheets(subscriber_path, max_rows=1000)
            for sheet_name, rows in sub_sheets.items():
                subscribers = parse_subscriber_file(rows, sheet_name)
                if subscribers:
                    # Merge subscriber info
                    sub = subscribers[0]
                    if sub.msisdn and not result.subscriber.msisdn:
                        result.subscriber.msisdn = sub.msisdn
                    if sub.owner_name and not result.subscriber.owner_name:
                        result.subscriber.owner_name = sub.owner_name
                    if sub.imsi and not result.subscriber.imsi:
                        result.subscriber.imsi = sub.imsi
                    if sub.imei and not result.subscriber.imei:
                        result.subscriber.imei = sub.imei
                    if sub.owner_address and not result.subscriber.owner_address:
                        result.subscriber.owner_address = sub.owner_address
                    if sub.owner_pesel and not result.subscriber.owner_pesel:
                        result.subscriber.owner_pesel = sub.owner_pesel
                    if sub.owner_id_number and not result.subscriber.owner_id_number:
                        result.subscriber.owner_id_number = sub.owner_id_number
                    if sub.activation_date and not result.subscriber.activation_date:
                        result.subscriber.activation_date = sub.activation_date
                    if sub.tariff and not result.subscriber.tariff:
                        result.subscriber.tariff = sub.tariff
                    if sub.sim_iccid and not result.subscriber.sim_iccid:
                        result.subscriber.sim_iccid = sub.sim_iccid
                    if sub.contract_type and not result.subscriber.contract_type:
                        result.subscriber.contract_type = sub.contract_type
                    # Store all subscribers in extra for multi-SIM scenarios
                    if len(subscribers) > 1:
                        result.subscriber.extra["additional_subscribers"] = [
                            s.to_dict() for s in subscribers[1:]
                        ]
                    break  # Use first sheet that has subscriber data
        except Exception as e:
            result.warnings.append(f"Błąd parsowania pliku abonenta: {e}")
            log.warning("Error parsing subscriber file: %s", e)

    # 5. Normalize
    effective_own = own_numbers or set()
    if result.subscriber.msisdn:
        effective_own.add(result.subscriber.msisdn)

    result = normalize_records(result, effective_own)

    log.info(
        "Parsed %d records for %s (%s)",
        len(result.records),
        result.subscriber.msisdn or "unknown",
        result.operator,
    )

    return result


def process_billing_batch(
    billing_paths: List[Path],
    subscriber_paths: Optional[List[Path]] = None,
) -> List[BillingParseResult]:
    """Process multiple billing files (e.g. multiple months or multiple subscribers).

    Args:
        billing_paths: List of billing XLSX file paths.
        subscriber_paths: Optional list of subscriber ID file paths
            (matched by index to billing_paths, or used as shared pool).

    Returns:
        List of BillingParseResult, one per billing file.
    """
    results: List[BillingParseResult] = []

    for i, bp in enumerate(billing_paths):
        sub_path = None
        if subscriber_paths:
            if i < len(subscriber_paths):
                sub_path = subscriber_paths[i]
            elif len(subscriber_paths) == 1:
                sub_path = subscriber_paths[0]  # shared subscriber file

        try:
            result = process_billing(bp, subscriber_path=sub_path)
            results.append(result)
        except Exception as e:
            log.error("Error processing %s: %s", bp.name, e)
            results.append(BillingParseResult(
                warnings=[f"Błąd przetwarzania {bp.name}: {e}"]
            ))

    return results
