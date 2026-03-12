"""Interactive agent command."""

from __future__ import annotations

import asyncio
import signal
import sys

import typer
from loguru import logger

from mebot import __logo__
from mebot.agent.config import AgentConfig
from mebot.agent.loop import AgentLoop
from mebot.bus.events import InboundMessage
from mebot.bus.queue import MessageBus
from mebot.cli import app, console
from mebot.cli.helpers import (
    _flush_pending_tty_input,
    _init_prompt_session,
    _is_exit_command,
    _load_runtime_config,
    _make_provider,
    _print_agent_response,
    _read_interactive_input_async,
    _restore_terminal,
)
from mebot.config.paths import get_cron_dir
from mebot.cron.service import CronService
from mebot.utils.helpers import sync_workspace_templates

@app.command()
def agent(
    message: str = typer.Option(None, "--message", "-m", help="Message to send to the agent"),
    session_id: str = typer.Option("cli:direct", "--session", "-s", help="Session ID"),
    workspace: str | None = typer.Option(None, "--workspace", "-w", help="Workspace directory"),
    config: str | None = typer.Option(None, "--config", "-c", help="Config file path"),
    markdown: bool = typer.Option(True, "--markdown/--no-markdown", help="Render assistant output as Markdown"),
    logs: bool = typer.Option(False, "--logs/--no-logs", help="Show mebot runtime logs during chat"),
) -> None:
    """Interact with the agent directly."""
    runtime_config = _load_runtime_config(config, workspace)

    sync_workspace_templates(runtime_config.workspace_path)

    bus = MessageBus()
    provider = _make_provider(runtime_config)
    cron_store_path = get_cron_dir() / "jobs.json"
    cron = CronService(cron_store_path)

    if logs:
        logger.enable("mebot")
    else:
        logger.disable("mebot")

    agent_loop = AgentLoop(
        bus=bus,
        provider=provider,
        config=AgentConfig.from_app_config(runtime_config),
        cron_service=cron,
        channels_config=runtime_config.channels,
    )

    def _thinking_ctx():
        if logs:
            from contextlib import nullcontext

            return nullcontext()
        return console.status("[dim]mebot is thinking...[/dim]", spinner="dots")

    async def _cli_progress(content: str, *, tool_hint: bool = False) -> None:
        channels = agent_loop.channels_config
        if channels and tool_hint and not channels.send_tool_hints:
            return
        if channels and not tool_hint and not channels.send_progress:
            return
        console.print(f"  [dim]↳ {content}[/dim]")

    if message:
        async def run_once() -> None:
            with _thinking_ctx():
                response = await agent_loop.process_direct(message, session_id, on_progress=_cli_progress)
            _print_agent_response(response, render_markdown=markdown)
            await agent_loop.close_mcp()

        asyncio.run(run_once())
        return

    _init_prompt_session()
    console.print(f"{__logo__} Interactive mode (type [bold]exit[/bold] or [bold]Ctrl+C[/bold] to quit)\n")

    if ":" in session_id:
        cli_channel, cli_chat_id = session_id.split(":", 1)
    else:
        cli_channel, cli_chat_id = "cli", session_id

    def _handle_signal(signum, _frame) -> None:
        sig_name = signal.Signals(signum).name
        _restore_terminal()
        console.print(f"\nReceived {sig_name}, goodbye!")
        sys.exit(0)

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)
    if hasattr(signal, "SIGHUP"):
        signal.signal(signal.SIGHUP, _handle_signal)
    if hasattr(signal, "SIGPIPE"):
        signal.signal(signal.SIGPIPE, signal.SIG_IGN)

    async def run_interactive() -> None:
        bus_task = asyncio.create_task(agent_loop.run())
        turn_done = asyncio.Event()
        turn_done.set()
        turn_response: list[str] = []

        async def _consume_outbound() -> None:
            while True:
                try:
                    msg = await asyncio.wait_for(bus.consume_outbound(), timeout=1.0)
                    if msg.metadata.get("_progress"):
                        is_tool_hint = msg.metadata.get("_tool_hint", False)
                        channels = agent_loop.channels_config
                        if channels and is_tool_hint and not channels.send_tool_hints:
                            pass
                        elif channels and not is_tool_hint and not channels.send_progress:
                            pass
                        else:
                            console.print(f"  [dim]↳ {msg.content}[/dim]")
                    elif not turn_done.is_set():
                        if msg.content:
                            turn_response.append(msg.content)
                        turn_done.set()
                    elif msg.content:
                        console.print()
                        _print_agent_response(msg.content, render_markdown=markdown)
                except asyncio.TimeoutError:
                    continue
                except asyncio.CancelledError:
                    break

        outbound_task = asyncio.create_task(_consume_outbound())

        try:
            while True:
                try:
                    _flush_pending_tty_input()
                    user_input = await _read_interactive_input_async()
                    command = user_input.strip()
                    if not command:
                        continue

                    if _is_exit_command(command):
                        _restore_terminal()
                        console.print("\nGoodbye!")
                        break

                    turn_done.clear()
                    turn_response.clear()

                    await bus.publish_inbound(
                        InboundMessage(
                            channel=cli_channel,
                            sender_id="user",
                            chat_id=cli_chat_id,
                            content=user_input,
                        )
                    )

                    with _thinking_ctx():
                        await turn_done.wait()

                    if turn_response:
                        _print_agent_response(turn_response[0], render_markdown=markdown)
                except KeyboardInterrupt:
                    _restore_terminal()
                    console.print("\nGoodbye!")
                    break
                except EOFError:
                    _restore_terminal()
                    console.print("\nGoodbye!")
                    break
        finally:
            agent_loop.stop()
            outbound_task.cancel()
            await asyncio.gather(bus_task, outbound_task, return_exceptions=True)
            await agent_loop.close_mcp()

    asyncio.run(run_interactive())
