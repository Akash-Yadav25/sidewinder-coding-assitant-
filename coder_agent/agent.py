"""Core Agent Loop orchestration for Coder Agent."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from coder_agent.types import AgentResult, Message, ToolCall, ToolResult

if TYPE_CHECKING:
    from coder_agent.config import Config
    from coder_agent.context import ContextBuilder
    from coder_agent.logger import setup_logger
    from coder_agent.providers.base import LLMProvider
    from coder_agent.safety import SafetyGuard
    from coder_agent.tools import ToolRegistry
    from coder_agent.ui import UI


class Agent:
    """Autonomous coding agent loop handling planning, tool execution, test verification, and recovery."""

    def __init__(
        self,
        provider: LLMProvider,
        tools: ToolRegistry,
        context: ContextBuilder,
        safety: SafetyGuard,
        config: Config,
        ui: UI,
        logger: logging.Logger | None = None,
    ):
        self.provider = provider
        self.tools = tools
        self.context = context
        self.safety = safety
        self.config = config
        self.ui = ui
        self.logger = logger or logging.getLogger("coder_agent")
        self.messages: list[dict[str, Any]] = []

    def _build_system_prompt(self, project_context: str) -> str:
        return f"""You are a senior AI software engineer and autonomous coding agent CLI.
Your goal is to inspect codebases, implement precise modifications, run builds and tests, diagnose any failures, fix them, and report results cleanly.

# Core Operating Principles
1. **Understand First**: Explore the existing codebase structure with `list_directory`, `search_code`, and `read_file` before making any assumptions or modifications.
2. **Precision & Preservation**: Preserve existing style, naming conventions, and unrelated functionality. Avoid unintended edits.
3. **Verification**: Always run existing unit tests or test commands using `run_command` to verify your changes. If tests fail, analyze the error output and iteratively fix your code until tests pass.
4. **Actionable Communication**: State your concise plan, execute tools, and upon finishing provide a clear summary of all modified files and verified test results.

# Available Tools
- `read_file`: Read specific files or line slices (with line numbers).
- `write_file`: Create new files or overwrite existing files.
- `delete_file`: Delete unnecessary files (subject to confirmation).
- `list_directory`: Recursively inspect directory tree.
- `search_code`: Regex search across all code files.
- `run_command`: Run tests, linters, package builds, or scripts.

{project_context}
"""

    def _track_tool_side_effects(
        self, tool_call: ToolCall, tool_result: ToolResult, result: AgentResult
    ) -> None:
        """Record created, modified, deleted files and commands into the AgentResult."""
        name = tool_call.name
        inputs = tool_call.input or {}

        if name == "run_command":
            cmd_str = inputs.get("command", "")
            exit_code = 0
            if "exit code " in tool_result.content:
                try:
                    part = tool_result.content.split("exit code ")[1].split("]")[0]
                    exit_code = int(part)
                except Exception:
                    exit_code = 1 if tool_result.is_error else 0
            elif tool_result.is_error:
                exit_code = 1
            result.commands_run.append({"command": cmd_str, "exit_code": exit_code})

        if tool_result.is_error:
            result.errors.append(f"Tool {name} failed: {tool_result.content[:150]}")
            return

        if name == "write_file":
            filepath = inputs.get("path", "")
            if "Created new file" in tool_result.content:
                if filepath not in result.files_created:
                    result.files_created.append(filepath)
            else:
                if filepath not in result.files_modified and filepath not in result.files_created:
                    result.files_modified.append(filepath)

        elif name == "delete_file":
            filepath = inputs.get("path", "")
            if filepath not in result.files_deleted:
                result.files_deleted.append(filepath)

    def run(self, requirement: str) -> AgentResult:
        """Execute the complete agent lifecycle for a user coding requirement."""
        result = AgentResult(success=True, summary="")

        self.ui.info(f"Initializing task with provider: {self.ui.bold(self.provider.name)}")

        # 1. Analyze and build project context
        with self.ui.spinner("Analyzing project context..."):
            project_context = self.context.build(self.config.project_dir)

        system_prompt = self._build_system_prompt(project_context)

        # 2. Seed message history
        self.messages.append({"role": "user", "content": requirement})
        self.logger.info("Starting agent loop for requirement: %s", requirement)

        iteration = 0
        while iteration < self.config.max_iterations:
            iteration += 1
            step_header = f"Step {iteration}/{self.config.max_iterations}"
            self.logger.debug("--- %s ---", step_header)

            # 3. Stream or request response from LLM
            stream_gen = self.provider.stream_message(
                system=system_prompt,
                messages=self.messages,
                tools=self.tools.get_definitions(),
            )

            assistant_text_chunks: list[str] = []
            final_message: Message | None = None

            try:
                for chunk in stream_gen:
                    if isinstance(chunk, str):
                        assistant_text_chunks.append(chunk)
                        self.ui.stream_token(chunk)
                    elif isinstance(chunk, Message):
                        final_message = chunk
            except Exception as e:
                self.logger.error("LLM generation failed: %s", e)
                result.success = False
                result.errors.append(f"LLM communication error: {e}")
                self.ui.error(f"LLM communication error: {e}")
                break

            if final_message is None:
                # If stream didn't yield final Message directly, construct from chunks
                final_message = Message(
                    role="assistant",
                    content="".join(assistant_text_chunks),
                    stop_reason="end_turn",
                )

            # Ensure newline after streamed tokens
            if assistant_text_chunks:
                print()

            # Track tokens
            result.total_tokens.add(final_message.usage)

            # Record assistant turn in conversation history
            self.messages.append(
                {
                    "role": "assistant",
                    "content": final_message.content,
                    "tool_calls": final_message.tool_calls,
                }
            )

            # Check if LLM finished without calling tools
            if final_message.stop_reason == "end_turn" and not final_message.tool_calls:
                self.logger.info("Agent concluded work with end_turn.")
                result.summary = final_message.content
                break

            # If LLM requested tool calls
            if final_message.tool_calls:
                tool_results: list[ToolResult] = []
                for tc in final_message.tool_calls:
                    args_summary = ", ".join(f"{k}={v!r}" for k, v in (tc.input or {}).items())
                    if len(args_summary) > 80:
                        args_summary = args_summary[:77] + "..."
                    self.ui.info(f"Tool Request: {self.ui.bold(tc.name)}({args_summary})")

                    # Execute tool
                    tool_res = self.tools.execute(tc)
                    tool_results.append(tool_res)

                    # Log & track
                    self._track_tool_side_effects(tc, tool_res, result)

                    if tool_res.is_error:
                        self.ui.warning(f"Tool {tc.name} reported error: {tool_res.content[:120]}")
                    else:
                        preview = tool_res.content.splitlines()[0] if tool_res.content else ""
                        if len(preview) > 100:
                            preview = preview[:97] + "..."
                        self.logger.debug("Tool %s executed: %s", tc.name, preview)

                # Record tool results in conversation history
                self.messages.append({"role": "tool_results", "results": tool_results})

        else:
            # Loop ended due to max iterations
            self.logger.warning("Agent reached max iterations without concluding.")
            result.success = False
            result.errors.append(f"Exceeded maximum limit of {self.config.max_iterations} iterations.")

        # Present structured summary
        self.ui.summary(result)
        return result
