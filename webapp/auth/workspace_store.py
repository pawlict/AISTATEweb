"""Workspace & subproject management — SQLite-backed.

Handles: workspaces, subprojects, links, members, invitations, activity log.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger("aistate.workspaces")


def _now() -> str:
    return datetime.now().isoformat()


def _id() -> str:
    return uuid.uuid4().hex


def _conn():
    from backend.db.engine import get_conn
    return get_conn()


# =====================================================================
# WORKSPACE CRUD
# =====================================================================

class WorkspaceStore:

    # --- Workspaces ---

    def create_workspace(
        self,
        owner_id: str,
        name: str,
        description: str = "",
        color: str = "#4a6cf7",
        icon: str = "folder",
    ) -> Dict[str, Any]:
        wid = _id()
        now = _now()
        with _conn() as conn:
            conn.execute(
                """INSERT INTO project_workspaces
                   (id, owner_id, name, description, color, icon, status, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?)""",
                (wid, owner_id, name, description, color, icon, now, now),
            )
            # Owner is also a member with role 'owner'
            conn.execute(
                """INSERT INTO project_members
                   (workspace_id, user_id, role, invited_by, invited_at, accepted_at, status)
                   VALUES (?, ?, 'owner', ?, ?, ?, 'accepted')""",
                (wid, owner_id, owner_id, now, now),
            )
            self._log_activity(conn, wid, None, owner_id, "", "created", {"name": name})
        return self.get_workspace(wid)

    def get_workspace(self, workspace_id: str) -> Optional[Dict[str, Any]]:
        with _conn() as conn:
            row = conn.execute(
                "SELECT * FROM project_workspaces WHERE id = ?", (workspace_id,)
            ).fetchone()
            if row is None:
                return None
            ws = dict(row)
            ws["member_count"] = self._count_members(conn, workspace_id)
            ws["subproject_count"] = self._count_subprojects(conn, workspace_id)
            return ws

    def list_workspaces(self, user_id: str, status: str = "active") -> List[Dict[str, Any]]:
        """List workspaces the user owns or is a member of."""
        with _conn() as conn:
            rows = conn.execute(
                """SELECT DISTINCT w.* FROM project_workspaces w
                   LEFT JOIN project_members m ON m.workspace_id = w.id
                   WHERE w.status = ?
                     AND (w.owner_id = ? OR (m.user_id = ? AND m.status = 'accepted'))
                   ORDER BY w.updated_at DESC""",
                (status, user_id, user_id),
            ).fetchall()
            result = []
            for r in rows:
                ws = dict(r)
                ws["member_count"] = self._count_members(conn, ws["id"])
                ws["subproject_count"] = self._count_subprojects(conn, ws["id"])
                ws["members"] = self._get_members_brief(conn, ws["id"])
                ws["my_role"] = self._get_user_role(conn, ws["id"], user_id)
                result.append(ws)
            return result

    def update_workspace(self, workspace_id: str, **kwargs) -> Optional[Dict[str, Any]]:
        allowed = {"name", "description", "color", "icon", "status"}
        updates = {k: v for k, v in kwargs.items() if k in allowed}
        if not updates:
            return self.get_workspace(workspace_id)
        updates["updated_at"] = _now()
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [workspace_id]
        with _conn() as conn:
            conn.execute(
                f"UPDATE project_workspaces SET {set_clause} WHERE id = ?", values
            )
        return self.get_workspace(workspace_id)

    def delete_workspace(self, workspace_id: str) -> bool:
        """Soft-delete (set status='deleted')."""
        with _conn() as conn:
            cursor = conn.execute(
                "UPDATE project_workspaces SET status = 'deleted', updated_at = ? WHERE id = ?",
                (_now(), workspace_id),
            )
            return cursor.rowcount > 0

    def hard_delete_workspace(self, workspace_id: str) -> bool:
        """Permanently delete workspace, all subprojects, members, invitations, activity."""
        with _conn() as conn:
            # Subprojects are CASCADE-deleted via FK, but delete explicitly for clarity
            conn.execute("DELETE FROM subprojects WHERE workspace_id = ?", (workspace_id,))
            conn.execute("DELETE FROM project_members WHERE workspace_id = ?", (workspace_id,))
            conn.execute("DELETE FROM project_invitations WHERE workspace_id = ?", (workspace_id,))
            conn.execute("DELETE FROM project_activity WHERE workspace_id = ?", (workspace_id,))
            cursor = conn.execute("DELETE FROM project_workspaces WHERE id = ?", (workspace_id,))
            return cursor.rowcount > 0

    # --- Subprojects ---

    def create_subproject(
        self,
        workspace_id: str,
        name: str,
        subproject_type: str = "analysis",
        data_dir: str = "",
        audio_file: str = "",
        metadata: Optional[Dict] = None,
        created_by: str = "",
        user_name: str = "",
    ) -> Dict[str, Any]:
        sid = _id()
        now = _now()
        meta_json = json.dumps(metadata or {}, ensure_ascii=False)
        # Get next position
        with _conn() as conn:
            row = conn.execute(
                "SELECT COALESCE(MAX(position), -1) + 1 as pos FROM subprojects WHERE workspace_id = ?",
                (workspace_id,),
            ).fetchone()
            pos = row["pos"] if row else 0
            conn.execute(
                """INSERT INTO subprojects
                   (id, workspace_id, name, subproject_type, status, data_dir, audio_file,
                    metadata, position, created_by, created_at, updated_at)
                   VALUES (?, ?, ?, ?, 'open', ?, ?, ?, ?, ?, ?, ?)""",
                (sid, workspace_id, name, subproject_type, data_dir, audio_file,
                 meta_json, pos, created_by, now, now),
            )
            conn.execute(
                "UPDATE project_workspaces SET updated_at = ? WHERE id = ?",
                (now, workspace_id),
            )
            self._log_activity(
                conn, workspace_id, sid, created_by, user_name,
                "subproject_created", {"name": name, "type": subproject_type},
            )
        return self.get_subproject(sid)

    def get_subproject(self, subproject_id: str) -> Optional[Dict[str, Any]]:
        with _conn() as conn:
            row = conn.execute(
                "SELECT * FROM subprojects WHERE id = ?", (subproject_id,)
            ).fetchone()
            if row is None:
                return None
            sp = dict(row)
            sp["metadata"] = json.loads(sp.get("metadata") or "{}")
            sp["links"] = self._get_links(conn, subproject_id)
            return sp

    def list_subprojects(self, workspace_id: str) -> List[Dict[str, Any]]:
        with _conn() as conn:
            rows = conn.execute(
                "SELECT * FROM subprojects WHERE workspace_id = ? ORDER BY position, created_at",
                (workspace_id,),
            ).fetchall()
            result = []
            for r in rows:
                sp = dict(r)
                sp["metadata"] = json.loads(sp.get("metadata") or "{}")
                sp["links"] = self._get_links(conn, sp["id"])
                result.append(sp)
            return result

    def update_subproject(self, subproject_id: str, **kwargs) -> Optional[Dict[str, Any]]:
        allowed = {"name", "subproject_type", "status", "data_dir", "audio_file", "metadata", "position"}
        updates = {}
        for k, v in kwargs.items():
            if k not in allowed:
                continue
            if k == "metadata" and isinstance(v, dict):
                updates[k] = json.dumps(v, ensure_ascii=False)
            else:
                updates[k] = v
        if not updates:
            return self.get_subproject(subproject_id)
        updates["updated_at"] = _now()
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [subproject_id]
        with _conn() as conn:
            conn.execute(f"UPDATE subprojects SET {set_clause} WHERE id = ?", values)
            # Touch parent workspace
            row = conn.execute("SELECT workspace_id FROM subprojects WHERE id = ?", (subproject_id,)).fetchone()
            if row:
                conn.execute("UPDATE project_workspaces SET updated_at = ? WHERE id = ?", (_now(), row["workspace_id"]))
        return self.get_subproject(subproject_id)

    def delete_subproject(self, subproject_id: str) -> bool:
        with _conn() as conn:
            row = conn.execute("SELECT workspace_id FROM subprojects WHERE id = ?", (subproject_id,)).fetchone()
            if row:
                conn.execute("UPDATE project_workspaces SET updated_at = ? WHERE id = ?", (_now(), row["workspace_id"]))
            cursor = conn.execute("DELETE FROM subprojects WHERE id = ?", (subproject_id,))
            return cursor.rowcount > 0

    # --- Links ---

    def link_subprojects(
        self, source_id: str, target_id: str,
        link_type: str = "related", note: str = "",
    ) -> Dict[str, Any]:
        lid = _id()
        with _conn() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO subproject_links (id, source_id, target_id, link_type, note) VALUES (?, ?, ?, ?, ?)",
                (lid, source_id, target_id, link_type, note),
            )
        return {"id": lid, "source_id": source_id, "target_id": target_id,
                "link_type": link_type, "note": note}

    def unlink_subprojects(self, source_id: str, target_id: str) -> bool:
        with _conn() as conn:
            cursor = conn.execute(
                "DELETE FROM subproject_links WHERE source_id = ? AND target_id = ?",
                (source_id, target_id),
            )
            return cursor.rowcount > 0

    # --- Members ---

    def list_members(self, workspace_id: str) -> List[Dict[str, Any]]:
        with _conn() as conn:
            return self._get_members_full(conn, workspace_id)

    def add_member(self, workspace_id: str, user_id: str, role: str = "viewer",
                   invited_by: str = "") -> bool:
        now = _now()
        with _conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO project_members
                   (workspace_id, user_id, role, invited_by, invited_at, accepted_at, status)
                   VALUES (?, ?, ?, ?, ?, ?, 'accepted')""",
                (workspace_id, user_id, role, invited_by, now, now),
            )
        return True

    def remove_member(self, workspace_id: str, user_id: str) -> bool:
        with _conn() as conn:
            cursor = conn.execute(
                "DELETE FROM project_members WHERE workspace_id = ? AND user_id = ? AND role != 'owner'",
                (workspace_id, user_id),
            )
            return cursor.rowcount > 0

    def update_member_role(self, workspace_id: str, user_id: str, new_role: str) -> bool:
        if new_role == "owner":
            return False  # can't promote to owner this way
        with _conn() as conn:
            cursor = conn.execute(
                "UPDATE project_members SET role = ? WHERE workspace_id = ? AND user_id = ? AND role != 'owner'",
                (new_role, workspace_id, user_id),
            )
            return cursor.rowcount > 0

    def get_user_role(self, workspace_id: str, user_id: str) -> Optional[str]:
        with _conn() as conn:
            return self._get_user_role(conn, workspace_id, user_id)

    def can_user_access(self, workspace_id: str, user_id: str) -> bool:
        role = self.get_user_role(workspace_id, user_id)
        return role is not None

    def can_user_edit(self, workspace_id: str, user_id: str) -> bool:
        role = self.get_user_role(workspace_id, user_id)
        return role in ("owner", "manager", "editor")

    def can_user_manage(self, workspace_id: str, user_id: str) -> bool:
        role = self.get_user_role(workspace_id, user_id)
        return role in ("owner", "manager")

    # --- Invitations ---

    def create_invitation(
        self, workspace_id: str, inviter_id: str,
        invitee_id: str, role: str = "viewer", message: str = "",
    ) -> Dict[str, Any]:
        inv_id = _id()
        now = _now()
        with _conn() as conn:
            # Check if already a member
            existing = conn.execute(
                "SELECT 1 FROM project_members WHERE workspace_id = ? AND user_id = ?",
                (workspace_id, invitee_id),
            ).fetchone()
            if existing:
                raise ValueError("User is already a member of this workspace")
            # Check pending invitation
            pending = conn.execute(
                "SELECT 1 FROM project_invitations WHERE workspace_id = ? AND invitee_id = ? AND status = 'pending'",
                (workspace_id, invitee_id),
            ).fetchone()
            if pending:
                raise ValueError("Invitation already pending for this user")
            conn.execute(
                """INSERT INTO project_invitations
                   (id, workspace_id, inviter_id, invitee_id, role, message, status, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)""",
                (inv_id, workspace_id, inviter_id, invitee_id, role, message, now),
            )
        return {"id": inv_id, "workspace_id": workspace_id, "role": role, "status": "pending"}

    def list_invitations_for_user(self, user_id: str) -> List[Dict[str, Any]]:
        with _conn() as conn:
            rows = conn.execute(
                """SELECT i.*, w.name as workspace_name, w.color as workspace_color
                   FROM project_invitations i
                   JOIN project_workspaces w ON w.id = i.workspace_id
                   WHERE i.invitee_id = ? AND i.status = 'pending'
                   ORDER BY i.created_at DESC""",
                (user_id,),
            ).fetchall()
            result = []
            for r in rows:
                d = dict(r)
                # Resolve inviter name
                inviter = conn.execute("SELECT display_name, username FROM users WHERE id = ?",
                                       (d["inviter_id"],)).fetchone()
                d["inviter_name"] = (dict(inviter).get("display_name") or dict(inviter).get("username", "?")) if inviter else "?"
                result.append(d)
            return result

    def respond_invitation(self, invitation_id: str, user_id: str, accept: bool) -> bool:
        now = _now()
        with _conn() as conn:
            inv = conn.execute(
                "SELECT * FROM project_invitations WHERE id = ? AND invitee_id = ? AND status = 'pending'",
                (invitation_id, user_id),
            ).fetchone()
            if inv is None:
                return False
            inv = dict(inv)
            new_status = "accepted" if accept else "rejected"
            conn.execute(
                "UPDATE project_invitations SET status = ?, responded_at = ? WHERE id = ?",
                (new_status, now, invitation_id),
            )
            if accept:
                conn.execute(
                    """INSERT OR REPLACE INTO project_members
                       (workspace_id, user_id, role, invited_by, invited_at, accepted_at, status)
                       VALUES (?, ?, ?, ?, ?, ?, 'accepted')""",
                    (inv["workspace_id"], user_id, inv["role"], inv["inviter_id"], inv["created_at"], now),
                )
                self._log_activity(
                    conn, inv["workspace_id"], None, user_id, "",
                    "member_added", {"role": inv["role"]},
                )
        return True

    # --- Activity ---

    def get_activity(self, workspace_id: str, limit: int = 30) -> List[Dict[str, Any]]:
        with _conn() as conn:
            rows = conn.execute(
                "SELECT * FROM project_activity WHERE workspace_id = ? ORDER BY created_at DESC LIMIT ?",
                (workspace_id, limit),
            ).fetchall()
            result = []
            for r in rows:
                d = dict(r)
                d["detail"] = json.loads(d.get("detail") or "{}")
                result.append(d)
            return result

    def log_activity(self, workspace_id: str, subproject_id: Optional[str],
                     user_id: str, user_name: str, action: str,
                     detail: Optional[Dict] = None) -> None:
        with _conn() as conn:
            self._log_activity(conn, workspace_id, subproject_id, user_id, user_name, action, detail)

    # --- Migration: file-based projects → workspaces ---

    def migrate_file_projects(self, projects_dir: Path, owner_id: str) -> int:
        """Scan data_www/projects/ and create workspaces for any legacy projects
        not yet migrated.  Runs once — after the first successful migration we
        write a sentinel file so subsequent server restarts skip the scan.
        This prevents re-creating workspaces for projects that were deliberately
        deleted by users."""
        if not projects_dir.exists():
            return 0

        # Sentinel: if migration already ran, skip entirely
        sentinel = projects_dir / "_workspace_migration_done"
        if sentinel.exists():
            return 0

        migrated = 0
        for pdir in sorted(projects_dir.iterdir()):
            if not pdir.is_dir() or pdir.name.startswith("_"):
                continue
            meta_file = pdir / "project.json"
            if not meta_file.exists():
                continue

            project_id = pdir.name
            # Check if already migrated (subproject with this data_dir exists)
            with _conn() as conn:
                existing = conn.execute(
                    "SELECT id FROM subprojects WHERE data_dir = ?",
                    (f"projects/{project_id}",),
                ).fetchone()
                if existing:
                    continue

            try:
                meta = json.loads(meta_file.read_text(encoding="utf-8"))
            except Exception:
                continue

            project_name = meta.get("name", project_id[:8])
            proj_owner = meta.get("owner_id", owner_id) or owner_id

            # Determine subproject type from meta
            sp_type = "analysis"
            if meta.get("has_transcript"):
                sp_type = "transcription"
            if meta.get("has_diarized"):
                sp_type = "diarization"

            audio = meta.get("audio_file", "")

            # Find or create the owner's default workspace (NOT one-per-project)
            owner_workspaces = self.list_workspaces(proj_owner, "active")
            owned = [w for w in owner_workspaces if w.get("owner_id") == proj_owner]
            if owned:
                ws = owned[0]
            else:
                ws = self.create_workspace(proj_owner, "Moje projekty")
            if not ws:
                continue

            # Create subproject pointing to legacy data dir
            self.create_subproject(
                workspace_id=ws["id"],
                name=project_name,
                subproject_type=sp_type,
                data_dir=f"projects/{project_id}",
                audio_file=audio,
                metadata=meta,
                created_by=proj_owner,
            )

            migrated += 1

        # Write sentinel so migration does not re-run on restart
        try:
            sentinel.write_text(
                f"Migration completed. {migrated} projects migrated.\n",
                encoding="utf-8",
            )
        except OSError:
            pass  # read-only FS — tolerate

        if migrated > 0:
            log.info("Migrated %d file-based projects to workspaces", migrated)
        return migrated

    # --- Aggressive cleanup of workspace memberships ---

    def cleanup_migration_memberships(self) -> int:
        """Aggressively clean up workspace membership data.

        Runs on every server start.  Fixes three categories of issues:
        1) Non-owner members without invitation records (ghost memberships
           from old migration code that used add_member() directly).
        2) 'owner' role members who don't match workspace.owner_id
           (impossible state — but fix it if data is corrupt).
        3) Duplicate owner entries (keep only the real owner).
        """
        removed = 0
        with _conn() as conn:
            # 1) Remove non-owner members without invitation records
            rows = conn.execute(
                """SELECT m.workspace_id, m.user_id
                   FROM project_members m
                   LEFT JOIN project_invitations i
                     ON  i.workspace_id = m.workspace_id
                     AND i.invitee_id   = m.user_id
                   WHERE m.role != 'owner'
                     AND i.id IS NULL""",
            ).fetchall()
            for r in rows:
                conn.execute(
                    "DELETE FROM project_members WHERE workspace_id = ? AND user_id = ? AND role != 'owner'",
                    (r["workspace_id"], r["user_id"]),
                )
                removed += 1

            # 2) Fix 'owner' role members that don't match workspace.owner_id
            bad_owners = conn.execute(
                """SELECT m.workspace_id, m.user_id
                   FROM project_members m
                   JOIN project_workspaces w ON w.id = m.workspace_id
                   WHERE m.role = 'owner'
                     AND m.user_id != w.owner_id""",
            ).fetchall()
            for r in bad_owners:
                conn.execute(
                    "DELETE FROM project_members WHERE workspace_id = ? AND user_id = ? AND role = 'owner'",
                    (r["workspace_id"], r["user_id"]),
                )
                removed += 1

            # 3) Ensure each workspace has its real owner in project_members
            missing_owners = conn.execute(
                """SELECT w.id as workspace_id, w.owner_id
                   FROM project_workspaces w
                   LEFT JOIN project_members m
                     ON m.workspace_id = w.id AND m.user_id = w.owner_id AND m.role = 'owner'
                   WHERE m.user_id IS NULL""",
            ).fetchall()
            now = _now()
            for r in missing_owners:
                conn.execute(
                    """INSERT OR IGNORE INTO project_members
                       (workspace_id, user_id, role, invited_by, invited_at, accepted_at, status)
                       VALUES (?, ?, 'owner', ?, ?, ?, 'accepted')""",
                    (r["workspace_id"], r["owner_id"], r["owner_id"], now, now),
                )

        if removed > 0:
            log.info("Cleaned up %d invalid workspace memberships", removed)
        return removed

    # --- Internal helpers ---

    def _log_activity(self, conn, workspace_id, subproject_id, user_id, user_name, action, detail=None):
        conn.execute(
            """INSERT INTO project_activity
               (id, workspace_id, subproject_id, user_id, user_name, action, detail, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (_id(), workspace_id, subproject_id, user_id, user_name, action,
             json.dumps(detail or {}, ensure_ascii=False), _now()),
        )

    def _count_members(self, conn, workspace_id: str) -> int:
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM project_members WHERE workspace_id = ? AND status = 'accepted'",
            (workspace_id,),
        ).fetchone()
        return row["cnt"] if row else 0

    def _count_subprojects(self, conn, workspace_id: str) -> int:
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM subprojects WHERE workspace_id = ?",
            (workspace_id,),
        ).fetchone()
        return row["cnt"] if row else 0

    def _get_members_brief(self, conn, workspace_id: str) -> List[Dict[str, str]]:
        rows = conn.execute(
            """SELECT m.user_id, m.role, u.display_name, u.username
               FROM project_members m
               LEFT JOIN users u ON u.id = m.user_id
               WHERE m.workspace_id = ? AND m.status = 'accepted'
               ORDER BY CASE m.role
                 WHEN 'owner' THEN 0 WHEN 'manager' THEN 1
                 WHEN 'editor' THEN 2 WHEN 'commenter' THEN 3 ELSE 4 END""",
            (workspace_id,),
        ).fetchall()
        return [{"user_id": r["user_id"], "role": r["role"],
                 "name": r["display_name"] or r["username"] or "?"} for r in rows]

    def _get_members_full(self, conn, workspace_id: str) -> List[Dict[str, Any]]:
        rows = conn.execute(
            """SELECT m.*, u.display_name, u.username
               FROM project_members m
               LEFT JOIN users u ON u.id = m.user_id
               WHERE m.workspace_id = ? AND m.status = 'accepted'
               ORDER BY CASE m.role
                 WHEN 'owner' THEN 0 WHEN 'manager' THEN 1
                 WHEN 'editor' THEN 2 WHEN 'commenter' THEN 3 ELSE 4 END""",
            (workspace_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def _get_user_role(self, conn, workspace_id: str, user_id: str) -> Optional[str]:
        # Owner always has access
        row = conn.execute(
            "SELECT owner_id FROM project_workspaces WHERE id = ?", (workspace_id,)
        ).fetchone()
        if row and row["owner_id"] == user_id:
            return "owner"
        # Check membership
        row = conn.execute(
            "SELECT role FROM project_members WHERE workspace_id = ? AND user_id = ? AND status = 'accepted'",
            (workspace_id, user_id),
        ).fetchone()
        return row["role"] if row else None

    def _get_links(self, conn, subproject_id: str) -> List[Dict[str, Any]]:
        rows = conn.execute(
            """SELECT l.*, s.name as target_name, s.subproject_type as target_type
               FROM subproject_links l
               JOIN subprojects s ON s.id = l.target_id
               WHERE l.source_id = ?
               UNION ALL
               SELECT l.*, s.name as target_name, s.subproject_type as target_type
               FROM subproject_links l
               JOIN subprojects s ON s.id = l.source_id
               WHERE l.target_id = ?""",
            (subproject_id, subproject_id),
        ).fetchall()
        return [dict(r) for r in rows]
