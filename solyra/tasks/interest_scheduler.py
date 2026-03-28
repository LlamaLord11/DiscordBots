"""
tasks/interest_scheduler.py
----------------------------
Weekly interest scheduler using discord.ext.tasks.
Posts a confirmation embed to the audit channel — an admin must confirm
before any balances are modified.
"""

from __future__ import annotations
import asyncio
import calendar
import datetime
import logging
from typing import Callable, Coroutine, TYPE_CHECKING

import discord
from discord.ext import tasks

from ..services.interest_service import (
    get_all_configs,
    check_missed_payment,
    preview_interest_run,
)
from ..utils.embeds import missed_interest_alert
from ..utils.formatting import format_timestamp

if TYPE_CHECKING:
    from ..db.database import Database

log = logging.getLogger(__name__)


class InterestScheduler:
    """Wraps a discord.ext.tasks loop to fire interest alerts on a weekly schedule.

    The scheduler does NOT apply interest directly — it posts a confirmation
    embed with an Apply button to the audit log channel. An admin must press
    the button to trigger the actual application.

    Args:
        db:               Database instance.
        scheduled_day:    Day of week string (e.g. 'monday').
        scheduled_time:   HH:MM UTC string (e.g. '00:00').
        alert_fn:         Async callable — sends embed + view to audit channel.
        apply_view_fn:    Callable that returns a discord.ui.View with Apply button.
    """

    def __init__(
        self,
        db: "Database",
        scheduled_day: str,
        scheduled_time: str,
        alert_fn: Callable[..., Coroutine],
        apply_view_fn: Callable[[str], discord.ui.View],
    ) -> None:
        self.db = db
        self.scheduled_day = scheduled_day.lower()
        self.scheduled_time = scheduled_time
        self.alert_fn = alert_fn
        self.apply_view_fn = apply_view_fn
        self._task: tasks.Loop | None = None

        h, m = map(int, scheduled_time.split(":"))
        self._scheduled_time_obj = datetime.time(hour=h, minute=m, tzinfo=datetime.timezone.utc)

    def start(self) -> None:
        """Build and start the task loop."""

        @tasks.loop(time=self._scheduled_time_obj)
        async def _loop():
            await self._on_scheduled_fire()

        self._task = _loop
        self._task.start()
        log.info(
            "Interest scheduler started — %s at %s UTC",
            self.scheduled_day.capitalize(),
            self.scheduled_time,
        )

    def stop(self) -> None:
        if self._task:
            self._task.cancel()

    async def _on_scheduled_fire(self) -> None:
        """Called by the task loop every day at the scheduled time.
        Only acts on the configured day of week.
        """
        now = datetime.datetime.now(datetime.timezone.utc)
        day_num = list(calendar.day_name).index(self.scheduled_day.capitalize())

        if now.weekday() != day_num:
            return  # Not our day

        configs = await get_all_configs(self.db)
        for config in configs:
            if config.get("is_paused"):
                log.info("Interest skipped for %s — paused.", config["account_type"])
                continue
            await self._post_interest_alert(config["account_type"])

    async def _post_interest_alert(self, account_type: str) -> None:
        """Post a missed/scheduled interest alert with Apply button."""
        try:
            preview = await preview_interest_run(self.db, account_type)
            config = preview["config"]
            last_applied = format_timestamp(config.get("last_applied"))

            embed = missed_interest_alert(
                account_type=account_type,
                scheduled_day=self.scheduled_day,
                scheduled_time=self.scheduled_time,
                last_applied=last_applied,
            )
            # Override title for scheduled (not missed) runs
            embed.title = f"⏰ Scheduled Interest Due — {account_type.capitalize()}"
            embed.description = (
                f"Weekly interest is due for **{account_type.capitalize()}** accounts.\n"
                f"Rate: **{preview['rate_display']}** | "
                f"Eligible accounts: **{preview['eligible_count']}** | "
                f"Estimated total: **{preview['estimated_total_display']}**\n\n"
                "Press **Apply** to process, or dismiss this message."
            )

            view = self.apply_view_fn(account_type)
            await self.alert_fn(embed=embed, view=view)

        except Exception as exc:
            log.error("Failed to post interest alert for %s: %s", account_type, exc)

    async def check_missed_on_startup(self) -> None:
        """Called during startup — posts alerts for any missed scheduled runs."""
        configs = await get_all_configs(self.db)
        for config in configs:
            if config.get("is_paused"):
                continue
            missed = check_missed_payment(
                config.get("last_applied"),
                self.scheduled_day,
                self.scheduled_time,
            )
            if missed:
                log.warning(
                    "Missed interest payment detected for %s", config["account_type"]
                )
                await self._post_missed_alert(config)

    async def _post_missed_alert(self, config: dict) -> None:
        """Post a missed payment alert with Apply button."""
        try:
            account_type = config["account_type"]
            last_applied = format_timestamp(config.get("last_applied"))

            embed = missed_interest_alert(
                account_type=account_type,
                scheduled_day=self.scheduled_day,
                scheduled_time=self.scheduled_time,
                last_applied=last_applied,
            )
            view = self.apply_view_fn(account_type)
            await self.alert_fn(embed=embed, view=view)

        except Exception as exc:
            log.error("Failed to post missed interest alert: %s", exc)