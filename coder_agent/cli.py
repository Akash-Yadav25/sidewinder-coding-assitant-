"""Command-Line Interface entry point for Coder Agent."""

from __future__ import annotations

import argparse
import sys

from coder_agent import __version__
from coder_agent.agent import Agent
from coder_agent.config import load_config
from coder_agent.context import ContextBuilder
from coder_agent.interactive import start_interactive
from coder_agent.logger import setup_logger
from coder_agent.providers import create_provider
from coder_agent.safety import SafetyGuard
from coder_agent.tools import ToolRegistry
from coder_agent.ui import UI


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments using standard argparse."""
    parser = argparse.ArgumentParser(
        prog="coder-agent",
        description="Autonomous AI Coding Agent CLI — inspect codebases, implement changes, and verify with tests.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  coder-agent "Fix the pagination bug in api/routes.py"
  coder-agent -i
  coder-agent -p bedrock -m anthropic.claude-sonnet-4-20250514-v1:0 "Add unit tests"
  coder-agent -p azure -m gpt-4o "Refactor logger to use structured JSON"
  coder-agent -p ollama -m qwen3 "Implement healthcheck endpoint"
        """,
    )

    parser.add_argument(
        "requirement",
        nargs="?",
        help="Natural language coding requirement to execute directly",
    )
    parser.add_argument(
        "-i",
        "--interactive",
        action="store_true",
        help="Start interactive REPL mode for multi-turn sessions",
    )
    parser.add_argument(
        "-p",
        "--provider",
        choices=["anthropic", "bedrock", "azure", "ollama"],
        help="LLM provider: anthropic (default), bedrock, azure, or ollama",
    )
    parser.add_argument(
        "-m",
        "--model",
        help="Model ID or deployment name (e.g. claude-sonnet-4-20250514, gpt-4o, qwen3)",
    )
    parser.add_argument(
        "--approval",
        choices=["always", "destructive", "never"],
        help="Approval mode: destructive (default), always, or never",
    )
    parser.add_argument(
        "--project-dir",
        default=".",
        help="Target project directory (default: current directory)",
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        help="Maximum loop iterations per requirement (default: 40)",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        help="Maximum tokens per LLM completion (default: 8192)",
    )
    parser.add_argument(
        "--log-level",
        choices=["debug", "info", "warn", "error"],
        default="info",
        help="Logging verbosity written to stderr (default: info)",
    )
    parser.add_argument(
        "-v",
        "--version",
        action="version",
        version=f"coder-agent {__version__}",
    )

    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Main CLI execution flow."""
    args = parse_args(argv)
    ui = UI()

    # Load configuration
    config = load_config(vars(args))
    logger = setup_logger(config.log_level)

    # Initialize Provider
    try:
        provider = create_provider(config)
    except Exception as e:
        ui.error(f"Configuration error: {e}")
        return 1

    # Initialize core subsystems
    safety = SafetyGuard(config)
    context = ContextBuilder(config)
    tools = ToolRegistry(
        project_dir=config.project_dir,
        safety=safety,
        ui=ui,
        config=config,
    )

    # Dispatch to interactive mode or direct execution
    if args.interactive or not args.requirement:
        return start_interactive(
            config=config,
            provider=provider,
            tools=tools,
            context=context,
            safety=safety,
            ui=ui,
            logger=logger,
        )
    else:
        agent = Agent(
            provider=provider,
            tools=tools,
            context=context,
            safety=safety,
            config=config,
            ui=ui,
            logger=logger,
        )
        result = agent.run(args.requirement)
        return 0 if result.success else 1


if __name__ == "__main__":
    sys.exit(main())
