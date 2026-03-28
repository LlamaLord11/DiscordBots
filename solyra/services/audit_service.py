"""
services/audit_service.py
-------------------------
Audit log writes and real-time alert posting.
Discord-agnostic for the write path — the post_to_channel helper
accepts a callable so it can be used without importing discord directly.
"""

from __future__ import annotations
import logging
from typing import Optional, Callable, Coroutine, Any

from ..db.database import Database
from ..db.queries.audit import insert_audit_log, get_audit_log, get_audit_log_count
from ..utils.formatting import utcnow, format_timestamp

log = logging.getLogger(__name__)

# Type alias for "an async function that accepts a discord.Embed and sends it"
ChannelSendFn = Callable[..., Coroutine[Any, Any, None]]


async def log_action(
    db: Database,
    actor_id: int,
    action: str,
    details: str,
    origin_server_id: Optional[str] = None,
    origin_server_name: str = "Direct Message",
    target_account_id: Optional[int] = None,
    send_fn: Optional[ChannelSendFn] = None,
    embed=None,
) -> None:
    """Write an audit log entry and optionally post an embed to the audit channel.

    Args:
        db:                  Database instance.
        actor_id:            Discord user ID of who performed the action.
        action:              Action type string (e.g. 'deposit', 'freeze').
        details:             Human-readable description.
        origin_server_id:    Guild ID string, or None for DMs.
        origin_server_name:  Guild name, or 'Direct Message'.
        target_account_id:   Account affected, if applicable.
        send_fn:             Async callable that sends an embed to the audit channel.
        embed:               discord.Embed to post. Only used if send_fn is provided.
    """
    now = utcnow().isoformat()

    await insert_audit_log(
        db=db,
        actor_id=actor_id,
        action=action,
        details=details,
        timestamp=now,
        target_account_id=target_account_id,
        origin_server_id=origin_server_id,
        origin_server_name=origin_server_name,
    )

    if send_fn and embed:
        try:
            await send_fn(embed=embed)
        except Exception as exc:
            log.error("Failed to post audit embed: %s", exc)


async def get_paginated_audit(
    db: Database,
    page: int = 0,
    page_size: int = 10,
    actor_id: Optional[int] = None,
    target_account_id: Optional[int] = None,
    origin_server_id: Optional[str] = None,
) -> tuple[list, int, int]:
    """Return a page of audit log entries plus total count and total pages.

    Returns:
        (rows, total_count, total_pages)
    """
    offset = page * page_size
    rows = await get_audit_log(
        db,
        limit=page_size,
        offset=offset,
        actor_id=actor_id,
        target_account_id=target_account_id,
        origin_server_id=origin_server_id,
    )
    total = await get_audit_log_count(
        db,
        actor_id=actor_id,
        target_account_id=target_account_id,
        origin_server_id=origin_server_id,
    )
    total_pages = max(1, (total + page_size - 1) // page_size)
    return rows, total, total_pages