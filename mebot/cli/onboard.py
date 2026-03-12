"""Onboarding command."""

from __future__ import annotations

import typer

from mebot import __logo__
from mebot.cli import app, console
from mebot.config.schema import Config


@app.command()
def onboard() -> None:
    """Initialize mebot configuration and workspace."""
    from mebot.config.loader import get_config_path, load_config, save_config
    # TODO(codex): Inline these imports from stable modules after the remaining
    # CLI compatibility shims in `mebot.cli.commands` are retired.
    from mebot.cli import commands as commands_module

    config_path = get_config_path()

    if config_path.exists():
        console.print(f"[yellow]Config already exists at {config_path}[/yellow]")
        console.print("  [bold]y[/bold] = overwrite with defaults (existing values will be lost)")
        console.print("  [bold]N[/bold] = refresh config, keeping existing values and adding new fields")
        if typer.confirm("Overwrite?"):
            config = Config()
            save_config(config)
            console.print(f"[green]✓[/green] Config reset to defaults at {config_path}")
        else:
            config = load_config()
            save_config(config)
            console.print(
                f"[green]✓[/green] Config refreshed at {config_path} (existing values preserved)"
            )
    else:
        save_config(Config())
        console.print(f"[green]✓[/green] Created config at {config_path}")

    workspace = commands_module.get_workspace_path()
    if not workspace.exists():
        workspace.mkdir(parents=True, exist_ok=True)
        console.print(f"[green]✓[/green] Created workspace at {workspace}")

    commands_module.sync_workspace_templates(workspace)

    console.print(f"\n{__logo__} mebot is ready!")
    console.print("\nNext steps:")
    console.print("  1. Add your API key to [cyan]~/.mebot/config.json[/cyan]")
    console.print("     Get one at: https://openrouter.ai/keys")
    console.print("  2. Configure Mezon bot token in [cyan]channels.mezon[/cyan]")
    console.print("  3. Start gateway: [cyan]mebot gateway[/cyan]")
