"""
utils/validators.py
-------------------
Stateless validation functions. Returns (is_valid: bool, error_message: str | None).
No Discord or database imports.
"""

from __future__ import annotations

ALLOWED_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}
ALLOWED_IMAGE_MIMETYPES = {
    "image/png",
    "image/jpeg",
    "image/gif",
    "image/webp",
}


def validate_image_attachment(filename: str, content_type: str | None = None) -> tuple[bool, str | None]:
    """Validate that an uploaded file is an accepted image type.

    Checks both the filename extension and content_type if provided.

    Returns:
        (True, None) if valid.
        (False, error_message) if invalid.
    """
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    if ext not in ALLOWED_IMAGE_EXTENSIONS:
        allowed = ", ".join(sorted(ALLOWED_IMAGE_EXTENSIONS))
        return False, (
            f"Invalid file type `.{ext or 'unknown'}`. "
            f"Please attach an image ({allowed})."
        )

    if content_type and content_type.lower() not in ALLOWED_IMAGE_MIMETYPES:
        return False, (
            f"Invalid file type. Please attach an image "
            f"(png, jpg, jpeg, gif, webp)."
        )

    return True, None


def validate_account_id_format(raw: str) -> tuple[bool, str | None]:
    """Validate that a string looks like a valid account ID (numeric, 1-5 digits)."""
    stripped = raw.strip().lstrip("0") or "0"
    if not stripped.isdigit():
        return False, f"Invalid account ID `{raw}`. Account IDs must be numeric."
    return True, None


def validate_in_game_name(name: str) -> tuple[bool, str | None]:
    """Validate a Minecraft in-game name (3-16 alphanumeric/underscore chars)."""
    name = name.strip()
    if not name:
        return False, "In-game name cannot be empty."
    if len(name) < 3 or len(name) > 16:
        return False, f"In-game name must be between 3 and 16 characters (got {len(name)})."
    if not all(c.isalnum() or c == "_" for c in name):
        return False, "In-game name can only contain letters, numbers, and underscores."
    return True, None


def validate_interest_rate(raw: str) -> tuple[bool, str | None]:
    """Validate an interest rate string (non-negative percentage, ≤ 2 decimal places)."""
    raw = raw.strip().rstrip("%")
    try:
        value = float(raw)
    except ValueError:
        return False, "Invalid rate. Please enter a numeric percentage (e.g. 2.00)."
    if value < 0:
        return False, "Interest rate cannot be negative."
    # Check decimal places
    if "." in raw and len(raw.split(".")[1]) > 2:
        return False, "Interest rate can have at most 2 decimal places (e.g. 2.50)."
    return True, None


def validate_interest_day(day: str) -> tuple[bool, str | None]:
    """Validate a day-of-week string for the interest scheduler."""
    valid = {"monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"}
    if day.lower().strip() not in valid:
        return False, f"Invalid day `{day}`. Must be one of: {', '.join(sorted(valid))}."
    return True, None


def validate_interest_time(time_str: str) -> tuple[bool, str | None]:
    """Validate a HH:MM UTC time string for the interest scheduler."""
    parts = time_str.strip().split(":")
    if len(parts) != 2:
        return False, "Invalid time format. Use HH:MM (e.g. 14:30)."
    try:
        hour = int(parts[0])
        minute = int(parts[1])
    except ValueError:
        return False, "Invalid time format. Use HH:MM (e.g. 14:30)."
    if not (0 <= hour <= 23):
        return False, "Hour must be between 00 and 23."
    if not (0 <= minute <= 59):
        return False, "Minute must be between 00 and 59."
    return True, None