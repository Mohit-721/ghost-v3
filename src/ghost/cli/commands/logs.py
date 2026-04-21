"""ghost logs / ghost debug — View logs."""

import typer

from ghost.cli.display import console, print_audit_logs, print_error

logs_app = typer.Typer(no_args_is_help=False, invoke_without_command=True)


@logs_app.callback(invoke_without_command=True)
def logs_default(
    topic: str | None = typer.Option(None, "--topic", "-t", help="Filter by topic"),
    limit: int = typer.Option(50, "--limit", "-n", help="Number of entries"),
) -> None:
    """View audit log (semantic events)."""
    from ghost.cli.commands.start import _get_client

    client, _ = _get_client()
    try:
        logs = client.get_audit_logs(topic=topic, limit=limit)
        print_audit_logs(logs)
    except Exception as e:
        print_error(f"Failed: {e}")


def debug_cmd(
    level: str | None = typer.Option(
        None, "--level", "-l", help="Set log level (DEBUG/INFO/WARNING)"
    ),
    follow: bool = typer.Option(False, "--follow", "-f", help="Follow log output"),
    lines: int = typer.Option(50, "--lines", "-n", help="Number of lines to show"),
) -> None:
    """View operational log (Python debug output)."""
    import os
    from pathlib import Path

    from ghost.constants import DEFAULT_GHOST_HOME, LOG_FILE, LOGS_DIR

    ghost_home = Path(os.environ.get("GHOST_HOME", str(DEFAULT_GHOST_HOME)))
    log_file = ghost_home / LOGS_DIR / LOG_FILE

    # Set log level on running daemon
    if level:
        from ghost.cli.commands.start import _get_client

        client, _ = _get_client()
        try:
            client.set_log_level(level.upper())
            console.print(f"Log level set to [cyan]{level.upper()}[/cyan]")
        except Exception as e:
            print_error(f"Could not set log level: {e}")
        return

    if not log_file.exists():
        print_error(f"No log file at {log_file}")
        console.print("   Is the daemon running? Try: [cyan]ghost start[/cyan]")
        return

    if follow:
        # Tail -f equivalent
        import subprocess

        try:
            subprocess.run(["tail", "-f", str(log_file)])
        except KeyboardInterrupt:
            pass
    else:
        # Show last N lines
        content = log_file.read_text()
        last_lines = content.strip().split("\n")[-lines:]
        for line in last_lines:
            console.print(line, style="dim")
