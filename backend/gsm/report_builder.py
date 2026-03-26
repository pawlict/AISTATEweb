"""
GSM Report Builder — transforms analysis data into a standardised report model.

Reads from gsm_latest.json, filters by selected sections,
and produces a format-agnostic report data structure consumed by
DOCX / HTML / TXT generators.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from backend.gsm.report_sections import GSM_SECTIONS, resolve_data_path


# ─── Public API ───────────────────────────────────────────────────────────────

def build_report_data(
    gsm_data: dict,
    selected_sections: List[str],
    llm_narrative: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a standardised report data model from GSM analysis data.

    Args:
        gsm_data: Full gsm_latest.json content (has "billing", "identification", etc.)
        selected_sections: List of section keys chosen by user.
        llm_narrative: Optional LLM-generated narrative text.

    Returns:
        {
            "title": str,
            "generated_at": str,
            "subscriber_label": str,
            "sections": [
                {
                    "key": str,
                    "title": str,
                    "group": str,
                    "content_md": str,      # Markdown text for DOCX/TXT
                    "tables": [...],         # Structured table data
                    "data": {...},           # Raw data for HTML interactive
                },
                ...
            ]
        }
    """
    billing = gsm_data.get("billing", {})
    subscriber = billing.get("subscriber", {})

    msisdn = subscriber.get("msisdn", "N/A")
    operator = subscriber.get("operator_name") or billing.get("operator", "N/A")
    subscriber_label = f"{msisdn} ({operator})"

    # Inject llm_narrative into data tree for resolve_data_path
    if llm_narrative:
        gsm_data["llm_narrative"] = llm_narrative

    sections_out: List[Dict[str, Any]] = []

    for sec_key in selected_sections:
        sec_def = GSM_SECTIONS.get(sec_key)
        if sec_def is None:
            continue

        # Get raw data from data tree
        raw_data = resolve_data_path(gsm_data, sec_def.data_path)

        # Get renderer
        renderer = _RENDERERS.get(sec_key)
        if renderer is None:
            continue

        try:
            section_result = renderer(gsm_data, raw_data)
        except Exception:
            section_result = {
                "content_md": f"*Błąd renderowania sekcji {sec_def.label}*",
                "tables": [],
                "data": raw_data,
            }

        sections_out.append({
            "key": sec_key,
            "title": sec_def.label,
            "group": sec_def.group,
            "content_md": section_result.get("content_md", ""),
            "tables": section_result.get("tables", []),
            "data": section_result.get("data", raw_data),
        })

    return {
        "title": "Raport z analizy bilingu GSM",
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "subscriber_label": subscriber_label,
        "sections": sections_out,
    }


# ─── Section renderers ───────────────────────────────────────────────────────
# Each renderer receives (full_data, section_raw_data) and returns
# {"content_md": str, "tables": list, "data": any}

def _render_subscriber(full_data: dict, raw: Any) -> dict:
    if not raw or not isinstance(raw, dict):
        return {"content_md": "*Brak danych abonenta.*", "tables": [], "data": raw}

    lines = []
    if raw.get("msisdn"):
        lines.append(f"**MSISDN:** {raw['msisdn']}")
    if raw.get("imsi"):
        lines.append(f"**IMSI:** {raw['imsi']}")
    if raw.get("imei"):
        lines.append(f"**IMEI:** {raw['imei']}")
    if raw.get("operator_name"):
        lines.append(f"**Operator:** {raw['operator_name']}")
    if raw.get("name"):
        lines.append(f"**Nazwa:** {raw['name']}")
    if raw.get("address"):
        lines.append(f"**Adres:** {raw['address']}")

    return {"content_md": "\n".join(lines) if lines else "*Brak danych.*", "tables": [], "data": raw}


def _render_period(full_data: dict, raw: Any) -> dict:
    if not raw or not isinstance(raw, dict):
        return {"content_md": "*Brak danych okresu.*", "tables": [], "data": raw}

    period = raw.get("period", {})
    start = period.get("start", "N/A")
    end = period.get("end", "N/A")
    days = period.get("days", "N/A")

    md = f"**Okres bilingu:** {start} — {end} ({days} dni)"
    return {"content_md": md, "tables": [], "data": raw}


def _render_summary(full_data: dict, raw: Any) -> dict:
    if not raw or not isinstance(raw, dict):
        return {"content_md": "*Brak danych podsumowania.*", "tables": [], "data": raw}

    billing = full_data.get("billing", {})
    analysis = billing.get("analysis", {})

    lines = []
    rc = billing.get("record_count", 0)
    lines.append(f"**Liczba rekordów:** {rc}")

    by_type = raw.get("by_type", {})
    if by_type:
        table_rows = []
        for rtype, count in sorted(by_type.items()):
            table_rows.append({"Typ": rtype, "Liczba": count})
        lines.append("")
        lines.append(_md_table(["Typ", "Liczba"], table_rows))

    # Call duration stats from analysis
    avg_dur = analysis.get("avg_call_duration", 0)
    median_dur = analysis.get("median_call_duration", 0)
    longest = analysis.get("longest_call_seconds", 0)
    longest_contact = analysis.get("longest_call_contact", "")

    if avg_dur:
        lines.append(f"\n**Średni czas połączenia:** {_fmt_duration(avg_dur)}")
    if median_dur:
        lines.append(f"**Mediana czasu połączenia:** {_fmt_duration(median_dur)}")
    if longest:
        extra = f" (z {longest_contact})" if longest_contact else ""
        lines.append(f"**Najdłuższe połączenie:** {_fmt_duration(longest)}{extra}")

    busiest = analysis.get("busiest_date", "")
    busiest_count = analysis.get("busiest_date_count", 0)
    if busiest:
        lines.append(f"**Najbardziej aktywny dzień:** {busiest} ({busiest_count} zdarzeń)")

    tables = []
    if by_type:
        tables.append({
            "title": "Rozkład typów zdarzeń",
            "headers": ["Typ", "Liczba"],
            "rows": [[rtype, count] for rtype, count in sorted(by_type.items())],
        })

    return {"content_md": "\n".join(lines), "tables": tables, "data": raw}


def _render_devices(full_data: dict, raw: Any) -> dict:
    if not raw or not isinstance(raw, list):
        return {"content_md": "*Brak danych urządzeń.*", "tables": [], "data": raw}

    headers = ["IMEI", "Marka / Model", "Rekordy", "Pierwszy", "Ostatni"]
    rows = []
    for dev in raw:
        name = dev.get("display_name") or f"{dev.get('brand', '?')} {dev.get('model', '?')}"
        rows.append([
            dev.get("imei", "N/A"),
            name,
            dev.get("record_count", 0),
            dev.get("first_seen", ""),
            dev.get("last_seen", ""),
        ])

    md = _md_table(headers, [{h: r for h, r in zip(headers, row)} for row in rows])
    tables = [{"title": "Urządzenia", "headers": headers, "rows": rows}]
    return {"content_md": md, "tables": tables, "data": raw}


def _render_dual_imei(full_data: dict, raw: Any) -> dict:
    if not raw:
        return {"content_md": "*Nie wykryto dual-IMEI.*", "tables": [], "data": raw}

    lines = [
        "**Wykryto urządzenie dual-modem (voice + data):**",
        f"- Voice IMEI: {raw.get('voice_imei', 'N/A')} ({raw.get('voice_records', 0)} rekordów)",
        f"- Data IMEI: {raw.get('data_imei', 'N/A')} ({raw.get('data_records', 0)} rekordów)",
    ]
    if raw.get("same_tac"):
        lines.append("- TAC obu IMEI jest identyczny (to samo urządzenie)")

    return {"content_md": "\n".join(lines), "tables": [], "data": raw}


def _render_imei_changes(full_data: dict, raw: Any) -> dict:
    if not raw or not isinstance(raw, list) or len(raw) == 0:
        return {"content_md": "*Brak zmian IMEI.*", "tables": [], "data": raw}

    headers = ["Data", "Stary IMEI", "Nowy IMEI", "Grupa"]
    rows = []
    for ch in raw:
        rows.append([
            ch.get("date", ""),
            ch.get("old_imei", ""),
            ch.get("new_imei", ""),
            ch.get("group", ""),
        ])

    md = f"**Wykryto {len(raw)} zmian IMEI:**\n\n"
    md += _md_table(headers, [{h: r for h, r in zip(headers, row)} for row in rows])
    tables = [{"title": "Zmiany IMEI", "headers": headers, "rows": rows}]
    return {"content_md": md, "tables": tables, "data": raw}


def _render_anomalies(full_data: dict, raw: Any) -> dict:
    if not raw or not isinstance(raw, list) or len(raw) == 0:
        return {"content_md": "*Nie wykryto anomalii.*", "tables": [], "data": raw}

    lines = [f"**Wykryto {len(raw)} anomalii:**\n"]
    for i, a in enumerate(raw, 1):
        atype = a.get("type", "unknown")
        desc = a.get("description", a.get("explain", str(a)))
        severity = a.get("severity", "")
        sev_str = f" [{severity}]" if severity else ""
        lines.append(f"{i}. **{atype}**{sev_str}: {desc}")

    return {"content_md": "\n".join(lines), "tables": [], "data": raw}


def _render_top_contacts(full_data: dict, raw: Any) -> dict:
    if not raw or not isinstance(raw, list) or len(raw) == 0:
        return {"content_md": "*Brak danych kontaktów.*", "tables": [], "data": raw}

    headers = ["Nr", "Numer", "Interakcje", "Wychodzące", "Przychodzące", "SMS wych.", "SMS przych.", "Czas (s)", "Aktywne dni"]
    rows = []
    for i, c in enumerate(raw[:20], 1):
        rows.append([
            i,
            c.get("number", "N/A"),
            c.get("total_interactions", 0),
            c.get("calls_out", 0),
            c.get("calls_in", 0),
            c.get("sms_out", 0),
            c.get("sms_in", 0),
            c.get("total_duration_seconds", 0),
            c.get("active_days", 0),
        ])

    md = f"**Top {len(rows)} kontaktów:**\n\n"
    md += _md_table(headers, [{h: r for h, r in zip(headers, row)} for row in rows])
    tables = [{"title": "Top kontakty", "headers": headers, "rows": rows}]
    return {"content_md": md, "tables": tables, "data": raw}


def _render_special_numbers(full_data: dict, raw: Any) -> dict:
    if not raw or not isinstance(raw, list) or len(raw) == 0:
        return {"content_md": "*Brak numerów specjalnych.*", "tables": [], "data": raw}

    headers = ["Numer", "Typ", "Opis", "Liczba"]
    rows = []
    for sn in raw:
        rows.append([
            sn.get("number", "N/A"),
            sn.get("type", ""),
            sn.get("description", sn.get("label", "")),
            sn.get("count", 0),
        ])

    md = _md_table(headers, [{h: r for h, r in zip(headers, row)} for row in rows])
    tables = [{"title": "Numery specjalne", "headers": headers, "rows": rows}]
    return {"content_md": md, "tables": tables, "data": raw}


def _render_temporal(full_data: dict, raw: Any) -> dict:
    if not raw or not isinstance(raw, dict):
        return {"content_md": "*Brak danych aktywności czasowej.*", "tables": [], "data": raw}

    lines = []
    peak_hour = raw.get("peak_hour")
    peak_day = raw.get("peak_day")
    if peak_hour is not None:
        lines.append(f"**Szczytowa godzina:** {peak_hour}:00")
    if peak_day:
        lines.append(f"**Szczytowy dzień tygodnia:** {peak_day}")

    night_ratio = raw.get("night_activity_ratio", 0)
    if night_ratio:
        lines.append(f"**Udział aktywności nocnej:** {night_ratio:.1%}")

    hourly = raw.get("hourly_distribution", {})
    if hourly:
        headers = ["Godzina", "Liczba zdarzeń"]
        rows = [[f"{h}:00", count] for h, count in sorted(hourly.items(), key=lambda x: int(x[0]))]
        lines.append("\n**Rozkład godzinowy:**\n")
        lines.append(_md_table(headers, [{h_: r for h_, r in zip(headers, row)} for row in rows]))

    return {"content_md": "\n".join(lines), "tables": [], "data": raw}


def _render_night_activity(full_data: dict, raw: Any) -> dict:
    if not raw or not isinstance(raw, dict):
        return {"content_md": "*Brak danych aktywności nocnej.*", "tables": [], "data": raw}

    total = raw.get("total_events", 0)
    lines = [f"**Zdarzenia nocne (22:00–6:00):** {total}"]

    by_type = raw.get("by_type", {})
    if by_type:
        for t, cnt in sorted(by_type.items()):
            lines.append(f"- {t}: {cnt}")

    return {"content_md": "\n".join(lines), "tables": [], "data": raw}


def _render_weekend_activity(full_data: dict, raw: Any) -> dict:
    if not raw or not isinstance(raw, dict):
        return {"content_md": "*Brak danych aktywności weekendowej.*", "tables": [], "data": raw}

    total = raw.get("total_events", 0)
    lines = [f"**Zdarzenia weekendowe:** {total}"]

    by_type = raw.get("by_type", {})
    if by_type:
        for t, cnt in sorted(by_type.items()):
            lines.append(f"- {t}: {cnt}")

    return {"content_md": "\n".join(lines), "tables": [], "data": raw}


def _render_geolocation(full_data: dict, raw: Any) -> dict:
    if not raw:
        return {"content_md": "*Brak danych geolokalizacji.*", "tables": [], "data": raw}

    lines = ["**Dane geolokalizacyjne dostępne.**"]

    if isinstance(raw, dict):
        total = raw.get("total_locations", raw.get("total_bts", 0))
        if total:
            lines.append(f"Łączna liczba lokalizacji: {total}")
        clusters = raw.get("clusters")
        if clusters and isinstance(clusters, list):
            lines.append(f"Wykryte klastry: {len(clusters)}")

    return {"content_md": "\n".join(lines), "tables": [], "data": raw}


def _render_locations(full_data: dict, raw: Any) -> dict:
    if not raw or not isinstance(raw, list) or len(raw) == 0:
        return {"content_md": "*Brak danych lokalizacji BTS.*", "tables": [], "data": raw}

    headers = ["Lokalizacja", "LAC", "Cell ID", "Rekordy", "Pierwszy", "Ostatni"]
    rows = []
    for loc in raw[:30]:  # Limit to 30
        rows.append([
            loc.get("location", "N/A"),
            loc.get("lac", ""),
            loc.get("cell_id", ""),
            loc.get("record_count", 0),
            loc.get("first_seen", ""),
            loc.get("last_seen", ""),
        ])

    md = f"**Lokalizacje BTS ({len(raw)} łącznie, wyświetlono {len(rows)}):**\n\n"
    md += _md_table(headers, [{h: r for h, r in zip(headers, row)} for row in rows])
    tables = [{"title": "Lokalizacje BTS", "headers": headers, "rows": rows}]
    return {"content_md": md, "tables": tables, "data": raw}


def _render_overnight_stays(full_data: dict, raw: Any) -> dict:
    if not raw or not isinstance(raw, list) or len(raw) == 0:
        analysis = full_data.get("billing", {}).get("analysis", {})
        home = analysis.get("overnight_stays_home", "")
        md = "*Nie wykryto noclegów poza domem.*"
        if home:
            md += f"\n\n**Domowa lokalizacja:** {home}"
        return {"content_md": md, "tables": [], "data": raw}

    analysis = full_data.get("billing", {}).get("analysis", {})
    home = analysis.get("overnight_stays_home", "")

    lines = []
    if home:
        lines.append(f"**Domowa lokalizacja:** {home}")
    lines.append(f"**Wykryto {len(raw)} noclegów poza domem:**\n")

    for i, stay in enumerate(raw, 1):
        start = stay.get("start_date", "?")
        end = stay.get("end_date", "?")
        nights = stay.get("nights", 1)
        locs = stay.get("locations", [])
        loc_str = ", ".join(locs) if locs else "N/A"
        lines.append(f"{i}. {start} — {end} ({nights} nocy) → {loc_str}")

    return {"content_md": "\n".join(lines), "tables": [], "data": raw}


def _render_records(full_data: dict, raw: Any) -> dict:
    if not raw or not isinstance(raw, list) or len(raw) == 0:
        return {"content_md": "*Brak rekordów.*", "tables": [], "data": raw}

    total = len(raw)
    limit = min(total, 100)  # Limit for report

    headers = ["Data/czas", "Typ", "Numer B", "Czas (s)", "Lokalizacja"]
    rows = []
    for rec in raw[:limit]:
        dt = rec.get("datetime", rec.get("date", ""))
        rtype = rec.get("record_type", "")
        callee = rec.get("callee", rec.get("caller", ""))
        dur = rec.get("duration_seconds", "")
        loc = rec.get("location", "")
        rows.append([dt, rtype, callee, dur, loc])

    md = f"**Rekordy ({total} łącznie, wyświetlono {limit}):**\n\n"
    md += _md_table(headers, [{h: r for h, r in zip(headers, row)} for row in rows])

    tables = [{"title": "Rekordy bilingu", "headers": headers, "rows": rows}]
    return {"content_md": md, "tables": tables, "data": {"total": total, "shown": limit}}


def _render_llm_narrative(full_data: dict, raw: Any) -> dict:
    if not raw or not isinstance(raw, str) or not raw.strip():
        return {"content_md": "*Analiza narracyjna nie została wygenerowana.*", "tables": [], "data": raw}

    return {"content_md": raw, "tables": [], "data": raw}


def _render_warnings(full_data: dict, raw: Any) -> dict:
    if not raw or not isinstance(raw, list) or len(raw) == 0:
        return {"content_md": "*Brak ostrzeżeń parsera.*", "tables": [], "data": raw}

    lines = [f"**Ostrzeżenia parsera ({len(raw)}):**\n"]
    for i, w in enumerate(raw, 1):
        lines.append(f"{i}. {w}")

    return {"content_md": "\n".join(lines), "tables": [], "data": raw}


# ─── Renderer registry ───────────────────────────────────────────────────────

_RENDERERS = {
    "subscriber": _render_subscriber,
    "period": _render_period,
    "summary": _render_summary,
    "devices": _render_devices,
    "dual_imei": _render_dual_imei,
    "imei_changes": _render_imei_changes,
    "anomalies": _render_anomalies,
    "top_contacts": _render_top_contacts,
    "special_numbers": _render_special_numbers,
    "temporal": _render_temporal,
    "night_activity": _render_night_activity,
    "weekend_activity": _render_weekend_activity,
    "geolocation": _render_geolocation,
    "locations": _render_locations,
    "overnight_stays": _render_overnight_stays,
    "records": _render_records,
    "llm_narrative": _render_llm_narrative,
    "warnings": _render_warnings,
}


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _fmt_duration(seconds: float) -> str:
    """Format seconds as human-readable duration."""
    s = int(seconds)
    if s < 60:
        return f"{s} s"
    m, s = divmod(s, 60)
    if m < 60:
        return f"{m} min {s} s"
    h, m = divmod(m, 60)
    return f"{h} h {m} min {s} s"


def _md_table(headers: list, rows: list) -> str:
    """Build a markdown table from headers and list of dicts."""
    if not rows:
        return ""
    lines = []
    lines.append("| " + " | ".join(str(h) for h in headers) + " |")
    lines.append("| " + " | ".join("---" for _ in headers) + " |")
    for row in rows:
        if isinstance(row, dict):
            cells = [str(row.get(h, "")) for h in headers]
        elif isinstance(row, (list, tuple)):
            cells = [str(c) for c in row]
        else:
            cells = [str(row)]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)
