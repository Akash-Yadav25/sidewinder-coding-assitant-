"""Model Context Protocol (MCP) integration subsystem."""

from __future__ import annotations

from coder_agent.mcp.client import MCPClient
from coder_agent.mcp.registry import MCPRegistry

__all__ = ["MCPClient", "MCPRegistry"]
