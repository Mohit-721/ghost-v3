"""
LLM Provider Protocol.

Each provider implements structured_complete() using its NATIVE mechanism:
- OpenAI: response_format with json_schema (strict: true)
- Anthropic: tool_use (defined as a tool that returns structured data)
- Google: response_mime_type + response_schema

Phase 1 only implements OpenAI. Anthropic + Google are Phase 3.
"""
from typing import Any, Protocol, TypeVar, runtime_checkable

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


@runtime_checkable
class LLMProviderProtocol(Protocol):
    """Protocol all LLM providers must implement."""

    @property
    def name(self) -> str:
        """Provider name (e.g., 'openai', 'anthropic', 'google')."""
        ...

    @property
    def model(self) -> str:
        """Current model name."""
        ...

    async def complete(self, messages: list[dict[str, Any]], **kwargs: Any) -> "CompletionResult":
        """
        Standard text completion.

        Args:
            messages: List of {"role": "user"|"assistant"|"system", "content": "..."}

        Returns:
            {"content": "...", "usage": {"input_tokens": N, "output_tokens": N}}
        """
        ...

    async def structured_complete(
        self, messages: list[dict[str, Any]], response_model: type[T], **kwargs: Any
    ) -> T:
        """
        Completion with guaranteed structured output.
        Returns a validated Pydantic model instance.

        Each provider implements this using its native mechanism.
        If validation fails, retries ONCE with a correction prompt.
        """
        ...

    def count_tokens(self, text: str) -> int:
        """Provider-specific token counting."""
        ...

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings. Raises NotImplementedError if not supported."""
        ...

    def model_info(self) -> dict[str, Any]:
        """Model name, context window, pricing tier."""
        ...


class CompletionUsage(BaseModel):
    """Token usage from a completion."""
    input_tokens: int
    output_tokens: int


class CompletionResult(BaseModel):
    """Result from a standard completion."""
    content: str
    usage: CompletionUsage
    model: str
    raw_response: dict[str, Any] | None = None
