"""Session management commands."""

from __future__ import annotations

import asyncio

import typer

from mebot.cli import console
from mebot.cli.helpers import _load_runtime_config
from mebot.session.migrate import migrate_disk_to_redis
from mebot.session.redis_manager import RedisSessionManager
from mebot.utils.redis_pool import create_redis_clients

session_app = typer.Typer(help="Manage sessions")


@session_app.command("migrate")
def session_migrate(
    workspace: str | None = typer.Option(None, "--workspace", "-w", help="Workspace directory"),
    config: str | None = typer.Option(None, "--config", "-c", help="Config file path"),
) -> None:
    """Migrate disk sessions to Redis."""
    runtime_config = _load_runtime_config(config, workspace)
    if not runtime_config.redis.enabled or not runtime_config.redis.session.enabled:
        console.print("[red]Redis session is not enabled in config.[/red]")
        raise typer.Exit(1)

    try:
        redis_clients = create_redis_clients(
            runtime_config.redis.url,
            password=runtime_config.redis.password,
        )
    except Exception as exc:
        console.print(f"[red]Failed to connect Redis:[/red] {exc}")
        raise typer.Exit(1)

    manager = RedisSessionManager(redis_clients.sync, runtime_config.redis.session)
    migrated = migrate_disk_to_redis(runtime_config.workspace_path / "sessions", manager)
    console.print(f"[green]✓[/green] Migrated {migrated} session(s) to Redis")
    asyncio.run(redis_clients.aclose())
