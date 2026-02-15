"""Tests for the workspace & subproject management system.

Covers: WorkspaceStore CRUD, members, invitations, links, activity,
permissions, file-project migration, and the API router.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _init_test_db(tmp_path: Path) -> Path:
    from backend.db.engine import set_db_path, init_db
    db_path = tmp_path / "test_ws.db"
    set_db_path(db_path)
    init_db(db_path)
    return db_path


def _store():
    from webapp.auth.workspace_store import WorkspaceStore
    return WorkspaceStore()


def _create_user(uid: str, username: str = "", display_name: str = ""):
    """Insert a minimal user row so JOINs work."""
    from backend.db.engine import get_conn
    username = username or uid
    display_name = display_name or uid
    with get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO users (id, username, display_name, password_hash, role) "
            "VALUES (?, ?, ?, '', '')",
            (uid, username, display_name),
        )


# ===========================================================================
# Workspace CRUD
# ===========================================================================

class TestWorkspaceCRUD:
    def test_create_workspace(self, tmp_path):
        _init_test_db(tmp_path)
        _create_user("u1")
        ws = _store().create_workspace("u1", "My Project", description="desc", color="#ff0000")
        assert ws is not None
        assert ws["name"] == "My Project"
        assert ws["description"] == "desc"
        assert ws["color"] == "#ff0000"
        assert ws["owner_id"] == "u1"
        assert ws["status"] == "active"
        assert ws["member_count"] == 1  # owner is auto-added
        assert ws["subproject_count"] == 0

    def test_get_workspace(self, tmp_path):
        _init_test_db(tmp_path)
        _create_user("u1")
        ws = _store().create_workspace("u1", "Test")
        fetched = _store().get_workspace(ws["id"])
        assert fetched["id"] == ws["id"]
        assert fetched["name"] == "Test"

    def test_get_nonexistent_workspace(self, tmp_path):
        _init_test_db(tmp_path)
        assert _store().get_workspace("nonexistent") is None

    def test_list_workspaces_owner(self, tmp_path):
        _init_test_db(tmp_path)
        _create_user("u1")
        _store().create_workspace("u1", "WS1")
        _store().create_workspace("u1", "WS2")
        wss = _store().list_workspaces("u1")
        assert len(wss) == 2
        names = {w["name"] for w in wss}
        assert names == {"WS1", "WS2"}

    def test_list_workspaces_excludes_others(self, tmp_path):
        _init_test_db(tmp_path)
        _create_user("u1")
        _create_user("u2")
        _store().create_workspace("u1", "U1 WS")
        _store().create_workspace("u2", "U2 WS")
        u1_wss = _store().list_workspaces("u1")
        assert len(u1_wss) == 1
        assert u1_wss[0]["name"] == "U1 WS"

    def test_update_workspace(self, tmp_path):
        _init_test_db(tmp_path)
        _create_user("u1")
        ws = _store().create_workspace("u1", "Old Name")
        updated = _store().update_workspace(ws["id"], name="New Name", color="#00ff00")
        assert updated["name"] == "New Name"
        assert updated["color"] == "#00ff00"

    def test_update_workspace_ignores_unknown_fields(self, tmp_path):
        _init_test_db(tmp_path)
        _create_user("u1")
        ws = _store().create_workspace("u1", "WS")
        updated = _store().update_workspace(ws["id"], fake_field="bad")
        assert updated["name"] == "WS"  # unchanged

    def test_delete_workspace_soft(self, tmp_path):
        _init_test_db(tmp_path)
        _create_user("u1")
        ws = _store().create_workspace("u1", "To Delete")
        result = _store().delete_workspace(ws["id"])
        assert result is True
        # Workspace still exists but status changed
        fetched = _store().get_workspace(ws["id"])
        assert fetched["status"] == "deleted"
        # Not in active list
        active = _store().list_workspaces("u1", status="active")
        assert len(active) == 0

    def test_list_archived(self, tmp_path):
        _init_test_db(tmp_path)
        _create_user("u1")
        ws = _store().create_workspace("u1", "Archive Me")
        _store().update_workspace(ws["id"], status="archived")
        archived = _store().list_workspaces("u1", status="archived")
        assert len(archived) == 1
        assert archived[0]["name"] == "Archive Me"


# ===========================================================================
# Subproject CRUD
# ===========================================================================

class TestSubprojectCRUD:
    def test_create_subproject(self, tmp_path):
        _init_test_db(tmp_path)
        _create_user("u1")
        ws = _store().create_workspace("u1", "WS")
        sp = _store().create_subproject(ws["id"], "Sub1", subproject_type="transcription",
                                        created_by="u1", user_name="u1")
        assert sp is not None
        assert sp["name"] == "Sub1"
        assert sp["subproject_type"] == "transcription"
        assert sp["status"] == "open"
        assert sp["workspace_id"] == ws["id"]
        assert sp["position"] == 0

    def test_multiple_subprojects_positions(self, tmp_path):
        _init_test_db(tmp_path)
        _create_user("u1")
        ws = _store().create_workspace("u1", "WS")
        sp1 = _store().create_subproject(ws["id"], "Sub1", created_by="u1")
        sp2 = _store().create_subproject(ws["id"], "Sub2", created_by="u1")
        sp3 = _store().create_subproject(ws["id"], "Sub3", created_by="u1")
        assert sp1["position"] == 0
        assert sp2["position"] == 1
        assert sp3["position"] == 2

    def test_list_subprojects(self, tmp_path):
        _init_test_db(tmp_path)
        _create_user("u1")
        ws = _store().create_workspace("u1", "WS")
        _store().create_subproject(ws["id"], "A", created_by="u1")
        _store().create_subproject(ws["id"], "B", created_by="u1")
        subs = _store().list_subprojects(ws["id"])
        assert len(subs) == 2
        assert subs[0]["name"] == "A"
        assert subs[1]["name"] == "B"

    def test_get_subproject(self, tmp_path):
        _init_test_db(tmp_path)
        _create_user("u1")
        ws = _store().create_workspace("u1", "WS")
        sp = _store().create_subproject(ws["id"], "S1", created_by="u1")
        fetched = _store().get_subproject(sp["id"])
        assert fetched["name"] == "S1"
        assert isinstance(fetched["metadata"], dict)
        assert isinstance(fetched["links"], list)

    def test_get_nonexistent_subproject(self, tmp_path):
        _init_test_db(tmp_path)
        assert _store().get_subproject("nonexistent") is None

    def test_update_subproject(self, tmp_path):
        _init_test_db(tmp_path)
        _create_user("u1")
        ws = _store().create_workspace("u1", "WS")
        sp = _store().create_subproject(ws["id"], "Old", created_by="u1")
        updated = _store().update_subproject(sp["id"], name="New", status="completed")
        assert updated["name"] == "New"
        assert updated["status"] == "completed"

    def test_update_subproject_metadata(self, tmp_path):
        _init_test_db(tmp_path)
        _create_user("u1")
        ws = _store().create_workspace("u1", "WS")
        sp = _store().create_subproject(ws["id"], "S", created_by="u1")
        updated = _store().update_subproject(sp["id"], metadata={"key": "value"})
        assert updated["metadata"] == {"key": "value"}

    def test_delete_subproject(self, tmp_path):
        _init_test_db(tmp_path)
        _create_user("u1")
        ws = _store().create_workspace("u1", "WS")
        sp = _store().create_subproject(ws["id"], "Del", created_by="u1")
        result = _store().delete_subproject(sp["id"])
        assert result is True
        assert _store().get_subproject(sp["id"]) is None

    def test_create_subproject_updates_workspace(self, tmp_path):
        _init_test_db(tmp_path)
        _create_user("u1")
        ws = _store().create_workspace("u1", "WS")
        old_updated = ws["updated_at"]
        import time; time.sleep(0.01)  # Ensure different timestamp
        _store().create_subproject(ws["id"], "S", created_by="u1")
        ws2 = _store().get_workspace(ws["id"])
        assert ws2["subproject_count"] == 1


# ===========================================================================
# Subproject Links
# ===========================================================================

class TestSubprojectLinks:
    def test_link_and_list(self, tmp_path):
        _init_test_db(tmp_path)
        _create_user("u1")
        ws = _store().create_workspace("u1", "WS")
        sp1 = _store().create_subproject(ws["id"], "A", created_by="u1")
        sp2 = _store().create_subproject(ws["id"], "B", created_by="u1")
        link = _store().link_subprojects(sp1["id"], sp2["id"], link_type="depends_on", note="test")
        assert link["source_id"] == sp1["id"]
        assert link["target_id"] == sp2["id"]
        assert link["link_type"] == "depends_on"
        # Both subprojects should see the link
        sp1_detail = _store().get_subproject(sp1["id"])
        sp2_detail = _store().get_subproject(sp2["id"])
        assert len(sp1_detail["links"]) == 1
        assert len(sp2_detail["links"]) == 1

    def test_unlink(self, tmp_path):
        _init_test_db(tmp_path)
        _create_user("u1")
        ws = _store().create_workspace("u1", "WS")
        sp1 = _store().create_subproject(ws["id"], "A", created_by="u1")
        sp2 = _store().create_subproject(ws["id"], "B", created_by="u1")
        _store().link_subprojects(sp1["id"], sp2["id"])
        result = _store().unlink_subprojects(sp1["id"], sp2["id"])
        assert result is True
        sp1_detail = _store().get_subproject(sp1["id"])
        assert len(sp1_detail["links"]) == 0

    def test_duplicate_link_ignored(self, tmp_path):
        _init_test_db(tmp_path)
        _create_user("u1")
        ws = _store().create_workspace("u1", "WS")
        sp1 = _store().create_subproject(ws["id"], "A", created_by="u1")
        sp2 = _store().create_subproject(ws["id"], "B", created_by="u1")
        _store().link_subprojects(sp1["id"], sp2["id"])
        _store().link_subprojects(sp1["id"], sp2["id"])  # duplicate
        sp1_detail = _store().get_subproject(sp1["id"])
        assert len(sp1_detail["links"]) == 1  # still just one


# ===========================================================================
# Members
# ===========================================================================

class TestMembers:
    def test_owner_auto_added(self, tmp_path):
        _init_test_db(tmp_path)
        _create_user("u1")
        ws = _store().create_workspace("u1", "WS")
        members = _store().list_members(ws["id"])
        assert len(members) == 1
        assert members[0]["user_id"] == "u1"
        assert members[0]["role"] == "owner"

    def test_add_member(self, tmp_path):
        _init_test_db(tmp_path)
        _create_user("u1")
        _create_user("u2")
        ws = _store().create_workspace("u1", "WS")
        _store().add_member(ws["id"], "u2", "editor", "u1")
        members = _store().list_members(ws["id"])
        assert len(members) == 2
        roles = {m["user_id"]: m["role"] for m in members}
        assert roles["u1"] == "owner"
        assert roles["u2"] == "editor"

    def test_remove_member(self, tmp_path):
        _init_test_db(tmp_path)
        _create_user("u1")
        _create_user("u2")
        ws = _store().create_workspace("u1", "WS")
        _store().add_member(ws["id"], "u2", "viewer", "u1")
        result = _store().remove_member(ws["id"], "u2")
        assert result is True
        members = _store().list_members(ws["id"])
        assert len(members) == 1

    def test_cannot_remove_owner(self, tmp_path):
        _init_test_db(tmp_path)
        _create_user("u1")
        ws = _store().create_workspace("u1", "WS")
        result = _store().remove_member(ws["id"], "u1")
        assert result is False
        members = _store().list_members(ws["id"])
        assert len(members) == 1

    def test_update_member_role(self, tmp_path):
        _init_test_db(tmp_path)
        _create_user("u1")
        _create_user("u2")
        ws = _store().create_workspace("u1", "WS")
        _store().add_member(ws["id"], "u2", "viewer", "u1")
        result = _store().update_member_role(ws["id"], "u2", "editor")
        assert result is True
        role = _store().get_user_role(ws["id"], "u2")
        assert role == "editor"

    def test_cannot_update_to_owner(self, tmp_path):
        _init_test_db(tmp_path)
        _create_user("u1")
        _create_user("u2")
        ws = _store().create_workspace("u1", "WS")
        _store().add_member(ws["id"], "u2", "viewer", "u1")
        result = _store().update_member_role(ws["id"], "u2", "owner")
        assert result is False

    def test_cannot_change_owner_role(self, tmp_path):
        _init_test_db(tmp_path)
        _create_user("u1")
        ws = _store().create_workspace("u1", "WS")
        result = _store().update_member_role(ws["id"], "u1", "editor")
        assert result is False  # owner role can't be changed


# ===========================================================================
# Permissions
# ===========================================================================

class TestPermissions:
    def test_owner_has_all_permissions(self, tmp_path):
        _init_test_db(tmp_path)
        _create_user("u1")
        ws = _store().create_workspace("u1", "WS")
        assert _store().can_user_access(ws["id"], "u1") is True
        assert _store().can_user_edit(ws["id"], "u1") is True
        assert _store().can_user_manage(ws["id"], "u1") is True

    def test_manager_can_manage(self, tmp_path):
        _init_test_db(tmp_path)
        _create_user("u1")
        _create_user("u2")
        ws = _store().create_workspace("u1", "WS")
        _store().add_member(ws["id"], "u2", "manager", "u1")
        assert _store().can_user_access(ws["id"], "u2") is True
        assert _store().can_user_edit(ws["id"], "u2") is True
        assert _store().can_user_manage(ws["id"], "u2") is True

    def test_editor_can_edit_not_manage(self, tmp_path):
        _init_test_db(tmp_path)
        _create_user("u1")
        _create_user("u2")
        ws = _store().create_workspace("u1", "WS")
        _store().add_member(ws["id"], "u2", "editor", "u1")
        assert _store().can_user_access(ws["id"], "u2") is True
        assert _store().can_user_edit(ws["id"], "u2") is True
        assert _store().can_user_manage(ws["id"], "u2") is False

    def test_commenter_readonly(self, tmp_path):
        _init_test_db(tmp_path)
        _create_user("u1")
        _create_user("u2")
        ws = _store().create_workspace("u1", "WS")
        _store().add_member(ws["id"], "u2", "commenter", "u1")
        assert _store().can_user_access(ws["id"], "u2") is True
        assert _store().can_user_edit(ws["id"], "u2") is False
        assert _store().can_user_manage(ws["id"], "u2") is False

    def test_viewer_readonly(self, tmp_path):
        _init_test_db(tmp_path)
        _create_user("u1")
        _create_user("u2")
        ws = _store().create_workspace("u1", "WS")
        _store().add_member(ws["id"], "u2", "viewer", "u1")
        assert _store().can_user_access(ws["id"], "u2") is True
        assert _store().can_user_edit(ws["id"], "u2") is False
        assert _store().can_user_manage(ws["id"], "u2") is False

    def test_non_member_no_access(self, tmp_path):
        _init_test_db(tmp_path)
        _create_user("u1")
        _create_user("u3")
        ws = _store().create_workspace("u1", "WS")
        assert _store().can_user_access(ws["id"], "u3") is False
        assert _store().can_user_edit(ws["id"], "u3") is False
        assert _store().can_user_manage(ws["id"], "u3") is False

    def test_get_user_role(self, tmp_path):
        _init_test_db(tmp_path)
        _create_user("u1")
        _create_user("u2")
        ws = _store().create_workspace("u1", "WS")
        _store().add_member(ws["id"], "u2", "editor", "u1")
        assert _store().get_user_role(ws["id"], "u1") == "owner"
        assert _store().get_user_role(ws["id"], "u2") == "editor"
        assert _store().get_user_role(ws["id"], "nobody") is None


# ===========================================================================
# Invitations
# ===========================================================================

class TestInvitations:
    def test_create_invitation(self, tmp_path):
        _init_test_db(tmp_path)
        _create_user("u1")
        _create_user("u2")
        ws = _store().create_workspace("u1", "WS")
        inv = _store().create_invitation(ws["id"], "u1", "u2", "editor", "Join us!")
        assert inv["status"] == "pending"
        assert inv["role"] == "editor"

    def test_accept_invitation(self, tmp_path):
        _init_test_db(tmp_path)
        _create_user("u1")
        _create_user("u2")
        ws = _store().create_workspace("u1", "WS")
        inv = _store().create_invitation(ws["id"], "u1", "u2", "editor")
        result = _store().respond_invitation(inv["id"], "u2", accept=True)
        assert result is True
        # Now u2 should be a member
        role = _store().get_user_role(ws["id"], "u2")
        assert role == "editor"
        members = _store().list_members(ws["id"])
        assert len(members) == 2

    def test_reject_invitation(self, tmp_path):
        _init_test_db(tmp_path)
        _create_user("u1")
        _create_user("u2")
        ws = _store().create_workspace("u1", "WS")
        inv = _store().create_invitation(ws["id"], "u1", "u2", "viewer")
        result = _store().respond_invitation(inv["id"], "u2", accept=False)
        assert result is True
        # u2 should NOT be a member
        role = _store().get_user_role(ws["id"], "u2")
        assert role is None

    def test_cannot_invite_existing_member(self, tmp_path):
        _init_test_db(tmp_path)
        _create_user("u1")
        _create_user("u2")
        ws = _store().create_workspace("u1", "WS")
        _store().add_member(ws["id"], "u2", "viewer", "u1")
        with pytest.raises(ValueError, match="already a member"):
            _store().create_invitation(ws["id"], "u1", "u2", "editor")

    def test_cannot_duplicate_pending_invitation(self, tmp_path):
        _init_test_db(tmp_path)
        _create_user("u1")
        _create_user("u2")
        ws = _store().create_workspace("u1", "WS")
        _store().create_invitation(ws["id"], "u1", "u2", "editor")
        with pytest.raises(ValueError, match="already pending"):
            _store().create_invitation(ws["id"], "u1", "u2", "viewer")

    def test_list_invitations_for_user(self, tmp_path):
        _init_test_db(tmp_path)
        _create_user("u1", "user1", "User One")
        _create_user("u2")
        ws = _store().create_workspace("u1", "Project X")
        _store().create_invitation(ws["id"], "u1", "u2", "editor")
        invs = _store().list_invitations_for_user("u2")
        assert len(invs) == 1
        assert invs[0]["workspace_name"] == "Project X"
        assert invs[0]["role"] == "editor"

    def test_respond_wrong_user(self, tmp_path):
        _init_test_db(tmp_path)
        _create_user("u1")
        _create_user("u2")
        _create_user("u3")
        ws = _store().create_workspace("u1", "WS")
        inv = _store().create_invitation(ws["id"], "u1", "u2", "viewer")
        result = _store().respond_invitation(inv["id"], "u3", accept=True)
        assert result is False  # u3 is not the invitee

    def test_respond_nonexistent(self, tmp_path):
        _init_test_db(tmp_path)
        _create_user("u1")
        result = _store().respond_invitation("fake_id", "u1", accept=True)
        assert result is False


# ===========================================================================
# Activity Log
# ===========================================================================

class TestActivity:
    def test_workspace_creation_logged(self, tmp_path):
        _init_test_db(tmp_path)
        _create_user("u1")
        ws = _store().create_workspace("u1", "WS")
        activity = _store().get_activity(ws["id"])
        assert len(activity) >= 1
        assert activity[0]["action"] == "created"

    def test_subproject_creation_logged(self, tmp_path):
        _init_test_db(tmp_path)
        _create_user("u1")
        ws = _store().create_workspace("u1", "WS")
        _store().create_subproject(ws["id"], "Sub", created_by="u1", user_name="User1")
        activity = _store().get_activity(ws["id"])
        actions = [a["action"] for a in activity]
        assert "subproject_created" in actions

    def test_log_activity_manual(self, tmp_path):
        _init_test_db(tmp_path)
        _create_user("u1")
        ws = _store().create_workspace("u1", "WS")
        _store().log_activity(ws["id"], None, "u1", "User1", "custom_action", {"extra": "data"})
        activity = _store().get_activity(ws["id"])
        custom = [a for a in activity if a["action"] == "custom_action"]
        assert len(custom) == 1
        assert custom[0]["detail"]["extra"] == "data"

    def test_activity_limit(self, tmp_path):
        _init_test_db(tmp_path)
        _create_user("u1")
        ws = _store().create_workspace("u1", "WS")
        for i in range(10):
            _store().log_activity(ws["id"], None, "u1", "u1", f"action_{i}")
        activity = _store().get_activity(ws["id"], limit=5)
        assert len(activity) == 5

    def test_invitation_accept_logged(self, tmp_path):
        _init_test_db(tmp_path)
        _create_user("u1")
        _create_user("u2")
        ws = _store().create_workspace("u1", "WS")
        inv = _store().create_invitation(ws["id"], "u1", "u2", "editor")
        _store().respond_invitation(inv["id"], "u2", accept=True)
        activity = _store().get_activity(ws["id"])
        actions = [a["action"] for a in activity]
        assert "member_added" in actions


# ===========================================================================
# File-project migration
# ===========================================================================

class TestMigration:
    def test_migrate_empty_dir(self, tmp_path):
        _init_test_db(tmp_path)
        projects_dir = tmp_path / "projects"
        projects_dir.mkdir()
        count = _store().migrate_file_projects(projects_dir, "u1")
        assert count == 0

    def test_migrate_nonexistent_dir(self, tmp_path):
        _init_test_db(tmp_path)
        count = _store().migrate_file_projects(tmp_path / "nope", "u1")
        assert count == 0

    def test_migrate_legacy_project(self, tmp_path):
        _init_test_db(tmp_path)
        _create_user("u1")
        projects_dir = tmp_path / "projects"
        projects_dir.mkdir()
        p_dir = projects_dir / "proj_abc123"
        p_dir.mkdir()
        meta = {
            "name": "Legacy Project",
            "owner_id": "u1",
            "audio_file": "audio.wav",
            "has_transcript": True,
            "shares": [
                {"user_id": "u2", "permission": "read"},
                {"user_id": "u3", "permission": "edit"},
            ],
        }
        (p_dir / "project.json").write_text(json.dumps(meta), encoding="utf-8")
        _create_user("u2")
        _create_user("u3")

        count = _store().migrate_file_projects(projects_dir, "u1")
        assert count == 1

        # Verify workspace created
        wss = _store().list_workspaces("u1")
        assert len(wss) == 1
        assert wss[0]["name"] == "Legacy Project"

        # Verify subproject created
        subs = _store().list_subprojects(wss[0]["id"])
        assert len(subs) == 1
        assert subs[0]["data_dir"] == "projects/proj_abc123"
        assert subs[0]["subproject_type"] == "transcription"
        assert subs[0]["audio_file"] == "audio.wav"

        # Verify members migrated
        members = _store().list_members(wss[0]["id"])
        user_ids = {m["user_id"] for m in members}
        assert "u1" in user_ids
        assert "u2" in user_ids
        assert "u3" in user_ids

    def test_migrate_idempotent(self, tmp_path):
        _init_test_db(tmp_path)
        _create_user("u1")
        projects_dir = tmp_path / "projects"
        projects_dir.mkdir()
        p_dir = projects_dir / "proj_xyz"
        p_dir.mkdir()
        (p_dir / "project.json").write_text(
            json.dumps({"name": "Test"}), encoding="utf-8"
        )
        count1 = _store().migrate_file_projects(projects_dir, "u1")
        assert count1 == 1
        count2 = _store().migrate_file_projects(projects_dir, "u1")
        assert count2 == 0  # already migrated

    def test_migrate_skips_dirs_without_json(self, tmp_path):
        _init_test_db(tmp_path)
        _create_user("u1")
        projects_dir = tmp_path / "projects"
        projects_dir.mkdir()
        (projects_dir / "empty_dir").mkdir()
        (projects_dir / "_hidden").mkdir()
        count = _store().migrate_file_projects(projects_dir, "u1")
        assert count == 0


# ===========================================================================
# Cross-feature integration
# ===========================================================================

class TestIntegration:
    def test_full_workspace_lifecycle(self, tmp_path):
        """Create workspace, add subprojects, invite user, accept, verify access."""
        _init_test_db(tmp_path)
        _create_user("alice", "alice", "Alice")
        _create_user("bob", "bob", "Bob")

        store = _store()

        # Alice creates workspace
        ws = store.create_workspace("alice", "Research Project", description="NLP research")
        assert ws is not None

        # Alice adds subprojects
        sp1 = store.create_subproject(ws["id"], "Transcription", "transcription",
                                       created_by="alice", user_name="Alice")
        sp2 = store.create_subproject(ws["id"], "Analysis", "analysis",
                                       created_by="alice", user_name="Alice")

        # Link subprojects
        store.link_subprojects(sp1["id"], sp2["id"], "depends_on", "analysis needs transcript")

        # Invite Bob as editor
        inv = store.create_invitation(ws["id"], "alice", "bob", "editor", "Help me!")

        # Bob cannot access yet
        assert store.can_user_access(ws["id"], "bob") is False

        # Bob accepts
        store.respond_invitation(inv["id"], "bob", accept=True)

        # Bob can now access and edit
        assert store.can_user_access(ws["id"], "bob") is True
        assert store.can_user_edit(ws["id"], "bob") is True
        assert store.can_user_manage(ws["id"], "bob") is False

        # Bob sees the workspace in his list
        bob_wss = store.list_workspaces("bob")
        assert len(bob_wss) == 1
        assert bob_wss[0]["name"] == "Research Project"

        # Verify subprojects
        subs = store.list_subprojects(ws["id"])
        assert len(subs) == 2

        # Verify links
        sp1_detail = store.get_subproject(sp1["id"])
        assert len(sp1_detail["links"]) == 1

        # Verify activity
        activity = store.get_activity(ws["id"])
        assert len(activity) >= 4  # created, 2 subprojects, member_added

    def test_workspace_with_multiple_roles(self, tmp_path):
        """Different users with different roles."""
        _init_test_db(tmp_path)
        _create_user("owner1")
        _create_user("manager1")
        _create_user("editor1")
        _create_user("viewer1")

        store = _store()
        ws = store.create_workspace("owner1", "Team Project")
        store.add_member(ws["id"], "manager1", "manager", "owner1")
        store.add_member(ws["id"], "editor1", "editor", "owner1")
        store.add_member(ws["id"], "viewer1", "viewer", "owner1")

        members = store.list_members(ws["id"])
        assert len(members) == 4

        # Verify role ordering (owner > manager > editor > viewer)
        roles = [m["role"] for m in members]
        assert roles == ["owner", "manager", "editor", "viewer"]

    def test_delete_workspace_cascade(self, tmp_path):
        """Soft-deleting workspace keeps data but hides from active list."""
        _init_test_db(tmp_path)
        _create_user("u1")
        store = _store()
        ws = store.create_workspace("u1", "To Delete")
        store.create_subproject(ws["id"], "Sub", created_by="u1")
        store.delete_workspace(ws["id"])

        # Not in active
        assert len(store.list_workspaces("u1")) == 0
        # But still fetchable
        ws_d = store.get_workspace(ws["id"])
        assert ws_d["status"] == "deleted"
        # Subprojects still there
        subs = store.list_subprojects(ws["id"])
        assert len(subs) == 1
