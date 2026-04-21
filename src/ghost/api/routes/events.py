"""WebSocket event stream (for live monitoring)."""

import asyncio
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter(tags=["events"])


@router.websocket("/events")
async def event_stream(websocket: WebSocket) -> None:
    """WebSocket endpoint for live event streaming."""
    await websocket.accept()

    event_bus = websocket.app.state.event_bus
    event_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

    # Subscribe to all events
    async def handler(event: Any) -> None:
        await event_queue.put(
            {
                "topic": event.topic,
                "payload": event.payload,
                "id": event.id,
                "timestamp": event.timestamp.isoformat(),
            }
        )

    event_bus.subscribe("*", handler)

    try:
        while True:
            event_data = await event_queue.get()
            await websocket.send_json(event_data)
    except WebSocketDisconnect:
        event_bus.unsubscribe("*", handler)
    except Exception:
        event_bus.unsubscribe("*", handler)


@router.get("/logs")
async def get_audit_logs(
    request: Any = None, topic: str | None = None, limit: int = 50
) -> list[dict[str, Any]]:
    """Get audit log entries."""
    # Access via dependency injection
    audit = request.app.state.audit
    logs = await audit.query(topic=topic, limit=limit)
    return logs
