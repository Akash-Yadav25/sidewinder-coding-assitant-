"""Unit tests for context compaction and history budgeting."""

from __future__ import annotations

from coder_agent.compactor import (
    compact_history,
    estimate_message_tokens,
    estimate_tokens,
    truncate_older_tool_results,
)
from coder_agent.types import ToolCall, ToolResult


def test_estimate_tokens():
    assert estimate_tokens("") == 0
    assert estimate_tokens("hello") == 1
    assert estimate_tokens("a" * 400) == 100


def test_estimate_message_tokens():
    msgs = [
        {"role": "user", "content": "hello world"},
        {
            "role": "assistant",
            "content": "Let me check",
            "tool_calls": [ToolCall(id="c1", name="read_file", input={"path": "main.py"})],
        },
        {
            "role": "tool_results",
            "results": [ToolResult(tool_use_id="c1", content="print('hi')")],
        },
    ]
    tokens = estimate_message_tokens(msgs)
    assert tokens > 15


def test_truncate_older_tool_results():
    long_output = "line\n" * 1000  # 5000 chars
    msgs = [
        {"role": "user", "content": "initial prompt"},
        {
            "role": "tool_results",
            "results": [ToolResult(tool_use_id="c1", content=long_output)],
        },
        {"role": "assistant", "content": "turn 2"},
        {
            "role": "tool_results",
            "results": [ToolResult(tool_use_id="c2", content=long_output)],
        },
        {"role": "assistant", "content": "turn 3"},
        {"role": "user", "content": "recent prompt"},
    ]

    # Preserve last 2 turns, older turn 1 should be truncated
    condensed = truncate_older_tool_results(msgs, max_recent_turns_to_preserve=2, max_chars=200)
    # The first tool result should have been truncated
    first_tool_res = condensed[1]["results"][0]
    assert "[Output truncated:" in first_tool_res.content
    assert len(first_tool_res.content) < len(long_output)


def test_compact_history_under_budget():
    msgs = [
        {"role": "user", "content": "Fix bug"},
        {"role": "assistant", "content": "Will do"},
    ]
    result = compact_history(msgs, token_budget=1000)
    assert result == msgs


def test_compact_history_over_budget():
    # Construct a verbose conversation
    msgs = [{"role": "user", "content": "Fix bug in auth.py"}]
    for i in range(10):
        msgs.append(
            {
                "role": "assistant",
                "content": f"Step {i}: inspecting file",
                "tool_calls": [ToolCall(id=f"c_{i}", name="read_file", input={"path": f"file_{i}.py"})],
            }
        )
        msgs.append(
            {
                "role": "tool_results",
                "results": [ToolResult(tool_use_id=f"c_{i}", content=f"data {i} " * 200)],
            }
        )
    msgs.append({"role": "assistant", "content": "Recent action"})
    msgs.append({"role": "tool_results", "results": [ToolResult(tool_use_id="recent", content="recent result")]})

    compacted = compact_history(msgs, token_budget=50, keep_recent_count=2)
    # Must preserve initial message
    assert compacted[0]["content"] == "Fix bug in auth.py"
    # Second message must be milestone
    assert "CONVERSATION MILESTONE" in compacted[1]["content"]
    assert "file_0.py" in compacted[1]["content"]
    # Must preserve recent messages
    assert compacted[-2]["content"] == "Recent action"
    assert len(compacted) < len(msgs)
