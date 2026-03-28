"""
cogs/deposits.py
----------------
/deposit command and deposit ticket button handlers (Approve / Deny / Close).
"""

from __future__ import annotations
import logging
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from ..services.transaction_service import (
    open_deposit_ticket,
    approve_deposit,
    deny_deposit,
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
from ..utils.validators import validate_image_attachment
from ..utils.permissions import is_admin_or_accounting, get_origin_context
from ..utils import embeds as E

if TYPE_CHECKING:
    from ..db.database import Database

log = logging.getLogger(__name__)

TICKET_BUTTON_PREFIX = "deposit_"


class DenyReasonModal(discord.ui.Modal, title="Denial Reason"):
    reason = discord.ui.TextInput(
        label="Reason",
        style=discord.TextStyle.paragraph,
        placeholder="Enter the reason for denial...",
        required=True,
        max_length=500,
    )

    def __init__(self, transaction_id: int, cog: "DepositsCog") -> None:
        super().__init__()
        self.transaction_id = transaction_id
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        await self.cog.handle_deny(interaction, self.transaction_id, self.reason.value)


class DepositTicketView(discord.ui.View):
    """Persistent view attached to deposit ticket embeds."""

    def __init__(self, transaction_id: int, cog: "DepositsCog") -> None:
        super().__init__(timeout=None)
        self.transaction_id = transaction_id
        self.cog = cog
        # Set custom_ids so views survive restarts
        self.approve_btn.custom_id = f"{TICKET_BUTTON_PREFIX}approve_{transaction_id}"
        self.deny_btn.custom_id = f"{TICKET_BUTTON_PREFIX}deny_{transaction_id}"

    @discord.ui.button(label="✅ Approve", style=discord.ButtonStyle.success)
    async def approve_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        if not is_admin_or_accounting(
            interaction.user,
            self.cog.admin_role_id,
            self.cog.accounting_role_id,
        ):
            await interaction.followup.send(embed=E.error("Permission Denied", "Only Admin or Accounting can approve deposits."), ephemeral=True)
            return
        await self.cog.handle_approve(interaction, self.transaction_id)

    @discord.ui.button(label="❌ Deny", style=discord.ButtonStyle.danger)
    async def deny_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_admin_or_accounting(
            interaction.user,
            self.cog.admin_role_id,
            self.cog.accounting_role_id,
        ):
            await interaction.response.send_message(embed=E.error("Permission Denied", "Only Admin or Accounting can deny deposits."), ephemeral=True)
            return
        await interaction.response.send_modal(DenyReasonModal(self.transaction_id, self.cog))




class DepositsCog(commands.Cog, name="Deposits"):
    def __init__(self, bot: commands.Bot, db: "Database", config: dict) -> None:
        self.bot = bot
        self.db = db
        self.admin_role_id: int = config["ADMIN_ROLE_ID"]
        self.accounting_role_id: int = config["ACCOUNTING_ROLE_ID"]
        self.ticket_category_id: int = config["TICKET_CATEGORY_ID"]
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
                continue  # Hide house account
            label = f"{row['account_name']} | ${row['balance'] / 100:.2f}"
            value = str(row["account_id"])
            if current.lower() in label.lower() or current in value:
                choices.append(app_commands.Choice(name=label[:100], value=value))
        return choices[:25]

    # ── Command ───────────────────────────────────────────────────────────────

    @app_commands.command(name="deposit", description="Submit a deposit request with proof of payment.")
    @app_commands.describe(
        amount="Amount to deposit (e.g. 100 or 50.00)",
        account="Account to deposit into",
        proof="Image proof of payment (png, jpg, jpeg, gif, webp)",
    )
    @app_commands.autocomplete(account=account_autocomplete)
    async def deposit(
        self,
        interaction: discord.Interaction,
        amount: str,
        account: str,
        proof: discord.Attachment,
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        # Validate file type
        valid, err = validate_image_attachment(proof.filename, proof.content_type)
        if not valid:
            await interaction.followup.send(embed=E.error("Invalid File", err), ephemeral=True)
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
        category = guild.get_channel(self.ticket_category_id)
        username = interaction.user.name.replace(" ", "-").lower()
        timestamp = int(utcnow().timestamp())
        channel_name = f"deposit-{username}-{timestamp}"

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
                reason=f"Deposit ticket for {interaction.user}",
            )
        except discord.HTTPException as exc:
            await interaction.followup.send(
                embed=E.error("Error", f"Could not create ticket channel: {exc}"),
                ephemeral=True,
            )
            return

        # Create pending transaction
        try:
            tx_id = await open_deposit_ticket(
                db=self.db,
                account_id=account_id,
                amount_cents=amount_cents,
                user_id=interaction.user.id,
                channel_id=str(ticket_channel.id),
            )
        except ValueError as exc:
            await ticket_channel.delete(reason="Transaction creation failed")
            await interaction.followup.send(embed=E.error("Error", str(exc)), ephemeral=True)
            return

        # Post ticket embed
        amount_display = cents_to_display(amount_cents)
        acc_id_display = format_account_id(account_id)
        ticket_embed = E.deposit_ticket(
            initiator=interaction.user,
            account_name=acc["account_name"],
            account_id_display=acc_id_display,
            amount_display=amount_display,
            transaction_id=tx_id,
        )
        ticket_embed.set_image(url=proof.url)

        view = DepositTicketView(tx_id, self)
        ping_msg = accounting_role.mention if accounting_role else "Staff"
        await ticket_channel.send(content=f"{ping_msg} — new deposit request.", embed=ticket_embed, view=view)

        # Audit log
        server_id, server_name = get_origin_context(interaction)
        audit_channel = self.bot.get_channel(self.audit_channel_id)
        send_fn = audit_channel.send if audit_channel else None
        await log_action(
            db=self.db,
            actor_id=interaction.user.id,
            action="deposit",
            details=f"Deposit of {amount_display} to account {acc_id_display} — pending.",
            origin_server_id=server_id,
            origin_server_name=server_name,
            target_account_id=account_id,
            send_fn=send_fn,
            embed=E.audit_log_entry(
                action="deposit",
                actor_mention=interaction.user.mention,
                target_account=f"{acc['account_name']} ({acc_id_display})",
                details=f"Deposit of {amount_display} — pending. Ticket: {ticket_channel.mention}",
                origin_server=server_name,
            ),
        )

        await interaction.followup.send(
            embed=E.info(
                "Deposit Submitted",
                f"Your deposit request has been received and is pending staff review. "
                f"Ticket: {ticket_channel.mention} (ID: `{ticket_channel.id}`)",
            ),
            ephemeral=True,
        )

    # ── Button Handlers ───────────────────────────────────────────────────────

    async def handle_approve(self, interaction: discord.Interaction, transaction_id: int) -> None:
        try:
            result = await approve_deposit(self.db, transaction_id, interaction.user.id)
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
        amount_display = cents_to_display(tx["amount"])
        new_bal_display = cents_to_display(result["new_balance_cents"])
        acc_id_display = format_account_id(acc["account_id"])

        # DM the initiator who ran /deposit
        dm_embed = E.deposit_approved_dm(
            account_name=acc["account_name"],
            account_id_display=acc_id_display,
            amount_display=amount_display,
            new_balance_display=new_bal_display,
            processed_by=interaction.user,
        )
        initiator_id = tx.get("initiator_id") or acc["owner_id"]
        try:
            initiator = await self.bot.fetch_user(initiator_id)
            await initiator.send(embed=dm_embed)
        except Exception:
            pass  # DM failure is non-fatal

        # Audit
        server_id, server_name = get_origin_context(interaction)
        audit_channel = self.bot.get_channel(self.audit_channel_id)
        send_fn = audit_channel.send if audit_channel else None
        await log_action(
            db=self.db,
            actor_id=interaction.user.id,
            action="deposit",
            details=f"Deposit of {amount_display} to account {acc_id_display} approved.",
            origin_server_id=server_id,
            origin_server_name=server_name,
            target_account_id=acc["account_id"],
            send_fn=send_fn,
            embed=E.audit_log_entry(
                action="deposit_approved",
                actor_mention=interaction.user.mention,
                target_account=f"{acc['account_name']} ({acc_id_display})",
                details=f"Deposit of {amount_display} approved. New balance: {new_bal_display}.",
                origin_server=server_name,
            ),
        )

        await interaction.followup.send(
            embed=E.success("Deposit Approved", f"Approved deposit of {amount_display} to account {acc_id_display}."),
            ephemeral=True,
        )
        # Trigger VC tracker update
        admin_cog = self.bot.cogs.get("Admin")
        if admin_cog:
            await admin_cog.vc_tracker.trigger_update()
        # Delete ticket channel
        try:
            await interaction.channel.delete(reason="Deposit approved.")
        except Exception:
            pass

    async def handle_deny(self, interaction: discord.Interaction, transaction_id: int, reason: str) -> None:
        try:
            result = await deny_deposit(self.db, transaction_id, interaction.user.id, reason)
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
        amount_display = cents_to_display(tx["amount"])
        acc_id_display = format_account_id(acc["account_id"])

        # DM account owner
        try:
            owner = await self.bot.fetch_user(acc["owner_id"])
            dm_embed = E.deposit_denied_dm(
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
            action="deposit",
            details=f"Deposit of {amount_display} to account {acc_id_display} denied. Reason: {reason}",
            origin_server_id=server_id,
            origin_server_name=server_name,
            target_account_id=acc["account_id"],
            send_fn=send_fn,
            embed=E.audit_log_entry(
                action="deposit_denied",
                actor_mention=interaction.user.mention,
                target_account=f"{acc['account_name']} ({acc_id_display})",
                details=f"Deposit of {amount_display} denied. Reason: {reason}",
                origin_server=server_name,
            ),
        )

        await interaction.followup.send(
            embed=E.success("Deposit Denied", "The deposit has been denied and the user notified."),
            ephemeral=True,
        )
        try:
            await interaction.channel.delete(reason="Deposit denied.")
        except Exception:
            pass

    # ── Crash recovery: re-attach views ───────────────────────────────────────

    async def reattach_views(self, pending_txs: list[dict]) -> None:
        """Re-attach DepositTicketView to existing ticket channels on startup."""
        deposit_txs = [t for t in pending_txs if t["type"] == "deposit"]
        for tx in deposit_txs:
            channel = self.bot.get_channel(int(tx["channel_id"]))
            if channel is None:
                log.warning("Deposit ticket channel %s not found for tx %s", tx["channel_id"], tx["transaction_id"])
                continue
            view = DepositTicketView(tx["transaction_id"], self)
            self.bot.add_view(view)
            log.info("Re-attached deposit view for tx %s in channel %s", tx["transaction_id"], tx["channel_id"])


async def setup(bot: commands.Bot) -> None:
    # Called by bot.load_extension — config and db are injected via bot attributes
    await bot.add_cog(DepositsCog(bot, bot.db, bot.config))