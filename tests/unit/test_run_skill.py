"""Tests for run_skill auto-land integration.

Verifies that the run() function calls land() instead of attempt_auto_merge
when auto_merge is True on the intent.
"""

from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from harness.harness_run_history import history_path
from harness.delivery_results import DeliveryResult
from harness.run_intent import RunIntent
from harness.skills.run_skill import RunContextError, _resolve_run_roots
from harness.verify_result import FailureCategory, FailureEntry, VerifyResult


def _make_converged_result() -> DeliveryResult:
    return DeliveryResult(
        status="converged",
        termination_reason="converged",
        outer_iterations=1,
        inner_iterations=0,
        pr_url="https://github.com/t/r/pull/1",
        tokens_used=10000,
        final_verify=VerifyResult(passed=True, failures=[]),
        blocked_phase=None,
    )


def _make_failed_result() -> DeliveryResult:
    return DeliveryResult(
        status="blocked",
        termination_reason="outer_cap",
        outer_iterations=5,
        inner_iterations=0,
        pr_url="https://github.com/t/r/pull/1",
        tokens_used=50000,
        final_verify=VerifyResult(passed=False, failures=[]),
        blocked_phase="implementation",
    )


def _make_checkpoint_result() -> DeliveryResult:
    return DeliveryResult(
        status="blocked",
        termination_reason="build_incomplete",
        outer_iterations=2,
        inner_iterations=3,
        pr_url=None,
        tokens_used=0,
        final_verify=None,
        blocked_phase="implementation",
        branch="001-demo",
    )


def _make_checkpoint_outer_cap_result() -> DeliveryResult:
    return DeliveryResult(
        status="blocked",
        termination_reason="checkpoint_outer_cap",
        outer_iterations=5,
        inner_iterations=0,
        pr_url="https://github.com/t/r/pull/1",
        tokens_used=0,
        final_verify=VerifyResult(
            passed=False,
            failures=[
                FailureEntry(
                    category=FailureCategory.OTHER,
                    id="fulfillment-refresh-deferred",
                    error="full verify-spec refresh deferred",
                )
            ],
        ),
        blocked_phase="implementation",
        branch="001-demo",
    )


def test_resolve_run_roots_defaults_workspace_to_harness_root(tmp_path: Path) -> None:
    harness_root, workspace_root = _resolve_run_roots(str(tmp_path), None)

    assert harness_root == tmp_path.resolve()
    assert workspace_root == tmp_path.resolve()


def test_resolve_run_roots_keeps_polyrepo_roots_distinct(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    harness = workspace / "runs" / "targets" / "api"
    harness.mkdir(parents=True)

    harness_root, workspace_root = _resolve_run_roots(harness, workspace)

    assert harness_root == harness.resolve()
    assert workspace_root == workspace.resolve()


def test_resolve_run_roots_rejects_missing_explicit_workspace(tmp_path: Path) -> None:
    missing = tmp_path / "missing"

    with pytest.raises(
        RunContextError,
        match=f"orchestration root is not a directory: {missing.resolve()}",
    ):
        _resolve_run_roots(tmp_path, missing)


@pytest.mark.unit
class TestRunContextValidation:
    @patch("harness.skills.run_skill.StrategyCoordinator")
    @patch("harness.skills.run_skill.find_spec_dir")
    @patch("harness.skills.run_skill.parse_intent")
    def test_run_rejects_missing_explicit_orchestration_root_before_coordinator(
        self,
        mock_parse: MagicMock,
        mock_find_spec_dir: MagicMock,
        mock_coordinator_cls: MagicMock,
        tmp_path: Path,
    ) -> None:
        from harness.skills.run_skill import run

        missing = tmp_path / "missing"
        mock_parse.return_value = RunIntent(spec_id="012", mode="semi")

        with pytest.raises(
            RunContextError,
            match=f"orchestration root is not a directory: {missing.resolve()}",
        ):
            run(
                "spec 012 semi",
                provider=MagicMock(),
                gitops=MagicMock(),
                base_dir=tmp_path,
                orchestration_root=missing,
            )

        mock_find_spec_dir.assert_not_called()
        mock_coordinator_cls.assert_not_called()

    @patch("harness.skills.run_skill.StrategyCoordinator")
    @patch("harness.skills.run_skill.find_spec_dir", return_value=None)
    @patch("harness.skills.run_skill.parse_intent")
    def test_run_rejects_missing_spec_from_explicit_orchestration_root_before_coordinator(
        self,
        mock_parse: MagicMock,
        mock_find_spec_dir: MagicMock,
        mock_coordinator_cls: MagicMock,
        tmp_path: Path,
    ) -> None:
        from harness.skills.run_skill import run

        workspace = tmp_path / "workspace"
        workspace.mkdir()
        mock_parse.return_value = RunIntent(spec_id="012", mode="semi")

        with pytest.raises(
            RunContextError,
            match=(
                f"spec directory for 012 was not found from orchestration root "
                f"{workspace.resolve()}"
            ),
        ):
            run(
                "spec 012 semi",
                provider=MagicMock(),
                gitops=MagicMock(),
                base_dir=tmp_path,
                orchestration_root=workspace,
            )

        mock_find_spec_dir.assert_called_once_with("012", workspace.resolve())
        mock_coordinator_cls.assert_not_called()


@pytest.mark.unit
class TestRunSkillAutoLand:
    """Test that run() calls land() when auto_merge is True."""

    @patch("harness.skills.run_skill.parse_intent")
    @patch("harness.skills.run_skill.load_config")
    @patch("harness.skills.run_skill.run_gc")
    @patch("harness.skills.run_skill.StrategyCoordinator")
    def test_coordinator_exception_still_emits_one_delivery_summary(
        self,
        mock_coordinator_cls: MagicMock,
        _mock_gc: MagicMock,
        _mock_config: MagicMock,
        mock_parse: MagicMock,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        from harness.skills.run_skill import run

        spec_dir = tmp_path / "specs" / "001-demo"
        spec_dir.mkdir(parents=True)
        mock_parse.return_value = RunIntent(
            spec_id="001-demo",
            mode="semi",
            strategies=("default",),
        )
        mock_coordinator_cls.return_value.start.side_effect = RuntimeError(
            "coordinator exploded"
        )
        runs = tmp_path / "runs"
        state_dir = runs / "build-durable" / "state"
        state_dir.mkdir(parents=True)
        (runs / ".current-build-001-demo").write_text(
            "build-durable\n",
            encoding="utf-8",
        )
        (state_dir / "default.json").write_text(
            '{"status":"blocked","outer_iteration":"unknown"}',
            encoding="utf-8",
        )

        with patch(
            "harness.run_summary.summarize_run_for_cli",
            return_value="Recorded the failed delivery handoff.",
        ):
            with pytest.raises(RuntimeError, match="coordinator exploded"):
                run(
                    "spec 001-demo",
                    MagicMock(),
                    MagicMock(),
                    base_dir=tmp_path,
                    resume_build_id="build-durable",
                )

        output = capsys.readouterr().err
        assert output.count("DELIVERY SUMMARY") == 1
        assert output.count("worked on") == 1
        assert "Recorded the failed delivery handoff." in output

    @patch("harness.skills.run_skill.parse_intent")
    @patch("harness.skills.run_skill.run_gc")
    @patch("harness.skills.run_skill.StrategyCoordinator")
    @patch("harness.land.land", return_value=False)
    def test_landing_block_does_not_change_converged_delivery(
        self,
        mock_land: MagicMock,
        mock_coordinator_cls: MagicMock,
        _mock_gc: MagicMock,
        mock_parse: MagicMock,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A failed post-convergence land is reported independently."""
        from harness.skills.run_skill import run

        spec_dir = tmp_path / "specs" / "042-demo"
        spec_dir.mkdir(parents=True)
        (spec_dir / "spec.md").write_text("# Demo\n", encoding="utf-8")
        mock_parse.return_value = RunIntent(spec_id="042", mode="semi", auto_merge=True)
        coordinator = mock_coordinator_cls.return_value
        coordinator.start.return_value = [_make_converged_result()]
        coordinator.compare_results.return_value = {
            "strategies": {}, "summary": {"converged": 1, "failed": 0, "total_tokens": 0}
        }
        coordinator.status.return_value = {"strategies": {"default": {}}}

        outcome = run("spec 042 auto_merge", MagicMock(), MagicMock(), base_dir=tmp_path)

        assert outcome.results[0].status == "converged"
        assert outcome.landing.status == "blocked"
        mock_land.assert_called_once()
        output = capsys.readouterr().err
        assert output.count("DELIVERY SUMMARY") == 1
        assert output.count("worked on") == 1
        assert output.count("echelon delivery land 042") == 1

    @patch("harness.skills.run_skill.parse_intent")
    @patch("harness.skills.run_skill.load_config")
    @patch("harness.skills.run_skill.run_gc")
    @patch("harness.skills.run_skill.StrategyCoordinator")
    @patch("harness.land.land")
    def test_polyrepo_auto_land_uses_workspace_root_and_keeps_target_harness_root(
        self,
        mock_land: MagicMock,
        mock_coordinator_cls: MagicMock,
        mock_gc: MagicMock,
        mock_config: MagicMock,
        mock_parse: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Auto-land resolves specs from the workspace while state stays target-local."""
        from harness.run_intent import RunIntent
        from harness.skills.run_skill import run

        workspace = tmp_path / "workspace"
        harness_root = workspace / "runs" / "targets" / "api"
        harness_root.mkdir(parents=True)
        target_root = workspace / "sources" / "api"
        target_root.mkdir(parents=True)
        spec_dir = workspace / "specs" / "042-demo"
        spec_dir.mkdir(parents=True)
        (spec_dir / "spec.md").write_text(
            "---\ntargets:\n- sources/api\n---\n# Demo\n",
            encoding="utf-8",
        )

        intent = RunIntent(spec_id="042", mode="banzai", auto_merge=True)
        mock_parse.return_value = intent

        coordinator_instance = MagicMock()
        coordinator_instance.start.return_value = [_make_converged_result()]
        coordinator_instance.compare_results.return_value = {
            "strategies": {},
            "summary": {"converged": 1, "failed": 0, "total_tokens": 10000},
        }
        coordinator_instance.status.return_value = {"strategies": {"default": {}}}
        mock_coordinator_cls.return_value = coordinator_instance

        mock_land.return_value = True

        gitops = MagicMock()
        provider = MagicMock()

        run(
            "run 042 mode=banzai",
            provider=provider,
            gitops=gitops,
            base_dir=str(harness_root),
            orchestration_root=workspace,
        )

        mock_land.assert_called_once_with(
            "042",
            project_dir=workspace.resolve(),
            gitops=gitops,
            harness_root=harness_root.resolve(),
        )
        assert mock_coordinator_cls.call_args.kwargs["base_dir"] == harness_root.resolve()
        assert (
            mock_coordinator_cls.call_args.kwargs["orchestration_root"]
            == workspace.resolve()
        )

    @patch("harness.skills.run_skill.parse_intent")
    @patch("harness.skills.run_skill.load_config")
    @patch("harness.skills.run_skill.run_gc")
    @patch("harness.skills.run_skill.StrategyCoordinator")
    @patch("harness.land.land")
    def test_multi_target_auto_land_is_skipped(
        self,
        mock_land: MagicMock,
        mock_coordinator_cls: MagicMock,
        mock_gc: MagicMock,
        mock_config: MagicMock,
        mock_parse: MagicMock,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        from harness.skills.run_skill import run

        workspace = tmp_path / "workspace"
        harness_root = workspace / "sources" / "api"
        harness_root.mkdir(parents=True)
        spec_dir = workspace / "specs" / "042-demo"
        spec_dir.mkdir(parents=True)
        (spec_dir / "spec.md").write_text(
            "---\ntargets:\n- sources/api\n- sources/web\n---\n# Demo\n",
            encoding="utf-8",
        )
        mock_parse.return_value = RunIntent(spec_id="042", mode="banzai", auto_merge=True)

        coordinator_instance = MagicMock()
        coordinator_instance.start.return_value = [_make_converged_result()]
        coordinator_instance.compare_results.return_value = {
            "strategies": {},
            "summary": {"converged": 1, "failed": 0, "total_tokens": 10000},
        }
        coordinator_instance.status.return_value = {"strategies": {"default": {}}}
        mock_coordinator_cls.return_value = coordinator_instance

        run(
            "run 042 mode=banzai",
            provider=MagicMock(),
            gitops=MagicMock(),
            base_dir=str(harness_root),
            orchestration_root=workspace,
        )

        mock_land.assert_not_called()
        warning = (
            "auto-land skipped for spec 042: aggregate multi-target landing is "
            "unsupported (2 targets)"
        )
        assert [record.message for record in caplog.records].count(warning) == 1

    @patch("harness.skills.run_skill.parse_intent")
    @patch("harness.skills.run_skill.load_config")
    @patch("harness.skills.run_skill.run_gc")
    @patch("harness.skills.run_skill.StrategyCoordinator")
    @patch("harness.land.land")
    def test_land_not_called_when_auto_merge_false(
        self,
        mock_land: MagicMock,
        mock_coordinator_cls: MagicMock,
        mock_gc: MagicMock,
        mock_config: MagicMock,
        mock_parse: MagicMock,
    ) -> None:
        """land() is NOT called when auto_merge is False."""
        from harness.run_intent import RunIntent
        from harness.skills.run_skill import run

        intent = RunIntent(spec_id="012", mode="banzai", auto_merge=False)
        mock_parse.return_value = intent

        coordinator_instance = MagicMock()
        coordinator_instance.start.return_value = [_make_converged_result()]
        coordinator_instance.compare_results.return_value = {
            "strategies": {},
            "summary": {"converged": 1, "failed": 0, "total_tokens": 10000},
        }
        mock_coordinator_cls.return_value = coordinator_instance

        gitops = MagicMock()
        provider = MagicMock()

        run("spec 012 banzai", provider=provider, gitops=gitops, base_dir="/tmp/test")

        mock_land.assert_not_called()

    @patch("harness.skills.run_skill.parse_intent")
    @patch("harness.skills.run_skill.load_config")
    @patch("harness.skills.run_skill.run_gc")
    @patch("harness.skills.run_skill.StrategyCoordinator")
    def test_resume_uses_existing_build_id(
        self,
        mock_coordinator_cls: MagicMock,
        mock_gc: MagicMock,
        mock_config: MagicMock,
        mock_parse: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Resuming must continue the selected build directory instead of minting a new one."""
        from harness.paths import current_build_marker
        from harness.run_intent import RunIntent
        from harness.skills.run_skill import run

        intent = RunIntent(spec_id="012", mode="semi", auto_merge=False)
        mock_parse.return_value = intent
        coordinator_instance = MagicMock()
        coordinator_instance.start.return_value = [_make_failed_result()]
        coordinator_instance.compare_results.return_value = {
            "strategies": {},
            "summary": {"converged": 0, "failed": 1, "total_tokens": 0},
        }
        mock_coordinator_cls.return_value = coordinator_instance

        gitops = MagicMock()
        provider = MagicMock()

        run(
            "spec 012 resume",
            provider=provider,
            gitops=gitops,
            base_dir=str(tmp_path),
            resume_build_id="build-existing",
        )

        assert current_build_marker(tmp_path, "012").read_text(encoding="utf-8") == "build-existing"
        assert mock_coordinator_cls.call_args.kwargs["build_id"] == "build-existing"

    @patch("harness.skills.run_skill.parse_intent")
    @patch("harness.skills.run_skill.load_config")
    @patch("harness.skills.run_skill.run_gc")
    @patch("harness.skills.run_skill.StrategyCoordinator")
    def test_new_budget_uses_checkpoint_from_prior_blocked_run(
        self,
        mock_coordinator_cls: MagicMock,
        mock_gc: MagicMock,
        mock_config: MagicMock,
        mock_parse: MagicMock,
        tmp_path: Path,
    ) -> None:
        """A new delivery must not reset durable unfinished work to main."""
        from harness.paths import current_build_marker
        from harness.skills.run_skill import run

        intent = RunIntent(spec_id="012", mode="semi", auto_merge=False)
        mock_parse.return_value = intent
        candidate = "a" * 40
        prior_state = tmp_path / "runs" / "build-prior" / "state"
        prior_state.mkdir(parents=True)
        (prior_state / "default.json").write_text(json.dumps({
            "status": "blocked",
            "termination_reason": "task_progress_incomplete",
            "checkpoint_commits": [{"commit": candidate}],
        }), encoding="utf-8")
        marker = current_build_marker(tmp_path, "012")
        marker.parent.mkdir(parents=True, exist_ok=True)
        # A newer aborted build owns the marker but has no checkpoint.  Baseline
        # selection must still recover the durable prior candidate.
        newer_state = tmp_path / "runs" / "build-newer" / "state"
        newer_state.mkdir(parents=True)
        (newer_state / "default.json").write_text(json.dumps({
            "status": "running", "termination_reason": None,
        }), encoding="utf-8")
        marker.write_text("build-newer", encoding="utf-8")
        coordinator_instance = MagicMock()
        coordinator_instance.start.return_value = [_make_failed_result()]
        coordinator_instance.compare_results.return_value = {
            "strategies": {}, "summary": {"converged": 0, "failed": 1, "total_tokens": 0},
        }
        mock_coordinator_cls.return_value = coordinator_instance

        run(
            "spec 012",
            provider=MagicMock(),
            gitops=MagicMock(),
            base_dir=str(tmp_path),
            # The CLI reserves a new build directory before entering run().
            # That is still a fresh budget, not a blocked-state resume.
            resume_build_id="build-prepared",
        )

        assert mock_coordinator_cls.call_args.kwargs["fresh_branch_bases"] == {"default": candidate}

    @patch("harness.skills.run_skill.parse_intent")
    @patch("harness.skills.run_skill.load_config")
    @patch("harness.skills.run_skill.run_gc")
    @patch("harness.skills.run_skill.StrategyCoordinator")
    @patch("harness.land.land")
    def test_land_returns_false_logs_warning(
        self,
        mock_land: MagicMock,
        mock_coordinator_cls: MagicMock,
        mock_gc: MagicMock,
        mock_config: MagicMock,
        mock_parse: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """When land() returns False, a warning is logged."""
        from harness.run_intent import RunIntent
        from harness.skills.run_skill import run

        intent = RunIntent(spec_id="012", mode="banzai", auto_merge=True)
        mock_parse.return_value = intent

        coordinator_instance = MagicMock()
        coordinator_instance.start.return_value = [_make_converged_result()]
        coordinator_instance.compare_results.return_value = {
            "strategies": {},
            "summary": {"converged": 1, "failed": 0, "total_tokens": 10000},
        }
        mock_coordinator_cls.return_value = coordinator_instance

        mock_land.return_value = False

        gitops = MagicMock()
        provider = MagicMock()

        import logging
        with caplog.at_level(logging.WARNING, logger="harness.skills.run_skill"):
            run("spec 012 banzai auto_merge", provider=provider, gitops=gitops, base_dir="/tmp/test")

        assert any("land() returned False" in record.message for record in caplog.records)

    @patch("harness.skills.run_skill.parse_intent")
    @patch("harness.skills.run_skill.run_gc")
    @patch("harness.skills.run_skill.StrategyCoordinator")
    def test_delivery_run_does_not_prepare_or_switch_target_checkout(
        self,
        mock_coordinator_cls: MagicMock,
        mock_gc: MagicMock,
        mock_parse: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Delivery uses the mirror/worktree boundary, not the authoring checkout."""
        from harness.config import HarnessConfig
        from harness.paths import current_build_marker
        from harness.run_intent import RunIntent
        from harness.skills.run_skill import run

        target = tmp_path / "repo-a"
        target.mkdir()
        runtime = tmp_path / "wrapper" / "runs" / "targets" / "repo-a"
        runtime.mkdir(parents=True)
        config = HarnessConfig(
            target_repo=str(target),
            target_default_branch="main",
            provider="docker",
        )
        intent = RunIntent(spec_id="012", mode="semi", auto_merge=False)
        mock_parse.return_value = intent

        coordinator_instance = MagicMock()
        coordinator_instance.start.return_value = [_make_converged_result()]
        coordinator_instance.compare_results.return_value = {
            "strategies": {},
            "summary": {"converged": 1, "failed": 0, "total_tokens": 0},
        }
        mock_coordinator_cls.return_value = coordinator_instance

        gitops = MagicMock()
        provider = MagicMock()

        run(
            "spec 012 semi",
            provider=provider,
            gitops=gitops,
            base_dir=str(runtime),
            config=config,
        )

        gitops.ensure_on_default_branch.assert_not_called()
        assert current_build_marker(runtime, "012").exists()

    @patch("harness.skills.run_skill.parse_intent")
    @patch("harness.skills.run_skill.run_gc")
    @patch("harness.skills.run_skill.StrategyCoordinator")
    def test_delivery_preserves_active_authoring_branch_dirty_state_and_pointer(
        self,
        mock_coordinator_cls: MagicMock,
        mock_gc: MagicMock,
        mock_parse: MagicMock,
        tmp_path: Path,
    ) -> None:
        """A selected delivery run leaves another active Phase A run untouched."""
        import subprocess

        from harness.config import HarnessConfig
        from harness.run_intent import RunIntent
        from harness.skills.run_skill import run

        def git(*args: str) -> str:
            result = subprocess.run(
                ["git", *args],
                cwd=tmp_path,
                check=True,
                capture_output=True,
                text=True,
            )
            return result.stdout.strip()

        (tmp_path / ".gitignore").write_text("/runs/\n", encoding="utf-8")
        (tmp_path / "authoring.txt").write_text("base\n", encoding="utf-8")
        git("init", "-b", "main")
        git("config", "user.email", "tests@example.com")
        git("config", "user.name", "Echelon Tests")
        git("add", ".gitignore", "authoring.txt")
        git("commit", "-m", "base")
        git("switch", "-c", "002-spec-b")
        (tmp_path / "authoring.txt").write_text("unfinished B\n", encoding="utf-8")
        current = tmp_path / "runs" / ".current"
        current.parent.mkdir(parents=True)
        current.write_text("run-b", encoding="utf-8")
        before_status = git("status", "--porcelain")

        config = HarnessConfig(
            target_repo=str(tmp_path),
            target_default_branch="main",
            provider="docker",
        )
        mock_parse.return_value = RunIntent(spec_id="001-spec-a", mode="semi", auto_merge=False)
        coordinator_instance = MagicMock()
        coordinator_instance.start.return_value = [_make_converged_result()]
        coordinator_instance.compare_results.return_value = {
            "strategies": {},
            "summary": {"converged": 1, "failed": 0, "total_tokens": 0},
        }
        mock_coordinator_cls.return_value = coordinator_instance
        gitops = MagicMock()

        run(
            "spec 001-spec-a semi",
            provider=MagicMock(),
            gitops=gitops,
            base_dir=str(tmp_path),
            config=config,
        )

        assert git("branch", "--show-current") == "002-spec-b"
        assert git("status", "--porcelain") == before_status
        assert current.read_text(encoding="utf-8") == "run-b"
        gitops.ensure_on_default_branch.assert_not_called()

    @patch("harness.skills.run_skill.parse_intent")
    @patch("harness.skills.run_skill.load_config")
    @patch("harness.skills.run_skill.run_gc")
    @patch("harness.skills.run_skill.StrategyCoordinator")
    @patch("harness.land.land")
    def test_land_not_called_when_not_converged(
        self,
        mock_land: MagicMock,
        mock_coordinator_cls: MagicMock,
        mock_gc: MagicMock,
        mock_config: MagicMock,
        mock_parse: MagicMock,
    ) -> None:
        """land() is NOT called when auto_merge is True but no strategy converged."""
        from harness.run_intent import RunIntent
        from harness.skills.run_skill import run

        intent = RunIntent(spec_id="012", mode="banzai", auto_merge=True)
        mock_parse.return_value = intent

        coordinator_instance = MagicMock()
        coordinator_instance.start.return_value = [_make_failed_result()]
        coordinator_instance.compare_results.return_value = {
            "strategies": {},
            "summary": {"converged": 0, "failed": 1, "total_tokens": 50000},
        }
        mock_coordinator_cls.return_value = coordinator_instance

        gitops = MagicMock()
        provider = MagicMock()

        run("spec 012 banzai auto_merge", provider=provider, gitops=gitops, base_dir="/tmp/test")

        mock_land.assert_not_called()

    def test_delivery_summary_renders_build_incomplete_as_checkpointed(
        self,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Recoverable salvaged harness stops should not be summarized as failed."""
        from harness.run_intent import RunIntent
        from harness.skills.run_skill import _print_delivery_summary

        intent = RunIntent(spec_id="001-demo", mode="semi")
        result = _make_checkpoint_result()
        comparison = {
            "strategies": {
                "default": {
                    "status": result.status,
                    "termination_reason": result.termination_reason,
                    "outer_iterations": result.outer_iterations,
                    "inner_iterations": result.inner_iterations,
                    "tokens_used": result.tokens_used,
                    "pr_url": result.pr_url,
                    "branch": result.branch,
                    "converged": False,
                }
            },
            "summary": {"converged": 0, "failed": 1, "total_tokens": 0},
        }

        _print_delivery_summary(
            intent,
            {"default": result},
            comparison,
            workspace_root=Path("/tmp/nonexistent"),
            spec_dir=None,
        )

        captured = capsys.readouterr()
        assert "◐ CHECKPOINTED" in captured.err
        assert "stopped: checkpoint recovery needed" in captured.err
        assert "continue: echelon delivery continue 001-demo" in captured.err
        assert "0 converged, 0 failed, 1 checkpointed" in captured.err

    def test_delivery_summary_includes_human_readable_worked_on_section(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        from harness.run_intent import RunIntent
        from harness.skills.run_skill import _print_delivery_summary

        intent = RunIntent(spec_id="001-demo", mode="semi")
        result = _make_converged_result()
        comparison = {
            "strategies": {
                "default": {
                    "status": result.status,
                    "termination_reason": result.termination_reason,
                    "converged": True,
                    "outer_iterations": 1,
                    "inner_iterations": 0,
                    "branch": "001-demo",
                }
            },
            "summary": {"converged": 1, "failed": 0, "total_tokens": 10_000},
        }

        with patch(
            "harness.run_summary.summarize_run_for_cli",
            return_value="Implemented the requested delivery.",
        ) as summarize:
            _print_delivery_summary(
                intent,
                {"default": result},
                comparison,
                tmp_path,
                None,
                summary_command="echelon delivery continue",
            )

        assert summarize.call_args.args[0].command == "echelon delivery continue"
        from harness.run_summary import SummaryFact

        assert all(
            isinstance(fact, SummaryFact)
            for fact in summarize.call_args.args[0].facts
        )
        assert not hasattr(summarize.call_args.args[0], "inspect_paths")

        output = capsys.readouterr().err
        assert output.count("DELIVERY SUMMARY") == 1
        assert "worked on" in output
        assert "Implemented the requested delivery." in output

    def test_delivery_summary_preserves_late_authority_in_bounded_packet(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        from harness.ai_cli_backend import CliRunResult
        from harness.run_summary import SummaryAgent, summarize_run
        from harness.skills.run_skill import _print_delivery_summary

        intent = RunIntent(spec_id="001-demo", mode="semi")
        result_map: dict[str, DeliveryResult] = {}
        strategies: dict[str, dict[str, object]] = {}
        for index in range(30):
            sid = f"strategy-{index:02}"
            result = _make_converged_result()
            result_map[sid] = result
            strategies[sid] = {
                "status": result.status,
                "termination_reason": result.termination_reason,
                "converged": True,
                "outer_iterations": 1,
                "inner_iterations": 0,
                "branch": f"harness/001-demo/{sid}/{'segment-' * 55}",
            }
        limited_sid = "strategy-provider-limited"
        limited = replace(
            _make_checkpoint_result(),
            termination_reason="provider_session_limit",
        )
        provider_message = "You've hit your session limit · resets 9:10pm"
        result_map[limited_sid] = limited
        strategies[limited_sid] = {
            "status": limited.status,
            "termination_reason": limited.termination_reason,
            "converged": False,
            "outer_iterations": limited.outer_iterations,
            "inner_iterations": limited.inner_iterations,
            "branch": f"harness/001-demo/{limited_sid}/{'segment-' * 55}",
            "build_status": "provider_session_limit",
            "provider_limit_message": provider_message,
            "provider_reset_hint": "9:10pm",
        }
        comparison = {
            "strategies": strategies,
            "summary": {"converged": 30, "failed": 1, "total_tokens": 300_000},
        }
        captured: dict[str, object] = {}

        class RecordingProvider:
            prompt = ""

            def run_agent_result(self, _cwd, prompt, **_kwargs):
                self.prompt = prompt
                return CliRunResult(
                    exit_code=0,
                    stdout=json.dumps(
                        {"selected_fact_ids": ["f0001", "f0002"]}
                    ),
                    stderr="",
                )

        provider = RecordingProvider()

        def render(context):
            captured["context"] = context
            return summarize_run(
                context,
                provider=provider,
                agent=SummaryAgent(prompt="Summarize.", metadata={}),
            )

        with patch(
            "harness.run_summary.summarize_run_for_cli",
            side_effect=render,
        ):
            _print_delivery_summary(
                intent,
                result_map,
                comparison,
                tmp_path,
                None,
            )

        capsys.readouterr()
        context = captured["context"]
        from harness.run_summary import SummaryFact

        assert context.facts
        assert all(isinstance(fact, SummaryFact) for fact in context.facts)
        packet = provider.prompt.split("<evidence_packet>", 1)[1].split(
            "</evidence_packet>", 1
        )[0]
        assert len(packet.encode("utf-8")) <= 12 * 1024
        decoded = json.loads(packet)
        assert decoded["schema_version"] == 2
        facts = decoded["facts"]
        assert all(
            set(fact) == {"id", "category", "importance", "text"}
            for fact in facts
        )
        assert any(fact["category"] == "verification" for fact in facts)
        assert context.provider_limit_message == provider_message
        assert all(provider_message not in fact["text"] for fact in facts)

    def test_delivery_summary_marks_mixed_strategy_outcome_blocked(
        self,
        tmp_path: Path,
    ) -> None:
        from harness.run_intent import RunIntent
        from harness.skills.run_skill import _print_delivery_summary

        converged = _make_converged_result()
        checkpointed = _make_checkpoint_result()
        comparison = {
            "strategies": {
                "default": {
                    "status": converged.status,
                    "termination_reason": converged.termination_reason,
                    "converged": True,
                    "outer_iterations": 1,
                    "inner_iterations": 0,
                },
                "backup": {
                    "status": checkpointed.status,
                    "termination_reason": checkpointed.termination_reason,
                    "converged": False,
                    "outer_iterations": checkpointed.outer_iterations,
                    "inner_iterations": checkpointed.inner_iterations,
                },
            },
            "summary": {"converged": 1, "failed": 1, "total_tokens": 10_000},
        }
        captured: dict[str, object] = {}

        def summarize(context):
            captured["context"] = context
            return "One strategy completed while another needs continuation."

        with patch(
            "harness.run_summary.summarize_run_for_cli",
            side_effect=summarize,
        ):
            _print_delivery_summary(
                RunIntent(spec_id="001-demo", mode="semi"),
                {"default": converged, "backup": checkpointed},
                comparison,
                tmp_path,
                None,
            )

        assert captured["context"].status == "blocked"

    def test_delivery_summary_renders_provider_session_limit_as_block(
        self,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        from harness.run_intent import RunIntent
        from harness.skills.run_skill import _print_delivery_summary

        intent = RunIntent(spec_id="001-demo", mode="semi")
        result = _make_checkpoint_result()
        result = replace(result, termination_reason="provider_session_limit")
        comparison = {
            "strategies": {
                "default": {
                    "status": result.status,
                    "termination_reason": result.termination_reason,
                    "outer_iterations": result.outer_iterations,
                    "inner_iterations": result.inner_iterations,
                    "tokens_used": result.tokens_used,
                    "pr_url": result.pr_url,
                    "branch": result.branch,
                    "converged": False,
                    "build_status": "provider_session_limit",
                    "provider_limit_message": "You've hit your session limit · resets 9:10pm",
                    "provider_reset_hint": "9:10pm",
                    "salvage_commit": "abcdef1234567890abcdef1234567890abcdef12",
                    "salvage_branch": "harness/001-demo/default/iter-0",
                    "salvage_verified": "not_run",
                }
            },
            "summary": {"converged": 0, "failed": 1, "total_tokens": 0},
        }

        _print_delivery_summary(
            intent,
            {"default": result},
            comparison,
            workspace_root=Path("/tmp/nonexistent"),
            spec_dir=None,
        )

        captured = capsys.readouterr()
        assert "◐ PROVIDER SESSION LIMIT" in captured.err
        assert "stopped: provider session limit" in captured.err
        assert "You've hit your session limit" in captured.err
        assert "reset: 9:10pm" in captured.err
        assert "salvage commit: abcdef123456" in captured.err
        assert "salvage branch: harness/001-demo/default/iter-0" in captured.err
        assert "salvage verified: not_run" in captured.err
        assert "continue: echelon delivery continue 001-demo" in captured.err
        assert "0 converged, 0 failed, 1 provider-limited" in captured.err
        assert "CHECKPOINTED" not in captured.err

    def test_delivery_summary_ignores_stale_provider_status_for_escalation(
        self,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        from harness.run_intent import RunIntent
        from harness.skills.run_skill import _print_delivery_summary

        intent = RunIntent(spec_id="906", mode="semi")
        result = DeliveryResult(
            status="blocked",
            termination_reason="blocker_escalation",
            outer_iterations=1,
            inner_iterations=3,
            pr_url=None,
            tokens_used=100,
            final_verify=VerifyResult(
                passed=False,
                failures=[
                    FailureEntry(
                        category=FailureCategory.OTHER,
                        id="fulfillment-gaps",
                        error="fulfillment report has unresolved statuses",
                    )
                ],
            ),
            blocked_phase="implementation",
        )
        comparison = {
            "strategies": {
                "default": {
                    "status": result.status,
                    "termination_reason": result.termination_reason,
                    "outer_iterations": result.outer_iterations,
                    "inner_iterations": result.inner_iterations,
                    "tokens_used": result.tokens_used,
                    "pr_url": result.pr_url,
                    "converged": False,
                    "build_status": "provider_session_limit",
                    "provider_limit_message": "stale provider limit text",
                }
            },
            "summary": {"converged": 0, "failed": 1, "total_tokens": 100},
        }

        _print_delivery_summary(
            intent,
            {"default": result},
            comparison,
            workspace_root=Path("/tmp/nonexistent"),
            spec_dir=None,
        )

        captured = capsys.readouterr()
        assert "PROVIDER SESSION LIMIT" not in captured.err
        assert "provider: stale provider limit text" not in captured.err
        assert "provider-limited" not in captured.err
        assert "fulfillment report has unresolved statuses" in captured.err

    def test_delivery_summary_renders_deferred_outer_cap_as_checkpointed(
        self,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Outer cap with deferred fulfillment is continuation, not failure."""
        from harness.run_intent import RunIntent
        from harness.skills.run_skill import _print_delivery_summary

        intent = RunIntent(spec_id="001-demo", mode="banzai")
        result = _make_checkpoint_outer_cap_result()
        comparison = {
            "strategies": {
                "default": {
                    "status": result.status,
                    "termination_reason": result.termination_reason,
                    "outer_iterations": result.outer_iterations,
                    "inner_iterations": result.inner_iterations,
                    "tokens_used": result.tokens_used,
                    "pr_url": result.pr_url,
                    "branch": result.branch,
                    "converged": False,
                }
            },
            "summary": {"converged": 0, "failed": 1, "total_tokens": 0},
        }

        _print_delivery_summary(
            intent,
            {"default": result},
            comparison,
            workspace_root=Path("/tmp/nonexistent"),
            spec_dir=None,
        )

        captured = capsys.readouterr()
        assert "◐ CHECKPOINTED" in captured.err
        assert "stopped: checkpoint continuation needed" in captured.err
        assert "continue: echelon delivery continue 001-demo" in captured.err
        assert "verify: deferred" in captured.err
        assert "verify: ✗ FAILED" not in captured.err
        assert "deferred [other] full verify-spec refresh deferred" in captured.err
        assert "✗ [other] full verify-spec refresh deferred" not in captured.err
        assert "0 converged, 0 failed, 1 checkpointed" in captured.err

    def test_delivery_summary_renders_verified_ledger_counts(
        self,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        from harness.run_intent import RunIntent
        from harness.skills.run_skill import _print_delivery_summary

        intent = RunIntent(spec_id="001-demo", mode="semi")
        result = _make_checkpoint_result()
        comparison = {
            "strategies": {
                "default": {
                    "status": result.status,
                    "termination_reason": result.termination_reason,
                    "outer_iterations": result.outer_iterations,
                    "inner_iterations": result.inner_iterations,
                    "tokens_used": result.tokens_used,
                    "pr_url": result.pr_url,
                    "branch": result.branch,
                    "converged": False,
                    "fulfillment_refresh": {
                        "verified_ledger": {
                            "reused": 70,
                            "rechecked": 5,
                            "invalidated": 1,
                            "unresolved": 2,
                        }
                    },
                }
            },
            "summary": {"converged": 0, "failed": 1, "total_tokens": 0},
        }

        _print_delivery_summary(
            intent,
            {"default": result},
            comparison,
            workspace_root=Path("/tmp/nonexistent"),
            spec_dir=None,
        )

        captured = capsys.readouterr()
        assert "verified ledger: reused 70, rechecked 5, invalidated 1, unresolved 2" in captured.err

    def test_delivery_summary_renders_next_step_for_failed_outer_cap(
        self,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        from harness.run_intent import RunIntent
        from harness.skills.run_skill import _print_delivery_summary

        intent = RunIntent(spec_id="001-demo", mode="banzai")
        result = _make_failed_result()
        result = replace(result, final_verify=VerifyResult(
            passed=False,
            failures=[
                FailureEntry(
                    category=FailureCategory.OTHER,
                    id="fulfillment-report-stale",
                    error="fulfillment report is stale for current HEAD abc123",
                )
            ],
        ))
        comparison = {
            "strategies": {
                "default": {
                    "status": result.status,
                    "termination_reason": result.termination_reason,
                    "outer_iterations": result.outer_iterations,
                    "inner_iterations": result.inner_iterations,
                    "tokens_used": result.tokens_used,
                    "pr_url": result.pr_url,
                    "branch": result.branch,
                    "converged": False,
                }
            },
            "summary": {"converged": 0, "failed": 1, "total_tokens": 0},
        }

        _print_delivery_summary(
            intent,
            {"default": result},
            comparison,
            workspace_root=Path("/tmp/nonexistent"),
            spec_dir=None,
        )

        captured = capsys.readouterr()
        assert "stopped: outer_cap" in captured.err
        assert "next: echelon delivery run 001-demo" in captured.err
        assert "continue with a fresh outer-loop budget" in captured.err

    def test_delivery_summary_promotes_fulfillment_gap_remediation(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        from harness.run_intent import RunIntent
        from harness.skills.run_skill import _print_delivery_summary

        spec_dir = tmp_path / "specs" / "001-demo"
        spec_dir.mkdir(parents=True)
        (spec_dir / "fulfillment-gaps.md").write_text(
            "# Fulfillment Gaps\n\n"
            "## Gap 1 - NFR-008\n\n"
            "- **Remediation (WHAT decision):** Choose a palette with measured "
            "simulated contrast of at least 3:1 for every state pair.\n",
            encoding="utf-8",
        )
        intent = RunIntent(spec_id="001-demo", mode="semi")
        result = DeliveryResult(
            status="blocked",
            termination_reason="blocker_escalation",
            outer_iterations=1,
            inner_iterations=3,
            pr_url=None,
            tokens_used=100,
            final_verify=VerifyResult(
                passed=False,
                failures=[
                    FailureEntry(
                        category=FailureCategory.OTHER,
                        id="fulfillment-gaps",
                        error="fulfillment report has unresolved statuses",
                    )
                ],
            ),
            blocked_phase="implementation",
        )
        comparison = {
            "strategies": {
                "default": {
                    "status": result.status,
                    "termination_reason": result.termination_reason,
                    "outer_iterations": result.outer_iterations,
                    "inner_iterations": result.inner_iterations,
                    "tokens_used": result.tokens_used,
                    "pr_url": result.pr_url,
                    "converged": False,
                }
            },
            "summary": {"converged": 0, "failed": 1, "total_tokens": 100},
        }

        _print_delivery_summary(intent, {"default": result}, comparison, tmp_path, spec_dir)

        captured = capsys.readouterr()
        assert "recommended action:" in captured.err
        assert "Choose a palette with measured simulated contrast" in captured.err

    def test_delivery_summary_prints_suggested_answers_from_escalation_file(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        from harness.run_intent import RunIntent
        from harness.skills.run_skill import _print_delivery_summary

        escalation_file = tmp_path / "runs" / "build-test" / "escalations" / "906-default.md"
        escalation_file.parent.mkdir(parents=True)
        escalation_file.write_text(
            "# Escalation\n\n"
            "## Decision Metadata\n\n"
            "```json\n"
            "{\n"
            '  "schema_version": 1,\n'
            '  "suggested_answers": [\n'
            "    {\n"
            '      "label": "Continue implementing gaps",\n'
            '      "answer": "Continue delivery using fulfillment-gaps.md as mandatory implementation context.",\n'
            '      "consequence": "Runs another harness-owned implementation attempt.",\n'
            '      "recommended": true\n'
            "    },\n"
            "    {\n"
            '      "label": "Stop and reopen/waive through harness",\n'
            '      "answer": "Stop delivery and use echelon spec reopen 906 for the unresolved requirement decision.",\n'
            '      "consequence": "Keeps the fulfillment gate owned by the harness."\n'
            "    }\n"
            "  ]\n"
            "}\n"
            "```\n",
            encoding="utf-8",
        )
        intent = RunIntent(spec_id="906", mode="semi")
        result = DeliveryResult(
            status="blocked",
            termination_reason="outer_cap",
            outer_iterations=1,
            inner_iterations=3,
            pr_url=None,
            tokens_used=100,
            final_verify=VerifyResult(
                passed=False,
                failures=[
                    FailureEntry(
                        category=FailureCategory.OTHER,
                        id="fulfillment-gaps",
                        error="fulfillment report has unresolved statuses",
                    )
                ],
            ),
            blocked_phase="implementation",
        )
        comparison = {
            "strategies": {
                "default": {
                    "status": result.status,
                    "termination_reason": result.termination_reason,
                    "outer_iterations": result.outer_iterations,
                    "inner_iterations": result.inner_iterations,
                    "tokens_used": result.tokens_used,
                    "pr_url": result.pr_url,
                    "converged": False,
                    "escalation_file": str(escalation_file),
                }
            },
            "summary": {"converged": 0, "failed": 1, "total_tokens": 100},
        }

        _print_delivery_summary(intent, {"default": result}, comparison, tmp_path, None)

        captured = capsys.readouterr()
        assert "suggested answers:" in captured.err
        assert "Continue implementing gaps (recommended)" in captured.err
        assert 'echelon delivery resume 906 "Continue delivery using fulfillment-gaps.md' in captured.err
        assert "Stop and reopen/waive through harness" in captured.err
        assert "bypass" not in captured.err.lower()
        assert "cherry-pick" not in captured.err.lower()

    def test_delivery_summary_omits_stale_suggested_answers_for_non_escalation_stop(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        from harness.run_intent import RunIntent
        from harness.skills.run_skill import _print_delivery_summary

        escalation_file = tmp_path / "runs" / "build-test" / "escalations" / "906-default.md"
        escalation_file.parent.mkdir(parents=True)
        escalation_file.write_text(
            "# Escalation\n\n"
            "## Decision Metadata\n\n"
            "```json\n"
            "{\n"
            '  "suggested_answers": [\n'
            "    {\n"
            '      "label": "Continue implementing gaps",\n'
            '      "answer": "Continue delivery using fulfillment-gaps.md.",\n'
            '      "recommended": true\n'
            "    }\n"
            "  ]\n"
            "}\n"
            "```\n",
            encoding="utf-8",
        )
        intent = RunIntent(spec_id="906", mode="semi")
        result = DeliveryResult(
            status="blocked",
            termination_reason="external_spec_artifact_missing",
            outer_iterations=1,
            inner_iterations=0,
            pr_url=None,
            tokens_used=100,
            final_verify=VerifyResult(
                passed=False,
                failures=[
                    FailureEntry(
                        category=FailureCategory.OTHER,
                        id="documentation-impact-report-missing",
                        error="missing documentation-impact-report.md",
                    )
                ],
            ),
            blocked_phase="implementation",
        )
        comparison = {
            "strategies": {
                "default": {
                    "status": result.status,
                    "termination_reason": result.termination_reason,
                    "outer_iterations": result.outer_iterations,
                    "inner_iterations": result.inner_iterations,
                    "tokens_used": result.tokens_used,
                    "pr_url": result.pr_url,
                    "converged": False,
                    "escalation_file": str(escalation_file),
                }
            },
            "summary": {"converged": 0, "failed": 1, "total_tokens": 100},
        }

        _print_delivery_summary(intent, {"default": result}, comparison, tmp_path, None)

        captured = capsys.readouterr()
        assert "stopped: external_spec_artifact_missing" in captured.err
        assert "suggested answers:" not in captured.err
        assert "Continue implementing gaps" not in captured.err

    @patch("harness.skills.run_skill.parse_intent")
    @patch("harness.skills.run_skill.load_config")
    @patch("harness.skills.run_skill.run_gc")
    @patch("harness.skills.run_skill.StrategyCoordinator")
    @patch("harness.skills.run_skill._print_delivery_summary")
    def test_run_prints_harness_history_before_and_after_and_appends_entry(
        self,
        mock_delivery: MagicMock,
        mock_coordinator_cls: MagicMock,
        mock_gc: MagicMock,
        mock_config: MagicMock,
        mock_parse: MagicMock,
        tmp_path: Path,
    ) -> None:
        from harness.run_intent import RunIntent
        from harness.skills.run_skill import run

        spec_dir = tmp_path / "specs" / "001-demo"
        spec_dir.mkdir(parents=True)
        history_path(spec_dir).write_text(
            '{"runs":[{"build_id":"build-old","strategy_id":"default","status":"failed","termination_reason":"outer_cap","tokens_used":1200}]}',
            encoding="utf-8",
        )

        intent = RunIntent(spec_id="001-demo", mode="banzai", auto_merge=False)
        mock_parse.return_value = intent

        coordinator_instance = MagicMock()
        result = _make_failed_result()
        coordinator_instance.start.return_value = [result]
        coordinator_instance.compare_results.return_value = {
            "strategies": {
                "default": {
                    "status": result.status,
                    "termination_reason": result.termination_reason,
                    "outer_iterations": result.outer_iterations,
                    "inner_iterations": result.inner_iterations,
                    "tokens_used": result.tokens_used,
                    "pr_url": result.pr_url,
                    "branch": result.branch,
                    "converged": False,
                }
            },
            "summary": {"converged": 0, "failed": 1, "total_tokens": result.tokens_used},
        }
        coordinator_instance.status.return_value = {"strategies": {"default": {}}}
        mock_coordinator_cls.return_value = coordinator_instance

        gitops = MagicMock()
        provider = MagicMock()

        with patch("harness.skills.run_skill._print_harness_history_summary") as mock_history:
            run("spec 001-demo mode=banzai", provider=provider, gitops=gitops, base_dir=str(tmp_path))

        assert mock_history.call_count == 2
        history = history_path(spec_dir).read_text(encoding="utf-8")
        assert '"build_id": "build-old"' in history
        assert '"termination_reason": "outer_cap"' in history
        assert '"tokens_used": 50000' in history

    @patch("harness.skills.run_skill.parse_intent")
    @patch("harness.skills.run_skill.load_config")
    @patch("harness.skills.run_skill.run_gc")
    @patch("harness.skills.run_skill.StrategyCoordinator")
    @patch("harness.land.land")
    def test_land_exception_caught_and_logged(
        self,
        mock_land: MagicMock,
        mock_coordinator_cls: MagicMock,
        mock_gc: MagicMock,
        mock_config: MagicMock,
        mock_parse: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """When land() raises, the exception is caught and a warning is logged."""
        from harness.run_intent import RunIntent
        from harness.skills.run_skill import run

        intent = RunIntent(spec_id="012", mode="banzai", auto_merge=True)
        mock_parse.return_value = intent

        coordinator_instance = MagicMock()
        coordinator_instance.start.return_value = [_make_converged_result()]
        coordinator_instance.compare_results.return_value = {
            "strategies": {},
            "summary": {"converged": 1, "failed": 0, "total_tokens": 10000},
        }
        mock_coordinator_cls.return_value = coordinator_instance

        mock_land.side_effect = RuntimeError("git merge failed")

        gitops = MagicMock()
        provider = MagicMock()

        import logging
        with caplog.at_level(logging.WARNING, logger="harness.skills.run_skill"):
            # Must not raise
            run("spec 012 banzai auto_merge", provider=provider, gitops=gitops, base_dir="/tmp/test")

        assert any("land() raised" in record.message for record in caplog.records)
        assert any("git merge failed" in record.message for record in caplog.records)
