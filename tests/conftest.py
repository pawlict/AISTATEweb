"""Shared pytest fixtures for AISTATEweb tests."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

# Ensure the project root is importable
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Override data directory so tests don't touch production data.
_tmp_data = tempfile.mkdtemp(prefix="aistate_test_data_")
os.environ["AISTATEWEB_DATA_DIR"] = _tmp_data
os.environ["AISTATE_CONFIG_DIR"] = tempfile.mkdtemp(prefix="aistate_test_cfg_")
os.environ["AISTATEWEB_ADMIN_LOG_DIR"] = tempfile.mkdtemp(prefix="aistate_test_logs_")


@pytest.fixture
def tmp_dir(tmp_path: Path) -> Path:
    """Provide a clean temp directory for each test."""
    return tmp_path


@pytest.fixture
def sample_txt_file(tmp_path: Path) -> Path:
    """Create a simple text file for testing."""
    p = tmp_path / "sample.txt"
    p.write_text("Hello world.\nSecond line.", encoding="utf-8")
    return p


@pytest.fixture
def sample_json_file(tmp_path: Path) -> Path:
    """Create a simple JSON file for testing."""
    p = tmp_path / "sample.json"
    p.write_text(json.dumps({"key": "value", "items": [1, 2, 3]}), encoding="utf-8")
    return p


@pytest.fixture
def sample_csv_file(tmp_path: Path) -> Path:
    """Create a simple CSV file for testing."""
    p = tmp_path / "sample.csv"
    p.write_text("name,age,city\nAlice,30,Warsaw\nBob,25,Krakow\n", encoding="utf-8")
    return p


@pytest.fixture
def projects_dir(tmp_path: Path) -> Path:
    """Provide a temp projects directory."""
    d = tmp_path / "projects"
    d.mkdir()
    return d
