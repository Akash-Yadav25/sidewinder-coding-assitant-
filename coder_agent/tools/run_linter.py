"""Auto-detect and run project linter for static analysis."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from coder_agent.types import ToolResult

if TYPE_CHECKING:
    from coder_agent.config import Config
    from coder_agent.safety import SafetyGuard
    from coder_agent.ui import UI


def _detect_linter(project_dir: Path) -> tuple[str, list[str]] | None:
    """Returns (display_name, command_parts) for the best available linter, or None if none detected."""
    # Python
    has_py = (
        (project_dir / "pyproject.toml").exists()
        or (project_dir / "setup.py").exists()
        or any(project_dir.glob("*.py"))
        or any(project_dir.glob("*/*.py"))
    )
    if has_py:
        for tool, args in [
            ("ruff", ["ruff", "check", "."]),
            ("mypy", ["mypy", ".", "--ignore-missing-imports"]),
            ("flake8", ["flake8", "."]),
            ("pylint", ["pylint", "."]),
        ]:
            if shutil.which(tool):
                return (tool, args)

    # JavaScript/TypeScript
    has_js = (
        (project_dir / "package.json").exists()
        or any(project_dir.glob("*.ts"))
        or any(project_dir.glob("*.js"))
    )
    if has_js:
        if shutil.which("eslint"):
            return ("eslint", ["eslint", "."])

    # Go
    if (project_dir / "go.mod").exists() or any(project_dir.glob("*.go")):
        if shutil.which("go"):
            return ("go vet", ["go", "vet", "./..."])

    # Rust
    if (project_dir / "Cargo.toml").exists():
        if shutil.which("cargo"):
            return ("cargo clippy", ["cargo", "clippy", "--", "-D", "warnings"])

    return None


def execute(
    input_args: dict,
    project_dir: str,
    safety: SafetyGuard,
    ui: UI,
    config: Config,
) -> ToolResult:
    """Run static analysis with the detected linter."""
    rel_path = input_args.get("path")
    target_dir = Path(project_dir) / rel_path if rel_path else Path(project_dir)
    fix = bool(input_args.get("fix", False))

    detected = _detect_linter(target_dir)
    if not detected:
        return ToolResult(
            tool_use_id="",
            content="[run_linter] No supported linter (ruff, mypy, flake8, eslint, go vet, cargo clippy) found in PATH.",
            is_error=False,
        )

    tool_name, base_cmd = detected
    cmd = list(base_cmd)

    if fix and tool_name in ("ruff", "eslint"):
        cmd.append("--fix")

    import shlex

    cmd_str = " ".join(shlex.quote(p) for p in cmd)
    try:
        safety.validate_command(cmd_str)
    except ValueError as e:
        return ToolResult(tool_use_id="", content=str(e), is_error=True)

    if not safety.approve_command(cmd_str, ui):
        return ToolResult(
            tool_use_id="",
            content=f"Operation cancelled: User denied permission to run linter: '{cmd_str}'",
            is_error=True,
        )

    try:
        proc = subprocess.run(
            cmd,
            cwd=str(target_dir),
            capture_output=True,
            text=True,
            timeout=60,
        )
        output = (proc.stdout + proc.stderr).strip()
        status = "✅ No issues found" if proc.returncode == 0 else f"⚠️ Issues found (exit code {proc.returncode})"
        content = f"[{tool_name}] {status}"
        if output:
            content += f"\n\n{output[:4000]}"
        return ToolResult(
            tool_use_id="",
            content=content,
            is_error=(proc.returncode != 0),
        )
    except subprocess.TimeoutExpired:
        return ToolResult(
            tool_use_id="",
            content=f"[{tool_name}] Linter timed out after 60s.",
            is_error=True,
        )
    except Exception as e:
        return ToolResult(
            tool_use_id="",
            content=f"[{tool_name}] Error running linter: {e}",
            is_error=True,
        )
