"""Abstract base class for all LLM providers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Generator

from coder_agent.types import Message, ToolDefinition, ToolResult


class LLMProvider(ABC):
    """Abstract interface normalizing multi-provider tool use and streaming."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Friendly provider identifier."""
        ...

    @abstractmethod
    def send_message(
        self,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[ToolDefinition],
    ) -> Message:
        """Send complete conversation context and receive response turn."""
        ...

    @abstractmethod
    def stream_message(
        self,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[ToolDefinition],
    ) -> Generator[str | Message, None, Message]:
        """Stream conversational text chunks, yielding string chunks and final Message."""
        ...
