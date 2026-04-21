"""Shared test fixtures for Ghost test suite."""

import asyncio
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture
def tmp_ghost_home(tmp_path):
    """Create a temporary ~/.ghost directory structure."""
    ghost_home = tmp_path / ".ghost"
    ghost_home.mkdir()
    (ghost_home / "quarantine").mkdir()
    (ghost_home / "tools").mkdir()
    (ghost_home / "logs").mkdir()
    return ghost_home


@pytest.fixture
def tmp_project_dir(tmp_path):
    """Create a temporary project directory with sample files."""
    project = tmp_path / "test-project"
    project.mkdir()
    (project / "main.py").write_text('print("hello")\n')
    (project / "utils.py").write_text('def helper(): pass\n')
    (project / "README.md").write_text("# Test Project\n")
    return project


@pytest.fixture
def mock_config(tmp_ghost_home):
    """Create a mock GhostConfig pointing to temp directories."""
    from ghost.config.schema import GhostConfig, LLMConfig, TierConfig

    return GhostConfig(
        ghost_home=tmp_ghost_home,
        socket_path=tmp_ghost_home / "ghost.sock",
        db_path=tmp_ghost_home / "ghost.db",
        llm=LLMConfig(
            tier2=TierConfig(provider="openai", model="gpt-4o-mini"),
            tier3=TierConfig(provider="openai", model="gpt-4o"),
        ),
    )
