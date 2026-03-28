"""
utils/embeds.py
---------------
Centralised branded embed builders.
All embeds use the Sølyra Central Bank visual identity.

Colors:
    PRIMARY   #FFC42B  Gold     — standard informational
    SECONDARY #FFFDFF  Off-white — success / neutral
    ERROR     #050000  Near-black — denial / error
"""

from __future__ import annotations
import discord
from datetime import datetime, timezone
from typing import Optional

# ─── Brand Colors ─────────────────────────────────────────────────────────────
PRIMARY   = 0xFFC42B   # Gold
SECONDARY = 0xFFFDFF   # Off-white
ERROR     = 0x050000   # Near-black
WARNING   = 0xFF8C00   # Orange — used for alerts/warnings

FOOTER_TEXT = "Sølyra Central Bank"


def _base(color: int, title: str, description: str = "") -> discord.Embed:
    """Internal helper — create a base embed with footer and absolute timestamp field."""
    now = datetime.now(timezone.utc)
    unix = int(now.timestamp())
    embed = discord.Embed(
        title=title,
        description=description,
        color=color,
    )
    embed.set_footer(text=FOOTER_TEXT)
    embed.add_field(name="Time", value=f"<t:{unix}:F>", inline=False)
    return embed


# ─── Generic ──────────────────────────────────────────────────────────────────

def info(title: str, description: str = "") -> discord.Embed:
    """Gold informational embed."""
    return _base(PRIMARY, title, description)


def success(title: str, description: str = "") -> discord.Embed:
    """Off-white success embed."""
    return _base(SECONDARY, title, description)


def error(title: str, description: str = "") -> discord.Embed:
    """Near-black error embed."""
    return _base(ERROR, title, description)


def warning(title: str, description: str = "") -> discord.Embed:
    """Orange warning/alert embed."""
    return _base(WARNING, title, description)


# ─── Deposit ──────────────────────────────────────────────────────────────────

def deposit_ticket(
    initiator: discord.User | discord.Member,
    account_name: str,
    account_id_display: str,
    amount_display: str,
    transaction_id: int,
) -> discord.Embed:
    """Embed posted inside a deposit ticket channel."""
    embed = _base(PRIMARY, "📥 Deposit Request")
    embed.set_author(name=str(initiator), icon_url=initiator.display_avatar.url)
    embed.add_field(name="Account", value=f"{account_name} (`{account_id_display}`)", inline=True)
    embed.add_field(name="Amount", value=amount_display, inline=True)
    embed.add_field(name="Requested By", value=initiator.mention, inline=True)
    embed.add_field(name="Transaction ID", value=f"`#{transaction_id}`", inline=True)
    embed.set_footer(text=f"{FOOTER_TEXT} • Approve, Deny, or Close this ticket")
    return embed


def deposit_approved_dm(
    account_name: str,
    account_id_display: str,
    amount_display: str,
    new_balance_display: str,
    processed_by: discord.Member,
) -> discord.Embed:
    """DM sent to the user when their deposit is approved."""
    embed = _base(SECONDARY, "✅ Deposit Approved")
    embed.add_field(name="Account", value=f"{account_name} (`{account_id_display}`)", inline=True)
    embed.add_field(name="Amount Deposited", value=amount_display, inline=True)
    embed.add_field(name="New Balance", value=new_balance_display, inline=True)
    embed.add_field(name="Processed By", value=processed_by.mention, inline=False)
    return embed


def deposit_denied_dm(
    account_name: str,
    account_id_display: str,
    amount_display: str,
    reason: str,
    processed_by: discord.Member,
) -> discord.Embed:
    """DM sent to the user when their deposit is denied."""
    embed = _base(ERROR, "❌ Deposit Denied")
    embed.add_field(name="Account", value=f"{account_name} (`{account_id_display}`)", inline=True)
    embed.add_field(name="Amount Requested", value=amount_display, inline=True)
    embed.add_field(name="Reason", value=reason, inline=False)
    embed.add_field(name="Processed By", value=processed_by.mention, inline=False)
    return embed


# ─── Withdrawal ───────────────────────────────────────────────────────────────

def withdrawal_ticket(
    initiator: discord.User | discord.Member,
    account_name: str,
    account_id_display: str,
    amount_display: str,
    in_game_name: str,
    transaction_id: int,
) -> discord.Embed:
    """Embed posted inside a withdrawal ticket channel."""
    embed = _base(PRIMARY, "📤 Withdrawal Request")
    embed.set_author(name=str(initiator), icon_url=initiator.display_avatar.url)
    embed.add_field(name="Account", value=f"{account_name} (`{account_id_display}`)", inline=True)
    embed.add_field(name="Amount", value=amount_display, inline=True)
    embed.add_field(name="In-Game Name", value=f"`{in_game_name}`", inline=True)
    embed.add_field(name="Requested By", value=initiator.mention, inline=True)
    embed.add_field(name="Transaction ID", value=f"`#{transaction_id}`", inline=True)
    embed.add_field(
        name="Minecraft Command",
        value=f"```/pay {in_game_name} {amount_display.lstrip('$')}```",
        inline=False,
    )
    embed.set_footer(text=f"{FOOTER_TEXT} • Completed or Deny this ticket")
    return embed


def withdrawal_pending_dm(
    account_name: str,
    account_id_display: str,
    amount_display: str,
    in_game_name: str,
) -> discord.Embed:
    """DM sent immediately when a withdrawal ticket is opened."""
    embed = _base(WARNING, "⏳ Withdrawal Pending")
    embed.add_field(name="Account", value=f"{account_name} (`{account_id_display}`)", inline=True)
    embed.add_field(name="Amount", value=amount_display, inline=True)
    embed.add_field(name="In-Game Name", value=f"`{in_game_name}`", inline=True)
    embed.add_field(name="Status", value="Pending processing by staff", inline=False)
    return embed


def withdrawal_completed_dm(
    account_name: str,
    account_id_display: str,
    amount_display: str,
    in_game_name: str,
    processed_by: discord.Member,
) -> discord.Embed:
    """DM sent to the user when their withdrawal is completed."""
    embed = _base(SECONDARY, "✅ Withdrawal Completed")
    embed.add_field(name="Account", value=f"{account_name} (`{account_id_display}`)", inline=True)
    embed.add_field(name="Amount Paid", value=amount_display, inline=True)
    embed.add_field(name="Paid To", value=f"`{in_game_name}`", inline=True)
    embed.add_field(name="Processed By", value=processed_by.mention, inline=False)
    return embed


def withdrawal_denied_dm(
    account_name: str,
    account_id_display: str,
    amount_display: str,
    reason: str,
    processed_by: discord.Member,
) -> discord.Embed:
    """DM sent to the user when their withdrawal is denied."""
    embed = _base(ERROR, "❌ Withdrawal Denied")
    embed.add_field(name="Account", value=f"{account_name} (`{account_id_display}`)", inline=True)
    embed.add_field(name="Amount Requested", value=amount_display, inline=True)
    embed.add_field(name="Reason", value=reason, inline=False)
    embed.add_field(name="Processed By", value=processed_by.mention, inline=False)
    return embed


# ─── Transfer ─────────────────────────────────────────────────────────────────

def transfer_received_dm(
    amount_display: str,
    source_account_id_display: str,
    dest_account_name: str,
    dest_account_id_display: str,
    new_balance_display: str,
) -> discord.Embed:
    """DM sent to destination account users when a transfer is received."""
    embed = _base(SECONDARY, "💸 Transfer Received")
    embed.add_field(name="Amount", value=amount_display, inline=True)
    embed.add_field(name="From Account", value=f"`{source_account_id_display}`", inline=True)
    embed.add_field(name="To Account", value=f"{dest_account_name} (`{dest_account_id_display}`)", inline=True)
    embed.add_field(name="New Balance", value=new_balance_display, inline=True)
    return embed


# ─── Account ──────────────────────────────────────────────────────────────────

def account_closed_dm(
    account_name: str,
    account_id_display: str,
    closed_by: Optional[discord.Member] = None,
) -> discord.Embed:
    """DM sent to all account users when an account is closed."""
    embed = _base(ERROR, "🔒 Account Closed")
    embed.add_field(name="Account", value=f"{account_name} (`{account_id_display}`)", inline=True)
    if closed_by:
        embed.add_field(name="Closed By", value=closed_by.mention, inline=True)
    return embed


def user_added_dm(
    account_name: str,
    account_id_display: str,
    added_by: discord.Member,
) -> discord.Embed:
    """DM sent to a user when they are added as authorized on an account."""
    embed = _base(SECONDARY, "👤 Added to Account")
    embed.description = "You have been added as an authorized user on the following account:"
    embed.add_field(name="Account", value=f"{account_name} (`{account_id_display}`)", inline=True)
    embed.add_field(name="Added By", value=added_by.mention, inline=True)
    return embed


def user_removed_dm(
    account_name: str,
    account_id_display: str,
    removed_by: discord.Member,
) -> discord.Embed:
    """DM sent to a user when they are removed as authorized on an account."""
    embed = _base(WARNING, "👤 Removed from Account")
    embed.description = "You have been removed as an authorized user on the following account:"
    embed.add_field(name="Account", value=f"{account_name} (`{account_id_display}`)", inline=True)
    embed.add_field(name="Removed By", value=removed_by.mention, inline=True)
    return embed


# ─── Balance ──────────────────────────────────────────────────────────────────

def balance_display(
    account_name: str,
    account_id_display: str,
    account_type: str,
    balance_display: str,
    available_display: str,
    reserved_display: str | None,
    is_frozen: bool,
) -> discord.Embed:
    """Embed returned by /bal command."""
    color = ERROR if is_frozen else PRIMARY
    embed = _base(color, "🏦 Account Balance")
    embed.add_field(name="Account", value=f"{account_name} (`{account_id_display}`)", inline=False)
    embed.add_field(name="Total Balance", value=balance_display, inline=True)
    embed.add_field(name="Available", value=available_display, inline=True)
    if reserved_display:
        embed.add_field(name="Reserved (Pending)", value=reserved_display, inline=True)
    embed.add_field(name="Account Type", value=account_type.capitalize(), inline=True)
    embed.add_field(name="Status", value="🔴 Frozen" if is_frozen else "🟢 Active", inline=True)
    return embed


# ─── Interest ─────────────────────────────────────────────────────────────────

def interest_confirmation(
    account_type: str,
    rate_display: str,
    eligible_count: int,
    estimated_total_display: str,
    estimated_remainder_display: str,
) -> discord.Embed:
    """Confirmation embed shown before interest is applied."""
    embed = _base(WARNING, "⚠️ Confirm Interest Application")
    embed.description = "Please review the following before confirming. **This action cannot be undone.**"
    embed.add_field(name="Account Type", value=account_type.capitalize(), inline=True)
    embed.add_field(name="Rate", value=rate_display, inline=True)
    embed.add_field(name="Eligible Accounts", value=str(eligible_count), inline=True)
    embed.add_field(name="Estimated Total Interest", value=estimated_total_display, inline=True)
    embed.add_field(name="Remainder → House Account", value=estimated_remainder_display, inline=True)
    return embed


def interest_applied(
    account_type: str,
    applied_count: int,
    total_applied_display: str,
    remainder_display: str,
    applied_by: discord.Member,
) -> discord.Embed:
    """Embed shown after interest is successfully applied."""
    embed = _base(SECONDARY, "✅ Interest Applied")
    embed.add_field(name="Account Type", value=account_type.capitalize(), inline=True)
    embed.add_field(name="Accounts Updated", value=str(applied_count), inline=True)
    embed.add_field(name="Total Interest Applied", value=total_applied_display, inline=True)
    embed.add_field(name="Remainder Deposited to House Account", value=remainder_display, inline=True)
    embed.add_field(name="Applied By", value=applied_by.mention, inline=False)
    return embed


def missed_interest_alert(
    account_type: str,
    scheduled_day: str,
    scheduled_time: str,
    last_applied: str,
) -> discord.Embed:
    """Alert embed posted to audit log channel on startup if a scheduled run was missed."""
    embed = _base(WARNING, "⚠️ Missed Interest Payment Detected")
    embed.description = (
        "The bot was offline when the scheduled interest payment was due. "
        "An admin can apply it manually using the button below, or dismiss this alert."
    )
    embed.add_field(name="Account Type", value=account_type.capitalize(), inline=True)
    embed.add_field(name="Scheduled", value=f"{scheduled_day.capitalize()} at {scheduled_time} UTC", inline=True)
    embed.add_field(name="Last Applied", value=last_applied, inline=True)
    return embed


# ─── Admin ────────────────────────────────────────────────────────────────────

def admin_status(
    total_accounts: int,
    bank_total_display: str,
    pending_deposits: int,
    pending_withdrawals: int,
    frozen_accounts: int,
    interest_rows: list[dict],
    uptime: str,
) -> discord.Embed:
    """Embed returned by /admin status."""
    embed = _base(PRIMARY, "📊 Bank Status")
    embed.add_field(name="Total Accounts", value=str(total_accounts), inline=True)
    embed.add_field(name="Bank Total", value=bank_total_display, inline=True)
    embed.add_field(name="Frozen Accounts", value=str(frozen_accounts), inline=True)
    embed.add_field(name="Pending Deposits", value=str(pending_deposits), inline=True)
    embed.add_field(name="Pending Withdrawals", value=str(pending_withdrawals), inline=True)
    embed.add_field(name="Bot Uptime", value=uptime, inline=True)

    if interest_rows:
        interest_lines = []
        for row in interest_rows:
            status = "⏸ Paused" if row.get("is_paused") else "▶ Active"
            last = row.get("last_applied_display", "Never")
            interest_lines.append(
                f"**{row['account_type'].capitalize()}** — {row['rate_display']} — Last: {last} — {status}"
            )
        embed.add_field(name="Interest Config", value="\n".join(interest_lines), inline=False)

    return embed


def audit_log_entry(
    action: str,
    actor_mention: str,
    target_account: str | None,
    details: str,
    origin_server: str,
) -> discord.Embed:
    """Single audit log entry embed for posting to the audit log channel."""
    embed = _base(PRIMARY, f"📋 Audit: {action.replace('_', ' ').title()}")
    embed.add_field(name="Actor", value=actor_mention, inline=True)
    if target_account:
        embed.add_field(name="Account", value=target_account, inline=True)
    embed.add_field(name="Server", value=origin_server, inline=True)
    embed.add_field(name="Details", value=details, inline=False)
    return embed


def freeze_confirmation(
    account_name: str,
    account_id_display: str,
    frozen: bool,
) -> discord.Embed:
    """Confirmation embed after freeze/unfreeze."""
    action = "Frozen" if frozen else "Unfrozen"
    color = ERROR if frozen else SECONDARY
    icon = "🔴" if frozen else "🟢"
    embed = _base(color, f"{icon} Account {action}")
    embed.add_field(name="Account", value=f"{account_name} (`{account_id_display}`)", inline=True)
    embed.add_field(name="Status", value=action, inline=True)
    return embed


def adjust_confirmation(
    account_name: str,
    account_id_display: str,
    delta_display: str,
    new_balance_display: str,
    note: str,
) -> discord.Embed:
    """Confirmation embed after a manual balance adjustment."""
    embed = _base(WARNING, "🔧 Balance Adjusted")
    embed.add_field(name="Account", value=f"{account_name} (`{account_id_display}`)", inline=True)
    embed.add_field(name="Adjustment", value=delta_display, inline=True)
    embed.add_field(name="New Balance", value=new_balance_display, inline=True)
    embed.add_field(name="Note", value=note, inline=False)
    return embed


# ─── Orphan Recovery ──────────────────────────────────────────────────────────

def orphaned_transaction_alert(
    transaction_id: int,
    account_name: str,
    account_id_display: str,
    tx_type: str,
    amount_display: str,
) -> discord.Embed:
    """Alert embed posted at startup for each orphaned transaction."""
    embed = _base(ERROR, "🚨 Orphaned Transaction Detected")
    embed.description = (
        "A pending transaction's ticket channel could not be found on startup. "
        "No funds have been moved. An admin must resolve this manually."
    )
    embed.add_field(name="Transaction ID", value=f"`#{transaction_id}`", inline=True)
    embed.add_field(name="Type", value=tx_type.capitalize(), inline=True)
    embed.add_field(name="Amount", value=amount_display, inline=True)
    embed.add_field(name="Account", value=f"{account_name} (`{account_id_display}`)", inline=True)
    return embed


# ─── Backup ───────────────────────────────────────────────────────────────────

def backup_failure_alert(path: str, error_message: str) -> discord.Embed:
    """Alert embed posted to audit log channel on backup failure."""
    embed = _base(ERROR, "💾 Backup Failed")
    embed.add_field(name="Destination", value=f"`{path}`", inline=False)
    embed.add_field(name="Error", value=error_message, inline=False)
    return embed