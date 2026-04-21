# Agent 2 Task: Brain + Synthesis

> **Role**: You are building the INTELLIGENCE layer of Ghost — LLM providers, model routing, context assembly, cost tracking, tool synthesis, quarantine, and execution. You handle all LLM interactions and tool lifecycle.
>
> **Working Directory**: `/home/mohit/Coding/ghost v3.0/`
>
> **Do NOT touch files outside your assigned list.** Other agents are building config/, memory/, core/, cli/, and api/ concurrently.

---

## Context: What Is Ghost?

Ghost is a local-first AI daemon. You are building the "brain" (LLM interactions) and "synthesis" (tool creation and execution) subsystems. Your code takes natural language intents, sends them to LLM providers, gets structured responses back, and manages the full tool lifecycle: forge → quarantine → approve → execute → register.

**Read these files to understand the full spec:**
- `ghost_implementation_plan_v3.md` — Sections 4.6-4.9 are most relevant to you
- `final_gaps_analysis.md` — Gaps 2, 3 are yours (PEP 723, Structured Output)
- `final_bug_sweep.md` — Bug #5 (token fallback) affects you. Bug #3 (signal handler) does NOT — that's Agent 3.

---

## Dependencies From Other Agents

You import FROM Agent 1's code (treat as available):
```python
from ghost.config.schema import GhostConfig, SecretConfig, LLMProvider, TierConfig, LLMConfig, SandboxConfig
from ghost.constants import (
    MODEL_PRICING, TOKEN_FALLBACK_CHARS_PER_TOKEN, DEFAULT_MAX_RETRIES,
    DEFAULT_REQUEST_TIMEOUT, VERSION, Topics
)
from ghost.memory.writer import DatabaseWriter
from ghost.memory.entities import EntityStore
from ghost.memory.graph import GraphStore
from ghost.memory.search import UnifiedSearch
from ghost.memory.audit import AuditLog
from ghost.core.events import EventBus, Event
from ghost.core.tasks import TaskManager
```

Agent 3 imports FROM your code. These are the public interfaces you MUST provide:

```python
# Agent 3 will import:
from ghost.brain.providers.base import LLMProvider as LLMProviderProtocol
from ghost.brain.router import ModelRouter
from ghost.brain.context import ContextAssembler
from ghost.brain.cost import CostMeter, TokenCounter
from ghost.brain.queue import IntentQueue
from ghost.brain.retry import with_llm_retry
from ghost.synthesis.forge import ToolForge
from ghost.synthesis.quarantine import QuarantineManager
from ghost.synthesis.executor import ToolExecutor, ExecutionResult
from ghost.synthesis.registry import ToolRegistry
```

---

## Your Files (18 files)

```
src/ghost/
├── brain/
│   ├── __init__.py          # Already exists (empty)
│   ├── providers/
│   │   ├── __init__.py      # Already exists (empty)
│   │   ├── base.py          # ← YOU BUILD THIS
│   │   └── openai.py        # ← YOU BUILD THIS
│   ├── router.py            # ← YOU BUILD THIS
│   ├── context.py           # ← YOU BUILD THIS
│   ├── cost.py              # ← YOU BUILD THIS
│   ├── queue.py             # ← YOU BUILD THIS
│   ├── retry.py             # ← YOU BUILD THIS
│   └── prompts/
│       ├── __init__.py      # Already exists (empty)
│       ├── registry.py      # ← YOU BUILD THIS
│       └── v1/
│           ├── __init__.py  # Already exists (empty)
│           ├── forge.py     # ← YOU BUILD THIS
│           ├── triage.py    # ← YOU BUILD THIS
│           └── analyze.py   # ← YOU BUILD THIS
├── synthesis/
│   ├── __init__.py          # Already exists (empty)
│   ├── forge.py             # ← YOU BUILD THIS
│   ├── quarantine.py        # ← YOU BUILD THIS
│   ├── executor.py          # ← YOU BUILD THIS
│   ├── registry.py          # ← YOU BUILD THIS
│   └── templates/
│       ├── __init__.py      # Already exists (empty)
│       └── tool_skeleton.py # ← YOU BUILD THIS

tests/unit/
├── test_cost.py             # ← YOU BUILD THIS
├── test_router.py           # ← YOU BUILD THIS
├── test_quarantine.py       # ← YOU BUILD THIS
├── test_registry.py         # ← YOU BUILD THIS
```

---

## File 1: `src/ghost/brain/providers/base.py`

The LLM Provider protocol. Every provider implements this.

```python
"""
LLM Provider Protocol.

Each provider implements structured_complete() using its NATIVE mechanism:
- OpenAI: response_format with json_schema (strict: true)
- Anthropic: tool_use (defined as a tool that returns structured data)
- Google: response_mime_type + response_schema

Phase 1 only implements OpenAI. Anthropic + Google are Phase 3.
"""
from typing import Protocol, TypeVar, Any, runtime_checkable
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
    
    async def complete(self, messages: list[dict[str, Any]], **kwargs) -> dict[str, Any]:
        """
        Standard text completion.
        
        Args:
            messages: List of {"role": "user"|"assistant"|"system", "content": "..."}
        
        Returns:
            {"content": "...", "usage": {"input_tokens": N, "output_tokens": N}}
        """
        ...
    
    async def structured_complete(
        self, messages: list[dict[str, Any]], response_model: type[T], **kwargs
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
```

---

## File 2: `src/ghost/brain/providers/openai.py`

OpenAI provider using httpx directly (no SDK dependency).

```python
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

from ghost.brain.providers.base import LLMProviderProtocol, CompletionResult, CompletionUsage
from ghost.constants import TOKEN_FALLBACK_CHARS_PER_TOKEN

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class OpenAIProvider:
    """OpenAI LLM provider using httpx + structured output."""
    
    def __init__(self, api_key: str, model: str = "gpt-4o-mini",
                 base_url: str = "https://api.openai.com/v1",
                 timeout: int = 60):
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
    
    async def complete(self, messages: list[dict[str, Any]], **kwargs) -> CompletionResult:
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
        self, messages: list[dict[str, Any]], response_model: type[T], **kwargs
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
                {"role": "user", "content": f"Your response had a validation error: {e}. Please fix the JSON and try again. The schema is: {json.dumps(schema, indent=2)}"},
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
```

---

## File 3: `src/ghost/brain/router.py`

Tiered model selection.

```python
"""
Model router — selects the right provider + model based on task tier.

Tiers:
- Tier 0: No LLM (local grep/AST operations)
- Tier 2: Tool synthesis, triage (mid-range: gpt-4o-mini)
- Tier 3: Complex analysis (high-end: gpt-4o)
"""
import logging
from typing import Any

from ghost.config.schema import GhostConfig, SecretConfig, LLMProvider
from ghost.brain.providers.openai import OpenAIProvider

logger = logging.getLogger(__name__)


class ModelRouter:
    """Routes requests to the appropriate LLM provider and model."""
    
    def __init__(self, config: GhostConfig, secrets: SecretConfig):
        self._config = config
        self._providers: dict[str, Any] = {}
        self._init_providers(secrets)
    
    def _init_providers(self, secrets: SecretConfig) -> None:
        """Initialize providers based on config."""
        # OpenAI (always available in Phase 1)
        if secrets.openai_api_key:
            self._providers["openai"] = OpenAIProvider(
                api_key=secrets.openai_api_key,
                model=self._config.llm.tier2.model,  # Default to tier2
                timeout=self._config.llm.request_timeout,
            )
        
        # Anthropic and Google are Phase 3
        # if secrets.anthropic_api_key:
        #     self._providers["anthropic"] = AnthropicProvider(...)
        # if secrets.google_api_key:
        #     self._providers["google"] = GoogleProvider(...)
    
    def get_provider(self, tier: int = 2) -> Any:
        """
        Get the provider for the given tier.
        
        Args:
            tier: 2 (mid-range) or 3 (high-end)
        
        Returns:
            LLMProviderProtocol instance
        
        Raises:
            RuntimeError: If no provider is configured for the tier
        """
        if tier == 2:
            tier_config = self._config.llm.tier2
        elif tier == 3:
            tier_config = self._config.llm.tier3
        else:
            raise ValueError(f"Unknown tier: {tier}. Use 2 or 3.")
        
        provider_name = tier_config.provider.value
        
        if provider_name not in self._providers:
            available = list(self._providers.keys())
            raise RuntimeError(
                f"Provider '{provider_name}' not configured. "
                f"Available: {available}. Check ~/.ghost/.env for API keys."
            )
        
        provider = self._providers[provider_name]
        
        # If the provider's current model doesn't match tier config, create a new one
        if provider.model != tier_config.model:
            # For now, create a new provider instance with the correct model
            # In the future, providers should support model switching
            if provider_name == "openai":
                from ghost.config.schema import SecretConfig
                secrets = SecretConfig()
                provider = OpenAIProvider(
                    api_key=secrets.openai_api_key,
                    model=tier_config.model,
                    timeout=self._config.llm.request_timeout,
                )
                self._providers[f"{provider_name}_{tier}"] = provider
        
        return provider
    
    @property
    def available_providers(self) -> list[str]:
        """List of configured provider names."""
        return list(self._providers.keys())
    
    async def close(self) -> None:
        """Close all provider connections."""
        for provider in self._providers.values():
            if hasattr(provider, 'close'):
                await provider.close()
```

---

## File 4: `src/ghost/brain/context.py`

Context assembly pipeline for RAG.

```python
"""
Context Assembly Pipeline (RAG).

Gathers relevant context for LLM requests:
1. Queries Entity Graph for project-scoped context
2. Queries sqlite-vec for semantically similar entities (if available)
3. Merges via Reciprocal Rank Fusion
4. Packs into token budget using provider-specific tokenizer
"""
import logging
from typing import Any

logger = logging.getLogger(__name__)


class ContextAssembler:
    """Assembles context for LLM requests within a token budget."""
    
    def __init__(self, search, token_counter, max_context_tokens: int = 4000):
        """
        Args:
            search: UnifiedSearch instance
            token_counter: TokenCounter instance (provider-specific)
            max_context_tokens: Maximum tokens to include as context
        """
        self.search = search
        self.counter = token_counter
        self.max_tokens = max_context_tokens
    
    async def assemble(self, query: str, project_id: str,
                       budget: int | None = None) -> str:
        """
        Assemble context for an LLM request.
        
        1. Search for relevant entities
        2. Pack into token budget (most relevant first)
        3. Return formatted context string
        
        Args:
            query: The user's query or intent
            project_id: Scope context to this project
            budget: Override max_context_tokens
        
        Returns:
            Formatted context string ready for LLM system prompt
        """
        budget = budget or self.max_tokens
        
        # Search for relevant entities
        results = await self.search.search(query, project_id, limit=30)
        
        if not results:
            return "No relevant context found."
        
        # Pack results into budget
        packed = []
        used_tokens = 0
        
        for entity in results:
            entry = self._format_entity(entity)
            entry_tokens = self.counter.count(entry)
            
            if used_tokens + entry_tokens > budget:
                # Try truncating the content
                remaining = budget - used_tokens
                if remaining > 100:  # Worth including a truncated version
                    truncated = self._truncate_to_tokens(entry, remaining)
                    packed.append(truncated)
                break
            
            packed.append(entry)
            used_tokens += entry_tokens
        
        context = "\n\n---\n\n".join(packed)
        
        return f"## Relevant Context\n\n{context}"
    
    def _format_entity(self, entity: dict) -> str:
        """Format an entity as a context snippet."""
        kind = entity.get("kind", "unknown")
        name = entity.get("name", "unnamed")
        content = entity.get("content", "")
        
        if not content:
            return f"[{kind}] {name}"
        
        # Truncate mega-files (> 200 lines → first 200 + summary marker)
        lines = content.split("\n")
        if len(lines) > 200:
            content = "\n".join(lines[:200]) + f"\n\n... ({len(lines) - 200} more lines truncated)"
        
        return f"### [{kind}] {name}\n\n```\n{content}\n```"
    
    def _truncate_to_tokens(self, text: str, max_tokens: int) -> str:
        """Truncate text to fit within token budget."""
        # Binary search for the right length
        tokens = self.counter.count(text)
        if tokens <= max_tokens:
            return text
        
        # Rough estimate: remove proportional amount
        ratio = max_tokens / tokens
        char_limit = int(len(text) * ratio * 0.9)  # 10% safety margin
        return text[:char_limit] + "\n\n... (truncated to fit context budget)"
```

---

## File 5: `src/ghost/brain/cost.py`

Cost meter with provider-specific token counting.

> [!IMPORTANT]
> Bug #5 fix: Use `TOKEN_FALLBACK_CHARS_PER_TOKEN` (which is 4) consistently everywhere.

```python
"""
Cost tracking and provider-specific token counting.

A "token" is NOT a universal unit — each provider tokenizes differently.
This module handles the correct tokenizer for each provider.
"""
import logging
from datetime import datetime, timezone

import tiktoken

from ghost.constants import TOKEN_FALLBACK_CHARS_PER_TOKEN, MODEL_PRICING

logger = logging.getLogger(__name__)


class TokenCounter:
    """Provider-specific token counting."""
    
    def __init__(self, provider_name: str, model: str, llm_client=None):
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
                    model=self.model,
                    messages=[{"role": "user", "content": text}]
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
    
    def __init__(self, writer, session_id: str | None = None):
        """
        Args:
            writer: DatabaseWriter for persisting cost records
            session_id: Optional session identifier for grouping
        """
        self.writer = writer
        self.session_id = session_id
        
        # In-memory session totals
        self._session_cost = 0.0
        self._session_input_tokens = 0
        self._session_output_tokens = 0
        self._session_calls = 0
    
    def record(self, model: str, input_tokens: int, output_tokens: int,
               purpose: str) -> float:
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
            """INSERT INTO cost_records (model, input_tokens, output_tokens, cost_usd, purpose, session_id)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (model, input_tokens, output_tokens, cost_usd, purpose, self.session_id)
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
        if not pricing:
            # Unknown model, estimate conservatively
            logger.warning(f"No pricing for model '{model}', estimating at $10/1M tokens")
            pricing = {"input": 10.0, "output": 10.0}
        
        input_cost = (input_tokens / 1_000_000) * pricing["input"]
        output_cost = (output_tokens / 1_000_000) * pricing["output"]
        return input_cost + output_cost
    
    @property
    def session_summary(self) -> dict:
        """Current session cost summary."""
        return {
            "total_cost_usd": round(self._session_cost, 6),
            "total_input_tokens": self._session_input_tokens,
            "total_output_tokens": self._session_output_tokens,
            "total_calls": self._session_calls,
            "session_id": self.session_id,
        }
```

---

## File 6: `src/ghost/brain/queue.py`

Intent queue for LLM unavailability.

```python
"""
Intent queue — buffer for LLM requests when the API is unavailable.

When the LLM returns 429/503/timeout, intents are queued in SQLite
and drained when the API becomes available again.
"""
import json
import logging
import uuid

logger = logging.getLogger(__name__)


class IntentQueue:
    """Persistent intent queue backed by SQLite."""
    
    def __init__(self, db, writer):
        self.db = db
        self.writer = writer
    
    async def enqueue(self, payload: dict) -> str:
        """
        Add an intent to the queue.
        
        Returns:
            Intent ID
        """
        intent_id = str(uuid.uuid4())
        await self.writer.write(
            "INSERT INTO intent_queue (id, payload) VALUES (?, ?)",
            (intent_id, json.dumps(payload))
        )
        logger.info(f"Intent queued: {intent_id} (type: {payload.get('type', 'unknown')})")
        return intent_id
    
    async def get_pending(self, limit: int = 10) -> list[dict]:
        """Get pending intents in FIFO order."""
        cursor = await self.db.execute(
            """SELECT * FROM intent_queue
               WHERE status = 'pending'
               ORDER BY created_at ASC
               LIMIT ?""",
            (limit,)
        )
        rows = await cursor.fetchall()
        results = []
        for r in rows:
            d = dict(r)
            d["payload"] = json.loads(d["payload"])
            results.append(d)
        return results
    
    async def mark_completed(self, intent_id: str) -> None:
        """Mark an intent as completed."""
        await self.writer.write(
            """UPDATE intent_queue
               SET status = 'completed', completed_at = datetime('now')
               WHERE id = ?""",
            (intent_id,)
        )
    
    async def mark_failed(self, intent_id: str, error: str) -> None:
        """Mark an intent as failed."""
        await self.writer.write(
            """UPDATE intent_queue
               SET status = 'failed', error = ?, completed_at = datetime('now')
               WHERE id = ?""",
            (error, intent_id)
        )
    
    async def pending_count(self) -> int:
        """Number of pending intents."""
        cursor = await self.db.execute(
            "SELECT COUNT(*) FROM intent_queue WHERE status = 'pending'"
        )
        row = await cursor.fetchone()
        return row[0]
    
    async def drain(self, processor) -> int:
        """
        Process all pending intents.
        
        Args:
            processor: async callable(payload) -> result
        
        Returns:
            Number of intents processed
        """
        pending = await self.get_pending(limit=50)
        processed = 0
        
        for intent in pending:
            try:
                await processor(intent["payload"])
                await self.mark_completed(intent["id"])
                processed += 1
            except Exception as e:
                logger.error(f"Failed to process intent {intent['id']}: {e}")
                await self.mark_failed(intent["id"], str(e))
        
        if processed:
            logger.info(f"Drained {processed} intents from queue")
        return processed
```

---

## File 7: `src/ghost/brain/retry.py`

Retry policies using tenacity.

```python
"""
Retry policies for LLM API calls.

Uses tenacity for exponential backoff with jitter.
Handles 429 (rate limit), 503 (service unavailable), and timeout errors.
"""
import logging

import httpx
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential_jitter,
    retry_if_exception_type,
    before_sleep_log,
    RetryError,
)

from ghost.constants import DEFAULT_MAX_RETRIES

logger = logging.getLogger(__name__)


def _is_retryable(exception: BaseException) -> bool:
    """Determine if an exception is retryable."""
    if isinstance(exception, httpx.HTTPStatusError):
        return exception.response.status_code in (429, 500, 502, 503, 504)
    if isinstance(exception, (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.PoolTimeout)):
        return True
    if isinstance(exception, httpx.ConnectError):
        return True
    return False


# Pre-built retry decorator for LLM calls
llm_retry = retry(
    retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.TimeoutException, httpx.ConnectError)),
    stop=stop_after_attempt(DEFAULT_MAX_RETRIES),
    wait=wait_exponential_jitter(initial=1, max=60, jitter=5),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True,
)


def with_llm_retry(func):
    """
    Decorator that applies LLM retry policy to a function.
    
    Usage:
        @with_llm_retry
        async def call_llm(...):
            ...
    """
    return llm_retry(func)


async def retry_with_queue(func, intent_queue, payload, *args, **kwargs):
    """
    Try to call func. If it fails after retries, queue the intent.
    
    Args:
        func: The async function to call
        intent_queue: IntentQueue instance
        payload: Payload to queue if all retries fail
    
    Returns:
        Result from func, or None if queued
    """
    try:
        return await llm_retry(func)(*args, **kwargs)
    except RetryError as e:
        logger.warning(f"All retries exhausted, queuing intent: {e}")
        await intent_queue.enqueue(payload)
        return None
```

---

## File 8: `src/ghost/brain/prompts/registry.py`

```python
"""
Prompt version management.

Tools are pinned to the prompt version that generated them.
When prompts change, tools can be flagged for regeneration.
"""
import logging
from importlib import import_module

logger = logging.getLogger(__name__)

# Registry of prompt versions
PROMPT_VERSIONS = {
    "v1": "ghost.brain.prompts.v1",
}

CURRENT_VERSION = "v1"


def get_prompt(name: str, version: str | None = None) -> str:
    """
    Get a prompt template by name and version.
    
    Args:
        name: Prompt name (e.g., "forge", "triage", "analyze")
        version: Version string (e.g., "v1"). Defaults to current.
    
    Returns:
        Prompt template string
    """
    version = version or CURRENT_VERSION
    
    if version not in PROMPT_VERSIONS:
        raise ValueError(f"Unknown prompt version: {version}. Available: {list(PROMPT_VERSIONS.keys())}")
    
    module_path = f"{PROMPT_VERSIONS[version]}.{name}"
    
    try:
        module = import_module(module_path)
        return module.PROMPT
    except (ImportError, AttributeError) as e:
        raise ValueError(f"Prompt '{name}' not found in version '{version}': {e}")
```

---

## File 9: `src/ghost/brain/prompts/v1/forge.py`

```python
"""Tool synthesis prompt — v1."""

PROMPT = """\
You are Ghost, an AI tool forge. Your job is to write self-contained Python scripts that solve specific tasks.

## Requirements

1. The script MUST include a PEP 723 inline metadata header declaring its dependencies:
```python
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "package-name>=x.y",
# ]
# ///
```

2. If the script only uses the standard library, use an empty dependencies list:
```python
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
```

3. The script MUST have a `main()` function that returns a JSON-serializable result.

4. Use `if __name__ == "__main__":` to call main() and print the result as JSON.

5. The script should be SELF-CONTAINED. Do not import from ghost or any internal modules.

6. Handle errors gracefully. Print errors to stderr as JSON: {"error": "message"}.

7. If the script needs to read files from a project, use the GHOST_PROJECT_DIR environment variable.

## Context

{context}

## Task

{intent}

## Output Format

Return your response as a JSON object with the following structure. You MUST follow this schema exactly.
"""
```

---

## File 10: `src/ghost/brain/prompts/v1/triage.py`

```python
"""Event triage/significance scoring prompt — v1."""

PROMPT = """\
You are Ghost's triage system. You evaluate file system events to determine their significance.

Given a file change event, score its significance from 0.0 to 1.0:
- 0.0-0.3: Trivial (formatting, comments, whitespace)
- 0.3-0.6: Minor (small refactors, adding tests)
- 0.6-0.8: Significant (new features, bug fixes, API changes)
- 0.8-1.0: Critical (security fixes, breaking changes, architecture changes)

## Context

{context}

## Event

File: {file_path}
Change type: {change_type}
Diff summary: {diff_summary}

## Output

Respond with a JSON object containing:
- score: float between 0.0 and 1.0
- reason: brief explanation (1-2 sentences)
- tags: list of relevant tags (e.g., ["security", "api-change", "refactor"])
"""
```

---

## File 11: `src/ghost/brain/prompts/v1/analyze.py`

```python
"""General analysis prompt — v1."""

PROMPT = """\
You are Ghost, an AI assistant analyzing a software project.

## Context

{context}

## Question

{query}

## Instructions

Provide a thorough analysis. Be specific and reference actual code when possible.
Structure your response clearly with sections if needed.
"""
```

---

## File 12: `src/ghost/synthesis/forge.py`

The main tool synthesis orchestrator.

```python
"""
Tool Forge — Intent → structured LLM → quarantine.

Orchestrates the full tool synthesis pipeline:
1. Assemble context for the intent
2. Send to LLM with structured output
3. Write generated tool to quarantine
4. Return tool metadata for user review
"""
import logging
from typing import Any

from pydantic import BaseModel, Field

from ghost.brain.prompts.registry import get_prompt, CURRENT_VERSION
from ghost.constants import Topics, VERSION

logger = logging.getLogger(__name__)


# ─── Structured Output Models ──────────────────────────────────────────────

class ToolDependency(BaseModel):
    """A Python package dependency."""
    name: str
    version_spec: str = ""  # e.g., ">=2.31"


class ToolSynthesisResponse(BaseModel):
    """Structured response from the LLM for tool generation."""
    name: str = Field(description="Snake_case tool name")
    description: str = Field(description="What the tool does (1-2 sentences)")
    dependencies: list[ToolDependency] = Field(default_factory=list)
    code: str = Field(description="Complete Python script body (the main() function and helpers)")
    capabilities: list[str] = Field(default_factory=list, description="What this tool can do")


# ─── Forge ─────────────────────────────────────────────────────────────────

class ToolForge:
    """Synthesizes tools from natural language intents."""
    
    def __init__(self, router, context_assembler, cost_meter,
                 quarantine, event_bus, audit_log, task_manager):
        self.router = router
        self.context = context_assembler
        self.cost = cost_meter
        self.quarantine = quarantine
        self.events = event_bus
        self.audit = audit_log
        self.tasks = task_manager
    
    async def forge(self, intent: str, project_id: str | None = None) -> dict[str, Any]:
        """
        Synthesize a tool from a natural language intent.
        
        Args:
            intent: What the user wants the tool to do
            project_id: Optional project context
        
        Returns:
            dict with tool metadata (id, name, description, file_path, code_preview)
        """
        logger.info(f"Forging tool for intent: {intent[:100]}")
        
        # Publish event
        await self.events.publish(Topics.FORGE_REQUESTED, {"intent": intent, "project_id": project_id})
        
        try:
            # Step 1: Assemble context
            context_str = ""
            if project_id:
                context_str = await self.context.assemble(intent, project_id)
            
            # Step 2: Build prompt
            prompt_template = get_prompt("forge")
            prompt = prompt_template.format(
                context=context_str or "No project context available.",
                intent=intent,
            )
            
            # Step 3: Call LLM with structured output (via TaskManager semaphore)
            provider = self.router.get_provider(tier=2)
            
            async def _llm_call():
                return await provider.structured_complete(
                    messages=[
                        {"role": "system", "content": prompt},
                        {"role": "user", "content": intent},
                    ],
                    response_model=ToolSynthesisResponse,
                    temperature=0.3,
                )
            
            result: ToolSynthesisResponse = await self.tasks.submit_llm_task(_llm_call())
            
            # Step 4: Record cost
            # (In a real implementation, we'd capture usage from the response)
            # For now, estimate based on prompt + response length
            input_tokens = provider.count_tokens(prompt + intent)
            output_tokens = provider.count_tokens(result.code)
            self.cost.record(
                model=provider.model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                purpose="forge",
            )
            
            # Step 5: Write to quarantine
            tool_info = await self.quarantine.add(
                name=result.name,
                description=result.description,
                code=result.code,
                dependencies=result.dependencies,
                capabilities=result.capabilities,
                prompt_version=CURRENT_VERSION,
            )
            
            # Step 6: Audit log
            self.audit.log(Topics.FORGE_COMPLETED, {
                "tool_id": tool_info["id"],
                "name": result.name,
                "intent": intent[:200],
            })
            
            # Step 7: Publish completion event
            await self.events.publish(Topics.FORGE_COMPLETED, tool_info)
            
            return tool_info
            
        except Exception as e:
            logger.exception(f"Forge failed for intent: {intent[:100]}")
            await self.events.publish(Topics.FORGE_FAILED, {"intent": intent, "error": str(e)})
            self.audit.log(Topics.FORGE_FAILED, {"intent": intent[:200], "error": str(e)})
            raise
```

---

## File 13: `src/ghost/synthesis/quarantine.py`

Manages quarantined tools awaiting approval.

```python
"""
Quarantine — holds synthesized tools pending user approval.

Tools are written to ~/.ghost/quarantine/ as Python scripts.
Each tool has PEP 723 inline metadata for dependency management.

Flow: forge → quarantine → user reviews → approve → registry
                                        → reject  → delete
"""
import hashlib
import logging
import uuid
from pathlib import Path

from ghost.constants import QUARANTINE_DIR, VERSION

logger = logging.getLogger(__name__)


class QuarantineManager:
    """Manages tools pending user approval."""
    
    def __init__(self, ghost_home: Path, writer):
        self.quarantine_dir = ghost_home / QUARANTINE_DIR
        self.quarantine_dir.mkdir(parents=True, exist_ok=True)
        self.writer = writer
    
    async def add(self, name: str, description: str, code: str,
                  dependencies: list = None, capabilities: list = None,
                  prompt_version: str = "v1") -> dict:
        """
        Write a synthesized tool to quarantine.
        
        Returns:
            dict with tool metadata (id, name, file_path, etc.)
        """
        tool_id = str(uuid.uuid4())
        short_hash = hashlib.sha256(code.encode()).hexdigest()[:8]
        
        # Build PEP 723 script
        dep_lines = ""
        if dependencies:
            dep_strs = []
            for dep in dependencies:
                if hasattr(dep, 'name'):
                    spec = f'"{dep.name}{dep.version_spec}"' if dep.version_spec else f'"{dep.name}"'
                elif isinstance(dep, dict):
                    spec = f'"{dep["name"]}{dep.get("version_spec", "")}"'
                else:
                    spec = f'"{dep}"'
                dep_strs.append(f"#   {spec},")
            dep_lines = "\n".join(dep_strs)
        
        script = f'''# /// script
# requires-python = ">=3.11"
# dependencies = [
{dep_lines}
# ]
# ///
"""
Tool: {name}
Generated by Ghost v{VERSION}
Prompt version: {prompt_version}
Capabilities: {", ".join(capabilities or [])}
"""

import sys
import json

{code}

if __name__ == "__main__":
    try:
        result = main()
        if result is not None:
            print(json.dumps(result, indent=2, default=str))
    except Exception as e:
        print(json.dumps({{"error": str(e)}}), file=sys.stderr)
        sys.exit(1)
'''
        
        # Write to quarantine directory
        file_name = f"{name}_{short_hash}.py"
        file_path = self.quarantine_dir / file_name
        file_path.write_text(script)
        
        source_hash = hashlib.sha256(code.encode()).hexdigest()
        
        # Register in DB as quarantined
        await self.writer.write(
            """INSERT INTO tools (id, name, version, description, file_path, source_hash,
                                  status, capabilities, prompt_version, ghost_api_version)
               VALUES (?, ?, 1, ?, ?, ?, 'quarantined', ?, ?, ?)""",
            (tool_id, name, description, str(file_path), source_hash,
             str(capabilities or []), prompt_version, VERSION)
        )
        
        tool_info = {
            "id": tool_id,
            "name": name,
            "description": description,
            "file_path": str(file_path),
            "source_hash": source_hash,
            "status": "quarantined",
            "capabilities": capabilities or [],
            "code_preview": code[:500],
        }
        
        logger.info(f"Tool '{name}' quarantined at {file_path}")
        return tool_info
    
    async def list_pending(self) -> list[dict]:
        """List all quarantined tools."""
        cursor = await self.writer.db.execute(
            "SELECT * FROM tools WHERE status = 'quarantined' ORDER BY created_at DESC"
        )
        return [dict(r) for r in await cursor.fetchall()]
    
    async def get(self, tool_id: str) -> dict | None:
        """Get a quarantined tool by ID."""
        cursor = await self.writer.db.execute(
            "SELECT * FROM tools WHERE id = ? AND status = 'quarantined'",
            (tool_id,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None
    
    async def approve(self, tool_id: str) -> dict | None:
        """Approve a tool — changes status to 'approved'."""
        await self.writer.write(
            "UPDATE tools SET status = 'approved' WHERE id = ? AND status = 'quarantined'",
            (tool_id,)
        )
        # Return updated tool
        cursor = await self.writer.db.execute("SELECT * FROM tools WHERE id = ?", (tool_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None
    
    async def reject(self, tool_id: str) -> bool:
        """Reject and delete a quarantined tool."""
        tool = await self.get(tool_id)
        if not tool:
            return False
        
        # Delete file
        file_path = Path(tool["file_path"])
        if file_path.exists():
            file_path.unlink()
        
        # Remove from DB
        await self.writer.write(
            "DELETE FROM tools WHERE id = ? AND status = 'quarantined'",
            (tool_id,)
        )
        
        logger.info(f"Tool '{tool['name']}' rejected and deleted")
        return True
```

---

## File 14: `src/ghost/synthesis/executor.py`

Tool execution with `uv run` + PEP 723 support.

```python
"""
Tool execution. Prefers `uv run` for automatic dependency management.
Falls back to bare `python` if uv is not installed.

Security:
- Runs in a temp directory (not in the project)
- API keys are NOT passed to tools
- Resource limits via POSIX setrlimit
- Timeout enforced
"""
import logging
import os
import resource
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from ghost.config.schema import SandboxConfig

logger = logging.getLogger(__name__)


@dataclass
class ExecutionResult:
    """Result from tool execution."""
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool
    used_uv: bool


class ToolExecutor:
    """Execute tools in isolated subprocesses."""
    
    def __init__(self, config: SandboxConfig):
        self.exec_timeout = config.exec_timeout_seconds
        self.install_timeout = config.install_timeout_seconds
        self.memory_limit = config.memory_limit_mb * 1024 * 1024
        self.max_output = config.max_output_bytes
        self._has_uv = shutil.which("uv") is not None and config.prefer_uv
    
    async def execute(self, tool_path: Path, args: list[str] | None = None,
                      project_dir: Path | None = None) -> ExecutionResult:
        """
        Run a tool in an isolated subprocess.
        
        If uv is available: `uv run` reads PEP 723 metadata and auto-installs deps.
        If uv is not available: bare `python` (tools needing 3rd-party packages will fail).
        """
        cmd = self._build_command(tool_path, args)
        env = self._build_env(project_dir)
        
        # Use install_timeout for uv (may need to download deps first time)
        timeout = self.install_timeout if self._has_uv else self.exec_timeout
        
        try:
            with tempfile.TemporaryDirectory(prefix="ghost_") as tmpdir:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    cwd=tmpdir,
                    env=env,
                    preexec_fn=self._set_limits,
                )
                return ExecutionResult(
                    exit_code=result.returncode,
                    stdout=result.stdout[:self.max_output],
                    stderr=result.stderr[:self.max_output],
                    timed_out=False,
                    used_uv=self._has_uv,
                )
        except subprocess.TimeoutExpired:
            return ExecutionResult(
                exit_code=-1,
                stdout="",
                stderr=f"Execution timed out after {timeout}s",
                timed_out=True,
                used_uv=self._has_uv,
            )
        except Exception as e:
            return ExecutionResult(
                exit_code=-1,
                stdout="",
                stderr=str(e),
                timed_out=False,
                used_uv=self._has_uv,
            )
    
    def _build_command(self, tool_path: Path, args: list[str] | None) -> list[str]:
        if self._has_uv:
            return ["uv", "run", "--quiet", "--no-progress", str(tool_path)] + (args or [])
        else:
            return ["python", str(tool_path)] + (args or [])
    
    def _build_env(self, project_dir: Path | None) -> dict:
        """Restricted environment. API keys are NOT passed."""
        env = {
            "PATH": "/usr/local/bin:/usr/bin:/bin",
            "HOME": "/tmp",
            "LANG": "en_US.UTF-8",
        }
        if project_dir:
            env["GHOST_PROJECT_DIR"] = str(project_dir)
        return env
    
    def _set_limits(self):
        """POSIX resource limits on child process."""
        try:
            resource.setrlimit(resource.RLIMIT_AS, (self.memory_limit, self.memory_limit))
            resource.setrlimit(resource.RLIMIT_CPU, (self.exec_timeout, self.exec_timeout))
        except (ValueError, OSError) as e:
            # Some systems don't support all limits
            logger.debug(f"Could not set resource limit: {e}")
    
    @property
    def has_uv(self) -> bool:
        return self._has_uv
```

---

## File 15: `src/ghost/synthesis/registry.py`

Versioned tool registry.

```python
"""
Tool registry — versioned storage for approved tools.

Supports multiple versions of the same tool name.
Each tool name has a "current version" pointer.
"""
import hashlib
import json
import logging
import shutil
import uuid
from pathlib import Path

from ghost.constants import TOOLS_DIR

logger = logging.getLogger(__name__)


class ToolRegistry:
    """Manages registered (approved) tools."""
    
    def __init__(self, ghost_home: Path, db, writer):
        self.tools_dir = ghost_home / TOOLS_DIR
        self.tools_dir.mkdir(parents=True, exist_ok=True)
        self.db = db
        self.writer = writer
    
    async def register(self, tool_id: str) -> dict | None:
        """
        Register a tool (move from quarantined/approved to registered).
        Copies the tool file from quarantine to tools dir.
        Updates the current version pointer.
        """
        cursor = await self.db.execute(
            "SELECT * FROM tools WHERE id = ?", (tool_id,)
        )
        tool = await cursor.fetchone()
        if not tool:
            return None
        
        tool = dict(tool)
        
        # Copy file to tools directory
        src = Path(tool["file_path"])
        dst = self.tools_dir / src.name
        if src.exists():
            shutil.copy2(str(src), str(dst))
            # Update file_path
            await self.writer.write(
                "UPDATE tools SET file_path = ?, status = 'registered' WHERE id = ?",
                (str(dst), tool_id)
            )
        
        # Update current version pointer
        await self.writer.write(
            """INSERT OR REPLACE INTO tool_current (name, current_version_id)
               VALUES (?, ?)""",
            (tool["name"], tool_id)
        )
        
        logger.info(f"Tool '{tool['name']}' v{tool['version']} registered")
        tool["file_path"] = str(dst)
        tool["status"] = "registered"
        return tool
    
    async def get_current(self, name: str) -> dict | None:
        """Get the current version of a tool by name."""
        cursor = await self.db.execute(
            """SELECT t.* FROM tools t
               JOIN tool_current tc ON t.id = tc.current_version_id
               WHERE tc.name = ?""",
            (name,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None
    
    async def get_by_id(self, tool_id: str) -> dict | None:
        """Get a tool by its ID."""
        cursor = await self.db.execute("SELECT * FROM tools WHERE id = ?", (tool_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None
    
    async def list_all(self, status: str | None = None) -> list[dict]:
        """List all tools, optionally filtered by status."""
        if status:
            cursor = await self.db.execute(
                "SELECT * FROM tools WHERE status = ? ORDER BY name, version DESC",
                (status,)
            )
        else:
            cursor = await self.db.execute(
                "SELECT * FROM tools ORDER BY name, version DESC"
            )
        return [dict(r) for r in await cursor.fetchall()]
    
    async def record_run(self, tool_id: str) -> None:
        """Increment run counter and update last_run_at."""
        await self.writer.write(
            """UPDATE tools SET runs = runs + 1, last_run_at = datetime('now')
               WHERE id = ?""",
            (tool_id,)
        )
    
    async def delete(self, tool_id: str) -> bool:
        """Delete a tool (file + DB record)."""
        tool = await self.get_by_id(tool_id)
        if not tool:
            return False
        
        # Delete file
        file_path = Path(tool["file_path"])
        if file_path.exists():
            file_path.unlink()
        
        # Remove current version pointer if this is the current version
        await self.writer.write(
            "DELETE FROM tool_current WHERE current_version_id = ?",
            (tool_id,)
        )
        
        # Delete DB record
        await self.writer.write("DELETE FROM tools WHERE id = ?", (tool_id,))
        
        logger.info(f"Tool '{tool['name']}' v{tool['version']} deleted")
        return True
    
    async def get_versions(self, name: str) -> list[dict]:
        """Get all versions of a tool by name."""
        cursor = await self.db.execute(
            "SELECT * FROM tools WHERE name = ? ORDER BY version DESC",
            (name,)
        )
        return [dict(r) for r in await cursor.fetchall()]
```

---

## File 16: `src/ghost/synthesis/templates/tool_skeleton.py`

```python
"""
Template for synthesized tools.
The forge prompt instructs the LLM to generate code following this structure.
"""

TOOL_TEMPLATE = '''\
# /// script
# requires-python = ">=3.11"
# dependencies = [{dependencies}]
# ///
"""
Tool: {name}
Generated by Ghost v{ghost_version}
Prompt version: {prompt_version}
Capabilities: {capabilities}
"""

import sys
import json

def main():
    {body}

if __name__ == "__main__":
    try:
        result = main()
        if result is not None:
            print(json.dumps(result, indent=2, default=str))
    except Exception as e:
        print(json.dumps({{"error": str(e)}}), file=sys.stderr)
        sys.exit(1)
'''
```

---

## Unit Tests to Write

### `tests/unit/test_cost.py`

```
Test cases:
1. TokenCounter with OpenAI provider uses tiktoken
2. TokenCounter fallback uses TOKEN_FALLBACK_CHARS_PER_TOKEN (// 4)
3. CostMeter.record() calculates correct cost from MODEL_PRICING
4. CostMeter.record() with unknown model logs warning
5. CostMeter.session_summary reflects accumulated totals
6. CostMeter.record() enqueues to DatabaseWriter
```

### `tests/unit/test_router.py`

```
Test cases:
1. ModelRouter initializes with OpenAI when API key provided
2. ModelRouter raises RuntimeError when no API key configured
3. get_provider(tier=2) returns provider with tier2 model
4. get_provider(tier=3) returns provider with tier3 model
5. get_provider with invalid tier raises ValueError
6. available_providers lists configured providers
```

### `tests/unit/test_quarantine.py`

```
Test cases:
1. add() creates file in quarantine directory
2. add() file contains PEP 723 header
3. add() registers tool in DB with status='quarantined'
4. list_pending() returns quarantined tools
5. approve() changes status to 'approved'
6. reject() deletes file and DB record
7. get() returns None for non-existent tool
```

### `tests/unit/test_registry.py`

```
Test cases:
1. register() moves file from quarantine to tools dir
2. register() updates current version pointer
3. get_current() returns the current version
4. list_all() returns all tools
5. list_all(status='registered') filters correctly
6. delete() removes file and DB record
7. record_run() increments counter
8. get_versions() returns all versions sorted by version DESC
```

---

## Important Reminders

1. **Import `constants` for all magic values** — MODEL_PRICING, TOKEN_FALLBACK_CHARS_PER_TOKEN, Topics, VERSION, etc.
2. **All DB writes go through `DatabaseWriter`** (you receive it as a dependency).
3. **All DB reads can use `db` directly** (WAL allows concurrent reads).
4. **Use `logging.getLogger(__name__)` in every module.**
5. **Pydantic v2** — `model_validate()`, `model_dump()`, `model_json_schema()`.
6. **Bug #5 fix**: The fallback is `len(text) // 4` everywhere. This is already correct in `constants.TOKEN_FALLBACK_CHARS_PER_TOKEN = 4`.
7. **`with_llm_retry` decorator** must work with both sync and async functions.

---

## Definition of Done

- [ ] All 18 files created and syntactically valid
- [ ] `python -c "from ghost.brain.providers.openai import OpenAIProvider; print('OK')"` works
- [ ] `python -c "from ghost.synthesis.forge import ToolForge; print('OK')"` works
- [ ] `python -c "from ghost.synthesis.executor import ToolExecutor, ExecutionResult; print('OK')"` works
- [ ] All unit tests pass: `pytest tests/unit/test_cost.py tests/unit/test_router.py tests/unit/test_quarantine.py tests/unit/test_registry.py -v`
- [ ] `ruff check src/ghost/brain/ src/ghost/synthesis/` passes
