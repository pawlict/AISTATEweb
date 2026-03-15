"""
GSM Note Builder — maps AnalysisResult / gsm_latest.json data to the
placeholder dict expected by the professional DOCX note template.

Two variants:
  1) Variant "data"  — pure data, no LLM, template text stays as-is
  2) Variant "llm"   — LLM generates narrative sections (4-9)

This module handles variant 1 (data extraction).  For variant 2,
see note_llm.py which produces overrides for text-heavy placeholders.
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
    """Extract all 54 template placeholders from gsm_latest.json.

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
    period = summary.get("period", {})
    by_type = summary.get("by_type", {})

    # ── Basic subscriber / meta ──
    msisdn = subscriber.get("msisdn", "N/A")
    operator = subscriber.get("operator_name") or billing.get("operator", "N/A")
    imsi = subscriber.get("imsi", "")
    imsi_list = _list_unique(analysis.get("devices", []), "imsi") or imsi or "N/A"
    imsi_primary = imsi or imsi_list.split(",")[0].strip() if imsi_list else "N/A"

    # IMEI
    devices = analysis.get("devices", [])
    imei_list_items = [d.get("imei", "") for d in devices if d.get("imei")]
    imei_list = ", ".join(imei_list_items) if imei_list_items else subscriber.get("imei", "N/A")

    # Dual-IMEI
    dual_imei = analysis.get("dual_imei") or {}
    dual_detected = bool(dual_imei and dual_imei.get("detected", False))
    dual_imei_present = "TAK" if dual_detected else "NIE"
    if dual_detected:
        dual_imei_value = f"Voice: {dual_imei.get('voice_imei', '?')} / Data: {dual_imei.get('data_imei', '?')}"
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
    if imei_changes:
        device_notes_parts.append(f"Wykryto {len(imei_changes)} zmian IMEI w badanym okresie")
    device_identification_notes = ". ".join(device_notes_parts) if device_notes_parts else "Brak uwag"

    # ── Period ──
    period_from = period.get("start", "N/A")
    period_to = period.get("end", "N/A")

    # ── Statistics ──
    total_records = billing.get("record_count", 0)
    outgoing_calls = by_type.get("Połączenie wychodzące", by_type.get("outgoing_call", 0))
    incoming_calls = by_type.get("Połączenie przychodzące", by_type.get("incoming_call", 0))
    sms_out = by_type.get("SMS wychodzący", by_type.get("sms_out", 0))
    sms_in = by_type.get("SMS przychodzący", by_type.get("sms_in", 0))
    data_sessions = by_type.get("Transmisja danych", by_type.get("data", 0))

    # ── Source descriptions ──
    source_calls = f"{outgoing_calls + incoming_calls} rekordów połączeń głosowych" if (outgoing_calls + incoming_calls) else "brak danych o połączeniach"
    source_sms = f"{sms_out + sms_in} rekordów SMS/MMS" if (sms_out + sms_in) else "brak danych SMS"
    source_data = f"{data_sessions} sesji transmisji danych" if data_sessions else "brak danych transmisji"
    source_identifiers = f"{len(imei_list_items)} identyfikatorów IMEI" if imei_list_items else "dane identyfikacyjne"

    # Contacts
    top_contacts = analysis.get("top_contacts", [])
    unique_contacts = summary.get("unique_contacts", len(top_contacts))
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

    # Hourly pattern description
    peak_hour = temporal.get("peak_hour")
    hourly_pattern = f"szczytową aktywność w godzinie {peak_hour}:00" if peak_hour is not None else "brak danych o rozkładzie godzinowym"

    night_ratio = temporal.get("night_activity_ratio", 0)
    night_share = f"{night_ratio:.1%}" if night_ratio else "brak danych"

    weekend_total = weekend_activity.get("total_events", 0)
    all_total = total_records if total_records else 1
    weekend_share = f"{weekend_total / all_total:.1%}" if weekend_total else "brak danych"

    # ── Special numbers ──
    special_numbers = analysis.get("special_numbers", [])
    if special_numbers:
        sn_types = set(sn.get("type", "") for sn in special_numbers)
        special_numbers_summary = ", ".join(sorted(t for t in sn_types if t)) or "numery specjalne wykryte"
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

    contacts_assessment = _build_contacts_assessment(top_contacts)

    # ── Anomalies details ──
    anomaly_categories = _categorize_anomalies(anomalies)
    anomaly_count = str(len(anomaly_categories))
    anomaly_categories_str = ", ".join(anomaly_categories) if anomaly_categories else "brak"
    anomaly_top_findings = _top_anomaly_findings(anomalies)

    # ── Locations details ──
    if locations:
        main_areas = ", ".join(loc.get("location", "?") for loc in locations[:3])
        bts_count = str(len(locations))
        dominant_bts = locations[0].get("location", "?") if locations else "brak danych"
    else:
        main_areas = "brak danych lokalizacyjnych"
        bts_count = "0"
        dominant_bts = "brak danych"

    # Overnight stays
    overnight_stays = analysis.get("overnight_stays", [])
    if overnight_stays:
        overnights_summary = f"Wykryto {len(overnight_stays)} noclegów poza domem"
    else:
        overnights_summary = "nie wykryto noclegów poza domem"

    # ── Assessment (variant "data" — descriptive, non-interpretive) ──
    assessment_main = _build_main_characteristics(
        total_records, outgoing_calls, incoming_calls, sms_out, sms_in,
        data_sessions, anomalies, dual_detected
    )
    assessment_working = (
        "Dane bilingowe dostarczają informacji o aktywności telekomunikacyjnej, "
        "które mogą stanowić podstawę do dalszych ustaleń analitycznych"
    )

    # ── Conclusions (template variant — generic) ──
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
    if outgoing_calls + incoming_calls > 0:
        zrodla.append("połączenia głosowe")
    if sms_out + sms_in > 0:
        zrodla.append("SMS")
    if data_sessions > 0:
        zrodla.append("transmisja danych")
    if locations:
        zrodla.append("BTS")
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
        "imsi_list": imsi_list,
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

        # Stats
        "stats": {
            "outgoing_calls": str(outgoing_calls),
            "incoming_calls": str(incoming_calls),
            "sms_out": str(sms_out),
            "sms_in": str(sms_in),
            "data_sessions": str(data_sessions),
        },

        # Sources (section 2)
        "source": {
            "calls": source_calls,
            "sms": source_sms,
            "data": source_data,
            "identifiers": source_identifiers,
            "contacts": source_contacts,
            "locations": source_locations,
            "anomalies": source_anomalies,
        },

        # Activity (section 4)
        "activity": {
            "hourly_pattern": hourly_pattern,
            "night_share": night_share,
            "weekend_share": weekend_share,
        },
        "special_numbers_summary": special_numbers_summary,

        # Contacts (section 5)
        "contacts": {
            "unique_count": str(unique_contacts),
            "top_list": contacts_top_list,
            "assessment": contacts_assessment,
        },

        # Anomalies (section 6)
        "anomalies": {
            "count": anomaly_count,
            "categories": anomaly_categories_str,
            "top_findings": anomaly_top_findings,
        },

        # Locations (section 7)
        "locations": {
            "main_areas": main_areas,
            "bts_count": bts_count,
            "dominant_bts": dominant_bts,
            "overnights_summary": overnights_summary,
        },

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


def _build_contacts_assessment(top_contacts: list) -> str:
    """Build a short textual assessment of contact patterns."""
    if not top_contacts:
        return "brak danych do oceny relacji kontaktowych"

    n = len(top_contacts)
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
        desc = a.get("description", a.get("explain", str(a.get("type", ""))))
        if desc:
            # Trim to reasonable length
            if len(desc) > 120:
                desc = desc[:117] + "..."
            findings.append(desc)

    return "; ".join(findings) if findings else "brak danych"


def _severity_score(severity: str) -> int:
    s = (severity or "").lower()
    if "critical" in s or "wysok" in s:
        return 3
    if "warning" in s or "średni" in s:
        return 2
    if "info" in s or "nisk" in s:
        return 1
    return 0


def _build_main_characteristics(
    total_records, calls_out, calls_in, sms_out, sms_in,
    data_sessions, anomalies, dual_detected
) -> str:
    """Build descriptive assessment string for section 8."""
    parts = []

    # Communication profile
    voice = calls_out + calls_in
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

    if anomalies:
        n = len(set(a.get("type", "") for a in anomalies))
        parts.append(f"występowaniem {n} kategorii anomalii")

    return ", ".join(parts)


def _build_conclusions(
    msisdn, period_from, period_to, total_records, imei_count,
    dual_detected, anomaly_categories_count, unique_contacts,
    top_contacts, main_areas
) -> List[str]:
    """Build 4 conclusion points for section 9."""
    conclusions = []

    # Point 1: activity period
    conclusions.append(
        f"Analizowany numer {msisdn} był aktywny w okresie {period_from} – {period_to} "
        f"i wygenerował {total_records} rekordów telekomunikacyjnych."
    )

    # Point 2: devices
    if dual_detected:
        dev_info = "konfigurację dual-IMEI"
    elif imei_count > 1:
        dev_info = f"{imei_count} identyfikatory IMEI"
    else:
        dev_info = "1 identyfikator IMEI (brak zmian urządzenia)"
    conclusions.append(f"W materiale ujawniono {dev_info}.")

    # Point 3: anomalies + contacts
    conclusions.append(
        f"Stwierdzono {anomaly_categories_count} kategorii anomalii wymagających odnotowania. "
        f"Wyodrębniono {unique_contacts} unikalnych kontaktów."
    )

    # Point 4: locations + recommendation
    conclusions.append(
        f"Aktywność lokalizacyjna koncentrowała się w rejonach: {main_areas}. "
        f"Dalsza interpretacja materiału wymaga konfrontacji z dodatkowymi źródłami danych."
    )

    return conclusions
