"""Prompt template rendering for mebot."""

from __future__ import annotations

from typing import Any


def render_template(name: str, *, strip: bool = False, **kwargs: Any) -> str:
    """Render a named template. Falls back to simple string formatting."""
    # Handle known templates with inline implementations
    if name == "agent/max_iterations_message.md":
        max_iterations = kwargs.get("max_iterations", 40)
        text = (
            f"I reached the maximum number of tool call iterations ({max_iterations}) "
            "without completing the task. You can try breaking the task into smaller steps."
        )
        return text.rstrip() if strip else text

    if name == "agent/skills_section.md":
        skills_summary = kwargs.get("skills_summary", "")
        text = (
            "# Skills\n\n"
            "The following skills extend your capabilities. To use a skill, read its SKILL.md file using the read_file tool.\n"
            "Skills with available=\"false\" need dependencies installed first - you can try installing them with apt/brew.\n\n"
            f"{skills_summary}"
        )
        return text.rstrip() if strip else text

    # Generic fallback: return empty string for unknown templates
    return ""
