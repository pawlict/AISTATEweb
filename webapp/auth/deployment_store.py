from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Optional


class DeploymentStore:
    """Reads/writes deployment.json — the mode selector (single vs multi)."""

    def __init__(self, config_dir: Path) -> None:
        self._path = config_dir / "deployment.json"

    def get_mode(self) -> Optional[str]:
        """Return 'single', 'multi', or None (not yet configured)."""
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            return data.get("mode")
        except FileNotFoundError:
            return None
        except Exception:
            return None

    def set_mode(self, mode: str) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "mode": mode,
            "initialized_at": datetime.now().isoformat(),
            "version": 1,
        }
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self._path)

    def is_multiuser(self) -> bool:
        return self.get_mode() == "multi"

    def is_configured(self) -> bool:
        return self.get_mode() is not None
