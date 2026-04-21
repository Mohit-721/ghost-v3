"""ghost init — First-run setup wizard."""

import os
from pathlib import Path

import typer

from ghost.cli.display import console, print_ghost, print_info, print_success, print_warning
from ghost.constants import DEFAULT_CONFIG_FILE, DEFAULT_ENV_FILE, DEFAULT_GHOST_HOME


def init_cmd(
    path: str = typer.Argument(".", help="Project directory to initialize"),
) -> None:
    """Initialize Ghost for a project directory."""
    project_dir = Path(path).resolve()
    ghost_home = Path(os.environ.get("GHOST_HOME", str(DEFAULT_GHOST_HOME)))

    print_ghost("Initializing Ghost...")
    console.print(f"   Project: {project_dir}")
    console.print(f"   Ghost home: {ghost_home}")

    # Create ghost home directory structure
    ghost_home.mkdir(parents=True, exist_ok=True)
    (ghost_home / "quarantine").mkdir(exist_ok=True)
    (ghost_home / "tools").mkdir(exist_ok=True)
    (ghost_home / "logs").mkdir(exist_ok=True)

    # Create default config if it doesn't exist
    config_file = ghost_home / DEFAULT_CONFIG_FILE
    if not config_file.exists():
        from ghost.config.loader import load_config, save_config

        config = load_config()
        save_config(config)
        print_success(f"Created config at {config_file}")
    else:
        print_info(f"Config already exists at {config_file}")

    # Create .env template if it doesn't exist
    env_file = ghost_home / DEFAULT_ENV_FILE
    if not env_file.exists():
        env_file.write_text(
            "# Ghost API Keys\n"
            "# At least one provider key is required.\n"
            "OPENAI_API_KEY=\n"
            "ANTHROPIC_API_KEY=\n"
            "GOOGLE_API_KEY=\n"
        )
        env_file.chmod(0o600)
        print_success(f"Created .env at {env_file} (chmod 600)")
        print_warning("Edit ~/.ghost/.env and add your API key(s)")
    else:
        print_info(f".env already exists at {env_file}")

    # Create .ghostignore in project dir if doesn't exist
    ignore_file = project_dir / ".ghostignore"
    if not ignore_file.exists():
        ignore_file.write_text(
            "# Ghost ignore patterns (gitignore syntax)\n"
            "node_modules/\n"
            ".venv/\n"
            "venv/\n"
            "__pycache__/\n"
            "*.pyc\n"
            ".git/\n"
            "dist/\n"
            "build/\n"
        )
        print_success(f"Created .ghostignore in {project_dir}")

    print_ghost("Ghost initialized! Next steps:")
    console.print("   1. Add your API key: [cyan]nano ~/.ghost/.env[/cyan]")
    console.print("   2. Start the daemon: [cyan]ghost start[/cyan]")
    console.print('   3. Forge your first tool: [cyan]ghost forge "find all TODO comments"[/cyan]')
