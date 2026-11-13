"""Interactive REPL mode for multi-turn sessions with Coder Agent."""

from __future__ import annotations

import logging
import sys
from typing import TYPE_CHECKING

from coder_agent import __version__
from coder_agent.agent import Agent
from coder_agent.commands import SlashCommandHandler
from coder_agent.compactor import estimate_message_tokens
from coder_agent.types import TokenUsage

if TYPE_CHECKING:
    from coder_agent.config import Config
    from coder_agent.context import ContextBuilder
    from coder_agent.providers.base import LLMProvider
    from coder_agent.safety import SafetyGuard
    from coder_agent.tools import ToolRegistry
    from coder_agent.ui import UI



def start_interactive(
    config: Config,
    provider: LLMProvider,
    tools: ToolRegistry,
    context: ContextBuilder,
    safety: SafetyGuard,
    ui: UI,
    logger: logging.Logger,
    session_id: str | None = None,
) -> int:
    """Launch the interactive REPL loop with conversation continuity and signal trapping."""
    banner = f"""
{ui.bold('┌────────────────────────────────────────────────────────┐')}
{ui.bold('│')}  {ui.cyan('Coder Agent')} v{__version__} — AI Autonomous Coding CLI          {ui.bold('│')}
{ui.bold('├────────────────────────────────────────────────────────┤')}
{ui.bold('│')}  Provider:    {ui.green(provider.name.ljust(39))} {ui.bold('│')}
{ui.bold('│')}  Project Dir: {ui.yellow(config.project_dir[:39].ljust(39))} {ui.bold('│')}
{ui.bold('│')}  Approval:    {config.approval_mode.ljust(39)} {ui.bold('│')}
{ui.bold('└────────────────────────────────────────────────────────┘')}
Type a coding request, {ui.cyan('/help')} for commands, or {ui.cyan('/exit')} to quit.
"""
    print(banner)

    # Maintain single persistent Agent instance across REPL turns for conversational continuity
    agent = Agent(
        provider=provider,
        tools=tools,
        context=context,
        safety=safety,
        config=config,
        ui=ui,
        logger=logger,
        session_id=session_id,
    )

    if session_id:
        prior_messages = agent.storage.get_session_messages(agent.session_id)
        if prior_messages:
            agent.messages = prior_messages
            ui.info(f"Resumed session {ui.bold(agent.session_id)} ({len(prior_messages)} messages loaded)")

    cumulative_tokens = TokenUsage()
    last_checkpoint_id: str | None = None
    interrupted_once = False
    cmd_handler = SlashCommandHandler(agent=agent, ui=ui, config=config)

    while True:
        try:
            tokens_in_history = estimate_message_tokens(agent.messages)
            token_indicator = f" [{tokens_in_history:,} tok]" if tokens_in_history > 0 else ""
            prompt_str = f"{ui.bold(ui.cyan('coder-agent'))}{ui.dim(token_indicator)}> "
            user_input = input(prompt_str).strip()
            interrupted_once = False
        except KeyboardInterrupt:
            if interrupted_once:
                print("\nExiting session.")
                break
            interrupted_once = True
            print(f"\n{ui.dim('Press Ctrl+C again or type /exit to quit.')}")
            continue
        except EOFError:
            print("\nExiting session.")
            break

        if not user_input:
            continue

        # Handle slash commands via dedicated handler
        cmd_result = cmd_handler.handle(user_input, cumulative_tokens, last_checkpoint_id)
        if cmd_result.handled:
            if cmd_result.should_exit:
                break
            if cmd_result.new_checkpoint_id is not None:
                last_checkpoint_id = cmd_result.new_checkpoint_id
            continue

        # Execute coding requirement
        try:
            result = agent.run(user_input)
            cumulative_tokens.add(result.total_tokens)
            if result.checkpoint_id:
                last_checkpoint_id = result.checkpoint_id
        except KeyboardInterrupt:
            ui.warning("\n[Task interrupted by user (Ctrl+C). Returning to prompt.]")
        except Exception as e:
            ui.error(f"Task failed with error: {e}")
            logger.exception("Error executing interactive task")

        print()

    return 0
