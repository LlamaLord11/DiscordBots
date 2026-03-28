"""
tasks/backup_task.py
--------------------
Periodic database backup loop with retention rotation.
Calls services only — no direct DB queries.
"""

from __future__ import annotations
import asyncio
import logging
import shutil
import os
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Coroutine

from ..utils.formatting import utcnow, backup_filename

if TYPE_CHECKING:
    pass

log = logging.getLogger(__name__)


class BackupTask:
    """Manages the periodic database backup loop.

    Args:
        db_path:           Path to the SQLite database file.
        backup_dir:        Directory to write backup files into.
        interval_hours:    How often to run backups (hours).
        retention_count:   Max number of backup files to keep.
        alert_fn:          Async callable that accepts a discord.Embed for failure alerts.
    """

    def __init__(
        self,
        db_path: str,
        backup_dir: str,
        interval_hours: int,
        retention_count: int,
        alert_fn: Callable[..., Coroutine] | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.backup_dir = Path(backup_dir)
        self.interval_seconds = interval_hours * 3600
        self.retention_count = retention_count
        self.alert_fn = alert_fn
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._loop())
        log.info(
            "Backup task started — every %sh, keeping %s files in %s",
            self.interval_seconds // 3600,
            self.retention_count,
            self.backup_dir,
        )

    def stop(self) -> None:
        if self._task:
            self._task.cancel()

    async def _loop(self) -> None:
        while True:
            await asyncio.sleep(self.interval_seconds)
            await self._run_backup()

    async def _run_backup(self) -> None:
        filename = backup_filename(utcnow())
        dest = self.backup_dir / filename
        try:
            shutil.copy2(self.db_path, dest)
            log.info("Backup written: %s", dest)
            self._rotate()
        except Exception as exc:
            log.error("Backup failed: %s", exc)
            if self.alert_fn:
                from ..utils.embeds import backup_failure_alert
                try:
                    await self.alert_fn(embed=backup_failure_alert(str(dest), str(exc)))
                except Exception:
                    pass  # Don't let alert failure crash the task

    def _rotate(self) -> None:
        """Delete oldest backup files beyond the retention limit."""
        files = sorted(
            self.backup_dir.glob("solyra_backup_*.db"),
            key=lambda f: f.stat().st_mtime,
        )
        excess = len(files) - self.retention_count
        if excess > 0:
            for f in files[:excess]:
                try:
                    f.unlink()
                    log.info("Rotated old backup: %s", f)
                except Exception as exc:
                    log.warning("Could not delete old backup %s: %s", f, exc)