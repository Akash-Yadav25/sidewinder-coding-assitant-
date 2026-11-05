"""Azure OpenAI Service provider implementation."""

from __future__ import annotations

import json
import os
from typing import Any, Generator

from openai import AzureOpenAI

from coder_agent.config import Config
from coder_agent.providers.base import LLMProvider
from coder_agent.types import Message, TokenUsage, ToolCall, ToolDefinition


class AzureOpenAIProvider(LLMProvider):
    """Azure OpenAI service integration using official OpenAI SDK."""

    def __init__(self, config: Config):
        endpoint = config.azure_endpoint or os.environ.get("AZURE_OPENAI_ENDPOINT")
        api_key = config.azure_api_key or os.environ.get("AZURE_OPENAI_API_KEY")
        api_version = (
            config.azure_api_version
            or os.environ.get("AZURE_OPENAI_API_VERSION")
            or "2024-10-01-preview"
        )

        if not endpoint:
            raise ValueError(
                "Missing Azure OpenAI Endpoint. Set AZURE_OPENAI_ENDPOINT environment variable "
                "or define it in .env / .coder-agent.json"
            )
        if not api_key:
            raise ValueError(
                "Missing Azure OpenAI API Key. Set AZURE_OPENAI_API_KEY environment variable "
                "or define it in .env / .coder-agent.json"
            )

        self.client = AzureOpenAI(
            azure_endpoint=endpoint,
            api_key=api_key,
            api_version=api_version,
        )
        self.model = config.model or "gpt-4o"
        self.max_tokens = config.max_tokens

    @property
    def name(self) -> str:
        return f"azure ({self.model})"

    def _format_tools(self, tools: list[ToolDefinition]) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
            }
            for t in tools
        ]

    def _format_messages(
        self, system: str, messages: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        formatted: list[dict[str, Any]] = []
        if system:
            formatted.append({"role": "system", "content": system})

        for m in messages:
            role = m.get("role")
            if role == "user":
                formatted.append({"role": "user", "content": m.get("content", "")})
            elif role == "assistant":
                item: dict[str, Any] = {"role": "assistant"}
                content = m.get("content", "")
                item["content"] = content if content else None

                tcs = m.get("tool_calls", [])
                if tcs:
                    item["tool_calls"] = [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.name,
                                "arguments": json.dumps(tc.input)
                                if isinstance(tc.input, dict)
                                else str(tc.input),
                            },
                        }
                        for tc in tcs
                    ]
                formatted.append(item)
            elif role == "tool_results":
                for res in m.get("results", []):
                    formatted.append(
                        {
                            "role": "tool",
                            "tool_call_id": res.tool_use_id,
                            "content": res.content,
                        }
                    )
        return formatted

    def _parse_response(self, response: Any) -> Message:
        choice = response.choices[0]
        msg = choice.message
        content = msg.content or ""
        tool_calls: list[ToolCall] = []

        if getattr(msg, "tool_calls", None):
            for tc in msg.tool_calls:
                fn = tc.function
                args_dict = {}
                if fn.arguments:
                    try:
                        args_dict = json.loads(fn.arguments)
                    except json.JSONDecodeError:
                        args_dict = {}
                tool_calls.append(
                    ToolCall(
                        id=tc.id,
                        name=fn.name,
                        input=args_dict,
                    )
                )

        stop_reason = "tool_use" if choice.finish_reason == "tool_calls" else "end_turn"
        prompt_tokens = getattr(response.usage, "prompt_tokens", 0) if response.usage else 0
        completion_tokens = (
            getattr(response.usage, "completion_tokens", 0) if response.usage else 0
        )

        return Message(
            role="assistant",
            content=content,
            tool_calls=tool_calls,
            stop_reason=stop_reason,
            usage=TokenUsage(input_tokens=prompt_tokens, output_tokens=completion_tokens),
        )

    def send_message(
        self,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[ToolDefinition],
    ) -> Message:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": self._format_messages(system, messages),
            "max_tokens": self.max_tokens,
        }
        if tools:
            kwargs["tools"] = self._format_tools(tools)
            kwargs["tool_choice"] = "auto"

        response = self.client.chat.completions.create(**kwargs)
        return self._parse_response(response)

    def stream_message(
        self,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[ToolDefinition],
    ) -> Generator[str | Message, None, Message]:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": self._format_messages(system, messages),
            "max_tokens": self.max_tokens,
            "stream": True,
        }
        if tools:
            kwargs["tools"] = self._format_tools(tools)
            kwargs["tool_choice"] = "auto"

        response_stream = self.client.chat.completions.create(**kwargs)

        text_chunks: list[str] = []
        tool_call_chunks: dict[int, dict[str, Any]] = {}
        finish_reason = "stop"

        for chunk in response_stream:
            if not chunk.choices:
                continue
            choice = chunk.choices[0]
            delta = choice.delta

            if delta.content:
                text_chunks.append(delta.content)
                yield delta.content

            if delta.tool_calls:
                for tc_delta in delta.tool_calls:
                    idx = tc_delta.index
                    if idx not in tool_call_chunks:
                        tool_call_chunks[idx] = {
                            "id": tc_delta.id or "",
                            "name": tc_delta.function.name or ""
                            if tc_delta.function
                            else "",
                            "arguments": "",
                        }
                    else:
                        if tc_delta.id:
                            tool_call_chunks[idx]["id"] = tc_delta.id
                        if tc_delta.function and tc_delta.function.name:
                            tool_call_chunks[idx]["name"] = tc_delta.function.name

                    if tc_delta.function and tc_delta.function.arguments:
                        tool_call_chunks[idx]["arguments"] += tc_delta.function.arguments

            if choice.finish_reason:
                finish_reason = choice.finish_reason

        tool_calls: list[ToolCall] = []
        for idx in sorted(tool_call_chunks.keys()):
            tc_data = tool_call_chunks[idx]
            try:
                args = (
                    json.loads(tc_data["arguments"])
                    if tc_data["arguments"]
                    else {}
                )
            except json.JSONDecodeError:
                args = {}
            tool_calls.append(
                ToolCall(
                    id=tc_data["id"] or f"call_{idx}",
                    name=tc_data["name"],
                    input=args,
                )
            )

        stop_reason = "tool_use" if finish_reason == "tool_calls" or tool_calls else "end_turn"

        final_msg = Message(
            role="assistant",
            content="".join(text_chunks),
            tool_calls=tool_calls,
            stop_reason=stop_reason,
            usage=TokenUsage(0, 0),
        )
        yield final_msg
        return final_msg
