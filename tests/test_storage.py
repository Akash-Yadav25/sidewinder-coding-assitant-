"""Unit tests for SQLite SessionStore and project memory."""

from __future__ import annotations

from pathlib import Path

from coder_agent.storage.db import SessionStore
from coder_agent.types import ToolCall, ToolResult


def test_session_lifecycle(tmp_path: Path):
    store = SessionStore(tmp_path)
    sid = store.create_session(provider="anthropic", model="claude-sonnet-4")
    assert sid.startswith("sess_")

    # Persist user turn
    store.save_message(sid, role="user", content="Hello test")

    # Persist assistant turn with tool call
    tc = ToolCall(id="c1", name="edit_file", input={"path": "a.py"})
    store.save_message(sid, role="assistant", content="Editing file", tool_calls=[tc])

    # Persist tool result
    tr = ToolResult(tool_use_id="c1", content="Success: edited a.py")
    store.save_message(sid, role="tool_results", results=[tr])

    # Load messages
    messages = store.get_session_messages(sid)
    assert len(messages) == 3
    assert messages[0]["role"] == "user"
    assert messages[0]["content"] == "Hello test"
    assert messages[1]["tool_calls"][0].name == "edit_file"
    assert messages[2]["results"][0].content == "Success: edited a.py"


def test_get_latest_session_id(tmp_path: Path):
    store = SessionStore(tmp_path)
    s1 = store.create_session(session_id="session_1")
    s2 = store.create_session(session_id="session_2")
    # Update s2
    store.save_message(s2, role="user", content="latest msg")
    assert store.get_latest_session_id() == "session_2"


def test_project_memory(tmp_path: Path):
    store = SessionStore(tmp_path)
    store.set_memory("test_runner", "pytest -k unit")
    assert store.get_memory("test_runner") == "pytest -k unit"
    assert store.get_memory("nonexistent") is None


def test_gitignore_handling(tmp_path: Path):
    gitignore = tmp_path / ".gitignore"
    gitignore.write_text("*.pyc\n", encoding="utf-8")
    SessionStore(tmp_path)
    content = gitignore.read_text(encoding="utf-8")
    assert ".coder-agent/" in content


def test_session_records_and_listing(tmp_path: Path):
    store = SessionStore(tmp_path)
    s1 = store.create_session(session_id="sess_alpha", provider="bedrock", model="claude-haiku")
    s2 = store.create_session(session_id="sess_beta", provider="azure", model="gpt-4o")

    rec1 = store.get_session_record("sess_alpha")
    assert rec1 is not None
    assert rec1.id == "sess_alpha"
    assert rec1.provider == "bedrock"
    assert rec1.model == "claude-haiku"

    all_recs = store.list_sessions()
    assert len(all_recs) == 2
    ids = [r.id for r in all_recs]
    assert "sess_alpha" in ids
    assert "sess_beta" in ids
