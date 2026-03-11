# Code Review: Redis Integration

**Reviewer:** Claude
**Date:** 2026-03-11
**Scope:** All files changed/added for Redis Streams bridge + Redis session manager

---

## Overall Assessment

Implementation is solid and well-structured. Config schema, session manager, stream bridge, migration helper, tests, and Docker wiring are all present and functional. Below are issues ranked by severity.

---

## Critical

### 1. `RedisSessionManager` uses sync Redis in an async gateway

**File:** `mebot/session/redis_manager.py`
**File:** `mebot/cli/commands.py:318`

`RedisSessionManager` uses synchronous `redis.Redis` calls (`hgetall`, `rpush`, `lrange`, `expire`, etc.) but the gateway runs in an `asyncio` event loop. These blocking calls will block the entire event loop during I/O, degrading throughput under load.

**Suggestion:** Either:
- Use `redis.asyncio.Redis` and make all methods `async`, or
- Run sync calls in `asyncio.to_thread()` / `loop.run_in_executor()`

The disk `SessionManager` gets away with sync I/O because file operations are fast and local. Redis has network latency.

### 2. `_handle_inbound_entry` always ACKs, even on validation failure

**File:** `mebot/channels/redis_channel.py:147-151`

Messages rejected by `_validate_api_key` or missing fields are still ACKed. An attacker or misconfigured producer sending invalid messages will have them silently consumed and lost. Consider:
- NACK or move rejected messages to a dead-letter stream
- At minimum, log the full `msg_id` + `fields` for rejected entries (currently only logs a generic warning)

---

## Major

### 3. No interface/protocol shared between `SessionManager` and `RedisSessionManager`

**File:** `mebot/session/manager.py`, `mebot/session/redis_manager.py`

Both managers expose the same methods (`get_or_create`, `save`, `invalidate`, `list_sessions`) but share no `Protocol` or ABC. The gateway assigns either to the same variable (`session_manager`), relying on duck typing. This works but is fragile:
- Type checkers can't verify correctness
- A future method rename in one class won't be caught

**Suggestion:** Add a `SessionStore` Protocol in `mebot/session/manager.py`:

```python
from typing import Protocol

class SessionStore(Protocol):
    def get_or_create(self, key: str) -> Session: ...
    def save(self, session: Session) -> None: ...
    def invalidate(self, key: str) -> None: ...
    def list_sessions(self) -> list[dict[str, Any]]: ...
```

### 4. `RedisSessionManager` has no in-memory cache

**File:** `mebot/session/redis_manager.py:38`

Every `get_or_create` call hits Redis. The disk `SessionManager` caches sessions in `_cache`. For a gateway handling multiple messages per second to the same channel, this means redundant Redis round-trips.

**Suggestion:** Add a simple `_cache` dict like `SessionManager` does, invalidate on `save`/`invalidate`.

### 5. `gateway()` function shadows `config` parameter with loaded config

**File:** `mebot/cli/commands.py:281,298`

```python
def gateway(
    config: str | None = typer.Option(...),  # str | None
):
    config = _load_runtime_config(config, workspace)  # now Config object
```

The `config` variable changes type from `str | None` to `Config`. This confuses type checkers and IDEs. Rename the loaded config to `cfg` (already done in `session_migrate`).

### 6. Missing Redis connectivity check at startup

**File:** `mebot/cli/commands.py:309-331`

The gateway creates Redis clients but never calls `ping()` to verify connectivity. If Redis is unreachable, the error will only surface later during stream consumption or session save. The `session_migrate` command does `redis_sync_client.ping()` — gateway should too.

---

## Minor

### 7. `_touch_ttl` is sync, no pipeline

**File:** `mebot/session/redis_manager.py:32-36`

Two separate `expire` calls per save. Use a Redis pipeline to batch them into one round-trip:

```python
pipe = self.redis.pipeline()
pipe.expire(self._meta_key(key), self.ttl_seconds)
pipe.expire(self._messages_key(key), self.ttl_seconds)
pipe.execute()
```

### 8. `_safe_key` double-sanitizes colons

**File:** `mebot/session/redis_manager.py:23-24`

`_safe_key` replaces `:` with `_`, then passes through `safe_filename`. But the key prefix already uses `:` as delimiter (`mebot:session:mezon_123:meta`). If the raw key contains underscores, different keys could collide (e.g., `mezon:1_2` and `mezon:1:2` both become `mezon_1_2`).

**Suggestion:** Use a more robust separator (e.g., keep `:` in the sub-key since Redis keys support it, or use URL-safe encoding).

### 9. `_serialize_payload` swallows `model_dump()` exceptions silently

**File:** `mebot/channels/redis_channel.py:181-184`

If `model_dump()` raises, it falls through to `__dict__` scraping. This could produce incomplete or incorrect event data. At minimum log a warning.

### 10. `setattr(session, "_saved_count", ...)` is a code smell

**File:** `mebot/session/redis_manager.py:66,92`

Using `setattr` to attach `_saved_count` to a `Session` dataclass is brittle. If `Session` ever validates attributes or uses `__slots__`, this breaks.

**Suggestion:** Add `_saved_count` as a field on `Session` (with `default=0`, excluded from serialization), or track it in a dict inside `RedisSessionManager`.

### 11. `redis_channel.py` imports not guarded

**File:** `mebot/channels/__init__.py:3`

`from mebot.channels.redis_channel import RedisChannel` runs at import time. If the `redis` package is not installed (it's now a hard dependency, but was optional before), this import won't fail directly since `redis_channel.py` doesn't import `redis` at module level. Fine for now, but worth noting if `redis` dependency becomes optional again.

### 12. Test coverage gaps

**File:** `tests/test_redis_session_manager.py`

Missing tests for:
- `list_sessions()` return value
- `invalidate()` then `get_or_create()` returns empty session
- `get_or_create()` with corrupted JSON in messages list
- TTL disabled (`ttl_days=0`) scenario
- `RedisChannel` has no tests at all

### 13. `approximate=False` on XADD maxlen

**File:** `mebot/channels/redis_channel.py:170`

`approximate=False` means exact trimming, which is slower. Redis docs recommend `approximate=True` (the `~` prefix) for better performance. Unless exact cap is required, switch to `approximate=True`.

### 14. `dispatch_task` could be `None` when accessed in `finally`

**File:** `mebot/cli/commands.py:485`

If `redis_stream_ch.start()` or `cron.start()` raises before `dispatch_task` is assigned at line 476, the `finally` block will hit `dispatch_task.cancel()` on `None`.

---

## Nitpicks

- `mebot/cli/commands.py:298` — `config` variable name reuse (mentioned above), also applies to `agent()` command at line 527.
- `mebot/session/redis_manager.py:62` — `last_consolidated` stored as int but retrieved from Redis hash as string; `int(meta.get("last_consolidated", 0) or 0)` works but is fragile — consider explicit `str` -> `int` conversion.
- `docker-compose.yml:14` — `maxmemory-policy allkeys-lru` will evict session keys under memory pressure. Consider `volatile-lru` and setting TTL on all keys (which you already do), so only expired keys get evicted first.

---

## Architectural

### 15. `RedisChannel` is misplaced in `channels/`

**File:** `mebot/channels/redis_channel.py`

`MezonChannel` is a chat platform — receives user messages, sends replies. `RedisChannel` is fundamentally different: it's an **infrastructure bridge** with two responsibilities:

- **Inbound:** consume external triggers (n8n, webhooks) from `mebot:inbound` → publish to internal bus
- **Outbound:** forward Mezon SDK events → `mezon:events` stream

It doesn't represent a chat platform. Placing it alongside `MezonChannel` in `channels/` conflates two different abstraction levels and misleads future contributors into thinking it's another chat integration.

**Suggestion:** Move to `mebot/bridge/redis_streams.py` or `mebot/infra/redis_bridge.py`:

```
mebot/
├── channels/
│   └── mezon.py              # chat platform integration
├── bridge/
│   └── redis_streams.py      # external trigger bridge (renamed from redis_channel.py)
```

Update imports in `mebot/channels/__init__.py` and `mebot/cli/commands.py` accordingly.

### 16. Internal MessageBus should NOT be replaced by Redis Streams

The current design where `RedisChannel` bridges into the internal `asyncio.Queue`-based `MessageBus` is correct. Rationale:

- **Zero latency** — in-process queue, no serialization, no network hop per message
- **Redis stays optional** — CLI mode, tests, local dev all run without Redis
- **Single-process bot** — `asyncio.Queue` is essentially free; replacing with Redis Streams for all internal routing adds ~1ms latency per message + ser/deser overhead for every agent interaction
- **Graceful degradation** — Redis goes down, bot keeps running (only loses external triggers)

Replacing the internal bus with Redis Streams would only make sense if mebot becomes multi-process or needs message persistence across restarts. For current single-process architecture, keep the internal bus.

---

## Summary

| Severity | Count |
|----------|-------|
| Critical | 2 |
| Major | 4 |
| Minor | 8 |
| Architectural | 2 |
| Nitpick | 3 |

**Top priority:** Fix sync Redis in async context (#1). Everything else can be addressed incrementally.

---

## Maintainer Responses

### #1 Sync Redis in async gateway
reply: Đúng về mặt kiến trúc dài hạn, nhưng hiện tại `AgentLoop` và `SessionStore` interface đang sync toàn bộ. Chuyển async cho session layer cần refactor diện rộng (AgentLoop, Memory flow, heartbeat target selection). Đã giảm rủi ro ngắn hạn bằng cache nội bộ + giảm round-trip Redis; đề xuất async refactor sẽ làm ở PR riêng.

reviewer: Chấp nhận. Cache nội bộ giảm đáng kể tần suất hit Redis (chỉ cold-start và save mới gọi). Lưu ý: `save()` vẫn blocking trên event loop — nếu Redis latency spike (network hiccup, persistence fork), gateway sẽ freeze cho tất cả channel. Đề xuất bổ sung: wrap `save()` trong `asyncio.to_thread()` tại call-site trong `AgentLoop` — nhẹ hơn nhiều so với async toàn bộ SessionStore, không cần đổi interface. Đánh dấu TODO cho PR tiếp.

### #2 Always ACK invalid inbound entries
reply: Hành vi này là chủ đích theo spec hiện tại (fire-and-forget, reject thì bỏ message để không retry vô hạn). Đã giữ nguyên ACK để tránh poison pending list.

reviewer: Đồng ý ACK là đúng để tránh poison pill. Concern ban đầu là về observability, không phải retry. Hiện log chỉ ghi `"invalid x-api-key"` hoặc `"missing content/targetChannelId"` — không kèm `msg_id` hay sender info. Đề xuất nhỏ: thêm `msg_id` vào warning log để debug production dễ hơn, không cần thay đổi flow.

### #5 `config` variable shadowing
reply: Đây là vấn đề readability/type-hint nhỏ, chưa ảnh hưởng runtime. Tạm thời giữ để tránh patch lớn lan rộng; sẽ cleanup naming ở PR refactor CLI.

reviewer: OK, defer hợp lý.

### #8 `_safe_key` potential collision
reply: Nhận xét hợp lý, nhưng thay encoding key ngay lúc này có thể phá backward compatibility của dữ liệu Redis đã ghi. Cần migration key-space rõ ràng trước khi đổi format.

reviewer: Push back nhẹ — Redis session là feature **mới**, chưa có production data. Đây chính là thời điểm tốt nhất để fix key format trước khi có user data cần migrate. Sau khi ship lên production thì backward compat mới thực sự ràng buộc. Nếu chưa muốn sửa ngay, ít nhất nên document key format hiện tại và collision scenario trong code comment, để người sau biết limitation.

### #13 `approximate=False` on maxlen
reply: Cố ý giữ `approximate=False` để đảm bảo checklist yêu cầu "stream không vượt quá maxLen entries". Nếu ưu tiên throughput hơn giới hạn cứng, có thể đổi lại `approximate=True`.

reviewer: Chấp nhận. Nếu spec yêu cầu hard cap thì exact trimming là đúng. Để lại ghi chú inline trong code giải thích lý do chọn `approximate=False` — tránh người sau "optimize" nhầm.

### #15 `RedisChannel` placement in `channels/`
reply: Về kiến trúc là đề xuất tốt, nhưng hiện tại ưu tiên giữ scope thay đổi nhỏ để ổn định release. Việc tách sang `bridge/` sẽ xử lý trong đợt tái cấu trúc module boundaries.

reviewer: OK, scope management hợp lý. Đề xuất: thêm comment ở đầu `redis_channel.py` ghi rõ đây là bridge/adapter, không phải chat channel, để tránh nhầm lẫn trong thời gian chờ refactor.

---

## Resolved Items (verified in code)

- **#3** SessionStore Protocol — `manager.py:216-222` added `SessionStore(Protocol)` ✓
- **#4** In-memory cache — `redis_manager.py:22-23` added `_cache` dict + `_saved_counts` dict ✓
- **#6** Redis ping at startup — `commands.py:319` added `redis_sync_client.ping()` ✓
- **#7** Pipeline for TTL — `redis_manager.py:37-40` uses `pipeline()` for batched expire ✓
- **#9** Silent `model_dump()` — `redis_channel.py:183-184` now logs warning on failure ✓
- **#10** `setattr _saved_count` hack — `redis_manager.py:23` replaced with `_saved_counts: dict[str, int]` tracked in manager ✓
- **#12** Test coverage — 4 new tests added (`invalidate`, `list_sessions`, `corrupted JSON`, `ttl_days=0`) ✓
- **#14** dispatch_task None guard — `commands.py:486` wrapped with `if dispatch_task:` ✓

### Verification notes

**#4 cache + #10 _saved_counts:** Đã xác nhận `_cache` và `_saved_counts` được:
- Populated on `get_or_create()` (line 73-74)
- Updated on `save()` (line 100-101)
- Cleared on `invalidate()` (line 105-106)
- `test_invalidate_clears_cache_only` test confirms invalidate clears cache but Redis data remains, subsequent `get_or_create` re-fetches from Redis ✓

**#4 nhận xét thêm:** `invalidate()` hiện tại chỉ xóa cache nội bộ, **không** xóa data trong Redis (khác với bản cũ dùng `self.redis.delete()`). Đây là thay đổi hành vi so với bản review ban đầu — cần xác nhận đây là chủ đích. Disk `SessionManager.invalidate()` cũng chỉ xóa cache nên hành vi này consistent, nhưng tên method `invalidate` có thể gây nhầm lẫn. Nếu muốn xóa data Redis thật thì cần method riêng (ví dụ `delete()`).

**#7 pipeline:** FakeRedis test cũng được cập nhật với `_Pipeline` class để support pipeline API ✓

**#9 model_dump warning:** `redis_channel.py:183-184` giờ ghi `logger.warning("Failed model_dump() for event payload: {}", exc)` trước khi fallback sang `__dict__` ✓

## Still Open

| # | Item | Status |
|---|------|--------|
| 1 | Sync Redis in async loop | Deferred — mitigated by cache, needs `to_thread` wrap |
| 2 | ACK invalid entries | Won't fix (by design) — **chưa thêm `msg_id` vào log** |
| 5 | Config variable shadowing | Deferred to CLI refactor PR |
| 8 | Key collision risk | **Should fix now** before production data exists |
| 11 | Import guard for redis | Open — low priority |
| 13 | `approximate=False` | Won't change (by spec) — **chưa thêm code comment** |
| 15 | RedisChannel placement | Deferred — **chưa thêm bridge/adapter comment ở đầu file** |
| 16 | Keep internal MessageBus | Acknowledged (no action needed) |

### Micro-fixes còn thiếu (từ reviewer suggestions đã agreed)

1. **#2 log `msg_id`:** `redis_channel.py:125,132` — warning log vẫn chưa kèm `msg_id`. Sửa:
   ```python
   logger.warning("Redis inbound rejected ({}): invalid x-api-key", msg_id)
   logger.warning("Redis inbound rejected ({}): missing content/targetChannelId", msg_id)
   ```
2. **#13 inline comment:** `redis_channel.py:170` — thêm comment giải thích `approximate=False`:
   ```python
   # exact trimming (not approximate) — spec requires hard cap on stream length
   kwargs["approximate"] = False
   ```
3. **#15 module docstring:** `redis_channel.py:1` — cập nhật docstring rõ hơn:
   ```python
   """Redis Streams bridge (NOT a chat channel) for external triggers and Mezon event forwarding.

   NOTE: This module lives in channels/ for now but is architecturally a bridge/adapter.
   Planned to move to mebot/bridge/ in a future refactor.
   """
   ```

### Update (applied)

- #2 đã thêm `msg_id` vào warning log reject inbound.
- #13 đã thêm inline comment giải thích vì sao dùng `approximate=False`.
- #15 đã cập nhật module docstring rõ vai trò bridge/adapter.
- #8 đã sửa key encoding sang URL-encode để tránh collision `:` vs `_`.
