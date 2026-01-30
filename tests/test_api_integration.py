"""Integration tests for AISTATEweb API endpoints using FastAPI TestClient.

These tests exercise the real server application but mock external
dependencies (Ollama, GPU, ML models).
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure environment is set up before importing server
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

_tmp = tempfile.mkdtemp(prefix="aistate_integ_")
os.environ.setdefault("AISTATEWEB_DATA_DIR", _tmp)
os.environ.setdefault("AISTATE_CONFIG_DIR", tempfile.mkdtemp(prefix="aistate_integ_cfg_"))
os.environ.setdefault("AISTATEWEB_ADMIN_LOG_DIR", tempfile.mkdtemp(prefix="aistate_integ_logs_"))


@pytest.fixture(scope="module")
def client():
    """Create a TestClient for the FastAPI app (once per module)."""
    from fastapi.testclient import TestClient
    from webapp.server import app

    with TestClient(app) as c:
        yield c


# ---------- Page routes ----------

class TestPageRoutes:
    def test_home_redirects(self, client):
        """Home page should return 200 or redirect."""
        r = client.get("/", follow_redirects=True)
        assert r.status_code == 200

    def test_transcription_page(self, client):
        """Transcription page should render."""
        r = client.get("/transcription")
        assert r.status_code == 200
        assert "transcription" in r.text.lower() or "transkrypcja" in r.text.lower() or "html" in r.text.lower()

    def test_new_project_page(self, client):
        """New project page should render."""
        r = client.get("/new-project")
        assert r.status_code == 200

    def test_diarization_page(self, client):
        """Diarization page should render."""
        r = client.get("/diarization")
        assert r.status_code == 200

    def test_analysis_page(self, client):
        """Analysis page should render."""
        r = client.get("/analysis")
        assert r.status_code == 200

    def test_chat_page(self, client):
        """Chat page should render."""
        r = client.get("/chat")
        assert r.status_code == 200
        assert "chat" in r.text.lower()

    def test_translation_page(self, client):
        """Translation page should render."""
        r = client.get("/translation")
        assert r.status_code == 200

    def test_settings_page(self, client):
        """Settings page should render."""
        r = client.get("/settings")
        assert r.status_code == 200

    def test_logs_page(self, client):
        """Logs page should render."""
        r = client.get("/logs")
        assert r.status_code == 200

    def test_info_page(self, client):
        """Info page should render."""
        r = client.get("/info")
        assert r.status_code == 200

    def test_legacy_polish_routes(self, client):
        """Legacy Polish routes should redirect to English equivalents."""
        r = client.get("/transkrypcja", follow_redirects=False)
        assert r.status_code in (301, 302, 307, 308)

        r = client.get("/nowy-projekt", follow_redirects=False)
        assert r.status_code in (301, 302, 307, 308)


# ---------- Settings API ----------

class TestSettingsAPI:
    def test_get_settings(self, client):
        """GET /api/settings should return settings."""
        r = client.get("/api/settings")
        assert r.status_code == 200
        data = r.json()
        assert "whisper_model" in data or "settings" in data or isinstance(data, dict)

    def test_save_settings(self, client):
        """POST /api/settings should accept settings update."""
        r = client.post("/api/settings", json={"whisper_model": "small"})
        assert r.status_code == 200


# ---------- Projects API ----------

class TestProjectsAPI:
    def test_list_projects(self, client):
        """GET /api/projects should return project list."""
        r = client.get("/api/projects")
        assert r.status_code == 200
        data = r.json()
        assert "projects" in data

    def test_create_project(self, client):
        """POST /api/projects/create should create a new project."""
        r = client.post("/api/projects/create", data={"name": "Test Project"})
        assert r.status_code == 200
        data = r.json()
        assert "project_id" in data

    def test_get_project_meta(self, client):
        """Created project metadata should be retrievable."""
        # Create first
        r = client.post("/api/projects/create", data={"name": "Meta Test"})
        pid = r.json()["project_id"]

        r = client.get(f"/api/projects/{pid}/meta")
        assert r.status_code == 200
        meta = r.json()
        assert meta.get("project_id") == pid


# ---------- Tasks API (router) ----------

class TestTasksAPI:
    def test_list_tasks(self, client):
        """GET /api/tasks should return task list."""
        r = client.get("/api/tasks")
        assert r.status_code == 200
        data = r.json()
        assert "tasks" in data
        assert isinstance(data["tasks"], list)

    def test_get_system_task(self, client):
        """System task should always exist."""
        r = client.get("/api/tasks/system")
        assert r.status_code == 200
        data = r.json()
        assert data["task_id"] == "system"
        assert data["kind"] == "system"

    def test_get_nonexistent_task(self, client):
        """Non-existent task should return 404."""
        r = client.get("/api/tasks/nonexistent_id_12345")
        assert r.status_code == 404

    def test_clear_tasks(self, client):
        """POST /api/tasks/clear should reset tasks."""
        r = client.post("/api/tasks/clear")
        assert r.status_code == 200
        data = r.json()
        assert data.get("ok") is True


# ---------- Admin API (router) ----------

class TestAdminAPI:
    def test_gpu_status(self, client):
        """GET /api/admin/gpu/status should return GPU info."""
        r = client.get("/api/admin/gpu/status")
        assert r.status_code == 200
        data = r.json()
        assert "cuda_available" in data
        assert "config" in data

    def test_gpu_jobs(self, client):
        """GET /api/admin/gpu/jobs should return job list."""
        r = client.get("/api/admin/gpu/jobs")
        assert r.status_code == 200
        data = r.json()
        assert "jobs" in data

    def test_gpu_priorities_get(self, client):
        """GET /api/admin/gpu/priorities should return priorities."""
        r = client.get("/api/admin/gpu/priorities")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"

    def test_gpu_config_update(self, client):
        """POST /api/admin/gpu/config should accept valid config."""
        r = client.post("/api/admin/gpu/config", json={
            "gpu_mem_fraction": 0.8,
            "gpu_slots_per_gpu": 2,
            "cpu_slots": 2,
        })
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        assert data["config"]["gpu_mem_fraction"] == 0.8

    def test_gpu_cancel_missing_id(self, client):
        """Cancel with empty task_id should return 400."""
        r = client.post("/api/admin/gpu/cancel", json={"task_id": ""})
        assert r.status_code == 400


# ---------- Chat API (router) ----------

class TestChatAPI:
    def test_chat_models(self, client):
        """GET /api/chat/models should return a response."""
        r = client.get("/api/chat/models")
        assert r.status_code == 200
        data = r.json()
        assert "status" in data
        assert "models" in data

    def test_chat_complete_no_model(self, client):
        """POST /api/chat/complete without model should return 400."""
        r = client.post("/api/chat/complete", json={
            "model": "",
            "messages": [{"role": "user", "content": "Hi"}],
        })
        assert r.status_code == 400

    def test_chat_complete_no_messages(self, client):
        """POST /api/chat/complete with no messages should return 400."""
        r = client.post("/api/chat/complete", json={
            "model": "test-model",
            "messages": [],
        })
        assert r.status_code == 400

    def test_chat_stream_no_model(self, client):
        """GET /api/chat/stream without model should return 400."""
        r = client.get("/api/chat/stream?model=&messages=[]")
        assert r.status_code == 400

    def test_chat_stream_invalid_json(self, client):
        """GET /api/chat/stream with invalid JSON should return 400."""
        r = client.get("/api/chat/stream?model=test&messages=not-json")
        assert r.status_code == 400


# ---------- Models info ----------

class TestModelsAPI:
    def test_models_list(self, client):
        """GET /api/models/list should return model catalog."""
        r = client.get("/api/models/list")
        assert r.status_code == 200

    def test_custom_models_list(self, client):
        """GET /api/models/custom should return custom models."""
        r = client.get("/api/models/custom")
        assert r.status_code == 200
