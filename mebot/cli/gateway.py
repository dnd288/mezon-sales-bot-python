"""Gateway command."""

from __future__ import annotations

import asyncio

import typer

from mebot import __logo__
from mebot.agent.config import AgentConfig
from mebot.agent.loop import AgentLoop
from mebot.bridge.redis_streams import RedisStreamsBridge
from mebot.bus.queue import MessageBus
from mebot.channels.mezon import MezonChannel
from mebot.cli import app, console
from mebot.cli.helpers import _load_runtime_config, _make_provider
from mebot.config.paths import get_cron_dir
from mebot.cron.service import CronService
from mebot.cron.types import CronJob
from mebot.heartbeat.service import HeartbeatService
from mebot.session.manager import SessionManager
from mebot.session.redis_manager import RedisSessionManager
from mebot.utils.helpers import sync_workspace_templates
from mebot.utils.redis_pool import RedisClients, create_redis_clients


@app.command()
def gateway(
    port: int | None = typer.Option(None, "--port", "-p", help="Gateway port"),
    workspace: str | None = typer.Option(None, "--workspace", "-w", help="Workspace directory"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output"),
    config: str | None = typer.Option(None, "--config", "-c", help="Path to config file"),
) -> None:
    """Start the mebot gateway."""
    if verbose:
        import logging

        logging.basicConfig(level=logging.DEBUG)

    runtime_config = _load_runtime_config(config, workspace)
    port = port if port is not None else runtime_config.gateway.port

    console.print(f"{__logo__} Starting mebot gateway on port {port}...")
    sync_workspace_templates(runtime_config.workspace_path)

    bus = MessageBus()
    provider = _make_provider(runtime_config)

    redis_clients: RedisClients | None = None
    redis_stream_bridge: RedisStreamsBridge | None = None
    session_manager = SessionManager(runtime_config.workspace_path)

    if runtime_config.redis.enabled:
        try:
            redis_clients = create_redis_clients(
                runtime_config.redis.url,
                password=runtime_config.redis.password,
            )
            if runtime_config.redis.session.enabled:
                session_manager = RedisSessionManager(redis_clients.sync, runtime_config.redis.session)
                console.print("[green]✓[/green] Using Redis session store")

            redis_stream_bridge = RedisStreamsBridge(
                runtime_config.redis.streams,
                bus,
                redis_clients.async_,
            )
            console.print("[green]✓[/green] Redis stream bridge configured")
        except Exception as exc:
            console.print(f"[red]Redis init failed, fallback to disk sessions:[/red] {exc}")
            redis_clients = None
            redis_stream_bridge = None
            session_manager = SessionManager(runtime_config.workspace_path)

    cron_store_path = get_cron_dir() / "jobs.json"
    cron = CronService(cron_store_path)

    agent = AgentLoop(
        bus=bus,
        provider=provider,
        config=AgentConfig.from_app_config(runtime_config),
        session_manager=session_manager,
        cron_service=cron,
        channels_config=runtime_config.channels,
    )

    async def on_cron_job(job: CronJob) -> str | None:
        """Execute a cron job through the agent."""
        from mebot.agent.tools.cron import CronTool
        from mebot.agent.tools.message import MessageTool

        reminder_note = (
            "[Scheduled Task] Timer finished.\n\n"
            f"Task '{job.name}' has been triggered.\n"
            f"Scheduled instruction: {job.payload.message}"
        )

        cron_tool = agent.tools.get("cron")
        cron_token = None
        if isinstance(cron_tool, CronTool):
            cron_token = cron_tool.set_cron_context(True)
        try:
            response = await agent.process_direct(
                reminder_note,
                session_key=f"cron:{job.id}",
                channel=job.payload.channel or "cli",
                chat_id=job.payload.to or "direct",
            )
        finally:
            if isinstance(cron_tool, CronTool) and cron_token is not None:
                cron_tool.reset_cron_context(cron_token)

        message_tool = agent.tools.get("message")
        if isinstance(message_tool, MessageTool) and message_tool._sent_in_turn:
            return response

        if job.payload.deliver and job.payload.to and response:
            from mebot.bus.events import OutboundMessage

            await bus.publish_outbound(
                OutboundMessage(
                    channel=job.payload.channel or "cli",
                    chat_id=job.payload.to,
                    content=response,
                )
            )
        return response

    cron.on_job = on_cron_job
    mezon_channel = MezonChannel(
        runtime_config.channels.mezon,
        bus,
        event_forwarder=redis_stream_bridge,
    )

    def _pick_heartbeat_target() -> tuple[str, str]:
        """Pick the most recent mezon session, or fall back to cli."""
        for item in session_manager.list_sessions():
            key = item.get("key") or ""
            if ":" not in key:
                continue
            channel, chat_id = key.split(":", 1)
            if channel == "mezon" and chat_id:
                return channel, chat_id
        return "cli", "direct"

    async def on_heartbeat_execute(tasks: str) -> str:
        channel, chat_id = _pick_heartbeat_target()

        async def _silent(*_args, **_kwargs) -> None:
            return None

        return await agent.process_direct(
            tasks,
            session_key="heartbeat",
            channel=channel,
            chat_id=chat_id,
            on_progress=_silent,
        )

    async def on_heartbeat_notify(response: str) -> None:
        from mebot.bus.events import OutboundMessage

        channel, chat_id = _pick_heartbeat_target()
        if channel == "cli":
            return
        await bus.publish_outbound(OutboundMessage(channel=channel, chat_id=chat_id, content=response))

    hb_cfg = runtime_config.gateway.heartbeat
    heartbeat = HeartbeatService(
        workspace=runtime_config.workspace_path,
        provider=provider,
        model=agent.model,
        on_execute=on_heartbeat_execute,
        on_notify=on_heartbeat_notify,
        interval_s=hb_cfg.interval_s,
        enabled=hb_cfg.enabled,
    )

    console.print("[green]✓[/green] Mezon channel ready")
    cron_status = cron.status()
    if cron_status["jobs"] > 0:
        console.print(f"[green]✓[/green] Cron: {cron_status['jobs']} scheduled jobs")
    console.print(f"[green]✓[/green] Heartbeat: every {hb_cfg.interval_s}s")

    async def _dispatch_outbound() -> None:
        while True:
            try:
                msg = await asyncio.wait_for(bus.consume_outbound(), timeout=1.0)
                if msg.metadata.get("_progress"):
                    if msg.metadata.get("_tool_hint") and not runtime_config.channels.send_tool_hints:
                        continue
                    if not msg.metadata.get("_tool_hint") and not runtime_config.channels.send_progress:
                        continue
                await mezon_channel.send(msg)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

    async def run() -> None:
        dispatch_task = None
        try:
            if redis_stream_bridge:
                await redis_stream_bridge.start()
            await cron.start()
            await heartbeat.start()
            dispatch_task = asyncio.create_task(_dispatch_outbound())
            await asyncio.gather(agent.run(), mezon_channel.start(), dispatch_task)
        except KeyboardInterrupt:
            console.print("\nShutting down...")
        finally:
            await agent.close_mcp()
            heartbeat.stop()
            cron.stop()
            agent.stop()
            if dispatch_task:
                dispatch_task.cancel()
                try:
                    await dispatch_task
                except asyncio.CancelledError:
                    pass
            if redis_stream_bridge:
                await redis_stream_bridge.stop()
            if redis_clients:
                await redis_clients.aclose()
            await mezon_channel.stop()

    asyncio.run(run())
