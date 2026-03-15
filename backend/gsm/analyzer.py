"""GSM billing analysis — pattern detection and anomaly finding.

Provides analytical functions for parsed billing data:
- Contact frequency analysis
- Temporal patterns (hourly/daily/weekly)
- Location analysis (BTS/cell)
- Duration statistics
- Anomaly detection (unusual patterns)
- Cross-billing correlation
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from .parsers.base import BillingRecord, BillingParseResult, BillingSummary
from .imei_db import lookup_imei, DeviceInfo


@dataclass
class ContactProfile:
    """Profile of a contact number."""

    number: str = ""
    total_interactions: int = 0
    calls_out: int = 0
    calls_in: int = 0
    calls_fwd: int = 0
    sms_out: int = 0
    sms_in: int = 0
    total_duration_seconds: int = 0
    first_contact: str = ""       # YYYY-MM-DD
    last_contact: str = ""        # YYYY-MM-DD
    active_days: int = 0          # unique days with interaction
    locations: List[str] = field(default_factory=list)  # BTS locations during contact

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class TemporalPattern:
    """Temporal activity pattern."""

    hourly_distribution: Dict[int, int] = field(default_factory=dict)   # hour → count
    daily_distribution: Dict[str, int] = field(default_factory=dict)    # day_name → count
    monthly_distribution: Dict[str, int] = field(default_factory=dict)  # YYYY-MM → count
    peak_hour: int = 0
    peak_day: str = ""
    night_activity_ratio: float = 0.0  # 23:00-05:00 ratio

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class LocationProfile:
    """BTS/cell location analysis."""

    location: str = ""
    lac: str = ""
    cell_id: str = ""
    record_count: int = 0
    first_seen: str = ""
    last_seen: str = ""
    hours_seen: List[int] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AnalysisResult:
    """Complete GSM billing analysis result."""

    # Top contacts
    top_contacts: List[ContactProfile] = field(default_factory=list)
    # Temporal patterns
    temporal: TemporalPattern = field(default_factory=TemporalPattern)
    # Location analysis
    locations: List[LocationProfile] = field(default_factory=list)
    # Anomalies
    anomalies: List[Dict[str, Any]] = field(default_factory=list)
    # Statistics
    avg_call_duration: float = 0.0
    median_call_duration: float = 0.0
    longest_call_seconds: int = 0
    longest_call_contact: str = ""
    busiest_date: str = ""
    busiest_date_count: int = 0
    # IMEI tracking
    imei_changes: List[Dict[str, str]] = field(default_factory=list)
    # Dual-IMEI detection (voice vs data use different stable IMEI)
    dual_imei: Optional[Dict[str, Any]] = None
    # Device identification (IMEI → brand/model)
    devices: List[Dict[str, Any]] = field(default_factory=list)
    # Special numbers (non-standard: voicemail, services, premium, short codes)
    special_numbers: List[Dict[str, Any]] = field(default_factory=list)
    # Night activity aggregates (22:00-6:00) for chart
    night_activity: Dict[str, Any] = field(default_factory=dict)
    # Weekend activity aggregates (Fri 20:00 - Mon 6:00) for chart
    weekend_activity: Dict[str, Any] = field(default_factory=dict)
    # Overnight stays away from home
    overnight_stays: List[Dict[str, Any]] = field(default_factory=list)
    overnight_stays_home: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "top_contacts": [c.to_dict() for c in self.top_contacts],
            "temporal": self.temporal.to_dict(),
            "locations": [l.to_dict() for l in self.locations],
            "anomalies": self.anomalies,
            "avg_call_duration": self.avg_call_duration,
            "median_call_duration": self.median_call_duration,
            "longest_call_seconds": self.longest_call_seconds,
            "longest_call_contact": self.longest_call_contact,
            "busiest_date": self.busiest_date,
            "busiest_date_count": self.busiest_date_count,
            "imei_changes": self.imei_changes,
            "dual_imei": self.dual_imei,
            "devices": self.devices,
            "special_numbers": self.special_numbers,
            "night_activity": self.night_activity,
            "weekend_activity": self.weekend_activity,
            "overnight_stays": self.overnight_stays,
            "overnight_stays_home": self.overnight_stays_home,
        }


def analyze_billing(
    result: BillingParseResult,
    own_numbers: Optional[Set[str]] = None,
    top_n: int = 20,
) -> AnalysisResult:
    """Run full analysis on parsed billing data.

    Args:
        result: Parsed billing result.
        own_numbers: Set of own phone numbers to exclude from contacts.
        top_n: Number of top contacts to include.

    Returns:
        AnalysisResult with all analyses.
    """
    if own_numbers is None:
        own_numbers = set()
        if result.subscriber.msisdn:
            own_numbers.add(result.subscriber.msisdn)

    records = result.records
    analysis = AnalysisResult()

    if not records:
        return analysis

    # 1. Contact analysis
    analysis.top_contacts = _analyze_contacts(records, own_numbers, top_n)

    # 2. Temporal patterns
    analysis.temporal = _analyze_temporal(records)

    # 3. Location analysis
    analysis.locations = _analyze_locations(records)

    # 3b. Overnight stays away from home
    analysis.overnight_stays, analysis.overnight_stays_home = (
        _analyze_overnight_stays(records, analysis.locations)
    )

    # 4. Call duration statistics
    _analyze_duration_stats(records, analysis)

    # 5. Busiest date
    _analyze_busiest_date(records, analysis)

    # 6. IMEI changes (per domain group: voice vs data)
    analysis.imei_changes = _detect_imei_changes(records)

    # 6b. Dual-IMEI detection (voice ≠ data IMEI = same device, different modems)
    analysis.dual_imei = _detect_dual_imei(records)

    # 7. Device identification (IMEI → brand/model)
    analysis.devices = _identify_devices(records, result.subscriber)

    # Enrich IMEI changes with device names
    for ch in analysis.imei_changes:
        for d in analysis.devices:
            if d["imei"] == ch.get("old_imei"):
                ch["old_device"] = d["display_name"]
            if d["imei"] == ch.get("new_imei"):
                ch["new_device"] = d["display_name"]

    # 8. Special numbers detection
    analysis.special_numbers = _detect_special_numbers(records, own_numbers)

    # 9. Night activity (22:00-6:00) and weekend activity (Fri 20:00 - Mon 6:00)
    analysis.night_activity = _compute_night_activity(records)
    analysis.weekend_activity = _compute_weekend_activity(records)

    # 10. Anomaly detection
    analysis.anomalies = _detect_anomalies(records, analysis, own_numbers, result.operator_id)

    return analysis


def _analyze_contacts(
    records: List[BillingRecord],
    own_numbers: Set[str],
    top_n: int,
) -> List[ContactProfile]:
    """Build contact profiles for all interacted numbers.

    Special numbers (short codes, operator IDs, service SMSes, APNs, etc.)
    are excluded from top contacts — they are shown separately in the
    "Numery specjalne" section.
    """
    profiles: Dict[str, ContactProfile] = {}

    for r in records:
        # Determine contact number (the one that's not own number)
        contact = None
        if r.callee and r.callee not in own_numbers:
            contact = r.callee
        elif r.caller and r.caller not in own_numbers:
            contact = r.caller

        if not contact:
            continue

        # Skip special numbers — they belong in the special numbers section
        if _classify_special_number(contact) is not None:
            continue

        if contact not in profiles:
            profiles[contact] = ContactProfile(number=contact)

        p = profiles[contact]
        p.total_interactions += 1

        # Check if this record has forwarding data (even if record_type is not CALL_FORWARDED)
        _has_fwd_extra = False
        for _ff in ("c_msisdn", "forwarded_msisdn", "nr_powiazany"):
            _fv = r.extra.get(_ff, "")
            if _fv and _fv not in own_numbers:
                _has_fwd_extra = True
                break

        if r.record_type == "CALL_FORWARDED" or _has_fwd_extra:
            p.calls_fwd += 1
        elif r.record_type == "CALL_OUT":
            p.calls_out += 1
        elif r.record_type == "CALL_IN":
            p.calls_in += 1
        elif r.record_type == "SMS_OUT":
            p.sms_out += 1
        elif r.record_type == "SMS_IN":
            p.sms_in += 1

        p.total_duration_seconds += r.duration_seconds

        if r.date:
            if not p.first_contact or r.date < p.first_contact:
                p.first_contact = r.date
            if not p.last_contact or r.date > p.last_contact:
                p.last_contact = r.date

        if r.location and r.location not in p.locations:
            p.locations.append(r.location)

    # Calculate active days
    for contact, p in profiles.items():
        days = set()
        for r in records:
            c = r.callee if r.callee not in own_numbers else r.caller
            if c == contact and r.date:
                days.add(r.date)
        p.active_days = len(days)

    # Sort by total interactions and return top N
    sorted_profiles = sorted(profiles.values(), key=lambda p: -p.total_interactions)
    return sorted_profiles[:top_n]


def _analyze_temporal(records: List[BillingRecord]) -> TemporalPattern:
    """Analyze temporal patterns in billing records."""
    pattern = TemporalPattern()
    hourly: Counter = Counter()
    daily: Counter = Counter()
    monthly: Counter = Counter()

    day_names = {
        0: "Poniedziałek",
        1: "Wtorek",
        2: "Środa",
        3: "Czwartek",
        4: "Piątek",
        5: "Sobota",
        6: "Niedziela",
    }

    for r in records:
        if not r.time:
            continue

        # Hour
        try:
            hour = int(r.time.split(":")[0])
            hourly[hour] += 1
        except (ValueError, IndexError):
            pass

        # Day of week
        if r.date:
            try:
                from datetime import date as date_cls
                parts = r.date.split("-")
                d = date_cls(int(parts[0]), int(parts[1]), int(parts[2]))
                day_name = day_names.get(d.weekday(), "")
                if day_name:
                    daily[day_name] += 1
            except (ValueError, IndexError):
                pass

        # Month
        if r.date and len(r.date) >= 7:
            monthly[r.date[:7]] += 1

    pattern.hourly_distribution = dict(sorted(hourly.items()))
    pattern.daily_distribution = dict(daily.most_common())
    pattern.monthly_distribution = dict(sorted(monthly.items()))

    if hourly:
        pattern.peak_hour = hourly.most_common(1)[0][0]
    if daily:
        pattern.peak_day = daily.most_common(1)[0][0]

    # Night activity (23:00 - 05:00)
    total = sum(hourly.values())
    if total > 0:
        night = sum(hourly.get(h, 0) for h in [23, 0, 1, 2, 3, 4])
        pattern.night_activity_ratio = round(night / total, 3)

    return pattern


def _analyze_locations(records: List[BillingRecord]) -> List[LocationProfile]:
    """Analyze BTS/cell location usage."""
    locs: Dict[str, LocationProfile] = {}

    for r in records:
        loc_key = r.location or r.location_cell_id or r.location_lac
        if not loc_key:
            continue

        if loc_key not in locs:
            locs[loc_key] = LocationProfile(
                location=r.location,
                lac=r.location_lac,
                cell_id=r.location_cell_id,
            )

        p = locs[loc_key]
        p.record_count += 1

        if r.date:
            if not p.first_seen or r.date < p.first_seen:
                p.first_seen = r.date
            if not p.last_seen or r.date > p.last_seen:
                p.last_seen = r.date

        if r.time:
            try:
                hour = int(r.time.split(":")[0])
                if hour not in p.hours_seen:
                    p.hours_seen.append(hour)
            except (ValueError, IndexError):
                pass

    sorted_locs = sorted(locs.values(), key=lambda p: -p.record_count)
    return sorted_locs[:50]


def _analyze_overnight_stays(
    records: List[BillingRecord],
    locations: List[LocationProfile],
) -> Tuple[List[Dict[str, Any]], str]:
    """Detect overnight stays away from home.

    Algorithm:
    1. Home = most frequent location (locations[0]).
    2. Group records by date, keeping only those with a location.
    3. For each pair of consecutive days: if the last record of day N
       and the first record of day N+1 are both NOT at the home
       location → overnight stay detected.
    4. Group consecutive overnight nights into "stays".

    Returns:
        (stays, home_location) where stays is a list of dicts.
    """
    if not locations or not records:
        return [], ""

    home = locations[0].location
    if not home:
        return [], ""

    # Group records by date (only those with a location)
    by_day: Dict[str, List[BillingRecord]] = defaultdict(list)
    for r in records:
        if r.date and r.location:
            by_day[r.date].append(r)

    if len(by_day) < 2:
        return [], home

    # Sort each day's records by datetime
    for day_recs in by_day.values():
        day_recs.sort(key=lambda r: r.datetime)

    sorted_days = sorted(by_day.keys())

    # Detect overnight nights
    nights: List[Dict[str, Any]] = []
    for i in range(len(sorted_days) - 1):
        day_cur = sorted_days[i]
        day_next = sorted_days[i + 1]

        last_rec = by_day[day_cur][-1]   # last activity of current day
        first_rec = by_day[day_next][0]  # first activity of next day

        last_loc = last_rec.location
        first_loc = first_rec.location

        if last_loc != home and first_loc != home:
            nights.append({
                "date": day_cur,
                "date_next": day_next,
                "location_evening": last_loc,
                "location_morning": first_loc,
                "last_time": last_rec.time or last_rec.datetime[-8:],
                "first_time": first_rec.time or first_rec.datetime[-8:],
            })

    if not nights:
        return [], home

    # Group consecutive nights into stays
    stays: List[Dict[str, Any]] = []
    current_stay: Dict[str, Any] | None = None

    for n in nights:
        if current_stay is None:
            current_stay = {
                "start_date": n["date"],
                "end_date": n["date_next"],
                "nights": 1,
                "locations": set(),
                "details": [n],
            }
            current_stay["locations"].add(n["location_evening"])
            current_stay["locations"].add(n["location_morning"])
        else:
            # Check if this night is consecutive (previous end == this start)
            if n["date"] == current_stay["end_date"]:
                current_stay["end_date"] = n["date_next"]
                current_stay["nights"] += 1
                current_stay["locations"].add(n["location_evening"])
                current_stay["locations"].add(n["location_morning"])
                current_stay["details"].append(n)
            else:
                # Finalize previous stay
                current_stay["locations"] = sorted(current_stay["locations"])
                stays.append(current_stay)
                # Start new stay
                current_stay = {
                    "start_date": n["date"],
                    "end_date": n["date_next"],
                    "nights": 1,
                    "locations": set(),
                    "details": [n],
                }
                current_stay["locations"].add(n["location_evening"])
                current_stay["locations"].add(n["location_morning"])

    if current_stay:
        current_stay["locations"] = sorted(current_stay["locations"])
        stays.append(current_stay)

    return stays, home


def _analyze_duration_stats(
    records: List[BillingRecord],
    analysis: AnalysisResult,
) -> None:
    """Compute call duration statistics."""
    call_durations = [
        r.duration_seconds for r in records
        if r.duration_seconds > 0 and "CALL" in r.record_type
    ]

    if not call_durations:
        return

    analysis.avg_call_duration = round(sum(call_durations) / len(call_durations), 1)

    sorted_d = sorted(call_durations)
    mid = len(sorted_d) // 2
    if len(sorted_d) % 2 == 0:
        analysis.median_call_duration = (sorted_d[mid - 1] + sorted_d[mid]) / 2
    else:
        analysis.median_call_duration = sorted_d[mid]

    # Longest call
    longest = max(records, key=lambda r: r.duration_seconds)
    analysis.longest_call_seconds = longest.duration_seconds
    analysis.longest_call_contact = longest.callee or longest.caller


def _analyze_busiest_date(
    records: List[BillingRecord],
    analysis: AnalysisResult,
) -> None:
    """Find the busiest day."""
    date_counts: Counter = Counter()
    for r in records:
        if r.date:
            date_counts[r.date] += 1

    if date_counts:
        busiest = date_counts.most_common(1)[0]
        analysis.busiest_date = busiest[0]
        analysis.busiest_date_count = busiest[1]


def _identify_devices(
    records: List[BillingRecord],
    subscriber: Any = None,
) -> List[Dict[str, Any]]:
    """Identify devices from unique IMEI numbers found in records and subscriber info."""
    seen_imeis: Dict[str, Dict[str, Any]] = {}

    # Collect unique IMEIs with usage stats
    for r in records:
        if not r.imei:
            continue
        imei = r.imei.strip()
        if imei not in seen_imeis:
            seen_imeis[imei] = {
                "imei": imei,
                "first_seen": r.date,
                "last_seen": r.date,
                "record_count": 0,
            }
        entry = seen_imeis[imei]
        entry["record_count"] += 1
        if r.date:
            if not entry["first_seen"] or r.date < entry["first_seen"]:
                entry["first_seen"] = r.date
            if not entry["last_seen"] or r.date > entry["last_seen"]:
                entry["last_seen"] = r.date

    # Also check subscriber IMEI (may not appear in individual records)
    if subscriber and hasattr(subscriber, "imei") and subscriber.imei:
        imei = subscriber.imei.strip()
        if imei and imei not in seen_imeis:
            seen_imeis[imei] = {
                "imei": imei,
                "first_seen": "",
                "last_seen": "",
                "record_count": 0,
            }

    # Look up each IMEI in the TAC database
    devices: List[Dict[str, Any]] = []
    for imei, stats in seen_imeis.items():
        info = lookup_imei(imei)
        device: Dict[str, Any] = {
            **stats,
            "brand": info.brand if info else "",
            "model": info.model if info else "",
            "type": info.device_type if info else "",
            "tac": info.tac if info else "",
            "display_name": info.display_name if info else "",
            "known": info is not None,
        }
        devices.append(device)

    # Sort: most-used first
    devices.sort(key=lambda d: -d["record_count"])
    return devices


def _classify_record_group(record_type: str) -> str:
    """Classify a record_type into a domain group for IMEI tracking.

    Voice/SMS and DATA use separate modem domains in many handsets,
    so IMEI may legitimately differ between them without indicating
    a real device change.
    """
    if record_type == "DATA":
        return "data"
    return "voice"  # CALL_OUT, CALL_IN, SMS_OUT, SMS_IN, etc.


def _detect_imei_changes(records: List[BillingRecord]) -> List[Dict[str, str]]:
    """Detect real IMEI changes over time (device changes).

    Changes are tracked **per domain group** (voice vs data) to avoid
    false positives when merging complementary billing files where voice
    and data sessions report different IMEI (dual-modem / eSIM devices).
    """
    changes: List[Dict[str, str]] = []
    last_imei_by_group: Dict[str, str] = {}  # group → last seen IMEI

    for r in sorted(records, key=lambda r: r.datetime):
        if not r.imei:
            continue
        group = _classify_record_group(r.record_type)
        last = last_imei_by_group.get(group, "")
        if r.imei != last:
            if last:
                changes.append({
                    "date": r.date,
                    "old_imei": last,
                    "new_imei": r.imei,
                    "group": group,
                })
            last_imei_by_group[group] = r.imei

    return changes


def _detect_dual_imei(records: List[BillingRecord]) -> Optional[Dict[str, Any]]:
    """Detect if the subscriber uses different stable IMEI for voice vs data.

    This is common in:
    - Dual-modem devices (separate CS/PS modems)
    - Devices with eSIM + physical SIM
    - Merged billing files (POL + TD) for the same subscriber

    Returns None if not a dual-IMEI situation, otherwise a dict with details.
    """
    voice_imeis: Dict[str, int] = {}
    data_imeis: Dict[str, int] = {}

    for r in records:
        if not r.imei:
            continue
        if r.record_type == "DATA":
            data_imeis[r.imei] = data_imeis.get(r.imei, 0) + 1
        else:
            voice_imeis[r.imei] = voice_imeis.get(r.imei, 0) + 1

    if not voice_imeis or not data_imeis:
        return None

    # Dominant IMEI per group
    voice_main = max(voice_imeis, key=voice_imeis.get)
    data_main = max(data_imeis, key=data_imeis.get)

    if voice_main == data_main:
        return None  # Same IMEI for both — no dual-modem

    # Check stability: dominant IMEI should cover ≥80% of records in its group
    voice_total = sum(voice_imeis.values())
    data_total = sum(data_imeis.values())
    voice_pct = voice_imeis[voice_main] / voice_total if voice_total else 0
    data_pct = data_imeis[data_main] / data_total if data_total else 0

    if voice_pct < 0.8 or data_pct < 0.8:
        return None  # Not stable enough — real device changes likely

    return {
        "voice_imei": voice_main,
        "voice_records": voice_imeis[voice_main],
        "voice_total": voice_total,
        "data_imei": data_main,
        "data_records": data_imeis[data_main],
        "data_total": data_total,
        "same_tac": voice_main[:8] == data_main[:8] if len(voice_main) >= 8 and len(data_main) >= 8 else False,
    }


# ---------------------------------------------------------------------------
# Special numbers — Polish operator service numbers, short codes, premium, etc.
# ---------------------------------------------------------------------------

# Known special number patterns for Polish operators
_SPECIAL_NUMBER_DB: Dict[str, Dict[str, str]] = {
    # --- Poczta głosowa (voicemail) ---
    "+48601000600": {"category": "voicemail", "label": "Poczta głosowa T-Mobile"},
    "+48600100600": {"category": "voicemail", "label": "Poczta głosowa T-Mobile"},
    "+48501200500": {"category": "voicemail", "label": "Poczta głosowa Orange"},
    "+48501200300": {"category": "voicemail", "label": "Poczta głosowa Orange"},
    "+48601000400": {"category": "voicemail", "label": "Poczta głosowa Plus"},
    "+48601000100": {"category": "voicemail", "label": "Poczta głosowa Plus"},
    "+48790200200": {"category": "voicemail", "label": "Poczta głosowa Play"},
    "+48790100100": {"category": "voicemail", "label": "Poczta głosowa Play"},
    # --- BOK / Biuro Obsługi Klienta ---
    "+48602900000": {"category": "service", "label": "BOK T-Mobile"},
    "+48510100100": {"category": "service", "label": "BOK Orange"},
    "+48501100100": {"category": "service", "label": "BOK Orange"},
    "+48510100200": {"category": "service", "label": "Orange — informacja"},
    "+48601102601": {"category": "service", "label": "BOK Plus"},
    "+48601100100": {"category": "service", "label": "BOK Plus"},
    "+48790500500": {"category": "service", "label": "BOK Play"},
    "+48790200500": {"category": "service", "label": "BOK Play"},
    # --- Sklep / usługi dodatkowe ---
    "+48602100100": {"category": "service", "label": "T-Mobile — usługi"},
    "+48601000200": {"category": "service", "label": "Plus — usługi"},
    "+48790300300": {"category": "service", "label": "Play — usługi"},
    "+48510100300": {"category": "service", "label": "Orange — usługi"},
    # --- Numery alarmowe ---
    "112": {"category": "emergency", "label": "Numer alarmowy 112"},
    "997": {"category": "emergency", "label": "Policja"},
    "998": {"category": "emergency", "label": "Straż pożarna"},
    "999": {"category": "emergency", "label": "Pogotowie ratunkowe"},
    "984": {"category": "emergency", "label": "Pogotowie wodociągowe"},
    "985": {"category": "emergency", "label": "Pogotowie rzeczne"},
    "986": {"category": "emergency", "label": "Straż Miejska"},
    "991": {"category": "emergency", "label": "Pogotowie energetyczne"},
    "992": {"category": "emergency", "label": "Pogotowie gazowe"},
    "993": {"category": "emergency", "label": "Pogotowie ciepłownicze"},
    "994": {"category": "emergency", "label": "Pogotowie wodociągowe"},
    "116000": {"category": "emergency", "label": "Telefon zaufania dla dzieci"},
    "116111": {"category": "emergency", "label": "Telefon zaufania dla młodzieży"},
    "116123": {"category": "emergency", "label": "Telefon zaufania"},
    # --- Informacja / usługi krótkie ---
    "118913": {"category": "info", "label": "Informacja o numerach"},
    "118912": {"category": "info", "label": "Informacja o numerach"},
    "19115": {"category": "info", "label": "Miejskie Centrum Kontaktu (Warszawa)"},
    "19116": {"category": "info", "label": "Informacja PKP"},
}

# Known alphanumeric sender IDs — Polish operators, stores, banks, services.
# These appear as text identifiers (not phone numbers) in billing records,
# typically as SMS senders. Matched case-insensitively.
_ALPHANUMERIC_SENDERS: Dict[str, Dict[str, str]] = {
    # --- Operatorzy / sieci telekomunikacyjne ---
    "orange": {"category": "operator_sms", "label": "Orange Polska"},
    "orange flex": {"category": "operator_sms", "label": "Orange Flex"},
    "orangeflex": {"category": "operator_sms", "label": "Orange Flex"},
    "orange pl": {"category": "operator_sms", "label": "Orange Polska"},
    "nju mobile": {"category": "operator_sms", "label": "nju mobile (Orange MVNO)"},
    "nju": {"category": "operator_sms", "label": "nju mobile"},
    "t-mobile": {"category": "operator_sms", "label": "T-Mobile Polska"},
    "tmobile": {"category": "operator_sms", "label": "T-Mobile Polska"},
    "t-mobile pl": {"category": "operator_sms", "label": "T-Mobile Polska"},
    "heyah": {"category": "operator_sms", "label": "Heyah (T-Mobile MVNO)"},
    "play": {"category": "operator_sms", "label": "Play"},
    "play pl": {"category": "operator_sms", "label": "Play"},
    "virgin": {"category": "operator_sms", "label": "Virgin Mobile (Play MVNO)"},
    "red bull mob": {"category": "operator_sms", "label": "Red Bull Mobile (Play MVNO)"},
    "plus": {"category": "operator_sms", "label": "Plus (Polkomtel)"},
    "plus gsm": {"category": "operator_sms", "label": "Plus GSM"},
    "plush": {"category": "operator_sms", "label": "Plush (Plus MVNO)"},
    "lycamobile": {"category": "operator_sms", "label": "Lycamobile"},
    "lajt mobile": {"category": "operator_sms", "label": "Lajt Mobile"},
    "vectra": {"category": "operator_sms", "label": "Vectra Mobile"},
    "premium mob": {"category": "operator_sms", "label": "Premium Mobile"},
    # --- Dyskonty i sieci handlowe ---
    "biedronka": {"category": "commercial_sms", "label": "Biedronka"},
    "lidl": {"category": "commercial_sms", "label": "Lidl"},
    "lidl plus": {"category": "commercial_sms", "label": "Lidl Plus"},
    "kaufland": {"category": "commercial_sms", "label": "Kaufland"},
    "aldi": {"category": "commercial_sms", "label": "Aldi"},
    "netto": {"category": "commercial_sms", "label": "Netto"},
    "zabka": {"category": "commercial_sms", "label": "Żabka"},
    "żabka": {"category": "commercial_sms", "label": "Żabka"},
    "zappka": {"category": "commercial_sms", "label": "Żabka (Żappka)"},
    "rossmann": {"category": "commercial_sms", "label": "Rossmann"},
    "hebe": {"category": "commercial_sms", "label": "Hebe"},
    "pepco": {"category": "commercial_sms", "label": "Pepco"},
    "action": {"category": "commercial_sms", "label": "Action"},
    "dino": {"category": "commercial_sms", "label": "Dino"},
    "stokrotka": {"category": "commercial_sms", "label": "Stokrotka"},
    "polomarket": {"category": "commercial_sms", "label": "Polomarket"},
    "intermarche": {"category": "commercial_sms", "label": "Intermarché"},
    "carrefour": {"category": "commercial_sms", "label": "Carrefour"},
    "auchan": {"category": "commercial_sms", "label": "Auchan"},
    "leroy": {"category": "commercial_sms", "label": "Leroy Merlin"},
    "leroymerlin": {"category": "commercial_sms", "label": "Leroy Merlin"},
    "castorama": {"category": "commercial_sms", "label": "Castorama"},
    "ikea": {"category": "commercial_sms", "label": "IKEA"},
    "obi": {"category": "commercial_sms", "label": "OBI"},
    "decathlon": {"category": "commercial_sms", "label": "Decathlon"},
    "mediamarkt": {"category": "commercial_sms", "label": "MediaMarkt"},
    "media expert": {"category": "commercial_sms", "label": "Media Expert"},
    "rtv euro": {"category": "commercial_sms", "label": "RTV Euro AGD"},
    "euro agd": {"category": "commercial_sms", "label": "RTV Euro AGD"},
    "empik": {"category": "commercial_sms", "label": "Empik"},
    "reserved": {"category": "commercial_sms", "label": "Reserved (LPP)"},
    "mohito": {"category": "commercial_sms", "label": "Mohito (LPP)"},
    "sinsay": {"category": "commercial_sms", "label": "Sinsay (LPP)"},
    "cropp": {"category": "commercial_sms", "label": "Cropp (LPP)"},
    "house": {"category": "commercial_sms", "label": "House (LPP)"},
    "ccc": {"category": "commercial_sms", "label": "CCC"},
    "halfprice": {"category": "commercial_sms", "label": "HalfPrice (CCC)"},
    "deichmann": {"category": "commercial_sms", "label": "Deichmann"},
    "smyk": {"category": "commercial_sms", "label": "Smyk"},
    "apart": {"category": "commercial_sms", "label": "Apart"},
    "douglas": {"category": "commercial_sms", "label": "Douglas"},
    "sephora": {"category": "commercial_sms", "label": "Sephora"},
    "zara": {"category": "commercial_sms", "label": "Zara"},
    "h&m": {"category": "commercial_sms", "label": "H&M"},
    "hm": {"category": "commercial_sms", "label": "H&M"},
    "primark": {"category": "commercial_sms", "label": "Primark"},
    "tk maxx": {"category": "commercial_sms", "label": "TK Maxx"},
    "jysk": {"category": "commercial_sms", "label": "Jysk"},
    "orlen": {"category": "commercial_sms", "label": "PKN Orlen"},
    "bp": {"category": "commercial_sms", "label": "BP"},
    "lotos": {"category": "commercial_sms", "label": "Lotos"},
    "circle k": {"category": "commercial_sms", "label": "Circle K"},
    # --- E-commerce / kurier ---
    "allegro": {"category": "commercial_sms", "label": "Allegro"},
    "olx": {"category": "commercial_sms", "label": "OLX"},
    "amazon": {"category": "commercial_sms", "label": "Amazon"},
    "aliexpress": {"category": "commercial_sms", "label": "AliExpress"},
    "temu": {"category": "commercial_sms", "label": "Temu"},
    "shein": {"category": "commercial_sms", "label": "Shein"},
    "zalando": {"category": "commercial_sms", "label": "Zalando"},
    "modivo": {"category": "commercial_sms", "label": "Modivo"},
    "modivoclub": {"category": "commercial_sms", "label": "Modivo Club"},
    "eobuwie": {"category": "commercial_sms", "label": "eobuwie.pl"},
    "inpost": {"category": "commercial_sms", "label": "InPost"},
    "dpd": {"category": "commercial_sms", "label": "DPD"},
    "dhl": {"category": "commercial_sms", "label": "DHL"},
    "gls": {"category": "commercial_sms", "label": "GLS"},
    "gls poland": {"category": "commercial_sms", "label": "GLS Poland"},
    "ups": {"category": "commercial_sms", "label": "UPS"},
    "fedex": {"category": "commercial_sms", "label": "FedEx"},
    "poczta pol": {"category": "commercial_sms", "label": "Poczta Polska"},
    "pocztapol": {"category": "commercial_sms", "label": "Poczta Polska"},
    # --- Banki ---
    "mbank": {"category": "commercial_sms", "label": "mBank"},
    "pkobp": {"category": "commercial_sms", "label": "PKO BP"},
    "pko bp": {"category": "commercial_sms", "label": "PKO BP"},
    "ing": {"category": "commercial_sms", "label": "ING Bank Śląski"},
    "ingbank": {"category": "commercial_sms", "label": "ING Bank Śląski"},
    "santander": {"category": "commercial_sms", "label": "Santander Bank"},
    "bnp paribas": {"category": "commercial_sms", "label": "BNP Paribas"},
    "millennium": {"category": "commercial_sms", "label": "Bank Millennium"},
    "pekao": {"category": "commercial_sms", "label": "Bank Pekao SA"},
    "alior": {"category": "commercial_sms", "label": "Alior Bank"},
    "credit agr": {"category": "commercial_sms", "label": "Credit Agricole"},
    "citi": {"category": "commercial_sms", "label": "Citi Handlowy"},
    "nest bank": {"category": "commercial_sms", "label": "Nest Bank"},
    "velo bank": {"category": "commercial_sms", "label": "VeloBank"},
    "velobank": {"category": "commercial_sms", "label": "VeloBank"},
    "blik": {"category": "commercial_sms", "label": "BLIK"},
    # --- Inne usługi ---
    "uber": {"category": "commercial_sms", "label": "Uber"},
    "bolt": {"category": "commercial_sms", "label": "Bolt"},
    "glovo": {"category": "commercial_sms", "label": "Glovo"},
    "wolt": {"category": "commercial_sms", "label": "Wolt"},
    "pyszne.pl": {"category": "commercial_sms", "label": "Pyszne.pl"},
    "netflix": {"category": "commercial_sms", "label": "Netflix"},
    "spotify": {"category": "commercial_sms", "label": "Spotify"},
    "disney+": {"category": "commercial_sms", "label": "Disney+"},
    "hbo max": {"category": "commercial_sms", "label": "HBO Max"},
    "canal+": {"category": "commercial_sms", "label": "Canal+"},
    "polsat box": {"category": "commercial_sms", "label": "Polsat Box"},
    "google": {"category": "commercial_sms", "label": "Google"},
    "microsoft": {"category": "commercial_sms", "label": "Microsoft"},
    "apple": {"category": "commercial_sms", "label": "Apple"},
    "facebook": {"category": "commercial_sms", "label": "Facebook (Meta)"},
    "meta": {"category": "commercial_sms", "label": "Meta"},
    "whatsapp": {"category": "commercial_sms", "label": "WhatsApp"},
    "instagram": {"category": "commercial_sms", "label": "Instagram"},
    "twitter": {"category": "commercial_sms", "label": "Twitter/X"},
    "linkedin": {"category": "commercial_sms", "label": "LinkedIn"},
    "tiktok": {"category": "commercial_sms", "label": "TikTok"},
    "signal": {"category": "commercial_sms", "label": "Signal"},
    "telegram": {"category": "commercial_sms", "label": "Telegram"},
    "ibcorp": {"category": "commercial_sms", "label": "IBcorp"},
    "zus": {"category": "commercial_sms", "label": "ZUS"},
    "epuap": {"category": "commercial_sms", "label": "ePUAP"},
    "gov.pl": {"category": "commercial_sms", "label": "Gov.pl"},
}

# Patterns for number classification
_SPECIAL_PATTERNS: List[Tuple[str, str, str]] = [
    # (regex_pattern, category, label_prefix)
    # USSD / control codes — contain * or #
    (r"^[*#]", "ussd", "Kod sterujący"),
    (r".*[*#]", "ussd", "Kod sterujący"),
    # Toll-free must be checked before premium (800/801 are toll-free, not premium)
    (r"^\+?48800\d{6}$", "toll_free", "Numer bezpłatny 800"),
    (r"^\+?48801\d{6}$", "toll_free", "Numer bezpłatny 801"),
    (r"^\+?48[78]0[01]\d{6}$", "premium", "Numer premium"),
    (r"^\+?48700\d{6}$", "premium", "Numer premium 700"),
    (r"^\+?48300\d{6}$", "premium", "Numer premium 300"),
    (r"^\d{3,6}$", "short_code", "Kod krótki"),
]

# ---------------------------------------------------------------------------
# International phone prefix → country mapping (ITU-T E.164)
# ---------------------------------------------------------------------------
# Sorted by prefix length descending for longest-prefix-match.
# Value: (ISO 3166-1 alpha-2, Polish country name)
# CRITICAL countries (RU, UA, BY, CN) trigger elevated anomaly severity.

_CRITICAL_COUNTRY_CODES = {"RU", "UA", "BY", "CN"}

_PHONE_PREFIX_TO_COUNTRY: List[Tuple[str, str, str]] = [
    # ── Longest prefixes first (4+ digits) ──
    ("+1242", "BS", "Bahamy"),
    ("+1246", "BB", "Barbados"),
    ("+1264", "AI", "Anguilla"),
    ("+1268", "AG", "Antigua i Barbuda"),
    ("+1284", "VG", "Brytyjskie Wyspy Dziewicze"),
    ("+1340", "VI", "Wyspy Dziewicze Stanów Zjednoczonych"),
    ("+1345", "KY", "Kajmany"),
    ("+1441", "BM", "Bermudy"),
    ("+1473", "GD", "Grenada"),
    ("+1649", "TC", "Turks i Caicos"),
    ("+1658", "JM", "Jamajka"),
    ("+1664", "MS", "Montserrat"),
    ("+1670", "MP", "Mariany Północne"),
    ("+1671", "GU", "Guam"),
    ("+1684", "AS", "Samoa Amerykańskie"),
    ("+1721", "SX", "Sint Maarten"),
    ("+1758", "LC", "Saint Lucia"),
    ("+1767", "DM", "Dominika"),
    ("+1784", "VC", "Saint Vincent i Grenadyny"),
    ("+1787", "PR", "Portoryko"),
    ("+1809", "DO", "Dominikana"),
    ("+1829", "DO", "Dominikana"),
    ("+1849", "DO", "Dominikana"),
    ("+1868", "TT", "Trynidad i Tobago"),
    ("+1869", "KN", "Saint Kitts i Nevis"),
    ("+1876", "JM", "Jamajka"),
    ("+1939", "PR", "Portoryko"),
    # ── 3-digit prefixes ──
    ("+993", "TM", "Turkmenistan"),
    ("+992", "TJ", "Tadżykistan"),
    ("+998", "UZ", "Uzbekistan"),
    ("+996", "KG", "Kirgistan"),
    ("+995", "GE", "Gruzja"),
    ("+994", "AZ", "Azerbejdżan"),
    ("+977", "NP", "Nepal"),
    ("+976", "MN", "Mongolia"),
    ("+975", "BT", "Bhutan"),
    ("+974", "QA", "Katar"),
    ("+973", "BH", "Bahrajn"),
    ("+972", "IL", "Izrael"),
    ("+971", "AE", "Zjednoczone Emiraty Arabskie"),
    ("+970", "PS", "Palestyna"),
    ("+968", "OM", "Oman"),
    ("+967", "YE", "Jemen"),
    ("+966", "SA", "Arabia Saudyjska"),
    ("+965", "KW", "Kuwejt"),
    ("+964", "IQ", "Irak"),
    ("+963", "SY", "Syria"),
    ("+962", "JO", "Jordania"),
    ("+961", "LB", "Liban"),
    ("+960", "MV", "Malediwy"),
    ("+886", "TW", "Tajwan"),
    ("+880", "BD", "Bangladesz"),
    ("+856", "LA", "Laos"),
    ("+855", "KH", "Kambodża"),
    ("+853", "MO", "Makau"),
    ("+852", "HK", "Hongkong"),
    ("+850", "KP", "Korea Północna"),
    ("+692", "MH", "Wyspy Marshalla"),
    ("+691", "FM", "Mikronezja"),
    ("+690", "TK", "Tokelau"),
    ("+689", "PF", "Polinezja Francuska"),
    ("+688", "TV", "Tuvalu"),
    ("+687", "NC", "Nowa Kaledonia"),
    ("+686", "KI", "Kiribati"),
    ("+685", "WS", "Samoa"),
    ("+683", "NU", "Niue"),
    ("+682", "CK", "Wyspy Cooka"),
    ("+681", "WF", "Wallis i Futuna"),
    ("+680", "PW", "Palau"),
    ("+679", "FJ", "Fidżi"),
    ("+678", "VU", "Vanuatu"),
    ("+677", "SB", "Wyspy Salomona"),
    ("+676", "TO", "Tonga"),
    ("+675", "PG", "Papua-Nowa Gwinea"),
    ("+674", "NR", "Nauru"),
    ("+673", "BN", "Brunei"),
    ("+672", "NF", "Norfolk"),
    ("+670", "TL", "Timor Wschodni"),
    ("+599", "CW", "Curaçao"),
    ("+598", "UY", "Urugwaj"),
    ("+597", "SR", "Surinam"),
    ("+596", "MQ", "Martynika"),
    ("+595", "PY", "Paragwaj"),
    ("+594", "GF", "Gujana Francuska"),
    ("+593", "EC", "Ekwador"),
    ("+592", "GY", "Gujana"),
    ("+591", "BO", "Boliwia"),
    ("+590", "GP", "Gwadelupa"),
    ("+509", "HT", "Haiti"),
    ("+508", "PM", "Saint-Pierre i Miquelon"),
    ("+507", "PA", "Panama"),
    ("+506", "CR", "Kostaryka"),
    ("+505", "NI", "Nikaragua"),
    ("+504", "HN", "Honduras"),
    ("+503", "SV", "Salwador"),
    ("+502", "GT", "Gwatemala"),
    ("+501", "BZ", "Belize"),
    ("+500", "FK", "Falklandy"),
    ("+423", "LI", "Liechtenstein"),
    ("+421", "SK", "Słowacja"),
    ("+420", "CZ", "Czechy"),
    ("+389", "MK", "Macedonia Północna"),
    ("+387", "BA", "Bośnia i Hercegowina"),
    ("+386", "SI", "Słowenia"),
    ("+385", "HR", "Chorwacja"),
    ("+383", "XK", "Kosowo"),
    ("+382", "ME", "Czarnogóra"),
    ("+381", "RS", "Serbia"),
    ("+380", "UA", "Ukraina"),
    ("+378", "SM", "San Marino"),
    ("+377", "MC", "Monako"),
    ("+376", "AD", "Andora"),
    ("+375", "BY", "Białoruś"),
    ("+374", "AM", "Armenia"),
    ("+373", "MD", "Mołdawia"),
    ("+372", "EE", "Estonia"),
    ("+371", "LV", "Łotwa"),
    ("+370", "LT", "Litwa"),
    ("+359", "BG", "Bułgaria"),
    ("+358", "FI", "Finlandia"),
    ("+357", "CY", "Cypr"),
    ("+356", "MT", "Malta"),
    ("+355", "AL", "Albania"),
    ("+354", "IS", "Islandia"),
    ("+353", "IE", "Irlandia"),
    ("+352", "LU", "Luksemburg"),
    ("+351", "PT", "Portugalia"),
    ("+350", "GI", "Gibraltar"),
    ("+299", "GL", "Grenlandia"),
    ("+298", "FO", "Wyspy Owcze"),
    ("+297", "AW", "Aruba"),
    ("+291", "ER", "Erytrea"),
    ("+269", "KM", "Komory"),
    ("+268", "SZ", "Eswatini"),
    ("+267", "BW", "Botswana"),
    ("+266", "LS", "Lesotho"),
    ("+265", "MW", "Malawi"),
    ("+264", "NA", "Namibia"),
    ("+263", "ZW", "Zimbabwe"),
    ("+262", "RE", "Reunion"),
    ("+261", "MG", "Madagaskar"),
    ("+260", "ZM", "Zambia"),
    ("+258", "MZ", "Mozambik"),
    ("+257", "BI", "Burundi"),
    ("+256", "UG", "Uganda"),
    ("+255", "TZ", "Tanzania"),
    ("+254", "KE", "Kenia"),
    ("+253", "DJ", "Dżibuti"),
    ("+252", "SO", "Somalia"),
    ("+251", "ET", "Etiopia"),
    ("+250", "RW", "Rwanda"),
    ("+249", "SD", "Sudan"),
    ("+248", "SC", "Seszele"),
    ("+247", "SH", "Wyspa Wniebowstąpienia"),
    ("+246", "IO", "Brytyjskie Terytorium Oceanu Indyjskiego"),
    ("+245", "GW", "Gwinea Bissau"),
    ("+244", "AO", "Angola"),
    ("+243", "CD", "Demokratyczna Republika Konga"),
    ("+242", "CG", "Kongo"),
    ("+241", "GA", "Gabon"),
    ("+240", "GQ", "Gwinea Równikowa"),
    ("+239", "ST", "Wyspy Świętego Tomasza i Książęca"),
    ("+238", "CV", "Republika Zielonego Przylądka"),
    ("+237", "CM", "Kamerun"),
    ("+236", "CF", "Republika Środkowoafrykańska"),
    ("+235", "TD", "Czad"),
    ("+234", "NG", "Nigeria"),
    ("+233", "GH", "Ghana"),
    ("+232", "SL", "Sierra Leone"),
    ("+231", "LR", "Liberia"),
    ("+230", "MU", "Mauritius"),
    ("+229", "BJ", "Benin"),
    ("+228", "TG", "Togo"),
    ("+227", "NE", "Niger"),
    ("+226", "BF", "Burkina Faso"),
    ("+225", "CI", "Wybrzeże Kości Słoniowej"),
    ("+224", "GN", "Gwinea"),
    ("+223", "ML", "Mali"),
    ("+222", "MR", "Mauretania"),
    ("+221", "SN", "Senegal"),
    ("+220", "GM", "Gambia"),
    ("+218", "LY", "Libia"),
    ("+216", "TN", "Tunezja"),
    ("+213", "DZ", "Algieria"),
    ("+212", "MA", "Maroko"),
    ("+211", "SS", "Sudan Południowy"),
    # ── 2-digit prefixes ──
    ("+98", "IR", "Iran"),
    ("+95", "MM", "Mjanma"),
    ("+94", "LK", "Sri Lanka"),
    ("+93", "AF", "Afganistan"),
    ("+92", "PK", "Pakistan"),
    ("+91", "IN", "Indie"),
    ("+90", "TR", "Turcja"),
    ("+86", "CN", "Chiny"),
    ("+84", "VN", "Wietnam"),
    ("+82", "KR", "Korea Południowa"),
    ("+81", "JP", "Japonia"),
    ("+66", "TH", "Tajlandia"),
    ("+65", "SG", "Singapur"),
    ("+64", "NZ", "Nowa Zelandia"),
    ("+63", "PH", "Filipiny"),
    ("+62", "ID", "Indonezja"),
    ("+61", "AU", "Australia"),
    ("+60", "MY", "Malezja"),
    ("+58", "VE", "Wenezuela"),
    ("+57", "CO", "Kolumbia"),
    ("+56", "CL", "Chile"),
    ("+55", "BR", "Brazylia"),
    ("+54", "AR", "Argentyna"),
    ("+53", "CU", "Kuba"),
    ("+52", "MX", "Meksyk"),
    ("+51", "PE", "Peru"),
    ("+49", "DE", "Niemcy"),
    # +48 = Polska — pomijamy (krajowe)
    ("+47", "NO", "Norwegia"),
    ("+46", "SE", "Szwecja"),
    ("+45", "DK", "Dania"),
    ("+44", "GB", "Wielka Brytania"),
    ("+43", "AT", "Austria"),
    ("+41", "CH", "Szwajcaria"),
    ("+40", "RO", "Rumunia"),
    ("+39", "IT", "Włochy"),
    ("+36", "HU", "Węgry"),
    ("+34", "ES", "Hiszpania"),
    ("+33", "FR", "Francja"),
    ("+32", "BE", "Belgia"),
    ("+31", "NL", "Holandia"),
    ("+30", "GR", "Grecja"),
    ("+27", "ZA", "Republika Południowej Afryki"),
    ("+20", "EG", "Egipt"),
    # ── 1-digit prefix ──
    ("+1", "US", "USA / Kanada"),
    # ── Special: +7 covers Russia AND Kazakhstan (+77) ──
    ("+77", "KZ", "Kazachstan"),
    ("+7", "RU", "Rosja"),
]

# Pre-sorted by prefix length (longest first) for matching
_PHONE_PREFIX_TO_COUNTRY.sort(key=lambda x: -len(x[0]))


def _identify_country_by_prefix(number: str) -> Optional[Tuple[str, str]]:
    """Identify country by phone number prefix (longest prefix match).

    Args:
        number: Phone number starting with '+' (e.g. '+79031234567').

    Returns:
        (iso_code, country_name_pl) or None if not matched.
    """
    if not number or not number.startswith("+"):
        return None
    for prefix, iso, name in _PHONE_PREFIX_TO_COUNTRY:
        if number.startswith(prefix):
            return (iso, name)
    return None


def _is_standard_phone(number: str) -> bool:
    """Check if number is a standard domestic or international phone number.

    Standard Polish numbers: +48 + 9 digits (or bare 9 digits).
    International numbers: + followed by country code + number (>8 digits total).
    Bare international: 7-15 digits without + (e.g. from billing records).
    """
    if not number:
        return False
    # If it contains any letters → definitely not a standard phone number
    if re.search(r"[a-zA-Z]", number):
        return False
    digits = re.sub(r"[^\d+]", "", number)
    # Standard Polish: +48NNNNNNNNN or 48NNNNNNNNN or NNNNNNNNN
    if re.match(r"^\+?48\d{9}$", digits):
        return True
    # Bare 9-digit Polish number
    if re.match(r"^\d{9}$", digits):
        return True
    # International: + then 7-15 digits
    if re.match(r"^\+\d{7,15}$", digits):
        return True
    # International without +: 00 + country code + number
    if re.match(r"^00\d{8,15}$", digits):
        return True
    # Bare international number: 10-15 digits (e.g. 375295434940 = Belarus)
    # These often appear in billing records without + prefix
    if re.match(r"^\d{10,15}$", digits):
        return True
    return False


def _classify_special_number(number: str) -> Optional[Dict[str, str]]:
    """Check if a number is 'special' (non-standard phone number).

    GLOBAL RULE: any identifier that is NOT a standard domestic or international
    phone number is classified as special. This includes:
    - Known operator/service/store/bank alphanumeric sender IDs
    - USSD codes (containing * or #)
    - Short codes (≤6 digits)
    - Premium / toll-free numbers (700/800/801/300 prefixes)
    - Internet APN names (e.g. "internetipv6")
    - Any other text-based identifier

    Returns dict with category/label or None if it's a regular phone number.
    """
    if not number:
        return None

    # Exact match in known DB
    if number in _SPECIAL_NUMBER_DB:
        return dict(_SPECIAL_NUMBER_DB[number])

    # Also check without +48 prefix
    bare = number
    if bare.startswith("+48"):
        bare = bare[3:]
    for db_num, info in _SPECIAL_NUMBER_DB.items():
        db_bare = db_num[3:] if db_num.startswith("+48") else db_num
        if bare == db_bare:
            return dict(info)

    # Check known alphanumeric senders (case-insensitive)
    num_lower = number.lower().strip()
    if num_lower in _ALPHANUMERIC_SENDERS:
        return dict(_ALPHANUMERIC_SENDERS[num_lower])
    # Partial match: check if a known sender name (≥4 chars) is contained
    # in the number as a word boundary, or if the number matches a sender.
    # Short names (≤3 chars like "ing", "bp") require exact match only
    # to avoid false positives (e.g. "ing" matching "roaming").
    for sender, info in _ALPHANUMERIC_SENDERS.items():
        if len(sender) >= 4 and sender in num_lower:
            return dict(info)
        if num_lower in sender and len(num_lower) >= 4:
            return dict(info)

    # Pattern-based
    for pat, cat, label in _SPECIAL_PATTERNS:
        if re.match(pat, number):
            return {"category": cat, "label": f"{label} ({number})"}

    # Foreign numbers are now handled by anomaly "foreign_contacts"
    # — not classified as special numbers anymore.

    # GLOBAL CATCH-ALL: if not a standard phone number → special
    if not _is_standard_phone(number):
        # Determine sub-category for non-phone identifiers
        has_alpha = bool(re.search(r"[a-zA-Z]", number))
        if has_alpha:
            # Text-based identifier (operator name, store, service, APN, etc.)
            return {"category": "alphanumeric", "label": f"ID alfanumeryczny ({number})"}
        else:
            # Numeric but non-standard (7-8 digits, or other non-phone format)
            return {"category": "short_code", "label": f"Kod krótki ({number})"}

    return None


def _detect_special_numbers(
    records: List[BillingRecord],
    own_numbers: Set[str],
) -> List[Dict[str, Any]]:
    """Detect all interactions with special (non-standard) numbers."""
    seen: Dict[str, Dict[str, Any]] = {}

    for r in records:
        # Determine the "other party" — check both callee and caller
        contact = None
        if r.callee and r.callee not in own_numbers:
            contact = r.callee
        elif r.caller and r.caller not in own_numbers:
            contact = r.caller
        if not contact:
            continue

        if contact in seen:
            seen[contact]["interactions"] += 1
            seen[contact]["total_duration_seconds"] += r.duration_seconds
            if r.date:
                if r.date < seen[contact]["first_date"]:
                    seen[contact]["first_date"] = r.date
                if r.date > seen[contact]["last_date"]:
                    seen[contact]["last_date"] = r.date
            continue

        info = _classify_special_number(contact)
        if info is None:
            continue

        seen[contact] = {
            "number": contact,
            "category": info["category"],
            "label": info["label"],
            "interactions": 1,
            "total_duration_seconds": r.duration_seconds,
            "first_date": r.date or "",
            "last_date": r.date or "",
        }

    result = sorted(seen.values(), key=lambda x: -x["interactions"])
    return result


# ---------------------------------------------------------------------------
# Night / Weekend activity for charts
# ---------------------------------------------------------------------------

def _compute_night_activity(records: List[BillingRecord]) -> Dict[str, Any]:
    """Compute night activity stats (22:00-6:00).

    Returns aggregate totals plus weekly and monthly breakdowns for drill-down.
    """
    from datetime import date as date_cls, timedelta

    night_hours = {22, 23, 0, 1, 2, 3, 4, 5}
    total = 0
    night_total = 0
    calls = 0
    sms = 0
    data = 0
    other = 0
    duration_sec = 0
    hourly: Dict[int, int] = {h: 0 for h in [22, 23, 0, 1, 2, 3, 4, 5]}
    # Per-hour per-type for grouped bar chart
    hourly_calls: Dict[int, int] = {h: 0 for h in [22, 23, 0, 1, 2, 3, 4, 5]}
    hourly_sms: Dict[int, int] = {h: 0 for h in [22, 23, 0, 1, 2, 3, 4, 5]}
    hourly_data: Dict[int, int] = {h: 0 for h in [22, 23, 0, 1, 2, 3, 4, 5]}
    # Weekly/monthly collectors
    weekly: Dict[str, Dict[str, Any]] = {}   # "2024-W03" → {records, calls, sms, ...}
    monthly: Dict[str, Dict[str, Any]] = {}  # "2024-01" → {records, calls, sms, ...}

    def _empty_bucket() -> Dict[str, Any]:
        return {
            "records": 0, "calls": 0, "sms": 0, "data": 0, "other": 0, "duration_sec": 0,
            "hourly_calls": {h: 0 for h in [22, 23, 0, 1, 2, 3, 4, 5]},
            "hourly_sms": {h: 0 for h in [22, 23, 0, 1, 2, 3, 4, 5]},
            "hourly_data": {h: 0 for h in [22, 23, 0, 1, 2, 3, 4, 5]},
        }

    for r in records:
        total += 1
        if not r.time:
            continue
        try:
            hour = int(r.time.split(":")[0])
        except (ValueError, IndexError):
            continue

        if hour not in night_hours:
            continue

        night_total += 1
        hourly[hour] += 1
        duration_sec += r.duration_seconds

        rt = r.record_type
        cat = "other"
        if "CALL" in rt:
            calls += 1
            cat = "calls"
            hourly_calls[hour] += 1
        elif "SMS" in rt or "MMS" in rt:
            sms += 1
            cat = "sms"
            hourly_sms[hour] += 1
        elif rt == "DATA":
            data += 1
            cat = "data"
            hourly_data[hour] += 1
        else:
            other += 1

        # Bucket by week and month
        if r.date:
            try:
                parts = r.date.split("-")
                d = date_cls(int(parts[0]), int(parts[1]), int(parts[2]))
                iso = d.isocalendar()
                week_key = f"{iso[0]}-W{iso[1]:02d}"
                month_key = r.date[:7]

                if week_key not in weekly:
                    weekly[week_key] = _empty_bucket()
                weekly[week_key]["records"] += 1
                weekly[week_key][cat] += 1
                weekly[week_key]["duration_sec"] += r.duration_seconds
                if cat in ("calls", "sms", "data"):
                    weekly[week_key][f"hourly_{cat}"][hour] += 1

                if month_key not in monthly:
                    monthly[month_key] = _empty_bucket()
                monthly[month_key]["records"] += 1
                monthly[month_key][cat] += 1
                monthly[month_key]["duration_sec"] += r.duration_seconds
                if cat in ("calls", "sms", "data"):
                    monthly[month_key][f"hourly_{cat}"][hour] += 1
            except (ValueError, IndexError):
                pass

    # Convert hourly dict keys to strings for JSON serialization
    def _stringify_hourly(bucket: Dict[str, Any]) -> Dict[str, Any]:
        for key in ("hourly_calls", "hourly_sms", "hourly_data"):
            if key in bucket:
                bucket[key] = {str(h): v for h, v in bucket[key].items()}
        return bucket

    # Sort weekly/monthly by key
    weekly_sorted = {k: _stringify_hourly(v) for k, v in sorted(weekly.items())}
    monthly_sorted = {k: _stringify_hourly(v) for k, v in sorted(monthly.items())}

    # Compute anomalies — weeks/months deviating significantly from average
    anomalies = _detect_period_anomalies(weekly_sorted, monthly_sorted, "nocna")

    return {
        "total_records": night_total,
        "all_records": total,
        "percentage": round(night_total / total * 100, 1) if total > 0 else 0,
        "calls": calls,
        "sms": sms,
        "data": data,
        "other": other,
        "total_duration_seconds": duration_sec,
        "hourly": hourly,
        "hourly_calls": hourly_calls,
        "hourly_sms": hourly_sms,
        "hourly_data": hourly_data,
        "weekly": weekly_sorted,
        "monthly": monthly_sorted,
        "anomalies": anomalies,
    }


def _compute_weekend_activity(records: List[BillingRecord]) -> Dict[str, Any]:
    """Compute weekend activity stats (Friday 20:00 - Monday 6:00).

    Returns aggregate totals plus weekly and monthly breakdowns for drill-down.
    """
    from datetime import date as date_cls

    total = 0
    weekend_total = 0
    calls = 0
    sms = 0
    data = 0
    other = 0
    duration_sec = 0
    segments: Dict[str, int] = {
        "fri_evening": 0,
        "saturday": 0,
        "sunday": 0,
        "mon_morning": 0,
    }
    # Per-segment per-type for grouped bar chart
    seg_keys = ["fri_evening", "saturday", "sunday", "mon_morning"]
    seg_calls: Dict[str, int] = {s: 0 for s in seg_keys}
    seg_sms: Dict[str, int] = {s: 0 for s in seg_keys}
    seg_data: Dict[str, int] = {s: 0 for s in seg_keys}
    weekly: Dict[str, Dict[str, Any]] = {}
    monthly: Dict[str, Dict[str, Any]] = {}

    def _empty_bucket() -> Dict[str, Any]:
        return {"records": 0, "calls": 0, "sms": 0, "data": 0, "other": 0, "duration_sec": 0,
                "fri_evening": 0, "saturday": 0, "sunday": 0, "mon_morning": 0,
                "seg_calls": {s: 0 for s in seg_keys},
                "seg_sms": {s: 0 for s in seg_keys},
                "seg_data": {s: 0 for s in seg_keys}}

    for r in records:
        total += 1
        if not r.date or not r.time:
            continue

        try:
            parts = r.date.split("-")
            d = date_cls(int(parts[0]), int(parts[1]), int(parts[2]))
            weekday = d.weekday()
            hour = int(r.time.split(":")[0])
        except (ValueError, IndexError):
            continue

        is_weekend = False
        segment = ""

        if weekday == 4 and hour >= 20:
            is_weekend = True
            segment = "fri_evening"
        elif weekday == 5:
            is_weekend = True
            segment = "saturday"
        elif weekday == 6:
            is_weekend = True
            segment = "sunday"
        elif weekday == 0 and hour < 6:
            is_weekend = True
            segment = "mon_morning"

        if not is_weekend:
            continue

        weekend_total += 1
        segments[segment] += 1
        duration_sec += r.duration_seconds

        rt = r.record_type
        cat = "other"
        if "CALL" in rt:
            calls += 1
            cat = "calls"
            seg_calls[segment] += 1
        elif "SMS" in rt or "MMS" in rt:
            sms += 1
            cat = "sms"
            seg_sms[segment] += 1
        elif rt == "DATA":
            data += 1
            cat = "data"
            seg_data[segment] += 1
        else:
            other += 1

        # Bucket by week and month
        try:
            iso = d.isocalendar()
            week_key = f"{iso[0]}-W{iso[1]:02d}"
            month_key = r.date[:7]

            if week_key not in weekly:
                weekly[week_key] = _empty_bucket()
            weekly[week_key]["records"] += 1
            weekly[week_key][cat] += 1
            weekly[week_key][segment] += 1
            weekly[week_key]["duration_sec"] += r.duration_seconds
            if cat in ("calls", "sms", "data"):
                weekly[week_key][f"seg_{cat}"][segment] += 1

            if month_key not in monthly:
                monthly[month_key] = _empty_bucket()
            monthly[month_key]["records"] += 1
            monthly[month_key][cat] += 1
            monthly[month_key][segment] += 1
            monthly[month_key]["duration_sec"] += r.duration_seconds
            if cat in ("calls", "sms", "data"):
                monthly[month_key][f"seg_{cat}"][segment] += 1
        except (ValueError, IndexError):
            pass

    weekly_sorted = dict(sorted(weekly.items()))
    monthly_sorted = dict(sorted(monthly.items()))

    anomalies = _detect_period_anomalies(weekly_sorted, monthly_sorted, "weekendowa")

    return {
        "total_records": weekend_total,
        "all_records": total,
        "percentage": round(weekend_total / total * 100, 1) if total > 0 else 0,
        "calls": calls,
        "sms": sms,
        "data": data,
        "other": other,
        "total_duration_seconds": duration_sec,
        "segments": segments,
        "seg_calls": seg_calls,
        "seg_sms": seg_sms,
        "seg_data": seg_data,
        "weekly": weekly_sorted,
        "monthly": monthly_sorted,
        "anomalies": anomalies,
    }


def _format_duration_short(sec: int) -> str:
    """Format seconds as short Polish duration string."""
    if sec <= 0:
        return "0s"
    h = sec // 3600
    m = (sec % 3600) // 60
    s = sec % 60
    if h > 0:
        return f"{h}h {m}m"
    if m > 0:
        return f"{m}m {s}s"
    return f"{s}s"


def _detect_period_anomalies(
    weekly: Dict[str, Dict[str, Any]],
    monthly: Dict[str, Dict[str, Any]],
    activity_name: str,
) -> List[Dict[str, Any]]:
    """Detect anomalies and build per-period + overall summary descriptions."""
    anomalies: List[Dict[str, Any]] = []

    # --- Per-week descriptions with anomaly flagging ---
    if len(weekly) >= 2:
        counts = [b["records"] for b in weekly.values()]
        avg = sum(counts) / len(counts)
        std_dev = (sum((c - avg) ** 2 for c in counts) / len(counts)) ** 0.5
        threshold_hi = avg + max(std_dev * 1.5, 1)
        threshold_lo = max(avg - max(std_dev * 1.5, 1), 0)

        for key, bucket in weekly.items():
            rec = bucket["records"]
            dur = _format_duration_short(bucket.get("duration_sec", 0))
            detail = (
                f"rozmowy: {bucket.get('calls', 0)}, "
                f"SMS/MMS: {bucket.get('sms', 0)}, "
                f"dane: {bucket.get('data', 0)}, "
                f"czas: {dur}"
            )

            if rec > threshold_hi and avg > 0:
                ratio = rec / avg
                anomalies.append({
                    "period_type": "week",
                    "period_key": key,
                    "records": rec,
                    "average": round(avg, 1),
                    "ratio": round(ratio, 1),
                    "description": (
                        f"Tydzień {key}: {rec} rekordów "
                        f"({ratio:.1f}x powyżej średniej {avg:.0f}/tydz.) — "
                        f"{detail}"
                    ),
                })
            elif rec < threshold_lo and avg > 2:
                ratio = rec / avg if avg > 0 else 0
                anomalies.append({
                    "period_type": "week",
                    "period_key": key,
                    "records": rec,
                    "average": round(avg, 1),
                    "ratio": round(ratio, 1),
                    "description": (
                        f"Tydzień {key}: tylko {rec} rekordów "
                        f"(poniżej średniej {avg:.0f}/tydz.) — "
                        f"{detail}"
                    ),
                })

    # --- Per-month descriptions with anomaly flagging ---
    if len(monthly) >= 2:
        counts = [b["records"] for b in monthly.values()]
        avg = sum(counts) / len(counts)
        std_dev = (sum((c - avg) ** 2 for c in counts) / len(counts)) ** 0.5
        threshold_hi = avg + max(std_dev * 1.5, 1)

        for key, bucket in monthly.items():
            rec = bucket["records"]
            dur = _format_duration_short(bucket.get("duration_sec", 0))
            detail = (
                f"rozmowy: {bucket.get('calls', 0)}, "
                f"SMS/MMS: {bucket.get('sms', 0)}, "
                f"dane: {bucket.get('data', 0)}, "
                f"czas: {dur}"
            )

            if rec > threshold_hi and avg > 0:
                ratio = rec / avg
                anomalies.append({
                    "period_type": "month",
                    "period_key": key,
                    "records": rec,
                    "average": round(avg, 1),
                    "ratio": round(ratio, 1),
                    "description": (
                        f"Miesiąc {key}: {rec} rekordów "
                        f"({ratio:.1f}x powyżej średniej {avg:.0f}/mies.) — "
                        f"{detail}"
                    ),
                })

    # --- Overall summary (always present if data exists) ---
    total_weeks = len(weekly)
    total_months = len(monthly)
    if total_weeks > 0:
        total_rec = sum(b["records"] for b in weekly.values())
        total_calls = sum(b.get("calls", 0) for b in weekly.values())
        total_sms = sum(b.get("sms", 0) for b in weekly.values())
        total_data = sum(b.get("data", 0) for b in weekly.values())
        total_dur = sum(b.get("duration_sec", 0) for b in weekly.values())

        avg_week = total_rec / total_weeks if total_weeks else 0
        avg_month = total_rec / total_months if total_months else 0

        max_week = max(weekly.items(), key=lambda x: x[1]["records"])
        min_week = min(weekly.items(), key=lambda x: x[1]["records"])

        summary_lines = [
            f"Łącznie {total_rec} rekordów aktywności {activity_name} "
            f"w {total_weeks} tygodniach ({total_months} miesięcy).",
            f"Rozkład: rozmowy {total_calls}, SMS/MMS {total_sms}, "
            f"dane {total_data}, łączny czas {_format_duration_short(total_dur)}.",
            f"Średnio {avg_week:.1f} rek./tydzień, {avg_month:.1f} rek./miesiąc.",
        ]
        if total_weeks >= 2:
            summary_lines.append(
                f"Najaktywniejszy tydzień: {max_week[0]} ({max_week[1]['records']} rek.), "
                f"najcichszy: {min_week[0]} ({min_week[1]['records']} rek.)."
            )

        anomalies.append({
            "period_type": "summary",
            "description": " ".join(summary_lines),
        })

    return anomalies


def _detect_anomalies(
    records: List[BillingRecord],
    analysis: AnalysisResult,
    own_numbers: Set[str],
    operator_id: str = "",
) -> List[Dict[str, Any]]:
    """Detect anomalies and unusual patterns.

    Returns a list of anomaly groups. Each group has:
      - type: category key
      - label: human-readable Polish category name
      - description: short explanation of what this category checks
      - severity: info | warning | critical
      - items: list of individual findings (empty list = "brak")
    """
    groups: List[Dict[str, Any]] = []

    if not records:
        return groups

    # ── 1. Long calls (> 1 hour) ──
    long_calls = []
    for r in records:
        if r.duration_seconds > 3600 and "CALL" in r.record_type:
            long_calls.append({
                "contact": r.callee or r.caller or "nieznany",
                "duration_min": r.duration_seconds // 60,
                "date": r.date,
                "time": r.time,
            })
    groups.append({
        "type": "long_call",
        "label": "Długie połączenia",
        "description": "Połączenia trwające ponad 1 godzinę",
        "severity": "info" if long_calls else "ok",
        "items": long_calls,
    })

    # ── 2. Late-night voice calls (00:00–05:00) ──
    late_calls = []
    for r in records:
        if "CALL" not in r.record_type or r.duration_seconds < 10:
            continue
        try:
            hour = int(r.time.split(":")[0])
        except (ValueError, IndexError):
            continue
        if 0 <= hour < 5:
            late_calls.append({
                "contact": r.callee or r.caller or "nieznany",
                "date": r.date,
                "time": r.time,
                "duration_min": max(1, r.duration_seconds // 60),
                "direction": "wychodzące" if "OUT" in r.record_type else "przychodzące",
            })
    groups.append({
        "type": "late_night_calls",
        "label": "Połączenia głosowe w nocy",
        "description": "Rozmowy telefoniczne między 00:00 a 05:00 (dłuższe niż 10 sek.)",
        "severity": "warning" if late_calls else "ok",
        "items": late_calls,
    })

    # ── 3. High night activity ratio ──
    night_items = []
    ratio = analysis.temporal.night_activity_ratio
    if ratio > 0.3:
        night_items.append({
            "ratio_pct": round(ratio * 100),
        })
    groups.append({
        "type": "night_activity",
        "label": "Wysoka aktywność nocna",
        "description": (
            "Ponad 30% wszystkich zdarzeń (połączenia, SMS, dane) "
            "przypada na godziny 23:00–05:00"
        ),
        "severity": "warning" if night_items else "ok",
        "items": night_items,
    })

    # ── 4. Night movement — BTS change during 23:00–05:00 ──
    night_move_items = _detect_night_movement(records)
    groups.append({
        "type": "night_movement",
        "label": "Przemieszczanie nocne",
        "description": (
            "Zmiana stacji BTS między kolejnymi zdarzeniami nocnymi "
            "(23:00–05:00) — wskazuje na ruch urządzenia w nocy"
        ),
        "severity": "warning" if night_move_items else "ok",
        "items": night_move_items,
    })

    # ── 5. Burst activity — many records in short time ──
    burst_items: List[Dict[str, Any]] = []
    _detect_burst_activity(records, burst_items)
    groups.append({
        "type": "burst_activity",
        "label": "Nagły wzrost aktywności",
        "description": (
            "Co najmniej 20 rekordów (połączenia/SMS) w ciągu 30 minut — "
            "może wskazywać na masowe wysyłanie SMS, automatyczne systemy "
            "lub intensywną komunikację"
        ),
        "severity": "warning" if burst_items else "ok",
        "items": burst_items,
    })

    # ── 6. Premium numbers ──
    premium_seen: Dict[str, List[str]] = {}
    for r in records:
        contact = r.callee or r.caller
        if not contact:
            continue
        if re.match(r"^\+?48[78]0\d", contact):
            premium_seen.setdefault(contact, []).append(r.date)
    premium_items = [
        {"contact": num, "count": len(dates), "dates": sorted(set(dates))}
        for num, dates in premium_seen.items()
    ]
    groups.append({
        "type": "premium_number",
        "label": "Numery premium / płatne",
        "description": (
            "Kontakty z numerami o podwyższonej opłacie (70x, 80x) — "
            "mogą generować wysokie koszty"
        ),
        "severity": "info" if premium_items else "ok",
        "items": premium_items,
    })

    # ── 7. Roaming / foreign networks ──
    roaming_items = _detect_roaming_activity(records)
    groups.append({
        "type": "roaming",
        "label": "Aktywność w sieciach zagranicznych",
        "description": (
            "Rekordy z flagą roamingu lub z siecią zagraniczną. "
            'Szczegóły wyjazdów \u2014 patrz sekcja "Przekroczenia granic"'
        ),
        "severity": "info" if roaming_items else "ok",
        "items": roaming_items,
    })

    # ── 7b. Foreign contacts (interactions with foreign numbers) ──
    foreign_items, foreign_critical = _detect_foreign_contacts(records, own_numbers)
    groups.append({
        "type": "foreign_contacts",
        "label": "Interakcje z numerami zagranicznymi",
        "description": (
            "Połączenia i SMS z numerami zagranicznymi (spoza Polski). "
            "Dla każdego kraju podano liczbę interakcji i numery kontaktowe."
        ),
        "severity": "critical" if foreign_critical else ("info" if foreign_items else "ok"),
        "items": foreign_items,
    })

    # ── 7c. Forwarded calls ──
    forwarded_items = _detect_forwarded_calls(records, own_numbers, operator_id)
    # Build supported operators note
    _fwd_operators = "Plus, Play, T-Mobile"
    groups.append({
        "type": "forwarded_calls",
        "label": "Przekierowania połączeń",
        "description": (
            "Połączenia przekierowane na inny numer. Dla każdego zdarzenia "
            "podano datę, godzinę, numer kontaktowy i numer docelowy przekierowania. "
            f"Obsługiwane parsery: {_fwd_operators}."
        ),
        "severity": "warning" if forwarded_items else "ok",
        "items": forwarded_items,
    })

    # ── 8. One-time contacts ──
    one_time_items = _detect_one_time_contacts(records, own_numbers)
    groups.append({
        "type": "one_time_contacts",
        "label": "Jednorazowe kontakty",
        "description": (
            "Numery telefonów z którymi był dokładnie jeden kontakt "
            "w całym okresie bilingu — mogą wskazywać na jednorazowe "
            "połączenia, pomyłki lub kontakty incydentalne"
        ),
        "severity": "info" if one_time_items else "ok",
        "items": one_time_items,
    })

    # ── 9. Satellite phone numbers ──
    satellite_items = _detect_satellite_numbers(records, own_numbers)
    groups.append({
        "type": "satellite_numbers",
        "label": "Numery satelitarne",
        "description": (
            "Połączenia z numerami telefonów satelitarnych (Iridium, Inmarsat, "
            "Thuraya, Globalstar i in.) — rozpoznane na podstawie dedykowanych "
            "prefiksów międzynarodowych (+881x, +870, +882x)"
        ),
        "severity": "warning" if satellite_items else "ok",
        "items": satellite_items,
    })

    # ── 10. Social media / messenger platforms ──
    social_media_items = _detect_social_media(records, own_numbers)
    groups.append({
        "type": "social_media",
        "label": "Konta społecznościowe / komunikatory",
        "description": (
            "Nazwy komunikatorów i platform społecznościowych wykryte w polach "
            "bilingu (WhatsApp, Telegram, Viber, Facebook, VKontakte, WeChat i in.)"
        ),
        "severity": "info" if social_media_items else "ok",
        "items": social_media_items,
    })

    # ── 11. Inactivity gaps (>12 hours without any activity) ──
    inactivity_items = _detect_inactivity_gaps(records, min_hours=12)
    groups.append({
        "type": "inactivity_gap",
        "label": "Brak aktywności >12 godzin",
        "description": (
            "Okresy powyżej 12 godzin bez żadnego zdarzenia (połączenia, SMS, dane). "
            "Dla każdego okresu podano ostatni i pierwszy kontakt."
        ),
        "severity": "info" if inactivity_items else "ok",
        "items": inactivity_items,
    })

    return groups


def _detect_roaming_activity(records: List[BillingRecord]) -> List[Dict[str, Any]]:
    """Detect roaming / foreign network activity.

    Checks both the roaming flag and network field for foreign operators.
    Groups by country/network with record counts.
    """
    # Known Polish networks (prefixes / patterns)
    _POLISH_NETWORKS = {
        "orange", "play", "plus", "t-mobile", "tmobile", "t mobile",
        "polkomtel", "p4", "orange polska", "cyfrowy polsat",
        "sferia", "aero2", "mobyland", "lycamobile pl", "heyah",
        "nju mobile", "virgin mobile", "premium mobile",
    }

    country_info: Dict[str, Dict[str, Any]] = {}

    for r in records:
        country = ""
        network = ""
        mcc_mnc = ""

        if r.roaming and r.roaming_country:
            country = r.roaming_country
            network = r.network or ""
            mcc_mnc = r.extra.get("roaming_mcc_mnc", "") if r.extra else ""
        elif r.network:
            # Check if the network is non-Polish
            net_lower = r.network.strip().lower()
            is_polish = any(pn in net_lower for pn in _POLISH_NETWORKS)
            if not is_polish and net_lower and len(net_lower) > 1:
                # Try to extract country from network name or mark as foreign
                country = r.roaming_country or "zagraniczny"
                network = r.network
        else:
            continue

        if not country:
            continue

        key = country.upper()
        if key not in country_info:
            country_info[key] = {"country": country, "count": 0, "networks": set(),
                                 "mcc_mnc_codes": set(),
                                 "first_date": r.date, "last_date": r.date}
        country_info[key]["count"] += 1
        if network:
            country_info[key]["networks"].add(network)
        if mcc_mnc:
            country_info[key]["mcc_mnc_codes"].add(mcc_mnc)
        if r.date < country_info[key]["first_date"]:
            country_info[key]["first_date"] = r.date
        if r.date > country_info[key]["last_date"]:
            country_info[key]["last_date"] = r.date

    items = []
    for key, info in sorted(country_info.items()):
        period = info["first_date"]
        if info["first_date"] != info["last_date"]:
            period = f"{info['first_date']} – {info['last_date']}"
        item: Dict[str, Any] = {
            "country": info["country"],
            "count": info["count"],
            "networks": sorted(info["networks"]),
            "period": period,
        }
        if info["mcc_mnc_codes"]:
            item["mcc_mnc"] = sorted(info["mcc_mnc_codes"])
        items.append(item)
    return items


def _detect_foreign_contacts(
    records: List[BillingRecord],
    own_numbers: Set[str],
) -> Tuple[List[Dict[str, Any]], bool]:
    """Detect interactions with foreign (non-Polish) phone numbers.

    Groups by country with number lists, counts, and date ranges.
    Marks as critical if Russia, Ukraine, Belarus, or China detected.

    Returns:
        (items, is_critical) — items grouped by country, is_critical=True
        if RU/UA/BY/CN numbers found.
    """
    country_info: Dict[str, Dict[str, Any]] = {}

    for r in records:
        # Check both callee and caller
        for contact, is_outgoing in [
            (r.callee, True),
            (r.caller, False),
        ]:
            if not contact or contact in own_numbers:
                continue
            if not contact.startswith("+") or contact.startswith("+48"):
                continue
            if len(contact) <= 8:
                continue  # too short to be a real international number

            result = _identify_country_by_prefix(contact)
            if not result:
                # Unknown prefix — group as "Nieznany"
                iso, country_name = "??", f"Nieznany ({contact[:4]}...)"
            else:
                iso, country_name = result

            key = iso
            if key not in country_info:
                country_info[key] = {
                    "country": country_name,
                    "country_code": iso,
                    "numbers": set(),
                    "count": 0,
                    "outgoing": 0,
                    "incoming": 0,
                    "first_date": r.date or "",
                    "last_date": r.date or "",
                    "critical": iso in _CRITICAL_COUNTRY_CODES,
                }

            info = country_info[key]
            info["numbers"].add(contact)
            info["count"] += 1
            if is_outgoing:
                info["outgoing"] += 1
            else:
                info["incoming"] += 1
            if r.date:
                if not info["first_date"] or r.date < info["first_date"]:
                    info["first_date"] = r.date
                if not info["last_date"] or r.date > info["last_date"]:
                    info["last_date"] = r.date

    # Build items — critical countries first, then by count
    is_critical = any(info["critical"] for info in country_info.values())

    items = []
    for key, info in sorted(
        country_info.items(),
        key=lambda kv: (not kv[1]["critical"], -kv[1]["count"]),
    ):
        period = info["first_date"]
        if info["first_date"] != info["last_date"]:
            period = f"{info['first_date']} \u2013 {info['last_date']}"
        items.append({
            "country": info["country"],
            "country_code": info["country_code"],
            "count": info["count"],
            "numbers": sorted(info["numbers"]),
            "period": period,
            "outgoing": info["outgoing"],
            "incoming": info["incoming"],
            "critical": info["critical"],
        })

    return items, is_critical


# Parsers that support forwarding data (operator_id → field name in extra)
_FORWARDING_SUPPORT: Dict[str, str] = {
    "plus": "c_msisdn",           # Plus: C party MSISDN
    "play": "forwarded_msisdn",   # Play: PRZEK_MSISDN column
    "tmobile": "nr_powiazany",    # T-Mobile: Nr powiązany (may contain forwarded-to)
}


def _detect_forwarded_calls(
    records: List[BillingRecord],
    own_numbers: Set[str],
    operator_id: str = "",
) -> List[Dict[str, Any]]:
    """Detect call forwarding events.

    Looks for records with record_type == CALL_FORWARDED and extracts
    forwarding details (forwarded-to number, date/time).

    Forwarding data availability by operator:
    - Plus (Polkomtel): FORW type code, C party (c_msisdn) = forwarded-to
    - Play (P4): PRZEK_MSISDN column (forwarded_msisdn in extra)
    - T-Mobile: direction "przekierowane", nr_powiazany may have target
    - Orange: text-based detection via record_type label, no target number
    - Orange Retencja: no forwarding support

    Returns:
        List of forwarding event dicts.
    """
    items: List[Dict[str, Any]] = []

    # Determine which extra field holds forwarded-to number
    fwd_field = _FORWARDING_SUPPORT.get(operator_id, "")

    for r in records:
        # Detect forwarding: explicit CALL_FORWARDED record_type OR
        # non-empty forwarding extra field (c_msisdn, forwarded_msisdn, nr_powiazany)
        # even when record_type is CALL_OUT/CALL_IN (Plus may use MOC/MTC with c_msisdn)
        is_fwd = r.record_type == "CALL_FORWARDED"
        forwarded_to = ""

        if not is_fwd:
            # Check extra fields for forwarding indicators
            if fwd_field and r.extra.get(fwd_field):
                val = r.extra[fwd_field]
                if val not in own_numbers:
                    is_fwd = True
                    forwarded_to = val
            if not forwarded_to:
                for f in ("c_msisdn", "forwarded_msisdn", "nr_powiazany"):
                    val = r.extra.get(f, "")
                    if val and val not in own_numbers:
                        is_fwd = True
                        forwarded_to = val
                        break

        if not is_fwd:
            continue

        # Determine the forwarded-to number (for explicit CALL_FORWARDED records)
        if not forwarded_to:
            if fwd_field and r.extra.get(fwd_field):
                forwarded_to = r.extra[fwd_field]
            if not forwarded_to:
                for f in ("c_msisdn", "forwarded_msisdn", "nr_powiazany"):
                    val = r.extra.get(f, "")
                    if val and val not in own_numbers:
                        forwarded_to = val
                        break

        # Determine calling party (the other end)
        contact = ""
        if r.callee and r.callee not in own_numbers:
            contact = r.callee
        elif r.caller and r.caller not in own_numbers:
            contact = r.caller

        items.append({
            "date": r.date,
            "time": r.time,
            "contact": contact,
            "forwarded_to": forwarded_to,
            "duration_seconds": r.duration_seconds,
            "duration_min": round(r.duration_seconds / 60, 1) if r.duration_seconds else 0,
            "location": r.location or "",
        })

    # Sort by date/time
    items.sort(key=lambda x: f"{x['date']} {x['time']}")

    return items


def _detect_inactivity_gaps(
    records: List[BillingRecord],
    min_hours: float = 12,
) -> List[Dict[str, Any]]:
    """Detect gaps in activity longer than min_hours.

    For each gap, reports:
    - last record before the gap (date, time, contact, type)
    - first record after the gap (date, time, contact, type)
    - gap duration in hours
    """
    from datetime import datetime as dt_cls, timedelta

    def _parse_dt(s: str) -> Optional[dt_cls]:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
            try:
                return dt_cls.strptime(s, fmt)
            except (ValueError, TypeError):
                continue
        return None

    # Parse and sort records by datetime
    parsed: List[Tuple[dt_cls, BillingRecord]] = []
    for r in records:
        if r.datetime:
            d = _parse_dt(r.datetime)
            if d:
                parsed.append((d, r))
    parsed.sort(key=lambda x: x[0])

    if len(parsed) < 2:
        return []

    items: List[Dict[str, Any]] = []
    threshold = timedelta(hours=min_hours)

    for i in range(1, len(parsed)):
        prev_dt, prev = parsed[i - 1]
        curr_dt, curr = parsed[i]
        gap = curr_dt - prev_dt
        if gap >= threshold:
            gap_hours = round(gap.total_seconds() / 3600, 1)
            items.append({
                "gap_hours": gap_hours,
                "last_date": prev.date,
                "last_time": prev.time,
                "last_contact": prev.callee or prev.caller or "\u2014",
                "last_type": prev.record_type,
                "first_date": curr.date,
                "first_time": curr.time,
                "first_contact": curr.callee or curr.caller or "\u2014",
                "first_type": curr.record_type,
            })

    # Sort by gap duration (longest first)
    items.sort(key=lambda x: -x["gap_hours"])
    return items


def _detect_night_movement(records: List[BillingRecord]) -> List[Dict[str, Any]]:
    """Detect BTS location changes after night-time activity (23:00–05:00).

    Finds cases where the user has communication at night and the BTS location
    changes significantly between consecutive night records — suggesting
    they were on the move at unusual hours.
    """
    items: List[Dict[str, Any]] = []
    sorted_recs = sorted(
        [r for r in records if r.datetime and r.location],
        key=lambda r: r.datetime,
    )

    prev_night_rec = None
    for r in sorted_recs:
        try:
            hour = int(r.time.split(":")[0])
        except (ValueError, IndexError):
            continue
        if hour >= 23 or hour < 5:
            if prev_night_rec and prev_night_rec.date == r.date:
                loc_a = prev_night_rec.location.strip()
                loc_b = r.location.strip()
                if loc_a and loc_b and loc_a != loc_b:
                    items.append({
                        "date": r.date,
                        "time_from": prev_night_rec.time,
                        "time_to": r.time,
                        "bts_from": loc_a,
                        "bts_to": loc_b,
                        "contact": r.callee or r.caller or "",
                    })
            prev_night_rec = r
        else:
            prev_night_rec = None

    # Deduplicate — keep unique (date, bts_from, bts_to) combos
    seen = set()
    unique = []
    for it in items:
        key = (it["date"], it["bts_from"], it["bts_to"])
        if key not in seen:
            seen.add(key)
            unique.append(it)
    return unique


def _detect_one_time_contacts(
    records: List[BillingRecord],
    own_numbers: Set[str],
) -> List[Dict[str, Any]]:
    """Find phone numbers that appear exactly once in the entire billing."""
    contact_counts: Dict[str, Dict[str, Any]] = {}
    for r in records:
        contact = r.callee or r.caller
        if not contact or contact in own_numbers:
            continue
        if contact not in contact_counts:
            contact_counts[contact] = {"count": 0, "date": r.date, "type": r.record_type}
        contact_counts[contact]["count"] += 1

    items = []
    for num, info in contact_counts.items():
        if info["count"] == 1:
            items.append({
                "contact": num,
                "date": info["date"],
                "record_type": info["type"],
            })
    # Limit to 30 most recent
    items.sort(key=lambda x: x["date"], reverse=True)
    return items[:30]


def _load_satellite_rules() -> Dict[str, Any]:
    """Load satellite detection rules from JSON config (cached)."""
    if not hasattr(_load_satellite_rules, "_cache"):
        rules_path = Path(__file__).parent / "satellite_rules.json"
        try:
            _load_satellite_rules._cache = json.loads(rules_path.read_text(encoding="utf-8"))
        except Exception:
            _load_satellite_rules._cache = {}
    return _load_satellite_rules._cache


def _normalize_for_satellite(number: str) -> str:
    """Normalize a phone number to E.164-like format for satellite matching.

    Strips separators, converts 00 prefix to +, keeps only + and digits.
    """
    # Remove common separators
    cleaned = re.sub(r"[\s\-\(\)\./]", "", number)
    # Convert 00 prefix to +
    if cleaned.startswith("00"):
        cleaned = "+" + cleaned[2:]
    # Keep only leading + and digits
    if cleaned.startswith("+"):
        cleaned = "+" + re.sub(r"[^\d]", "", cleaned[1:])
    else:
        cleaned = re.sub(r"[^\d]", "", cleaned)
    return cleaned


def _detect_satellite_numbers(
    records: List[BillingRecord],
    own_numbers: Set[str],
) -> List[Dict[str, Any]]:
    """Detect calls to/from satellite phone numbers based on prefix rules.

    Uses rules from satellite_rules.json — checks active_high_confidence first,
    then optional_medium_low_confidence.
    """
    rules_data = _load_satellite_rules()
    if not rules_data:
        return []

    rules_section = rules_data.get("rules", {})
    high_rules = rules_section.get("active_high_confidence", [])
    optional_rules = rules_section.get("optional_medium_low_confidence", [])

    # Compile regexes once
    compiled_rules: List[Tuple[re.Pattern, re.Pattern, Dict[str, Any]]] = []
    for rule in high_rules + optional_rules:
        try:
            pat_e164 = re.compile(rule["regex_e164"])
            pat_digits = re.compile(rule["regex_digits"])
            compiled_rules.append((pat_e164, pat_digits, rule))
        except (KeyError, re.error):
            continue

    # Scan records
    satellite_hits: Dict[str, Dict[str, Any]] = {}  # keyed by normalized number
    for r in records:
        contact = r.callee or r.caller
        if not contact or contact in own_numbers:
            continue

        normalized = _normalize_for_satellite(contact)
        if not normalized or len(normalized) < 6:
            continue

        # Already matched this number
        if normalized in satellite_hits:
            satellite_hits[normalized]["count"] += 1
            satellite_hits[normalized]["dates"].add(r.date)
            continue

        # Try matching
        for pat_e164, pat_digits, rule in compiled_rules:
            digits_only = normalized.lstrip("+")
            if pat_e164.match(normalized) or pat_digits.match(digits_only):
                satellite_hits[normalized] = {
                    "contact": contact,
                    "normalized": normalized,
                    "operator": rule.get("operator", "?"),
                    "rule_id": rule.get("rule_id", ""),
                    "confidence": rule.get("confidence", "?"),
                    "category": rule.get("category", ""),
                    "description": rule.get("description", ""),
                    "count": 1,
                    "dates": {r.date},
                }
                break

    # Convert to list
    items = []
    for info in satellite_hits.values():
        items.append({
            "contact": info["contact"],
            "normalized": info["normalized"],
            "operator": info["operator"],
            "rule_id": info["rule_id"],
            "confidence": info["confidence"],
            "category": info["category"],
            "count": info["count"],
            "dates": sorted(info["dates"]),
        })
    items.sort(key=lambda x: x["count"], reverse=True)
    return items


def _load_social_media_rules() -> Dict[str, Any]:
    """Load social media / messenger detection rules from JSON config (cached)."""
    if not hasattr(_load_social_media_rules, "_cache"):
        rules_path = Path(__file__).parent / "social_media_rules.json"
        try:
            _load_social_media_rules._cache = json.loads(rules_path.read_text(encoding="utf-8"))
        except Exception:
            _load_social_media_rules._cache = {}
    return _load_social_media_rules._cache


def _detect_social_media(
    records: List[BillingRecord],
    own_numbers: Set[str],
) -> List[Dict[str, Any]]:
    """Detect messenger / social media platform names in billing record fields.

    Scans callee, caller, network, raw_text, and extra fields for known
    platform names using regex patterns from social_media_rules.json.
    """
    rules_data = _load_social_media_rules()
    if not rules_data:
        return []

    categories = rules_data.get("categories", {})

    # Pre-compile all regexes grouped by platform
    compiled: List[Tuple[re.Pattern, str, str, str]] = []  # (regex, platform_name, category_key, category_label)
    for cat_key, cat_data in categories.items():
        cat_label = cat_data.get("label", cat_key)
        for platform in cat_data.get("platforms", []):
            regex_str = platform.get("regex", "")
            if not regex_str:
                continue
            try:
                pat = re.compile(regex_str, re.IGNORECASE)
                compiled.append((pat, platform["name"], cat_key, cat_label))
            except re.error:
                continue

    if not compiled:
        return []

    # Scan records
    platform_hits: Dict[str, Dict[str, Any]] = {}  # keyed by platform name

    for r in records:
        # Build searchable text from all relevant fields
        parts = []
        if r.callee:
            parts.append(r.callee)
        if r.caller:
            parts.append(r.caller)
        if r.network:
            parts.append(r.network)
        if r.raw_text:
            parts.append(r.raw_text)
        # Check extra dict fields
        if r.extra:
            for key in ("service", "description", "direction", "system"):
                val = r.extra.get(key, "")
                if val:
                    parts.append(str(val))

        if not parts:
            continue

        search_text = " ".join(parts).lower()

        for pat, platform_name, cat_key, cat_label in compiled:
            if pat.search(search_text):
                if platform_name not in platform_hits:
                    platform_hits[platform_name] = {
                        "platform": platform_name,
                        "category": cat_label,
                        "category_key": cat_key,
                        "count": 0,
                        "dates": set(),
                        "record_types": set(),
                        "contacts": set(),
                    }
                info = platform_hits[platform_name]
                info["count"] += 1
                if r.date:
                    info["dates"].add(r.date)
                if r.record_type:
                    info["record_types"].add(r.record_type)
                contact = r.callee or r.caller
                if contact and contact not in own_numbers:
                    info["contacts"].add(contact)

    # Convert to list
    items = []
    for info in platform_hits.values():
        items.append({
            "platform": info["platform"],
            "category": info["category"],
            "category_key": info["category_key"],
            "count": info["count"],
            "dates": sorted(info["dates"]),
            "record_types": sorted(info["record_types"]),
            "unique_contacts": len(info["contacts"]),
        })
    items.sort(key=lambda x: x["count"], reverse=True)
    return items


def _detect_burst_activity(
    records: List[BillingRecord],
    items: List[Dict[str, Any]],
    threshold: int = 20,
    window_minutes: int = 30,
) -> None:
    """Detect bursts of activity (many records in a short time window)."""
    sorted_records = sorted(records, key=lambda r: r.datetime)

    for i, r in enumerate(sorted_records):
        if not r.datetime:
            continue
        count = 1
        for j in range(i + 1, min(i + threshold * 2, len(sorted_records))):
            if not sorted_records[j].datetime:
                continue
            if sorted_records[j].date == r.date:
                try:
                    t1_parts = r.time.split(":")
                    t2_parts = sorted_records[j].time.split(":")
                    mins1 = int(t1_parts[0]) * 60 + int(t1_parts[1])
                    mins2 = int(t2_parts[0]) * 60 + int(t2_parts[1])
                    if mins2 - mins1 <= window_minutes:
                        count += 1
                    else:
                        break
                except (ValueError, IndexError):
                    break
            else:
                break

        if count >= threshold:
            items.append({
                "date": r.date,
                "time": r.time,
                "count": count,
                "window_min": window_minutes,
            })
            break  # Report only the first burst
