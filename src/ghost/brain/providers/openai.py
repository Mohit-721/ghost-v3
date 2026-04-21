"""
OpenAI provider — uses httpx directly (no openai SDK).

Structured output: response_format with json_schema (strict: true).
Token counting: tiktoken (local, fast).

This is the PRIMARY provider for Phase 1.
"""

import json
import logging
from typing import Any, TypeVar

import httpx
import tiktoken
from pydantic import BaseModel, ValidationError

from ghost.brain.providers.base import CompletionResult, CompletionUsage
from ghost.constants import TOKEN_FALLBACK_CHARS_PER_TOKEN

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class OpenAIProvider:
    """OpenAI LLM provider using httpx + structured output."""

    def __init__(
        self,
        api_key: str,
        model: str = "gpt-4o-mini",
        base_url: str = "https://api.openai.com/v1",
        timeout: int = 60,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=timeout,
        )

        # Pre-load tiktoken encoder
        try:
            self._encoding = tiktoken.encoding_for_model(model)
        except KeyError:
            self._encoding = tiktoken.get_encoding("cl100k_base")

    @property
    def name(self) -> str:
        return "openai"

    @property
    def model(self) -> str:
        return self._model

    async def complete(self, messages: list[dict[str, Any]], **kwargs: Any) -> CompletionResult:
        """Standard text completion via OpenAI chat API."""
        payload = {
            "model": self._model,
            "messages": messages,
            **kwargs,
        }

        response = await self._client.post("/chat/completions", json=payload)
        response.raise_for_status()
        data = response.json()

        choice = data["choices"][0]
        usage = data.get("usage", {})

        return CompletionResult(
            content=choice["message"]["content"],
            usage=CompletionUsage(
                input_tokens=usage.get("prompt_tokens", 0),
                output_tokens=usage.get("completion_tokens", 0),
            ),
            model=data.get("model", self._model),
            raw_response=data,
        )

    async def structured_complete(
        self, messages: list[dict[str, Any]], response_model: type[T], **kwargs: Any
    ) -> T:
        """
        Structured output using OpenAI's json_schema strict mode.

        Uses response_format = { type: "json_schema", json_schema: {...}, strict: true }
        which constrains token generation at the model level.
        """
        # Build JSON schema from Pydantic model
        schema = response_model.model_json_schema()

        payload = {
            "model": self._model,
            "messages": messages,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": response_model.__name__,
                    "strict": True,
                    "schema": schema,
                },
            },
            **kwargs,
        }

        response = await self._client.post("/chat/completions", json=payload)
        response.raise_for_status()
        data = response.json()

        content = data["choices"][0]["message"]["content"]

        try:
            parsed = json.loads(content)
            result = response_model.model_validate(parsed)
            return result
        except (json.JSONDecodeError, ValidationError) as e:
            # Retry once with correction prompt
            logger.warning(f"Structured output validation failed, retrying: {e}")

            correction_messages = messages + [
                {"role": "assistant", "content": content},
                {
                    "role": "user",
                    "content": (
                        f"Your response had a validation error: {e}. "
                        f"Please fix the JSON and try again. The schema is: "
                        f"{json.dumps(schema, indent=2)}"
                    ),
                },
            ]

            retry_payload = {
                "model": self._model,
                "messages": correction_messages,
                "response_format": payload["response_format"],
            }

            retry_response = await self._client.post("/chat/completions", json=retry_payload)
            retry_response.raise_for_status()
            retry_data = retry_response.json()

            retry_content = retry_data["choices"][0]["message"]["content"]
            parsed = json.loads(retry_content)
            return response_model.model_validate(parsed)

    def count_tokens(self, text: str) -> int:
        """Count tokens using tiktoken (local, fast)."""
        if self._encoding:
            return len(self._encoding.encode(text))
        return len(text) // TOKEN_FALLBACK_CHARS_PER_TOKEN

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings via OpenAI embeddings API."""
        payload = {
            "model": "text-embedding-3-small",
            "input": texts,
        }
        response = await self._client.post("/embeddings", json=payload)
        response.raise_for_status()
        data = response.json()
        return [item["embedding"] for item in data["data"]]

    def model_info(self) -> dict[str, Any]:
        """Return model metadata."""
        return {
            "provider": "openai",
            "model": self._model,
            "supports_structured_output": True,
            "supports_embeddings": True,
        }

    async def close(self) -> None:
        """Close the httpx client."""
        await self._client.aclose()
