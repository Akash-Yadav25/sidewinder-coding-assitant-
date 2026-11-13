"""Core Agent Loop orchestration for Coder Agent."""

from __future__ import annotations

import ast
import concurrent.futures
import logging
from pathlib import Path
import re
from typing import TYPE_CHECKING, Any

from coder_agent.compactor import compact_history
from coder_agent.git import GitManager
from coder_agent.providers.cost import calculate_cost
from coder_agent.storage.db import SessionStore
from coder_agent.types import (
    AgentPhase,
    AgentResult,
    Message,
    ToolCall,
    ToolResult,
    ValidationCheck,
)

if TYPE_CHECKING:
    from coder_agent.config import Config
    from coder_agent.context import ContextBuilder
    from coder_agent.logger import setup_logger
    from coder_agent.providers.base import LLMProvider
    from coder_agent.safety import SafetyGuard
    from coder_agent.tools import ToolRegistry
    from coder_agent.ui import UI


_PLAN_INJECTION = """\
╔══════════════════════════════════════════════════════╗
║  PHASE: PLAN                                         ║
╚══════════════════════════════════════════════════════╝
Before making any changes, analyze the task and produce a structured plan.
Use read_file, list_directory, search_code freely to explore the codebase.
Output your plan in this format:

<plan>
UNDERSTANDING: [what exactly is being asked]
ROOT_CAUSE: [what is broken or missing and why]
APPROACH: [high-level strategy]
STEPS:
  1. [specific action]
  2. [specific action]
VALIDATION_STRATEGY: [how you will verify BEHAVIORAL correctness, beyond just tests]
RISK_AREAS: [what could go wrong]
</plan>

State your plan clearly before proceeding.
"""

_ACT_INJECTION = """\
╔══════════════════════════════════════════════════════╗
║  PHASE: ACT                                          ║
╚══════════════════════════════════════════════════════╝
Execute your plan. Make all necessary code changes using edit_file / write_file.
You may run quick sanity checks (run_command, run_tests) during implementation
if it helps you, but comprehensive validation will occur in the next phase.
When done with all changes, summarize what was modified.
"""

_VALIDATE_INJECTION = """\
╔══════════════════════════════════════════════════════╗
║  PHASE: VALIDATE                                     ║
╚══════════════════════════════════════════════════════╝
Thoroughly validate your changes. Do NOT modify any files in this phase.
Run these checks in order and report each as PASS or FAIL:

1. TESTS: run_tests or run_command -> all pass?
2. STATIC ANALYSIS: run_linter (if applicable) -> any errors?
3. BEHAVIORAL: use verify_output or run_command to run the program with real inputs.
   Confirm the ACTUAL OUTPUT matches expected behavior.
   Do NOT just rely on unit tests passing — verify behavioral correctness!
4. REGRESSION: Ensure unrelated functionality is not broken.

Format your validation report clearly:
  [PASS] Tests: all passed
  [FAIL] Behavioral: expected '42' but got 'None'
  ...

If all critical checks pass, conclude with "VALIDATION COMPLETE — ALL CHECKS PASSED".
If any fail, conclude with "VALIDATION FAILED" and specify the exact failure details.
"""

_DIAGNOSE_INJECTION = """\
╔══════════════════════════════════════════════════════╗
║  PHASE: DIAGNOSE -> REPLAN                           ║
╚══════════════════════════════════════════════════════╝
One or more validation checks FAILED. Do not give up — analyze and replan.

1. DIAGNOSIS: What specifically went wrong? Why did the previous approach fail?
2. ROOT CAUSE UPDATE: Was the original root cause analysis accurate?
3. REVISED PLAN: Produce an updated <plan>...</plan> with the corrected approach.
4. Then proceed directly to making the fixes.
"""


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
        self._last_phase_history: list[str] = []
        self._last_plan_text: str = ""

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
- `run_linter`: Auto-detect and run mypy/ruff/flake8/eslint/cargo clippy for static analysis.
- `verify_output`: Run a command and assert it produces expected output. Use to verify BEHAVIORAL correctness.

{project_context}
"""

    def _track_tool_side_effects(
        self, tool_call: ToolCall, tool_result: ToolResult, result: AgentResult
    ) -> None:
        """Record created, modified, deleted files and commands into the AgentResult."""
        name = tool_call.name
        inputs = tool_call.input or {}

        if name in ("run_command", "run_tests", "verify_output", "run_linter"):
            if name == "run_command":
                cmd_str = inputs.get("command", "")
            elif name == "verify_output":
                cmd_str = f"verify_output: {inputs.get('command', '')}"
            elif name == "run_linter":
                cmd_str = f"run_linter: {inputs.get('path', '.')}"
            else:
                cmd_str = f"run_tests {inputs.get('targets', '')}"
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

    def _truncate_tool_output(self, content: str) -> str:
        """Truncate overly large tool outputs to prevent context explosion."""
        limit = getattr(self.config, "max_tool_output_chars", 6000)
        if len(content) <= limit:
            return content
        head = content[: limit // 2]
        tail = content[-(limit // 4) :]
        trimmed = len(content) - (limit // 2) - (limit // 4)
        return f"{head}\n... [{trimmed:,} chars trimmed — output too large] ...\n{tail}"

    def _estimate_complexity(self, requirement: str) -> str:
        """Estimate task complexity based on word count and domain keywords."""
        words = len(requirement.split())
        req_lower = requirement.lower()
        architectural_keywords = {
            "refactor",
            "migrate",
            "redesign",
            "entire",
            "all files",
            "overhaul",
            "restructure",
            "architecture",
            "rewrite",
        }
        general_keywords = {
            "implement",
            "integrate",
            "debug",
            "fix bug",
            "feature",
            "add",
            "replace",
        }
        threshold = getattr(self.config, "complexity_threshold_words", 25)
        if words >= threshold or any(kw in req_lower for kw in architectural_keywords):
            return "complex"
        if words >= 12 or any(kw in req_lower for kw in general_keywords):
            return "medium"
        return "simple"

    def _should_use_pav(self, requirement: str) -> bool:
        """Decide whether to engage the Plan->Act->Validate loop."""
        mode = getattr(self.config, "reasoning_mode", "auto").lower()
        if mode == "always":
            return True
        if mode == "never":
            return False
        # auto mode:
        words = len(requirement.split())
        threshold = getattr(self.config, "complexity_threshold_words", 25)
        architectural_keywords = {
            "refactor", "migrate", "redesign", "entire", "all files",
            "overhaul", "restructure", "architecture", "rewrite",
        }
        has_arch_kw = any(kw in requirement.lower() for kw in architectural_keywords)
        return words >= threshold or has_arch_kw

    def _show_phase(self, phase: str | AgentPhase, cycle: int) -> None:
        """Display a phase banner in the terminal."""
        phase_str = str(phase.value if isinstance(phase, AgentPhase) else phase)
        cycle_label = f" (retry {cycle})" if cycle > 0 else ""
        icons = {
            AgentPhase.PLAN.value: "🗺",
            AgentPhase.ACT.value: "⚡",
            AgentPhase.VALIDATE.value: "🔍",
            AgentPhase.DIAGNOSE.value: "🩺",
        }
        icon = icons.get(phase_str, "⟳")
        self.ui.phase_banner(icon, phase_str, cycle_label)

    def _extract_plan_block(self, text: str) -> str:
        """Extract content between <plan>...</plan> tags, or return summary."""
        m = re.search(r"<plan>(.*?)</plan>", text, re.DOTALL | re.IGNORECASE)
        return m.group(1).strip() if m else text.strip()

    def _parse_validation_checks(self, text: str) -> list[ValidationCheck]:
        """Parse [PASS]/[FAIL] markers from LLM validation output."""
        checks: list[ValidationCheck] = []
        for line in text.splitlines():
            m_pass = re.match(r"^.*\[PASS\]\s*(.+?)(?::\s*(.*))?$", line, re.IGNORECASE)
            m_fail = re.match(r"^.*\[FAIL\]\s*(.+?)(?::\s*(.*))?$", line, re.IGNORECASE)
            if m_pass:
                name = m_pass.group(1).strip()
                out = (m_pass.group(2) or "").strip()
                checks.append(ValidationCheck(name=name, passed=True, output=out))
            elif m_fail:
                name = m_fail.group(1).strip()
                out = (m_fail.group(2) or "").strip()
                checks.append(ValidationCheck(name=name, passed=False, output=out))

        if not checks:
            upper = text.upper()
            all_passed = ("ALL CHECKS PASSED" in upper or "VALIDATION COMPLETE" in upper) and ("FAIL" not in upper)
            checks.append(ValidationCheck(name="validation_overall", passed=all_passed, output=text[:200]))

        return checks

    def _persist_message(self, **kwargs) -> None:
        try:
            self.storage.save_message(self.session_id, **kwargs)
        except Exception as e:
            self.logger.debug("Failed to persist message: %s", e)

    def _run_inner_loop(self, result: AgentResult, system_prompt: str) -> AgentResult:
        """Core execution loop for a single phase or single requirement."""
        iteration = 0
        while iteration < self.config.max_iterations:
            iteration += 1
            step_header = f"Step {iteration}/{self.config.max_iterations}"
            self.logger.debug("--- %s ---", step_header)

            # Auto-compact conversation history if approaching token limits
            token_budget = max(20000, self.config.max_tokens * 3)
            self.messages = compact_history(self.messages, token_budget=token_budget)

            # Stream or request response from LLM
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
                final_message = Message(
                    role="assistant",
                    content="".join(assistant_text_chunks),
                    stop_reason="end_turn",
                )

            if assistant_text_chunks:
                print()

            result.total_tokens.add(final_message.usage)

            self.messages.append(
                {
                    "role": "assistant",
                    "content": final_message.content,
                    "tool_calls": final_message.tool_calls,
                }
            )
            self._persist_message(
                role="assistant",
                content=final_message.content,
                tool_calls=final_message.tool_calls,
            )

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
                            tool_res.content = self._truncate_tool_output(tool_res.content)
                            tool_results.append(tool_res)
                            self._track_tool_side_effects(tc, tool_res, result)
                else:
                    for tc in final_message.tool_calls:
                        args_summary = ", ".join(f"{k}={v!r}" for k, v in (tc.input or {}).items())
                        if len(args_summary) > 80:
                            args_summary = args_summary[:77] + "..."
                        self.ui.info(f"Tool Request: {self.ui.bold(tc.name)}({args_summary})")

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

                        tool_res.content = self._truncate_tool_output(tool_res.content)
                        tool_results.append(tool_res)
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

                self.messages.append({"role": "tool_results", "results": tool_results})
                self._persist_message(role="tool_results", results=tool_results)
                if interrupted_tools:
                    result.success = False
                    result.errors.append("Execution interrupted by user (Ctrl+C)")
                    break

        else:
            self.logger.warning("Agent reached max iterations without concluding.")
            result.success = False
            result.errors.append(f"Exceeded maximum limit of {self.config.max_iterations} iterations.")

        return result

    def run(self, requirement: str) -> AgentResult:
        """Execute the complete agent lifecycle for a user coding requirement."""
        # Reset per-run state so stale data from prior tasks doesn't bleed through
        self._last_phase_history = []
        self._last_plan_text = ""

        result = AgentResult(success=True, summary="")
        result.complexity = self._estimate_complexity(requirement)

        # 0. Create pre-task checkpoint for instant rollback / recovery
        checkpoint_id = self.git.create_checkpoint(description=f"pre-task: {requirement[:40]}")
        result.checkpoint_id = checkpoint_id

        self.ui.info(f"Initializing task with provider: {self.ui.bold(self.provider.name)}")

        # 1. Analyze and build project context
        with self.ui.spinner("Analyzing project context..."):
            project_context = self.context.build(self.config.project_dir)

        system_prompt = self._build_system_prompt(project_context)

        # Decide mode
        use_pav = self._should_use_pav(requirement)
        if use_pav:
            self.ui.info(f"[Reasoning Loop] Complexity: {result.complexity} -> PAV mode active")

        if not use_pav:
            # Simple flat mode - direct single-phase loop
            self.messages.append({"role": "user", "content": requirement})
            self._persist_message(role="user", content=requirement)
            self.logger.info("Starting agent loop for requirement: %s", requirement)
            self._run_inner_loop(result, system_prompt)
            result.total_cost = calculate_cost(
                self.config.provider, self.config.model, result.total_tokens
            )
            self.ui.summary(result)
            return result

        # --- PAV MODE ---
        self.logger.info("Starting PAV agent loop for requirement: %s", requirement)

        # 1. PLAN Phase
        self._show_phase(AgentPhase.PLAN, 0)
        result.phase_history.append(AgentPhase.PLAN.value)
        plan_message = _PLAN_INJECTION + "\n\nTask:\n" + requirement
        self.messages.append({"role": "user", "content": plan_message})
        self._persist_message(role="user", content=plan_message)

        plan_res = AgentResult(success=True, summary="")
        self._run_inner_loop(plan_res, system_prompt)
        result.total_tokens.add(plan_res.total_tokens)
        result.plan_text = self._extract_plan_block(plan_res.summary)
        self._last_plan_text = result.plan_text

        # 2. Cycles of ACT -> VALIDATE -> DIAGNOSE
        for cycle in range(self.config.max_replan_cycles + 1):
            if cycle > 0:
                # DIAGNOSE Phase
                self._show_phase(AgentPhase.DIAGNOSE, cycle)
                result.phase_history.append(f"{AgentPhase.DIAGNOSE.value}-{cycle}")
                failed = [c for c in result.validation_checks if not c.passed]
                failure_detail = (
                    "\n".join(f"  - [{c.name}]: {c.output[:300]}" for c in failed)
                    if failed
                    else "Validation failed."
                )
                diag_msg = _DIAGNOSE_INJECTION + f"\n\nFailed checks:\n{failure_detail}"
                self.messages.append({"role": "user", "content": diag_msg})
                self._persist_message(role="user", content=diag_msg)

                diag_res = AgentResult(success=True, summary="")
                self._run_inner_loop(diag_res, system_prompt)
                result.total_tokens.add(diag_res.total_tokens)
                revised = self._extract_plan_block(diag_res.summary)
                if revised:
                    result.plan_text = revised
                    self._last_plan_text = revised

            # ACT Phase
            self._show_phase(AgentPhase.ACT, cycle)
            result.phase_history.append(f"{AgentPhase.ACT.value}-{cycle}")
            act_msg = (
                _ACT_INJECTION
                if cycle == 0
                else _ACT_INJECTION + "\n\n(Proceeding with implementation according to revised plan)"
            )
            self.messages.append({"role": "user", "content": act_msg})
            self._persist_message(role="user", content=act_msg)

            act_res = AgentResult(success=True, summary="")
            self._run_inner_loop(act_res, system_prompt)
            result.total_tokens.add(act_res.total_tokens)

            # Merge file side effects and commands
            for f in act_res.files_modified:
                if f not in result.files_modified:
                    result.files_modified.append(f)
            for f in act_res.files_created:
                if f not in result.files_created:
                    result.files_created.append(f)
            for f in act_res.files_deleted:
                if f not in result.files_deleted:
                    result.files_deleted.append(f)
            result.commands_run.extend(act_res.commands_run)
            result.errors.extend(act_res.errors)
            result.summary = act_res.summary

            # VALIDATE Phase
            self._show_phase(AgentPhase.VALIDATE, cycle)
            result.phase_history.append(f"{AgentPhase.VALIDATE.value}-{cycle}")
            self.messages.append({"role": "user", "content": _VALIDATE_INJECTION})
            self._persist_message(role="user", content=_VALIDATE_INJECTION)

            val_res = AgentResult(success=True, summary="")
            self._run_inner_loop(val_res, system_prompt)
            result.total_tokens.add(val_res.total_tokens)
            result.commands_run.extend(val_res.commands_run)

            checks = self._parse_validation_checks(val_res.summary)
            result.validation_checks = checks

            critical_checks = [c for c in checks if c.is_critical]
            all_passed = bool(critical_checks) and all(c.passed for c in critical_checks)

            if all_passed:
                result.success = True
                result.replan_count = cycle
                break
            elif cycle >= self.config.max_replan_cycles:
                result.success = False
                failed_names = [c.name for c in checks if not c.passed]
                result.errors.append(
                    f"PAV loop exhausted after {cycle + 1} cycles. Failed checks: {failed_names}"
                )
                result.replan_count = cycle
                break

        self._last_phase_history = list(result.phase_history)
        result.total_cost = calculate_cost(
            self.config.provider, self.config.model, result.total_tokens
        )
        self.ui.summary(result)
        return result
