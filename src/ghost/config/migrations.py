"""Config version transforms. Handles upgrading old config.toml formats."""

import logging

logger = logging.getLogger(__name__)


def migrate_config(data: dict) -> dict:
    """Apply sequential config migrations based on version field."""
    version = data.get("version", 0)

    if version < 1:
        data = _migrate_v0_to_v1(data)

    # Future: if version < 2: data = _migrate_v1_to_v2(data)

    return data


def _migrate_v0_to_v1(data: dict) -> dict:
    """Initial migration: ensure all required fields exist with defaults."""
    data.setdefault("version", 1)
    data.setdefault("log_level", "INFO")
    logger.info("Migrated config from v0 to v1")
    return data
