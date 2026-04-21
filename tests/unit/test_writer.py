"""
Unit tests for ghost.memory.writer.DatabaseWriter.
"""

import asyncio

import aiosqlite
import pytest

from ghost.memory.writer import DatabaseWriter


@pytest.fixture
async def db_and_writer(tmp_path):
    """Create an in-memory SQLite DB and a started DatabaseWriter."""
    db = await aiosqlite.connect(":memory:")
    db.row_factory = aiosqlite.Row
    await db.execute("CREATE TABLE test (id INTEGER PRIMARY KEY AUTOINCREMENT, val TEXT)")
    await db.commit()
    writer = DatabaseWriter(db)
    await writer.start()
    yield db, writer
    await writer.stop()
    await db.close()


# ─── Basic Write ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_write_returns_result(db_and_writer):
    """write() returns the row result from the DB."""
    db, writer = db_and_writer
    result = await writer.write("INSERT INTO test (val) VALUES (?)", ("hello",))
    # SQLite returns [] for INSERT without RETURNING — just check no exception
    assert result is not None


@pytest.mark.asyncio
async def test_write_data_persists(db_and_writer):
    """Data written via write() is readable from the DB."""
    db, writer = db_and_writer
    await writer.write("INSERT INTO test (val) VALUES (?)", ("ghost",))
    cursor = await db.execute("SELECT val FROM test")
    row = await cursor.fetchone()
    assert row["val"] == "ghost"


# ─── Fire-and-Forget ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_enqueue_is_fire_and_forget(db_and_writer):
    """enqueue() does not block — call returns immediately."""
    db, writer = db_and_writer
    # enqueue is synchronous (no await)
    writer.enqueue("INSERT INTO test (val) VALUES (?)", ("queued",))
    # Wait for queue to drain
    await asyncio.sleep(0.05)
    cursor = await db.execute("SELECT val FROM test")
    row = await cursor.fetchone()
    assert row["val"] == "queued"


# ─── Concurrent Safety ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_multiple_concurrent_writes_are_serialized(db_and_writer):
    """Multiple concurrent write() calls all succeed without corruption."""
    db, writer = db_and_writer
    tasks = [
        asyncio.create_task(writer.write("INSERT INTO test (val) VALUES (?)", (f"item_{i}",)))
        for i in range(20)
    ]
    await asyncio.gather(*tasks)
    cursor = await db.execute("SELECT COUNT(*) FROM test")
    row = await cursor.fetchone()
    assert row[0] == 20


# ─── Shutdown ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_stop_drains_pending_writes():
    """stop() drains all pending writes before exiting (Bug #2 fix)."""
    db = await aiosqlite.connect(":memory:")
    db.row_factory = aiosqlite.Row
    await db.execute("CREATE TABLE test (id INTEGER PRIMARY KEY AUTOINCREMENT, val TEXT)")
    await db.commit()
    writer = DatabaseWriter(db)
    await writer.start()

    # Enqueue many fire-and-forget writes
    for i in range(50):
        writer.enqueue("INSERT INTO test (val) VALUES (?)", (f"item_{i}",))

    # stop() must drain them all
    await writer.stop()

    cursor = await db.execute("SELECT COUNT(*) FROM test")
    row = await cursor.fetchone()
    assert row[0] == 50

    await db.close()


# ─── Error Handling ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_exception_in_write_sets_future_exception(db_and_writer):
    """A bad SQL propagates as an exception to the awaiting caller."""
    db, writer = db_and_writer
    with pytest.raises(Exception):
        await writer.write("INSERT INTO nonexistent_table (x) VALUES (?)", ("x",))


@pytest.mark.asyncio
async def test_enqueue_exception_is_logged_not_raised(db_and_writer, caplog):
    """A bad SQL passed via enqueue() is logged but doesn't crash the bus."""

    db, writer = db_and_writer
    writer.enqueue("INSERT INTO nonexistent_table (x) VALUES (?)", ("x",))
    await asyncio.sleep(0.1)
    # The writer should still be alive
    assert writer._started is True


# ─── Sentinel / Bug #2 ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sentinel_stops_consumer():
    """Sending None sentinel via stop() terminates the consumer task (Bug #2 fix)."""
    db = await aiosqlite.connect(":memory:")
    db.row_factory = aiosqlite.Row
    writer = DatabaseWriter(db)
    await writer.start()
    assert writer._task is not None
    assert not writer._task.done()

    await writer.stop()

    assert writer._task is None or writer._task.done()
    await db.close()


# ─── Pending Count ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_pending_count_reflects_queue_size():
    """pending_count reflects the number of items currently in the queue."""
    db = await aiosqlite.connect(":memory:")
    db.row_factory = aiosqlite.Row
    await db.execute("CREATE TABLE test (id INTEGER PRIMARY KEY AUTOINCREMENT, val TEXT)")
    await db.commit()

    writer = DatabaseWriter(db)
    # Don't start the writer — items accumulate in the queue
    writer.enqueue("INSERT INTO test (val) VALUES (?)", ("a",))
    writer.enqueue("INSERT INTO test (val) VALUES (?)", ("b",))
    writer.enqueue("INSERT INTO test (val) VALUES (?)", ("c",))

    assert writer.pending_count == 3

    await db.close()
