"""Comprehensive unit tests for all workspace tools."""

from __future__ import annotations

from pathlib import Path

import pytest

from coder_agent.tools import ToolRegistry
from coder_agent.types import ToolCall


class TestReadFile:
    def test_read_existing_file(self, tool_registry: ToolRegistry, tmp_project: Path):
        call = ToolCall(id="1", name="read_file", input={"path": "main.py"})
        result = tool_registry.execute(call)
        assert not result.is_error
        assert "def add(a, b):" in result.content
        assert "    1 | def add(a, b):" in result.content

    def test_read_with_line_range(self, tool_registry: ToolRegistry, tmp_project: Path):
        call = ToolCall(
            id="2",
            name="read_file",
            input={"path": "main.py", "start_line": 1, "end_line": 2},
        )
        result = tool_registry.execute(call)
        assert not result.is_error
        assert "def add(a, b):" in result.content
        assert "divide" not in result.content

    def test_read_nonexistent_file(self, tool_registry: ToolRegistry):
        call = ToolCall(id="3", name="read_file", input={"path": "does_not_exist.py"})
        result = tool_registry.execute(call)
        assert result.is_error
        assert "File not found" in result.content

    def test_read_rejects_path_traversal(self, tool_registry: ToolRegistry):
        call = ToolCall(id="4", name="read_file", input={"path": "../../etc/passwd"})
        result = tool_registry.execute(call)
        assert result.is_error
        assert "Security violation" in result.content


class TestWriteFile:
    def test_create_new_file_in_new_dir(self, tool_registry: ToolRegistry, tmp_project: Path):
        new_path = "nested/deep/module.py"
        content = "VALUE = 42\n"
        call = ToolCall(id="1", name="write_file", input={"path": new_path, "content": content})
        result = tool_registry.execute(call)
        assert not result.is_error
        assert "Created new file" in result.content
        assert (tmp_project / "nested" / "deep" / "module.py").read_text(encoding="utf-8") == content

    def test_overwrite_existing_file(self, tool_registry: ToolRegistry, tmp_project: Path):
        updated_content = "def add(a, b):\n    return a + b + 10\n"
        call = ToolCall(
            id="2",
            name="write_file",
            input={"path": "main.py", "content": updated_content},
        )
        result = tool_registry.execute(call)
        assert not result.is_error
        assert "Updated existing file" in result.content
        assert (tmp_project / "main.py").read_text(encoding="utf-8") == updated_content

    def test_write_rejects_path_traversal(self, tool_registry: ToolRegistry):
        call = ToolCall(
            id="3",
            name="write_file",
            input={"path": "../forbidden.py", "content": "bad code"},
        )
        result = tool_registry.execute(call)
        assert result.is_error
        assert "Security violation" in result.content


class TestDeleteFile:
    def test_delete_existing_file(self, tool_registry: ToolRegistry, tmp_project: Path):
        target = tmp_project / "to_delete.txt"
        target.write_text("temporary", encoding="utf-8")
        assert target.exists()

        call = ToolCall(id="1", name="delete_file", input={"path": "to_delete.txt"})
        result = tool_registry.execute(call)
        assert not result.is_error
        assert not target.exists()

    def test_delete_nonexistent_file(self, tool_registry: ToolRegistry):
        call = ToolCall(id="2", name="delete_file", input={"path": "ghost.txt"})
        result = tool_registry.execute(call)
        assert result.is_error
        assert "does not exist" in result.content


class TestListDirectory:
    def test_list_project_structure(self, tool_registry: ToolRegistry):
        call = ToolCall(id="1", name="list_directory", input={"path": "."})
        result = tool_registry.execute(call)
        assert not result.is_error
        assert "main.py" in result.content
        assert "test_main.py" in result.content
        assert "utils/" in result.content

    def test_list_respects_depth(self, tool_registry: ToolRegistry, tmp_project: Path):
        deep = tmp_project / "level1" / "level2" / "level3"
        deep.mkdir(parents=True)
        (deep / "deep_file.txt").write_text("hello", encoding="utf-8")

        call = ToolCall(id="2", name="list_directory", input={"path": ".", "max_depth": 1})
        result = tool_registry.execute(call)
        assert not result.is_error
        assert "level1/" in result.content
        assert "deep_file.txt" not in result.content


class TestSearchCode:
    def test_search_pattern_match(self, tool_registry: ToolRegistry):
        call = ToolCall(id="1", name="search_code", input={"pattern": "def divide"})
        result = tool_registry.execute(call)
        assert not result.is_error
        assert "main.py:4: def divide(a, b):" in result.content

    def test_search_with_filter(self, tool_registry: ToolRegistry):
        call = ToolCall(
            id="2",
            name="search_code",
            input={"pattern": "def ", "file_pattern": "test_*.py"},
        )
        result = tool_registry.execute(call)
        assert not result.is_error
        assert "test_main.py:3: def test_add():" in result.content
        assert "\nmain.py:" not in result.content

    def test_search_invalid_regex(self, tool_registry: ToolRegistry):
        call = ToolCall(id="3", name="search_code", input={"pattern": "[unclosed"})
        result = tool_registry.execute(call)
        assert result.is_error
        assert "Invalid regular expression" in result.content


class TestRunCommand:
    def test_run_successful_command(self, tool_registry: ToolRegistry):
        call = ToolCall(
            id="1",
            name="run_command",
            input={"command": "python3 -c \"print('Hello from tool')\""},
        )
        result = tool_registry.execute(call)
        assert not result.is_error
        assert "exit code 0" in result.content
        assert "Hello from tool" in result.content

    def test_run_failing_command(self, tool_registry: ToolRegistry):
        call = ToolCall(
            id="2",
            name="run_command",
            input={"command": "python3 -c \"import sys; sys.exit(42)\""},
        )
        result = tool_registry.execute(call)
        assert result.is_error
        assert "exit code 42" in result.content

    def test_blocks_dangerous_command(self, tool_registry: ToolRegistry):
        call = ToolCall(
            id="3",
            name="run_command",
            input={"command": "rm -rf /"},
        )
        result = tool_registry.execute(call)
        assert result.is_error
        assert "Security violation" in result.content
