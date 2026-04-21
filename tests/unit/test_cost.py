"""
Unit tests for Context and Cost Meter modules.
"""

from typing import Any

from ghost.brain.cost import CostMeter, TokenCounter
from ghost.constants import MODEL_PRICING


class MockWriter:
    """Mock DatabaseWriter for testing."""

    def __init__(self) -> None:
        self.enqueued: list[tuple[str, tuple[Any, ...]]] = []

    def enqueue(self, sql: str, params: tuple[Any, ...]) -> None:
        self.enqueued.append((sql, params))


# ─── TokenCounter ─────────────────────────────────────────────────────────────


def test_token_counter_openai_uses_tiktoken() -> None:
    """TokenCounter with OpenAI provider uses tiktoken."""
    counter = TokenCounter("openai", "gpt-4o-mini")
    # 'hello world' is usually 2 tokens
    assert counter.count("hello world") == 2
    assert counter.count("function definition test with more tokens inside") > 5


def test_token_counter_fallback() -> None:
    """TokenCounter fallback uses TOKEN_FALLBACK_CHARS_PER_TOKEN (// 4)."""
    # Use unknown provider to force fallback
    counter = TokenCounter("unknown", "gpt-4o-mini")
    text = "a" * 40
    # 40 chars // 4 chars/token = 10 tokens
    assert counter.count(text) == 10


# ─── CostMeter ────────────────────────────────────────────────────────────────


def test_cost_meter_calculates_correct_cost() -> None:
    """CostMeter.record() calculates correct cost from MODEL_PRICING."""
    writer = MockWriter()
    meter = CostMeter(writer, session_id="test_session")

    # 1M input = $0.150, 1M output = $0.600
    model = "gpt-4o-mini"
    pricing = MODEL_PRICING[model]

    input_tokens = 1_000_000
    output_tokens = 1_000_000
    expected_cost = pricing["input"] + pricing["output"]

    cost = meter.record(model, input_tokens, output_tokens, "test")
    assert abs(cost - expected_cost) < 0.0001


def test_cost_meter_unknown_model_fallback() -> None:
    """CostMeter.record() with unknown model uses default 10.0/1M rate."""
    writer = MockWriter()
    meter = CostMeter(writer)

    # Unknown model defaults to $10/1M for input and output
    cost = meter.record("unknown-model-123", 1_000_000, 1_000_000, "test")
    assert abs(cost - 20.0) < 0.0001


def test_cost_meter_session_summary() -> None:
    """CostMeter.session_summary reflects accumulated totals."""
    writer = MockWriter()
    meter = CostMeter(writer, session_id="test_session")

    meter.record("gpt-4o-mini", 1000, 500, "test1")
    meter.record("gpt-4o-mini", 2000, 1000, "test2")

    summary = meter.session_summary
    assert summary["total_input_tokens"] == 3000
    assert summary["total_output_tokens"] == 1500
    assert summary["total_calls"] == 2
    assert summary["session_id"] == "test_session"


def test_cost_meter_enqueues_to_writer() -> None:
    """CostMeter.record() enqueues to DatabaseWriter."""
    writer = MockWriter()
    meter = CostMeter(writer)

    meter.record("gpt-4o-mini", 100, 50, "test")
    assert len(writer.enqueued) == 1

    sql, params = writer.enqueued[0]
    assert "INSERT INTO cost_records" in sql
    # Params: (model, input_tokens, output_tokens, cost_usd, purpose, session_id)
    assert params[0] == "gpt-4o-mini"
    assert params[1] == 100
    assert params[2] == 50
    assert params[4] == "test"
    assert params[5] is None
