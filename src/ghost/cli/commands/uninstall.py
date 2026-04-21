"""ghost uninstall — Full removal."""

import os
import shutil
from pathlib import Path

from ghost.cli.display import confirm_action, console, print_ghost, print_success, print_warning
from ghost.constants import DEFAULT_GHOST_HOME


def uninstall_cmd() -> None:
    """Remove Ghost completely (daemon + data + config)."""
    ghost_home = Path(os.environ.get("GHOST_HOME", str(DEFAULT_GHOST_HOME)))

    console.print()
    print_warning("This will:")
    console.print("   1. Stop the Ghost daemon (if running)")
    console.print("   2. Delete ~/.ghost/ (database, tools, config, logs)")
    console.print()
    console.print(
        "   [red]Your synthesized tools and knowledge graph will be permanently deleted.[/red]"
    )
    console.print()

    if not confirm_action("Proceed with uninstall?"):
        console.print("Cancelled.")
        return

    # Stop daemon
    try:
        from ghost.cli.commands.start import stop_cmd

        stop_cmd()
    except Exception:
        pass

    # Delete ghost home
    if ghost_home.exists():
        size = sum(f.stat().st_size for f in ghost_home.rglob("*") if f.is_file())
        size_mb = size / (1024 * 1024)
        shutil.rmtree(str(ghost_home))
        print_success(f"Deleted {ghost_home} ({size_mb:.1f} MB)")

    console.print()
    print_ghost("Ghost has been fully removed.")
    console.print("   Run [cyan]pip uninstall ghost-ai[/cyan] to remove the Python package.")
