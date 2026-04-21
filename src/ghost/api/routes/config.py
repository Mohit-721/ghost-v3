"""Dynamic configuration endpoints."""

from fastapi import APIRouter, Request

from ghost.api.schemas import LogLevelRequest

router = APIRouter(tags=["config"])


@router.post("/config/log-level")
async def set_log_level_route(req: LogLevelRequest, request: Request) -> dict[str, str]:
    """Dynamically change the daemon's log level."""
    from ghost.core.logging import set_log_level

    level = req.level.upper()
    if level not in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
        return {"error": f"Invalid log level: {level}"}

    set_log_level(level)
    return {"status": "ok", "log_level": level}
