"""Status commands."""

from __future__ import annotations

import typer
from rich.table import Table

from mebot import __logo__
from mebot.cli import app, console

channels_app = typer.Typer(help="Manage channels")


@channels_app.command("status")
def channels_status() -> None:
    """Show channel status."""
    from mebot.config.loader import load_config

    config = load_config()

    table = Table(title="Channel Status")
    table.add_column("Channel", style="cyan")
    table.add_column("Configuration", style="yellow")

    mz = config.channels.mezon
    mz_config = f"client_id: {mz.client_id[:10]}..." if mz.client_id else "[dim]not configured[/dim]"
    table.add_row("Mezon", mz_config)

    console.print(table)


@app.command()
def status() -> None:
    """Show mebot status."""
    from mebot.config.loader import get_config_path, load_config

    config_path = get_config_path()
    config = load_config()
    workspace = config.workspace_path

    console.print(f"{__logo__} mebot Status\n")
    console.print(f"Config: {config_path} {'[green]✓[/green]' if config_path.exists() else '[red]✗[/red]'}")
    console.print(f"Workspace: {workspace} {'[green]✓[/green]' if workspace.exists() else '[red]✗[/red]'}")

    if config_path.exists():
        from mebot.providers.registry import PROVIDERS

        console.print(f"Model: {config.agents.defaults.model}")
        for spec in PROVIDERS:
            provider_config = getattr(config.providers, spec.name, None)
            if provider_config is None:
                continue
            if spec.is_oauth:
                console.print(f"{spec.label}: [green]✓ (OAuth)[/green]")
            elif spec.is_local:
                if provider_config.api_base:
                    console.print(f"{spec.label}: [green]✓ {provider_config.api_base}[/green]")
                else:
                    console.print(f"{spec.label}: [dim]not set[/dim]")
            else:
                has_key = bool(provider_config.api_key)
                console.print(f"{spec.label}: {'[green]✓[/green]' if has_key else '[dim]not set[/dim]'}")
