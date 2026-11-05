"""AWS Bedrock Converse API provider implementation."""

from __future__ import annotations

import os
from typing import Any, Generator

import boto3
from botocore.config import Config as BotoConfig

from coder_agent.config import Config
from coder_agent.providers.base import LLMProvider
from coder_agent.types import Message, TokenUsage, ToolCall, ToolDefinition


class BedrockProvider(LLMProvider):
    """AWS Bedrock integration using the standardized Converse API."""

    def __init__(self, config: Config):
        region = config.aws_region or os.environ.get("AWS_REGION") or "us-east-1"
        boto_kwargs: dict[str, Any] = {
            "service_name": "bedrock-runtime",
            "region_name": region,
            "config": BotoConfig(retries={"max_attempts": 3, "mode": "standard"}),
        }

        # Optional explicit credentials
        if config.aws_access_key_id:
            boto_kwargs["aws_access_key_id"] = config.aws_access_key_id
        if config.aws_secret_access_key:
            boto_kwargs["aws_secret_access_key"] = config.aws_secret_access_key
        if config.aws_session_token:
            boto_kwargs["aws_session_token"] = config.aws_session_token

        self.client = boto3.client(**boto_kwargs)
        self.model = config.model or "anthropic.claude-sonnet-4-20250514-v1:0"
        self.max_tokens = config.max_tokens

    @property
    def name(self) -> str:
        return f"bedrock ({self.model})"

    def _format_tools(self, tools: list[ToolDefinition]) -> dict[str, Any]:
        return {
            "tools": [
                {
                    "toolSpec": {
                        "name": t.name,
                        "description": t.description,
                        "inputSchema": {"json": t.parameters},
                    }
                }
                for t in tools
            ]
        }

    def _format_messages(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        formatted = []
        for m in messages:
            role = m.get("role")
            if role == "user":
                formatted.append({"role": "user", "content": [{"text": m.get("content", "")}]})
            elif role == "assistant":
                blocks: list[dict[str, Any]] = []
                text_content = m.get("content", "")
                if text_content:
                    blocks.append({"text": text_content})
                for tc in m.get("tool_calls", []):
                    blocks.append(
                        {
                            "toolUse": {
                                "toolUseId": tc.id,
                                "name": tc.name,
                                "input": tc.input,
                            }
                        }
                    )
                if not blocks:
                    blocks.append({"text": ""})
                formatted.append({"role": "assistant", "content": blocks})
            elif role == "tool_results":
                blocks = []
                for res in m.get("results", []):
                    blocks.append(
                        {
                            "toolResult": {
                                "toolUseId": res.tool_use_id,
                                "content": [{"text": res.content}],
                                "status": "error" if res.is_error else "success",
                            }
                        }
                    )
                formatted.append({"role": "user", "content": blocks})
        return formatted

    def _parse_response(self, response: dict[str, Any]) -> Message:
        output_msg = response.get("output", {}).get("message", {})
        raw_content = output_msg.get("content", [])

        text_parts = []
        tool_calls: list[ToolCall] = []

        for block in raw_content:
            if "text" in block:
                text_parts.append(block["text"])
            elif "toolUse" in block:
                tu = block["toolUse"]
                tool_calls.append(
                    ToolCall(
                        id=tu.get("toolUseId", ""),
                        name=tu.get("name", ""),
                        input=tu.get("input", {}),
                    )
                )

        stop_reason = "tool_use" if response.get("stopReason") == "tool_use" else "end_turn"
        usage_data = response.get("usage", {})
        input_tokens = usage_data.get("inputTokens", 0)
        output_tokens = usage_data.get("outputTokens", 0)

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
            "modelId": self.model,
            "messages": self._format_messages(messages),
            "inferenceConfig": {"maxTokens": self.max_tokens},
        }
        if system:
            kwargs["system"] = [{"text": system}]
        if tools:
            kwargs["toolConfig"] = self._format_tools(tools)

        response = self.client.converse(**kwargs)
        return self._parse_response(response)

    def stream_message(
        self,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[ToolDefinition],
    ) -> Generator[str | Message, None, Message]:
        kwargs: dict[str, Any] = {
            "modelId": self.model,
            "messages": self._format_messages(messages),
            "inferenceConfig": {"maxTokens": self.max_tokens},
        }
        if system:
            kwargs["system"] = [{"text": system}]
        if tools:
            kwargs["toolConfig"] = self._format_tools(tools)

        response = self.client.converse_stream(**kwargs)
        stream = response.get("stream")

        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        stop_reason = "end_turn"
        input_tokens = 0
        output_tokens = 0

        current_tool_id = ""
        current_tool_name = ""
        current_tool_input_json = ""

        if stream:
            for event in stream:
                if "contentBlockStart" in event:
                    start = event["contentBlockStart"].get("start", {})
                    if "toolUse" in start:
                        tu = start["toolUse"]
                        current_tool_id = tu.get("toolUseId", "")
                        current_tool_name = tu.get("name", "")
                        current_tool_input_json = ""
                elif "contentBlockDelta" in event:
                    delta = event["contentBlockDelta"].get("delta", {})
                    if "text" in delta:
                        chunk = delta["text"]
                        text_parts.append(chunk)
                        yield chunk
                    elif "toolUse" in delta:
                        input_chunk = delta["toolUse"].get("input", "")
                        current_tool_input_json += input_chunk
                elif "contentBlockStop" in event:
                    if current_tool_name:
                        import json

                        try:
                            parsed_input = (
                                json.loads(current_tool_input_json)
                                if current_tool_input_json
                                else {}
                            )
                        except json.JSONDecodeError:
                            parsed_input = {}
                        tool_calls.append(
                            ToolCall(
                                id=current_tool_id,
                                name=current_tool_name,
                                input=parsed_input,
                            )
                        )
                        current_tool_name = ""
                        current_tool_id = ""
                        current_tool_input_json = ""
                elif "messageStop" in event:
                    stop_reason = (
                        "tool_use"
                        if event["messageStop"].get("stopReason") == "tool_use"
                        else "end_turn"
                    )
                elif "metadata" in event:
                    usage = event["metadata"].get("usage", {})
                    input_tokens = usage.get("inputTokens", 0)
                    output_tokens = usage.get("outputTokens", 0)

        final_msg = Message(
            role="assistant",
            content="".join(text_parts),
            tool_calls=tool_calls,
            stop_reason=stop_reason,
            usage=TokenUsage(input_tokens=input_tokens, output_tokens=output_tokens),
        )
        yield final_msg
        return final_msg
