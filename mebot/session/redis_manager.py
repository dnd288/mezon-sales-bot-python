"""Redis-backed session manager."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from urllib.parse import quote

from mebot.config.schema import RedisSessionConfig
from mebot.session.manager import Session


class RedisSessionManager:
    """Session storage in Redis (meta hash + messages list)."""

    def __init__(self, redis_client: Any, config: RedisSessionConfig):
        self.redis = redis_client
        self.config = config
        self.key_prefix = config.key_prefix
        self.ttl_seconds = max(0, int(config.ttl_days * 24 * 60 * 60))
        self._cache: dict[str, Session] = {}
        self._saved_counts: dict[str, int] = {}

    def _safe_key(self, key: str) -> str:
        # URL-encode full session key to avoid collisions (e.g. ':' vs '_').
        return quote(key, safe="")

    def _meta_key(self, key: str) -> str:
        return f"{self.key_prefix}:{self._safe_key(key)}:meta"

    def _messages_key(self, key: str) -> str:
        return f"{self.key_prefix}:{self._safe_key(key)}:messages"

    def _touch_ttl(self, key: str) -> None:
        if self.ttl_seconds <= 0:
            return
        pipe = self.redis.pipeline()
        pipe.expire(self._meta_key(key), self.ttl_seconds)
        pipe.expire(self._messages_key(key), self.ttl_seconds)
        pipe.execute()

    def get_or_create(self, key: str) -> Session:
        if key in self._cache:
            return self._cache[key]

        meta = self.redis.hgetall(self._meta_key(key)) or {}
        raw_msgs = self.redis.lrange(self._messages_key(key), 0, -1) or []
        messages = []
        for raw in raw_msgs:
            try:
                messages.append(json.loads(raw))
            except Exception:
                continue

        if meta:
            created = meta.get("created_at")
            updated = meta.get("updated_at")
            metadata = meta.get("metadata", "{}")
            try:
                metadata_obj = json.loads(metadata) if isinstance(metadata, str) else {}
            except Exception:
                metadata_obj = {}
            session = Session(
                key=meta.get("key", key),
                messages=messages,
                created_at=datetime.fromisoformat(created) if created else datetime.now(),
                updated_at=datetime.fromisoformat(updated) if updated else datetime.now(),
                metadata=metadata_obj if isinstance(metadata_obj, dict) else {},
                last_consolidated=int(meta.get("last_consolidated", 0) or 0),
            )
        else:
            session = Session(key=key)
        self._cache[key] = session
        self._saved_counts[key] = len(session.messages)
        return session

    def save(self, session: Session) -> None:
        saved_count = int(self._saved_counts.get(session.key, 0) or 0)
        if saved_count < 0 or saved_count > len(session.messages):
            saved_count = 0

        new_msgs = session.messages[saved_count:]
        if new_msgs:
            self.redis.rpush(
                self._messages_key(session.key),
                *[json.dumps(m, ensure_ascii=False) for m in new_msgs],
            )

        self.redis.hset(
            self._meta_key(session.key),
            mapping={
                "key": session.key,
                "created_at": session.created_at.isoformat(),
                "updated_at": session.updated_at.isoformat(),
                "metadata": json.dumps(session.metadata, ensure_ascii=False),
                "last_consolidated": session.last_consolidated,
            },
        )

        self._cache[session.key] = session
        self._saved_counts[session.key] = len(session.messages)
        self._touch_ttl(session.key)

    def invalidate(self, key: str) -> None:
        self._cache.pop(key, None)
        self._saved_counts.pop(key, None)

    def list_sessions(self) -> list[dict[str, Any]]:
        pattern = f"{self.key_prefix}:*:meta"
        out: list[dict[str, Any]] = []
        for meta_key in self.redis.scan_iter(match=pattern):
            meta = self.redis.hgetall(meta_key) or {}
            if not meta:
                continue
            out.append({
                "key": meta.get("key", ""),
                "created_at": meta.get("created_at"),
                "updated_at": meta.get("updated_at"),
                "path": f"redis://{meta_key}",
            })
        return sorted(out, key=lambda x: x.get("updated_at", ""), reverse=True)
