"""
Unit tests for ModelRouter.
"""
import pytest
from pydantic import SecretStr

from ghost.brain.router import ModelRouter
from ghost.config.schema import GhostConfig, SecretConfig


@pytest.fixture
def base_config() -> GhostConfig:
    import os
    from pathlib import Path
    
    from ghost.config.schema import LLMConfig, LLMProvider, TierConfig
    
    return GhostConfig(
        ghost_home=Path("/tmp/ghost"),
        socket_path=Path("/tmp/ghost/ghost.sock"),
        db_path=Path("/tmp/ghost/ghost.db"),
        llm=LLMConfig(
            tier2=TierConfig(provider=LLMProvider.OPENAI, model="gpt-4o-mini"),
            tier3=TierConfig(provider=LLMProvider.OPENAI, model="gpt-4o"),
        ),
        log_level="INFO",
    )


def test_router_initializes_with_openai(base_config: GhostConfig, monkeypatch: pytest.MonkeyPatch) -> None:
    """ModelRouter initializes with OpenAI when API key provided."""
    monkeypatch.setenv("OPENAI_API_KEY", "test_key_123")
    secrets = SecretConfig()
    
    router = ModelRouter(config=base_config, secrets=secrets)
    assert "openai" in router.available_providers
    
    provider = router.get_provider(tier=2)
    assert provider.name == "openai"
    assert provider.model == "gpt-4o-mini"
    # The provider's internal client check is out of scope, just check properties


def test_get_provider_raises_without_api_key(base_config: GhostConfig, monkeypatch: pytest.MonkeyPatch) -> None:
    """ModelRouter raises RuntimeError when no API key configured."""
    # Ensure no API keys
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    
    secrets = SecretConfig()
    router = ModelRouter(config=base_config, secrets=secrets)
    
    assert len(router.available_providers) == 0
    with pytest.raises(RuntimeError, match="Provider 'openai' not configured"):
        router.get_provider(tier=2)


def test_get_provider_for_different_tiers(base_config: GhostConfig, monkeypatch: pytest.MonkeyPatch) -> None:
    """get_provider returns provider with correct model for tier."""
    monkeypatch.setenv("OPENAI_API_KEY", "test_key_123")
    secrets = SecretConfig()
    router = ModelRouter(config=base_config, secrets=secrets)
    
    t2_provider = router.get_provider(tier=2)
    assert t2_provider.model == "gpt-4o-mini"
    
    t3_provider = router.get_provider(tier=3)
    assert t3_provider.model == "gpt-4o"
    
    # Internal cache check
    assert "openai" in router._providers
    assert "openai_3" in router._providers


def test_get_provider_invalid_tier(base_config: GhostConfig, monkeypatch: pytest.MonkeyPatch) -> None:
    """get_provider with invalid tier raises ValueError."""
    monkeypatch.setenv("OPENAI_API_KEY", "test_key_123")
    secrets = SecretConfig()
    router = ModelRouter(config=base_config, secrets=secrets)
    
    with pytest.raises(ValueError, match="Unknown tier: 4"):
        router.get_provider(tier=4)
