# Codebase Summary

## Overview

`mebot` is an AI assistant/bot runtime with three main execution modes:

- `mebot gateway`: runs the Mezon channel, cron service, heartbeat service, and optional Redis bridge
- `mebot agent`: runs the same agent loop in direct CLI mode
- background/system execution: cron and subagent flows feed work back into the shared `AgentLoop`

## Main modules

- `mebot/agent/`
  - `config.py`: runtime `AgentConfig` value object
  - `loop.py`: core orchestration loop, tool execution, session persistence, consolidation
  - `memory.py`: long-term memory consolidation
  - `subagent.py`: background task execution
- `mebot/channels/`
  - `mezon.py`: Mezon WebSocket channel, mention filtering, typing indicator lifecycle
  - `redis_channel.py`: compatibility re-export for the moved Redis bridge
- `mebot/bridge/`
  - `redis_streams.py`: Redis Streams bridge for inbound triggers and outbound Mezon event forwarding
- `mebot/cli/`
  - `commands.py`: CLI entrypoint and Typer registration
  - `gateway.py`, `agent_cmd.py`, `onboard.py`, `status.py`, `provider_cmd.py`, `session_cmd.py`: command implementations
  - `helpers.py`: shared terminal/config/provider helpers
- `mebot/session/`
  - `manager.py`: disk-backed JSONL sessions
  - `redis_manager.py`: Redis-backed sessions with TTL-aware cache refresh
- `mebot/utils/`
  - `helpers.py`: generic helpers like message splitting and short-id generation
  - `redis_pool.py`: sync/async Redis client factory and cleanup

## Flow

1. A channel or CLI command produces an `InboundMessage`.
2. `AgentLoop` loads the session, builds prompt context, and calls the provider.
3. Tool calls are executed through `ToolRegistry`.
4. The final response is persisted to the session store and emitted as `OutboundMessage`.
5. Channels/CLI consume outbound messages and deliver them to the user.

## Compatibility notes

- `mebot/channels/redis_channel.py` still exports `RedisChannel` so older imports continue to work.
- `AgentLoop` accepts both the newer `AgentConfig` path and the older keyword-based constructor for compatibility during the transition.
