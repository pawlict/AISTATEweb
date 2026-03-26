"""
GSM Report Section Registry — Single Source of Truth.

Every section available for GSM reports is defined here.
Adding/removing sections here automatically updates:
- Frontend content selection dialog
- DOCX report builder
- HTML report builder
- TXT report builder
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List
from collections import OrderedDict


@dataclass(frozen=True)
class SectionDef:
    """Definition of a single report section."""
    key: str            # Unique key, e.g. "subscriber"
    label: str          # Human-readable label for UI
    group: str          # Group name for UI grouping
    data_path: str      # Dot-separated path in billing data JSON
    order: int          # Sort order in report
    supports_chart: bool = False  # Whether this section has chart/visual (HTML only)

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "label": self.label,
            "group": self.group,
            "data_path": self.data_path,
            "order": self.order,
            "supports_chart": self.supports_chart,
        }


# ─── GSM Section Registry ────────────────────────────────────────────────────

GSM_SECTIONS: Dict[str, SectionDef] = OrderedDict([
    ("subscriber", SectionDef(
        "subscriber", "Dane abonenta", "Informacje podstawowe",
        "billing.subscriber", 10,
    )),
    ("period", SectionDef(
        "period", "Okres bilingu", "Informacje podstawowe",
        "billing.summary", 11,
    )),
    ("summary", SectionDef(
        "summary", "Podsumowanie statystyczne", "Podsumowanie",
        "billing.summary", 20,
    )),
    ("devices", SectionDef(
        "devices", "Urządzenia (IMEI/IMSI)", "Urządzenia",
        "billing.analysis.devices", 30,
    )),
    ("dual_imei", SectionDef(
        "dual_imei", "Dual-IMEI", "Urządzenia",
        "billing.analysis.dual_imei", 31,
    )),
    ("imei_changes", SectionDef(
        "imei_changes", "Zmiany IMEI", "Urządzenia",
        "billing.analysis.imei_changes", 32,
    )),
    ("anomalies", SectionDef(
        "anomalies", "Anomalie", "Anomalie",
        "billing.analysis.anomalies", 40,
    )),
    ("top_contacts", SectionDef(
        "top_contacts", "Top kontakty", "Kontakty",
        "billing.analysis.top_contacts", 50,
    )),
    ("special_numbers", SectionDef(
        "special_numbers", "Numery specjalne", "Numery specjalne",
        "billing.analysis.special_numbers", 60,
    )),
    ("temporal", SectionDef(
        "temporal", "Rozkład godzinowy", "Aktywność czasowa",
        "billing.analysis.temporal", 70, supports_chart=True,
    )),
    ("night_activity", SectionDef(
        "night_activity", "Aktywność nocna", "Aktywność czasowa",
        "billing.analysis.night_activity", 71,
    )),
    ("weekend_activity", SectionDef(
        "weekend_activity", "Aktywność weekendowa", "Aktywność czasowa",
        "billing.analysis.weekend_activity", 72,
    )),
    ("geolocation", SectionDef(
        "geolocation", "Geolokalizacja", "Geolokalizacja",
        "geolocation", 80, supports_chart=True,
    )),
    ("locations", SectionDef(
        "locations", "Lokalizacje BTS", "Geolokalizacja",
        "billing.analysis.locations", 81,
    )),
    ("overnight_stays", SectionDef(
        "overnight_stays", "Noclegi poza domem", "Noclegi",
        "billing.analysis.overnight_stays", 90,
    )),
    ("records", SectionDef(
        "records", "Rekordy", "Rekordy",
        "billing.records", 100,
    )),
    ("llm_narrative", SectionDef(
        "llm_narrative", "Analiza narracyjna (LLM)", "Analiza LLM",
        "llm_narrative", 110,
    )),
    ("warnings", SectionDef(
        "warnings", "Ostrzeżenia parsera", "Ostrzeżenia",
        "billing.warnings", 120,
    )),
])


# ─── Placeholder (Content Control) definitions ───────────────────────────────

@dataclass(frozen=True)
class PlaceholderDef:
    """Definition of an editable placeholder field in DOCX."""
    key: str            # SDT tag name, e.g. "INSTYTUCJA"
    label: str          # Human-readable label for UI
    field_type: str     # "text" | "richtext" | "date"
    default: str        # Default value (empty string = user fills in)

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "label": self.label,
            "type": self.field_type,
            "default": self.default,
        }


GSM_PLACEHOLDERS: List[PlaceholderDef] = [
    PlaceholderDef("INSTYTUCJA", "Nazwa instytucji", "richtext", ""),
    PlaceholderDef("ADRES_INSTYTUCJI", "Adres instytucji", "richtext", ""),
    PlaceholderDef("SYGNATURA", "Nr sprawy / sygnatury", "text", ""),
    PlaceholderDef("DATA_RAPORTU", "Data sporządzenia", "date", ""),
    PlaceholderDef("ANALITYK", "Analityk", "text", ""),
    PlaceholderDef("PODPIS", "Podpis", "richtext", ""),
    PlaceholderDef("STOPKA", "Stopka dokumentu", "richtext", "Wygenerowano w AISTATEweb"),
]


# ─── Helpers ──────────────────────────────────────────────────────────────────

def get_sections_grouped() -> Dict[str, List[SectionDef]]:
    """Return sections grouped by group name, sorted by order."""
    groups: Dict[str, List[SectionDef]] = OrderedDict()
    for sec in sorted(GSM_SECTIONS.values(), key=lambda s: s.order):
        groups.setdefault(sec.group, []).append(sec)
    return groups


def get_section_keys() -> List[str]:
    """Return list of section keys in order."""
    return [s.key for s in sorted(GSM_SECTIONS.values(), key=lambda s: s.order)]


def get_sections_for_api() -> dict:
    """Return sections + placeholders formatted for the frontend API."""
    grouped = get_sections_grouped()
    groups_list = []
    for group_name, sections in grouped.items():
        groups_list.append({
            "name": group_name,
            "sections": [{"key": s.key, "label": s.label, "checked": True} for s in sections],
        })
    return {
        "groups": groups_list,
        "placeholders": [p.to_dict() for p in GSM_PLACEHOLDERS],
    }


def resolve_data_path(data: dict, path: str):
    """Resolve a dot-separated path in nested dict. Returns None if not found."""
    parts = path.split(".")
    current = data
    for part in parts:
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return None
        if current is None:
            return None
    return current
