"""
cogs/admin.py
-------------
All /admin subcommands: freeze, unfreeze, adjust, audit, status,
interest pause/resume/forceapply, and the VC tracker update helper.
"""

from __future__ import annotations
import asyncio
import logging
import time
from typing import TYPE_CHECKING, Optional

import discord
from discord import app_commands
from discord.ext import commands

from ..services.account_service import (
    freeze_account,
    unfreeze_account,
    admin_adjust_balance,
    get_bank_stats,
    get_account_or_raise,
)
from ..services.interest_service import (
    get_all_configs,
    pause_all,
    resume_all,
    preview_interest_run,
    apply_interest,
)
from ..services.audit_service import log_action, get_paginated_audit
from ..utils.formatting import (
    parse_amount_to_cents,
    cents_to_display,
    format_account_id,
    format_timestamp,
    utcnow,
    basis_points_to_percent,
)
from ..utils.permissions import is_admin, get_origin_context
from ..utils import embeds as E

if TYPE_CHECKING:
    from ..db.database import Database

log = logging.getLogger(__name__)

# ─── VC Tracker ───────────────────────────────────────────────────────────────

class VCTracker:
    """Manages rate-limited voice channel name updates."""

    def __init__(self, channel_id: int, cooldown_minutes: int, bot: commands.Bot, db) -> None:
        self.channel_id = channel_id
        self.cooldown_seconds = cooldown_minutes * 60
        self.bot = bot
        self.db = db
        self._last_update: float = 0
        self._pending: bool = False

    async def trigger_update(self) -> None:
        """Called whenever a transaction completes. Respects cooldown.
        If within the cooldown window, schedules a deferred update for when
        the cooldown expires so no completed transaction is silently dropped.
        """
        now = time.monotonic()
        elapsed = now - self._last_update
        if elapsed >= self.cooldown_seconds:
            await self._do_update()
        elif not self._pending:
            self._pending = True
            remaining = self.cooldown_seconds - elapsed
            asyncio.create_task(self._deferred_update(remaining))

    async def _deferred_update(self, delay: float) -> None:
        """Wait for the cooldown to expire then fire the deferred update."""
        await asyncio.sleep(delay)
        if self._pending:
            await self._do_update()

    async def _do_update(self) -> None:
        from ..db.queries.accounts import get_bank_total
        channel = self.bot.get_channel(self.channel_id)
        if channel is None:
            return
        try:
            total_cents = await get_bank_total(self.db)
            total_display = cents_to_display(total_cents)
            new_name = f"🏦 Bank Total: {total_display}"
            await channel.edit(name=new_name)
            self._last_update = time.monotonic()
            self._pending = False
            log.info("VC tracker updated: %s", new_name)
        except discord.HTTPException as exc:
            log.warning("VC tracker update failed: %s", exc)


# ─── Audit filter choices ─────────────────────────────────────────────────────

AUDIT_FILTER_CHOICES = [
    app_commands.Choice(name="All", value="all"),
    app_commands.Choice(name="By Account", value="account"),
    app_commands.Choice(name="By Server", value="server"),
    app_commands.Choice(name="By Actor", value="actor"),
]


class AdminCog(commands.Cog, name="Admin"):
    def __init__(self, bot: commands.Bot, db: "Database", config: dict) -> None:
        self.bot = bot
        self.db = db
        self.admin_role_id: int = config["ADMIN_ROLE_ID"]
        self.accounting_role_id: int = config["ACCOUNTING_ROLE_ID"]
        self.audit_channel_id: int = config["AUDIT_LOG_CHANNEL_ID"]
        self.main_guild_id: int = config["MAIN_GUILD_ID"]
        self.vc_tracker = VCTracker(
            channel_id=config["TRACKER_CHANNEL_ID"],
            cooldown_minutes=config.get("VC_COOLDOWN_MINUTES", 10),
            bot=bot,
            db=db,
        )
        self._bot_start_time = time.monotonic()

    def _require_main_guild(self, interaction: discord.Interaction) -> bool:
        """Return True if the interaction is from the main guild."""
        return interaction.guild is not None and interaction.guild.id == self.main_guild_id

    def _require_admin(self, interaction: discord.Interaction) -> bool:
        return self._require_main_guild(interaction) and is_admin(interaction.user, self.admin_role_id)

    def _admin_denied_reason(self, interaction: discord.Interaction) -> str:
        """Return the appropriate denial reason."""
        if not self._require_main_guild(interaction):
            return "Admin commands can only be used in the main server."
        return "Admins only."

    # ── /admin group ──────────────────────────────────────────────────────────

    admin_group = app_commands.Group(
        name="admin",
        description="[Admin] Administrative commands.",
        default_permissions=discord.Permissions(administrator=True),
    )

    # ── /admin freeze ─────────────────────────────────────────────────────────

    @admin_group.command(name="freeze", description="[Admin] Freeze an account.")
    @app_commands.describe(account_id="Account ID to freeze (5-digit number)")
    async def admin_freeze(self, interaction: discord.Interaction, account_id: str) -> None:
        await interaction.response.defer(ephemeral=True)
        if not self._require_admin(interaction):
            await interaction.followup.send(embed=E.error("Permission Denied", self._admin_denied_reason(interaction)), ephemeral=True)
            return
        try:
            acc = await freeze_account(self.db, int(account_id))
        except ValueError as exc:
            await interaction.followup.send(embed=E.error("Error", str(exc)), ephemeral=True)
            return

        acc_id_display = format_account_id(acc["account_id"])
        server_id, server_name = get_origin_context(interaction)
        audit_channel = self.bot.get_channel(self.audit_channel_id)
        send_fn = audit_channel.send if audit_channel else None
        await log_action(
            db=self.db,
            actor_id=interaction.user.id,
            action="freeze",
            details=f"Account {acc['account_name']} ({acc_id_display}) frozen by {interaction.user}.",
            origin_server_id=server_id,
            origin_server_name=server_name,
            target_account_id=acc["account_id"],
            send_fn=send_fn,
            embed=E.audit_log_entry(
                action="freeze",
                actor_mention=interaction.user.mention,
                target_account=f"{acc['account_name']} ({acc_id_display})",
                details="Account frozen.",
                origin_server=server_name,
            ),
        )
        await interaction.followup.send(
            embed=E.freeze_confirmation(acc["account_name"], acc_id_display, frozen=True),
            ephemeral=True,
        )

    # ── /admin unfreeze ───────────────────────────────────────────────────────

    @admin_group.command(name="unfreeze", description="[Admin] Unfreeze an account.")
    @app_commands.describe(account_id="Account ID to unfreeze")
    async def admin_unfreeze(self, interaction: discord.Interaction, account_id: str) -> None:
        await interaction.response.defer(ephemeral=True)
        if not self._require_admin(interaction):
            await interaction.followup.send(embed=E.error("Permission Denied", self._admin_denied_reason(interaction)), ephemeral=True)
            return
        try:
            acc = await unfreeze_account(self.db, int(account_id))
        except ValueError as exc:
            await interaction.followup.send(embed=E.error("Error", str(exc)), ephemeral=True)
            return

        acc_id_display = format_account_id(acc["account_id"])
        server_id, server_name = get_origin_context(interaction)
        audit_channel = self.bot.get_channel(self.audit_channel_id)
        send_fn = audit_channel.send if audit_channel else None
        await log_action(
            db=self.db,
            actor_id=interaction.user.id,
            action="unfreeze",
            details=f"Account {acc['account_name']} ({acc_id_display}) unfrozen.",
            origin_server_id=server_id,
            origin_server_name=server_name,
            target_account_id=acc["account_id"],
            send_fn=send_fn,
            embed=E.audit_log_entry(
                action="unfreeze",
                actor_mention=interaction.user.mention,
                target_account=f"{acc['account_name']} ({acc_id_display})",
                details="Account unfrozen.",
                origin_server=server_name,
            ),
        )
        await interaction.followup.send(
            embed=E.freeze_confirmation(acc["account_name"], acc_id_display, frozen=False),
            ephemeral=True,
        )

    # ── /admin adjust ─────────────────────────────────────────────────────────

    @admin_group.command(name="adjust", description="[Admin] Manually adjust an account balance.")
    @app_commands.describe(
        account_id="Account ID",
        amount="Adjustment amount (e.g. 50.00 or -25.00)",
        note="Reason for adjustment",
    )
    async def admin_adjust(
        self,
        interaction: discord.Interaction,
        account_id: str,
        amount: str,
        note: str,
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        if not self._require_admin(interaction):
            await interaction.followup.send(embed=E.error("Permission Denied", self._admin_denied_reason(interaction)), ephemeral=True)
            return

        # Parse amount — allow negative
        raw = amount.strip().lstrip("$")
        negative = raw.startswith("-")
        raw_abs = raw.lstrip("-")
        delta_cents, err = parse_amount_to_cents(raw_abs)
        if err:
            await interaction.followup.send(embed=E.error("Invalid Amount", err), ephemeral=True)
            return
        if negative:
            delta_cents = -delta_cents

        try:
            acc = await admin_adjust_balance(self.db, int(account_id), delta_cents, note)
        except ValueError as exc:
            await interaction.followup.send(embed=E.error("Error", str(exc)), ephemeral=True)
            return

        acc_id_display = format_account_id(acc["account_id"])
        delta_display = ("+" if delta_cents >= 0 else "") + cents_to_display(delta_cents)
        new_bal_display = cents_to_display(acc["balance"])

        server_id, server_name = get_origin_context(interaction)
        audit_channel = self.bot.get_channel(self.audit_channel_id)
        send_fn = audit_channel.send if audit_channel else None
        await log_action(
            db=self.db,
            actor_id=interaction.user.id,
            action="adjust",
            details=f"Balance adjustment of {delta_display} on account {acc_id_display}. Note: {note}",
            origin_server_id=server_id,
            origin_server_name=server_name,
            target_account_id=acc["account_id"],
            send_fn=send_fn,
            embed=E.audit_log_entry(
                action="adjust",
                actor_mention=interaction.user.mention,
                target_account=f"{acc['account_name']} ({acc_id_display})",
                details=f"Balance adjusted by {delta_display}. New balance: {new_bal_display}. Note: {note}",
                origin_server=server_name,
            ),
        )

        await interaction.followup.send(
            embed=E.adjust_confirmation(acc["account_name"], acc_id_display, delta_display, new_bal_display, note),
            ephemeral=True,
        )

        # Trigger VC update
        await self.vc_tracker.trigger_update()

    # ── /admin status ─────────────────────────────────────────────────────────

    @admin_group.command(name="status", description="[Admin] View bank status summary.")
    async def admin_status(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        if not self._require_admin(interaction):
            await interaction.followup.send(embed=E.error("Permission Denied", self._admin_denied_reason(interaction)), ephemeral=True)
            return

        stats = await get_bank_stats(self.db)
        configs = await get_all_configs(self.db)

        interest_rows = []
        for cfg in configs:
            interest_rows.append({
                "account_type": cfg["account_type"],
                "rate_display": cfg["rate_display"],
                "is_paused": cfg.get("is_paused", False),
                "last_applied_display": format_timestamp(cfg.get("last_applied")),
            })

        uptime_secs = int(time.monotonic() - self._bot_start_time)
        hours, rem = divmod(uptime_secs, 3600)
        minutes, seconds = divmod(rem, 60)
        uptime_str = f"{hours}h {minutes}m {seconds}s"

        await interaction.followup.send(
            embed=E.admin_status(
                total_accounts=stats["total_accounts"],
                bank_total_display=cents_to_display(stats["bank_total_cents"]),
                pending_deposits=stats["pending_deposits"],
                pending_withdrawals=stats["pending_withdrawals"],
                frozen_accounts=stats["frozen_accounts"],
                interest_rows=interest_rows,
                uptime=uptime_str,
            ),
            ephemeral=True,
        )

    # ── /admin audit ──────────────────────────────────────────────────────────

    @admin_group.command(name="audit", description="[Admin] Browse the audit log.")
    @app_commands.describe(
        filter="Filter type",
        value="Filter value (account ID, server ID/'dm', or @mention)",
    )
    @app_commands.choices(filter=AUDIT_FILTER_CHOICES)
    async def admin_audit(
        self,
        interaction: discord.Interaction,
        filter: str = "all",
        value: Optional[str] = None,
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        if not self._require_admin(interaction):
            await interaction.followup.send(embed=E.error("Permission Denied", self._admin_denied_reason(interaction)), ephemeral=True)
            return

        # Parse filter
        actor_id = None
        target_account_id = None
        origin_server_id = None

        if filter == "account" and value:
            try:
                target_account_id = int(value.strip())
            except ValueError:
                await interaction.followup.send(embed=E.error("Invalid Filter", "Account ID must be numeric."), ephemeral=True)
                return
        elif filter == "server" and value:
            origin_server_id = value.strip()
        elif filter == "actor" and value:
            # Strip mention formatting
            cleaned = value.strip().lstrip("<@!").rstrip(">")
            try:
                actor_id = int(cleaned)
            except ValueError:
                await interaction.followup.send(embed=E.error("Invalid Filter", "Could not parse actor ID."), ephemeral=True)
                return

        rows, total, total_pages = await get_paginated_audit(
            self.db,
            page=0,
            actor_id=actor_id,
            target_account_id=target_account_id,
            origin_server_id=origin_server_id,
        )

        embed = self._build_audit_embed(rows, total, page=0, total_pages=total_pages, filter=filter, value=value)

        if total_pages > 1:
            view = AuditPaginationView(
                db=self.db,
                cog=self,
                total_pages=total_pages,
                actor_id=actor_id,
                target_account_id=target_account_id,
                origin_server_id=origin_server_id,
                filter=filter,
                value=value,
            )
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)
        else:
            await interaction.followup.send(embed=embed, ephemeral=True)

    def _build_audit_embed(
        self,
        rows: list,
        total: int,
        page: int,
        total_pages: int,
        filter: str = "all",
        value: Optional[str] = None,
    ) -> discord.Embed:
        embed = E.info(f"Audit Log — {total} entries")
        filter_desc = f"Filter: **{filter.capitalize()}**"
        if value:
            filter_desc += f" = `{value}`"
        embed.description = filter_desc
        embed.set_footer(text=f"Sølyra Central Bank | Page {page + 1}/{total_pages}")

        if not rows:
            embed.description += "\n\nNo entries found."
            return embed

        lines = []
        for row in rows:
            ts = format_timestamp(row["timestamp"])
            actor = f"<@{row['actor_id']}>"
            account = f"`{format_account_id(row['target_account_id'])}`" if row["target_account_id"] else "—"
            server = row["origin_server_name"] or "Direct Message"
            lines.append(
                f"**{row['action'].replace('_', ' ').title()}** | {actor} | Acct: {account} | {server}\n"
                f"{row['details'][:100]}{'...' if len(row['details']) > 100 else ''}\n{ts}"
            )
        embed.description += "\n\n" + "\n\n".join(lines)
        return embed

    # ── /admin interest subgroup ───────────────────────────────────────────────

    interest_group = app_commands.Group(
        name="interest",
        description="[Admin] Manage the interest scheduler.",
        default_permissions=discord.Permissions(administrator=True),
    )
    admin_group.add_command(interest_group)

    @interest_group.command(name="pause", description="[Admin] Globally pause the interest scheduler.")
    async def interest_pause(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        if not self._require_admin(interaction):
            await interaction.followup.send(embed=E.error("Permission Denied", self._admin_denied_reason(interaction)), ephemeral=True)
            return
        await pause_all(self.db)
        server_id, server_name = get_origin_context(interaction)
        audit_channel = self.bot.get_channel(self.audit_channel_id)
        send_fn = audit_channel.send if audit_channel else None
        await log_action(
            db=self.db,
            actor_id=interaction.user.id,
            action="config_change",
            details="Interest scheduler globally paused.",
            origin_server_id=server_id,
            origin_server_name=server_name,
            send_fn=send_fn,
            embed=E.audit_log_entry(
                action="interest_paused",
                actor_mention=interaction.user.mention,
                target_account=None,
                details="Interest scheduler globally paused.",
                origin_server=server_name,
            ),
        )
        await interaction.followup.send(embed=E.warning("Interest Paused", "The interest scheduler has been globally paused."), ephemeral=True)

    @interest_group.command(name="resume", description="[Admin] Globally resume the interest scheduler.")
    async def interest_resume(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        if not self._require_admin(interaction):
            await interaction.followup.send(embed=E.error("Permission Denied", self._admin_denied_reason(interaction)), ephemeral=True)
            return
        await resume_all(self.db)
        server_id, server_name = get_origin_context(interaction)
        audit_channel = self.bot.get_channel(self.audit_channel_id)
        send_fn = audit_channel.send if audit_channel else None
        await log_action(
            db=self.db,
            actor_id=interaction.user.id,
            action="config_change",
            details="Interest scheduler globally resumed.",
            origin_server_id=server_id,
            origin_server_name=server_name,
            send_fn=send_fn,
            embed=E.audit_log_entry(
                action="interest_resumed",
                actor_mention=interaction.user.mention,
                target_account=None,
                details="Interest scheduler globally resumed.",
                origin_server=server_name,
            ),
        )
        await interaction.followup.send(embed=E.success("Interest Resumed", "The interest scheduler has been globally resumed."), ephemeral=True)

    @interest_group.command(name="forceapply", description="[Admin] Force-apply interest for an account type immediately.")
    @app_commands.describe(account_type="Account type to apply interest to")
    async def interest_forceapply(self, interaction: discord.Interaction, account_type: str) -> None:
        await interaction.response.defer(ephemeral=True)
        if not self._require_admin(interaction):
            await interaction.followup.send(embed=E.error("Permission Denied", self._admin_denied_reason(interaction)), ephemeral=True)
            return

        try:
            preview = await preview_interest_run(self.db, account_type)
        except ValueError as exc:
            await interaction.followup.send(embed=E.error("Error", str(exc)), ephemeral=True)
            return

        from .accounts import InterestConfirmView
        confirm_embed = E.interest_confirmation(
            account_type=preview["account_type"],
            rate_display=preview["rate_display"],
            eligible_count=preview["eligible_count"],
            estimated_total_display=preview["estimated_total_display"],
            estimated_remainder_display=preview["estimated_remainder_display"],
        )
        confirm_embed.title = "⚠️ Force Apply Interest — Confirm"

        # Reuse the accounts cog's confirm view
        accounts_cog = self.bot.cogs.get("Accounts")
        if accounts_cog:
            from .accounts import InterestConfirmView
            view = InterestConfirmView(account_type, accounts_cog, interaction.user)
            await interaction.followup.send(embed=confirm_embed, view=view, ephemeral=True)
        else:
            await interaction.followup.send(embed=E.error("Error", "Accounts cog not loaded."), ephemeral=True)

    # ── /admin shutdown ───────────────────────────────────────────────────────
    # Set ENABLE_SHUTDOWN = True in config.py to enable this command.
    # Set to False (or omit) to disable it for production.

    @admin_group.command(name="shutdown", description="[Admin] Shut down the bot. Testing only.")
    async def admin_shutdown(self, interaction: discord.Interaction) -> None:
        if not self.bot.config.get("ENABLE_SHUTDOWN", False):
            await interaction.response.send_message(
                embed=E.error("Unavailable", "The shutdown command is not enabled."),
                ephemeral=True,
            )
            return
        if not self._require_admin(interaction):
            await interaction.response.send_message(
                embed=E.error("Permission Denied", self._admin_denied_reason(interaction)),
                ephemeral=True,
            )
            return
        await interaction.response.send_message(
            embed=E.warning("Shutting Down", "The bot is going offline."),
            ephemeral=True,
        )
        log.info("Shutdown command issued by %s (%s)", interaction.user, interaction.user.id)
        await self.bot.close()

    # ── /admin report ─────────────────────────────────────────────────────────

    @admin_group.command(name="report", description="[Admin] Generate a CSV report of all accounts.")
    async def admin_report(self, interaction: discord.Interaction) -> None:
        if not self._require_admin(interaction):
            await interaction.response.send_message(
                embed=E.error("Permission Denied", self._admin_denied_reason(interaction)),
                ephemeral=True,
            )
            return
        await interaction.response.defer(ephemeral=True)

        import csv
        import io
        from datetime import datetime, timezone
        from ..db.queries.accounts import get_all_accounts_for_report
        from ..utils.formatting import cents_to_display, format_account_id

        rows = await get_all_accounts_for_report(self.db)

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "Account ID",
            "Account Name",
            "Account Type",
            "Status",
            "Balance",
            "Reserved",
            "Available",
            "Owner Discord ID",
            "Owner Username",
            "Authorized Users",
            "Created At",
        ])

        for entry in rows:
            acc = entry["account"]
            auth_ids = entry["authorized_user_ids"]

            # Resolve owner username
            try:
                owner = await self.bot.fetch_user(acc["owner_id"])
                owner_name = str(owner)
            except Exception:
                owner_name = str(acc["owner_id"])

            # Resolve authorized user usernames
            auth_names = []
            for uid in auth_ids:
                try:
                    u = await self.bot.fetch_user(uid)
                    auth_names.append(str(u))
                except Exception:
                    auth_names.append(str(uid))

            available = acc["balance"] - acc["reserved_cents"]
            writer.writerow([
                format_account_id(acc["account_id"]),
                acc["account_name"],
                acc["account_type"],
                "Frozen" if acc["is_frozen"] else "Active",
                cents_to_display(acc["balance"]),
                cents_to_display(acc["reserved_cents"]),
                cents_to_display(available),
                acc["owner_id"],
                owner_name,
                ", ".join(auth_names) if auth_names else "",
                acc["created_at"],
            ])

        output.seek(0)
        now = datetime.now(timezone.utc)
        unix = int(now.timestamp())
        filename = f"solyra_report_{now.strftime('%Y-%m-%d')}.csv"
        file = discord.File(fp=io.BytesIO(output.getvalue().encode()), filename=filename)

        # Ephemeral response to admin
        await interaction.followup.send(
            embed=E.success("Report Generated", f"Account report generated at <t:{unix}:F>."),
            file=file,
            ephemeral=True,
        )

        # Audit channel post
        audit_channel = self.bot.get_channel(self.audit_channel_id)
        if audit_channel:
            file2 = discord.File(fp=io.BytesIO(output.getvalue().encode()), filename=filename)
            await audit_channel.send(
                embed=E.info("Report Generated", f"Account report generated by {interaction.user.mention} at <t:{unix}:F>."),
                file=file2,
            )

        log.info("Report generated by %s (%s)", interaction.user, interaction.user.id)


class AuditPaginationView(discord.ui.View):
    def __init__(self, db, cog: AdminCog, total_pages: int, actor_id, target_account_id, origin_server_id, filter, value) -> None:
        super().__init__(timeout=120)
        self.db = db
        self.cog = cog
        self.total_pages = total_pages
        self.actor_id = actor_id
        self.target_account_id = target_account_id
        self.origin_server_id = origin_server_id
        self.filter = filter
        self.value = value
        self.current_page = 0
        self._update_buttons()

    def _update_buttons(self) -> None:
        self.prev_btn.disabled = self.current_page == 0
        self.next_btn.disabled = self.current_page >= self.total_pages - 1

    @discord.ui.button(label="◀ Previous", style=discord.ButtonStyle.secondary)
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_admin(interaction.user, self.cog.admin_role_id):
            await interaction.response.send_message(embed=E.error("Permission Denied", "Admins only."), ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        self.current_page = max(0, self.current_page - 1)
        self._update_buttons()
        rows, total, _ = await get_paginated_audit(
            self.db, page=self.current_page,
            actor_id=self.actor_id,
            target_account_id=self.target_account_id,
            origin_server_id=self.origin_server_id,
        )
        embed = self.cog._build_audit_embed(rows, total, self.current_page, self.total_pages, self.filter, self.value)
        await interaction.edit_original_response(embed=embed, view=self)

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.secondary)
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_admin(interaction.user, self.cog.admin_role_id):
            await interaction.response.send_message(embed=E.error("Permission Denied", "Admins only."), ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        self.current_page = min(self.total_pages - 1, self.current_page + 1)
        self._update_buttons()
        rows, total, _ = await get_paginated_audit(
            self.db, page=self.current_page,
            actor_id=self.actor_id,
            target_account_id=self.target_account_id,
            origin_server_id=self.origin_server_id,
        )
        embed = self.cog._build_audit_embed(rows, total, self.current_page, self.total_pages, self.filter, self.value)
        await interaction.edit_original_response(embed=embed, view=self)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AdminCog(bot, bot.db, bot.config))