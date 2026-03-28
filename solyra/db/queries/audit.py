"""
db/queries/audit.py
-------------------
All SQL touching the audit_log table.
"""

from __future__ import annotations
from typing import Optional
from ..database import Database


async def insert_audit_log(
    db: Database,
    actor_id: int,
    action: str,
    details: str,
    timestamp: str,
    target_account_id: Optional[int] = None,
    origin_server_id: Optional[str] = None,
    origin_server_name: str = "Direct Message",
) -> None:
    await db.execute(
        """
        INSERT INTO audit_log
            (actor_id, action, target_account_id, details,
             origin_server_id, origin_server_name, timestamp)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (actor_id, action, target_account_id, details,
         origin_server_id, origin_server_name, timestamp),
    )


async def get_audit_log(
    db: Database,
    limit: int = 200,
    offset: int = 0,
    actor_id: Optional[int] = None,
    target_account_id: Optional[int] = None,
    origin_server_id: Optional[str] = None,
) -> list:
    """Fetch audit log entries with optional filters."""
    conditions = []
    params: list = []

    if actor_id is not None:
        conditions.append("actor_id = ?")
        params.append(actor_id)
    if target_account_id is not None:
        conditions.append("target_account_id = ?")
        params.append(target_account_id)
    if origin_server_id is not None:
        if origin_server_id.lower() == "dm":
            conditions.append("origin_server_id IS NULL")
        else:
            conditions.append("origin_server_id = ?")
            params.append(origin_server_id)

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    params += [limit, offset]

    return await db.fetchall(
        f"""
        SELECT * FROM audit_log
        {where}
        ORDER BY timestamp DESC
        LIMIT ? OFFSET ?
        """,
        tuple(params),
    )


async def get_audit_log_count(
    db: Database,
    actor_id: Optional[int] = None,
    target_account_id: Optional[int] = None,
    origin_server_id: Optional[str] = None,
) -> int:
    """Count audit log entries with optional filters (for pagination)."""
    conditions = []
    params: list = []

    if actor_id is not None:
        conditions.append("actor_id = ?")
        params.append(actor_id)
    if target_account_id is not None:
        conditions.append("target_account_id = ?")
        params.append(target_account_id)
    if origin_server_id is not None:
        if origin_server_id.lower() == "dm":
            conditions.append("origin_server_id IS NULL")
        else:
            conditions.append("origin_server_id = ?")
            params.append(origin_server_id)

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    return await db.fetchval(
        f"SELECT COUNT(*) FROM audit_log {where}",
        tuple(params),
        default=0,
    )