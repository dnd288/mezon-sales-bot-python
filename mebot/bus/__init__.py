"""Message bus module for decoupled channel-agent communication."""

from mebot.bus.events import InboundMessage, OutboundMessage
from mebot.bus.queue import MessageBus

__all__ = ["MessageBus", "InboundMessage", "OutboundMessage"]
