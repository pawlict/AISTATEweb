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
    # --- Section 4: Stats ---
    {"id": "b01", "type": "marker", "key": "table_stats"},

    # --- Section 5: Contacts ---
    {"id": "b02", "type": "marker", "key": "table_contacts"},
    {"id": "b03", "type": "marker", "key": "list_contacts"},
    {
        "id": "b04", "type": "text",
        "content": (
            "Graf \u201eNajczęstsze kontakty\u201d obrazuje strukturę relacji "
            "komunikacyjnych analizowanego numeru, wskazując podmioty występujące "
            "najczęściej w\u00a0ruchu telekomunikacyjnym. Pozwala to określić "
            "krąg najaktywniejszych kontaktów, uchwycić powtarzalność "
            "komunikacji oraz wskazać numery, które mogą odgrywać istotną "
            "rolę w\u00a0badanym modelu łączności."
        ),
    },
    {"id": "b05", "type": "marker", "key": "chart_top_contacts"},
    {"id": "b06", "type": "marker", "key": "footnotes_special"},

    # --- Section 6: Activity type (auto-inserted heading) ---
    {
        "id": "b07", "type": "text",
        "content": (
            "Mapa rozkładu aktywności przedstawia intensywność zdarzeń "
            "telekomunikacyjnych w\u00a0zależności od dnia tygodnia i\u00a0pory doby. "
            "Zestawienie to pozwala uchwycić dominujące przedziały aktywności, "
            "wskazać powtarzalne schematy czasowe oraz ocenić, czy komunikacja "
            "koncentrowała się w\u00a0typowych godzinach dziennych, czy również "
            "w\u00a0porach nietypowych."
        ),
    },
    {"id": "b08", "type": "marker", "key": "chart_activity"},
    {"id": "b09", "type": "marker", "key": "chart_night"},
    {"id": "b10", "type": "marker", "key": "chart_weekend"},

    # --- Section 7: Anomalies ---
    {
        "id": "b11", "type": "text",
        "content": (
            "W\u00a0toku analizy materiału bilingowego zidentyfikowano zdarzenia oraz "
            "sekwencje aktywności odbiegające od typowego profilu korzystania "
            "z\u00a0numeru. Za anomalie uznano zarówno pojedyncze incydenty "
            "o\u00a0niestandardowych cechach, jak i\u00a0powtarzalne wzorce czasowe, "
            "kontaktowe lub lokalizacyjne, które mogą wymagać "
            "pogłębionej weryfikacji analitycznej."
        ),
    },
    {"id": "b12", "type": "marker", "key": "table_anomalies"},

    # --- Section 8: Locations ---
    {"id": "b13", "type": "marker", "key": "table_locations"},
    {"id": "b14", "type": "marker", "key": "list_locations"},
    {"id": "b15", "type": "marker", "key": "bts_summary"},
    {"id": "b16", "type": "marker", "key": "list_movement"},
    {"id": "b17", "type": "marker", "key": "chart_map_bts"},
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
