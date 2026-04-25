"""Tests for failure signature normalization and same-failure detection.

6 tests per test-strategy 3.1.
"""

from __future__ import annotations

import pytest

from harness.failure_signature import detect_same_failure, normalize


@pytest.mark.unit
class TestNormalization:
    """Test failure signature normalization."""

    def test_lowercase_applied(self) -> None:
        fp = normalize("test", "test_calc", "AssertionError: Expected TRUE")
        assert "true" in fp
        assert "TRUE" not in fp

    def test_paths_stripped(self) -> None:
        error = 'File "/home/user/project/tests/test_calc.py", line 42: assert False'
        fp = normalize("test", "test_calc", error)
        assert "/home/user" not in fp
        assert "test_calc.py" not in fp

    def test_line_numbers_stripped(self) -> None:
        error = "Error at :42:10 — expected 5, got 10"
        fp = normalize("test", "test_calc", error)
        # Line numbers should be removed but assertion message retained
        assert "expected 5, got 10" in fp

    def test_assertion_message_retained(self) -> None:
        error = 'AssertionError: expected 5.0, got 10.0 at /tmp/test.py:15'
        fp = normalize("test", "test_divide", error)
        assert "expected 5.0, got 10.0" in fp

    def test_different_errors_same_test_are_different(self) -> None:
        fp1 = normalize("test", "test_calc", "AssertionError: expected 5")
        fp2 = normalize("test", "test_calc", "TypeError: int not callable")
        assert fp1 != fp2


@pytest.mark.unit
class TestSameFailureDetection:
    """Test same-failure detection across iterations."""

    def test_threshold_3_fires_correctly(self) -> None:
        """Same fingerprint in 3 consecutive iterations -> detected."""
        fp = "test:test_divide:assertionerror: expected 5.0, got 10.0"
        failure_lists = [[fp], [fp], [fp]]
        result = detect_same_failure(failure_lists, threshold=3)
        assert fp in result

    def test_threshold_3_not_triggered_at_2(self) -> None:
        """Same fingerprint in only 2 consecutive iterations -> not detected."""
        fp = "test:test_divide:assertionerror: expected 5.0, got 10.0"
        failure_lists = [[fp], [fp]]
        result = detect_same_failure(failure_lists, threshold=3)
        assert fp not in result

    def test_threshold_1_fires_immediately(self) -> None:
        """threshold=1 -> any appearance triggers detection."""
        fp = "test:test_divide:error"
        failure_lists = [[fp]]
        result = detect_same_failure(failure_lists, threshold=1)
        assert fp in result

    def test_non_consecutive_not_detected(self) -> None:
        """Fingerprint appears in iterations 1 and 3 but not 2 -> not detected."""
        fp = "test:test_divide:error"
        failure_lists = [[fp], [], [fp]]
        result = detect_same_failure(failure_lists, threshold=2)
        assert fp not in result

    def test_empty_failure_lists(self) -> None:
        """Empty input -> empty result."""
        result = detect_same_failure([], threshold=3)
        assert result == set()
