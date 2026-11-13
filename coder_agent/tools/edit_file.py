"""Implementation of the edit_file tool for targeted search-and-replace."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from coder_agent.types import ToolResult

if TYPE_CHECKING:
    from coder_agent.config import Config
    from coder_agent.safety import SafetyGuard
    from coder_agent.ui import UI


def _find_line_numbers_of_occurrences(content: str, target: str) -> list[int]:
    """Return 1-based line numbers where target occurs in content."""
    lines = content.splitlines(keepends=True)
    matched_lines: list[int] = []
    accumulated_pos = 0

    while True:
        idx = content.find(target, accumulated_pos)
        if idx == -1:
            break
        # Count lines up to idx
        line_num = content[:idx].count("\n") + 1
        matched_lines.append(line_num)
        accumulated_pos = idx + len(target)

    return matched_lines


def _fuzzy_replace(content: str, old_text: str, new_text: str) -> str | None:
    """Attempt fuzzy replacement by normalizing whitespace line-by-line."""
    old_lines = [line.rstrip() for line in old_text.splitlines()]
    if not old_lines:
        return None

    content_lines = content.splitlines(keepends=True)
    content_lines_stripped = [line.rstrip() for line in content_lines]

    target_len = len(old_lines)
    candidates: list[int] = []

    for i in range(len(content_lines_stripped) - target_len + 1):
        if content_lines_stripped[i : i + target_len] == old_lines:
            candidates.append(i)

    if len(candidates) == 1:
        start_idx = candidates[0]
        # Preserve trailing newline style from the target region
        end_idx = start_idx + target_len
        prefix = "".join(content_lines[:start_idx])
        suffix = "".join(content_lines[end_idx:])
        # Ensure replacement text ends with appropriate newline if replaced chunk did
        new_text_normalized = new_text
        if content_lines[end_idx - 1].endswith("\n") and not new_text_normalized.endswith("\n"):
            new_text_normalized += "\n"
        return prefix + new_text_normalized + suffix

    return None


def execute(
    input_args: dict[str, Any],
    project_dir: str,
    safety: SafetyGuard,
    ui: UI,
    config: Config,
) -> ToolResult:
    """Perform targeted replacement of old_text with new_text in an existing file."""
    file_path = input_args.get("path")
    old_text = input_args.get("old_text")
    new_text = input_args.get("new_text")

    if not file_path:
        return ToolResult(tool_use_id="", content="Error: 'path' parameter is required", is_error=True)
    if old_text is None:
        return ToolResult(tool_use_id="", content="Error: 'old_text' parameter is required", is_error=True)
    if new_text is None:
        return ToolResult(tool_use_id="", content="Error: 'new_text' parameter is required", is_error=True)

    try:
        path = safety.validate_path(file_path, project_dir)
    except ValueError as e:
        return ToolResult(tool_use_id="", content=str(e), is_error=True)

    if not path.exists() or not path.is_file():
        return ToolResult(
            tool_use_id="",
            content=f"Error: File '{file_path}' does not exist or is not a regular file.",
            is_error=True,
        )

    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return ToolResult(tool_use_id="", content=f"Error reading '{file_path}': {e}", is_error=True)

    # 1. Exact match check
    count = content.count(old_text)
    new_content: str | None = None

    if count == 1:
        new_content = content.replace(old_text, new_text, 1)
    elif count > 1:
        line_numbers = _find_line_numbers_of_occurrences(content, old_text)
        lines_str = ", ".join(f"line {ln}" for ln in line_numbers[:10])
        return ToolResult(
            tool_use_id="",
            content=(
                f"Error: 'old_text' matches {count} occurrences in '{file_path}' ({lines_str}). "
                "Please provide more surrounding context lines in 'old_text' to make the match unique."
            ),
            is_error=True,
        )
    else:
        # 2. Fuzzy match fallback
        new_content = _fuzzy_replace(content, old_text, new_text)
        if new_content is None:
            return ToolResult(
                tool_use_id="",
                content=(
                    f"Error: 'old_text' was not found in '{file_path}'. "
                    "Make sure you use `read_file` first to verify the exact current file contents."
                ),
                is_error=True,
            )

    # Approval check
    approved = safety.approve_file_write(path, new_content, content, ui)
    if not approved:
        return ToolResult(
            tool_use_id="",
            content=f"Operation cancelled: User denied permission to edit '{file_path}'",
            is_error=True,
        )

    try:
        path.write_text(new_content, encoding="utf-8")
        diff_count = len(new_content.splitlines()) - len(content.splitlines())
        delta_str = f"+{diff_count}" if diff_count >= 0 else str(diff_count)

        return ToolResult(
            tool_use_id="",
            content=f"Success: Successfully edited '{file_path}' (lines delta: {delta_str})",
        )
    except Exception as e:
        return ToolResult(tool_use_id="", content=f"Error writing to '{file_path}': {e}", is_error=True)
