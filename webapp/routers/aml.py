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
    if risk_row:
        risk = dict(risk_row)
        for jf in ("score_breakdown", "risk_reasons"):
            if risk.get(jf):
                try:
                    risk[jf] = json.loads(risk[jf])
                except (json.JSONDecodeError, TypeError):
                    risk[jf] = {} if jf == "score_breakdown" else []

    # Graph
    from backend.aml.graph import get_graph_json
    graph = get_graph_json(stmt_dict["case_id"])

    return JSONResponse({
        "statement": stmt_dict,
        "transactions": transactions,
        "risk": risk,
        "graph": graph,
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


@router.post("/api/system/migrate")
async def system_migrate():
    """Migrate existing JSON projects to SQLite."""
    from starlette.concurrency import run_in_threadpool
    from backend.db.migrate import migrate_json_projects
    result = await run_in_threadpool(migrate_json_projects)
    return JSONResponse(result)
