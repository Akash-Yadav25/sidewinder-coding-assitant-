"""Implementation of the list_directory tool."""

from __future__ import annotations

import fnmatch
from pathlib import Path
from typing import TYPE_CHECKING, Any

from coder_agent.types import ToolResult

if TYPE_CHECKING:
    from coder_agent.config import Config
    from coder_agent.safety import SafetyGuard
    from coder_agent.ui import UI


def _is_excluded(path: Path, base_dir: Path, exclude_patterns: list[str]) -> bool:
    """Check if file or directory matches any exclusion pattern."""
    rel = path.relative_to(base_dir).as_posix()
    name = path.name

    for pat in exclude_patterns:
        if fnmatch.fnmatch(name, pat) or fnmatch.fnmatch(rel, pat):
            return True
        # Match pattern against parts (e.g. "node_modules" in sub/node_modules/...)
        for part in path.parts:
            if fnmatch.fnmatch(part, pat):
                return True
    return False


def execute(
    input_args: dict[str, Any],
    project_dir: str,
    safety: SafetyGuard,
    ui: UI,
    config: Config,
) -> ToolResult:
    """Recursively list directory hierarchy up to max_depth."""
    target_rel = input_args.get("path") or "."
    max_depth = input_args.get("max_depth", 3)

    try:
        target_path = safety.validate_path(target_rel, project_dir)
    except ValueError as e:
        return ToolResult(tool_use_id="", content=str(e), is_error=True)

    if not target_path.exists():
        return ToolResult(tool_use_id="", content=f"Error: Path does not exist: '{target_rel}'", is_error=True)

    if not target_path.is_dir():
        return ToolResult(tool_use_id="", content=f"Error: Path is not a directory: '{target_rel}'", is_error=True)

    tree_lines: list[str] = [f"{target_rel}/"]
    dir_count = 0
    file_count = 0

    def _walk(current: Path, prefix: str, current_depth: int) -> None:
        nonlocal dir_count, file_count

        if current_depth > max_depth:
            return

        try:
            entries = sorted(list(current.iterdir()), key=lambda p: (not p.is_dir(), p.name.lower()))
        except PermissionError:
            tree_lines.append(f"{prefix}└── [Permission Denied]")
            return

        # Filter excluded entries
        valid_entries = [e for e in entries if not _is_excluded(e, Path(project_dir).resolve(), config.exclude_patterns)]

        count = len(valid_entries)
        for idx, entry in enumerate(valid_entries):
            is_last = idx == count - 1
            connector = "└── " if is_last else "├── "
            extension = "    " if is_last else "│   "

            if entry.is_dir():
                dir_count += 1
                tree_lines.append(f"{prefix}{connector}{entry.name}/")
                _walk(entry, prefix + extension, current_depth + 1)
            else:
                file_count += 1
                tree_lines.append(f"{prefix}{connector}{entry.name}")

    _walk(target_path, "", 1)

    summary = f"\n\nTotal: {dir_count} directories, {file_count} files (depth limit: {max_depth})"
    return ToolResult(tool_use_id="", content="\n".join(tree_lines) + summary)
