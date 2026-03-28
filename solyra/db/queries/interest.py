"""
db/queries/interest.py
----------------------
All SQL touching the interest_config table.
"""

from __future__ import annotations
from typing import Optional
from ..database import Database


async def get_interest_config(db: Database, account_type: str) -> Optional[object]:
    return await db.fetchone(
        "SELECT * FROM interest_config WHERE account_type = ?",
        (account_type,),
    )


async def get_all_interest_configs(db: Database) -> list:
    return await db.fetchall(
        "SELECT * FROM interest_config ORDER BY account_type",
    )


async def seed_general_if_missing(db: Database) -> None:
    """Seed the 'general' account type with defaults using INSERT OR IGNORE."""
    await db.execute(
        """
        INSERT OR IGNORE INTO interest_config
            (account_type, rate_basis_points, is_paused, last_applied,
             remainder_cents, updated_by, updated_at)
        VALUES ('general', 0, 0, NULL, 0, NULL, NULL)
        """,
    )


async def upsert_interest_config(
    db: Database,
    account_type: str,
    rate_basis_points: int,
    updated_by: int,
    updated_at: str,
) -> None:
    """Insert or update an interest config row."""
    await db.execute(
        """
        INSERT INTO interest_config
            (account_type, rate_basis_points, is_paused, last_applied,
             remainder_cents, updated_by, updated_at)
        VALUES (?, ?, 0, NULL, 0, ?, ?)
        ON CONFLICT(account_type) DO UPDATE SET
            rate_basis_points = excluded.rate_basis_points,
            updated_by        = excluded.updated_by,
            updated_at        = excluded.updated_at
        """,
        (account_type, rate_basis_points, updated_by, updated_at),
    )


async def update_after_apply(
    db: Database,
    account_type: str,
    new_remainder: int,
    last_applied: str,
) -> None:
    """Update remainder_cents and last_applied after an interest run."""
    await db.execute(
        """
        UPDATE interest_config
        SET remainder_cents = ?, last_applied = ?
        WHERE account_type = ?
        """,
        (new_remainder, last_applied, account_type),
    )


async def set_paused_all(db: Database, paused: bool) -> None:
    """Globally pause or resume all account types."""
    await db.execute(
        "UPDATE interest_config SET is_paused = ?",
        (1 if paused else 0,),
    )