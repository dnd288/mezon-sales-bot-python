# mezon-sales-bot-python

AI sales bot for the [Mezon](https://mezon.ai) platform, built on the `mebot` agent framework. Connects to Mezon via WebSocket (no public IP required) and handles customer inquiries using an LLM backend.

## Features

- Mezon channel integration via `mezon-sdk` with auto-reconnect
- Lean message pipeline with mention-only filtering and typing indicators
- LLM support via LiteLLM (OpenRouter, Anthropic, OpenAI, DeepSeek, etc.)
- Cron scheduling and heartbeat service
- MCP (Model Context Protocol) tool support
- Split CLI surface for direct agent interaction, gateway server mode, provider login, and session tools
- Optional Redis integration: Streams bridge for external triggers (n8n, webhooks) and Redis-backed session storage with TTL

## Requirements

- Python 3.13+
- A Mezon bot account (`client_id` + `token`)
- An LLM API key (e.g. OpenRouter, Anthropic)
- Redis 7+ (optional — for Streams bridge and/or session storage)

## Installation

```bash
pip install -e .
```

## Configuration

Initialize config:

```bash
mebot onboard
```

Edit `~/.mebot/config.json`:

```json
{
  "channels": {
    "mezon": {
      "enabled": true,
      "clientId": "YOUR_BOT_CLIENT_ID",
      "token": "YOUR_BOT_TOKEN"
    }
  },
  "providers": {
    "openrouter": {
      "apiKey": "sk-or-..."
    }
  },
  "agents": {
    "defaults": {
      "model": "anthropic/claude-opus-4-5"
    }
  }
}
```

## Usage

**Start the gateway (Mezon channel + cron + heartbeat):**

```bash
mebot gateway
```

**Chat directly via CLI:**

```bash
mebot agent -m "Hello!"
# or interactive mode
mebot agent
```

**Check status:**

```bash
mebot status
mebot channels status
```

## Redis Integration (optional)

Enable Redis in `~/.mebot/config.json`:

```json
{
  "redis": {
    "enabled": true,
    "url": "redis://localhost:6379/0",
    "session": { "enabled": true, "ttlDays": 30 },
    "streams": { "apiKey": "your-secret", "forwardEvents": ["channel_message"] }
  }
}
```

- **Streams bridge:** External services push to `mebot:inbound` stream; Mezon events forwarded to `mezon:events` stream
- **Session storage:** Sessions stored in Redis hashes+lists with configurable TTL (fallback: disk JSONL)
- **Migration:** `mebot session migrate` converts disk sessions to Redis

If `redis.enabled` is `false` or Redis is unreachable, the bot falls back to disk sessions automatically.

## Docker

```bash
docker compose up -d mebot-gateway
```

Config is mounted from `~/.mebot` on the host. Docker Compose includes a Redis service by default.

## Project Structure

```
mebot/
├── agent/          # Agent loop, runtime config, tools, memory
├── bridge/         # External transport adapters (Redis Streams)
├── channels/       # Chat channel integrations + compatibility exports
├── cli/            # Split CLI command modules and entrypoint
├── config/         # Config schema and loader
├── cron/           # Cron job scheduler
├── heartbeat/      # Periodic task runner
├── providers/      # LLM provider adapters
├── session/        # Disk/Redis session management
└── utils/          # Shared helpers and Redis client bootstrap
```

## License

MIT
