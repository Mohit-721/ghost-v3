"""
Vector storage and similarity search.

Uses sqlite-vec if available, gracefully falls back to no vector search.
When sqlite-vec is unavailable, search.py falls back to FTS5-only.
"""
import json
import logging

logger = logging.getLogger(__name__)

_HAS_SQLITE_VEC = False


def check_sqlite_vec(db_path: object) -> bool:
    """
    Check if sqlite-vec extension is available on this system.
    Sets the module-level flag used by VectorStore instances.
    """
    global _HAS_SQLITE_VEC
    import sqlite3

    try:
        conn = sqlite3.connect(str(db_path))
        conn.enable_load_extension(True)
        conn.load_extension("vec0")
        conn.close()
        _HAS_SQLITE_VEC = True
        logger.info("sqlite-vec extension loaded successfully — vector search enabled")
        return True
    except Exception as e:
        logger.info(f"sqlite-vec not available: {e}. Vector search disabled.")
        _HAS_SQLITE_VEC = False
        return False


class VectorStore:
    """Vector storage with sqlite-vec. All methods are no-ops if extension unavailable."""

    def __init__(self, db: object, writer: object) -> None:
        self.db = db
        self.writer = writer
        self.available = _HAS_SQLITE_VEC

    async def store(self, entity_id: str, embedding: list[float]) -> None:
        """Store a vector embedding for an entity."""
        if not self.available:
            return

        await self.writer.write(
            "INSERT OR REPLACE INTO entity_vectors (entity_id, embedding) VALUES (?, ?)",
            (entity_id, json.dumps(embedding)),
        )

    async def search(
        self, query_embedding: list[float], limit: int = 20
    ) -> list[dict]:
        """Find nearest neighbors by cosine similarity."""
        if not self.available:
            return []

        cursor = await self.db.execute(
            """SELECT entity_id, distance
               FROM entity_vectors
               WHERE embedding MATCH ?
               ORDER BY distance
               LIMIT ?""",
            (json.dumps(query_embedding), limit),
        )
        return [dict(r) for r in await cursor.fetchall()]

    async def delete(self, entity_id: str) -> None:
        """Remove vector for an entity."""
        if not self.available:
            return
        await self.writer.write(
            "DELETE FROM entity_vectors WHERE entity_id = ?",
            (entity_id,),
        )
