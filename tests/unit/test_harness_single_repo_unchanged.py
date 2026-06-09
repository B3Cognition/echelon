"""Regression: single-repo harness run path is unchanged by polyrepo changes.

Verifies that when a spec has no targets, the single-repo path is taken
(requires local echelon-config.yml) regardless of whether one exists.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


@pytest.mark.unit
class TestSingleRepoPathUnchanged:
    def test_no_targets_in_spec_uses_single_repo_path(self, tmp_path: Path) -> None:
        """Spec with no targets and local echelon-config.yml: run_multi_target never called."""
        echelon_yml = tmp_path / ".specify" / "extensions" / "echelon" / "echelon-config.yml"
        echelon_yml.parent.mkdir(parents=True)
        echelon_yml.write_text("harness:\n  target_repo: .\n", encoding="utf-8")

        spec_dir = tmp_path / "specs" / "024-test"
        spec_dir.mkdir(parents=True)
        (spec_dir / "spec.md").write_text("# No targets\n", encoding="utf-8")

        with patch("echelon.orchestrator.run_multi_target") as mock_orch:
            with patch("harness.config.load_config") as mock_cfg:
                mock_cfg.return_value = MagicMock(buffer_limit_bytes=1024 * 1024)
                with patch("harness.gitops.GitOpsManager"):
                    with patch("harness.docker_provider.DockerWorktreeProvider"):
                        with patch("harness.skills.run_skill.run"):
                            import os
                            orig = os.getcwd()
                            try:
                                os.chdir(tmp_path)
                                from echelon.cli import _cmd_harness_run
                                try:
                                    _cmd_harness_run(["024"])
                                except SystemExit:
                                    pass
                            finally:
                                os.chdir(orig)
            mock_orch.assert_not_called()

    def test_targets_in_spec_triggers_orchestrator_even_with_local_echelon_yml(
        self, tmp_path: Path
    ) -> None:
        """Spec with targets triggers orchestrator mode even when local echelon-config.yml exists.

        This is the kill-gate scenario: a polyrepo root that has its own echelon-config.yml
        (e.g. for deploy) must not silently run the harness against itself.
        """
        echelon_yml = tmp_path / ".specify" / "extensions" / "echelon" / "echelon-config.yml"
        echelon_yml.parent.mkdir(parents=True)
        echelon_yml.write_text("harness:\n  target_repo: .\n", encoding="utf-8")

        spec_dir = tmp_path / "specs" / "024-test"
        spec_dir.mkdir(parents=True)
        (spec_dir / "spec.md").write_text(
            "---\ntargets:\n  - repo-a\n---\n# spec\n", encoding="utf-8"
        )

        import os
        orig = os.getcwd()
        try:
            os.chdir(tmp_path)
            from echelon.cli import _cmd_harness_run
            with pytest.raises(SystemExit) as exc:
                _cmd_harness_run(["024"])
            # validate_targets exits 1 because repo-a doesn't exist
            assert exc.value.code == 1
        finally:
            os.chdir(orig)

    def test_target_side_polyrepo_run_does_not_recurse_to_orchestrator(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """run_multi_target dispatches into the target; that child run must build locally."""
        polyrepo = tmp_path / "wrapper"
        target = polyrepo / "repo-a"
        target.mkdir(parents=True)
        (target / ".git").mkdir()
        echelon_yml = polyrepo / ".specify" / "extensions" / "echelon" / "echelon-config.yml"
        echelon_yml.parent.mkdir(parents=True)
        echelon_yml.write_text(
            "harness:\n  target_repo: .\n  target_default_branch: main\n  provider: docker\n",
            encoding="utf-8",
        )
        (echelon_yml.parent / "agents" / "control").mkdir(parents=True)
        (echelon_yml.parent / "agents" / "control" / "commander.md").write_text(
            "# Commander\n",
            encoding="utf-8",
        )
        (echelon_yml.parent / "workflow").mkdir(parents=True)
        (echelon_yml.parent / "workflow" / "definition.yaml").write_text(
            "phases: []\n",
            encoding="utf-8",
        )

        spec_dir = polyrepo / "specs" / "024-test"
        spec_dir.mkdir(parents=True)
        (spec_dir / "spec.md").write_text(
            "---\ntargets:\n  - repo-a\n---\n# spec\n",
            encoding="utf-8",
        )
        (spec_dir / "tasks.md").write_text(
            "- [ ] T-001 complexity=standard phase=build req=FR-001 depends=none\n",
            encoding="utf-8",
        )

        monkeypatch.setenv("ECHELON_POLYREPO_ROOT", str(polyrepo))
        monkeypatch.setenv("ECHELON_TARGET_REPO_PATH", str(target))
        monkeypatch.setenv("ECHELON_TARGET_REPO_NAME", "repo-a")

        import os

        orig = os.getcwd()
        try:
            os.chdir(target)
            from echelon.cli import _cmd_harness_run
            with patch("echelon.orchestrator.run_multi_target") as mock_orch:
                with patch("harness.config.load_config") as mock_cfg:
                    mock_cfg.return_value = MagicMock(
                        buffer_limit_bytes=1024 * 1024,
                        target_repo=".",
                        target_default_branch="main",
                    )
                    with patch("harness.gitops.GitOpsManager") as MockGitOps:
                        mock_gitops = MagicMock()
                        MockGitOps.return_value = mock_gitops
                        with patch("harness.docker_provider.DockerWorktreeProvider"):
                            with patch("harness.skills.run_skill.run") as mock_run:
                                _cmd_harness_run(["024-test"])
        finally:
            os.chdir(orig)

        mock_orch.assert_not_called()
        mock_run.assert_called_once()
        assert mock_cfg.call_args.kwargs["project_root"] == polyrepo
        assert mock_run.call_args.kwargs["base_dir"] == str(
            polyrepo / "runs" / "targets" / "repo-a"
        )
        assert mock_run.call_args.kwargs["config"].target_repo == str(target.resolve())
        mock_gitops.clone_mirror.assert_called_once_with(str(target.resolve()))

    def test_spec_without_targets_in_polyrepo_blocks_before_wrapper_harness(
        self, tmp_path: Path, capsys
    ) -> None:
        spec_dir = tmp_path / "specs" / "024-test"
        spec_dir.mkdir(parents=True)
        (spec_dir / "spec.md").write_text("# Wrapper spec\n", encoding="utf-8")
        (spec_dir / "tasks.md").write_text("Fix `src/service.ts`\n", encoding="utf-8")

        for name in ["repo-a", "repo-b"]:
            repo = tmp_path / name
            (repo / ".git").mkdir(parents=True)

        import os
        orig = os.getcwd()
        try:
            os.chdir(tmp_path)
            from echelon.cli import _cmd_harness_run
            with pytest.raises(SystemExit) as exc:
                _cmd_harness_run(["024"])
            assert exc.value.code == 1
        finally:
            os.chdir(orig)

        err = capsys.readouterr().err
        assert "No implementation target configured" in err
        assert "echelon spec target" in err

    def test_find_spec_dir_local_takes_precedence(self, tmp_path: Path) -> None:
        """Local spec shadows parent-level spec of same id."""
        from harness.spec_frontmatter import find_spec_dir

        parent_spec = tmp_path / "specs" / "024-parent"
        parent_spec.mkdir(parents=True)
        (parent_spec / "spec.md").write_text("# parent\n", encoding="utf-8")

        child = tmp_path / "repo-a"
        local_spec = child / "specs" / "024-local"
        local_spec.mkdir(parents=True)
        (local_spec / "spec.md").write_text("# local\n", encoding="utf-8")

        result = find_spec_dir("024", child)
        assert result == local_spec
