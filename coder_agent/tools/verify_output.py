"""Run a command and assert its output matches expected behavior."""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

from coder_agent.types import ToolResult

if TYPE_CHECKING:
    from coder_agent.config import Config
    from coder_agent.safety import SafetyGuard
    from coder_agent.ui import UI


def execute(
    input_args: dict,
    project_dir: str,
    safety: SafetyGuard,
    ui: UI,
    config: Config,
) -> ToolResult:
    """Run a shell command and assert stdout/stderr and exit code match expectations."""
    command = input_args.get("command", "")
    if not command:
        return ToolResult(tool_use_id="", content="Error: 'command' is required.", is_error=True)

    expected_contains = input_args.get("expected_output_contains", "")
    expected_excludes = input_args.get("expected_output_excludes", "")
    expected_exit_code = int(input_args.get("expected_exit_code", 0))
    timeout = int(input_args.get("timeout", 30))

    # Safety guard: validate and optionally prompt before executing
    try:
        safety.validate_command(command)
    except ValueError as e:
        return ToolResult(tool_use_id="", content=str(e), is_error=True)

    if not safety.approve_command(command, ui):
        return ToolResult(
            tool_use_id="",
            content=f"Operation cancelled: User denied permission to run verify command: '{command}'",
            is_error=True,
        )

    try:
        proc = subprocess.run(
            command,
            shell=True,
            cwd=project_dir,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        actual_output = (proc.stdout + proc.stderr).strip()
        actual_exit = proc.returncode

        failures = []
        if actual_exit != expected_exit_code:
            failures.append(f"Exit code: expected {expected_exit_code}, got {actual_exit}")
        if expected_contains and expected_contains not in actual_output:
            failures.append(f"Expected output to contain: {expected_contains!r}")
        if expected_excludes and expected_excludes in actual_output:
            failures.append(f"Expected output NOT to contain: {expected_excludes!r}")

        if not failures:
            preview = f"\nOutput:\n{actual_output[:800]}" if actual_output else ""
            return ToolResult(
                tool_use_id="",
                content=f"✅ PASS\nCommand: {command}{preview}",
                is_error=False,
            )
        else:
            return ToolResult(
                tool_use_id="",
                content=(
                    f"❌ FAIL\n"
                    f"Command: {command}\n"
                    f"Failures:\n"
                    + "\n".join(f"  - {f}" for f in failures)
                    + f"\nActual output:\n{actual_output[:800]}"
                ),
                is_error=True,
            )
    except subprocess.TimeoutExpired:
        return ToolResult(
            tool_use_id="",
            content=f"❌ FAIL\nCommand timed out after {timeout}s: {command}",
            is_error=True,
        )
    except Exception as e:
        return ToolResult(
            tool_use_id="",
            content=f"Error running verify_output: {e}",
            is_error=True,
        )
