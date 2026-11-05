"""Project context analyzer and structure builder for the LLM system prompt."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from coder_agent.tools.list_directory import _is_excluded

if TYPE_CHECKING:
    from coder_agent.config import Config


class ContextBuilder:
    """Builds an informative project overview to bootstrap agent understanding."""

    def __init__(self, config: Config):
        self.config = config

    def detect_project_type(self, root: Path) -> list[str]:
        """Detect project technologies from marker files."""
        types = []
        if (root / "pyproject.toml").is_file() or (root / "requirements.txt").is_file() or (root / "setup.py").is_file():
            types.append("Python")
        if (root / "package.json").is_file():
            types.append("Node.js / JavaScript / TypeScript")
        if (root / "Cargo.toml").is_file():
            types.append("Rust")
        if (root / "go.mod").is_file():
            types.append("Go")
        if (root / "pom.xml").is_file() or (root / "build.gradle").is_file():
            types.append("Java")
        if (root / "CMakeLists.txt").is_file() or (root / "Makefile").is_file():
            types.append("C/C++ or Make")
        return types or ["General Codebase"]

    def build_tree(self, root: Path, max_depth: int = 3) -> str:
        """Render a clean, depth-limited ASCII tree."""
        lines: list[str] = [f"{root.name}/"]

        def _traverse(curr: Path, prefix: str, depth: int) -> None:
            if depth > max_depth:
                return

            try:
                entries = sorted(list(curr.iterdir()), key=lambda p: (not p.is_dir(), p.name.lower()))
            except PermissionError:
                return

            valid = [
                e
                for e in entries
                if not _is_excluded(e, root, self.config.exclude_patterns)
            ]

            for idx, entry in enumerate(valid):
                is_last = idx == len(valid) - 1
                connector = "└── " if is_last else "├── "
                sub_prefix = "    " if is_last else "│   "

                if entry.is_dir():
                    lines.append(f"{prefix}{connector}{entry.name}/")
                    _traverse(entry, prefix + sub_prefix, depth + 1)
                else:
                    lines.append(f"{prefix}{connector}{entry.name}")

        _traverse(root, "", 1)
        return "\n".join(lines)

    def extract_key_configs(self, root: Path) -> str:
        """Extract summaries of essential configuration files."""
        summaries: list[str] = []

        # package.json
        pkg_json = root / "package.json"
        if pkg_json.is_file():
            try:
                data = json.loads(pkg_json.read_text(encoding="utf-8"))
                scripts = data.get("scripts", {})
                deps = list(data.get("dependencies", {}).keys())[:10]
                dev_deps = list(data.get("devDependencies", {}).keys())[:10]
                summary = f"**package.json** (name: {data.get('name', 'unnamed')})\n"
                if scripts:
                    summary += f"- Scripts: {', '.join(f'{k}: `{v}`' for k, v in scripts.items())}\n"
                if deps:
                    summary += f"- Dependencies: {', '.join(deps)}\n"
                if dev_deps:
                    summary += f"- DevDependencies: {', '.join(dev_deps)}\n"
                summaries.append(summary)
            except Exception:
                pass

        # pyproject.toml
        pyproject = root / "pyproject.toml"
        if pyproject.is_file():
            try:
                content = pyproject.read_text(encoding="utf-8")
                truncated = "\n".join(content.splitlines()[:30])
                summaries.append(f"**pyproject.toml (first 30 lines):**\n```toml\n{truncated}\n```")
            except Exception:
                pass

        # pytest / test commands hint
        test_hints = []
        if (root / "pytest.ini").is_file() or (root / "tests").is_dir() or any(root.glob("test_*.py")):
            test_hints.append("Python tests detected: use `pytest` or `python -m unittest` to run tests.")
        if pkg_json.is_file():
            test_hints.append("Node.js tests detected: check scripts in package.json (e.g. `npm test`).")
        if (root / "Cargo.toml").is_file():
            test_hints.append("Rust detected: use `cargo test` to execute test suites.")

        if test_hints:
            summaries.append("**Testing Guidance:**\n" + "\n".join(f"- {h}" for h in test_hints))

        return "\n\n".join(summaries)

    def build(self, project_dir: str) -> str:
        """Generate the complete project context string."""
        root = Path(project_dir).resolve()
        project_types = self.detect_project_type(root)
        tree = self.build_tree(root, max_depth=3)
        configs = self.extract_key_configs(root)

        parts = [
            f"## Project Root: `{root.name}`",
            f"## Project Type: {', '.join(project_types)}",
            "## Directory Structure:",
            f"```text\n{tree}\n```",
        ]
        if configs:
            parts.append("## Project Configurations & Testing Instructions:")
            parts.append(configs)

        return "\n\n".join(parts)
