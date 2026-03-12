# Architecture & Codebase Summary

Welcome to the internal documentation for the `mebot` agent framework. This guide provides a high-level overview of the architecture, module layout, and request lifecycle to help contributors navigate the codebase.

## 🏗️ High-Level Architecture

`mebot` acts as a centralized orchestrator, connecting messaging channels (like Mezon) to advanced AI capabilities (powered by LLMs). 

### Execution Modes

The application supports three primary execution profiles:
1. **`mebot gateway`**: The production daemon. It manages persistent WebSocket connections to Mezon, runs the Redis streams bridge, and executes periodic cron/heartbeat services.
2. **`mebot agent`**: A developer-focused CLI mode for interacting directly with the `AgentLoop` bypassing the messaging channels.
3. **Background Systems**: Autonomous cron jobs and subagent flows that execute asynchronously and feed data back into the shared `AgentLoop`.

---

## 📂 Module Layout

The codebase is organized into cleanly separated domains:

### Core Agent Logic
- **`mebot/agent/`**
  - `config.py`: Defines `AgentConfig`, a purely runtime value object constructed from external configuration.
  - `loop.py`: The heart of the bot. Manages the `AgentLoop`, tool execution via `ToolRegistry`, context boundary management, and session locking.
  - `memory.py`: Implements long-term memory extraction and consolidation.
  - `subagent.py`: Handles background task execution for complex, multi-step agent actions.

### Channels & Transports
- **`mebot/channels/`**
  - `mezon.py`: The direct integration with the Mezon WebSocket API. Handles mention filtering, typing indicator lifecycles, and event wrapping.
  - `redis_channel.py`: Provides backward-compatibility re-exports for the Redis bridge.
- **`mebot/bridge/`**
  - `redis_streams.py`: The Redis Streams bridge. Pushes outbound events to `mezon:events` and listens for inbound external triggers on `mebot:inbound`.

### Infrastructure & State
- **`mebot/session/`**
  - `manager.py`: Manages fallback disk-backed JSONL session storage.
  - `redis_manager.py`: Redis-backed distributed sessions with TTL-aware cache refreshing.
- **`mebot/utils/`**
  - `redis_pool.py`: Robust factory managing sync and async Redis connection pooling/cleanup.
  - `helpers.py`: Shared utilities (e.g., message splitting, short-ID generation).
- **`mebot/config/`**
  - System configuration schema and loading logic via Pydantic.

### Command Line Interface (CLI)
- **`mebot/cli/`**
  - `commands.py`: The primary Typer entrypoint and command registry.
  - `helpers.py`: Shared terminal formatting, config loading, and provider initialization.
  - Sub-modules (`gateway.py`, `agent_cmd.py`, `onboard.py`, `status.py`, `provider_cmd.py`, `session_cmd.py`): Isolated implementations for their respective CLI commands.

---

## 🔄 Request Lifecycle (Flow)

Understanding how a message travels through the system is critical for debugging:

1. **Ingestion**: A message arrives via the `MezonChannel` WebSocket or via CLI input.
2. **Filtering**: The channel checks `is_allowed()` (e.g., verifying if the bot was mentioned explicitly).
3. **Dispatch**: The message is converted into an `InboundMessage` and dispatched to the Core event Bus.
4. **Processing**: The `AgentLoop`:
   - Acquires a consolidation lock (with lifecycle reference counting) to prevent race conditions.
   - Loads the conversation history via the Session Manager.
   - Builds the prompt context and calls the configured LLM provider (LiteLLM).
5. **Tool Execution**: If the LLM requests actions, the `ToolRegistry` executes them sequentially and appends results to the context.
6. **Response Emission**: The final textual response is persisted to the session store and emitted onto the Bus as an `OutboundMessage`.
7. **Delivery**: The channel adapter consumes the outbound message and delivers it back to the user via the Mezon API.

---

## ⚠️ Compatibility & Refactoring Notes

Recent architectural refactors have introduced several backward-compatibility layers to preserve downstream code:
- **`RedisChannel` Exports**: `mebot/channels/redis_channel.py` still aliases `RedisStreamsBridge` to `RedisChannel` to prevent import breaks in external integrations.
- **`AgentLoop` Constructor**: The `AgentLoop` accepts both the streamlined `config=AgentConfig(...)` parameter and the legacy keyword-argument constructor to accommodate in-flight test suites during migration. Always prefer `AgentConfig` for new code. 
- **Configurable Tool Truncation**: Tool result maximum characters are now driven dynamically via `AgentConfig.tool_result_max_chars` (defaulting to 500) rather than hardcoded class variables.
