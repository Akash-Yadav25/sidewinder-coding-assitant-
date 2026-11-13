"""Standard benchmark evaluation challenge tasks for Coder Agent."""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

from evals.harness import EvalTask


def _verify_bugfix_task(task_dir: Path) -> bool:
    """Verify bugfix challenge by running test suite in task directory."""
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "unittest", "test_math.py"],
            cwd=str(task_dir),
            capture_output=True,
            timeout=15,
        )
        return proc.returncode == 0
    except Exception:
        return False


def create_bugfix_task() -> EvalTask:
    """Create an evaluation challenge: fix ZeroDivisionError handling."""
    math_utils_py = (
        "def divide(a: float, b: float) -> float:\n"
        "    # Bug: does not raise ValueError on zero division\n"
        "    return a / b\n"
    )

    test_math_py = (
        "import unittest\n"
        "from math_utils import divide\n\n"
        "class TestMath(unittest.TestCase):\n"
        "    def test_divide_valid(self):\n"
        "        self.assertEqual(divide(10, 2), 5)\n\n"
        "    def test_divide_by_zero(self):\n"
        "        with self.assertRaises(ValueError):\n"
        "            divide(10, 0)\n\n"
        "if __name__ == '__main__':\n"
        "    unittest.main()\n"
    )

    return EvalTask(
        task_id="bugfix_zerodiv",
        requirement="Fix divide() in math_utils.py so it raises ValueError('Cannot divide by zero') when b == 0.",
        setup_files={
            "math_utils.py": math_utils_py,
            "test_math.py": test_math_py,
        },
        verify_fn=_verify_bugfix_task,
    )


def _verify_feature_task(task_dir: Path) -> bool:
    """Verify feature challenge by running test suite in task directory."""
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "unittest", "test_calculator.py"],
            cwd=str(task_dir),
            capture_output=True,
            timeout=15,
        )
        return proc.returncode == 0
    except Exception:
        return False


def create_feature_task() -> EvalTask:
    """Create an evaluation challenge: add power function."""
    calculator_py = (
        "def add(a: int, b: int) -> int:\n"
        "    return a + b\n"
    )

    test_calc_py = (
        "import unittest\n"
        "from calculator import add, power\n\n"
        "class TestCalculator(unittest.TestCase):\n"
        "    def test_add(self):\n"
        "        self.assertEqual(add(2, 3), 5)\n\n"
        "    def test_power(self):\n"
        "        self.assertEqual(power(2, 3), 8)\n"
        "        self.assertEqual(power(5, 0), 1)\n"
        "        self.assertEqual(power(2, -1), 0.5)\n\n"
        "if __name__ == '__main__':\n"
        "    unittest.main()\n"
    )

    return EvalTask(
        task_id="feature_power",
        requirement="Implement power(base, exponent) in calculator.py so all tests in test_calculator.py pass.",
        setup_files={
            "calculator.py": calculator_py,
            "test_calculator.py": test_calc_py,
        },
        verify_fn=_verify_feature_task,
    )


def _verify_refactor_task(task_dir: Path) -> bool:
    """Verify refactoring challenge by inspecting AST annotations."""
    user_service = task_dir / "user_service.py"
    if not user_service.is_file():
        return False
    try:
        tree = ast.parse(user_service.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "format_user":
                # Check return annotation
                if node.returns is None:
                    return False
                # Check arguments have annotations
                has_ann = any(arg.annotation is not None for arg in node.args.args)
                return has_ann
        return False
    except Exception:
        return False


def create_refactor_task() -> EvalTask:
    """Create an evaluation challenge: add type hints and clean docstrings."""
    user_service_py = (
        "def format_user(name, age, email=None):\n"
        "    return f'{name} ({age}) - {email or \"N/A\"}'\n"
    )

    return EvalTask(
        task_id="refactor_type_hints",
        requirement="Add comprehensive type hints and a docstring to format_user in user_service.py.",
        setup_files={
            "user_service.py": user_service_py,
        },
        verify_fn=_verify_refactor_task,
    )


def get_benchmark_tasks() -> list[EvalTask]:
    """Retrieve the standard suite of evaluation benchmark challenges."""
    return [
        create_bugfix_task(),
        create_feature_task(),
        create_refactor_task(),
    ]
