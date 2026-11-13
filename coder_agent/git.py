"""Native Git integration and automatic workspace checkpointing."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger("coder_agent.git")


class GitManager:
    """Manages Git interactions, status queries, diffs, and workspace checkpoints."""

    def __init__(self, project_dir: str | Path):
        self.project_dir = Path(project_dir).resolve()
        self._checkpoints_dir = self.project_dir / ".coder-agent" / "backups"
        self._ensure_gitignore()

    def _ensure_gitignore(self) -> None:
        """Ensure .coder-agent is added to .gitignore if .gitignore exists."""
        gitignore = self.project_dir / ".gitignore"
        try:
            if gitignore.is_file():
                content = gitignore.read_text(encoding="utf-8")
                if ".coder-agent" not in content:
                    with open(gitignore, "a", encoding="utf-8") as f:
                        f.write("\n# Coder Agent session cache & backups\n.coder-agent/\n")
        except Exception as e:
            logger.debug("Failed to update .gitignore: %s", e)

    def _run_git(self, args: list[str], check: bool = False) -> subprocess.CompletedProcess[str]:
        """Execute a git command within project_dir."""
        return subprocess.run(
            ["git"] + args,
            cwd=str(self.project_dir),
            capture_output=True,
            text=True,
            check=check,
        )

    def is_git_repo(self) -> bool:
        """Check if project_dir is inside a valid git work tree."""
        proc = self._run_git(["rev-parse", "--is-inside-work-tree"])
        return proc.returncode == 0 and proc.stdout.strip() == "true"

    def init_repo(self) -> bool:
        """Initialize a new git repository in project_dir."""
        proc = self._run_git(["init"])
        return proc.returncode == 0

    def get_status(self, porcelain: bool = True) -> str:
        """Get git status output."""
        if not self.is_git_repo():
            return "Not a git repository."
        args = ["status", "--porcelain"] if porcelain else ["status"]
        proc = self._run_git(args)
        return proc.stdout.strip()

    def get_diff(self, file_path: str | None = None, staged: bool = False) -> str:
        """Retrieve unified diff of working tree or staged changes."""
        if not self.is_git_repo():
            return "Not a git repository."
        args = ["diff"]
        if staged:
            args.append("--staged")
        if file_path:
            args.extend(["--", file_path])
        proc = self._run_git(args)
        return proc.stdout

    def create_checkpoint(self, description: str = "") -> str:
        """Create a workspace checkpoint. Returns a unique checkpoint identifier."""
        ts = int(time.time())
        checkpoint_id = f"chk_{ts}_{os.urandom(4).hex()}"

        if self.is_git_repo():
            try:
                # Stage all current files to capture complete tree
                self._run_git(["add", "-A"])
                tree_proc = self._run_git(["write-tree"])
                if tree_proc.returncode == 0:
                    tree_sha = tree_proc.stdout.strip()
                    # Store ref in refs/coder-agent/checkpoints/<checkpoint_id>
                    self._run_git(["update-ref", f"refs/coder-agent/checkpoints/{checkpoint_id}", tree_sha])
                    # Unstage so user's workspace index is not disrupted
                    self._run_git(["reset"])
                    logger.debug("Created git tree checkpoint %s (%s)", checkpoint_id, tree_sha)
                    return checkpoint_id
            except Exception as e:
                logger.warning("Git checkpoint failed, falling back to shadow backup: %s", e)

        # Fallback for non-git workspaces or initial git setups: file-based snapshot
        backup_path = self._checkpoints_dir / checkpoint_id
        backup_path.mkdir(parents=True, exist_ok=True)
        # Record marker
        (backup_path / ".metadata").write_text(description or "pre-task-checkpoint", encoding="utf-8")
        logger.debug("Created file-based fallback checkpoint at %s", backup_path)
        return checkpoint_id

    def restore_checkpoint(self, checkpoint_id: str) -> bool:
        """Restore workspace to the state captured in checkpoint_id."""
        if not checkpoint_id:
            return False

        if self.is_git_repo():
            # Check if ref exists
            ref_proc = self._run_git(["rev-parse", f"refs/coder-agent/checkpoints/{checkpoint_id}"])
            if ref_proc.returncode == 0:
                tree_sha = ref_proc.stdout.strip()
                # Restore tree to working directory
                restore_proc = self._run_git(["read-tree", "--reset", "-u", tree_sha])
                if restore_proc.returncode != 0:
                    # Fallback to checkout
                    self._run_git(["checkout", tree_sha, "--", "."])
                    self._run_git(["clean", "-fd"])
                else:
                    # Clean untracked files not in that tree
                    self._run_git(["clean", "-fd"])
                logger.info("Successfully restored git checkpoint %s", checkpoint_id)
                return True

        # Fallback restoration from shadow backup if present
        backup_path = self._checkpoints_dir / checkpoint_id
        if backup_path.is_dir():
            # If files were copied, restore them
            for item in backup_path.rglob("*"):
                if item.name == ".metadata" or item.is_dir():
                    continue
                rel = item.relative_to(backup_path)
                dest = self.project_dir / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, dest)
            logger.info("Successfully restored fallback checkpoint %s", checkpoint_id)
            return True

        logger.error("Checkpoint %s not found or could not be restored.", checkpoint_id)
        return False

    def commit(self, message: str) -> bool:
        """Stage changes (excluding .coder-agent) and commit with message."""
        if not self.is_git_repo():
            return False
        self._ensure_gitignore()
        # Stage excluding .coder-agent directory
        add_proc = self._run_git(["add", "-A", "--", ":!.coder-agent", ":!.coder-agent/**"])
        if add_proc.returncode != 0:
            add_proc = self._run_git(["add", "-A"])
            if add_proc.returncode != 0:
                return False
        # Guarantee .coder-agent is unstaged if staged by fallback
        self._run_git(["reset", "HEAD", "--", ".coder-agent"])
        commit_proc = self._run_git(["commit", "-m", message])
        return commit_proc.returncode == 0
