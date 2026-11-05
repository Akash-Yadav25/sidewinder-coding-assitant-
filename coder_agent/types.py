"""Core data models and type definitions for Coder Agent."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolCall:
    """A tool call requested by the LLM."""

    id: str
    name: str
    input: dict[str, Any] = field(default_factory=dict)


@dataclass
class TokenUsage:
    """Token usage tracking across turns."""

    input_tokens: int = 0
    output_tokens: int = 0

    def add(self, other: TokenUsage) -> None:
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens


@dataclass
class Message:
    """Normalized provider-agnostic representation of an LLM turn."""

    role: str  # "user" | "assistant" | "system"
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    stop_reason: str = "end_turn"  # "end_turn" | "tool_use" | "max_tokens"
    usage: TokenUsage = field(default_factory=TokenUsage)


@dataclass
class ToolResult:
    """Result returned by tool execution."""

    tool_use_id: str
    content: str
    is_error: bool = False


@dataclass
class ToolDefinition:
    """Provider-agnostic tool definition."""

    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema specification


@dataclass
class AgentResult:
    """Summary of the execution of an agent task."""

    success: bool
    summary: str
    files_modified: list[str] = field(default_factory=list)
    files_created: list[str] = field(default_factory=list)
    files_deleted: list[str] = field(default_factory=list)
    commands_run: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    total_tokens: TokenUsage = field(default_factory=TokenUsage)
