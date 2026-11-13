"""Targeted test runner and error diagnostician tool."""

from __future__ import annotations

import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

from coder_agent.types import ToolResult

if TYPE_CHECKING:
    from coder_agent.config import Config
    from coder_agent.safety import SafetyGuard
    from coder_agent.ui import UI


def _detect_test_command(project_dir: Path, targets: list[str] | None = None) -> list[str]:
    """Determine the optimal test command based on workspace markers."""
    targets = targets or []

    # 1. Python projects
    if (project_dir / "pytest.ini").is_file() or (project_dir / "tests").is_dir() or any(project_dir.glob("test_*.py")):
        # Check if pytest is available in Python environment
        pytest_cmd = [sys.executable, "-m", "pytest", "-q"]
        if targets:
            pytest_cmd.extend(targets)
        return pytest_cmd

    # 2. Node.js projects
    if (project_dir / "package.json").is_file():
        npm_cmd = ["npm", "test"]
        if targets:
            npm_cmd.extend(["--"] + targets)
        return npm_cmd

    # 3. Cargo / Rust
    if (project_dir / "Cargo.toml").is_file():
        cargo_cmd = ["cargo", "test"]
        if targets:
            cargo_cmd.extend(targets)
        return cargo_cmd

    # 4. Go
    if (project_dir / "go.mod").is_file():
        go_cmd = ["go", "test"]
        if targets:
            go_cmd.extend(targets)
        else:
            go_cmd.append("./...")
        return go_cmd

    return [sys.executable, "-m", "unittest"]


def _format_diagnostics(stdout: str, stderr: str, returncode: int) -> str:
    """Extract and format failing tests and tracebacks cleanly."""
    combined = (stdout + "\n" + stderr).strip()

    if returncode == 0:
        # Find summary line (e.g. "5 passed in 0.12s")
        summary_match = re.search(r"(\d+\s+passed.*)", combined)
        summary = summary_match.group(1) if summary_match else "All tests passed successfully."
        return f"✅ Tests Succeeded:\n{summary}"

    # Extract failures from pytest or standard tracebacks
    failures: list[str] = []

    # Look for FAILURES / ERRORS sections in pytest
    if "FAILURES" in combined:
        parts = combined.split("FAILURES")[-1]
        # Look for short test summary info
        summary_section = parts.split("short test summary info")[-1] if "short test summary info" in parts else parts
        failures.append(summary_section.strip())
    else:
        # Generic error traceback
        lines = combined.splitlines()
        # Keep last 35 lines containing failure details
        tail_lines = lines[-35:] if len(lines) > 35 else lines
        failures.append("\n".join(tail_lines))

    diagnostic_msg = (
        f"❌ Tests Failed (exit code {returncode}):\n\n"
        + "\n".join(failures)
    )

    # Cap output at 8KB
    if len(diagnostic_msg) > 8192:
        diagnostic_msg = diagnostic_msg[:8000] + "\n... [Diagnostics truncated for brevity] ..."

    return diagnostic_msg


def execute(
    input_args: dict[str, Any],
    project_dir: str,
    safety: SafetyGuard,
    ui: UI,
    config: Config,
) -> ToolResult:
    """Execute targeted test suite and return structured failure diagnostics."""
    targets_arg = input_args.get("targets")
    targets: list[str] = []
    if isinstance(targets_arg, list):
        targets = [str(t) for t in targets_arg]
    elif isinstance(targets_arg, str) and targets_arg.strip():
        targets = targets_arg.strip().split()

    work_dir = Path(project_dir).resolve()

    # Validate targets to prevent path traversal
    for target in targets:
        if not target.startswith("-"):
            try:
                safety.validate_path(target)
            except ValueError as e:
                return ToolResult(tool_use_id="", content=str(e), is_error=True)

    cmd_parts = _detect_test_command(work_dir, targets)
    cmd_str = " ".join(shlex.quote(p) for p in cmd_parts)

    # Validate generated command against safety blocklist
    try:
        safety.validate_command(cmd_str)
    except ValueError as e:
        return ToolResult(tool_use_id="", content=str(e), is_error=True)

    # User approval prompt
    if not safety.approve_command(cmd_str, ui):
        return ToolResult(
            tool_use_id="",
            content=f"Operation cancelled: User denied permission to execute test command: '{cmd_str}'",
            is_error=True,
        )

    timeout = input_args.get("timeout") or 90
    if not isinstance(timeout, (int, float)) or timeout <= 0:
        timeout = 90

    try:
        proc = subprocess.run(
            cmd_parts,
            cwd=str(work_dir),
            capture_output=True,
            text=True,
            timeout=timeout,
        )

        formatted = _format_diagnostics(proc.stdout or "", proc.stderr or "", proc.returncode)
        return ToolResult(
            tool_use_id="",
            content=formatted,
            is_error=(proc.returncode != 0),
        )

    except subprocess.TimeoutExpired:
        return ToolResult(
            tool_use_id="",
            content=f"Error: Test suite execution timed out after {timeout} seconds.",
            is_error=True,
        )
    except Exception as e:
        return ToolResult(
            tool_use_id="",
            content=f"Error running test command '{cmd_str}': {e}",
            is_error=True,
        )
