"""
Report Profile Manager — per-user template and placeholder storage.

Each user (identified by UUID) has their own profile with:
- Custom DOCX templates (GSM / AML)
- Saved placeholder values (institution name, signature, analyst, etc.)
- Profile metadata (name, creation date)

Profiles are stored as flat JSON files:
    data_www/report_profiles/{profile_id}/profile.json
    data_www/report_profiles/{profile_id}/placeholders.json
    data_www/report_profiles/{profile_id}/gsm_report_template.docx
    data_www/report_profiles/{profile_id}/aml_report_template.docx

A `_default` profile provides the base template for new users.
"""
from __future__ import annotations

import json
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


class ReportProfileManager:
    """Manages report profiles (templates + placeholders) for users."""

    DEFAULT_PROFILE_ID = "_default"

    def __init__(self, data_dir: Path):
        self.profiles_dir = data_dir / "report_profiles"
        self.profiles_dir.mkdir(parents=True, exist_ok=True)
        # Ensure default profile directory exists
        default_dir = self.profiles_dir / self.DEFAULT_PROFILE_ID
        default_dir.mkdir(exist_ok=True)
        default_profile = default_dir / "profile.json"
        if not default_profile.exists():
            default_profile.write_text(json.dumps({
                "id": self.DEFAULT_PROFILE_ID,
                "name": "Domyślny",
                "created_at": datetime.now().isoformat(),
            }, ensure_ascii=False, indent=2), encoding="utf-8")

    # ─── Profile CRUD ─────────────────────────────────────────────────────

    def list_profiles(self) -> List[Dict[str, Any]]:
        """List all profiles (excluding _default)."""
        profiles = []
        for d in sorted(self.profiles_dir.iterdir()):
            if not d.is_dir():
                continue
            pf = d / "profile.json"
            if pf.exists():
                try:
                    data = json.loads(pf.read_text(encoding="utf-8"))
                    profiles.append({
                        "id": data.get("id", d.name),
                        "name": data.get("name", d.name),
                        "created_at": data.get("created_at", ""),
                    })
                except (json.JSONDecodeError, OSError):
                    pass
        return profiles

    def create_profile(self, name: str) -> Dict[str, Any]:
        """Create a new profile with a unique UUID. Returns profile info."""
        profile_id = str(uuid.uuid4())
        profile_dir = self.profiles_dir / profile_id
        profile_dir.mkdir(parents=True, exist_ok=True)

        now = datetime.now().isoformat()
        profile_data = {
            "id": profile_id,
            "name": name,
            "created_at": now,
        }
        (profile_dir / "profile.json").write_text(
            json.dumps(profile_data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        # Initialize empty placeholders
        (profile_dir / "placeholders.json").write_text(
            json.dumps({}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return profile_data

    def get_profile(self, profile_id: str) -> Optional[Dict[str, Any]]:
        """Get profile info + placeholders."""
        profile_dir = self.profiles_dir / profile_id
        pf = profile_dir / "profile.json"
        if not pf.exists():
            return None
        try:
            data = json.loads(pf.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

        # Load placeholders
        ph_path = profile_dir / "placeholders.json"
        placeholders = {}
        if ph_path.exists():
            try:
                placeholders = json.loads(ph_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass

        data["placeholders"] = placeholders

        # Check which custom templates exist
        data["has_gsm_template"] = (profile_dir / "gsm_report_template.docx").exists()
        data["has_aml_template"] = (profile_dir / "aml_report_template.docx").exists()

        return data

    def update_profile(self, profile_id: str, name: Optional[str] = None,
                       placeholders: Optional[Dict[str, str]] = None) -> bool:
        """Update profile name and/or placeholders. Returns True on success."""
        profile_dir = self.profiles_dir / profile_id
        pf = profile_dir / "profile.json"
        if not pf.exists():
            return False

        if name is not None:
            try:
                data = json.loads(pf.read_text(encoding="utf-8"))
                data["name"] = name
                pf.write_text(
                    json.dumps(data, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            except (json.JSONDecodeError, OSError):
                return False

        if placeholders is not None:
            ph_path = profile_dir / "placeholders.json"
            # Merge with existing
            existing = {}
            if ph_path.exists():
                try:
                    existing = json.loads(ph_path.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    pass
            existing.update(placeholders)
            ph_path.write_text(
                json.dumps(existing, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

        return True

    def delete_profile(self, profile_id: str) -> bool:
        """Delete a profile. Cannot delete _default."""
        if profile_id == self.DEFAULT_PROFILE_ID:
            return False
        profile_dir = self.profiles_dir / profile_id
        if not profile_dir.exists():
            return False
        shutil.rmtree(profile_dir, ignore_errors=True)
        return True

    # ─── Template management ──────────────────────────────────────────────

    def get_template_path(self, profile_id: str, report_type: str) -> Optional[Path]:
        """Get path to the DOCX template for a profile.

        Falls back to _default if profile doesn't have a custom template.
        report_type: "gsm" or "aml"
        """
        filename = f"{report_type}_report_template.docx"
        # Check profile-specific template first
        profile_dir = self.profiles_dir / profile_id
        custom_path = profile_dir / filename
        if custom_path.exists():
            return custom_path
        # Fallback to default
        default_path = self.profiles_dir / self.DEFAULT_PROFILE_ID / filename
        if default_path.exists():
            return default_path
        return None

    def save_template(self, profile_id: str, report_type: str,
                      template_bytes: bytes) -> bool:
        """Save a custom template for a profile."""
        filename = f"{report_type}_report_template.docx"
        profile_dir = self.profiles_dir / profile_id
        if not profile_dir.exists():
            return False
        (profile_dir / filename).write_bytes(template_bytes)
        return True

    def reset_template(self, profile_id: str, report_type: str) -> bool:
        """Delete custom template, falling back to _default."""
        if profile_id == self.DEFAULT_PROFILE_ID:
            return False
        filename = f"{report_type}_report_template.docx"
        profile_dir = self.profiles_dir / profile_id
        custom_path = profile_dir / filename
        if custom_path.exists():
            custom_path.unlink()
            return True
        return False

    def save_default_template(self, report_type: str,
                              template_bytes: bytes) -> Path:
        """Save/update the default template. Returns the path."""
        filename = f"{report_type}_report_template.docx"
        default_dir = self.profiles_dir / self.DEFAULT_PROFILE_ID
        default_dir.mkdir(exist_ok=True)
        path = default_dir / filename
        path.write_bytes(template_bytes)
        return path

    def get_placeholders(self, profile_id: str) -> Dict[str, str]:
        """Get saved placeholder values for a profile."""
        profile_dir = self.profiles_dir / profile_id
        ph_path = profile_dir / "placeholders.json"
        if not ph_path.exists():
            return {}
        try:
            return json.loads(ph_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
