"""
utils/formatting.py
-------------------
Stateless pure functions for formatting and parsing amounts, dates, and IDs.
No external dependencies beyond the Python standard library.
"""

from __future__ import annotations
import re
from datetime import datetime, timezone
from typing import Optional


# ─── Currency ────────────────────────────────────────────────────────────────

def cents_to_display(cents: int, symbol: str = "$") -> str:
    """Convert an integer cent value to a display string.

    Examples:
        cents_to_display(1000)   -> "$10.00"
        cents_to_display(150)    -> "$1.50"
        cents_to_display(0)      -> "$0.00"
        cents_to_display(-500)   -> "-$5.00"
    """
    negative = cents < 0
    abs_cents = abs(cents)
    dollars = abs_cents // 100
    rem = abs_cents % 100
    value = f"{symbol}{dollars}.{rem:02d}"
    return f"-{value}" if negative else value


def parse_amount_to_cents(raw: str) -> tuple[int, str | None]:
    """Parse a user-supplied amount string into integer cents.

    Rules:
    - Whole integers are treated as whole dollars (e.g. "100" -> 10000 cents).
    - Decimals must have at most 2 decimal places (e.g. "10.50" -> 1050 cents).
    - Inputs with more than 2 decimal places return an error.
    - Leading $ symbol is stripped if present.
    - Negative values are rejected.

    Returns:
        (cents: int, error: str | None)
        If error is not None, cents is 0 and should be discarded.
    """
    raw = raw.strip().lstrip("$").strip()

    # Must match digits, optional single decimal point, optional digits after
    if not re.fullmatch(r"\d+(\.\d+)?", raw):
        return 0, "Invalid amount. Please enter a numeric value (e.g. 10 or 10.50)."

    if "." in raw:
        integer_part, decimal_part = raw.split(".")
        if len(decimal_part) > 2:
            return 0, "Invalid amount. Please enter a value with at most 2 decimal places (e.g. 10.50)."
        # Pad to 2 decimal places
        decimal_part = decimal_part.ljust(2, "0")
        cents = int(integer_part) * 100 + int(decimal_part)
    else:
        cents = int(raw) * 100

    if cents <= 0:
        return 0, "Invalid amount. Please enter a positive value greater than $0.00."

    return cents, None


def format_account_id(account_id: int) -> str:
    """Zero-pad an account ID to 5 digits for display.

    Examples:
        format_account_id(1)   -> "00001"
        format_account_id(42)  -> "00042"
        format_account_id(0)   -> "00000"
    """
    return str(account_id).zfill(5)


def format_account_name(in_game_name: str, account_id: int) -> str:
    """Build the canonical account name string."""
    return f"{in_game_name} {format_account_id(account_id)}"


# ─── Interest ─────────────────────────────────────────────────────────────────

def basis_points_to_percent(basis_points: int) -> str:
    """Convert basis points to a display percentage string.

    Examples:
        basis_points_to_percent(200)  -> "2.00%"
        basis_points_to_percent(25)   -> "0.25%"
        basis_points_to_percent(0)    -> "0.00%"
    """
    percent = basis_points / 100
    return f"{percent:.2f}%"


def percent_to_basis_points(percent_str: str) -> tuple[int, str | None]:
    """Parse a percentage string into integer basis points.

    Examples:
        percent_to_basis_points("2.00")  -> (200, None)
        percent_to_basis_points("0.25")  -> (25, None)
        percent_to_basis_points("abc")   -> (0, "error message")
    """
    try:
        value = float(percent_str.strip().rstrip("%"))
    except ValueError:
        return 0, "Invalid rate. Please enter a numeric percentage (e.g. 2.00 for 2.00%)."

    if value < 0:
        return 0, "Interest rate cannot be negative."

    basis_points = round(value * 100)
    return basis_points, None


def calculate_interest(balance_cents: int, rate_basis_points: int, carry_remainder: int) -> tuple[int, int, int]:
    """Calculate interest to apply for a single account.

    Formula:
        raw = balance_cents * rate_basis_points + carry_remainder
        applied = raw // 10000   (floor to whole cents)
        new_remainder = raw % 10000

    Args:
        balance_cents:      Current account balance in cents.
        rate_basis_points:  Interest rate in basis points.
        carry_remainder:    Accumulated remainder from previous runs.

    Returns:
        (applied_cents, new_remainder, raw)
    """
    raw = balance_cents * rate_basis_points + carry_remainder
    applied = raw // 10000
    new_remainder = raw % 10000
    return applied, new_remainder, raw


# ─── Dates ────────────────────────────────────────────────────────────────────

def utcnow() -> datetime:
    """Return the current UTC datetime (timezone-aware)."""
    return datetime.now(timezone.utc)


def format_timestamp(dt: datetime | str | None, fallback: str = "Never") -> str:
    """Format a datetime (or ISO string) for display.

    Returns a human-readable string like "2024-03-15 14:30 UTC".
    Returns fallback if dt is None.
    """
    if dt is None:
        return fallback
    if isinstance(dt, str):
        try:
            dt = datetime.fromisoformat(dt.replace("Z", "+00:00"))
        except ValueError:
            return fallback
    return dt.strftime("%Y-%m-%d %H:%M UTC")


def format_discord_timestamp(dt: datetime | str | None) -> str:
    """Format as a Discord dynamic timestamp (<t:unix:f>)."""
    if dt is None:
        return "Never"
    if isinstance(dt, str):
        try:
            dt = datetime.fromisoformat(dt.replace("Z", "+00:00"))
        except ValueError:
            return "Unknown"
    unix = int(dt.timestamp())
    return f"<t:{unix}:f>"


def backup_filename(dt: Optional[datetime] = None) -> str:
    """Generate a timestamped backup filename."""
    if dt is None:
        dt = utcnow()
    return f"solyra_backup_{dt.strftime('%Y-%m-%d_%H-%M-%S')}.db"