"""Provider-agnostic tool definitions using JSON Schema."""

from __future__ import annotations

from coder_agent.types import ToolDefinition

TOOL_DEFINITIONS: list[ToolDefinition] = [
    ToolDefinition(
        name="read_file",
        description="Read the contents of a file in the workspace. Returns numbered lines. Can read an entire file or a specific line slice.",
        parameters={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative path to the file to read",
                },
                "start_line": {
                    "type": "integer",
                    "description": "Optional start line number (1-based)",
                },
                "end_line": {
                    "type": "integer",
                    "description": "Optional end line number (1-based, inclusive)",
                },
            },
            "required": ["path"],
        },
    ),
    ToolDefinition(
        name="write_file",
        description="Create a new file or overwrite an existing file in the project directory. Creates parent directories if needed.",
        parameters={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative path to the file to write",
                },
                "content": {
                    "type": "string",
                    "description": "Complete new content to write to the file",
                },
            },
            "required": ["path", "content"],
        },
    ),
    ToolDefinition(
        name="delete_file",
        description="Delete a file from the workspace. Requires user confirmation.",
        parameters={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative path to the file to delete",
                },
            },
            "required": ["path"],
        },
    ),
    ToolDefinition(
        name="list_directory",
        description="Explore the project directory structure recursively, respecting ignored patterns like node_modules, .git, and virtual environments.",
        parameters={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative path of directory to list (default: '.')",
                },
                "max_depth": {
                    "type": "integer",
                    "description": "Maximum directory recursion depth (default: 3)",
                },
            },
        },
    ),
    ToolDefinition(
        name="search_code",
        description="Search for regex or text patterns across files in the project directory, skipping binary and ignored files.",
        parameters={
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Regular expression pattern or substring to search for",
                },
                "path": {
                    "type": "string",
                    "description": "Relative directory or file path to search within (default: '.')",
                },
                "file_pattern": {
                    "type": "string",
                    "description": "Glob pattern to filter filenames (e.g. '*.py', '*.ts', '*.json')",
                },
            },
            "required": ["pattern"],
        },
    ),
    ToolDefinition(
        name="run_command",
        description="Execute a shell command (e.g. pytest, npm test, python -m unittest, flake8, tsc, cargo test) in the project root to build, test, or check code.",
        parameters={
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The exact shell command line string to run",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds before terminating the process (default: 60)",
                },
            },
            "required": ["command"],
        },
    ),
]
