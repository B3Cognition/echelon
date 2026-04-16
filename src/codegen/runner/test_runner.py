"""
test_runner.py — Tier 1 test execution and result parsing.
Spec 008: SOAR-Powered Claude Code Software Development Agent
Version: 1.0.0

T-023: Test Runner Integration.

Responsibilities:
  1. Run language-appropriate test command (FR-TEST-001, ADR-008-005).
  2. Parse test runner output → TestResult WME (FR-TEST-001).
  3. Instability detection per run history (FR-TEST-008):
       pass < 2 of 3 consecutive runs → "unstable" (not "confirmed-failing").
  4. Regression eval registry (FR-TEST-003):
       test passed in run N-1 and fails in run N → RETRY_TASK signal.
  5. INV-010: test-pass-rate 1.0 is gate condition for DELIVER.

Supported runners (ADR-008-005 table):
  - python     → pytest --tb=short --json-report --json-report-file=...
  - typescript → vitest --reporter=json  /  jest --json
  - go         → go test -v -json ./...
  - java       → mvn test (surefire XML reports)
"""

from __future__ import annotations

import json
import re
import subprocess
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Enums & constants
# ---------------------------------------------------------------------------

class TestStatus(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    ERROR = "error"
    UNSTABLE = "unstable"          # FR-TEST-008
    CONFIRMED_FAILING = "confirmed-failing"  # ≥ 2 of 3 consecutive failures


class SoarSignal(str, Enum):
    """SOAR operator signals produced by the runner."""
    DELIVER = "DELIVER"           # test-pass-rate == 1.0
    RETRY_TASK = "RETRY_TASK"     # regression detected
    ESCALATE = "ESCALATE"         # max retries exceeded with failures


# ADR-008-005 runner commands (template — caller substitutes paths)
_RUNNER_COMMANDS: dict[str, list[str]] = {
    "python": [
        "python", "-m", "pytest",
        "--tb=short",
        "--json-report",
        "--json-report-file={report_path}",
        "{test_path}",
    ],
    "typescript": [
        "npx", "vitest", "run",
        "--reporter=json",
        "--outputFile={report_path}",
        "{test_path}",
    ],
    "javascript": [
        "npx", "jest",
        "--json",
        "--outputFile={report_path}",
        "{test_path}",
    ],
    "go": [
        "go", "test", "-v", "-json", "./...",
    ],
    "java": [
        "mvn", "test",
        "-Dsurefire.reportsDirectory={report_path}",
    ],
}

# History window for instability detection
_INSTABILITY_WINDOW = 3
_INSTABILITY_PASS_THRESHOLD = 2   # must pass ≥ this many in window to be stable


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class TestCaseResult:
    """Result for a single test case."""
    name: str
    status: TestStatus
    duration_ms: float = 0.0
    error_message: str = ""
    file: str = ""


@dataclass
class TestResult:
    """
    Aggregate test result WME for one task execution.

    FR-TEST-001: Must include test-pass-rate, status, and per-test breakdown.
    INV-010: test-pass-rate 1.0 is the gate condition for DELIVER.
    """
    task_id: str
    language: str
    total: int = 0
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    errors: int = 0
    duration_ms: float = 0.0
    test_cases: list[TestCaseResult] = field(default_factory=list)
    runner_output: str = ""
    soar_signal: Optional[SoarSignal] = None
    regression_tests: list[str] = field(default_factory=list)  # FR-TEST-003

    @property
    def test_pass_rate(self) -> float:
        """Fraction of tests that passed (0.0–1.0)."""
        if self.total == 0:
            return 1.0   # vacuously true (no tests = nothing failed)
        return self.passed / self.total

    @property
    def build_status(self) -> str:
        """CLEAN if all tests pass, FAILING otherwise."""
        return "CLEAN" if self.test_pass_rate == 1.0 else "FAILING"

    def to_wme_dict(self) -> dict[str, Any]:
        """Serialize as a SOAR TestResult WME."""
        return {
            "wme_type": "test-result",
            "task-id": self.task_id,
            "language": self.language,
            "test-pass-rate": round(self.test_pass_rate, 4),
            "build-status": self.build_status,
            "total": self.total,
            "passed": self.passed,
            "failed": self.failed,
            "skipped": self.skipped,
            "errors": self.errors,
            "duration-ms": self.duration_ms,
            "soar-signal": self.soar_signal.value if self.soar_signal else None,
            "regression-tests": self.regression_tests,
            "preference": "best",   # INV-003
        }


# ---------------------------------------------------------------------------
# Instability tracker (FR-TEST-008)
# ---------------------------------------------------------------------------

@dataclass
class RunHistory:
    """Per-test run history for instability detection."""
    test_name: str
    outcomes: list[bool] = field(default_factory=list)   # True=passed, False=failed

    def record(self, passed: bool) -> None:
        self.outcomes.append(passed)
        # Keep only the last _INSTABILITY_WINDOW outcomes
        if len(self.outcomes) > _INSTABILITY_WINDOW:
            self.outcomes = self.outcomes[-_INSTABILITY_WINDOW:]

    def effective_status(self) -> TestStatus:
        """
        FR-TEST-008: classify stability.
          - < WINDOW runs: return based on last outcome.
          - WINDOW runs present:
              pass_count ≥ threshold → "passed" (stable pass)
              pass_count == 0        → "confirmed-failing"
              else                   → "unstable"
        """
        if not self.outcomes:
            return TestStatus.PASSED
        if len(self.outcomes) < _INSTABILITY_WINDOW:
            return TestStatus.PASSED if self.outcomes[-1] else TestStatus.FAILED

        pass_count = sum(self.outcomes[-_INSTABILITY_WINDOW:])
        if pass_count >= _INSTABILITY_PASS_THRESHOLD:
            return TestStatus.PASSED
        elif pass_count == 0:
            return TestStatus.CONFIRMED_FAILING
        else:
            return TestStatus.UNSTABLE


class InstabilityTracker:
    """
    Tracks run history for all tests across multiple executions.

    FR-TEST-008: unstable tests must NOT block phase advancement.
    SOAR gates on confirmed-failing, not unstable.
    """

    def __init__(self) -> None:
        self._histories: dict[str, RunHistory] = {}

    def record_run(self, test_cases: list[TestCaseResult]) -> None:
        """Record the outcome of each test case in a run."""
        for tc in test_cases:
            if tc.name not in self._histories:
                self._histories[tc.name] = RunHistory(tc.name)
            passed = tc.status == TestStatus.PASSED
            self._histories[tc.name].record(passed)

    def effective_status(self, test_name: str) -> TestStatus:
        """Return the instability-adjusted status for a test."""
        if test_name not in self._histories:
            return TestStatus.PASSED
        return self._histories[test_name].effective_status()

    def apply_to_result(self, result: TestResult) -> TestResult:
        """
        Recompute passed/failed/unstable counts after applying instability logic.

        Tests classified as "unstable" are excluded from the failing count
        so SOAR does not block phase advancement for them.
        """
        adjusted_passed = 0
        adjusted_failed = 0
        adjusted_unstable = 0

        for tc in result.test_cases:
            eff = self.effective_status(tc.name)
            if eff in (TestStatus.PASSED,):
                adjusted_passed += 1
            elif eff == TestStatus.UNSTABLE:
                adjusted_unstable += 1
                tc.status = TestStatus.UNSTABLE
            elif eff == TestStatus.CONFIRMED_FAILING:
                adjusted_failed += 1
                tc.status = TestStatus.CONFIRMED_FAILING
            # else: keep original

        # Only update counts if individual test_cases were parsed;
        # fall back to summary-level counts from runner output.
        if result.test_cases:
            result.passed = adjusted_passed
            result.failed = adjusted_failed
        # Unstable tests are not counted in failed (FR-TEST-008)
        return result

    def get_history(self, test_name: str) -> Optional[RunHistory]:
        return self._histories.get(test_name)


# ---------------------------------------------------------------------------
# Regression registry (FR-TEST-003)
# ---------------------------------------------------------------------------

class RegressionRegistry:
    """
    Detect tests that passed in a prior run but fail in the current run.

    FR-TEST-003: regression → SOAR RETRY_TASK signal.
    """

    def __init__(self) -> None:
        self._prior_passing: dict[str, set[str]] = {}   # task_id → set of test names

    def record_passing(self, task_id: str, test_cases: list[TestCaseResult]) -> None:
        """Store the set of passing tests for a task after a successful run."""
        self._prior_passing[task_id] = {
            tc.name for tc in test_cases if tc.status == TestStatus.PASSED
        }

    def detect_regressions(
        self, task_id: str, test_cases: list[TestCaseResult]
    ) -> list[str]:
        """
        Return test names that passed in the prior run but fail now.
        """
        prior = self._prior_passing.get(task_id, set())
        current_failing = {
            tc.name for tc in test_cases
            if tc.status in (TestStatus.FAILED, TestStatus.CONFIRMED_FAILING, TestStatus.ERROR)
        }
        return sorted(prior & current_failing)

    def has_prior_run(self, task_id: str) -> bool:
        return task_id in self._prior_passing


# ---------------------------------------------------------------------------
# Output parsers
# ---------------------------------------------------------------------------

def _parse_pytest_json(report_path: Path, task_id: str, language: str) -> TestResult:
    """Parse pytest-json-report output."""
    data = json.loads(report_path.read_text())
    summary = data.get("summary", {})
    tests = data.get("tests", [])

    cases: list[TestCaseResult] = []
    for t in tests:
        status_str = t.get("outcome", "failed").lower()
        status = TestStatus.PASSED if status_str == "passed" else (
            TestStatus.SKIPPED if status_str == "skipped" else TestStatus.FAILED
        )
        cases.append(TestCaseResult(
            name=t.get("nodeid", t.get("name", "unknown")),
            status=status,
            duration_ms=t.get("duration", 0.0) * 1000,
        ))

    return TestResult(
        task_id=task_id,
        language=language,
        total=summary.get("total", len(tests)),
        passed=summary.get("passed", 0),
        failed=summary.get("failed", 0),
        skipped=summary.get("skipped", 0),
        errors=summary.get("error", 0),
        duration_ms=data.get("duration", 0.0) * 1000,
        test_cases=cases,
    )


def _parse_vitest_json(report_path: Path, task_id: str, language: str) -> TestResult:
    """Parse vitest --reporter=json output."""
    data = json.loads(report_path.read_text())
    # Vitest JSON: {"numTotalTests": N, "numPassedTests": P, ...}
    cases: list[TestCaseResult] = []
    for suite in data.get("testResults", []):
        for t in suite.get("assertionResults", []):
            status_str = t.get("status", "failed").lower()
            status = TestStatus.PASSED if status_str == "passed" else (
                TestStatus.SKIPPED if status_str == "skipped" else TestStatus.FAILED
            )
            cases.append(TestCaseResult(
                name=t.get("fullName", t.get("title", "unknown")),
                status=status,
                duration_ms=t.get("duration", 0.0),
            ))

    total = data.get("numTotalTests", len(cases))
    passed = data.get("numPassedTests", sum(1 for c in cases if c.status == TestStatus.PASSED))
    failed = data.get("numFailedTests", sum(1 for c in cases if c.status == TestStatus.FAILED))
    skipped = data.get("numPendingTests", 0) + data.get("numSkippedTests", 0)

    return TestResult(
        task_id=task_id,
        language=language,
        total=total,
        passed=passed,
        failed=failed,
        skipped=skipped,
        duration_ms=data.get("startTime", 0),
        test_cases=cases,
    )


def _parse_go_json(output: str, task_id: str) -> TestResult:
    """Parse go test -json output (one JSON object per line)."""
    cases: dict[str, TestCaseResult] = {}
    total_duration_ms = 0.0

    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue

        action = event.get("Action", "")
        test_name = event.get("Test")
        elapsed = event.get("Elapsed", 0.0) * 1000

        if test_name is None:
            if action == "pass":
                total_duration_ms += elapsed
            continue

        if test_name not in cases:
            cases[test_name] = TestCaseResult(name=test_name, status=TestStatus.PASSED)

        if action == "pass":
            cases[test_name].status = TestStatus.PASSED
            cases[test_name].duration_ms = elapsed
        elif action == "fail":
            cases[test_name].status = TestStatus.FAILED
            cases[test_name].duration_ms = elapsed
        elif action == "skip":
            cases[test_name].status = TestStatus.SKIPPED

    case_list = list(cases.values())
    passed = sum(1 for c in case_list if c.status == TestStatus.PASSED)
    failed = sum(1 for c in case_list if c.status == TestStatus.FAILED)
    skipped = sum(1 for c in case_list if c.status == TestStatus.SKIPPED)

    return TestResult(
        task_id=task_id,
        language="go",
        total=len(case_list),
        passed=passed,
        failed=failed,
        skipped=skipped,
        duration_ms=total_duration_ms,
        test_cases=case_list,
    )


def _parse_surefire_xml(report_dir: Path, task_id: str) -> TestResult:
    """Parse Maven Surefire XML reports."""
    cases: list[TestCaseResult] = []
    total = passed = failed = skipped = errors = 0
    total_duration_ms = 0.0

    for xml_file in report_dir.glob("TEST-*.xml"):
        try:
            root = ET.parse(xml_file).getroot()
        except ET.ParseError:
            continue
        for tc in root.findall(".//testcase"):
            name = f"{tc.get('classname', '')}.{tc.get('name', 'unknown')}"
            duration_ms = float(tc.get("time", 0.0)) * 1000
            total_duration_ms += duration_ms

            if tc.find("failure") is not None or tc.find("error") is not None:
                status = TestStatus.FAILED
                failed += 1
            elif tc.find("skipped") is not None:
                status = TestStatus.SKIPPED
                skipped += 1
            else:
                status = TestStatus.PASSED
                passed += 1
            total += 1
            cases.append(TestCaseResult(name=name, status=status, duration_ms=duration_ms))

    return TestResult(
        task_id=task_id,
        language="java",
        total=total,
        passed=passed,
        failed=failed,
        skipped=skipped,
        errors=errors,
        duration_ms=total_duration_ms,
        test_cases=cases,
    )


# ---------------------------------------------------------------------------
# Result parsing from raw subprocess output (no report file)
# ---------------------------------------------------------------------------

def _parse_pytest_stdout(output: str, task_id: str) -> TestResult:
    """Minimal fallback: parse pytest text output for pass/fail summary."""
    # e.g. "5 passed, 1 failed in 0.32s"
    passed = failed = skipped = errors = 0
    m = re.search(r"(\d+) passed", output)
    if m:
        passed = int(m.group(1))
    m = re.search(r"(\d+) failed", output)
    if m:
        failed = int(m.group(1))
    m = re.search(r"(\d+) skipped", output)
    if m:
        skipped = int(m.group(1))
    m = re.search(r"(\d+) error", output)
    if m:
        errors = int(m.group(1))

    # Parse individual test outcomes (PASSED/FAILED lines)
    cases: list[TestCaseResult] = []
    for line in output.splitlines():
        if " PASSED" in line:
            name = line.split("PASSED")[0].strip()
            cases.append(TestCaseResult(name=name, status=TestStatus.PASSED))
        elif " FAILED" in line:
            name = line.split("FAILED")[0].strip()
            cases.append(TestCaseResult(name=name, status=TestStatus.FAILED))

    total = passed + failed + skipped + errors
    return TestResult(
        task_id=task_id,
        language="python",
        total=total,
        passed=passed,
        failed=failed,
        skipped=skipped,
        errors=errors,
        test_cases=cases,
        runner_output=output,
    )


# ---------------------------------------------------------------------------
# SOAR signal assignment (INV-010, FR-DELIVER-002)
# ---------------------------------------------------------------------------

def _assign_soar_signal(
    result: TestResult,
    retry_count: int,
    max_retries: int,
    regressions: list[str],
) -> SoarSignal:
    """
    Determine the SOAR operator signal based on test result.

    INV-010: test-pass-rate 1.0 → DELIVER.
    FR-TEST-003: regression → RETRY_TASK (before checking DELIVER).
    SOAR-RT-004: retry_count >= max_retries with failures → ESCALATE.
    """
    if regressions:
        # FR-TEST-003: regression always triggers RETRY_TASK
        if retry_count >= max_retries:
            return SoarSignal.ESCALATE
        return SoarSignal.RETRY_TASK

    # Count only confirmed-failing (unstable excluded per FR-TEST-008)
    confirmed_failing = sum(
        1 for tc in result.test_cases
        if tc.status == TestStatus.CONFIRMED_FAILING
    )
    raw_failing = result.failed

    # If unstable tests are the only "failures", treat as pass for DELIVER signal
    effective_failing = max(confirmed_failing, raw_failing)

    if effective_failing == 0 and result.test_pass_rate == 1.0:
        return SoarSignal.DELIVER

    if retry_count >= max_retries:
        return SoarSignal.ESCALATE

    return SoarSignal.RETRY_TASK


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

class TierOneRunner:
    """
    Tier 1 test runner integration.

    Executes the appropriate test runner for a task, parses output,
    applies instability detection and regression checking, and returns
    a TestResult WME with a SOAR operator signal.

    FR-TEST-001: run tests after IMPLEMENTER completes.
    FR-TEST-008: instability detection.
    FR-TEST-003: regression eval registry.
    INV-010: test-pass-rate gate for DELIVER.
    """

    def __init__(
        self,
        instability_tracker: Optional[InstabilityTracker] = None,
        regression_registry: Optional[RegressionRegistry] = None,
        max_retries: int = 3,
        timeout_seconds: int = 120,
        dry_run: bool = False,       # if True, skip subprocess execution
    ) -> None:
        self.instability_tracker = instability_tracker or InstabilityTracker()
        self.regression_registry = regression_registry or RegressionRegistry()
        self.max_retries = max_retries
        self.timeout_seconds = timeout_seconds
        self.dry_run = dry_run

    def run(
        self,
        task_id: str,
        language: str,
        test_path: Path,
        project_root: Path,
        retry_count: int = 0,
        report_dir: Optional[Path] = None,
    ) -> TestResult:
        """
        Run Tier 1 tests for a task and return a TestResult WME.

        Args:
            task_id:      Task identifier.
            language:     Target language.
            test_path:    Path to the test file or directory.
            project_root: Project root (for go test ./... invocation).
            retry_count:  Current retry number (for SOAR signal logic).
            report_dir:   Directory for report files (defaults to tmp).
        """
        lang = language.lower().strip()
        if report_dir is None:
            report_dir = project_root / ".echelon" / "reports"
        report_dir.mkdir(parents=True, exist_ok=True)

        if self.dry_run:
            result = self._dry_run_result(task_id, lang)
        else:
            result = self._execute(task_id, lang, test_path, project_root, report_dir)

        # Apply instability detection
        self.instability_tracker.record_run(result.test_cases)
        result = self.instability_tracker.apply_to_result(result)

        # Detect regressions
        regressions = []
        if self.regression_registry.has_prior_run(task_id):
            regressions = self.regression_registry.detect_regressions(task_id, result.test_cases)
        result.regression_tests = regressions

        # Record passing tests for future regression detection
        if result.test_pass_rate == 1.0:
            self.regression_registry.record_passing(task_id, result.test_cases)

        # Assign SOAR signal
        result.soar_signal = _assign_soar_signal(
            result, retry_count, self.max_retries, regressions,
        )

        return result

    def run_from_output(
        self,
        task_id: str,
        language: str,
        raw_output: str,
        retry_count: int = 0,
    ) -> TestResult:
        """
        Parse a pre-captured test runner output string.

        Used when the subprocess is executed externally (e.g. in tests
        that supply mock output).
        """
        lang = language.lower().strip()
        result = self._parse_output(task_id, lang, raw_output)

        self.instability_tracker.record_run(result.test_cases)
        result = self.instability_tracker.apply_to_result(result)

        regressions = []
        if self.regression_registry.has_prior_run(task_id):
            regressions = self.regression_registry.detect_regressions(task_id, result.test_cases)
        result.regression_tests = regressions

        if result.test_pass_rate == 1.0:
            self.regression_registry.record_passing(task_id, result.test_cases)

        result.soar_signal = _assign_soar_signal(
            result, retry_count, self.max_retries, regressions,
        )
        return result

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _execute(
        self,
        task_id: str,
        language: str,
        test_path: Path,
        project_root: Path,
        report_dir: Path,
    ) -> TestResult:
        """Execute the test runner subprocess."""
        report_path = report_dir / f"{task_id}-report.json"

        cmd_template = _RUNNER_COMMANDS.get(language)
        if cmd_template is None:
            raise ValueError(f"No runner configured for language '{language}'")

        cmd = [
            part.format(
                report_path=str(report_path),
                test_path=str(test_path),
            )
            for part in cmd_template
        ]

        try:
            proc = subprocess.run(
                cmd,
                cwd=str(project_root),
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
            )
            raw_output = proc.stdout + "\n" + proc.stderr
        except subprocess.TimeoutExpired:
            return TestResult(
                task_id=task_id,
                language=language,
                runner_output="TIMEOUT",
                soar_signal=SoarSignal.ESCALATE,
            )
        except FileNotFoundError as exc:
            raise RuntimeError(
                f"Test runner not found for language '{language}'. "
                f"Ensure the runner is installed before executing Tier 1 tests. "
                f"Original error: {exc}"
            ) from exc

        # Try to parse report file first, fall back to stdout parsing
        if report_path.exists():
            try:
                if language == "python":
                    return _parse_pytest_json(report_path, task_id, language)
                elif language in ("typescript", "javascript"):
                    return _parse_vitest_json(report_path, task_id, language)
            except (json.JSONDecodeError, KeyError):
                pass
        elif language == "java":
            return _parse_surefire_xml(report_dir, task_id)
        elif language == "go":
            return _parse_go_json(raw_output, task_id)

        return self._parse_output(task_id, language, raw_output)

    def _parse_output(self, task_id: str, language: str, raw_output: str) -> TestResult:
        """Fallback: parse raw text output."""
        if language in ("go",):
            return _parse_go_json(raw_output, task_id)
        # Default: pytest-style text
        result = _parse_pytest_stdout(raw_output, task_id)
        result.language = language
        return result

    def _dry_run_result(self, task_id: str, language: str) -> TestResult:
        """Return a synthetic all-pass result for dry-run mode."""
        return TestResult(
            task_id=task_id,
            language=language,
            total=1,
            passed=1,
            test_cases=[TestCaseResult(name="dry_run_placeholder", status=TestStatus.PASSED)],
            runner_output="dry-run",
        )

    def build_command(self, language: str, test_path: Path, report_path: Path) -> list[str]:
        """Return the shell command that would be executed (for display/logging)."""
        cmd_template = _RUNNER_COMMANDS.get(language.lower(), [])
        return [
            part.format(report_path=str(report_path), test_path=str(test_path))
            for part in cmd_template
        ]
