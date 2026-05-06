"""Utility functions for mebot."""

import base64
import json
import re
import shutil
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any


def detect_image_mime(data: bytes) -> str | None:
    """Detect image MIME type from magic bytes, ignoring file extension."""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def build_image_content_blocks(
    raw: bytes, mime: str, path: str, label: str
) -> list[dict[str, Any]]:
    """Build native image blocks plus a short text label."""
    b64 = base64.b64encode(raw).decode()
    return [
        {
            "type": "image_url",
            "image_url": {"url": f"data:{mime};base64,{b64}"},
            "_meta": {"path": path},
        },
        {"type": "text", "text": label},
    ]


def ensure_dir(path: Path) -> Path:
    """Ensure directory exists, return it."""
    path.mkdir(parents=True, exist_ok=True)
    return path


def timestamp() -> str:
    """Current ISO timestamp."""
    return datetime.now().isoformat()


_UNSAFE_CHARS = re.compile(r'[<>:"/\\|?*]')

def safe_filename(name: str) -> str:
    """Replace unsafe path characters with underscores."""
    return _UNSAFE_CHARS.sub("_", name).strip()


def split_message(content: str, max_len: int = 2000) -> list[str]:
    """
    Split content into chunks within max_len, preferring line breaks.

    Args:
        content: The text content to split.
        max_len: Maximum length per chunk (default 2000 for Discord compatibility).

    Returns:
        List of message chunks, each within max_len.
    """
    if not content:
        return []
    if len(content) <= max_len:
        return [content]
    chunks: list[str] = []
    while content:
        if len(content) <= max_len:
            chunks.append(content)
            break
        cut = content[:max_len]
        # Try to break at newline first, then space, then hard break
        pos = cut.rfind('\n')
        if pos <= 0:
            pos = cut.rfind(' ')
        if pos <= 0:
            pos = max_len
        chunks.append(content[:pos])
        content = content[pos:].lstrip()
    return chunks


def generate_short_id(length: int = 12) -> str:
    """Generate a short random identifier from a UUID4 hex string."""
    if length <= 0:
        raise ValueError("length must be greater than 0")
    if length > 32:
        raise ValueError("length must be 32 or less")
    return uuid.uuid4().hex[:length]


def sync_workspace_templates(workspace: Path, silent: bool = False) -> list[str]:
    """Sync bundled templates to workspace. Only creates missing files."""
    from importlib.resources import files as pkg_files
    try:
        tpl = pkg_files("mebot") / "templates"
    except Exception:
        return []
    if not tpl.is_dir():
        return []

    added: list[str] = []

    def _write(src, dest: Path):
        if dest.exists():
            return
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(src.read_text(encoding="utf-8") if src else "", encoding="utf-8")
        added.append(str(dest.relative_to(workspace)))

    for item in tpl.iterdir():
        if item.name.endswith(".md"):
            _write(item, workspace / item.name)
    _write(tpl / "memory" / "MEMORY.md", workspace / "memory" / "MEMORY.md")
    _write(None, workspace / "memory" / "HISTORY.md")
    (workspace / "skills").mkdir(exist_ok=True)

    if added and not silent:
        from rich.console import Console
        for name in added:
            Console().print(f"  [dim]Created {name}[/dim]")
    return added


def build_status_content(
    version: str = "",
    model: str = "",
    start_time: float = 0.0,
    last_usage: dict | None = None,
    context_window_tokens: int | None = None,
    session_msg_count: int = 0,
    context_tokens_estimate: int = 0,
    search_usage_text: str = "",
    active_task_count: int = 0,
    max_completion_tokens: int = 8192,
) -> str:
    """Build a status summary string."""
    uptime_s = int(time.time() - start_time) if start_time else 0
    h, rem = divmod(uptime_s, 3600)
    m, s = divmod(rem, 60)
    uptime = f"{h}h {m}m {s}s" if h else f"{m}m {s}s"
    usage = last_usage or {}
    lines = [
        f"mebot v{version}" if version else "mebot",
        f"Model: {model}" if model else "",
        f"Uptime: {uptime}",
        f"Session messages: {session_msg_count}",
        f"Context tokens (est.): {context_tokens_estimate}",
    ]
    if context_window_tokens:
        lines.append(f"Context window: {context_window_tokens}")
    if usage:
        lines.append(f"Last turn — prompt: {usage.get('prompt_tokens', 0)}, completion: {usage.get('completion_tokens', 0)}")
    if active_task_count:
        lines.append(f"Active tasks: {active_task_count}")
    if search_usage_text:
        lines.append(search_usage_text)
    return "\n".join(l for l in lines if l)


# ---------------------------------------------------------------------------
# Functions ported from nanobot helpers for runner/context compatibility
# ---------------------------------------------------------------------------

_TOOL_RESULTS_DIR = ".tool_results"
_TOOL_RESULT_PREVIEW_CHARS = 800
_TOOL_RESULT_RETENTION_SECS = 3600
_TOOL_RESULT_MAX_BUCKETS = 10


def safe_filename(name: str) -> str:
    """Sanitize a string for use as a filename."""
    return re.sub(r"[^a-zA-Z0-9_\-.]", "_", name)[:80]


def truncate_text(text: str, max_chars: int) -> str:
    """Truncate text with a stable suffix."""
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n... (truncated)"


def stringify_text_blocks(content: list[dict[str, Any]]) -> str | None:
    parts: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            return None
        if block.get("type") != "text":
            return None
        text = block.get("text")
        if not isinstance(text, str):
            return None
        parts.append(text)
    return "\n".join(parts)


def find_legal_message_start(messages: list[dict[str, Any]]) -> int:
    """Find the first index whose tool results have matching assistant calls."""
    declared: set[str] = set()
    start = 0
    for i, msg in enumerate(messages):
        role = msg.get("role")
        if role == "assistant":
            for tc in msg.get("tool_calls") or []:
                if isinstance(tc, dict) and tc.get("id"):
                    declared.add(str(tc["id"]))
        elif role == "tool":
            tid = msg.get("tool_call_id")
            if tid and str(tid) not in declared:
                start = i + 1
                declared.clear()
                for prev in messages[start : i + 1]:
                    if prev.get("role") == "assistant":
                        for tc in prev.get("tool_calls") or []:
                            if isinstance(tc, dict) and tc.get("id"):
                                declared.add(str(tc["id"]))
    return start


def build_assistant_message(
    content: str | None,
    tool_calls: list[dict[str, Any]] | None = None,
    reasoning_content: str | None = None,
    thinking_blocks: list[dict] | None = None,
) -> dict[str, Any]:
    """Build a provider-safe assistant message with optional reasoning fields."""
    msg: dict[str, Any] = {"role": "assistant", "content": content or ""}
    if tool_calls:
        msg["tool_calls"] = tool_calls
    if reasoning_content is not None or thinking_blocks:
        msg["reasoning_content"] = reasoning_content if reasoning_content is not None else ""
    if thinking_blocks:
        msg["thinking_blocks"] = thinking_blocks
    return msg


def estimate_message_tokens(message: dict[str, Any]) -> int:
    """Estimate prompt tokens contributed by one persisted message."""
    content = message.get("content")
    parts: list[str] = []
    if isinstance(content, str):
        parts.append(content)
    elif isinstance(content, list):
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                text = part.get("text", "")
                if text:
                    parts.append(text)
            else:
                parts.append(json.dumps(part, ensure_ascii=False))
    elif content is not None:
        parts.append(json.dumps(content, ensure_ascii=False))
    for key in ("name", "tool_call_id"):
        value = message.get(key)
        if isinstance(value, str) and value:
            parts.append(value)
    if message.get("tool_calls"):
        parts.append(json.dumps(message["tool_calls"], ensure_ascii=False))
    rc = message.get("reasoning_content")
    if isinstance(rc, str) and rc:
        parts.append(rc)
    payload = "\n".join(parts)
    if not payload:
        return 4
    try:
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")
        return max(4, len(enc.encode(payload)) + 4)
    except Exception:
        return max(4, len(payload) // 4 + 4)


def estimate_prompt_tokens_chain(
    provider: Any,
    model: str | None,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
) -> tuple[int, str]:
    """Estimate prompt tokens via provider counter first, then fallback."""
    provider_counter = getattr(provider, "estimate_prompt_tokens", None)
    if callable(provider_counter):
        try:
            tokens, source = provider_counter(messages, tools, model)
            if isinstance(tokens, (int, float)) and tokens > 0:
                return int(tokens), str(source or "provider_counter")
        except Exception:
            pass
    # Fallback: char heuristic
    total = sum(estimate_message_tokens(m) for m in messages)
    return total, "estimate"


def _write_text_atomic(path: Path, content: str) -> None:
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_text(content, encoding="utf-8")
        tmp.replace(path)
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)


def _bucket_mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _cleanup_tool_result_buckets(root: Path, current_bucket: Path) -> None:
    siblings = [p for p in root.iterdir() if p.is_dir() and p != current_bucket]
    cutoff = time.time() - _TOOL_RESULT_RETENTION_SECS
    for p in siblings:
        if _bucket_mtime(p) < cutoff:
            shutil.rmtree(p, ignore_errors=True)
    keep = max(_TOOL_RESULT_MAX_BUCKETS - 1, 0)
    siblings = [p for p in siblings if p.exists()]
    if len(siblings) <= keep:
        return
    siblings.sort(key=_bucket_mtime, reverse=True)
    for p in siblings[keep:]:
        shutil.rmtree(p, ignore_errors=True)


def maybe_persist_tool_result(
    workspace: "Path | None",
    session_key: "str | None",
    tool_call_id: str,
    content: Any,
    *,
    max_chars: int,
) -> Any:
    """Persist oversized tool output and replace it with a stable reference string."""
    if workspace is None or max_chars <= 0:
        return content
    text_payload: str | None = None
    suffix = "txt"
    if isinstance(content, str):
        text_payload = content
    elif isinstance(content, list):
        text_payload = stringify_text_blocks(content)
        if text_payload is None:
            return content
        suffix = "json"
    else:
        return content
    if len(text_payload) <= max_chars:
        return content
    from mebot.utils.helpers import ensure_dir
    root = ensure_dir(workspace / _TOOL_RESULTS_DIR)
    bucket = ensure_dir(root / safe_filename(session_key or "default"))
    try:
        _cleanup_tool_result_buckets(root, bucket)
    except Exception:
        pass
    path = bucket / f"{safe_filename(tool_call_id)}.{suffix}"
    if not path.exists():
        if suffix == "json" and isinstance(content, list):
            _write_text_atomic(path, json.dumps(content, ensure_ascii=False, indent=2))
        else:
            _write_text_atomic(path, text_payload)
    preview = text_payload[:_TOOL_RESULT_PREVIEW_CHARS]
    result = (
        f"[tool output persisted]\n"
        f"Full output saved to: {path}\n"
        f"Original size: {len(text_payload)} chars\n"
        f"Preview:\n{preview}"
    )
    if len(text_payload) > _TOOL_RESULT_PREVIEW_CHARS:
        result += "\n...\n(Read the saved file if you need the full output.)"
    return result

