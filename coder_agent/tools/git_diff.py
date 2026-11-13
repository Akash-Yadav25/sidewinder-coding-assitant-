"""Implementation of the git_diff tool for inspecting repository changes."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from coder_agent.git import GitManager
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
    """Inspect git diff of uncommitted changes in the repository."""
    git = GitManager(project_dir)
    if not git.is_git_repo():
        return ToolResult(
            tool_use_id="",
            content="Error: Workspace is not a git repository.",
            is_error=True,
        )

    file_path = input_args.get("path")
    staged = bool(input_args.get("staged", False))

    if file_path:
        try:
            safety.validate_path(file_path, project_dir)
        except ValueError as e:
            return ToolResult(tool_use_id="", content=str(e), is_error=True)

    try:
        diff_output = git.get_diff(file_path=file_path, staged=staged)
        if not diff_output.strip():
            status = git.get_status()
            if not status.strip():
                return ToolResult(tool_use_id="", content="Working tree is clean. No changes detected.")
            return ToolResult(
                tool_use_id="",
                content=f"No diff for tracked files, but untracked files exist:\n{status}",
            )

        # Truncate if diff is huge (> 15KB)
        if len(diff_output.encode("utf-8")) > 15360:
            diff_output = diff_output[:15000] + "\n... [Diff truncated after 15KB] ..."

        return ToolResult(tool_use_id="", content=diff_output)
    except Exception as e:
        return ToolResult(tool_use_id="", content=f"Error running git diff: {e}", is_error=True)
