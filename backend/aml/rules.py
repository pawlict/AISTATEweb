"""Deterministic AML rules engine with explainability.

Loads rules from YAML config, classifies transactions by channel/category/risk,
and returns explanations for every decision.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .normalize import NormalizedTransaction, strip_diacritics

log = logging.getLogger("aistate.aml.rules")

_RULES_DIR = Path(__file__).parent / "config"
_rules_cache: Optional[Dict[str, Any]] = None


def _load_yaml(path: Path) -> Dict[str, Any]:
    """Load YAML config (with fallback to JSON if PyYAML not available)."""
    try:
        import yaml
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except ImportError:
        import json
        # Fallback: try JSON version
        json_path = path.with_suffix(".json")
        if json_path.exists():
            return json.loads(json_path.read_text(encoding="utf-8"))
        log.warning("PyYAML not installed and no JSON fallback for %s", path)
        return {}


def load_rules(config_path: Optional[Path] = None) -> Dict[str, Any]:
    """Load and cache rules configuration."""
    global _rules_cache
    if _rules_cache is not None:
        return _rules_cache

    if config_path is None:
        config_path = _RULES_DIR / "rules.yaml"

    if not config_path.exists():
        log.warning("Rules config not found: %s", config_path)
        _rules_cache = _default_rules()
        return _rules_cache

    _rules_cache = _load_yaml(config_path)
    log.info("Loaded %d rule categories from %s", len(_rules_cache.get("categories", {})), config_path)
    return _rules_cache


def reload_rules(config_path: Optional[Path] = None) -> Dict[str, Any]:
    """Force reload rules (for hot-reload)."""
    global _rules_cache
    _rules_cache = None
    return load_rules(config_path)


def _default_rules() -> Dict[str, Any]:
    """Minimal built-in rules if config file is missing."""
    return {
        "version": "1.0.0",
        "scoring": {
            "CRYPTO_RELATED": 25,
            "GAMBLING": 30,
            "LARGE_OUTLIER": 20,
            "NEW_COUNTERPARTY_LARGE": 15,
            "P2P_BURST": 15,
            "CASH_CLUSTER": 10,
            "SPENDING_OVER_INCOME": 10,
            "WHITELIST_MATCH": -10,
            "BLACKLIST_MATCH": 30,
        },
        "categories": {},
        "risk_dictionary": {},
    }


class RuleResult:
    """Result of applying rules to a transaction."""
    __slots__ = (
        "category", "subcategory", "risk_tags", "risk_score",
        "explains", "is_whitelisted", "is_blacklisted",
    )

    def __init__(
        self,
        category: str = "",
        subcategory: str = "",
        risk_tags: Optional[List[str]] = None,
        risk_score: float = 0.0,
        explains: Optional[List[Dict[str, str]]] = None,
        is_whitelisted: bool = False,
        is_blacklisted: bool = False,
    ):
        self.category = category
        self.subcategory = subcategory
        self.risk_tags = risk_tags or []
        self.risk_score = risk_score
        self.explains = explains or []
        self.is_whitelisted = is_whitelisted
        self.is_blacklisted = is_blacklisted


def classify_transaction(
    tx: NormalizedTransaction,
    counterparty_label: str = "neutral",
    counterparty_note: str = "",
) -> RuleResult:
    """Apply all rules to a single transaction.

    Args:
        tx: Normalized transaction
        counterparty_label: From memory: neutral/whitelist/blacklist
        counterparty_note: User note for context

    Returns:
        RuleResult with category, risk_tags, score, and explains.
    """
    rules = load_rules()
    result = RuleResult()
    search_text = f"{tx.counterparty_clean} {tx.title_clean} {tx.raw_text}".lower()
    search_ascii = strip_diacritics(search_text)

    # --- Category rules (from config) ---
    categories = rules.get("categories", {})
    for cat_name, cat_data in categories.items():
        if not isinstance(cat_data, dict):
            continue
        for subcat_name, patterns in cat_data.items():
            if subcat_name.startswith("_"):
                continue
            if not isinstance(patterns, list):
                continue
            for pattern in patterns:
                try:
                    if re.search(pattern, search_text, re.I) or re.search(pattern, search_ascii, re.I):
                        result.category = result.category or cat_name
                        result.subcategory = result.subcategory or f"{cat_name}:{subcat_name}"
                        if cat_name not in result.risk_tags:
                            result.risk_tags.append(cat_name)
                        result.explains.append({
                            "rule": f"category:{cat_name}:{subcat_name}",
                            "pattern": pattern,
                            "matched": cat_name,
                        })
                        break  # one match per subcategory is enough
                except re.error:
                    continue

    # --- Risk dictionary (from config) ---
    risk_dict = rules.get("risk_dictionary", {})
    for risk_name, risk_patterns in risk_dict.items():
        if not isinstance(risk_patterns, list):
            continue
        for pattern in risk_patterns:
            try:
                if re.search(pattern, search_text, re.I) or re.search(pattern, search_ascii, re.I):
                    tag = f"RISK:{risk_name}"
                    if tag not in result.risk_tags:
                        result.risk_tags.append(tag)
                    result.explains.append({
                        "rule": f"risk:{risk_name}",
                        "pattern": pattern,
                        "matched": risk_name,
                    })
                    break
            except re.error:
                continue

    # --- URL-based classification ---
    for url in tx.urls:
        domain = _extract_domain(url)
        url_cats = rules.get("url_domains", {})
        if domain in url_cats:
            cat_info = url_cats[domain]
            cat = cat_info.get("category", "")
            sub = cat_info.get("subcategory", "")
            if cat and cat not in result.risk_tags:
                result.risk_tags.append(cat)
            result.category = result.category or cat
            result.subcategory = result.subcategory or f"{cat}:{sub}"
            result.explains.append({
                "rule": f"url_domain:{domain}",
                "pattern": url,
                "matched": f"{cat}:{sub}",
            })

    # --- Counterparty memory influence ---
    if counterparty_label == "whitelist":
        result.is_whitelisted = True
        scoring = rules.get("scoring", {})
        result.risk_score += scoring.get("WHITELIST_MATCH", -10)
        result.explains.append({
            "rule": "memory:whitelist",
            "pattern": "",
            "matched": "whitelist",
        })
    elif counterparty_label == "blacklist":
        result.is_blacklisted = True
        scoring = rules.get("scoring", {})
        result.risk_score += scoring.get("BLACKLIST_MATCH", 30)
        result.risk_tags.append("BLACKLISTED")
        result.explains.append({
            "rule": "memory:blacklist",
            "pattern": counterparty_note,
            "matched": "blacklist",
        })

    # --- Scoring from config ---
    scoring = rules.get("scoring", {})
    for tag in result.risk_tags:
        tag_upper = tag.upper().replace(":", "_")
        if tag_upper in scoring:
            result.risk_score += scoring[tag_upper]
        elif tag_upper.replace("RISK_", "") in scoring:
            result.risk_score += scoring[tag_upper.replace("RISK_", "")]

    # Clamp score
    result.risk_score = max(0, min(100, result.risk_score))

    return result


def classify_all(
    transactions: List[NormalizedTransaction],
    counterparty_labels: Optional[Dict[str, str]] = None,
    counterparty_notes: Optional[Dict[str, str]] = None,
) -> List[Tuple[NormalizedTransaction, RuleResult]]:
    """Classify all transactions. Returns list of (tx, result) tuples."""
    labels = counterparty_labels or {}
    notes = counterparty_notes or {}

    results = []
    for tx in transactions:
        cp_key = tx.counterparty_clean.lower()
        label = labels.get(cp_key, "neutral")
        note = notes.get(cp_key, "")
        rule_result = classify_transaction(tx, label, note)

        # Apply classification back to transaction
        tx.category = rule_result.category
        tx.subcategory = rule_result.subcategory
        tx.risk_tags = rule_result.risk_tags
        tx.risk_score = rule_result.risk_score
        tx.rule_explains = rule_result.explains

        results.append((tx, rule_result))

    return results


def _extract_domain(url: str) -> str:
    """Extract domain from URL."""
    url = url.lower().rstrip("/")
    if "://" in url:
        url = url.split("://", 1)[1]
    domain = url.split("/")[0].split(":")[0]
    return domain


def compute_risk_score(
    transactions: List[NormalizedTransaction],
    rules_config: Optional[Dict[str, Any]] = None,
) -> Tuple[float, List[Dict[str, Any]]]:
    """Compute aggregate risk score (0-100) for a set of transactions.

    Returns:
        (total_score, risk_reasons)
    """
    if rules_config is None:
        rules_config = load_rules()

    scoring = rules_config.get("scoring", {})
    reasons: List[Dict[str, Any]] = []
    score = 0.0

    # Count risk tags across all transactions
    tag_counts: Dict[str, int] = {}
    tag_amounts: Dict[str, float] = {}
    tag_tx_ids: Dict[str, List[str]] = {}

    for tx in transactions:
        for tag in tx.risk_tags:
            tag_upper = tag.upper()
            tag_counts[tag_upper] = tag_counts.get(tag_upper, 0) + 1
            tag_amounts[tag_upper] = tag_amounts.get(tag_upper, 0) + float(abs(tx.amount))
            if tag_upper not in tag_tx_ids:
                tag_tx_ids[tag_upper] = []
            tag_tx_ids[tag_upper].append(tx.id)

    total_amount = sum(float(abs(tx.amount)) for tx in transactions)

    for tag, count in tag_counts.items():
        weight = scoring.get(tag, 0)
        if not weight:
            # Try without prefix
            clean_tag = tag.replace("RISK:", "").replace("RISK_", "")
            weight = scoring.get(clean_tag, 0)

        if weight > 0:
            pct = (tag_amounts.get(tag, 0) / total_amount * 100) if total_amount > 0 else 0
            # Scale weight by prevalence
            effective = min(weight, weight * (pct / 10)) if pct < 10 else weight
            score += effective
            reasons.append({
                "tag": tag,
                "count": count,
                "amount": round(tag_amounts.get(tag, 0), 2),
                "pct_of_total": round(pct, 1),
                "score_delta": round(effective, 1),
                "evidence_tx_ids": tag_tx_ids.get(tag, [])[:10],
            })

    score = max(0, min(100, score))
    reasons.sort(key=lambda r: -r["score_delta"])
    return score, reasons
