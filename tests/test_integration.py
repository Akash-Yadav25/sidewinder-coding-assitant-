"""Integration test simulating complete autonomous coding workflows."""

from __future__ import annotations

import shlex
import sys
from pathlib import Path

from coder_agent.agent import Agent
from coder_agent.config import Config
from coder_agent.context import ContextBuilder
from coder_agent.safety import SafetyGuard
from coder_agent.tools import ToolRegistry
from coder_agent.types import Message, TokenUsage, ToolCall
from coder_agent.ui import UI
from tests.conftest import MockProvider


class TestAutonomousWorkflow:
    def test_full_diagnose_fix_test_workflow(
        self,
        test_config: Config,
        tool_registry: ToolRegistry,
        safety_guard: SafetyGuard,
        silent_ui: UI,
        tmp_project: Path,
    ):
        """Simulate complete agent lifecycle: inspect -> modify -> test -> summarize."""
        updated_code = """def add(a, b):
    return a + b

def divide(a, b):
    if b == 0:
        raise ValueError("Cannot divide by zero")
    return a / b
"""
        test_code = """from main import add, divide
import pytest

def test_add():
    assert add(2, 3) == 5

def test_divide_zero():
    with pytest.raises(ValueError):
        divide(10, 0)
"""
        (tmp_project / "test_main.py").write_text(test_code, encoding="utf-8")
        test_cmd = f"{shlex.quote(sys.executable)} -m pytest test_main.py"

        mock_responses = [
            # Turn 1: Read existing implementation
            Message(
                role="assistant",
                content="I will read main.py to inspect the divide function.",
                tool_calls=[ToolCall(id="t1", name="read_file", input={"path": "main.py"})],
                stop_reason="tool_use",
                usage=TokenUsage(120, 30),
            ),
            # Turn 2: Write fixed implementation
            Message(
                role="assistant",
                content="I will now add zero-division validation to main.py.",
                tool_calls=[
                    ToolCall(
                        id="t2",
                        name="write_file",
                        input={"path": "main.py", "content": updated_code},
                    )
                ],
                stop_reason="tool_use",
                usage=TokenUsage(200, 50),
            ),
            # Turn 3: Run pytest to verify changes
            Message(
                role="assistant",
                content="Now I will run pytest to verify the fix.",
                tool_calls=[
                    ToolCall(
                        id="t3",
                        name="run_command",
                        input={"command": test_cmd},
                    )
                ],
                stop_reason="tool_use",
                usage=TokenUsage(300, 40),
            ),
            # Turn 4: Summarize success
            Message(
                role="assistant",
                content="Successfully fixed division by zero error in main.py and verified that all tests pass.",
                stop_reason="end_turn",
                usage=TokenUsage(400, 60),
            ),
        ]

        mock_provider = MockProvider(responses=mock_responses)
        context = ContextBuilder(test_config)
        agent = Agent(
            provider=mock_provider,
            tools=tool_registry,
            context=context,
            safety=safety_guard,
            config=test_config,
            ui=silent_ui,
        )

        result = agent.run("Fix division by zero in main.py and make sure tests pass")

        # 1. Verification of agent result
        assert result.success
        assert "Successfully fixed division by zero" in result.summary

        # 2. Verification of file modifications on disk
        current_content = (tmp_project / "main.py").read_text(encoding="utf-8")
        assert "Cannot divide by zero" in current_content

        # 3. Verification of tracked side-effects
        assert "main.py" in result.files_modified
        assert len(result.commands_run) == 1
        assert test_cmd in result.commands_run[0]["command"]
        assert result.commands_run[0]["exit_code"] == 0

        # 4. Verification of token accumulation
        assert result.total_tokens.input_tokens == 1020
        assert result.total_tokens.output_tokens == 180

