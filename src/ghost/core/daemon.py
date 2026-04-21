"""
Daemon entry point: ghostd.

Handles:
1. Single-instance enforcement via PID file
2. Stale socket cleanup
3. UDS path length safety
4. SQLite integrity check
5. Uvicorn launch on Unix Domain Socket

NOTE: Signal handling is done via FastAPI lifespan (app.py), NOT signal.signal().
This avoids conflicting with uvicorn's own signal handlers (Bug #3 fix).
"""

import hashlib
import logging
import os
import sys
from pathlib import Path

from ghost.config.schema import GhostConfig

logger = logging.getLogger(__name__)


def safe_socket_path(config: GhostConfig) -> Path:
    """
    Ensure socket path is within OS kernel limit.

    Edge Case 1 fix: UDS path limit is 108 chars on Linux, 104 on macOS.
    If the default path exceeds this, fall back to /tmp/ghost_<hash>.sock
    and write a pointer file so the CLI knows where to find it.
    """
    from ghost.constants import DEFAULT_SOCKET_POINTER, UDS_PATH_LIMIT_LINUX, UDS_PATH_LIMIT_MACOS

    resolved = str(config.socket_path.resolve())
    limit = UDS_PATH_LIMIT_MACOS if sys.platform == "darwin" else UDS_PATH_LIMIT_LINUX

    if len(resolved) < limit:
        return config.socket_path

    # Fallback: /tmp/ghost_<hash>.sock
    home_hash = hashlib.md5(str(config.ghost_home).encode()).hexdigest()[:12]
    fallback = Path(f"/tmp/ghost_{home_hash}.sock")

    # Write pointer so CLI can find the socket
    pointer_file = config.ghost_home / DEFAULT_SOCKET_POINTER
    pointer_file.write_text(str(fallback))

    logger.warning(
        f"Socket path too long ({len(resolved)} chars, limit {limit}). Using fallback: {fallback}"
    )
    return fallback


def ensure_single_instance(config: GhostConfig) -> None:
    """
    Prevent multiple daemon instances. Clean up stale artifacts.

    Bug #6 fix: Catches PermissionError from os.kill(pid, 0) which occurs
    when the PID exists but belongs to another user (PID reuse scenario).
    """
    pid_file = config.ghost_home / "ghost.pid"
    sock_file = config.socket_path

    if pid_file.exists():
        try:
            old_pid = int(pid_file.read_text().strip())
            os.kill(old_pid, 0)  # Signal 0 = check existence
            # Process exists — another daemon is running
            print(f"👻 Ghost daemon already running (PID {old_pid})", file=sys.stderr)
            print("   Run 'ghost stop' first, or 'ghost restart'.", file=sys.stderr)
            sys.exit(1)
        except (ProcessLookupError, PermissionError, ValueError):
            # ProcessLookupError: PID doesn't exist (stale)
            # PermissionError: PID exists but belongs to another user (PID reuse)
            # ValueError: PID file contains garbage
            pid_file.unlink(missing_ok=True)

    # Clean stale socket file (left over from crash)
    if sock_file.exists():
        sock_file.unlink()

    # Write current PID
    pid_file.write_text(str(os.getpid()))


def main() -> None:
    """Entry point for `ghostd` command."""
    import uvicorn

    from ghost.config.loader import load_config
    from ghost.memory.database import check_integrity

    config = load_config()
    config.ghost_home.mkdir(parents=True, exist_ok=True)

    # Setup operational logging first
    from ghost.core.logging import setup_logging

    log_listener = setup_logging(config.ghost_home, config.log_level)

    logger.info(f"Ghost daemon starting (v{config.version})")

    # Integrity check on database
    check_integrity(config.db_path)

    # Single instance guard
    ensure_single_instance(config)

    # Resolve safe socket path (Edge Case 1)
    socket_path = safe_socket_path(config)

    # Create FastAPI app (lifespan handles startup/shutdown)
    from ghost.core.app import create_app

    app = create_app(config, log_listener)

    # Launch uvicorn on Unix socket
    # NOTE: uvicorn handles SIGTERM/SIGINT — we piggyback via lifespan (Bug #3 fix)
    try:
        uvicorn.run(
            app,
            uds=str(socket_path),
            log_level=config.log_level.lower(),
            access_log=False,
        )
    finally:
        # Cleanup (in case lifespan didn't run)
        pid_file = config.ghost_home / "ghost.pid"
        pid_file.unlink(missing_ok=True)
        socket_path.unlink(missing_ok=True)
        log_listener.stop()


if __name__ == "__main__":
    main()
