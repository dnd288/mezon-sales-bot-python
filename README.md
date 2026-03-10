# mezon-sales-bot-python

AI sales bot for the [Mezon](https://mezon.ai) platform, built on the `mebot` agent framework. Connects to Mezon via WebSocket (no public IP required) and handles customer inquiries using an LLM backend.

## Features

- Mezon channel integration via `mezon-sdk` with auto-reconnect
- Extensible handler-based architecture for routing commands
- LLM support via LiteLLM (OpenRouter, Anthropic, OpenAI, DeepSeek, etc.)
- Cron scheduling and heartbeat service
- MCP (Model Context Protocol) tool support
- CLI for direct agent interaction and gateway server mode

## Requirements

- Python 3.11+
- A Mezon bot account (`client_id` + `token`)
- An LLM API key (e.g. OpenRouter, Anthropic)

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

## Docker

```bash
docker compose up -d mebot-gateway
```

Config is mounted from `~/.mebot` on the host.

## Project Structure

```
mebot/
├── agent/          # Agent loop, tools, memory
├── channels/       # Mezon channel integration
├── cli/            # CLI commands
├── config/         # Config schema and loader
├── cron/           # Cron job scheduler
├── heartbeat/      # Periodic task runner
├── providers/      # LLM provider adapters
└── session/        # Session management
```

## License

MIT
