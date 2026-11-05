"""Anthropic Claude API provider implementation."""

from __future__ import annotations

import os
from typing import Any, Generator

import anthropic

from coder_agent.config import Config
from coder_agent.providers.base import LLMProvider
from coder_agent.types import Message, TokenUsage, ToolCall, ToolDefinition


class AnthropicProvider(LLMProvider):
    """Direct provider integration with Anthropic Claude API."""

    def __init__(self, config: Config):
        api_key = config.anthropic_api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError(
                "Missing Anthropic API Key. Set ANTHROPIC_API_KEY environment variable "
                "or define it in .env / .coder-agent.json"
            )
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = config.model or "claude-sonnet-4-20250514"
        self.max_tokens = config.max_tokens

    @property
    def name(self) -> str:
        return f"anthropic ({self.model})"

    def _format_tools(self, tools: list[ToolDefinition]) -> list[dict[str, Any]]:
        return [
            {
                "name": t.name,
                "description": t.description,
                "input_schema": t.parameters,
            }
            for t in tools
        ]

    def _format_messages(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        formatted = []
        for m in messages:
            role = m.get("role")
            if role == "user":
                formatted.append({"role": "user", "content": m.get("content", "")})
            elif role == "assistant":
                blocks = []
                text_content = m.get("content", "")
                if text_content:
                    blocks.append({"type": "text", "text": text_content})
                for tc in m.get("tool_calls", []):
                    blocks.append(
                        {
                            "type": "tool_use",
                            "id": tc.id,
                            "name": tc.name,
                            "input": tc.input,
                        }
                    )
                # Anthropic requires non-empty content
                if not blocks:
                    blocks.append({"type": "text", "text": ""})
                formatted.append({"role": "assistant", "content": blocks})
            elif role == "tool_results":
                blocks = []
                for res in m.get("results", []):
                    item: dict[str, Any] = {
                        "type": "tool_result",
                        "tool_use_id": res.tool_use_id,
                        "content": res.content,
                    }
                    if res.is_error:
                        item["is_error"] = True
                    blocks.append(item)
                formatted.append({"role": "user", "content": blocks})
        return formatted

    def _parse_response(self, raw_message: Any) -> Message:
        text_parts = []
        tool_calls: list[ToolCall] = []

        for block in raw_message.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append(
                    ToolCall(
                        id=block.id,
                        name=block.name,
                        input=block.input if isinstance(block.input, dict) else {},
                    )
                )

        stop_reason = "tool_use" if raw_message.stop_reason == "tool_use" else "end_turn"
        input_tokens = getattr(raw_message.usage, "input_tokens", 0)
        output_tokens = getattr(raw_message.usage, "output_tokens", 0)

        return Message(
            role="assistant",
            content="".join(text_parts),
            tool_calls=tool_calls,
            stop_reason=stop_reason,
            usage=TokenUsage(input_tokens=input_tokens, output_tokens=output_tokens),
        )

    def send_message(
        self,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[ToolDefinition],
    ) -> Message:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "messages": self._format_messages(messages),
        }
        if system:
            kwargs["system"] = system
        if tools:
            kwargs["tools"] = self._format_tools(tools)

        response = self.client.messages.create(**kwargs)
        return self._parse_response(response)

    def stream_message(
        self,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[ToolDefinition],
    ) -> Generator[str | Message, None, Message]:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "messages": self._format_messages(messages),
        }
        if system:
            kwargs["system"] = system
        if tools:
            kwargs["tools"] = self._format_tools(tools)

        with self.client.messages.stream(**kwargs) as stream:
            for text_chunk in stream.text_stream:
                yield text_chunk
            final_message = stream.get_final_message()

        parsed = self._parse_response(final_message)
        yield parsed
        return parsed
