"""Tests for ING parser transaction segmentation.

Focuses on _lookbehind_for_contractor and _segment_transactions to verify
correct boundary detection between adjacent transactions in various ING
statement layouts.
"""

from __future__ import annotations

import pytest

from backend.finance.parsers.ing import INGParser


def _make_items(specs):
    """Build a list of items from compact specs.

    Each spec is a tuple: (page, y0, x0, col, text)
    """
    return [
        {"page": p, "y0": y, "x0": x, "col": col, "text": txt}
        for p, y, x, col, txt in specs
    ]


class TestLookbehindForContractor:
    """Unit tests for INGParser._lookbehind_for_contractor."""

    def test_layout_a_with_header(self):
        """Layout A: contractor block above dates with 'Nazwa i adres' header."""
        items = _make_items([
            # tx A contractor block
            (0, 50.0, 108.0, "contractor", "Nazwa i adres odbiorcy:"),
            (0, 55.0, 108.0, "contractor", "JAN KOWALSKI"),
            (0, 60.0, 108.0, "contractor", "UL. TESTOWA 1"),
            (0, 65.0, 108.0, "contractor", "12 1111 2222 3333 4444 5555 6666"),
            # tx A dates
            (0, 70.0, 40.0, "date", "15.01.2025"),
            (0, 75.0, 40.0, "date", "14.01.2025"),
            # tx A other columns
            (0, 70.0, 238.0, "title", "Przelew"),
            (0, 70.0, 491.0, "amount", "-500,00 PLN"),
        ])
        # Lookbehind from date at index 4 (y=70)
        start = INGParser._lookbehind_for_contractor(
            items, scan_from=4, lower_bound=0,
            ref_page=0, ref_y=70.0, y_lookbehind=8.0,
        )
        seg_texts = [items[i]["text"] for i in range(start, len(items))]
        assert "Nazwa i adres odbiorcy:" in seg_texts
        assert "JAN KOWALSKI" in seg_texts
        assert "12 1111 2222 3333 4444 5555 6666" in seg_texts

    def test_layout_b_contractor_below_dates(self):
        """Layout B: contractor lines appear at/below date Y position."""
        items = _make_items([
            # tx A dates
            (0, 100.0, 40.0, "date", "15.01.2025"),
            (0, 100.0, 108.0, "contractor", "JAN KOWALSKI"),
            (0, 100.0, 238.0, "title", "Przelew"),
            (0, 100.0, 491.0, "amount", "-500,00 PLN"),
            (0, 110.0, 40.0, "date", "14.01.2025"),
            # contractor below dates
            (0, 120.0, 108.0, "contractor", "UL. NOWA 5"),
            (0, 130.0, 108.0, "contractor", "12 1111 2222 3333 4444 5555 6666"),
        ])
        # Lookbehind from date at index 0 (y=100) — should grab items at same Y
        start = INGParser._lookbehind_for_contractor(
            items, scan_from=0, lower_bound=0,
            ref_page=0, ref_y=100.0, y_lookbehind=8.0,
        )
        # Start should be 0 (at the date itself, no items above)
        assert start == 0

    def test_two_txns_adjacent_contractor_blocks_with_nrb(self):
        """Test 5 scenario: two adjacent contractor blocks without clear separator.

        tx A has contractor lines BELOW its dates, tx B has contractor lines
        ABOVE its dates. No gap, header, or date row between them — only the
        NRB (account number) pattern serves as a boundary marker.
        """
        items = _make_items([
            # tx A: dates + contractor at same Y
            (0, 100.0, 40.0, "date", "15.01.2025"),
            (0, 100.0, 108.0, "contractor", "JAN KOWALSKI"),
            (0, 100.0, 238.0, "title", "Przelew"),
            (0, 100.0, 491.0, "amount", "-500,00 PLN"),
            (0, 110.0, 40.0, "date", "14.01.2025"),
            # tx A: contractor below dates (Layout B continuation)
            (0, 120.0, 108.0, "contractor", "UL. NOWA 5"),
            (0, 130.0, 108.0, "contractor", "12 1111 2222 3333 4444 5555 6666"),
            # tx B: contractor above dates (Layout A, no header)
            (0, 150.0, 108.0, "contractor", "ANNA NOWAK"),
            (0, 160.0, 108.0, "contractor", "98 7654 3210 0000 1111 2222 3333"),
            # tx B: dates
            (0, 180.0, 40.0, "date", "20.01.2025"),
            (0, 180.0, 238.0, "title", "Platnosc"),
            (0, 180.0, 491.0, "amount", "-100,00 PLN"),
            (0, 190.0, 40.0, "date", "19.01.2025"),
        ])

        # Lookbehind for tx B from date at index 9 (y=180),
        # lower_bound = 5 (after tx A's second date at index 4)
        start_b = INGParser._lookbehind_for_contractor(
            items, scan_from=9, lower_bound=5,
            ref_page=0, ref_y=180.0, y_lookbehind=8.0,
        )
        seg_b_texts = [items[i]["text"] for i in range(start_b, len(items))]

        # tx B should include its own contractor lines
        assert "ANNA NOWAK" in seg_b_texts
        assert "98 7654 3210 0000 1111 2222 3333" in seg_b_texts

        # tx B must NOT steal tx A's contractor lines
        assert "UL. NOWA 5" not in seg_b_texts, "tx B stole tx A's address line"
        assert "12 1111 2222 3333 4444 5555 6666" not in seg_b_texts, "tx B stole tx A's NRB"

    def test_cross_page_contractor(self):
        """Contractor block starts on previous page, dates on current page."""
        items = _make_items([
            # previous page items
            (0, 700.0, 108.0, "contractor", "Nazwa i adres nadawcy:"),
            (0, 710.0, 108.0, "contractor", "FIRMA ABC SP Z O O"),
            (0, 720.0, 108.0, "contractor", "UL. DLUGA 10 WARSZAWA"),
            (0, 730.0, 108.0, "contractor", "55 1234 5678 9012 3456 7890 1234"),
            # current page dates
            (1, 50.0, 40.0, "date", "01.02.2025"),
            (1, 55.0, 40.0, "date", "31.01.2025"),
            (1, 50.0, 238.0, "title", "Przelew przychodzacy"),
            (1, 50.0, 491.0, "amount", "+2500,00 PLN"),
        ])

        start = INGParser._lookbehind_for_contractor(
            items, scan_from=4, lower_bound=0,
            ref_page=1, ref_y=50.0, y_lookbehind=8.0,
        )
        seg_texts = [items[i]["text"] for i in range(start, len(items))]
        assert "Nazwa i adres nadawcy:" in seg_texts
        assert "FIRMA ABC SP Z O O" in seg_texts
        assert "55 1234 5678 9012 3456 7890 1234" in seg_texts

    def test_gap_stops_lookbehind(self):
        """A Y-gap > 20pt between contractor rows should stop lookbehind."""
        items = _make_items([
            # far-away contractor (belongs to previous tx)
            (0, 50.0, 108.0, "contractor", "OLD CONTRACTOR"),
            # gap of 25pt (> 20pt threshold)
            (0, 75.0, 108.0, "contractor", "CORRECT CONTRACTOR"),
            (0, 85.0, 108.0, "contractor", "22 3333 4444 5555 6666 7777 8888"),
            # dates
            (0, 100.0, 40.0, "date", "10.01.2025"),
            (0, 105.0, 40.0, "date", "09.01.2025"),
        ])

        start = INGParser._lookbehind_for_contractor(
            items, scan_from=3, lower_bound=0,
            ref_page=0, ref_y=100.0, y_lookbehind=8.0,
        )
        seg_texts = [items[i]["text"] for i in range(start, len(items))]
        assert "CORRECT CONTRACTOR" in seg_texts
        assert "OLD CONTRACTOR" not in seg_texts

    def test_single_nrb_not_blocked(self):
        """A single NRB in the contractor block should NOT trigger early stop."""
        items = _make_items([
            (0, 60.0, 108.0, "contractor", "ADAM NOWAK"),
            (0, 65.0, 108.0, "contractor", "UL. KRÓTKA 2"),
            (0, 70.0, 108.0, "contractor", "44 5555 6666 7777 8888 9999 0000"),
            # dates
            (0, 78.0, 40.0, "date", "05.01.2025"),
            (0, 83.0, 40.0, "date", "04.01.2025"),
        ])

        start = INGParser._lookbehind_for_contractor(
            items, scan_from=3, lower_bound=0,
            ref_page=0, ref_y=78.0, y_lookbehind=8.0,
        )
        seg_texts = [items[i]["text"] for i in range(start, len(items))]
        assert "ADAM NOWAK" in seg_texts
        assert "UL. KRÓTKA 2" in seg_texts
        assert "44 5555 6666 7777 8888 9999 0000" in seg_texts


class TestSegmentTransactions:
    """Integration tests for INGParser._segment_transactions."""

    def test_two_simple_transactions(self):
        """Two Layout A transactions with headers — basic case."""
        items = _make_items([
            # tx 1
            (0, 50.0, 108.0, "contractor", "Nazwa i adres odbiorcy:"),
            (0, 55.0, 108.0, "contractor", "SKLEP ABC"),
            (0, 60.0, 108.0, "contractor", "11 2222 3333 4444 5555 6666 7777"),
            (0, 70.0, 40.0, "date", "01.01.2025"),
            (0, 70.0, 238.0, "title", "Zakup"),
            (0, 70.0, 491.0, "amount", "-50,00 PLN"),
            (0, 75.0, 40.0, "date", "31.12.2024"),
            # tx 2
            (0, 100.0, 108.0, "contractor", "Nazwa i adres nadawcy:"),
            (0, 105.0, 108.0, "contractor", "FIRMA XYZ"),
            (0, 110.0, 108.0, "contractor", "88 9999 0000 1111 2222 3333 4444"),
            (0, 120.0, 40.0, "date", "02.01.2025"),
            (0, 120.0, 238.0, "title", "Wyplata"),
            (0, 120.0, 491.0, "amount", "+3000,00 PLN"),
            (0, 125.0, 40.0, "date", "01.01.2025"),
        ])

        parser = INGParser()
        segments = parser._segment_transactions(items, y_lookbehind=8.0)

        assert len(segments) == 2

        seg1_texts = [it["text"] for it in segments[0]]
        seg2_texts = [it["text"] for it in segments[1]]

        # tx 1 should have its contractor and data
        assert "SKLEP ABC" in seg1_texts
        assert "11 2222 3333 4444 5555 6666 7777" in seg1_texts
        assert "-50,00 PLN" in seg1_texts

        # tx 2 should have its own contractor, not tx 1's
        assert "FIRMA XYZ" in seg2_texts
        assert "88 9999 0000 1111 2222 3333 4444" in seg2_texts
        assert "+3000,00 PLN" in seg2_texts

        # No cross-contamination
        assert "SKLEP ABC" not in seg2_texts
        assert "FIRMA XYZ" not in seg1_texts

    def test_adjacent_contractor_blocks_no_separator(self):
        """Two transactions: tx A has contractor below dates (Layout B),
        tx B has contractor above dates (Layout A, no header).
        NRB pattern should prevent cross-contamination."""
        items = _make_items([
            # tx A: dates + inline contractor
            (0, 100.0, 40.0, "date", "15.01.2025"),
            (0, 100.0, 108.0, "contractor", "JAN KOWALSKI"),
            (0, 100.0, 238.0, "title", "Przelew"),
            (0, 100.0, 491.0, "amount", "-500,00 PLN"),
            (0, 110.0, 40.0, "date", "14.01.2025"),
            # tx A: contractor BELOW dates
            (0, 120.0, 108.0, "contractor", "UL. NOWA 5"),
            (0, 130.0, 108.0, "contractor", "12 1111 2222 3333 4444 5555 6666"),
            # tx B: contractor ABOVE dates (no header, no gap separator)
            (0, 150.0, 108.0, "contractor", "ANNA NOWAK"),
            (0, 160.0, 108.0, "contractor", "98 7654 3210 0000 1111 2222 3333"),
            # tx B: dates
            (0, 180.0, 40.0, "date", "20.01.2025"),
            (0, 180.0, 238.0, "title", "Platnosc"),
            (0, 180.0, 491.0, "amount", "-100,00 PLN"),
            (0, 190.0, 40.0, "date", "19.01.2025"),
        ])

        parser = INGParser()
        segments = parser._segment_transactions(items, y_lookbehind=8.0)

        assert len(segments) == 2

        seg_a_texts = [it["text"] for it in segments[0]]
        seg_b_texts = [it["text"] for it in segments[1]]

        # tx A should keep its below-dates contractor lines
        assert "JAN KOWALSKI" in seg_a_texts
        assert "UL. NOWA 5" in seg_a_texts
        assert "12 1111 2222 3333 4444 5555 6666" in seg_a_texts
        assert "-500,00 PLN" in seg_a_texts

        # tx B should have only its own contractor lines
        assert "ANNA NOWAK" in seg_b_texts
        assert "98 7654 3210 0000 1111 2222 3333" in seg_b_texts
        assert "-100,00 PLN" in seg_b_texts

        # No stealing
        assert "UL. NOWA 5" not in seg_b_texts
        assert "12 1111 2222 3333 4444 5555 6666" not in seg_b_texts
        assert "ANNA NOWAK" not in seg_a_texts

    def test_three_transactions_mixed_layouts(self):
        """Three transactions: Layout A, Layout B, Layout A.
        Ensures no cross-contamination across multiple consecutive txns."""
        items = _make_items([
            # tx 1 (Layout A with header)
            (0, 40.0, 108.0, "contractor", "Nazwa i adres odbiorcy:"),
            (0, 45.0, 108.0, "contractor", "MARKET BIEDRONKA"),
            (0, 50.0, 40.0, "date", "01.01.2025"),
            (0, 50.0, 238.0, "title", "Zakup kartą"),
            (0, 50.0, 491.0, "amount", "-120,00 PLN"),
            (0, 55.0, 40.0, "date", "31.12.2024"),
            # tx 2 (Layout B — contractor below dates)
            (0, 80.0, 40.0, "date", "05.01.2025"),
            (0, 80.0, 108.0, "contractor", "TOMASZ WIŚNIEWSKI"),
            (0, 80.0, 238.0, "title", "Przelew BLIK"),
            (0, 80.0, 491.0, "amount", "-200,00 PLN"),
            (0, 90.0, 40.0, "date", "04.01.2025"),
            (0, 100.0, 108.0, "contractor", "77 8888 9999 0000 1111 2222 3333"),
            # tx 3 (Layout A with header)
            (0, 130.0, 108.0, "contractor", "Nazwa i adres nadawcy:"),
            (0, 135.0, 108.0, "contractor", "PRACODAWCA SP Z O O"),
            (0, 140.0, 108.0, "contractor", "33 4444 5555 6666 7777 8888 9999"),
            (0, 150.0, 40.0, "date", "10.01.2025"),
            (0, 150.0, 238.0, "title", "Wynagrodzenie"),
            (0, 150.0, 491.0, "amount", "+5000,00 PLN"),
            (0, 155.0, 40.0, "date", "09.01.2025"),
        ])

        parser = INGParser()
        segments = parser._segment_transactions(items, y_lookbehind=8.0)

        assert len(segments) == 3

        s1 = [it["text"] for it in segments[0]]
        s2 = [it["text"] for it in segments[1]]
        s3 = [it["text"] for it in segments[2]]

        # tx 1
        assert "MARKET BIEDRONKA" in s1
        assert "-120,00 PLN" in s1

        # tx 2 keeps its below-dates NRB
        assert "TOMASZ WIŚNIEWSKI" in s2
        assert "77 8888 9999 0000 1111 2222 3333" in s2
        assert "-200,00 PLN" in s2

        # tx 3 has its own contractor, not tx 2's NRB
        assert "PRACODAWCA SP Z O O" in s3
        assert "33 4444 5555 6666 7777 8888 9999" in s3
        assert "+5000,00 PLN" in s3

        # No cross-contamination
        assert "77 8888 9999 0000 1111 2222 3333" not in s3
        assert "PRACODAWCA SP Z O O" not in s2

    def test_contractor_without_nrb(self):
        """Transactions where contractor block has no NRB (e.g., card payments).
        Should still segment correctly using gap/date/header stops."""
        items = _make_items([
            # tx 1 — card payment, no NRB
            (0, 50.0, 108.0, "contractor", "Nazwa i adres odbiorcy:"),
            (0, 55.0, 108.0, "contractor", "ZABKA Z3456 WARSZAWA"),
            (0, 65.0, 40.0, "date", "01.01.2025"),
            (0, 65.0, 238.0, "title", "Płatność kartą"),
            (0, 65.0, 491.0, "amount", "-15,50 PLN"),
            (0, 70.0, 40.0, "date", "31.12.2024"),
            # gap of ~25pt (> 18pt threshold)
            # tx 2 — card payment, no NRB
            (0, 95.0, 108.0, "contractor", "Nazwa i adres odbiorcy:"),
            (0, 100.0, 108.0, "contractor", "ORLEN STACJA 789"),
            (0, 110.0, 40.0, "date", "02.01.2025"),
            (0, 110.0, 238.0, "title", "Płatność kartą"),
            (0, 110.0, 491.0, "amount", "-180,00 PLN"),
            (0, 115.0, 40.0, "date", "01.01.2025"),
        ])

        parser = INGParser()
        segments = parser._segment_transactions(items, y_lookbehind=8.0)

        assert len(segments) == 2
        s1 = [it["text"] for it in segments[0]]
        s2 = [it["text"] for it in segments[1]]

        assert "ZABKA Z3456 WARSZAWA" in s1
        assert "ORLEN STACJA 789" in s2
        assert "ZABKA Z3456 WARSZAWA" not in s2
