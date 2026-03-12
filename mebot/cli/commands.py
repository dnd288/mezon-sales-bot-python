"""CLI entrypoint and command registration."""

from __future__ import annotations

import typer
from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.history import FileHistory
from prompt_toolkit.patch_stdout import patch_stdout

from mebot import __logo__, __version__
from mebot.cli import app, console
# TODO(codex): Replace import-time command registration with explicit registration
# functions or sub-app wiring. These imports are intentionally retained for
# backward-compatible command discovery during the CLI split.
from mebot.cli import agent_cmd as _agent_cmd  # noqa: F401
from mebot.cli import gateway as _gateway  # noqa: F401
from mebot.cli import onboard as _onboard  # noqa: F401
from mebot.cli.helpers import _load_runtime_config, _make_provider, _print_agent_response
from mebot.cli import provider_cmd, session_cmd, status as status_cmd
from mebot.config.paths import get_workspace_path
from mebot.utils.helpers import sync_workspace_templates

_PROMPT_SESSION: PromptSession | None = None

app.add_typer(status_cmd.channels_app, name="channels")
app.add_typer(provider_cmd.provider_app, name="provider")
app.add_typer(session_cmd.session_app, name="session")


def _init_prompt_session() -> None:
    """Compatibility wrapper for tests and external callers."""
    # TODO(codex): Drop this wrapper once tests and external callers patch
    # `mebot.cli.helpers` directly instead of `mebot.cli.commands`.
    global _PROMPT_SESSION
    from mebot.config.paths import get_cli_history_path

    history_file = get_cli_history_path()
    history_file.parent.mkdir(parents=True, exist_ok=True)
    _PROMPT_SESSION = PromptSession(
        history=FileHistory(str(history_file)),
        enable_open_in_editor=False,
        multiline=False,
    )


async def _read_interactive_input_async() -> str:
    """Compatibility wrapper for tests and external callers."""
    # TODO(codex): Remove after callers migrate to `mebot.cli.helpers`.
    if _PROMPT_SESSION is None:
        raise RuntimeError("Call _init_prompt_session() first")
    try:
        with patch_stdout():
            return await _PROMPT_SESSION.prompt_async(HTML("<b fg='ansiblue'>You:</b> "))
    except EOFError as exc:
        raise KeyboardInterrupt from exc


def version_callback(value: bool) -> None:
    if value:
        console.print(f"{__logo__} mebot v{__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        None,
        "--version",
        "-v",
        callback=version_callback,
        is_eager=True,
    ),
) -> None:
    """mebot - Personal AI Assistant."""


if __name__ == "__main__":
    app()
