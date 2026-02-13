#!/usr/bin/env python3
"""Diagnostic script: run on a bank statement PDF to see exactly what
pdfplumber extracts and how the parser interprets the data.

Usage:
    python debug_parse_pdf.py /path/to/wyciag.pdf
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from backend.finance.pipeline import extract_pdf_tables, _TABLE_STRATEGIES, _try_extract_tables_with_settings
from backend.finance.parsers import get_parser


def main(pdf_path: str):
    path = Path(pdf_path)
    if not path.exists():
        print(f"Plik nie istnieje: {path}")
        return

    import pdfplumber

    print(f"=== Diagnostyka PDF: {path.name} ===\n")

    with pdfplumber.open(str(path)) as pdf:
        print(f"Liczba stron: {len(pdf.pages)}\n")

        for pg_idx, pg in enumerate(pdf.pages[:3]):
            print(f"--- Strona {pg_idx + 1} ---")

            # Raw text
            text = (pg.extract_text() or "").strip()
            print(f"Tekst (pierwsze 500 znaków):")
            print(text[:500])
            print()

            # Try each strategy
            for strat_idx, settings in enumerate(_TABLE_STRATEGIES):
                strat_name = ["line-based", "text-edge", "relaxed"][strat_idx]
                try:
                    raw = pg.extract_tables(table_settings=settings) or []
                except Exception as e:
                    print(f"  Strategia {strat_idx+1} ({strat_name}): BŁĄD - {e}")
                    continue

                if not raw:
                    print(f"  Strategia {strat_idx+1} ({strat_name}): brak tabel")
                    continue

                for tbl_idx, tbl in enumerate(raw):
                    clean = [[(c or "").strip() for c in row] for row in tbl]
                    non_empty = max((sum(1 for c in row if c) for row in clean), default=0)
                    ncols = max((len(row) for row in clean), default=0)

                    print(f"  Strategia {strat_idx+1} ({strat_name}), tabela {tbl_idx+1}:")
                    print(f"    Wiersze: {len(clean)}, Kolumny (max): {ncols}, Max niepustych/wiersz: {non_empty}")

                    # Print first 10 rows
                    for row_idx, row in enumerate(clean[:10]):
                        row_display = " | ".join(f"[{c[:40]}]" if c else "[  ]" for c in row)
                        print(f"    [{row_idx:3d}] {row_display}")
                    if len(clean) > 10:
                        print(f"    ... ({len(clean) - 10} więcej wierszy)")
                    print()

                # Only show first strategy that works
                if raw:
                    break

    # Full pipeline extraction
    print("\n=== Ekstrakcja tabel (pipeline) ===")
    tables, full_text, page_count = extract_pdf_tables(path)
    print(f"Wyodrębniono {len(tables)} tabel z {page_count} stron")

    for t_idx, table in enumerate(tables):
        print(f"\n--- Tabela {t_idx + 1}: {len(table)} wierszy ---")
        for row_idx, row in enumerate(table[:15]):
            row_display = " | ".join(f"[{c[:40]}]" if c else "[  ]" for c in row)
            print(f"  [{row_idx:3d}] {row_display}")
        if len(table) > 15:
            print(f"  ... ({len(table) - 15} więcej wierszy)")

    # Parser detection
    print("\n=== Detekcja banku ===")
    parser = get_parser(full_text[:5000])
    print(f"Parser: {parser.BANK_ID} ({parser.BANK_NAME})")

    # Parse
    print("\n=== Parsowanie ===")
    if hasattr(parser, "supports_direct_pdf") and parser.supports_direct_pdf():
        result = parser.parse_pdf(path)
    else:
        result = parser.parse(tables, full_text)
    result.page_count = page_count

    print(f"Metoda: {result.parse_method}")
    print(f"Transakcje: {len(result.transactions)}")
    print(f"Ostrzeżenia: {result.warnings}")
    print(f"Info: okres {result.info.period_from} - {result.info.period_to}")
    print(f"  Saldo otw.: {result.info.opening_balance}")
    print(f"  Saldo końc.: {result.info.closing_balance}")

    print("\n=== Transakcje (pierwsze 15) ===")
    for i, txn in enumerate(result.transactions[:15]):
        print(f"  #{i+1:3d} | {txn.date} | {txn.amount:>12,.2f} | bal={txn.balance_after} | {txn.counterparty[:40]} | {txn.title[:60]}")
        if not txn.title and not txn.counterparty:
            print(f"        >>> BRAK TYTUŁU/KONTRAHENTA! raw_text: {txn.raw_text[:100]}")

    if len(result.transactions) > 15:
        print(f"  ... ({len(result.transactions) - 15} więcej)")

    # Also test column mapping directly for debugging
    if tables and hasattr(parser, '_find_column_mapping'):
        print("\n=== Debug: mapowanie kolumn ===")
        for t_idx, table in enumerate(tables):
            for row_idx, row in enumerate(table):
                if hasattr(parser, '_is_header_row') and parser._is_header_row(row):
                    col_map = parser._find_column_mapping(row)
                    print(f"  Tabela {t_idx+1}, nagłówek w wierszu {row_idx}:")
                    print(f"    Header: {row}")
                    print(f"    Mapowanie: {col_map}")

                    # Test merge_continuation_rows
                    from backend.finance.parsers.base import BankParser
                    merged = BankParser.merge_continuation_rows(table, col_map, row_idx + 1)
                    print(f"    Wiersze po merge: {len(merged)} (z {len(table) - row_idx - 1} oryginalnych)")
                    for m_idx, mrow in enumerate(merged[:5]):
                        print(f"      [{m_idx}] {' | '.join(c[:30] for c in mrow)}")
                    break


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Użycie: python debug_parse_pdf.py <ścieżka_do_pdf>")
        sys.exit(1)
    main(sys.argv[1])
