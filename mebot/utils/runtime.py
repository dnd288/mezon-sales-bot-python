"""Runtime-specific helper functions and constants."""

from __future__ import annotations

from typing import Any

from loguru import logger

from mebot.utils.helpers import stringify_text_blocks

_MAX_REPEAT_EXTERNAL_LOOKUPS = 2

EMPTY_FINAL_RESPONSE_MESSAGE = (
    "I completed the tool steps but couldn't produce a final answer. "
    "Please try again or narrow the task."
)

FINALIZATION_RETRY_PROMPT = (
    "Please provide your response to the user based on the conversation above."
)

LENGTH_RECOVERY_PROMPT = (
    "Output limit reached. Continue exactly where you left off "
    "— no recap, no apology. Break remaining work into smaller steps if needed."
)


def ensure_nonempty_tool_result(tool_name: str, content: Any) -> Any:
    """Replace semantically empty tool results with a short marker string."""
    marker = f"({tool_name} completed with no output)"
    if content is None:
        return marker
    if isinstance(content, str) and not content.strip():
        return marker
    if isinstance(content, list):
        if not content:
            return marker
        text_payload = stringify_text_blocks(content)
        if text_payload is not None and not text_payload.strip():
            return marker
    return content


def is_blank_text(content: str | None) -> bool:
    """True when *content* is missing or only whitespace."""
    return content is None or not content.strip()


def build_finalization_retry_message() -> dict[str, str]:
    return {"role": "user", "content": FINALIZATION_RETRY_PROMPT}


def build_length_recovery_message() -> dict[str, str]:
    return {"role": "user", "content": LENGTH_RECOVERY_PROMPT}


def repeated_external_lookup_error(
    tool_name: str,
    arguments: dict[str, Any],
    seen_counts: dict[str, int],
) -> str | None:
    """Block repeated external lookups after a small retry budget."""
    signature = None
    if tool_name == "web_fetch":
        url = str(arguments.get("url") or "").strip()
        if url:
            signature = f"web_fetch:{url.lower()}"
    elif tool_name == "web_search":
        query = str(arguments.get("query") or arguments.get("search_term") or "").strip()
        if query:
            signature = f"web_search:{query.lower()}"
    if signature is None:
        return None
    count = seen_counts.get(signature, 0) + 1
    seen_counts[signature] = count
    if count <= _MAX_REPEAT_EXTERNAL_LOOKUPS:
        return None
    logger.warning("Blocking repeated external lookup {} on attempt {}", signature[:160], count)
    return (
        "Error: repeated external lookup blocked. "
        "Use the results you already have to answer, or try a meaningfully different source."
    )
