"""Unit tests for the targeted run_tests tool."""

from __future__ import annotations

from pathlib import Path

from coder_agent.config import Config
from coder_agent.safety import SafetyGuard
from coder_agent.tools import run_tests
from coder_agent.tools.run_tests import _detect_test_command, _format_diagnostics
from coder_agent.ui import UI


def test_detect_test_command_python(tmp_path: Path):
    (tmp_path / "pytest.ini").write_text("", encoding="utf-8")
    cmd = _detect_test_command(tmp_path, ["tests/test_auth.py"])
    assert "pytest" in " ".join(cmd)
    assert "tests/test_auth.py" in cmd


def test_detect_test_command_node(tmp_path: Path):
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")
    cmd = _detect_test_command(tmp_path, ["auth.test.js"])
    assert cmd[:2] == ["npm", "test"]
    assert "auth.test.js" in cmd


def test_format_diagnostics_success():
    res = _format_diagnostics("5 passed in 0.23s", "", 0)
    assert "✅ Tests Succeeded" in res
    assert "5 passed" in res


def test_format_diagnostics_failure():
    stdout = "=== FAILURES ===\n_ test_fail _\nAssertionError\n=== short test summary info ===\nFAILED test.py::test_fail"
    res = _format_diagnostics(stdout, "", 1)
    assert "❌ Tests Failed" in res
    assert "FAILED test.py::test_fail" in res


def test_run_tests_execution(tmp_path: Path):
    test_file = tmp_path / "test_simple.py"
    test_file.write_text("def test_ok(): assert True\n", encoding="utf-8")

    cfg = Config(project_dir=str(tmp_path), approval_mode="never")
    safety = SafetyGuard(cfg)
    ui = UI(use_colors=False)

    res = run_tests.execute(
        {"targets": ["test_simple.py"]},
        project_dir=str(tmp_path),
        safety=safety,
        ui=ui,
        config=cfg,
    )
    assert not res.is_error
    assert "Tests Succeeded" in res.content


def test_run_tests_rejects_path_traversal(tmp_path: Path):
    cfg = Config(project_dir=str(tmp_path), approval_mode="never")
    safety = SafetyGuard(cfg)
    ui = UI(use_colors=False)

    res = run_tests.execute(
        {"targets": ["../../etc/passwd"]},
        project_dir=str(tmp_path),
        safety=safety,
        ui=ui,
        config=cfg,
    )
    assert res.is_error
    assert "Security violation" in res.content


def test_run_tests_denied_approval(tmp_path: Path, monkeypatch):
    test_file = tmp_path / "test_dummy.py"
    test_file.write_text("def test_x(): pass\n", encoding="utf-8")

    cfg = Config(project_dir=str(tmp_path), approval_mode="always")
    safety = SafetyGuard(cfg)
    ui = UI(use_colors=False)

    monkeypatch.setattr(ui, "confirm", lambda prompt: False)

    res = run_tests.execute(
        {"targets": ["test_dummy.py"]},
        project_dir=str(tmp_path),
        safety=safety,
        ui=ui,
        config=cfg,
    )
    assert res.is_error
    assert "User denied permission" in res.content
