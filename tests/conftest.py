"""Pytest shared fixtures and mock LLM provider for tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Generator

import pytest

from coder_agent.config import Config
from coder_agent.providers.base import LLMProvider
from coder_agent.safety import SafetyGuard
from coder_agent.tools import ToolRegistry
from coder_agent.types import Message, TokenUsage, ToolCall, ToolDefinition, ToolResult
from coder_agent.ui import UI


class MockProvider(LLMProvider):
    """Deterministic mock provider delivering scripted turns for unit & integration testing."""

    def __init__(self, responses: list[Message] | None = None):
        self.responses: list[Message] = responses or []
        self.call_history: list[dict[str, Any]] = []
        self._current_idx: int = 0

    @property
    def name(self) -> str:
        return "mock-provider"

    def send_message(
        self,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[ToolDefinition],
    ) -> Message:
        self.call_history.append(
            {"system": system, "messages": list(messages), "tools": tools}
        )
        if self._current_idx < len(self.responses):
            resp = self.responses[self._current_idx]
            self._current_idx += 1
            return resp
        return Message(role="assistant", content="Default mock response", stop_reason="end_turn")

    def stream_message(
        self,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[ToolDefinition],
    ) -> Generator[str | Message, None, Message]:
        resp = self.send_message(system, messages, tools)
        if resp.content:
            yield resp.content
        yield resp
        return resp


@pytest.fixture
def tmp_project(tmp_path: Path) -> Path:
    """Create a temporary project sandbox with sample source code and tests."""
    # Main application file
    main_file = tmp_path / "main.py"
    main_file.write_text(
        "def add(a, b):\n    return a + b\n\ndef divide(a, b):\n    return a / b\n",
        encoding="utf-8",
    )

    # Test file
    test_file = tmp_path / "test_main.py"
    test_file.write_text(
        "from main import add, divide\n\ndef test_add():\n    assert add(2, 3) == 5\n",
        encoding="utf-8",
    )

    # Subdirectory with module
    sub = tmp_path / "utils"
    sub.mkdir()
    (sub / "helper.py").write_text("# Helper functions\n", encoding="utf-8")

    return tmp_path


@pytest.fixture
def test_config(tmp_project: Path) -> Config:
    """Config with approval disabled for automated test runs."""
    return Config(
        provider="anthropic",
        model="claude-sonnet-4-20250514",
        anthropic_api_key="test-key-12345",
        project_dir=str(tmp_project),
        approval_mode="never",
        max_iterations=10,
        max_tokens=2048,
        log_level="error",
    )


@pytest.fixture
def silent_ui() -> UI:
    """UI instance with disabled ANSI colors."""
    return UI(use_colors=False)


@pytest.fixture
def safety_guard(test_config: Config) -> SafetyGuard:
    return SafetyGuard(test_config)


@pytest.fixture
def tool_registry(
    test_config: Config, safety_guard: SafetyGuard, silent_ui: UI
) -> ToolRegistry:
    return ToolRegistry(
        project_dir=test_config.project_dir,
        safety=safety_guard,
        ui=silent_ui,
        config=test_config,
    )
