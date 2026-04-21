"""
Unit tests for ghost.config.schema and ghost.config.loader.
"""
import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from ghost.config.schema import (
    GhostConfig,
    LLMConfig,
    LLMProvider,
    SandboxConfig,
    SecretConfig,
    TierConfig,
    WatchConfig,
)


# ─── GhostConfig ──────────────────────────────────────────────────────────────

def make_default_config() -> GhostConfig:
    return GhostConfig(
        llm=LLMConfig(
            tier2=TierConfig(provider=LLMProvider.OPENAI, model="gpt-4o-mini"),
            tier3=TierConfig(provider=LLMProvider.OPENAI, model="gpt-4o"),
        )
    )


def test_ghost_config_default_values():
    """GhostConfig defaults match expected paths and settings."""
    config = make_default_config()
    assert config.version == 1
    assert config.ghost_home == Path.home() / ".ghost"
    assert config.socket_path == Path.home() / ".ghost" / "ghost.sock"
    assert config.db_path == Path.home() / ".ghost" / "ghost.db"
    assert config.log_level == "INFO"


def test_ghost_config_llm_defaults():
    """LLMConfig tier defaults are correct."""
    config = make_default_config()
    assert config.llm.tier2.model == "gpt-4o-mini"
    assert config.llm.tier2.provider == LLMProvider.OPENAI
    assert config.llm.tier3.model == "gpt-4o"
    assert config.llm.request_timeout == 60
    assert config.llm.max_retries == 3


def test_ghost_config_watch_defaults():
    """WatchConfig defaults are sensible."""
    config = make_default_config()
    assert config.watch.debounce_seconds == 2.0
    assert config.watch.significance_threshold == 0.6
    assert config.watch.max_watched_dirs == 5
    assert config.watch.storm_threshold == 50


def test_ghost_config_sandbox_defaults():
    """SandboxConfig defaults match constants."""
    from ghost.constants import (
        DEFAULT_EXEC_TIMEOUT,
        DEFAULT_INSTALL_TIMEOUT,
        DEFAULT_MAX_OUTPUT_BYTES,
        DEFAULT_MEMORY_LIMIT_MB,
    )
    config = make_default_config()
    assert config.sandbox.exec_timeout_seconds == DEFAULT_EXEC_TIMEOUT
    assert config.sandbox.install_timeout_seconds == DEFAULT_INSTALL_TIMEOUT
    assert config.sandbox.memory_limit_mb == DEFAULT_MEMORY_LIMIT_MB
    assert config.sandbox.max_output_bytes == DEFAULT_MAX_OUTPUT_BYTES
    assert config.sandbox.prefer_uv is True


def test_ghost_config_custom_values():
    """GhostConfig accepts custom values."""
    config = GhostConfig(
        ghost_home=Path("/tmp/test_ghost"),
        socket_path=Path("/tmp/test_ghost/ghost.sock"),
        db_path=Path("/tmp/test_ghost/ghost.db"),
        log_level="DEBUG",
        llm=LLMConfig(
            tier2=TierConfig(model="gpt-4o-mini"),
            tier3=TierConfig(model="gpt-4o"),
        ),
    )
    assert config.ghost_home == Path("/tmp/test_ghost")
    assert config.log_level == "DEBUG"


def test_ghost_config_serialization_round_trip():
    """Config can be serialized to dict and re-created."""
    config = make_default_config()
    data = config.model_dump(mode="json")
    # Convert strings back to Path for reconstruction
    data["ghost_home"] = Path(data["ghost_home"])
    data["socket_path"] = Path(data["socket_path"])
    data["db_path"] = Path(data["db_path"])
    config2 = GhostConfig(**data)
    assert config2.version == config.version
    assert config2.llm.tier2.model == config.llm.tier2.model
    assert config2.llm.tier3.model == config.llm.tier3.model


# ─── LLMProvider ──────────────────────────────────────────────────────────────

def test_llm_provider_enum_values():
    """LLMProvider enum has the correct string values."""
    assert LLMProvider.OPENAI.value == "openai"
    assert LLMProvider.ANTHROPIC.value == "anthropic"
    assert LLMProvider.GOOGLE.value == "google"


def test_tier_config_defaults():
    """TierConfig uses sensible defaults."""
    tier = TierConfig(model="gpt-4o-mini")
    assert tier.provider == LLMProvider.OPENAI
    assert tier.max_tokens == 4096
    assert tier.temperature == 0.3


# ─── SecretConfig ─────────────────────────────────────────────────────────────

def test_secret_config_loads_from_env(monkeypatch, tmp_path):
    """SecretConfig picks up env vars."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-123")
    # Point env_file to a non-existent path to ensure env var takes precedence
    config = SecretConfig(
        _env_file=str(tmp_path / ".env"),
    )
    assert config.openai_api_key == "sk-test-123"


def test_secret_config_empty_defaults():
    """SecretConfig defaults to empty strings when no key is set."""
    config = SecretConfig(_env_file="/nonexistent/.env")
    # Should not raise; keys default to ""
    assert isinstance(config.openai_api_key, str)
    assert isinstance(config.anthropic_api_key, str)
    assert isinstance(config.google_api_key, str)
