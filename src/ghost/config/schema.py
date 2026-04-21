"""
Ghost configuration schema — Pydantic v2 models.

Config is loaded from ~/.ghost/config.toml.
API keys are loaded from ~/.ghost/.env via SecretConfig (pydantic-settings).
"""
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class LLMProvider(StrEnum):
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GOOGLE = "google"


class TierConfig(BaseModel):
    """Configuration for a single LLM tier."""

    provider: LLMProvider = LLMProvider.OPENAI
    model: str
    max_tokens: int = 4096
    temperature: float = 0.3


class LLMConfig(BaseModel):
    """LLM provider and model configuration."""

    default_provider: LLMProvider = LLMProvider.OPENAI
    tier2: TierConfig  # Tool synthesis, triage (mid-range)
    tier3: TierConfig  # Complex analysis (high-end)
    request_timeout: int = 60
    max_retries: int = 3


class WatchConfig(BaseModel):
    """File watching and event processing configuration."""

    debounce_seconds: float = 2.0
    significance_threshold: float = 0.6
    reconcile_interval_minutes: int = 60
    max_watched_dirs: int = 5
    storm_threshold: int = 50
    storm_window_seconds: float = 3.0
    storm_cooldown_seconds: float = 30.0


class SandboxConfig(BaseModel):
    """Tool execution sandbox limits."""

    exec_timeout_seconds: int = 30
    install_timeout_seconds: int = 120  # For uv first-run cold cache
    memory_limit_mb: int = 256
    max_output_bytes: int = 1_048_576
    prefer_uv: bool = True


class GhostConfig(BaseModel):
    """Root configuration model."""

    version: int = 1
    ghost_home: Path = Field(default_factory=lambda: Path.home() / ".ghost")
    socket_path: Path = Field(
        default_factory=lambda: Path.home() / ".ghost" / "ghost.sock"
    )
    db_path: Path = Field(
        default_factory=lambda: Path.home() / ".ghost" / "ghost.db"
    )
    llm: LLMConfig
    watch: WatchConfig = Field(default_factory=WatchConfig)
    sandbox: SandboxConfig = Field(default_factory=SandboxConfig)
    log_level: str = "INFO"


class SecretConfig(BaseSettings):
    """
    API keys loaded from ~/.ghost/.env (NOT config.toml).
    Uses pydantic-settings for env file + env var loading.

    Bug #4 fix (final_bug_sweep.md):
    Uses model_config = SettingsConfigDict(...) instead of inner Config class.
    Pydantic v2 deprecated the inner Config class.
    """

    model_config = SettingsConfigDict(
        env_file=str(Path.home() / ".ghost" / ".env"),
        env_file_encoding="utf-8",
    )

    openai_api_key: str = ""
    anthropic_api_key: str = ""
    google_api_key: str = ""
