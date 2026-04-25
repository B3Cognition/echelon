"""Calculator tests. test_divide is expected to FAIL (bug in divide)."""

import sys
sys.path.insert(0, "src")

from calculator import add, subtract, multiply, divide


def test_add():
    assert add(2, 3) == 5


def test_subtract():
    assert subtract(5, 3) == 2


def test_multiply():
    assert multiply(3, 4) == 12


def test_divide():
    """This test should FAIL because divide() has a bug."""
    assert divide(10, 2) == 5  # Will fail: divide returns 10*2=20
