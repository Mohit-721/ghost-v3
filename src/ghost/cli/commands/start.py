"""ghost start / stop / restart / status commands."""

import shutil
import subprocess
import sys
import time
from typing import Any

import typer

from ghost.cli.display import console, print_error, print_ghost, print_health, print_success


def _get_client() -> tuple[Any, Any]:
    from ghost.cli.client import GhostClient
    from ghost.config.loader import load_config

    config = load_config()
    return GhostClient(config.socket_path, config.ghost_home), config


def start_cmd() -> None:
    """Start the Ghost daemon as a background process."""
    client, config = _get_client()

    if client.is_daemon_running():
        print_ghost("Ghost daemon is already running")
        return

    # Find ghostd binary
    ghostd_path = shutil.which("ghostd")
    if ghostd_path:
        cmd = [ghostd_path]
    else:
        cmd = [sys.executable, "-m", "ghost.core.daemon"]

    # Launch detached
    proc = subprocess.Popen(
        cmd,
        start_new_session=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
    )

    # Wait up to 5s for daemon to be ready
    for _ in range(50):
        time.sleep(0.1)
        if client.is_daemon_running():
            print_ghost(f"Ghost daemon started (PID {proc.pid})")
            console.print(f"   Socket: {client.socket_path}")
            return

    print_error("Daemon failed to start. Check `ghost debug` for logs.")
    raise typer.Exit(code=1)


def stop_cmd() -> None:
    """Stop the Ghost daemon gracefully."""
    client, config = _get_client()

    if not client.is_daemon_running():
        print_ghost("Ghost daemon is not running")
        return

    # Try graceful shutdown via API
    client.shutdown()

    # Wait for process to exit
    for _ in range(30):
        time.sleep(0.1)
        if not client.is_daemon_running():
            print_success("Daemon stopped")
            return

    # Fallback: SIGTERM via PID file
    from ghost.core.lifecycle import stop_daemon_by_pid

    pid_file = config.ghost_home / "ghost.pid"
    if pid_file.exists():
        try:
            pid = int(pid_file.read_text().strip())
            stop_daemon_by_pid(pid)
        except (ValueError, OSError):
            pass

    # Clean up artifacts
    pid_file.unlink(missing_ok=True)
    config.socket_path.unlink(missing_ok=True)
    print_success("Daemon stopped")


def restart_cmd() -> None:
    """Restart the Ghost daemon."""
    stop_cmd()
    time.sleep(0.5)
    start_cmd()


def status_cmd() -> None:
    """Show Ghost daemon status."""
    client, config = _get_client()

    if not client.is_daemon_running():
        print_ghost("Ghost daemon is [red]not running[/red]")
        console.print("   Run [cyan]ghost start[/cyan] to start it.")
        return

    try:
        health = client.get_health()
        print_health(health)
    except Exception as e:
        print_error(f"Could not get status: {e}")
