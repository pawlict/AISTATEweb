"""Tests for the multi-user authentication and authorization system.

All auth stores now use SQLite (backend/db/engine.py) instead of JSON files.
Tests use a temporary database per test via the ``tmp_path`` fixture.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Helpers: set up an isolated SQLite DB for each test
# ---------------------------------------------------------------------------

def _init_test_db(tmp_path: Path) -> Path:
    """Create a fresh SQLite database in tmp_path and configure the engine."""
    from backend.db.engine import set_db_path, init_db
    db_path = tmp_path / "test_aistate.db"
    set_db_path(db_path)
    init_db(db_path)
    return db_path


# ---------------------------------------------------------------------------
# Password utilities (unchanged — no DB dependency)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# DeploymentStore (SQLite)
# ---------------------------------------------------------------------------

class TestDeploymentStore:
    def test_not_configured(self, tmp_path):
        _init_test_db(tmp_path)
        from webapp.auth.deployment_store import DeploymentStore
        ds = DeploymentStore(tmp_path)
        assert ds.get_mode() is None
        assert not ds.is_configured()
        assert not ds.is_multiuser()

    def test_set_single(self, tmp_path):
        _init_test_db(tmp_path)
        from webapp.auth.deployment_store import DeploymentStore
        ds = DeploymentStore(tmp_path)
        ds.set_mode("single")
        assert ds.get_mode() == "single"
        assert ds.is_configured()
        assert not ds.is_multiuser()

    def test_set_multi(self, tmp_path):
        _init_test_db(tmp_path)
        from webapp.auth.deployment_store import DeploymentStore
        ds = DeploymentStore(tmp_path)
        ds.set_mode("multi")
        assert ds.get_mode() == "multi"
        assert ds.is_multiuser()

    def test_migrate_from_json(self, tmp_path):
        _init_test_db(tmp_path)
        # Write legacy JSON
        legacy = tmp_path / "deployment.json"
        legacy.write_text(json.dumps({"mode": "multi", "version": 1}), encoding="utf-8")

        from webapp.auth.deployment_store import DeploymentStore
        ds = DeploymentStore(tmp_path)
        result = ds.migrate_from_json()
        assert result is True
        assert ds.get_mode() == "multi"
        # Old file renamed
        assert not legacy.exists()
        assert (tmp_path / "deployment.json.bak").exists()

    def test_migrate_no_overwrite(self, tmp_path):
        _init_test_db(tmp_path)
        from webapp.auth.deployment_store import DeploymentStore
        ds = DeploymentStore(tmp_path)
        ds.set_mode("single")

        # Write legacy JSON with different mode
        legacy = tmp_path / "deployment.json"
        legacy.write_text(json.dumps({"mode": "multi"}), encoding="utf-8")

        result = ds.migrate_from_json()
        assert result is False
        # DB keeps original value
        assert ds.get_mode() == "single"


# ---------------------------------------------------------------------------
# UserStore (SQLite)
# ---------------------------------------------------------------------------

class TestUserStore:
    def test_create_and_get(self, tmp_path):
        _init_test_db(tmp_path)
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
        _init_test_db(tmp_path)
        from webapp.auth.user_store import UserStore, UserRecord
        store = UserStore(tmp_path)
        store.create_user(UserRecord(username="alice", display_name="Alice", password_hash="x", role="Analityk"))
        assert store.get_by_username("alice") is not None
        assert store.get_by_username("ALICE") is not None  # case-insensitive
        assert store.get_by_username("bob") is None

    def test_duplicate_username(self, tmp_path):
        _init_test_db(tmp_path)
        from webapp.auth.user_store import UserStore, UserRecord
        store = UserStore(tmp_path)
        store.create_user(UserRecord(username="dup", password_hash="x", role="Analityk"))
        with pytest.raises(ValueError, match="already exists"):
            store.create_user(UserRecord(username="dup", password_hash="y", role="Lingwista"))

    def test_update_user(self, tmp_path):
        _init_test_db(tmp_path)
        from webapp.auth.user_store import UserStore, UserRecord
        store = UserStore(tmp_path)
        rec = store.create_user(UserRecord(username="upd", password_hash="x", role="Analityk"))
        updated = store.update_user(rec.user_id, {"display_name": "Updated"})
        assert updated.display_name == "Updated"

    def test_delete_user(self, tmp_path):
        _init_test_db(tmp_path)
        from webapp.auth.user_store import UserStore, UserRecord
        store = UserStore(tmp_path)
        rec = store.create_user(UserRecord(username="del", password_hash="x", role="Analityk"))
        assert store.delete_user(rec.user_id)
        assert store.get_user(rec.user_id) is None

    def test_list_users(self, tmp_path):
        _init_test_db(tmp_path)
        from webapp.auth.user_store import UserStore, UserRecord
        store = UserStore(tmp_path)
        store.create_user(UserRecord(username="a", password_hash="x", role="Analityk"))
        store.create_user(UserRecord(username="b", password_hash="y", role="Lingwista"))
        assert len(store.list_users()) == 2

    def test_ban_fields(self, tmp_path):
        _init_test_db(tmp_path)
        from webapp.auth.user_store import UserStore, UserRecord
        store = UserStore(tmp_path)
        rec = store.create_user(UserRecord(username="ban_me", password_hash="x", role="Analityk"))
        store.update_user(rec.user_id, {"banned": True, "ban_reason": "test"})
        fetched = store.get_user(rec.user_id)
        assert fetched.banned is True
        assert fetched.ban_reason == "test"

    def test_user_count(self, tmp_path):
        _init_test_db(tmp_path)
        from webapp.auth.user_store import UserStore, UserRecord
        store = UserStore(tmp_path)
        assert store.user_count() == 0
        assert not store.has_users()
        store.create_user(UserRecord(username="one", password_hash="x", role="Analityk"))
        assert store.user_count() == 1
        assert store.has_users()

    def test_has_approved_users(self, tmp_path):
        _init_test_db(tmp_path)
        from webapp.auth.user_store import UserStore, UserRecord
        store = UserStore(tmp_path)
        # Create pending user
        store.create_user(UserRecord(username="pending", password_hash="x", role="Analityk", pending=True))
        assert not store.has_approved_users()
        # Approve them
        users = store.list_users()
        store.update_user(users[0].user_id, {"pending": False})
        assert store.has_approved_users()

    def test_admin_roles_json(self, tmp_path):
        _init_test_db(tmp_path)
        from webapp.auth.user_store import UserStore, UserRecord
        store = UserStore(tmp_path)
        rec = store.create_user(UserRecord(
            username="admin1",
            password_hash="x",
            is_admin=True,
            admin_roles=["Architekt Funkcji", "Strażnik Dostępu"],
            is_superadmin=True,
        ))
        fetched = store.get_user(rec.user_id)
        assert fetched.is_admin is True
        assert fetched.is_superadmin is True
        assert "Architekt Funkcji" in fetched.admin_roles
        assert "Strażnik Dostępu" in fetched.admin_roles

    def test_lockout_fields(self, tmp_path):
        _init_test_db(tmp_path)
        from webapp.auth.user_store import UserStore, UserRecord
        store = UserStore(tmp_path)
        rec = store.create_user(UserRecord(username="lock", password_hash="x", role="Analityk"))
        store.update_user(rec.user_id, {"failed_login_count": 5, "locked_until": "2099-01-01T00:00:00"})
        fetched = store.get_user(rec.user_id)
        assert fetched.failed_login_count == 5
        assert fetched.locked_until == "2099-01-01T00:00:00"

    def test_update_username_uniqueness(self, tmp_path):
        _init_test_db(tmp_path)
        from webapp.auth.user_store import UserStore, UserRecord
        store = UserStore(tmp_path)
        store.create_user(UserRecord(username="user1", password_hash="x", role="Analityk"))
        rec2 = store.create_user(UserRecord(username="user2", password_hash="x", role="Analityk"))
        with pytest.raises(ValueError, match="already exists"):
            store.update_user(rec2.user_id, {"username": "user1"})

    def test_migrate_from_json(self, tmp_path):
        _init_test_db(tmp_path)
        from webapp.auth.user_store import UserStore, UserRecord

        # Write legacy JSON users
        legacy = tmp_path / "users.json"
        users_data = {
            "uid-001": {
                "username": "migrated_user",
                "display_name": "Migrated",
                "password_hash": "pbkdf2:260000:aabb:ccdd",
                "role": "Transkryptor",
                "is_admin": False,
                "admin_roles": [],
                "is_superadmin": False,
                "banned": False,
                "pending": False,
                "created_at": "2025-01-01T00:00:00",
                "created_by": "system",
            }
        }
        legacy.write_text(json.dumps(users_data), encoding="utf-8")

        store = UserStore(tmp_path)
        count = store.migrate_from_json()
        assert count == 1
        # Old file renamed
        assert not legacy.exists()
        assert (tmp_path / "users.json.bak").exists()
        # User in DB
        user = store.get_user("uid-001")
        assert user is not None
        assert user.username == "migrated_user"
        assert user.role == "Transkryptor"


# ---------------------------------------------------------------------------
# SessionStore (SQLite)
# ---------------------------------------------------------------------------

class TestSessionStore:
    def test_create_and_get(self, tmp_path):
        _init_test_db(tmp_path)
        from webapp.auth.session_store import SessionStore
        ss = SessionStore(tmp_path)
        token = ss.create_session("user1", timeout_hours=1)
        assert len(token) > 20
        session = ss.get_session(token)
        assert session is not None
        assert session["user_id"] == "user1"

    def test_expired_session(self, tmp_path):
        _init_test_db(tmp_path)
        from webapp.auth.session_store import SessionStore
        ss = SessionStore(tmp_path)
        token = ss.create_session("user1", timeout_hours=0)
        # Session with 0-hour timeout expires immediately
        session = ss.get_session(token)
        assert session is None

    def test_delete_session(self, tmp_path):
        _init_test_db(tmp_path)
        from webapp.auth.session_store import SessionStore
        ss = SessionStore(tmp_path)
        token = ss.create_session("user1")
        assert ss.delete_session(token)
        assert ss.get_session(token) is None

    def test_delete_user_sessions(self, tmp_path):
        _init_test_db(tmp_path)
        from webapp.auth.session_store import SessionStore
        ss = SessionStore(tmp_path)
        ss.create_session("user1")
        ss.create_session("user1")
        ss.create_session("user2")
        assert ss.delete_user_sessions("user1") == 2
        assert ss.count_user_sessions("user1") == 0
        assert ss.count_user_sessions("user2") == 1

    def test_cleanup_expired(self, tmp_path):
        _init_test_db(tmp_path)
        from webapp.auth.session_store import SessionStore
        ss = SessionStore(tmp_path)
        ss.create_session("user1", timeout_hours=0)
        ss.create_session("user1", timeout_hours=0)
        ss.create_session("user2", timeout_hours=24)
        removed = ss.cleanup_expired()
        assert removed == 2
        assert ss.count_user_sessions("user2") == 1

    def test_migrate_from_json(self, tmp_path):
        _init_test_db(tmp_path)
        from webapp.auth.session_store import SessionStore
        from datetime import datetime, timedelta

        # Write legacy JSON
        legacy = tmp_path / "sessions.json"
        future = (datetime.now() + timedelta(hours=8)).isoformat()
        past = (datetime.now() - timedelta(hours=1)).isoformat()
        sessions_data = {
            "valid-token-123": {
                "user_id": "uid-001",
                "created_at": datetime.now().isoformat(),
                "expires_at": future,
                "ip": "127.0.0.1",
            },
            "expired-token-456": {
                "user_id": "uid-002",
                "created_at": datetime.now().isoformat(),
                "expires_at": past,
                "ip": "127.0.0.1",
            },
        }
        legacy.write_text(json.dumps(sessions_data), encoding="utf-8")

        ss = SessionStore(tmp_path)
        count = ss.migrate_from_json()
        assert count == 1  # Only valid session migrated
        assert ss.get_session("valid-token-123") is not None
        assert ss.get_session("expired-token-456") is None
        assert not legacy.exists()


# ---------------------------------------------------------------------------
# AuditStore (SQLite)
# ---------------------------------------------------------------------------

class TestAuditStore:
    def test_log_and_get(self, tmp_path):
        _init_test_db(tmp_path)
        from webapp.auth.audit_store import AuditStore
        audit = AuditStore(tmp_path)
        audit.log_event("login", user_id="u1", username="alice", ip="127.0.0.1")
        audit.log_event("login_failed", user_id="u2", username="bob", ip="10.0.0.1")

        events = audit.get_events()
        assert len(events) == 2
        # Newest first
        assert events[0]["event"] == "login_failed"
        assert events[1]["event"] == "login"

    def test_filter_by_user(self, tmp_path):
        _init_test_db(tmp_path)
        from webapp.auth.audit_store import AuditStore
        audit = AuditStore(tmp_path)
        audit.log_event("login", user_id="u1", username="alice")
        audit.log_event("login", user_id="u2", username="bob")
        audit.log_event("logout", user_id="u1", username="alice")

        events = audit.get_events(user_id="u1")
        assert len(events) == 2
        assert all(e["user_id"] == "u1" for e in events)

    def test_filter_by_event_type(self, tmp_path):
        _init_test_db(tmp_path)
        from webapp.auth.audit_store import AuditStore
        audit = AuditStore(tmp_path)
        audit.log_event("login", user_id="u1", username="alice")
        audit.log_event("logout", user_id="u1", username="alice")
        audit.log_event("login_failed", user_id="u2", username="bob")

        events = audit.get_events(event_type="login")
        assert len(events) == 1
        assert events[0]["event"] == "login"

    def test_count_events(self, tmp_path):
        _init_test_db(tmp_path)
        from webapp.auth.audit_store import AuditStore
        audit = AuditStore(tmp_path)
        audit.log_event("login", user_id="u1", username="alice")
        audit.log_event("login", user_id="u1", username="alice")
        audit.log_event("logout", user_id="u1", username="alice")

        assert audit.count_events() == 3
        assert audit.count_events(event_type="login") == 2
        assert audit.count_events(user_id="u1") == 3

    def test_fingerprint_roundtrip(self, tmp_path):
        _init_test_db(tmp_path)
        from webapp.auth.audit_store import AuditStore
        audit = AuditStore(tmp_path)
        fp = {"browser": "Chrome", "os": "Linux", "screen": "1920x1080"}
        audit.log_event("login", user_id="u1", username="alice", fingerprint=fp)

        events = audit.get_events()
        assert len(events) == 1
        assert events[0]["fingerprint"]["browser"] == "Chrome"

    def test_actor_fields(self, tmp_path):
        _init_test_db(tmp_path)
        from webapp.auth.audit_store import AuditStore
        audit = AuditStore(tmp_path)
        audit.log_event("user_banned", user_id="u1", username="alice",
                        actor_id="admin1", actor_name="Admin")

        events = audit.get_events()
        assert events[0]["actor_id"] == "admin1"
        assert events[0]["actor_name"] == "Admin"

    def test_get_user_events(self, tmp_path):
        _init_test_db(tmp_path)
        from webapp.auth.audit_store import AuditStore
        audit = AuditStore(tmp_path)
        audit.log_event("login", user_id="u1", username="alice")
        audit.log_event("login", user_id="u2", username="bob")

        events = audit.get_user_events("u1")
        assert len(events) == 1
        assert events[0]["username"] == "alice"

    def test_pagination(self, tmp_path):
        _init_test_db(tmp_path)
        from webapp.auth.audit_store import AuditStore
        audit = AuditStore(tmp_path)
        for i in range(10):
            audit.log_event("login", user_id=f"u{i}", username=f"user{i}")

        page1 = audit.get_events(limit=3, offset=0)
        page2 = audit.get_events(limit=3, offset=3)
        assert len(page1) == 3
        assert len(page2) == 3
        # No overlap
        ids1 = {e["id"] for e in page1}
        ids2 = {e["id"] for e in page2}
        assert not ids1 & ids2

    def test_migrate_from_json(self, tmp_path):
        _init_test_db(tmp_path)
        from webapp.auth.audit_store import AuditStore

        # Write legacy JSON
        legacy = tmp_path / "audit_log.json"
        events = [
            {"id": "ev-1", "timestamp": "2025-01-01T00:00:00", "event": "login",
             "user_id": "u1", "username": "alice", "ip": "127.0.0.1", "detail": ""},
            {"id": "ev-2", "timestamp": "2025-01-01T00:01:00", "event": "logout",
             "user_id": "u1", "username": "alice", "ip": "127.0.0.1", "detail": ""},
        ]
        legacy.write_text(json.dumps(events), encoding="utf-8")

        audit = AuditStore(tmp_path)
        count = audit.migrate_from_json()
        assert count == 2
        assert not legacy.exists()

        fetched = audit.get_events()
        assert len(fetched) == 2


# ---------------------------------------------------------------------------
# MessageStore (SQLite)
# ---------------------------------------------------------------------------

class TestMessageStore:
    def test_create_and_list(self, tmp_path):
        _init_test_db(tmp_path)
        from webapp.auth.message_store import MessageStore, Message
        ms = MessageStore(tmp_path)

        msg = Message(
            author_id="admin1",
            author_name="Admin",
            subject="Test",
            content="<p>Hello</p>",
            target_groups=["all"],
        )
        created = ms.create_message(msg)
        assert created.message_id

        msgs = ms.list_messages()
        assert len(msgs) == 1
        assert msgs[0].subject == "Test"

    def test_get_message(self, tmp_path):
        _init_test_db(tmp_path)
        from webapp.auth.message_store import MessageStore, Message
        ms = MessageStore(tmp_path)
        msg = ms.create_message(Message(subject="Get Test", content="x", target_groups=["all"]))
        fetched = ms.get_message(msg.message_id)
        assert fetched is not None
        assert fetched.subject == "Get Test"

    def test_delete_message(self, tmp_path):
        _init_test_db(tmp_path)
        from webapp.auth.message_store import MessageStore, Message
        ms = MessageStore(tmp_path)
        msg = ms.create_message(Message(subject="Del", content="x", target_groups=["all"]))
        assert ms.delete_message(msg.message_id)
        assert ms.get_message(msg.message_id) is None

    def test_mark_read(self, tmp_path):
        _init_test_db(tmp_path)
        from webapp.auth.message_store import MessageStore, Message
        ms = MessageStore(tmp_path)
        msg = ms.create_message(Message(subject="Read", content="x", target_groups=["all"]))

        assert ms.mark_read(msg.message_id, "user1")
        fetched = ms.get_message(msg.message_id)
        assert "user1" in fetched.read_by

        # Mark read again (idempotent)
        assert ms.mark_read(msg.message_id, "user1")

    def test_mark_read_nonexistent(self, tmp_path):
        _init_test_db(tmp_path)
        from webapp.auth.message_store import MessageStore
        ms = MessageStore(tmp_path)
        assert not ms.mark_read("nonexistent", "user1")

    def test_get_unread_for_user(self, tmp_path):
        _init_test_db(tmp_path)
        from webapp.auth.message_store import MessageStore, Message
        ms = MessageStore(tmp_path)

        # Message for admins only
        ms.create_message(Message(subject="Admin Only", content="x", target_groups=["Strażnik Dostępu"]))
        # Message for all
        msg_all = ms.create_message(Message(subject="For All", content="y", target_groups=["all"]))

        # Regular user sees only "all" message
        unread = ms.get_unread_for_user("user1", user_role="Transkryptor", is_admin=False,
                                         admin_roles=None, is_superadmin=False)
        assert len(unread) == 1
        assert unread[0].subject == "For All"

        # Admin user sees both
        unread_admin = ms.get_unread_for_user("admin1", user_role=None, is_admin=True,
                                               admin_roles=["Strażnik Dostępu"], is_superadmin=False)
        assert len(unread_admin) == 2

        # Mark one as read
        ms.mark_read(msg_all.message_id, "user1")
        unread_after = ms.get_unread_for_user("user1", user_role="Transkryptor", is_admin=False,
                                               admin_roles=None, is_superadmin=False)
        assert len(unread_after) == 0

    def test_migrate_from_json(self, tmp_path):
        _init_test_db(tmp_path)
        from webapp.auth.message_store import MessageStore

        legacy = tmp_path / "messages.json"
        messages_data = {
            "msg-001": {
                "author_id": "admin1",
                "author_name": "Admin",
                "subject": "Legacy",
                "content": "<p>Old message</p>",
                "target_groups": ["all"],
                "created_at": "2025-01-01T00:00:00",
                "read_by": ["user1", "user2"],
            }
        }
        legacy.write_text(json.dumps(messages_data), encoding="utf-8")

        ms = MessageStore(tmp_path)
        count = ms.migrate_from_json()
        assert count == 1
        assert not legacy.exists()

        msgs = ms.list_messages()
        assert len(msgs) == 1
        assert msgs[0].subject == "Legacy"
        assert "user1" in msgs[0].read_by
        assert "user2" in msgs[0].read_by


# ---------------------------------------------------------------------------
# Permissions (unchanged — no DB dependency)
# ---------------------------------------------------------------------------

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
        # Główny Opiekun via is_superadmin flag (real setup flow)
        modules = get_user_modules(None, True, ["Architekt Funkcji", "Strażnik Dostępu"], is_superadmin=True)
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


# ---------------------------------------------------------------------------
# Cross-store integration: user + session + audit in single transaction
# ---------------------------------------------------------------------------

class TestCrossStoreIntegration:
    def test_full_login_flow(self, tmp_path):
        """Simulate: create user → login (session + audit) → logout."""
        _init_test_db(tmp_path)
        from webapp.auth.user_store import UserStore, UserRecord
        from webapp.auth.session_store import SessionStore
        from webapp.auth.audit_store import AuditStore
        from webapp.auth.passwords import hash_password, verify_password

        us = UserStore(tmp_path)
        ss = SessionStore(tmp_path)
        audit = AuditStore(tmp_path)

        # Create user
        rec = us.create_user(UserRecord(
            username="testlogin",
            password_hash=hash_password("mypass"),
            role="Analityk",
        ))

        # Simulate login
        user = us.get_by_username("testlogin")
        assert user is not None
        assert verify_password("mypass", user.password_hash)

        token = ss.create_session(user.user_id, timeout_hours=8, ip="127.0.0.1")
        audit.log_event("login", user_id=user.user_id, username=user.username, ip="127.0.0.1")
        us.update_user(user.user_id, {"last_login": "2025-06-01T12:00:00", "failed_login_count": 0})

        # Verify session
        session = ss.get_session(token)
        assert session is not None
        assert session["user_id"] == user.user_id

        # Simulate logout
        ss.delete_session(token)
        audit.log_event("logout", user_id=user.user_id, username=user.username)

        assert ss.get_session(token) is None
        events = audit.get_events(user_id=user.user_id)
        assert len(events) == 2

    def test_ban_invalidates_sessions(self, tmp_path):
        """Ban user → all their sessions deleted."""
        _init_test_db(tmp_path)
        from webapp.auth.user_store import UserStore, UserRecord
        from webapp.auth.session_store import SessionStore

        us = UserStore(tmp_path)
        ss = SessionStore(tmp_path)

        rec = us.create_user(UserRecord(username="banned", password_hash="x", role="Analityk"))
        ss.create_session(rec.user_id)
        ss.create_session(rec.user_id)
        assert ss.count_user_sessions(rec.user_id) == 2

        # Ban the user
        us.update_user(rec.user_id, {"banned": True, "ban_reason": "violation"})
        removed = ss.delete_user_sessions(rec.user_id)
        assert removed == 2
        assert ss.count_user_sessions(rec.user_id) == 0

    def test_delete_user_cleanup(self, tmp_path):
        """Delete user → sessions cleaned up."""
        _init_test_db(tmp_path)
        from webapp.auth.user_store import UserStore, UserRecord
        from webapp.auth.session_store import SessionStore

        us = UserStore(tmp_path)
        ss = SessionStore(tmp_path)

        rec = us.create_user(UserRecord(username="deleteme", password_hash="x", role="Analityk"))
        ss.create_session(rec.user_id)

        ss.delete_user_sessions(rec.user_id)
        us.delete_user(rec.user_id)

        assert us.get_user(rec.user_id) is None
        assert ss.count_user_sessions(rec.user_id) == 0
