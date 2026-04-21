"""
Unified search combining FTS5, graph traversal, and optional vector search.

Uses Reciprocal Rank Fusion (RRF) to merge results from different sources
into a single scored list without needing to normalize individual scores.
"""
import logging

logger = logging.getLogger(__name__)

# RRF constant (standard value from the 2009 paper)
RRF_K = 60


class UnifiedSearch:
    def __init__(
        self, db: object, graph_store: object, vector_store: object | None = None
    ) -> None:
        self.db = db
        self.graph = graph_store
        self.vectors = vector_store

    async def search(
        self,
        query: str,
        project_id: str,
        limit: int = 20,
        query_embedding: list[float] | None = None,
    ) -> list[dict]:
        """
        Multi-source search with RRF fusion.

        1. FTS5 text search
        2. Graph-based related entity search
        3. Vector similarity search (if available + embedding provided)
        4. Fuse with Reciprocal Rank Fusion
        """
        # Source 1: FTS5
        fts_results = await self._fts_search(query, project_id, limit=limit * 2)

        # Source 2: Graph
        graph_results = await self.graph.search_related(
            query, project_id, limit=limit * 2
        )

        # Source 3: Vectors (optional)
        vector_results: list[dict] = []
        if self.vectors and self.vectors.available and query_embedding:
            vector_results = await self.vectors.search(
                query_embedding, limit=limit * 2
            )

        # Fuse results with RRF
        scores: dict[str, float] = {}
        entity_data: dict[str, dict] = {}

        for rank, result in enumerate(fts_results):
            eid = result["id"]
            scores[eid] = scores.get(eid, 0) + 1.0 / (RRF_K + rank + 1)
            entity_data[eid] = result

        for rank, result in enumerate(graph_results):
            eid = result["id"]
            scores[eid] = scores.get(eid, 0) + 1.0 / (RRF_K + rank + 1)
            entity_data[eid] = result

        for rank, result in enumerate(vector_results):
            eid = result.get("entity_id", result.get("id", ""))
            if eid:
                scores[eid] = scores.get(eid, 0) + 1.0 / (RRF_K + rank + 1)
                # Vector results may not have full entity data — that's OK

        # Sort by fused score, take top `limit`
        sorted_ids = sorted(scores, key=lambda x: scores[x], reverse=True)[:limit]

        results = []
        for eid in sorted_ids:
            if eid in entity_data:
                entry = entity_data[eid].copy()
                entry["_rrf_score"] = scores[eid]
                results.append(entry)

        return results

    async def _fts_search(
        self, query: str, project_id: str, limit: int = 40
    ) -> list[dict]:
        """Full-text search via FTS5."""
        try:
            cursor = await self.db.execute(
                """SELECT e.*, rank as _fts_rank
                   FROM entities_fts fts
                   JOIN entities e ON e.rowid = fts.rowid
                   WHERE entities_fts MATCH ? AND e.project_id = ? AND e.deleted_at IS NULL
                   ORDER BY rank
                   LIMIT ?""",
                (query, project_id, limit),
            )
            return [dict(r) for r in await cursor.fetchall()]
        except Exception as e:
            logger.warning(f"FTS search failed: {e}")
            return []
