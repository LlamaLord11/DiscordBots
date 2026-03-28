"""
db/queries/transactions.py
--------------------------
All SQL touching the transactions table.
"""

from __future__ import annotations
from typing import Optional
from ..database import Database


async def create_transaction(
    db: Database,
    account_id: int,
    tx_type: str,
    amount: int,
    status: str,
    created_at: str,
    channel_id: Optional[str] = None,
    initiator_id: Optional[int] = None,
    counterpart_id: Optional[int] = None,
    processed_by: Optional[int] = None,
    notes: Optional[str] = None,
) -> int:
    """Insert a new transaction and return its transaction_id."""
    return await db.execute_returning(
        """
        INSERT INTO transactions
            (account_id, type, amount, status, channel_id, initiator_id,
             counterpart_id, processed_by, notes, created_at, resolved_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
        """,
        (account_id, tx_type, amount, status, channel_id, initiator_id,
         counterpart_id, processed_by, notes, created_at),
    )


async def get_transaction(db: Database, transaction_id: int) -> Optional[object]:
    return await db.fetchone(
        "SELECT * FROM transactions WHERE transaction_id = ?",
        (transaction_id,),
    )


async def update_transaction_status(
    db: Database,
    transaction_id: int,
    status: str,
    resolved_at: str,
    processed_by: Optional[int] = None,
    notes: Optional[str] = None,
    clear_channel_id: bool = False,
) -> None:
    """Update a transaction's status. Optionally clear channel_id on resolution."""
    sets = ["status = ?", "resolved_at = ?"]
    params: list = [status, resolved_at]

    if processed_by is not None:
        sets.append("processed_by = ?")
        params.append(processed_by)

    if notes is not None:
        sets.append("notes = ?")
        params.append(notes)

    if clear_channel_id:
        sets.append("channel_id = NULL")

    params.append(transaction_id)
    await db.execute(
        f"UPDATE transactions SET {', '.join(sets)} WHERE transaction_id = ?",
        tuple(params),
    )


async def get_pending_ticket_transactions(db: Database) -> list:
    """Return all pending transactions that have a channel_id (for crash recovery)."""
    return await db.fetchall(
        """
        SELECT t.*, a.account_name, a.account_type
        FROM transactions t
        JOIN accounts a ON a.account_id = t.account_id
        WHERE t.status = 'pending' AND t.channel_id IS NOT NULL
        """,
    )


async def get_history_for_account(
    db: Database,
    account_id: int,
    since_iso: str,
    limit: int = 200,
) -> list:
    """Return up to `limit` transactions for an account within the last 30 days."""
    return await db.fetchall(
        """
        SELECT * FROM transactions
        WHERE account_id = ?
          AND created_at >= ?
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (account_id, since_iso, limit),
    )


async def get_pending_count_by_type(db: Database, tx_type: str) -> int:
    return await db.fetchval(
        "SELECT COUNT(*) FROM transactions WHERE status = 'pending' AND type = ?",
        (tx_type,),
        default=0,
    )