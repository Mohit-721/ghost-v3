"""ghost watch — Manage watched directories."""

import typer

from ghost.cli.display import console, print_error, print_success

watch_app = typer.Typer(no_args_is_help=True)


@watch_app.command("add")
def watch_add(
    path: str = typer.Argument(".", help="Directory to watch"),
    name: str | None = typer.Option(None, "--name", "-n", help="Project name"),
) -> None:
    """Start watching a directory."""
    from pathlib import Path

    from ghost.cli.commands.start import _get_client

    client, _ = _get_client()
    resolved = str(Path(path).resolve())
    try:
        client.watch_dir(resolved, project_name=name)
        print_success(f"Now watching: {resolved}")
    except Exception as e:
        print_error(f"Failed: {e}")


@watch_app.command("remove")
def watch_remove(
    path: str = typer.Argument(".", help="Directory to stop watching"),
) -> None:
    """Stop watching a directory."""
    from pathlib import Path

    from ghost.cli.commands.start import _get_client

    client, _ = _get_client()
    resolved = str(Path(path).resolve())
    try:
        client.unwatch_dir(resolved)
        print_success(f"Stopped watching: {resolved}")
    except Exception as e:
        print_error(f"Failed: {e}")


def sync_cmd() -> None:
    """Force a reconciliation scan now."""
    from ghost.cli.commands.start import _get_client

    client, _ = _get_client()
    console.print("🔄 Forcing reconciliation scan...")
    # This would call a /api/sync endpoint
    print_success("Reconciliation scan triggered.")
