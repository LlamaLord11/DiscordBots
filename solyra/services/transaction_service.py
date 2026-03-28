"""
services/transaction_service.py
--------------------------------
Business logic for deposits, withdrawals, transfers, and history.
No Discord imports.
"""

from __future__ import annotations
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from ..db.database import Database
from ..db.queries import accounts as account_q
from ..db.queries import transactions as tx_q
from ..utils.formatting import utcnow, cents_to_display

log = logging.getLogger(__name__)


# ─── Available Balance ────────────────────────────────────────────────────────

def available_balance(account: dict) -> int:
    """Return the spendable balance (balance minus reserved_cents)."""
    return account["balance"] - account["reserved_cents"]


# ─── Deposit ──────────────────────────────────────────────────────────────────

async def open_deposit_ticket(
    db: Database,
    account_id: int,
    amount_cents: int,
    user_id: int,
    channel_id: str,
) -> int:
    """Create a pending deposit transaction tied to a ticket channel.

    Returns the new transaction_id.
    """
    account = await account_q.get_account(db, account_id)
    if account is None:
        raise ValueError("Account not found.")
    if account["is_frozen"]:
        raise ValueError(f"Account `{account_id:05d}` is frozen.")

    tx_id = await tx_q.create_transaction(
        db=db,
        account_id=account_id,
        tx_type="deposit",
        amount=amount_cents,
        status="pending",
        created_at=utcnow().isoformat(),
        channel_id=channel_id,
        initiator_id=user_id,
    )
    log.info("Deposit ticket opened: tx=%s account=%s amount=%s", tx_id, account_id, amount_cents)
    return tx_id


async def approve_deposit(
    db: Database,
    transaction_id: int,
    processed_by_id: int,
) -> dict:
    """Approve a deposit: credit the balance and mark completed.

    Returns a dict with transaction and account info for DM/embed building.
    Raises ValueError if already resolved (idempotency guard).
    """
    tx = await tx_q.get_transaction(db, transaction_id)
    if tx is None:
        raise ValueError(f"Transaction #{transaction_id} not found.")
    if tx["status"] != "pending":
        raise ValueError(f"Transaction #{transaction_id} is already {tx['status']}.")

    now = utcnow().isoformat()
    # Read current balance before writing so we can calculate new balance accurately
    account = await account_q.get_account(db, tx["account_id"])
    if account["is_frozen"]:
        raise ValueError(f"Account `{account['account_id']:05d}` is frozen. Unfreeze before approving deposits.")
    new_balance_cents = account["balance"] + tx["amount"]
    # Credit balance atomically
    await account_q.update_balance(db, tx["account_id"], tx["amount"])
    # Mark completed, clear channel_id
    await tx_q.update_transaction_status(
        db, transaction_id, "completed", now,
        processed_by=processed_by_id,
        clear_channel_id=True,
    )
    return {
        "transaction": dict(tx),
        "account": dict(account),
        "new_balance_cents": new_balance_cents,
    }


async def deny_deposit(
    db: Database,
    transaction_id: int,
    processed_by_id: int,
    reason: str,
) -> dict:
    """Deny a deposit: mark denied, no balance change.

    Returns a dict with transaction and account info for DM/embed building.
    Raises ValueError if already resolved.
    """
    tx = await tx_q.get_transaction(db, transaction_id)
    if tx is None:
        raise ValueError(f"Transaction #{transaction_id} not found.")
    if tx["status"] != "pending":
        raise ValueError(f"Transaction #{transaction_id} is already {tx['status']}.")

    now = utcnow().isoformat()
    await tx_q.update_transaction_status(
        db, transaction_id, "denied", now,
        processed_by=processed_by_id,
        notes=reason,
        clear_channel_id=True,
    )
    account = await account_q.get_account(db, tx["account_id"])
    return {
        "transaction": dict(tx),
        "account": dict(account),
    }


# ─── Withdrawal ───────────────────────────────────────────────────────────────

async def open_withdrawal_ticket(
    db: Database,
    account_id: int,
    amount_cents: int,
    user_id: int,
    channel_id: str,
    in_game_name: str,
) -> int:
    """Create a pending withdrawal and soft-lock the funds.

    Returns the new transaction_id.
    Raises ValueError on pre-condition failure.
    """
    account = await account_q.get_account(db, account_id)
    if account is None:
        raise ValueError("Account not found.")
    if account["is_frozen"]:
        raise ValueError(f"Account `{account_id:05d}` is frozen.")

    avail = available_balance(dict(account))
    if amount_cents > avail:
        bal = cents_to_display(account["balance"])
        res = cents_to_display(account["reserved_cents"])
        avail_disp = cents_to_display(avail)
        raise ValueError(
            f"Insufficient available balance. "
            f"Available: {avail_disp}. Reserved: {res}. Total balance: {bal}."
        )

    # Soft-lock the funds
    await account_q.update_reserved(db, account_id, amount_cents)

    tx_id = await tx_q.create_transaction(
        db=db,
        account_id=account_id,
        tx_type="withdrawal",
        amount=amount_cents,
        status="pending",
        created_at=utcnow().isoformat(),
        channel_id=channel_id,
        initiator_id=user_id,
        notes=in_game_name,
    )
    log.info("Withdrawal ticket opened: tx=%s account=%s amount=%s ign=%s",
             tx_id, account_id, amount_cents, in_game_name)
    return tx_id


async def complete_withdrawal(
    db: Database,
    transaction_id: int,
    processed_by_id: int,
) -> dict:
    """Mark a withdrawal completed: deduct balance and release reserved.

    Returns a dict with transaction and account info.
    Raises ValueError if already resolved.
    """
    tx = await tx_q.get_transaction(db, transaction_id)
    if tx is None:
        raise ValueError(f"Transaction #{transaction_id} not found.")
    if tx["status"] != "pending":
        raise ValueError(f"Transaction #{transaction_id} is already {tx['status']}.")

    now = utcnow().isoformat()
    amount = tx["amount"]

    # Deduct balance and release reserved atomically (both through queue)
    await account_q.update_balance(db, tx["account_id"], -amount)
    await account_q.update_reserved(db, tx["account_id"], -amount)
    await tx_q.update_transaction_status(
        db, transaction_id, "completed", now,
        processed_by=processed_by_id,
        clear_channel_id=True,
    )
    account = await account_q.get_account(db, tx["account_id"])
    return {
        "transaction": dict(tx),
        "account": dict(account),
        "in_game_name": tx["notes"],
    }


async def deny_withdrawal(
    db: Database,
    transaction_id: int,
    processed_by_id: int,
    reason: str,
) -> dict:
    """Deny a withdrawal: release reserved funds, mark denied.

    Returns a dict with transaction and account info.
    Raises ValueError if already resolved.
    """
    tx = await tx_q.get_transaction(db, transaction_id)
    if tx is None:
        raise ValueError(f"Transaction #{transaction_id} not found.")
    if tx["status"] != "pending":
        raise ValueError(f"Transaction #{transaction_id} is already {tx['status']}.")

    now = utcnow().isoformat()
    # Release soft-lock first
    await account_q.update_reserved(db, tx["account_id"], -tx["amount"])
    await tx_q.update_transaction_status(
        db, transaction_id, "denied", now,
        processed_by=processed_by_id,
        notes=reason,
        clear_channel_id=True,
    )
    account = await account_q.get_account(db, tx["account_id"])
    return {
        "transaction": dict(tx),
        "account": dict(account),
        "in_game_name": tx["notes"],
    }


# ─── Transfer ─────────────────────────────────────────────────────────────────

async def execute_transfer(
    db: Database,
    source_account_id: int,
    dest_account_id: int,
    amount_cents: int,
    requesting_user_id: int,
) -> dict:
    """Execute an immediate transfer between two accounts.

    Returns a dict with both accounts and transaction info.
    Raises ValueError on any pre-condition failure.
    """
    if source_account_id == dest_account_id:
        raise ValueError("Source and destination account cannot be the same.")

    source = await account_q.get_account(db, source_account_id)
    dest = await account_q.get_account(db, dest_account_id)

    if source is None:
        raise ValueError(f"Source account `{source_account_id:05d}` not found.")
    if dest is None:
        raise ValueError(f"Destination account `{dest_account_id:05d}` not found.")

    if source["is_frozen"]:
        raise ValueError(f"Source account `{source_account_id:05d}` is frozen.")
    if dest["is_frozen"]:
        raise ValueError(f"Destination account `{dest_account_id:05d}` is frozen.")

    avail = available_balance(dict(source))
    if amount_cents > avail:
        bal = cents_to_display(source["balance"])
        res = cents_to_display(source["reserved_cents"])
        avail_disp = cents_to_display(avail)
        raise ValueError(
            f"Insufficient available balance. "
            f"Available: {avail_disp}. Reserved: {res}. Total balance: {bal}."
        )

    now = utcnow().isoformat()

    # Debit source
    await account_q.update_balance(db, source_account_id, -amount_cents)
    out_tx_id = await tx_q.create_transaction(
        db=db,
        account_id=source_account_id,
        tx_type="transfer_out",
        amount=amount_cents,
        status="completed",
        created_at=now,
        counterpart_id=dest_account_id,
    )

    # Credit destination
    await account_q.update_balance(db, dest_account_id, amount_cents)
    in_tx_id = await tx_q.create_transaction(
        db=db,
        account_id=dest_account_id,
        tx_type="transfer_in",
        amount=amount_cents,
        status="completed",
        created_at=now,
        counterpart_id=source_account_id,
    )

    dest_updated = await account_q.get_account(db, dest_account_id)
    return {
        "source_account": dict(source),
        "dest_account": dict(dest_updated),
        "amount_cents": amount_cents,
        "out_tx_id": out_tx_id,
        "in_tx_id": in_tx_id,
    }


# ─── History ──────────────────────────────────────────────────────────────────

async def get_balance_history(
    db: Database,
    account_id: int,
    page: int = 0,
    page_size: int = 10,
) -> tuple[list, int, int]:
    """Return a page of transaction history for the last 30 days.

    Returns:
        (rows, total_count, total_pages)
    """
    since = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    all_rows = await tx_q.get_history_for_account(db, account_id, since)
    total = len(all_rows)
    total_pages = max(1, (total + page_size - 1) // page_size)
    start = page * page_size
    page_rows = all_rows[start: start + page_size]
    return [dict(r) for r in page_rows], total, total_pages


# ─── Crash Recovery ───────────────────────────────────────────────────────────

async def get_pending_tickets(db: Database) -> list[dict]:
    """Return all pending transactions with a channel_id for crash recovery."""
    rows = await tx_q.get_pending_ticket_transactions(db)
    return [dict(r) for r in rows]


async def mark_orphaned(db: Database, transaction_id: int) -> None:
    """Mark a transaction as orphaned when its channel cannot be recovered."""
    await tx_q.update_transaction_status(
        db,
        transaction_id,
        status="orphaned",
        resolved_at=utcnow().isoformat(),
        notes="Ticket channel not found on startup recovery.",
        clear_channel_id=True,
    )