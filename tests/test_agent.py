"""Unit tests for the core Agent loop and side-effect tracking."""

from __future__ import annotations

from pathlib import Path

from coder_agent.agent import Agent
from coder_agent.config import Config
from coder_agent.context import ContextBuilder
from coder_agent.safety import SafetyGuard
from coder_agent.tools import ToolRegistry
from coder_agent.types import AgentResult, Message, TokenUsage, ToolCall, ToolResult
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

    def test_agent_pav_loop_success(
        self,
        test_config: Config,
        tool_registry: ToolRegistry,
        safety_guard: SafetyGuard,
        silent_ui: UI,
    ):
        test_config.reasoning_mode = "always"
        mock_provider = MockProvider(
            responses=[
                # Turn 1: PLAN
                Message(
                    role="assistant",
                    content="<plan>\nUNDERSTANDING: Fix division\nAPPROACH: Add check\n</plan>",
                    stop_reason="end_turn",
                ),
                # Turn 2: ACT
                Message(
                    role="assistant",
                    content="Changes implemented successfully.",
                    stop_reason="end_turn",
                ),
                # Turn 3: VALIDATE
                Message(
                    role="assistant",
                    content="[PASS] Tests: 128 passed\n[PASS] Behavioral: returns 0 on divide by zero\nVALIDATION COMPLETE — ALL CHECKS PASSED",
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

        result = agent.run("Fix the division logic")
        assert result.success
        assert result.phase_history == ["PLAN", "ACT-0", "VALIDATE-0"]
        assert len(result.validation_checks) == 2
        assert all(chk.passed for chk in result.validation_checks)
        assert "Fix division" in result.plan_text

    def test_agent_pav_loop_diagnose_and_replan(
        self,
        test_config: Config,
        tool_registry: ToolRegistry,
        safety_guard: SafetyGuard,
        silent_ui: UI,
    ):
        test_config.reasoning_mode = "always"
        test_config.max_replan_cycles = 2
        mock_provider = MockProvider(
            responses=[
                # 1. PLAN
                Message(role="assistant", content="<plan>Initial strategy</plan>", stop_reason="end_turn"),
                # 2. ACT-0
                Message(role="assistant", content="Did initial edit", stop_reason="end_turn"),
                # 3. VALIDATE-0 (fails)
                Message(role="assistant", content="[FAIL] Tests: division by zero unhandled\nVALIDATION FAILED", stop_reason="end_turn"),
                # 4. DIAGNOSE-1
                Message(role="assistant", content="<plan>Corrected strategy: check b == 0</plan>", stop_reason="end_turn"),
                # 5. ACT-1
                Message(role="assistant", content="Applied corrected fix", stop_reason="end_turn"),
                # 6. VALIDATE-1 (passes)
                Message(role="assistant", content="[PASS] Tests: passed\nVALIDATION COMPLETE — ALL CHECKS PASSED", stop_reason="end_turn"),
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

        result = agent.run("Refactor division module")
        assert result.success
        assert result.replan_count == 1
        assert "DIAGNOSE-1" in result.phase_history
        assert "ACT-1" in result.phase_history
        assert "VALIDATE-1" in result.phase_history

    def test_agent_complexity_and_tool_truncation(
        self,
        test_config: Config,
        tool_registry: ToolRegistry,
        safety_guard: SafetyGuard,
        silent_ui: UI,
    ):
        agent = Agent(
            provider=MockProvider(),
            tools=tool_registry,
            context=ContextBuilder(test_config),
            safety=safety_guard,
            config=test_config,
            ui=silent_ui,
        )

        assert agent._estimate_complexity("simple typo") == "simple"
        assert agent._should_use_pav("simple typo") is False

        # Keyword trigger
        assert agent._should_use_pav("refactor authentication subsystem") is True
        assert agent._estimate_complexity("refactor authentication subsystem and migrate db") == "complex"

        # Long requirement trigger
        long_req = " ".join(["word"] * 30)
        assert agent._should_use_pav(long_req) is True

        # Tool output truncation
        short_out = "Short output"
        assert agent._truncate_tool_output(short_out) == short_out

        long_out = "X" * 10000
        truncated = agent._truncate_tool_output(long_out)
        assert len(truncated) < 10000
        assert "trimmed" in truncated

    def test_track_tool_side_effects_linter(
        self,
        test_config: Config,
        tool_registry: ToolRegistry,
        safety_guard: SafetyGuard,
        silent_ui: UI,
    ):
        agent = Agent(
            provider=MockProvider(),
            tools=tool_registry,
            context=ContextBuilder(test_config),
            safety=safety_guard,
            config=test_config,
            ui=silent_ui,
        )
        result = AgentResult(success=True, summary="")
        call = ToolCall(id="1", name="run_linter", input={"path": "."})
        res = ToolResult(tool_use_id="1", content="[ruff] ✅ No issues found", is_error=False)
        agent._track_tool_side_effects(call, res, result)

        assert len(result.commands_run) == 1
        assert result.commands_run[0]["command"] == "run_linter: ."
        assert result.commands_run[0]["exit_code"] == 0

    def test_run_resets_phase_and_plan_state(
        self,
        test_config: Config,
        tool_registry: ToolRegistry,
        safety_guard: SafetyGuard,
        silent_ui: UI,
    ):
        mock_provider = MockProvider(
            responses=[
                Message(role="assistant", content="Done task 1", stop_reason="end_turn"),
                Message(role="assistant", content="Done task 2", stop_reason="end_turn"),
            ]
        )
        agent = Agent(
            provider=mock_provider,
            tools=tool_registry,
            context=ContextBuilder(test_config),
            safety=safety_guard,
            config=test_config,
            ui=silent_ui,
        )
        agent._last_phase_history = ["STALE-PHASE"]
        agent._last_plan_text = "STALE PLAN"

        agent.run("Fix typo in file.py")
        assert agent._last_phase_history == []
        assert agent._last_plan_text == ""
