"""Tests for AML module: normalize, rules, memory, graph, baseline, report."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path):
    """Each test gets its own database."""
    from backend.db import engine
    db_path = tmp_path / "test_aml.db"
    engine.set_db_path(db_path)
    engine.init_db(db_path)
    yield
    engine._initialized = False
    engine._db_path = None


def _make_raw_transactions():
    """Create sample RawTransaction objects for testing."""
    from backend.finance.parsers.base import RawTransaction
    return [
        RawTransaction(
            date="2024-01-05", amount=-150.00, counterparty="BIEDRONKA WARSZAWA",
            title="Zakup kartą", bank_category="TR.KART", direction="out",
        ),
        RawTransaction(
            date="2024-01-07", amount=-500.00, counterparty="ZONDA SP Z O O",
            title="Przelew na giełdę kryptowalut", bank_category="PRZELEW", direction="out",
        ),
        RawTransaction(
            date="2024-01-10", amount=5000.00, counterparty="FIRMA XYZ SP Z O O",
            title="Wynagrodzenie za styczeń", bank_category="PRZELEW", direction="in",
        ),
        RawTransaction(
            date="2024-01-12", amount=-200.00, counterparty="STS ZAKLADY BUKMACHERSKIE",
            title="Depozyt", bank_category="PRZELEW", direction="out",
        ),
        RawTransaction(
            date="2024-01-15", amount=-30.00, counterparty="JAN KOWALSKI",
            title="Przelew na telefon", bank_category="P.BLIK", direction="out",
        ),
        RawTransaction(
            date="2024-01-18", amount=-800.00, counterparty="WSPÓLNOTA MIESZKANIOWA",
            title="Czynsz za styczeń", bank_category="ST.ZLEC", direction="out",
        ),
        RawTransaction(
            date="2024-01-20", amount=-50.00,
            counterparty="Płatność BLIK https://www.lotto.pl/",
            title="Zakup losu", bank_category="P.BLIK", direction="out",
        ),
        RawTransaction(
            date="2024-01-22", amount=-3000.00, counterparty="BANKOMAT WARSZAWA",
            title="Wypłata gotówkowa", direction="out",
        ),
    ]


class TestNormalize:
    def test_normalize_transactions(self):
        from backend.aml.normalize import normalize_transactions
        raw = _make_raw_transactions()
        normalized = normalize_transactions(raw, statement_id="stmt_001")

        assert len(normalized) == 8
        assert all(n.tx_hash for n in normalized)  # all have hashes
        assert all(n.statement_id == "stmt_001" for n in normalized)

    def test_deduplication(self):
        from backend.aml.normalize import normalize_transactions
        from backend.finance.parsers.base import RawTransaction

        # Duplicate transactions
        tx = RawTransaction(date="2024-01-05", amount=-100.0, counterparty="TEST", title="DUP")
        normalized = normalize_transactions([tx, tx, tx])
        assert len(normalized) == 1

    def test_channel_detection(self):
        from backend.aml.normalize import detect_channel
        assert detect_channel("TR.KART", "", "") == "CARD"
        assert detect_channel("P.BLIK", "Przelew na telefon", "") == "BLIK_P2P"
        assert detect_channel("P.BLIK", "Zakup w sklepie", "") == "BLIK_MERCHANT"
        assert detect_channel("ST.ZLEC", "", "") == "TRANSFER"
        assert detect_channel("", "Bankomat", "") == "CASH"
        assert detect_channel("OPŁATA", "", "") == "FEE"

    def test_url_extraction(self):
        from backend.aml.normalize import extract_urls
        urls = extract_urls("Płatność BLIK https://www.lotto.pl/ za los")
        assert urls == ["https://www.lotto.pl/"]

    def test_amount_decimal(self):
        from backend.aml.normalize import to_decimal
        assert to_decimal(150.00) == Decimal("150.00")
        assert to_decimal(-0.01) == Decimal("-0.01")


class TestRules:
    def test_classify_crypto(self):
        from backend.aml.normalize import normalize_transactions
        from backend.aml.rules import classify_transaction
        from backend.finance.parsers.base import RawTransaction

        tx = RawTransaction(
            date="2024-01-07", amount=-500.0,
            counterparty="ZONDA SP Z O O",
            title="Przelew", direction="out",
        )
        normalized = normalize_transactions([tx])
        result = classify_transaction(normalized[0])
        assert "crypto" in result.risk_tags
        assert result.explains  # has explanation
        assert any("zonda" in e["pattern"] for e in result.explains)

    def test_classify_gambling(self):
        from backend.aml.normalize import normalize_transactions
        from backend.aml.rules import classify_transaction
        from backend.finance.parsers.base import RawTransaction

        tx = RawTransaction(
            date="2024-01-12", amount=-200.0,
            counterparty="STS ZAKLADY",
            title="Depozyt", direction="out",
        )
        normalized = normalize_transactions([tx])
        result = classify_transaction(normalized[0])
        assert "gambling" in result.risk_tags

    def test_whitelist_reduces_score(self):
        from backend.aml.normalize import normalize_transactions
        from backend.aml.rules import classify_transaction
        from backend.finance.parsers.base import RawTransaction

        tx = RawTransaction(
            date="2024-01-10", amount=5000.0,
            counterparty="FIRMA XYZ",
            title="Wynagrodzenie", direction="in",
        )
        normalized = normalize_transactions([tx])
        result = classify_transaction(normalized[0], counterparty_label="whitelist")
        assert result.is_whitelisted
        # Whitelist bonus is -10, but score is clamped to 0 minimum
        assert result.risk_score == 0
        assert any(e["rule"] == "memory:whitelist" for e in result.explains)

    def test_blacklist_increases_score(self):
        from backend.aml.normalize import normalize_transactions
        from backend.aml.rules import classify_transaction
        from backend.finance.parsers.base import RawTransaction

        tx = RawTransaction(
            date="2024-01-05", amount=-100.0,
            counterparty="PODEJRZANY",
            title="Przelew", direction="out",
        )
        normalized = normalize_transactions([tx])
        result = classify_transaction(normalized[0], counterparty_label="blacklist")
        assert result.is_blacklisted
        assert "BLACKLISTED" in result.risk_tags
        assert result.risk_score > 0


class TestMemory:
    def test_create_and_search(self):
        from backend.aml.memory import create_counterparty, search_counterparties

        cp = create_counterparty("BIEDRONKA SP Z O O", label="whitelist", note="Sklep spożywczy")
        assert cp is not None
        assert cp["label"] == "whitelist"

        results = search_counterparties(query="biedronka")
        assert len(results) >= 1
        assert results[0]["canonical_name"] == "BIEDRONKA SP Z O O"

    def test_entity_resolution_exact(self):
        from backend.aml.memory import create_counterparty, resolve_entity

        create_counterparty("JAN KOWALSKI")
        cp_id, conf = resolve_entity("Jan Kowalski")
        assert cp_id  # should find existing
        assert conf >= 0.9  # high confidence

    def test_entity_resolution_new(self):
        from backend.aml.memory import resolve_entity

        cp_id, conf = resolve_entity("NOWY KONTRAHENT XYZ")
        assert cp_id  # creates new
        assert conf == 0.5  # default confidence

    def test_update_label(self):
        from backend.aml.memory import create_counterparty, get_counterparty, update_counterparty

        cp = create_counterparty("TEST FIRMA")
        updated = update_counterparty(cp["id"], label="blacklist", note="Podejrzana")
        assert updated["label"] == "blacklist"
        assert updated["note"] == "Podejrzana"

    def test_add_alias(self):
        from backend.aml.memory import add_alias, create_counterparty, resolve_entity

        cp = create_counterparty("ORLEN S.A.")
        add_alias(cp["id"], "PKN ORLEN")

        # Should resolve via alias
        found_id, conf = resolve_entity("PKN ORLEN")
        assert found_id == cp["id"]

    def test_learning_queue(self):
        from backend.aml.memory import (
            add_to_learning_queue,
            get_learning_queue,
            resolve_learning_item,
        )

        item_id = add_to_learning_queue("NIEZNANA FIRMA", "risky", ["tx1", "tx2"])
        queue = get_learning_queue()
        assert len(queue) >= 1
        assert queue[0]["suggested_name"] == "NIEZNANA FIRMA"

        resolve_learning_item(item_id, "approved", label="blacklist", note="Potwierdzone")
        queue = get_learning_queue(status="pending")
        assert len(queue) == 0


class TestGraph:
    def test_build_graph(self):
        from backend.aml.graph import build_graph
        from backend.aml.normalize import normalize_transactions

        raw = _make_raw_transactions()
        normalized = normalize_transactions(raw)
        graph = build_graph(normalized, save_to_db=False)

        assert graph["stats"]["total_nodes"] > 1  # at least account + counterparties
        assert graph["stats"]["total_edges"] > 0
        # Account node always present
        account_nodes = [n for n in graph["nodes"] if n["type"] == "ACCOUNT"]
        assert len(account_nodes) == 1

    def test_graph_risk_levels(self):
        from backend.aml.graph import build_graph
        from backend.aml.normalize import normalize_transactions

        raw = _make_raw_transactions()
        normalized = normalize_transactions(raw)
        # Manually set risk for testing
        for tx in normalized:
            if "ZONDA" in tx.counterparty_raw.upper():
                tx.risk_tags = ["crypto"]
        graph = build_graph(normalized, save_to_db=False)

        high_risk_nodes = [n for n in graph["nodes"] if n["risk_level"] == "high"]
        assert len(high_risk_nodes) >= 1


class TestBaseline:
    def test_build_baseline(self):
        from backend.aml.baseline import build_baseline
        from backend.aml.normalize import normalize_transactions

        raw = _make_raw_transactions()
        normalized = normalize_transactions(raw)
        baseline = build_baseline(normalized)

        assert "2024-01" in baseline
        profile = baseline["2024-01"]
        assert profile.tx_count == 8
        assert profile.total_credit > 0
        assert profile.total_debit > 0

    def test_detect_outlier(self):
        from backend.aml.baseline import detect_anomalies
        from backend.aml.normalize import NormalizedTransaction, to_decimal
        from backend.db.engine import new_id

        # Create baseline with small transactions
        small_txns = [
            NormalizedTransaction(
                id=new_id(), booking_date="2024-01-01",
                amount=to_decimal(-50), direction="DEBIT",
                counterparty_clean="SHOP", channel="CARD",
            )
            for _ in range(20)
        ]
        # Add one massive outlier
        outlier = NormalizedTransaction(
            id=new_id(), booking_date="2024-01-25",
            amount=to_decimal(-50000), direction="DEBIT",
            counterparty_clean="NOWY KONTRAHENT", channel="TRANSFER",
        )
        all_txns = small_txns + [outlier]

        alerts = detect_anomalies(all_txns)
        outlier_alerts = [a for a in alerts if a.alert_type == "LARGE_OUTLIER"]
        assert len(outlier_alerts) >= 1


class TestReport:
    def test_generate_report_html(self):
        from backend.aml.baseline import AnomalyAlert
        from backend.aml.normalize import normalize_transactions
        from backend.aml.report import generate_report

        raw = _make_raw_transactions()
        normalized = normalize_transactions(raw)
        alerts = [
            AnomalyAlert("LARGE_OUTLIER", "high", 20, "Duża kwota"),
            AnomalyAlert("P2P_BURST", "medium", 15, "Wiele przelewów"),
        ]
        graph = {"nodes": [], "edges": [], "stats": {"total_nodes": 0, "total_edges": 0}}

        html = generate_report(
            transactions=normalized,
            alerts=alerts,
            graph_data=graph,
            risk_score=45.0,
            statement_info={"bank_name": "ING Bank Śląski", "period_from": "2024-01-01", "period_to": "2024-01-31"},
        )

        assert "<!DOCTYPE html>" in html
        assert "ING Bank" in html
        assert "LARGE_OUTLIER" in html
        assert "45" in html  # risk score
        assert "BIEDRONKA" in html  # transaction

    def test_report_has_audit_trail(self):
        from backend.aml.normalize import normalize_transactions
        from backend.aml.report import generate_report

        raw = _make_raw_transactions()
        normalized = normalize_transactions(raw)
        html = generate_report(
            transactions=normalized,
            alerts=[],
            graph_data={"nodes": [], "edges": [], "stats": {}},
            audit_info={"pdf_hash": "abc123def456", "rules_version": "1.0.0", "ocr_used": False},
        )
        assert "abc123def456" in html
        assert "1.0.0" in html


class TestSanityCheck:
    """Balance sanity checks — critical for AML accuracy."""

    def test_balance_chain_valid(self):
        from backend.finance.parsers.base import RawTransaction, validate_balance_chain

        txns = [
            RawTransaction(date="2024-01-01", amount=-100.0, balance_after=900.0),
            RawTransaction(date="2024-01-02", amount=200.0, balance_after=1100.0),
            RawTransaction(date="2024-01-03", amount=-50.0, balance_after=1050.0),
        ]
        valid, warnings = validate_balance_chain(txns, 1000.0, 1050.0)
        assert valid is True
        assert not any("ROZBIEŻNOŚĆ" in w for w in warnings)

    def test_balance_chain_invalid(self):
        from backend.finance.parsers.base import RawTransaction, validate_balance_chain

        txns = [
            RawTransaction(date="2024-01-01", amount=-100.0, balance_after=900.0),
            RawTransaction(date="2024-01-02", amount=200.0, balance_after=1100.0),
        ]
        # Closing balance doesn't match
        valid, warnings = validate_balance_chain(txns, 1000.0, 2000.0)
        assert valid is False
        assert any("ROZBIEŻNOŚĆ" in w for w in warnings)

    def test_declared_sums_match(self):
        from backend.finance.parsers.base import RawTransaction, validate_balance_chain

        txns = [
            RawTransaction(date="2024-01-01", amount=500.0),
            RawTransaction(date="2024-01-02", amount=-200.0),
        ]
        valid, warnings = validate_balance_chain(
            txns, 1000.0, 1300.0,
            declared_credits_sum=500.0,
            declared_debits_sum=200.0,
            declared_credits_count=1,
            declared_debits_count=1,
        )
        assert valid is True
