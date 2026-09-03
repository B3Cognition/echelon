"""Normalize Playwright JSON output into deterministic execution evidence."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any, Iterable


class PlaywrightEvidenceError(ValueError):
    """Raised when stdout is not a usable Playwright JSON report."""


@dataclass(frozen=True)
class PlaywrightTestEvidence:
    """The terminal execution state of one Playwright project test."""

    id: str
    title: str
    file: str
    project: str
    status: str
    error: str = ""


@dataclass(frozen=True)
class PlaywrightEvidence:
    """Normalized counts and per-test states from a Playwright JSON report."""

    total: int
    passed: int
    failed: int
    skipped: int
    tests: tuple[PlaywrightTestEvidence, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "passed": self.passed,
            "failed": self.failed,
            "skipped": self.skipped,
            "tests": [asdict(test) for test in self.tests],
        }


def parse_playwright_json(stdout: str) -> PlaywrightEvidence:
    """Parse reporter output without accepting process exit status as evidence."""
    if not stdout.strip():
        raise PlaywrightEvidenceError("Playwright produced no JSON report")
    try:
        report = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise PlaywrightEvidenceError("Playwright output is not valid JSON") from exc
    if not isinstance(report, dict) or not isinstance(report.get("suites"), list):
        raise PlaywrightEvidenceError("Playwright JSON report has no suites array")

    normalized: list[PlaywrightTestEvidence] = []
    for spec in _walk_specs(report["suites"]):
        title = str(spec.get("title") or "unknown")
        file_name = str(spec.get("file") or "")
        tests = spec.get("tests", [])
        if not isinstance(tests, list):
            raise PlaywrightEvidenceError("Playwright spec tests must be an array")
        for index, test in enumerate(tests):
            if not isinstance(test, dict):
                raise PlaywrightEvidenceError("Playwright test entry must be an object")
            project = str(test.get("projectName") or "default")
            status, error = _test_status(test)
            normalized.append(
                PlaywrightTestEvidence(
                    id=f"{file_name or 'unknown'}::{title}::{project}::{index}",
                    title=title,
                    file=file_name,
                    project=project,
                    status=status,
                    error=error,
                )
            )

    return PlaywrightEvidence(
        total=len(normalized),
        passed=sum(test.status == "passed" for test in normalized),
        failed=sum(test.status == "failed" for test in normalized),
        skipped=sum(test.status == "skipped" for test in normalized),
        tests=tuple(normalized),
    )


def _walk_specs(suites: Iterable[Any]) -> Iterable[dict[str, Any]]:
    for suite in suites:
        if not isinstance(suite, dict):
            raise PlaywrightEvidenceError("Playwright suite entry must be an object")
        specs = suite.get("specs", [])
        nested = suite.get("suites", [])
        if not isinstance(specs, list) or not isinstance(nested, list):
            raise PlaywrightEvidenceError("Playwright suite arrays are malformed")
        for spec in specs:
            if not isinstance(spec, dict):
                raise PlaywrightEvidenceError("Playwright spec entry must be an object")
            yield spec
        yield from _walk_specs(nested)


def _test_status(test: dict[str, Any]) -> tuple[str, str]:
    annotations = test.get("annotations", [])
    if isinstance(annotations, list) and any(
        isinstance(annotation, dict)
        and str(annotation.get("type", "")).lower() in {"skip", "fixme"}
        for annotation in annotations
    ):
        return "skipped", "test is annotated as skipped or fixme"

    expected = str(test.get("expectedStatus") or "passed").lower()
    if expected == "skipped":
        return "skipped", "test expected status is skipped"

    results = test.get("results", [])
    if not isinstance(results, list):
        raise PlaywrightEvidenceError("Playwright test results must be an array")
    if not results:
        return "skipped", "test has no execution result"

    terminal = results[-1]
    if not isinstance(terminal, dict):
        raise PlaywrightEvidenceError("Playwright result entry must be an object")
    actual = str(terminal.get("status") or "").lower()
    if actual == "passed" and expected == "passed":
        return "passed", ""
    if actual == "skipped":
        return "skipped", "test execution was skipped"

    error = terminal.get("error")
    if isinstance(error, dict):
        message = str(error.get("message") or error.get("value") or "")
    else:
        message = str(error or "")
    if not message:
        message = f"terminal status was {actual or 'unknown'} (expected {expected})"
    return "failed", message[:1000]
