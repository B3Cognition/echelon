"""Tests for VisualRalphController."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from harness.config import GCConfig, HarnessConfig, NetworkConfig, ResourceLimits, VisualTestsConfig
from harness.exec_result import ExecResult, ResourceStats
from harness.loop_result import LoopResult
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


def _exec_result(stdout="", exit_code=0, duration_ms=1000) -> ExecResult:
    return ExecResult(
        stdout=stdout,
        stderr="",
        exit_code=exit_code,
        duration_ms=duration_ms,
        resource_stats=ResourceStats(peak_memory_bytes=0, cpu_time_ms=0, wall_time_ms=duration_ms),
    )


PLAYWRIGHT_PASS_JSON = json.dumps({
    "stats": {"expected": 3, "unexpected": 0, "skipped": 0, "flaky": 0},
    "suites": [],
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


def test_exec_visual_verify_fail_parses_failures():
    """Failing playwright JSON → VerifyResult with PLAYWRIGHT_TEST failures."""
    from harness.visual_ralph import VisualRalphController

    provider = MagicMock()
    provider.exec.return_value = _exec_result(stdout=PLAYWRIGHT_FAIL_JSON, exit_code=1)

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

    assert result.status == "converged"
    assert result.termination_reason == "converged"
    assert result.outer_iterations == 1
    provider.destroy.assert_called_once()


def test_run_loop_exhausts_max_iterations():
    """run_loop returns failed/visual_failed when max_iterations exceeded."""
    from harness.visual_ralph import VisualRalphController

    provider = MagicMock()
    provider.create.return_value = SandboxHandle(id="ctr1", session_id="s1")
    provider.exec.return_value = _exec_result(stdout=PLAYWRIGHT_FAIL_JSON, exit_code=1)

    ctrl = VisualRalphController(
        provider=provider,
        config=_make_config(max_iterations=2),
        spec_id="001",
        strategy_id="default",
        base_dir=".",
    )

    with patch.object(ctrl, "_retrieve_screenshots", return_value=[]):
        result = ctrl.run_loop(worktree_path="/tmp/wt")

    assert result.status == "failed"
    assert result.termination_reason == "visual_failed"
    assert result.outer_iterations == 2
    assert provider.destroy.call_count == 2
