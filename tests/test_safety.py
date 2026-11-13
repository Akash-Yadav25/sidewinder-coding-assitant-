"""Unit tests for SafetyGuard path validation and command inspection."""

from __future__ import annotations

from pathlib import Path

import pytest

from coder_agent.config import Config
from coder_agent.safety import SafetyGuard
from coder_agent.ui import UI


class TestSafetyGuard:
    def test_path_validation_allows_internal_paths(self, tmp_path: Path):
        cfg = Config(project_dir=str(tmp_path), approval_mode="never")
        guard = SafetyGuard(cfg)

        resolved = guard.validate_path("src/app.py")
        assert resolved == (tmp_path / "src" / "app.py").resolve()

    def test_path_validation_rejects_parent_traversal(self, tmp_path: Path):
        cfg = Config(project_dir=str(tmp_path), approval_mode="never")
        guard = SafetyGuard(cfg)

        with pytest.raises(ValueError, match="Security violation"):
            guard.validate_path("../../etc/passwd")

    def test_path_validation_rejects_absolute_path_outside_root(self, tmp_path: Path):
        cfg = Config(project_dir=str(tmp_path), approval_mode="never")
        guard = SafetyGuard(cfg)

        with pytest.raises(ValueError, match="Security violation"):
            guard.validate_path("/tmp/outside.txt")

    def test_path_validation_rejects_symlink_traversal(self, tmp_path: Path):
        cfg = Config(project_dir=str(tmp_path), approval_mode="never")
        guard = SafetyGuard(cfg)

        outside_target = tmp_path.parent / "outside_target.txt"
        outside_target.write_text("secret outside", encoding="utf-8")

        symlink_file = tmp_path / "sneaky_symlink.txt"
        symlink_file.symlink_to(outside_target)

        with pytest.raises(ValueError, match="Security violation.*outside project root"):
            guard.validate_path("sneaky_symlink.txt")

    def test_secret_redaction(self, tmp_path: Path):
        cfg = Config(project_dir=str(tmp_path), approval_mode="never")
        guard = SafetyGuard(cfg)

        leaked_prompt = (
            "My Anthropic key is sk-ant-api03-abcdef1234567890abcdef1234567890-test and "
            "AWS is AKIAIOSFODNN7EXAMPLE with token ghp_123456789012345678901234567890123456"
        )
        cleaned = guard.redact_secrets(leaked_prompt)
        assert "sk-ant-api03" not in cleaned
        assert "[REDACTED_ANTHROPIC_KEY]" in cleaned
        assert "AKIAIOSFODNN7EXAMPLE" not in cleaned
        assert "[REDACTED_AWS_KEY_ID]" in cleaned
        assert "ghp_12345" not in cleaned
        assert "[REDACTED_GITHUB_TOKEN]" in cleaned

    @pytest.mark.parametrize(
        "cmd",
        [
            "rm -rf /",
            "rm -rf ~",
            "sudo rm -rf ./tmp",
            "mkfs.ext4 /dev/sdb",
            "dd if=/dev/zero of=/dev/sda",
            ":(){ :|:& };:",
            "chmod 777 /",
        ],
    )
    def test_command_validation_blocks_dangerous_commands(self, tmp_path: Path, cmd: str):
        cfg = Config(project_dir=str(tmp_path), approval_mode="never")
        guard = SafetyGuard(cfg)

        with pytest.raises(ValueError, match="Security violation"):
            guard.validate_command(cmd)

    def test_command_validation_rejects_empty(self, tmp_path: Path):
        cfg = Config(project_dir=str(tmp_path), approval_mode="never")
        guard = SafetyGuard(cfg)

        with pytest.raises(ValueError, match="cannot be empty"):
            guard.validate_command("   ")

    @pytest.mark.parametrize(
        "cmd",
        [
            "pytest -v",
            "npm test",
            "python -m unittest discover",
            "git status",
            "cargo test --all",
            "flake8 .",
        ],
    )
    def test_command_validation_allows_safe_commands(self, tmp_path: Path, cmd: str):
        cfg = Config(project_dir=str(tmp_path), approval_mode="never")
        guard = SafetyGuard(cfg)

        # Should not raise
        guard.validate_command(cmd)

    def test_approval_mode_decisions(self, tmp_path: Path):
        # "never" mode
        guard_never = SafetyGuard(Config(project_dir=str(tmp_path), approval_mode="never"))
        assert not guard_never.should_approve("write", is_destructive=True)
        assert not guard_never.should_approve("command", is_destructive=True)

        # "always" mode
        guard_always = SafetyGuard(Config(project_dir=str(tmp_path), approval_mode="always"))
        assert guard_always.should_approve("write", is_destructive=False)
        assert guard_always.should_approve("command", is_destructive=False)

        # "destructive" mode
        guard_dest = SafetyGuard(Config(project_dir=str(tmp_path), approval_mode="destructive"))
        assert guard_dest.should_approve("delete", is_destructive=True)
        assert not guard_dest.should_approve("write", is_destructive=False)
