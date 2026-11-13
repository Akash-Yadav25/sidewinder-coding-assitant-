"""Unit tests for GitManager and git_diff tool."""

from __future__ import annotations

import subprocess
from pathlib import Path

from coder_agent.config import Config
from coder_agent.git import GitManager
from coder_agent.safety import SafetyGuard
from coder_agent.tools import git_diff
from coder_agent.ui import UI


def _setup_git_repo(repo_dir: Path) -> None:
    """Helper to initialize git and make an initial commit."""
    subprocess.run(["git", "init"], cwd=str(repo_dir), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Tester"], cwd=str(repo_dir), check=True)
    subprocess.run(["git", "config", "user.email", "tester@example.com"], cwd=str(repo_dir), check=True)
    (repo_dir / "initial.txt").write_text("v1\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=str(repo_dir), check=True)
    subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=str(repo_dir), check=True)


def test_git_repo_detection(tmp_path: Path):
    plain_dir = tmp_path / "plain"
    plain_dir.mkdir()
    git = GitManager(plain_dir)
    assert not git.is_git_repo()

    git_dir = tmp_path / "repo"
    git_dir.mkdir()
    _setup_git_repo(git_dir)
    git_repo = GitManager(git_dir)
    assert git_repo.is_git_repo()


def test_checkpoint_and_rollback(tmp_path: Path):
    repo_dir = tmp_path / "work"
    repo_dir.mkdir()
    _setup_git_repo(repo_dir)

    git = GitManager(repo_dir)
    # File before task
    file_a = repo_dir / "file_a.txt"
    file_a.write_text("original A\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=str(repo_dir), check=True)
    subprocess.run(["git", "commit", "-m", "Add file_a"], cwd=str(repo_dir), check=True)

    # Create checkpoint
    chk_id = git.create_checkpoint("before task")
    assert chk_id.startswith("chk_")

    # Agent performs modifications
    file_a.write_text("corrupted A\n", encoding="utf-8")
    file_b = repo_dir / "new_unwanted.txt"
    file_b.write_text("temporary\n", encoding="utf-8")

    assert file_a.read_text(encoding="utf-8") == "corrupted A\n"
    assert file_b.exists()

    # Rollback to checkpoint
    restored = git.restore_checkpoint(chk_id)
    assert restored
    assert file_a.read_text(encoding="utf-8") == "original A\n"
    assert not file_b.exists()


def test_git_diff_tool(tmp_path: Path):
    repo_dir = tmp_path / "diff_repo"
    repo_dir.mkdir()
    _setup_git_repo(repo_dir)

    cfg = Config(project_dir=str(repo_dir), approval_mode="never")
    safety = SafetyGuard(cfg)
    ui = UI(use_colors=False)

    # Initial state: clean
    res = git_diff.execute({}, project_dir=str(repo_dir), safety=safety, ui=ui, config=cfg)
    assert not res.is_error
    assert "clean" in res.content.lower()

    # Modify file
    (repo_dir / "initial.txt").write_text("v2\n", encoding="utf-8")
    res2 = git_diff.execute({}, project_dir=str(repo_dir), safety=safety, ui=ui, config=cfg)
    assert not res2.is_error
    assert "-v1" in res2.content
    assert "+v2" in res2.content


def test_git_commit_excludes_coder_agent(tmp_path: Path):
    repo_dir = tmp_path / "commit_repo"
    repo_dir.mkdir()
    _setup_git_repo(repo_dir)

    git = GitManager(repo_dir)

    # Add a normal file and an internal .coder-agent file
    (repo_dir / "code.py").write_text("print('hello')\n", encoding="utf-8")
    internal_dir = repo_dir / ".coder-agent"
    internal_dir.mkdir(parents=True, exist_ok=True)
    (internal_dir / "sessions.db").write_text("dummy binary db", encoding="utf-8")

    committed = git.commit("Add code.py")
    assert committed

    # Check git log of committed files
    proc = subprocess.run(
        ["git", "show", "--name-only", "--pretty=format:"],
        cwd=str(repo_dir),
        capture_output=True,
        text=True,
        check=True,
    )
    committed_files = proc.stdout.splitlines()
    assert "code.py" in committed_files
    assert not any(".coder-agent" in f for f in committed_files)
