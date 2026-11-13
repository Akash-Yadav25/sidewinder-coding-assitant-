"""Unit tests for configuration loading and resolution."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from coder_agent.config import DEFAULT_MODELS, Config, load_config


class TestConfig:
    def test_default_models_map(self):
        assert "anthropic" in DEFAULT_MODELS
        assert "bedrock" in DEFAULT_MODELS
        assert "azure" in DEFAULT_MODELS
        assert "ollama" in DEFAULT_MODELS

    def test_load_defaults(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("CODER_AGENT_PROVIDER", raising=False)
        monkeypatch.delenv("CODER_AGENT_MODEL", raising=False)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

        cfg = load_config({})
        assert cfg.provider == "anthropic"
        assert cfg.model == DEFAULT_MODELS["anthropic"]
        assert cfg.approval_mode == "destructive"
        assert cfg.max_iterations == 40
        assert cfg.max_tokens == 8192

    def test_load_from_env_vars(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("CODER_AGENT_PROVIDER", "azure")
        monkeypatch.setenv("CODER_AGENT_MODEL", "my-gpt-deployment")
        monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://test.openai.azure.com")
        monkeypatch.setenv("AZURE_OPENAI_API_KEY", "secret-key")
        monkeypatch.setenv("CODER_AGENT_APPROVAL", "always")

        cfg = load_config({})
        assert cfg.provider == "azure"
        assert cfg.model == "my-gpt-deployment"
        assert cfg.azure_endpoint == "https://test.openai.azure.com"
        assert cfg.azure_api_key == "secret-key"
        assert cfg.approval_mode == "always"

    def test_cli_overrides_env_and_defaults(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("CODER_AGENT_PROVIDER", "anthropic")
        monkeypatch.setenv("CODER_AGENT_MODEL", "claude-sonnet-4-20250514")

        cli_args = {
            "provider": "bedrock",
            "model": "anthropic.claude-opus-4-20250514-v1:0",
            "approval": "never",
            "max_iterations": 25,
        }
        cfg = load_config(cli_args)
        assert cfg.provider == "bedrock"
        assert cfg.model == "anthropic.claude-opus-4-20250514-v1:0"
        assert cfg.approval_mode == "never"
        assert cfg.max_iterations == 25

    def test_load_from_config_file(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        monkeypatch.chdir(tmp_path)
        cfg_file = tmp_path / ".coder-agent.json"
        cfg_file.write_text(
            json.dumps(
                {
                    "provider": "ollama",
                    "model": "llama3.3",
                    "max_iterations": 15,
                }
            ),
            encoding="utf-8",
        )

        cfg = load_config({})
        assert cfg.provider == "ollama"
        assert cfg.model == "llama3.3"
        assert cfg.max_iterations == 15

    def test_reasoning_defaults(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("CODER_AGENT_REASONING_MODE", raising=False)
        monkeypatch.delenv("CODER_AGENT_MAX_REPLAN_CYCLES", raising=False)
        monkeypatch.delenv("CODER_AGENT_COMPLEXITY_THRESHOLD_WORDS", raising=False)
        monkeypatch.delenv("CODER_AGENT_MAX_TOOL_OUTPUT_CHARS", raising=False)

        cfg = load_config({})
        assert cfg.reasoning_mode == "auto"
        assert cfg.max_replan_cycles == 3
        assert cfg.complexity_threshold_words == 25
        assert cfg.max_tool_output_chars == 6000

    def test_reasoning_env_vars(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("CODER_AGENT_REASONING_MODE", "always")
        monkeypatch.setenv("CODER_AGENT_MAX_REPLAN_CYCLES", "5")
        monkeypatch.setenv("CODER_AGENT_COMPLEXITY_THRESHOLD_WORDS", "30")
        monkeypatch.setenv("CODER_AGENT_MAX_TOOL_OUTPUT_CHARS", "10000")

        cfg = load_config({})
        assert cfg.reasoning_mode == "always"
        assert cfg.max_replan_cycles == 5
        assert cfg.complexity_threshold_words == 30
        assert cfg.max_tool_output_chars == 10000

    def test_reasoning_cli_overrides(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("CODER_AGENT_REASONING_MODE", "always")
        cli_args = {
            "reasoning_mode": "never",
            "max_replan_cycles": 2,
        }
        cfg = load_config(cli_args)
        assert cfg.reasoning_mode == "never"
        assert cfg.max_replan_cycles == 2

    def test_reasoning_config_file(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        monkeypatch.chdir(tmp_path)
        cfg_file = tmp_path / ".coder-agent.json"
        cfg_file.write_text(
            json.dumps(
                {
                    "reasoning_mode": "always",
                    "max_replan_cycles": 4,
                }
            ),
            encoding="utf-8",
        )
        cfg = load_config({})
        assert cfg.reasoning_mode == "always"
        assert cfg.max_replan_cycles == 4
