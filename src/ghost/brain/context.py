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

    def __init__(self, search: Any, token_counter: Any, max_context_tokens: int = 4000) -> None:
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

    def _format_entity(self, entity: dict[str, Any]) -> str:
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
