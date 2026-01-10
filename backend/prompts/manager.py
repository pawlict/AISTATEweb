"""Prompt management (system + user-defined).

User prompts are stored in:
  projects/_global/prompts/

Each user prompt is a JSON file named: <prompt_id>.json
A lightweight metadata file (metadata.json) keeps usage counters and timestamps.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .templates import PROMPT_LIBRARY


_ALLOWED_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_\-]{0,63}$")


def _now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _slugify(name: str) -> str:
    """Convert an arbitrary display name into a safe prompt id."""
    s = name.strip().lower()
    # Replace whitespace with underscore
    s = re.sub(r"\s+", "_", s)
    # Keep ASCII-ish letters/numbers/underscore/dash
    s = re.sub(r"[^a-z0-9_\-]", "", s)
    s = re.sub(r"_+", "_", s).strip("_-")
    return s or "prompt"


@dataclass
class PromptSummary:
    id: str
    name: str
    icon: str = "🧩"
    editable: bool = True
    usage: int = 0
    category: str = "Custom"
    combinable: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "icon": self.icon,
            "editable": self.editable,
            "usage": self.usage,
            "category": self.category,
            "combinable": self.combinable,
        }


class PromptManager:
    def __init__(self, projects_dir: Path) -> None:
        self.projects_dir = projects_dir
        self.global_dir = self.projects_dir / "_global" / "prompts"
        self.global_dir.mkdir(parents=True, exist_ok=True)
        self._metadata_path = self.global_dir / "metadata.json"

    # -------------------- metadata --------------------
    def _load_metadata(self) -> Dict[str, Any]:
        if self._metadata_path.exists():
            try:
                return json.loads(self._metadata_path.read_text(encoding="utf-8"))
            except Exception:
                return {}
        return {}

    def _save_metadata(self, meta: Dict[str, Any]) -> None:
        self._metadata_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    def _get_usage(self, meta: Dict[str, Any], prompt_id: str) -> int:
        usage = meta.get("usage", {})
        try:
            return int(usage.get(prompt_id, 0))
        except Exception:
            return 0

    def bump_usage(self, prompt_id: str, delta: int = 1) -> None:
        """Increase usage counter for a prompt (best-effort)."""
        try:
            meta = self._load_metadata()
            meta.setdefault("usage", {})
            meta["usage"][prompt_id] = int(meta["usage"].get(prompt_id, 0)) + int(delta)
            meta.setdefault("updated_at", {})
            meta["updated_at"][prompt_id] = _now_iso()
            self._save_metadata(meta)
        except Exception:
            pass

    # -------------------- listing --------------------
    def list_system(self) -> List[PromptSummary]:
        out: List[PromptSummary] = []
        for pid, p in PROMPT_LIBRARY.items():
            out.append(
                PromptSummary(
                    id=pid,
                    name=str(p.get("name", pid)),
                    icon=str(p.get("icon", "📚")),
                    editable=False,
                    usage=0,
                    category=str(p.get("category", "System")),
                    combinable=bool(p.get("combinable", True)),
                )
            )
        # Stable sort by name for UI
        out.sort(key=lambda x: x.name)
        return out

    def list_user(self) -> List[PromptSummary]:
        meta = self._load_metadata()
        out: List[PromptSummary] = []
        for fp in sorted(self.global_dir.glob("*.json")):
            if fp.name == "metadata.json":
                continue
            try:
                obj = json.loads(fp.read_text(encoding="utf-8"))
            except Exception:
                continue

            pid = str(obj.get("id") or fp.stem)
            name = str(obj.get("name") or pid)
            icon = str(obj.get("icon") or "✨")
            category = str(obj.get("category") or "Custom")
            combinable = bool(obj.get("combinable", True))
            out.append(
                PromptSummary(
                    id=pid,
                    name=name,
                    icon=icon,
                    editable=True,
                    usage=self._get_usage(meta, pid),
                    category=category,
                    combinable=combinable,
                )
            )

        out.sort(key=lambda x: (-x.usage, x.name))
        return out

    def list_all(self) -> Dict[str, Any]:
        return {
            "system": [p.to_dict() for p in self.list_system()],
            "user": [p.to_dict() for p in self.list_user()],
        }

    # -------------------- CRUD --------------------
    def _validate_id(self, prompt_id: str) -> str:
        pid = (prompt_id or "").strip().lower()
        if not pid:
            raise ValueError("prompt_id is empty")
        if not _ALLOWED_ID_RE.match(pid):
            raise ValueError("prompt_id contains invalid characters")
        if pid in PROMPT_LIBRARY:
            raise ValueError("prompt_id conflicts with a system prompt")
        return pid

    def _unique_id(self, base_id: str) -> str:
        pid = base_id
        i = 2
        while (self.global_dir / f"{pid}.json").exists() or pid in PROMPT_LIBRARY:
            pid = f"{base_id}_{i}"
            i += 1
        return pid

    def create_user_prompt(self, data: Dict[str, Any]) -> str:
        name = str(data.get("name") or "").strip()
        prompt_text = str(data.get("prompt") or "").strip()
        if not name:
            raise ValueError("name is required")
        if not prompt_text:
            raise ValueError("prompt is required")

        requested_id = str(data.get("id") or "").strip().lower()
        base_id = _slugify(requested_id or name)
        if not _ALLOWED_ID_RE.match(base_id):
            base_id = _slugify(name)
        pid = self._unique_id(base_id)
        pid = self._validate_id(pid)

        obj = {
            "id": pid,
            "name": name,
            "description": str(data.get("description") or "").strip(),
            "prompt": prompt_text,
            "icon": str(data.get("icon") or "✨"),
            "category": str(data.get("category") or "Custom"),
            "combinable": bool(data.get("combinable", True)),
        }

        (self.global_dir / f"{pid}.json").write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")

        meta = self._load_metadata()
        meta.setdefault("usage", {})
        meta.setdefault("created_at", {})
        meta.setdefault("updated_at", {})
        meta["created_at"][pid] = meta["created_at"].get(pid, _now_iso())
        meta["updated_at"][pid] = _now_iso()
        self._save_metadata(meta)

        return pid

    def update_user_prompt(self, prompt_id: str, updates: Dict[str, Any]) -> None:
        pid = self._validate_id(prompt_id)
        fp = self.global_dir / f"{pid}.json"
        if not fp.exists():
            raise FileNotFoundError(pid)

        obj = json.loads(fp.read_text(encoding="utf-8"))
        # Allowed fields
        for key in ("name", "description", "prompt", "icon", "category", "combinable"):
            if key in updates:
                obj[key] = updates[key]

        # Basic validation
        if not str(obj.get("name") or "").strip():
            raise ValueError("name cannot be empty")
        if not str(obj.get("prompt") or "").strip():
            raise ValueError("prompt cannot be empty")

        obj["id"] = pid
        fp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")

        meta = self._load_metadata()
        meta.setdefault("updated_at", {})
        meta["updated_at"][pid] = _now_iso()
        self._save_metadata(meta)

    def delete_user_prompt(self, prompt_id: str) -> None:
        pid = self._validate_id(prompt_id)
        fp = self.global_dir / f"{pid}.json"
        if not fp.exists():
            raise FileNotFoundError(pid)

        fp.unlink(missing_ok=True)  # type: ignore[arg-type]

        meta = self._load_metadata()
        for k in ("usage", "created_at", "updated_at"):
            if isinstance(meta.get(k), dict):
                meta[k].pop(pid, None)
        self._save_metadata(meta)

    # -------------------- access --------------------
    def get_prompt_text(self, prompt_id: str) -> str:
        """Return the actual prompt instruction text (system or user)."""
        pid = (prompt_id or "").strip()
        if pid in PROMPT_LIBRARY:
            return str(PROMPT_LIBRARY[pid].get("prompt") or "")

        pid = self._validate_id(pid)
        fp = self.global_dir / f"{pid}.json"
        if not fp.exists():
            raise FileNotFoundError(pid)
        obj = json.loads(fp.read_text(encoding="utf-8"))
        return str(obj.get("prompt") or "")

    def export_user_prompt_path(self, prompt_id: str) -> Path:
        pid = self._validate_id(prompt_id)
        fp = self.global_dir / f"{pid}.json"
        if not fp.exists():
            raise FileNotFoundError(pid)
        return fp

    def import_user_prompt(self, obj: Dict[str, Any]) -> str:
        """Import a user prompt from JSON object. Returns the created prompt_id."""
        name = str(obj.get("name") or "").strip()
        prompt_text = str(obj.get("prompt") or "").strip()
        if not name or not prompt_text:
            raise ValueError("Imported prompt must include 'name' and 'prompt'")

        requested_id = str(obj.get("id") or "").strip().lower()
        base_id = _slugify(requested_id or name)
        if not _ALLOWED_ID_RE.match(base_id):
            base_id = _slugify(name)

        pid = self._unique_id(base_id)
        pid = self._validate_id(pid)

        obj = dict(obj)
        obj["id"] = pid
        obj.setdefault("icon", "✨")
        obj.setdefault("category", "Custom")
        obj.setdefault("combinable", True)

        (self.global_dir / f"{pid}.json").write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")

        meta = self._load_metadata()
        meta.setdefault("usage", {})
        meta.setdefault("created_at", {})
        meta.setdefault("updated_at", {})
        meta["created_at"][pid] = _now_iso()
        meta["updated_at"][pid] = _now_iso()
        self._save_metadata(meta)

        return pid

    def build_combined_prompt(self, template_ids: List[str], custom_prompt: Optional[str] = None) -> str:
        """Combine multiple prompt templates + optional custom prompt into one instruction."""
        parts: List[str] = []
        for pid in template_ids:
            text = self.get_prompt_text(pid)
            if text.strip():
                parts.append(text.strip())
        if custom_prompt and str(custom_prompt).strip():
            parts.append(str(custom_prompt).strip())
        return "\n\n---\n\n".join(parts).strip()
