"""
Intent queue — buffer for LLM requests when the API is unavailable.

When the LLM returns 429/503/timeout, intents are queued in SQLite
and drained when the API becomes available again.
"""
import json
import logging
import uuid
from collections.abc import Callable, Coroutine
from typing import Any

logger = logging.getLogger(__name__)


class IntentQueue:
    """Persistent intent queue backed by SQLite."""

    def __init__(self, db: Any, writer: Any) -> None:
        self.db = db
        self.writer = writer

    async def enqueue(self, payload: dict[str, Any]) -> str:
        """
        Add an intent to the queue.

        Returns:
            Intent ID
        """
        intent_id = str(uuid.uuid4())
        await self.writer.write(
            "INSERT INTO intent_queue (id, payload) VALUES (?, ?)",
            (intent_id, json.dumps(payload))
        )
        payload_type = payload.get("type", "unknown")
        logger.info(f"Intent queued: {intent_id} (type: {payload_type})")
        return intent_id

    async def get_pending(self, limit: int = 10) -> list[dict[str, Any]]:
        """Get pending intents in FIFO order."""
        cursor = await self.db.execute(
            """SELECT * FROM intent_queue
               WHERE status = 'pending'
               ORDER BY created_at ASC
               LIMIT ?""",
            (limit,)
        )
        rows = await cursor.fetchall()
        results = []
        for r in rows:
            d = dict(r)
            d["payload"] = json.loads(d["payload"])
            results.append(d)
        return results

    async def mark_completed(self, intent_id: str) -> None:
        """Mark an intent as completed."""
        await self.writer.write(
            """UPDATE intent_queue
               SET status = 'completed', completed_at = datetime('now')
               WHERE id = ?""",
            (intent_id,)
        )

    async def mark_failed(self, intent_id: str, error: str) -> None:
        """Mark an intent as failed."""
        await self.writer.write(
            """UPDATE intent_queue
               SET status = 'failed', error = ?, completed_at = datetime('now')
               WHERE id = ?""",
            (error, intent_id)
        )

    async def pending_count(self) -> int:
        """Number of pending intents."""
        cursor = await self.db.execute(
            "SELECT COUNT(*) FROM intent_queue WHERE status = 'pending'"
        )
        row = await cursor.fetchone()
        return row[0]

    async def drain(self, processor: Callable[[dict[str, Any]], Coroutine[Any, Any, Any]]) -> int:
        """
        Process all pending intents.

        Args:
            processor: async callable(payload) -> result

        Returns:
            Number of intents processed
        """
        pending = await self.get_pending(limit=50)
        processed = 0

        for intent in pending:
            try:
                await processor(intent["payload"])
                await self.mark_completed(intent["id"])
                processed += 1
            except Exception as e:
                logger.error(f"Failed to process intent {intent['id']}: {e}")
                await self.mark_failed(intent["id"], str(e))

        if processed:
            logger.info(f"Drained {processed} intents from queue")
        return processed
