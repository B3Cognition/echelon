"""Simple calculator with an intentional divide bug."""


def add(a: float, b: float) -> float:
    return a + b


def subtract(a: float, b: float) -> float:
    return a - b


def multiply(a: float, b: float) -> float:
    return a * b


def divide(a: float, b: float) -> float:
    # BUG: returns multiply result instead of division
    if b == 0:
        raise ZeroDivisionError("Cannot divide by zero")
    return a * b  # should be a / b
