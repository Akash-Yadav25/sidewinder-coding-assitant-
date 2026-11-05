"""Configuration management for Coder Agent."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_EXCLUDES = [
    "node_modules",
    ".git",
    "dist",
    "build",
    "__pycache__",
    ".venv",
    "venv",
    ".tox",
    ".mypy_cache",
    ".pytest_cache",
    "*.pyc",
    "*.pyo",
    ".DS_Store",
]

DEFAULT_MODELS = {
    "anthropic": "claude-sonnet-4-20250514",
    "bedrock": "anthropic.claude-sonnet-4-20250514-v1:0",
    "azure": "gpt-4o",
    "ollama": "qwen3",
}


@dataclass
class Config:
    """Resolved configuration parameters."""

    # Active provider & model
    provider: str = "anthropic"
    model: str = ""

    # Provider specific credentials & settings
    anthropic_api_key: str = ""

    aws_region: str = "us-east-1"
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    aws_session_token: str = ""

    azure_endpoint: str = ""
    azure_api_key: str = ""
    azure_api_version: str = "2024-10-01-preview"

    ollama_base_url: str = "http://localhost:11434/v1"

    # Execution limits & behavior
    max_tokens: int = 8192
    max_iterations: int = 40
    project_dir: str = "."
    approval_mode: str = "destructive"  # "always" | "destructive" | "never"
    exclude_patterns: list[str] = field(default_factory=lambda: list(DEFAULT_EXCLUDES))
    max_file_size: int = 102400  # 100KB
    max_context_files: int = 50
    log_level: str = "info"


def _load_dotenv_if_present(env_path: Path) -> None:
    """Simple stdlib parser for .env files without external dependencies."""
    if not env_path.is_file():
        return
    try:
        content = env_path.read_text(encoding="utf-8")
        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, val = line.split("=", 1)
                key = key.strip()
                val = val.strip().strip("'\"")
                if key and key not in os.environ:
                    os.environ[key] = val
    except Exception:
        pass


def load_config(cli_args: dict[str, Any] | None = None) -> Config:
    """Merge configuration from defaults, .env, .coder-agent.json, env vars, and CLI flags."""
    cli_args = cli_args or {}

    # 1. Project Directory determines where we search for .env and .coder-agent.json
    project_dir_arg = cli_args.get("project_dir") or os.environ.get("CODER_AGENT_PROJECT_DIR") or "."
    project_path = Path(project_dir_arg).resolve()

    # Load .env if present in current dir or project dir
    _load_dotenv_if_present(Path(".env"))
    if project_path != Path(".").resolve():
        _load_dotenv_if_present(project_path / ".env")

    # 2. Check for .coder-agent.json in current or project dir
    file_cfg: dict[str, Any] = {}
    config_paths = [Path(".coder-agent.json"), project_path / ".coder-agent.json"]
    for cp in config_paths:
        if cp.is_file():
            try:
                file_cfg = json.loads(cp.read_text(encoding="utf-8"))
                break
            except Exception:
                pass

    # 3. Resolve Provider
    provider = (
        cli_args.get("provider")
        or os.environ.get("CODER_AGENT_PROVIDER")
        or file_cfg.get("provider")
        or "anthropic"
    ).lower()

    # 4. Resolve Model
    model = (
        cli_args.get("model")
        or os.environ.get("CODER_AGENT_MODEL")
        or file_cfg.get("model")
        or DEFAULT_MODELS.get(provider, "claude-sonnet-4-20250514")
    )

    # 5. Approval mode
    approval_mode = (
        cli_args.get("approval")
        or cli_args.get("approval_mode")
        or os.environ.get("CODER_AGENT_APPROVAL")
        or file_cfg.get("approval_mode")
        or "destructive"
    ).lower()

    # 6. Log level
    log_level = (
        cli_args.get("log_level")
        or os.environ.get("CODER_AGENT_LOG_LEVEL")
        or file_cfg.get("log_level")
        or "info"
    ).lower()

    # 7. Max limits
    max_tokens = int(
        cli_args.get("max_tokens")
        or os.environ.get("CODER_AGENT_MAX_TOKENS")
        or file_cfg.get("max_tokens")
        or 8192
    )
    max_iterations = int(
        cli_args.get("max_iterations")
        or os.environ.get("CODER_AGENT_MAX_ITERATIONS")
        or file_cfg.get("max_iterations")
        or 40
    )
    max_file_size = int(file_cfg.get("max_file_size") or 102400)
    max_context_files = int(file_cfg.get("max_context_files") or 50)
    exclude_patterns = file_cfg.get("exclude_patterns") or list(DEFAULT_EXCLUDES)

    # 8. Provider Credentials & Endpoints
    anthropic_api_key = (
        cli_args.get("anthropic_api_key")
        or os.environ.get("ANTHROPIC_API_KEY")
        or file_cfg.get("anthropic_api_key")
        or ""
    )

    aws_region = (
        cli_args.get("aws_region")
        or os.environ.get("AWS_REGION")
        or os.environ.get("AWS_DEFAULT_REGION")
        or file_cfg.get("aws_region")
        or "us-east-1"
    )
    aws_access_key_id = (
        os.environ.get("AWS_ACCESS_KEY_ID")
        or file_cfg.get("aws_access_key_id")
        or ""
    )
    aws_secret_access_key = (
        os.environ.get("AWS_SECRET_ACCESS_KEY")
        or file_cfg.get("aws_secret_access_key")
        or ""
    )
    aws_session_token = (
        os.environ.get("AWS_SESSION_TOKEN")
        or file_cfg.get("aws_session_token")
        or ""
    )

    azure_endpoint = (
        cli_args.get("azure_endpoint")
        or os.environ.get("AZURE_OPENAI_ENDPOINT")
        or file_cfg.get("azure_endpoint")
        or ""
    )
    azure_api_key = (
        cli_args.get("azure_api_key")
        or os.environ.get("AZURE_OPENAI_API_KEY")
        or file_cfg.get("azure_api_key")
        or ""
    )
    azure_api_version = (
        cli_args.get("azure_api_version")
        or os.environ.get("AZURE_OPENAI_API_VERSION")
        or file_cfg.get("azure_api_version")
        or "2024-10-01-preview"
    )

    ollama_base_url = (
        cli_args.get("ollama_base_url")
        or os.environ.get("OLLAMA_BASE_URL")
        or file_cfg.get("ollama_base_url")
        or "http://localhost:11434/v1"
    )

    return Config(
        provider=provider,
        model=model,
        anthropic_api_key=anthropic_api_key,
        aws_region=aws_region,
        aws_access_key_id=aws_access_key_id,
        aws_secret_access_key=aws_secret_access_key,
        aws_session_token=aws_session_token,
        azure_endpoint=azure_endpoint,
        azure_api_key=azure_api_key,
        azure_api_version=azure_api_version,
        ollama_base_url=ollama_base_url,
        max_tokens=max_tokens,
        max_iterations=max_iterations,
        project_dir=str(project_path),
        approval_mode=approval_mode,
        exclude_patterns=exclude_patterns,
        max_file_size=max_file_size,
        max_context_files=max_context_files,
        log_level=log_level,
    )
