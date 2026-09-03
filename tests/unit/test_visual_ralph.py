"""Tests for VisualRalphController."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
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
from harness.provider import NetworkPolicy, ResourceLimits as SandboxResourceLimits
from harness.provider import SandboxHandle, SandboxSpec
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


def test_run_loop_converges_on_first_pass(tmp_path: Path):
    """run_loop returns converged immediately when visual verify passes."""
    from harness.visual_ralph import VisualRalphController

    provider = MagicMock()
    provider.create.return_value = SandboxHandle(id="ctr1", session_id="s1")
    provider.exec.return_value = _exec_result(stdout=PLAYWRIGHT_PASS_JSON, exit_code=0)
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    screenshot = tmp_path / "journey.png"
    screenshot.write_bytes(b"visual-proof")

    ctrl = VisualRalphController(
        provider=provider,
        config=_make_config(max_iterations=3),
        spec_id="001",
        strategy_id="default",
        base_dir=str(tmp_path),
        build_id="build-1",
    )

    with patch.object(ctrl, "_retrieve_screenshots", return_value=[str(screenshot)]):
        result = ctrl.run_loop(worktree_path=str(worktree))

    assert result.status == "passed"
    assert result.termination_reason == "converged"
    assert result.iterations == 1
    provider.destroy.assert_called_once()


def test_visual_loop_reuses_delivery_sandbox_and_starts_verification_services(
    tmp_path: Path,
) -> None:
    """Visual verification gets dependencies and the same service environment."""
    from harness.visual_ralph import VisualRalphController

    provider = MagicMock()
    provider.create.return_value = SandboxHandle(id="ctr1", session_id="s1")
    provider.exec.return_value = _exec_result(
        stdout=PLAYWRIGHT_PASS_JSON, exit_code=0
    )
    sandbox = SandboxSpec(
        image="delivery-image",
        image_source="config_override",
        worktree_mount=str(tmp_path),
        container_mount="/workspace",
        resource_limits=SandboxResourceLimits(),
        network_policy=NetworkPolicy(),
        env={},
        secrets_env={},
        post_create_command=None,
        forward_ports=[],
    )
    sandbox_factory = MagicMock(return_value=sandbox)
    (tmp_path / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n")
    screenshot = tmp_path / "journey.png"
    screenshot.write_bytes(b"visual-proof")
    materialized = SimpleNamespace(
        services=(object(),),
        verifier_environment={"TEST_DATABASE_URL": "postgresql://fixture"},
    )
    config = _make_config(max_iterations=1)
    config.verification_services = [object()]
    controller = VisualRalphController(
        provider=provider,
        config=config,
        spec_id="001",
        strategy_id="default",
        base_dir=str(tmp_path),
        build_id="build-1",
        sandbox_spec_factory=sandbox_factory,
    )

    with (
        patch("harness.visual_ralph.materialize_services", return_value=materialized),
        patch.object(
            controller, "_retrieve_screenshots", return_value=[str(screenshot)]
        ),
    ):
        result = controller.run_loop(worktree_path=str(tmp_path))

    assert result.status == "passed"
    sandbox_factory.assert_called_once_with(str(tmp_path))
    provider.start_services.assert_called_once_with(
        provider.create.return_value, materialized.services
    )
    bootstrap_call = next(
        call for call in provider.exec.call_args_list if "pnpm install" in call.args[1]
    )
    assert bootstrap_call.kwargs["cwd"] == "/workspace"
    assert bootstrap_call.kwargs["env"] == materialized.verifier_environment
    playwright_call = next(
        call for call in provider.exec.call_args_list if "playwright" in call.args[1]
    )
    assert playwright_call.kwargs["env"] == materialized.verifier_environment


def test_zero_test_failure_reports_command_stderr() -> None:
    from harness.visual_ralph import VisualRalphController

    provider = MagicMock()
    provider.exec.return_value = _exec_result(
        stdout=json.dumps({"suites": [], "errors": []}),
        stderr="sh: playwright: command not found",
        exit_code=127,
    )
    controller = VisualRalphController(
        provider=provider,
        config=_make_config(),
        spec_id="001",
        strategy_id="default",
    )

    result = controller._exec_visual_verify(
        SandboxHandle(id="abc123", session_id="s1")
    )

    assert result.failures[0].id == "playwright_no_tests"
    assert "command not found" in result.failures[0].error


def test_playwright_parse_failure_reports_command_stderr() -> None:
    """An empty/non-JSON command failure retains its actionable stderr."""
    from harness.visual_ralph import VisualRalphController

    provider = MagicMock()
    provider.exec.return_value = _exec_result(
        stdout="",
        stderr="pnpm: command not found",
        exit_code=127,
    )
    controller = VisualRalphController(
        provider=provider,
        config=_make_config(),
        spec_id="001",
        strategy_id="default",
    )

    result = controller._exec_visual_verify(
        SandboxHandle(id="abc123", session_id="s1")
    )

    assert result.failures[0].id == "playwright_parse_error"
    assert "pnpm: command not found" in result.failures[0].error


def test_visual_command_diagnostics_redact_runtime_credentials() -> None:
    from harness.visual_ralph import VisualRalphController

    secret_url = "postgresql://generated:secret@postgres:5432/echelon_verify"
    provider = MagicMock()
    provider.exec.return_value = _exec_result(
        stdout="",
        stderr=f"could not connect to {secret_url}",
        exit_code=1,
    )
    controller = VisualRalphController(
        provider=provider,
        config=_make_config(),
        spec_id="001",
        strategy_id="default",
    )
    controller._runtime_env = {"TEST_DATABASE_URL": secret_url}

    result = controller._exec_visual_verify(
        SandboxHandle(id="abc123", session_id="s1")
    )

    assert secret_url not in result.failures[0].error
    assert "[REDACTED:environment]" in result.failures[0].error


def test_visual_dependency_bootstrap_failure_is_actionable(
    tmp_path: Path,
) -> None:
    """Visual setup failures report the command output and stop before tests."""
    from harness.visual_ralph import VisualRalphController

    (tmp_path / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n")
    provider = MagicMock()
    provider.create.return_value = SandboxHandle(id="ctr1", session_id="s1")
    provider.exec.return_value = _exec_result(
        stdout="",
        stderr="ERR_PNPM_FETCH_403 registry denied",
        exit_code=1,
    )
    controller = VisualRalphController(
        provider=provider,
        config=_make_config(max_iterations=1),
        spec_id="001",
        strategy_id="default",
    )

    result = controller.run_loop(worktree_path=str(tmp_path))

    assert result.status == "blocked"
    assert result.termination_reason == "app_runtime_failed"
    assert "pnpm install" in result.final_verify.failures[0].error
    assert "ERR_PNPM_FETCH_403" in result.final_verify.failures[0].error
    provider.destroy.assert_called_once_with(provider.create.return_value)


def test_run_loop_retains_success_screenshot_as_candidate_evidence(
    tmp_path: Path,
) -> None:
    """A successful visual gate persists sandbox imagery beyond retrieval staging."""
    from harness.visual_evidence import validate_visual_receipt
    from harness.visual_ralph import VisualRalphController

    worktree = tmp_path / "worktree"
    worktree.mkdir()
    (worktree / "app.ts").write_text("export const ready = true;\n", encoding="utf-8")
    screenshot = tmp_path / "source.png"
    screenshot.write_bytes(b"visual-proof")
    provider = MagicMock()
    provider.create.return_value = SandboxHandle(id="ctr1", session_id="s1")
    provider.exec.return_value = _exec_result(stdout=PLAYWRIGHT_PASS_JSON, exit_code=0)
    ctrl = VisualRalphController(
        provider=provider,
        config=_make_config(max_iterations=1),
        spec_id="001",
        strategy_id="default",
        base_dir=str(tmp_path),
        build_id="build-1",
    )

    with patch.object(ctrl, "_retrieve_screenshots", return_value=[str(screenshot)]):
        result = ctrl.run_loop(worktree_path=str(worktree))

    screenshot.unlink()
    assert result.status == "passed"
    assert result.evidence is not None
    assert result.evidence.artifact_count == 1
    assert validate_visual_receipt(
        result.evidence,
        candidate_fingerprint=result.evidence.candidate_fingerprint,
    ).valid


def test_run_loop_rejects_success_without_required_screenshot(tmp_path: Path) -> None:
    """Executed tests alone cannot satisfy the browser visual artifact gate."""
    from harness.visual_ralph import VisualRalphController

    worktree = tmp_path / "worktree"
    worktree.mkdir()
    (worktree / "app.ts").write_text("export const ready = true;\n", encoding="utf-8")
    provider = MagicMock()
    provider.create.return_value = SandboxHandle(id="ctr1", session_id="s1")
    provider.exec.side_effect = [
        _exec_result(stdout=PLAYWRIGHT_PASS_JSON, exit_code=0),
        _exec_result(stderr="could not create screenshot", exit_code=1),
    ]
    ctrl = VisualRalphController(
        provider=provider,
        config=_make_config(max_iterations=1),
        spec_id="001",
        strategy_id="default",
        base_dir=str(tmp_path),
        build_id="build-1",
    )

    with patch.object(ctrl, "_retrieve_screenshots", return_value=[]):
        result = ctrl.run_loop(worktree_path=str(worktree))

    assert result.status == "blocked"
    assert result.final_verify is not None
    assert result.final_verify.failures[0].id == "visual_artifacts_missing"
    assert result.evidence is not None
    assert result.evidence.passed is False


def test_run_loop_starts_waits_and_stops_command_app_runtime(tmp_path: Path):
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
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    screenshot = tmp_path / "journey.png"
    screenshot.write_bytes(b"visual-proof")

    ctrl = VisualRalphController(
        provider=provider,
        config=_make_command_app_config(),
        spec_id="001",
        strategy_id="default",
        base_dir=str(tmp_path),
        build_id="build-1",
    )

    with patch.object(ctrl, "_retrieve_screenshots", return_value=[str(screenshot)]):
        result = ctrl.run_loop(worktree_path=str(worktree))

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


def test_visual_feedback_uses_configured_provider_repair_runner(
    tmp_path: Path,
) -> None:
    """Visual repair delegates to Codex/Claude instead of a sandbox CLI binary."""
    from harness.visual_ralph import VisualRalphController

    provider = MagicMock()
    provider.create.return_value = SandboxHandle(id="ctr1", session_id="s1")
    provider.exec.return_value = _exec_result(
        stdout=PLAYWRIGHT_PASS_JSON,
        exit_code=0,
    )
    repair_runner = MagicMock(return_value={
        "exit_code": 0,
        "passed": True,
        "duration_s": 2.0,
        "tokens": 42,
        "stdout": "repair complete",
        "stderr": "",
    })
    controller = VisualRalphController(
        provider=provider,
        config=_make_config(max_iterations=1),
        spec_id="001",
        strategy_id="default",
        feedback_runner=repair_runner,
    )

    with patch.object(controller, "_retrieve_screenshots", return_value=[]):
        result = controller.run_loop(worktree_path=str(tmp_path))

    assert result.status == "fix_applied"
    assert result.tokens_used >= 42
    repair_runner.assert_called_once()
    assert repair_runner.call_args.args[1] == str(tmp_path)
    assert not any(
        "echelon build --fix" in call.args[1]
        for call in provider.exec.call_args_list
    )


def test_changed_visual_repair_can_defer_host_browser_verification(
    tmp_path: Path,
) -> None:
    """A changed candidate proceeds to authoritative sandbox re-verification."""
    from harness.visual_ralph import VisualRalphController

    worktree = tmp_path / "worktree"
    worktree.mkdir()
    (worktree / "playwright.config.ts").write_text("screenshot: 'off'\n")
    provider = MagicMock()
    provider.create.return_value = SandboxHandle(id="ctr1", session_id="s1")
    provider.exec.return_value = _exec_result(
        stdout=PLAYWRIGHT_PASS_JSON,
        exit_code=0,
    )

    def defer_after_change(*_args):
        (worktree / "playwright.config.ts").write_text("screenshot: 'on'\n")
        return {
            "exit_code": 0,
            "passed": False,
            "build_status": "blocked",
            "blocker_kind": "verification_environment",
            "completion_marker_explicit": True,
            "build_reason": "host Chromium unavailable",
            "duration_s": 2.0,
            "tokens": 42,
            "stdout": "",
            "stderr": "",
        }

    controller = VisualRalphController(
        provider=provider,
        config=_make_config(max_iterations=1),
        spec_id="001",
        strategy_id="default",
        feedback_runner=defer_after_change,
    )

    with patch.object(controller, "_retrieve_screenshots", return_value=[]):
        result = controller.run_loop(worktree_path=str(worktree))

    assert result.status == "fix_applied"
    assert (worktree / "playwright.config.ts").read_text() == "screenshot: 'on'\n"


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
    feedback_failure = next(
        failure
        for failure in result.final_verify.failures
        if failure.id == "visual_feedback_command_failed"
    )
    assert "build fix failed" in feedback_failure.error
