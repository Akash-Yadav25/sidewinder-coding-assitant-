"""Safety guards, path validation, command verification, and user approval flows."""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from coder_agent.config import Config
    from coder_agent.ui import UI


class SafetyGuard:
    """Enforces boundaries and approval requirements for file operations and commands."""

    BLOCKED_PATTERNS = [
        re.compile(r"rm\s+(-[a-zA-Z]*r[a-zA-Z]*f|-[a-zA-Z]*f[a-zA-Z]*r)\s+/(?:\s|$)", re.IGNORECASE),  # rm -rf /
        re.compile(r"rm\s+(-[a-zA-Z]*r[a-zA-Z]*f|-[a-zA-Z]*f[a-zA-Z]*r)\s+~(?:\s|$)", re.IGNORECASE),  # rm -rf ~
        re.compile(r"sudo\s+", re.IGNORECASE),  # sudo anything
        re.compile(r"mkfs\.", re.IGNORECASE),  # filesystem formatting
        re.compile(r"dd\s+if=", re.IGNORECASE),  # raw disk writes
        re.compile(r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:", re.IGNORECASE),  # fork bomb
        re.compile(r"chmod\s+(-[a-zA-Z]*R\s+)?777\s+/(?:\s|$)", re.IGNORECASE),  # chmod 777 /
        re.compile(r">\s*/dev/sd[a-z]", re.IGNORECASE),  # overwriting block device
    ]

    def __init__(self, config: Config):
        self.config = config
        self.approval_mode = config.approval_mode.lower()
        self.project_dir = Path(config.project_dir).resolve()

    def validate_path(self, file_path: str | Path, base_dir: str | Path | None = None) -> Path:
        """Resolve and validate that file_path resides strictly within the project directory."""
        base = Path(base_dir).resolve() if base_dir else self.project_dir

        # Expand user and resolve
        resolved = (base / Path(file_path)).resolve()

        # Check if resolved path is within base
        try:
            resolved.relative_to(base)
        except ValueError:
            raise ValueError(
                f"Security violation: Path '{file_path}' resolves to '{resolved}', "
                f"which is outside project root '{base}'"
            )

        return resolved

    def validate_command(self, command: str) -> None:
        """Validate shell command against safety blocklist."""
        stripped = command.strip()
        if not stripped:
            raise ValueError("Command cannot be empty")

        for pattern in self.BLOCKED_PATTERNS:
            if pattern.search(stripped):
                raise ValueError(
                    f"Security violation: Command '{command}' matched dangerous pattern '{pattern.pattern}'"
                )

    def should_approve(self, operation: str, is_destructive: bool = False) -> bool:
        """Check if an operation requires interactive user approval."""
        if self.approval_mode == "never":
            return False
        if self.approval_mode == "always":
            return True
        # "destructive" mode
        return is_destructive

    def approve_file_write(
        self, path: Path, new_content: str, existing_content: str | None, ui: UI
    ) -> bool:
        """Request approval for writing/overwriting a file."""
        is_overwrite = existing_content is not None
        # In destructive mode, new file creation doesn't require confirmation, overwrite does
        if not self.should_approve("write", is_destructive=is_overwrite):
            return True

        rel_path = path.relative_to(self.project_dir) if path.is_relative_to(self.project_dir) else path
        if is_overwrite:
            assert existing_content is not None
            ui.diff(existing_content, new_content, str(rel_path))
            return ui.confirm(f"Approve overwriting file '{rel_path}'?")
        else:
            return ui.confirm(f"Approve creating new file '{rel_path}'?")

    def approve_file_deletion(self, path: Path, ui: UI) -> bool:
        """Request approval for deleting a file."""
        if not self.should_approve("delete", is_destructive=True):
            return True

        rel_path = path.relative_to(self.project_dir) if path.is_relative_to(self.project_dir) else path
        return ui.confirm(f"Approve deleting file '{rel_path}'?")

    def approve_command(self, command: str, ui: UI) -> bool:
        """Request approval for running an arbitrary shell command."""
        if not self.should_approve("command", is_destructive=True):
            return True

        return ui.confirm(f"Approve execution of shell command: '{command}'?")
