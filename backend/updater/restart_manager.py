from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import sys
from datetime import datetime, timedelta
from typing import Optional

log = logging.getLogger("aistate.updater")


class RestartManager:
    """Manages scheduled application restarts after updates."""

    def __init__(self) -> None:
        self._restart_at: Optional[datetime] = None
        self._timer_task: Optional[asyncio.Task] = None
        self._auto_restart: bool = True
        self._delay_seconds: int = 300  # default 5 minutes
        self._pending: bool = False  # True after update installed, awaiting restart

    def schedule_restart(self, delay_seconds: int = 300) -> None:
        """Schedule an auto-restart after delay_seconds."""
        self._delay_seconds = delay_seconds
        self._pending = True

        if not self._auto_restart:
            self._restart_at = None
            return

        self._restart_at = datetime.now() + timedelta(seconds=delay_seconds)

        # Cancel any existing timer
        if self._timer_task and not self._timer_task.done():
            self._timer_task.cancel()

        try:
            loop = asyncio.get_event_loop()
            self._timer_task = loop.create_task(self._countdown(delay_seconds))
        except RuntimeError:
            log.warning("No event loop available for restart timer")

    async def _countdown(self, seconds: int) -> None:
        """Wait and then restart."""
        try:
            await asyncio.sleep(seconds)
            self._do_restart()
        except asyncio.CancelledError:
            pass

    def cancel_restart(self) -> bool:
        """Cancel a pending auto-restart. Returns True if there was one to cancel."""
        if self._timer_task and not self._timer_task.done():
            self._timer_task.cancel()
            self._timer_task = None
        self._restart_at = None
        return True

    def restart_now(self) -> None:
        """Trigger an immediate restart."""
        if self._timer_task and not self._timer_task.done():
            self._timer_task.cancel()
        self._do_restart()

    def set_auto_restart(self, enabled: bool) -> None:
        """Enable/disable auto-restart."""
        self._auto_restart = enabled
        if not enabled:
            self.cancel_restart()

    def get_status(self) -> dict:
        """Return current restart status."""
        seconds_remaining = 0
        if self._restart_at:
            delta = (self._restart_at - datetime.now()).total_seconds()
            seconds_remaining = max(0, int(delta))

        return {
            "pending": self._pending,
            "auto_restart": self._auto_restart,
            "scheduled": self._restart_at is not None,
            "restart_at": self._restart_at.isoformat() if self._restart_at else None,
            "seconds_remaining": seconds_remaining,
            "delay_seconds": self._delay_seconds,
        }

    def _do_restart(self) -> None:
        """Perform the actual process restart."""
        log.info("Restarting application...")

        python = sys.executable
        args = sys.argv[:]

        if sys.platform == "win32":
            # On Windows, os.execv doesn't work well — use subprocess + exit
            subprocess.Popen([python] + args)
            os._exit(0)
        else:
            os.execv(python, [python] + args)
