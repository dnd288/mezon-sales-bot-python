# Refactor Plan — mezon-sales-bot-python

## Context

Codebase ~8K lines Python, AI sales bot framework with Mezon chat integration, multi-LLM support, Redis streams bridge, session management. Currently on `feat/redis-integration` branch. Architecture is sound but accumulated technical debt: duplicate code, oversized files, misplaced modules, dead abstractions, minor bugs. Goal: clean up without breaking existing behavior or config format.

---

## Phase 1: Quick Wins (bug fixes + dedup)

No architecture changes. Mechanical fixes only.

### 1.1 Remove duplicate `_split_message()`
- **Delete** `_split_message()` in [mezon.py:18-35](mebot/channels/mezon.py#L18-L35)
- **Import** `split_message` from `mebot.utils.helpers` instead
- Update all call sites in mezon.py

### 1.2 Remove duplicate `is_allowed()` logic
- `HandlerManager._is_allowed()` and `MezonChannel.is_allowed()` contain identical logic
- Extract module-level `is_allowed(allow_from, sender_id, clan_id, channel_id)` function
- Both classes call the shared function

### 1.3 Fix WeakValueDictionary consolidation lock bug
- [loop.py:~111](mebot/agent/loop.py) — `_consolidation_locks` uses `weakref.WeakValueDictionary`, locks can be GC'd mid-process
- **Change to** regular `dict[str, asyncio.Lock]` with reference counting
- Add `_lock_refs: dict[str, int]` — increment on acquire, decrement + pop on release to 0 (in `try/finally`)
- Safe vì asyncio là single-threaded, không có race condition khi pop
- Remove `import weakref`

### 1.4 Fix hardcoded Vietnamese error message
- [loop.py:48](mebot/agent/loop.py#L48): replace with `"An error occurred with the LLM provider. Please try again later."`

### 1.5 Fix short ID collision risk
- `uuid4()[:8]` (32-bit) used in both [subagent.py:62](mebot/agent/subagent.py) and [cron/service.py:302](mebot/cron/service.py)
- Create shared `generate_short_id(length=12)` in `mebot/utils/helpers.py`
- Replace both call sites

**Files:** `mebot/channels/mezon.py`, `mebot/agent/loop.py`, `mebot/agent/subagent.py`, `mebot/cron/service.py`, `mebot/utils/helpers.py`
**Verify:** `pytest` passes, `mebot gateway` starts normally

---

## Phase 2: Module Organization (split large files, relocate modules)

### 2.1 Move RedisChannel to `mebot/bridge/`
- Create `mebot/bridge/__init__.py` + `mebot/bridge/redis_streams.py`
- Rename class `RedisChannel` → `RedisStreamsBridge`
- Update internal imports in CLI files
- Backward-compatible re-exports:
  - `mebot/channels/redis_channel.py`: `from mebot.bridge.redis_streams import RedisStreamsBridge as RedisChannel  # deprecated`
  - `mebot/channels/__init__.py`: keep exporting `RedisChannel` as-is

### 2.2 Split `cli/commands.py` (883 lines)

**Import strategy:** shared objects (`app`, `console`, `EXIT_COMMANDS`) live in `cli/__init__.py`. Sub-modules import from there only. `commands.py` is the sole orchestrator that imports sub-modules and registers commands — no reverse imports.

| New file | Content |
|----------|---------|
| `cli/__init__.py` | `app`, `console`, `EXIT_COMMANDS`, Windows UTF-8 fix |
| `cli/helpers.py` | `_make_provider()`, `_load_runtime_config()`, terminal utils, `_print_agent_response()`, `_is_exit_command()` |
| `cli/gateway.py` | `gateway()` command, `_dispatch_outbound`, `run`, cron/heartbeat callbacks |
| `cli/agent_cmd.py` | `agent()` interactive command |
| `cli/onboard.py` | `onboard()` command |
| `cli/status.py` | `status()`, `channels_app`, `channels_status()` |
| `cli/provider_cmd.py` | `provider_app`, `provider_login()`, `_register_login()`, `_LOGIN_HANDLERS`, `_login_openai_codex()`, `_login_github_copilot()` |
| `cli/session_cmd.py` | `session_app`, `session_migrate()` |
| `cli/commands.py` | `version_callback()`, `main()` callback, import + register all sub-commands/sub-apps |

Entry point `pyproject.toml` (`mebot.cli.commands:app`) unchanged.

### 2.3 Remove dead handler pattern
- Delete `BaseMessageHandler`, `HandlerManager`, `DefaultHandler` in [mezon.py:69-164](mebot/channels/mezon.py#L69-L164) (~95 lines)
- Move `is_allowed` check (from 1.2) directly into `_on_message`
- Remove `self.handler_manager` from `MezonChannel.__init__`

**Files:** `mebot/bridge/` (new), `mebot/channels/`, `mebot/cli/` (split), `mebot/channels/mezon.py`
**Verify:** All CLI commands work, `mebot gateway` starts with/without Redis

---

## Phase 3: Constructor Cleanup, Caching, Connection Pooling

### 3.1 Introduce `AgentConfig` dataclass

Internal value object to reduce `AgentLoop.__init__()` from 17 params to 6. Constructed in code from `Config` (Pydantic) — no need for Pydantic validation at this layer.

```python
# mebot/agent/config.py
@dataclass
class AgentConfig:
    workspace: Path
    model: str | None = None
    max_iterations: int = 40
    temperature: float = 0.1
    max_tokens: int = 4096
    memory_window: int = 100
    reasoning_effort: str | None = None
    brave_api_key: str | None = None
    web_proxy: str | None = None
    exec_config: ExecToolConfig = field(default_factory=ExecToolConfig)
    restrict_to_workspace: bool = False
    mcp_servers: dict = field(default_factory=dict)
    tool_result_max_chars: int = 500
```

`AgentLoop.__init__` becomes: `(self, bus, provider, config, session_manager=None, cron_service=None, channels_config=None)`

### 3.2 Make tool result truncation configurable
- Add `tool_result_max_chars: int = 500` to `AgentDefaults` in [schema.py](mebot/config/schema.py)
- Pass through `AgentConfig` → `AgentLoop`
- Remove hardcoded `_TOOL_RESULT_MAX_CHARS` class var

### 3.3 Add Redis connection pooling
- Create `mebot/utils/redis_pool.py`: factory returning pooled sync+async clients
- Use in gateway startup and session commands
- Add pool cleanup in gateway's `finally` block

### 3.4 Fix stale session cache with Redis TTL
- `RedisSessionManager._cache` never expires entries
- Add `_cache_ts: dict[str, float]` tracking `time.monotonic()` per entry
- In `get_or_create()`: if cache entry >5min old, re-fetch from Redis
- No external dependency needed — ~10 lines code

**Files:** new `mebot/agent/config.py`, new `mebot/utils/redis_pool.py`, `mebot/agent/loop.py`, `mebot/session/redis_manager.py`, `mebot/config/schema.py`, CLI files
**Verify:** `pytest`, gateway starts, Redis session create/read/expire works

---

## Phase 4: Logging Cleanup

### 4.1 Standardize logging format
- Replace f-string logging with loguru `{}` lazy format throughout
- Key files: `mezon.py`, `redis_streams.py`, `loop.py`, CLI files
- Convention: `logger.exception()` for unexpected errors, `logger.error()` for handled ones

### 4.2 Reduce typing indicator log spam
- `_typing_loop()` logs debug every 4s per channel
- Change to: log once on start, once on stop/error only

**Files:** multiple (grep for `f"` in logger calls)
**Verify:** Clean log output during gateway run

---

## Phase 5: Documentation Update

### 5.1 Update project docs
- Update `README.md` structure section to reflect `bridge/` module and CLI split
- Update `docs/codebase-summary.md` with current architecture
- Add module docstrings to all `__init__.py` files

### 5.2 Clean up inline imports
- Move type-only imports to `TYPE_CHECKING` blocks where possible
- Keep lazy runtime imports (mezon SDK) with comment explaining why
- CLI lazy imports are intentional (startup speed) — document pattern

**Files:** `README.md`, `docs/`, all `__init__.py` files
**Verify:** Documentation review, no import errors on startup

---

## Dependency Graph

```
Phase 1 (Quick Wins)           ← no deps, merge first
    ↓
Phase 2 (Module Organization)  ← depends on Phase 1
    ↓
Phase 3 (Constructors/Pooling/Caching) ← depends on Phase 2
    ↓ ↘
    ↓  Phase 4 (Logging cleanup) ← can parallel with Phase 3
    ↓ ↙
Phase 5 (Docs)                 ← last, reflects all changes
```

## Intentionally Excluded

- **Metrics/observability**: Feature addition, not refactoring
- **Channel protocol/ABC**: Only 1 channel (Mezon), premature abstraction
- **Provider registry split**: 449 lines but mostly data, well-organized as-is
- **Test coverage expansion**: Important but orthogonal to refactoring
- **cachetools dependency**: Overkill for single bounded-size cache use case

## Verification Plan

After each phase:
1. `pytest` — all existing tests pass
2. `mebot gateway` — starts, connects to Mezon, processes messages
3. `mebot agent` — CLI interactive mode works
4. `mebot status` — shows correct config/status
5. Redis enabled: streams bridge + session storage functional
6. Redis disabled: graceful fallback to disk sessions
