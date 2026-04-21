"""
Unit tests for ghost.core.events.EventBus.
"""
import asyncio

import pytest

from ghost.core.events import Event, EventBus


@pytest.fixture
def bus() -> EventBus:
    return EventBus()


# ─── Subscribe + Publish ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_subscribe_publish_calls_handler(bus):
    """Handler is called with the correct event when topic matches."""
    received: list[Event] = []

    async def handler(event: Event) -> None:
        received.append(event)

    bus.subscribe("forge.completed", handler)
    event = await bus.publish("forge.completed", {"tool": "test_tool"})
    await bus.drain()

    assert len(received) == 1
    assert received[0].topic == "forge.completed"
    assert received[0].payload == {"tool": "test_tool"}
    assert received[0].id == event.id


@pytest.mark.asyncio
async def test_publish_no_subscribers_no_error(bus):
    """Publishing to a topic with no subscribers does not raise."""
    event = await bus.publish("nonexistent.topic", {"data": 42})
    assert event.topic == "nonexistent.topic"


@pytest.mark.asyncio
async def test_wildcard_subscription(bus):
    """Wildcard 'forge.*' handler matches 'forge.completed'."""
    received: list[Event] = []

    async def wildcard_handler(event: Event) -> None:
        received.append(event)

    bus.subscribe("forge.*", wildcard_handler)
    await bus.publish("forge.completed", {})
    await bus.publish("forge.failed", {})
    await bus.drain()

    assert len(received) == 2
    topics = [e.topic for e in received]
    assert "forge.completed" in topics
    assert "forge.failed" in topics


@pytest.mark.asyncio
async def test_wildcard_does_not_match_exact_parent(bus):
    """Wildcard 'forge.*' does NOT match 'forge' itself."""
    received: list[Event] = []

    async def wildcard_handler(event: Event) -> None:
        received.append(event)

    bus.subscribe("forge.*", wildcard_handler)
    await bus.publish("forge", {})
    await bus.drain()

    assert len(received) == 0


@pytest.mark.asyncio
async def test_handler_exception_does_not_crash_bus(bus):
    """A handler that raises does not crash the EventBus."""

    async def bad_handler(event: Event) -> None:
        raise RuntimeError("Handler failure!")

    async def good_handler(event: Event) -> None:
        pass

    bus.subscribe("test.event", bad_handler)
    bus.subscribe("test.event", good_handler)

    # Should not raise
    await bus.publish("test.event", {})
    await bus.drain()


@pytest.mark.asyncio
async def test_history_is_bounded(bus):
    """History is capped at 500 events (deque maxlen — Bug #7 fix)."""
    for i in range(600):
        await bus.publish("test.event", {"i": i})
    await bus.drain()

    # Must never exceed 500
    assert len(bus.history) == 500
    # Most recent events should be in history
    last = bus.history[-1]
    assert last.payload["i"] == 599


@pytest.mark.asyncio
async def test_drain_waits_for_all_handlers(bus):
    """drain() waits until all handler tasks complete."""
    completed: list[bool] = []

    async def slow_handler(event: Event) -> None:
        await asyncio.sleep(0.05)
        completed.append(True)

    bus.subscribe("test.slow", slow_handler)
    await bus.publish("test.slow", {})
    # Before drain, handler may not be done
    await bus.drain()
    assert completed == [True]


@pytest.mark.asyncio
async def test_unsubscribe_removes_handler(bus):
    """Unsubscribing a handler prevents it from being called."""
    received: list[Event] = []

    async def handler(event: Event) -> None:
        received.append(event)

    bus.subscribe("test.event", handler)
    bus.unsubscribe("test.event", handler)

    await bus.publish("test.event", {})
    await bus.drain()

    assert len(received) == 0


@pytest.mark.asyncio
async def test_event_has_auto_uuid_and_timestamp(bus):
    """Published Event has a non-empty UUID id and a timezone-aware timestamp."""
    from datetime import timezone

    event = await bus.publish("test.meta", {})
    assert event.id and len(event.id) == 36  # UUID4 format
    assert event.timestamp.tzinfo is not None
    assert event.timestamp.tzinfo == timezone.utc
