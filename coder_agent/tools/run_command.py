"""Implementation of the run_command tool."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Any

from coder_agent.types import ToolResult

if TYPE_CHECKING:
    from coder_agent.config import Config
    from coder_agent.safety import SafetyGuard
    from coder_agent.ui import UI

MAX_OUTPUT_BYTES = 15360  # 15KB


def execute(
    input_args: dict[str, Any],
    project_dir: str,
    safety: SafetyGuard,
    ui: UI,
    config: Config,
) -> ToolResult:
    """Execute a shell command in project directory with approval check and timeout."""
    command = input_args.get("command")
    if not command:
        return ToolResult(tool_use_id="", content="Error: 'command' parameter is required", is_error=True)

    try:
        safety.validate_command(command)
    except ValueError as e:
        return ToolResult(tool_use_id="", content=str(e), is_error=True)

    timeout = input_args.get("timeout") or 60
    if not isinstance(timeout, (int, float)) or timeout <= 0:
        timeout = 60

    # User approval prompt
    if not safety.approve_command(command, ui):
        return ToolResult(
            tool_use_id="",
            content=f"Operation cancelled: User denied permission to execute command: '{command}'",
            is_error=True,
        )

    work_dir = Path(project_dir).resolve()

    try:
        proc = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(work_dir),
        )

        stdout = proc.stdout or ""
        stderr = proc.stderr or ""
        combined = stdout
        if stderr:
            if combined:
                combined += "\n--- STDERR ---\n"
            combined += stderr

        # Limit output length if exceeded
        if len(combined.encode("utf-8")) > MAX_OUTPUT_BYTES:
            combined = combined[:MAX_OUTPUT_BYTES] + "\n... [Output truncated after 15KB] ..."

        status_msg = f"[Process completed with exit code {proc.returncode}]\n\n"
        result_content = status_msg + (combined if combined else "(No output produced)")

        return ToolResult(
            tool_use_id="",
            content=result_content,
            is_error=(proc.returncode != 0),
        )

    except subprocess.TimeoutExpired:
        return ToolResult(
            tool_use_id="",
            content=f"Error: Command timed out after {timeout} seconds.",
            is_error=True,
        )
    except Exception as e:
        return ToolResult(
            tool_use_id="",
            content=f"Error executing command: {e}",
            is_error=True,
        )
