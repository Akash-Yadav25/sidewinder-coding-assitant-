"""Unit tests for Calculator."""

import pytest
from calculator import Calculator


@pytest.fixture
def calc():
    return Calculator()


def test_addition(calc):
    assert calc.add(10, 5) == 15
    assert calc.add(-1, 1) == 0


def test_subtraction(calc):
    assert calc.subtract(10, 4) == 6


def test_multiplication(calc):
    assert calc.multiply(3, 7) == 21


def test_division(calc):
    assert calc.divide(10, 2) == 5.0


def test_division_by_zero(calc):
    with pytest.raises(ValueError, match="Cannot divide by zero"):
        calc.divide(10, 0)
