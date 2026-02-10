"""Project and case management on top of SQLite.

Provides CRUD operations for projects, cases, and files.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from .engine import fetch_all, fetch_one, get_conn, new_id

log = logging.getLogger("aistate.db.projects")


# ============================================================
# PROJECTS
# ============================================================

def create_project(
    owner_id: str,
    name: str,
    description: str = "",
) -> Dict[str, Any]:
    """Create a new project. Returns the project dict."""
    project_id = new_id()
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO projects (id, owner_id, name, description)
               VALUES (?, ?, ?, ?)""",
            (project_id, owner_id, name, description),
        )
    return get_project(project_id)  # type: ignore


def get_project(project_id: str) -> Optional[Dict[str, Any]]:
    """Get project by ID."""
    return fetch_one(
        "SELECT * FROM projects WHERE id = ? AND status != 'deleted'",
        (project_id,),
    )


def list_projects(
    owner_id: Optional[str] = None,
    status: str = "active",
) -> List[Dict[str, Any]]:
    """List projects, optionally filtered by owner and status."""
    if owner_id:
        return fetch_all(
            "SELECT * FROM projects WHERE owner_id = ? AND status = ? ORDER BY updated_at DESC",
            (owner_id, status),
        )
    return fetch_all(
        "SELECT * FROM projects WHERE status = ? ORDER BY updated_at DESC",
        (status,),
    )


def update_project(
    project_id: str,
    **kwargs: Any,
) -> Optional[Dict[str, Any]]:
    """Update project fields. Allowed: name, description, status."""
    allowed = {"name", "description", "status"}
    updates = {k: v for k, v in kwargs.items() if k in allowed}
    if not updates:
        return get_project(project_id)

    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [project_id]

    with get_conn() as conn:
        conn.execute(
            f"UPDATE projects SET {set_clause}, updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE id = ?",
            values,
        )
    return get_project(project_id)


def delete_project(project_id: str) -> bool:
    """Soft-delete a project."""
    with get_conn() as conn:
        cur = conn.execute(
            "UPDATE projects SET status = 'deleted', updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE id = ?",
            (project_id,),
        )
    return cur.rowcount > 0


# ============================================================
# CASES
# ============================================================

def create_case(
    project_id: str,
    name: str,
    case_type: str,
    data_dir: str = "",
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Create a new case within a project."""
    case_id = new_id()
    meta_json = json.dumps(metadata or {}, ensure_ascii=False)
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO cases (id, project_id, name, case_type, data_dir, metadata)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (case_id, project_id, name, case_type, data_dir, meta_json),
        )
    return get_case(case_id)  # type: ignore


def get_case(case_id: str) -> Optional[Dict[str, Any]]:
    """Get case by ID."""
    row = fetch_one("SELECT * FROM cases WHERE id = ?", (case_id,))
    if row and row.get("metadata"):
        try:
            row["metadata"] = json.loads(row["metadata"])
        except (json.JSONDecodeError, TypeError):
            row["metadata"] = {}
    return row


def list_cases(
    project_id: str,
    case_type: Optional[str] = None,
    status: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """List cases for a project."""
    sql = "SELECT * FROM cases WHERE project_id = ?"
    params: list = [project_id]

    if case_type:
        sql += " AND case_type = ?"
        params.append(case_type)
    if status:
        sql += " AND status = ?"
        params.append(status)

    sql += " ORDER BY updated_at DESC"
    rows = fetch_all(sql, tuple(params))
    for row in rows:
        if row.get("metadata"):
            try:
                row["metadata"] = json.loads(row["metadata"])
            except (json.JSONDecodeError, TypeError):
                row["metadata"] = {}
    return rows


def update_case(case_id: str, **kwargs: Any) -> Optional[Dict[str, Any]]:
    """Update case fields."""
    allowed = {"name", "case_type", "status", "data_dir", "metadata"}
    updates = {}
    for k, v in kwargs.items():
        if k not in allowed:
            continue
        if k == "metadata" and isinstance(v, dict):
            updates[k] = json.dumps(v, ensure_ascii=False)
        else:
            updates[k] = v

    if not updates:
        return get_case(case_id)

    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [case_id]

    with get_conn() as conn:
        conn.execute(
            f"UPDATE cases SET {set_clause}, updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE id = ?",
            values,
        )
    return get_case(case_id)


def delete_case(case_id: str) -> bool:
    """Delete a case (hard delete — cascades to files, transactions, etc.)."""
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM cases WHERE id = ?", (case_id,))
    return cur.rowcount > 0


# ============================================================
# CASE FILES
# ============================================================

def add_case_file(
    case_id: str,
    file_type: str,
    file_name: str,
    file_path: str,
    mime_type: str = "",
    size_bytes: int = 0,
    checksum: str = "",
) -> Dict[str, Any]:
    """Register a file attached to a case."""
    file_id = new_id()
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO case_files (id, case_id, file_type, file_name, file_path, mime_type, size_bytes, checksum)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (file_id, case_id, file_type, file_name, file_path, mime_type, size_bytes, checksum),
        )
    return fetch_one("SELECT * FROM case_files WHERE id = ?", (file_id,))  # type: ignore


def list_case_files(case_id: str, file_type: Optional[str] = None) -> List[Dict[str, Any]]:
    """List files for a case."""
    if file_type:
        return fetch_all(
            "SELECT * FROM case_files WHERE case_id = ? AND file_type = ? ORDER BY created_at",
            (case_id, file_type),
        )
    return fetch_all(
        "SELECT * FROM case_files WHERE case_id = ? ORDER BY created_at",
        (case_id,),
    )
