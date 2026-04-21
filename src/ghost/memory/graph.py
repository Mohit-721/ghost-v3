"""
Edge CRUD and graph traversal.

Edges connect entities with typed relationships.
All edges are project-scoped implicitly (through their connected entities).
"""

import json
import logging
import uuid

logger = logging.getLogger(__name__)


class GraphStore:
    def __init__(self, db: object, writer: object) -> None:
        self.db = db
        self.writer = writer

    async def add_edge(
        self,
        source_id: str,
        target_id: str,
        relation: str,
        weight: float = 1.0,
        metadata: dict | None = None,
    ) -> str:
        """Create an edge between two entities. Returns edge ID."""
        edge_id = str(uuid.uuid4())
        await self.writer.write(
            """INSERT OR REPLACE INTO edges (id, source_id, target_id, relation, weight, metadata)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (edge_id, source_id, target_id, relation, weight, json.dumps(metadata or {})),
        )
        return edge_id

    async def get_edges_from(self, entity_id: str, relation: str | None = None) -> list[dict]:
        """Get all outgoing edges from an entity."""
        if relation:
            cursor = await self.db.execute(
                "SELECT * FROM edges WHERE source_id = ? AND relation = ?",
                (entity_id, relation),
            )
        else:
            cursor = await self.db.execute(
                "SELECT * FROM edges WHERE source_id = ?",
                (entity_id,),
            )
        return [dict(r) for r in await cursor.fetchall()]

    async def get_edges_to(self, entity_id: str, relation: str | None = None) -> list[dict]:
        """Get all incoming edges to an entity."""
        if relation:
            cursor = await self.db.execute(
                "SELECT * FROM edges WHERE target_id = ? AND relation = ?",
                (entity_id, relation),
            )
        else:
            cursor = await self.db.execute(
                "SELECT * FROM edges WHERE target_id = ?",
                (entity_id,),
            )
        return [dict(r) for r in await cursor.fetchall()]

    async def get_neighbors(self, entity_id: str, depth: int = 1, limit: int = 50) -> list[dict]:
        """
        Get neighboring entities up to N hops away.
        Returns entities (not edges) with their shortest distance.
        """
        visited: set[str] = {entity_id}
        current_layer = [entity_id]
        results: list[dict] = []

        for d in range(depth):
            next_layer: list[str] = []
            for eid in current_layer:
                # Outgoing neighbors
                cursor = await self.db.execute(
                    """SELECT e.*, ed.relation, ed.weight
                       FROM entities e
                       JOIN edges ed ON e.id = ed.target_id
                       WHERE ed.source_id = ? AND e.deleted_at IS NULL""",
                    (eid,),
                )
                for row in await cursor.fetchall():
                    row_dict = dict(row)
                    if row_dict["id"] not in visited:
                        visited.add(row_dict["id"])
                        row_dict["_distance"] = d + 1
                        results.append(row_dict)
                        next_layer.append(row_dict["id"])

                # Incoming neighbors
                cursor = await self.db.execute(
                    """SELECT e.*, ed.relation, ed.weight
                       FROM entities e
                       JOIN edges ed ON e.id = ed.source_id
                       WHERE ed.target_id = ? AND e.deleted_at IS NULL""",
                    (eid,),
                )
                for row in await cursor.fetchall():
                    row_dict = dict(row)
                    if row_dict["id"] not in visited:
                        visited.add(row_dict["id"])
                        row_dict["_distance"] = d + 1
                        results.append(row_dict)
                        next_layer.append(row_dict["id"])

            current_layer = next_layer
            if len(results) >= limit:
                break

        return results[:limit]

    async def remove_edges_for(self, entity_id: str) -> int:
        """Remove all edges involving an entity. Returns count removed."""
        result = await self.writer.write(
            "DELETE FROM edges WHERE source_id = ? OR target_id = ?",
            (entity_id, entity_id),
        )
        return len(result) if result else 0

    async def search_related(self, query: str, project_id: str, limit: int = 20) -> list[dict]:
        """
        Find entities related to a query using FTS5 + graph expansion.
        1. FTS5 search for matching entities
        2. Expand via graph neighbors (1-hop)
        3. Return combined, deduplicated results
        """
        # Step 1: FTS5 search
        try:
            cursor = await self.db.execute(
                """SELECT e.*, rank
                   FROM entities_fts fts
                   JOIN entities e ON e.rowid = fts.rowid
                   WHERE entities_fts MATCH ? AND e.project_id = ? AND e.deleted_at IS NULL
                   ORDER BY rank
                   LIMIT ?""",
                (query, project_id, limit),
            )
            fts_results = [dict(r) for r in await cursor.fetchall()]
        except Exception as e:
            logger.warning(f"FTS search failed in graph.search_related: {e}")
            fts_results = []

        # Step 2: Expand via 1-hop neighbors (top 5 only)
        all_results: dict[str, dict] = {r["id"]: r for r in fts_results}
        for r in fts_results[:5]:
            neighbors = await self.get_neighbors(r["id"], depth=1, limit=10)
            for n in neighbors:
                if n["id"] not in all_results:
                    all_results[n["id"]] = n

        return list(all_results.values())[:limit]
