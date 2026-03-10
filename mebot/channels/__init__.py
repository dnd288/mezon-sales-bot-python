"""Chat channels module with plugin architecture."""

from mebot.channels.base import BaseChannel
from mebot.channels.manager import ChannelManager

__all__ = ["BaseChannel", "ChannelManager"]
