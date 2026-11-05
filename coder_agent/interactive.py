"""Interactive REPL mode for multi-turn sessions with Coder Agent."""

from __future__ import annotations

import logging
import sys
from typing import TYPE_CHECKING

from coder_agent import __version__
from coder_agent.agent import Agent

if TYPE_CHECKING:
    from coder_agent.config import Config
    from coder_agent.context import ContextBuilder
    from coder_agent.providers.base import LLMProvider
    from coder_agent.safety import SafetyGuard
    from coder_agent.tools import ToolRegistry
    from coder_agent.ui import UI


def _print_help(ui: UI) -> None:
    print(f"\n{ui.bold('Available Interactive Commands:')}")
    print(f"  {ui.cyan('help')}              - Show this command guidance")
    print(f"  {ui.cyan('config')}            - Display current active configuration")
    print(f"  {ui.cyan('clear')}             - Clear the terminal screen")
    print(f"  {ui.cyan('exit')} or {ui.cyan('quit')}     - Terminate the session")
    print(f"\nOr type any natural-language coding task to execute.\n")


def start_interactive(
    config: Config,
    provider: LLMProvider,
    tools: ToolRegistry,
    context: ContextBuilder,
    safety: SafetyGuard,
    ui: UI,
    logger: logging.Logger,
) -> int:
    """Launch the interactive REPL loop."""
    banner = f"""
{ui.bold('┌────────────────────────────────────────────────────────┐')}
{ui.bold('│')}  {ui.cyan('Coder Agent')} v{__version__} — AI Autonomous Coding CLI          {ui.bold('│')}
{ui.bold('├────────────────────────────────────────────────────────┤')}
{ui.bold('│')}  Provider:    {ui.green(provider.name.ljust(39))} {ui.bold('│')}
{ui.bold('│')}  Project Dir: {ui.yellow(config.project_dir[:39].ljust(39))} {ui.bold('│')}
{ui.bold('│')}  Approval:    {config.approval_mode.ljust(39)} {ui.bold('│')}
{ui.bold('└────────────────────────────────────────────────────────┘')}
Type a coding request, {ui.cyan('help')} for options, or {ui.cyan('exit')} to quit.
"""
    print(banner)

    while True:
        try:
            prompt_str = f"{ui.bold(ui.cyan('coder-agent'))}> "
            user_input = input(prompt_str).strip()
        except (KeyboardInterrupt, EOFError):
            print("\nExiting session.")
            break

        if not user_input:
            continue

        cmd = user_input.lower()
        if cmd in ("exit", "quit", "q"):
            print("Goodbye.")
            break
        elif cmd == "help":
            _print_help(ui)
            continue
        elif cmd == "clear":
            sys.stdout.write("\033[2J\033[H")
            sys.stdout.flush()
            continue
        elif cmd == "config":
            print(f"\n{ui.bold('Active Configuration:')}")
            print(f"  Provider:         {config.provider}")
            print(f"  Model:            {config.model}")
            print(f"  Project Root:     {config.project_dir}")
            print(f"  Approval Mode:    {config.approval_mode}")
            print(f"  Max Iterations:   {config.max_iterations}")
            print(f"  Max Tokens:       {config.max_tokens}\n")
            continue

        agent = Agent(
            provider=provider,
            tools=tools,
            context=context,
            safety=safety,
            config=config,
            ui=ui,
            logger=logger,
        )
        try:
            agent.run(user_input)
        except Exception as e:
            ui.error(f"Task failed with error: {e}")
            logger.exception("Error executing interactive task")

        print()

    return 0
