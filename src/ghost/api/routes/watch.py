"""Watch directory management endpoints."""

import uuid

from fastapi import APIRouter, Request

from ghost.api.schemas import WatchRequest

router = APIRouter(tags=["watch"])


@router.post("/watch")
async def watch_directory(req: WatchRequest, request: Request) -> dict[str, str]:
    """Start watching a directory."""
    # In Phase 1, we just register in DB. Phase 2 adds actual watchfiles integration.
    writer = request.app.state.writer

    project_id = str(uuid.uuid4())
    project_name = req.project_name or req.path.split("/")[-1]

    await writer.write(
        "INSERT OR IGNORE INTO projects (id, name, root_path) VALUES (?, ?, ?)",
        (project_id, project_name, req.path),
    )
    await writer.write(
        "INSERT OR IGNORE INTO watched_dirs (path, project_id) VALUES (?, ?)",
        (req.path, project_id),
    )

    return {"status": "watching", "path": req.path, "project_id": project_id}


@router.delete("/watch")
async def unwatch_directory(path: str, request: Request) -> dict[str, str]:
    """Stop watching a directory."""
    writer = request.app.state.writer
    await writer.write("DELETE FROM watched_dirs WHERE path = ?", (path,))
    return {"status": "unwatched", "path": path}
