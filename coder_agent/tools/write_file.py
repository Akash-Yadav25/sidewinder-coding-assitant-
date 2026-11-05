"""Implementation of the write_file tool."""

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
    """Create or update a file, creating parent directories and prompting for approval when required."""
    file_path = input_args.get("path")
    content = input_args.get("content")

    if not file_path:
        return ToolResult(tool_use_id="", content="Error: 'path' parameter is required", is_error=True)
    if content is None:
        return ToolResult(tool_use_id="", content="Error: 'content' parameter is required", is_error=True)

    try:
        path = safety.validate_path(file_path, project_dir)
    except ValueError as e:
        return ToolResult(tool_use_id="", content=str(e), is_error=True)

    existing_content: str | None = None
    if path.exists() and path.is_file():
        try:
            existing_content = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            existing_content = ""

    # Approval check
    approved = safety.approve_file_write(path, content, existing_content, ui)
    if not approved:
        return ToolResult(
            tool_use_id="",
            content=f"Operation cancelled: User denied permission to write to '{file_path}'",
            is_error=True,
        )

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

        lines_count = len(content.splitlines())
        bytes_count = len(content.encode("utf-8"))
        action = "Updated existing file" if existing_content is not None else "Created new file"

        return ToolResult(
            tool_use_id="",
            content=f"Success: {action} '{file_path}' ({lines_count} lines, {bytes_count} bytes written)",
        )
    except Exception as e:
        return ToolResult(tool_use_id="", content=f"Error writing to '{file_path}': {e}", is_error=True)
