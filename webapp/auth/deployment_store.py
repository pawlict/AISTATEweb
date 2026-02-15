from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

log = logging.getLogger("aistate.auth.deployment")


class DeploymentStore:
    """SQLite-backed deployment config (drop-in replacement for JSON version)."""

    def __init__(self, config_dir: Path) -> None:
        self._config_dir = config_dir
        self._json_path = config_dir / "deployment.json"

    def _conn(self):
        from backend.db.engine import get_conn
        return get_conn()

    def get_mode(self) -> Optional[str]:
        """Return 'single', 'multi', or None (not yet configured)."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT value FROM deployment_config WHERE key = 'mode'"
            ).fetchone()
            if row is None:
                return None
            return row["value"]

    def set_mode(self, mode: str) -> None:
        now = datetime.now().isoformat()
        with self._conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO deployment_config (key, value, updated_at) VALUES (?, ?, ?)",
                ("mode", mode, now),
            )
            conn.execute(
                "INSERT OR REPLACE INTO deployment_config (key, value, updated_at) VALUES (?, ?, ?)",
                ("initialized_at", now, now),
            )
            conn.execute(
                "INSERT OR REPLACE INTO deployment_config (key, value, updated_at) VALUES (?, ?, ?)",
                ("version", "1", now),
            )

    def is_multiuser(self) -> bool:
        return self.get_mode() == "multi"

    def is_configured(self) -> bool:
        return self.get_mode() is not None

    # ---- JSON → SQLite migration ----

    def migrate_from_json(self) -> bool:
        """Import deployment config from legacy deployment.json if it exists."""
        if not self._json_path.exists():
            return False

        try:
            data = json.loads(self._json_path.read_text(encoding="utf-8"))
        except Exception:
            return False

        mode = data.get("mode")
        if not mode:
            return False

        # Don't overwrite if already configured in DB
        if self.is_configured():
            # Rename old file anyway
            backup = self._json_path.with_suffix(".json.bak")
            self._json_path.rename(backup)
            return False

        self.set_mode(mode)

        backup = self._json_path.with_suffix(".json.bak")
        self._json_path.rename(backup)
        log.info("Migrated deployment config (mode=%s) from JSON; old file renamed to %s", mode, backup.name)
        return True
