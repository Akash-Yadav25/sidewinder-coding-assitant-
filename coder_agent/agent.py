"""Core Agent Loop orchestration for Coder Agent."""

from __future__ import annotations

import ast
import concurrent.futures
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from coder_agent.compactor import compact_history
from coder_agent.git import GitManager
from coder_agent.providers.cost import calculate_cost
from coder_agent.storage.db import SessionStore
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
        session_id: str | None = None,
        storage: SessionStore | None = None,
    ):
        self.provider = provider
        self.tools = tools
        self.context = context
        self.safety = safety
        self.config = config
        self.ui = ui
        self.logger = logger or logging.getLogger("coder_agent")
        self.git = GitManager(config.project_dir)
        self.storage = storage or SessionStore(config.project_dir)
        provider_name = str(getattr(provider, "name", "unknown")) if provider else ""
        model_name = str(config.model) if config and config.model else ""
        self.session_id = session_id or self.storage.create_session(
            provider=provider_name, model=model_name
        )
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
- `edit_file`: Make precise, targeted changes to existing files by replacing unique snippets. ALWAYS prefer this over write_file for existing code!
- `write_file`: Create brand new files or completely rewrite files.
- `delete_file`: Delete unnecessary files (subject to confirmation).
- `list_directory`: Recursively inspect directory tree.
- `search_code`: Regex search across all code files.
- `run_command`: Run tests, linters, package builds, or scripts.
- `run_tests`: Run targeted tests with framework auto-detection and concise failure diagnostics.
- `git_diff`: View git diff of modified files to verify your changes or inspect repository state.

{project_context}
"""

    def _track_tool_side_effects(
        self, tool_call: ToolCall, tool_result: ToolResult, result: AgentResult
    ) -> None:
        """Record created, modified, deleted files and commands into the AgentResult."""
        name = tool_call.name
        inputs = tool_call.input or {}

        if name in ("run_command", "run_tests"):
            cmd_str = inputs.get("command", "") if name == "run_command" else f"run_tests {inputs.get('targets', '')}"
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

        if name in ("write_file", "edit_file"):
            filepath = inputs.get("path", "")
            if name == "write_file" and "Created new file" in tool_result.content:
                if filepath not in result.files_created:
                    result.files_created.append(filepath)
            else:
                if filepath not in result.files_modified and filepath not in result.files_created:
                    result.files_modified.append(filepath)

        elif name == "delete_file":
            filepath = inputs.get("path", "")
            if filepath not in result.files_deleted:
                result.files_deleted.append(filepath)

    def _run_self_review(self, result: AgentResult) -> list[str]:
        """Perform autonomous self-review of modified files (AST syntax & sanity check)."""
        review_errors: list[str] = []
        project_path = Path(self.config.project_dir)

        for rel_file in result.files_modified + result.files_created:
            fpath = project_path / rel_file
            if not fpath.is_file():
                continue

            # Python AST syntax check
            if fpath.suffix.lower() == ".py":
                try:
                    content = fpath.read_text(encoding="utf-8", errors="replace")
                    ast.parse(content, filename=str(fpath))
                except SyntaxError as syn_err:
                    msg = (
                        f"Self-Review Error: SyntaxError in '{rel_file}' at line {syn_err.lineno}: "
                        f"{syn_err.msg}. Please fix this syntax error before concluding."
                    )
                    review_errors.append(msg)
                    self.logger.warning(msg)

        return review_errors

    def run(self, requirement: str) -> AgentResult:
        """Execute the complete agent lifecycle for a user coding requirement."""
        result = AgentResult(success=True, summary="")

        # 0. Create pre-task checkpoint for instant rollback / recovery
        checkpoint_id = self.git.create_checkpoint(description=f"pre-task: {requirement[:40]}")
        result.checkpoint_id = checkpoint_id

        self.ui.info(f"Initializing task with provider: {self.ui.bold(self.provider.name)}")

        # 1. Analyze and build project context
        with self.ui.spinner("Analyzing project context..."):
            project_context = self.context.build(self.config.project_dir)

        system_prompt = self._build_system_prompt(project_context)

        # 2. Seed message history
        self.messages.append({"role": "user", "content": requirement})
        try:
            self.storage.save_message(self.session_id, role="user", content=requirement)
        except Exception as e:
            self.logger.debug("Failed to persist user message: %s", e)
        self.logger.info("Starting agent loop for requirement: %s", requirement)

        iteration = 0
        while iteration < self.config.max_iterations:
            iteration += 1
            step_header = f"Step {iteration}/{self.config.max_iterations}"
            self.logger.debug("--- %s ---", step_header)

            # Auto-compact conversation history if approaching token limits
            token_budget = max(20000, self.config.max_tokens * 3)
            self.messages = compact_history(self.messages, token_budget=token_budget)

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
            except KeyboardInterrupt:
                self.ui.warning("\n[Interrupted generation with Ctrl+C]")
                result.success = False
                result.errors.append("User interrupted LLM generation with Ctrl+C")
                break
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
            try:
                self.storage.save_message(
                    self.session_id,
                    role="assistant",
                    content=final_message.content,
                    tool_calls=final_message.tool_calls,
                )
            except Exception as e:
                self.logger.debug("Failed to persist assistant message: %s", e)

            # Check if LLM finished without calling tools
            if final_message.stop_reason == "end_turn" and not final_message.tool_calls:
                review_errors = self._run_self_review(result)
                if review_errors and iteration < self.config.max_iterations:
                    self.ui.warning(
                        f"[Self-Review]: Issues found: {len(review_errors)}. Triggering correction turn..."
                    )
                    self.messages.append(
                        {
                            "role": "user",
                            "content": "\n".join(review_errors),
                        }
                    )
                    continue

                if review_errors:
                    result.success = False
                    result.errors.extend(review_errors)

                self.logger.info("Agent concluded work with end_turn.")
                result.summary = final_message.content
                if result.files_modified or result.files_created:
                    count = len(result.files_modified) + len(result.files_created)
                    result.summary += f"\n[Self-Review: Verified {count} files, AST syntax valid]"
                break

            # If LLM requested tool calls
            if final_message.tool_calls:
                tool_results: list[ToolResult] = []
                interrupted_tools = False

                read_only_tool_names = {"read_file", "search_code", "list_directory", "git_diff"}
                can_parallelize = len(final_message.tool_calls) > 1 and all(
                    tc.name in read_only_tool_names for tc in final_message.tool_calls
                )

                if can_parallelize:
                    self.ui.info(
                        f"Executing {len(final_message.tool_calls)} read-only requests in parallel..."
                    )
                    with concurrent.futures.ThreadPoolExecutor(
                        max_workers=min(4, len(final_message.tool_calls))
                    ) as executor:
                        future_to_tc = {
                            executor.submit(self.tools.execute, tc): tc
                            for tc in final_message.tool_calls
                        }
                        for future in concurrent.futures.as_completed(future_to_tc):
                            tc = future_to_tc[future]
                            try:
                                tool_res = future.result()
                            except Exception as e:
                                tool_res = ToolResult(
                                    tool_use_id=tc.id,
                                    content=f"Error executing {tc.name}: {e}",
                                    is_error=True,
                                )
                            tool_results.append(tool_res)
                            self._track_tool_side_effects(tc, tool_res, result)
                else:
                    for tc in final_message.tool_calls:
                        args_summary = ", ".join(f"{k}={v!r}" for k, v in (tc.input or {}).items())
                        if len(args_summary) > 80:
                            args_summary = args_summary[:77] + "..."
                        self.ui.info(f"Tool Request: {self.ui.bold(tc.name)}({args_summary})")

                        # Execute tool
                        try:
                            tool_res = self.tools.execute(tc)
                        except KeyboardInterrupt:
                            self.ui.warning(f"\n[Tool {tc.name} interrupted by user with Ctrl+C]")
                            tool_res = ToolResult(
                                tool_use_id=tc.id,
                                content="Operation interrupted by user (Ctrl+C).",
                                is_error=True,
                            )
                            interrupted_tools = True

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

                        if interrupted_tools:
                            break

                # Record tool results in conversation history
                self.messages.append({"role": "tool_results", "results": tool_results})
                try:
                    self.storage.save_message(
                        self.session_id, role="tool_results", results=tool_results
                    )
                except Exception as e:
                    self.logger.debug("Failed to persist tool results: %s", e)
                if interrupted_tools:
                    result.success = False
                    result.errors.append("Execution interrupted by user (Ctrl+C)")
                    break

        else:
            # Loop ended due to max iterations
            self.logger.warning("Agent reached max iterations without concluding.")
            result.success = False
            result.errors.append(f"Exceeded maximum limit of {self.config.max_iterations} iterations.")

        # Compute cost
        result.total_cost = calculate_cost(
            self.config.provider, self.config.model, result.total_tokens
        )

        # Present structured summary
        self.ui.summary(result)
        return result
