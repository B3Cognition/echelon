"""Normalize Vitest JSON output into deterministic execution evidence."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from harness.test_execution_evidence import ObservedTestExecution


class VitestEvidenceError(ValueError):
    """Raised when a Vitest JSON report cannot prove individual executions."""


_TERMINAL_STATUS = {
    "passed": "passed",
    "failed": "failed",
    "skipped": "skipped",
    "pending": "skipped",
    "todo": "skipped",
    "disabled": "skipped",
}


def parse_vitest_json(
    stdout: str,
    *,
    observer_id: str,
    test_type: str,
) -> tuple[ObservedTestExecution, ...]:
    """Parse a Jest-compatible Vitest JSON report into terminal test results."""
    if not isinstance(stdout, str) or not stdout.strip():
        raise VitestEvidenceError("Vitest produced no JSON report")
    try:
        report = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise VitestEvidenceError("Vitest output is not valid JSON") from exc
    if not isinstance(report, dict) or not isinstance(report.get("testResults"), list):
        raise VitestEvidenceError("Vitest JSON report has no testResults array")

    executions: list[ObservedTestExecution] = []
    for result_index, result in enumerate(report["testResults"]):
        result_path = f"testResults[{result_index}]"
        if not isinstance(result, dict):
            raise VitestEvidenceError(f"{result_path} must be an object")
        file = _target_relative_file(result.get("name"), result_path)
        assertions = result.get("assertionResults")
        if not isinstance(assertions, list):
            raise VitestEvidenceError(f"{result_path}.assertionResults must be an array")
        project = _non_empty_string(result.get("projectName"), default="default")
        for assertion_index, assertion in enumerate(assertions):
            assertion_path = f"{result_path}.assertionResults[{assertion_index}]"
            if not isinstance(assertion, dict):
                raise VitestEvidenceError(f"{assertion_path} must be an object")
            title = _non_empty_string(assertion.get("title"))
            raw_status = _non_empty_string(assertion.get("status")).lower()
            status = _TERMINAL_STATUS.get(raw_status)
            if status is None:
                raise VitestEvidenceError(
                    f"{assertion_path}.status has unsupported terminal status: {raw_status}"
                )
            executions.append(
                ObservedTestExecution(
                    observer_id=observer_id,
                    test_type=test_type,
                    file=file,
                    title=title,
                    project=project,
                    status=status,
                    retry_count=_retry_count(assertion, assertion_path),
                    error=_failure_message(assertion),
                )
            )

    if not executions:
        raise VitestEvidenceError("Vitest JSON report has zero executed tests")
    return tuple(executions)


def _target_relative_file(value: Any, field_path: str) -> str:
    file = _non_empty_string(value)
    path = Path(file)
    if path.is_absolute() or ".." in path.parts or "." in path.parts or "\\" in file:
        raise VitestEvidenceError(f"{field_path}.name must be target-relative")
    return file


def _non_empty_string(value: Any, *, default: str | None = None) -> str:
    if value is None and default is not None:
        return default
    if not isinstance(value, str) or not value.strip():
        raise VitestEvidenceError("Vitest report requires a non-empty string")
    return value.strip()


def _retry_count(assertion: dict[str, Any], field_path: str) -> int:
    value = assertion.get("retryCount", assertion.get("retry", 0))
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise VitestEvidenceError(f"{field_path}.retry must be a non-negative integer")
    return value


def _failure_message(assertion: dict[str, Any]) -> str:
    messages = assertion.get("failureMessages", [])
    if messages is None:
        return ""
    if not isinstance(messages, list):
        raise VitestEvidenceError("Vitest assertion failureMessages must be an array")
    return "\n".join(str(message) for message in messages if str(message))[:1000]
