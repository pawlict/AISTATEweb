"""Migration tool: JSON flat files → SQLite.

Reads existing project.json files from data_www/projects/ and imports
them into the new SQL database as cases within a default project.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from .engine import ensure_initialized, get_conn, get_default_user_id, new_id
from .projects import add_case_file, create_case, create_project

log = logging.getLogger("aistate.db.migrate")


def _detect_case_type(meta: Dict[str, Any], project_dir: Path) -> str:
    """Detect the case type from legacy project metadata and directory contents."""
    # Check for finance data
    finance_dir = project_dir / "finance"
    if finance_dir.exists() and any(finance_dir.iterdir()):
        return "finance"

    # Check metadata flags
    if meta.get("has_diarized"):
        return "diarization"
    if meta.get("has_transcript"):
        return "transcription"
    if meta.get("has_translation"):
        return "translation"

    # Check for analysis output
    analysis_dir = project_dir / "analysis"
    if analysis_dir.exists() and any(analysis_dir.iterdir()):
        return "analysis"

    return "analysis"  # default fallback


def _compute_file_hash(path: Path) -> str:
    """Compute SHA-256 of a file (first 10MB for large files)."""
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


def _register_files(case_id: str, project_dir: Path, data_root: Path) -> int:
    """Register existing files in the project directory."""
    count = 0
    file_type_map = {
        "audio": "audio",
        "transcript": "transcript",
        "diarized": "transcript",
        "translation": "result",
        "analysis": "result",
        "reports": "report",
        "finance": "result",
    }

    for subdir_name, file_type in file_type_map.items():
        subdir = project_dir / subdir_name
        if not subdir.exists():
            continue
        for fp in subdir.rglob("*"):
            if fp.is_file():
                rel_path = str(fp.relative_to(data_root))
                mime = ""
                if fp.suffix == ".json":
                    mime = "application/json"
                elif fp.suffix == ".txt":
                    mime = "text/plain"
                elif fp.suffix == ".html":
                    mime = "text/html"
                elif fp.suffix in (".mp3", ".wav", ".ogg", ".m4a"):
                    mime = f"audio/{fp.suffix[1:]}"
                elif fp.suffix == ".pdf":
                    mime = "application/pdf"

                add_case_file(
                    case_id=case_id,
                    file_type=file_type,
                    file_name=fp.name,
                    file_path=rel_path,
                    mime_type=mime,
                    size_bytes=fp.stat().st_size,
                )
                count += 1
    return count


def migrate_json_projects(data_dir: Optional[Path] = None) -> Dict[str, Any]:
    """Migrate all existing JSON-based projects to SQLite.

    Creates a default project "Zmigrowane projekty" and imports each
    old project as a case within it.

    Returns:
        Dict with migration stats.
    """
    ensure_initialized()

    if data_dir is None:
        env_dir = os.environ.get("AISTATEWEB_DATA_DIR", "")
        if env_dir:
            data_dir = Path(env_dir)
        else:
            data_dir = Path(__file__).resolve().parents[2] / "data_www"

    projects_dir = data_dir / "projects"
    if not projects_dir.exists():
        return {"status": "skip", "reason": "no projects directory", "migrated": 0}

    # Find all project dirs (exclude _global)
    project_dirs: List[Path] = []
    for d in sorted(projects_dir.iterdir()):
        if d.is_dir() and d.name != "_global" and (d / "project.json").exists():
            project_dirs.append(d)

    if not project_dirs:
        return {"status": "skip", "reason": "no projects found", "migrated": 0}

    # Check if already migrated
    with get_conn() as conn:
        row = conn.execute(
            "SELECT value FROM system_config WHERE key = 'json_migration_done'"
        ).fetchone()
        if row and row["value"] == "true":
            return {"status": "skip", "reason": "already migrated", "migrated": 0}

    owner_id = get_default_user_id()

    # Create the migration target project
    migration_project = create_project(
        owner_id=owner_id,
        name="Zmigrowane projekty",
        description="Projekty zaimportowane z poprzedniej wersji (flat JSON)",
    )
    project_id = migration_project["id"]

    migrated = 0
    errors: List[str] = []

    for pdir in project_dirs:
        try:
            meta_path = pdir / "project.json"
            meta = json.loads(meta_path.read_text(encoding="utf-8"))

            case_type = _detect_case_type(meta, pdir)
            case_name = meta.get("name", "") or meta.get("project_name", "") or pdir.name

            # Use the original project_id as data_dir reference
            rel_data_dir = str(pdir.relative_to(data_dir))

            case = create_case(
                project_id=project_id,
                name=case_name,
                case_type=case_type,
                data_dir=rel_data_dir,
                metadata=meta,
            )

            # Register files
            file_count = _register_files(case["id"], pdir, data_dir)

            log.info(
                "Migrated project %s → case %s (%s, %d files)",
                pdir.name, case["id"], case_type, file_count,
            )
            migrated += 1

        except Exception as e:
            err = f"Error migrating {pdir.name}: {e}"
            log.error(err)
            errors.append(err)

    # Mark migration as done
    with get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO system_config (key, value) VALUES (?, ?)",
            ("json_migration_done", "true"),
        )

    result = {
        "status": "ok",
        "migrated": migrated,
        "errors": errors,
        "migration_project_id": project_id,
    }
    log.info("Migration complete: %d projects migrated, %d errors", migrated, len(errors))
    return result
