"""
Cost tracking and provider-specific token counting.

A "token" is NOT a universal unit — each provider tokenizes differently.
This module handles the correct tokenizer for each provider.
"""

import logging
from typing import Any

import tiktoken

from ghost.constants import MODEL_PRICING, TOKEN_FALLBACK_CHARS_PER_TOKEN

logger = logging.getLogger(__name__)


class TokenCounter:
    """Provider-specific token counting."""

    def __init__(self, provider_name: str, model: str, llm_client: Any = None) -> None:
        self.provider = provider_name
        self.model = model
        self._client = llm_client

        # Pre-load tiktoken for OpenAI (offline, fast)
        self._encoding = None
        if provider_name == "openai":
            try:
                self._encoding = tiktoken.encoding_for_model(model)
            except KeyError:
                self._encoding = tiktoken.get_encoding("cl100k_base")

    def count(self, text: str) -> int:
        """Count tokens using the provider-specific tokenizer."""
        if self.provider == "openai" and self._encoding:
            return len(self._encoding.encode(text))

        if self.provider == "anthropic" and self._client:
            try:
                result = self._client.messages.count_tokens(
                    model=self.model, messages=[{"role": "user", "content": text}]
                )
                return result.input_tokens
            except Exception:
                pass

        if self.provider == "google" and self._client:
            try:
                result = self._client.count_tokens(text)
                return result.total_tokens
            except Exception:
                pass

        # Universal fallback — consistent with constants.TOKEN_FALLBACK_CHARS_PER_TOKEN
        return len(text) // TOKEN_FALLBACK_CHARS_PER_TOKEN


class CostMeter:
    """Tracks LLM API costs."""

    def __init__(self, writer: Any, session_id: str | None = None) -> None:
        """
        Args:
            writer: DatabaseWriter for persisting cost records
            session_id: Optional session identifier for grouping
        """
        self.writer = writer
        self.session_id = session_id

        # In-memory session totals
        self._session_cost: float = 0.0
        self._session_input_tokens: int = 0
        self._session_output_tokens: int = 0
        self._session_calls: int = 0

    def record(self, model: str, input_tokens: int, output_tokens: int, purpose: str) -> float:
        """
        Record a cost entry. Returns the cost in USD.

        Args:
            model: Model name (e.g., "gpt-4o-mini")
            input_tokens: Number of input tokens
            output_tokens: Number of output tokens
            purpose: What the call was for (e.g., "forge", "triage")

        Returns:
            Estimated cost in USD
        """
        cost_usd = self._calculate_cost(model, input_tokens, output_tokens)

        # Fire-and-forget to DB
        self.writer.enqueue(
            "INSERT INTO cost_records "
            "(model, input_tokens, output_tokens, cost_usd, purpose, session_id) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (model, input_tokens, output_tokens, cost_usd, purpose, self.session_id),
        )

        # Update session totals
        self._session_cost += cost_usd
        self._session_input_tokens += input_tokens
        self._session_output_tokens += output_tokens
        self._session_calls += 1

        logger.info(
            f"Cost: {model} {input_tokens}+{output_tokens} tokens = ${cost_usd:.6f} [{purpose}]"
        )

        return cost_usd

    def _calculate_cost(self, model: str, input_tokens: int, output_tokens: int) -> float:
        """Calculate cost based on MODEL_PRICING table."""
        pricing = MODEL_PRICING.get(model)
        if pricing is None:
            # Unknown model, estimate conservatively
            logger.warning(f"No pricing for model '{model}', estimating at $10/1M tokens")
            pricing = {"input": 10.0, "output": 10.0}

        input_cost = (input_tokens / 1_000_000) * pricing["input"]
        output_cost = (output_tokens / 1_000_000) * pricing["output"]
        return input_cost + output_cost

    @property
    def session_summary(self) -> dict[str, Any]:
        """Current session cost summary."""
        return {
            "total_cost_usd": round(self._session_cost, 6),
            "total_input_tokens": self._session_input_tokens,
            "total_output_tokens": self._session_output_tokens,
            "total_calls": self._session_calls,
            "session_id": self.session_id,
        }
