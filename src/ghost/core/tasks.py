"""
Task manager — controlled concurrency for Ghost operations.

Limits:
- LLM calls: max 2 concurrent (parallel forge + triage)
- Tool execution: max 1 at a time (prevent resource contention)

Background tasks are tracked and cancelled cleanly on shutdown.
"""
import asyncio
import logging
from collections.abc import Coroutine
from typing import Any, TypeVar

from ghost.constants import MAX_CONCURRENT_EXEC, MAX_CONCURRENT_LLM_CALLS

logger = logging.getLogger(__name__)

T = TypeVar("T")


class TaskManager:
    """Manages concurrent Ghost operations with controlled parallelism."""

    def __init__(
        self,
        max_llm: int = MAX_CONCURRENT_LLM_CALLS,
        max_exec: int = MAX_CONCURRENT_EXEC,
    ) -> None:
        self._llm_semaphore = asyncio.Semaphore(max_llm)
        self._exec_semaphore = asyncio.Semaphore(max_exec)
        self._active_tasks: set[asyncio.Task] = set()

    async def submit_llm_task(self, coro: Coroutine[Any, Any, T]) -> T:
        """Run an LLM call with concurrency limiting (max 2 concurrent)."""
        async with self._llm_semaphore:
            logger.debug("LLM task acquired semaphore")
            return await coro

    async def submit_exec_task(self, coro: Coroutine[Any, Any, T]) -> T:
        """Run a tool execution with concurrency limiting (max 1 concurrent)."""
        async with self._exec_semaphore:
            logger.debug("Exec task acquired semaphore")
            return await coro

    def spawn(self, coro: Coroutine, name: str | None = None) -> asyncio.Task:
        """Spawn a fire-and-forget background task, tracked for clean shutdown."""
        task = asyncio.create_task(coro, name=name)
        self._active_tasks.add(task)
        task.add_done_callback(self._task_done)
        return task

    def _task_done(self, task: asyncio.Task) -> None:
        self._active_tasks.discard(task)
        if task.cancelled():
            return
        exc = task.exception()
        if exc:
            logger.exception(
                f"Background task {task.get_name()!r} failed", exc_info=exc
            )

    async def shutdown(self) -> None:
        """Cancel all active tasks and wait for completion."""
        for task in list(self._active_tasks):
            task.cancel()
        if self._active_tasks:
            await asyncio.gather(*list(self._active_tasks), return_exceptions=True)
        self._active_tasks.clear()

    @property
    def active_count(self) -> int:
        return len(self._active_tasks)

    @property
    def llm_available(self) -> int:
        """Number of available LLM semaphore slots."""
        return self._llm_semaphore._value  # type: ignore[attr-defined]

    @property
    def exec_available(self) -> int:
        """Number of available exec semaphore slots."""
        return self._exec_semaphore._value  # type: ignore[attr-defined]
