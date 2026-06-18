"""Tests for _cmd_harness_run argument parsing in cli.py.

Covers the free-text task description capture introduced to fix the bug
where 'echelon harness run 013 strategy=codegen "do X"' silently dropped "do X".
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from echelon.workspace_model import WorkspaceInfo, WorkspaceManifest
from harness.phase_a_readiness import REQUIRED_PHASE_A_BUILD_INPUTS
from harness.run_intent import parse_intent


VALID_PLAN = """# Implementation Plan: Demo

## Summary
Demo.

## Technical Context
Python.

## Architecture Decisions
- ADR-001: Keep it simple.

## Project Structure
```text
src/
```

## Implementation Phases
- Foundation.

## Testing Strategy
- Unit tests.

## Risks
- None.

## Constitution Check
| Principle | Compliance |
| --- | --- |
| Local-first | PASS |
"""


def _write_phase_a_build_inputs(spec_dir: Path) -> None:
    spec_dir.mkdir(parents=True, exist_ok=True)
    for name in REQUIRED_PHASE_A_BUILD_INPUTS:
        if name == "plan.md":
            content = VALID_PLAN
        elif name == "tasks.md":
            content = "- [ ] T-001 complexity=standard phase=foundation req=INFRA depends=none\n"
        elif name == "constitution.md":
            content = "# Constitution\n\nReal project rules.\n"
        else:
            content = f"# {name}\n"
        (spec_dir / name).write_text(content, encoding="utf-8")


@pytest.fixture(autouse=True)
def _git_backed_workspace(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()


@pytest.mark.unit
class TestHarnessRunArgParsing:
    """Verify the user_message built by _cmd_harness_run reaches parse_intent correctly."""

    def _build_user_message(self, args: list[str]) -> str:
        """Replicate the user_message construction logic from _cmd_harness_run."""
        spec_id = args[0]
        kv: dict[str, str] = {}
        free_text: list[str] = []
        for arg in args[1:]:
            if "=" in arg:
                k, _, v = arg.partition("=")
                kv[k.strip()] = v.strip()
            else:
                free_text.append(arg)
        strategy = kv.get("strategy", "default")
        mode = kv.get("mode", "semi")
        parts = [f"spec {spec_id}", f"{mode} mode", f"strategies={strategy}"]
        if free_text:
            parts.append(f"task: {' '.join(free_text)}")
        return " ".join(parts)

    def test_free_text_becomes_task_description(self) -> None:
        """Free-text arg is forwarded as task_description through parse_intent."""
        msg = self._build_user_message(
            ["013", "strategy=codegen", "fix the bug as described in 'bugfix-1.md'"]
        )
        intent = parse_intent(msg)
        assert intent.task_description == "fix the bug as described in 'bugfix-1.md'"
        assert intent.spec_id == "013"
        assert intent.strategies == ["codegen"]

    def test_no_free_text_gives_empty_task_description(self) -> None:
        """When only kv args are given, task_description is empty."""
        msg = self._build_user_message(["013", "strategy=codegen"])
        intent = parse_intent(msg)
        assert intent.task_description == ""

    def test_multiple_free_text_words_joined(self) -> None:
        """Multiple free-text tokens are joined into a single task_description."""
        msg = self._build_user_message(["013", "implement", "feature", "X"])
        intent = parse_intent(msg)
        assert intent.task_description == "implement feature X"

    def test_kv_args_not_leaked_into_task(self) -> None:
        """key=value pairs are not included in task_description."""
        msg = self._build_user_message(["013", "mode=banzai", "strategy=default", "do the thing"])
        intent = parse_intent(msg)
        assert intent.task_description == "do the thing"
        assert intent.mode == "banzai"
        assert "mode=banzai" not in intent.task_description


@pytest.mark.unit
class TestHarnessRunTaskFormatErrors:
    def test_branchless_harness_run_blocks_with_full_rerun_command(
        self,
        tmp_path: Path,
        monkeypatch,
        capsys,
    ) -> None:
        (tmp_path / ".git").rmdir()
        source = tmp_path / "og-platform"
        source.mkdir()
        (source / ".git").mkdir()
        (source / "package.json").write_text("{}", encoding="utf-8")
        monkeypatch.chdir(tmp_path)

        from echelon.cli import _cmd_harness_run

        with pytest.raises(SystemExit) as exc:
            _cmd_harness_run(["003", "mode=banzai", "strategy=soar", "finish slice"])

        assert exc.value.code == 2
        err = capsys.readouterr().err
        assert "workspace root is not a Git repo" in err
        assert "echelon harness run 003 mode=banzai strategy=soar 'finish slice'" in err

    def test_harness_run_snapshots_spec_before_preflight_exit(
        self,
        tmp_path: Path,
        monkeypatch,
        capsys,
    ) -> None:
        spec_dir = tmp_path / "specs" / "003-test"
        spec_dir.mkdir(parents=True)
        (spec_dir / "spec.md").write_text("# Spec\n", encoding="utf-8")
        (spec_dir / "tasks.md").write_text(
            "- [ ] T-001 complexity=standard phase=foundation req=INFRA depends=none\n",
            encoding="utf-8",
        )

        monkeypatch.chdir(tmp_path)

        from echelon.cli import _cmd_harness_run

        with pytest.raises(SystemExit) as exc:
            _cmd_harness_run(["003"])

        assert exc.value.code == 1
        capsys.readouterr()
        snapshots = list((tmp_path / "runs" / "spec-snapshots").glob("003-test-*"))
        assert len(snapshots) == 1
        assert (snapshots[0] / "spec" / "spec.md").read_text(encoding="utf-8") == "# Spec\n"
        assert (snapshots[0] / "spec" / "tasks.md").exists()
        manifest = snapshots[0] / "snapshot.json"
        assert manifest.exists()

    def test_old_task_format_exits_with_migration_guidance(
        self,
        tmp_path: Path,
        monkeypatch,
        capsys,
    ) -> None:
        echelon_yml = tmp_path / ".specify" / "extensions" / "echelon" / "echelon-config.yml"
        echelon_yml.parent.mkdir(parents=True)
        echelon_yml.write_text("harness:\n  target_repo: .\n", encoding="utf-8")
        (tmp_path / "package.json").write_text("{}\n", encoding="utf-8")

        mirror = tmp_path / "runs" / "mirror.git"
        mirror.mkdir(parents=True)

        spec_dir = tmp_path / "specs" / "003-test"
        spec_dir.mkdir(parents=True)
        (spec_dir / "spec.md").write_text("# Spec\n", encoding="utf-8")
        (spec_dir / "tasks.md").write_text("### T-001: Legacy task\n", encoding="utf-8")

        monkeypatch.chdir(tmp_path)

        with patch("harness.config.load_config") as mock_cfg, \
             patch("harness.paths.mirror_path", return_value=mirror), \
             patch("harness.gitops.GitOpsManager"), \
             patch("harness.docker_provider.DockerWorktreeProvider"), \
             patch("harness.skills.run_skill.run") as mock_run:
            mock_cfg.return_value = MagicMock(buffer_limit_bytes=1024 * 1024, target_repo=".")
            from echelon.cli import _cmd_harness_run

            with pytest.raises(SystemExit) as exc:
                _cmd_harness_run(["003"])

        assert exc.value.code == 1
        mock_run.assert_not_called()
        err = capsys.readouterr().err
        assert "tasks.md is not in canonical format" in err
        assert "no canonical task rows found" in err
        assert "python -m harness migrate-tasks" in err
        assert "--write" in err

    def test_old_task_format_preserves_full_rerun_command(
        self,
        tmp_path: Path,
        monkeypatch,
        capsys,
    ) -> None:
        echelon_yml = tmp_path / ".specify" / "extensions" / "echelon" / "echelon-config.yml"
        echelon_yml.parent.mkdir(parents=True)
        echelon_yml.write_text("harness:\n  target_repo: .\n", encoding="utf-8")
        (tmp_path / "package.json").write_text("{}\n", encoding="utf-8")

        mirror = tmp_path / "runs" / "mirror.git"
        mirror.mkdir(parents=True)

        spec_dir = tmp_path / "specs" / "003-test"
        spec_dir.mkdir(parents=True)
        (spec_dir / "spec.md").write_text("# Spec\n", encoding="utf-8")
        (spec_dir / "tasks.md").write_text("### T-001: Legacy task\n", encoding="utf-8")

        monkeypatch.chdir(tmp_path)

        with patch("harness.config.load_config") as mock_cfg, \
             patch("harness.paths.mirror_path", return_value=mirror), \
             patch("harness.gitops.GitOpsManager"), \
             patch("harness.docker_provider.DockerWorktreeProvider"), \
             patch("harness.skills.run_skill.run") as mock_run:
            mock_cfg.return_value = MagicMock(buffer_limit_bytes=1024 * 1024, target_repo=".")
            from echelon.cli import _cmd_harness_run

            with pytest.raises(SystemExit):
                _cmd_harness_run(["003", "mode=banzai", "strategy=soar", "finish slice"])

        mock_run.assert_not_called()
        err = capsys.readouterr().err
        assert "echelon harness run 003 mode=banzai strategy=soar 'finish slice'" in err

    def test_invalid_plan_format_exits_with_migration_guidance(
        self,
        tmp_path: Path,
        monkeypatch,
        capsys,
    ) -> None:
        echelon_yml = tmp_path / ".specify" / "extensions" / "echelon" / "echelon-config.yml"
        echelon_yml.parent.mkdir(parents=True)
        echelon_yml.write_text("harness:\n  target_repo: .\n", encoding="utf-8")
        (tmp_path / "package.json").write_text("{}\n", encoding="utf-8")

        mirror = tmp_path / "runs" / "mirror.git"
        mirror.mkdir(parents=True)

        spec_dir = tmp_path / "specs" / "003-test"
        spec_dir.mkdir(parents=True)
        (spec_dir / "spec.md").write_text("# Spec\n", encoding="utf-8")
        (spec_dir / "tasks.md").write_text(
            "- [ ] T-001 complexity=standard phase=foundation req=INFRA depends=none\n",
            encoding="utf-8",
        )
        (spec_dir / "plan.md").write_text("# Plan\n\n## Summary\n", encoding="utf-8")

        monkeypatch.chdir(tmp_path)

        with patch("harness.config.load_config") as mock_cfg, \
             patch("harness.paths.mirror_path", return_value=mirror), \
             patch("harness.gitops.GitOpsManager"), \
             patch("harness.docker_provider.DockerWorktreeProvider"), \
             patch("harness.skills.run_skill.run") as mock_run:
            mock_cfg.return_value = MagicMock(buffer_limit_bytes=1024 * 1024, target_repo=".")
            from echelon.cli import _cmd_harness_run

            with pytest.raises(SystemExit) as exc:
                _cmd_harness_run(["003"])

        assert exc.value.code == 1
        mock_run.assert_not_called()
        err = capsys.readouterr().err
        assert "plan.md is not in canonical format" in err
        assert "python -m harness migrate-plan" in err
        assert "--write" in err

    def test_docker_unavailable_exits_with_actionable_message(
        self,
        tmp_path: Path,
        monkeypatch,
        capsys,
    ) -> None:
        echelon_yml = tmp_path / ".specify" / "extensions" / "echelon" / "echelon-config.yml"
        echelon_yml.parent.mkdir(parents=True)
        echelon_yml.write_text("harness:\n  target_repo: .\n", encoding="utf-8")
        (tmp_path / "package.json").write_text("{}\n", encoding="utf-8")

        mirror = tmp_path / "runs" / "mirror.git"
        mirror.mkdir(parents=True)

        spec_dir = tmp_path / "specs" / "003-test"
        _write_phase_a_build_inputs(spec_dir)

        monkeypatch.chdir(tmp_path)

        from harness.errors import SandboxExecError

        with patch("harness.config.load_config") as mock_cfg, \
             patch("harness.paths.mirror_path", return_value=mirror), \
             patch("harness.gitops.GitOpsManager"), \
             patch("harness.docker_provider.DockerWorktreeProvider"), \
             patch("harness.skills.run_skill.run") as mock_run:
            mock_cfg.return_value = MagicMock(buffer_limit_bytes=1024 * 1024, target_repo=".")
            mock_run.side_effect = SandboxExecError(
                "Docker command failed: docker network create: failed to connect "
                "to the docker API at unix:///Users/me/.docker/run/docker.sock; "
                "check if the path is correct and if the daemon is running"
            )
            from echelon.cli import _cmd_harness_run

            with pytest.raises(SystemExit) as exc:
                _cmd_harness_run(["003"])

        assert exc.value.code == 1
        err = capsys.readouterr().err
        assert "Docker is not running" in err
        assert "start Docker" in err
        assert "echelon harness run 003" in err
        assert "Traceback" not in err

    def test_placeholder_constitution_blocks_before_harness_dispatch(
        self,
        tmp_path: Path,
        monkeypatch,
        capsys,
    ) -> None:
        echelon_yml = tmp_path / ".specify" / "extensions" / "echelon" / "echelon-config.yml"
        echelon_yml.parent.mkdir(parents=True)
        echelon_yml.write_text("harness:\n  target_repo: .\n", encoding="utf-8")
        (tmp_path / "package.json").write_text("{}\n", encoding="utf-8")

        mirror = tmp_path / "runs" / "mirror.git"
        mirror.mkdir(parents=True)

        spec_dir = tmp_path / "specs" / "003-test"
        _write_phase_a_build_inputs(spec_dir)
        (spec_dir / "constitution.md").write_text(
            "# Constitution\n\nProject: [PROJECT_NAME]\n",
            encoding="utf-8",
        )

        monkeypatch.chdir(tmp_path)

        with patch("harness.config.load_config") as mock_cfg, \
             patch("harness.paths.mirror_path", return_value=mirror), \
             patch("harness.gitops.GitOpsManager"), \
             patch("harness.docker_provider.DockerWorktreeProvider"), \
             patch("harness.skills.run_skill.run") as mock_run:
            mock_cfg.return_value = MagicMock(buffer_limit_bytes=1024 * 1024, target_repo=".")
            from echelon.cli import _cmd_harness_run

            with pytest.raises(SystemExit) as exc:
                _cmd_harness_run(["003"])

        assert exc.value.code == 1
        mock_run.assert_not_called()
        err = capsys.readouterr().err
        assert "Phase A build inputs are not ready" in err
        assert "constitution.md contains unresolved template markers" in err
        assert "echelon continue" in err


@pytest.mark.unit
class TestHarnessTargetPreflight:
    def test_semi_mode_recommends_detected_target_and_stops(
        self,
        tmp_path: Path,
        monkeypatch,
        capsys,
    ) -> None:
        root = tmp_path
        echelon_yml = root / ".specify" / "extensions" / "echelon" / "echelon-config.yml"
        echelon_yml.parent.mkdir(parents=True)
        echelon_yml.write_text("harness:\n  target_repo: .\n", encoding="utf-8")

        spec_dir = root / "specs" / "001-opta-points-perf-fix"
        spec_dir.mkdir(parents=True)
        (spec_dir / "spec.md").write_text("# OptaPoints\n", encoding="utf-8")
        (spec_dir / "tasks.md").write_text(
            "- [ ] T-002 complexity=complex phase=foundation req=FR-001 depends=none "
            "Fix `src/lib/sdapi/services/shared-promise.ts`\n",
            encoding="utf-8",
        )

        target = root / "rbf-opta-points"
        (target / ".git").mkdir(parents=True)
        (target / "src/lib/sdapi/services").mkdir(parents=True)
        (target / "src/lib/sdapi/services/shared-promise.ts").write_text(
            "export {}\n",
            encoding="utf-8",
        )
        other = root / "qag-load-testing-framework"
        (other / ".git").mkdir(parents=True)

        monkeypatch.chdir(root)
        from echelon import target_detection

        monkeypatch.setattr(
            target_detection,
            "discover_workspace",
            lambda _: WorkspaceManifest(
                schema_version=1,
                workspace=WorkspaceInfo(
                    root=root.resolve(),
                    git_role="orchestration",
                    git_present=False,
                ),
                sources=(),
            ),
        )
        from echelon.cli import _cmd_harness_run

        with pytest.raises(SystemExit) as exc:
            _cmd_harness_run(["001", "mode=semi"])

        assert exc.value.code == 1
        err = capsys.readouterr().err
        assert "Recommended implementation target: rbf-opta-points" in err
        assert "echelon spec target 001-opta-points-perf-fix rbf-opta-points" in err

    def test_banzai_mode_writes_detected_target_and_dispatches(
        self,
        tmp_path: Path,
        monkeypatch,
    ) -> None:
        root = tmp_path
        spec_dir = root / "specs" / "001-opta-points-perf-fix"
        _write_phase_a_build_inputs(spec_dir)
        (spec_dir / "spec.md").write_text("# OptaPoints\n", encoding="utf-8")
        (spec_dir / "tasks.md").write_text(
            "Fix `src/lib/sdapi/services/shared-promise.ts`\n",
            encoding="utf-8",
        )

        target = root / "rbf-opta-points"
        (target / ".git").mkdir(parents=True)
        yml = target / ".specify" / "extensions" / "echelon" / "echelon-config.yml"
        yml.parent.mkdir(parents=True)
        yml.write_text("harness:\n  target_repo: .\n", encoding="utf-8")
        (target / "src/lib/sdapi/services").mkdir(parents=True)
        (target / "src/lib/sdapi/services/shared-promise.ts").write_text(
            "export {}\n",
            encoding="utf-8",
        )

        other = root / "qag-load-testing-framework"
        (other / ".git").mkdir(parents=True)

        monkeypatch.chdir(root)
        from echelon import target_detection
        from echelon.cli import _cmd_harness_run
        from harness.spec_frontmatter import read_frontmatter

        monkeypatch.setattr(
            target_detection,
            "discover_workspace",
            lambda _: WorkspaceManifest(
                schema_version=1,
                workspace=WorkspaceInfo(
                    root=root.resolve(),
                    git_role="orchestration",
                    git_present=False,
                ),
                sources=(),
            ),
        )
        with patch("echelon.orchestrator.run_multi_target", return_value=0) as mock_run:
            with pytest.raises(SystemExit) as exc:
                _cmd_harness_run(["001", "mode=banzai"])

        assert exc.value.code == 0
        assert read_frontmatter(spec_dir)["targets"] == ["rbf-opta-points"]
        mock_run.assert_called_once()

    def test_multiple_workspace_source_roots_stop_before_workspace_config(
        self,
        tmp_path: Path,
        monkeypatch,
        capsys,
    ) -> None:
        root = tmp_path
        echelon_yml = root / ".specify" / "extensions" / "echelon" / "echelon-config.yml"
        echelon_yml.parent.mkdir(parents=True)
        echelon_yml.write_text("harness:\n  target_repo: .\n", encoding="utf-8")

        spec_dir = root / "specs" / "001-feature"
        spec_dir.mkdir(parents=True)
        (spec_dir / "spec.md").write_text("# Feature\n", encoding="utf-8")
        (spec_dir / "tasks.md").write_text(
            "- [ ] T-001 complexity=standard phase=foundation req=FR-001 depends=none\n",
            encoding="utf-8",
        )

        for name in ["og-platform", "pbg-api"]:
            source = root / name
            (source / ".git").mkdir(parents=True)
            (source / "package.json").write_text("{}\n", encoding="utf-8")

        monkeypatch.chdir(root)
        from echelon.cli import _cmd_harness_run

        with patch("harness.config.load_config") as mock_load_config:
            with pytest.raises(SystemExit) as exc:
                _cmd_harness_run(["001", "mode=banzai"])

        assert exc.value.code == 1
        mock_load_config.assert_not_called()
        err = capsys.readouterr().err
        assert "Multiple source roots found" in err
        assert "og-platform" in err
        assert "pbg-api" in err
        assert "echelon spec target 001-feature <source-root>" in err

    def test_no_workspace_source_roots_stop_before_workspace_config(
        self,
        tmp_path: Path,
        monkeypatch,
        capsys,
    ) -> None:
        root = tmp_path
        echelon_yml = root / ".specify" / "extensions" / "echelon" / "echelon-config.yml"
        echelon_yml.parent.mkdir(parents=True)
        echelon_yml.write_text("harness:\n  target_repo: .\n", encoding="utf-8")

        spec_dir = root / "specs" / "001-feature"
        spec_dir.mkdir(parents=True)
        (spec_dir / "spec.md").write_text("# Feature\n", encoding="utf-8")
        (spec_dir / "tasks.md").write_text(
            "- [ ] T-001 complexity=standard phase=foundation req=FR-001 depends=none\n",
            encoding="utf-8",
        )

        monkeypatch.chdir(root)
        from echelon.cli import _cmd_harness_run

        with patch("harness.config.load_config") as mock_load_config:
            with pytest.raises(SystemExit) as exc:
                _cmd_harness_run(["001"])

        assert exc.value.code == 1
        mock_load_config.assert_not_called()
        err = capsys.readouterr().err
        assert "No source roots found" in err
