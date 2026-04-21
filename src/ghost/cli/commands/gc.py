"""ghost gc — Garbage collection."""

import typer

from ghost.cli.display import console, print_ghost, print_success


def gc_cmd(
    days: int = typer.Option(30, "--days", "-d", help="Prune entries older than N days"),
) -> None:
    """Garbage collect old audit logs and retired tools."""
    print_ghost(f"Garbage collecting entries older than {days} days...")
    # This would call /api/gc on the daemon
    # For now, placeholder
    console.print("   Audit log pruning: [dim]not yet implemented (Phase 4)[/dim]")
    console.print("   Retired tool cleanup: [dim]not yet implemented (Phase 4)[/dim]")
    print_success("Done.")
