"""Tests for the multi-user authentication and authorization system."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

# --- Unit tests for auth modules ---


class TestPasswords:
    def test_hash_and_verify(self):
        from webapp.auth.passwords import hash_password, verify_password
        h = hash_password("secret123")
        assert h.startswith("pbkdf2:")
        assert verify_password("secret123", h)
        assert not verify_password("wrong", h)

    def test_different_hashes(self):
        from webapp.auth.passwords import hash_password
        h1 = hash_password("same")
        h2 = hash_password("same")
        # Different salts produce different hashes
        assert h1 != h2

    def test_generate_token(self):
        from webapp.auth.passwords import generate_token
        t1 = generate_token()
        t2 = generate_token()
        assert len(t1) > 20
        assert t1 != t2


class TestDeploymentStore:
    def test_not_configured(self, tmp_path):
        from webapp.auth.deployment_store import DeploymentStore
        ds = DeploymentStore(tmp_path)
        assert ds.get_mode() is None
        assert not ds.is_configured()
        assert not ds.is_multiuser()

    def test_set_single(self, tmp_path):
        from webapp.auth.deployment_store import DeploymentStore
        ds = DeploymentStore(tmp_path)
        ds.set_mode("single")
        assert ds.get_mode() == "single"
        assert ds.is_configured()
        assert not ds.is_multiuser()

    def test_set_multi(self, tmp_path):
        from webapp.auth.deployment_store import DeploymentStore
        ds = DeploymentStore(tmp_path)
        ds.set_mode("multi")
        assert ds.get_mode() == "multi"
        assert ds.is_multiuser()


class TestUserStore:
    def test_create_and_get(self, tmp_path):
        from webapp.auth.user_store import UserStore, UserRecord
        from webapp.auth.passwords import hash_password
        store = UserStore(tmp_path)
        rec = UserRecord(
            username="test_user",
            display_name="Test",
            password_hash=hash_password("pass123"),
            role="Transkryptor",
        )
        created = store.create_user(rec)
        assert created.user_id
        assert created.username == "test_user"

        fetched = store.get_user(created.user_id)
        assert fetched is not None
        assert fetched.username == "test_user"
        assert fetched.role == "Transkryptor"

    def test_get_by_username(self, tmp_path):
        from webapp.auth.user_store import UserStore, UserRecord
        store = UserStore(tmp_path)
        store.create_user(UserRecord(username="alice", display_name="Alice", password_hash="x", role="Analityk"))
        assert store.get_by_username("alice") is not None
        assert store.get_by_username("ALICE") is not None  # case-insensitive
        assert store.get_by_username("bob") is None

    def test_duplicate_username(self, tmp_path):
        from webapp.auth.user_store import UserStore, UserRecord
        store = UserStore(tmp_path)
        store.create_user(UserRecord(username="dup", password_hash="x", role="Analityk"))
        with pytest.raises(ValueError, match="already exists"):
            store.create_user(UserRecord(username="dup", password_hash="y", role="Lingwista"))

    def test_update_user(self, tmp_path):
        from webapp.auth.user_store import UserStore, UserRecord
        store = UserStore(tmp_path)
        rec = store.create_user(UserRecord(username="upd", password_hash="x", role="Analityk"))
        updated = store.update_user(rec.user_id, {"display_name": "Updated"})
        assert updated.display_name == "Updated"

    def test_delete_user(self, tmp_path):
        from webapp.auth.user_store import UserStore, UserRecord
        store = UserStore(tmp_path)
        rec = store.create_user(UserRecord(username="del", password_hash="x", role="Analityk"))
        assert store.delete_user(rec.user_id)
        assert store.get_user(rec.user_id) is None

    def test_list_users(self, tmp_path):
        from webapp.auth.user_store import UserStore, UserRecord
        store = UserStore(tmp_path)
        store.create_user(UserRecord(username="a", password_hash="x", role="Analityk"))
        store.create_user(UserRecord(username="b", password_hash="y", role="Lingwista"))
        assert len(store.list_users()) == 2

    def test_ban_fields(self, tmp_path):
        from webapp.auth.user_store import UserStore, UserRecord
        store = UserStore(tmp_path)
        rec = store.create_user(UserRecord(username="ban_me", password_hash="x", role="Analityk"))
        store.update_user(rec.user_id, {"banned": True, "ban_reason": "test"})
        fetched = store.get_user(rec.user_id)
        assert fetched.banned is True
        assert fetched.ban_reason == "test"


class TestSessionStore:
    def test_create_and_get(self, tmp_path):
        from webapp.auth.session_store import SessionStore
        ss = SessionStore(tmp_path)
        token = ss.create_session("user1", timeout_hours=1)
        assert len(token) > 20
        session = ss.get_session(token)
        assert session is not None
        assert session["user_id"] == "user1"

    def test_expired_session(self, tmp_path):
        from webapp.auth.session_store import SessionStore
        ss = SessionStore(tmp_path)
        token = ss.create_session("user1", timeout_hours=0)
        # Session with 0-hour timeout expires immediately
        session = ss.get_session(token)
        assert session is None

    def test_delete_session(self, tmp_path):
        from webapp.auth.session_store import SessionStore
        ss = SessionStore(tmp_path)
        token = ss.create_session("user1")
        assert ss.delete_session(token)
        assert ss.get_session(token) is None

    def test_delete_user_sessions(self, tmp_path):
        from webapp.auth.session_store import SessionStore
        ss = SessionStore(tmp_path)
        ss.create_session("user1")
        ss.create_session("user1")
        ss.create_session("user2")
        assert ss.delete_user_sessions("user1") == 2
        assert ss.count_user_sessions("user1") == 0
        assert ss.count_user_sessions("user2") == 1


class TestPermissions:
    def test_user_modules(self):
        from webapp.auth.permissions import get_user_modules
        modules = get_user_modules("Transkryptor", False, [])
        assert "transcription" in modules
        assert "diarization" in modules
        assert "translation" not in modules

    def test_strateg_modules(self):
        from webapp.auth.permissions import get_user_modules
        modules = get_user_modules("Strateg", False, [])
        assert "translation" in modules
        assert "analysis" in modules
        assert "chat" in modules
        assert "transcription" not in modules

    def test_mistrz_sesji_modules(self):
        from webapp.auth.permissions import get_user_modules
        modules = get_user_modules("Mistrz Sesji", False, [])
        assert "transcription" in modules
        assert "diarization" in modules
        assert "translation" in modules
        assert "analysis" in modules
        assert "chat" in modules

    def test_superadmin_all_modules(self):
        from webapp.auth.permissions import get_user_modules, SUPER_ADMIN_MODULES
        modules = get_user_modules(None, True, ["Super Admin"])
        assert modules == SUPER_ADMIN_MODULES

    def test_admin_architekt(self):
        from webapp.auth.permissions import get_user_modules
        modules = get_user_modules(None, True, ["Architekt Funkcji"])
        assert "admin_settings" in modules
        assert "user_mgmt" not in modules

    def test_admin_straznik(self):
        from webapp.auth.permissions import get_user_modules
        modules = get_user_modules(None, True, ["Strażnik Dostępu"])
        assert "user_mgmt" in modules
        assert "admin_settings" not in modules

    def test_route_allowed(self):
        from webapp.auth.permissions import is_route_allowed
        modules = ["projects", "transcription"]
        assert is_route_allowed("/transcription", modules)
        assert is_route_allowed("/new-project", modules)
        assert not is_route_allowed("/chat", modules)
        assert not is_route_allowed("/translation", modules)
        assert is_route_allowed("/login", modules)  # public
        assert is_route_allowed("/info", modules)    # common
