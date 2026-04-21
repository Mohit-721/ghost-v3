"""Tool management endpoints."""

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from ghost.api.schemas import ToolRunRequest, ToolRunResponse

router = APIRouter(tags=["tools"])


@router.get("/tools")
async def list_tools(request: Request, status: str | None = None) -> list[dict[str, Any]]:
    """List tools, optionally filtered by status."""
    if status == "quarantined":
        return await request.app.state.quarantine.list_pending()
    return await request.app.state.registry.list_all(status=status)


@router.post("/tools/{tool_id}/approve")
async def approve_tool(tool_id: str, request: Request) -> dict[str, Any]:
    """Approve a quarantined tool."""
    result = await request.app.state.quarantine.approve(tool_id)
    if not result:
        raise HTTPException(status_code=404, detail="Tool not found or not quarantined")
    # Register it
    registered = await request.app.state.registry.register(tool_id)
    return registered or result


@router.post("/tools/{tool_id}/reject")
async def reject_tool(tool_id: str, request: Request) -> dict[str, str]:
    """Reject a quarantined tool."""
    success = await request.app.state.quarantine.reject(tool_id)
    if not success:
        raise HTTPException(status_code=404, detail="Tool not found or not quarantined")
    return {"status": "rejected", "tool_id": tool_id}


@router.post("/tools/{name}/run", response_model=ToolRunResponse)
async def run_tool(name: str, req: ToolRunRequest, request: Request) -> ToolRunResponse:
    """Run a registered tool."""
    tool = await request.app.state.registry.get_current(name)
    if not tool:
        raise HTTPException(status_code=404, detail=f"Tool '{name}' not found")

    project_dir = Path(req.project_dir) if req.project_dir else None

    async def _execute() -> Any:
        return await request.app.state.executor.execute(
            tool_path=Path(tool["file_path"]),
            args=req.args,
            project_dir=project_dir,
        )

    result = await request.app.state.task_manager.submit_exec_task(_execute())

    # Record the run
    await request.app.state.registry.record_run(tool["id"])

    return ToolRunResponse(
        exit_code=result.exit_code,
        stdout=result.stdout,
        stderr=result.stderr,
        timed_out=result.timed_out,
        used_uv=result.used_uv,
    )
