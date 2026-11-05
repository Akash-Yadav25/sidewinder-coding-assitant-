"""Unit tests for the core Agent loop and side-effect tracking."""

from __future__ import annotations

from pathlib import Path

from coder_agent.agent import Agent
from coder_agent.config import Config
from coder_agent.context import ContextBuilder
from coder_agent.safety import SafetyGuard
from coder_agent.tools import ToolRegistry
from coder_agent.types import Message, TokenUsage, ToolCall
from coder_agent.ui import UI
from tests.conftest import MockProvider


class TestAgentLoop:
    def test_direct_conclusion_without_tools(
        self,
        test_config: Config,
        tool_registry: ToolRegistry,
        safety_guard: SafetyGuard,
        silent_ui: UI,
    ):
        mock_provider = MockProvider(
            responses=[
                Message(
                    role="assistant",
                    content="I have analyzed your request and no changes are necessary.",
                    stop_reason="end_turn",
                    usage=TokenUsage(input_tokens=100, output_tokens=20),
                )
            ]
        )
        context = ContextBuilder(test_config)
        agent = Agent(
            provider=mock_provider,
            tools=tool_registry,
            context=context,
            safety=safety_guard,
            config=test_config,
            ui=silent_ui,
        )

        result = agent.run("Check codebase health")
        assert result.success
        assert "no changes are necessary" in result.summary
        assert result.total_tokens.input_tokens == 100
        assert result.total_tokens.output_tokens == 20

    def test_agent_executes_tool_call_and_concludes(
        self,
        test_config: Config,
        tool_registry: ToolRegistry,
        safety_guard: SafetyGuard,
        silent_ui: UI,
        tmp_project: Path,
    ):
        mock_provider = MockProvider(
            responses=[
                # Turn 1: request read_file
                Message(
                    role="assistant",
                    content="Inspecting main.py",
                    tool_calls=[ToolCall(id="c1", name="read_file", input={"path": "main.py"})],
                    stop_reason="tool_use",
                ),
                # Turn 2: conclude
                Message(
                    role="assistant",
                    content="Finished reading main.py. All looks good.",
                    stop_reason="end_turn",
                ),
            ]
        )
        context = ContextBuilder(test_config)
        agent = Agent(
            provider=mock_provider,
            tools=tool_registry,
            context=context,
            safety=safety_guard,
            config=test_config,
            ui=silent_ui,
        )

        result = agent.run("Review main.py")
        assert result.success
        assert "Finished reading main.py" in result.summary
        # Verify provider received the tool results in turn 2
        assert len(mock_provider.call_history) == 2
        last_messages = mock_provider.call_history[1]["messages"]
        assert last_messages[-1]["role"] == "tool_results"
        assert last_messages[-1]["results"][0].tool_use_id == "c1"

    def test_agent_stops_at_max_iterations(
        self,
        test_config: Config,
        tool_registry: ToolRegistry,
        safety_guard: SafetyGuard,
        silent_ui: UI,
    ):
        test_config.max_iterations = 2
        # An infinite loop of tool calls
        infinite_responses = [
            Message(
                role="assistant",
                content="Step",
                tool_calls=[ToolCall(id=f"c_{i}", name="list_directory", input={"path": "."})],
                stop_reason="tool_use",
            )
            for i in range(5)
        ]
        mock_provider = MockProvider(responses=infinite_responses)
        context = ContextBuilder(test_config)
        agent = Agent(
            provider=mock_provider,
            tools=tool_registry,
            context=context,
            safety=safety_guard,
            config=test_config,
            ui=silent_ui,
        )

        result = agent.run("Loop forever")
        assert not result.success
        assert any("maximum limit" in err for err in result.errors)
