"""Sample calculator module with arithmetic operations."""


class Calculator:
    """Performs standard mathematical operations."""

    def add(self, a: float, b: float) -> float:
        return a + b

    def subtract(self, a: float, b: float) -> float:
        return a - b

    def multiply(self, a: float, b: float) -> float:
        return a * b

    def divide(self, a: float, b: float) -> float:
        # BUG: Currently unhandled division by zero raises unhandled ZeroDivisionError
        # Expected behavior: Raise ValueError("Cannot divide by zero")
        return a / b

    def power(self, base: float, exponent: float) -> float:
        return base ** exponent
