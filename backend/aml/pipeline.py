"""AML Analysis Pipeline — end-to-end orchestration.

upload PDF → detect bank → parse → normalize → rules → baseline →
anomaly (stats + ML) → graph → score → charts → LLM prompt →
report HTML → audit log.

Integrates with existing finance parsers (adapter pattern).
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..db.engine import ensure_initialized, get_conn, get_default_user_id, new_id
from ..db.projects import add_case_file, create_case, get_case
from ..finance.parsers.base import ParseResult, RawTransaction, StatementInfo
from ..finance.pipeline import extract_header_words, extract_pdf_tables
from ..finance.parsers import get_parser
from ..finance.parsers.base import reconcile_balances, validate_balance_chain

from .baseline import AnomalyAlert, build_baseline, detect_anomalies
from .charts import generate_all_charts
from .graph import build_graph
from .llm_analysis import build_aml_prompt
from .memory import (
    get_counterparty_labels,
    get_counterparty_notes,
    resolve_entity,
)
from .anonymize import get_or_create_profile
from .ml_anomaly import detect_ml_anomalies
from .normalize import NormalizedTransaction, normalize_transactions
from .report import generate_report
from .rules import classify_all, compute_risk_score, load_rules

log = logging.getLogger("aistate.aml.pipeline")


def _safe_float(val) -> Optional[float]:
    """Convert value to float, handling Polish number formats and currency suffixes.

    Handles: "65,35 PLN", "1 053,83 zł", "21 850,08PLN", "-73,14 PLN",
             "12 345,67", "12345.67", plain numbers.
    """
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        pass
    try:
        s = str(val).strip()
        # Strip currency codes/symbols that may be appended to the number
        import re as _re
        s = _re.sub(r'\s*(PLN|EUR|USD|GBP|CHF|CZK|SEK|NOK|DKK|zł|zl)\s*$', '', s, flags=_re.IGNORECASE)
        s = _re.sub(r'^\s*(PLN|EUR|USD|GBP|CHF|CZK|SEK|NOK|DKK|zł|zl)\s*', '', s, flags=_re.IGNORECASE)
        s = s.strip().replace("\u00a0", "").replace(" ", "")
        if "," in s and "." not in s:
            s = s.replace(",", ".")
        elif "," in s and "." in s:
            s = s.replace(",", "")  # "12,345.67" → "12345.67"
        return float(s)
    except (ValueError, TypeError):
        return None


def _safe_int(val) -> Optional[int]:
    """Convert value to int, returning None on failure."""
    if val is None:
        return None
    try:
        return int(val)
    except (ValueError, TypeError):
        pass
    # Try stripping whitespace/currency then parse
    try:
        import re as _re
        s = str(val).strip()
        s = _re.sub(r'\s*(PLN|EUR|USD|GBP|CHF|zł|zl)\s*$', '', s, flags=_re.IGNORECASE)
        s = s.strip().replace("\u00a0", "").replace(" ", "")
        return int(float(s))
    except (ValueError, TypeError):
        return None


def _compute_pdf_hash(path: Path) -> str:
    """SHA-256 of PDF file (first 10MB)."""
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
                if f.tell() > 10 * 1024 * 1024:
                    break
    except Exception:
        return ""
    return h.hexdigest()


def _check_ocr_needed(full_text: str, page_count: int) -> bool:
    """Check if OCR is needed (text layer is empty or nearly empty)."""
    if not full_text or not full_text.strip():
        return True
    # Very little text relative to pages
    chars_per_page = len(full_text.strip()) / max(page_count, 1)
    return chars_per_page < 50


def _run_ocr(pdf_path: Path) -> Tuple[str, float]:
    """Run OCR on PDF. Returns (text, confidence).

    Uses pytesseract + pymupdf for rendering if available.
    """
    try:
        import fitz  # PyMuPDF
        import pytesseract
        from PIL import Image
        import io

        doc = fitz.open(str(pdf_path))
        texts = []
        confidences = []

        for page in doc:
            pix = page.get_pixmap(dpi=300)
            img = Image.open(io.BytesIO(pix.tobytes("png")))
            data = pytesseract.image_to_data(img, lang="pol+eng", output_type=pytesseract.Output.DICT)

            page_text = " ".join(w for w in data["text"] if w.strip())
            texts.append(page_text)

            confs = [int(c) for c in data["conf"] if str(c).isdigit() and int(c) > 0]
            if confs:
                confidences.append(sum(confs) / len(confs))

        doc.close()
        full_text = "\n\n".join(texts)
        avg_conf = sum(confidences) / len(confidences) if confidences else 0
        return full_text, avg_conf / 100.0

    except ImportError as e:
        log.warning("OCR dependencies not available: %s", e)
        return "", 0.0
    except Exception as e:
        log.error("OCR failed: %s", e)
        return "", 0.0


def _run_multi_statement_aml(
    results: "List[ParseResult]",
    pdf_path: Path,
    pdf_hash: str,
    case_id: str,
    project_id: str,
    page_count: int,
    save_report: bool,
    log_cb,
    t0: float,
) -> Dict[str, Any]:
    """Process multiple ParseResults from a single multi-currency PDF.

    Runs ``run_aml_pipeline`` for each currency sub-statement, reusing
    the same case_id so all sub-statements belong to one analysis case.
    """
    statements: List[Dict[str, Any]] = []
    all_warnings: List[str] = []
    shared_case_id = case_id  # may be empty — first call will create it

    for pr in results:
        currency = pr.info.currency if pr.info else "?"
        sub_hash = f"{pdf_hash}_{currency}"

        sub_result = run_aml_pipeline(
            pdf_path=pdf_path,
            case_id=shared_case_id,
            project_id=project_id,
            save_report=save_report,
            log_cb=log_cb,
            _parse_result=pr,
            _pdf_hash=sub_hash,
        )

        # Reuse the case created by the first sub-statement
        if not shared_case_id and sub_result.get("case_id"):
            shared_case_id = sub_result["case_id"]

        statements.append({
            "statement_id": sub_result.get("statement_id"),
            "account_id": sub_result.get("account_id"),
            "bank": sub_result.get("bank"),
            "bank_name": sub_result.get("bank_name"),
            "currency": currency,
            "transaction_count": sub_result.get("transaction_count", 0),
            "risk_score": sub_result.get("risk_score", 0),
            "status": sub_result.get("status", "error"),
            "warnings": sub_result.get("warnings", []),
        })
        all_warnings.extend(sub_result.get("warnings", []))

    dt = time.time() - t0
    total_tx = sum(s.get("transaction_count", 0) for s in statements)

    return {
        "status": "ok",
        "multi": True,
        "case_id": shared_case_id,
        "statements": statements,
        "total_transactions": total_tx,
        "statement_count": len(statements),
        "warnings": all_warnings,
        "pipeline_time_s": round(dt, 2),
    }


def run_aml_pipeline(
    pdf_path: Path,
    case_id: str = "",
    project_id: str = "",
    save_report: bool = True,
    log_cb=None,
    *,
    _parse_result: Optional[ParseResult] = None,
    _pdf_hash: str = "",
) -> Dict[str, Any]:
    """Run the full AML analysis pipeline on a bank statement PDF.

    Args:
        pdf_path: Path to bank statement PDF
        case_id: Existing case ID (or empty to create new)
        project_id: Project ID for new case creation
        save_report: Whether to save HTML report to disk
        log_cb: Optional progress callback
        _parse_result: Pre-parsed result (for multi-currency sub-statements).
        _pdf_hash: Overridden PDF hash (for multi-currency dedup).

    Returns:
        Dict with all pipeline results including report HTML.
    """
    ensure_initialized()
    t0 = time.time()

    def _log(msg: str):
        log.info(msg)
        if log_cb:
            try:
                log_cb(msg)
            except Exception:
                pass

    pdf_hash = _pdf_hash or _compute_pdf_hash(pdf_path)
    rules_config = load_rules()
    rules_version = rules_config.get("version", "1.0.0")
    warnings: List[str] = []

    ocr_used = False
    ocr_confidence = 0.0

    if _parse_result is not None:
        # Multi-statement mode: ParseResult provided externally
        parse_result = _parse_result
    else:
        # --- Step 1: Parse PDF with PyMuPDF universal parser ---
        _log("Parsowanie PDF (PyMuPDF)...")
        from .universal_parser import parse_bank_statement

        try:
            parse_result = parse_bank_statement(pdf_path)
        except RuntimeError as e:
            _log(f"Universal parser: {e}")
            # Fallback to legacy pdfplumber-based parsers
            _log("Fallback: parsowanie pdfplumber...")
            tables, full_text, page_count = extract_pdf_tables(pdf_path)

            if _check_ocr_needed(full_text, page_count):
                _log("Brak warstwy tekstowej — uruchamiam OCR...")
                ocr_text, ocr_confidence = _run_ocr(pdf_path)
                if ocr_text:
                    full_text = ocr_text
                    ocr_used = True
                else:
                    warnings.append("OCR nie powiódł się")

            parser = get_parser(full_text[:5000])
            _log(f"Bank (fallback): {parser.BANK_NAME}")

            header_words = None
            if parser.BANK_ID == "ing":
                header_words = extract_header_words(pdf_path)

            # Check for multi-result parser (e.g., Revolut multi-currency)
            if hasattr(parser, "parse_multi"):
                multi_results = parser.parse_multi(
                    tables, full_text, header_words=header_words,
                )
                if len(multi_results) > 1:
                    _log(f"Multi-statement: {len(multi_results)} walut wykrytych")
                    for r in multi_results:
                        r.page_count = page_count
                    return _run_multi_statement_aml(
                        multi_results, pdf_path, pdf_hash,
                        case_id, project_id, page_count,
                        save_report, log_cb, t0,
                    )
                elif multi_results:
                    parse_result = multi_results[0]
                    parse_result.page_count = page_count
                else:
                    parse_result = parser.parse(
                        tables, full_text, header_words=header_words,
                    )
                    parse_result.page_count = page_count
            else:
                parse_result = parser.parse(
                    tables, full_text, header_words=header_words,
                )
                parse_result.page_count = page_count

    bank_name = parse_result.bank or parse_result.info.bank
    # Derive bank_id from bank name
    bank_id = bank_name.lower().replace(" ", "_")[:20] if bank_name else "unknown"
    info = parse_result.info

    # Merge any parser-level warnings (e.g. exchange tx exclusion notes)
    if parse_result.warnings:
        warnings.extend(parse_result.warnings)

    _log(f"Bank: {bank_name} | Metoda: {parse_result.parse_method}")

    _log(f"Znaleziono {len(parse_result.transactions)} transakcji")

    if not parse_result.transactions:
        _log("UWAGA: Brak transakcji w dokumencie")
        return {"status": "error", "error": "no_transactions", "warnings": warnings}

    # --- Step 4: Reconcile balances ---
    _log("Rekoncyliacja sald...")
    opening, closing, recon_notes = reconcile_balances(
        parse_result.transactions, parse_result.info
    )
    warnings.extend(n for n in recon_notes if "BRAK" in n or "≠" in n)

    # Validate balance chain
    bal_valid, bal_warnings = validate_balance_chain(
        parse_result.transactions, opening, closing,
        declared_credits_sum=parse_result.info.declared_credits_sum,
        declared_debits_sum=parse_result.info.declared_debits_sum,
        declared_credits_count=parse_result.info.declared_credits_count,
        declared_debits_count=parse_result.info.declared_debits_count,
    )
    warnings.extend(bal_warnings)
    if bal_valid:
        _log("Łańcuch sald: OK")
    else:
        _log("Łańcuch sald: ROZBIEŻNOŚCI")

    # --- Step 5: Save statement to DB ---
    _log("Zapis do bazy danych...")
    info = parse_result.info

    # --- Step 5a: Duplicate detection by pdf_hash ---
    # Only block duplicates within the SAME case (same PDF uploaded twice
    # in one analysis session). New cases always get fresh analysis — this
    # allows re-analysis after parser improvements.
    _existing_stmt = None
    _is_duplicate = False
    if case_id and pdf_hash:
        with get_conn() as conn:
            _existing_stmt = conn.execute(
                "SELECT id, case_id FROM statements WHERE case_id = ? AND pdf_hash = ? LIMIT 1",
                (case_id, pdf_hash),
            ).fetchone()

    if _existing_stmt:
        _is_duplicate = True
        existing_id = _existing_stmt["id"]
        existing_case = _existing_stmt["case_id"]
        _log(f"DUPLIKAT: ten PDF został już przeanalizowany w tej analizie "
             f"(statement={existing_id[:8]}). Pomijam ponowny zapis.")
        dt = time.time() - t0
        return {
            "status": "duplicate",
            "case_id": existing_case,
            "statement_id": existing_id,
            "bank": bank_id,
            "bank_name": bank_name,
            "transaction_count": len(parse_result.transactions),
            "duplicate_of": existing_id,
            "message": f"Ten wyciąg ({bank_name} {info.period_from}—{info.period_to}) "
                        "został już wczytany w tej analizie. Używam istniejącej analizy.",
            "warnings": warnings,
            "pipeline_time_s": round(dt, 2),
        }

    statement_id = new_id()

    # --- Step 5b: Create/update account profile (before main DB block to avoid nested connections) ---
    account_profile_id = None
    if info.account_number:
        try:
            profile = get_or_create_profile(
                account_number=info.account_number,
                bank_id=bank_id,
                bank_name=bank_name,
                account_holder=info.account_holder or "",
            )
            account_profile_id = profile.get("id")
        except Exception as e:
            log.warning("Account profile creation failed: %s", e)

    with get_conn() as conn:
        # Create case if needed
        if not case_id:
            # Verify provided project_id actually exists in DB; reset if not
            if project_id:
                exists = conn.execute(
                    "SELECT id FROM projects WHERE id = ?", (project_id,)
                ).fetchone()
                if not exists:
                    log.warning("Provided project_id %s not found in DB, will create/find default", project_id)
                    project_id = None

            if not project_id:
                owner_id = get_default_user_id()
                # Create or find default AML project
                row = conn.execute(
                    "SELECT id FROM projects WHERE name = 'Analizy AML' AND status = 'active' LIMIT 1"
                ).fetchone()
                if row:
                    project_id = row["id"]
                else:
                    project_id = new_id()
                    conn.execute(
                        """INSERT INTO projects (id, owner_id, name, description)
                           VALUES (?, ?, ?, ?)""",
                        (project_id, owner_id, "Analizy AML", "Automatyczne analizy wyciągów bankowych"),
                    )

            case_id = new_id()
            case_name = f"{info.bank} {info.period_from or ''} — {info.period_to or ''}"
            conn.execute(
                """INSERT INTO cases (id, project_id, name, case_type, metadata)
                   VALUES (?, ?, ?, ?, ?)""",
                (case_id, project_id, case_name.strip(), "aml", "{}"),
            )

        # Ensure extra columns exist (migration for existing DBs)
        for col in ("previous_closing_balance", "debt_limit",
                     "overdue_commission", "blocked_amount",
                     "account_holder", "pdf_hash", "account_id"):
            try:
                conn.execute(f"SELECT {col} FROM statements LIMIT 0")
            except Exception:
                conn.execute(f"ALTER TABLE statements ADD COLUMN {col} TEXT")

        # Save statement (with account_id FK)
        conn.execute(
            """INSERT INTO statements
               (id, case_id, account_id, bank_id, bank_name, period_from, period_to,
                opening_balance, closing_balance, available_balance, currency,
                account_number, account_holder,
                declared_credits_sum, declared_credits_count,
                declared_debits_sum, declared_debits_count,
                previous_closing_balance, debt_limit,
                overdue_commission, blocked_amount,
                parse_method, ocr_used, ocr_confidence,
                parser_version, pdf_hash, warnings)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (statement_id, case_id, account_profile_id, bank_id, bank_name,
             info.period_from, info.period_to,
             str(info.opening_balance) if info.opening_balance is not None else None,
             str(info.closing_balance) if info.closing_balance is not None else None,
             str(info.available_balance) if info.available_balance is not None else None,
             info.currency, info.account_number, info.account_holder,
             str(info.declared_credits_sum) if info.declared_credits_sum is not None else None,
             info.declared_credits_count,
             str(info.declared_debits_sum) if info.declared_debits_sum is not None else None,
             info.declared_debits_count,
             str(info.previous_closing_balance) if info.previous_closing_balance is not None else None,
             str(info.debt_limit) if info.debt_limit is not None else None,
             str(info.overdue_commission) if info.overdue_commission is not None else None,
             str(info.blocked_amount) if info.blocked_amount is not None else None,
             parse_result.parse_method, int(ocr_used), ocr_confidence,
             f"{bank_id}_v1", pdf_hash,
             json.dumps(warnings, ensure_ascii=False)),
        )

    # --- Step 6: Normalize transactions ---
    _log("Normalizacja transakcji...")
    normalized = normalize_transactions(parse_result.transactions, statement_id)
    _log(f"Znormalizowano {len(normalized)} transakcji")

    # --- Step 7: Entity resolution ---
    _log("Rozpoznawanie kontrahentów...")
    for tx in normalized:
        if tx.counterparty_clean:
            cp_id, confidence = resolve_entity(
                name=tx.counterparty_raw,
                source_bank=bank_id,
                amount=float(tx.amount),
                date=tx.booking_date,
            )
            tx.counterparty_id = cp_id

    # --- Step 7b: Apply learned categories from counterparty memory ---
    _log("Stosowanie zapamiętanych kategorii kontrahentów...")
    learned = 0
    with get_conn() as conn:
        for tx in normalized:
            if tx.counterparty_id:
                row = conn.execute(
                    "SELECT auto_category FROM counterparties WHERE id = ? AND auto_category != ''",
                    (tx.counterparty_id,),
                ).fetchone()
                if row:
                    tx.category = row["auto_category"]
                    tx.subcategory = row["auto_category"]
                    learned += 1
    if learned:
        _log(f"Zastosowano zapamiętane kategorie dla {learned} transakcji")

    # --- Step 8: Rules classification ---
    _log("Klasyfikacja regułowa...")
    cp_labels = get_counterparty_labels()
    cp_notes = get_counterparty_notes()
    classified = classify_all(normalized, cp_labels, cp_notes)
    tagged = sum(1 for tx, r in classified if r.risk_tags)
    _log(f"Otagowano {tagged}/{len(classified)} transakcji")

    # Apply results back to normalized list
    tx_list = [tx for tx, _ in classified]

    # --- Step 9: Baseline & anomaly detection ---
    _log("Detekcja anomalii...")
    baseline = build_baseline(tx_list)
    known_cps = set(get_counterparty_labels().keys())
    alerts = detect_anomalies(tx_list, baseline, known_cps)
    _log(f"Wykryto {len(alerts)} alertów")

    # --- Step 10: Risk scoring ---
    _log("Obliczanie risk score...")
    risk_score, risk_reasons = compute_risk_score(tx_list, rules_config)
    _log(f"Risk score: {risk_score:.0f}/100")

    # --- Step 10b: ML anomaly detection ---
    _log("Detekcja anomalii ML (Isolation Forest)...")
    ml_anomalies = []
    try:
        ml_anomalies = detect_ml_anomalies(tx_list, known_cps)
        ml_anom_count = sum(1 for a in ml_anomalies if a.get("is_anomaly"))
        _log(f"ML anomalie: {ml_anom_count} z {len(ml_anomalies)} transakcji")
    except Exception as e:
        log.warning("ML anomaly detection failed: %s", e)
        warnings.append(f"ML anomaly detection failed: {e}")

    # --- Step 11: Build flow graph ---
    _log("Budowa grafu przepływów...")
    account_label = info.account_holder or info.account_number or "Moje konto"
    graph_data = build_graph(tx_list, case_id=case_id, statement_id=statement_id, account_label=account_label)
    _log(f"Graf: {graph_data['stats']['total_nodes']} węzłów, "
         f"{graph_data['stats']['total_edges']} krawędzi")

    # --- Step 11b: Generate chart data ---
    _log("Generowanie wykresów...")
    charts_data = {}
    try:
        charts_data = generate_all_charts(tx_list, opening_balance=opening)
        _log(f"Wykresy: {len(charts_data)} typów")
    except Exception as e:
        log.warning("Chart generation failed: %s", e)
        warnings.append(f"Chart generation failed: {e}")

    # --- Step 11c: Enrich transactions & build LLM prompt ---
    enriched_result = None
    llm_prompt = ""
    try:
        from .enrich import enrich_transactions
        # Build dicts suitable for enrichment (need date, amount, direction, counterparty, title, etc.)
        enrich_input = []
        for tx in tx_list:
            enrich_input.append({
                "date": tx.booking_date,
                "amount": float(tx.amount),
                "direction": tx.direction,
                "counterparty": tx.counterparty_raw or "",
                "title": tx.title or "",
                "channel": tx.channel or "",
                "category": tx.category or "",
                "counterparty_account": "",
                "raw_86": getattr(tx, "raw_86", ""),
                "swift_code": getattr(tx, "swift_code", ""),
            })
        enriched_result = enrich_transactions(enrich_input)
        _log(f"Wzbogacono transakcje: {len(enriched_result.channel_summary)} kanałów, "
             f"{len(enriched_result.category_summary)} kategorii, "
             f"{len(enriched_result.recurring)} wzorców cyklicznych")
    except Exception as e:
        log.warning("Transaction enrichment failed: %s", e)

    try:
        statement_info_for_llm = {
            "bank_name": bank_name,
            "account_holder": info.account_holder,
            "account_number": info.account_number,
            "period_from": info.period_from,
            "period_to": info.period_to,
            "opening_balance": info.opening_balance,
            "closing_balance": info.closing_balance,
            "currency": info.currency,
            # Extra header fields
            "previous_closing_balance": getattr(info, "previous_closing_balance", None),
            "declared_credits_sum": info.declared_credits_sum,
            "declared_credits_count": info.declared_credits_count,
            "declared_debits_sum": info.declared_debits_sum,
            "declared_debits_count": info.declared_debits_count,
            "debt_limit": getattr(info, "debt_limit", None),
            "overdue_commission": getattr(info, "overdue_commission", None),
            "blocked_amount": getattr(info, "blocked_amount", None),
            "available_balance": info.available_balance,
        }
        llm_prompt = build_aml_prompt(
            statement_info=statement_info_for_llm,
            transactions=tx_list,
            alerts=[a.to_dict() for a in alerts],
            risk_score=risk_score,
            risk_reasons=risk_reasons,
            ml_anomalies=ml_anomalies,
            enriched=enriched_result,
        )
        _log(f"LLM prompt: {len(llm_prompt)} znaków")
    except Exception as e:
        log.warning("LLM prompt build failed: %s", e)

    # --- Step 12: Save transactions to DB ---
    _log("Zapis transakcji do bazy...")
    with get_conn() as conn:
        # Ensure extra columns exist in transactions (migration for older DBs)
        for col in ("raw_text", "tx_date"):
            try:
                conn.execute(f"SELECT {col} FROM transactions LIMIT 0")
            except Exception:
                conn.execute(f"ALTER TABLE transactions ADD COLUMN {col} TEXT DEFAULT ''")

        for tx in tx_list:
            d = tx.to_db_dict()
            # FK constraint: empty counterparty_id must be NULL, not ""
            cp_id = d.get("counterparty_id") or None
            conn.execute(
                """INSERT INTO transactions
                   (id, statement_id, counterparty_id, booking_date, tx_date,
                    amount, currency, direction, balance_after,
                    channel, category, subcategory, risk_tags, risk_score,
                    title, counterparty_raw, bank_category, raw_text,
                    rule_explains, tx_hash, is_recurring, recurring_group)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (d["id"], d["statement_id"], cp_id,
                 d["booking_date"], d["tx_date"],
                 d["amount"], d["currency"], d["direction"], d.get("balance_after"),
                 d["channel"], d["category"], d["subcategory"],
                 d["risk_tags"], d["risk_score"],
                 d["title"], d["counterparty_raw"], d["bank_category"], d["raw_text"],
                 d["rule_explains"], d["tx_hash"],
                 d["is_recurring"], d["recurring_group"]),
            )

        # Save risk assessment
        assessment_id = new_id()
        score_breakdown = {
            "alerts": [a.to_dict() for a in alerts],
            "ml_anomalies": ml_anomalies[:50],  # limit stored anomalies
            "charts": charts_data,
        }
        conn.execute(
            """INSERT INTO risk_assessments
               (id, statement_id, total_score, score_breakdown, risk_reasons, rules_version)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (assessment_id, statement_id, risk_score,
             json.dumps(score_breakdown, ensure_ascii=False),
             json.dumps(risk_reasons, ensure_ascii=False),
             rules_version),
        )

        # Save LLM prompt for later use
        if llm_prompt:
            conn.execute(
                """INSERT OR REPLACE INTO system_config (key, value)
                   VALUES (?, ?)""",
                (f"llm_prompt:{statement_id}", llm_prompt),
            )

        # Audit log
        conn.execute(
            """INSERT INTO audit_log (user_id, case_id, action, details)
               VALUES (?, ?, ?, ?)""",
            (get_default_user_id(), case_id, "aml_analysis",
             json.dumps({
                 "statement_id": statement_id,
                 "pdf_hash": pdf_hash,
                 "ocr_used": ocr_used,
                 "parser": bank_id,
                 "transactions": len(tx_list),
                 "alerts": len(alerts),
                 "risk_score": risk_score,
                 "rules_version": rules_version,
             }, ensure_ascii=False)),
        )

    # --- Step 13: Generate HTML report ---
    _log("Generowanie raportu HTML...")
    statement_info_dict = {
        "bank": bank_id,
        "bank_name": bank_name,
        "period_from": info.period_from,
        "period_to": info.period_to,
        "opening_balance": info.opening_balance,
        "closing_balance": info.closing_balance,
        "account_number": info.account_number,
        "account_holder": info.account_holder,
    }
    audit_info = {
        "ocr_used": ocr_used,
        "ocr_confidence": ocr_confidence,
        "parser_version": f"{bank_id}_v1",
        "rules_version": rules_version,
        "pdf_hash": pdf_hash,
        "warnings": warnings,
    }

    report_html = generate_report(
        transactions=tx_list,
        alerts=alerts,
        graph_data=graph_data,
        risk_score=risk_score,
        risk_reasons=risk_reasons,
        statement_info=statement_info_dict,
        audit_info=audit_info,
        title=f"Raport AML — {bank_name} {info.period_from or ''}",
    )

    # Register source PDF in case_files for traceability & cleanup
    if case_id:
        try:
            add_case_file(
                case_id=case_id,
                file_type="source",
                file_name=pdf_path.name,
                file_path=str(pdf_path),
                mime_type="application/pdf",
                size_bytes=pdf_path.stat().st_size,
                checksum=pdf_hash,
            )
        except Exception:
            pass  # Non-critical

    # Save report
    report_path = None
    if save_report:
        reports_dir = pdf_path.parent / "aml_reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        report_path = reports_dir / f"aml_report_{statement_id[:8]}.html"
        report_path.write_text(report_html, encoding="utf-8")
        _log(f"Raport zapisany: {report_path}")

        # Register in DB
        if case_id:
            add_case_file(
                case_id=case_id,
                file_type="report",
                file_name=report_path.name,
                file_path=str(report_path),
                mime_type="text/html",
                size_bytes=len(report_html.encode("utf-8")),
            )

    # --- Step 14: Save JSON analysis snapshot to project folder ---
    try:
        results_dir = pdf_path.parent / "aml_results"
        results_dir.mkdir(parents=True, exist_ok=True)
        result_json_path = results_dir / f"aml_result_{statement_id[:8]}.json"
        result_snapshot = {
            "statement_id": statement_id,
            "case_id": case_id,
            "account_id": account_profile_id,
            "bank": bank_id,
            "bank_name": bank_name,
            "period_from": getattr(info, "period_from", None),
            "period_to": getattr(info, "period_to", None),
            "account_number": getattr(info, "account_number", None),
            "account_holder": getattr(info, "account_holder", None),
            "transaction_count": len(tx_list),
            "risk_score": risk_score,
            "risk_reasons": risk_reasons,
            "alerts_count": len(alerts),
            "graph_stats": graph_data["stats"],
            "pdf_hash": pdf_hash,
            "ocr_used": ocr_used,
            "warnings": warnings,
        }
        result_json_path.write_text(
            json.dumps(result_snapshot, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        _log(f"Snapshot JSON zapisany: {result_json_path}")
    except Exception as e:
        log.warning("Failed to save JSON snapshot: %s", e)

    dt = time.time() - t0
    _log(f"Pipeline AML zakończony w {dt:.1f}s")

    return {
        "status": "ok",
        "case_id": case_id,
        "statement_id": statement_id,
        "account_id": account_profile_id,
        "bank": bank_id,
        "bank_name": bank_name,
        "transaction_count": len(tx_list),
        "risk_score": risk_score,
        "risk_reasons": risk_reasons,
        "alerts_count": len(alerts),
        "alerts": [a.to_dict() for a in alerts],
        "graph_stats": graph_data["stats"],
        "ml_anomalies_count": sum(1 for a in ml_anomalies if a.get("is_anomaly")),
        "charts": charts_data,
        "has_llm_prompt": bool(llm_prompt),
        "balance_valid": bal_valid,
        "ocr_used": ocr_used,
        "warnings": warnings,
        "report_path": str(report_path) if report_path else None,
        "report_html": report_html,
        "pipeline_time_s": round(dt, 2),
    }
