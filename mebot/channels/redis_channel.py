"""Redis Streams bridge (NOT a chat channel) for external triggers/event forwarding.

NOTE: This module lives under `channels/` for now, but architecturally it is a
bridge/adapter. Planned move target in a future refactor: `mebot/bridge/`.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any

from loguru import logger

from mebot.bus.events import InboundMessage, OutboundMessage
from mebot.bus.queue import MessageBus
from mebot.config.schema import RedisStreamsConfig


class RedisChannel:
    """Bridge between Redis Streams and the internal message bus."""

    name = "redis"

    def __init__(self, config: RedisStreamsConfig, bus: MessageBus, redis_client: Any):
        self.config = config
        self.bus = bus
        self._redis = redis_client
        self._running = False
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        """Start inbound stream consumption."""
        if self._running:
            return
        self._running = True
        await self._ensure_group()
        logger.info(
            "RedisChannel consuming stream={} group={} consumer={}",
            self.config.inbound_stream,
            self.config.consumer_group,
            self.config.consumer_name,
        )
        self._task = asyncio.create_task(self._consume_loop())

    async def stop(self) -> None:
        """Stop consumption loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _ensure_group(self) -> None:
        """Create consumer group if absent."""
        try:
            await self._redis.xgroup_create(
                name=self.config.inbound_stream,
                groupname=self.config.consumer_group,
                id="$",
                mkstream=True,
            )
        except Exception as exc:
            msg = str(exc).lower()
            if "busygroup" not in msg:
                raise

    async def setup_event_forwarding(self, client: Any) -> None:
        """Register Mezon event handlers for configured events."""
        if not self.config.forward_events:
            return

        registered = 0
        for event_name in self.config.forward_events:
            if self._register_client_event(client, event_name):
                registered += 1
        logger.info("RedisChannel forwarding {} Mezon event types", registered)

    def _register_client_event(self, client: Any, event_name: str) -> bool:
        """Register one event callback using best available SDK API."""
        async def _handler(payload: Any) -> None:
            await self._publish_event(event_name, payload)

        # Prefer EventManager API to avoid overriding existing `on_*` callbacks.
        event_manager = getattr(client, "event_manager", None)
        on_event = getattr(event_manager, "on", None) if event_manager else None
        if callable(on_event):
            on_event(event_name, _handler)
            return True

        on_method = getattr(client, f"on_{event_name}", None)
        if callable(on_method):
            on_method(_handler)
            return True

        logger.warning("Unable to register Mezon event handler for '{}'", event_name)
        return False

    async def _consume_loop(self) -> None:
        """Consume inbound triggers from Redis stream and publish to bus."""
        while self._running:
            try:
                result = await self._redis.xreadgroup(
                    groupname=self.config.consumer_group,
                    consumername=self.config.consumer_name,
                    streams={self.config.inbound_stream: ">"},
                    count=10,
                    block=1000,
                )
                if not result:
                    continue
                for _, entries in result:
                    for msg_id, fields in entries:
                        await self._handle_inbound_entry(msg_id, fields)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("Redis inbound consume error: {}", exc)
                await asyncio.sleep(1)

    async def _handle_inbound_entry(self, msg_id: str, fields: dict[str, Any]) -> None:
        """Validate and forward one inbound stream entry."""
        try:
            if not self._validate_api_key(fields):
                logger.warning("Redis inbound rejected ({}): invalid x-api-key", msg_id)
                return

            content = str(fields.get("content", "") or "")
            target_type = str(fields.get("targetType", "channel") or "channel").lower()
            clan_id = str(fields.get("clanId", "") or "")

            if target_type == "dm":
                target = str(fields.get("targetUserId", "") or "")
                if not content or not target:
                    logger.warning("Redis inbound rejected ({}): missing content/targetUserId for DM", msg_id)
                    return
            else:
                target = str(fields.get("targetChannelId", "") or "")
                if not content or not target:
                    logger.warning("Redis inbound rejected ({}): missing content/targetChannelId", msg_id)
                    return

            sender = str(fields.get("senderId", "n8n") or "n8n")

            metadata_raw = fields.get("metadata")
            metadata = self._parse_json_obj(metadata_raw)
            metadata["_redis_stream_id"] = msg_id
            metadata["target_type"] = target_type
            if clan_id:
                metadata["clan_id"] = clan_id

            direct = str(fields.get("directSend", "") or "").lower() in ("1", "true", "yes")
            if direct:
                logger.info("RedisChannel direct send to {}:{}", target_type, target)
                await self.bus.publish_outbound(OutboundMessage(
                    channel="mezon",
                    chat_id=target,
                    content=content,
                    metadata=metadata,
                ))
            else:
                await self.bus.publish_inbound(InboundMessage(
                    channel="mezon",
                    sender_id=sender,
                    chat_id=target,
                    content=content,
                    metadata=metadata,
                    session_key_override=f"mezon:{target}",
                ))
        finally:
            try:
                await self._redis.xack(self.config.inbound_stream, self.config.consumer_group, msg_id)
            except Exception as exc:
                logger.warning("Redis inbound XACK failed for {}: {}", msg_id, exc)

    def _validate_api_key(self, fields: dict[str, Any]) -> bool:
        """Validate x-api-key field if configured."""
        configured = self.config.api_key
        if not configured:
            return True
        return str(fields.get("x-api-key", "") or "") == configured

    async def _publish_event(self, event_name: str, payload: Any) -> None:
        """Publish one Mezon event to outbound stream."""
        body = {
            "event": event_name,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "data": json.dumps(self._serialize_payload(payload), ensure_ascii=False),
        }
        kwargs: dict[str, Any] = {"name": self.config.events_stream, "fields": body}
        if self.config.max_len > 0:
            kwargs["maxlen"] = self.config.max_len
            # Use exact trimming (not "~") because current spec requires hard cap.
            kwargs["approximate"] = False
        await self._redis.xadd(**kwargs)

    @staticmethod
    def _serialize_payload(payload: Any) -> Any:
        """Best-effort serializer for SDK event objects."""
        if payload is None:
            return {}
        if isinstance(payload, (dict, list, str, int, float, bool)):
            return payload
        if hasattr(payload, "model_dump"):
            try:
                return payload.model_dump()
            except Exception as exc:
                logger.warning("Failed model_dump() for event payload: {}", exc)
        if hasattr(payload, "__dict__"):
            return {
                k: v for k, v in vars(payload).items()
                if not k.startswith("_")
            }
        return str(payload)

    @staticmethod
    def _parse_json_obj(value: Any) -> dict[str, Any]:
        if value is None:
            return {}
        if isinstance(value, dict):
            return value
        if isinstance(value, (bytes, bytearray)):
            try:
                value = value.decode("utf-8")
            except Exception:
                return {}
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
                return parsed if isinstance(parsed, dict) else {}
            except json.JSONDecodeError:
                return {}
        return {}
