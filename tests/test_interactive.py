"""Tests for interactive multi-line input handling."""

from unittest.mock import MagicMock, patch
import pytest

from coder_agent.interactive import read_multiline_input
from coder_agent.ui import UI


@pytest.fixture
def mock_ui():
    return UI(use_colors=False)


def test_read_multiline_single_line_then_blank(mock_ui):
    with patch("builtins.input", side_effect=["Fix the calculator", ""]):
        result = read_multiline_input("prompt> ", mock_ui)
        assert result == "Fix the calculator"


def test_read_multiline_multiple_lines_then_blank(mock_ui):
    with patch("builtins.input", side_effect=["Line 1", "Line 2", "Line 3", ""]):
        result = read_multiline_input("prompt> ", mock_ui)
        assert result == "Line 1\nLine 2\nLine 3"


def test_read_multiline_ctrl_d_on_continuation(mock_ui):
    with patch("builtins.input", side_effect=["First line", "Second line", EOFError]):
        result = read_multiline_input("prompt> ", mock_ui)
        assert result == "First line\nSecond line"


def test_read_multiline_empty_first_line(mock_ui):
    with patch("builtins.input", side_effect=[""]):
        result = read_multiline_input("prompt> ", mock_ui)
        assert result == ""


def test_read_multiline_eof_on_first_line(mock_ui):
    with patch("builtins.input", side_effect=EOFError):
        with pytest.raises(EOFError):
            read_multiline_input("prompt> ", mock_ui)


def test_read_multiline_slash_command_immediate(mock_ui):
    # Should not call input a second time
    with patch("builtins.input", side_effect=["/diff"]):
        result = read_multiline_input("prompt> ", mock_ui)
        assert result == "/diff"


def test_read_multiline_slash_command_with_args(mock_ui):
    with patch("builtins.input", side_effect=["/commit initial setup"]):
        result = read_multiline_input("prompt> ", mock_ui)
        assert result == "/commit initial setup"
