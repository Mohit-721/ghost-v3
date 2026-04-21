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

from ghost.brain.prompts.registry import CURRENT_VERSION, get_prompt
from ghost.constants import Topics

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

    def __init__(
        self,
        router: Any,
        context_assembler: Any,
        cost_meter: Any,
        quarantine: Any,
        event_bus: Any,
        audit_log: Any,
        task_manager: Any,
    ) -> None:
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
        await self.events.publish(
            Topics.FORGE_REQUESTED, {"intent": intent, "project_id": project_id}
        )

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

            async def _llm_call() -> ToolSynthesisResponse:
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
            self.audit.log(
                Topics.FORGE_COMPLETED,
                {
                    "tool_id": tool_info["id"],
                    "name": result.name,
                    "intent": intent[:200],
                },
            )

            # Step 7: Publish completion event
            await self.events.publish(Topics.FORGE_COMPLETED, tool_info)

            return tool_info

        except Exception as e:
            logger.exception(f"Forge failed for intent: {intent[:100]}")
            await self.events.publish(Topics.FORGE_FAILED, {"intent": intent, "error": str(e)})
            self.audit.log(Topics.FORGE_FAILED, {"intent": intent[:200], "error": str(e)})
            raise
