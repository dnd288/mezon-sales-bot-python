"""Mezon chat channel implementation."""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any

from loguru import logger

from mebot.bus.events import InboundMessage, OutboundMessage
from mebot.bus.queue import MessageBus
from mebot.config.schema import AllowFromConfig, MezonConfig
from mebot.utils.helpers import split_message


def is_allowed(
    allow_from: AllowFromConfig,
    sender_id: str,
    clan_id: str = "",
    channel_id: str = "",
) -> bool:
    """Check whether a sender is permitted by allow_from filters."""

    def _match(ids: list[str], value: str) -> bool:
        return not ids or "*" in ids or value in ids

    return (
        _match(allow_from.clan, clan_id)
        and _match(allow_from.channel, channel_id)
        and _match(allow_from.user, sender_id)
    )


def _extract_message_text(raw_content: Any) -> str:
    """Extract text from Mezon message content across dict/object/string payloads."""
    if raw_content is None:
        return ""

    if isinstance(raw_content, dict):
        return str(raw_content.get("t") or "")

    if hasattr(raw_content, "t"):
        try:
            return str(getattr(raw_content, "t") or "")
        except Exception:
            pass

    if isinstance(raw_content, (bytes, bytearray)):
        try:
            raw_content = raw_content.decode("utf-8")
        except Exception:
            return ""

    if isinstance(raw_content, str):
        try:
            data = json.loads(raw_content)
            if isinstance(data, dict):
                return str(data.get("t") or "")
        except json.JSONDecodeError:
            return raw_content

    return str(raw_content)


class MezonChannel:
    """
    Mezon channel using mezon-sdk WebSocket connection.

    No public IP required; uses a persistent WebSocket with reconnect.
    """

    name = "mezon"

    def __init__(self, config: MezonConfig, bus: MessageBus, event_forwarder: Any | None = None):
        self.config = config
        self.bus = bus
        self._event_forwarder = event_forwarder
        self._running = False
        self._client = None
        self._typing_tasks: dict[str, asyncio.Task] = {}

    def is_allowed(self, sender_id: str, clan_id: str = "", channel_id: str = "") -> bool:
        """Check if message is permitted based on clan/channel/user filters."""
        return is_allowed(self.config.allow_from, sender_id, clan_id=clan_id, channel_id=channel_id)

    async def _handle_message(
        self,
        sender_id: str,
        chat_id: str,
        content: str,
        clan_id: str = "",
        media: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        session_key: str | None = None,
    ) -> None:
        """Publish an inbound message to the bus."""
        await self.bus.publish_inbound(
            InboundMessage(
                channel=self.name,
                sender_id=str(sender_id),
                chat_id=str(chat_id),
                content=content,
                media=media or [],
                metadata=metadata or {},
                session_key_override=session_key,
            )
        )

    @property
    def is_running(self) -> bool:
        return self._running

    async def start(self) -> None:
        """Start the Mezon bot connection."""
        if not self.config.client_id or not self.config.token:
            logger.error("Mezon clientId and token must be configured")
            return

        from mezon import MezonClient

        self._running = True
        reconnect_delay = 5

        while self._running:
            try:
                self._client = MezonClient(
                    client_id=self.config.client_id,
                    api_key=self.config.token,
                )
                self._client.on_channel_message(self._on_message)

                async def _skip_zk_proof() -> None:
                    return None  # type: ignore[return-value]

                self._client.get_zk_proof = _skip_zk_proof  # type: ignore[method-assign]

                logger.info("Connecting to Mezon...")
                await self._client.login(enable_auto_reconnect=False)
                logger.info("Mezon bot connected (client_id={})", self.config.client_id)

                if self._event_forwarder and hasattr(self._event_forwarder, "setup_event_forwarding"):
                    try:
                        await self._event_forwarder.setup_event_forwarding(self._client)
                    except Exception as exc:
                        logger.warning("Failed to setup Redis event forwarding: {}", exc)

                active = [k for k in ("clan", "channel", "user") if getattr(self.config.allow_from, k)]
                if active:
                    logger.info("Allow_from filter active on: {}", ", ".join(active))
                else:
                    logger.info(
                        "Allow_from filter disabled (accepting messages from all clans/channels/users)"
                    )

                while self._running:
                    await asyncio.sleep(5)
                    if self._client and not await self._client.socket_manager.is_connected():
                        logger.warning("Mezon socket lost, restarting connection...")
                        break

            except asyncio.CancelledError:
                break
            except Exception as exc:
                if not self._running:
                    break
                logger.warning("Mezon connection error: {}. Reconnecting in {}s...", exc, reconnect_delay)
                await asyncio.sleep(reconnect_delay)
                reconnect_delay = min(reconnect_delay * 2, 60)

    async def stop(self) -> None:
        """Stop the Mezon bot connection."""
        self._running = False
        for channel_id in list(self._typing_tasks):
            self._stop_typing(channel_id)
        if self._client:
            try:
                await self._client.disconnect()
            except Exception as exc:
                logger.debug("Mezon disconnect: {}", exc)
            self._client = None

    async def send(self, msg: OutboundMessage) -> None:
        """Send a message to a Mezon channel."""
        if not self._client:
            logger.warning("Mezon client not running")
            return

        if not msg.content or msg.content == "[empty message]":
            return

        if self._should_stop_typing(msg):
            self._stop_typing(msg.chat_id)

        try:
            from mezon import ChannelMessageContent

            target_type = (msg.metadata or {}).get("target_type", "channel")
            if target_type == "dm":
                user = await self._client.users.fetch(int(msg.chat_id))
                for chunk in split_message(msg.content):
                    await user.send_dm_message(ChannelMessageContent(t=chunk))
            else:
                channel = await self._client.channels.fetch(int(msg.chat_id))
                # Thread reply when thread_ts is set (task events reply to originating thread).
                thread_kwargs: dict = {}
                thread_ts = (msg.metadata or {}).get("thread_ts")
                if thread_ts:
                    thread_kwargs["thread_ts"] = thread_ts
                for chunk in split_message(msg.content):
                    logger.debug("Sending message to channel_id={}: {}...", msg.chat_id, chunk[:60])
                    await channel.send(content=ChannelMessageContent(t=chunk), **thread_kwargs)
        except Exception as exc:
            logger.error("Error sending Mezon message to {}: {}", msg.chat_id, exc)

    @staticmethod
    def _should_stop_typing(msg: OutboundMessage) -> bool:
        """Keep typing active for progress updates while agent is still processing."""
        return not bool((msg.metadata or {}).get("_progress"))

    async def _on_message(self, message: Any) -> None:
        """Handle an incoming Mezon channel message."""
        try:
            sender_id = str(getattr(message, "sender_id", "") or "")
            channel_id = str(getattr(message, "channel_id", "") or "")
            if not sender_id or not channel_id:
                return
            if sender_id == str(self.config.client_id):
                return

            clan_id = str(getattr(message, "clan_id", "") or "")
            if not self.is_allowed(sender_id, clan_id=clan_id, channel_id=channel_id):
                logger.debug(
                    "Message from sender={} clan={} channel={} blocked by allow_from filter",
                    sender_id,
                    clan_id,
                    channel_id,
                )
                return

            content = _extract_message_text(getattr(message, "content", None))
            if not content.strip():
                return
            if not self._should_respond_to_message(message, content):
                return

            channel_type = getattr(message, "channel_type", None)
            mode = self._resolve_typing_mode(
                channel_type=channel_type,
                message_mode=getattr(message, "mode", None),
            )
            is_public = getattr(message, "is_public", True)
            self._start_typing(channel_id, int(clan_id) if clan_id else 0, mode, is_public)

            await self._handle_message(
                sender_id=sender_id,
                chat_id=channel_id,
                content=content,
                clan_id=clan_id,
                metadata={
                    "message_id": str(getattr(message, "id", "") or ""),
                    "clan_id": clan_id,
                    "channel_type": getattr(message, "channel_type", 0),
                    "username": str(getattr(message, "username", "") or ""),
                },
            )
        except Exception:
            logger.exception("Error handling Mezon message")

    async def _typing_loop(self, clan_id: int, channel_id: int, mode: int, is_public: bool) -> None:
        """Send typing indicator every 4s until cancelled."""
        logged_error = False
        try:
            while True:
                if not self._client or not getattr(self._client, "socket_manager", None):
                    await asyncio.sleep(1)
                    continue
                try:
                    socket_manager = self._client.socket_manager
                    writer = getattr(socket_manager, "write_message_typing", None)
                    if callable(writer):
                        await writer(
                            clan_id=clan_id,
                            channel_id=channel_id,
                            mode=mode,
                            is_public=is_public,
                        )
                    else:
                        await socket_manager.get_socket().write_message_typing(
                            clan_id=clan_id,
                            channel_id=channel_id,
                            mode=mode,
                            is_public=is_public,
                        )
                    logged_error = False
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    if not logged_error:
                        logger.debug("Typing send failed for channel_id={}: {}", channel_id, exc)
                        logged_error = True
                    await asyncio.sleep(2)
                    continue
                await asyncio.sleep(4)
        except asyncio.CancelledError:
            logger.debug("Stopped typing indicator for channel_id={}", channel_id)

    @staticmethod
    def _resolve_typing_mode(channel_type: Any, message_mode: Any) -> int:
        """Resolve typing stream mode from channel_type first, fallback to message.mode."""
        try:
            if channel_type is not None:
                from mezon.utils.helper import convert_channeltype_to_channel_mode

                return int(convert_channeltype_to_channel_mode(int(channel_type)))
        except Exception:
            pass
        try:
            return int(message_mode) if message_mode is not None else 2
        except (TypeError, ValueError):
            return 2

    def _should_respond_to_message(self, message: Any, content: str) -> bool:
        """Apply mention-only gate when enabled."""
        if not self.config.mention_only:
            return True

        bot_id = str(self.config.client_id or "")
        bot_username = (self.config.bot_username or "").strip().lstrip("@").lower()

        mentions = self._normalize_mentions(getattr(message, "mentions", None))
        for mention in mentions:
            user_id = self._mention_value(mention, "user_id")
            if user_id is not None and str(user_id) == bot_id:
                return True
            username = self._mention_value(mention, "username")
            if bot_username and isinstance(username, str) and username.strip().lstrip("@").lower() == bot_username:
                return True

        if bot_id and re.search(rf"<@!?{re.escape(bot_id)}>", content):
            return True
        if bot_username and re.search(rf"(?<!\w)@?{re.escape(bot_username)}(?!\w)", content, re.IGNORECASE):
            return True

        logger.debug("Ignoring message in mention_only mode: no direct mention detected")
        return False

    @staticmethod
    def _normalize_mentions(raw_mentions: Any) -> list[Any]:
        """Best-effort normalization for incoming `mentions` payload variants."""
        if raw_mentions is None:
            return []
        if isinstance(raw_mentions, (bytes, bytearray)):
            try:
                raw_mentions = raw_mentions.decode("utf-8")
            except Exception:
                return []
        if isinstance(raw_mentions, str):
            try:
                raw_mentions = json.loads(raw_mentions)
            except json.JSONDecodeError:
                return []
        if isinstance(raw_mentions, dict):
            return [raw_mentions]
        if isinstance(raw_mentions, list):
            return raw_mentions
        return []

    @staticmethod
    def _mention_value(mention: Any, key: str) -> Any:
        """Read mention field from object or dict."""
        if isinstance(mention, dict):
            return mention.get(key)
        return getattr(mention, key, None)

    def _start_typing(self, channel_id: str, clan_id: int, mode: int, is_public: bool) -> None:
        """Start typing indicator loop for a channel (no-op if already running)."""
        if not self._client:
            return
        existing = self._typing_tasks.get(channel_id)
        if existing and not existing.done():
            return
        logger.debug("Starting typing indicator for channel_id={}", channel_id)
        self._typing_tasks[channel_id] = asyncio.create_task(
            self._typing_loop(int(clan_id), int(channel_id), mode, is_public)
        )

    def _stop_typing(self, channel_id: str) -> None:
        """Cancel typing indicator for a channel."""
        task = self._typing_tasks.pop(channel_id, None)
        if task:
            logger.debug("Stopping typing indicator for channel_id={}", channel_id)
            task.cancel()
