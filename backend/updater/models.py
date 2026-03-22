from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import List, Optional


class UpdateStatus(str, enum.Enum):
    IDLE = "idle"
    UPLOADED = "uploaded"
    VALIDATING = "validating"
    INSTALLING = "installing"
    INSTALLED = "installed"
    RESTARTING = "restarting"
    FAILED = "failed"
    ROLLING_BACK = "rolling_back"


@dataclass
class UpdateInfo:
    version: str = ""
    min_version: str = ""
    changelog: str = ""
    migrations: List[str] = field(default_factory=list)
    new_dependencies: List[str] = field(default_factory=list)
    min_python: str = ""
    release_date: str = ""


@dataclass
class UpdateHistoryEntry:
    version: str = ""
    installed_at: str = ""
    previous_version: str = ""
    backup_path: str = ""
    status: str = "installed"  # installed | rollback
    changelog: str = ""


@dataclass
class UpdateState:
    status: UpdateStatus = UpdateStatus.IDLE
    current_info: Optional[UpdateInfo] = None
    error: Optional[str] = None
    restart_at: Optional[str] = None
    restart_countdown_seconds: int = 300
    auto_restart: bool = True
