# 🤖 Mezon Sales Bot (Python)

[![Python 3.13+](https://img.shields.io/badge/python-3.13+-blue.svg)](https://www.python.org/downloads/release/python-3130/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

A powerful, extensible AI sales bot and agent framework designed specifically for the [Mezon](https://mezon.ai) platform. Built on the custom `mebot` framework, it connects securely via WebSocket (no public IP required) and handles customer inquiries autonomously using state-of-the-art LLMs.

---

## ✨ Key Features

- **Seamless Mezon Integration**: Uses `mezon-sdk` for reliable WebSocket connections, auto-reconnects, typing indicators, and mention-only filtering.
- **Multi-LLM Support**: Powered by LiteLLM. Easily switch between OpenAI, Anthropic (Claude), DeepSeek, and OpenRouter with simple configuration.
- **Agentic Capabilities**: Supports MCP (Model Context Protocol) tools, long-term memory consolidation, and autonomous subagent background tasks.
- **Redis Streams Bridge (Optional)**: Connect your bot to external no-code platforms (like n8n) or webhooks using Redis Streams.
- **Robust Session Management**: TTL-aware session storage backed by Redis, with seamless fallback to local disk (JSONL) if Redis is unavailable.
- **Cron & Heartbeat**: Built-in task runner and cron scheduler for proactive engagement.
- **Versatile CLI**: A developer-friendly command-line interface for direct agent testing, gateway execution, and status monitoring.

## 📋 Prerequisites

To run this project, you will need:
- **Python 3.13** or higher
- A **Mezon Bot Account** (`client_id` and `token`)
- An **LLM API Key** (e.g., from OpenRouter, OpenAI, or Anthropic)
- *(Optional)* **Redis 7+** (for advanced session storage and the Streams bridge)

## 🚀 Quick Start

### 1. Installation

Clone the repository and install the package in editable mode:

```bash
git clone https://github.com/your-org/mezon-sales-bot-python.git
cd mezon-sales-bot-python
pip install -e .
```

### 2. Configuration Initialization

Run the onboarding command to generate the default configuration structure into `~/.mebot/config.json`:

```bash
mebot onboard
```

### 3. Setup Credentials

Edit `~/.mebot/config.json` to include your Mezon and LLM credentials:

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
      "model": "anthropic/claude-3-5-sonnet",
      "tool_result_max_chars": 500
    }
  }
}
```

### 4. Running the Bot

**Start the Gateway Server:**
Runs the Mezon channel integration, cron jobs, and heartbeat service.
```bash
mebot gateway
```

**Test the Agent locally (CLI Chat):**
Chat directly with your configured agent without connecting to Mezon.
```bash
mebot agent -m "Hello!"
# Or launch interactive mode:
mebot agent
```

**Check System Status:**
```bash
mebot status
mebot channels status
```

## 📦 Advanced: Redis Integration

Redis unlocks advanced features for scaling and external integrations. Enable it in your `~/.mebot/config.json`:

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
- **Session Storage**: Automatically migrates chats to Redis hashes/lists. Expired sessions are cleaned up based on TTL. 
- **Migration**: Run `mebot session migrate` to move disk sessions to Redis.
- **Streams Bridge**: Consume external events by pushing to the `mebot:inbound` stream, and forward Mezon events outward to the `mezon:events` stream.

## 🐳 Docker Deployment

A production-ready `docker-compose.yml` is included. It mounts your `~/.mebot` configuration directory and spins up Redis alongside the gateway.

```bash
docker compose up -d mebot-gateway
```

## 🏗️ Architecture & Contributing

For a detailed breakdown of the internal architecture, module layout, and request lifecycle, please read the [Codebase Summary & Architecture Guide](docs/codebase-summary.md).

## 📄 License

This project is licensed under the [MIT License](LICENSE).
