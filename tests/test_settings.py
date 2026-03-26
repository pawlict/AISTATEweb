"""Tests for backend.settings and backend.settings_store."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest


def test_settings_dataclass_defaults():
    """Settings dataclass should have sensible defaults."""
    from backend.settings import Settings

    s = Settings()
    assert s.hf_token == ""
    assert s.default_language == "auto"
    assert s.whisper_model == "base"
    assert s.ui_language == "pl"


def test_settings_dataclass_custom_values():
    """Settings should accept custom values."""
    from backend.settings import Settings

    s = Settings(hf_token="tok123", whisper_model="large-v3", ui_language="en")
    assert s.hf_token == "tok123"
    assert s.whisper_model == "large-v3"
    assert s.ui_language == "en"


def test_app_metadata():
    """App metadata should be defined."""
    from backend.settings import APP_NAME, APP_VERSION, AUTHOR_EMAIL

    assert APP_NAME == "AISTATEweb"
    assert "beta" in APP_VERSION or APP_VERSION
    assert "@" in AUTHOR_EMAIL


def test_save_and_load_settings(tmp_path: Path):
    """Settings should roundtrip through save/load."""
    from backend.settings import Settings

    cfg_dir = tmp_path / "cfg"
    cfg_dir.mkdir()
    os.environ["AISTATE_CONFIG_DIR"] = str(cfg_dir)

    try:
        from backend.settings_store import save_settings, load_settings

        original = Settings(hf_token="test_token", whisper_model="medium", ui_language="en")
        save_settings(original)

        loaded = load_settings()
        assert loaded.hf_token == "test_token"
        assert loaded.whisper_model == "medium"
        assert loaded.ui_language == "en"
    finally:
        # Restore env
        os.environ["AISTATE_CONFIG_DIR"] = os.environ.get("AISTATE_CONFIG_DIR", "")


def test_load_settings_missing_file(tmp_path: Path):
    """load_settings should return defaults when no config file exists."""
    cfg_dir = tmp_path / "empty_cfg"
    cfg_dir.mkdir()
    os.environ["AISTATE_CONFIG_DIR"] = str(cfg_dir)

    try:
        from backend.settings_store import load_settings

        s = load_settings()
        assert s.hf_token == ""
        assert s.whisper_model == "base"
    finally:
        os.environ["AISTATE_CONFIG_DIR"] = os.environ.get("AISTATE_CONFIG_DIR", "")


def test_load_settings_corrupt_file(tmp_path: Path):
    """load_settings should handle corrupt JSON gracefully."""
    cfg_dir = tmp_path / "bad_cfg"
    cfg_dir.mkdir()
    (cfg_dir / "settings.json").write_text("{corrupt json!", encoding="utf-8")
    os.environ["AISTATE_CONFIG_DIR"] = str(cfg_dir)

    try:
        from backend.settings_store import load_settings

        s = load_settings()
        # Should fall back to defaults, not crash
        assert s.whisper_model == "base"
    finally:
        os.environ["AISTATE_CONFIG_DIR"] = os.environ.get("AISTATE_CONFIG_DIR", "")
