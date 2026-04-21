"""Health and status endpoints."""

import asyncio
import os

from fastapi import APIRouter, Request

from ghost.core.health import get_health_status

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(request: Request) -> dict[str, str | int]:
    """Get daemon health status."""
    return get_health_status(request.app)


@router.post("/shutdown")
async def shutdown(request: Request) -> dict[str, str]:
    """Initiate graceful shutdown."""
    # Schedule shutdown after responding
    loop = asyncio.get_event_loop()
    loop.call_later(0.5, lambda: os.kill(os.getpid(), __import__("signal").SIGTERM))
    return {"message": "Shutting down..."}
