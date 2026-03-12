"""Helpers for creating and closing Redis clients."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class RedisClients:
    """Container for paired sync and async Redis clients."""

    sync: Any
    async_: Any

    async def aclose(self) -> None:
        """Close both Redis clients."""
        if self.async_:
            aclose = getattr(self.async_, "aclose", None)
            if callable(aclose):
                await aclose()
            else:
                await self.async_.close()
        if self.sync:
            self.sync.close()


def create_redis_clients(url: str, password: str = "") -> RedisClients:
    """Create sync and async Redis clients with shared decode settings."""
    import redis
    import redis.asyncio as redis_async

    kwargs = {"decode_responses": True}
    if password:
        kwargs["password"] = password

    async_client = redis_async.from_url(url, **kwargs)
    sync_client = redis.Redis.from_url(url, **kwargs)
    sync_client.ping()
    return RedisClients(sync=sync_client, async_=async_client)
