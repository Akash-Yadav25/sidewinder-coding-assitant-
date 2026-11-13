"""Unit tests for the SlashCommandHandler router and commands."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from coder_agent.agent import Agent
from coder_agent.commands import CommandResult, SlashCommandHandler
from coder_agent.config import Config
from coder_agent.types import TokenUsage
from coder_agent.ui import UI


def test_command_exit():
    agent = MagicMock()
    ui = UI(use_colors=False)
    cfg = Config()
    handler = SlashCommandHandler(agent, ui, cfg)

    res = handler.handle("/exit", TokenUsage(), None)
    assert res.handled
    assert res.should_exit

    res_q = handler.handle("quit", TokenUsage(), None)
    assert res_q.handled
    assert res_q.should_exit


def test_command_help(capsys):
    agent = MagicMock()
    ui = UI(use_colors=False)
    cfg = Config()
    handler = SlashCommandHandler(agent, ui, cfg)

    res = handler.handle("/help", TokenUsage(), None)
    assert res.handled
    assert not res.should_exit
    captured = capsys.readouterr()
    assert "Available Slash Commands" in captured.out


def test_command_diff(capsys):
    agent = MagicMock()
    agent.git.get_diff.return_value = "diff --git a/x.py b/x.py"
    ui = UI(use_colors=False)
    cfg = Config()
    handler = SlashCommandHandler(agent, ui, cfg)

    res = handler.handle("/diff", TokenUsage(), None)
    assert res.handled
    captured = capsys.readouterr()
    assert "Uncommitted Changes" in captured.out


def test_command_undo():
    agent = MagicMock()
    agent.git.restore_checkpoint.return_value = True
    ui = UI(use_colors=False)
    cfg = Config()
    handler = SlashCommandHandler(agent, ui, cfg)

    # Without checkpoint
    res_no = handler.handle("/undo", TokenUsage(), None)
    assert res_no.handled

    # With checkpoint
    res_with = handler.handle("/undo", TokenUsage(), "chk_123")
    assert res_with.handled
    agent.git.restore_checkpoint.assert_called_with("chk_123")


def test_command_commit():
    agent = MagicMock()
    agent.git.commit.return_value = True
    ui = UI(use_colors=False)
    cfg = Config()
    handler = SlashCommandHandler(agent, ui, cfg)

    res = handler.handle("/commit Test commit message", TokenUsage(), None)
    assert res.handled
    agent.git.commit.assert_called_with("Test commit message")


def test_command_cost(capsys):
    agent = MagicMock()
    ui = UI(use_colors=False)
    cfg = Config(provider="anthropic", model="claude-3-5-sonnet-20241022")
    handler = SlashCommandHandler(agent, ui, cfg)

    tokens = TokenUsage(input_tokens=1000, output_tokens=500)
    res = handler.handle("/cost", tokens, None)
    assert res.handled
    captured = capsys.readouterr()
    assert "Session Token & Cost Analytics" in captured.out


def test_command_model(capsys):
    agent = MagicMock()
    ui = UI(use_colors=False)
    cfg = Config(provider="anthropic", model="claude-3-5-sonnet-20241022")
    handler = SlashCommandHandler(agent, ui, cfg)

    # Inspect current model
    res_inspect = handler.handle("/model", TokenUsage(), None)
    assert res_inspect.handled
    captured = capsys.readouterr()
    assert "Active Model Settings" in captured.out

    # Switch model
    res_switch = handler.handle("/model claude-3-5-haiku-20241022", TokenUsage(), None)
    assert res_switch.handled
    assert cfg.model == "claude-3-5-haiku-20241022"


def test_command_history(capsys):
    agent = MagicMock()
    agent.messages = [
        {"role": "user", "content": "Write calculator function"},
        {"role": "assistant", "content": "Done creating function", "tool_calls": []},
    ]
    ui = UI(use_colors=False)
    cfg = Config()
    handler = SlashCommandHandler(agent, ui, cfg)

    res = handler.handle("/history", TokenUsage(), None)
    assert res.handled
    captured = capsys.readouterr()
    assert "Recent Conversation History" in captured.out
    assert "[User]" in captured.out
    assert "[Assistant]" in captured.out


def test_command_reset():
    agent = MagicMock()
    agent.messages = [{"role": "user", "content": "old"}]
    ui = UI(use_colors=False)
    cfg = Config()
    handler = SlashCommandHandler(agent, ui, cfg)

    res = handler.handle("/reset", TokenUsage(), None)
    assert res.handled
    assert len(agent.messages) == 0


def test_command_unhandled():
    agent = MagicMock()
    ui = UI(use_colors=False)
    cfg = Config()
    handler = SlashCommandHandler(agent, ui, cfg)

    res_unknown = handler.handle("/foobar", TokenUsage(), None)
    assert res_unknown.handled  # handled as unknown command message

    res_natural = handler.handle("create a new file named test.py", TokenUsage(), None)
    assert not res_natural.handled  # natural language coding request
