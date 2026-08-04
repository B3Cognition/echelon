"""Unit tests for echelon.orchestrator — validate_targets and run_multi_target."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from echelon.orchestrator import (
    run_multi_target,
    validate_single_target,
    validate_targets,
)

def _make_target(tmp_path: Path, name: str, git_repo: bool = True) -> Path:
    t = tmp_path / name
    t.mkdir()
    if git_repo:
        (t / ".git").mkdir()
    return t


@pytest.mark.unit
class TestValidateTargets:
    def test_valid_targets_returned(self, tmp_path: Path) -> None:
        t = _make_target(tmp_path, "repo-a")
        result = validate_targets(["repo-a"], tmp_path)
        assert result == [t]

    def test_nonexistent_target_exits(self, tmp_path: Path) -> None:
        with pytest.raises(SystemExit) as exc:
            validate_targets(["does-not-exist"], tmp_path)
        assert exc.value.code == 1

    def test_non_git_target_exits(self, tmp_path: Path, capsys) -> None:
        _make_target(tmp_path, "repo-b", git_repo=False)
        with pytest.raises(SystemExit) as exc:
            validate_targets(["repo-b"], tmp_path)
        assert exc.value.code == 1
        err = capsys.readouterr().err
        assert "not a git repo" in err
        assert "must be initialized git repositories" in err

    def test_multiple_valid_targets(self, tmp_path: Path) -> None:
        a = _make_target(tmp_path, "repo-a")
        b = _make_target(tmp_path, "repo-b")
        result = validate_targets(["repo-a", "repo-b"], tmp_path)
        assert result == [a, b]


@pytest.mark.unit
class TestValidateSingleTarget:
    def test_one_target_returns_resolved_path(self, tmp_path: Path) -> None:
        target = _make_target(tmp_path, "repo-a")
        result = validate_single_target(["repo-a"], tmp_path)
        assert result == target

    def test_zero_targets_exits_one(self, tmp_path: Path, capsys) -> None:
        with pytest.raises(SystemExit) as exc:
            validate_single_target([], tmp_path)

        assert exc.value.code == 1
        assert "No implementation target configured" in capsys.readouterr().err

    def test_multiple_targets_exits_one(self, tmp_path: Path, capsys) -> None:
        _make_target(tmp_path, "repo-a")
        _make_target(tmp_path, "repo-b")

        with pytest.raises(SystemExit) as exc:
            validate_single_target(["repo-a", "repo-b"], tmp_path)

        assert exc.value.code == 1
        assert "Multiple targets configured for single-target harness build" in (
            capsys.readouterr().err
        )


@pytest.mark.unit
class TestRunMultiTarget:
    def _make_popen_factory(self, outputs: dict[str, str], exit_codes: dict[str, int]):
        """Return a Popen factory that simulates per-target output."""
        def popen_factory(cmd, cwd, stdout, stderr, text, env=None):
            name = Path(cwd).name
            mock = MagicMock()
            lines = outputs.get(name, "").splitlines(keepends=True)
            mock.stdout = iter(lines)
            mock.returncode = exit_codes.get(name, 0)
            mock.wait.return_value = None
            return mock
        return popen_factory

    def test_all_succeed_returns_zero(self, tmp_path: Path) -> None:
        targets = [tmp_path / "a", tmp_path / "b"]
        for t in targets:
            t.mkdir()
        outputs = {"a": "line1\n", "b": "line2\n"}
        exit_codes = {"a": 0, "b": 0}
        with patch("subprocess.Popen", side_effect=self._make_popen_factory(outputs, exit_codes)):
            rc = run_multi_target("024", targets, [], echelon_bin="echelon")
        assert rc == 0

    def test_one_failure_returns_one(self, tmp_path: Path) -> None:
        targets = [tmp_path / "a", tmp_path / "b"]
        for t in targets:
            t.mkdir()
        exit_codes = {"a": 0, "b": 1}
        with patch("subprocess.Popen", side_effect=self._make_popen_factory({"a": "", "b": ""}, exit_codes)):
            rc = run_multi_target("024", targets, [], echelon_bin="echelon")
        assert rc == 1

    def test_non_json_safe_canonical_contract_fails_before_launch(
        self,
        tmp_path: Path,
        capsys,
    ) -> None:
        target = tmp_path / "r"
        target.mkdir()
        spec_dir = tmp_path / "specs" / "024"
        spec_dir.mkdir(parents=True)
        (spec_dir / "targets.yml").write_text(
            "schema_version: 1\ntargets:\n"
            "  - id: r\n"
            "    path: r\n"
            "    role: primary\n"
            "    branch: '024'\n"
            "    release_on: 2026-08-04\n",
            encoding="utf-8",
        )

        with patch("subprocess.Popen") as popen:
            rc = run_multi_target(
                "024",
                [target],
                [],
                echelon_bin="echelon",
                workspace_root=tmp_path,
            )

        assert rc == 1
        popen.assert_not_called()
        assert "canonical target contract" in capsys.readouterr().err

    def test_launch_exception_is_recorded_as_failure(
        self,
        tmp_path: Path,
        capsys,
    ) -> None:
        target = tmp_path / "r"
        target.mkdir()

        with patch("subprocess.Popen", side_effect=OSError("launch failed")):
            rc = run_multi_target("024", [target], [], echelon_bin="echelon")

        assert rc == 1
        captured = capsys.readouterr()
        assert "launch failed" in captured.err
        assert "✗ [r]: exit 1" in captured.out

    def test_output_prefixed_with_target_name(self, tmp_path: Path, capsys) -> None:
        target = tmp_path / "myrepo"
        target.mkdir()
        mock_proc = MagicMock()
        mock_proc.stdout = iter(["hello\n"])
        mock_proc.returncode = 0
        mock_proc.wait.return_value = None
        with patch("subprocess.Popen", return_value=mock_proc):
            run_multi_target("024", [target], [], echelon_bin="echelon")
        captured = capsys.readouterr()
        assert "[myrepo] hello" in captured.out

    def test_extra_args_forwarded(self, tmp_path: Path) -> None:
        target = tmp_path / "r"
        target.mkdir()
        captured_cmd: dict = {}
        def fake_popen(cmd, cwd, stdout, stderr, text, env=None):
            captured_cmd["cmd"] = cmd
            m = MagicMock()
            m.stdout = iter([])
            m.returncode = 0
            m.wait.return_value = None
            return m
        with patch("subprocess.Popen", side_effect=fake_popen):
            run_multi_target("024", [target], ["strategy=codegen", "max_outer=3"],
                             echelon_bin="echelon")
        assert captured_cmd["cmd"] == ["echelon", "harness", "run", "024",
                                       "strategy=codegen", "max_outer=3"]

    def test_single_target_metadata_env_includes_owned_task_ids(self, tmp_path: Path) -> None:
        target = tmp_path / "r"
        target.mkdir()
        spec_dir = tmp_path / "specs" / "024"
        spec_dir.mkdir(parents=True)
        (spec_dir / "tasks.md").write_text(
            "- [ ] T-001 complexity=standard phase=foundation req=FR-001 depends=none target=r\n"
            "- [ ] T-002 complexity=standard phase=verify req=FR-002 depends=T-001 target=r\n",
            encoding="utf-8",
        )
        (spec_dir / "spec.md").write_text("# Spec\n", encoding="utf-8")
        (spec_dir / "targets.yml").write_text(
            "schema_version: 1\ntargets:\n"
            "  - id: r\n    path: r\n    role: primary\n    branch: '024'\n",
            encoding="utf-8",
        )
        captured: dict = {}

        def fake_popen(cmd, cwd, stdout, stderr, text, env=None):
            captured["env"] = env
            captured["cwd"] = cwd
            m = MagicMock()
            m.stdout = iter([])
            m.returncode = 0
            m.wait.return_value = None
            return m

        with patch("subprocess.Popen", side_effect=fake_popen):
            run_multi_target("024", [target], [], echelon_bin="echelon", workspace_root=tmp_path)

        assert captured["cwd"] == str(target)
        assert captured["env"]["ECHELON_POLYREPO_ROOT"] == str(tmp_path)
        assert captured["env"]["ECHELON_TARGET_REPO_PATH"] == str(target)
        assert captured["env"]["ECHELON_TARGET_REPO_NAME"] == "r"
        assert captured["env"]["ECHELON_WORKSPACE_ROOT"] == str(tmp_path)
        assert captured["env"]["ECHELON_SOURCE_ROOT"] == str(target.resolve())
        assert captured["env"]["ECHELON_SOURCE_ID"] == "r"
        assert captured["env"]["ECHELON_TARGET_TASK_IDS"] == "T-001,T-002"
        assert json.loads(captured["env"]["ECHELON_TARGET_CONTRACT_JSON"]) == {
            "branch": "024",
            "id": "r",
            "path": "r",
            "role": "primary",
        }
        assert json.loads(captured["env"]["ECHELON_TARGETS_CONTRACT_JSON"]) == [
            {"branch": "024", "id": "r", "path": "r", "role": "primary"}
        ]

    def test_multi_target_delivery_is_dependency_ordered_and_task_scoped(
        self,
        tmp_path: Path,
    ) -> None:
        sources = tmp_path / "sources"
        api = sources / "api"
        web = sources / "web"
        api.mkdir(parents=True)
        web.mkdir()
        spec_dir = tmp_path / "specs" / "001-dashboard"
        spec_dir.mkdir(parents=True)
        (spec_dir / "tasks.md").write_text(
            "- [ ] T-001 complexity=standard phase=api req=FR-001 depends=none target=sources/api\n\n"
            "  **Files:**\n"
            "  - `sources/api/src/dashboard.ts` — backend\n\n"
            "- [ ] T-002 complexity=standard phase=web req=FR-002 depends=T-001 target=sources/web\n\n"
            "  **Files:**\n"
            "  - `sources/web/src/dashboard.tsx` — frontend\n\n"
            "- [ ] T-003 complexity=standard phase=web req=FR-003 depends=T-002 target=sources/web\n\n"
            "  **Files:**\n"
            "  - `sources/web/src/dashboard.test.tsx` — frontend test\n",
            encoding="utf-8",
        )
        calls: list[dict[str, object]] = []

        def fake_popen(cmd, cwd, stdout, stderr, text, env=None):
            calls.append({"cmd": cmd, "cwd": cwd, "env": env})
            mock = MagicMock()
            mock.stdout = iter([])
            mock.returncode = 0
            mock.wait.return_value = None
            return mock

        with patch("subprocess.Popen", side_effect=fake_popen):
            rc = run_multi_target(
                "001",
                [web, api],
                [],
                echelon_bin="echelon",
                workspace_root=tmp_path,
            )

        assert rc == 0
        assert [Path(str(call["cwd"])).name for call in calls] == ["api", "web"]
        assert calls[0]["env"]["ECHELON_TARGET_TASK_IDS"] == "T-001"
        assert calls[1]["env"]["ECHELON_TARGET_TASK_IDS"] == "T-002,T-003"
        assert calls[0]["env"]["ECHELON_IMPLEMENTATION_TARGET"] == "sources/api"
        assert calls[1]["env"]["ECHELON_IMPLEMENTATION_TARGET"] == "sources/web"
        assert calls[0]["env"]["ECHELON_DECLARED_TARGETS"] == "sources/web,sources/api"

    def test_nested_target_metadata_keeps_workspace_root_and_source_id(
        self, tmp_path: Path
    ) -> None:
        workspace = tmp_path / "workspace"
        target = workspace / "apps" / "web"
        target.mkdir(parents=True)
        captured: dict = {}

        def fake_popen(cmd, cwd, stdout, stderr, text, env=None):
            captured["env"] = env
            captured["cwd"] = cwd
            m = MagicMock()
            m.stdout = iter([])
            m.returncode = 0
            m.wait.return_value = None
            return m

        with patch("subprocess.Popen", side_effect=fake_popen):
            run_multi_target(
                "024",
                [target],
                [],
                echelon_bin="echelon",
                workspace_root=workspace,
                source_ids={str(target.resolve()): "web-app"},
            )

        assert captured["cwd"] == str(target)
        assert captured["env"]["ECHELON_POLYREPO_ROOT"] == str(workspace.resolve())
        assert captured["env"]["ECHELON_WORKSPACE_ROOT"] == str(workspace.resolve())
        assert captured["env"]["ECHELON_TARGET_REPO_PATH"] == str(target.resolve())
        assert captured["env"]["ECHELON_SOURCE_ROOT"] == str(target.resolve())
        assert captured["env"]["ECHELON_SOURCE_ID"] == "web-app"

    def test_single_repo_dot_metadata_uses_source_workspace_role(
        self, tmp_path: Path
    ) -> None:
        target = tmp_path / "workspace"
        target.mkdir()
        captured: dict = {}

        def fake_popen(cmd, cwd, stdout, stderr, text, env=None):
            captured["env"] = env
            m = MagicMock()
            m.stdout = iter([])
            m.returncode = 0
            m.wait.return_value = None
            return m

        with patch("subprocess.Popen", side_effect=fake_popen):
            run_multi_target(
                "024",
                [target],
                [],
                echelon_bin="echelon",
                workspace_root=target,
                workspace_git_role="source",
                source_ids={str(target.resolve()): "."},
            )

        assert captured["env"]["ECHELON_WORKSPACE_GIT_ROLE"] == "source"
        assert captured["env"]["ECHELON_SOURCE_ID"] == "."
