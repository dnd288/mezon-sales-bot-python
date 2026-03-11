# Redis Integration Task

Source: `/Users/mrdnd/src/mezon/mezon-sales-bot-python/docs/redis-integration.md`

## Task Checklist

- [x] Add Redis dependency (`redis>=5.0`) in `pyproject.toml`
- [x] Add Redis config schema (`RedisConfig`, streams/session settings)
- [x] Implement Redis Streams bridge channel:
  - [x] Consume `mebot:inbound` via consumer group
  - [x] Validate `x-api-key`
  - [x] Publish to internal bus as `InboundMessage(channel="mezon", ...)`
  - [x] Forward configured Mezon events to `mezon:events`
- [x] Implement Redis session manager:
  - [x] Redis hash/list key model
  - [x] Delta append save strategy
  - [x] TTL refresh on save
  - [x] list/invalidate interfaces
- [x] Add migration helper `disk JSONL -> Redis`
- [x] Wire Redis into gateway startup/shutdown
- [x] Wire event forwarder into Mezon channel
- [x] Add Redis service in `docker-compose.yml`

## Notes

- Current implementation keeps existing fallbacks:
  - If `redis.enabled=false`, bot continues using disk `SessionManager`.
  - If Redis init fails, gateway logs warning and falls back to disk sessions.
