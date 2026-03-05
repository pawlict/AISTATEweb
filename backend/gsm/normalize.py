"""Normalization utilities for GSM billing data.

Handles phone number standardization, record deduplication, timezone
normalization, and data enrichment.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Set, Tuple

from .parsers.base import BillingRecord, BillingParseResult, SubscriberInfo
from .imei_db import normalize_imei


def normalize_records(
    result: BillingParseResult,
    own_numbers: Optional[Set[str]] = None,
) -> BillingParseResult:
    """Normalize all records in a parse result.

    Operations:
    1. Normalize all phone numbers (caller, callee)
    2. Fix record direction (IN/OUT) based on own_numbers
    3. Remove duplicate records
    4. Sort by datetime
    5. Enrich record_type if possible
    """
    if own_numbers is None:
        own_numbers = set()
        if result.subscriber.msisdn:
            own_numbers.add(result.subscriber.msisdn)

    # Normalize subscriber IMEI (14→15 digits)
    if result.subscriber.imei:
        result.subscriber.imei = normalize_imei(result.subscriber.imei)

    for record in result.records:
        # Normalize phones
        record.caller = _normalize_phone(record.caller)
        record.callee = _normalize_phone(record.callee)

        # Normalize IMEI (14→15 digits with Luhn check digit)
        if record.imei:
            record.imei = normalize_imei(record.imei)

        # Fix direction based on own numbers
        if own_numbers:
            _fix_direction(record, own_numbers)

        # Ensure record_type has direction suffix
        _enrich_record_type(record)

    # Deduplicate
    result.records = _deduplicate(result.records)

    # Sort by datetime
    result.records.sort(key=lambda r: r.datetime)

    return result


def _normalize_phone(number: str) -> str:
    """Normalize phone number."""
    if not number:
        return ""
    s = re.sub(r"[\s\-\(\)\.]+", "", number.strip())
    # Remove '00' international prefix
    if s.startswith("00") and len(s) > 10:
        s = "+" + s[2:]
    # Add +48 for 9-digit Polish numbers
    if re.match(r"^\d{9}$", s):
        s = "+48" + s
    if re.match(r"^48\d{9}$", s):
        s = "+" + s
    return s


def _fix_direction(record: BillingRecord, own_numbers: Set[str]) -> None:
    """Fix record direction based on own numbers.

    If caller is own number → outgoing.
    If callee is own number → incoming.
    """
    if record.record_type and ("_IN" in record.record_type or "_OUT" in record.record_type):
        return  # already has direction

    caller_is_own = record.caller in own_numbers
    callee_is_own = record.callee in own_numbers

    base_type = record.record_type.replace("_IN", "").replace("_OUT", "")

    if caller_is_own and not callee_is_own:
        if base_type in ("CALL", "CALL_OUT", "CALL_IN"):
            record.record_type = "CALL_OUT"
        elif base_type in ("SMS", "SMS_OUT", "SMS_IN"):
            record.record_type = "SMS_OUT"
        elif base_type in ("MMS", "MMS_OUT", "MMS_IN"):
            record.record_type = "MMS_OUT"
    elif callee_is_own and not caller_is_own:
        if base_type in ("CALL", "CALL_OUT", "CALL_IN"):
            record.record_type = "CALL_IN"
        elif base_type in ("SMS", "SMS_OUT", "SMS_IN"):
            record.record_type = "SMS_IN"
        elif base_type in ("MMS", "MMS_OUT", "MMS_IN"):
            record.record_type = "MMS_IN"


def _enrich_record_type(record: BillingRecord) -> None:
    """Add direction suffix if missing (based on cost heuristics)."""
    rt = record.record_type
    if not rt or rt == "OTHER":
        return

    # If type has no direction and we have cost info:
    # Outgoing calls usually have cost > 0
    if rt in ("CALL", "SMS", "MMS"):
        if record.cost is not None and record.cost > 0:
            record.record_type = rt + "_OUT"
        elif record.cost is not None and record.cost == 0:
            # Could be incoming or included in plan
            record.record_type = rt + "_OUT"  # default to outgoing


def _deduplicate(records: List[BillingRecord]) -> List[BillingRecord]:
    """Remove duplicate records based on key fields.

    Two records are duplicates if they have the same datetime, caller,
    callee, record_type, and duration.
    """
    seen: Set[Tuple] = set()
    unique: List[BillingRecord] = []

    for r in records:
        key = (r.datetime, r.caller, r.callee, r.record_type, r.duration_seconds)
        if key not in seen:
            seen.add(key)
            unique.append(r)

    return unique


def extract_contact_numbers(
    records: List[BillingRecord],
    own_numbers: Optional[Set[str]] = None,
) -> Dict[str, int]:
    """Extract all contact numbers with call/SMS counts (excluding own numbers).

    Returns dict of phone_number → total_interaction_count, sorted by count desc.
    """
    if own_numbers is None:
        own_numbers = set()

    counts: Dict[str, int] = {}
    for r in records:
        for num in (r.caller, r.callee):
            if num and num not in own_numbers:
                counts[num] = counts.get(num, 0) + 1

    return dict(sorted(counts.items(), key=lambda x: -x[1]))
