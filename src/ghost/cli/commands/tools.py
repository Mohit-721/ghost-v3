"""ghost tools — Manage registered tools."""

import typer

from ghost.cli.display import console, print_error, print_tool_table

tools_app = typer.Typer(no_args_is_help=True)


@tools_app.command("list")
def tools_list(
    status: str | None = typer.Option(None, "--status", "-s", help="Filter by status"),
) -> None:
    """List all tools."""
    from ghost.cli.commands.start import _get_client

    client, _ = _get_client()
    try:
        tools = client.list_tools(status=status)
        if tools:
            print_tool_table(tools)
        else:
            console.print('No tools found. Forge one with: [cyan]ghost forge "..."[/cyan]')
    except Exception as e:
        print_error(f"Failed: {e}")


@tools_app.command("run")
def tools_run(
    name: str = typer.Argument(..., help="Tool name to run"),
    project_dir: str | None = typer.Option(None, "--project-dir", "-d", help="Project directory"),
    args: list[str] | None = typer.Argument(None, help="Arguments to pass to the tool"),
) -> None:
    """Run a registered tool."""
    from ghost.cli.commands.start import _get_client

    client, _ = _get_client()
    try:
        result = client.run_tool(name, args=args, project_dir=project_dir)
        if result.get("stdout"):
            console.print(result["stdout"])
        if result.get("stderr"):
            console.print(result["stderr"], style="red")
        if result.get("timed_out"):
            print_error("Tool execution timed out")
    except Exception as e:
        print_error(f"Failed: {e}")


@tools_app.command("info")
def tools_info(
    name: str = typer.Argument(..., help="Tool name"),
) -> None:
    """Show detailed info about a tool."""
    from ghost.cli.commands.start import _get_client

    client, _ = _get_client()
    try:
        tools = client.list_tools()
        match = [t for t in tools if t.get("name") == name]
        if not match:
            print_error(f"Tool '{name}' not found")
            return
        tool = match[0]
        for key, val in tool.items():
            console.print(f"  [cyan]{key}[/cyan]: {val}")
    except Exception as e:
        print_error(f"Failed: {e}")


@tools_app.command("delete")
def tools_delete(
    name: str = typer.Argument(..., help="Tool name to delete"),
) -> None:
    """Delete a tool."""
    from ghost.cli.display import confirm_action

    if not confirm_action(f"Delete tool '{name}'?"):
        return
    console.print(f"Tool '{name}' deleted.", style="yellow")
