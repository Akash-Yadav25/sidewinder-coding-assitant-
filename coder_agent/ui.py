"""Terminal UI utilities using pure ANSI escape codes without external dependencies."""

from __future__ import annotations

import difflib
import sys
import threading
import time
from contextlib import contextmanager
from typing import Generator

from coder_agent.types import AgentResult


class Colors:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    UNDERLINE = "\033[4m"

    # Foreground colors
    BLACK = "\033[30m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"

    # Bright foreground colors
    BRIGHT_BLACK = "\033[90m"
    BRIGHT_RED = "\033[91m"
    BRIGHT_GREEN = "\033[92m"
    BRIGHT_YELLOW = "\033[93m"
    BRIGHT_BLUE = "\033[94m"
    BRIGHT_MAGENTA = "\033[95m"
    BRIGHT_CYAN = "\033[96m"
    BRIGHT_WHITE = "\033[97m"


class Spinner:
    """Non-blocking background spinner for long-running operations."""

    FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

    def __init__(self, message: str = "Working..."):
        self.message = message
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def _spin(self) -> None:
        idx = 0
        while not self._stop_event.is_set():
            frame = self.FRAMES[idx % len(self.FRAMES)]
            # Write to stdout with ANSI cyan
            sys.stdout.write(f"\r{Colors.CYAN}{frame}{Colors.RESET} {self.message}")
            sys.stdout.flush()
            idx += 1
            time.sleep(0.08)
        # Clear line on exit
        sys.stdout.write("\r\033[K")
        sys.stdout.flush()

    def start(self) -> None:
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._spin, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._thread is not None:
            self._stop_event.set()
            self._thread.join(timeout=1.0)
            self._thread = None


class UI:
    """Terminal UI wrapper for colored output, spinners, and interaction."""

    def __init__(self, use_colors: bool = True):
        self.use_colors = use_colors and sys.stdout.isatty()

    def _c(self, code: str, text: str) -> str:
        if not self.use_colors:
            return text
        return f"{code}{text}{Colors.RESET}"

    # Stylizers
    def bold(self, text: str) -> str:
        return self._c(Colors.BOLD, text)

    def dim(self, text: str) -> str:
        return self._c(Colors.DIM, text)

    def green(self, text: str) -> str:
        return self._c(Colors.GREEN, text)

    def red(self, text: str) -> str:
        return self._c(Colors.RED, text)

    def yellow(self, text: str) -> str:
        return self._c(Colors.YELLOW, text)

    def cyan(self, text: str) -> str:
        return self._c(Colors.CYAN, text)

    def blue(self, text: str) -> str:
        return self._c(Colors.BLUE, text)

    def magenta(self, text: str) -> str:
        return self._c(Colors.MAGENTA, text)

    # Status indicators
    def success(self, msg: str) -> None:
        print(f"{self.green('✓')} {msg}")

    def error(self, msg: str) -> None:
        print(f"{self.red('✗')} {msg}")

    def warning(self, msg: str) -> None:
        print(f"{self.yellow('⚠')} {msg}")

    def info(self, msg: str) -> None:
        print(f"{self.cyan('ℹ')} {msg}")

    def stream_token(self, token: str) -> None:
        """Stream an LLM token directly to stdout."""
        sys.stdout.write(token)
        sys.stdout.flush()

    @contextmanager
    def spinner(self, message: str) -> Generator[Spinner, None, None]:
        """Context manager for showing a spinner while executing a block."""
        s = Spinner(message)
        s.start()
        try:
            yield s
        finally:
            s.stop()

    def confirm(self, prompt: str, default: bool = False) -> bool:
        """Ask user for yes/no approval. Returns True if approved."""
        suffix = " [Y/n]: " if default else " [y/N]: "
        full_prompt = f"{self.yellow('?')} {self.bold(prompt)}{suffix}"
        try:
            answer = input(full_prompt).strip().lower()
            if not answer:
                return default
            return answer in ("y", "yes")
        except (KeyboardInterrupt, EOFError):
            print()
            return False

    def diff(self, old_content: str, new_content: str, filename: str) -> None:
        """Render a colorized unified diff between old and new file content."""
        old_lines = old_content.splitlines(keepends=True)
        new_lines = new_content.splitlines(keepends=True)
        diff_lines = list(
            difflib.unified_diff(
                old_lines,
                new_lines,
                fromfile=f"a/{filename}",
                tofile=f"b/{filename}",
                n=3,
            )
        )

        if not diff_lines:
            self.info(f"No changes detected in {filename}")
            return

        print(f"\n{self.bold('--- Diff for ' + filename + ' ---')}")
        for line in diff_lines:
            line_str = line.rstrip("\n")
            if line.startswith("+++") or line.startswith("---"):
                print(self.bold(line_str))
            elif line.startswith("@@"):
                print(self.cyan(line_str))
            elif line.startswith("+"):
                print(self.green(line_str))
            elif line.startswith("-"):
                print(self.red(line_str))
            else:
                print(f"  {line_str}")
        print(f"{self.bold('----------------------------')}\n")

    def file_tree(self, tree_str: str) -> None:
        """Print a formatted directory tree."""
        print(f"\n{self.bold('Directory Structure:')}")
        print(tree_str)

    def summary(self, result: AgentResult) -> None:
        """Display a structured summary of the completed task."""
        print()
        header = "Execution Summary"
        divider = "=" * 48
        print(self.bold(divider))
        print(self.bold(f" {header}"))
        print(self.bold(divider))

        status_str = self.green("SUCCESS") if result.success else self.red("FAILED")
        print(f"Status:          {status_str}")

        if result.files_created:
            print(f"Files Created:   {len(result.files_created)}")
            for f in result.files_created:
                print(f"  {self.green('+')} {f}")

        if result.files_modified:
            print(f"Files Modified:  {len(result.files_modified)}")
            for f in result.files_modified:
                print(f"  {self.yellow('~')} {f}")

        if result.files_deleted:
            print(f"Files Deleted:   {len(result.files_deleted)}")
            for f in result.files_deleted:
                print(f"  {self.red('-')} {f}")

        if result.commands_run:
            print(f"Commands Run:    {len(result.commands_run)}")
            for cmd in result.commands_run:
                code = cmd.get("exit_code", 0)
                code_str = self.green(f"exit {code}") if code == 0 else self.red(f"exit {code}")
                print(f"  {self.cyan('$')} {cmd.get('command')} ({code_str})")

        total_tok = result.total_tokens.input_tokens + result.total_tokens.output_tokens
        if total_tok > 0:
            print(f"Tokens Used:     {total_tok:,} (in: {result.total_tokens.input_tokens:,}, out: {result.total_tokens.output_tokens:,})")

        if result.errors:
            print(f"\n{self.red('Errors:')}")
            for err in result.errors:
                print(f"  • {err}")

        if result.summary:
            print(f"\n{self.bold('Result Details:')}")
            print(result.summary)

        print(self.bold(divider) + "\n")
