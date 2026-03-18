"""OFAC SDN Advanced XML crypto-address importer.

Downloads the official OFAC SDN_ADVANCED.XML file, extracts
"Digital Currency Address" records, and merges them into the
local sanctioned.json used by AISTATEweb risk rules.

Supports:
  - Online download from OFAC SLS API
  - Offline import from a local XML file
  - Export to sanctioned.json format (addresses + entities)
"""
from __future__ import annotations

import json
import logging
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

log = logging.getLogger("aistate.crypto.ofac")

DEFAULT_SOURCE_URL = (
    "https://sanctionslistservice.ofac.treas.gov/api/PublicationPreview/exports/SDN_ADVANCED.XML"
)
USER_AGENT = "AISTATEweb-OFAC-Importer/1.0 (+https://example.local)"
FEATURE_PREFIX = "Digital Currency Address - "

_CONFIG_DIR = Path(__file__).parent / "config"


@dataclass
class OFACAddressRecord:
    """Single sanctioned crypto address extracted from OFAC XML."""
    distinct_party_id: str
    party_name: str
    asset_symbol: str
    address: str
    feature_type_text: str
    extracted_at_utc: str


# ---------------------------------------------------------------------------
# XML helpers
# ---------------------------------------------------------------------------

def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _local_name(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[1]
    return tag


def _detect_namespace(root: ET.Element) -> Optional[str]:
    if root.tag.startswith("{") and "}" in root.tag:
        return root.tag[1:].split("}", 1)[0]
    return None


def _text_or_empty(value: Optional[str]) -> str:
    return (value or "").strip()


def _first_text(element: ET.Element, candidate_tags: Sequence[str]) -> str:
    wanted = set(candidate_tags)
    for node in element.iter():
        if _local_name(node.tag) in wanted:
            txt = _text_or_empty(node.text)
            if txt:
                return txt
    return ""


def _collect_texts(element: ET.Element, candidate_tags: Sequence[str]) -> List[str]:
    wanted = set(candidate_tags)
    values: List[str] = []
    seen: set = set()
    for node in element.iter():
        if _local_name(node.tag) in wanted:
            txt = _text_or_empty(node.text)
            if txt and txt not in seen:
                values.append(txt)
                seen.add(txt)
    return values


def _extract_party_name(distinct_party: ET.Element) -> str:
    direct = _first_text(distinct_party, [
        "WholeName", "OrganizationName", "VesselName",
        "AircraftName", "Name1", "Name",
    ])
    if direct:
        return direct

    parts = _collect_texts(distinct_party, [
        "NamePartValue", "FirstName", "MiddleName", "LastName",
        "Name2", "Name3", "Name4",
    ])
    if parts:
        return " ".join(parts[:8]).strip()

    aliases = _collect_texts(distinct_party, ["AliasWholeName", "AliasName", "Alias"])
    if aliases:
        return aliases[0]

    return ""


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------

def download_ofac_xml(
    destination: Path,
    url: str = DEFAULT_SOURCE_URL,
    timeout: int = 180,
) -> Path:
    """Download OFAC SDN_ADVANCED.XML to a local file."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    log.info("Downloading OFAC XML from %s", url)
    with urllib.request.urlopen(req, timeout=timeout) as response, \
         destination.open("wb") as fh:
        total = 0
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            fh.write(chunk)
            total += len(chunk)
    log.info("OFAC XML saved: %s (%d bytes)", destination, total)
    return destination


# ---------------------------------------------------------------------------
# Parse & extract
# ---------------------------------------------------------------------------

def parse_ofac_xml(xml_path: Path, source_url: str = DEFAULT_SOURCE_URL) -> List[OFACAddressRecord]:
    """Parse OFAC SDN_ADVANCED.XML and extract all crypto address records."""
    tree = ET.parse(xml_path)
    root = tree.getroot()

    ns = _detect_namespace(root)
    if ns is None:
        raise ValueError("Nie udało się wykryć namespace w pliku XML OFAC.")

    # Build feature type map (ID → (asset_symbol, full_text))
    feature_map: Dict[str, Tuple[str, str]] = {}
    ref_parent = root.find(f"{{{ns}}}ReferenceValueSets")
    search_root = ref_parent if ref_parent is not None else root

    for node in search_root.iter():
        node_id = node.attrib.get("ID", "").strip()
        txt = _text_or_empty(node.text)
        if not node_id or not txt.startswith(FEATURE_PREFIX):
            continue
        asset_symbol = txt[len(FEATURE_PREFIX):].strip()
        if asset_symbol:
            feature_map[node_id] = (asset_symbol, txt)

    if not feature_map:
        raise ValueError("Nie znaleziono w XML pól typu 'Digital Currency Address - ...'.")

    extracted_at = _utc_now_iso()
    records: List[OFACAddressRecord] = []
    dedupe: set = set()

    for distinct_party in root.findall(f".//{{{ns}}}DistinctParty"):
        party_id = (_text_or_empty(distinct_party.attrib.get("ID")) or
                    _text_or_empty(distinct_party.attrib.get("DistinctPartyID")))
        party_name = _extract_party_name(distinct_party)

        for feature in distinct_party.iter():
            feature_type_id = _text_or_empty(feature.attrib.get("FeatureTypeID"))
            if not feature_type_id or feature_type_id not in feature_map:
                continue

            asset_symbol, feature_text = feature_map[feature_type_id]

            values: List[str] = []
            for version_detail in feature.iter():
                if _local_name(version_detail.tag) == "VersionDetail":
                    txt = _text_or_empty(version_detail.text)
                    if txt:
                        values.append(txt)

            if not values:
                txt = _text_or_empty(feature.text)
                if txt:
                    values.append(txt)

            for address in values:
                dedupe_key = (asset_symbol.upper(), address.lower())
                if dedupe_key in dedupe:
                    continue
                dedupe.add(dedupe_key)
                records.append(OFACAddressRecord(
                    distinct_party_id=party_id,
                    party_name=party_name,
                    asset_symbol=asset_symbol,
                    address=address,
                    feature_type_text=feature_text,
                    extracted_at_utc=extracted_at,
                ))

    records.sort(key=lambda r: (r.asset_symbol, r.address))
    log.info("Parsed OFAC XML: %d crypto address records", len(records))
    return records


# ---------------------------------------------------------------------------
# Merge into sanctioned.json
# ---------------------------------------------------------------------------

# Map OFAC asset symbols to chain names used by AISTATEweb
_ASSET_TO_CHAIN: Dict[str, str] = {
    "XBT": "bitcoin",
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "USDT": "ethereum",
    "USDC": "ethereum",
    "XMR": "monero",
    "ZEC": "zcash",
    "LTC": "litecoin",
    "DASH": "dash",
    "BSV": "bitcoin_sv",
    "BCH": "bitcoin_cash",
    "XRP": "ripple",
    "TRX": "tron",
    "ARB": "arbitrum",
    "MATIC": "polygon",
    "SOL": "solana",
    "AVAX": "avalanche",
}


def merge_into_sanctioned(
    records: List[OFACAddressRecord],
    existing_path: Optional[Path] = None,
    replace: bool = False,
) -> Dict[str, Any]:
    """Merge OFAC records into sanctioned.json format.

    Args:
        records: Parsed OFAC address records
        existing_path: Path to existing sanctioned.json (if None, uses default)
        replace: If True, replace all OFAC-sourced addresses. If False, merge.

    Returns:
        Complete sanctioned.json dict ready to be saved.
    """
    config_path = existing_path or (_CONFIG_DIR / "sanctioned.json")
    existing: Dict[str, Any] = {"addresses": {}, "entities": {}}

    if config_path.exists() and not replace:
        try:
            existing = json.loads(config_path.read_text(encoding="utf-8"))
        except Exception as e:
            log.warning("Failed to load existing sanctioned.json: %s", e)

    addresses = existing.get("addresses", {})
    entities = existing.get("entities", {})

    # If replacing, remove all OFAC-sourced entries
    if replace:
        addresses = {
            k: v for k, v in addresses.items()
            if not (isinstance(v, dict) and "OFAC" in str(v.get("reason", "")))
        }

    # Collect entities from records
    entity_names: Dict[str, Dict[str, Any]] = {}

    for rec in records:
        addr_lower = rec.address.lower().strip()
        chain = _ASSET_TO_CHAIN.get(rec.asset_symbol.upper(), rec.asset_symbol.lower())

        addresses[addr_lower] = {
            "entity": rec.party_name or "Unknown (OFAC)",
            "reason": f"OFAC SDN — {rec.feature_type_text}",
            "chain": chain,
            "asset": rec.asset_symbol,
            "party_id": rec.distinct_party_id,
        }

        # Track entity
        if rec.party_name:
            ent_key = rec.party_name.lower().replace(" ", "_").replace(".", "")
            if ent_key not in entity_names:
                entity_names[ent_key] = {
                    "name": rec.party_name,
                    "type": "sanctioned",
                    "chains": set(),
                    "sanctioned_by": "OFAC",
                }
            entity_names[ent_key]["chains"].add(chain)

    # Merge entities
    for key, ent in entity_names.items():
        ent["chains"] = sorted(ent["chains"])
        entities[key] = ent

    result = {
        "_comment": "OFAC SDN sanctioned crypto addresses — auto-imported by AISTATEweb",
        "_last_update": _utc_now_iso(),
        "_ofac_records": len(records),
        "addresses": addresses,
        "entities": entities,
    }

    return result


def save_sanctioned(data: Dict[str, Any], path: Optional[Path] = None) -> Path:
    """Save sanctioned.json to disk."""
    config_path = path or (_CONFIG_DIR / "sanctioned.json")
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    log.info("Saved sanctioned.json: %s (%d addresses)",
             config_path, len(data.get("addresses", {})))
    return config_path


# ---------------------------------------------------------------------------
# High-level operations (used by API endpoints)
# ---------------------------------------------------------------------------

def download_and_import(
    url: str = DEFAULT_SOURCE_URL,
    replace: bool = True,
) -> Dict[str, Any]:
    """Download OFAC XML, parse, merge into sanctioned.json, save.

    Returns summary dict with stats.
    """
    import tempfile
    import os

    with tempfile.NamedTemporaryFile(delete=False, suffix=".xml") as tmp:
        tmp_path = Path(tmp.name)

    try:
        download_ofac_xml(tmp_path, url=url)
        records = parse_ofac_xml(tmp_path, source_url=url)

        merged = merge_into_sanctioned(records, replace=replace)
        save_path = save_sanctioned(merged)

        # Invalidate risk_rules cache
        _invalidate_cache()

        # Count by asset
        by_asset: Dict[str, int] = {}
        for rec in records:
            by_asset[rec.asset_symbol] = by_asset.get(rec.asset_symbol, 0) + 1

        return {
            "status": "ok",
            "total_addresses": len(records),
            "unique_addresses": len(merged.get("addresses", {})),
            "entities": len(merged.get("entities", {})),
            "by_asset": by_asset,
            "save_path": str(save_path),
            "source_url": url,
        }
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass


def import_from_file(xml_path: Path, replace: bool = True) -> Dict[str, Any]:
    """Import from a local OFAC XML file."""
    if not xml_path.exists():
        raise FileNotFoundError(f"OFAC XML nie istnieje: {xml_path}")

    records = parse_ofac_xml(xml_path)
    merged = merge_into_sanctioned(records, replace=replace)
    save_path = save_sanctioned(merged)

    # Invalidate cache
    _invalidate_cache()

    by_asset: Dict[str, int] = {}
    for rec in records:
        by_asset[rec.asset_symbol] = by_asset.get(rec.asset_symbol, 0) + 1

    return {
        "status": "ok",
        "total_addresses": len(records),
        "unique_addresses": len(merged.get("addresses", {})),
        "entities": len(merged.get("entities", {})),
        "by_asset": by_asset,
        "save_path": str(save_path),
    }


def get_ofac_stats() -> Dict[str, Any]:
    """Get current OFAC sanctioned.json statistics."""
    config_path = _CONFIG_DIR / "sanctioned.json"
    if not config_path.exists():
        return {
            "loaded": False,
            "address_count": 0,
            "entity_count": 0,
            "last_update": None,
            "by_chain": {},
        }

    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
        addresses = data.get("addresses", {})
        entities = data.get("entities", {})
        last_update = data.get("_last_update")
        ofac_records = data.get("_ofac_records", 0)

        by_chain: Dict[str, int] = {}
        by_asset: Dict[str, int] = {}
        for addr, info in addresses.items():
            if isinstance(info, dict):
                chain = info.get("chain", "unknown")
                by_chain[chain] = by_chain.get(chain, 0) + 1
                asset = info.get("asset", "")
                if asset:
                    by_asset[asset] = by_asset.get(asset, 0) + 1

        return {
            "loaded": True,
            "address_count": len(addresses),
            "entity_count": len(entities),
            "last_update": last_update,
            "ofac_records": ofac_records,
            "by_chain": by_chain,
            "by_asset": by_asset,
            "file_size_kb": round(config_path.stat().st_size / 1024, 1),
        }
    except Exception as e:
        log.warning("Failed to get OFAC stats: %s", e)
        return {
            "loaded": False,
            "address_count": 0,
            "entity_count": 0,
            "error": str(e),
        }


def _invalidate_cache() -> None:
    """Clear the cached sanctioned data so risk_rules reloads on next use."""
    try:
        from backend.crypto.risk_rules import _SANCTIONED
        import backend.crypto.risk_rules as rr
        rr._SANCTIONED = None
    except Exception:
        pass
