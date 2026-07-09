"""Tests for `echelon land <spec-id>` CLI command."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


class _NonInteractiveStdin:
    def isatty(self) -> bool:
        return False


class _InteractiveStdin:
    def isatty(self) -> bool:
        return True


@pytest.mark.unit
class TestCmdLand:
    """Verify _cmd_land wires arguments correctly and exits with proper codes."""

    def _assert_help_mentions_autonomous_land_flags(self, help_text: str) -> None:
        assert "Usage" in help_text
        assert "--continue" in help_text
        assert "--prepare-only" in help_text
        assert "--no-autoresolve" in help_text
        assert "--allow-fulfillment-gaps" in help_text
        assert "--strategy merge|rebase" in help_text

    @patch("harness.land.land")
    @patch("harness.gitops.GitOpsManager")
    @patch("harness.config.load_config")
    def test_calls_land_with_correct_args(
        self, mock_load_config, mock_gitops_cls, mock_land
    ):
        """land() is called with spec_id, project_dir, and gitops."""
        from echelon.cli import _cmd_land

        expected_cwd = Path.cwd()

        mock_config = MagicMock()
        mock_load_config.return_value = mock_config
        mock_gitops = MagicMock()
        mock_gitops_cls.return_value = mock_gitops
        mock_land.return_value = True

        with pytest.raises(SystemExit) as exc_info:
            _cmd_land(["042"])

        assert exc_info.value.code == 0
        mock_land.assert_called_once_with(
            "042",
            project_dir=expected_cwd,
            gitops=mock_gitops,
            options=mock_land.call_args.kwargs["options"],
        )
        options = mock_land.call_args.kwargs["options"]
        assert options.autoresolve is True
        assert options.prepare_only is False
        assert options.continue_existing is False
        assert options.strategy == "merge"
        assert options.allow_fulfillment_gaps is False

    def test_workspace_land_dispatches_to_spec_target(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from echelon.cli import HarnessWorkspaceTarget, _cmd_land

        root = tmp_path
        spec_dir = root / "specs" / "001-demo"
        spec_dir.mkdir(parents=True)
        (spec_dir / "spec.md").write_text(
            "---\ntargets:\n- sources/prosaic\nstatus: ready_to_land\n---\n# Demo\n",
            encoding="utf-8",
        )
        target = root / "sources" / "prosaic"
        (target / ".git").mkdir(parents=True)

        def fake_resolve(project_root, explicit_target, **kwargs):
            assert project_root == root
            assert explicit_target == "sources/prosaic"
            return HarnessWorkspaceTarget(
                workspace_root=root.resolve(),
                workspace_git_role="orchestration",
                source_root=target.resolve(),
                source_id="prosaic",
                source_git_role="source",
            )

        monkeypatch.chdir(root)
        monkeypatch.setattr("echelon.cli._resolve_harness_workspace_target", fake_resolve)
        with patch("echelon.orchestrator.run_multi_target", return_value=0) as run_multi:
            with pytest.raises(SystemExit) as exc_info:
                _cmd_land(["001", "--continue"])

        assert exc_info.value.code == 0
        run_multi.assert_called_once()
        assert run_multi.call_args.args[:3] == (
            "001-demo",
            [target.resolve()],
            ["--continue"],
        )
        assert run_multi.call_args.kwargs["command"] == "land"
        assert run_multi.call_args.kwargs["workspace_root"] == root.resolve()

    @patch("harness.land.land")
    @patch("harness.gitops.GitOpsManager")
    @patch("harness.config.load_config")
    def test_target_env_land_uses_workspace_root_and_target_gitops_base(
        self,
        mock_load_config,
        mock_gitops_cls,
        mock_land,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from echelon.cli import _cmd_land

        workspace = tmp_path / "workspace"
        target = workspace / "sources" / "prosaic"
        target.mkdir(parents=True)
        harness_base = workspace / "runs" / "targets" / "prosaic"
        mock_config = MagicMock()
        mock_load_config.return_value = mock_config
        mock_gitops = MagicMock()
        mock_gitops_cls.return_value = mock_gitops
        mock_land.return_value = True

        monkeypatch.chdir(target)
        monkeypatch.setenv("ECHELON_POLYREPO_ROOT", str(workspace))
        monkeypatch.setenv("ECHELON_TARGET_REPO_PATH", str(target))
        monkeypatch.setenv("ECHELON_TARGET_REPO_NAME", "prosaic")

        with (
            patch("echelon.cli._sync_polyrepo_runtime_extension") as sync_ext,
            patch("harness.paths.mirror_path", return_value=harness_base / "runs" / "mirror.git"),
            pytest.raises(SystemExit) as exc_info,
        ):
            _cmd_land(["001"])

        assert exc_info.value.code == 0
        mock_load_config.assert_called_once_with(project_root=workspace, squad_only=True)
        sync_ext.assert_called_once_with(workspace, harness_base)
        mock_gitops_cls.assert_called_once_with(mock_config, base_dir=str(harness_base))
        assert mock_config.target_repo == str(target.resolve())
        mock_gitops.clone_mirror.assert_called_once_with(str(target.resolve()))
        mock_land.assert_called_once_with(
            "001",
            project_dir=workspace,
            gitops=mock_gitops,
            options=mock_land.call_args.kwargs["options"],
        )

    @patch("harness.land.land")
    @patch("harness.gitops.GitOpsManager")
    @patch("harness.config.load_config")
    def test_land_passes_continue_option(
        self, mock_load_config, mock_gitops_cls, mock_land
    ):
        """--continue tells land() to continue an existing preparation."""
        from echelon.cli import _cmd_land

        mock_load_config.return_value = MagicMock()
        mock_gitops_cls.return_value = MagicMock()
        mock_land.return_value = True

        with pytest.raises(SystemExit) as exc_info:
            _cmd_land(["042", "--continue"])

        assert exc_info.value.code == 0
        options = mock_land.call_args.kwargs["options"]
        assert options.continue_existing is True

    @patch("harness.land.land")
    @patch("harness.gitops.GitOpsManager")
    @patch("harness.config.load_config")
    def test_land_passes_prepare_only_and_no_autoresolve_options(
        self, mock_load_config, mock_gitops_cls, mock_land
    ):
        """--prepare-only and --no-autoresolve are forwarded as LandOptions."""
        from echelon.cli import _cmd_land

        mock_load_config.return_value = MagicMock()
        mock_gitops_cls.return_value = MagicMock()
        mock_land.return_value = True

        with pytest.raises(SystemExit):
            _cmd_land(["042", "--prepare-only", "--no-autoresolve"])

        options = mock_land.call_args.kwargs["options"]
        assert options.prepare_only is True
        assert options.autoresolve is False

    @patch("echelon.cli._archive_squad_run")
    @patch("harness.land.land")
    @patch("harness.gitops.GitOpsManager")
    @patch("harness.config.load_config")
    def test_prepare_only_success_does_not_archive_as_landed(
        self, mock_load_config, mock_gitops_cls, mock_land, mock_archive, capsys
    ):
        """A prepare-only success is not treated as a completed landing."""
        from echelon.cli import _cmd_land

        mock_load_config.return_value = MagicMock()
        mock_gitops_cls.return_value = MagicMock()
        mock_land.return_value = True

        with pytest.raises(SystemExit) as exc_info:
            _cmd_land(["042", "--prepare-only"])

        assert exc_info.value.code == 0
        mock_archive.assert_not_called()
        captured = capsys.readouterr()
        assert "prepared" in captured.out.lower()
        assert "landed successfully" not in captured.out.lower()

    @patch("harness.land.land")
    @patch("harness.gitops.GitOpsManager")
    @patch("harness.config.load_config")
    def test_land_passes_rebase_strategy(
        self, mock_load_config, mock_gitops_cls, mock_land
    ):
        """--strategy rebase is forwarded as LandOptions.strategy."""
        from echelon.cli import _cmd_land

        mock_load_config.return_value = MagicMock()
        mock_gitops_cls.return_value = MagicMock()
        mock_land.return_value = True

        with pytest.raises(SystemExit):
            _cmd_land(["042", "--strategy", "rebase"])

        assert mock_land.call_args.kwargs["options"].strategy == "rebase"

    def test_archive_squad_run_skips_when_stdin_is_noninteractive(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        from echelon.cli import _archive_squad_run

        run_dir = tmp_path / "runs" / "spec-1"
        run_dir.mkdir(parents=True)
        (tmp_path / "runs" / ".current").write_text(str(run_dir), encoding="utf-8")
        spec_dir = tmp_path / "specs" / "001-demo"
        spec_dir.mkdir(parents=True)
        (spec_dir / "spec.md").write_text("# Spec\n", encoding="utf-8")

        with patch("sys.stdin", _NonInteractiveStdin()):
            _archive_squad_run(tmp_path, "001")

        assert run_dir.exists()
        assert not (spec_dir / "run").exists()
        assert "non-interactive stdin" in capsys.readouterr().out

    def test_archive_squad_run_skips_on_eof(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        from echelon.cli import _archive_squad_run

        run_dir = tmp_path / "runs" / "spec-1"
        run_dir.mkdir(parents=True)
        (tmp_path / "runs" / ".current").write_text(str(run_dir), encoding="utf-8")
        spec_dir = tmp_path / "specs" / "001-demo"
        spec_dir.mkdir(parents=True)
        (spec_dir / "spec.md").write_text("# Spec\n", encoding="utf-8")

        with (
            patch("sys.stdin", _InteractiveStdin()),
            patch("builtins.input", side_effect=EOFError),
        ):
            _archive_squad_run(tmp_path, "001")

        assert run_dir.exists()
        assert not (spec_dir / "run").exists()
        assert "no input available" in capsys.readouterr().out

    @patch("harness.land.land")
    @patch("harness.gitops.GitOpsManager")
    @patch("harness.config.load_config")
    def test_land_passes_explicit_merge_strategy(
        self, mock_load_config, mock_gitops_cls, mock_land
    ):
        """--strategy merge is forwarded as LandOptions.strategy."""
        from echelon.cli import _cmd_land

        mock_load_config.return_value = MagicMock()
        mock_gitops_cls.return_value = MagicMock()
        mock_land.return_value = True

        with pytest.raises(SystemExit):
            _cmd_land(["042", "--strategy", "merge"])

        assert mock_land.call_args.kwargs["options"].strategy == "merge"

    @patch("harness.land.land")
    @patch("harness.gitops.GitOpsManager")
    @patch("harness.config.load_config")
    def test_land_passes_allow_fulfillment_gaps_option(
        self, mock_load_config, mock_gitops_cls, mock_land
    ):
        """--allow-fulfillment-gaps permits landing despite fulfillment report gaps."""
        from echelon.cli import _cmd_land

        mock_load_config.return_value = MagicMock()
        mock_gitops_cls.return_value = MagicMock()
        mock_land.return_value = True

        with pytest.raises(SystemExit):
            _cmd_land(["042", "--allow-fulfillment-gaps"])

        assert mock_land.call_args.kwargs["options"].allow_fulfillment_gaps is True

    def test_missing_strategy_value_exits_1(self, capsys):
        """--strategy requires an explicit merge or rebase value."""
        from echelon.cli import _cmd_land

        with pytest.raises(SystemExit) as exc_info:
            _cmd_land(["042", "--strategy"])

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "--strategy requires" in captured.err

    def test_invalid_strategy_value_exits_1(self, capsys):
        """--strategy rejects values other than merge or rebase."""
        from echelon.cli import _cmd_land

        with pytest.raises(SystemExit) as exc_info:
            _cmd_land(["042", "--strategy", "squash"])

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "--strategy must be" in captured.err

    def test_unknown_land_flag_exits_1(self, capsys):
        """Unknown land flags are rejected instead of silently ignored."""
        from echelon.cli import _cmd_land

        with pytest.raises(SystemExit) as exc_info:
            _cmd_land(["042", "--no-autresolve"])

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "unknown option" in captured.err.lower()
        assert "--no-autresolve" in captured.err

    def test_flag_shaped_first_arg_exits_1(self, capsys):
        """The spec id cannot be replaced by an option-like token."""
        from echelon.cli import _cmd_land

        with pytest.raises(SystemExit) as exc_info:
            _cmd_land(["--continue", "042"])

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "missing spec_id" in captured.err.lower()
        assert "--continue" in captured.err

    @patch("harness.land.land")
    @patch("harness.gitops.GitOpsManager")
    @patch("harness.config.load_config")
    def test_exit_code_0_on_success(
        self, mock_load_config, mock_gitops_cls, mock_land
    ):
        """Exit code 0 when land() returns True."""
        from echelon.cli import _cmd_land

        mock_load_config.return_value = MagicMock()
        mock_gitops_cls.return_value = MagicMock()
        mock_land.return_value = True

        with pytest.raises(SystemExit) as exc_info:
            _cmd_land(["042"])

        assert exc_info.value.code == 0

    @patch("harness.land.land")
    @patch("harness.gitops.GitOpsManager")
    @patch("harness.config.load_config")
    def test_exit_code_1_on_failure(
        self, mock_load_config, mock_gitops_cls, mock_land
    ):
        """Exit code 1 when land() returns False."""
        from echelon.cli import _cmd_land

        mock_load_config.return_value = MagicMock()
        mock_gitops_cls.return_value = MagicMock()
        mock_land.return_value = False

        with pytest.raises(SystemExit) as exc_info:
            _cmd_land(["042"])

        assert exc_info.value.code == 1

    @patch("harness.land.land")
    @patch("harness.gitops.GitOpsManager")
    @patch("harness.config.load_config")
    def test_prints_success_message(
        self, mock_load_config, mock_gitops_cls, mock_land, capsys
    ):
        """A success message is printed when land() returns True."""
        from echelon.cli import _cmd_land

        mock_load_config.return_value = MagicMock()
        mock_gitops_cls.return_value = MagicMock()
        mock_land.return_value = True

        with pytest.raises(SystemExit):
            _cmd_land(["042"])

        captured = capsys.readouterr()
        assert "042" in captured.out
        assert "landed" in captured.out.lower()

    @patch("harness.land.land")
    @patch("harness.gitops.GitOpsManager")
    @patch("harness.config.load_config")
    def test_prints_failure_message(
        self, mock_load_config, mock_gitops_cls, mock_land, capsys
    ):
        """A failure message is printed to stderr when land() returns False."""
        from echelon.cli import _cmd_land

        mock_load_config.return_value = MagicMock()
        mock_gitops_cls.return_value = MagicMock()
        mock_land.return_value = False

        with pytest.raises(SystemExit):
            _cmd_land(["042"])

        captured = capsys.readouterr()
        assert "042" in captured.err

    @patch("harness.land.land")
    @patch("harness.gitops.GitOpsManager")
    @patch("harness.config.load_config")
    def test_gitops_instantiated_with_config(
        self, mock_load_config, mock_gitops_cls, mock_land
    ):
        """GitOpsManager is instantiated with the loaded config."""
        from echelon.cli import _cmd_land

        mock_config = MagicMock()
        mock_load_config.return_value = mock_config
        mock_gitops_cls.return_value = MagicMock()
        mock_land.return_value = True

        with pytest.raises(SystemExit):
            _cmd_land(["099"])

        mock_gitops_cls.assert_called_once_with(mock_config)

    @patch("harness.land.land")
    @patch("harness.gitops.GitOpsManager")
    @patch("harness.config.load_config")
    def test_land_exception_propagates(
        self, mock_load_config, mock_gitops_cls, mock_land
    ):
        """If land() raises an exception, it propagates (not silently caught)."""
        from echelon.cli import _cmd_land

        mock_load_config.return_value = MagicMock()
        mock_gitops_cls.return_value = MagicMock()
        mock_land.side_effect = RuntimeError("unexpected")

        with pytest.raises(RuntimeError, match="unexpected"):
            _cmd_land(["042"])

    def test_no_args_shows_help(self, capsys):
        """Calling land with no arguments shows help and exits 0."""
        from echelon.cli import _cmd_land

        with pytest.raises(SystemExit) as exc_info:
            _cmd_land([])

        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        self._assert_help_mentions_autonomous_land_flags(captured.out)

    @pytest.mark.parametrize("flag", ["-h", "--help"])
    def test_help_flag_shows_help(self, flag, capsys):
        """Calling land with -h or --help shows help and exits 0."""
        from echelon.cli import _cmd_land

        with pytest.raises(SystemExit) as exc_info:
            _cmd_land([flag])

        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        self._assert_help_mentions_autonomous_land_flags(captured.out)

    @patch("harness.config.load_config")
    def test_config_validation_error_exits_1(self, mock_load_config, capsys):
        """If load_config() raises ValidationError, exit 1 with user-friendly message."""
        from harness.config import ValidationError as HarnessValidationError
        from echelon.cli import _cmd_land

        mock_load_config.side_effect = HarnessValidationError("bad config")

        with pytest.raises(SystemExit) as exc_info:
            _cmd_land(["042"])

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "config error" in captured.err.lower()
