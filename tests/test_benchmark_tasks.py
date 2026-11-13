"""Unit tests for evaluation benchmark tasks."""

from __future__ import annotations

from pathlib import Path

from evals.tasks.benchmark_tasks import (
    create_bugfix_task,
    create_feature_task,
    create_refactor_task,
    get_benchmark_tasks,
)


def test_get_benchmark_tasks():
    tasks = get_benchmark_tasks()
    assert len(tasks) == 3
    ids = [t.task_id for t in tasks]
    assert "bugfix_zerodiv" in ids
    assert "feature_power" in ids
    assert "refactor_type_hints" in ids


def test_bugfix_task_verification(tmp_path: Path):
    task = create_bugfix_task()
    assert "divide" in task.requirement

    # Setup broken files
    for p, c in task.setup_files.items():
        (tmp_path / p).write_text(c, encoding="utf-8")

    # Before fix: verify_fn returns False
    assert not task.verify_fn(tmp_path)

    # After fix: verify_fn returns True
    fixed_code = (
        "def divide(a: float, b: float) -> float:\n"
        "    if b == 0:\n"
        "        raise ValueError('Cannot divide by zero')\n"
        "    return a / b\n"
    )
    (tmp_path / "math_utils.py").write_text(fixed_code, encoding="utf-8")
    assert task.verify_fn(tmp_path)


def test_feature_task_verification(tmp_path: Path):
    task = create_feature_task()
    for p, c in task.setup_files.items():
        (tmp_path / p).write_text(c, encoding="utf-8")

    # Before implementation: verify_fn returns False
    assert not task.verify_fn(tmp_path)

    # Implement power
    code = (
        "def add(a: int, b: int) -> int:\n"
        "    return a + b\n\n"
        "def power(base: float, exponent: int) -> float:\n"
        "    return base ** exponent\n"
    )
    (tmp_path / "calculator.py").write_text(code, encoding="utf-8")
    assert task.verify_fn(tmp_path)


def test_refactor_task_verification(tmp_path: Path):
    task = create_refactor_task()
    for p, c in task.setup_files.items():
        (tmp_path / p).write_text(c, encoding="utf-8")

    # Before refactor: no annotations
    assert not task.verify_fn(tmp_path)

    # With annotations
    refactored = (
        "def format_user(name: str, age: int, email: str | None = None) -> str:\n"
        "    \"\"\"Format user details.\"\"\"\n"
        "    return f'{name} ({age}) - {email or \"N/A\"}'\n"
    )
    (tmp_path / "user_service.py").write_text(refactored, encoding="utf-8")
    assert task.verify_fn(tmp_path)
