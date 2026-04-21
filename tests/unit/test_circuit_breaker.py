"""
Unit tests for the circuit breaker pattern — tested on the EventBus which
is the most natural place it applies (handler error isolation).

These tests verify the pattern is correctly implemented even though senses/
will build an explicit CircuitBreaker class in Phase 2.
"""
import asyncio
from collections import defaultdict

import pytest

from ghost.core.events import Event, EventBus


class CircuitBreaker:
    """
    Simple circuit breaker pattern for protecting unreliable services.

    States:
    - CLOSED: Normal operation (failures counted)
    - OPEN: Service unavailable (fast-fail for `open_duration` seconds)
    - HALF_OPEN: Trial request allowed to test recovery

    This implementation is tested here so senses/ can import and use it.
    """

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"

    def __init__(
        self,
        failure_threshold: int = 5,
        open_duration: float = 30.0,
        success_threshold: int = 2,
    ) -> None:
        self.failure_threshold = failure_threshold
        self.open_duration = open_duration
        self.success_threshold = success_threshold

        self._state = self.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._opened_at: float | None = None

    @property
    def state(self) -> str:
        return self._state

    def _check_transition(self, now: float) -> None:
        """Transition OPEN → HALF_OPEN after open_duration elapsed."""
        if self._state == self.OPEN and self._opened_at is not None:
            import time

            if now - self._opened_at >= self.open_duration:
                self._state = self.HALF_OPEN
                self._success_count = 0

    def is_available(self) -> bool:
        """Check if the service can be called."""
        import time

        self._check_transition(time.monotonic())
        return self._state in (self.CLOSED, self.HALF_OPEN)

    def record_success(self) -> None:
        """Record a successful call."""
        if self._state == self.HALF_OPEN:
            self._success_count += 1
            if self._success_count >= self.success_threshold:
                self._state = self.CLOSED
                self._failure_count = 0
        elif self._state == self.CLOSED:
            self._failure_count = 0

    def record_failure(self) -> None:
        """Record a failed call. Opens the circuit if threshold reached."""
        import time

        if self._state == self.HALF_OPEN:
            # Single failure in half-open → back to open
            self._state = self.OPEN
            self._opened_at = time.monotonic()
            return

        self._failure_count += 1
        if self._failure_count >= self.failure_threshold:
            self._state = self.OPEN
            self._opened_at = time.monotonic()

    def reset(self) -> None:
        """Force reset to CLOSED state."""
        self._state = self.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._opened_at = None


# ─── Circuit Breaker Tests ────────────────────────────────────────────────────

def test_initial_state_is_closed():
    cb = CircuitBreaker()
    assert cb.state == CircuitBreaker.CLOSED
    assert cb.is_available() is True


def test_opens_after_failure_threshold():
    cb = CircuitBreaker(failure_threshold=3)
    cb.record_failure()
    cb.record_failure()
    assert cb.state == CircuitBreaker.CLOSED
    cb.record_failure()
    assert cb.state == CircuitBreaker.OPEN
    assert cb.is_available() is False


def test_reset_closes_circuit():
    cb = CircuitBreaker(failure_threshold=1)
    cb.record_failure()
    assert cb.state == CircuitBreaker.OPEN
    cb.reset()
    assert cb.state == CircuitBreaker.CLOSED
    assert cb.is_available() is True


def test_success_resets_failure_count():
    cb = CircuitBreaker(failure_threshold=3)
    cb.record_failure()
    cb.record_failure()
    cb.record_success()
    cb.record_failure()
    # Failure count was reset by success; only 1 failure now
    assert cb.state == CircuitBreaker.CLOSED


def test_half_open_transitions_after_duration():
    """After open_duration, state transitions to HALF_OPEN."""
    import time

    cb = CircuitBreaker(failure_threshold=1, open_duration=0.01)
    cb.record_failure()
    assert cb.state == CircuitBreaker.OPEN

    time.sleep(0.02)
    # Calling is_available() triggers the transition check
    assert cb.is_available() is True
    assert cb.state == CircuitBreaker.HALF_OPEN


def test_half_open_closes_after_successes():
    """Sufficient successes in HALF_OPEN close the circuit."""
    import time

    cb = CircuitBreaker(failure_threshold=1, open_duration=0.01, success_threshold=2)
    cb.record_failure()
    time.sleep(0.02)
    cb.is_available()  # Trigger HALF_OPEN

    cb.record_success()
    assert cb.state == CircuitBreaker.HALF_OPEN  # Not yet
    cb.record_success()
    assert cb.state == CircuitBreaker.CLOSED


def test_half_open_failure_reopens():
    """A failure in HALF_OPEN immediately reopens the circuit."""
    import time

    cb = CircuitBreaker(failure_threshold=1, open_duration=0.01)
    cb.record_failure()
    time.sleep(0.02)
    cb.is_available()  # Trigger HALF_OPEN
    assert cb.state == CircuitBreaker.HALF_OPEN

    cb.record_failure()
    assert cb.state == CircuitBreaker.OPEN


# ─── EventBus Handler Isolation (demonstrates circuit breaker need) ──────────

@pytest.mark.asyncio
async def test_eventbus_isolates_handler_failures():
    """EventBus _safe_invoke isolates bad handlers — other handlers still run."""
    bus = EventBus()
    results: list[str] = []

    async def bad_handler(event: Event) -> None:
        raise RuntimeError("I always fail")

    async def good_handler(event: Event) -> None:
        results.append("good")

    bus.subscribe("test.topic", bad_handler)
    bus.subscribe("test.topic", good_handler)
    await bus.publish("test.topic", {})
    await bus.drain()

    # Good handler should have run despite bad handler failing
    assert "good" in results


@pytest.mark.asyncio
async def test_eventbus_continues_after_repeated_handler_errors():
    """EventBus keeps working even when a handler fails repeatedly."""
    bus = EventBus()
    good_calls: list[int] = []

    async def bad_handler(event: Event) -> None:
        raise ValueError("always bad")

    async def good_handler(event: Event) -> None:
        good_calls.append(1)

    bus.subscribe("test.repeat", bad_handler)
    bus.subscribe("test.repeat", good_handler)

    for _ in range(5):
        await bus.publish("test.repeat", {})
        await bus.drain()

    # Good handler ran 5 times, bad handler failed 5 times — bus is still alive
    assert len(good_calls) == 5
