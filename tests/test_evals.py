"""Unit tests for the evaluation benchmark harness."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Generator

from coder_agent.providers.base import LLMProvider
from coder_agent.types import Message, TokenUsage, ToolCall, ToolDefinition
from evals.harness import EvalHarness, EvalTask


class MockSolverProvider(LLMProvider):
    """Mock provider that calls edit_file to fix calculator bug, then concludes."""

    def __init__(self):
        self.turns = 0

    @property
    def name(self) -> str:
        return "mock-solver"

    def send_message(self, system: str, messages: list[dict[str, Any]], tools: list[ToolDefinition]) -> Message:
        return next(self.stream_message(system, messages, tools))  # type: ignore

    def stream_message(
        self, system: str, messages: list[dict[str, Any]], tools: list[ToolDefinition]
    ) -> Generator[str | Message, None, Message]:
        self.turns += 1
        if self.turns == 1:
            msg = Message(
                role="assistant",
                content="I will fix the bug.",
                tool_calls=[
                    ToolCall(
                        id="c1",
                        name="edit_file",
                        input={
                            "path": "calc.py",
                            "old_text": "return a - b  # bug",
                            "new_text": "return a + b",
                        },
                    )
                ],
                stop_reason="tool_use",
                usage=TokenUsage(100, 50),
            )
            yield msg
            return msg
        else:
            msg = Message(
                role="assistant",
                content="Bug is fixed and verified.",
                tool_calls=[],
                stop_reason="end_turn",
                usage=TokenUsage(150, 30),
            )
            yield msg
            return msg


def test_eval_harness_single_task(tmp_path: Path):
    harness = EvalHarness(workspace_root=tmp_path)

    task = EvalTask(
        task_id="fix_add",
        requirement="Fix addition bug in calc.py",
        setup_files={
            "calc.py": "def add(a, b):\n    return a - b  # bug\n",
        },
        verify_fn=lambda p: (p / "calc.py").read_text(encoding="utf-8") == "def add(a, b):\n    return a + b\n",
    )

    provider = MockSolverProvider()
    res = harness.run_task(task, provider)

    assert res["passed"]
    assert res["task_id"] == "fix_add"
    assert "calc.py" in res["files_modified"]
    assert res["tokens"] > 0


def test_eval_harness_suite(tmp_path: Path):
    harness = EvalHarness(workspace_root=tmp_path)

    task = EvalTask(
        task_id="t1",
        requirement="Fix addition",
        setup_files={"calc.py": "def add(a, b):\n    return a - b  # bug\n"},
        verify_fn=lambda p: "return a + b" in (p / "calc.py").read_text(encoding="utf-8"),
    )

    report = harness.run_suite([task], MockSolverProvider())
    assert report.total_tasks == 1
    assert report.passed_tasks == 1
    assert report.failed_tasks == 0
    assert report.total_tokens > 0
