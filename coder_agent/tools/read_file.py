"""Implementation of the read_file tool."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from coder_agent.types import ToolResult

if TYPE_CHECKING:
    from coder_agent.config import Config
    from coder_agent.safety import SafetyGuard
    from coder_agent.ui import UI


def execute(
    input_args: dict[str, Any],
    project_dir: str,
    safety: SafetyGuard,
    ui: UI,
    config: Config,
) -> ToolResult:
    """Read file content with line numbers and optional range filtering."""
    file_path = input_args.get("path")
    if not file_path:
        return ToolResult(tool_use_id="", content="Error: 'path' parameter is required", is_error=True)

    try:
        path = safety.validate_path(file_path, project_dir)
    except ValueError as e:
        return ToolResult(tool_use_id="", content=str(e), is_error=True)

    if not path.exists():
        return ToolResult(tool_use_id="", content=f"Error: File not found: '{file_path}'", is_error=True)

    if not path.is_file():
        return ToolResult(tool_use_id="", content=f"Error: Path is not a regular file: '{file_path}'", is_error=True)

    try:
        file_size = path.stat().st_size
        if file_size > config.max_file_size:
            return ToolResult(
                tool_use_id="",
                content=(
                    f"Error: File size ({file_size} bytes) exceeds configured limit "
                    f"({config.max_file_size} bytes). Use start_line and end_line to inspect chunks."
                ),
                is_error=True,
            )

        content = path.read_text(encoding="utf-8", errors="replace")
        lines = content.splitlines()
        total_lines = len(lines)

        start_line = input_args.get("start_line")
        end_line = input_args.get("end_line")

        start_idx = max(0, (start_line - 1) if isinstance(start_line, int) else 0)
        end_idx = min(total_lines, end_line if isinstance(end_line, int) else total_lines)

        if start_idx >= total_lines and total_lines > 0:
            return ToolResult(
                tool_use_id="",
                content=f"Error: start_line {start_line} is beyond total file lines ({total_lines})",
                is_error=True,
            )

        sliced = lines[start_idx:end_idx]
        numbered_lines = [f"{i + start_idx + 1:5d} | {line}" for i, line in enumerate(sliced)]

        header = f"[{file_path}] (lines {start_idx + 1}-{end_idx} of {total_lines})\n"
        return ToolResult(tool_use_id="", content=header + "\n".join(numbered_lines))

    except Exception as e:
        return ToolResult(tool_use_id="", content=f"Error reading file '{file_path}': {e}", is_error=True)
