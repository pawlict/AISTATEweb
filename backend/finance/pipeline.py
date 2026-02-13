"""Financial analysis pipeline — orchestrates the full flow.

PDF → extract → detect bank → parse → classify → score → build prompt.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .behavioral import (
    BehavioralReport,
    MonthSnapshot,
    build_month_snapshot,
    compute_behavioral_report,
    load_scoring_history,
    save_scoring_history,
)
from .classifier import ClassifiedTransaction, classify_all
from .detector import is_bank_statement
from .entity_memory import EntityMemory
from .parsers import get_parser
from .parsers.base import ParseResult, reconcile_balances, validate_balance_chain
from .prompt_builder import build_finance_prompt
from .scorer import ScoreBreakdown, compute_score
from .spending_analysis import SpendingReport, analyze_spending

log = logging.getLogger("aistate.finance")


def _try_extract_tables_with_settings(
    page: Any,
    settings_list: List[Dict[str, Any]],
) -> List[List[List[str]]]:
    """Try multiple table extraction strategies, return first non-empty result.

    pdfplumber's default settings rely on visible lines which many Polish bank
    PDFs lack.  This helper tries increasingly aggressive detection methods.
    """
    for settings in settings_list:
        try:
            raw = page.extract_tables(table_settings=settings) or []
            result: List[List[List[str]]] = []
            for tbl in raw:
                if tbl and isinstance(tbl, list) and len(tbl) <= 500:
                    clean = [[(c or "").strip() for c in row] for row in tbl]
                    # Skip tables where every row is a single cell (not real tables)
                    non_empty_cols = max(
                        (sum(1 for c in row if c) for row in clean), default=0
                    )
                    if non_empty_cols >= 2:
                        result.append(clean)
                    elif non_empty_cols > 0:
                        log.debug(
                            "Odrzucono tabelę z %d wierszami i max %d niepustymi kolumnami",
                            len(clean), non_empty_cols,
                        )
            if result:
                return result
        except Exception:
            continue
    return []


# Table extraction strategies ordered from strictest to most lenient.
_TABLE_STRATEGIES: List[Dict[str, Any]] = [
    # Strategy 1: default (line-based) — works for PDFs with visible grid
    {},
    # Strategy 2: text-edge based — works for PDFs without visible lines
    {
        "vertical_strategy": "text",
        "horizontal_strategy": "text",
        "snap_tolerance": 5,
        "join_tolerance": 5,
        "min_words_vertical": 2,
        "min_words_horizontal": 1,
    },
    # Strategy 3: relaxed text-edge — wider snapping for loosely formatted PDFs
    {
        "vertical_strategy": "text",
        "horizontal_strategy": "text",
        "snap_tolerance": 8,
        "join_tolerance": 8,
        "min_words_vertical": 1,
        "min_words_horizontal": 1,
    },
]


def extract_header_words(pdf_path: Path, max_pages: int = 2) -> List[Dict[str, Any]]:
    """Extract positioned words from first pages for spatial header parsing.

    Uses pdfplumber's extract_words() which returns word-level bounding boxes.
    This enables spatial analysis of columnar layouts where extract_text()
    would flatten columns into incorrect line sequences.
    """
    try:
        import pdfplumber
    except ImportError:
        return []

    words: List[Dict[str, Any]] = []
    try:
        with pdfplumber.open(str(pdf_path)) as pdf:
            for pg in pdf.pages[:max_pages]:
                page_words = pg.extract_words() or []
                words.extend(page_words)
    except Exception:
        pass
    return words


def extract_pdf_tables(pdf_path: Path) -> Tuple[List[List[List[str]]], str, int]:
    """Extract tables and text from PDF using pdfplumber.

    Uses multiple extraction strategies to handle PDFs both with and without
    visible table borders (common in Polish bank statements).

    Returns:
        (tables, full_text, page_count)
    """
    try:
        import pdfplumber
    except ImportError:
        log.warning("pdfplumber not available, falling back to text-only")
        return [], "", 0

    tables: List[List[List[str]]] = []
    text_parts: List[str] = []
    page_count = 0

    with pdfplumber.open(str(pdf_path)) as pdf:
        page_count = len(pdf.pages)
        for pg in pdf.pages:
            t = (pg.extract_text() or "").strip()
            if t:
                text_parts.append(t)
            page_tables = _try_extract_tables_with_settings(pg, _TABLE_STRATEGIES)
            tables.extend(page_tables)

    full_text = "\n\n".join(text_parts)
    return tables, full_text, page_count


def run_finance_pipeline(
    pdf_path: Path,
    cached_text: Optional[str] = None,
    save_dir: Optional[Path] = None,
    global_dir: Optional[Path] = None,
    log_cb=None,
) -> Optional[Dict[str, Any]]:
    """Run the full financial analysis pipeline on a PDF.

    Args:
        pdf_path: Path to bank statement PDF
        cached_text: Pre-extracted text (from document_processor cache)
        save_dir: Directory to save intermediate results (e.g. project finance dir)
        global_dir: Global projects dir for shared entity knowledge
        log_cb: Optional logging callback

    Returns:
        Dict with pipeline results, or None if document is not a bank statement.
    """
    def _log(msg: str):
        log.info(msg)
        if log_cb:
            try:
                log_cb(msg)
            except Exception:
                pass

    t0 = time.time()

    # Step 0: Check for cached parsed results
    if save_dir:
        parsed_cache = save_dir / "parsed" / f"{pdf_path.stem}.json"
        if parsed_cache.exists():
            try:
                cache_mtime = parsed_cache.stat().st_mtime
                pdf_mtime = pdf_path.stat().st_mtime
                if cache_mtime >= pdf_mtime:
                    _log(f"Znaleziono cache sparsowanych danych: {parsed_cache.name}")
                    cached = json.loads(parsed_cache.read_text(encoding="utf-8"))
                    # Validate cache has essential fields
                    if cached.get("transactions") and cached.get("score"):
                        _log(f"Cache zawiera {len(cached['transactions'])} transakcji — pomijam re-parsowanie")
                    else:
                        _log("Cache niekompletny — ponowne parsowanie")
            except Exception as e:
                _log(f"Błąd odczytu cache: {e}")

    # Step 1: Check if this looks like a bank statement
    preview_text = cached_text or ""
    if not preview_text:
        try:
            _, preview_text, _ = extract_pdf_tables(pdf_path)
        except Exception as e:
            _log(f"Błąd ekstrakcji PDF: {e}")
            return None

    is_stmt, confidence, indicators = is_bank_statement(preview_text[:10000])
    if not is_stmt:
        _log(f"Dokument nie wygląda na wyciąg bankowy (score={confidence})")
        return None

    _log(f"Wykryto wyciąg bankowy (pewność: {confidence}, wskaźniki: {len(indicators)})")

    # Step 2: Extract tables from PDF
    _log("Ekstrakcja tabel z PDF...")
    tables, full_text, page_count = extract_pdf_tables(pdf_path)
    _log(f"Wyodrębniono {len(tables)} tabel z {page_count} stron")

    # Step 3: Detect bank and get parser
    parser = get_parser(full_text[:5000])
    _log(f"Rozpoznany bank: {parser.BANK_NAME} (parser: {parser.BANK_ID})")

    # Step 4: Parse transactions
    _log("Parsowanie transakcji...")
    if hasattr(parser, "supports_direct_pdf") and parser.supports_direct_pdf():
        _log(f"Parser {parser.BANK_ID}: bezpośrednie parsowanie PDF (PyMuPDF)...")
        parse_result = parser.parse_pdf(pdf_path)
    else:
        header_words = None
        parse_result = parser.parse(tables, full_text, header_words=header_words)
    parse_result.page_count = page_count
    _log(f"Znaleziono {len(parse_result.transactions)} transakcji")

    if not parse_result.transactions:
        _log("UWAGA: Nie wyodrębniono żadnych transakcji. Dokument zostanie przesłany jako tekst surowy.")
        return None

    # Step 4b: Reconcile balances from multiple sources (table > header > computed)
    _log("Rekoncyliacja sald (tabela > nagłówek > obliczone)...")
    opening, closing, recon_notes = reconcile_balances(
        parse_result.transactions,
        parse_result.info,
    )
    for note in recon_notes:
        _log(f"  {note}")
    parse_result.warnings.extend(
        n for n in recon_notes if "BRAK" in n or "≠" in n
    )

    # Step 4c: Validate balance chain (including cross-validation against declared sums)
    _log("Walidacja łańcucha sald...")
    bal_valid, bal_warnings = validate_balance_chain(
        parse_result.transactions,
        opening,
        closing,
        declared_credits_sum=parse_result.info.declared_credits_sum,
        declared_debits_sum=parse_result.info.declared_debits_sum,
        declared_credits_count=parse_result.info.declared_credits_count,
        declared_debits_count=parse_result.info.declared_debits_count,
    )
    if bal_warnings:
        for w in bal_warnings:
            _log(f"  ⚠ {w}")
        parse_result.warnings.extend(bal_warnings)
    if bal_valid:
        _log("Łańcuch sald: OK ✓")
    else:
        _log("Łańcuch sald: ROZBIEŻNOŚCI — wyniki mogą być niedokładne")

    # Step 5: Load entity memory
    memory = None
    if save_dir:
        try:
            global_ents_dir = global_dir / "_global" if global_dir else None
            memory = EntityMemory(save_dir, global_ents_dir)
            flagged = memory.get_flagged_names()
            if flagged:
                _log(f"Entity memory: {len(flagged)} oznaczonych podmiotów")
        except Exception as e:
            _log(f"Nie udało się załadować entity memory: {e}")
            memory = None

    # Step 6: Classify transactions (with entity memory)
    _log("Klasyfikacja transakcji...")
    classified = classify_all(parse_result.transactions, entity_memory=memory)
    tagged_count = sum(1 for ct in classified if ct.categories)
    recurring_count = sum(1 for ct in classified if ct.is_recurring)
    flagged_count = sum(1 for ct in classified if ct.entity_flagged)
    _log(f"Sklasyfikowano: {tagged_count} otagowanych, {recurring_count} cyklicznych, {flagged_count} oznaczonych")

    # Step 6: Compute score
    _log("Obliczanie scoringu finansowego...")
    score = compute_score(classified)
    _log(f"Score końcowy: {score.total_score}/100")

    # Step 7: Save intermediate results
    if save_dir:
        save_dir.mkdir(parents=True, exist_ok=True)
        try:
            parsed_file = save_dir / "parsed" / f"{pdf_path.stem}.json"
            parsed_file.parent.mkdir(parents=True, exist_ok=True)
            parsed_file.write_text(json.dumps({
                "bank": parse_result.bank,
                "info": parse_result.info.to_dict(),
                "transactions": [ct.to_dict() for ct in classified],
                "score": score.to_dict(),
                "parse_method": parse_result.parse_method,
                "page_count": page_count,
                "warnings": parse_result.warnings,
                "pipeline_time_s": round(time.time() - t0, 2),
            }, ensure_ascii=False, indent=2), encoding="utf-8")
            _log(f"Zapisano dane: {parsed_file}")
        except Exception as e:
            _log(f"Błąd zapisu danych: {e}")

    # Step 8: Auto-update entity memory with seen counterparties
    if memory:
        try:
            cp_data = []
            for ct in classified:
                cp_name = ct.transaction.counterparty or ct.transaction.title
                if cp_name and len(cp_name.strip()) >= 3:
                    cp_data.append({
                        "name": cp_name,
                        "category": ct.categories[0] if ct.categories else "",
                        "amount": ct.transaction.amount,
                        "date": ct.transaction.date,
                    })
            updated = memory.update_from_transactions(cp_data)
            _log(f"Entity memory: zaktualizowano {updated} podmiotów")
        except Exception as e:
            _log(f"Błąd aktualizacji entity memory: {e}")

    # Step 9: Spending pattern analysis
    _log("Analiza wzorców wydatków...")
    spending = analyze_spending(classified)
    if spending.top_shops:
        _log(f"Top sklepy: {', '.join(s.name for s in spending.top_shops[:3])}")
    if spending.fuel_visits:
        _log(f"Tankowania: {len(spending.fuel_visits)} wizyt, "
             f"miasto bazowe: {spending.fuel_home_city or '?'}")
    if spending.blik_transactions:
        _log(f"BLIK: {spending.blik_phone_transfers} przelewów na tel, "
             f"{spending.blik_online_purchases} zakupów, "
             f"{spending.blik_other_payments} płatności")

    dt = time.time() - t0
    _log(f"Pipeline finansowy zakończony w {dt:.1f}s")

    return {
        "parse_result": parse_result,
        "classified": classified,
        "score": score,
        "spending": spending,
        "pipeline_time_s": round(dt, 2),
    }


def run_multi_statement_pipeline(
    pdf_paths: List[Tuple[Path, Optional[str]]],
    save_dir: Optional[Path] = None,
    global_dir: Optional[Path] = None,
    log_cb=None,
) -> Optional[Dict[str, Any]]:
    """Run pipeline on multiple PDF bank statements and aggregate results.

    Args:
        pdf_paths: List of (pdf_path, cached_text) tuples
        save_dir: Finance directory for the project
        global_dir: Global projects dir
        log_cb: Logging callback

    Returns:
        Dict with combined results + behavioral report, or None.
    """
    def _log(msg: str):
        log.info(msg)
        if log_cb:
            try:
                log_cb(msg)
            except Exception:
                pass

    all_results: List[Dict[str, Any]] = []
    month_snapshots: List[MonthSnapshot] = []

    for pdf_path, cached_text in pdf_paths:
        result = run_finance_pipeline(
            pdf_path=pdf_path,
            cached_text=cached_text,
            save_dir=save_dir,
            global_dir=global_dir,
            log_cb=log_cb,
        )
        if result:
            all_results.append(result)
            pr = result["parse_result"]
            snap = build_month_snapshot(
                classified=result["classified"],
                score=result["score"],
                period=pr.info.period_from[:7] if pr.info.period_from else "",
                bank=pr.bank,
                source_file=pdf_path.name,
            )
            month_snapshots.append(snap)

    if not all_results:
        return None

    # Load historical data and merge
    if save_dir:
        historical = load_scoring_history(save_dir)
        # Merge: new snapshots override same-period historical
        existing_periods = {s.period for s in month_snapshots}
        for h in historical:
            if h.period not in existing_periods:
                month_snapshots.append(h)
        # Save updated history
        save_scoring_history(save_dir, month_snapshots)
        _log(f"Scoring history: {len(month_snapshots)} miesięcy (w tym {len(historical)} historycznych)")

    # Compute behavioral report
    behavioral = None
    if len(month_snapshots) >= 2:
        behavioral = compute_behavioral_report(month_snapshots)
        _log(f"Analiza behawioralna: {behavioral.total_months} miesięcy, trajektoria={behavioral.debt_trajectory}")

    # Use the most recent statement as primary result
    primary = all_results[-1]
    primary["all_results"] = all_results
    primary["behavioral"] = behavioral
    primary["month_snapshots"] = month_snapshots

    return primary


def build_enriched_prompt(
    pipeline_result: Dict[str, Any],
    original_instruction: str = "",
) -> str:
    """Build the enriched prompt from pipeline results.

    This replaces the raw document text in the analysis prompt.
    Includes behavioral data if multi-month analysis was performed.
    """
    behavioral = pipeline_result.get("behavioral")
    spending = pipeline_result.get("spending")
    return build_finance_prompt(
        parse_result=pipeline_result["parse_result"],
        classified=pipeline_result["classified"],
        score=pipeline_result["score"],
        original_instruction=original_instruction,
        behavioral=behavioral,
        spending=spending,
    )
