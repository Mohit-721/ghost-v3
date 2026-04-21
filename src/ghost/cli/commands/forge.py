"""ghost forge — Synthesize a tool from natural language."""

import typer

from ghost.cli.display import console, print_error, print_ghost, print_success, print_tool_code


def forge_cmd(
    intent: str = typer.Argument(..., help="What you want the tool to do"),
    project: str | None = typer.Option(None, "--project", "-p", help="Project ID for context"),
) -> None:
    """Synthesize a new tool from natural language intent."""
    from ghost.cli.commands.start import _get_client

    client, config = _get_client()

    if not client.is_daemon_running():
        print_error("Ghost daemon is not running. Run `ghost start` first.")
        raise typer.Exit(code=1)

    print_ghost(f'Forging tool: "{intent}"')
    console.print("   This may take a moment...", style="dim")

    try:
        result = client.forge(intent, project_id=project)

        console.print()
        print_success(f"Tool '{result['name']}' synthesized!")
        console.print(f"   ID: {result['id']}")
        console.print(f"   Description: {result.get('description', 'N/A')}")
        console.print("   Status: [yellow]quarantined[/yellow]")

        if result.get("code_preview"):
            print_tool_code(result["code_preview"], title=result["name"])

        console.print()
        console.print("   To approve and run: [cyan]ghost approve " + result["id"][:8] + "[/cyan]")
        console.print("   To reject: [cyan]ghost reject " + result["id"][:8] + "[/cyan]")

    except Exception as e:
        print_error(f"Forge failed: {e}")
        raise typer.Exit(code=1)
