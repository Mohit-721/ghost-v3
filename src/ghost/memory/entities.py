"""
Entity CRUD — project-scoped nodes in the knowledge graph.

Entity kinds: "file", "function", "class", "module", "insight", "tool", "project"

All writes go through the DatabaseWriter.
Reads happen directly on the db connection (WAL allows this).
"""

import hashlib
import json
import logging
import uuid

logger = logging.getLogger(__name__)


class EntityStore:
    def __init__(self, db: object, writer: object) -> None:
        self.db = db
        self.writer = writer

    async def create(
        self,
        project_id: str,
        kind: str,
        name: str,
        content: str | None = None,
        metadata: dict | None = None,
    ) -> str:
        """Create entity, return its ID."""
        entity_id = str(uuid.uuid4())
        content_hash = hashlib.sha256(content.encode()).hexdigest() if content else None
        meta_json = json.dumps(metadata or {})

        await self.writer.write(
            """INSERT INTO entities (id, project_id, kind, name, content, content_hash, metadata)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (entity_id, project_id, kind, name, content, content_hash, meta_json),
        )
        return entity_id

    async def get(self, entity_id: str) -> dict | None:
        """Get entity by ID. Returns None if not found or soft-deleted."""
        cursor = await self.db.execute(
            "SELECT * FROM entities WHERE id = ? AND deleted_at IS NULL",
            (entity_id,),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def get_by_name(self, project_id: str, kind: str, name: str) -> dict | None:
        """Get entity by project + kind + name. Returns None if not found."""
        cursor = await self.db.execute(
            """SELECT * FROM entities
               WHERE project_id = ? AND kind = ? AND name = ? AND deleted_at IS NULL""",
            (project_id, kind, name),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def update(
        self,
        entity_id: str,
        content: str | None = None,
        metadata: dict | None = None,
    ) -> None:
        """Update entity content and/or metadata."""
        parts = ["updated_at = datetime('now')"]
        params: list = []

        if content is not None:
            parts.append("content = ?")
            parts.append("content_hash = ?")
            params.extend([content, hashlib.sha256(content.encode()).hexdigest()])

        if metadata is not None:
            parts.append("metadata = ?")
            params.append(json.dumps(metadata))

        params.append(entity_id)

        await self.writer.write(
            f"UPDATE entities SET {', '.join(parts)} WHERE id = ?",
            tuple(params),
        )

    async def soft_delete(self, entity_id: str) -> None:
        """Soft delete — sets deleted_at timestamp."""
        await self.writer.write(
            "UPDATE entities SET deleted_at = datetime('now') WHERE id = ?",
            (entity_id,),
        )

    async def list_by_project(
        self,
        project_id: str,
        kind: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        """List entities for a project, optionally filtered by kind."""
        if kind:
            cursor = await self.db.execute(
                """SELECT * FROM entities
                   WHERE project_id = ? AND kind = ? AND deleted_at IS NULL
                   ORDER BY updated_at DESC LIMIT ?""",
                (project_id, kind, limit),
            )
        else:
            cursor = await self.db.execute(
                """SELECT * FROM entities
                   WHERE project_id = ? AND deleted_at IS NULL
                   ORDER BY updated_at DESC LIMIT ?""",
                (project_id, limit),
            )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def upsert_by_hash(
        self,
        project_id: str,
        kind: str,
        name: str,
        content: str,
        metadata: dict | None = None,
    ) -> str:
        """
        Insert or update based on content hash.

        If an entity with the same project/kind/name exists and content changed,
        update it. If content is the same (same hash), skip the write.
        Returns the entity ID.
        """
        existing = await self.get_by_name(project_id, kind, name)
        content_hash = hashlib.sha256(content.encode()).hexdigest()

        if existing:
            if existing["content_hash"] == content_hash:
                return existing["id"]  # No change — skip write
            await self.update(existing["id"], content=content, metadata=metadata)
            return existing["id"]
        else:
            return await self.create(project_id, kind, name, content, metadata)
