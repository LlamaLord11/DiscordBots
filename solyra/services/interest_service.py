"""
services/interest_service.py
-----------------------------
Interest rate configuration, application logic, and remainder handling.
No Discord imports.
"""

from __future__ import annotations
import logging
from typing import Optional

from ..db.database import Database
from ..db.queries import accounts as account_q
from ..db.queries import interest as interest_q
from ..db.queries import transactions as tx_q
from ..utils.formatting import (
    utcnow,
    calculate_interest,
    basis_points_to_percent,
    percent_to_basis_points,
    cents_to_display,
)

log = logging.getLogger(__name__)

HOUSE_ACCOUNT_ID = 0


# ─── Config ───────────────────────────────────────────────────────────────────

async def set_interest_rate(
    db: Database,
    account_type: str,
    rate_percent_str: str,
    updated_by_id: int,
) -> dict:
    """Set the interest rate for an account type.

    Args:
        rate_percent_str: e.g. "2.00" for 2.00%

    Returns a dict with the new config row.
    Raises ValueError on invalid input.
    """
    basis_points, err = percent_to_basis_points(rate_percent_str)
    if err:
        raise ValueError(err)

    now = utcnow().isoformat()
    await interest_q.upsert_interest_config(
        db, account_type, basis_points, updated_by_id, now
    )
    row = await interest_q.get_interest_config(db, account_type)
    return dict(row)


async def get_all_configs(db: Database) -> list[dict]:
    rows = await interest_q.get_all_interest_configs(db)
    result = []
    for row in rows:
        d = dict(row)
        d["rate_display"] = basis_points_to_percent(d["rate_basis_points"])
        result.append(d)
    return result


async def pause_all(db: Database) -> None:
    await interest_q.set_paused_all(db, True)
    log.info("Interest scheduler paused globally.")


async def resume_all(db: Database) -> None:
    await interest_q.set_paused_all(db, False)
    log.info("Interest scheduler resumed globally.")


# ─── Preview ──────────────────────────────────────────────────────────────────

async def preview_interest_run(
    db: Database,
    account_type: str,
) -> dict:
    """Calculate a dry-run preview of an interest application.

    Returns a dict suitable for building the confirmation embed.
    Raises ValueError if account_type is not configured.
    """
    config = await interest_q.get_interest_config(db, account_type)
    if config is None:
        raise ValueError(f"No interest config found for account type `{account_type}`.")

    config = dict(config)
    accounts = await account_q.get_all_accounts_of_type(
        db, account_type,
        exclude_frozen=True,
        exclude_zero_balance=True,
        exclude_house=True,
    )

    carry = config["remainder_cents"]
    total_applied = 0
    remainder = carry

    for acc in accounts:
        applied, new_rem, _ = calculate_interest(acc["balance"], config["rate_basis_points"], remainder)
        total_applied += applied
        remainder = new_rem

    return {
        "account_type": account_type,
        "rate_display": basis_points_to_percent(config["rate_basis_points"]),
        "eligible_count": len(accounts),
        "estimated_total_display": cents_to_display(total_applied),
        "estimated_remainder_display": cents_to_display(remainder),
        "config": config,
    }


# ─── Application ──────────────────────────────────────────────────────────────

async def apply_interest(
    db: Database,
    account_type: str,
    applied_by_id: int,
) -> dict:
    """Apply interest to all eligible accounts of the given type.

    - Skips frozen, zero-balance, and house accounts.
    - Floors each calculation, carries remainder forward.
    - Deposits total remainder to house account 00000.
    - Records a transaction per account and for the house deposit.

    Returns a summary dict.
    """
    config = await interest_q.get_interest_config(db, account_type)
    if config is None:
        raise ValueError(f"No interest config for account type `{account_type}`.")

    config = dict(config)
    accounts = await account_q.get_all_accounts_of_type(
        db, account_type,
        exclude_frozen=True,
        exclude_zero_balance=True,
        exclude_house=True,
    )

    if not accounts:
        raise ValueError(f"No eligible accounts found for type `{account_type}`.")

    now = utcnow().isoformat()
    carry = config["remainder_cents"]
    total_applied = 0
    applied_count = 0

    for acc in accounts:
        applied, carry, _ = calculate_interest(acc["balance"], config["rate_basis_points"], carry)
        if applied > 0:
            await account_q.update_balance(db, acc["account_id"], applied)
            await tx_q.create_transaction(
                db=db,
                account_id=acc["account_id"],
                tx_type="interest",
                amount=applied,
                status="completed",
                created_at=now,
                processed_by=applied_by_id,
            )
            total_applied += applied
            applied_count += 1

    # Deposit remainder to house account
    if carry > 0:
        await account_q.update_balance(db, HOUSE_ACCOUNT_ID, carry)
        await tx_q.create_transaction(
            db=db,
            account_id=HOUSE_ACCOUNT_ID,
            tx_type="interest",
            amount=carry,
            status="completed",
            created_at=now,
            notes=f"Interest remainder from {account_type} run",
            processed_by=applied_by_id,
        )

    # Update config
    await interest_q.update_after_apply(db, account_type, 0, now)

    log.info(
        "Interest applied: type=%s accounts=%s total=%s remainder_to_house=%s",
        account_type, applied_count, total_applied, carry,
    )

    return {
        "account_type": account_type,
        "applied_count": applied_count,
        "total_applied_display": cents_to_display(total_applied),
        "remainder_display": cents_to_display(carry),
        "carry_deposited": carry,
    }


# ─── Missed Payment Detection ─────────────────────────────────────────────────

def check_missed_payment(
    last_applied_iso: Optional[str],
    scheduled_day: str,
    scheduled_time_str: str,
) -> bool:
    """Return True if a scheduled interest run was missed.

    Compares last_applied against what the most recent scheduled run would
    have been. Returns True if the scheduled time has passed since last_applied.
    """
    from datetime import datetime, timezone, timedelta
    import calendar

    now = datetime.now(timezone.utc)

    # Parse scheduled time
    h, m = map(int, scheduled_time_str.split(":"))
    day_num = list(calendar.day_name).index(scheduled_day.capitalize())

    # Find the most recent past scheduled datetime
    days_since = (now.weekday() - day_num) % 7
    last_scheduled = now.replace(hour=h, minute=m, second=0, microsecond=0) - timedelta(days=days_since)
    if last_scheduled > now:
        last_scheduled -= timedelta(weeks=1)

    if last_applied_iso is None:
        # Never applied — only alert if the scheduled time has passed at least once
        return last_scheduled < now

    last_applied = datetime.fromisoformat(last_applied_iso.replace("Z", "+00:00"))
    return last_applied < last_scheduled