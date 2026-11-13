"""Unit tests for the autonomous self-review engine in Agent."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from coder_agent.agent import Agent
from coder_agent.config import Config
from coder_agent.types import AgentResult, Message
from coder_agent.ui import UI


def test_self_review_clean_files(tmp_path: Path):
    py_file = tmp_path / "valid.py"
    py_file.write_text("def greet():\n    return 'hello'\n", encoding="utf-8")

    cfg = Config(project_dir=str(tmp_path))
    mock_provider = MagicMock()
    mock_provider.name = "mock"
    agent = Agent(
        provider=mock_provider,
        tools=MagicMock(),
        context=MagicMock(),
        safety=MagicMock(),
        config=cfg,
        ui=UI(use_colors=False),
    )

    result = AgentResult(success=True, summary="", files_modified=["valid.py"])
    errors = agent._run_self_review(result)
    assert len(errors) == 0


def test_self_review_catches_syntax_error(tmp_path: Path):
    broken_file = tmp_path / "broken.py"
    broken_file.write_text("def broken_syntax(:\n", encoding="utf-8")

    cfg = Config(project_dir=str(tmp_path))
    mock_provider = MagicMock()
    mock_provider.name = "mock"
    agent = Agent(
        provider=mock_provider,
        tools=MagicMock(),
        context=MagicMock(),
        safety=MagicMock(),
        config=cfg,
        ui=UI(use_colors=False),
    )

    result = AgentResult(success=True, summary="", files_modified=["broken.py"])
    errors = agent._run_self_review(result)
    assert len(errors) == 1
    assert "SyntaxError" in errors[0]
    assert "broken.py" in errors[0]


def test_self_review_triggers_correction_loop(tmp_path: Path):
    broken_file = tmp_path / "calc.py"
    broken_file.write_text("def calc(:\n", encoding="utf-8")

    cfg = Config(project_dir=str(tmp_path), max_iterations=4)
    provider = MagicMock()
    provider.name = "mock"

    from coder_agent.types import ToolCall, ToolResult

    # Turn 1: Model modifies calc.py
    tc = ToolCall(id="t1", name="edit_file", input={"path": "calc.py", "old_text": "", "new_text": ""})
    msg_turn1 = Message(role="assistant", content="Editing calc.py", tool_calls=[tc])

    # Turn 2: Model tries to conclude, but calc.py has broken syntax
    msg_turn2 = Message(role="assistant", content="Finished work", stop_reason="end_turn")

    def side_effect_fn(*args, **kwargs):
        call_num = provider.stream_message.call_count
        if call_num == 1:
            return iter([msg_turn1])
        elif call_num == 2:
            return iter([msg_turn2])
        else:
            broken_file.write_text("def calc():\n    return 42\n", encoding="utf-8")
            return iter([Message(role="assistant", content="Syntax fixed", stop_reason="end_turn")])

    provider.stream_message.side_effect = side_effect_fn

    agent = Agent(
        provider=provider,
        tools=MagicMock(),
        context=MagicMock(),
        safety=MagicMock(),
        config=cfg,
        ui=UI(use_colors=False),
    )
    agent.tools.execute.return_value = ToolResult(tool_use_id="t1", content="Edited calc.py")

    # Run agent
    res = agent.run("Create calc")

    # Verify agent iterated to Turn 3 after self-review flagged the syntax error
    assert provider.stream_message.call_count == 3
    assert res.success
    assert "calc.py" in res.files_modified
    assert res.success
