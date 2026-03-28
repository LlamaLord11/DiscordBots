"""
db/queries/accounts.py
----------------------
All SQL touching the accounts and account_users tables.
Returns raw aiosqlite.Row objects or primitives — no business logic here.
"""

from __future__ import annotations
from typing import Optional
from ..database import Database

HOUSE_ACCOUNT_ID = 0


# ─── Accounts ─────────────────────────────────────────────────────────────────

async def get_account(db: Database, account_id: int) -> Optional[object]:
    return await db.fetchone(
        "SELECT * FROM accounts WHERE account_id = ?",
        (account_id,),
    )


async def get_accounts_for_user(db: Database, user_id: int) -> list:
    """Return all accounts where the user is owner or authorized user."""
    return await db.fetchall(
        """
        SELECT DISTINCT a.*
        FROM accounts a
        LEFT JOIN account_users au ON a.account_id = au.account_id
        WHERE a.owner_id = ? OR au.user_id = ?
        ORDER BY a.account_id
        """,
        (user_id, user_id),
    )


async def get_accounts_for_user_on_server(
    db: Database,
    user_id: int,
    guild_id: str,
) -> list:
    """Return accounts the user can interact with, filtered to those used on this server.
    Used for transfer destination autocomplete.
    """
    return await db.fetchall(
        """
        SELECT DISTINCT a.*
        FROM accounts a
        LEFT JOIN account_users au ON a.account_id = au.account_id
        LEFT JOIN transactions t ON t.account_id = a.account_id
        LEFT JOIN audit_log al ON al.target_account_id = a.account_id
            AND al.origin_server_id = ?
        WHERE (a.owner_id = ? OR au.user_id = ?)
          AND al.target_account_id IS NOT NULL
          AND a.account_id != ?
        ORDER BY a.account_id
        """,
        (guild_id, user_id, user_id, HOUSE_ACCOUNT_ID),
    )


async def create_account(
    db: Database,
    account_name: str,
    account_type: str,
    owner_id: int,
    created_at: str,
) -> int:
    """Insert a new account and return its new account_id."""
    return await db.execute_returning(
        """
        INSERT INTO accounts (account_name, account_type, owner_id, balance,
                              reserved_cents, is_frozen, created_at)
        VALUES (?, ?, ?, 0, 0, 0, ?)
        """,
        (account_name, account_type, owner_id, created_at),
    )


async def create_house_account_if_missing(
    db: Database,
    bot_user_id: int,
    created_at: str,
) -> None:
    """Create account 00000 (house account) using INSERT OR IGNORE."""
    # SQLite AUTOINCREMENT won't let us force ID 0 via normal insert.
    # We use a direct INSERT with explicit account_id = 0.
    await db.execute(
        """
        INSERT OR IGNORE INTO accounts
            (account_id, account_name, account_type, owner_id,
             balance, reserved_cents, is_frozen, created_at)
        VALUES (0, 'Sølyra House Account', 'system', ?, 0, 0, 0, ?)
        """,
        (bot_user_id, created_at),
    )


async def update_balance(db: Database, account_id: int, delta_cents: int) -> None:
    """Atomically add delta_cents to the account balance (can be negative)."""
    await db.execute(
        "UPDATE accounts SET balance = balance + ? WHERE account_id = ?",
        (delta_cents, account_id),
    )


async def update_reserved(db: Database, account_id: int, delta_cents: int) -> None:
    """Atomically add delta_cents to reserved_cents (can be negative)."""
    await db.execute(
        "UPDATE accounts SET reserved_cents = reserved_cents + ? WHERE account_id = ?",
        (delta_cents, account_id),
    )


async def set_frozen(db: Database, account_id: int, frozen: bool) -> None:
    await db.execute(
        "UPDATE accounts SET is_frozen = ? WHERE account_id = ?",
        (1 if frozen else 0, account_id),
    )


async def delete_account(db: Database, account_id: int) -> None:
    """Delete an account and cascade to account_users."""
    await db.execute(
        "DELETE FROM accounts WHERE account_id = ?",
        (account_id,),
    )


async def get_all_accounts_of_type(
    db: Database,
    account_type: str,
    exclude_frozen: bool = True,
    exclude_zero_balance: bool = True,
    exclude_house: bool = True,
) -> list:
    """Return accounts of a given type, with optional filters for interest runs."""
    conditions = ["account_type = ?"]
    params: list = [account_type]

    if exclude_frozen:
        conditions.append("is_frozen = 0")
    if exclude_zero_balance:
        conditions.append("balance > 0")
    if exclude_house:
        conditions.append("account_id != 0")

    where = " AND ".join(conditions)
    return await db.fetchall(
        f"SELECT * FROM accounts WHERE {where} ORDER BY account_id",
        tuple(params),
    )


async def get_bank_total(db: Database) -> int:
    """Return sum of all account balances (includes house account)."""
    return await db.fetchval(
        "SELECT COALESCE(SUM(balance), 0) FROM accounts",
        default=0,
    )


async def get_account_count(db: Database) -> int:
    """Return total number of accounts excluding house account."""
    return await db.fetchval(
        "SELECT COUNT(*) FROM accounts WHERE account_id != 0",
        default=0,
    )


async def get_frozen_count(db: Database) -> int:
    return await db.fetchval(
        "SELECT COUNT(*) FROM accounts WHERE is_frozen = 1 AND account_id != 0",
        default=0,
    )


# ─── Account Users ────────────────────────────────────────────────────────────

async def get_authorized_user_ids(db: Database, account_id: int) -> list[int]:
    rows = await db.fetchall(
        "SELECT user_id FROM account_users WHERE account_id = ?",
        (account_id,),
    )
    return [row["user_id"] for row in rows]


async def is_user_authorized(db: Database, account_id: int, user_id: int) -> bool:
    row = await db.fetchone(
        "SELECT 1 FROM account_users WHERE account_id = ? AND user_id = ?",
        (account_id, user_id),
    )
    return row is not None


async def add_authorized_user(
    db: Database,
    account_id: int,
    user_id: int,
    added_at: str,
) -> None:
    await db.execute(
        "INSERT INTO account_users (account_id, user_id, added_at) VALUES (?, ?, ?)",
        (account_id, user_id, added_at),
    )


async def remove_authorized_user(db: Database, account_id: int, user_id: int) -> None:
    await db.execute(
        "DELETE FROM account_users WHERE account_id = ? AND user_id = ?",
        (account_id, user_id),
    )