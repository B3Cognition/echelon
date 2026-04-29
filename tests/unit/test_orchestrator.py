"""Unit tests for echelon.orchestrator — validate_targets and run_multi_target."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from echelon.orchestrator import run_multi_target, validate_targets

_ECHELON_YML = ".specify/extensions/echelon/echelon.yml"


def _make_target(tmp_path: Path, name: str, initialised: bool = True) -> Path:
    t = tmp_path / name
    t.mkdir()
    if initialised:
        yml = t / _ECHELON_YML
        yml.parent.mkdir(parents=True)
        yml.write_text("harness:\n  target_repo: .\n", encoding="utf-8")
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

    def test_uninitialised_target_exits(self, tmp_path: Path) -> None:
        _make_target(tmp_path, "repo-b", initialised=False)
        with pytest.raises(SystemExit) as exc:
            validate_targets(["repo-b"], tmp_path)
        assert exc.value.code == 1

    def test_multiple_valid_targets(self, tmp_path: Path) -> None:
        a = _make_target(tmp_path, "repo-a")
        b = _make_target(tmp_path, "repo-b")
        result = validate_targets(["repo-a", "repo-b"], tmp_path)
        assert result == [a, b]


@pytest.mark.unit
class TestRunMultiTarget:
    def _make_popen_factory(self, outputs: dict[str, str], exit_codes: dict[str, int]):
        """Return a Popen factory that simulates per-target output."""
        def popen_factory(cmd, cwd, stdout, stderr, text):
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
        def fake_popen(cmd, cwd, stdout, stderr, text):
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
