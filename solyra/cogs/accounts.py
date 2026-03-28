"""
cogs/accounts.py
----------------
/account subcommands: create, addUser, removeUser, close, interest (view/set/apply).
"""

from __future__ import annotations
import logging
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from ..services.account_service import (
    create_account,
    close_account,
    add_user_to_account,
    remove_user_from_account,
    get_account_or_raise,
    assert_user_can_access,
)
from ..services.interest_service import (
    set_interest_rate,
    get_all_configs,
    preview_interest_run,
    apply_interest,
)
from ..services.audit_service import log_action
from ..utils.formatting import (
    cents_to_display,
    format_account_id,
    utcnow,
    format_timestamp,
    basis_points_to_percent,
)
from ..utils.validators import validate_in_game_name
from ..utils.permissions import is_admin, is_main_guild, get_origin_context
from ..utils import embeds as E

if TYPE_CHECKING:
    from ..db.database import Database

log = logging.getLogger(__name__)


class InterestConfirmView(discord.ui.View):
    """Confirmation view for interest application."""

    def __init__(self, account_type: str, cog: "AccountsCog", applied_by: discord.Member) -> None:
        super().__init__(timeout=120)
        self.account_type = account_type
        self.cog = cog
        self.applied_by = applied_by

    @discord.ui.button(label="✅ Confirm Apply", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        if not is_admin(interaction.user, self.cog.admin_role_id):
            await interaction.followup.send(embed=E.error("Permission Denied", "Only Admins can apply interest."), ephemeral=True)
            return
        self.stop()
        for item in self.children:
            item.disabled = True
        await interaction.message.edit(view=self)
        await self.cog.do_apply_interest(interaction, self.account_type)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_admin(interaction.user, self.cog.admin_role_id):
            await interaction.response.send_message(embed=E.error("Permission Denied", "Only Admins can dismiss this."), ephemeral=True)
            return
        self.stop()
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(
            embed=E.info("Cancelled", "Interest application cancelled."),
            view=self,
        )


class AccountsCog(commands.Cog, name="Accounts"):
    def __init__(self, bot: commands.Bot, db: "Database", config: dict) -> None:
        self.bot = bot
        self.db = db
        self.admin_role_id: int = config["ADMIN_ROLE_ID"]
        self.audit_channel_id: int = config["AUDIT_LOG_CHANNEL_ID"]

    # ── Account autocomplete ──────────────────────────────────────────────────

    async def owned_account_autocomplete(
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
            if row["owner_id"] != interaction.user.id:
                continue  # Only owned accounts for management commands
            label = f"{row['account_name']}"
            value = str(row["account_id"])
            if current.lower() in label.lower() or current in value:
                choices.append(app_commands.Choice(name=label[:100], value=value))
        return choices[:25]

    async def account_type_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        configs = await get_all_configs(self.db)
        return [
            app_commands.Choice(name=c["account_type"].capitalize(), value=c["account_type"])
            for c in configs
            if current.lower() in c["account_type"].lower()
        ][:25]

    # ── /account group ────────────────────────────────────────────────────────

    account_group = app_commands.Group(name="account", description="Account management commands.")

    @account_group.command(name="create", description="Create a new bank account.")
    @app_commands.describe(in_game_name="Your Minecraft in-game username")
    async def account_create(self, interaction: discord.Interaction, in_game_name: str) -> None:
        await interaction.response.defer(ephemeral=True)

        valid, err = validate_in_game_name(in_game_name)
        if not valid:
            await interaction.followup.send(embed=E.error("Invalid Name", err), ephemeral=True)
            return

        try:
            acc = await create_account(self.db, in_game_name, interaction.user.id)
        except Exception as exc:
            await interaction.followup.send(embed=E.error("Error", str(exc)), ephemeral=True)
            return

        acc_id_display = format_account_id(acc["account_id"])
        server_id, server_name = get_origin_context(interaction)
        await log_action(
            db=self.db,
            actor_id=interaction.user.id,
            action="account_create",
            details=f"Account {acc['account_name']} ({acc_id_display}) created.",
            origin_server_id=server_id,
            origin_server_name=server_name,
            target_account_id=acc["account_id"],
        )

        embed = E.success("Account Created", f"Your account has been created successfully.")
        embed.add_field(name="Account Name", value=acc["account_name"], inline=True)
        embed.add_field(name="Account ID", value=f"`{acc_id_display}`", inline=True)
        embed.add_field(name="Starting Balance", value="$0.00", inline=True)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @account_group.command(name="adduser", description="Add an authorized user to your account.")
    @app_commands.describe(
        account="Your account",
        member="Discord member to add",
    )
    @app_commands.autocomplete(account=owned_account_autocomplete)
    async def account_add_user(
        self,
        interaction: discord.Interaction,
        account: str,
        member: discord.Member,
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        try:
            account_id = int(account)
            acc = await add_user_to_account(self.db, account_id, interaction.user.id, member.id)
        except ValueError as exc:
            await interaction.followup.send(embed=E.error("Error", str(exc)), ephemeral=True)
            return

        acc_id_display = format_account_id(acc["account_id"])

        # DM the added user
        try:
            await member.send(embed=E.user_added_dm(acc["account_name"], acc_id_display, interaction.user))
        except Exception:
            pass

        server_id, server_name = get_origin_context(interaction)
        await log_action(
            db=self.db,
            actor_id=interaction.user.id,
            action="account_add_user",
            details=f"User {member} ({member.id}) added to account {acc_id_display}.",
            origin_server_id=server_id,
            origin_server_name=server_name,
            target_account_id=acc["account_id"],
        )

        await interaction.followup.send(
            embed=E.success("User Added", f"{member.mention} has been added to account `{acc_id_display}`."),
            ephemeral=True,
        )

    @account_group.command(name="removeuser", description="Remove an authorized user from your account.")
    @app_commands.describe(
        account="Your account",
        member="Discord member to remove",
    )
    @app_commands.autocomplete(account=owned_account_autocomplete)
    async def account_remove_user(
        self,
        interaction: discord.Interaction,
        account: str,
        member: discord.Member,
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        try:
            account_id = int(account)
            acc = await remove_user_from_account(self.db, account_id, interaction.user.id, member.id)
        except ValueError as exc:
            await interaction.followup.send(embed=E.error("Error", str(exc)), ephemeral=True)
            return

        acc_id_display = format_account_id(acc["account_id"])

        # DM the removed user
        try:
            await member.send(embed=E.user_removed_dm(acc["account_name"], acc_id_display, interaction.user))
        except Exception:
            pass

        server_id, server_name = get_origin_context(interaction)
        await log_action(
            db=self.db,
            actor_id=interaction.user.id,
            action="account_remove_user",
            details=f"User {member} ({member.id}) removed from account {acc_id_display}.",
            origin_server_id=server_id,
            origin_server_name=server_name,
            target_account_id=acc["account_id"],
        )

        await interaction.followup.send(
            embed=E.success("User Removed", f"{member.mention} has been removed from account `{acc_id_display}`."),
            ephemeral=True,
        )

    @account_group.command(name="close", description="Close one of your accounts.")
    @app_commands.describe(account="Account to close")
    @app_commands.autocomplete(account=owned_account_autocomplete)
    async def account_close(self, interaction: discord.Interaction, account: str) -> None:
        await interaction.response.defer(ephemeral=True)
        try:
            account_id = int(account)
            acc, auth_ids = await close_account(self.db, account_id, interaction.user.id)
        except ValueError as exc:
            await interaction.followup.send(embed=E.error("Error", str(exc)), ephemeral=True)
            return

        acc_id_display = format_account_id(acc["account_id"])

        # DM owner and all authorized users
        all_ids = [acc["owner_id"]] + auth_ids
        for uid in set(all_ids):
            try:
                user = await self.bot.fetch_user(uid)
                await user.send(embed=E.account_closed_dm(acc["account_name"], acc_id_display))
            except Exception:
                pass

        server_id, server_name = get_origin_context(interaction)
        await log_action(
            db=self.db,
            actor_id=interaction.user.id,
            action="account_close",
            details=f"Account {acc['account_name']} ({acc_id_display}) closed.",
            origin_server_id=server_id,
            origin_server_name=server_name,
            target_account_id=account_id,
        )

        await interaction.followup.send(
            embed=E.success("Account Closed", f"Account `{acc_id_display}` has been closed."),
            ephemeral=True,
        )

    # ── /account interest subgroup ────────────────────────────────────────────

    interest_group = app_commands.Group(
        name="interest",
        description="[Admin] Manage interest rates.",
        default_permissions=discord.Permissions(administrator=True),
    )
    account_group.add_command(interest_group)

    @interest_group.command(name="view", description="[Admin] View all interest rate configurations.")
    async def interest_view(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        if not is_main_guild(interaction, self.bot.config["MAIN_GUILD_ID"]) or not is_admin(interaction.user, self.admin_role_id):
            reason = "Admin commands can only be used in the main server." if not is_main_guild(interaction, self.bot.config["MAIN_GUILD_ID"]) else "Admins only."
            await interaction.followup.send(embed=E.error("Permission Denied", reason), ephemeral=True)
            return

        configs = await get_all_configs(self.db)
        if not configs:
            await interaction.followup.send(embed=E.info("Interest Config", "No account types configured yet."), ephemeral=True)
            return

        embed = E.info("Interest Rate Configuration")
        for cfg in configs:
            status = "⏸ Paused" if cfg.get("is_paused") else "▶ Active"
            last = format_timestamp(cfg.get("last_applied"))
            remainder = cents_to_display(cfg.get("remainder_cents", 0))
            embed.add_field(
                name=cfg["account_type"].capitalize(),
                value=f"Rate: **{cfg['rate_display']}** | {status}\nLast Applied: {last}\nCarry Remainder: {remainder}",
                inline=False,
            )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @interest_group.command(name="set", description="[Admin] Set the interest rate for an account type.")
    @app_commands.describe(
        account_type="Account type to configure",
        rate="Interest rate as a percentage (e.g. 2.00 for 2.00%). Note: UTC schedule applies.",
    )
    @app_commands.autocomplete(account_type=account_type_autocomplete)
    async def interest_set(
        self,
        interaction: discord.Interaction,
        account_type: str,
        rate: str,
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        if not is_main_guild(interaction, self.bot.config["MAIN_GUILD_ID"]) or not is_admin(interaction.user, self.admin_role_id):
            reason = "Admin commands can only be used in the main server." if not is_main_guild(interaction, self.bot.config["MAIN_GUILD_ID"]) else "Admins only."
            await interaction.followup.send(embed=E.error("Permission Denied", reason), ephemeral=True)
            return

        try:
            config = await set_interest_rate(self.db, account_type, rate, interaction.user.id)
        except ValueError as exc:
            await interaction.followup.send(embed=E.error("Error", str(exc)), ephemeral=True)
            return

        rate_display = basis_points_to_percent(config["rate_basis_points"])
        server_id, server_name = get_origin_context(interaction)
        audit_channel = self.bot.get_channel(self.audit_channel_id)
        send_fn = audit_channel.send if audit_channel else None
        await log_action(
            db=self.db,
            actor_id=interaction.user.id,
            action="config_change",
            details=f"Interest rate for '{account_type}' set to {rate_display} by {interaction.user}.",
            origin_server_id=server_id,
            origin_server_name=server_name,
            send_fn=send_fn,
            embed=E.audit_log_entry(
                action="config_change",
                actor_mention=interaction.user.mention,
                target_account=None,
                details=f"Interest rate for `{account_type}` set to **{rate_display}**.",
                origin_server=server_name,
            ),
        )

        await interaction.followup.send(
            embed=E.success("Rate Updated", f"Interest rate for `{account_type}` set to **{rate_display}**."),
            ephemeral=True,
        )

    @interest_group.command(name="apply", description="[Admin] Manually apply interest for an account type.")
    @app_commands.describe(account_type="Account type to apply interest to")
    @app_commands.autocomplete(account_type=account_type_autocomplete)
    async def interest_apply(
        self,
        interaction: discord.Interaction,
        account_type: str,
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        if not is_main_guild(interaction, self.bot.config["MAIN_GUILD_ID"]) or not is_admin(interaction.user, self.admin_role_id):
            reason = "Admin commands can only be used in the main server." if not is_main_guild(interaction, self.bot.config["MAIN_GUILD_ID"]) else "Admins only."
            await interaction.followup.send(embed=E.error("Permission Denied", reason), ephemeral=True)
            return

        try:
            preview = await preview_interest_run(self.db, account_type)
        except ValueError as exc:
            await interaction.followup.send(embed=E.error("Error", str(exc)), ephemeral=True)
            return

        confirm_embed = E.interest_confirmation(
            account_type=preview["account_type"],
            rate_display=preview["rate_display"],
            eligible_count=preview["eligible_count"],
            estimated_total_display=preview["estimated_total_display"],
            estimated_remainder_display=preview["estimated_remainder_display"],
        )
        view = InterestConfirmView(account_type, self, interaction.user)
        await interaction.followup.send(embed=confirm_embed, view=view, ephemeral=True)

    async def do_apply_interest(self, interaction: discord.Interaction, account_type: str) -> None:
        """Called after admin confirms interest application."""
        try:
            result = await apply_interest(self.db, account_type, interaction.user.id)
        except ValueError as exc:
            await interaction.followup.send(embed=E.error("Error", str(exc)), ephemeral=True)
            return

        server_id, server_name = get_origin_context(interaction)
        audit_channel = self.bot.get_channel(self.audit_channel_id)
        send_fn = audit_channel.send if audit_channel else None
        await log_action(
            db=self.db,
            actor_id=interaction.user.id,
            action="interest_apply",
            details=(
                f"Interest applied to {result['applied_count']} accounts of type '{account_type}'. "
                f"Total: {result['total_applied_display']}. "
                f"Remainder to house: {result['remainder_display']}."
            ),
            origin_server_id=server_id,
            origin_server_name=server_name,
            send_fn=send_fn,
            embed=E.audit_log_entry(
                action="interest_apply",
                actor_mention=interaction.user.mention,
                target_account=None,
                details=(
                    f"Interest applied to **{result['applied_count']}** `{account_type}` accounts. "
                    f"Total: **{result['total_applied_display']}**. "
                    f"Remainder to house: **{result['remainder_display']}**."
                ),
                origin_server=server_name,
            ),
        )

        await interaction.followup.send(
            embed=E.interest_applied(
                account_type=account_type,
                applied_count=result["applied_count"],
                total_applied_display=result["total_applied_display"],
                remainder_display=result["remainder_display"],
                applied_by=interaction.user,
            ),
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AccountsCog(bot, bot.db, bot.config))