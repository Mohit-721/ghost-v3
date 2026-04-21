"""ghost doctor — System health check."""

import os
import shutil
import sys
from pathlib import Path

from ghost.cli.display import console, print_error, print_ghost, print_success, print_warning
from ghost.constants import DEFAULT_GHOST_HOME


def doctor_cmd() -> None:
    """Run system health checks."""
    print_ghost("Running diagnostics...\n")
    all_ok = True

    # Python version
    py_ver = sys.version_info
    if py_ver >= (3, 11):
        print_success(f"Python {py_ver.major}.{py_ver.minor}.{py_ver.micro}")
    else:
        print_error(f"Python {py_ver.major}.{py_ver.minor} (need >=3.11)")
        all_ok = False

    # uv installed?
    if shutil.which("uv"):
        print_success("uv is installed (tools can auto-install dependencies)")
    else:
        print_warning("uv not found. Install it for automatic tool dependency management.")
        console.print("   [dim]curl -LsSf https://astral.sh/uv/install.sh | sh[/dim]")

    # Ghost home exists?
    ghost_home = Path(os.environ.get("GHOST_HOME", str(DEFAULT_GHOST_HOME)))
    if ghost_home.exists():
        print_success(f"Ghost home: {ghost_home}")
    else:
        print_warning(f"Ghost home not found: {ghost_home}")
        console.print("   Run [cyan]ghost init[/cyan] first.")
        all_ok = False

    # API keys configured?
    env_file = ghost_home / ".env"
    if env_file.exists():
        content = env_file.read_text()
        has_key = any(
            line.strip()
            and not line.startswith("#")
            and "=" in line
            and line.split("=", 1)[1].strip()
            for line in content.split("\n")
            if "API_KEY" in line
        )
        if has_key:
            print_success("API key(s) configured in .env")
        else:
            print_warning("No API keys found in .env")
            console.print("   Edit [cyan]~/.ghost/.env[/cyan] and add at least one API key.")
    else:
        print_warning(".env file not found")

    # sqlite-vec available?
    try:
        import sqlite3

        conn = sqlite3.connect(":memory:")
        conn.enable_load_extension(True)
        conn.load_extension("vec0")
        conn.close()
        print_success("sqlite-vec extension available (vector search enabled)")
    except Exception:
        print_warning("sqlite-vec not available (vector search disabled, FTS5 fallback)")

    # Daemon running?
    try:
        from ghost.cli.commands.start import _get_client

        client, _ = _get_client()
        if client.is_daemon_running():
            print_success("Ghost daemon is running")
        else:
            print_warning("Ghost daemon is not running")
    except Exception:
        print_warning("Cannot check daemon status")

    # Disk space
    total, used, free = shutil.disk_usage(str(ghost_home.parent))
    free_gb = free / (1024**3)
    if free_gb > 1:
        print_success(f"Disk space: {free_gb:.1f} GB free")
    else:
        print_warning(f"Low disk space: {free_gb:.2f} GB free")

    console.print()
    if all_ok:
        print_ghost("All checks passed! Ghost is ready.")
    else:
        print_ghost("Some issues found. See warnings above.")
