"""Rich terminal display helpers for the Ghost CLI."""

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

console = Console()


def print_success(message: str) -> None:
    console.print(f"✅ {message}", style="green")


def print_error(message: str) -> None:
    console.print(f"❌ {message}", style="red bold")


def print_warning(message: str) -> None:
    console.print(f"⚠️  {message}", style="yellow")


def print_info(message: str) -> None:
    console.print(f"ℹ️  {message}", style="blue")


def print_ghost(message: str) -> None:
    console.print(f"👻 {message}", style="bold")


def print_tool_code(code: str, title: str = "Generated Tool") -> None:
    """Display tool source code with syntax highlighting."""
    syntax = Syntax(code, "python", theme="monokai", line_numbers=True)
    console.print(Panel(syntax, title=f"🔧 {title}", border_style="cyan"))


def print_tool_table(tools: list[dict[str, str | int]]) -> None:
    """Display tools in a table."""
    table = Table(title="🔧 Ghost Tools", box=box.ROUNDED)
    table.add_column("Name", style="cyan")
    table.add_column("Version", justify="center")
    table.add_column("Status", justify="center")
    table.add_column("Runs", justify="right")
    table.add_column("Description")

    for tool in tools:
        status_str = str(tool.get("status", ""))
        status_style = {
            "quarantined": "yellow",
            "approved": "green",
            "registered": "green bold",
        }.get(status_str, "white")

        desc = str(tool.get("description", ""))
        display_desc = (desc[:60] + "...") if len(desc) > 60 else desc

        table.add_row(
            str(tool.get("name", "?")),
            str(tool.get("version", "?")),
            Text(status_str, style=status_style) if status_str else Text("?"),
            str(tool.get("runs", 0)),
            display_desc,
        )

    console.print(table)


def print_cost_summary(cost: dict[str, float | int | str]) -> None:
    """Display cost summary."""
    table = Table(title="💰 API Cost Summary", box=box.ROUNDED)
    table.add_column("Metric", style="cyan")
    table.add_column("Value", justify="right")

    total_cost = float(cost.get("total_cost_usd", 0))
    table.add_row("Total Cost", f"${total_cost:.6f}")
    table.add_row("Input Tokens", f"{int(cost.get('total_input_tokens', 0)):,}")
    table.add_row("Output Tokens", f"{int(cost.get('total_output_tokens', 0)):,}")
    table.add_row("API Calls", str(cost.get("total_calls", 0)))

    session_id = str(cost.get("session_id", "?"))
    table.add_row("Session", session_id[:8])

    console.print(table)


def print_health(health: dict[str, str | int | float | dict[str, float | int | str]]) -> None:
    """Display health status."""
    table = Table(title="👻 Ghost Daemon Status", box=box.ROUNDED)
    table.add_column("Property", style="cyan")
    table.add_column("Value")

    for key, value in health.items():
        table.add_row(key, str(value))

    console.print(table)


def print_search_results(results: list[dict[str, str]]) -> None:
    """Display memory search results."""
    if not results:
        print_info("No results found.")
        return

    for i, r in enumerate(results, 1):
        kind = r.get("kind", "?")
        name = r.get("name", "?")
        content = r.get("content", "")
        preview = content[:200] + "..." if len(content) > 200 else content

        console.print(f"\n[cyan]{i}.[/cyan] [{kind}] [bold]{name}[/bold]")
        if preview:
            console.print(f"   {preview}", style="dim")


def print_audit_logs(logs: list[dict[str, str | dict[str, str]]]) -> None:
    """Display audit log entries."""
    table = Table(title="📋 Audit Log", box=box.ROUNDED)
    table.add_column("Time", style="dim")
    table.add_column("Topic", style="cyan")
    table.add_column("Details")

    for entry in logs:
        table.add_row(
            str(entry.get("created_at", "?")),
            str(entry.get("topic", "?")),
            str(entry.get("payload", {}))[:80],
        )

    console.print(table)


def confirm_action(message: str) -> bool:
    """Prompt for confirmation."""
    return console.input(f"\n{message} [y/N]: ").strip().lower() in ("y", "yes")
