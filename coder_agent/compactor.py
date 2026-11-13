"""Context compaction, token estimation, and history budgeting."""

from __future__ import annotations

import logging
from typing import Any

from coder_agent.types import ToolResult

logger = logging.getLogger("coder_agent.compactor")


def estimate_tokens(text: str) -> int:
    """Fast estimation of token count (~4 chars per token)."""
    if not text:
        return 0
    return max(1, len(text) // 4)


def estimate_message_tokens(messages: list[dict[str, Any]]) -> int:
    """Calculate the estimated total token count of a message list."""
    total = 0
    for m in messages:
        role = m.get("role", "")
        total += 2  # overhead per message
        content = m.get("content", "")
        if isinstance(content, str):
            total += estimate_tokens(content)

        # Tool calls in assistant turns
        for tc in m.get("tool_calls", []):
            total += 10 + estimate_tokens(tc.name) + estimate_tokens(str(tc.input))

        # Tool results
        for res in m.get("results", []):
            if isinstance(res, ToolResult):
                total += 10 + estimate_tokens(res.content)
            elif isinstance(res, dict):
                total += 10 + estimate_tokens(res.get("content", ""))

    return total


def truncate_older_tool_results(
    messages: list[dict[str, Any]],
    max_recent_turns_to_preserve: int = 4,
    max_chars: int = 2500,
) -> list[dict[str, Any]]:
    """Truncate verbose outputs from older tool results while keeping recent turns intact."""
    if len(messages) <= max_recent_turns_to_preserve:
        return messages

    cutoff_idx = len(messages) - max_recent_turns_to_preserve
    updated_messages: list[dict[str, Any]] = []

    for idx, m in enumerate(messages):
        if idx >= cutoff_idx:
            updated_messages.append(m)
            continue

        if m.get("role") == "tool_results":
            condensed_results = []
            for res in m.get("results", []):
                if isinstance(res, ToolResult):
                    c = res.content
                    if len(c) > max_chars:
                        lines = c.splitlines()
                        head = "\n".join(lines[:20])
                        tail = "\n".join(lines[-15:])
                        truncated_content = (
                            f"{head}\n\n... [Output truncated: {len(lines) - 35} lines omitted for token efficiency] ...\n\n{tail}"
                        )
                        condensed_results.append(
                            ToolResult(
                                tool_use_id=res.tool_use_id,
                                content=truncated_content,
                                is_error=res.is_error,
                            )
                        )
                    else:
                        condensed_results.append(res)
                else:
                    condensed_results.append(res)
            updated_messages.append({"role": "tool_results", "results": condensed_results})
        else:
            updated_messages.append(m)

    return updated_messages


def compact_history(
    messages: list[dict[str, Any]],
    token_budget: int = 24000,
    keep_recent_count: int = 4,
) -> list[dict[str, Any]]:
    """Compact middle conversation history when token budget is exceeded."""
    current_tokens = estimate_message_tokens(messages)
    if current_tokens <= token_budget or len(messages) <= (keep_recent_count + 2):
        return messages

    logger.info(
        "Estimated history tokens (%d) exceed budget (%d). Compacting conversation history...",
        current_tokens,
        token_budget,
    )

    # 1. Truncate older tool outputs first
    messages = truncate_older_tool_results(messages, max_recent_turns_to_preserve=keep_recent_count)
    if estimate_message_tokens(messages) <= token_budget:
        return messages

    # 2. Extract initial requirement and recent turns
    initial_user_msg = messages[0]
    middle_msgs = messages[1:-keep_recent_count]
    recent_msgs = messages[-keep_recent_count:]

    # 3. Synthesize summary of actions taken in middle turns
    actions_taken: list[str] = []
    for m in middle_msgs:
        role = m.get("role")
        if role == "assistant":
            for tc in m.get("tool_calls", []):
                name = tc.name
                target = tc.input.get("path") or tc.input.get("command") or tc.input.get("pattern") or ""
                actions_taken.append(f"- Called `{name}` on `{target}`")
        elif role == "tool_results":
            for res in m.get("results", []):
                if isinstance(res, ToolResult) and res.is_error:
                    actions_taken.append(f"  ↳ Error occurred: {res.content[:100]}...")

    summary_text = (
        "## Summary of Prior Actions Taken & Milestones\n"
        "The conversation history was compacted to optimize token budget. Below is the record of completed actions:\n"
        + ("\n".join(actions_taken[:30]) if actions_taken else "Previous exploration and verification steps completed.")
        + "\n\nPlease continue work based on the active state and recent context below."
    )

    milestone_msg = {
        "role": "user",
        "content": f"[SYSTEM RECOVERY & CONVERSATION MILESTONE]\n{summary_text}",
    }

    compacted = [initial_user_msg, milestone_msg] + recent_msgs
    new_token_count = estimate_message_tokens(compacted)
    logger.info("Compacted history from %d to %d tokens.", current_tokens, new_token_count)
    return compacted
