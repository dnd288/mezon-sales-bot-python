from datetime import datetime

from mebot.config.schema import RedisSessionConfig
from mebot.session.manager import Session
from mebot.session.redis_manager import RedisSessionManager


class _FakeRedis:
    def __init__(self):
        self.hashes: dict[str, dict] = {}
        self.lists: dict[str, list[str]] = {}
        self.expire_map: dict[str, int] = {}

    def hgetall(self, key: str):
        return dict(self.hashes.get(key, {}))

    def lrange(self, key: str, start: int, end: int):
        items = self.lists.get(key, [])
        if end == -1:
            return items[start:]
        return items[start:end + 1]

    def rpush(self, key: str, *values: str):
        self.lists.setdefault(key, []).extend(values)

    def hset(self, key: str, mapping: dict):
        self.hashes.setdefault(key, {}).update(mapping)

    def expire(self, key: str, ttl: int):
        self.expire_map[key] = ttl

    def delete(self, *keys: str):
        for key in keys:
            self.hashes.pop(key, None)
            self.lists.pop(key, None)
            self.expire_map.pop(key, None)

    class _Pipeline:
        def __init__(self, outer):
            self.outer = outer
            self.ops: list[tuple[str, str, int]] = []

        def expire(self, key: str, ttl: int):
            self.ops.append(("expire", key, ttl))
            return self

        def execute(self):
            for op, key, ttl in self.ops:
                if op == "expire":
                    self.outer.expire(key, ttl)
            self.ops.clear()
            return True

    def pipeline(self):
        return self._Pipeline(self)

    def scan_iter(self, match: str):
        # Supports "<prefix>:*:meta" pattern only (sufficient for unit test).
        prefix = match.split("*", 1)[0]
        for key in list(self.hashes):
            if key.startswith(prefix) and key.endswith(":meta"):
                yield key


def test_save_and_load_roundtrip() -> None:
    redis = _FakeRedis()
    cfg = RedisSessionConfig(enabled=True, ttl_days=30, key_prefix="mebot:session")
    mgr = RedisSessionManager(redis, cfg)

    session = Session(
        key="mezon:123",
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    session.messages.append({"role": "user", "content": "hello"})
    mgr.save(session)

    loaded = mgr.get_or_create("mezon:123")
    assert len(loaded.messages) == 1
    assert loaded.messages[0]["content"] == "hello"
    assert redis.expire_map  # TTL touched


def test_save_appends_delta_only() -> None:
    redis = _FakeRedis()
    cfg = RedisSessionConfig(enabled=True, ttl_days=30, key_prefix="mebot:session")
    mgr = RedisSessionManager(redis, cfg)

    session = Session(key="mezon:123")
    session.messages.append({"role": "user", "content": "m1"})
    mgr.save(session)
    session.messages.append({"role": "assistant", "content": "m2"})
    mgr.save(session)

    msg_key = mgr._messages_key("mezon:123")  # noqa: SLF001
    assert len(redis.lists[msg_key]) == 2


def test_invalidate_clears_cache_only() -> None:
    redis = _FakeRedis()
    cfg = RedisSessionConfig(enabled=True, ttl_days=30, key_prefix="mebot:session")
    mgr = RedisSessionManager(redis, cfg)

    session = Session(key="mezon:abc")
    session.messages.append({"role": "user", "content": "m1"})
    mgr.save(session)
    mgr.invalidate("mezon:abc")

    loaded = mgr.get_or_create("mezon:abc")
    assert len(loaded.messages) == 1


def test_list_sessions_returns_entries() -> None:
    redis = _FakeRedis()
    cfg = RedisSessionConfig(enabled=True, ttl_days=30, key_prefix="mebot:session")
    mgr = RedisSessionManager(redis, cfg)

    s1 = Session(key="mezon:1")
    s1.messages.append({"role": "user", "content": "a"})
    mgr.save(s1)
    s2 = Session(key="mezon:2")
    s2.messages.append({"role": "user", "content": "b"})
    mgr.save(s2)

    sessions = mgr.list_sessions()
    keys = {item["key"] for item in sessions}
    assert "mezon:1" in keys
    assert "mezon:2" in keys


def test_get_or_create_skips_corrupted_message_json() -> None:
    redis = _FakeRedis()
    cfg = RedisSessionConfig(enabled=True, ttl_days=30, key_prefix="mebot:session")
    mgr = RedisSessionManager(redis, cfg)
    msg_key = mgr._messages_key("mezon:bad")  # noqa: SLF001
    meta_key = mgr._meta_key("mezon:bad")  # noqa: SLF001
    redis.hashes[meta_key] = {
        "key": "mezon:bad",
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
        "metadata": "{}",
        "last_consolidated": "0",
    }
    redis.lists[msg_key] = ["{bad json", '{"role":"user","content":"ok"}']

    loaded = mgr.get_or_create("mezon:bad")
    assert len(loaded.messages) == 1
    assert loaded.messages[0]["content"] == "ok"


def test_ttl_disabled_does_not_set_expire() -> None:
    redis = _FakeRedis()
    cfg = RedisSessionConfig(enabled=True, ttl_days=0, key_prefix="mebot:session")
    mgr = RedisSessionManager(redis, cfg)
    session = Session(key="mezon:no-ttl")
    session.messages.append({"role": "user", "content": "hello"})
    mgr.save(session)
    assert redis.expire_map == {}
