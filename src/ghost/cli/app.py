"""
Ghost CLI — main entry point.

All commands communicate with the daemon via sync httpx over UDS.
The CLI is fully synchronous (Typer is sync).
"""

import typer
from rich.console import Console

from ghost.constants import VERSION

app = typer.Typer(
    name="ghost",
    help="👻 Ghost — The AI daemon that haunts your machine.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)

console = Console()

# Import and register command groups
from ghost.cli.commands import (  # noqa: E402
    approve,
    cost,
    doctor,
    forge,
    gc,
    init,
    logs,
    memory,
    start,
    tools,
    uninstall,
    watch,
)

# Register individual commands
app.command(name="init", help="Initialize Ghost in the current directory")(init.init_cmd)
app.command(name="start", help="Start the Ghost daemon")(start.start_cmd)
app.command(name="stop", help="Stop the Ghost daemon")(start.stop_cmd)
app.command(name="restart", help="Restart the Ghost daemon")(start.restart_cmd)
app.command(name="status", help="Show daemon status")(start.status_cmd)
app.command(name="forge", help="Synthesize a new tool")(forge.forge_cmd)
app.command(name="approve", help="Approve a quarantined tool")(approve.approve_cmd)
app.command(name="reject", help="Reject a quarantined tool")(approve.reject_cmd)
app.command(name="sync", help="Force a reconciliation scan")(watch.sync_cmd)

# Register sub-command groups (typer sub-apps)
app.add_typer(watch.watch_app, name="watch", help="Manage watched directories")
app.add_typer(tools.tools_app, name="tools", help="Manage registered tools")
app.add_typer(memory.memory_app, name="memory", help="Search and manage memory")
app.add_typer(logs.logs_app, name="logs", help="View audit logs")
app.add_typer(cost.cost_app, name="cost", help="View API costs")
app.command(name="debug", help="View operational logs")(logs.debug_cmd)
app.command(name="doctor", help="Run system health checks")(doctor.doctor_cmd)
app.command(name="gc", help="Garbage collect old data")(gc.gc_cmd)
app.command(name="uninstall", help="Remove Ghost completely")(uninstall.uninstall_cmd)


@app.callback(invoke_without_command=True)
def version_callback(
    version: bool = typer.Option(False, "--version", "-v", help="Show version"),
) -> None:
    if version:
        console.print(f"👻 Ghost v{VERSION}")
        raise typer.Exit()


def main() -> None:
    """Entry point for the `ghost` CLI."""
    app()
