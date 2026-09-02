"""Tests for _cmd_harness_resume in cli.py."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


_TEST_BUILD_ID = "build-test"


def _write_state(state_dir: Path, spec_id: str, strategy: str, state: dict) -> None:
    """Write a fake harness state file (new layout: state_dir/{strategy}.json, no spec_id subdir)."""
    path = state_dir / f"{strategy}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state))


def _setup_build(base: Path, spec_id: str) -> Path:
    """Write current-build marker and return the build's state_dir."""
    from harness.paths import build_dir, current_build_marker
    spec_dir = base / "specs" / f"{spec_id}-demo"
    spec_dir.mkdir(parents=True, exist_ok=True)
    (spec_dir / "spec.md").write_text(
        "---\ntargets:\n  - .\n---\n# Spec\n",
        encoding="utf-8",
    )
    marker = current_build_marker(base, spec_id)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(_TEST_BUILD_ID)
    sd = build_dir(base, _TEST_BUILD_ID) / "state"
    sd.mkdir(parents=True, exist_ok=True)
    return sd


def _make_echelon_yml(
    base: Path,
    verify_command: str = "",
    *,
    verify_detection: str = "",
    verify_reason: str = "",
) -> Path:
    """Write a minimal canonical Echelon config."""
    config_file = base / ".echelon" / "config.yml"
    config_file.parent.mkdir(parents=True, exist_ok=True)
    content = "autonomy:\n  mode: banzai\nprovider: docker\n"
    if verify_command:
        content += f"verify_command: {verify_command}\n"
    if verify_detection or verify_reason:
        content += "harness:\n"
        content += "  provider: docker\n"
        if verify_detection:
            content += f"  verify_command_detection: {verify_detection}\n"
        if verify_reason:
            content += f"  verify_command_reason: {verify_reason}\n"
    config_file.write_text(content)
    return config_file


def _make_phase_a_spec(base: Path, spec_dir_name: str = "001-demo", *, canonical_tasks: bool = True) -> Path:
    """Create minimal published Phase A build inputs for harness preflight."""
    spec_dir = base / "specs" / spec_dir_name
    spec_dir.mkdir(parents=True, exist_ok=True)
    for name in (
        "00-overview.md",
        "requirements-overview.md",
        "spec.md",
        "plan.md",
        "plan-conformance.md",
        "plan-conformance.json",
        "research.md",
        "data-model.md",
    ):
        if name == "spec.md":
            content = "---\ntargets:\n  - .\n---\n# Spec\n"
        elif name == "plan-conformance.json":
            content = json.dumps(
                {
                    "status": "pass",
                    "findings": [],
                    "sources": [
                        "spec.md",
                        "requirements-overview.md",
                        "plan.md",
                        "tasks.md",
                    ],
                },
                indent=2,
            )
        else:
            content = f"# {name}\n"
        (spec_dir / name).write_text(content, encoding="utf-8")
    for name in ("test-strategy.md", "test-architecture.md", "coverage-map.md"):
        (spec_dir / name).write_text(f"# {name}\n", encoding="utf-8")
    tasks = (
        "- [ ] T-001 complexity=standard phase=build req=FR-001 depends=none\n"
        if canonical_tasks
        else "- [ ] implement the thing\n"
    )
    (spec_dir / "tasks.md").write_text(tasks, encoding="utf-8")
    (spec_dir / "constitution.md").write_text(
        "# Constitution\n\nPrinciples are defined for this project.\n",
        encoding="utf-8",
    )
    return spec_dir


@pytest.mark.unit
def test_refreshing_v1_spec_paths_keeps_delivery_state_v1(tmp_path: Path) -> None:
    """CLI metadata repair may not choose a V2 delivery phase plan."""
    from echelon.cli import _refresh_harness_state_spec_paths
    from harness.state import StateStore

    spec_dir = tmp_path / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text("# Spec\n", encoding="utf-8")
    state_store = StateStore(tmp_path / "runs" / "state", "001", "default")
    state_store.state_file.parent.mkdir(parents=True, exist_ok=True)
    state_store.state_file.write_text(
        json.dumps({"status": "blocked", "legacy": True}), encoding="utf-8"
    )

    refreshed, _, changed = _refresh_harness_state_spec_paths(
        project_root=tmp_path,
        spec_id="001",
        state=state_store.read(),
        state_store=state_store,
    )

    assert changed is True
    assert refreshed["status"] == "blocked"
    assert "delivery_state_version" not in refreshed
    assert "enabled_phases" not in refreshed
    assert state_store.read()["legacy"] is True


@pytest.mark.unit
class TestCmdHarnessResume:
    """_cmd_harness_resume guards and banner."""

    def _call(self, args: list[str], cwd: Path) -> int:
        """Call _cmd_harness_resume and return exit code (0 = ok, else sys.exit arg)."""
        from echelon.cli import _cmd_harness_resume
        with patch("pathlib.Path.cwd", return_value=cwd):
            try:
                _cmd_harness_resume(args)
                return 0
            except SystemExit as e:
                return int(e.code)

    def test_missing_echelon_yml_exits_1(self, tmp_path: Path) -> None:
        rc = self._call(["001"], tmp_path)
        assert rc == 1

    def test_spec_not_blocked_exits_1(self, tmp_path: Path) -> None:
        _make_echelon_yml(tmp_path, verify_command="pytest")
        sd = _setup_build(tmp_path, "001")
        _write_state(sd, "001", "default", {"status": "converged", "termination_reason": "converged"})
        rc = self._call(["001"], tmp_path)
        assert rc == 1

    def test_unsupported_blocked_reason_exits_without_run_to_resume_guidance(
        self,
        tmp_path: Path,
        capsys,
    ) -> None:
        _make_echelon_yml(tmp_path, verify_command="pytest")
        sd = _setup_build(tmp_path, "001")
        _write_state(sd, "001", "default", {
            "status": "blocked", "termination_reason": "budget_exhausted",
        })
        rc = self._call(["001"], tmp_path)
        assert rc == 1
        err = capsys.readouterr().err
        assert "unsupported resume reason" in err
        assert "echelon delivery resume 001" in err
        assert "echelon delivery run 001 --reset" in err
        assert "echelon spec status" not in err
        assert "delivery state" in err
        assert "Use 'echelon delivery run <spec_id>' to resume" not in err

    def test_outer_cap_rejection_points_to_checkpoint_preserving_new_budget(
        self,
        tmp_path: Path,
        capsys,
    ) -> None:
        """Rejected outer-cap resume names the one non-destructive recovery command."""
        _make_echelon_yml(tmp_path, verify_command="pytest")
        sd = _setup_build(tmp_path, "001")
        _write_state(sd, "001", "default", {
            "status": "blocked",
            "termination_reason": "outer_cap",
            "escalation_file": "runs/build-test/escalation.md",
            "checkpoint_commits": [{"commit": "a" * 40}],
        })

        rc = self._call(["001", "Continue with blocker context"], tmp_path)

        assert rc == 1
        err = capsys.readouterr().err
        assert "echelon delivery run 001" in err
        assert "latest durable checkpoint" in err
        assert "echelon delivery run 001 --reset" in err
        assert "discard" in err.lower()
        assert "retry: echelon delivery resume 001" not in err

    def test_docs_report_only_containment_violation_resumes(
        self,
        tmp_path: Path,
    ) -> None:
        _make_echelon_yml(tmp_path, verify_command="pytest")
        sd = _setup_build(tmp_path, "001")
        _write_state(sd, "001", "default", {
            "status": "blocked",
            "termination_reason": "containment_violation",
            "containment_violation": {
                "changed_status": [
                    " M specs/001-demo/documentation-impact-report.md",
                    "?? specs/001-demo/docs-verification-report.md",
                ],
            },
        })

        with patch("pathlib.Path.cwd", return_value=tmp_path), \
             patch("harness.skills.run_skill.run") as mock_run, \
             patch("harness.docker_provider.DockerWorktreeProvider.__init__", return_value=None), \
             patch("harness.gitops.GitOpsManager.__init__", return_value=None):
            from echelon.cli import _cmd_harness_continue
            _cmd_harness_continue(["001"])

        mock_run.assert_called_once()
        assert mock_run.call_args.kwargs["resume_build_id"] == _TEST_BUILD_ID

    def test_non_docs_containment_violation_stays_unsupported(
        self,
        tmp_path: Path,
        capsys,
    ) -> None:
        _make_echelon_yml(tmp_path, verify_command="pytest")
        sd = _setup_build(tmp_path, "001")
        _write_state(sd, "001", "default", {
            "status": "blocked",
            "termination_reason": "containment_violation",
            "containment_violation": {
                "changed_status": [
                    "?? specs/001-demo/documentation-impact-report.md",
                    " M src/index.ts",
                ],
            },
        })

        rc = self._call(["001"], tmp_path)

        assert rc == 1
        err = capsys.readouterr().err
        assert "unsupported resume reason" in err
        assert "containment_violation" in err

    def test_build_blocked_requires_resolving_the_reported_blocker(
        self,
        tmp_path: Path,
        capsys,
    ) -> None:
        _make_echelon_yml(tmp_path, verify_command="pytest")
        sd = _setup_build(tmp_path, "001")
        _write_state(sd, "001", "default", {
            "status": "blocked",
            "termination_reason": "build_blocked",
            "build_status": "blocked",
            "build_reason": "NFR-008 requires an owner spec decision",
        })

        rc = self._call(["001"], tmp_path)

        assert rc == 1
        err = capsys.readouterr().err
        assert "requires an owner spec decision" in err
        assert "do not retry delivery until it is resolved" in err
        assert "echelon spec reopen 001" in err
        assert "echelon delivery continue 001" not in err

    def test_verify_command_still_missing_exits_1(self, tmp_path: Path, capsys) -> None:
        _make_echelon_yml(tmp_path)   # no verify_command
        sd = _setup_build(tmp_path, "001")
        _write_state(sd, "001", "default", {
            "status": "blocked", "termination_reason": "verify_command_needed",
        })
        rc = self._call(["001"], tmp_path)
        assert rc == 1
        err = capsys.readouterr().err
        assert "verify_command" in err
        assert "echelon delivery init" in err
        assert "echelon cicd" not in err

    def test_resume_accepts_canonical_workspace_config(self, tmp_path: Path, capsys) -> None:
        _make_echelon_yml(tmp_path)   # no verify_command
        sd = _setup_build(tmp_path, "001")
        _write_state(sd, "001", "default", {
            "status": "blocked", "termination_reason": "verify_command_needed",
        })

        rc = self._call(["001"], tmp_path)

        assert rc == 1
        err = capsys.readouterr().err
        assert "verify_command" in err
        assert "Harness not initialised" not in err

    def test_verify_command_missing_after_failed_detection_prioritizes_manual_config(
        self,
        tmp_path: Path,
        capsys,
    ) -> None:
        _make_echelon_yml(
            tmp_path,
            verify_detection="none",
            verify_reason="no high-confidence test runner detected",
        )
        sd = _setup_build(tmp_path, "001")
        _write_state(sd, "001", "default", {
            "status": "blocked", "termination_reason": "verify_command_needed",
        })

        rc = self._call(["001"], tmp_path)

        assert rc == 1
        err = capsys.readouterr().err
        assert "Auto-detection already ran" in err
        assert "no high-confidence test runner detected" in err
        assert "Add a top-level verify_command" in err
        assert "echelon delivery init" not in err
        assert "echelon delivery continue 001" in err

    def test_valid_resume_prints_banner_and_calls_run(self, tmp_path: Path) -> None:
        _make_echelon_yml(tmp_path, verify_command="pytest")
        sd = _setup_build(tmp_path, "001")
        _write_state(sd, "001", "default", {
            "status": "blocked", "termination_reason": "verify_command_needed",
        })

        with patch("pathlib.Path.cwd", return_value=tmp_path), \
             patch("harness.skills.run_skill.run") as mock_run, \
             patch("harness.docker_provider.DockerWorktreeProvider.__init__", return_value=None), \
             patch("harness.gitops.GitOpsManager.__init__", return_value=None):
            from echelon.cli import _cmd_harness_resume
            _cmd_harness_resume(["001"])

        mock_run.assert_called_once()
        assert mock_run.call_args.kwargs["resume_build_id"] == _TEST_BUILD_ID
        assert mock_run.call_args.kwargs["orchestration_root"] == tmp_path.resolve()
        assert mock_run.call_args.kwargs["summary_command"] == "echelon delivery resume"

    def test_valid_continue_labels_summary_as_continue(self, tmp_path: Path) -> None:
        _make_echelon_yml(tmp_path, verify_command="pytest")
        sd = _setup_build(tmp_path, "001")
        _write_state(sd, "001", "default", {
            "status": "blocked", "termination_reason": "verify_command_needed",
        })

        with patch("pathlib.Path.cwd", return_value=tmp_path), \
             patch("harness.skills.run_skill.run") as mock_run, \
             patch("harness.docker_provider.DockerWorktreeProvider.__init__", return_value=None), \
             patch("harness.gitops.GitOpsManager.__init__", return_value=None):
            from echelon.cli import _cmd_harness_continue
            _cmd_harness_continue(["001"])

        assert mock_run.call_args.kwargs["summary_command"] == "echelon delivery continue"

    def test_blocker_escalation_resume_calls_run_without_redirecting_to_run(
        self,
        tmp_path: Path,
        capsys,
    ) -> None:
        _make_echelon_yml(tmp_path, verify_command="pytest")
        sd = _setup_build(tmp_path, "001")
        escalation_file = tmp_path / "runs" / "build-test" / "escalation-default.md"
        escalation_file.parent.mkdir(parents=True, exist_ok=True)
        escalation_file.write_text("# Escalation\n\n## Question\n\nClarify?\n", encoding="utf-8")
        _write_state(sd, "001", "default", {
            "status": "blocked",
            "termination_reason": "blocker_escalation",
            "escalation_file": str(escalation_file),
        })

        with patch("pathlib.Path.cwd", return_value=tmp_path), \
             patch("harness.skills.run_skill.run") as mock_run, \
             patch("harness.docker_provider.DockerWorktreeProvider.__init__", return_value=None), \
             patch("harness.gitops.GitOpsManager.__init__", return_value=None):
            from echelon.cli import _cmd_harness_resume
            _cmd_harness_resume(["001", "Use the recommended option", "mode=banzai"])

        mock_run.assert_called_once()
        assert mock_run.call_args.kwargs["resume_build_id"] == _TEST_BUILD_ID
        assert mock_run.call_args.kwargs["orchestration_root"] == tmp_path.resolve()
        user_message = mock_run.call_args.args[0]
        assert "spec 001" in user_message
        assert "mode=banzai" in user_message
        err = capsys.readouterr().err
        assert "blocked for a different reason" not in err
        assert "Use 'echelon delivery run <spec_id>' to resume" not in err
        assert "Use the recommended option" in escalation_file.read_text(encoding="utf-8")

    def test_branchless_legacy_resume_warns_and_continues(
        self,
        tmp_path: Path,
        capsys,
    ) -> None:
        _make_echelon_yml(tmp_path, verify_command="pytest")
        source = tmp_path / "og-platform"
        source.mkdir()
        (source / ".git").mkdir()
        (source / "package.json").write_text("{}", encoding="utf-8")
        sd = _setup_build(tmp_path, "001")
        _write_state(sd, "001", "default", {
            "status": "blocked", "termination_reason": "verify_command_needed",
        })

        with patch("pathlib.Path.cwd", return_value=tmp_path), \
             patch("harness.skills.run_skill.run") as mock_run, \
             patch("harness.docker_provider.DockerWorktreeProvider.__init__", return_value=None), \
             patch("harness.gitops.GitOpsManager.__init__", return_value=None):
            from echelon.cli import _cmd_harness_resume
            _cmd_harness_resume(["001", "mode=banzai"])

        mock_run.assert_called_once()
        assert mock_run.call_args.kwargs["resume_build_id"] == _TEST_BUILD_ID
        err = capsys.readouterr().err
        assert "legacy branchless run detected; continuing for recovery only" in err

    def test_resume_forwards_mode_to_run(self, tmp_path: Path) -> None:
        _make_echelon_yml(tmp_path, verify_command="pytest")
        sd = _setup_build(tmp_path, "001")
        _write_state(sd, "001", "default", {
            "status": "blocked", "termination_reason": "verify_command_needed",
        })

        with patch("pathlib.Path.cwd", return_value=tmp_path), \
             patch("harness.skills.run_skill.run") as mock_run, \
             patch("harness.docker_provider.DockerWorktreeProvider.__init__", return_value=None), \
             patch("harness.gitops.GitOpsManager.__init__", return_value=None):
            from echelon.cli import _cmd_harness_resume
            _cmd_harness_resume(["001", "mode=banzai"])

        user_message = mock_run.call_args.args[0]
        assert "mode=banzai" in user_message
        assert mock_run.call_args.kwargs["resume_build_id"] == _TEST_BUILD_ID

    def test_checkpoint_outer_cap_resumes_without_recovery(self, tmp_path: Path) -> None:
        _make_echelon_yml(tmp_path, verify_command="pytest")
        sd = _setup_build(tmp_path, "001")
        _write_state(sd, "001", "default", {
            "status": "blocked", "termination_reason": "checkpoint_outer_cap",
        })

        with patch("pathlib.Path.cwd", return_value=tmp_path), \
             patch("harness.recovery.recover_blocked_run") as mock_recover, \
             patch("harness.skills.run_skill.run") as mock_run, \
             patch("harness.docker_provider.DockerWorktreeProvider.__init__", return_value=None), \
             patch("harness.gitops.GitOpsManager.__init__", return_value=None):
            from echelon.cli import _cmd_harness_resume
            _cmd_harness_resume(["001", "mode=banzai"])

        mock_recover.assert_not_called()
        mock_run.assert_called_once()
        assert mock_run.call_args.kwargs["resume_build_id"] == _TEST_BUILD_ID
        assert mock_run.call_args.kwargs["orchestration_root"] == tmp_path.resolve()
        user_message = mock_run.call_args.args[0]
        assert "mode=banzai" in user_message

    def test_no_progress_resumes_without_unsupported_reason_error(self, tmp_path: Path) -> None:
        _make_echelon_yml(tmp_path, verify_command="pytest")
        sd = _setup_build(tmp_path, "001")
        _write_state(sd, "001", "default", {
            "status": "blocked",
            "termination_reason": "no_progress",
        })

        with patch("pathlib.Path.cwd", return_value=tmp_path), \
             patch("harness.recovery.recover_blocked_run") as mock_recover, \
             patch("harness.skills.run_skill.run") as mock_run, \
             patch("harness.docker_provider.DockerWorktreeProvider.__init__", return_value=None), \
             patch("harness.gitops.GitOpsManager.__init__", return_value=None):
            from echelon.cli import _cmd_harness_resume
            _cmd_harness_resume(["001", "mode=banzai"])

        mock_recover.assert_not_called()
        mock_run.assert_called_once()
        assert mock_run.call_args.kwargs["resume_build_id"] == _TEST_BUILD_ID
        assert mock_run.call_args.kwargs["orchestration_root"] == tmp_path.resolve()
        user_message = mock_run.call_args.args[0]
        assert "mode=banzai" in user_message

    def test_target_merge_failure_retries_without_git_recovery(
        self, tmp_path: Path
    ) -> None:
        _make_echelon_yml(tmp_path, verify_command="pytest")
        sd = _setup_build(tmp_path, "001")
        _write_state(sd, "001", "default", {
            "status": "blocked",
            "termination_reason": "target_merge_failed",
            "verified_publish_checkpoint": {
                "schema_version": 1,
                "stage": "target_merge",
            },
        })

        with patch("pathlib.Path.cwd", return_value=tmp_path), \
             patch("harness.recovery.recover_blocked_run") as mock_recover, \
             patch("harness.skills.run_skill.run") as mock_run, \
             patch("harness.docker_provider.DockerWorktreeProvider.__init__", return_value=None), \
             patch("harness.gitops.GitOpsManager.__init__", return_value=None):
            from echelon.cli import _cmd_harness_resume
            _cmd_harness_resume(["001", "mode=banzai"])

        mock_recover.assert_not_called()
        mock_run.assert_called_once()
        assert mock_run.call_args.kwargs["resume_build_id"] == _TEST_BUILD_ID

    def test_delivery_continue_resumes_no_progress_without_answer(self, tmp_path: Path) -> None:
        _make_echelon_yml(tmp_path, verify_command="pytest")
        sd = _setup_build(tmp_path, "001")
        _write_state(sd, "001", "default", {
            "status": "blocked",
            "termination_reason": "no_progress",
        })

        with patch("pathlib.Path.cwd", return_value=tmp_path), \
             patch("harness.skills.run_skill.run") as mock_run, \
             patch("harness.docker_provider.DockerWorktreeProvider.__init__", return_value=None), \
             patch("harness.gitops.GitOpsManager.__init__", return_value=None):
            from echelon.cli import _cmd_harness_continue
            _cmd_harness_continue(["001", "mode=banzai"])

        mock_run.assert_called_once()
        user_message = mock_run.call_args.args[0]
        assert "mode=banzai" in user_message

    def test_resume_without_answer_warns_to_use_continue_when_no_escalation(
        self,
        tmp_path: Path,
        capsys,
    ) -> None:
        _make_echelon_yml(tmp_path, verify_command="pytest")
        sd = _setup_build(tmp_path, "001")
        _write_state(sd, "001", "default", {
            "status": "blocked",
            "termination_reason": "no_progress",
        })

        with patch("pathlib.Path.cwd", return_value=tmp_path), \
             patch("harness.skills.run_skill.run") as mock_run, \
             patch("harness.docker_provider.DockerWorktreeProvider.__init__", return_value=None), \
             patch("harness.gitops.GitOpsManager.__init__", return_value=None):
            from echelon.cli import _cmd_harness_resume
            _cmd_harness_resume(["001"])

        mock_run.assert_called_once()
        err = capsys.readouterr().err
        assert "delivery resume without an answer is deprecated" in err
        assert "echelon delivery continue 001" in err

    def test_resume_records_positional_answer_for_escalation_file(
        self,
        tmp_path: Path,
    ) -> None:
        _make_echelon_yml(tmp_path, verify_command="pytest")
        sd = _setup_build(tmp_path, "001")
        escalation_file = tmp_path / "runs" / _TEST_BUILD_ID / "escalations" / "001-default.md"
        escalation_file.parent.mkdir(parents=True)
        escalation_file.write_text("# Escalation\n\n## Question\n\nClarify?\n", encoding="utf-8")
        _write_state(sd, "001", "default", {
            "status": "blocked",
            "termination_reason": "no_progress",
            "escalation_file": str(escalation_file),
        })

        with patch("pathlib.Path.cwd", return_value=tmp_path), \
             patch("harness.skills.run_skill.run") as mock_run, \
             patch("harness.docker_provider.DockerWorktreeProvider.__init__", return_value=None), \
             patch("harness.gitops.GitOpsManager.__init__", return_value=None):
            from echelon.cli import _cmd_harness_resume
            _cmd_harness_resume(["001", "Use the current implementation and continue", "mode=banzai"])

        mock_run.assert_called_once()
        assert mock_run.call_args.kwargs["orchestration_root"] == tmp_path.resolve()
        content = escalation_file.read_text(encoding="utf-8")
        assert "## Answer" in content
        assert "Use the current implementation and continue" in content

    def test_resume_without_answer_stays_blocked_when_escalation_needs_answer(
        self,
        tmp_path: Path,
        capsys,
    ) -> None:
        _make_echelon_yml(tmp_path, verify_command="pytest")
        sd = _setup_build(tmp_path, "001")
        escalation_file = tmp_path / "runs" / _TEST_BUILD_ID / "escalations" / "001-default.md"
        escalation_file.parent.mkdir(parents=True)
        escalation_file.write_text("# Escalation\n\n## Question\n\nClarify?\n", encoding="utf-8")
        _write_state(sd, "001", "default", {
            "status": "blocked",
            "termination_reason": "no_progress",
            "escalation_file": str(escalation_file),
        })

        with patch("pathlib.Path.cwd", return_value=tmp_path), \
             patch("harness.skills.run_skill.run") as mock_run, \
             patch("harness.docker_provider.DockerWorktreeProvider.__init__", return_value=None), \
             patch("harness.gitops.GitOpsManager.__init__", return_value=None):
            from echelon.cli import _cmd_harness_resume
            with pytest.raises(SystemExit) as exc:
                _cmd_harness_resume(["001"])

        assert exc.value.code == 1
        mock_run.assert_not_called()
        err = capsys.readouterr().err
        assert 'echelon delivery resume 001 "<answer>"' in err
        assert "echelon delivery continue 001" in err

    def test_harness_error_retries_after_phase_a_repair_and_refreshes_spec_paths(
        self,
        tmp_path: Path,
    ) -> None:
        _make_echelon_yml(tmp_path)
        spec_dir = _make_phase_a_spec(tmp_path)
        sd = _setup_build(tmp_path, "001")
        _write_state(sd, "001", "default", {
            "status": "blocked",
            "termination_reason": "harness_error",
            "harness_error": "no canonical task rows found",
            "spec_dir": "/tmp/specs/001-wrong",
            "spec_file": "/tmp/specs/001-wrong/spec.md",
            "tasks_file": "/tmp/specs/001-wrong/tasks.md",
        })

        with patch("pathlib.Path.cwd", return_value=tmp_path), \
             patch("harness.skills.run_skill.run") as mock_run, \
             patch("harness.docker_provider.DockerWorktreeProvider.__init__", return_value=None), \
             patch("harness.gitops.GitOpsManager.__init__", return_value=None):
            from echelon.cli import _cmd_harness_resume
            _cmd_harness_resume(["001", "mode=banzai"])

        mock_run.assert_called_once()
        assert mock_run.call_args.kwargs["resume_build_id"] == _TEST_BUILD_ID
        assert mock_run.call_args.kwargs["orchestration_root"] == tmp_path.resolve()
        user_message = mock_run.call_args.args[0]
        assert "mode=banzai" in user_message
        state = json.loads((sd / "default.json").read_text(encoding="utf-8"))
        assert state["spec_dir"] == str(spec_dir)
        assert state["spec_file"] == str(spec_dir / "spec.md")
        assert state["tasks_file"] == str(spec_dir / "tasks.md")

    def test_harness_error_stays_blocked_when_repair_preflight_fails(
        self,
        tmp_path: Path,
        capsys,
    ) -> None:
        _make_echelon_yml(tmp_path)
        _make_phase_a_spec(tmp_path, canonical_tasks=False)
        sd = _setup_build(tmp_path, "001")
        _write_state(sd, "001", "default", {
            "status": "blocked",
            "termination_reason": "harness_error",
            "harness_error": "no canonical task rows found",
        })

        with patch("pathlib.Path.cwd", return_value=tmp_path), \
             patch("harness.skills.run_skill.run") as mock_run, \
             patch("harness.docker_provider.DockerWorktreeProvider.__init__", return_value=None), \
             patch("harness.gitops.GitOpsManager.__init__", return_value=None):
            from echelon.cli import _cmd_harness_resume
            with pytest.raises(SystemExit) as exc:
                _cmd_harness_resume(["001"])

        assert exc.value.code == 1
        mock_run.assert_not_called()
        err = capsys.readouterr().err
        assert "Resume preflight failed" in err
        assert "tasks.md is not canonical" in err
        state = json.loads((sd / "default.json").read_text(encoding="utf-8"))
        assert state["termination_reason"] == "harness_error"

    def test_phase_a_build_incomplete_retries_without_git_recovery(
        self,
        tmp_path: Path,
    ) -> None:
        _make_echelon_yml(tmp_path)
        _make_phase_a_spec(tmp_path)
        sd = _setup_build(tmp_path, "001")
        _write_state(sd, "001", "default", {
            "status": "blocked",
            "termination_reason": "build_incomplete",
            "build_status": "blocked",
            "build_reason": "Phase A artifacts are not build-ready: constitution.md contains unresolved template markers",
        })

        with patch("pathlib.Path.cwd", return_value=tmp_path), \
             patch("harness.recovery.recover_blocked_run") as mock_recover, \
             patch("harness.skills.run_skill.run") as mock_run, \
             patch("harness.docker_provider.DockerWorktreeProvider.__init__", return_value=None), \
             patch("harness.gitops.GitOpsManager.__init__", return_value=None):
            from echelon.cli import _cmd_harness_resume
            _cmd_harness_resume(["001"])

        mock_recover.assert_not_called()
        mock_run.assert_called_once()
        assert mock_run.call_args.kwargs["resume_build_id"] == _TEST_BUILD_ID

    def test_phase_a_build_incomplete_stays_blocked_when_preflight_fails(
        self,
        tmp_path: Path,
        capsys,
    ) -> None:
        _make_echelon_yml(tmp_path)
        _make_phase_a_spec(tmp_path, canonical_tasks=False)
        sd = _setup_build(tmp_path, "001")
        _write_state(sd, "001", "default", {
            "status": "blocked",
            "termination_reason": "build_incomplete",
            "build_status": "phase_a_not_ready",
            "build_reason": "Phase A artifacts are not build-ready",
        })

        with patch("pathlib.Path.cwd", return_value=tmp_path), \
             patch("harness.recovery.recover_blocked_run") as mock_recover, \
             patch("harness.skills.run_skill.run") as mock_run, \
             patch("harness.docker_provider.DockerWorktreeProvider.__init__", return_value=None), \
             patch("harness.gitops.GitOpsManager.__init__", return_value=None):
            from echelon.cli import _cmd_harness_resume
            with pytest.raises(SystemExit) as exc:
                _cmd_harness_resume(["001"])

        assert exc.value.code == 1
        mock_recover.assert_not_called()
        mock_run.assert_not_called()
        err = capsys.readouterr().err
        assert "still blocked after Phase A repair" in err
        assert "tasks.md is not canonical" in err

    @pytest.mark.parametrize("reason", ["build_incomplete", "publish_failed"])
    def test_recoverable_blocked_reason_recovers_and_calls_run(
        self,
        tmp_path: Path,
        reason: str,
    ) -> None:
        _make_echelon_yml(tmp_path)
        sd = _setup_build(tmp_path, "001")
        _write_state(sd, "001", "default", {
            "status": "blocked", "termination_reason": reason,
        })

        with patch("pathlib.Path.cwd", return_value=tmp_path), \
             patch("harness.recovery.recover_blocked_run") as mock_recover, \
             patch("harness.skills.run_skill.run") as mock_run, \
             patch("harness.docker_provider.DockerWorktreeProvider.__init__", return_value=None), \
             patch("harness.gitops.GitOpsManager.__init__", return_value=None):
            mock_recover.return_value = MagicMock(
                source="mirror",
                commit="abc123",
                target_branch="001-feature",
                applied=True,
            )
            from echelon.cli import _cmd_harness_resume
            _cmd_harness_resume(["001"])

        mock_recover.assert_called_once()
        mock_run.assert_called_once()
        assert mock_run.call_args.kwargs["resume_build_id"] == _TEST_BUILD_ID
        assert mock_run.call_args.kwargs["orchestration_root"] == tmp_path.resolve()

    def test_continue_returns_nonzero_when_recovered_delivery_cannot_land(
        self,
        tmp_path: Path,
    ) -> None:
        from harness.delivery_results import (
            DeliveryResult,
            DeliveryRunOutcome,
            LandingOutcome,
        )

        _make_echelon_yml(tmp_path)
        sd = _setup_build(tmp_path, "001")
        _write_state(
            sd,
            "001",
            "default",
            {"status": "blocked", "termination_reason": "publish_failed"},
        )
        outcome = DeliveryRunOutcome(
            results=(
                DeliveryResult(
                    status="converged",
                    termination_reason="converged",
                    outer_iterations=2,
                    inner_iterations=0,
                    pr_url=None,
                    tokens_used=100,
                    final_verify=None,
                    blocked_phase=None,
                    branch="harness/001/default/iter-1",
                ),
            ),
            landing=LandingOutcome("blocked", "land_returned_false"),
        )

        with patch("pathlib.Path.cwd", return_value=tmp_path), \
             patch("harness.recovery.recover_blocked_run") as mock_recover, \
             patch("harness.skills.run_skill.run", return_value=outcome), \
             patch(
                 "harness.docker_provider.DockerWorktreeProvider.__init__",
                 return_value=None,
             ), \
             patch("harness.gitops.GitOpsManager.__init__", return_value=None):
            mock_recover.return_value = MagicMock(
                source="worktree",
                commit="abc123",
                target_branch="harness/001/default/iter-0",
                applied=True,
            )
            from echelon.cli import _cmd_harness_continue

            with pytest.raises(SystemExit) as exc:
                _cmd_harness_continue(["001"])

        assert exc.value.code == 1

    def test_provider_limit_resume_skips_recovery_for_legacy_blocked_state(
        self, tmp_path: Path
    ) -> None:
        """Provider exhaustion resumes the preserved worktree without cherry-picking."""
        _make_echelon_yml(tmp_path, verify_command="pytest")
        sd = _setup_build(tmp_path, "001")
        _write_state(sd, "001", "default", {
            "status": "blocked",
            "termination_reason": "build_incomplete",
            "build_status": "provider_session_limit",
        })

        with patch("pathlib.Path.cwd", return_value=tmp_path), \
             patch("harness.recovery.recover_blocked_run") as mock_recover, \
             patch("harness.skills.run_skill.run") as mock_run, \
             patch("harness.docker_provider.DockerWorktreeProvider.__init__", return_value=None), \
             patch("harness.gitops.GitOpsManager.__init__", return_value=None):
            from echelon.cli import _cmd_harness_continue
            with pytest.raises(SystemExit) as exc:
                _cmd_harness_continue(["001"])

        assert exc.value.code == 2
        mock_recover.assert_not_called()
        mock_run.assert_called_once()
        state = json.loads((sd / "default.json").read_text(encoding="utf-8"))
        assert state["termination_reason"] == "provider_session_limit"

    def test_converged_resume_ignores_historical_provider_limit_status(
        self, tmp_path: Path
    ) -> None:
        """A successful resumed run must not inherit an old provider-limit exit code."""
        _make_echelon_yml(tmp_path, verify_command="pytest")
        sd = _setup_build(tmp_path, "001")
        _write_state(sd, "001", "default", {
            "status": "blocked",
            "termination_reason": "provider_session_limit",
            "build_status": "provider_session_limit",
        })

        def converge(*_args, **_kwargs) -> None:
            state_path = sd / "default.json"
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state.update({"status": "converged", "termination_reason": "converged"})
            state_path.write_text(json.dumps(state), encoding="utf-8")

        with patch("pathlib.Path.cwd", return_value=tmp_path), \
             patch("harness.recovery.recover_blocked_run") as mock_recover, \
             patch("harness.skills.run_skill.run", side_effect=converge) as mock_run, \
             patch("harness.docker_provider.DockerWorktreeProvider.__init__", return_value=None), \
             patch("harness.gitops.GitOpsManager.__init__", return_value=None):
            from echelon.cli import _cmd_harness_continue
            _cmd_harness_continue(["001"])

        mock_recover.assert_not_called()
        mock_run.assert_called_once()

    def test_target_resume_recovers_against_source_repo_not_target_harness_dir(
        self,
        tmp_path: Path,
    ) -> None:
        polyrepo = tmp_path / "workspace"
        source = polyrepo / "sources" / "prosaic"
        harness_base = polyrepo / "runs" / "targets" / "prosaic"
        source.mkdir(parents=True)
        _make_echelon_yml(polyrepo)
        _make_phase_a_spec(polyrepo, "001-prose-distribution-engine")
        sd = _setup_build(harness_base, "001-prose-distribution-engine")
        _write_state(sd, "001-prose-distribution-engine", "default", {
            "status": "blocked",
            "termination_reason": "build_incomplete",
            "target_path": str(source),
            "source_root": str(source),
            "workspace_root": str(polyrepo),
        })

        env = {
            "ECHELON_TARGET_REPO_PATH": str(source),
            "ECHELON_TARGET_REPO_NAME": "prosaic",
            "ECHELON_POLYREPO_ROOT": str(polyrepo),
        }
        with patch.dict("os.environ", env, clear=False), \
             patch("pathlib.Path.cwd", return_value=harness_base), \
             patch("echelon.cli._sync_polyrepo_runtime_extension"), \
             patch("harness.recovery.recover_blocked_run") as mock_recover, \
             patch("harness.skills.run_skill.run") as mock_run, \
             patch("harness.docker_provider.DockerWorktreeProvider.__init__", return_value=None), \
             patch("harness.gitops.GitOpsManager.__init__", return_value=None):
            mock_recover.return_value = MagicMock(
                source="target_branch",
                commit="abc123",
                target_branch="001-prose-distribution-engine",
                applied=False,
                backed_up_untracked=(),
            )
            from echelon.cli import _cmd_harness_resume
            _cmd_harness_resume(["001-prose-distribution-engine"])

        mock_recover.assert_called_once()
        assert mock_recover.call_args.kwargs["project_dir"] == source
        mock_run.assert_called_once()

    def test_target_continue_dispatches_continue_not_answer_required_resume(
        self,
        tmp_path: Path,
    ) -> None:
        polyrepo = tmp_path / "workspace"
        source = polyrepo / "sources" / "prosaic"
        source.mkdir(parents=True)
        (source / ".git").mkdir()
        _make_echelon_yml(polyrepo)
        spec_dir = _make_phase_a_spec(polyrepo, "001-prose-distribution-engine")
        (spec_dir / "spec.md").write_text(
            "---\ntargets:\n  - sources/prosaic\n---\n# Spec\n",
            encoding="utf-8",
        )
        (spec_dir / "tasks.md").write_text(
            "- [x] T-001 complexity=standard phase=build req=FR-001 depends=none target=sources/prosaic\n",
            encoding="utf-8",
        )

        with patch("pathlib.Path.cwd", return_value=polyrepo), \
             patch("echelon.orchestrator.run_multi_target", return_value=0) as mock_run:
            from echelon.cli import _cmd_harness_continue
            with pytest.raises(SystemExit) as exc:
                _cmd_harness_continue(["001-prose-distribution-engine"])

        assert exc.value.code == 0
        mock_run.assert_called_once()
        assert mock_run.call_args.kwargs["command"] == "continue"

    def test_target_resume_detects_verify_command_from_feature_branch(
        self,
        tmp_path: Path,
    ) -> None:
        polyrepo = tmp_path / "workspace"
        source = polyrepo / "sources" / "prosaic"
        harness_base = polyrepo / "runs" / "targets" / "prosaic"
        source.mkdir(parents=True)
        subprocess.run(["git", "init", "-b", "main"], cwd=source, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=source, check=True)
        subprocess.run(["git", "config", "user.name", "Test User"], cwd=source, check=True)
        (source / "README.md").write_text("# Prosaic\n", encoding="utf-8")
        subprocess.run(["git", "add", "README.md"], cwd=source, check=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=source, check=True, capture_output=True)
        subprocess.run(
            ["git", "switch", "-c", "001-prose-distribution-engine"],
            cwd=source,
            check=True,
            capture_output=True,
        )
        (source / "package.json").write_text(
            json.dumps({"scripts": {"test": "jest"}}),
            encoding="utf-8",
        )
        subprocess.run(["git", "add", "package.json"], cwd=source, check=True)
        subprocess.run(
            ["git", "commit", "-m", "add app"],
            cwd=source,
            check=True,
            capture_output=True,
        )
        subprocess.run(["git", "switch", "main"], cwd=source, check=True, capture_output=True)

        _make_echelon_yml(polyrepo)
        _make_phase_a_spec(polyrepo, "001-prose-distribution-engine")
        sd = _setup_build(harness_base, "001-prose-distribution-engine")
        _write_state(sd, "001-prose-distribution-engine", "default", {
            "status": "blocked",
            "termination_reason": "verify_command_needed",
            "target_path": str(source),
            "source_root": str(source),
            "workspace_root": str(polyrepo),
        })

        env = {
            "ECHELON_TARGET_REPO_PATH": str(source),
            "ECHELON_TARGET_REPO_NAME": "prosaic",
            "ECHELON_POLYREPO_ROOT": str(polyrepo),
        }
        from echelon import cli as echelon_cli

        with patch.dict("os.environ", env, clear=False), \
             patch("pathlib.Path.cwd", return_value=harness_base), \
             patch("echelon.cli._sync_polyrepo_runtime_extension"), \
             patch("harness.skills.run_skill.run") as mock_run, \
             patch("harness.docker_provider.DockerWorktreeProvider.__init__", return_value=None), \
             patch("harness.gitops.GitOpsManager.__init__", return_value=None):
            echelon_cli._cmd_harness_resume(["001-prose-distribution-engine", "mode=banzai"])

        mock_run.assert_called_once()
        assert mock_run.call_args.kwargs["config"].verify_command == "npm test"
        assert mock_run.call_args.kwargs["resume_build_id"] == _TEST_BUILD_ID

    def test_recoverable_resume_handles_docker_unavailable_gracefully(
        self,
        tmp_path: Path,
        capsys,
    ) -> None:
        from harness.errors import SandboxExecError

        _make_echelon_yml(tmp_path)
        sd = _setup_build(tmp_path, "001")
        _write_state(sd, "001", "default", {
            "status": "blocked", "termination_reason": "build_incomplete",
        })

        with patch("pathlib.Path.cwd", return_value=tmp_path), \
             patch("harness.recovery.recover_blocked_run") as mock_recover, \
             patch("harness.skills.run_skill.run") as mock_run, \
             patch("harness.docker_provider.DockerWorktreeProvider.__init__", return_value=None), \
             patch("harness.gitops.GitOpsManager.__init__", return_value=None):
            mock_recover.return_value = MagicMock(
                source="worktree",
                commit="abc123",
                target_branch="001-feature",
                applied=True,
            )
            mock_run.side_effect = SandboxExecError(
                "Docker command failed: failed to connect to the docker API at "
                "unix:///Users/example/.docker/run/docker.sock; check if the daemon is running"
            )
            from echelon.cli import _cmd_harness_resume
            with pytest.raises(SystemExit) as exc:
                _cmd_harness_resume(["001"])

        assert exc.value.code == 1
        state = json.loads((sd / "default.json").read_text(encoding="utf-8"))
        assert state["status"] == "blocked"
        assert state["termination_reason"] == "docker_unavailable"
        err = capsys.readouterr().err
        assert "Docker is not running or is unreachable" in err
        assert "echelon delivery continue 001" in err
        assert "Traceback" not in err

    def test_delivery_continue_retries_after_docker_unavailable(
        self,
        tmp_path: Path,
    ) -> None:
        _make_echelon_yml(tmp_path, verify_command="pytest")
        sd = _setup_build(tmp_path, "001")
        _write_state(sd, "001", "default", {
            "status": "blocked", "termination_reason": "docker_unavailable",
        })

        with patch("pathlib.Path.cwd", return_value=tmp_path), \
             patch("harness.skills.run_skill.run") as mock_run, \
             patch("harness.docker_provider.DockerWorktreeProvider.__init__", return_value=None), \
             patch("harness.gitops.GitOpsManager.__init__", return_value=None):
            from echelon.cli import _cmd_harness_continue
            _cmd_harness_continue(["001"])

        mock_run.assert_called_once()
        assert mock_run.call_args.kwargs["resume_build_id"] == _TEST_BUILD_ID

    def test_recoverable_resume_marks_unexpected_harness_error_blocked(
        self,
        tmp_path: Path,
        capsys,
    ) -> None:
        _make_echelon_yml(tmp_path)
        sd = _setup_build(tmp_path, "001")
        _write_state(sd, "001", "default", {
            "status": "blocked", "termination_reason": "build_incomplete",
        })

        with patch("pathlib.Path.cwd", return_value=tmp_path), \
             patch("harness.recovery.recover_blocked_run") as mock_recover, \
             patch("harness.skills.run_skill.run") as mock_run, \
             patch("harness.docker_provider.DockerWorktreeProvider.__init__", return_value=None), \
             patch("harness.gitops.GitOpsManager.__init__", return_value=None):
            mock_recover.return_value = MagicMock(
                source="worktree",
                commit="abc123",
                target_branch="001-feature",
                applied=True,
            )
            mock_run.side_effect = RuntimeError("fatal: invalid reference")
            from echelon.cli import _cmd_harness_resume
            with pytest.raises(SystemExit) as exc:
                _cmd_harness_resume(["001"])

        assert exc.value.code == 1
        state = json.loads((sd / "default.json").read_text(encoding="utf-8"))
        assert state["status"] == "blocked"
        assert state["termination_reason"] == "harness_error"
        assert "fatal: invalid reference" in state["harness_error"]
        err = capsys.readouterr().err
        assert "Harness run failed before completion" in err
        assert "echelon delivery resume 001" in err
        assert "Traceback" not in err

    def test_recoverable_reason_recovers_even_when_status_was_overwritten_done(
        self,
        tmp_path: Path,
    ) -> None:
        _make_echelon_yml(tmp_path)
        sd = _setup_build(tmp_path, "001")
        _write_state(sd, "001", "default", {
            "status": "done",
            "termination_reason": "build_incomplete",
        })

        with patch("pathlib.Path.cwd", return_value=tmp_path), \
             patch("harness.recovery.recover_blocked_run") as mock_recover, \
             patch("harness.skills.run_skill.run") as mock_run, \
             patch("harness.docker_provider.DockerWorktreeProvider.__init__", return_value=None), \
             patch("harness.gitops.GitOpsManager.__init__", return_value=None):
            mock_recover.return_value = MagicMock(
                source="mirror",
                commit="abc123",
                target_branch="001-feature",
                applied=True,
            )
            from echelon.cli import _cmd_harness_resume
            _cmd_harness_resume(["001"])

        mock_recover.assert_called_once()
        mock_run.assert_called_once()
        assert mock_run.call_args.kwargs["resume_build_id"] == _TEST_BUILD_ID

    def test_no_args_prints_help(self, tmp_path: Path, capsys) -> None:
        from echelon.cli import _cmd_harness_resume
        _cmd_harness_resume([])
        out = capsys.readouterr().out
        assert "verify_command" in out
        assert "echelon delivery resume" in out
