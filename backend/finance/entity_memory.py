"""Entity memory — persistent intelligence about known counterparties.

Stores user-flagged entities and auto-learned patterns so the system
can recognize them in future analyses. Works at two levels:
- Per-project: projects/{id}/finance/intel_memory.json
- Global: projects/_global/finance_entities.json (shared knowledge base)
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Set


@dataclass
class Entity:
    """A known counterparty/entity in the intelligence memory."""

    name: str  # normalized name (lowercase, trimmed)
    display_name: str = ""  # original casing
    entity_type: str = ""  # crypto, gambling, loans, risky, legitimate, unknown
    flagged: bool = False  # user-flagged as suspicious
    notes: str = ""  # user notes
    aliases: List[str] = field(default_factory=list)  # alternative names
    auto_category: str = ""  # category from rule classifier
    confidence: float = 1.0  # 0-1
    first_seen: str = ""  # ISO date
    last_seen: str = ""  # ISO date
    times_seen: int = 0
    total_amount: float = 0.0
    created_at: str = ""
    updated_at: str = ""
    source: str = ""  # "user" or "auto" or "global"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Entity":
        known_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in d.items() if k in known_fields}
        return cls(**filtered)


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


class EntityMemory:
    """Manages the entity intelligence memory for a project."""

    def __init__(self, project_finance_dir: Path, global_dir: Optional[Path] = None):
        self._project_dir = project_finance_dir
        self._project_dir.mkdir(parents=True, exist_ok=True)
        self._project_file = self._project_dir / "intel_memory.json"
        self._global_dir = global_dir
        self._global_file = global_dir / "finance_entities.json" if global_dir else None

        self._entities: Dict[str, Entity] = {}
        self._global_entities: Dict[str, Entity] = {}
        self._loaded = False

    def _load(self) -> None:
        if self._loaded:
            return
        self._entities = self._read_file(self._project_file)
        if self._global_file:
            self._global_entities = self._read_file(self._global_file)
        self._loaded = True

    @staticmethod
    def _read_file(path: Path) -> Dict[str, Entity]:
        if not path or not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return {}
            entities = {}
            for key, val in data.items():
                if isinstance(val, dict):
                    entities[key] = Entity.from_dict(val)
            return entities
        except Exception:
            return {}

    def _save_project(self) -> None:
        self._project_dir.mkdir(parents=True, exist_ok=True)
        data = {k: v.to_dict() for k, v in self._entities.items()}
        self._project_file.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _save_global(self) -> None:
        if not self._global_file or not self._global_dir:
            return
        self._global_dir.mkdir(parents=True, exist_ok=True)
        data = {k: v.to_dict() for k, v in self._global_entities.items()}
        self._global_file.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @staticmethod
    def normalize_name(name: str) -> str:
        """Normalize entity name for matching."""
        import re
        s = name.lower().strip()
        s = re.sub(r"\s+", " ", s)
        # Remove long numbers (account refs)
        s = re.sub(r"\d{10,}", "", s)
        s = re.sub(r"\s+", " ", s).strip()
        return s

    def lookup(self, name: str) -> Optional[Entity]:
        """Look up an entity by name (checks project first, then global)."""
        self._load()
        key = self.normalize_name(name)
        if not key:
            return None

        # Direct match
        if key in self._entities:
            return self._entities[key]
        if key in self._global_entities:
            return self._global_entities[key]

        # Alias match
        for ent in self._entities.values():
            if key in [self.normalize_name(a) for a in ent.aliases]:
                return ent
        for ent in self._global_entities.values():
            if key in [self.normalize_name(a) for a in ent.aliases]:
                return ent

        # Substring match (for partial counterparty names)
        for ent_key, ent in self._entities.items():
            if ent_key in key or key in ent_key:
                return ent
        for ent_key, ent in self._global_entities.items():
            if ent_key in key or key in ent_key:
                return ent

        return None

    def flag_entity(
        self,
        name: str,
        entity_type: str = "",
        notes: str = "",
        flagged: bool = True,
        propagate_global: bool = False,
    ) -> Entity:
        """Flag an entity as suspicious (or update existing)."""
        self._load()
        key = self.normalize_name(name)
        now = _now_iso()

        if key in self._entities:
            ent = self._entities[key]
            ent.flagged = flagged
            if entity_type:
                ent.entity_type = entity_type
            if notes:
                ent.notes = notes
            ent.updated_at = now
        else:
            ent = Entity(
                name=key,
                display_name=name.strip(),
                entity_type=entity_type,
                flagged=flagged,
                notes=notes,
                source="user",
                created_at=now,
                updated_at=now,
            )
            self._entities[key] = ent

        self._save_project()

        # Propagate to global if requested
        if propagate_global and self._global_file:
            if key not in self._global_entities:
                global_ent = Entity(
                    name=key,
                    display_name=name.strip(),
                    entity_type=entity_type,
                    flagged=flagged,
                    notes=notes,
                    source="global",
                    created_at=now,
                    updated_at=now,
                )
                self._global_entities[key] = global_ent
            else:
                self._global_entities[key].flagged = flagged
                if entity_type:
                    self._global_entities[key].entity_type = entity_type
                self._global_entities[key].updated_at = now
            self._save_global()

        return ent

    def unflag_entity(self, name: str) -> Optional[Entity]:
        """Remove flag from entity."""
        self._load()
        key = self.normalize_name(name)
        if key in self._entities:
            self._entities[key].flagged = False
            self._entities[key].updated_at = _now_iso()
            self._save_project()
            return self._entities[key]
        return None

    def update_from_transactions(
        self,
        counterparties: List[Dict[str, Any]],
    ) -> int:
        """Auto-update entity memory from classified transaction data.

        Args:
            counterparties: List of dicts with keys:
                name, category, amount, date

        Returns:
            Number of entities updated.
        """
        self._load()
        now = _now_iso()
        updated = 0

        for cp in counterparties:
            name = cp.get("name", "")
            key = self.normalize_name(name)
            if not key or len(key) < 3:
                continue

            category = cp.get("category", "")
            amount = abs(float(cp.get("amount", 0)))
            date_str = cp.get("date", "")

            if key in self._entities:
                ent = self._entities[key]
                ent.times_seen += 1
                ent.total_amount += amount
                if date_str > (ent.last_seen or ""):
                    ent.last_seen = date_str
                if not ent.first_seen or date_str < ent.first_seen:
                    ent.first_seen = date_str
                if category and not ent.auto_category:
                    ent.auto_category = category
                ent.updated_at = now
            else:
                self._entities[key] = Entity(
                    name=key,
                    display_name=name.strip(),
                    auto_category=category,
                    first_seen=date_str,
                    last_seen=date_str,
                    times_seen=1,
                    total_amount=amount,
                    source="auto",
                    created_at=now,
                    updated_at=now,
                )
            updated += 1

        if updated:
            self._save_project()
        return updated

    def delete_entity(self, name: str) -> bool:
        """Delete entity from project memory."""
        self._load()
        key = self.normalize_name(name)
        if key in self._entities:
            del self._entities[key]
            self._save_project()
            return True
        return False

    def list_entities(
        self,
        flagged_only: bool = False,
        entity_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """List all known entities."""
        self._load()
        result = []

        # Merge project + global (project takes precedence)
        all_ents: Dict[str, Entity] = {}
        for k, v in self._global_entities.items():
            all_ents[k] = v
        for k, v in self._entities.items():
            all_ents[k] = v

        for ent in all_ents.values():
            if flagged_only and not ent.flagged:
                continue
            if entity_type and ent.entity_type != entity_type:
                continue
            d = ent.to_dict()
            d["_source"] = "project" if ent.name in self._entities else "global"
            result.append(d)

        # Sort: flagged first, then by times_seen desc
        result.sort(key=lambda x: (-int(x.get("flagged", False)), -x.get("times_seen", 0)))
        return result

    def get_flagged_names(self) -> Set[str]:
        """Quick set of flagged entity names for fast lookup."""
        self._load()
        names = set()
        for ent in self._entities.values():
            if ent.flagged:
                names.add(ent.name)
                names.update(self.normalize_name(a) for a in ent.aliases)
        for ent in self._global_entities.values():
            if ent.flagged:
                names.add(ent.name)
                names.update(self.normalize_name(a) for a in ent.aliases)
        return names
