"""
Health endpoint logic and suspend detection.

The SuspendDetector monitors monotonic clock drift to detect system
suspend/resume (the laptop lid problem). When resume is detected,
it triggers a reconciliation scan.
"""

import asyncio
import logging
import os
import time
from collections.abc import Callable, Coroutine
from typing import Any

from ghost.constants import VERSION

logger = logging.getLogger(__name__)


class SuspendDetector:
    """Detects system suspend/resume by monitoring monotonic clock drift."""

    def __init__(self, check_interval: float = 10.0, threshold: float = 30.0) -> None:
        self.check_interval = check_interval
        self.threshold = threshold
        self._last_check = time.monotonic()
        self._resume_count = 0
        self._task: asyncio.Task[Any] | None = None

    async def start(self, on_resume: Callable[..., Coroutine[Any, Any, None]]) -> None:
        """Start the background detection loop."""
        self._task = asyncio.create_task(self._run(on_resume), name="suspend-detector")

    async def stop(self) -> None:
        """Stop the detection loop."""
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _run(self, on_resume: Callable[..., Coroutine[Any, Any, None]]) -> None:
        """Background loop. Calls on_resume() when suspend is detected."""
        while True:
            await asyncio.sleep(self.check_interval)
            now = time.monotonic()
            elapsed = now - self._last_check
            self._last_check = now

            if elapsed > self.threshold:
                gap = elapsed - self.check_interval
                logger.warning(f"System resume detected (gap: {gap:.0f}s)")
                self._resume_count += 1
                try:
                    await on_resume(gap_seconds=gap)
                except Exception:
                    logger.exception("Resume handler failed")

    @property
    def resume_count(self) -> int:
        return self._resume_count


def get_health_status(app: Any) -> dict[str, Any]:
    """Build health status response."""
    status: dict[str, Any] = {
        "status": "healthy",
        "version": VERSION,
        "pid": os.getpid(),
        "uptime_seconds": time.monotonic(),  # Approximate
        "session_id": getattr(app.state, "session_id", None),
    }

    # Memory usage (optional)
    try:
        import psutil

        process = psutil.Process()
        status["memory_mb"] = round(process.memory_info().rss / 1024 / 1024, 1)
    except Exception:
        # psutil not installed or error — skip
        pass

    # Writer queue status
    if hasattr(app.state, "writer"):
        status["writer_pending"] = app.state.writer.pending_count

    # Task manager status
    if hasattr(app.state, "task_manager"):
        tm = app.state.task_manager
        status["active_tasks"] = tm.active_count
        status["llm_slots_available"] = tm.llm_available
        status["exec_slots_available"] = tm.exec_available

    # Intent queue
    if hasattr(app.state, "intent_queue"):
        # Note: this is async, so we report last known value
        status["intent_queue_pending"] = "check /api/health/detailed"

    # Cost
    if hasattr(app.state, "cost_meter"):
        status["session_cost"] = app.state.cost_meter.session_summary

    return status
