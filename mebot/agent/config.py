"""Agent runtime configuration value object."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mebot.config.schema import Config, ExecToolConfig


def _default_exec_config() -> ExecToolConfig:
    return ExecToolConfig()


@dataclass(slots=True)
class AgentConfig:
    """Resolved runtime settings used by AgentLoop."""

    workspace: Path
    model: str | None = None
    max_iterations: int = 40
    temperature: float = 0.1
    max_tokens: int = 4096
    memory_window: int = 100
    reasoning_effort: str | None = None
    brave_api_key: str | None = None
    web_proxy: str | None = None
    exec_config: ExecToolConfig = field(default_factory=_default_exec_config)
    restrict_to_workspace: bool = False
    mcp_servers: dict[str, Any] = field(default_factory=dict)
    tool_result_max_chars: int = 500

    @classmethod
    def from_app_config(cls, config: Config) -> "AgentConfig":
        """Build agent settings from the top-level application config."""
        defaults = config.agents.defaults
        return cls(
            workspace=config.workspace_path,
            model=defaults.model,
            max_iterations=defaults.max_tool_iterations,
            temperature=defaults.temperature,
            max_tokens=defaults.max_tokens,
            memory_window=defaults.memory_window,
            reasoning_effort=defaults.reasoning_effort,
            brave_api_key=config.tools.web.search.api_key or None,
            web_proxy=config.tools.web.proxy or None,
            exec_config=config.tools.exec.model_copy(deep=True),
            restrict_to_workspace=config.tools.restrict_to_workspace,
            mcp_servers=dict(config.tools.mcp_servers),
            tool_result_max_chars=defaults.tool_result_max_chars,
        )
