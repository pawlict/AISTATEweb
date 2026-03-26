"""Tests for SQLite database module: schema, projects, cases, migration."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path):
    """Each test gets its own database."""
    from backend.db import engine
    db_path = tmp_path / "test.db"
    engine.set_db_path(db_path)
    engine.init_db(db_path)
    yield
    engine._initialized = False
    engine._db_path = None


class TestEngine:
    def test_init_creates_tables(self, tmp_path):
        from backend.db.engine import fetch_all
        tables = fetch_all(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        names = {t["name"] for t in tables}
        assert "users" in names
        assert "projects" in names
        assert "cases" in names
        assert "transactions" in names
        assert "counterparties" in names
        assert "audit_log" in names
        assert "graph_nodes" in names
        assert "graph_edges" in names

    def test_first_run_detection(self):
        from backend.db.engine import is_first_run, create_default_admin
        assert is_first_run() is True
        create_default_admin()
        assert is_first_run() is False

    def test_default_admin(self):
        from backend.db.engine import create_default_admin, fetch_one
        uid = create_default_admin()
        user = fetch_one("SELECT * FROM users WHERE id = ?", (uid,))
        assert user is not None
        assert user["username"] == "admin"
        assert user["role"] == "admin"

    def test_system_config(self):
        from backend.db.engine import get_system_config, set_system_config
        set_system_config("test_key", "test_value")
        assert get_system_config("test_key") == "test_value"
        assert get_system_config("nonexistent", "default") == "default"


class TestProjects:
    def test_create_and_get_project(self):
        from backend.db.engine import create_default_admin
        from backend.db.projects import create_project, get_project

        uid = create_default_admin()
        proj = create_project(uid, "Test Project", "Description")

        assert proj is not None
        assert proj["name"] == "Test Project"
        assert proj["status"] == "active"

        fetched = get_project(proj["id"])
        assert fetched["name"] == "Test Project"

    def test_list_projects(self):
        from backend.db.engine import create_default_admin
        from backend.db.projects import create_project, list_projects

        uid = create_default_admin()
        create_project(uid, "Project A")
        create_project(uid, "Project B")

        projects = list_projects(owner_id=uid)
        assert len(projects) == 2

    def test_delete_project(self):
        from backend.db.engine import create_default_admin
        from backend.db.projects import create_project, delete_project, get_project

        uid = create_default_admin()
        proj = create_project(uid, "To Delete")
        assert delete_project(proj["id"]) is True
        assert get_project(proj["id"]) is None  # soft-deleted


class TestCases:
    def test_create_case(self):
        from backend.db.engine import create_default_admin
        from backend.db.projects import create_case, create_project, get_case

        uid = create_default_admin()
        proj = create_project(uid, "Test")
        case = create_case(proj["id"], "ING 01/2024", "aml")

        assert case is not None
        assert case["name"] == "ING 01/2024"
        assert case["case_type"] == "aml"

    def test_list_cases(self):
        from backend.db.engine import create_default_admin
        from backend.db.projects import create_case, create_project, list_cases

        uid = create_default_admin()
        proj = create_project(uid, "Test")
        create_case(proj["id"], "Case A", "aml")
        create_case(proj["id"], "Case B", "transcription")

        all_cases = list_cases(proj["id"])
        assert len(all_cases) == 2

        aml_cases = list_cases(proj["id"], case_type="aml")
        assert len(aml_cases) == 1

    def test_case_files(self):
        from backend.db.engine import create_default_admin
        from backend.db.projects import (
            add_case_file, create_case, create_project, list_case_files,
        )

        uid = create_default_admin()
        proj = create_project(uid, "Test")
        case = create_case(proj["id"], "Test Case", "aml")

        add_case_file(case["id"], "source", "statement.pdf", "/uploads/statement.pdf",
                       mime_type="application/pdf", size_bytes=1024)
        add_case_file(case["id"], "report", "report.html", "/reports/report.html",
                       mime_type="text/html", size_bytes=5000)

        all_files = list_case_files(case["id"])
        assert len(all_files) == 2

        source_files = list_case_files(case["id"], file_type="source")
        assert len(source_files) == 1
        assert source_files[0]["file_name"] == "statement.pdf"


class TestMigration:
    def test_migrate_json_projects(self, tmp_path):
        from backend.db.engine import create_default_admin
        from backend.db.migrate import migrate_json_projects
        from backend.db.projects import list_cases, list_projects

        uid = create_default_admin()

        # Create fake legacy project structure
        projects_dir = tmp_path / "projects"
        proj1 = projects_dir / "abc123"
        proj1.mkdir(parents=True)
        (proj1 / "project.json").write_text(json.dumps({
            "project_id": "abc123",
            "name": "Test Transkrypcja",
            "has_transcript": True,
        }), encoding="utf-8")

        # Create audio file
        audio_dir = proj1 / "audio"
        audio_dir.mkdir()
        (audio_dir / "test.mp3").write_text("fake audio", encoding="utf-8")

        result = migrate_json_projects(data_dir=tmp_path)
        assert result["status"] == "ok"
        assert result["migrated"] == 1

        # Verify
        projects = list_projects(owner_id=uid)
        assert len(projects) == 1
        assert projects[0]["name"] == "Zmigrowane projekty"

        cases = list_cases(projects[0]["id"])
        assert len(cases) == 1
        assert cases[0]["name"] == "Test Transkrypcja"
        assert cases[0]["case_type"] == "transcription"

    def test_migrate_idempotent(self, tmp_path):
        from backend.db.engine import create_default_admin
        from backend.db.migrate import migrate_json_projects

        create_default_admin()
        projects_dir = tmp_path / "projects"
        proj1 = projects_dir / "xyz"
        proj1.mkdir(parents=True)
        (proj1 / "project.json").write_text('{"name":"X"}', encoding="utf-8")

        r1 = migrate_json_projects(data_dir=tmp_path)
        assert r1["status"] == "ok"

        r2 = migrate_json_projects(data_dir=tmp_path)
        assert r2["status"] == "skip"
        assert r2["reason"] == "already migrated"
