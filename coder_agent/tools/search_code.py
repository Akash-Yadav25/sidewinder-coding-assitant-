"""Implementation of the search_code tool."""

from __future__ import annotations

import fnmatch
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from coder_agent.tools.list_directory import _is_excluded
from coder_agent.types import ToolResult

if TYPE_CHECKING:
    from coder_agent.config import Config
    from coder_agent.safety import SafetyGuard
    from coder_agent.ui import UI

MAX_MATCHES = 50


def _is_binary(file_path: Path) -> bool:
    """Quick check if a file is binary by looking for null bytes."""
    try:
        with file_path.open("rb") as f:
            chunk = f.read(1024)
            return b"\x00" in chunk
    except Exception:
        return True


def execute(
    input_args: dict[str, Any],
    project_dir: str,
    safety: SafetyGuard,
    ui: UI,
    config: Config,
) -> ToolResult:
    """Search for regex patterns across project files."""
    pattern_str = input_args.get("pattern")
    if not pattern_str:
        return ToolResult(tool_use_id="", content="Error: 'pattern' parameter is required", is_error=True)

    target_rel = input_args.get("path") or "."
    file_filter = input_args.get("file_pattern")

    try:
        target_path = safety.validate_path(target_rel, project_dir)
    except ValueError as e:
        return ToolResult(tool_use_id="", content=str(e), is_error=True)

    if not target_path.exists():
        return ToolResult(tool_use_id="", content=f"Error: Path does not exist: '{target_rel}'", is_error=True)

    try:
        regex = re.compile(pattern_str, re.MULTILINE)
    except re.error as e:
        return ToolResult(tool_use_id="", content=f"Error: Invalid regular expression: {e}", is_error=True)

    base_project = Path(project_dir).resolve()
    matches: list[str] = []
    files_scanned = 0

    def _search_file(fpath: Path) -> bool:
        """Search in a single file. Returns True if max matches reached."""
        nonlocal files_scanned
        if _is_excluded(fpath, base_project, config.exclude_patterns):
            return False
        if file_filter and not fnmatch.fnmatch(fpath.name, file_filter):
            return False
        if _is_binary(fpath):
            return False

        files_scanned += 1
        try:
            rel_display = fpath.relative_to(base_project).as_posix()
            content = fpath.read_text(encoding="utf-8", errors="replace")
            for line_no, line in enumerate(content.splitlines(), start=1):
                if regex.search(line):
                    # Truncate overly long lines for readability
                    clean_line = line.strip()
                    if len(clean_line) > 200:
                        clean_line = clean_line[:200] + "..."
                    matches.append(f"{rel_display}:{line_no}: {clean_line}")
                    if len(matches) >= MAX_MATCHES:
                        return True
        except Exception:
            pass
        return False

    if target_path.is_file():
        _search_file(target_path)
    else:
        for p in target_path.rglob("*"):
            if p.is_file():
                if _search_file(p):
                    break

    if not matches:
        return ToolResult(
            tool_use_id="",
            content=f"No matches found for pattern '{pattern_str}' across {files_scanned} files.",
        )

    output = [f"Found {len(matches)} match(es) for '{pattern_str}':"]
    output.extend(matches)
    if len(matches) >= MAX_MATCHES:
        output.append(f"\n[Limit of {MAX_MATCHES} matches reached. Narrow your search pattern or path.]")

    return ToolResult(tool_use_id="", content="\n".join(output))
