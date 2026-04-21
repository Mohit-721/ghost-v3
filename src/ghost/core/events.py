"""
Async pub/sub event bus.

Central nervous system of Ghost. All modules communicate via events.
Handlers are async and run as tasks (non-blocking).

BUG FIX (Bug #7 from final_bug_sweep.md):
Uses deque(maxlen=500) instead of an unbounded list for history.
An unbounded list causes memory spikes during event storms where
thousands of high-frequency fs.changed events can accumulate.
"""
import asyncio
import logging
import uuid
from collections import defaultdict, deque
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class Event:
    """An event in the Ghost system."""

    topic: str
    payload: dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = field(
        default_factory=lambda: datetime.now(UTC)
    )
    causation_id: str | None = None


# Type alias for event handlers
EventHandler = Callable[[Event], Coroutine[Any, Any, None]]


class EventBus:
    """
    Async pub/sub event bus with topic-based routing and wildcard support.

    BUG FIX (Bug #7 from final_bug_sweep.md):
    History is a bounded deque(maxlen=500), not an unbounded list.
    This prevents unconstrained memory growth during file-change storms.
    """

    def __init__(self) -> None:
        self._handlers: dict[str, list[EventHandler]] = defaultdict(list)
        self._history: deque[Event] = deque(maxlen=500)
        self._active_tasks: set[asyncio.Task] = set()

    def subscribe(self, topic: str, handler: EventHandler) -> None:
        """Register a handler for a topic. Supports wildcards: 'forge.*'"""
        self._handlers[topic].append(handler)
        logger.debug(f"Subscribed {handler.__name__!r} to '{topic}'")

    def unsubscribe(self, topic: str, handler: EventHandler) -> None:
        """Remove a handler from a topic."""
        if topic in self._handlers:
            self._handlers[topic] = [
                h for h in self._handlers[topic] if h != handler
            ]

    async def publish(
        self,
        topic: str,
        payload: dict | None = None,
        causation_id: str | None = None,
    ) -> Event:
        """
        Publish an event. Matching handlers run as concurrent asyncio tasks.
        Returns the created Event.
        """
        event = Event(
            topic=topic,
            payload=payload or {},
            causation_id=causation_id,
        )
        self._history.append(event)

        # Collect matching handlers: exact match + wildcard patterns
        handlers: list[EventHandler] = list(self._handlers.get(topic, []))

        # Wildcard subscriptions: "forge.*" matches "forge.completed"
        for pattern, pattern_handlers in self._handlers.items():
            if pattern.endswith(".*"):
                prefix = pattern[:-2]
                if topic.startswith(prefix + ".") and pattern != topic:
                    handlers.extend(pattern_handlers)

        # Also check global wildcard "*"
        if "*" in self._handlers and topic != "*":
            handlers.extend(self._handlers["*"])

        # Run handlers as tasks (non-blocking)
        for handler in handlers:
            task = asyncio.create_task(
                self._safe_invoke(handler, event),
                name=f"event-{topic}-{handler.__name__}",
            )
            self._active_tasks.add(task)
            task.add_done_callback(self._active_tasks.discard)

        return event

    async def _safe_invoke(self, handler: EventHandler, event: Event) -> None:
        """Invoke handler with error catching — one bad handler won't kill the bus."""
        try:
            await handler(event)
        except Exception:
            logger.exception(
                f"Handler {handler.__name__!r} failed for event '{event.topic}'"
            )

    async def drain(self) -> None:
        """Wait for all active handler tasks to complete."""
        if self._active_tasks:
            await asyncio.gather(*list(self._active_tasks), return_exceptions=True)

    @property
    def history(self) -> list[Event]:
        """Recent event history (capped at 500 by deque maxlen)."""
        return list(self._history)

    @property
    def handler_count(self) -> dict[str, int]:
        """Number of handlers per topic."""
        return {
            topic: len(handlers)
            for topic, handlers in self._handlers.items()
        }
