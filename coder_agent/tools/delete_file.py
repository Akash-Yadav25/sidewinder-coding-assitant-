"""Implementation of the delete_file tool."""

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
    """Delete a file from the workspace after confirmation."""
    file_path = input_args.get("path")
    if not file_path:
        return ToolResult(tool_use_id="", content="Error: 'path' parameter is required", is_error=True)

    try:
        path = safety.validate_path(file_path, project_dir)
    except ValueError as e:
        return ToolResult(tool_use_id="", content=str(e), is_error=True)

    if not path.exists():
        return ToolResult(tool_use_id="", content=f"Error: Path does not exist: '{file_path}'", is_error=True)

    approved = safety.approve_file_deletion(path, ui)
    if not approved:
        return ToolResult(
            tool_use_id="",
            content=f"Operation cancelled: User denied permission to delete '{file_path}'",
            is_error=True,
        )

    try:
        if path.is_file():
            path.unlink()
        elif path.is_dir():
            path.rmdir()
        return ToolResult(tool_use_id="", content=f"Success: Deleted '{file_path}'")
    except Exception as e:
        return ToolResult(tool_use_id="", content=f"Error deleting '{file_path}': {e}", is_error=True)
