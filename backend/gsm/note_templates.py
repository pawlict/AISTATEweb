"""
GSM Note Templates — per-user template storage and built-in template definition.

A template is an ordered list of *sections* (blocks), each being either:
  - type "text"   → editable static text (HTML paragraph)
  - type "marker" → non-editable placeholder for a programmatic element
                     (table, chart, bullet-list, footnotes, data placeholder)

Templates are stored as JSON in:
    data_www/users/{user_id}/gsm_note_templates.json

Each user may have up to MAX_TEMPLATES custom templates.  One may be flagged
as *default*; if none is, the built-in template is used for generation.
"""
from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger("aistate.gsm.note_tpl")

MAX_TEMPLATES = 5

# ── Marker catalogue ────────────────────────────────────────────────────────
# Every marker that can appear in a template.  The frontend shows these as
# non-editable chips/tags; the backend uses the key to decide what to insert.

MARKER_CATALOGUE: List[Dict[str, str]] = [
    {"key": "table_stats",       "type": "table",  "label": "📊 Tabela: Statystyki"},
    {"key": "table_contacts",    "type": "table",  "label": "📊 Tabela: Najczęstsze kontakty"},
    {"key": "table_anomalies",   "type": "table",  "label": "📊 Tabela: Wykryte anomalie"},
    {"key": "table_locations",   "type": "table",  "label": "📊 Tabela: Lokalizacje BTS"},
    {"key": "chart_top_contacts","type": "chart",  "label": "📈 Graf: Najczęstsze kontakty"},
    {"key": "chart_activity",    "type": "chart",  "label": "📈 Rozkład aktywności"},
    {"key": "chart_night",       "type": "chart",  "label": "📈 Aktywność nocna"},
    {"key": "chart_weekend",     "type": "chart",  "label": "📈 Aktywność weekendowa"},
    {"key": "chart_map_bts",     "type": "chart",  "label": "🗺️ Mapa lokalizacji BTS"},
    {"key": "list_locations",    "type": "list",   "label": "📋 Lista: Rejony BTS"},
    {"key": "list_movement",     "type": "list",   "label": "📋 Lista: Przemieszczenia"},
    {"key": "list_contacts",     "type": "list",   "label": "📋 Lista: Kontakty"},
    {"key": "footnotes_special", "type": "footnote","label": "📝 Przypisy: Numery specjalne"},
    {"key": "bts_summary",       "type": "data",   "label": "📌 Podsumowanie BTS"},
]

VALID_MARKER_KEYS = {m["key"] for m in MARKER_CATALOGUE}

# ── Built-in (default) template ────────────────────────────────────────────
# Matches the current hard-coded order in note_generator._post_process_docx().
# Text blocks use the same constants defined in note_generator.py so that a
# user who has never edited a template gets the exact same output as before.

_BUILTIN_SECTIONS: List[Dict[str, Any]] = [
    # ─── Section 1: Wstęp ───────────────────────────────────────────────────
    {
        "id": "b01", "type": "text", "section": 1, "para_idx": 5,
        "content": (
            "W ramach czynności analitycznych przeprowadzono analizę materiału "
            "telekomunikacyjnego dotyczącego numeru {{ msisdn }} funkcjonującego "
            "w\u00a0sieci {{ operator }}. Analiza obejmuje okres od {{ period_from }} "
            "do {{ period_to }} i\u00a0została oparta na danych pochodzących z\u00a0raportu "
            "HTML oraz materiałów źródłowych w\u00a0postaci rekordów ruchu "
            "telekomunikacyjnego, danych identyfikacyjnych urządzeń, zestawień "
            "kontaktów, informacji lokalizacyjnych BTS oraz wykrytych anomalii."
        ),
    },
    {
        "id": "b02", "type": "text", "section": 1, "para_idx": 6,
        "content": (
            "Celem notatki jest syntetyczne przedstawienie ustaleń wynikających "
            "z\u00a0analizy, z\u00a0rozdzieleniem informacji o\u00a0charakterze potwierdzonym "
            "od ocen i\u00a0hipotez operacyjnych. Wnioski sformułowano wyłącznie "
            "w\u00a0granicach informacji wynikających z\u00a0materiału źródłowego, "
            "z\u00a0uwzględnieniem ograniczeń interpretacyjnych typowych dla danych "
            "bilingowych jednego numeru."
        ),
    },

    # ─── Section 2: Zakres materiału i metodologia ──────────────────────────
    {
        "id": "b03", "type": "text", "section": 2, "para_idx": 8,
        "content": "Do analizy wykorzystano w\u00a0szczególności:",
    },
    # Bullet items 9-15 are rendered from {{ source.* }} — not editable text
    {
        "id": "b04", "type": "text", "section": 2, "para_idx": 16,
        "content": (
            "W toku analizy zastosowano porównanie chronologiczne, ocenę "
            "intensywności aktywności, identyfikację wzorców kontaktowych, "
            "przegląd zmian urządzeń oraz korelację aktywności z\u00a0danymi "
            "lokalizacyjnymi. W\u00a0przypadku anomalii przyjęto ostrożne podejście "
            "analityczne, zgodnie z\u00a0którym nie formułuje się tez kategorycznych "
            "w\u00a0sytuacji, gdy materiał wskazuje wyłącznie na przesłanki lub "
            "wzorzec wymagający dalszej weryfikacji."
        ),
    },

    # ─── Section 3: Identyfikacja numeru i urządzenia ───────────────────────
    {
        "id": "b05", "type": "text", "section": 3, "para_idx": 18,
        "content": (
            "Analizowany materiał dotyczy numeru {{ msisdn }}, związanego "
            "z\u00a0parametrem głównym {{ parametr_glowny }}. W\u00a0badanym okresie "
            "zidentyfikowano następujące identyfikatory abonenta i\u00a0urządzeń: "
            "IMSI {{ imsi_list }}, IMEI {{ imei_list }}."
        ),
    },
    {
        "id": "b06", "type": "text", "section": 3, "para_idx": 19,
        "content": (
            "W raporcie odnotowano liczbę unikalnych urządzeń równą "
            "{{ unique_imei_count }}, przy czym układ dual-IMEI został oznaczony "
            "jako {{ dual_imei_present }}. Zmiany urządzenia lub zmiany aktywnego "
            "identyfikatora należy interpretować w\u00a0zestawieniu z\u00a0osią czasu "
            "aktywności i\u00a0charakterem ruchu, bez automatycznego przypisywania im "
            "znaczenia operacyjnego bez dodatkowych danych potwierdzających."
        ),
    },

    # ─── Section 4: Charakterystyka aktywności telekomunikacyjnej ───────────
    {
        "id": "b07", "type": "text", "section": 4, "para_idx": 22,
        "content": (
            "W analizowanym okresie odnotowano łącznie {{ total_records }} "
            "rekordów, w\u00a0tym połączenia przychodzące i\u00a0wychodzące, wiadomości, "
            "przekierowania oraz zdarzenia transmisji danych. Kluczowe statystyki "
            "przedstawiają się następująco: połączenia przychodzące "
            "{{ stats.incoming_calls }}, połączenia wychodzące "
            "{{ stats.outgoing_calls }}, SMS przychodzące {{ stats.sms_in }}, "
            "SMS wychodzące {{ stats.sms_out }}, transmisja danych "
            "{{ stats.data_sessions }}."
        ),
    },
    {"id": "b08", "type": "marker", "key": "table_stats"},
    {
        "id": "b09", "type": "text", "section": 4, "para_idx": 23,
        "content": (
            "Rozkład aktywności godzinowej i\u00a0tygodniowej wskazuje na "
            "{{ activity.hourly_pattern }}, przy czym aktywność nocna została "
            "oszacowana na {{ activity.night_share }}, a\u00a0aktywność weekendowa "
            "na {{ activity.weekend_share }}. W\u00a0przypadku istotnych odchyleń "
            "od typowego profilu użytkownika należy je rozpatrywać łącznie "
            "z\u00a0kontaktami, lokalizacją i\u00a0anomaliami czasowymi."
        ),
    },
    {
        "id": "b10", "type": "text", "section": 4, "para_idx": 24,
        "content": (
            "W zakresie numerów specjalnych odnotowano: "
            "{{ special_numbers_summary }}. Informacja ta może mieć znaczenie "
            "uzupełniające przy ocenie charakteru aktywności, jednak powinna "
            "być odnoszona do pełnego kontekstu sprawy."
        ),
    },

    # ─── Section 5: Charakterystyka kontaktów ───────────────────────────────
    {
        "id": "b11", "type": "text", "section": 5, "para_idx": 38,
        "content": (
            "Analiza relacji kontaktowych wskazuje, że numer {{ msisdn }} "
            "pozostawał w\u00a0relacji z\u00a0{{ contacts.unique_count }} unikalnymi "
            "numerami. Najczęściej występujące kontakty to: {{ contacts.top_list }}."
        ),
    },
    {"id": "b12", "type": "marker", "key": "table_contacts"},
    {"id": "b13", "type": "marker", "key": "list_contacts"},
    {
        "id": "b14", "type": "text", "section": 5, "para_idx": 39,
        "content": (
            "W odniesieniu do kontaktów należy odnotować ich strukturę "
            "kierunkową, częstotliwość i\u00a0trwałość relacji. Na uwagę zasługują "
            "w\u00a0szczególności kontakty o\u00a0zwiększonej intensywności, kontakty "
            "krótkotrwałe pojawiające się wyłącznie incydentalnie oraz kontakty "
            "o\u00a0potencjalnym znaczeniu operacyjnym, opisane w\u00a0raporcie jako "
            "{{ contacts.assessment }}."
        ),
    },
    {
        "id": "b15", "type": "text", "section": 5,
        "content": (
            "Graf \u201eNajczęstsze kontakty\u201d obrazuje strukturę relacji "
            "komunikacyjnych analizowanego numeru, wskazując podmioty występujące "
            "najczęściej w\u00a0ruchu telekomunikacyjnym. Pozwala to określić "
            "krąg najaktywniejszych kontaktów, uchwycić powtarzalność "
            "komunikacji oraz wskazać numery, które mogą odgrywać istotną "
            "rolę w\u00a0badanym modelu łączności."
        ),
    },
    {"id": "b16", "type": "marker", "key": "chart_top_contacts"},
    {"id": "b17", "type": "marker", "key": "footnotes_special"},

    # ─── Section 6: Rodzaj aktywności (auto-inserted heading) ───────────────
    {
        "id": "b18", "type": "text", "section": 6,
        "content": (
            "Mapa rozkładu aktywności przedstawia intensywność zdarzeń "
            "telekomunikacyjnych w\u00a0zależności od dnia tygodnia i\u00a0pory doby. "
            "Zestawienie to pozwala uchwycić dominujące przedziały aktywności, "
            "wskazać powtarzalne schematy czasowe oraz ocenić, czy komunikacja "
            "koncentrowała się w\u00a0typowych godzinach dziennych, czy również "
            "w\u00a0porach nietypowych."
        ),
    },
    {"id": "b19", "type": "marker", "key": "chart_activity"},
    {"id": "b20", "type": "marker", "key": "chart_night"},
    {"id": "b21", "type": "marker", "key": "chart_weekend"},

    # ─── Section 7: Anomalie i wzorce nietypowe ─────────────────────────────
    {
        "id": "b22", "type": "text", "section": 7,
        "content": (
            "W\u00a0toku analizy materiału bilingowego zidentyfikowano zdarzenia oraz "
            "sekwencje aktywności odbiegające od typowego profilu korzystania "
            "z\u00a0numeru. Za anomalie uznano zarówno pojedyncze incydenty "
            "o\u00a0niestandardowych cechach, jak i\u00a0powtarzalne wzorce czasowe, "
            "kontaktowe lub lokalizacyjne, które mogą wymagać "
            "pogłębionej weryfikacji analitycznej."
        ),
    },
    {"id": "b23", "type": "marker", "key": "table_anomalies"},

    # ─── Section 8: Dane lokalizacyjne i mobilność ──────────────────────────
    {
        "id": "b24", "type": "text", "section": 8, "para_idx": 48,
        "content": (
            "Na podstawie danych BTS i\u00a0geolokalizacyjnych ustalono, że "
            "aktywność numeru koncentrowała się w\u00a0rejonach: "
            "{{ locations.main_areas }}. Łączna liczba unikalnych lokalizacji BTS "
            "wyniosła {{ locations.bts_count }}, zaś dominujące punkty aktywności "
            "opisano jako {{ locations.dominant_bts }}."
        ),
    },
    {"id": "b25", "type": "marker", "key": "table_locations"},
    {"id": "b26", "type": "marker", "key": "list_locations"},
    {"id": "b27", "type": "marker", "key": "bts_summary"},
    {
        "id": "b28", "type": "text", "section": 8, "para_idx": 49,
        "content": (
            "W materiale odnotowano również następujące przesłanki dotyczące "
            "przemieszczania się i\u00a0miejsc noclegowych: "
            "{{ locations.overnights_summary }}. W\u00a0przypadku danych lokalizacyjnych "
            "należy pamiętać, że ich interpretacja ma charakter przybliżony "
            "i\u00a0zależy od gęstości sieci oraz sposobu logowania urządzenia "
            "do stacji bazowych."
        ),
    },
    {"id": "b29", "type": "marker", "key": "list_movement"},
    {"id": "b30", "type": "marker", "key": "chart_map_bts"},

    # ─── Section 9: Ocena sytuacji analitycznej ─────────────────────────────
    {
        "id": "b31", "type": "text", "section": 9, "para_idx": 55,
        "content": (
            "Całościowa ocena materiału wskazuje, że aktywność numeru "
            "{{ msisdn }} charakteryzuje się następującymi cechami dominującymi: "
            "{{ assessment.main_characteristics }}."
        ),
    },
    {
        "id": "b32", "type": "text", "section": 9, "para_idx": 56,
        "content": (
            "W świetle zgromadzonych danych można sformułować następującą ocenę "
            "roboczą: {{ assessment.working_assessment }}. W\u00a0przypadku "
            "występowania anomalii lub zmian urządzeń ich znaczenie powinno być "
            "odnoszone do szerszego kontekstu sprawy, a\u00a0nie interpretowane "
            "samoistnie."
        ),
    },

    # ─── Section 10: Wnioski ────────────────────────────────────────────────
    # Conclusions (points 1-4) are {{ conclusions.point_N }} — not editable text
    {
        "id": "b33", "type": "text", "section": 10, "para_idx": 62,
        "content": (
            "W razie potrzeby dalszych ustaleń rekomenduje się konfrontację "
            "powyższych wniosków z\u00a0dodatkowymi materiałami, w\u00a0szczególności "
            "z\u00a0pełnymi rekordami operatorskimi, danymi z\u00a0innych numerów, "
            "informacjami o\u00a0urządzeniach końcowych oraz materiałem "
            "pozatelekomunikacyjnym."
        ),
    },

    # ─── Section 11: Uwagi końcowe ─────────────────────────────────────────
    {
        "id": "b34", "type": "text", "section": 11, "para_idx": 64,
        "content": (
            "Niniejsza notatka ma charakter analityczny i\u00a0służy uporządkowaniu "
            "ustaleń wynikających z\u00a0raportu HTML. Miejsca oznaczone "
            "placeholderami należy uzupełnić automatycznie lub redakcyjnie, "
            "z\u00a0zachowaniem spójności z\u00a0materiałem źródłowym i\u00a0bez "
            "wprowadzania twierdzeń niewynikających z\u00a0danych."
        ),
    },
]


def get_builtin_template() -> Dict[str, Any]:
    """Return the built-in (read-only) template that mirrors the hard-coded logic."""
    return {
        "id": "__builtin__",
        "name": "Wbudowany",
        "builtin": True,
        "default": False,
        "sections": [dict(s) for s in _BUILTIN_SECTIONS],  # deep-ish copy
    }


# ── Persistence helpers ─────────────────────────────────────────────────────

def _templates_path(data_dir: str | Path, user_id: str) -> Path:
    """Return path to the user's template JSON file."""
    p = Path(data_dir) / "users" / user_id / "gsm_note_templates.json"
    return p


def _read_templates(data_dir: str | Path, user_id: str) -> List[Dict[str, Any]]:
    """Read stored templates for a user.  Returns empty list if none."""
    path = _templates_path(data_dir, user_id)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
        return []
    except Exception as exc:
        log.warning("Failed to read templates for user %s: %s", user_id, exc)
        return []


def _write_templates(data_dir: str | Path, user_id: str, templates: List[Dict[str, Any]]) -> None:
    """Persist templates list to disk."""
    path = _templates_path(data_dir, user_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(templates, ensure_ascii=False, indent=2), encoding="utf-8")
    log.debug("Saved %d templates for user %s", len(templates), user_id)


# ── CRUD ────────────────────────────────────────────────────────────────────

def list_templates(data_dir: str | Path, user_id: str) -> List[Dict[str, Any]]:
    """Return user templates (without heavy section data — summary only)."""
    templates = _read_templates(data_dir, user_id)
    result = []
    for t in templates:
        result.append({
            "id": t["id"],
            "name": t.get("name", ""),
            "default": t.get("default", False),
            "section_count": len(t.get("sections", [])),
        })
    return result


def get_template(data_dir: str | Path, user_id: str, tpl_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve a single template by ID.  Returns None if not found."""
    if tpl_id == "__builtin__":
        return get_builtin_template()
    templates = _read_templates(data_dir, user_id)
    for t in templates:
        if t["id"] == tpl_id:
            return t
    return None


def save_template(data_dir: str | Path, user_id: str, tpl: Dict[str, Any]) -> Dict[str, Any]:
    """Create or update a template.  Returns the saved template dict.

    Raises ValueError if:
      - template limit exceeded (MAX_TEMPLATES) on create
      - invalid marker key in sections
    """
    templates = _read_templates(data_dir, user_id)

    # Validate sections
    sections = tpl.get("sections", [])
    for s in sections:
        if s.get("type") == "marker" and s.get("key") not in VALID_MARKER_KEYS:
            raise ValueError(f"Unknown marker key: {s.get('key')}")

    tpl_id = tpl.get("id", "")

    # Update existing?
    existing_idx = None
    for i, t in enumerate(templates):
        if t["id"] == tpl_id:
            existing_idx = i
            break

    if existing_idx is not None:
        # Update in place
        templates[existing_idx] = _sanitize_template(tpl)
    else:
        # New template
        if len(templates) >= MAX_TEMPLATES:
            raise ValueError(f"Osiągnięto limit {MAX_TEMPLATES} szablonów")
        if not tpl_id:
            tpl["id"] = f"tpl_{uuid.uuid4().hex[:8]}"
        templates.append(_sanitize_template(tpl))

    # Ensure section IDs exist
    saved = templates[existing_idx] if existing_idx is not None else templates[-1]
    _ensure_section_ids(saved)

    # Handle default flag — if this template is set as default, clear others
    if saved.get("default"):
        for t in templates:
            if t["id"] != saved["id"]:
                t["default"] = False

    _write_templates(data_dir, user_id, templates)
    return saved


def delete_template(data_dir: str | Path, user_id: str, tpl_id: str) -> bool:
    """Delete a template.  Returns True if found & deleted."""
    if tpl_id == "__builtin__":
        return False  # can't delete built-in
    templates = _read_templates(data_dir, user_id)
    before = len(templates)
    templates = [t for t in templates if t["id"] != tpl_id]
    if len(templates) == before:
        return False
    _write_templates(data_dir, user_id, templates)
    return True


def set_default(data_dir: str | Path, user_id: str, tpl_id: str) -> None:
    """Set a template as the default.  Pass '__builtin__' to clear user default."""
    templates = _read_templates(data_dir, user_id)
    for t in templates:
        t["default"] = (t["id"] == tpl_id)
    _write_templates(data_dir, user_id, templates)
    log.debug("Set default template to '%s' for user %s", tpl_id, user_id)


def get_effective_template(data_dir: str | Path, user_id: str, tpl_id: Optional[str] = None) -> Dict[str, Any]:
    """Return the template to use for generation.

    Priority:
      1. Explicit tpl_id (if provided and found)
      2. User's default template
      3. Built-in template
    """
    if tpl_id and tpl_id != "__builtin__":
        tpl = get_template(data_dir, user_id, tpl_id)
        if tpl:
            return tpl

    # Look for user's default
    templates = _read_templates(data_dir, user_id)
    for t in templates:
        if t.get("default"):
            return t

    return get_builtin_template()


# ── Internal helpers ────────────────────────────────────────────────────────

def _sanitize_template(tpl: Dict[str, Any]) -> Dict[str, Any]:
    """Keep only the fields we care about."""
    return {
        "id": tpl.get("id", f"tpl_{uuid.uuid4().hex[:8]}"),
        "name": tpl.get("name", "Nowy szablon")[:100],
        "default": bool(tpl.get("default", False)),
        "sections": tpl.get("sections", []),
    }


def _ensure_section_ids(tpl: Dict[str, Any]) -> None:
    """Make sure every section has a unique id."""
    seen = set()
    for s in tpl.get("sections", []):
        if not s.get("id") or s["id"] in seen:
            s["id"] = f"s_{uuid.uuid4().hex[:6]}"
        seen.add(s["id"])
