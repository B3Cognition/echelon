"""Tests for VerifyResult schema validation.

4 tests per test-strategy 3.1:
- VerifyResult with empty failures validates
- VerifyResult with populated failures validates categories
- Missing 'passed' field raises SchemaViolationError
- Invalid failure category raises SchemaViolationError
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness.errors import SchemaViolationError
from harness.verify_result import FailureCategory, VerifyResult


FIXTURES = Path(__file__).parent.parent / "fixtures" / "verify-results"


def _load_fixture(name: str) -> dict:
    with open(FIXTURES / name) as f:
        return json.load(f)


@pytest.mark.unit
class TestVerifyResultFromDict:
    """Test VerifyResult.from_dict validation."""

    def test_passed_with_empty_failures(self) -> None:
        data = _load_fixture("passed.json")
        result = VerifyResult.from_dict(data)
        assert result.passed is True
        assert result.failures == []
        assert result.duration_s == 45.2
        assert result.token_usage == 1500

    def test_failed_with_test_failure(self) -> None:
        data = _load_fixture("failed-test.json")
        result = VerifyResult.from_dict(data)
        assert result.passed is False
        assert len(result.failures) == 1
        assert result.failures[0].category == FailureCategory.TEST
        assert "test_divide" in result.failures[0].id

    def test_missing_passed_raises_schema_violation(self) -> None:
        data = _load_fixture("invalid-schema.json")
        with pytest.raises(SchemaViolationError, match="passed"):
            VerifyResult.from_dict(data)

    def test_invalid_category_raises_schema_violation(self) -> None:
        data = {
            "passed": False,
            "failures": [
                {"category": "nonexistent_category", "id": "test1", "error": "err"}
            ],
        }
        with pytest.raises(SchemaViolationError, match="category"):
            VerifyResult.from_dict(data)

    def test_playwright_test_category_roundtrips(self) -> None:
        """PLAYWRIGHT_TEST category must deserialise from 'playwright_test' string."""
        from harness.verify_result import FailureEntry

        entry = FailureEntry.from_dict({
            "category": "playwright_test",
            "id": "test-home-renders",
            "error": "Expected locator('.hero').to_be_visible()",
        })
        assert entry.category == FailureCategory.PLAYWRIGHT_TEST
        assert entry.id == "test-home-renders"

    def test_invalid_category_still_raises(self) -> None:
        """Invalid categories should still raise SchemaViolationError."""
        from harness.verify_result import FailureEntry

        with pytest.raises(SchemaViolationError):
            FailureEntry.from_dict({"category": "not_a_category", "id": "x", "error": "y"})
