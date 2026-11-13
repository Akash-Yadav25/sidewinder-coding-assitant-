"""Unit and integration tests for Model Context Protocol (MCP) subsystem."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from coder_agent.config import Config
from coder_agent.mcp.client import MCPClient
from coder_agent.mcp.registry import MCPRegistry
from coder_agent.safety import SafetyGuard
from coder_agent.tools import ToolRegistry
from coder_agent.types import ToolCall
from coder_agent.ui import UI

# Mini stdio JSON-RPC MCP server script for testing
MOCK_SERVER_SCRIPT = """
import sys, json

for line in sys.stdin:
    if not line.strip(): continue
    req = json.loads(line)
    method = req.get("method")
    req_id = req.get("id")

    if method == "initialize":
        res = {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "test-mock-server", "version": "1.0.0"}
            }
        }
        sys.stdout.write(json.dumps(res) + "\\n")
        sys.stdout.flush()

    elif method == "notifications/initialized":
        pass  # Notification, no response

    elif method == "tools/list":
        res = {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "tools": [
                    {
                        "name": "echo",
                        "description": "Echo input message back",
                        "inputSchema": {
                            "type": "object",
                            "properties": {"message": {"type": "string"}},
                            "required": ["message"]
                        }
                    }
                ]
            }
        }
        sys.stdout.write(json.dumps(res) + "\\n")
        sys.stdout.flush()

    elif method == "tools/call":
        params = req.get("params", {})
        msg = params.get("arguments", {}).get("message", "")
        res = {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "content": [{"type": "text", "text": f"Echo: {msg}"}]
            }
        }
        sys.stdout.write(json.dumps(res) + "\\n")
        sys.stdout.flush()
"""


def test_mcp_client_handshake_and_call(tmp_path: Path):
    server_script = tmp_path / "mock_mcp.py"
    server_script.write_text(MOCK_SERVER_SCRIPT, encoding="utf-8")

    client = MCPClient(
        server_name="mock",
        command=sys.executable,
        args=[str(server_script)],
        cwd=tmp_path,
    )
    client.start()
    try:
        init_res = client.initialize()
        assert init_res.get("serverInfo", {}).get("name") == "test-mock-server"

        tools = client.list_tools()
        assert len(tools) == 1
        assert tools[0]["name"] == "echo"

        call_res = client.call_tool("echo", {"message": "hello antigravity"})
        assert "Echo: hello antigravity" in call_res
    finally:
        client.stop()


def test_mcp_registry_and_tool_adapter(tmp_path: Path):
    server_script = tmp_path / "mock_mcp.py"
    server_script.write_text(MOCK_SERVER_SCRIPT, encoding="utf-8")

    # Create .coder-agent/mcp.json
    dot_dir = tmp_path / ".coder-agent"
    dot_dir.mkdir(parents=True, exist_ok=True)
    mcp_json = dot_dir / "mcp.json"
    mcp_json.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "testserv": {
                        "command": sys.executable,
                        "args": [str(server_script)],
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    cfg = Config(project_dir=str(tmp_path), approval_mode="never")
    safety = SafetyGuard(cfg)
    ui = UI(use_colors=False)

    registry = ToolRegistry(project_dir=str(tmp_path), safety=safety, ui=ui, config=cfg)
    try:
        defs = registry.get_definitions()
        mcp_defs = [d for d in defs if d.name.startswith("mcp_testserv_")]
        assert len(mcp_defs) == 1
        assert mcp_defs[0].name == "mcp_testserv_echo"

        # Execute MCP tool via ToolRegistry
        tc = ToolCall(
            id="call_1",
            name="mcp_testserv_echo",
            input={"message": "automated test"},
        )
        res = registry.execute(tc)
        assert not res.is_error
        assert "Echo: automated test" in res.content
    finally:
        registry.shutdown()
