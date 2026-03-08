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

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
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

    # 6. IMEI changes
    analysis.imei_changes = _detect_imei_changes(records)

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
    analysis.anomalies = _detect_anomalies(records, analysis, own_numbers)

    return analysis


def _analyze_contacts(
    records: List[BillingRecord],
    own_numbers: Set[str],
    top_n: int,
) -> List[ContactProfile]:
    """Build contact profiles for all interacted numbers."""
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

        if contact not in profiles:
            profiles[contact] = ContactProfile(number=contact)

        p = profiles[contact]
        p.total_interactions += 1

        if r.record_type == "CALL_OUT":
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


def _detect_imei_changes(records: List[BillingRecord]) -> List[Dict[str, str]]:
    """Detect IMEI changes over time (device changes)."""
    changes: List[Dict[str, str]] = []
    last_imei = ""

    for r in sorted(records, key=lambda r: r.datetime):
        if r.imei and r.imei != last_imei:
            if last_imei:
                changes.append({
                    "date": r.date,
                    "old_imei": last_imei,
                    "new_imei": r.imei,
                })
            last_imei = r.imei

    return changes


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

# Patterns for number classification
_SPECIAL_PATTERNS: List[Tuple[str, str, str]] = [
    # (regex_pattern, category, label_prefix)
    # Toll-free must be checked before premium (800/801 are toll-free, not premium)
    (r"^\+?48800\d{6}$", "toll_free", "Numer bezpłatny 800"),
    (r"^\+?48801\d{6}$", "toll_free", "Numer bezpłatny 801"),
    (r"^\+?48[78]0[01]\d{6}$", "premium", "Numer premium"),
    (r"^\+?48700\d{6}$", "premium", "Numer premium 700"),
    (r"^\+?48300\d{6}$", "premium", "Numer premium 300"),
    (r"^\d{3,6}$", "short_code", "Kod krótki"),
]


def _classify_special_number(number: str) -> Optional[Dict[str, str]]:
    """Check if a number is 'special' (non-standard mobile number).

    Returns dict with category/label or None if it's a regular mobile number.
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

    # Pattern-based
    for pat, cat, label in _SPECIAL_PATTERNS:
        if re.match(pat, number):
            return {"category": cat, "label": f"{label} ({number})"}

    # Foreign numbers (non-Polish, non-short)
    if number.startswith("+") and not number.startswith("+48") and len(number) > 8:
        return {"category": "international", "label": f"Numer zagraniczny ({number[:4]}…)"}

    return None


def _detect_special_numbers(
    records: List[BillingRecord],
    own_numbers: Set[str],
) -> List[Dict[str, Any]]:
    """Detect all interactions with special (non-standard) numbers."""
    seen: Dict[str, Dict[str, Any]] = {}

    for r in records:
        contact = r.callee or r.caller
        if not contact or contact in own_numbers:
            continue

        if contact in seen:
            seen[contact]["interactions"] += 1
            seen[contact]["total_duration_seconds"] += r.duration_seconds
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
            "first_date": r.date,
            "last_date": r.date,
        }

    # Update date ranges
    for r in records:
        contact = r.callee or r.caller
        if contact in seen and r.date:
            if not seen[contact]["first_date"] or r.date < seen[contact]["first_date"]:
                seen[contact]["first_date"] = r.date
            if not seen[contact]["last_date"] or r.date > seen[contact]["last_date"]:
                seen[contact]["last_date"] = r.date

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
) -> List[Dict[str, Any]]:
    """Detect anomalies and unusual patterns."""
    anomalies: List[Dict[str, Any]] = []

    if not records:
        return anomalies

    # 1. Unusually long calls (> 2 hours)
    for r in records:
        if r.duration_seconds > 7200 and "CALL" in r.record_type:
            anomalies.append({
                "type": "long_call",
                "severity": "info",
                "description": (
                    f"Długie połączenie: {r.duration_seconds // 60} min "
                    f"z {r.callee or r.caller} ({r.date} {r.time})"
                ),
                "record_datetime": r.datetime,
                "contact": r.callee or r.caller,
            })

    # 2. High night activity
    if analysis.temporal.night_activity_ratio > 0.3:
        anomalies.append({
            "type": "night_activity",
            "severity": "warning",
            "description": (
                f"Wysoka aktywność nocna: "
                f"{analysis.temporal.night_activity_ratio:.0%} "
                f"połączeń między 23:00-05:00"
            ),
        })

    # 3. Burst activity — many records in short time
    _detect_burst_activity(records, anomalies)

    # 4. IMEI changes
    if len(analysis.imei_changes) > 2:
        anomalies.append({
            "type": "frequent_imei_change",
            "severity": "warning",
            "description": (
                f"Częste zmiany urządzenia (IMEI): "
                f"{len(analysis.imei_changes)} zmian"
            ),
            "changes": analysis.imei_changes,
        })

    # 5. Premium/foreign numbers
    for r in records:
        contact = r.callee or r.caller
        if not contact:
            continue
        # Premium rate numbers (70x, 80x)
        if re.match(r"^\+?48[78]0\d", contact):
            anomalies.append({
                "type": "premium_number",
                "severity": "info",
                "description": f"Połączenie z numerem premium: {contact} ({r.date})",
                "record_datetime": r.datetime,
                "contact": contact,
            })

    # 6. Roaming usage
    roaming_records = [r for r in records if r.roaming]
    if roaming_records:
        countries = set(r.roaming_country for r in roaming_records if r.roaming_country)
        anomalies.append({
            "type": "roaming",
            "severity": "info",
            "description": (
                f"Aktywność roamingowa: {len(roaming_records)} rekordów"
                + (f" (kraje: {', '.join(countries)})" if countries else "")
            ),
            "count": len(roaming_records),
        })

    return anomalies


def _detect_burst_activity(
    records: List[BillingRecord],
    anomalies: List[Dict[str, Any]],
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
            # Simple comparison — same date and close time
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
            anomalies.append({
                "type": "burst_activity",
                "severity": "warning",
                "description": (
                    f"Skok aktywności: {count} rekordów w {window_minutes} min "
                    f"({r.date} od {r.time})"
                ),
                "date": r.date,
                "time": r.time,
                "count": count,
            })
            break  # Report only the first burst
