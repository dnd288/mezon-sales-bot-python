"""Channel manager for the Mezon channel."""

from __future__ import annotations

import asyncio

from loguru import logger

from mebot.bus.queue import MessageBus
from mebot.channels.mezon import MezonChannel
from mebot.config.schema import Config


class ChannelManager:
    """Manages the Mezon channel and routes outbound messages."""

    def __init__(self, config: Config, bus: MessageBus):
        self.config = config
        self.bus = bus
        self._channel: MezonChannel | None = None
        self._dispatch_task: asyncio.Task | None = None

        if config.channels.mezon.enabled:
            self._channel = MezonChannel(config.channels.mezon, bus)
            logger.info("Mezon channel enabled")
        else:
            logger.warning("Mezon channel is disabled")

    @property
    def enabled_channels(self) -> list[str]:
        return ["mezon"] if self._channel else []

    async def start_all(self) -> None:
        if not self._channel:
            logger.warning("No channels enabled")
            return

        self._dispatch_task = asyncio.create_task(self._dispatch_outbound())
        logger.info("Starting mezon channel...")
        await self._channel.start()

    async def stop_all(self) -> None:
        logger.info("Stopping mezon channel...")

        if self._dispatch_task:
            self._dispatch_task.cancel()
            try:
                await self._dispatch_task
            except asyncio.CancelledError:
                pass

        if self._channel:
            try:
                await self._channel.stop()
                logger.info("Mezon channel stopped")
            except Exception as e:
                logger.error("Error stopping mezon channel: {}", e)

    async def _dispatch_outbound(self) -> None:
        """Forward outbound messages from the bus to the Mezon channel."""
        logger.info("Outbound dispatcher started")

        while True:
            try:
                msg = await asyncio.wait_for(self.bus.consume_outbound(), timeout=1.0)

                if msg.metadata.get("_progress"):
                    if msg.metadata.get("_tool_hint") and not self.config.channels.send_tool_hints:
                        continue
                    if not msg.metadata.get("_tool_hint") and not self.config.channels.send_progress:
                        continue

                if self._channel and msg.channel == "mezon":
                    try:
                        await self._channel.send(msg)
                    except Exception as e:
                        logger.error("Error sending to mezon: {}", e)
                else:
                    logger.warning("Unknown channel: {}", msg.channel)

            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
