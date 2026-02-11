"""AML API router for AISTATEweb.

Endpoints:
- POST /api/aml/analyze        — upload PDF and run full AML pipeline
- GET  /api/aml/history        — list past analyses
- GET  /api/aml/detail/{id}    — full analysis details (statement + transactions + alerts + graph)
- GET  /api/aml/report/{id}    — get generated report HTML
- GET  /api/aml/graph/{id}     — get flow graph JSON (filterable)

- GET  /api/memory             — search/list counterparties
- POST /api/memory             — create counterparty
- PATCH /api/memory/{id}       — update label/note/tags
- POST /api/memory/{id}/alias  — add alias

- GET  /api/memory/queue       — learning queue items
- POST /api/memory/queue/{id}/resolve — approve/reject

- GET  /api/db/projects        — list projects
- POST /api/db/projects        — create project
- GET  /api/db/projects/{id}/cases — list cases

- POST /api/aml/upload-mt940  — upload & parse MT940/STA file
- POST /api/aml/cross-validate — compare MT940 with PDF-parsed data

- GET  /api/system/setup       — first-run check
- POST /api/system/setup       — first-run setup
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, Form, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse

log = logging.getLogger("aistate.api.aml")

router = APIRouter()


# ============================================================
# COLUMN MAPPING (PDF preview & confirm)
# ============================================================

@router.post("/api/aml/preview-pdf")
async def aml_preview_pdf(
    request: Request,
    file: UploadFile = File(...),
):
    """Upload PDF and get spatial parse preview with page images.

    Uses coordinate-based word extraction to detect column boundaries
    and segment multi-line transactions.  Returns page image URLs +
    column zones for the visual SVG mask overlay.
    """
    from starlette.concurrency import run_in_threadpool
    from backend.aml.column_mapper import extract_raw_preview

    data_dir = os.environ.get("AISTATEWEB_DATA_DIR", "data_www")
    upload_dir = Path(data_dir) / "uploads" / "aml"
    upload_dir.mkdir(parents=True, exist_ok=True)

    file_path = upload_dir / (file.filename or "statement.pdf")
    with open(file_path, "wb") as f:
        content = await file.read()
        f.write(content)

    image_dir = upload_dir / ".preview"

    try:
        result = await run_in_threadpool(
            extract_raw_preview, file_path, image_dir,
        )
        result["file_path"] = str(file_path)
        return JSONResponse(result)
    except Exception as e:
        log.exception("PDF spatial preview error")
        return JSONResponse({"status": "error", "error": str(e)}, status_code=500)


@router.get("/api/aml/page-image/{page_num}")
async def aml_page_image(page_num: int):
    """Serve a rendered PDF page image for the visual overlay."""
    from fastapi.responses import FileResponse

    data_dir = os.environ.get("AISTATEWEB_DATA_DIR", "data_www")
    image_path = Path(data_dir) / "uploads" / "aml" / ".preview" / f"page_{page_num}.png"

    if not image_path.exists():
        return JSONResponse({"error": "Page image not found"}, status_code=404)

    return FileResponse(str(image_path), media_type="image/png")


@router.post("/api/aml/confirm-mapping")
async def aml_confirm_mapping(request: Request):
    """Confirm column mapping and run full AML pipeline.

    Accepts user-confirmed column mapping, optionally saves as template,
    then runs the full AML pipeline.
    """
    from starlette.concurrency import run_in_threadpool
    from backend.aml.column_mapper import parse_with_mapping, save_template, increment_template_usage
    from backend.aml.pipeline import run_aml_pipeline

    data = await request.json()
    file_path = Path(data.get("file_path", ""))
    column_mapping = data.get("column_mapping", {})
    header_row = data.get("header_row", 0)
    data_start_row = data.get("data_start_row", 1)
    main_table_index = data.get("main_table_index", 0)
    save_as_template = data.get("save_template", False)
    template_name = data.get("template_name", "")
    set_default = data.get("set_default", False)
    template_id = data.get("template_id", "")  # existing template used
    bank_id = data.get("bank_id", "")
    bank_name = data.get("bank_name", "")
    header_cells = data.get("header_cells", [])
    column_bounds = data.get("column_bounds")  # [{x_min, x_max, label, col_type}, ...]
    header_fields = data.get("header_fields", {})  # {field_type: value, ...}

    if not file_path.exists():
        return JSONResponse({"status": "error", "error": "PDF file not found"}, status_code=404)

    # Save template if requested
    if save_as_template and column_mapping:
        save_template(
            bank_id=bank_id,
            bank_name=bank_name,
            column_mapping=column_mapping,
            header_cells=header_cells,
            header_row=header_row,
            data_start_row=data_start_row,
            name=template_name,
            is_default=set_default,
        )

    # Track template usage
    if template_id:
        increment_template_usage(template_id)

    # Run full pipeline with user-confirmed column mapping and header fields
    try:
        result = await run_in_threadpool(
            run_aml_pipeline,
            pdf_path=file_path,
            column_mapping=column_mapping,
            column_bounds=column_bounds,
            header_fields=header_fields,
        )
        result.pop("report_html", None)
        return JSONResponse(result)
    except Exception as e:
        log.exception("AML pipeline error (confirmed mapping)")
        return JSONResponse({"status": "error", "error": str(e)}, status_code=500)


@router.post("/api/aml/preview-parse")
async def aml_preview_parse(request: Request):
    """Preview parsing result with user-adjusted column mapping.

    Uses spatial parsing with optional user-dragged column boundaries.
    """
    from starlette.concurrency import run_in_threadpool
    from backend.aml.column_mapper import parse_with_mapping

    data = await request.json()
    file_path = Path(data.get("file_path", ""))
    column_mapping = data.get("column_mapping", {})
    column_bounds = data.get("column_bounds")  # [{x_min, x_max}, ...]

    if not file_path.exists():
        return JSONResponse({"status": "error", "error": "PDF file not found"}, status_code=404)

    try:
        result = await run_in_threadpool(
            parse_with_mapping, file_path, column_mapping,
            column_bounds=column_bounds,
        )
        return JSONResponse(result)
    except Exception as e:
        log.exception("Preview parse error")
        return JSONResponse({"status": "error", "error": str(e)}, status_code=500)


@router.get("/api/aml/templates")
async def aml_templates_list(bank_id: str = Query("")):
    """List saved column mapping templates."""
    from backend.aml.column_mapper import list_templates
    templates = list_templates(bank_id=bank_id)
    return JSONResponse({"templates": templates, "count": len(templates)})


@router.delete("/api/aml/templates/{template_id}")
async def aml_templates_delete(template_id: str):
    """Delete a template."""
    from backend.aml.column_mapper import delete_template
    delete_template(template_id)
    return JSONResponse({"status": "ok"})


@router.get("/api/aml/column-types")
async def aml_column_types():
    """Get available column type definitions."""
    from backend.aml.column_mapper import get_column_types_meta
    return JSONResponse(get_column_types_meta())


# ============================================================
# AML ANALYSIS
# ============================================================

@router.post("/api/aml/analyze")
async def aml_analyze(
    request: Request,
    file: UploadFile = File(...),
    project_id: str = Form(""),
    case_id: str = Form(""),
):
    """Upload a bank statement PDF and run full AML analysis."""
    from starlette.concurrency import run_in_threadpool
    from backend.aml.pipeline import run_aml_pipeline

    # Save uploaded file
    data_dir = os.environ.get("AISTATEWEB_DATA_DIR", "data_www")
    upload_dir = Path(data_dir) / "uploads" / "aml"
    upload_dir.mkdir(parents=True, exist_ok=True)

    file_path = upload_dir / (file.filename or "statement.pdf")
    with open(file_path, "wb") as f:
        content = await file.read()
        f.write(content)

    try:
        result = await run_in_threadpool(
            run_aml_pipeline,
            pdf_path=file_path,
            case_id=case_id,
            project_id=project_id,
        )
        # Don't send full HTML in JSON response (too large)
        result.pop("report_html", None)
        return JSONResponse(result)
    except Exception as e:
        log.exception("AML pipeline error")
        return JSONResponse({"status": "error", "error": str(e)}, status_code=500)


@router.get("/api/aml/report/{statement_id}")
async def aml_report(statement_id: str):
    """Get generated AML report HTML."""
    from backend.db.engine import fetch_one

    row = fetch_one(
        """SELECT cf.file_path FROM case_files cf
           JOIN cases c ON cf.case_id = c.id
           JOIN statements s ON s.case_id = c.id
           WHERE s.id = ? AND cf.file_type = 'report' AND cf.file_name LIKE 'aml_report%'
           ORDER BY cf.created_at DESC LIMIT 1""",
        (statement_id,),
    )
    if not row:
        return JSONResponse({"error": "report not found"}, status_code=404)

    report_path = Path(row["file_path"])
    if not report_path.exists():
        return JSONResponse({"error": "report file missing"}, status_code=404)

    html_content = report_path.read_text(encoding="utf-8")
    return HTMLResponse(html_content)


@router.get("/api/aml/graph/{case_id}")
async def aml_graph(
    case_id: str,
    date_from: str = Query(""),
    date_to: str = Query(""),
    channel: str = Query(""),
    risk_level: str = Query(""),
    counterparty: str = Query(""),
):
    """Get flow graph JSON for a case, with optional filters."""
    from backend.aml.graph import filter_graph, get_graph_json

    graph = get_graph_json(case_id)
    if not graph["nodes"]:
        return JSONResponse({"error": "no graph data"}, status_code=404)

    # Apply filters if any
    channels = [c.strip() for c in channel.split(",") if c.strip()] if channel else None
    risk_levels = [r.strip() for r in risk_level.split(",") if r.strip()] if risk_level else None

    if date_from or date_to or channels or risk_levels or counterparty:
        graph = filter_graph(
            graph,
            date_from=date_from,
            date_to=date_to,
            channels=channels,
            risk_levels=risk_levels,
            counterparty_query=counterparty,
        )

    return JSONResponse(graph)


@router.get("/api/aml/charts/{statement_id}")
async def aml_charts(statement_id: str):
    """Get chart data for a statement (stored in risk_assessments.score_breakdown)."""
    from backend.db.engine import fetch_one

    risk_row = fetch_one(
        """SELECT score_breakdown FROM risk_assessments
           WHERE statement_id = ? ORDER BY created_at DESC LIMIT 1""",
        (statement_id,),
    )
    if not risk_row or not risk_row["score_breakdown"]:
        return JSONResponse({"error": "no chart data"}, status_code=404)

    try:
        breakdown = json.loads(risk_row["score_breakdown"])
        charts = breakdown.get("charts", {})
    except (json.JSONDecodeError, TypeError):
        charts = {}

    if not charts:
        return JSONResponse({"error": "no chart data"}, status_code=404)

    return JSONResponse(charts)


@router.post("/api/aml/llm-analyze/{statement_id}")
async def aml_llm_analyze(statement_id: str, request: Request):
    """Run LLM narrative analysis on an existing AML analysis.

    Retrieves the stored LLM prompt and sends it to Ollama.
    Returns the LLM's analysis text.
    """
    from starlette.concurrency import run_in_threadpool
    from backend.db.engine import fetch_one
    import asyncio

    # Get stored LLM prompt
    row = fetch_one(
        "SELECT value FROM system_config WHERE key = ?",
        (f"llm_prompt:{statement_id}",),
    )
    if not row or not row["value"]:
        return JSONResponse({"error": "No LLM prompt found. Re-run the analysis."}, status_code=404)

    prompt = row["value"]

    # Optional: get model from request body
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass
    model = body.get("model", "")

    try:
        from backend.aml.llm_analysis import run_llm_analysis
        result_text = await run_llm_analysis(prompt, model=model)
        return JSONResponse({"status": "ok", "analysis": result_text})
    except RuntimeError as e:
        return JSONResponse({"status": "error", "error": str(e)}, status_code=503)
    except Exception as e:
        log.exception("LLM analysis error")
        return JSONResponse({"status": "error", "error": str(e)}, status_code=500)


@router.get("/api/aml/history")
async def aml_history(limit: int = Query(20)):
    """List past AML analyses with basic info."""
    from backend.db.engine import fetch_all

    rows = fetch_all(
        """SELECT s.id AS statement_id, s.case_id, s.bank_name, s.account_holder,
                  s.period_from, s.period_to, s.opening_balance, s.closing_balance,
                  s.currency, s.created_at,
                  r.total_score AS risk_score,
                  (SELECT COUNT(*) FROM transactions t WHERE t.statement_id = s.id) AS tx_count
           FROM statements s
           LEFT JOIN risk_assessments r ON r.statement_id = s.id
           ORDER BY s.created_at DESC
           LIMIT ?""",
        (limit,),
    )
    items = []
    for row in rows:
        items.append({
            "statement_id": row["statement_id"],
            "case_id": row["case_id"],
            "bank_name": row["bank_name"] or "",
            "account_holder": row["account_holder"] or "",
            "period_from": row["period_from"] or "",
            "period_to": row["period_to"] or "",
            "opening_balance": row["opening_balance"],
            "closing_balance": row["closing_balance"],
            "currency": row["currency"] or "PLN",
            "risk_score": row["risk_score"],
            "tx_count": row["tx_count"] or 0,
            "created_at": row["created_at"] or "",
        })
    return JSONResponse({"items": items, "count": len(items)})


@router.get("/api/aml/detail/{statement_id}")
async def aml_detail(statement_id: str):
    """Full analysis details: statement + transactions + risk + graph."""
    from backend.db.engine import fetch_all, fetch_one

    stmt = fetch_one("SELECT * FROM statements WHERE id = ?", (statement_id,))
    if not stmt:
        return JSONResponse({"error": "not found"}, status_code=404)

    # Statement info
    stmt_dict = dict(stmt)
    for k in ("warnings",):
        if stmt_dict.get(k):
            try:
                stmt_dict[k] = json.loads(stmt_dict[k])
            except (json.JSONDecodeError, TypeError):
                stmt_dict[k] = []

    # Transactions
    tx_rows = fetch_all(
        """SELECT id, booking_date, amount, direction, counterparty_raw,
                  channel, category, subcategory, risk_tags, risk_score,
                  title, bank_category, balance_after, rule_explains
           FROM transactions WHERE statement_id = ?
           ORDER BY booking_date, id""",
        (statement_id,),
    )
    transactions = []
    for row in tx_rows:
        tx = dict(row)
        for jf in ("risk_tags", "rule_explains"):
            if tx.get(jf):
                try:
                    tx[jf] = json.loads(tx[jf])
                except (json.JSONDecodeError, TypeError):
                    tx[jf] = []
        transactions.append(tx)

    # Risk assessment
    risk_row = fetch_one(
        """SELECT * FROM risk_assessments
           WHERE statement_id = ? ORDER BY created_at DESC LIMIT 1""",
        (statement_id,),
    )
    risk = None
    charts = {}
    ml_anomalies = []
    if risk_row:
        risk = dict(risk_row)
        for jf in ("score_breakdown", "risk_reasons"):
            if risk.get(jf):
                try:
                    risk[jf] = json.loads(risk[jf])
                except (json.JSONDecodeError, TypeError):
                    risk[jf] = {} if jf == "score_breakdown" else []
        # Extract charts and ml_anomalies from score_breakdown
        if isinstance(risk.get("score_breakdown"), dict):
            charts = risk["score_breakdown"].get("charts", {})
            ml_anomalies = risk["score_breakdown"].get("ml_anomalies", [])

    # Graph
    from backend.aml.graph import get_graph_json
    graph = get_graph_json(stmt_dict["case_id"])

    # Check if LLM prompt is available
    from backend.db.engine import fetch_one as _fo
    llm_row = _fo(
        "SELECT key FROM system_config WHERE key = ?",
        (f"llm_prompt:{statement_id}",),
    )
    has_llm_prompt = llm_row is not None

    return JSONResponse({
        "statement": stmt_dict,
        "transactions": transactions,
        "risk": risk,
        "graph": graph,
        "charts": charts,
        "ml_anomalies": ml_anomalies,
        "has_llm_prompt": has_llm_prompt,
    })


# ============================================================
# COUNTERPARTY MEMORY
# ============================================================

@router.get("/api/memory")
async def memory_list(
    q: str = Query(""),
    label: str = Query(""),
    limit: int = Query(50),
):
    """Search/list counterparties."""
    from backend.aml.memory import search_counterparties
    results = search_counterparties(query=q, label=label or None, limit=limit)
    return JSONResponse({"counterparties": results, "count": len(results)})


@router.post("/api/memory")
async def memory_create(request: Request):
    """Create a new counterparty entry."""
    from backend.aml.memory import create_counterparty
    data = await request.json()
    cp = create_counterparty(
        canonical_name=data.get("name", ""),
        label=data.get("label", "neutral"),
        note=data.get("note", ""),
        tags=data.get("tags", []),
    )
    return JSONResponse({"status": "ok", "counterparty": cp})


@router.patch("/api/memory/{cp_id}")
async def memory_update(cp_id: str, request: Request):
    """Update counterparty label/note/tags."""
    from backend.aml.memory import update_counterparty
    data = await request.json()
    cp = update_counterparty(
        cp_id=cp_id,
        label=data.get("label"),
        note=data.get("note"),
        tags=data.get("tags"),
    )
    if not cp:
        return JSONResponse({"error": "not found"}, status_code=404)
    return JSONResponse({"status": "ok", "counterparty": cp})


@router.post("/api/memory/{cp_id}/alias")
async def memory_add_alias(cp_id: str, request: Request):
    """Add an alias to a counterparty."""
    from backend.aml.memory import add_alias
    data = await request.json()
    add_alias(cp_id, data.get("alias", ""), source="manual")
    return JSONResponse({"status": "ok"})


@router.get("/api/memory/queue")
async def memory_queue(status: str = Query("pending"), limit: int = Query(50)):
    """Get learning queue items."""
    from backend.aml.memory import get_learning_queue
    items = get_learning_queue(status=status, limit=limit)
    return JSONResponse({"items": items, "count": len(items)})


@router.post("/api/memory/queue/{item_id}/resolve")
async def memory_queue_resolve(item_id: str, request: Request):
    """Resolve a learning queue item."""
    from backend.aml.memory import resolve_learning_item
    data = await request.json()
    resolve_learning_item(
        item_id=item_id,
        decision=data.get("decision", "approved"),
        label=data.get("label", "neutral"),
        note=data.get("note", ""),
    )
    return JSONResponse({"status": "ok"})


# ============================================================
# TRANSACTION REVIEW & CLASSIFICATION
# ============================================================

@router.get("/api/aml/review/{statement_id}")
async def aml_review_transactions(statement_id: str):
    """Get transactions for review with existing classifications."""
    from backend.aml.review import get_review_transactions, get_statement_header, get_classification_stats

    transactions = get_review_transactions(statement_id)
    header = get_statement_header(statement_id)
    stats = get_classification_stats(statement_id)

    return JSONResponse({
        "transactions": transactions,
        "header": header,
        "classification_stats": stats,
        "total": len(transactions),
    })


@router.get("/api/aml/review/{statement_id}/header")
async def aml_review_header(statement_id: str):
    """Get statement header blocks for review/correction."""
    from backend.aml.review import get_statement_header
    header = get_statement_header(statement_id)
    if not header:
        return JSONResponse({"error": "not found"}, status_code=404)
    return JSONResponse(header)


@router.post("/api/aml/review/{statement_id}/classify")
async def aml_classify_transaction(statement_id: str, request: Request):
    """Classify a single transaction."""
    from backend.aml.review import classify_transaction
    data = await request.json()
    result = classify_transaction(
        tx_id=data.get("tx_id", ""),
        statement_id=statement_id,
        classification=data.get("classification", "neutral"),
        note=data.get("note", ""),
    )
    return JSONResponse({"status": "ok", **result})


@router.post("/api/aml/review/{statement_id}/classify-batch")
async def aml_classify_batch(statement_id: str, request: Request):
    """Classify multiple transactions at once."""
    from backend.aml.review import classify_batch
    data = await request.json()
    result = classify_batch(
        items=data.get("items", []),
        statement_id=statement_id,
    )
    return JSONResponse({"status": "ok", **result})


@router.get("/api/aml/review/{statement_id}/stats")
async def aml_classification_stats(statement_id: str):
    """Get classification stats for a statement."""
    from backend.aml.review import get_classification_stats
    stats = get_classification_stats(statement_id)
    return JSONResponse(stats)


@router.get("/api/aml/review/global/stats")
async def aml_global_stats():
    """Get global classification stats."""
    from backend.aml.review import get_global_classification_stats
    return JSONResponse(get_global_classification_stats())


@router.post("/api/aml/review/{statement_id}/header-update")
async def aml_update_header(statement_id: str, request: Request):
    """Update a statement header field (user correction)."""
    from backend.aml.review import update_statement_field
    data = await request.json()
    ok = update_statement_field(
        statement_id=statement_id,
        field=data.get("field", ""),
        value=data.get("value", ""),
    )
    if not ok:
        return JSONResponse({"error": "Field not editable"}, status_code=400)
    return JSONResponse({"status": "ok"})


@router.get("/api/aml/classifications-meta")
async def aml_classifications_meta():
    """Get classification labels metadata."""
    from backend.aml.review import get_classifications_meta
    return JSONResponse(get_classifications_meta())


# ============================================================
# ACCOUNT PROFILES
# ============================================================

@router.get("/api/aml/accounts")
async def aml_accounts_list():
    """List all account profiles."""
    from backend.aml.anonymize import list_profiles
    profiles = list_profiles()
    return JSONResponse({"profiles": profiles, "count": len(profiles)})


@router.post("/api/aml/accounts")
async def aml_accounts_create(request: Request):
    """Create or get account profile."""
    from backend.aml.anonymize import get_or_create_profile
    data = await request.json()
    profile = get_or_create_profile(
        account_number=data.get("account_number", ""),
        bank_id=data.get("bank_id", ""),
        bank_name=data.get("bank_name", ""),
        account_holder=data.get("account_holder", ""),
        account_type=data.get("account_type", "private"),
    )
    return JSONResponse({"status": "ok", "profile": profile})


@router.patch("/api/aml/accounts/{profile_id}")
async def aml_accounts_update(profile_id: str, request: Request):
    """Update account profile settings."""
    from backend.aml.anonymize import update_profile
    data = await request.json()
    profile = update_profile(
        profile_id=profile_id,
        account_type=data.get("account_type"),
        display_name=data.get("display_name"),
        is_anonymized=data.get("is_anonymized"),
    )
    if not profile:
        return JSONResponse({"error": "not found"}, status_code=404)
    return JSONResponse({"status": "ok", "profile": profile})


@router.get("/api/aml/accounts/for-statement/{statement_id}")
async def aml_account_for_statement(statement_id: str):
    """Get account profile linked to a statement."""
    from backend.aml.anonymize import get_profile_for_statement, anonymize_iban, anonymize_holder
    profile = get_profile_for_statement(statement_id)
    if not profile:
        return JSONResponse({"profile": None})

    # Add anonymized display fields
    profile["display_iban"] = anonymize_iban(
        profile.get("account_number", ""),
        profile.get("account_type", "private"),
    )
    profile["display_holder"] = anonymize_holder(
        profile.get("display_name", ""),
        profile.get("account_type", "private"),
        profile.get("owner_label", ""),
    )
    return JSONResponse({"profile": profile})


# ============================================================
# FIELD MAPPING RULES
# ============================================================

@router.get("/api/aml/field-rules")
async def aml_field_rules(bank_id: str = Query("")):
    """List field mapping rules."""
    from backend.aml.review import get_field_rules
    rules = get_field_rules(bank_id=bank_id)
    return JSONResponse({"rules": rules, "count": len(rules)})


@router.post("/api/aml/field-rules")
async def aml_field_rules_create(request: Request):
    """Create a field mapping rule."""
    from backend.aml.review import save_field_rule
    data = await request.json()
    rule_id = save_field_rule(
        bank_id=data.get("bank_id", ""),
        rule_type=data.get("rule_type", "header_remap"),
        source_field=data.get("source_field", ""),
        target_field=data.get("target_field", ""),
        condition=data.get("condition"),
        note=data.get("note", ""),
    )
    return JSONResponse({"status": "ok", "rule_id": rule_id})


@router.delete("/api/aml/field-rules/{rule_id}")
async def aml_field_rules_delete(rule_id: str):
    """Deactivate a field mapping rule."""
    from backend.aml.review import delete_field_rule
    delete_field_rule(rule_id)
    return JSONResponse({"status": "ok"})


# ============================================================
# PROJECTS & CASES
# ============================================================

@router.get("/api/db/projects")
async def db_projects_list(status: str = Query("active")):
    """List all projects from DB."""
    from backend.db.projects import list_projects
    from backend.db.engine import get_default_user_id
    projects = list_projects(owner_id=get_default_user_id(), status=status)
    return JSONResponse({"projects": projects})


@router.post("/api/db/projects")
async def db_projects_create(request: Request):
    """Create a new project."""
    from backend.db.projects import create_project
    from backend.db.engine import get_default_user_id
    data = await request.json()
    project = create_project(
        owner_id=get_default_user_id(),
        name=data.get("name", "Nowy projekt"),
        description=data.get("description", ""),
    )
    return JSONResponse({"status": "ok", "project": project})


@router.get("/api/db/projects/{project_id}/cases")
async def db_cases_list(project_id: str, case_type: str = Query(""), status: str = Query("")):
    """List cases for a project."""
    from backend.db.projects import list_cases
    cases = list_cases(
        project_id=project_id,
        case_type=case_type or None,
        status=status or None,
    )
    return JSONResponse({"cases": cases})


# ============================================================
# SYSTEM SETUP
# ============================================================

@router.get("/api/system/setup")
async def system_setup_check():
    """Check if first-run setup is needed."""
    from backend.db.engine import get_system_config, is_first_run
    return JSONResponse({
        "first_run": is_first_run(),
        "mode": get_system_config("deployment_mode", "single"),
        "db_version": get_system_config("db_version", ""),
    })


@router.post("/api/system/setup")
async def system_setup(request: Request):
    """First-run setup: create admin user and configure mode."""
    from backend.db.engine import (
        create_default_admin,
        is_first_run,
        set_system_config,
    )

    if not is_first_run():
        return JSONResponse({"status": "already_configured"})

    data = await request.json()
    mode = data.get("mode", "single")  # single | multi

    admin_id = create_default_admin()
    set_system_config("deployment_mode", mode)
    set_system_config("setup_complete", "true")

    return JSONResponse({
        "status": "ok",
        "mode": mode,
        "admin_id": admin_id,
    })


# ============================================================
# MT940 IMPORT & CROSS-VALIDATION
# ============================================================

@router.post("/api/aml/upload-mt940")
async def aml_upload_mt940(
    request: Request,
    file: UploadFile = File(...),
):
    """Upload MT940/STA file and parse it.

    Returns parsed statement summary + all transactions.
    """
    from starlette.concurrency import run_in_threadpool
    from backend.aml.mt940_parser import parse_mt940, statement_summary

    data_dir = os.environ.get("AISTATEWEB_DATA_DIR", "data_www")
    upload_dir = Path(data_dir) / "uploads" / "aml"
    upload_dir.mkdir(parents=True, exist_ok=True)

    file_path = upload_dir / (file.filename or "statement.sta")
    with open(file_path, "wb") as f:
        content = await file.read()
        f.write(content)

    try:
        stmt = await run_in_threadpool(parse_mt940, file_path)
        summary = statement_summary(stmt)

        # Convert transactions to dicts for JSON
        transactions = []
        for tx in stmt.transactions:
            sign = -1 if tx.direction == "DEBIT" else 1
            transactions.append({
                "row_index": tx.row_index,
                "date": tx.entry_date,
                "value_date": tx.value_date,
                "amount": round(tx.amount * sign, 2),
                "direction": tx.direction,
                "counterparty": tx.counterparty,
                "title": tx.title,
                "counterparty_account": tx.counterparty_account,
                "swift_code": tx.swift_code,
                "reference": tx.reference,
            })

        return JSONResponse({
            "status": "ok",
            "source": "mt940",
            "file_name": file.filename,
            "summary": summary,
            "transactions": transactions,
        })

    except Exception as e:
        log.exception("MT940 parse failed: %s", e)
        return JSONResponse({"status": "error", "error": str(e)}, status_code=400)


@router.post("/api/aml/cross-validate")
async def aml_cross_validate(request: Request):
    """Cross-validate MT940 data with PDF-parsed data.

    Expects JSON body: {
        mt940_file: str (filename in uploads/aml/),
        pdf_transactions: [...],
        pdf_statement_info: {...}
    }
    """
    from starlette.concurrency import run_in_threadpool
    from backend.aml.mt940_parser import parse_mt940, cross_validate

    data = await request.json()
    mt940_file = data.get("mt940_file", "")
    pdf_transactions = data.get("pdf_transactions", [])
    pdf_statement_info = data.get("pdf_statement_info", {})

    data_dir = os.environ.get("AISTATEWEB_DATA_DIR", "data_www")
    file_path = Path(data_dir) / "uploads" / "aml" / mt940_file

    if not file_path.exists():
        return JSONResponse(
            {"status": "error", "error": "MT940 file not found"},
            status_code=404,
        )

    try:
        stmt = await run_in_threadpool(parse_mt940, file_path)
        report = cross_validate(stmt, pdf_transactions, pdf_statement_info)
        return JSONResponse({"status": "ok", **report})
    except Exception as e:
        log.exception("Cross-validation failed: %s", e)
        return JSONResponse({"status": "error", "error": str(e)}, status_code=500)


@router.post("/api/system/migrate")
async def system_migrate():
    """Migrate existing JSON projects to SQLite."""
    from starlette.concurrency import run_in_threadpool
    from backend.db.migrate import migrate_json_projects
    result = await run_in_threadpool(migrate_json_projects)
    return JSONResponse(result)
