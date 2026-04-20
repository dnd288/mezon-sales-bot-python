"""Restart utilities for mebot."""

from __future__ import annotations

import os


def set_restart_notice_to_env(channel: str = "", chat_id: str = "") -> None:
    """Persist restart context to environment so it survives exec()."""
    if channel:
        os.environ["MEBOT_RESTART_CHANNEL"] = channel
    if chat_id:
        os.environ["MEBOT_RESTART_CHAT_ID"] = chat_id


def get_restart_notice_from_env() -> tuple[str, str] | None:
    """Read restart context set before exec(). Returns (channel, chat_id) or None."""
    channel = os.environ.pop("MEBOT_RESTART_CHANNEL", "")
    chat_id = os.environ.pop("MEBOT_RESTART_CHAT_ID", "")
    if channel and chat_id:
        return channel, chat_id
    return None
