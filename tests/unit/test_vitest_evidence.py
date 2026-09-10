"""Tests for normalized Vitest JSON observer output."""

from __future__ import annotations

import json

import pytest

from harness.vitest_evidence import VitestEvidenceError, parse_vitest_json


def _assertion(
    title: str,
    status: str,
    *,
    failures: list[str] | None = None,
    retry: int = 0,
) -> dict[str, object]:
    return {
        "title": title,
        "status": status,
        "failureMessages": failures or [],
        "retry": retry,
    }


def _report(*results: dict[str, object]) -> str:
    return json.dumps({"testResults": list(results)})


@pytest.mark.unit
def test_parse_vitest_json_normalizes_terminal_assertion_results() -> None:
    executions = parse_vitest_json(
        _report(
            {
                "name": "tests/inventory.test.ts",
                "assertionResults": [
                    _assertion("saves inventory [echelon:UT-001]", "passed"),
                    _assertion("skipped setup", "skipped"),
                    _assertion(
                        "rejects bad inventory [echelon:UT-002]",
                        "failed",
                        failures=["expected save to fail"],
                        retry=1,
                    ),
                ],
            }
        ),
        observer_id="vitest",
        test_type="unit",
    )

    assert [(item.file, item.title, item.status) for item in executions] == [
        ("tests/inventory.test.ts", "saves inventory [echelon:UT-001]", "passed"),
        ("tests/inventory.test.ts", "skipped setup", "skipped"),
        (
            "tests/inventory.test.ts",
            "rejects bad inventory [echelon:UT-002]",
            "failed",
        ),
    ]
    assert executions[2].project == "default"
    assert executions[2].retry_count == 1
    assert executions[2].error == "expected save to fail"


@pytest.mark.unit
def test_parse_vitest_json_accepts_null_failure_messages() -> None:
    executions = parse_vitest_json(
        _report(
            {
                "name": "tests/inventory.test.ts",
                "assertionResults": [
                    {
                        "title": "saves inventory [echelon:UT-001]",
                        "status": "passed",
                        "failureMessages": None,
                    }
                ],
            }
        ),
        observer_id="vitest",
        test_type="unit",
    )

    assert executions[0].error == ""


@pytest.mark.unit
def test_parse_vitest_json_normalizes_declared_sandbox_worktree_paths() -> None:
    executions = parse_vitest_json(
        _report(
            {
                "name": "/workspace/tests/inventory.test.ts",
                "assertionResults": [
                    _assertion("saves inventory [echelon:UT-001]", "passed")
                ],
            }
        ),
        observer_id="vitest",
        test_type="unit",
        sandbox_worktree_mount="/workspace",
    )

    assert executions[0].file == "tests/inventory.test.ts"


@pytest.mark.unit
@pytest.mark.parametrize(
    ("stdout", "message"),
    [
        ("", "no JSON report"),
        ("not json", "not valid JSON"),
        (json.dumps({}), "no testResults array"),
        (json.dumps({"testResults": []}), "zero executed tests"),
        (
            _report({"name": "/tmp/inventory.test.ts", "assertionResults": []}),
            "target-relative",
        ),
        (
            _report({"name": "../inventory.test.ts", "assertionResults": []}),
            "target-relative",
        ),
    ],
)
def test_parse_vitest_json_rejects_unusable_observer_reports(
    stdout: str, message: str
) -> None:
    with pytest.raises(VitestEvidenceError, match=message):
        parse_vitest_json(stdout, observer_id="vitest", test_type="unit")
