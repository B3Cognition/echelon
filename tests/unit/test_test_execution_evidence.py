"""Tests for common structured test-execution evidence."""

from __future__ import annotations

import pytest

from harness.test_execution_evidence import (
    ObservedTestExecution,
    PhysicalTestIdentity,
    TestExecutionEvidenceError,
    parse_echelon_case_tags,
)


@pytest.mark.unit
def test_parse_echelon_case_tags_returns_ordered_unique_case_ids() -> None:
    assert parse_echelon_case_tags(
        "persistent journey [echelon:E2E-001, UT-002, E2E-001]"
    ) == ("E2E-001", "UT-002")


@pytest.mark.unit
def test_parse_echelon_case_tags_accepts_case_insensitive_label() -> None:
    assert parse_echelon_case_tags("journey [EcHeLoN:E2E-001]") == ("E2E-001",)


@pytest.mark.unit
def test_parse_echelon_case_tags_returns_empty_for_an_untagged_title() -> None:
    assert parse_echelon_case_tags("ordinary test") == ()


@pytest.mark.unit
@pytest.mark.parametrize(
    ("title", "message"),
    [
        ("journey [echelon:]", "must contain at least one case id"),
        ("journey [echelon:E2E-001,]", "malformed comma"),
        ("journey [echelon:E2E-001] afterword", "must end"),
    ],
)
def test_parse_echelon_case_tags_rejects_malformed_terminal_tag(
    title: str, message: str
) -> None:
    with pytest.raises(TestExecutionEvidenceError, match=message):
        parse_echelon_case_tags(title)


@pytest.mark.unit
def test_physical_test_identity_ignores_project_and_retry() -> None:
    execution = ObservedTestExecution(
        observer_id="playwright",
        test_type="e2e",
        file="tests/journey.spec.ts",
        title="persistent journey [echelon:E2E-001]",
        project="chromium",
        status="passed",
        retry_count=1,
        error="",
    )

    assert PhysicalTestIdentity.from_execution(execution) == PhysicalTestIdentity(
        observer_id="playwright",
        file="tests/journey.spec.ts",
        title="persistent journey [echelon:E2E-001]",
    )
