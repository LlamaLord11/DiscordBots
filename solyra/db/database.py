"""
db/database.py
--------------
Database connection management, worker queue, schema initialisation.
This is the only file that holds the aiosqlite connection.

All writes must go through the queue worker.
Reads (SELECT queries) may be executed directly via the read() helper.
"""

from __future__ import annotations

import asyncio
import logging
import aiosqlite
from typing import Any, Callable, Coroutine, Optional

log = logging.getLogger(__name__)

# ─── Schema ───────────────────────────────────────────────────────────────────

SCHEMA_SQL = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS accounts (
    account_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    account_name  TEXT    NOT NULL,
    account_type  TEXT    NOT NULL DEFAULT 'general',
    owner_id      INTEGER NOT NULL,
    balance       INTEGER NOT NULL DEFAULT 0,
    reserved_cents INTEGER NOT NULL DEFAULT 0,
    is_frozen     INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS account_users (
    account_id  INTEGER NOT NULL REFERENCES accounts(account_id) ON DELETE CASCADE,
    user_id     INTEGER NOT NULL,
    added_at    TEXT    NOT NULL,
    PRIMARY KEY (account_id, user_id)
);

CREATE TABLE IF NOT EXISTS transactions (
    transaction_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id      INTEGER NOT NULL REFERENCES accounts(account_id),
    type            TEXT    NOT NULL,
    amount          INTEGER NOT NULL,
    status          TEXT    NOT NULL DEFAULT 'pending',
    channel_id      TEXT,
    initiator_id    INTEGER,
    counterpart_id  INTEGER,
    processed_by    INTEGER,
    notes           TEXT,
    created_at      TEXT    NOT NULL,
    resolved_at     TEXT
);

CREATE TABLE IF NOT EXISTS interest_config (
    account_type      TEXT    PRIMARY KEY,
    rate_basis_points INTEGER NOT NULL DEFAULT 0,
    is_paused         INTEGER NOT NULL DEFAULT 0,
    last_applied      TEXT,
    remainder_cents   INTEGER NOT NULL DEFAULT 0,
    updated_by        INTEGER,
    updated_at        TEXT
);

CREATE TABLE IF NOT EXISTS audit_log (
    log_id            INTEGER PRIMARY KEY AUTOINCREMENT,
    actor_id          INTEGER NOT NULL,
    action            TEXT    NOT NULL,
    target_account_id INTEGER,
    details           TEXT    NOT NULL,
    origin_server_id  TEXT,
    origin_server_name TEXT   NOT NULL DEFAULT 'Direct Message',
    timestamp         TEXT    NOT NULL
);
"""

# ─── Database class ───────────────────────────────────────────────────────────

class Database:
    """Manages the aiosqlite connection and the single write worker queue.

    Usage:
        db = Database(path)
        await db.init()
        ...
        await db.close()

    Writing:
        await db.write(some_coroutine_factory)
        # or the helper:
        await db.execute("UPDATE ...", (params,))

    Reading:
        rows = await db.fetchall("SELECT ...", (params,))
        row  = await db.fetchone("SELECT ...", (params,))
    """

    def __init__(self, path: str) -> None:
        self.path = path
        self._conn: Optional[aiosqlite.Connection] = None
        self._queue: asyncio.Queue[Callable[[], Coroutine]] = asyncio.Queue()
        self._worker_task: Optional[asyncio.Task] = None
        self._ready = asyncio.Event()

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def init(self) -> None:
        """Open connection, apply schema, start worker."""
        self._conn = await aiosqlite.connect(self.path)
        self._conn.row_factory = aiosqlite.Row

        # Apply schema and PRAGMAs
        await self._conn.executescript(SCHEMA_SQL)
        await self._conn.commit()

        # Start background worker
        self._worker_task = asyncio.create_task(self._worker())
        self._ready.set()
        log.info("Database initialised at %s", self.path)

    async def close(self) -> None:
        """Drain the queue then close the connection."""
        if self._worker_task:
            await self._queue.join()
            self._worker_task.cancel()
        if self._conn:
            await self._conn.close()
        log.info("Database connection closed.")

    # ── Worker ────────────────────────────────────────────────────────────────

    async def _worker(self) -> None:
        """Single write worker — processes one operation at a time."""
        while True:
            coro_factory = await self._queue.get()
            try:
                await coro_factory()
            except Exception as exc:
                log.error("DB worker error: %s", exc, exc_info=True)
                # Worker continues — individual failures are logged but not fatal
            finally:
                self._queue.task_done()

    # ── Write interface ───────────────────────────────────────────────────────

    async def write(self, coro_factory: Callable[[], Coroutine]) -> None:
        """Enqueue a write operation. The factory is called by the worker."""
        await self._queue.put(coro_factory)

    async def execute(self, sql: str, params: tuple = ()) -> None:
        """Convenience: enqueue a single execute + commit."""
        async def _run():
            await self._conn.execute(sql, params)
            await self._conn.commit()
        await self.write(_run)

    async def execute_returning(self, sql: str, params: tuple = ()) -> asyncio.Future[Any]:
        """Enqueue a write that returns the lastrowid via a Future."""
        loop = asyncio.get_running_loop()
        future: asyncio.Future[int] = loop.create_future()

        async def _run():
            try:
                cursor = await self._conn.execute(sql, params)
                await self._conn.commit()
                future.set_result(cursor.lastrowid)
            except Exception as exc:
                future.set_exception(exc)

        await self.write(_run)
        return await future

    async def executemany(self, sql: str, params_list: list[tuple]) -> None:
        """Enqueue an executemany + commit."""
        async def _run():
            await self._conn.executemany(sql, params_list)
            await self._conn.commit()
        await self.write(_run)

    async def execute_script(self, sql: str) -> None:
        """Enqueue an executescript + commit (for multi-statement blocks)."""
        async def _run():
            await self._conn.executescript(sql)
            await self._conn.commit()
        await self.write(_run)

    # ── Read interface ────────────────────────────────────────────────────────
    # Reads go directly to the connection (WAL allows concurrent reads).

    async def fetchall(self, sql: str, params: tuple = ()) -> list[aiosqlite.Row]:
        """Execute a SELECT and return all rows."""
        async with self._conn.execute(sql, params) as cursor:
            return await cursor.fetchall()

    async def fetchone(self, sql: str, params: tuple = ()) -> Optional[aiosqlite.Row]:
        """Execute a SELECT and return one row, or None."""
        async with self._conn.execute(sql, params) as cursor:
            return await cursor.fetchone()

    async def fetchval(self, sql: str, params: tuple = (), default: Any = None) -> Any:
        """Execute a SELECT and return the first column of the first row."""
        row = await self.fetchone(sql, params)
        if row is None:
            return default
        return row[0]


# ─── Singleton accessor ───────────────────────────────────────────────────────

_db_instance: Optional[Database] = None


def get_db() -> Database:
    """Return the global Database instance. Must be initialised first."""
    if _db_instance is None:
        raise RuntimeError("Database has not been initialised. Call init_db() first.")
    return _db_instance


async def init_db(path: str) -> Database:
    """Initialise the global Database instance."""
    global _db_instance
    _db_instance = Database(path)
    await _db_instance.init()
    return _db_instance