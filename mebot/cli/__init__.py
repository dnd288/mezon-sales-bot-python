"""CLI shared objects and bootstrap behavior."""

from __future__ import annotations

import os
import sys

import typer
from rich.console import Console

from mebot import __logo__

# Force UTF-8 encoding for Windows console.
if sys.platform == "win32" and sys.stdout.encoding != "utf-8":
    os.environ["PYTHONIOENCODING"] = "utf-8"
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

app = typer.Typer(
    name="mebot",
    help=f"{__logo__} mebot - Personal AI Assistant",
    no_args_is_help=True,
)

console = Console()
EXIT_COMMANDS = {"exit", "quit", "/exit", "/quit", ":q"}

__all__ = ["EXIT_COMMANDS", "app", "console"]
