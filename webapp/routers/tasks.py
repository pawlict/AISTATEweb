"""Tasks / Logs router."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api/tasks", tags=["tasks"])

# Injected at mount time
_tasks_manager = None  # type: Any


def init(tasks_manager: Any) -> None:
    global _tasks_manager
    _tasks_manager = tasks_manager


@router.get("")
def api_tasks() -> Any:
    tasks = _tasks_manager.list_tasks()
    return {
        "tasks": [
            {
                "task_id": t.task_id,
                "kind": t.kind,
                "status": t.status,
                "progress": t.progress,
                "project_id": t.project_id,
                "started_at": t.started_at,
                "finished_at": t.finished_at,
            }
            for t in tasks
        ]
    }


@router.post("/clear")
def api_tasks_clear() -> Any:
    _tasks_manager.clear()
    return {"ok": True}


@router.get("/{task_id}")
def api_task(task_id: str) -> Any:
    try:
        t = _tasks_manager.get(task_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Task not found.")
    data = asdict(t)
    if len(data.get("logs") or []) > 400:
        data["logs"] = data["logs"][-400:]
    return data
