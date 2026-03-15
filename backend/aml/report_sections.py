"""
AML Report Section Registry — Single Source of Truth.

Every section available for AML reports is defined here.
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
    key: str            # Unique key, e.g. "statement_info"
    label: str          # Human-readable label for UI
    group: str          # Group name for UI grouping
    data_path: str      # Dot-separated path in AML result JSON
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


# ─── AML Section Registry ────────────────────────────────────────────────────

AML_SECTIONS: Dict[str, SectionDef] = OrderedDict([
    ("statement_info", SectionDef(
        "statement_info", "Dane wyciągu", "Dane wyciągu",
        "statement", 10,
    )),
    ("summary", SectionDef(
        "summary", "Podsumowanie", "Podsumowanie",
        "summary", 20,
    )),
    ("transactions", SectionDef(
        "transactions", "Transakcje", "Transakcje",
        "transactions", 30,
    )),
    ("risk_assessment", SectionDef(
        "risk_assessment", "Ocena ryzyka", "Ocena ryzyka",
        "risk", 40,
    )),
    ("alerts", SectionDef(
        "alerts", "Alerty", "Alerty",
        "alerts", 50,
    )),
    ("channels", SectionDef(
        "channels", "Kanały płatności", "Kanały płatności",
        "charts.channels", 60, supports_chart=True,
    )),
    ("categories", SectionDef(
        "categories", "Kategorie wydatków", "Kategorie wydatków",
        "charts.categories", 70, supports_chart=True,
    )),
    ("counterparties", SectionDef(
        "counterparties", "Kontrahenci", "Kontrahenci",
        "counterparties", 80,
    )),
    ("recurring_patterns", SectionDef(
        "recurring_patterns", "Wzorce cykliczne", "Wzorce cykliczne",
        "recurring", 90,
    )),
    ("llm_narrative", SectionDef(
        "llm_narrative", "Analiza narracyjna (LLM)", "Analiza LLM",
        "llm_narrative", 100,
    )),
    ("graph", SectionDef(
        "graph", "Grafy powiązań", "Grafy powiązań",
        "graph", 110, supports_chart=True,
    )),
    ("ml_anomalies", SectionDef(
        "ml_anomalies", "Anomalie ML", "Anomalie ML",
        "ml_anomalies", 115,
    )),
    ("audit", SectionDef(
        "audit", "Audyt / metadane", "Audyt",
        "audit", 120,
    )),
    ("warnings", SectionDef(
        "warnings", "Ostrzeżenia", "Ostrzeżenia",
        "warnings", 130,
    )),
])


# ─── Placeholder (Content Control) definitions ───────────────────────────────

@dataclass(frozen=True)
class PlaceholderDef:
    """Definition of an editable placeholder field in DOCX."""
    key: str            # SDT tag name
    label: str          # Human-readable label for UI
    field_type: str     # "text" | "richtext" | "date"
    default: str        # Default value

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "label": self.label,
            "type": self.field_type,
            "default": self.default,
        }


AML_PLACEHOLDERS: List[PlaceholderDef] = [
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
    for sec in sorted(AML_SECTIONS.values(), key=lambda s: s.order):
        groups.setdefault(sec.group, []).append(sec)
    return groups


def get_section_keys() -> List[str]:
    """Return list of section keys in order."""
    return [s.key for s in sorted(AML_SECTIONS.values(), key=lambda s: s.order)]


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
        "placeholders": [p.to_dict() for p in AML_PLACEHOLDERS],
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
