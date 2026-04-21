"""ghost cost — View API spend."""

import typer

from ghost.cli.display import console, print_cost_summary, print_error

cost_app = typer.Typer(no_args_is_help=False, invoke_without_command=True)


@cost_app.callback(invoke_without_command=True)
def cost_default(
    detail: bool = typer.Option(False, "--detail", "-d", help="Show detailed breakdown"),
) -> None:
    """View API cost summary."""
    from ghost.cli.commands.start import _get_client

    client, _ = _get_client()
    try:
        cost = client.get_cost(detail=detail)
        if cost:
            print_cost_summary(cost)
        else:
            console.print("No cost data yet. Forge a tool to see costs.")
    except Exception as e:
        print_error(f"Failed: {e}")
