"""
Config loader: TOML file → GhostConfig.

Priority: config.toml → environment variables → defaults.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ghost.config.schema import GhostConfig

logger = logging.getLogger(__name__)



def load_config(config_path: Path | None = None) -> GhostConfig:
    """
    Load Ghost configuration.

    Args:
        config_path: Optional explicit path to config.toml.
                     Defaults to ~/.ghost/config.toml.

    Returns:
        Fully populated GhostConfig instance.
    """
    from ghost.config.schema import GhostConfig, LLMConfig, LLMProvider, TierConfig
    from ghost.constants import DEFAULT_CONFIG_FILE, DEFAULT_GHOST_HOME

    ghost_home = Path(os.environ.get("GHOST_HOME", str(DEFAULT_GHOST_HOME)))

    if config_path is None:
        config_path = ghost_home / DEFAULT_CONFIG_FILE

    if config_path.exists():
        # Load from TOML — tomllib is built-in on Python 3.11+
        import tomllib  # type: ignore[no-redef]

        with open(config_path, "rb") as f:
            data = tomllib.load(f)

        # Apply config version migrations if needed
        from ghost.config.migrations import migrate_config

        data = migrate_config(data)

        return GhostConfig(**data)
    else:
        # Return defaults
        logger.info(f"No config file at {config_path}, using defaults")
        return GhostConfig(
            ghost_home=ghost_home,
            socket_path=ghost_home / "ghost.sock",
            db_path=ghost_home / "ghost.db",
            llm=LLMConfig(
                tier2=TierConfig(provider=LLMProvider.OPENAI, model="gpt-4o-mini"),
                tier3=TierConfig(provider=LLMProvider.OPENAI, model="gpt-4o"),
            ),
            log_level=os.environ.get("GHOST_LOG_LEVEL", "INFO"),
        )


def save_config(config: GhostConfig, config_path: Path | None = None) -> None:
    """Save current config to TOML file."""
    import tomli_w  # type: ignore[import-untyped]

    from ghost.constants import DEFAULT_CONFIG_FILE

    if config_path is None:
        config_path = config.ghost_home / DEFAULT_CONFIG_FILE

    config_path.parent.mkdir(parents=True, exist_ok=True)

    data = config.model_dump(mode="json")
    # Convert Path objects to strings for TOML serialization
    for key in ("ghost_home", "socket_path", "db_path"):
        if key in data:
            data[key] = str(data[key])

    with open(config_path, "wb") as f:
        tomli_w.dump(data, f)
