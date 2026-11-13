"""Evaluation harness for benchmarking Coder Agent performance and recovery."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from coder_agent.agent import Agent
from coder_agent.config import Config
from coder_agent.context import ContextBuilder
from coder_agent.providers.base import LLMProvider
from coder_agent.safety import SafetyGuard
from coder_agent.tools import ToolRegistry
from coder_agent.ui import UI

logger = logging.getLogger("coder_agent.evals")


@dataclass
class EvalTask:
    """Specification of an evaluation challenge."""

    task_id: str
    requirement: str
    setup_files: dict[str, str]
    verify_fn: Callable[[Path], bool]


@dataclass
class EvalReport:
    """Summary of benchmark run across evaluation challenges."""

    total_tasks: int = 0
    passed_tasks: int = 0
    failed_tasks: int = 0
    total_tokens: int = 0
    total_duration_sec: float = 0.0
    task_results: list[dict[str, Any]] = field(default_factory=list)


class EvalHarness:
    """Runs a suite of coding tasks and benchmarks agent accuracy and efficiency."""

    def __init__(self, workspace_root: Path):
        self.workspace_root = workspace_root

    def run_task(self, task: EvalTask, provider: LLMProvider) -> dict[str, Any]:
        """Execute a single evaluation challenge in an isolated temporary directory."""
        task_dir = self.workspace_root / f"eval_{task.task_id}"
        task_dir.mkdir(parents=True, exist_ok=True)

        # Setup files
        for rel_path, content in task.setup_files.items():
            fpath = task_dir / rel_path
            fpath.parent.mkdir(parents=True, exist_ok=True)
            fpath.write_text(content, encoding="utf-8")

        cfg = Config(
            project_dir=str(task_dir),
            approval_mode="never",
            max_iterations=15,
        )
        safety = SafetyGuard(cfg)
        context = ContextBuilder(cfg)
        ui = UI(use_colors=False)
        tools = ToolRegistry(str(task_dir), safety, ui, cfg)

        agent = Agent(
            provider=provider,
            tools=tools,
            context=context,
            safety=safety,
            config=cfg,
            ui=ui,
        )

        start_time = time.time()
        try:
            result = agent.run(task.requirement)
            duration = time.time() - start_time
            passed = task.verify_fn(task_dir) and result.success

            return {
                "task_id": task.task_id,
                "passed": passed,
                "duration_sec": duration,
                "tokens": result.total_tokens.input_tokens + result.total_tokens.output_tokens,
                "files_modified": result.files_modified,
                "errors": result.errors,
            }
        finally:
            tools.shutdown()

    def run_suite(self, tasks: list[EvalTask], provider: LLMProvider) -> EvalReport:
        """Run multiple benchmark tasks and compile summary report."""
        report = EvalReport(total_tasks=len(tasks))
        start_all = time.time()

        for t in tasks:
            res = self.run_task(t, provider)
            report.task_results.append(res)
            if res["passed"]:
                report.passed_tasks += 1
            else:
                report.failed_tasks += 1
            report.total_tokens += res["tokens"]

        report.total_duration_sec = time.time() - start_all
        return report
