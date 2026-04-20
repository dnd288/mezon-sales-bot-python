"""Slash command routing and built-in handlers."""

from mebot.command.builtin import register_builtin_commands
from mebot.command.router import CommandContext, CommandRouter

__all__ = ["CommandContext", "CommandRouter", "register_builtin_commands"]
