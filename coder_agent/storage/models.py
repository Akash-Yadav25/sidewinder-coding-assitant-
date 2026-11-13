"""Dataclass and record abstractions for SQLite session storage."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class SessionRecord:
    """Represents a session stored in SQLite."""

    id: str
    project_dir: str
    provider: str
    model: str
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    status: str = "active"


@dataclass
class MessageRecord:
    """Represents a persisted message turn."""

    session_id: str
    role: str
    content: str
    id: int | None = None
    token_count: int = 0
    created_at: float = field(default_factory=time.time)


@dataclass
class ToolCallRecord:
    """Represents a persisted tool invocation and its execution result."""

    id: str
    tool_name: str
    inputs_json: str
    output_text: str
    message_id: int | None = None
    is_error: bool = False
    duration_ms: float = 0.0


@dataclass
class CheckpointRecord:
    """Represents a git or shadow workspace checkpoint record."""

    id: str
    session_id: str
    git_ref: str
    description: str = ""
    created_at: float = field(default_factory=time.time)


@dataclass
class ProjectMemoryRecord:
    """Represents project-level persistent key-value memory."""

    project_dir: str
    key: str
    value: str
    updated_at: float = field(default_factory=time.time)
