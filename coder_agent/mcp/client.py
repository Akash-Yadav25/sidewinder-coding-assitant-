"""Lightweight native stdio JSON-RPC 2.0 client for Model Context Protocol (MCP) servers."""

from __future__ import annotations

import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Any

logger = logging.getLogger("coder_agent.mcp.client")


class MCPClient:
    """Client communicating with an external MCP server process over stdio."""

    def __init__(
        self,
        server_name: str,
        command: str,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
        cwd: Path | None = None,
    ):
        self.server_name = server_name
        self.command = command
        self.args = args or []
        self.env = {**os.environ, **(env or {})}
        self.cwd = cwd
        self.process: subprocess.Popen[str] | None = None
        self._request_id = 0

    def start(self) -> None:
        """Spawn the MCP server process."""
        full_cmd = [self.command] + self.args
        logger.debug("Starting MCP server '%s': %s", self.server_name, full_cmd)
        self.process = subprocess.Popen(
            full_cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            cwd=str(self.cwd) if self.cwd else None,
            env=self.env,
        )

    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    def _send_request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Send a JSON-RPC request and wait synchronously for the response line."""
        if not self.process or not self.process.stdin or not self.process.stdout:
            raise RuntimeError(f"MCP server '{self.server_name}' is not running.")

        req_id = self._next_id()
        payload = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": params or {},
        }

        req_line = json.dumps(payload) + "\n"
        self.process.stdin.write(req_line)
        self.process.stdin.flush()

        resp_line = self.process.stdout.readline()
        if not resp_line:
            raise RuntimeError(f"MCP server '{self.server_name}' closed stdout unexpectedly.")

        resp = json.loads(resp_line.strip())
        if "error" in resp:
            raise RuntimeError(f"MCP error from '{self.server_name}': {resp['error']}")

        return resp.get("result", {})

    def _send_notification(self, method: str, params: dict[str, Any] | None = None) -> None:
        """Send a JSON-RPC notification (no id, no expected response)."""
        if not self.process or not self.process.stdin:
            return

        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params or {},
        }
        req_line = json.dumps(payload) + "\n"
        self.process.stdin.write(req_line)
        self.process.stdin.flush()

    def initialize(self) -> dict[str, Any]:
        """Perform MCP initialize handshake."""
        result = self._send_request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "clientInfo": {"name": "coder-agent", "version": "2.0.0"},
            },
        )
        self._send_notification("notifications/initialized")
        return result

    def list_tools(self) -> list[dict[str, Any]]:
        """Query server for its list of available tools."""
        result = self._send_request("tools/list")
        return result.get("tools", [])

    def call_tool(self, name: str, arguments: dict[str, Any]) -> str:
        """Execute a tool on the MCP server."""
        result = self._send_request("tools/call", {"name": name, "arguments": arguments})
        content_items = result.get("content", [])
        text_outputs = []
        for item in content_items:
            if isinstance(item, dict) and item.get("type") == "text":
                text_outputs.append(item.get("text", ""))
            else:
                text_outputs.append(str(item))

        return "\n".join(text_outputs) if text_outputs else json.dumps(result)

    def stop(self) -> None:
        """Gracefully terminate the MCP process."""
        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=2.0)
            except Exception:
                try:
                    self.process.kill()
                except Exception:
                    pass
            self.process = None
