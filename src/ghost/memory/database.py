"""
SQLite connection management.

Key design decisions:
- WAL mode for concurrent reads with single writer
- All pragmas applied on connection open
- Integrity check on startup with automatic recovery (archive corrupt DB)
"""
import logging
import time
from pathlib import Path

import aiosqlite

from ghost.constants import DB_PRAGMAS

logger = logging.getLogger(__name__)


async def get_connection(db_path: Path) -> aiosqlite.Connection:
    """
    Open a configured SQLite connection.

    Applies all pragmas from constants.DB_PRAGMAS.
    WAL mode allows concurrent reads while DatabaseWriter handles all writes.
    """
    db = await aiosqlite.connect(str(db_path))
    db.row_factory = aiosqlite.Row

    for pragma, value in DB_PRAGMAS.items():
        if isinstance(value, bool):
            value = int(value)
        await db.execute(f"PRAGMA {pragma} = {value};")

    return db


def check_integrity(db_path: Path) -> bool:
    """
    Synchronous integrity check run BEFORE async operations start.

    If corrupt: archives the DB file (renames to .corrupt.<timestamp>) and
    returns False so the caller can proceed with fresh DB creation.

    Gap #7 from final_gaps_analysis.md: automatic archive on corruption.
    """
    import sqlite3

    if not db_path.exists():
        return True  # No DB yet — will be created by migrations

    try:
        conn = sqlite3.connect(str(db_path))
        result = conn.execute("PRAGMA integrity_check;").fetchone()
        conn.close()

        if result[0] == "ok":
            return True

        # Corruption detected — archive the corrupt file
        corrupt_path = db_path.with_suffix(f".corrupt.{int(time.time())}")
        db_path.rename(corrupt_path)
        logger.error(
            f"Database corruption detected. "
            f"Corrupt file archived to {corrupt_path}. "
            f"Ghost will rebuild from scratch."
        )
        return False

    except Exception as e:
        logger.error(f"Cannot open database: {e}")
        try:
            corrupt_path = db_path.with_suffix(f".corrupt.{int(time.time())}")
            db_path.rename(corrupt_path)
        except Exception:
            pass
        return False
