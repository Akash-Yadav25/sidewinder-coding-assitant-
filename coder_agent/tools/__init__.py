"""Tool registry and dispatcher for Coder Agent."""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from coder_agent.mcp.registry import MCPRegistry
from coder_agent.tools import (
    delete_file,
    edit_file,
    git_diff,
    list_directory,
    read_file,
    run_command,
    run_tests,
    search_code,
    write_file,
)
from coder_agent.tools.schemas import TOOL_DEFINITIONS
from coder_agent.types import ToolCall, ToolDefinition, ToolResult

if TYPE_CHECKING:
    from coder_agent.config import Config
    from coder_agent.safety import SafetyGuard
    from coder_agent.ui import UI


class ToolRegistry:
    """Manages and dispatches calls to workspace tools."""

    def __init__(self, project_dir: str, safety: SafetyGuard, ui: UI, config: Config):
        self.project_dir = project_dir
        self.safety = safety
        self.ui = ui
        self.config = config

        self._handlers: dict[str, Callable] = {
            "read_file": read_file.execute,
            "edit_file": edit_file.execute,
            "write_file": write_file.execute,
            "delete_file": delete_file.execute,
            "list_directory": list_directory.execute,
            "search_code": search_code.execute,
            "run_command": run_command.execute,
            "git_diff": git_diff.execute,
            "run_tests": run_tests.execute,
        }

        # Discover & register MCP tools if configured
        try:
            self.mcp = MCPRegistry(project_dir)
            self._handlers.update(self.mcp.handlers)
        except Exception:
            self.mcp = None

    def get_definitions(self) -> list[ToolDefinition]:
        """Return provider-agnostic definitions for all registered tools."""
        defs = list(TOOL_DEFINITIONS)
        if self.mcp:
            defs.extend(self.mcp.tool_definitions)
        return defs

    def shutdown(self) -> None:
        """Cleanup any active background tool processes or MCP servers."""
        if self.mcp:
            self.mcp.shutdown()

    def execute(self, tool_call: ToolCall) -> ToolResult:
        """Dispatch a tool call to its respective handler."""
        handler = self._handlers.get(tool_call.name)
        if not handler:
            return ToolResult(
                tool_use_id=tool_call.id,
                content=f"Error: Unknown tool '{tool_call.name}'. Available: {list(self._handlers.keys())}",
                is_error=True,
            )

        try:
            result: ToolResult = handler(
                input_args=tool_call.input or {},
                project_dir=self.project_dir,
                safety=self.safety,
                ui=self.ui,
                config=self.config,
            )
            result.tool_use_id = tool_call.id
            return result
        except Exception as e:
            return ToolResult(
                tool_use_id=tool_call.id,
                content=f"Error executing tool '{tool_call.name}': {e}",
                is_error=True,
            )
