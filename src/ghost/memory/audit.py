"""
Audit log — semantic event logging.

Records WHAT Ghost did (not HOW — that's the operational log).
Examples: "tool forged", "entity created", "insight generated".

All writes go through DatabaseWriter (fire-and-forget).
"""

import json
import logging
import uuid

logger = logging.getLogger(__name__)


class AuditLog:
    def __init__(self, db: object, writer: object) -> None:
        self.db = db
        self.writer = writer

    def log(
        self,
        topic: str,
        payload: dict | None = None,
        causation_id: str | None = None,
    ) -> None:
        """
        Record an audit event. Fire-and-forget (non-blocking).

        Args:
            topic: Dotted event topic (e.g., "forge.completed")
            payload: Event data as dict
            causation_id: ID of the event that caused this one
        """
        event_id = str(uuid.uuid4())
        self.writer.enqueue(
            """INSERT INTO audit_log (id, topic, payload, causation_id)
               VALUES (?, ?, ?, ?)""",
            (event_id, topic, json.dumps(payload or {}), causation_id),
        )

    async def query(
        self,
        topic: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict]:
        """Query audit log entries, most recent first."""
        if topic:
            cursor = await self.db.execute(
                """SELECT * FROM audit_log
                   WHERE topic = ?
                   ORDER BY created_at DESC
                   LIMIT ? OFFSET ?""",
                (topic, limit, offset),
            )
        else:
            cursor = await self.db.execute(
                """SELECT * FROM audit_log
                   ORDER BY created_at DESC
                   LIMIT ? OFFSET ?""",
                (limit, offset),
            )
        rows = await cursor.fetchall()
        results = []
        for r in rows:
            d = dict(r)
            d["payload"] = json.loads(d["payload"]) if d["payload"] else {}
            results.append(d)
        return results

    async def prune(self, days: int = 30) -> int:
        """Delete audit entries older than N days. Returns count deleted."""
        result = await self.writer.write(
            "DELETE FROM audit_log WHERE created_at < datetime('now', ?)",
            (f"-{days} days",),
        )
        count = len(result) if result else 0
        if count:
            logger.info(f"Pruned {count} audit log entries older than {days} days")
        return count

    async def count(self) -> int:
        """Total number of audit entries."""
        cursor = await self.db.execute("SELECT COUNT(*) FROM audit_log")
        row = await cursor.fetchone()
        return row[0]
