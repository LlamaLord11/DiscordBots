"""
cogs/transfers.py
-----------------
/transfer, /bal, and /balHistory commands.
"""

from __future__ import annotations
import logging
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from ..services.transaction_service import (
    execute_transfer,
    get_balance_history,
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
    format_timestamp,
    utcnow,
)
from ..utils.permissions import is_admin, get_origin_context
from ..utils import embeds as E

if TYPE_CHECKING:
    from ..db.database import Database

log = logging.getLogger(__name__)

# Transaction type display labels
TX_TYPE_LABELS = {
    "deposit": "📥 Deposit",
    "withdrawal": "📤 Withdrawal",
    "transfer_in": "💸 Transfer In",
    "transfer_out": "💸 Transfer Out",
    "interest": "💰 Interest",
    "adjustment": "🔧 Adjustment",
}

STATUS_LABELS = {
    "pending": "⏳ Pending",
    "completed": "✅ Completed",
    "denied": "❌ Denied",
    "orphaned": "🚨 Orphaned",
}


class BalHistoryView(discord.ui.View):
    """Paginated view for /balHistory."""

    def __init__(
        self,
        db,
        account_id: int,
        account_name: str,
        total_pages: int,
        cog: "TransfersCog",
        current_page: int = 0,
    ) -> None:
        super().__init__(timeout=120)
        self.db = db
        self.account_id = account_id
        self.account_name = account_name
        self.total_pages = total_pages
        self.cog = cog
        self.current_page = current_page
        self._update_buttons()

    def _update_buttons(self) -> None:
        self.prev_btn.disabled = self.current_page == 0
        self.next_btn.disabled = self.current_page >= self.total_pages - 1

    @discord.ui.button(label="◀ Previous", style=discord.ButtonStyle.secondary)
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        self.current_page = max(0, self.current_page - 1)
        self._update_buttons()
        embed = await self.cog.build_history_embed(self.db, self.account_id, self.account_name, self.current_page)
        await interaction.edit_original_response(embed=embed, view=self)

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.secondary)
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        self.current_page = min(self.total_pages - 1, self.current_page + 1)
        self._update_buttons()
        embed = await self.cog.build_history_embed(self.db, self.account_id, self.account_name, self.current_page)
        await interaction.edit_original_response(embed=embed, view=self)


class TransfersCog(commands.Cog, name="Transfers"):
    def __init__(self, bot: commands.Bot, db: "Database", config: dict) -> None:
        self.bot = bot
        self.db = db
        self.admin_role_id: int = config["ADMIN_ROLE_ID"]
        self.audit_channel_id: int = config["AUDIT_LOG_CHANNEL_ID"]

    # ── Autocomplete ──────────────────────────────────────────────────────────

    async def source_account_autocomplete(
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

    async def dest_account_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        """Destination account — server-scoped, excludes user's own accounts and house."""
        if interaction.guild is None:
            return []
        from ..db.queries.accounts import get_accounts_for_user_on_server
        rows = await get_accounts_for_user_on_server(
            self.db, interaction.user.id, str(interaction.guild_id)
        )
        choices = []
        for row in rows:
            if row["account_id"] == 0:
                continue
            label = f"{row['account_name']} | ${row['balance'] / 100:.2f}"
            value = str(row["account_id"])
            if current.lower() in label.lower() or current in value:
                choices.append(app_commands.Choice(name=label[:100], value=value))
        return choices[:25]

    async def any_account_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        """All accessible accounts for the user (for /bal and /balHistory).
        Admins can see house account (00000).
        """
        from ..db.queries.accounts import get_accounts_for_user, get_account
        rows = await get_accounts_for_user(self.db, interaction.user.id)
        admin = is_admin(interaction.user, self.admin_role_id)
        choices = []
        # Admins: prepend house account since they are not its owner/authorized user
        if admin:
            house = await get_account(self.db, 0)
            if house:
                rows = [house] + list(rows)
        for row in rows:
            if row["account_id"] == 0 and not admin:
                continue
            label = f"{row['account_name']} | ${row['balance'] / 100:.2f}"
            value = str(row["account_id"])
            if current.lower() in label.lower() or current in value:
                choices.append(app_commands.Choice(name=label[:100], value=value))
        return choices[:25]

    # ── /bal ──────────────────────────────────────────────────────────────────

    @app_commands.command(name="bal", description="Check the balance of one of your accounts.")
    @app_commands.describe(account="Account to check")
    @app_commands.autocomplete(account=any_account_autocomplete)
    async def bal(self, interaction: discord.Interaction, account: str) -> None:
        await interaction.response.defer(ephemeral=True)
        try:
            account_id = int(account)
            # Hide house account from non-admins
            if account_id == 0 and not is_admin(interaction.user, self.admin_role_id):
                await interaction.followup.send(embed=E.error("Not Found", "No account found with that ID."), ephemeral=True)
                return
            acc = await get_account_or_raise(self.db, account_id)
            if not (account_id == 0 and is_admin(interaction.user, self.admin_role_id)):
                await assert_user_can_access(self.db, acc, interaction.user.id)
        except ValueError as exc:
            await interaction.followup.send(embed=E.error("Error", str(exc)), ephemeral=True)
            return

        balance_disp = cents_to_display(acc["balance"])
        available = acc["balance"] - acc["reserved_cents"]
        available_disp = cents_to_display(available)
        reserved_disp = cents_to_display(acc["reserved_cents"]) if acc["reserved_cents"] > 0 else None
        acc_id_display = format_account_id(acc["account_id"])

        await interaction.followup.send(
            embed=E.balance_display(
                account_name=acc["account_name"],
                account_id_display=acc_id_display,
                account_type=acc["account_type"],
                balance_display=balance_disp,
                available_display=available_disp,
                reserved_display=reserved_disp,
                is_frozen=bool(acc["is_frozen"]),
            ),
            ephemeral=True,
        )

    # ── /balHistory ───────────────────────────────────────────────────────────

    async def build_history_embed(
        self,
        db,
        account_id: int,
        account_name: str,
        page: int,
    ) -> discord.Embed:
        rows, total, total_pages = await get_balance_history(db, account_id, page)
        acc_id_display = format_account_id(account_id)

        if not rows:
            embed = E.info(f"Transaction History — {account_name}")
            embed.description = "No transactions found in the last 30 days."
            return embed

        embed = E.info(f"Transaction History — {account_name}")
        embed.set_footer(text=f"Sølyra Central Bank | Page {page + 1}/{total_pages} | {total} transactions")

        lines = []
        for tx in rows:
            type_label = TX_TYPE_LABELS.get(tx["type"], tx["type"].capitalize())
            status_label = STATUS_LABELS.get(tx["status"], tx["status"].capitalize())
            amount_disp = cents_to_display(tx["amount"])
            date = format_timestamp(tx["created_at"])
            lines.append(f"**{type_label}** — {amount_disp} — {status_label}\n{date}")

        embed.description = "\n\n".join(lines)
        return embed

    @app_commands.command(name="balhistory", description="View transaction history for one of your accounts.")
    @app_commands.describe(account="Account to view history for")
    @app_commands.autocomplete(account=any_account_autocomplete)
    async def bal_history(self, interaction: discord.Interaction, account: str) -> None:
        await interaction.response.defer(ephemeral=True)
        try:
            account_id = int(account)
            if account_id == 0 and not is_admin(interaction.user, self.admin_role_id):
                await interaction.followup.send(embed=E.error("Not Found", "No account found."), ephemeral=True)
                return
            acc = await get_account_or_raise(self.db, account_id)
            if not (account_id == 0 and is_admin(interaction.user, self.admin_role_id)):
                await assert_user_can_access(self.db, acc, interaction.user.id)
        except ValueError as exc:
            await interaction.followup.send(embed=E.error("Error", str(exc)), ephemeral=True)
            return

        rows, total, total_pages = await get_balance_history(self.db, account_id, page=0)

        embed = await self.build_history_embed(self.db, account_id, acc["account_name"], 0)

        if total_pages > 1:
            view = BalHistoryView(self.db, account_id, acc["account_name"], total_pages, self)
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)
        else:
            await interaction.followup.send(embed=embed, ephemeral=True)

    # ── /transfer ─────────────────────────────────────────────────────────────

    @app_commands.command(name="transfer", description="Transfer funds between accounts.")
    @app_commands.describe(
        amount="Amount to transfer (e.g. 100 or 50.00)",
        from_account="Account to transfer from",
        to_account="Account to transfer to",
    )
    @app_commands.autocomplete(from_account=source_account_autocomplete, to_account=dest_account_autocomplete)
    async def transfer(
        self,
        interaction: discord.Interaction,
        amount: str,
        from_account: str,
        to_account: str,
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        amount_cents, err = parse_amount_to_cents(amount)
        if err:
            await interaction.followup.send(embed=E.error("Invalid Amount", err), ephemeral=True)
            return

        try:
            source_id = int(from_account)
            dest_id = int(to_account)
        except ValueError:
            await interaction.followup.send(embed=E.error("Invalid Account", "Invalid account selection."), ephemeral=True)
            return

        # Validate source access
        try:
            source_acc = await get_account_or_raise(self.db, source_id)
            await assert_user_can_access(self.db, source_acc, interaction.user.id)
        except ValueError as exc:
            await interaction.followup.send(embed=E.error("Error", str(exc)), ephemeral=True)
            return

        try:
            result = await execute_transfer(self.db, source_id, dest_id, amount_cents, interaction.user.id)
        except ValueError as exc:
            await interaction.followup.send(embed=E.error("Transfer Failed", str(exc)), ephemeral=True)
            return

        amount_display = cents_to_display(amount_cents)
        src_id_display = format_account_id(source_id)
        dst_id_display = format_account_id(dest_id)
        dest_acc = result["dest_account"]
        new_dest_bal = cents_to_display(dest_acc["balance"])

        # DM dest account owner + authorized users
        dest_auth_ids = await get_authorized_ids(self.db, dest_id)
        all_dest_ids = list(set([dest_acc["owner_id"]] + dest_auth_ids))
        dm_embed = E.transfer_received_dm(
            amount_display=amount_display,
            source_account_id_display=src_id_display,
            dest_account_name=dest_acc["account_name"],
            dest_account_id_display=dst_id_display,
            new_balance_display=new_dest_bal,
        )
        for uid in all_dest_ids:
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
            action="transfer",
            details=f"Transfer of {amount_display} from account {src_id_display} to {dst_id_display}.",
            origin_server_id=server_id,
            origin_server_name=server_name,
            target_account_id=source_id,
            send_fn=send_fn,
            embed=E.audit_log_entry(
                action="transfer",
                actor_mention=interaction.user.mention,
                target_account=f"{source_acc['account_name']} ({src_id_display})",
                details=f"Transfer of {amount_display} from `{src_id_display}` → `{dst_id_display}`.",
                origin_server=server_name,
            ),
        )

        embed = E.success("Transfer Complete")
        embed.add_field(name="Amount", value=amount_display, inline=True)
        embed.add_field(name="From", value=f"`{src_id_display}`", inline=True)
        embed.add_field(name="To", value=f"`{dst_id_display}`", inline=True)
        await interaction.followup.send(embed=embed, ephemeral=True)
        # Trigger VC tracker update
        admin_cog = self.bot.cogs.get("Admin")
        if admin_cog:
            await admin_cog.vc_tracker.trigger_update()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(TransfersCog(bot, bot.db, bot.config))