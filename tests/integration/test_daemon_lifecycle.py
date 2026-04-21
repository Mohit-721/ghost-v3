"""Tests for daemon lifecycle and UDS bounds checking."""

import os
from pathlib import Path

from ghost.config.schema import GhostConfig
from ghost.core.daemon import ensure_single_instance, safe_socket_path


def test_safe_socket_path_under_limit(tmp_path: Path) -> None:
    """Socket path under limit is returned identically."""
    from ghost.config.schema import LLMConfig, TierConfig

    config = GhostConfig(
        ghost_home=tmp_path,
        socket_path=tmp_path / "ghost.sock",
        llm=LLMConfig(tier2=TierConfig(model="mock-tier2"), tier3=TierConfig(model="mock-tier3")),
    )
    result = safe_socket_path(config)
    assert result == config.socket_path


def test_safe_socket_path_over_limit(tmp_path: Path) -> None:
    """Socket path over limit uses fallback and writes pointer."""
    # Create an artificially long path exceeding UDS bounds
    long_dir_name = "x" * 150
    long_path = tmp_path / long_dir_name / "ghost.sock"

    from ghost.config.schema import LLMConfig, TierConfig

    config = GhostConfig(
        ghost_home=tmp_path,
        socket_path=long_path,
        llm=LLMConfig(tier2=TierConfig(model="mock-tier2"), tier3=TierConfig(model="mock-tier3")),
    )

    result = safe_socket_path(config)

    # Must use fallback instead of the huge path
    assert result != long_path
    assert str(result).startswith("/tmp/ghost_")

    # Needs a pointer
    pointer = tmp_path / "socket_path"
    assert pointer.exists()
    assert pointer.read_text().strip() == str(result)


def test_ensure_single_instance_clean(tmp_path: Path) -> None:
    """No existing PID file."""
    from ghost.config.schema import LLMConfig, TierConfig

    config = GhostConfig(
        ghost_home=tmp_path,
        socket_path=tmp_path / "ghost.sock",
        llm=LLMConfig(tier2=TierConfig(model="mock-tier2"), tier3=TierConfig(model="mock-tier3")),
    )
    ensure_single_instance(config)

    pid_file = tmp_path / "ghost.pid"
    assert pid_file.exists()
    assert int(pid_file.read_text().strip()) == os.getpid()


def test_ensure_single_instance_stale(tmp_path: Path) -> None:
    """Stale PID file where process DOES NOT exist."""
    from ghost.config.schema import LLMConfig, TierConfig

    config = GhostConfig(
        ghost_home=tmp_path,
        socket_path=tmp_path / "ghost.sock",
        llm=LLMConfig(tier2=TierConfig(model="mock-tier2"), tier3=TierConfig(model="mock-tier3")),
    )
    pid_file = tmp_path / "ghost.pid"

    # Find a free PID (use notoriously high PID)
    free_pid = 999998

    pid_file.write_text(str(free_pid))

    # Should replace it cleanly
    ensure_single_instance(config)
    assert pid_file.exists()
    assert int(pid_file.read_text().strip()) == os.getpid()


def test_ensure_single_instance_permission_error(tmp_path: Path, monkeypatch: object) -> None:
    """PID belongs to another user (Bug #6 Fix - PermissionError)."""
    import os

    from ghost.config.schema import LLMConfig, TierConfig

    config = GhostConfig(
        ghost_home=tmp_path,
        socket_path=tmp_path / "ghost.sock",
        llm=LLMConfig(tier2=TierConfig(model="mock-tier2"), tier3=TierConfig(model="mock-tier3")),
    )
    pid_file = tmp_path / "ghost.pid"
    pid_file.write_text("99999")

    # Patch os.kill to raise PermissionError
    def mock_kill(pid: int, sig: int) -> None:
        if sig == 0:
            raise PermissionError("Access denied")

    monkeypatch.setattr(os, "kill", mock_kill)

    ensure_single_instance(config)

    # Stale error caught, new PID written successfully
    assert int(pid_file.read_text().strip()) == os.getpid()
