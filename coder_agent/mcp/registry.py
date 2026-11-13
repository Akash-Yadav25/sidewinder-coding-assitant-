"""MCP Server Registry and Tool Adapter."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from coder_agent.mcp.client import MCPClient
from coder_agent.types import ToolDefinition, ToolResult

if TYPE_CHECKING:
    from coder_agent.config import Config
    from coder_agent.safety import SafetyGuard
    from coder_agent.ui import UI

logger = logging.getLogger("coder_agent.mcp.registry")


class MCPRegistry:
    """Discovers configured MCP servers, initializes them, and exposes their tools."""

    def __init__(self, project_dir: str | Path):
        self.project_dir = Path(project_dir).resolve()
        self.clients: dict[str, MCPClient] = {}
        self.tool_definitions: list[ToolDefinition] = []
        self.handlers: dict[str, Callable] = {}
        self._load_and_initialize()

    def _find_config_file(self) -> Path | None:
        candidates = [
            self.project_dir / ".coder-agent" / "mcp.json",
            self.project_dir / "mcp.json",
        ]
        for c in candidates:
            if c.is_file():
                return c
        return None

    def _load_and_initialize(self) -> None:
        cfg_file = self._find_config_file()
        if not cfg_file:
            return

        try:
            cfg_data = json.loads(cfg_file.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning("Failed to parse MCP configuration file %s: %s", cfg_file, e)
            return

        servers_cfg = cfg_data.get("mcpServers", {})
        for s_name, s_info in servers_cfg.items():
            cmd = s_info.get("command")
            if not cmd:
                continue
            args = s_info.get("args", [])
            env = s_info.get("env", {})

            client = MCPClient(
                server_name=s_name,
                command=cmd,
                args=args,
                env=env,
                cwd=self.project_dir,
            )

            try:
                client.start()
                client.initialize()
                raw_tools = client.list_tools()

                self.clients[s_name] = client

                for rt in raw_tools:
                    tool_orig_name = rt.get("name", "")
                    tool_alias = f"mcp_{s_name}_{tool_orig_name}"
                    t_def = ToolDefinition(
                        name=tool_alias,
                        description=f"[{s_name}] {rt.get('description', '')}",
                        parameters=rt.get("inputSchema", {"type": "object", "properties": {}}),
                    )
                    self.tool_definitions.append(t_def)

                    # Create closure for execution
                    def _make_handler(cl: MCPClient, orig_name: str):
                        def _handler(
                            input_args: dict[str, Any],
                            project_dir: str,
                            safety: SafetyGuard,
                            ui: UI,
                            config: Config,
                        ) -> ToolResult:
                            try:
                                output = cl.call_tool(orig_name, input_args)
                                return ToolResult(tool_use_id="", content=output)
                            except Exception as err:
                                return ToolResult(tool_use_id="", content=f"MCP Error: {err}", is_error=True)

                        return _handler

                    self.handlers[tool_alias] = _make_handler(client, tool_orig_name)

                logger.info("Loaded %d tools from MCP server '%s'", len(raw_tools), s_name)

            except Exception as e:
                logger.warning("Failed to initialize MCP server '%s': %s", s_name, e)
                client.stop()

    def shutdown(self) -> None:
        """Terminate all active MCP server processes."""
        for name, client in self.clients.items():
            try:
                client.stop()
            except Exception:
                pass
        self.clients.clear()
