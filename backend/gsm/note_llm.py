"""
GSM Note LLM — generates narrative text for the analytical note using Ollama.

Variant 3 "analytical":
  LLM receives all analysis data as JSON context and generates narrative
  sections 4-9 in Polish formal style.

Produces override placeholders that replace template defaults for:
  - activity.* (section 4)
  - contacts.* (section 5)
  - anomalies.top_findings (section 6)
  - locations.* (section 7)
  - assessment.* (section 8)
  - conclusions.point_1..4 (section 9)
"""
from __future__ import annotations

import json
import logging
from typing import Any, AsyncGenerator, Dict, Optional

log = logging.getLogger("aistate.gsm.note_llm")


# ─── System prompt ───────────────────────────────────────────────────────────

SYSTEM_PROMPT = """Jesteś analitykiem telekomunikacyjnym przygotowującym formalną notatkę służbową z analizy bilingu GSM.

ZASADY:
- Pisz w języku polskim, styl formalny, rzeczowy, ostrożny interpretacyjnie.
- ODDZIELAJ fakty (dane liczbowe) od hipotez i ocen.
- NIE przypisuj intencji użytkownikowi numeru.
- Używaj sformułowań warunkowych: „może wskazywać na...", „sugeruje...", „wymaga weryfikacji".
- Wszystkie dane liczbowe podawaj dokładnie — nie zaokrąglaj.
- Każda sekcja powinna mieć 2-4 akapity.
- NIE dodawaj nagłówków sekcji (H1/H2) — są już w szablonie.
"""

# ─── Section generation prompts ──────────────────────────────────────────────

SECTION_PROMPTS = {
    "section_4": """Na podstawie poniższych danych napisz sekcję "Charakterystyka aktywności telekomunikacyjnej".

Uwzględnij:
- Dominujący typ komunikacji (głos / SMS / dane)
- Rozkład aktywności godzinowej i tygodniowej
- Aktywność nocną i weekendową
- Numery specjalne (jeśli występują)
- Statystyki czasowe połączeń (średni czas, mediana, najdłuższe)

Dane JSON:
{data}""",

    "section_5": """Na podstawie poniższych danych napisz sekcję "Charakterystyka kontaktów".

Uwzględnij:
- Liczbę unikalnych kontaktów
- Top 5 kontaktów z ich charakterystyką (liczba interakcji, kierunek, aktywne dni)
- Strukturę relacji (wąska/rozbudowana sieć)
- Kontakty jednorazowe, zagraniczne, specjalne (jeśli występują)

Dane JSON:
{data}""",

    "section_6": """Na podstawie poniższych danych napisz sekcję "Anomalie i wzorce nietypowe".

Uwzględnij:
- Liczbę i kategorie wykrytych anomalii
- Opis najważniejszych zjawisk (max 5)
- Ostrożną interpretację (bez przesądzania o intencjach)

Dane JSON:
{data}""",

    "section_7": """Na podstawie poniższych danych napisz sekcję "Dane lokalizacyjne i mobilność".

Uwzględnij:
- Główne rejony aktywności (top 3 lokalizacji BTS)
- Liczbę unikalnych lokalizacji
- Noclegi poza domem (jeśli wykryto)
- Dynamikę przemieszczania się
- Brak danych geolokalizacyjnych — zaznacz wyraźnie jeśli brak

Dane JSON:
{data}""",

    "section_8": """Na podstawie WSZYSTKICH poniższych danych analizy napisz sekcję "Ocena sytuacji analitycznej".

Ta sekcja powinna:
- Syntetycznie opisać profil aktywności numeru
- Wskazać najważniejsze cechy i wzorce
- Sformułować ostrożne hipotezy robocze
- WYRAŹNIE oddzielić ustalenia od ocen

Dane JSON (pełna analiza):
{data}""",

    "section_9": """Na podstawie WSZYSTKICH poniższych danych sformułuj 4 punkty wniosków.

Każdy punkt powinien być 1-2 zdania. Wnioski powinny być:
1. Aktywność w okresie + liczba rekordów
2. Konfiguracja urządzeniowa (IMEI, dual-IMEI)
3. Anomalie + kontakty
4. Lokalizacje + rekomendacja dalszych działań

Odpowiedz w formacie JSON:
{{"point_1": "...", "point_2": "...", "point_3": "...", "point_4": "..."}}

Dane JSON:
{data}""",
}


# ─── Data preparation ────────────────────────────────────────────────────────

def _prepare_section_data(gsm_data: dict, section: str) -> str:
    """Extract relevant JSON data for a given section prompt."""
    billing = gsm_data.get("billing", {})
    analysis = billing.get("analysis", {})
    summary = billing.get("summary", {})

    if section == "section_4":
        data = {
            "summary": summary,
            "temporal": analysis.get("temporal", {}),
            "night_activity": analysis.get("night_activity", {}),
            "weekend_activity": analysis.get("weekend_activity", {}),
            "special_numbers": analysis.get("special_numbers", [])[:10],
            "avg_call_duration": analysis.get("avg_call_duration", 0),
            "median_call_duration": analysis.get("median_call_duration", 0),
            "longest_call_seconds": analysis.get("longest_call_seconds", 0),
            "busiest_date": analysis.get("busiest_date", ""),
            "busiest_date_count": analysis.get("busiest_date_count", 0),
        }
    elif section == "section_5":
        data = {
            "unique_contacts": summary.get("unique_contacts", 0),
            "top_contacts": analysis.get("top_contacts", [])[:10],
        }
    elif section == "section_6":
        data = {
            "anomalies": analysis.get("anomalies", []),
        }
    elif section == "section_7":
        data = {
            "locations": analysis.get("locations", [])[:15],
            "overnight_stays": analysis.get("overnight_stays", []),
            "overnight_stays_home": analysis.get("overnight_stays_home", ""),
        }
    elif section in ("section_8", "section_9"):
        # Full data summary for assessment/conclusions
        data = {
            "subscriber": billing.get("subscriber", {}),
            "summary": summary,
            "devices": analysis.get("devices", []),
            "dual_imei": analysis.get("dual_imei"),
            "anomalies_count": len(analysis.get("anomalies", [])),
            "anomaly_types": list(set(a.get("type", "") for a in analysis.get("anomalies", []))),
            "top_contacts_count": len(analysis.get("top_contacts", [])),
            "top_3_contacts": [
                {"number": c.get("number"), "interactions": c.get("total_interactions")}
                for c in analysis.get("top_contacts", [])[:3]
            ],
            "locations_count": len(analysis.get("locations", [])),
            "top_3_locations": [
                {"location": l.get("location"), "records": l.get("record_count")}
                for l in analysis.get("locations", [])[:3]
            ],
            "night_activity_ratio": (analysis.get("temporal") or {}).get("night_activity_ratio", 0),
        }
    else:
        data = {}

    return json.dumps(data, ensure_ascii=False, indent=2, default=str)


# ─── LLM generation ─────────────────────────────────────────────────────────

async def generate_note_sections_llm(
    gsm_data: dict,
    model: str,
    *,
    ollama_client: Any = None,
    on_progress: Optional[Any] = None,
) -> Dict[str, str]:
    """Generate all narrative sections using LLM.

    Args:
        gsm_data: Full gsm_latest.json
        model: Ollama model name (e.g., "qwen2.5:14b", "SpeakLeash/bielik-11b-v2.3-instruct:Q4_K_M")
        ollama_client: OllamaClient instance (if None, creates one)
        on_progress: Optional async callback(section_name: str, progress_pct: int)

    Returns:
        Dict with keys matching template override paths:
        {
            "activity.hourly_pattern": "...",
            "activity.night_share": "...",  # kept from data
            "activity.weekend_share": "...",  # kept from data
            "special_numbers_summary": "...",  # kept from data
            "contacts.assessment": "...",
            "anomalies.top_findings": "...",
            "locations.overnights_summary": "...",
            "assessment.main_characteristics": "...",
            "assessment.working_assessment": "...",
            "conclusions.point_1": "...",
            "conclusions.point_2": "...",
            "conclusions.point_3": "...",
            "conclusions.point_4": "...",
            # Full section texts for inline replacement
            "_section_4_text": "...",
            "_section_5_text": "...",
            "_section_6_text": "...",
            "_section_7_text": "...",
            "_section_8_text": "...",
        }
    """
    if ollama_client is None:
        from backend.ollama_client import OllamaClient
        ollama_client = OllamaClient()

    overrides: Dict[str, str] = {}
    sections = ["section_4", "section_5", "section_6", "section_7", "section_8", "section_9"]
    total = len(sections)

    for i, section in enumerate(sections):
        if on_progress:
            pct = int((i / total) * 100)
            try:
                await on_progress(section, pct)
            except Exception:
                pass

        prompt_template = SECTION_PROMPTS.get(section, "")
        if not prompt_template:
            continue

        data_json = _prepare_section_data(gsm_data, section)
        user_prompt = prompt_template.format(data=data_json)

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

        try:
            response_text = ""
            async for chunk in ollama_client.stream_chat(model, messages):
                response_text += chunk

            response_text = response_text.strip()

            if section == "section_9":
                # Parse JSON response for conclusions
                _parse_conclusions(response_text, overrides)
            else:
                # Store as override text
                key = f"_section_{section.split('_')[1]}_text"
                overrides[key] = response_text

                # Also extract specific placeholders
                if section == "section_8":
                    overrides["assessment.main_characteristics"] = response_text
                    overrides["assessment.working_assessment"] = response_text

        except Exception as e:
            log.error("LLM generation failed for %s: %s", section, e, exc_info=True)
            overrides[f"_section_{section.split('_')[1]}_error"] = str(e)

    if on_progress:
        try:
            await on_progress("done", 100)
        except Exception:
            pass

    return overrides


def _parse_conclusions(text: str, overrides: dict) -> None:
    """Parse LLM conclusions response (may be JSON or plain text)."""
    import re

    # Try JSON parse first
    try:
        # Find JSON in response
        json_match = re.search(r'\{[^{}]*"point_1"[^{}]*\}', text, re.DOTALL)
        if json_match:
            data = json.loads(json_match.group())
            for k in ["point_1", "point_2", "point_3", "point_4"]:
                if k in data:
                    overrides[f"conclusions.{k}"] = str(data[k])
            return
    except (json.JSONDecodeError, AttributeError):
        pass

    # Fallback: split by numbered points
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    points = []
    for line in lines:
        cleaned = re.sub(r'^\d+[\.\)]\s*', '', line)
        if cleaned:
            points.append(cleaned)

    for i, point in enumerate(points[:4]):
        overrides[f"conclusions.point_{i+1}"] = point
