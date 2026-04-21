"""ghost memory — Search and manage the knowledge graph."""

import typer

from ghost.cli.display import print_error, print_info, print_search_results

memory_app = typer.Typer(no_args_is_help=True)


@memory_app.command("search")
def memory_search(
    query: str = typer.Argument(..., help="Search query"),
    project: str | None = typer.Option(None, "--project", "-p", help="Scope to project"),
) -> None:
    """Search the knowledge graph."""
    from ghost.cli.commands.start import _get_client

    client, _ = _get_client()
    try:
        results = client.search_memory(query, project_id=project)
        print_search_results(results)
    except Exception as e:
        print_error(f"Search failed: {e}")


@memory_app.command("stats")
def memory_stats() -> None:
    """Show memory statistics."""
    from ghost.cli.commands.start import _get_client

    client, _ = _get_client()
    try:
        # Just call a basic request to check it works
        client.get_health()
        print_info("Status: see `ghost status` for full details")
    except Exception as e:
        print_error(f"Failed: {e}")
