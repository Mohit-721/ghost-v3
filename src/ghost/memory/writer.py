"""
Single-writer pattern for SQLite.

ALL writes to the database go through this queue.
Readers can read directly (WAL mode allows concurrent reads).
This eliminates lock contention entirely.

Architecture:
- Any module can call writer.write() or writer.enqueue()
- All writes are processed sequentially by a single consumer coroutine
- writer.write() returns the result (awaits completion)
- writer.enqueue() is fire-and-forget (no result needed)
- writer.stop() sends a sentinel None and waits for drain

BUG FIX (Bug #2 from final_bug_sweep.md):
Consumer uses `while True` + sentinel-only exit, NOT
`while self._running or not self._queue.empty()` which has a race condition
where items enqueued during shutdown are silently dropped.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class WriteOp:
    """A single database write operation."""

    sql: str
    params: tuple[Any, ...] = field(default_factory=tuple)
    many: bool = False  # If True, use executemany
    future: asyncio.Future | None = None  # For callers that need the result
    _is_script: bool = False  # For multi-statement SQL scripts


class DatabaseWriter:
    """
    Single async consumer that processes all DB writes sequentially.

    Usage:
        writer = DatabaseWriter(db)
        await writer.start()

        # From any module (concurrency-safe):
        result = await writer.write("INSERT INTO ... RETURNING id", (val1, val2))

        # Or fire-and-forget:
        writer.enqueue("INSERT INTO audit_log ...", (val1,))

        # Shutdown:
        await writer.stop()  # Drains queue first
    """

    def __init__(self, db: Any) -> None:
        self.db = db
        self._queue: asyncio.Queue[WriteOp | None] = asyncio.Queue()
        self._task: asyncio.Task | None = None
        self._started = False

    async def start(self) -> None:
        """Start the writer consumer loop."""
        if self._started:
            return
        self._started = True
        self._task = asyncio.create_task(self._consumer(), name="db-writer")

    async def stop(self) -> None:
        """Drain queue and stop. Blocks until all pending writes complete."""
        if not self._started:
            return
        self._started = False
        # Send sentinel to unblock the consumer
        await self._queue.put(None)
        if self._task:
            await self._task
            self._task = None

    async def write(self, sql: str, params: tuple = (), many: bool = False) -> Any:
        """Write with result — awaits completion and returns cursor results."""
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        await self._queue.put(WriteOp(sql=sql, params=params, many=many, future=future))
        return await future

    def enqueue(self, sql: str, params: tuple = (), many: bool = False) -> None:
        """Fire-and-forget write — no result, no blocking."""
        try:
            self._queue.put_nowait(WriteOp(sql=sql, params=params, many=many))
        except asyncio.QueueFull:
            logger.error(f"Write queue full, dropping: {sql[:80]}")

    async def execute_script(self, sql: str) -> None:
        """Execute a multi-statement SQL script (for migrations)."""
        future = asyncio.get_running_loop().create_future()
        op = WriteOp(sql=sql, params=(), many=False, future=future, _is_script=True)
        await self._queue.put(op)
        return await future

    async def _consumer(self) -> None:
        """
        Process writes until sentinel None is received.

        BUG FIX (Bug #2 from final_bug_sweep.md):
        Uses `while True` + sentinel-only exit. The old pattern
        `while self._running or not self._queue.empty()` had a race condition:
        if an item was enqueued after the running flag was set to False but before
        the queue-empty check passed, that item would be silently dropped.
        """
        while True:
            op = await self._queue.get()
            if op is None:
                # Sentinel received — flush remaining and exit
                self._queue.task_done()
                break
            try:
                if op._is_script:
                    await self.db.executescript(op.sql)
                    await self.db.commit()
                    if op.future and not op.future.done():
                        op.future.set_result(None)
                elif op.many:
                    await self.db.executemany(op.sql, op.params)
                    await self.db.commit()
                    if op.future and not op.future.done():
                        op.future.set_result(None)
                else:
                    cursor = await self.db.execute(op.sql, op.params)
                    result = await cursor.fetchall()
                    await self.db.commit()
                    if op.future and not op.future.done():
                        op.future.set_result(result)
            except Exception as e:
                if op.future and not op.future.done():
                    op.future.set_exception(e)
                else:
                    logger.exception(f"Write failed (fire-and-forget): {op.sql[:100]}")
            finally:
                self._queue.task_done()

    @property
    def pending_count(self) -> int:
        """Number of writes waiting in queue."""
        return self._queue.qsize()
