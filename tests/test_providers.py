"""Unit tests for the multi-provider abstraction layer."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from coder_agent.config import Config
from coder_agent.providers import create_provider
from coder_agent.providers.anthropic_provider import AnthropicProvider
from coder_agent.providers.azure_openai_provider import AzureOpenAIProvider
from coder_agent.providers.bedrock_provider import BedrockProvider
from coder_agent.providers.ollama_provider import OllamaProvider
from coder_agent.types import Message, TokenUsage, ToolCall, ToolDefinition, ToolResult


@pytest.fixture
def sample_tool_defs() -> list[ToolDefinition]:
    return [
        ToolDefinition(
            name="dummy_tool",
            description="A test tool",
            parameters={
                "type": "object",
                "properties": {"arg1": {"type": "string"}},
                "required": ["arg1"],
            },
        )
    ]


class TestProviderFactory:
    def test_creates_anthropic(self):
        cfg = Config(provider="anthropic", anthropic_api_key="sk-test")
        p = create_provider(cfg)
        assert isinstance(p, AnthropicProvider)
        assert "anthropic" in p.name

    def test_creates_bedrock(self):
        cfg = Config(provider="bedrock", aws_region="us-west-2")
        p = create_provider(cfg)
        assert isinstance(p, BedrockProvider)
        assert "bedrock" in p.name

    def test_creates_azure(self):
        cfg = Config(
            provider="azure",
            azure_endpoint="https://test.openai.azure.com",
            azure_api_key="key",
        )
        p = create_provider(cfg)
        assert isinstance(p, AzureOpenAIProvider)
        assert "azure" in p.name

    def test_creates_ollama(self):
        cfg = Config(provider="ollama", ollama_base_url="http://localhost:11434/v1")
        p = create_provider(cfg)
        assert isinstance(p, OllamaProvider)
        assert "ollama" in p.name

    def test_rejects_unknown_provider(self):
        cfg = Config(provider="unknown_llm")
        with pytest.raises(ValueError, match="Unsupported provider"):
            create_provider(cfg)


class TestAnthropicProviderFormatting:
    def test_format_tools(self, sample_tool_defs):
        cfg = Config(provider="anthropic", anthropic_api_key="sk-test")
        p = AnthropicProvider(cfg)
        formatted = p._format_tools(sample_tool_defs)
        assert len(formatted) == 1
        assert formatted[0]["name"] == "dummy_tool"
        assert "input_schema" in formatted[0]

    def test_format_messages(self):
        cfg = Config(provider="anthropic", anthropic_api_key="sk-test")
        p = AnthropicProvider(cfg)
        messages = [
            {"role": "user", "content": "Hello"},
            {
                "role": "assistant",
                "content": "Let me run a tool",
                "tool_calls": [ToolCall(id="tc1", name="dummy_tool", input={"arg1": "val"})],
            },
            {
                "role": "tool_results",
                "results": [ToolResult(tool_use_id="tc1", content="Result content", is_error=False)],
            },
        ]
        formatted = p._format_messages(messages)
        assert len(formatted) == 3
        assert formatted[0]["role"] == "user"
        assert formatted[1]["role"] == "assistant"
        assert any(b["type"] == "tool_use" for b in formatted[1]["content"])
        assert formatted[2]["role"] == "user"
        assert formatted[2]["content"][0]["type"] == "tool_result"
        assert formatted[2]["content"][0]["tool_use_id"] == "tc1"


class TestBedrockProviderFormatting:
    def test_format_tools(self, sample_tool_defs):
        cfg = Config(provider="bedrock")
        p = BedrockProvider(cfg)
        formatted = p._format_tools(sample_tool_defs)
        assert "tools" in formatted
        tool_spec = formatted["tools"][0]["toolSpec"]
        assert tool_spec["name"] == "dummy_tool"
        assert "inputSchema" in tool_spec
        assert "json" in tool_spec["inputSchema"]

    def test_format_messages(self):
        cfg = Config(provider="bedrock")
        p = BedrockProvider(cfg)
        messages = [
            {"role": "user", "content": "Inspect code"},
            {
                "role": "assistant",
                "content": "Checking...",
                "tool_calls": [ToolCall(id="bed_1", name="dummy_tool", input={"arg1": "abc"})],
            },
            {
                "role": "tool_results",
                "results": [ToolResult(tool_use_id="bed_1", content="ok", is_error=False)],
            },
        ]
        formatted = p._format_messages(messages)
        assert len(formatted) == 3
        assert formatted[0]["content"][0]["text"] == "Inspect code"
        assert "toolUse" in formatted[1]["content"][1]
        assert formatted[2]["content"][0]["toolResult"]["toolUseId"] == "bed_1"


class TestAzureAndOllamaProviderFormatting:
    def test_format_tools(self, sample_tool_defs):
        cfg = Config(
            provider="azure",
            azure_endpoint="https://test.openai.azure.com",
            azure_api_key="key",
        )
        p = AzureOpenAIProvider(cfg)
        formatted = p._format_tools(sample_tool_defs)
        assert len(formatted) == 1
        assert formatted[0]["type"] == "function"
        assert formatted[0]["function"]["name"] == "dummy_tool"

    def test_format_messages(self):
        cfg = Config(
            provider="azure",
            azure_endpoint="https://test.openai.azure.com",
            azure_api_key="key",
        )
        p = AzureOpenAIProvider(cfg)
        messages = [
            {"role": "user", "content": "Help me code"},
            {
                "role": "assistant",
                "content": "Calling tool",
                "tool_calls": [ToolCall(id="call_99", name="dummy_tool", input={"arg1": "test"})],
            },
            {
                "role": "tool_results",
                "results": [ToolResult(tool_use_id="call_99", content="Output data", is_error=False)],
            },
        ]
        formatted = p._format_messages("System instruction", messages)
        assert formatted[0]["role"] == "system"
        assert formatted[1]["role"] == "user"
        assert formatted[2]["role"] == "assistant"
        assert formatted[2]["tool_calls"][0]["function"]["name"] == "dummy_tool"
        assert formatted[3]["role"] == "tool"
        assert formatted[3]["tool_call_id"] == "call_99"
        assert formatted[3]["content"] == "Output data"
