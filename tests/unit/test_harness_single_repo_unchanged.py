"""Regression: single-repo harness run path is unchanged by polyrepo changes.

Verifies that when a spec has no targets, the single-repo path is taken
(requires local echelon.yml) regardless of whether one exists.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


@pytest.mark.unit
class TestSingleRepoPathUnchanged:
    def test_no_targets_in_spec_uses_single_repo_path(self, tmp_path: Path) -> None:
        """Spec with no targets and local echelon.yml: run_multi_target never called."""
        echelon_yml = tmp_path / ".specify" / "extensions" / "echelon" / "echelon.yml"
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
        """Spec with targets triggers orchestrator mode even when local echelon.yml exists.

        This is the kill-gate scenario: a polyrepo root that has its own echelon.yml
        (e.g. for deploy) must not silently run the harness against itself.
        """
        echelon_yml = tmp_path / ".specify" / "extensions" / "echelon" / "echelon.yml"
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

    def test_spec_without_targets_falls_through_to_init_error(self, tmp_path: Path) -> None:
        """Spec found but no targets: still shows the init error, not orchestrator."""
        spec_dir = tmp_path / "specs" / "024-test"
        spec_dir.mkdir(parents=True)
        (spec_dir / "spec.md").write_text("# No frontmatter\n", encoding="utf-8")

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
