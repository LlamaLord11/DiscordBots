"""
utils/permissions.py
--------------------
Role-based and account-based permission checks.
Depends only on discord.py types — no database or service imports.
"""

from __future__ import annotations
import discord
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass


def is_admin(member: discord.Member, admin_role_id: int) -> bool:
    """Return True if the member has the Admin role."""
    return any(role.id == admin_role_id for role in member.roles)


def is_accounting(member: discord.Member, accounting_role_id: int) -> bool:
    """Return True if the member has the Accounting role."""
    return any(role.id == accounting_role_id for role in member.roles)


def is_admin_or_accounting(
    member: discord.Member,
    admin_role_id: int,
    accounting_role_id: int,
) -> bool:
    """Return True if the member has either the Admin or Accounting role."""
    return is_admin(member, admin_role_id) or is_accounting(member, accounting_role_id)


def is_account_owner(user_id: int, account_row: dict) -> bool:
    """Return True if the user is the owner of the account."""
    return account_row["owner_id"] == user_id


def is_account_authorized(user_id: int, account_row: dict, authorized_user_ids: list[int]) -> bool:
    """Return True if the user owns or is authorized on the account.

    Args:
        user_id:              The Discord user ID to check.
        account_row:          The accounts table row as a dict.
        authorized_user_ids:  List of user IDs from account_users table.
    """
    if account_row["owner_id"] == user_id:
        return True
    return user_id in authorized_user_ids


def is_main_guild(interaction: discord.Interaction, main_guild_id: int) -> bool:
    """Return True if the interaction is coming from the main guild."""
    return interaction.guild is not None and interaction.guild.id == main_guild_id


def get_origin_context(interaction: discord.Interaction) -> tuple[str | None, str]:
    """Extract the origin server ID and name from an interaction.

    Returns:
        (server_id, server_name)
        server_id is None and server_name is 'Direct Message' if run in DMs.
    """
    if interaction.guild is None:
        return None, "Direct Message"
    return str(interaction.guild.id), interaction.guild.name