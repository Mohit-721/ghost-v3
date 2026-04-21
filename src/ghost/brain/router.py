"""
Model router — selects the right provider + model based on task tier.

Tiers:
- Tier 0: No LLM (local grep/AST operations)
- Tier 2: Tool synthesis, triage (mid-range: gpt-4o-mini)
- Tier 3: Complex analysis (high-end: gpt-4o)
"""
import logging
from typing import Any

from ghost.brain.providers.openai import OpenAIProvider
from ghost.config.schema import GhostConfig, SecretConfig

logger = logging.getLogger(__name__)


class ModelRouter:
    """Routes requests to the appropriate LLM provider and model."""

    def __init__(self, config: GhostConfig, secrets: SecretConfig) -> None:
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
                secrets = SecretConfig()
                if secrets.openai_api_key:
                    provider = OpenAIProvider(
                        api_key=secrets.openai_api_key,
                        model=tier_config.model,
                        timeout=self._config.llm.request_timeout,
                    )
                    self._providers[f"{provider_name}_{tier}"] = provider
                else:
                    raise RuntimeError("Lost OpenAI API key during provider reload.")

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
