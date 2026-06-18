"""Tests for _cmd_harness_resume in cli.py."""

from __future__ import annotations

import json
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
    marker = current_build_marker(base, spec_id)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(_TEST_BUILD_ID)
    sd = build_dir(base, _TEST_BUILD_ID) / "state"
    sd.mkdir(parents=True, exist_ok=True)
    return sd


def _make_echelon_yml(base: Path, verify_command: str = "") -> Path:
    """Write a minimal echelon-config.yml."""
    yml_dir = base / ".specify" / "extensions" / "echelon"
    yml_dir.mkdir(parents=True, exist_ok=True)
    content = "autonomy:\n  mode: banzai\ntarget_repo: .\ntarget_default_branch: main\nprovider: docker\n"
    if verify_command:
        content += f"verify_command: {verify_command}\n"
    (yml_dir / "echelon-config.yml").write_text(content)
    return yml_dir / "echelon-config.yml"


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

    def test_wrong_blocked_reason_exits_1(self, tmp_path: Path) -> None:
        _make_echelon_yml(tmp_path, verify_command="pytest")
        sd = _setup_build(tmp_path, "001")
        _write_state(sd, "001", "default", {
            "status": "blocked", "termination_reason": "budget_exhausted",
        })
        rc = self._call(["001"], tmp_path)
        assert rc == 1

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
        assert "echelon harness init" in err
        assert "echelon cicd" not in err

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
        user_message = mock_run.call_args.args[0]
        assert "mode=banzai" in user_message

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
        assert "echelon harness resume 001" in err
        assert "Traceback" not in err

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
        assert "echelon harness resume 001" in err
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

    def test_no_args_prints_help(self, tmp_path: Path, capsys) -> None:
        from echelon.cli import _cmd_harness_resume
        _cmd_harness_resume([])
        out = capsys.readouterr().out
        assert "verify_command" in out
        assert "echelon harness resume" in out
