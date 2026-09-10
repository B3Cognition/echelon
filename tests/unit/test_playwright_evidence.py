"""Tests for deterministic Playwright JSON evidence normalization."""

from __future__ import annotations

import json

import pytest

from harness.playwright_evidence import (
    PlaywrightEvidenceError,
    parse_playwright_json,
    parse_playwright_json_executions,
)


def _report(*tests: dict) -> str:
    return json.dumps(
        {
            "suites": [
                {
                    "title": "journey",
                    "specs": [
                        {
                            "title": "persistent journey",
                            "file": "tests/journey.spec.ts",
                            "tests": list(tests),
                        }
                    ],
                }
            ]
        }
    )


def test_parse_playwright_json_counts_executed_tests() -> None:
    evidence = parse_playwright_json(
        _report(
            {
                "projectName": "chromium",
                "expectedStatus": "passed",
                "results": [{"status": "passed"}],
            },
            {
                "projectName": "firefox",
                "expectedStatus": "passed",
                "results": [
                    {"status": "failed", "error": {"message": "restore failed"}}
                ],
            },
            {
                "projectName": "webkit",
                "expectedStatus": "skipped",
                "results": [{"status": "skipped"}],
            },
        )
    )

    assert evidence.total == 3
    assert evidence.passed == 1
    assert evidence.failed == 1
    assert evidence.skipped == 1
    assert evidence.tests[1].error == "restore failed"


def test_parse_playwright_json_treats_empty_results_as_skipped() -> None:
    evidence = parse_playwright_json(
        _report(
            {
                "projectName": "chromium",
                "expectedStatus": "passed",
                "results": [],
            }
        )
    )

    assert evidence.total == 1
    assert evidence.skipped == 1
    assert evidence.tests[0].status == "skipped"


@pytest.mark.unit
def test_parse_playwright_json_executions_preserves_projects_and_terminal_retry() -> None:
    executions = parse_playwright_json_executions(
        _report(
            {
                "projectName": "chromium",
                "expectedStatus": "passed",
                "results": [
                    {"status": "failed", "error": {"message": "first try"}},
                    {"status": "passed"},
                ],
            },
            {
                "projectName": "webkit",
                "expectedStatus": "passed",
                "results": [{"status": "passed"}],
            },
        ),
        observer_id="playwright",
        test_type="e2e",
    )

    assert [(item.project, item.status, item.retry_count) for item in executions] == [
        ("chromium", "passed", 1),
        ("webkit", "passed", 0),
    ]
    assert {item.file for item in executions} == {"tests/journey.spec.ts"}
    assert {item.title for item in executions} == {"persistent journey"}


@pytest.mark.unit
def test_parse_playwright_json_executions_rejects_absolute_test_files() -> None:
    report = json.dumps(
        {
            "suites": [
                {
                    "specs": [
                        {
                            "title": "journey",
                            "file": "/tmp/journey.spec.ts",
                            "tests": [
                                {
                                    "projectName": "chromium",
                                    "expectedStatus": "passed",
                                    "results": [{"status": "passed"}],
                                }
                            ],
                        }
                    ]
                }
            ]
        }
    )

    with pytest.raises(PlaywrightEvidenceError, match="target-relative"):
        parse_playwright_json_executions(
            report,
            observer_id="playwright",
            test_type="e2e",
        )


@pytest.mark.unit
def test_parse_playwright_json_executions_normalizes_declared_sandbox_worktree_paths() -> None:
    report = json.dumps(
        {
            "suites": [
                {
                    "specs": [
                        {
                            "title": "journey [echelon:E2E-001]",
                            "file": "/workspace/tests/journey.spec.ts",
                            "tests": [
                                {
                                    "projectName": "chromium",
                                    "expectedStatus": "passed",
                                    "results": [{"status": "passed"}],
                                }
                            ],
                        }
                    ]
                }
            ]
        }
    )

    executions = parse_playwright_json_executions(
        report,
        observer_id="playwright",
        test_type="e2e",
        sandbox_worktree_mount="/workspace",
    )

    assert executions[0].file == "tests/journey.spec.ts"


@pytest.mark.parametrize("stdout", ["", "not json", "[]", '{"suites":"wrong"}'])
def test_parse_playwright_json_rejects_absent_or_malformed_reports(stdout: str) -> None:
    with pytest.raises(PlaywrightEvidenceError):
        parse_playwright_json(stdout)
