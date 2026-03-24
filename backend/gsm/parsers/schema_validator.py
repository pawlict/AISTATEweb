"""Schema validator for GSM billing parsers.

Compares actual billing headers against expected parser schemas using
three matching strategies: exact, regex, and fuzzy (with multiple sub-strategies).
"""

from __future__ import annotations

import difflib
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from .schema_registry import ColumnSchema, ParserSchema, SchemaRegistry


# ---------------------------------------------------------------------------
# Validation result
# ---------------------------------------------------------------------------

@dataclass
class SchemaValidationResult:
    """Result of validating actual headers against a parser schema."""

    parser_id: str = ""
    parser_version: str = ""
    format_variant: str = ""
    match_type: str = ""              # "exact", "partial", "drift", "failed"
    matched_columns: Dict[str, int] = field(default_factory=dict)  # logical → index
    missing_columns: List[str] = field(default_factory=list)        # required columns not found
    extra_headers: List[str] = field(default_factory=list)          # headers not in schema
    fuzzy_matches: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    # fuzzy_matches: { logical_name: { header_index, header_text, confidence, method } }
    confidence: float = 0.0
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "parser_id": self.parser_id,
            "parser_version": self.parser_version,
            "format_variant": self.format_variant,
            "match_type": self.match_type,
            "matched_columns": self.matched_columns,
            "missing_columns": self.missing_columns,
            "extra_headers": self.extra_headers,
            "fuzzy_matches": self.fuzzy_matches,
            "confidence": round(self.confidence, 3),
            "warnings": self.warnings,
        }


# ---------------------------------------------------------------------------
# Semantic equivalence groups for Polish billing terminology
# ---------------------------------------------------------------------------

_SEMANTIC_GROUPS: Dict[str, List[str]] = {
    "datetime": [
        "data", "czas", "godz", "godzina", "kiedy", "termin",
        "pocz", "poczatek", "start", "data i czas", "data i godz",
        "data polaczenia", "data rozpoczecia",
    ],
    "phone_number": [
        "numer", "msisdn", "telefon", "nr", "abonent", "identyfikator",
    ],
    "caller": [
        "numer a", "msisdn a", "dzwoniacy", "nadawca", "caller",
    ],
    "callee": [
        "numer b", "msisdn b", "rozmowca", "odbiorca", "called",
        "numer docelowy", "numer wywolywany",
    ],
    "duration": [
        "czas trwania", "dlugosc", "czas polaczenia", "duration",
        "czas rozmowy",
    ],
    "service_type": [
        "usluga", "typ", "rodzaj", "kierunek", "typ uslugi",
        "rodzaj uslugi", "kategoria", "typ polaczenia",
    ],
    "location": [
        "lokalizacja", "bts", "stacja", "adres", "miejsce",
        "stacja bazowa", "cell", "location",
    ],
    "cost": [
        "koszt", "oplata", "kwota", "cena", "naleznosc", "wartosc",
        "netto", "koszt netto",
    ],
    "imei": ["imei", "esn"],
    "imsi": ["imsi"],
    "data_volume": [
        "dane", "transfer", "objetosc", "wolumen", "volume",
        "internet", "gprs", "lte",
    ],
    # ── Identification-specific groups ──
    "subscriber_name": [
        "abonent", "nazwisko", "imie", "imie i nazwisko", "nazwa",
        "nazwa firmy", "name", "subscriber", "uzytkownik", "wlasciciel",
    ],
    "personal_id": [
        "pesel", "nip", "regon", "pesel/regon/nip", "pesel regon nip",
    ],
    "address": [
        "adres", "ulica", "miasto", "miejscowosc", "kod", "kod pocztowy",
        "nr", "nr domu", "ulica nr",
    ],
    "document": [
        "nr dokumentu", "numer dokumentu", "typ dokumentu",
        "nr dokumentu tozsamosci", "document", "seria i nr",
    ],
    "sim_iccid": [
        "sim", "sim numer", "iccid", "numer karty sim",
    ],
    "activation": [
        "data akt", "data aktywacji", "aktywacja", "aktywacja msisdn",
        "wazne od", "abonent od", "data od",
    ],
    "deactivation": [
        "data dezakt", "data dezaktywacji", "wylaczenie", "wylaczenie msisdn",
        "wazne do", "abonent do", "data do",
    ],
    "contract": [
        "status kontraktu", "typ kontraktu", "typ msisdn",
        "status", "kontrakt", "taryfa", "usluga",
    ],
}


# ---------------------------------------------------------------------------
# Text normalization helpers
# ---------------------------------------------------------------------------

def _strip_diacritics(text: str) -> str:
    """Remove Polish/Unicode diacritics: e.g. ł→l, ą→a, ś→s."""
    # Special-case Polish ł/Ł (not decomposed by NFD)
    text = text.replace("\u0142", "l").replace("\u0141", "L")
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def _normalize_header(text: str) -> str:
    """Normalize a header for comparison: lowercase, strip diacritics,
    replace underscores/dots/dashes with spaces, collapse whitespace."""
    text = text.strip().lower()
    text = _strip_diacritics(text)
    text = re.sub(r"[_.\-/]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _semantic_group_for(text: str) -> Optional[str]:
    """Find which semantic group a normalized header fragment belongs to."""
    norm = _normalize_header(text)
    for group_name, keywords in _SEMANTIC_GROUPS.items():
        for kw in keywords:
            if kw in norm or norm in kw:
                return group_name
    return None


# ---------------------------------------------------------------------------
# Fuzzy matching strategies
# ---------------------------------------------------------------------------

def _fuzzy_normalized(expected_headers: List[str], actual: str) -> float:
    """Strategy 1: Normalized comparison (handles encoding, underscores, diacritics).

    Returns best confidence score (0.0-1.0).
    """
    norm_actual = _normalize_header(actual)
    if not norm_actual:
        return 0.0

    best = 0.0
    for eh in expected_headers:
        norm_expected = _normalize_header(eh)
        if not norm_expected:
            continue
        if norm_expected == norm_actual:
            return 1.0
        # Check if one contains the other
        if norm_expected in norm_actual or norm_actual in norm_expected:
            ratio = min(len(norm_expected), len(norm_actual)) / max(
                len(norm_expected), len(norm_actual)
            )
            best = max(best, 0.5 + ratio * 0.4)  # 0.5-0.9 range
    return best


def _fuzzy_sequence_matcher(expected_headers: List[str], actual: str) -> float:
    """Strategy 2: difflib.SequenceMatcher ratio.

    Returns best confidence score (0.0-1.0).
    """
    norm_actual = _normalize_header(actual)
    if not norm_actual:
        return 0.0

    best = 0.0
    for eh in expected_headers:
        norm_expected = _normalize_header(eh)
        if not norm_expected:
            continue
        ratio = difflib.SequenceMatcher(None, norm_expected, norm_actual).ratio()
        best = max(best, ratio)
    return best


def _fuzzy_semantic(
    logical_name: str, actual: str, description: str = ""
) -> float:
    """Strategy 3: Semantic matching via Polish billing term equivalences.

    Returns confidence score (0.0-1.0).
    """
    norm_actual = _normalize_header(actual)
    if not norm_actual:
        return 0.0

    # Find semantic group for the logical name
    target_group = None
    for group_name, keywords in _SEMANTIC_GROUPS.items():
        norm_logical = _normalize_header(logical_name)
        if norm_logical in keywords or group_name == norm_logical:
            target_group = group_name
            break
        # Check if logical_name is a substring of a keyword
        for kw in keywords:
            if norm_logical in kw or kw in norm_logical:
                target_group = group_name
                break
        if target_group:
            break

    if not target_group:
        return 0.0

    # Check if actual header matches any keyword in the same group
    group_keywords = _SEMANTIC_GROUPS[target_group]
    for kw in group_keywords:
        norm_kw = _normalize_header(kw)
        if norm_kw == norm_actual:
            return 0.85
        if norm_kw in norm_actual or norm_actual in norm_kw:
            ratio = min(len(norm_kw), len(norm_actual)) / max(
                len(norm_kw), len(norm_actual)
            )
            if ratio > 0.4:
                return 0.5 + ratio * 0.3

    return 0.0


# ---------------------------------------------------------------------------
# Schema Validator
# ---------------------------------------------------------------------------

class SchemaValidator:
    """Validates actual billing headers against expected parser schemas."""

    # Confidence thresholds
    FUZZY_CONSIDER_THRESHOLD = 0.55   # minimum to consider a fuzzy match
    FUZZY_AUTO_ACCEPT = 0.85          # auto-accept without user review

    def __init__(self, registry: Optional[SchemaRegistry] = None):
        if registry is None:
            registry = SchemaRegistry()
        self._registry = registry

    def validate(
        self,
        parser_id: str,
        actual_headers: List[str],
        variant: str = "",
    ) -> SchemaValidationResult:
        """Compare actual headers from a billing file against expected schema.

        Returns SchemaValidationResult with match_type:
        - "exact":   all required columns matched by expected_headers / regex
        - "drift":   all required columns found (some via fuzzy matching)
        - "partial": some required columns still missing after fuzzy
        - "failed":  schema not found or critical failure
        """
        result = SchemaValidationResult(
            parser_id=parser_id,
            format_variant=variant,
        )

        schema = self._registry.get_schema(parser_id, variant)
        if schema is None:
            result.match_type = "failed"
            result.warnings.append(
                f"Brak zarejestrowanego schematu dla {parser_id}"
                + (f" ({variant})" if variant else "")
            )
            return result

        result.parser_version = schema.parser_version

        # Phase 1: Exact header matching
        matched, unmatched_cols = self._exact_match(actual_headers, schema)
        result.matched_columns.update(matched)

        # Phase 2: Regex matching for remaining unmatched columns
        if unmatched_cols:
            regex_matched = self._regex_match(actual_headers, unmatched_cols, matched)
            result.matched_columns.update(regex_matched)
            unmatched_cols = [c for c in unmatched_cols if c.logical_name not in regex_matched]

        # Identify unmapped header indices (for fuzzy matching candidates)
        mapped_indices: Set[int] = set(result.matched_columns.values())
        unmatched_headers = [
            (i, h) for i, h in enumerate(actual_headers)
            if i not in mapped_indices and h.strip()
        ]

        # Phase 3: Fuzzy matching for still-unmatched required columns
        if unmatched_cols and unmatched_headers:
            fuzzy = self._fuzzy_match(unmatched_cols, unmatched_headers)
            result.fuzzy_matches = fuzzy

            # Apply auto-accepted fuzzy matches
            for logical, info in fuzzy.items():
                if info["confidence"] >= self.FUZZY_AUTO_ACCEPT:
                    result.matched_columns[logical] = info["header_index"]
                    mapped_indices.add(info["header_index"])

            unmatched_cols = [
                c for c in unmatched_cols
                if c.logical_name not in result.matched_columns
            ]

        # Classify missing vs extra
        required_missing = [c.logical_name for c in unmatched_cols if c.required]
        result.missing_columns = required_missing
        result.extra_headers = [
            h for i, h in enumerate(actual_headers)
            if i not in mapped_indices and h.strip()
        ]

        # Determine match_type
        total_required = len(schema.get_required_columns())
        matched_required = total_required - len(required_missing)

        if not required_missing and not result.fuzzy_matches:
            result.match_type = "exact"
            result.confidence = 1.0
        elif not required_missing and result.fuzzy_matches:
            result.match_type = "drift"
            # Confidence based on fuzzy match quality
            avg_conf = sum(
                m["confidence"] for m in result.fuzzy_matches.values()
            ) / max(len(result.fuzzy_matches), 1)
            result.confidence = avg_conf
        elif matched_required > 0 or result.fuzzy_matches:
            result.match_type = "partial"
            if result.fuzzy_matches:
                avg_conf = sum(
                    m["confidence"] for m in result.fuzzy_matches.values()
                ) / max(len(result.fuzzy_matches), 1)
                result.confidence = avg_conf
            else:
                result.confidence = matched_required / max(total_required, 1)
        else:
            result.match_type = "failed"
            result.confidence = 0.0

        return result

    # ------------------------------------------------------------------
    # Matching phases
    # ------------------------------------------------------------------

    @staticmethod
    def _exact_match(
        actual_headers: List[str],
        schema: ParserSchema,
    ) -> Tuple[Dict[str, int], List[ColumnSchema]]:
        """Phase 1: Match headers by expected_headers (exact lowercase match).

        Returns (matched: logical→index, unmatched: remaining ColumnSchemas).
        """
        matched: Dict[str, int] = {}
        unmatched: List[ColumnSchema] = []

        for col in schema.columns:
            found = False
            for exp in col.expected_headers:
                exp_lower = exp.lower()
                for i, h in enumerate(actual_headers):
                    if h.lower().strip() == exp_lower:
                        matched[col.logical_name] = i
                        found = True
                        break
                if found:
                    break
            if not found:
                unmatched.append(col)

        return matched, unmatched

    @staticmethod
    def _regex_match(
        actual_headers: List[str],
        unmatched_cols: List[ColumnSchema],
        already_matched: Dict[str, int],
    ) -> Dict[str, int]:
        """Phase 2: Match unmatched columns using regex patterns.

        Returns additional matched: logical→index.
        """
        matched: Dict[str, int] = {}
        used_indices: Set[int] = set(already_matched.values())

        for col in unmatched_cols:
            if not col.regex_patterns:
                continue
            for i, h in enumerate(actual_headers):
                if i in used_indices:
                    continue
                h_text = h.strip().lower()
                if not h_text:
                    continue
                for pat in col.regex_patterns:
                    if re.search(pat, h_text, re.I):
                        matched[col.logical_name] = i
                        used_indices.add(i)
                        break
                if col.logical_name in matched:
                    break

        return matched

    def _fuzzy_match(
        self,
        unmatched_cols: List[ColumnSchema],
        unmatched_headers: List[Tuple[int, str]],
    ) -> Dict[str, Dict[str, Any]]:
        """Phase 3: Fuzzy matching for remaining unmatched columns.

        Applies three strategies and takes the highest-confidence result.

        Returns: { logical_name: { header_index, header_text, confidence, method } }
        """
        results: Dict[str, Dict[str, Any]] = {}
        used_indices: Set[int] = set()

        for col in unmatched_cols:
            best_match: Optional[Dict[str, Any]] = None
            best_conf = 0.0

            for idx, header_text in unmatched_headers:
                if idx in used_indices:
                    continue

                # Strategy 1: Normalized comparison
                conf1 = _fuzzy_normalized(col.expected_headers, header_text)
                if conf1 > best_conf:
                    best_conf = conf1
                    best_match = {
                        "header_index": idx,
                        "header_text": header_text,
                        "confidence": conf1,
                        "method": "normalized",
                    }

                # Strategy 2: SequenceMatcher
                conf2 = _fuzzy_sequence_matcher(col.expected_headers, header_text)
                if conf2 > best_conf:
                    best_conf = conf2
                    best_match = {
                        "header_index": idx,
                        "header_text": header_text,
                        "confidence": conf2,
                        "method": "sequence_matcher",
                    }

                # Strategy 3: Semantic matching
                conf3 = _fuzzy_semantic(col.logical_name, header_text, col.description)
                if conf3 > best_conf:
                    best_conf = conf3
                    best_match = {
                        "header_index": idx,
                        "header_text": header_text,
                        "confidence": conf3,
                        "method": "semantic",
                    }

            if best_match and best_conf >= self.FUZZY_CONSIDER_THRESHOLD:
                results[col.logical_name] = best_match
                used_indices.add(best_match["header_index"])

        return results
