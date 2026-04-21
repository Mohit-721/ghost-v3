"""ghost approve / reject — Manage quarantined tools."""

import typer

from ghost.cli.display import console, print_error, print_ghost, print_success


def approve_cmd(
    tool_id: str = typer.Argument(..., help="Tool ID (or prefix) to approve"),
) -> None:
    """Approve a quarantined tool for execution."""
    from ghost.cli.commands.start import _get_client

    client, config = _get_client()

    if not client.is_daemon_running():
        print_error("Ghost daemon is not running.")
        raise typer.Exit(code=1)

    try:
        result = client.approve_tool(tool_id)
        print_success(f"Tool '{result.get('name', tool_id)}' approved!")
        console.print(f"   Run it with: [cyan]ghost tools run {result.get('name', tool_id)}[/cyan]")
    except Exception as e:
        print_error(f"Approve failed: {e}")
        raise typer.Exit(code=1)


def reject_cmd(
    tool_id: str = typer.Argument(..., help="Tool ID (or prefix) to reject"),
) -> None:
    """Reject and delete a quarantined tool."""
    from ghost.cli.commands.start import _get_client

    client, config = _get_client()

    if not client.is_daemon_running():
        print_error("Ghost daemon is not running.")
        raise typer.Exit(code=1)

    try:
        client.reject_tool(tool_id)
        print_ghost("Tool rejected and removed.")
    except Exception as e:
        print_error(f"Reject failed: {e}")
        raise typer.Exit(code=1)
