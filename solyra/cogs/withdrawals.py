"""
cogs/withdrawals.py
-------------------
/withdraw command and withdrawal ticket button handlers (Completed / Deny).
"""

from __future__ import annotations
import logging
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from ..services.transaction_service import (
    open_withdrawal_ticket,
    complete_withdrawal,
    deny_withdrawal,
)
from ..services.account_service import (
    get_account_or_raise,
    assert_user_can_access,
    assert_not_frozen,
    get_authorized_ids,
)
from ..services.audit_service import log_action
from ..utils.formatting import (
    parse_amount_to_cents,
    cents_to_display,
    format_account_id,
    utcnow,
)
from ..utils.validators import validate_in_game_name
from ..utils.permissions import is_admin_or_accounting, get_origin_context
from ..utils import embeds as E

if TYPE_CHECKING:
    from ..db.database import Database

log = logging.getLogger(__name__)

TICKET_BUTTON_PREFIX = "withdrawal_"


class WithdrawalDenyModal(discord.ui.Modal, title="Denial Reason"):
    reason = discord.ui.TextInput(
        label="Reason",
        style=discord.TextStyle.paragraph,
        placeholder="Enter the reason for denial...",
        required=True,
        max_length=500,
    )

    def __init__(self, transaction_id: int, cog: "WithdrawalsCog") -> None:
        super().__init__()
        self.transaction_id = transaction_id
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        await self.cog.handle_deny(interaction, self.transaction_id, self.reason.value)


class WithdrawalTicketView(discord.ui.View):
    """Persistent view attached to withdrawal ticket embeds."""

    def __init__(self, transaction_id: int, cog: "WithdrawalsCog") -> None:
        super().__init__(timeout=None)
        self.transaction_id = transaction_id
        self.cog = cog
        self.completed_btn.custom_id = f"{TICKET_BUTTON_PREFIX}complete_{transaction_id}"
        self.deny_btn.custom_id = f"{TICKET_BUTTON_PREFIX}deny_{transaction_id}"

    @discord.ui.button(label="✅ Completed", style=discord.ButtonStyle.success)
    async def completed_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        if not is_admin_or_accounting(
            interaction.user,
            self.cog.admin_role_id,
            self.cog.accounting_role_id,
        ):
            await interaction.followup.send(
                embed=E.error("Permission Denied", "Only Admin or Accounting can complete withdrawals."),
                ephemeral=True,
            )
            return
        await self.cog.handle_complete(interaction, self.transaction_id)

    @discord.ui.button(label="❌ Deny", style=discord.ButtonStyle.danger)
    async def deny_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_admin_or_accounting(
            interaction.user,
            self.cog.admin_role_id,
            self.cog.accounting_role_id,
        ):
            await interaction.response.send_message(
                embed=E.error("Permission Denied", "Only Admin or Accounting can deny withdrawals."),
                ephemeral=True,
            )
            return
        await interaction.response.send_modal(WithdrawalDenyModal(self.transaction_id, self.cog))


class WithdrawalsCog(commands.Cog, name="Withdrawals"):
    def __init__(self, bot: commands.Bot, db: "Database", config: dict) -> None:
        self.bot = bot
        self.db = db
        self.admin_role_id: int = config["ADMIN_ROLE_ID"]
        self.accounting_role_id: int = config["ACCOUNTING_ROLE_ID"]
        self.withdrawal_category_id: int = config["WITHDRAWAL_CATEGORY_ID"]
        self.audit_channel_id: int = config["AUDIT_LOG_CHANNEL_ID"]
        self.main_guild_id: int = config["MAIN_GUILD_ID"]

    # ── Autocomplete ──────────────────────────────────────────────────────────

    async def account_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        from ..db.queries.accounts import get_accounts_for_user
        rows = await get_accounts_for_user(self.db, interaction.user.id)
        choices = []
        for row in rows:
            if row["account_id"] == 0:
                continue
            avail = row["balance"] - row["reserved_cents"]
            label = f"{row['account_name']} | Avail: ${avail / 100:.2f}"
            value = str(row["account_id"])
            if current.lower() in label.lower() or current in value:
                choices.append(app_commands.Choice(name=label[:100], value=value))
        return choices[:25]

    # ── Command ───────────────────────────────────────────────────────────────

    @app_commands.command(name="withdraw", description="Request a withdrawal from your account.")
    @app_commands.describe(
        amount="Amount to withdraw (e.g. 100 or 50.00)",
        account="Account to withdraw from",
        in_game_name="Your Minecraft in-game username",
    )
    @app_commands.autocomplete(account=account_autocomplete)
    async def withdraw(
        self,
        interaction: discord.Interaction,
        amount: str,
        account: str,
        in_game_name: str,
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        # Validate in-game name
        valid, err = validate_in_game_name(in_game_name)
        if not valid:
            await interaction.followup.send(embed=E.error("Invalid Name", err), ephemeral=True)
            return

        # Validate amount
        amount_cents, err = parse_amount_to_cents(amount)
        if err:
            await interaction.followup.send(embed=E.error("Invalid Amount", err), ephemeral=True)
            return

        # Validate account
        try:
            account_id = int(account)
            acc = await get_account_or_raise(self.db, account_id)
            await assert_user_can_access(self.db, acc, interaction.user.id)
            await assert_not_frozen(acc)
        except ValueError as exc:
            await interaction.followup.send(embed=E.error("Error", str(exc)), ephemeral=True)
            return

        # Always create ticket in the main guild regardless of where command was run
        guild = self.bot.get_guild(self.main_guild_id)
        if guild is None:
            await interaction.followup.send(
                embed=E.error("Error", "Could not reach the main server. Please try again later."),
                ephemeral=True,
            )
            return

        # Create ticket channel
        category = guild.get_channel(self.withdrawal_category_id)
        username = interaction.user.name.replace(" ", "-").lower()
        timestamp = int(utcnow().timestamp())
        channel_name = f"withdrawal-{username}-{timestamp}"

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True),
        }
        admin_role = guild.get_role(self.admin_role_id)
        accounting_role = guild.get_role(self.accounting_role_id)
        if admin_role:
            overwrites[admin_role] = discord.PermissionOverwrite(view_channel=True, send_messages=True)
        if accounting_role:
            overwrites[accounting_role] = discord.PermissionOverwrite(view_channel=True, send_messages=True)

        try:
            ticket_channel = await guild.create_text_channel(
                name=channel_name,
                category=category,
                overwrites=overwrites,
                reason=f"Withdrawal ticket for {interaction.user}",
            )
        except discord.HTTPException as exc:
            await interaction.followup.send(
                embed=E.error("Error", f"Could not create ticket channel: {exc}"),
                ephemeral=True,
            )
            return

        # Open withdrawal (soft-locks funds)
        try:
            tx_id = await open_withdrawal_ticket(
                db=self.db,
                account_id=account_id,
                amount_cents=amount_cents,
                user_id=interaction.user.id,
                channel_id=str(ticket_channel.id),
                in_game_name=in_game_name,
            )
        except ValueError as exc:
            await ticket_channel.delete(reason="Transaction creation failed")
            await interaction.followup.send(embed=E.error("Error", str(exc)), ephemeral=True)
            return

        amount_display = cents_to_display(amount_cents)
        acc_id_display = format_account_id(account_id)

        # Post ticket embed
        ticket_embed = E.withdrawal_ticket(
            initiator=interaction.user,
            account_name=acc["account_name"],
            account_id_display=acc_id_display,
            amount_display=amount_display,
            in_game_name=in_game_name,
            transaction_id=tx_id,
        )
        view = WithdrawalTicketView(tx_id, self)
        ping_msg = accounting_role.mention if accounting_role else "Staff"
        await ticket_channel.send(content=f"{ping_msg} — new withdrawal request.", embed=ticket_embed, view=view)

        # DM initiator immediately
        try:
            dm_embed = E.withdrawal_pending_dm(
                account_name=acc["account_name"],
                account_id_display=acc_id_display,
                amount_display=amount_display,
                in_game_name=in_game_name,
            )
            await interaction.user.send(embed=dm_embed)
        except Exception:
            pass

        # Audit
        server_id, server_name = get_origin_context(interaction)
        audit_channel = self.bot.get_channel(self.audit_channel_id)
        send_fn = audit_channel.send if audit_channel else None
        await log_action(
            db=self.db,
            actor_id=interaction.user.id,
            action="withdrawal",
            details=f"Withdrawal of {amount_display} from account {acc_id_display} to IGN {in_game_name} — pending.",
            origin_server_id=server_id,
            origin_server_name=server_name,
            target_account_id=account_id,
            send_fn=send_fn,
            embed=E.audit_log_entry(
                action="withdrawal",
                actor_mention=interaction.user.mention,
                target_account=f"{acc['account_name']} ({acc_id_display})",
                details=f"Withdrawal of {amount_display} to IGN `{in_game_name}` — pending. Ticket: {ticket_channel.mention}",
                origin_server=server_name,
            ),
        )

        await interaction.followup.send(
            embed=E.info(
                "Withdrawal Submitted",
                f"Your withdrawal request has been received and is pending staff review. "
                f"Ticket: {ticket_channel.mention} (ID: `{ticket_channel.id}`)",
            ),
            ephemeral=True,
        )

    # ── Button Handlers ───────────────────────────────────────────────────────

    async def handle_complete(self, interaction: discord.Interaction, transaction_id: int) -> None:
        try:
            result = await complete_withdrawal(self.db, transaction_id, interaction.user.id)
        except ValueError as exc:
            msg = str(exc)
            if "already" in msg:
                await interaction.followup.send(
                    embed=E.error("Already Resolved", "This ticket has already been processed."),
                    ephemeral=True,
                )
            else:
                await interaction.followup.send(embed=E.error("Error", msg), ephemeral=True)
            return

        tx = result["transaction"]
        acc = result["account"]
        in_game_name = result["in_game_name"]
        amount_display = cents_to_display(tx["amount"])
        acc_id_display = format_account_id(acc["account_id"])

        # DM the initiator who ran /withdraw, plus owner and all authorized users
        dm_embed = E.withdrawal_completed_dm(
            account_name=acc["account_name"],
            account_id_display=acc_id_display,
            amount_display=amount_display,
            in_game_name=in_game_name,
            processed_by=interaction.user,
        )
        initiator_id = tx.get("initiator_id") or acc["owner_id"]
        auth_ids = await get_authorized_ids(self.db, acc["account_id"])
        all_notify = set([acc["owner_id"]] + auth_ids + [initiator_id])
        for uid in all_notify:
            try:
                user = await self.bot.fetch_user(uid)
                await user.send(embed=dm_embed)
            except Exception:
                pass

        # Audit
        server_id, server_name = get_origin_context(interaction)
        audit_channel = self.bot.get_channel(self.audit_channel_id)
        send_fn = audit_channel.send if audit_channel else None
        await log_action(
            db=self.db,
            actor_id=interaction.user.id,
            action="withdrawal",
            details=f"Withdrawal of {amount_display} from account {acc_id_display} completed. IGN: {in_game_name}",
            origin_server_id=server_id,
            origin_server_name=server_name,
            target_account_id=acc["account_id"],
            send_fn=send_fn,
            embed=E.audit_log_entry(
                action="withdrawal_completed",
                actor_mention=interaction.user.mention,
                target_account=f"{acc['account_name']} ({acc_id_display})",
                details=f"Withdrawal of {amount_display} completed. Paid to IGN `{in_game_name}`.",
                origin_server=server_name,
            ),
        )

        await interaction.followup.send(
            embed=E.success("Withdrawal Completed", f"Marked {amount_display} as paid to `{in_game_name}`."),
            ephemeral=True,
        )
        # Trigger VC tracker update
        admin_cog = self.bot.cogs.get("Admin")
        if admin_cog:
            await admin_cog.vc_tracker.trigger_update()
        try:
            await interaction.channel.delete(reason="Withdrawal completed.")
        except Exception:
            pass

    async def handle_deny(self, interaction: discord.Interaction, transaction_id: int, reason: str) -> None:
        try:
            result = await deny_withdrawal(self.db, transaction_id, interaction.user.id, reason)
        except ValueError as exc:
            msg = str(exc)
            if "already" in msg:
                await interaction.followup.send(
                    embed=E.error("Already Resolved", "This ticket has already been processed."),
                    ephemeral=True,
                )
            else:
                await interaction.followup.send(embed=E.error("Error", msg), ephemeral=True)
            return

        tx = result["transaction"]
        acc = result["account"]
        in_game_name = result["in_game_name"]
        amount_display = cents_to_display(tx["amount"])
        acc_id_display = format_account_id(acc["account_id"])

        # DM account owner
        try:
            owner = await self.bot.fetch_user(acc["owner_id"])
            dm_embed = E.withdrawal_denied_dm(
                account_name=acc["account_name"],
                account_id_display=acc_id_display,
                amount_display=amount_display,
                reason=reason,
                processed_by=interaction.user,
            )
            await owner.send(embed=dm_embed)
        except Exception:
            pass

        # Audit
        server_id, server_name = get_origin_context(interaction)
        audit_channel = self.bot.get_channel(self.audit_channel_id)
        send_fn = audit_channel.send if audit_channel else None
        await log_action(
            db=self.db,
            actor_id=interaction.user.id,
            action="withdrawal",
            details=f"Withdrawal of {amount_display} from account {acc_id_display} denied. Reason: {reason}",
            origin_server_id=server_id,
            origin_server_name=server_name,
            target_account_id=acc["account_id"],
            send_fn=send_fn,
            embed=E.audit_log_entry(
                action="withdrawal_denied",
                actor_mention=interaction.user.mention,
                target_account=f"{acc['account_name']} ({acc_id_display})",
                details=f"Withdrawal of {amount_display} denied. Reason: {reason}",
                origin_server=server_name,
            ),
        )

        await interaction.followup.send(
            embed=E.success("Withdrawal Denied", "The withdrawal has been denied and the user notified."),
            ephemeral=True,
        )
        try:
            await interaction.channel.delete(reason="Withdrawal denied.")
        except Exception:
            pass

    # ── Crash recovery ────────────────────────────────────────────────────────

    async def reattach_views(self, pending_txs: list[dict]) -> None:
        withdrawal_txs = [t for t in pending_txs if t["type"] == "withdrawal"]
        for tx in withdrawal_txs:
            channel = self.bot.get_channel(int(tx["channel_id"]))
            if channel is None:
                log.warning("Withdrawal channel %s not found for tx %s", tx["channel_id"], tx["transaction_id"])
                continue
            view = WithdrawalTicketView(tx["transaction_id"], self)
            self.bot.add_view(view)
            log.info("Re-attached withdrawal view for tx %s", tx["transaction_id"])


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(WithdrawalsCog(bot, bot.db, bot.config))