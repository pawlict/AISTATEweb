"""AML Analysis Pipeline — end-to-end orchestration.

upload PDF → detect bank → parse → normalize → rules → baseline →
anomaly → graph → score → report HTML → audit log.

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
from ..finance.parsers.base import ParseResult
from ..finance.pipeline import extract_header_words, extract_pdf_tables
from ..finance.parsers import get_parser
from ..finance.parsers.base import reconcile_balances, validate_balance_chain

from .baseline import AnomalyAlert, build_baseline, detect_anomalies
from .graph import build_graph
from .memory import (
    get_counterparty_labels,
    get_counterparty_notes,
    resolve_entity,
)
from .normalize import NormalizedTransaction, normalize_transactions
from .report import generate_report
from .rules import classify_all, compute_risk_score, load_rules

log = logging.getLogger("aistate.aml.pipeline")


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


def run_aml_pipeline(
    pdf_path: Path,
    case_id: str = "",
    project_id: str = "",
    save_report: bool = True,
    log_cb=None,
) -> Dict[str, Any]:
    """Run the full AML analysis pipeline on a bank statement PDF.

    Args:
        pdf_path: Path to bank statement PDF
        case_id: Existing case ID (or empty to create new)
        project_id: Project ID for new case creation
        save_report: Whether to save HTML report to disk
        log_cb: Optional progress callback

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

    pdf_hash = _compute_pdf_hash(pdf_path)
    rules_config = load_rules()
    rules_version = rules_config.get("version", "1.0.0")
    warnings: List[str] = []

    # --- Step 1: Extract text and tables ---
    _log("Ekstrakcja tekstu z PDF...")
    tables, full_text, page_count = extract_pdf_tables(pdf_path)
    _log(f"Wyodrębniono {len(tables)} tabel z {page_count} stron")

    # --- Step 2: OCR if needed ---
    ocr_used = False
    ocr_confidence = 0.0
    if _check_ocr_needed(full_text, page_count):
        _log("Brak warstwy tekstowej — uruchamiam OCR...")
        ocr_text, ocr_confidence = _run_ocr(pdf_path)
        if ocr_text:
            full_text = ocr_text
            ocr_used = True
            _log(f"OCR zakończony (confidence: {ocr_confidence:.1%})")
        else:
            warnings.append("OCR nie powiódł się — brak wymaganych bibliotek (pytesseract, PyMuPDF)")
            _log("OCR niedostępny")

    # --- Step 3: Detect bank and parse ---
    _log("Rozpoznawanie banku...")
    parser = get_parser(full_text[:5000])
    _log(f"Bank: {parser.BANK_NAME}")

    header_words = None
    if parser.BANK_ID == "ing":
        _log("Ekstrakcja pozycyjna nagłówka (ING)...")
        header_words = extract_header_words(pdf_path)

    _log("Parsowanie transakcji...")
    parse_result: ParseResult = parser.parse(tables, full_text, header_words=header_words)
    parse_result.page_count = page_count
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
        _log("Łańcuch sald: OK ✓")
    else:
        _log("Łańcuch sald: ROZBIEŻNOŚCI")

    # --- Step 5: Save statement to DB ---
    _log("Zapis do bazy danych...")
    statement_id = new_id()
    info = parse_result.info

    with get_conn() as conn:
        # Create case if needed
        if not case_id:
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

        # Save statement
        conn.execute(
            """INSERT INTO statements
               (id, case_id, bank_id, bank_name, period_from, period_to,
                opening_balance, closing_balance, available_balance, currency,
                account_number, account_holder,
                declared_credits_sum, declared_credits_count,
                declared_debits_sum, declared_debits_count,
                parse_method, ocr_used, ocr_confidence,
                parser_version, pdf_hash, warnings)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (statement_id, case_id, parser.BANK_ID, parser.BANK_NAME,
             info.period_from, info.period_to,
             str(info.opening_balance) if info.opening_balance is not None else None,
             str(info.closing_balance) if info.closing_balance is not None else None,
             str(info.available_balance) if info.available_balance is not None else None,
             info.currency, info.account_number, info.account_holder,
             str(info.declared_credits_sum) if info.declared_credits_sum is not None else None,
             info.declared_credits_count,
             str(info.declared_debits_sum) if info.declared_debits_sum is not None else None,
             info.declared_debits_count,
             parse_result.parse_method, int(ocr_used), ocr_confidence,
             f"{parser.BANK_ID}_v1", pdf_hash,
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
                source_bank=parser.BANK_ID,
                amount=float(tx.amount),
                date=tx.booking_date,
            )
            tx.counterparty_id = cp_id

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

    # --- Step 11: Build flow graph ---
    _log("Budowa grafu przepływów...")
    account_label = info.account_holder or info.account_number or "Moje konto"
    graph_data = build_graph(tx_list, case_id=case_id, account_label=account_label)
    _log(f"Graf: {graph_data['stats']['total_nodes']} węzłów, "
         f"{graph_data['stats']['total_edges']} krawędzi")

    # --- Step 12: Save transactions to DB ---
    _log("Zapis transakcji do bazy...")
    with get_conn() as conn:
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
        conn.execute(
            """INSERT INTO risk_assessments
               (id, statement_id, total_score, score_breakdown, risk_reasons, rules_version)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (assessment_id, statement_id, risk_score,
             json.dumps({"alerts": [a.to_dict() for a in alerts]}, ensure_ascii=False),
             json.dumps(risk_reasons, ensure_ascii=False),
             rules_version),
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
                 "parser": parser.BANK_ID,
                 "transactions": len(tx_list),
                 "alerts": len(alerts),
                 "risk_score": risk_score,
                 "rules_version": rules_version,
             }, ensure_ascii=False)),
        )

    # --- Step 13: Generate HTML report ---
    _log("Generowanie raportu HTML...")
    statement_info_dict = {
        "bank": parser.BANK_ID,
        "bank_name": parser.BANK_NAME,
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
        "parser_version": f"{parser.BANK_ID}_v1",
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
        title=f"Raport AML — {parser.BANK_NAME} {info.period_from or ''}",
    )

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

    dt = time.time() - t0
    _log(f"Pipeline AML zakończony w {dt:.1f}s")

    return {
        "status": "ok",
        "case_id": case_id,
        "statement_id": statement_id,
        "bank": parser.BANK_ID,
        "bank_name": parser.BANK_NAME,
        "transaction_count": len(tx_list),
        "risk_score": risk_score,
        "risk_reasons": risk_reasons,
        "alerts_count": len(alerts),
        "alerts": [a.to_dict() for a in alerts],
        "graph_stats": graph_data["stats"],
        "balance_valid": bal_valid,
        "ocr_used": ocr_used,
        "warnings": warnings,
        "report_path": str(report_path) if report_path else None,
        "report_html": report_html,
        "pipeline_time_s": round(dt, 2),
    }
