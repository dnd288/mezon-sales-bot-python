"""Backward-compatible Redis bridge import surface."""

from mebot.bridge.redis_streams import RedisStreamsBridge, RedisStreamsBridge as RedisChannel

__all__ = ["RedisChannel", "RedisStreamsBridge"]
