"""Tests for VisualRalphController."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from harness.config import (
    AppRuntimeConfig,
    GCConfig,
    HarnessConfig,
    NetworkConfig,
    ResourceLimits,
    VisualTestsConfig,
)
from harness.exec_result import ExecResult, ResourceStats
from harness.delivery_results import VisualResult
from harness.provider import SandboxHandle
from harness.verify_result import FailureCategory, VerifyResult


def _make_config(enabled=True, max_iterations=2) -> HarnessConfig:
    return HarnessConfig(
        target_repo="https://github.com/x/y",
        target_default_branch="main",
        provider="docker",
        visual_tests=VisualTestsConfig(
            enabled=enabled,
            serve_command="npm run preview",
            test_command="npx playwright test --reporter=json",
            timeout_ms=60_000,
            screenshot_dir="playwright-report",
            max_iterations=max_iterations,
        ),
    )


def _make_command_app_config() -> HarnessConfig:
    config = _make_config(enabled=True, max_iterations=1)
    config.app = AppRuntimeConfig(
        enabled=True,
        mode="command",
        app="frontend",
        setup_commands=["docker compose -f compose.db.yml up -d postgres"],
        start_commands=["npx nx dev frontend"],
        stop_commands=["npx nx reset"],
        url="http://localhost:3000",
        readiness_timeout_ms=120_000,
    )
    return config


def _exec_result(stdout="", stderr="", exit_code=0, duration_ms=1000) -> ExecResult:
    return ExecResult(
        stdout=stdout,
        stderr=stderr,
        exit_code=exit_code,
        duration_ms=duration_ms,
        resource_stats=ResourceStats(peak_memory_bytes=0, cpu_time_ms=0, wall_time_ms=duration_ms),
    )


PLAYWRIGHT_PASS_JSON = json.dumps({
    "stats": {"expected": 1, "unexpected": 0, "skipped": 0, "flaky": 0},
    "suites": [{
        "specs": [{
            "title": "persistent journey",
            "file": "tests/journey.spec.ts",
            "tests": [{
                "projectName": "chromium",
                "expectedStatus": "passed",
                "results": [{"status": "passed"}],
            }],
        }],
    }],
    "errors": [],
})

PLAYWRIGHT_FAIL_JSON = json.dumps({
    "stats": {"expected": 3, "unexpected": 1, "skipped": 0, "flaky": 0},
    "suites": [{
        "specs": [{
            "title": "home renders",
            "tests": [{
                "results": [{
                    "status": "failed",
                    "error": {"message": "Expected visible"},
                    "attachments": [],
                }]
            }]
        }],
        "suites": [],
    }],
    "errors": [],
})


def test_exec_visual_verify_pass():
    """Passing playwright JSON → VerifyResult.passed = True, no failures."""
    from harness.visual_ralph import VisualRalphController

    provider = MagicMock()
    provider.exec.return_value = _exec_result(stdout=PLAYWRIGHT_PASS_JSON, exit_code=0)

    ctrl = VisualRalphController(
        provider=provider,
        config=_make_config(),
        spec_id="001",
        strategy_id="default",
        base_dir=".",
    )
    handle = SandboxHandle(id="abc123", session_id="s1")
    result = ctrl._exec_visual_verify(handle)

    assert result.passed is True
    assert result.failures == []
    assert result.verification_evidence["playwright"]["passed"] == 1


def test_exec_visual_verify_rejects_zero_test_success() -> None:
    """Exit zero is not sufficient when Playwright executed no tests."""
    from harness.visual_ralph import VisualRalphController

    provider = MagicMock()
    provider.exec.return_value = _exec_result(
        stdout=json.dumps({"suites": [], "errors": []}), exit_code=0
    )
    ctrl = VisualRalphController(
        provider=provider,
        config=_make_config(),
        spec_id="001",
        strategy_id="default",
    )

    result = ctrl._exec_visual_verify(SandboxHandle(id="abc123", session_id="s1"))

    assert result.passed is False
    assert result.failures[0].id == "playwright_no_tests"


def test_exec_visual_verify_rejects_skipped_required_test() -> None:
    """A discovered but skipped required journey cannot satisfy the visual gate."""
    from harness.visual_ralph import VisualRalphController

    report = json.dumps({
        "suites": [{
            "specs": [{
                "title": "persistent journey",
                "file": "tests/journey.spec.ts",
                "tests": [{
                    "projectName": "chromium",
                    "expectedStatus": "skipped",
                    "results": [{"status": "skipped"}],
                }],
            }],
        }],
    })
    provider = MagicMock()
    provider.exec.return_value = _exec_result(stdout=report, exit_code=0)
    ctrl = VisualRalphController(
        provider=provider,
        config=_make_config(),
        spec_id="001",
        strategy_id="default",
    )

    result = ctrl._exec_visual_verify(SandboxHandle(id="abc123", session_id="s1"))

    assert result.passed is False
    assert result.failures[0].id.startswith("playwright_skipped::")


def test_exec_visual_verify_fail_parses_failures():
    """Failing playwright JSON → VerifyResult with PLAYWRIGHT_TEST failures."""
    from harness.visual_ralph import VisualRalphController

    provider = MagicMock()
    provider.exec.side_effect = [
        _exec_result(stdout=PLAYWRIGHT_FAIL_JSON, exit_code=1),
        _exec_result(exit_code=0),
    ]

    ctrl = VisualRalphController(
        provider=provider,
        config=_make_config(),
        spec_id="001",
        strategy_id="default",
        base_dir=".",
    )
    handle = SandboxHandle(id="abc123", session_id="s1")
    result = ctrl._exec_visual_verify(handle)

    assert result.passed is False
    assert len(result.failures) == 1
    assert result.failures[0].category == FailureCategory.PLAYWRIGHT_TEST
    assert result.failures[0].id == "home renders"
    assert "Expected visible" in result.failures[0].error


def test_exec_visual_verify_non_json_stdout():
    """Non-JSON stdout → single parse_error failure entry."""
    from harness.visual_ralph import VisualRalphController

    provider = MagicMock()
    provider.exec.return_value = _exec_result(stdout="Error: playwright not found", exit_code=1)

    ctrl = VisualRalphController(
        provider=provider,
        config=_make_config(),
        spec_id="001",
        strategy_id="default",
        base_dir=".",
    )
    handle = SandboxHandle(id="abc123", session_id="s1")
    result = ctrl._exec_visual_verify(handle)

    assert result.passed is False
    assert len(result.failures) == 1
    assert result.failures[0].category == FailureCategory.PLAYWRIGHT_TEST
    assert result.failures[0].id == "playwright_parse_error"


def test_run_loop_converges_on_first_pass():
    """run_loop returns converged immediately when visual verify passes."""
    from harness.visual_ralph import VisualRalphController

    provider = MagicMock()
    provider.create.return_value = SandboxHandle(id="ctr1", session_id="s1")
    provider.exec.return_value = _exec_result(stdout=PLAYWRIGHT_PASS_JSON, exit_code=0)

    ctrl = VisualRalphController(
        provider=provider,
        config=_make_config(max_iterations=3),
        spec_id="001",
        strategy_id="default",
        base_dir=".",
    )

    with patch.object(ctrl, "_retrieve_screenshots", return_value=[]):
        result = ctrl.run_loop(worktree_path="/tmp/wt")

    assert result.status == "passed"
    assert result.termination_reason == "converged"
    assert result.iterations == 1
    provider.destroy.assert_called_once()


def test_run_loop_starts_waits_and_stops_command_app_runtime():
    """command app profile starts before Playwright and stops during cleanup."""
    from harness.visual_ralph import VisualRalphController

    provider = MagicMock()
    provider.create.return_value = SandboxHandle(id="ctr1", session_id="s1")
    provider.exec.side_effect = [
        _exec_result(stdout="db ready", exit_code=0),  # setup command
        _exec_result(stdout="123\n", exit_code=0),  # start command backgrounded
        _exec_result(stdout="ready", exit_code=0),  # readiness curl
        _exec_result(stdout=PLAYWRIGHT_PASS_JSON, exit_code=0),  # playwright
        _exec_result(stdout="", exit_code=0),  # explicit stop command
        _exec_result(stdout="", exit_code=0),  # pid cleanup
    ]

    ctrl = VisualRalphController(
        provider=provider,
        config=_make_command_app_config(),
        spec_id="001",
        strategy_id="default",
        base_dir=".",
    )

    result = ctrl.run_loop(worktree_path="/tmp/wt")

    assert result.status == "passed"
    executed = [call.args[1] for call in provider.exec.call_args_list]
    assert executed[0] == "docker compose -f compose.db.yml up -d postgres"
    assert "npx nx dev frontend" in executed[1]
    assert "curl -fsS http://localhost:3000" in executed[2]
    assert executed[3] == "npx playwright test --reporter=json"
    assert executed[4] == "npx nx reset"


def test_run_loop_reports_fix_applied_after_visual_feedback():
    """A visual fix is handed back to Phase 1 for re-verification."""
    from harness.visual_ralph import VisualRalphController

    provider = MagicMock()
    provider.create.return_value = SandboxHandle(id="ctr1", session_id="s1")
    provider.exec.side_effect = [
        _exec_result(stdout="db ready", exit_code=0),
        _exec_result(stdout="123\n", exit_code=0),
        _exec_result(stdout="ready", exit_code=0),
        _exec_result(stdout=PLAYWRIGHT_FAIL_JSON, exit_code=1),
        _exec_result(stdout="", exit_code=0),
        _exec_result(stdout="", exit_code=0),
        _exec_result(stdout="", exit_code=0),
    ]

    ctrl = VisualRalphController(
        provider=provider,
        config=_make_command_app_config(),
        spec_id="001",
        strategy_id="default",
        base_dir=".",
    )

    with patch.object(ctrl, "_retrieve_screenshots", return_value=[]):
        result = ctrl.run_loop(worktree_path="/tmp/wt")

    assert result.status == "fix_applied"
    executed = [call.args[1] for call in provider.exec.call_args_list]
    assert "npx nx reset" in executed


def test_run_loop_reports_failure_when_command_app_never_ready():
    """readiness failure returns structured visual_failed and still cleans up."""
    from harness.visual_ralph import VisualRalphController

    provider = MagicMock()
    provider.create.return_value = SandboxHandle(id="ctr1", session_id="s1")
    provider.exec.side_effect = [
        _exec_result(stdout="db ready", exit_code=0),
        _exec_result(stdout="123\n", exit_code=0),
        _exec_result(stdout="", stderr="curl failed", exit_code=1),
        _exec_result(stdout="", exit_code=0),
        _exec_result(stdout="", exit_code=0),
    ]

    ctrl = VisualRalphController(
        provider=provider,
        config=_make_command_app_config(),
        spec_id="001",
        strategy_id="default",
        base_dir=".",
    )

    result = ctrl.run_loop(worktree_path="/tmp/wt")

    assert result.status == "blocked"
    assert result.termination_reason == "app_runtime_failed"
    assert result.final_verify is not None
    assert result.final_verify.failures[0].id == "app-runtime"
    provider.destroy.assert_called_once()


def test_run_loop_reports_failure_when_setup_command_fails():
    """setup command failure returns structured app_runtime_failed."""
    from harness.visual_ralph import VisualRalphController

    provider = MagicMock()
    provider.create.return_value = SandboxHandle(id="ctr1", session_id="s1")
    provider.exec.side_effect = [
        _exec_result(stdout="", stderr="compose failed", exit_code=1),
        _exec_result(stdout="", exit_code=0),
        _exec_result(stdout="", exit_code=0),
    ]

    ctrl = VisualRalphController(
        provider=provider,
        config=_make_command_app_config(),
        spec_id="001",
        strategy_id="default",
        base_dir=".",
    )

    result = ctrl.run_loop(worktree_path="/tmp/wt")

    assert result.status == "blocked"
    assert result.termination_reason == "app_runtime_failed"
    assert result.final_verify is not None
    assert "setup command failed" in result.final_verify.failures[0].error
    provider.destroy.assert_called_once()


def test_run_loop_reports_fix_applied_without_retrying_visual_evidence():
    """run_loop returns the first applied fix instead of accepting a later pass."""
    from harness.visual_ralph import VisualRalphController

    provider = MagicMock()
    provider.create.return_value = SandboxHandle(id="ctr1", session_id="s1")
    provider.exec.side_effect = [
        _exec_result(stdout=PLAYWRIGHT_FAIL_JSON, exit_code=1),
        _exec_result(stdout="visual fix queued", exit_code=0),
    ]

    ctrl = VisualRalphController(
        provider=provider,
        config=_make_config(max_iterations=2),
        spec_id="001",
        strategy_id="default",
        base_dir=".",
    )

    with patch.object(ctrl, "_retrieve_screenshots", return_value=[]):
        result = ctrl.run_loop(worktree_path="/tmp/wt")

    assert result.status == "fix_applied"
    assert result.termination_reason == "fix_applied"
    assert result.iterations == 1
    assert provider.destroy.call_count == 1


def test_run_loop_blocks_when_visual_feedback_fails():
    """A failed feedback command cannot be reported as an applied visual fix."""
    from harness.visual_ralph import VisualRalphController

    provider = MagicMock()
    provider.create.return_value = SandboxHandle(id="ctr1", session_id="s1")
    provider.exec.side_effect = [
        _exec_result(stdout=PLAYWRIGHT_FAIL_JSON, exit_code=1),
        _exec_result(stderr="build fix failed", exit_code=1),
    ]
    ctrl = VisualRalphController(
        provider=provider,
        config=_make_config(max_iterations=1),
        spec_id="001",
        strategy_id="default",
    )

    with patch.object(ctrl, "_retrieve_screenshots", return_value=[]):
        result = ctrl.run_loop(worktree_path="/tmp/wt")

    assert result.status == "blocked"
    assert result.termination_reason == "visual_feedback_failed"
