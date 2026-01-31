"""Admin / GPU Resource Manager router."""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api/admin", tags=["admin"])

# Injected at mount time
_gpu_rm = None  # type: Any
_get_gpu_rm_settings = None  # type: Any
_save_gpu_rm_settings = None  # type: Any
_app_log = None  # type: Any


def init(
    gpu_rm: Any,
    get_gpu_rm_settings: Any,
    save_gpu_rm_settings: Any,
    app_log_fn: Any,
) -> None:
    global _gpu_rm, _get_gpu_rm_settings, _save_gpu_rm_settings, _app_log
    _gpu_rm = gpu_rm
    _get_gpu_rm_settings = get_gpu_rm_settings
    _save_gpu_rm_settings = save_gpu_rm_settings
    _app_log = app_log_fn


@router.get("/gpu/status")
def api_admin_gpu_status() -> Dict[str, Any]:
    return _gpu_rm.status_snapshot()


@router.get("/gpu/jobs")
def api_admin_gpu_jobs() -> Dict[str, Any]:
    return _gpu_rm.jobs_snapshot()


@router.post("/gpu/config")
def api_admin_gpu_config(payload: Dict[str, Any]) -> Dict[str, Any]:
    cfg = _get_gpu_rm_settings()
    try:
        mf = float(payload.get("gpu_mem_fraction", cfg["gpu_mem_fraction"]))
        mf = max(0.3, min(0.98, mf))
        cfg["gpu_mem_fraction"] = mf
    except Exception:
        pass
    try:
        spg = int(payload.get("gpu_slots_per_gpu", cfg["gpu_slots_per_gpu"]))
        cfg["gpu_slots_per_gpu"] = max(1, min(8, spg))
    except Exception:
        pass
    try:
        cs = int(payload.get("cpu_slots", cfg["cpu_slots"]))
        cfg["cpu_slots"] = max(1, min(32, cs))
    except Exception:
        pass

    _save_gpu_rm_settings(cfg)
    _gpu_rm.apply_config(cfg)
    _app_log(f"Admin updated GPU RM config: mem_fraction={cfg['gpu_mem_fraction']}, slots_per_gpu={cfg['gpu_slots_per_gpu']}, cpu_slots={cfg['cpu_slots']}")
    return {"status": "ok", "config": cfg}


@router.get("/gpu/priorities")
def api_admin_gpu_get_priorities() -> Dict[str, Any]:
    cfg = _get_gpu_rm_settings()
    return {"status": "ok", "priorities": cfg.get("priorities") or {}}


@router.post("/gpu/priorities")
def api_admin_gpu_set_priorities(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Update admin-facing scheduling priorities."""
    cfg = _get_gpu_rm_settings()
    allow = ("transcription", "diarization", "translation", "analysis_quick", "analysis", "chat")

    # Mode 2: ordering (1..N)
    incoming_order = payload.get("order")
    if isinstance(incoming_order, list):
        order = [str(x) for x in incoming_order]
        if len(order) != len(allow) or set(order) != set(allow):
            raise HTTPException(status_code=400, detail="Invalid order")

        cur = dict(_gpu_rm.category_priorities)
        if isinstance(cfg.get("priorities"), dict):
            for k, v in (cfg.get("priorities") or {}).items():
                if k in cur:
                    try:
                        cur[k] = int(v)
                    except Exception:
                        continue

        vals = [int(cur.get(k, 100)) for k in allow]
        if len(set(vals)) != len(vals):
            vals = [300, 200, 180, 140, 120, 60]
        vals_sorted = sorted(vals, reverse=True)

        pr = {order[i]: int(vals_sorted[i]) for i in range(len(allow))}
        cfg["priorities"] = pr
        _save_gpu_rm_settings(cfg)
        _gpu_rm.apply_config(cfg)
        _app_log("Admin updated GPU RM priority order: " + " > ".join(order))
        return {"status": "ok", "priorities": pr, "config": cfg}

    # Mode 1: numeric priorities
    pr = dict(cfg.get("priorities") or {})

    incoming = payload.get("priorities") if isinstance(payload.get("priorities"), dict) else payload
    if not isinstance(incoming, dict):
        raise HTTPException(status_code=400, detail="Invalid payload")

    for k in allow:
        if k not in incoming:
            continue
        try:
            v = int(incoming.get(k))
            v = max(1, min(1000, v))
            pr[k] = v
        except Exception:
            raise HTTPException(status_code=400, detail=f"Invalid priority for {k}")

    for k in allow:
        if k not in pr:
            pr[k] = int(_get_gpu_rm_settings().get("priorities", {}).get(k, 100))

    vals = [int(pr.get(k)) for k in allow]
    if len(set(vals)) != len(vals):
        raise HTTPException(status_code=400, detail="Priorities must be unique for each area")

    cfg["priorities"] = pr
    _save_gpu_rm_settings(cfg)
    _gpu_rm.apply_config(cfg)
    _app_log("Admin updated GPU RM priorities: " + ", ".join([f"{k}={pr.get(k)}" for k in allow]))
    return {"status": "ok", "priorities": pr, "config": cfg}


@router.post("/gpu/cancel")
def api_admin_gpu_cancel(payload: Dict[str, Any]) -> Dict[str, Any]:
    task_id = str(payload.get("task_id", "")).strip()
    if not task_id:
        raise HTTPException(status_code=400, detail="task_id required")
    ok = _gpu_rm.cancel(task_id)
    return {"status": "ok", "canceled": ok}
