"""Geocoding BTS addresses via OpenStreetMap Nominatim.

Converts text-based BTS addresses (e.g. Plus Polkomtel CSV billings)
to geographic coordinates (lat, lon) using the Nominatim API.

Features:
- Persistent JSON cache to avoid duplicate requests
- Rate limiting (1 request/sec, Nominatim policy)
- Polish address parsing (street, postal code, city extraction)
- Batch geocoding with progress callback
"""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.error import URLError
from urllib.parse import quote_plus
from urllib.request import Request, urlopen

log = logging.getLogger(__name__)

# Nominatim settings
_NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
_USER_AGENT = "AISTATEweb/3.2 (GSM billing geocoding)"
_RATE_LIMIT_SEC = 1.1  # slightly over 1s for safety
_REQUEST_TIMEOUT = 10  # seconds

# Address cleanup patterns
_STRIP_PREFIXES = re.compile(
    r"\b(Ul\.?|Al\.?|Pl\.?|Os\.?|ul\.?|al\.?|pl\.?|os\.?)\s+",
    re.IGNORECASE,
)
_STRIP_INFRA_TAGS = re.compile(
    r"\b(SLR|BTS|IBC|RBS|eNB|gNB|NodeB)\b",
    re.IGNORECASE,
)
_POSTAL_CODE = re.compile(r"\b(\d{2}-\d{3})\b")
_DZIALKA = re.compile(
    r"\bDzia[łl]ka\s+nr\s+[\d/]+\b",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Address parsing
# ---------------------------------------------------------------------------

def parse_plus_bts_address(raw: str) -> Tuple[str, str, str]:
    """Parse a Plus-style BTS address into (street, postal_code, city).

    Input examples:
        "Ul Cieszynska 3,SLR Bialystok 15-371 Bialystok"
        "Gorczyca Dzialka nr 1/33 16-326 Gorczyca"
        "Kartuska 407A,BTS Gdansk 80-125 Gdansk"

    Returns:
        (street_part, postal_code, city) — any may be empty string.
    """
    if not raw or not raw.strip():
        return ("", "", "")

    addr = raw.strip()

    # Extract postal code
    m_postal = _POSTAL_CODE.search(addr)
    postal_code = m_postal.group(1) if m_postal else ""

    # City: text AFTER postal code (usually the last word(s))
    city = ""
    if m_postal:
        after_postal = addr[m_postal.end():].strip()
        if after_postal:
            city = after_postal
        else:
            # Sometimes city appears before postal code: "SLR Bialystok 15-371"
            before_postal = addr[:m_postal.start()].strip()
            # Take last word before postal code
            parts = before_postal.split()
            if parts:
                # Skip infra tags
                for p in reversed(parts):
                    if not _STRIP_INFRA_TAGS.match(p):
                        city = p
                        break

    # Street: everything before the postal code, cleaned up
    street = ""
    if m_postal:
        street = addr[:m_postal.start()].strip()
    else:
        street = addr

    # Remove comma and everything after (often comma separates street from infra tag)
    if "," in street:
        street = street.split(",")[0].strip()

    # Clean street: remove prefixes and infra tags
    street = _STRIP_PREFIXES.sub("", street).strip()
    street = _STRIP_INFRA_TAGS.sub("", street).strip()
    street = _DZIALKA.sub("", street).strip()

    # Remove city name from street if it appears there
    if city and street.endswith(city):
        street = street[: -len(city)].strip()

    # Remove trailing comma
    street = street.rstrip(",").strip()

    return (street, postal_code, city)


def build_geocode_query(raw_address: str) -> Tuple[str, Optional[str]]:
    """Build Nominatim query string from a Plus BTS address.

    Returns:
        (primary_query, fallback_query) — fallback is postal+city if primary
        is more specific. Returns (query, None) if only one query makes sense.
    """
    street, postal, city = parse_plus_bts_address(raw_address)

    if not postal and not city:
        # Can't geocode without at least city or postal code
        return (raw_address + ", Poland", None)

    # Build primary: street + postal + city
    parts_primary = []
    if street:
        parts_primary.append(street)
    if postal and city:
        parts_primary.append(f"{postal} {city}")
    elif city:
        parts_primary.append(city)
    elif postal:
        parts_primary.append(postal)
    parts_primary.append("Poland")
    primary = ", ".join(parts_primary)

    # Fallback: just postal + city
    fallback = None
    if street:  # only if primary had street detail
        fb_parts = []
        if postal and city:
            fb_parts.append(f"{postal} {city}")
        elif city:
            fb_parts.append(city)
        elif postal:
            fb_parts.append(postal)
        fb_parts.append("Poland")
        fallback = ", ".join(fb_parts)

    return (primary, fallback)


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

def _load_cache(cache_path: Path) -> Dict[str, Any]:
    """Load geocode cache from JSON file."""
    if cache_path.exists():
        try:
            data = json.loads(cache_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except (json.JSONDecodeError, OSError) as e:
            log.warning("Geocode cache load error: %s", e)
    return {}


def _save_cache(cache_path: Path, cache: Dict[str, Any]) -> None:
    """Save geocode cache to JSON file."""
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(
            json.dumps(cache, ensure_ascii=False, indent=1),
            encoding="utf-8",
        )
    except OSError as e:
        log.warning("Geocode cache save error: %s", e)


def _cache_key(raw_address: str) -> str:
    """Normalize address for cache key (lowercase, stripped)."""
    return raw_address.strip().lower()


# ---------------------------------------------------------------------------
# Nominatim API
# ---------------------------------------------------------------------------

def _nominatim_search(query: str) -> Optional[Tuple[float, float]]:
    """Query Nominatim API. Returns (lat, lon) or None."""
    url = (
        f"{_NOMINATIM_URL}"
        f"?q={quote_plus(query)}"
        f"&format=json&countrycodes=pl&limit=1"
    )
    req = Request(url, headers={"User-Agent": _USER_AGENT})

    try:
        with urlopen(req, timeout=_REQUEST_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if data and isinstance(data, list) and len(data) > 0:
                lat = float(data[0]["lat"])
                lon = float(data[0]["lon"])
                return (lat, lon)
    except (URLError, OSError, json.JSONDecodeError, KeyError, ValueError) as e:
        log.debug("Nominatim query failed for %r: %s", query, e)

    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

_last_request_time: float = 0.0


def geocode_address(
    raw_address: str,
    cache_dir: Path,
) -> Optional[Tuple[float, float]]:
    """Geocode a single BTS address string.

    Args:
        raw_address: Raw BTS address (e.g. from Plus CSV billing).
        cache_dir: Directory containing geocode_cache.json.

    Returns:
        (lat, lon) tuple, or None if geocoding failed.
    """
    global _last_request_time

    if not raw_address or not raw_address.strip():
        return None

    cache_path = cache_dir / "geocode_cache.json"
    cache = _load_cache(cache_path)
    key = _cache_key(raw_address)

    # Check cache
    if key in cache:
        entry = cache[key]
        if entry is None:
            return None  # previously failed — negative cache
        return (entry["lat"], entry["lon"])

    # Build query
    primary, fallback = build_geocode_query(raw_address)

    # Rate limit
    elapsed = time.monotonic() - _last_request_time
    if elapsed < _RATE_LIMIT_SEC:
        time.sleep(_RATE_LIMIT_SEC - elapsed)

    # Try primary query
    result = _nominatim_search(primary)
    _last_request_time = time.monotonic()

    # Try fallback if primary failed
    if result is None and fallback:
        elapsed = time.monotonic() - _last_request_time
        if elapsed < _RATE_LIMIT_SEC:
            time.sleep(_RATE_LIMIT_SEC - elapsed)
        result = _nominatim_search(fallback)
        _last_request_time = time.monotonic()

    # Store in cache (None = negative cache)
    if result:
        cache[key] = {"lat": result[0], "lon": result[1]}
    else:
        cache[key] = None  # type: ignore[assignment]
        log.debug("Geocoding failed for: %r (query: %r)", raw_address, primary)

    _save_cache(cache_path, cache)

    return result


def geocode_batch(
    addresses: List[str],
    cache_dir: Path,
    progress_cb: Optional[Callable[[int, int], None]] = None,
) -> Dict[str, Tuple[float, float]]:
    """Geocode multiple BTS addresses in batch.

    Results are cached persistently — subsequent calls for the same
    addresses will return instantly from cache.

    Args:
        addresses: List of raw BTS address strings.
        cache_dir: Directory for geocode_cache.json.
        progress_cb: Optional callback(done, total) for progress reporting.

    Returns:
        Dict mapping raw_address → (lat, lon) for successfully geocoded
        addresses. Addresses that failed geocoding are omitted.
    """
    global _last_request_time

    if not addresses:
        return {}

    cache_path = cache_dir / "geocode_cache.json"
    cache = _load_cache(cache_path)

    # Deduplicate
    unique = list(dict.fromkeys(a.strip() for a in addresses if a and a.strip()))
    results: Dict[str, Tuple[float, float]] = {}

    # Split into cached and uncached
    to_fetch: List[str] = []
    for addr in unique:
        key = _cache_key(addr)
        if key in cache:
            entry = cache[key]
            if entry is not None:
                results[addr] = (entry["lat"], entry["lon"])
        else:
            to_fetch.append(addr)

    cached_count = len(unique) - len(to_fetch)
    if cached_count > 0:
        log.info("Geocode batch: %d/%d already cached", cached_count, len(unique))

    if not to_fetch:
        log.info("Geocode batch: all %d addresses cached, no API calls needed", len(unique))
        return results

    log.info("Geocode batch: fetching %d new addresses from Nominatim", len(to_fetch))

    for i, addr in enumerate(to_fetch):
        key = _cache_key(addr)
        primary, fallback = build_geocode_query(addr)

        # Rate limit
        elapsed = time.monotonic() - _last_request_time
        if elapsed < _RATE_LIMIT_SEC:
            time.sleep(_RATE_LIMIT_SEC - elapsed)

        result = _nominatim_search(primary)
        _last_request_time = time.monotonic()

        # Try fallback
        if result is None and fallback:
            elapsed = time.monotonic() - _last_request_time
            if elapsed < _RATE_LIMIT_SEC:
                time.sleep(_RATE_LIMIT_SEC - elapsed)
            result = _nominatim_search(fallback)
            _last_request_time = time.monotonic()

        if result:
            cache[key] = {"lat": result[0], "lon": result[1]}
            results[addr] = result
        else:
            cache[key] = None  # type: ignore[assignment]
            log.debug("Geocoding failed [%d/%d]: %r", i + 1, len(to_fetch), addr)

        if progress_cb:
            progress_cb(i + 1, len(to_fetch))

        # Save cache periodically (every 20 addresses)
        if (i + 1) % 20 == 0:
            _save_cache(cache_path, cache)

    # Final save
    _save_cache(cache_path, cache)

    success = len(results)
    failed = len(unique) - success
    log.info(
        "Geocode batch complete: %d/%d resolved (%d cached, %d fetched, %d failed)",
        success, len(unique), cached_count,
        success - cached_count, failed,
    )

    return results
