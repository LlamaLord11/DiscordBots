"""
services/account_service.py
----------------------------
Business logic for account management.
No Discord imports — all return plain dicts or raise ValueError with user-facing messages.
"""

from __future__ import annotations
import logging
from typing import Optional

from ..db.database import Database
from ..db.queries import accounts as account_q
from ..utils.formatting import (
    utcnow,
    format_account_id,
    format_account_name,
    cents_to_display,
)

log = logging.getLogger(__name__)


# ─── Account Retrieval ────────────────────────────────────────────────────────

async def get_account_or_raise(db: Database, account_id: int) -> dict:
    """Fetch an account by ID or raise ValueError."""
    row = await account_q.get_account(db, account_id)
    if row is None:
        raise ValueError(f"No account found with ID `{format_account_id(account_id)}`.")
    return dict(row)


async def get_authorized_ids(db: Database, account_id: int) -> list[int]:
    return await account_q.get_authorized_user_ids(db, account_id)


async def assert_user_can_access(
    db: Database,
    account: dict,
    user_id: int,
) -> None:
    """Raise ValueError if the user is not the owner or an authorized user."""
    if account["owner_id"] == user_id:
        return
    authorized = await account_q.get_authorized_user_ids(db, account["account_id"])
    if user_id not in authorized:
        raise ValueError("You are not authorized to perform actions on this account.")


async def assert_user_is_owner(account: dict, user_id: int) -> None:
    """Raise ValueError if the user is not the account owner."""
    if account["owner_id"] != user_id:
        raise ValueError("Only the account owner can perform this action.")


async def assert_not_frozen(account: dict) -> None:
    """Raise ValueError if the account is frozen."""
    if account["is_frozen"]:
        aid = format_account_id(account["account_id"])
        raise ValueError(
            f"Account `{aid}` is currently frozen. Contact an administrator."
        )


async def assert_not_house_account(account: dict) -> None:
    """Raise ValueError if this is account 00000."""
    if account["account_id"] == 0:
        raise ValueError("This operation cannot be performed on the house account.")


# ─── Account Creation ─────────────────────────────────────────────────────────

async def create_account(
    db: Database,
    in_game_name: str,
    owner_id: int,
) -> dict:
    """Create a new General account. Returns the new account as a dict."""
    now = utcnow().isoformat()
    # We need the ID before we can build the name, so insert with placeholder
    # then update. SQLite AUTOINCREMENT starts at 1 (0 is reserved for house).
    account_id = await account_q.create_account(
        db=db,
        account_name="__pending__",
        account_type="general",
        owner_id=owner_id,
        created_at=now,
    )
    name = format_account_name(in_game_name, account_id)
    await db.execute(
        "UPDATE accounts SET account_name = ? WHERE account_id = ?",
        (name, account_id),
    )
    row = await account_q.get_account(db, account_id)
    return dict(row)


async def ensure_house_account(db: Database, bot_user_id: int) -> None:
    """Create account 00000 if it does not exist (called on startup)."""
    await account_q.create_house_account_if_missing(
        db, bot_user_id, utcnow().isoformat()
    )
    log.info("House account 00000 verified.")


# ─── Account Closure ──────────────────────────────────────────────────────────

async def close_account(
    db: Database,
    account_id: int,
    requesting_user_id: int,
) -> tuple[dict, list[int]]:
    """Close an account. Returns (account_dict, list_of_authorized_user_ids).

    Raises ValueError on any pre-condition failure.
    """
    account = await get_account_or_raise(db, account_id)
    await assert_not_house_account(account)
    await assert_user_is_owner(account, requesting_user_id)

    if account["balance"] > 0:
        bal = cents_to_display(account["balance"])
        raise ValueError(
            f"Account still has {bal}. "
            "Please withdraw remaining funds before closing."
        )

    if account["reserved_cents"] > 0:
        raise ValueError(
            "Account has a pending withdrawal ticket. "
            "Please wait for it to be resolved before closing."
        )

    authorized_ids = await account_q.get_authorized_user_ids(db, account_id)
    await account_q.delete_account(db, account_id)
    log.info("Account %s closed by user %s", account_id, requesting_user_id)
    return account, authorized_ids


# ─── Freeze / Unfreeze ────────────────────────────────────────────────────────

async def freeze_account(db: Database, account_id: int) -> dict:
    """Freeze an account. Returns the updated account dict."""
    account = await get_account_or_raise(db, account_id)
    await assert_not_house_account(account)
    await account_q.set_frozen(db, account_id, True)
    account["is_frozen"] = True
    return account


async def unfreeze_account(db: Database, account_id: int) -> dict:
    """Unfreeze an account. Returns the updated account dict."""
    account = await get_account_or_raise(db, account_id)
    await account_q.set_frozen(db, account_id, False)
    account["is_frozen"] = False
    return account


# ─── Balance Adjustment ───────────────────────────────────────────────────────

async def admin_adjust_balance(
    db: Database,
    account_id: int,
    delta_cents: int,
    note: str,
) -> dict:
    """Manually adjust a balance. Blocks adjustments that would go negative.

    Returns the updated account dict.
    """
    account = await get_account_or_raise(db, account_id)
    new_balance = account["balance"] + delta_cents

    if new_balance < 0:
        current = cents_to_display(account["balance"])
        raise ValueError(
            f"Adjustment would result in a negative balance. "
            f"Current balance: {current}. "
            f"Minimum adjustment allowed brings balance to $0.00."
        )

    await account_q.update_balance(db, account_id, delta_cents)
    account["balance"] = new_balance
    return account


# ─── Authorized User Management ───────────────────────────────────────────────

async def add_user_to_account(
    db: Database,
    account_id: int,
    requesting_user_id: int,
    target_user_id: int,
) -> dict:
    """Add an authorized user to an account.

    Returns the account dict.
    Raises ValueError on pre-condition failures.
    """
    account = await get_account_or_raise(db, account_id)
    await assert_not_house_account(account)
    await assert_user_is_owner(account, requesting_user_id)

    already = await account_q.is_user_authorized(db, account_id, target_user_id)
    if already:
        raise ValueError(
            f"<@{target_user_id}> is already an authorized user on this account."
        )

    await account_q.add_authorized_user(db, account_id, target_user_id, utcnow().isoformat())
    return account


async def remove_user_from_account(
    db: Database,
    account_id: int,
    requesting_user_id: int,
    target_user_id: int,
) -> dict:
    """Remove an authorized user from an account.

    Returns the account dict.
    Raises ValueError on pre-condition failures.
    """
    account = await get_account_or_raise(db, account_id)
    await assert_not_house_account(account)
    await assert_user_is_owner(account, requesting_user_id)

    if target_user_id == account["owner_id"]:
        raise ValueError("Cannot remove the account owner using this command.")

    exists = await account_q.is_user_authorized(db, account_id, target_user_id)
    if not exists:
        raise ValueError(
            f"<@{target_user_id}> is not an authorized user on this account."
        )

    await account_q.remove_authorized_user(db, account_id, target_user_id)
    return account


# ─── Stats ────────────────────────────────────────────────────────────────────

async def get_bank_stats(db: Database) -> dict:
    """Return aggregated bank stats for /admin status."""
    from ..db.queries.transactions import get_pending_count_by_type
    return {
        "total_accounts": await account_q.get_account_count(db),
        "bank_total_cents": await account_q.get_bank_total(db),
        "pending_deposits": await get_pending_count_by_type(db, "deposit"),
        "pending_withdrawals": await get_pending_count_by_type(db, "withdrawal"),
        "frozen_accounts": await account_q.get_frozen_count(db),
    }