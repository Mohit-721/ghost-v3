"""Tests for suspend detection logic."""

import asyncio

import pytest

from ghost.core.health import SuspendDetector


@pytest.mark.asyncio
async def test_suspend_detector() -> None:
    """Test suspend detector background task."""
    detector = SuspendDetector(check_interval=0.1, threshold=0.3)

    events = []

    async def on_resume(gap_seconds: float) -> None:
        events.append(gap_seconds)

    await detector.start(on_resume)

    # Let it run normally
    await asyncio.sleep(0.3)
    assert len(events) == 0
    assert detector.resume_count == 0

    # Simulate a fake "suspend" by altering the check threshold logic internally
    # Or in this case we can just mimic the clock jumping
    import time

    detector._last_check = time.monotonic() - 0.5  # Simulate being asleep for 0.5s

    await asyncio.sleep(0.2)  # Wait for it to check itself again

    assert len(events) >= 1
    assert events[0] >= 0.2  # 0.5 passed simulated - 0.1 interval - rough timings
    assert detector.resume_count >= 1

    await detector.stop()
