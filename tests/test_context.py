"""Unit tests for the project context builder."""

from __future__ import annotations

import json
from pathlib import Path

from coder_agent.config import Config
from coder_agent.context import ContextBuilder


class TestContextBuilder:
    def test_detect_python_project(self, tmp_path: Path):
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'test'\n", encoding="utf-8")
        cfg = Config(project_dir=str(tmp_path))
        builder = ContextBuilder(cfg)
        types = builder.detect_project_type(tmp_path)
        assert "Python" in types

    def test_detect_node_project(self, tmp_path: Path):
        (tmp_path / "package.json").write_text(
            json.dumps({"name": "my-app", "scripts": {"test": "jest"}}),
            encoding="utf-8",
        )
        cfg = Config(project_dir=str(tmp_path))
        builder = ContextBuilder(cfg)
        types = builder.detect_project_type(tmp_path)
        assert any("Node.js" in t for t in types)

    def test_build_tree_skips_excluded(self, tmp_path: Path):
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "index.py").write_text("# code", encoding="utf-8")

        node_mods = tmp_path / "node_modules" / "some_pkg"
        node_mods.mkdir(parents=True)
        (node_mods / "index.js").write_text("// vendor", encoding="utf-8")

        cfg = Config(project_dir=str(tmp_path), exclude_patterns=["node_modules", ".git"])
        builder = ContextBuilder(cfg)
        tree = builder.build_tree(tmp_path)

        assert "index.py" in tree
        assert "node_modules" not in tree

    def test_full_context_build(self, tmp_path: Path):
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'demo'\n", encoding="utf-8")
        (tmp_path / "main.py").write_text("print('hello')", encoding="utf-8")

        cfg = Config(project_dir=str(tmp_path))
        builder = ContextBuilder(cfg)
        context_str = builder.build(str(tmp_path))

        assert "## Project Root:" in context_str
        assert "## Project Type: Python" in context_str
        assert "## Directory Structure:" in context_str
        assert "main.py" in context_str
