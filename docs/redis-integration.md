# Redis Integration

Redis được dùng cho hai mục đích trong cùng một service:
1. **Redis Streams** — bidirectional event bridge với external systems (n8n, ...)
2. **Redis Session Store** — thay thế disk-based JSONL session storage

---

## Part 1: Redis Streams — Event Bridge

### Problem

External systems (n8n) cần:
1. **Trigger** bot làm việc gì đó mà không qua Mezon chat — ví dụ: gửi thông báo vào channel, post pricing info
2. **React** với Mezon platform events — ví dụ: user join clan -> n8n trigger onboarding workflow

Hiện tại bot chỉ nhận input qua Mezon WebSocket và không forward platform events ra ngoài.

### Architecture

```
[INBOUND]
n8n ──XADD──> mebot:inbound (Stream) ──> RedisChannel ──> bus.inbound ──> AgentLoop ──> MezonChannel.send()

[OUTBOUND]
MezonChannel ──event handlers──> RedisChannel._publish_event() ──XADD──> mezon:events (Stream)
                                                                              |
                                                              n8n XREAD/XREADGROUP <──┘
```

### Design Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Technology | Redis Streams (not RabbitMQ/Kafka) | Fire-and-forget là use case chính, không cần native RPC; nhẹ hơn RabbitMQ (~50MB vs ~128MB); Redis đã có cho session store |
| Inbound mode | Fire-and-forget only | n8n trigger bot "làm việc gì đó" — không cần wait for response |
| Outbound | Single stream `mezon:events`, filter by `event` field | Đơn giản hơn topic exchange, consumer dùng XREADGROUP + filter |
| Auth | `x-api-key` field trong message body | AMQP headers không có trong Redis Streams protocol |
| Event forwarding | Configurable per event, default off | `forwardEvents` list trong config |
| Python library | `redis>=5.0` (`redis.asyncio`) | Đã phổ biến, async support tốt, cùng package dùng cho session |
| Consumer groups | Dùng cho outbound events | n8n subscribe qua XREADGROUP để đảm bảo at-least-once |

### Inbound: External Trigger (n8n -> bot)

**n8n publishes** vào stream `mebot:inbound`:

```
XADD mebot:inbound * \
  x-api-key your-secret-key \
  content "Gửi pricing info vào channel sales" \
  targetChannelId "12345678" \
  senderId "n8n-workflow-abc" \
  metadata "{\"workflowId\": \"wf-123\"}"
```

Fields:
- `x-api-key` (required): auth key khớp với config
- `content` (required): nội dung yêu cầu cho agent
- `targetChannelId` (required): Mezon channel ID để bot gửi response
- `senderId` (optional, default `"n8n"`): dùng làm session key prefix
- `metadata` (optional): JSON string, pass-through vào `InboundMessage.metadata`

**Session key**: `mezon:{targetChannelId}` — chia sẻ session với Mezon conversations trực tiếp, bot nhớ context.

**Bot processing**:
1. `RedisChannel` đọc stream qua `XREADGROUP` (consumer group `mebot-workers`)
2. Validate `x-api-key`
3. Tạo `InboundMessage(channel="mezon", chat_id=targetChannelId, ...)`
4. Push vào `bus.inbound` -> `AgentLoop` xử lý -> `MezonChannel.send()` gửi vào Mezon
5. ACK message (`XACK mebot:inbound mebot-workers {id}`)

### Outbound: Mezon Event Forwarding (Mezon -> Redis)

**Available events** (từ Mezon SDK `Events` enum):

| Event name | Description |
|---|---|
| `channel_message` | Message in channel/thread |
| `message_reaction_event` | Reaction on message |
| `message_button_clicked` | Button click in embed message |
| `dropdown_box_selected` | Dropdown selection |
| `user_channel_added_event` | User added to channel |
| `user_channel_removed_event` | User removed from channel |
| `add_clan_user_event` | User joined clan |
| `user_clan_removed_event` | User left/removed from clan |
| `channel_created_event` | Channel created |
| `channel_updated_event` | Channel updated |
| `channel_deleted_event` | Channel deleted |
| `role_event` | New role created |
| `role_assign_event` | Role assigned to user |
| `give_coffee_event` | Coffee given |
| `token_sent_event` | Token sent |
| `clan_event_created` | Clan event created |
| `voice_started_event` | Voice started |
| `voice_ended_event` | Voice ended |
| `voice_joined_event` | User joined voice |
| `voice_leaved_event` | User left voice |
| `streaming_joined_event` | User joined stream |
| `streaming_leaved_event` | User left stream |
| `notifications` | Notifications |
| `quick_menu_event` | Quick menu |
| `ai_agent_enabled_event` | AI agent enabled |

**Format** (XADD vào `mezon:events`):

```
event       = "channel_message"
timestamp   = "2026-03-11T10:00:00Z"
data        = "{...}"   ← JSON string của event attributes
```

**n8n consume**:

```
# Subscribe tất cả events
XREADGROUP GROUP n8n-consumers worker1 BLOCK 0 STREAMS mezon:events >

# Filter trong n8n Function node theo field `event`
if (item.event === 'add_clan_user_event') { ... }
```

---

## Part 2: Redis Session Store

### Problem

`SessionManager` hiện tại lưu session vào JSONL files trên disk:
- Mỗi session = 1 file `{workspace}/sessions/{safe_key}.jsonl`
- In-memory `_cache` dict để giảm disk reads
- `save()` **rewrite toàn bộ file** mỗi lần — không hiệu quả

### Mapping sang Redis

```
mebot:session:{key}:meta      → Hash   { created_at, updated_at, metadata, last_consolidated }
mebot:session:{key}:messages  → List   [ msg_json, msg_json, ... ]
```

Key conventions:
- `{key}` = session key hiện tại, ví dụ `mezon_1234567890` (`:` thay bằng `_` như hiện tại)
- TTL: 30 ngày mặc định, configurable — auto-expire sessions không active

### RedisSessionManager

Interface giống hệt `SessionManager` để dễ swap:

```python
class RedisSessionManager:
    def __init__(self, redis: Redis, ttl_days: int = 30)

    def get_or_create(key: str) -> Session        # HGETALL meta + LRANGE messages 0 -1
    def save(session: Session) -> None             # HSET meta + RPUSH chỉ messages mới (delta)
    def invalidate(key: str) -> None               # DEL hoặc EXPIRE = 0 (tùy config)
    def list_sessions() -> list[dict]              # SCAN mebot:session:*:meta + HGETALL
```

**Smart save (delta append)**:
- Track `_saved_count` trên `Session` object
- `save()` chỉ RPUSH `messages[_saved_count:]` (messages mới chưa được lưu)
- Không xóa và ghi lại toàn bộ như disk version
- HSET meta mỗi lần (nhỏ, O(1))
- Reset TTL sau mỗi save: `EXPIRE mebot:session:{key}:* {ttl_seconds}`

**Xóa `_cache` dict**:
- Redis đã là cache — không cần double cache trong memory
- `get_or_create` luôn đọc từ Redis (nhanh hơn disk, không cần cache thêm)

### Migration từ disk

Cần migration tool khi switch sang Redis:

```python
# mebot/session/migrate.py
async def migrate_disk_to_redis(sessions_dir: Path, redis_manager: RedisSessionManager):
    for jsonl_path in sessions_dir.glob("*.jsonl"):
        session = disk_manager._load(key)
        if session:
            await redis_manager.save(session)
```

CLI command: `mebot session migrate` hoặc auto-migrate khi `get_or_create` không tìm thấy session trong Redis.

---

## Configuration

```json
{
  "redis": {
    "enabled": false,
    "url": "redis://localhost:6379/0",
    "password": "",
    "streams": {
      "inboundStream": "mebot:inbound",
      "eventsStream": "mezon:events",
      "consumerGroup": "mebot-workers",
      "consumerName": "mebot-1",
      "apiKey": "your-secret-api-key",
      "forwardEvents": [
        "channel_message",
        "message_reaction_event",
        "add_clan_user_event"
      ],
      "maxLen": 10000
    },
    "session": {
      "enabled": false,
      "ttlDays": 30,
      "keyPrefix": "mebot:session"
    }
  }
}
```

- `redis.enabled`: master switch — nếu false, không kết nối Redis, mọi thứ fallback về disk
- `streams` và `session` có thể bật/tắt riêng lẻ
- `maxLen`: giới hạn độ dài stream (MAXLEN ~), auto-trim entries cũ
- `session.ttlDays`: 0 = không expire

---

## Implementation Plan

### Files to create

| File | Description |
|---|---|
| `mebot/channels/redis_channel.py` | `RedisChannel` — inbound stream consumer + outbound event publisher |
| `mebot/session/redis_manager.py` | `RedisSessionManager` — Redis-backed session store |
| `mebot/session/migrate.py` | Migration tool: disk JSONL -> Redis |

### Files to modify

| File | Changes |
|---|---|
| `pyproject.toml` | Add `redis>=5.0` |
| `mebot/config/schema.py` | Add `RedisConfig`, `RedisStreamsConfig`, `RedisSessionConfig` |
| `mebot/channels/__init__.py` | Export `RedisChannel` |
| `mebot/channels/mezon.py` | Accept optional `event_forwarder`, call `setup_event_forwarding()` sau khi login |
| `mebot/cli/commands.py` | Wire `RedisChannel` vào gateway, khởi tạo `RedisSessionManager` nếu enabled, truyền vào `AgentLoop` |
| `mebot/session/__init__.py` | Export `RedisSessionManager` |
| `docker-compose.yml` | Add Redis service + volume |

### RedisChannel class structure

```
RedisChannel
├── __init__(config, bus)
├── start()                        # connect, create consumer groups, start consume loop
├── stop()                         # close connection
├── setup_event_forwarding(client) # register Mezon SDK event handlers
├── _consume_loop()                # XREADGROUP loop, validate auth, push to bus, XACK
├── _publish_event(event, data)    # XADD vào mezon:events stream
└── _validate_api_key(fields)      # check x-api-key field
```

### Gateway startup (`commands.py`)

```python
redis_client = await create_redis(config.redis) if config.redis.enabled else None
redis_ch = RedisChannel(config.redis.streams, bus) if redis_client and config.redis.streams else None
session_mgr = RedisSessionManager(redis_client, config.redis.session) if redis_client and config.redis.session.enabled else SessionManager(workspace)

# asyncio.gather tasks
tasks = [mezon_ch.start()]
if redis_ch:
    tasks.append(redis_ch.start())
```

### Docker-compose addition

```yaml
redis:
  image: redis:7-alpine
  container_name: mebot-redis
  ports:
    - "6379:6379"
  command: redis-server --appendonly yes --maxmemory 256mb --maxmemory-policy allkeys-lru
  volumes:
    - redis_data:/data
  restart: unless-stopped
  healthcheck:
    test: ["CMD", "redis-cli", "ping"]
    interval: 10s
    timeout: 3s
    retries: 5
```

Add `depends_on: redis: condition: service_healthy` vào `mebot-gateway`.
Add `redis_data` volume.

---

## Verification Checklist

### Redis Streams
- [ ] `docker compose up redis` — `redis-cli ping` trả về PONG
- [ ] `mebot gateway` — logs "Redis connected", "Consuming mebot:inbound", "Forwarding N Mezon events"
- [ ] Inbound trigger: `XADD mebot:inbound * x-api-key test content "test" targetChannelId "123"` -> bot gửi vào Mezon
- [ ] Auth rejection: sai `x-api-key` -> message bị XACK không xử lý, log warning
- [ ] Outbound events: gửi message trong Mezon -> `XRANGE mezon:events - +` thấy event
- [ ] Consumer group: `XINFO GROUPS mebot:inbound` hiển thị group `mebot-workers`
- [ ] Stream trimming: stream không vượt quá `maxLen` entries

### Redis Session
- [ ] `mebot gateway` với `redis.session.enabled=true` — logs "Using Redis session store"
- [ ] Gửi message -> session được lưu: `HGETALL mebot:session:mezon_123:meta`
- [ ] Messages được append: `LRANGE mebot:session:mezon_123:messages 0 -1`
- [ ] TTL được set: `TTL mebot:session:mezon_123:meta` trả về > 0
- [ ] Delta save: chỉ messages mới được RPUSH, không rewrite toàn bộ
- [ ] Migration: `mebot session migrate` chuyển JSONL cũ sang Redis thành công
- [ ] Fallback: `redis.enabled=false` -> bot dùng disk `SessionManager` như cũ

---

## Why Redis over RabbitMQ/Kafka

| | Redis Streams | RabbitMQ | Kafka |
|---|---|---|---|
| RPC pattern | Manual (không cần) | Native | Manual |
| Fire-and-forget | Tốt | Tốt | Tốt |
| Event replay | Có (XRANGE) | Không | Có |
| Consumer groups | Có | Có | Có |
| Footprint | ~50MB | ~128MB | ~1GB+ |
| Multi-purpose | Cache, session, streams | Messaging only | Streaming only |
| Ops complexity | Thấp | Thấp-vừa | Cao |

**Redis thắng** vì: use case chính là fire-and-forget, không cần RPC; Redis đồng thời làm session store — một service cho cả hai, giảm infra complexity.
