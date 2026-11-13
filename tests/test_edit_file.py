"""Unit tests for the targeted edit_file tool."""

from __future__ import annotations

from pathlib import Path

from coder_agent.config import Config
from coder_agent.safety import SafetyGuard
from coder_agent.tools import edit_file
from coder_agent.ui import UI


def test_edit_file_exact_match(tmp_path: Path):
    target = tmp_path / "sample.py"
    target.write_text("def add(a, b):\n    return a - b  # bug\n", encoding="utf-8")

    cfg = Config(project_dir=str(tmp_path), approval_mode="never")
    safety = SafetyGuard(cfg)
    ui = UI(use_colors=False)

    res = edit_file.execute(
        {
            "path": "sample.py",
            "old_text": "    return a - b  # bug",
            "new_text": "    return a + b",
        },
        project_dir=str(tmp_path),
        safety=safety,
        ui=ui,
        config=cfg,
    )

    assert not res.is_error
    assert "Successfully edited 'sample.py'" in res.content
    assert target.read_text(encoding="utf-8") == "def add(a, b):\n    return a + b\n"


def test_edit_file_multiple_matches_rejected_with_lines(tmp_path: Path):
    target = tmp_path / "repeated.txt"
    target.write_text("ITEM\nOTHER\nITEM\nANOTHER\n", encoding="utf-8")

    cfg = Config(project_dir=str(tmp_path), approval_mode="never")
    safety = SafetyGuard(cfg)
    ui = UI(use_colors=False)

    res = edit_file.execute(
        {
            "path": "repeated.txt",
            "old_text": "ITEM",
            "new_text": "REPLACED",
        },
        project_dir=str(tmp_path),
        safety=safety,
        ui=ui,
        config=cfg,
    )

    assert res.is_error
    assert "matches 2 occurrences" in res.content
    assert "line 1" in res.content
    assert "line 3" in res.content
    # File must not be modified
    assert target.read_text(encoding="utf-8") == "ITEM\nOTHER\nITEM\nANOTHER\n"


def test_edit_file_not_found(tmp_path: Path):
    target = tmp_path / "code.py"
    target.write_text("x = 10\n", encoding="utf-8")

    cfg = Config(project_dir=str(tmp_path), approval_mode="never")
    safety = SafetyGuard(cfg)
    ui = UI(use_colors=False)

    res = edit_file.execute(
        {
            "path": "code.py",
            "old_text": "y = 20",
            "new_text": "y = 30",
        },
        project_dir=str(tmp_path),
        safety=safety,
        ui=ui,
        config=cfg,
    )

    assert res.is_error
    assert "'old_text' was not found" in res.content


def test_edit_file_fuzzy_whitespace_tolerance(tmp_path: Path):
    target = tmp_path / "whitespace.py"
    # Target has trailing spaces on lines
    target.write_text("def test():   \n    val = 1   \n    return val\n", encoding="utf-8")

    cfg = Config(project_dir=str(tmp_path), approval_mode="never")
    safety = SafetyGuard(cfg)
    ui = UI(use_colors=False)

    # old_text without trailing spaces
    res = edit_file.execute(
        {
            "path": "whitespace.py",
            "old_text": "def test():\n    val = 1",
            "new_text": "def test():\n    val = 42",
        },
        project_dir=str(tmp_path),
        safety=safety,
        ui=ui,
        config=cfg,
    )

    assert not res.is_error
    assert "val = 42" in target.read_text(encoding="utf-8")


def test_edit_file_nonexistent_file(tmp_path: Path):
    cfg = Config(project_dir=str(tmp_path), approval_mode="never")
    safety = SafetyGuard(cfg)
    ui = UI(use_colors=False)

    res = edit_file.execute(
        {
            "path": "does_not_exist.py",
            "old_text": "a",
            "new_text": "b",
        },
        project_dir=str(tmp_path),
        safety=safety,
        ui=ui,
        config=cfg,
    )

    assert res.is_error
    assert "does not exist" in res.content


def test_edit_file_path_violation(tmp_path: Path):
    cfg = Config(project_dir=str(tmp_path), approval_mode="never")
    safety = SafetyGuard(cfg)
    ui = UI(use_colors=False)

    res = edit_file.execute(
        {
            "path": "../../secret.txt",
            "old_text": "a",
            "new_text": "b",
        },
        project_dir=str(tmp_path),
        safety=safety,
        ui=ui,
        config=cfg,
    )

    assert res.is_error
    assert "Security violation" in res.content


def test_edit_file_denied_approval(tmp_path: Path, monkeypatch):
    target = tmp_path / "secure.txt"
    target.write_text("original content\n", encoding="utf-8")

    cfg = Config(project_dir=str(tmp_path), approval_mode="always")
    safety = SafetyGuard(cfg)
    ui = UI(use_colors=False)
    # Simulate user rejecting the approval prompt
    monkeypatch.setattr(ui, "confirm", lambda prompt, default=False: False)

    res = edit_file.execute(
        {
            "path": "secure.txt",
            "old_text": "original",
            "new_text": "modified",
        },
        project_dir=str(tmp_path),
        safety=safety,
        ui=ui,
        config=cfg,
    )

    assert res.is_error
    assert "User denied permission" in res.content
    assert target.read_text(encoding="utf-8") == "original content\n"
