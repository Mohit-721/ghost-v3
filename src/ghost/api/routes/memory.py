"""Memory/knowledge graph endpoints."""

from typing import Any

from fastapi import APIRouter, Request

from ghost.api.schemas import MemorySearchRequest

router = APIRouter(tags=["memory"])


@router.post("/memory/search")
async def search_memory(req: MemorySearchRequest, request: Request) -> list[dict[str, Any]]:
    """Search the knowledge graph."""
    results = await request.app.state.search.search(
        query=req.query,
        project_id=req.project_id or "",
        limit=req.limit,
    )
    return results


@router.get("/memory/stats")
async def memory_stats(request: Request) -> dict[str, int]:
    """Get memory statistics."""
    db = request.app.state.db

    entity_count = (
        await (
            await db.execute("SELECT COUNT(*) FROM entities WHERE deleted_at IS NULL")
        ).fetchone()
    )[0]
    edge_count = (await (await db.execute("SELECT COUNT(*) FROM edges")).fetchone())[0]
    project_count = (await (await db.execute("SELECT COUNT(*) FROM projects")).fetchone())[0]
    tool_count = (await (await db.execute("SELECT COUNT(*) FROM tools")).fetchone())[0]

    return {
        "entities": entity_count,
        "edges": edge_count,
        "projects": project_count,
        "tools": tool_count,
    }
