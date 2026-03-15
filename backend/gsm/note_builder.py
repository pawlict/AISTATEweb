"""
GSM Note Builder — maps gsm_latest.json data to the placeholder dict
expected by the professional DOCX note template.

Two variants:
  1) Variant "data"  — pure data, no LLM, template text stays as-is
  2) Variant "llm"   — LLM generates narrative sections (4-9)

This module handles variant 1 (data extraction).  For variant 2,
see note_llm.py which produces overrides for text-heavy placeholders.

Data structure reference (gsm_latest.json):
  billing.subscriber: {msisdn, imsi, imei, operator, owner_name, ...}
  billing.summary: {total_records, calls_out, calls_in, sms_out, sms_in,
                    data_sessions, period_from, period_to, unique_contacts,
                    total_duration_seconds, call_duration_seconds, ...}
  billing.analysis: {top_contacts[], temporal{}, locations[], anomalies[],
                     devices[], dual_imei{}, imei_changes[], special_numbers[],
                     night_activity{}, weekend_activity{}, overnight_stays[],
                     avg_call_duration, median_call_duration, ...}
"""
from __future__ import annotations

import datetime
from typing import Any, Dict, List, Optional


# ─── Public API ──────────────────────────────────────────────────────────────

def build_note_placeholders(
    gsm_data: dict,
    *,
    user_placeholders: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Extract all template placeholders from gsm_latest.json.

    Args:
        gsm_data: Full gsm_latest.json (has "billing", "identification", etc.)
        user_placeholders: User-supplied values for meta fields
            (sygnatura_sprawy, analityk, miejscowosc, etc.)

    Returns:
        Dict[str, Any] with keys matching {{ placeholder }} names in the DOCX template.
    """
    up = user_placeholders or {}
    billing = gsm_data.get("billing", {})
    subscriber = billing.get("subscriber", {})
    summary = billing.get("summary", {})
    analysis = billing.get("analysis", {})

    # ── Basic subscriber / meta ──
    msisdn = subscriber.get("msisdn", "N/A")
    # operator can be in subscriber.operator, subscriber.operator_name, or billing.operator
    operator = (
        subscriber.get("operator_name")
        or subscriber.get("operator")
        or billing.get("operator", "N/A")
    )
    imsi = subscriber.get("imsi", "")

    # IMEI from devices list
    devices = analysis.get("devices", [])
    imei_list_items = [d.get("imei", "") for d in devices if d.get("imei")]
    imei_list = ", ".join(imei_list_items) if imei_list_items else subscriber.get("imei", "N/A")
    imsi_primary = imsi or "N/A"
    imsi_list_str = imsi or "N/A"

    # Dual-IMEI — detected if dict exists and has voice_imei
    dual_imei = analysis.get("dual_imei") or {}
    dual_detected = bool(dual_imei and dual_imei.get("voice_imei"))
    dual_imei_present = "TAK" if dual_detected else "NIE"
    if dual_detected:
        dual_imei_value = (
            f"Voice: {dual_imei.get('voice_imei', '?')} "
            f"({dual_imei.get('voice_records', 0)} rek.) / "
            f"Data: {dual_imei.get('data_imei', '?')} "
            f"({dual_imei.get('data_records', 0)} rek.)"
        )
    else:
        dual_imei_value = "brak"

    # IMEI changes
    imei_changes = analysis.get("imei_changes", [])
    imei_change_count = str(len(imei_changes)) if imei_changes else "0"

    # Device notes
    device_notes_parts = []
    if dual_detected:
        device_notes_parts.append(
            f"Urządzenie dual-modem: IMEI głosowy {dual_imei.get('voice_imei', '?')}, "
            f"IMEI danych {dual_imei.get('data_imei', '?')}"
        )
        if dual_imei.get("same_tac"):
            device_notes_parts.append("TAC obu IMEI identyczny (to samo urządzenie)")
    if imei_changes:
        device_notes_parts.append(f"Wykryto {len(imei_changes)} zmian IMEI w badanym okresie")
    # Add device brand/model info
    for dev in devices:
        dn = dev.get("display_name", "")
        if dn and dn != "Unknown":
            device_notes_parts.append(f"{dev.get('imei', '?')}: {dn}")
    device_identification_notes = ". ".join(device_notes_parts) if device_notes_parts else "Brak uwag"

    # ── Period — directly in summary as period_from / period_to ──
    period_from = summary.get("period_from", "N/A")
    period_to = summary.get("period_to", "N/A")

    # ── Statistics — directly in summary, NOT in by_type ──
    total_records = summary.get("total_records", billing.get("record_count", 0))
    calls_out = summary.get("calls_out", 0) or 0
    calls_in = summary.get("calls_in", 0) or 0
    sms_out = summary.get("sms_out", 0) or 0
    sms_in = summary.get("sms_in", 0) or 0
    mms_out = summary.get("mms_out", 0) or 0
    mms_in = summary.get("mms_in", 0) or 0
    data_sessions = summary.get("data_sessions", 0) or 0
    unique_contacts = summary.get("unique_contacts", 0) or 0
    call_duration_seconds = summary.get("call_duration_seconds", 0) or 0
    total_duration_seconds = summary.get("total_duration_seconds", 0) or 0
    roaming_records = summary.get("roaming_records", 0) or 0

    # Forwarded calls — count from records if available
    records = billing.get("records", [])
    fwd_count = sum(1 for r in records if r.get("record_type") == "CALL_FORWARDED") if records else 0

    # ── Source descriptions ──
    voice_total = calls_out + calls_in + fwd_count
    sms_total = sms_out + sms_in + mms_out + mms_in
    source_calls = f"{voice_total} rekordów połączeń głosowych" if voice_total else "brak danych o połączeniach"
    source_sms = f"{sms_total} rekordów SMS/MMS" if sms_total else "brak danych SMS"
    source_data = f"{data_sessions} sesji transmisji danych" if data_sessions else "brak danych transmisji"
    source_identifiers = f"{len(imei_list_items)} identyfikatorów IMEI" if imei_list_items else "dane identyfikacyjne"

    # Contacts
    top_contacts = analysis.get("top_contacts", [])
    if not unique_contacts:
        unique_contacts = len(top_contacts)
    source_contacts = f"{unique_contacts} unikalnych kontaktów" if unique_contacts else "brak danych kontaktowych"

    # Locations
    locations = analysis.get("locations", [])
    source_locations = f"{len(locations)} lokalizacji BTS" if locations else "brak danych lokalizacyjnych"

    # Anomalies
    anomalies = analysis.get("anomalies", [])
    source_anomalies = f"{len(anomalies)} kategorii anomalii" if anomalies else "brak anomalii"

    # ── Activity patterns ──
    temporal = analysis.get("temporal", {})
    night_activity = analysis.get("night_activity", {})
    weekend_activity = analysis.get("weekend_activity", {})

    # Hourly pattern
    peak_hour = temporal.get("peak_hour")
    hourly_pattern = (
        f"szczytową aktywność w godzinie {peak_hour}:00"
        if peak_hour is not None
        else "brak danych o rozkładzie godzinowym"
    )

    # Night share — use night_activity.percentage or temporal.night_activity_ratio
    night_pct = night_activity.get("percentage")
    if night_pct is not None:
        night_share = f"{night_pct:.1f}%"
    else:
        night_ratio = temporal.get("night_activity_ratio", 0)
        night_share = f"{night_ratio:.1%}" if night_ratio else "brak danych"

    # Weekend share — use weekend_activity.percentage
    weekend_pct = weekend_activity.get("percentage")
    if weekend_pct is not None:
        weekend_share = f"{weekend_pct:.1f}%"
    else:
        weekend_total = weekend_activity.get("total_records", 0)
        all_total = total_records if total_records else 1
        weekend_share = f"{weekend_total / all_total:.1%}" if weekend_total else "brak danych"

    # ── Special numbers ──
    special_numbers = analysis.get("special_numbers", [])
    if special_numbers:
        # category is the field name, not type
        sn_categories = set(sn.get("category", sn.get("type", "")) for sn in special_numbers)
        special_numbers_summary = ", ".join(sorted(c for c in sn_categories if c)) or f"{len(special_numbers)} numerów specjalnych"
    else:
        special_numbers_summary = "brak numerów specjalnych"

    # ── Contacts details ──
    if top_contacts:
        top_list_parts = []
        for c in top_contacts[:5]:
            num = c.get("number", "?")
            total_int = c.get("total_interactions", 0)
            top_list_parts.append(f"{num} ({total_int} interakcji)")
        contacts_top_list = "; ".join(top_list_parts)
    else:
        contacts_top_list = "brak danych"

    contacts_assessment = _build_contacts_assessment(top_contacts, unique_contacts)

    # ── Anomalies details ──
    anomaly_categories = _categorize_anomalies(anomalies)
    anomaly_count = str(len(anomaly_categories))
    # Use label if available, else type
    anomaly_labels = []
    for a in anomalies:
        lbl = a.get("label", a.get("type", ""))
        if lbl and lbl not in anomaly_labels:
            anomaly_labels.append(lbl)
    anomaly_categories_str = ", ".join(anomaly_labels) if anomaly_labels else "brak"
    anomaly_top_findings = _top_anomaly_findings(anomalies)

    # Anomaly table rows with "Dane" column (items from billing data)
    anomaly_table_rows = _build_anomaly_table_rows(anomalies)

    # ── Locations details ──
    if locations:
        main_areas = ", ".join(loc.get("location", "?") for loc in locations[:3])
        bts_count = str(len(locations))
        dominant_bts = locations[0].get("location", "?")
    else:
        main_areas = "brak danych lokalizacyjnych"
        bts_count = "0"
        dominant_bts = "brak danych"

    # Location dash-list for BTS areas (section 7)
    location_areas_list = _build_location_areas_list(locations)

    # Overnight stays
    overnight_stays = analysis.get("overnight_stays", [])
    if overnight_stays:
        home = analysis.get("overnight_stays_home", "")
        home_str = f" (dom: {home})" if home else ""
        overnights_summary = f"Wykryto {len(overnight_stays)} noclegów poza domem{home_str}"
    else:
        overnights_summary = "nie wykryto noclegów poza domem"

    # Movement/overnight dash-list (section 7)
    location_movement_list = _build_location_movement_list(
        overnight_stays, analysis.get("overnight_stays_home", ""),
        night_activity, locations
    )

    # ── Assessment ──
    assessment_main = _build_main_characteristics(
        total_records, calls_out, calls_in, sms_out, sms_in,
        data_sessions, anomalies, dual_detected, fwd_count
    )
    assessment_working = (
        "Dane bilingowe dostarczają informacji o aktywności telekomunikacyjnej, "
        "które mogą stanowić podstawę do dalszych ustaleń analitycznych"
    )

    # ── Conclusions ──
    conclusions = _build_conclusions(
        msisdn, period_from, period_to, total_records, len(imei_list_items),
        dual_detected, len(anomaly_categories), unique_contacts, top_contacts,
        main_areas
    )

    # ── Data raportu HTML ──
    data_raportu_html = datetime.datetime.now().strftime("%d.%m.%Y, %H:%M")

    # ── Parametr główny ──
    parametr_glowny = msisdn

    # ── Źródła danych ──
    zrodla = []
    if voice_total > 0:
        zrodla.append("połączenia głosowe")
    if sms_total > 0:
        zrodla.append("SMS/MMS")
    if data_sessions > 0:
        zrodla.append("transmisja danych")
    if locations:
        zrodla.append("dane BTS")
    if roaming_records > 0:
        zrodla.append("roaming")
    zrodla_danych = ", ".join(zrodla) if zrodla else "biling telekomunikacyjny"

    # ── Build final dict ──
    placeholders: Dict[str, Any] = {
        # Meta (user-editable)
        "miejscowosc": up.get("miejscowosc", ""),
        "data_sporzadzenia": up.get("data_sporzadzenia", datetime.datetime.now().strftime("%d.%m.%Y")),
        "sygnatura_sprawy": up.get("sygnatura_sprawy", ""),
        "analityk": up.get("analityk", ""),
        "podpis": up.get("podpis", up.get("analityk", "")),
        "akceptacja": up.get("akceptacja", ""),

        # Subscriber / Identification
        "msisdn": msisdn,
        "operator": operator,
        "period_from": period_from,
        "period_to": period_to,
        "total_records": str(total_records),
        "parametr_glowny": parametr_glowny,
        "imsi_list": imsi_list_str,
        "imsi_primary": imsi_primary,
        "imei_list": imei_list,
        "unique_imei_count": str(len(imei_list_items)) if imei_list_items else "1",
        "dual_imei_present": dual_imei_present,
        "dual_imei_value": dual_imei_value,
        "imei_change_count": imei_change_count,
        "device_identification_notes": device_identification_notes,

        # Table meta
        "data_raportu_html": data_raportu_html,
        "zrodla_danych": zrodla_danych,

        # Stats (section 4 — {{ stats.outgoing_calls }} etc.)
        "stats": {
            "outgoing_calls": str(calls_out),
            "incoming_calls": str(calls_in),
            "sms_out": str(sms_out),
            "sms_in": str(sms_in),
            "data_sessions": str(data_sessions),
        },

        # Sources (section 2 — {{ source.calls }} etc.)
        "source": {
            "calls": source_calls,
            "sms": source_sms,
            "data": source_data,
            "identifiers": source_identifiers,
            "contacts": source_contacts,
            "locations": source_locations,
            "anomalies": source_anomalies,
        },

        # Activity (section 4 — {{ activity.hourly_pattern }} etc.)
        "activity": {
            "hourly_pattern": hourly_pattern,
            "night_share": night_share,
            "weekend_share": weekend_share,
        },
        "special_numbers_summary": special_numbers_summary,

        # Contacts (section 5 — {{ contacts.unique_count }} etc.)
        "contacts": {
            "unique_count": str(unique_contacts),
            "top_list": contacts_top_list,
            "assessment": contacts_assessment,
        },

        # Anomalies (section 6)
        # NOTE: categories and top_findings are cleared — the old synthetic
        # description is replaced by the programmatic anomaly intro + table.
        "anomalies": {
            "count": anomaly_count,
            "categories": "",
            "top_findings": "",
        },
        # Anomaly table rows for programmatic insertion (Kategoria/Opis/Dane)
        "_anomaly_table_rows": anomaly_table_rows,

        # Locations (section 7 — {{ locations.main_areas }} etc.)
        "locations": {
            "main_areas": main_areas,
            "bts_count": bts_count,
            "dominant_bts": dominant_bts,
            "overnights_summary": overnights_summary,
        },
        # Location dash-lists for programmatic insertion
        "_location_areas_list": location_areas_list,
        "_location_movement_list": location_movement_list,

        # Assessment (section 8)
        "assessment": {
            "main_characteristics": assessment_main,
            "working_assessment": assessment_working,
        },

        # Conclusions (section 9)
        "conclusions": {
            "point_1": conclusions[0] if len(conclusions) > 0 else "",
            "point_2": conclusions[1] if len(conclusions) > 1 else "",
            "point_3": conclusions[2] if len(conclusions) > 2 else "",
            "point_4": conclusions[3] if len(conclusions) > 3 else "",
        },
    }

    return placeholders


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _list_unique(devices: list, key: str) -> str:
    """Extract unique non-empty values of key from device list."""
    vals = list(dict.fromkeys(d.get(key, "") for d in devices if d.get(key)))
    return ", ".join(vals) if vals else ""


def _fmt_duration(seconds: float) -> str:
    s = int(seconds)
    if s < 60:
        return f"{s} s"
    m, sec = divmod(s, 60)
    if m < 60:
        return f"{m} min {sec} s" if sec else f"{m} min"
    h, m = divmod(m, 60)
    return f"{h} h {m} min {sec} s"


def _build_contacts_assessment(top_contacts: list, unique_contacts: int) -> str:
    """Build a short textual assessment of contact patterns."""
    n = unique_contacts or len(top_contacts)
    if not n:
        return "brak danych do oceny relacji kontaktowych"
    if n <= 5:
        return f"wąska grupa {n} kontaktów, co sugeruje ograniczoną sieć komunikacyjną"
    elif n <= 20:
        return f"umiarkowana sieć {n} kontaktów z wyraźnymi relacjami dominującymi"
    else:
        return f"rozbudowana sieć {n} kontaktów o zróżnicowanej intensywności"


def _categorize_anomalies(anomalies: list) -> List[str]:
    """Extract unique anomaly category names."""
    categories = []
    seen = set()
    for a in anomalies:
        cat = a.get("type", a.get("category", ""))
        if cat and cat not in seen:
            seen.add(cat)
            categories.append(cat)
    return categories


def _top_anomaly_findings(anomalies: list) -> str:
    """Build a summary of the most important anomaly findings."""
    if not anomalies:
        return "brak anomalii"

    # Take up to 3 most severe
    sorted_a = sorted(anomalies, key=lambda a: _severity_score(a.get("severity", "")), reverse=True)
    findings = []
    for a in sorted_a[:3]:
        desc = a.get("description", a.get("explain", a.get("label", str(a.get("type", "")))))
        if desc:
            if len(desc) > 120:
                desc = desc[:117] + "..."
            findings.append(desc)

    return "; ".join(findings) if findings else "brak danych"


def _severity_score(severity: str) -> int:
    s = (severity or "").lower()
    if "critical" in s or "wysok" in s or "high" in s:
        return 3
    if "warning" in s or "średni" in s or "medium" in s:
        return 2
    if "info" in s or "nisk" in s or "low" in s:
        return 1
    return 0


def _build_main_characteristics(
    total_records, calls_out, calls_in, sms_out, sms_in,
    data_sessions, anomalies, dual_detected, fwd_count=0
) -> str:
    """Build descriptive assessment string for section 8."""
    parts = []

    voice = calls_out + calls_in + fwd_count
    sms = sms_out + sms_in
    data = data_sessions

    if data > voice and data > sms:
        parts.append("dominacją transmisji danych nad komunikacją głosową i tekstową")
    elif voice > data and voice > sms:
        parts.append("przewagą komunikacji głosowej")
    elif sms > voice and sms > data:
        parts.append("przewagą komunikacji tekstowej (SMS)")
    else:
        parts.append("zrównoważonym rozkładem typów komunikacji")

    if dual_detected:
        parts.append("konfiguracją urządzeniową typu dual-IMEI")

    if fwd_count > 0:
        parts.append(f"obecnością przekierowań połączeń ({fwd_count})")

    if anomalies:
        n = len(set(a.get("type", "") for a in anomalies))
        parts.append(f"występowaniem {n} kategorii anomalii")

    return ", ".join(parts)


def _build_anomaly_table_rows(anomalies: list) -> List[List[str]]:
    """Build anomaly table rows with Kategoria / Opis / Dane columns.

    The 'Dane' column lists actual items from the billing data.
    If an anomaly has no items, 'Dane' says 'Nie występuje'.
    """
    if not anomalies:
        return []

    rows = []
    for a in anomalies:
        label = a.get("label", a.get("type", "?"))
        desc = a.get("description", a.get("explain", ""))
        if len(desc) > 120:
            desc = desc[:117] + "..."

        items = a.get("items", [])
        if not items:
            dane = "Nie występuje"
        else:
            dane = _format_anomaly_items(a.get("type", ""), items)

        rows.append([label, desc, dane])

    return rows


def _format_anomaly_items(anomaly_type: str, items: list) -> str:
    """Format anomaly items into a readable string for the 'Dane' column."""
    parts = []
    for item in items[:8]:  # Limit to 8 items
        if anomaly_type in ("long_call", "late_night_calls"):
            contact = item.get("contact", "?")
            date = item.get("date", "")
            time = item.get("time", "")
            dur = item.get("duration_min", 0)
            direction = item.get("direction", "")
            dir_str = f" ({direction})" if direction else ""
            parts.append(f"{date} {time} → {contact}, {dur} min{dir_str}")

        elif anomaly_type in ("high_night_activity", "night_activity"):
            # Period-based: show stats
            period = item.get("period", item.get("week", ""))
            records = item.get("records", item.get("count", 0))
            parts.append(f"{period}: {records} rek.")

        elif anomaly_type in ("night_movement", "night_travel"):
            date = item.get("date", "")
            loc_from = item.get("location_from", item.get("location_evening", "?"))
            loc_to = item.get("location_to", item.get("location_morning", "?"))
            parts.append(f"{date}: {loc_from} → {loc_to}")

        elif anomaly_type in ("activity_spike", "burst_activity"):
            date = item.get("date", "")
            count = item.get("count", item.get("records", 0))
            parts.append(f"{date}: {count} zdarzenia")

        elif anomaly_type in ("premium_number", "premium_numbers", "special_numbers"):
            number = item.get("number", "?")
            cat = item.get("category", item.get("label", ""))
            interactions = item.get("interactions", item.get("count", 0))
            parts.append(f"{number} ({cat}) — {interactions} interakcji")

        elif anomaly_type in ("roaming", "foreign_roaming"):
            country = item.get("country", "?")
            count = item.get("count", 0)
            period = item.get("period", "")
            parts.append(f"{country}: {count} rek. ({period})")

        elif anomaly_type == "foreign_contacts":
            country = item.get("country", "?")
            count = item.get("count", 0)
            numbers = item.get("numbers", [])
            nums_str = ", ".join(numbers[:3])
            parts.append(f"{country}: {count} int. [{nums_str}]")

        elif anomaly_type == "forwarded_calls":
            date = item.get("date", "")
            contact = item.get("contact", "?")
            fwd_to = item.get("forwarded_to", "?")
            parts.append(f"{date}: {contact} → {fwd_to}")

        elif anomaly_type == "one_time_contacts":
            number = item.get("number", item.get("contact", "?"))
            date = item.get("date", "")
            parts.append(f"{number} ({date})")

        elif anomaly_type == "inactivity_gap":
            last_date = item.get("last_date", item.get("last_record_date", ""))
            last_time = item.get("last_time", "")
            first_date = item.get("first_date", item.get("first_record_date", ""))
            first_time = item.get("first_time", "")
            gap_h = item.get("gap_hours", 0)
            last_str = f"{last_date} {last_time}".strip()
            first_str = f"{first_date} {first_time}".strip()
            parts.append(f"{last_str} \u2013 {first_str}: {gap_h:.0f} h przerwy")

        elif anomaly_type in ("satellite_numbers", "social_media", "social_messaging"):
            number = item.get("number", "?")
            label = item.get("label", item.get("category", ""))
            interactions = item.get("interactions", item.get("count", 0))
            parts.append(f"{number} ({label}) — {interactions}")

        else:
            # Generic fallback
            contact = item.get("contact", item.get("number", ""))
            date = item.get("date", "")
            count = item.get("count", item.get("interactions", ""))
            desc_parts = [p for p in [date, contact, str(count) if count else ""] if p]
            parts.append(", ".join(desc_parts) if desc_parts else str(item)[:60])

    result = "; ".join(parts)
    if len(items) > 8:
        result += f" (+ {len(items) - 8} więcej)"
    return result if result else "Nie występuje"


def _build_location_areas_list(locations: list) -> List[str]:
    """Build dash-list of main BTS areas for section 7."""
    if not locations:
        return ["brak danych lokalizacyjnych"]
    result = []
    for loc in locations[:10]:
        name = loc.get("location", loc.get("address", "?"))
        count = loc.get("record_count", 0)
        first = loc.get("first_seen", "")
        last = loc.get("last_seen", "")
        period_str = f", {first} – {last}" if first and last else ""
        result.append(f"{name} ({count} rekordów{period_str})")
    return result


def _build_location_movement_list(
    overnight_stays: list,
    home_location: str,
    night_activity: dict,
    locations: list,
) -> List[str]:
    """Build dash-list of movement/overnight info for section 7."""
    result = []

    if home_location:
        result.append(f"Dominujące miejsce noclegowe: {home_location}")

    if overnight_stays:
        for stay in overnight_stays[:5]:
            locs = stay.get("locations", [])
            nights = stay.get("nights", 0)
            start = stay.get("start_date", "")
            end = stay.get("end_date", "")
            locs_str = ", ".join(locs[:3])
            result.append(f"{start} – {end}: {nights} nocleg(ów) — {locs_str}")
    else:
        result.append("Nie odnotowano noclegów poza dominującym miejscem pobytu")

    # Night movement from night_activity
    na_records = night_activity.get("total_records", 0)
    na_pct = night_activity.get("percentage", 0)
    if na_records > 0:
        na_calls = night_activity.get("calls", 0)
        na_sms = night_activity.get("sms", 0)
        na_data = night_activity.get("data", 0)
        result.append(
            f"Aktywność nocna (22:00–06:00): {na_records} rekordów ({na_pct:.1f}%) "
            f"— połączenia: {na_calls}, SMS: {na_sms}, dane: {na_data}"
        )

    return result if result else ["brak danych o przemieszczaniu"]


def _build_conclusions(
    msisdn, period_from, period_to, total_records, imei_count,
    dual_detected, anomaly_categories_count, unique_contacts,
    top_contacts, main_areas
) -> List[str]:
    """Build 4 conclusion points for section 9."""
    conclusions = []

    conclusions.append(
        f"Analizowany numer {msisdn} był aktywny w okresie {period_from} – {period_to} "
        f"i wygenerował {total_records} rekordów telekomunikacyjnych."
    )

    if dual_detected:
        dev_info = "konfigurację dual-IMEI"
    elif imei_count > 1:
        dev_info = f"{imei_count} identyfikatory IMEI"
    else:
        dev_info = "1 identyfikator IMEI (brak zmian urządzenia)"
    conclusions.append(f"W materiale ujawniono {dev_info}.")

    top_short = ""
    if top_contacts:
        top_short = " Relacje dominujące: " + ", ".join(
            c.get("number", "?") for c in top_contacts[:3]
        ) + "."
    conclusions.append(
        f"Stwierdzono {anomaly_categories_count} kategorii anomalii wymagających odnotowania. "
        f"Wyodrębniono {unique_contacts} unikalnych kontaktów.{top_short}"
    )

    conclusions.append(
        f"Aktywność lokalizacyjna koncentrowała się w rejonach: {main_areas}. "
        f"Dalsza interpretacja materiału wymaga konfrontacji z dodatkowymi źródłami danych."
    )

    return conclusions
