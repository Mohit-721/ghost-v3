"""Tool synthesis endpoints."""

from fastapi import APIRouter, HTTPException, Request

from ghost.api.schemas import ForgeRequest, ForgeResponse

router = APIRouter(tags=["forge"])


@router.post("/forge", response_model=ForgeResponse)
async def forge_tool(req: ForgeRequest, request: Request) -> ForgeResponse:
    """Synthesize a new tool from natural language."""
    try:
        result = await request.app.state.forge.forge(
            intent=req.intent,
            project_id=req.project_id,
        )
        return ForgeResponse(**result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
