"""Tests for deterministic Playwright JSON evidence normalization."""

from __future__ import annotations

import json

import pytest

from harness.playwright_evidence import PlaywrightEvidenceError, parse_playwright_json


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


@pytest.mark.parametrize("stdout", ["", "not json", "[]", '{"suites":"wrong"}'])
def test_parse_playwright_json_rejects_absent_or_malformed_reports(stdout: str) -> None:
    with pytest.raises(PlaywrightEvidenceError):
        parse_playwright_json(stdout)

