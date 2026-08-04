"""Tests for _cmd_harness_run argument parsing in cli.py.

Covers the free-text task description capture introduced to fix the bug
where 'echelon delivery run 013 strategy=codegen "do X"' silently dropped "do X".
"""

from __future__ import annotations

import json
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

## Requirement Preservation
| Requirement | Product Invariant | Architecture Decision | Preserves? | Evidence |
| --- | --- | --- | --- | --- |
| INFRA | Delivery remains stable. | ADR-001 | yes | Covered by harness tests. |

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


SPEC_WITH_LOCAL_TARGET = "---\ntargets:\n  - .\n---\n# Spec\n"


def _write_phase_a_build_inputs(spec_dir: Path) -> None:
    spec_dir.mkdir(parents=True, exist_ok=True)
    for name in REQUIRED_PHASE_A_BUILD_INPUTS:
        if name == "plan.md":
            content = VALID_PLAN
        elif name == "tasks.md":
            content = "- [ ] T-001 complexity=standard phase=foundation req=INFRA depends=none target=.\n"
        elif name == "constitution.md":
            content = "# Constitution\n\nReal project rules.\n"
        elif name == "spec.md":
            content = SPEC_WITH_LOCAL_TARGET
        elif name == "plan-conformance.json":
            content = (
                '{\n'
                '  "status": "pass",\n'
                '  "findings": [],\n'
                '  "sources": ["spec.md", "requirements-overview.md", "plan.md", "tasks.md"]\n'
                '}\n'
            )
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
    def test_delivery_blocks_before_dispatch_when_tasks_reference_other_repos(
        self,
        tmp_path: Path,
        capsys,
    ) -> None:
        spec_dir = tmp_path / "specs" / "001-dashboard"
        spec_dir.mkdir(parents=True)
        (spec_dir / "tasks.md").write_text(
            "- [ ] T-001 complexity=standard phase=api req=FR-001 depends=none target=sources/api\n\n"
            "  **Files:**\n"
            "  - `sources/api/src/dashboard.ts` — backend\n\n"
            "- [ ] T-002 complexity=standard phase=web req=FR-002 depends=T-001 target=sources/web\n\n"
            "  **Files:**\n"
            "  - `sources/web/src/dashboard.tsx` — frontend\n\n"
            "- [ ] T-003 complexity=standard phase=test req=INFRA depends=T-002\n\n"
            "  **Files:**\n"
            "  - `e2e/dashboard.spec.ts` — unspecified target\n",
            encoding="utf-8",
        )

        from echelon.cli import _block_if_spec_task_targets_mismatch

        with pytest.raises(SystemExit) as exc:
            _block_if_spec_task_targets_mismatch(
                spec_dir,
                ["sources/selected-web"],
                "001-dashboard",
            )

        assert exc.value.code == 2
        err = capsys.readouterr().err
        assert "Task ownership does not match the spec delivery targets" in err
        assert "declared: sources/selected-web" in err
        assert "missing targets: sources/api, sources/web" in err
        assert "unreferenced targets: sources/selected-web" in err
        assert "tasks without explicit target= ownership: T-003" in err
        assert "Regenerate target-dependent plan/tasks artifacts" in err

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
        assert "echelon delivery run 003 mode=banzai strategy=soar 'finish slice'" in err

    def test_harness_run_snapshots_spec_before_preflight_exit(
        self,
        tmp_path: Path,
        monkeypatch,
        capsys,
    ) -> None:
        spec_dir = tmp_path / "specs" / "003-test"
        spec_dir.mkdir(parents=True)
        (spec_dir / "spec.md").write_text(SPEC_WITH_LOCAL_TARGET, encoding="utf-8")
        (spec_dir / "tasks.md").write_text(
            "- [ ] T-001 complexity=standard phase=foundation req=INFRA depends=none target=.\n",
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
        assert (snapshots[0] / "spec" / "spec.md").read_text(encoding="utf-8") == SPEC_WITH_LOCAL_TARGET
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
        (spec_dir / "spec.md").write_text(SPEC_WITH_LOCAL_TARGET, encoding="utf-8")
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
        (spec_dir / "spec.md").write_text(SPEC_WITH_LOCAL_TARGET, encoding="utf-8")
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
        assert "echelon delivery run 003 mode=banzai strategy=soar 'finish slice'" in err

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
        (spec_dir / "spec.md").write_text(SPEC_WITH_LOCAL_TARGET, encoding="utf-8")
        (spec_dir / "tasks.md").write_text(
            "- [ ] T-001 complexity=standard phase=foundation req=INFRA depends=none target=.\n",
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
        assert "echelon delivery run 003" in err
        assert "Traceback" not in err

    def test_harness_run_accepts_canonical_workspace_config(
        self,
        tmp_path: Path,
        monkeypatch,
    ) -> None:
        config_file = tmp_path / ".echelon" / "config.yml"
        config_file.parent.mkdir(parents=True)
        config_file.write_text("harness:\n  target_repo: .\n", encoding="utf-8")
        (tmp_path / "package.json").write_text("{}\n", encoding="utf-8")

        mirror = tmp_path / "runs" / "mirror.git"
        mirror.mkdir(parents=True)

        spec_dir = tmp_path / "specs" / "003-test"
        _write_phase_a_build_inputs(spec_dir)

        monkeypatch.chdir(tmp_path)

        with patch("harness.config.load_config") as mock_cfg, \
             patch("harness.paths.mirror_path", return_value=mirror), \
             patch("harness.gitops.GitOpsManager"), \
             patch("harness.docker_provider.DockerWorktreeProvider"), \
             patch("harness.skills.run_skill.run") as mock_run:
            mock_cfg.return_value = MagicMock(buffer_limit_bytes=1024 * 1024, target_repo=".")
            from echelon.cli import _cmd_harness_run

            _cmd_harness_run(["003"])

        mock_run.assert_called_once()

    def test_delivery_preparation_refuses_active_spec_mutation_lock(
        self,
        tmp_path: Path,
        monkeypatch,
        capsys,
    ) -> None:
        config_file = tmp_path / ".echelon" / "config.yml"
        config_file.parent.mkdir(parents=True)
        config_file.write_text("harness:\n  target_repo: .\n", encoding="utf-8")
        (tmp_path / "package.json").write_text("{}\n", encoding="utf-8")
        mirror = tmp_path / "runs" / "mirror.git"
        mirror.mkdir(parents=True)
        spec_dir = tmp_path / "specs" / "003-test"
        _write_phase_a_build_inputs(spec_dir)
        monkeypatch.chdir(tmp_path)

        from echelon.cli import _cmd_harness_run
        from echelon.spec_lifecycle import SpecMutationLock

        with patch("harness.config.load_config") as mock_cfg, \
             patch("harness.paths.mirror_path", return_value=mirror), \
             patch("harness.gitops.GitOpsManager"), \
             patch("harness.docker_provider.DockerWorktreeProvider"), \
             patch("harness.skills.run_skill.run") as mock_run:
            mock_cfg.return_value = MagicMock(
                buffer_limit_bytes=1024 * 1024,
                target_repo=".",
            )
            with SpecMutationLock.acquire(tmp_path, "003-test", "retarget-held"):
                with pytest.raises(SystemExit) as exc:
                    _cmd_harness_run(["003"])

        assert exc.value.code == 1
        mock_run.assert_not_called()
        assert "spec mutation" in capsys.readouterr().err.lower()
        assert not list((tmp_path / "runs").glob("build-*"))

    def test_delivery_releases_mutation_lock_after_durable_phase_b_evidence(
        self,
        tmp_path: Path,
        monkeypatch,
    ) -> None:
        config_file = tmp_path / ".echelon" / "config.yml"
        config_file.parent.mkdir(parents=True)
        config_file.write_text("harness:\n  target_repo: .\n", encoding="utf-8")
        (tmp_path / "package.json").write_text("{}\n", encoding="utf-8")
        mirror = tmp_path / "runs" / "mirror.git"
        mirror.mkdir(parents=True)
        spec_dir = tmp_path / "specs" / "003-test"
        _write_phase_a_build_inputs(spec_dir)
        monkeypatch.chdir(tmp_path)

        from echelon.cli import _cmd_harness_run
        from echelon.spec_lifecycle import SpecMutationLock

        observed_build_ids: list[str] = []

        def observe_delivery(*_args, **kwargs) -> None:
            build_id = kwargs["resume_build_id"]
            observed_build_ids.append(build_id)
            evidence = json.loads(
                (tmp_path / "runs" / build_id / "state.json").read_text(
                    encoding="utf-8"
                )
            )
            assert evidence["spec_id"] == "003-test"
            assert evidence["status"] == "preparing"
            with SpecMutationLock.acquire(tmp_path, "003-test", "retarget-after"):
                pass

        with patch("harness.config.load_config") as mock_cfg, \
             patch("harness.paths.mirror_path", return_value=mirror), \
             patch("harness.gitops.GitOpsManager"), \
             patch("harness.docker_provider.DockerWorktreeProvider"), \
             patch("harness.skills.run_skill.run", side_effect=observe_delivery):
            mock_cfg.return_value = MagicMock(
                buffer_limit_bytes=1024 * 1024,
                target_repo=".",
            )
            _cmd_harness_run(["003"])

        assert len(observed_build_ids) == 1

    def test_delivery_preparation_fsyncs_build_and_runs_directories(
        self,
        tmp_path: Path,
        monkeypatch,
    ) -> None:
        import echelon.cli as cli

        events: list[tuple[str, Path]] = []
        state_path = tmp_path / "runs" / "build-test" / "state.json"

        def write_state(path: Path, _payload) -> None:
            path.parent.mkdir(parents=True)
            path.write_text("{}\n", encoding="utf-8")
            events.append(("write", path))

        monkeypatch.setattr(
            "harness.lexicon_gate_io.write_json_atomic",
            write_state,
        )
        monkeypatch.setattr(
            cli,
            "_fsync_directory",
            lambda path: events.append(("fsync", path)),
            raising=False,
        )

        cli._write_delivery_preparation_state(
            state_path,
            {"spec_id": "003-test"},
        )

        assert events == [
            ("write", state_path),
            ("fsync", state_path.parent),
            ("fsync", state_path.parent.parent),
            ("fsync", state_path.parent.parent.parent),
        ]

    def test_harness_run_forwards_loop_options_to_run_intent(
        self,
        tmp_path: Path,
        monkeypatch,
    ) -> None:
        config_file = tmp_path / ".echelon" / "config.yml"
        config_file.parent.mkdir(parents=True)
        config_file.write_text("harness:\n  target_repo: .\n", encoding="utf-8")
        (tmp_path / "package.json").write_text("{}\n", encoding="utf-8")

        mirror = tmp_path / "runs" / "mirror.git"
        mirror.mkdir(parents=True)

        spec_dir = tmp_path / "specs" / "003-test"
        _write_phase_a_build_inputs(spec_dir)

        monkeypatch.chdir(tmp_path)

        with patch("harness.config.load_config") as mock_cfg, \
             patch("harness.paths.mirror_path", return_value=mirror), \
             patch("harness.gitops.GitOpsManager"), \
             patch("harness.docker_provider.DockerWorktreeProvider"), \
             patch("harness.skills.run_skill.run") as mock_run:
            mock_cfg.return_value = MagicMock(buffer_limit_bytes=1024 * 1024, target_repo=".")
            from echelon.cli import _cmd_harness_run

            _cmd_harness_run([
                "003",
                "mode=banzai",
                "strategy=codegen",
                "max_outer=3",
                "max_inner=2",
                "token_budget=1000",
                "auto_merge=false",
                "kill_losers=true",
            ])

        user_message = mock_run.call_args.args[0]
        intent = parse_intent(user_message)
        assert intent.spec_id == "003"
        assert intent.mode == "banzai"
        assert intent.strategies == ["codegen"]
        assert intent.max_outer == 3
        assert intent.max_inner == 2
        assert intent.token_budget == 1000
        assert intent.auto_merge is False
        assert intent.kill_losers is True

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
        assert "echelon spec continue" in err

    def test_delivery_blocks_unready_requested_spec_before_runner(
        self,
        tmp_path: Path,
        monkeypatch,
        capsys,
    ) -> None:
        config_file = tmp_path / ".echelon" / "config.yml"
        config_file.parent.mkdir(parents=True)
        config_file.write_text("harness:\n  target_repo: .\n", encoding="utf-8")
        (tmp_path / "package.json").write_text("{}\n", encoding="utf-8")
        mirror = tmp_path / "runs" / "mirror.git"
        mirror.mkdir(parents=True)

        ready_spec = tmp_path / "specs" / "001-ready"
        _write_phase_a_build_inputs(ready_spec)
        unready_spec = tmp_path / "specs" / "002-unready"
        unready_spec.mkdir(parents=True)
        (unready_spec / "spec.md").write_text(SPEC_WITH_LOCAL_TARGET, encoding="utf-8")
        (unready_spec / "tasks.md").write_text(
            "- [ ] T-001 complexity=standard phase=foundation req=INFRA depends=none target=.\n",
            encoding="utf-8",
        )
        active_run = tmp_path / "runs" / "run-ready"
        active_run.mkdir(parents=True)
        (active_run / "state.json").write_text(
            '{"run_id":"ready","spec_id":"001-ready",'
            '"feature_branch":"001-ready","spec_dir":"specs/001-ready"}',
            encoding="utf-8",
        )
        (tmp_path / "runs" / ".current").write_text("run-ready", encoding="utf-8")

        monkeypatch.chdir(tmp_path)
        with patch("harness.config.load_config") as mock_cfg, \
             patch("harness.paths.mirror_path", return_value=mirror), \
             patch("harness.gitops.GitOpsManager"), \
             patch("harness.docker_provider.DockerWorktreeProvider"), \
             patch("harness.skills.run_skill.run") as mock_run:
            mock_cfg.return_value = MagicMock(buffer_limit_bytes=1024 * 1024, target_repo=".")
            from echelon.cli import _cmd_harness_run

            with pytest.raises(SystemExit) as exc:
                _cmd_harness_run(["002-unready"])

        assert exc.value.code == 1
        mock_run.assert_not_called()
        err = capsys.readouterr().err
        assert "Phase A build inputs are not ready" in err
        assert "002-unready" in err


@pytest.mark.unit
class TestHarnessTargetPreflight:
    def test_target_child_uses_json_contract_for_path_containing_comma(
        self,
        tmp_path: Path,
        monkeypatch,
    ) -> None:
        root = tmp_path
        target = root / "sources" / "api,legacy"
        target.mkdir(parents=True)
        spec_dir = root / "specs" / "001-feature"
        spec_dir.mkdir(parents=True)
        contract = (
            "schema_version: 1\ntargets:\n"
            "  - id: api-legacy\n"
            "    path: sources/api,legacy\n"
            "    role: primary\n"
            "    branch: 001-feature\n"
        )
        (spec_dir / "targets.yml").write_text(contract, encoding="utf-8")

        from echelon.cli import _validate_locked_target_child_contract
        from harness.spec_frontmatter import read_canonical_target_entries

        inherited_entries = read_canonical_target_entries(spec_dir)
        monkeypatch.setenv("ECHELON_TARGET_REPO_PATH", str(target))
        monkeypatch.setenv("ECHELON_SOURCE_ROOT", str(target))
        monkeypatch.setenv("ECHELON_IMPLEMENTATION_TARGET", "sources/api,legacy")
        monkeypatch.setenv("ECHELON_DECLARED_TARGETS", "sources/api,legacy")
        monkeypatch.setenv(
            "ECHELON_TARGET_CONTRACT_JSON",
            json.dumps(inherited_entries[0], sort_keys=True),
        )
        monkeypatch.setenv(
            "ECHELON_TARGETS_CONTRACT_JSON",
            json.dumps(inherited_entries, sort_keys=True),
        )

        _validate_locked_target_child_contract(project_root=root, spec_dir=spec_dir)

        (spec_dir / "targets.yml").write_text(
            contract.replace("branch: 001-feature", "branch: replacement-branch"),
            encoding="utf-8",
        )
        with pytest.raises(SystemExit) as exc:
            _validate_locked_target_child_contract(project_root=root, spec_dir=spec_dir)
        assert exc.value.code == 1

    def test_resolver_uses_single_source_root(self, tmp_path: Path) -> None:
        source = tmp_path / "og-platform"
        (source / ".git").mkdir(parents=True)
        (source / "package.json").write_text("{}\n", encoding="utf-8")

        from echelon.cli import _resolve_harness_workspace_target

        target = _resolve_harness_workspace_target(tmp_path, explicit_target=None)

        assert target.workspace_root == tmp_path.resolve()
        assert target.workspace_git_role == "orchestration"
        assert target.source_root == source.resolve()
        assert target.source_id == "og-platform"
        assert target.source_git_role == "source"

    def test_orchestrator_parent_does_not_create_orphan_preparing_build(
        self,
        tmp_path: Path,
        monkeypatch,
    ) -> None:
        root = tmp_path
        spec_dir = root / "specs" / "001-feature"
        _write_phase_a_build_inputs(spec_dir)
        (spec_dir / "spec.md").write_text(
            "---\ntargets:\n  - sources/api\n---\n# Feature\n",
            encoding="utf-8",
        )
        (spec_dir / "tasks.md").write_text(
            "- [ ] T-001 complexity=standard phase=foundation req=INFRA "
            "depends=none target=sources/api\n",
            encoding="utf-8",
        )
        target = root / "sources" / "api"
        (target / ".git").mkdir(parents=True)
        monkeypatch.chdir(root)

        from echelon.cli import HarnessWorkspaceTarget, _cmd_harness_run

        monkeypatch.setattr(
            "echelon.cli._resolve_harness_workspace_target",
            lambda *_args, **_kwargs: HarnessWorkspaceTarget(
                workspace_root=root.resolve(),
                workspace_git_role="orchestration",
                source_root=target.resolve(),
                source_id="api",
                source_git_role="source",
            ),
        )
        with patch("echelon.orchestrator.run_multi_target", return_value=0) as mock_run:
            with pytest.raises(SystemExit) as exc:
                _cmd_harness_run(["001"])

        assert exc.value.code == 0
        mock_run.assert_called_once()
        assert not list((root / "runs").glob("build-*"))

    def test_target_child_prepares_and_runs_in_same_build_root(
        self,
        tmp_path: Path,
        monkeypatch,
    ) -> None:
        root = tmp_path
        target = root / "sources" / "api"
        (target / ".git").mkdir(parents=True)
        (target / "package.json").write_text("{}\n", encoding="utf-8")
        spec_dir = root / "specs" / "001-feature"
        _write_phase_a_build_inputs(spec_dir)
        (spec_dir / "spec.md").write_text(
            "---\ntargets:\n  - sources/api\n---\n# Feature\n",
            encoding="utf-8",
        )
        (spec_dir / "tasks.md").write_text(
            "- [ ] T-001 complexity=standard phase=foundation req=INFRA "
            "depends=none target=sources/api\n",
            encoding="utf-8",
        )
        config_file = root / ".echelon" / "config.yml"
        config_file.parent.mkdir(parents=True)
        config_file.write_text("harness:\n  target_repo: sources/api\n", encoding="utf-8")
        harness_base = root / "runs" / "targets" / "api"
        mirror = harness_base / "runs" / "mirror.git"
        mirror.mkdir(parents=True)

        monkeypatch.chdir(target)
        monkeypatch.setenv("ECHELON_POLYREPO_ROOT", str(root))
        monkeypatch.setenv("ECHELON_TARGET_REPO_PATH", str(target))
        monkeypatch.setenv("ECHELON_TARGET_REPO_NAME", "api")
        monkeypatch.setenv("ECHELON_SOURCE_ROOT", str(target))
        monkeypatch.setenv("ECHELON_IMPLEMENTATION_TARGET", "sources/api")
        monkeypatch.setenv("ECHELON_DECLARED_TARGETS", "sources/api")
        from harness.spec_frontmatter import read_target_entries

        inherited_entries = read_target_entries(spec_dir)
        monkeypatch.setenv(
            "ECHELON_TARGET_CONTRACT_JSON",
            json.dumps(inherited_entries[0], sort_keys=True),
        )
        monkeypatch.setenv(
            "ECHELON_TARGETS_CONTRACT_JSON",
            json.dumps(inherited_entries, sort_keys=True),
        )
        monkeypatch.setattr("echelon.cli._sync_polyrepo_runtime_extension", lambda *_: None)
        monkeypatch.setattr(
            "echelon.cli._apply_target_verify_command_detection",
            lambda *_args, **_kwargs: None,
        )

        observed: list[str] = []

        def observe_run(*_args, **kwargs) -> None:
            build_id = kwargs["resume_build_id"]
            observed.append(build_id)
            assert Path(kwargs["base_dir"]) == harness_base
            evidence_path = harness_base / "runs" / build_id / "state.json"
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
            assert evidence["build_id"] == build_id
            assert evidence["spec_id"] == "001-feature"

        with patch("harness.config.load_config") as mock_cfg, \
             patch("harness.paths.mirror_path", return_value=mirror), \
             patch("harness.gitops.GitOpsManager"), \
             patch("harness.docker_provider.DockerWorktreeProvider"), \
             patch("harness.skills.run_skill.run", side_effect=observe_run):
            mock_cfg.return_value = MagicMock(
                buffer_limit_bytes=1024 * 1024,
                target_repo=str(target),
            )
            from echelon.cli import _cmd_harness_run

            _cmd_harness_run(["001"])

        assert len(observed) == 1
        assert not list((root / "runs").glob("build-*"))

    @pytest.mark.parametrize(
        "replacement_contract",
        [
            "schema_version: 1\ntargets: []\n",
            (
                "schema_version: 1\ntargets:\n"
                "  - id: api\n"
                "    path: sources/api\n"
                "    role: primary\n"
                "    branch: replacement-branch\n"
            ),
        ],
        ids=("removed", "same-name-changed-branch"),
    )
    def test_target_child_rejects_stale_inherited_target_contract_before_preparing(
        self,
        tmp_path: Path,
        monkeypatch,
        replacement_contract: str,
    ) -> None:
        root = tmp_path
        target = root / "sources" / "api"
        (target / ".git").mkdir(parents=True)
        (target / "package.json").write_text("{}\n", encoding="utf-8")
        spec_dir = root / "specs" / "001-feature"
        _write_phase_a_build_inputs(spec_dir)
        (spec_dir / "spec.md").write_text(
            "---\ntargets:\n  - sources/api\n---\n# Feature\n",
            encoding="utf-8",
        )
        original_contract = (
            "schema_version: 1\ntargets:\n"
            "  - id: api\n"
            "    path: sources/api\n"
            "    role: primary\n"
            "    branch: 001-feature\n"
        )
        (spec_dir / "targets.yml").write_text(original_contract, encoding="utf-8")
        (spec_dir / "tasks.md").write_text(
            "- [ ] T-001 complexity=standard phase=foundation req=INFRA "
            "depends=none target=sources/api\n",
            encoding="utf-8",
        )
        config_file = root / ".echelon" / "config.yml"
        config_file.parent.mkdir(parents=True)
        config_file.write_text("harness:\n  target_repo: sources/api\n", encoding="utf-8")
        harness_base = root / "runs" / "targets" / "api"
        mirror = harness_base / "runs" / "mirror.git"
        mirror.mkdir(parents=True)

        from harness.spec_frontmatter import read_target_entries
        from echelon.spec_lifecycle import SpecMutationLock

        inherited_entries = read_target_entries(spec_dir)
        monkeypatch.chdir(target)
        monkeypatch.setenv("ECHELON_POLYREPO_ROOT", str(root))
        monkeypatch.setenv("ECHELON_TARGET_REPO_PATH", str(target))
        monkeypatch.setenv("ECHELON_TARGET_REPO_NAME", "api")
        monkeypatch.setenv("ECHELON_SOURCE_ID", "api")
        monkeypatch.setenv("ECHELON_IMPLEMENTATION_TARGET", "sources/api")
        monkeypatch.setenv("ECHELON_DECLARED_TARGETS", "sources/api")
        monkeypatch.setenv(
            "ECHELON_TARGET_CONTRACT_JSON",
            json.dumps(inherited_entries[0], sort_keys=True),
        )
        monkeypatch.setenv(
            "ECHELON_TARGETS_CONTRACT_JSON",
            json.dumps(inherited_entries, sort_keys=True),
        )
        monkeypatch.setattr("echelon.cli._sync_polyrepo_runtime_extension", lambda *_: None)
        monkeypatch.setattr(
            "echelon.cli._apply_target_verify_command_detection",
            lambda *_args, **_kwargs: None,
        )

        original_acquire = SpecMutationLock.acquire.__func__

        def replace_contract_before_acquire(cls, project_root, spec_id, operation_id):
            (spec_dir / "targets.yml").write_text(
                replacement_contract,
                encoding="utf-8",
            )
            return original_acquire(cls, project_root, spec_id, operation_id)

        monkeypatch.setattr(
            SpecMutationLock,
            "acquire",
            classmethod(replace_contract_before_acquire),
        )

        with patch("harness.config.load_config") as mock_cfg, \
             patch("harness.paths.mirror_path", return_value=mirror), \
             patch("harness.gitops.GitOpsManager"), \
             patch("harness.docker_provider.DockerWorktreeProvider"), \
             patch("harness.skills.run_skill.run") as mock_run:
            mock_cfg.return_value = MagicMock(
                buffer_limit_bytes=1024 * 1024,
                target_repo=str(target),
            )
            from echelon.cli import _cmd_harness_run

            with pytest.raises(SystemExit) as exc:
                _cmd_harness_run(["001"])

        assert exc.value.code == 1
        mock_run.assert_not_called()
        assert not list((harness_base / "runs").glob("build-*"))

    def test_delivery_without_declared_target_stops_before_source_detection(
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
        from echelon.cli import _cmd_harness_run

        with pytest.raises(SystemExit) as exc:
            _cmd_harness_run(["001", "mode=semi"])

        assert exc.value.code == 1
        err = capsys.readouterr().err
        assert "has no implementation target" in err
        assert "echelon spec run <description> --target <source-path>" in err

    def test_delivery_does_not_infer_sole_source_root(
        self,
        tmp_path: Path,
        monkeypatch,
    ) -> None:
        root = tmp_path
        spec_dir = root / "specs" / "001-opta-points-perf-fix"
        _write_phase_a_build_inputs(spec_dir)
        (spec_dir / "spec.md").write_text("# OptaPoints\n", encoding="utf-8")
        (spec_dir / "tasks.md").write_text(
            "- [ ] T-001 complexity=standard phase=foundation req=FR-001 depends=none\n",
            encoding="utf-8",
        )

        target = root / "og-platform"
        (target / ".git").mkdir(parents=True)
        yml = target / ".specify" / "extensions" / "echelon" / "echelon-config.yml"
        yml.parent.mkdir(parents=True)
        yml.write_text("harness:\n  target_repo: .\n", encoding="utf-8")
        (target / "package.json").write_text("{}\n", encoding="utf-8")

        monkeypatch.chdir(root)
        from echelon.cli import _cmd_harness_run
        with patch("echelon.orchestrator.run_multi_target", return_value=0) as mock_run:
            with pytest.raises(SystemExit) as exc:
                _cmd_harness_run(["001", "mode=semi"])

        assert exc.value.code == 1
        mock_run.assert_not_called()

    def test_noncanonical_declared_target_is_rejected_without_mutation(
        self,
        tmp_path: Path,
        monkeypatch,
    ) -> None:
        root = tmp_path
        spec_dir = root / "specs" / "001-feature"
        spec_dir.mkdir(parents=True)
        (spec_dir / "spec.md").write_text(
            "---\ntargets:\n- api\n---\n# Feature\n",
            encoding="utf-8",
        )
        (spec_dir / "tasks.md").write_text(
            "- [ ] T-001 complexity=standard phase=foundation req=FR-001 depends=none\n",
            encoding="utf-8",
        )

        target = root / "services" / "api"
        (target / ".git").mkdir(parents=True)
        (target / "package.json").write_text("{}\n", encoding="utf-8")

        monkeypatch.chdir(root)
        from echelon.cli import HarnessWorkspaceTarget, _cmd_harness_run
        from harness.spec_frontmatter import read_frontmatter

        def fake_resolve(project_root, explicit_target, **kwargs):
            assert explicit_target == "api"
            return HarnessWorkspaceTarget(
                workspace_root=root.resolve(),
                workspace_git_role="orchestration",
                source_root=target.resolve(),
                source_id="api",
                source_git_role="source",
            )

        monkeypatch.setattr("echelon.cli._resolve_harness_workspace_target", fake_resolve)
        with patch("echelon.orchestrator.run_multi_target", return_value=0) as mock_run:
            with pytest.raises(SystemExit) as exc:
                _cmd_harness_run(["001", "mode=banzai"])

        assert exc.value.code == 2
        assert read_frontmatter(spec_dir)["targets"] == ["api"]
        mock_run.assert_not_called()

    def test_explicit_delivery_target_override_is_rejected(
        self,
        tmp_path: Path,
        monkeypatch,
    ) -> None:
        root = tmp_path
        spec_dir = root / "specs" / "001-feature"
        _write_phase_a_build_inputs(spec_dir)
        (spec_dir / "spec.md").write_text("# Feature\n", encoding="utf-8")

        target = root / "services" / "api"
        (target / ".git").mkdir(parents=True)
        (target / "package.json").write_text("{}\n", encoding="utf-8")
        other = root / "services" / "web"
        (other / ".git").mkdir(parents=True)

        monkeypatch.chdir(root)
        from echelon.cli import HarnessWorkspaceTarget, _cmd_harness_run

        with patch("echelon.orchestrator.run_multi_target", return_value=0) as mock_run:
            with pytest.raises(SystemExit) as exc:
                _cmd_harness_run(["001", "mode=banzai", "target=api"])

        assert exc.value.code == 2
        mock_run.assert_not_called()

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
        assert "has no implementation target" in err
        assert "echelon spec run <description> --target <source-path>" in err

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
        assert "has no implementation target" in err
