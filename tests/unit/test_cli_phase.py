"""Tests for manual squad phase replay commands."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

from echelon.cli import _cmd_phase
from harness.squad_provider import SquadAgentResult


ROOT = Path(__file__).resolve().parent.parent.parent
EXT_DIR = ROOT / "extension"


def _initialize_active_run(project_root: Path) -> Path:
    subprocess.run(
        ["git", "init", "-b", "main"],
        cwd=project_root,
        check=True,
        capture_output=True,
    )
    subprocess.run(["git", "config", "user.name", "Echelon Tests"], cwd=project_root, check=True)
    subprocess.run(
        ["git", "config", "user.email", "echelon@example.test"],
        cwd=project_root,
        check=True,
    )
    (project_root / ".gitignore").write_text("/runs/.current\n", encoding="utf-8")
    subprocess.run(["git", "add", ".gitignore"], cwd=project_root, check=True)
    subprocess.run(
        ["git", "commit", "-m", "base"], cwd=project_root, check=True, capture_output=True
    )
    run_dir = project_root / "runs" / "run-active"
    run_dir.mkdir(parents=True)
    (run_dir / "staging").mkdir()
    (project_root / "runs" / ".current").write_text("run-active\n", encoding="utf-8")
    return run_dir


def test_phase_list_prints_workflow_phases(tmp_path: Path, capsys) -> None:
    _cmd_phase(["list"], project_root=tmp_path, ext_dir=EXT_DIR)

    out = capsys.readouterr().out
    assert "PHASES" in out
    assert "phase1-constitution" in out
    assert "phase3-plan" in out


def test_phase_list_does_not_require_dispatch_config_compatibility(
    tmp_path: Path,
    capsys,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_if_called(_project_root: Path) -> None:
        raise AssertionError("phase list must not enforce agent-dispatch config")

    monkeypatch.setattr("echelon.cli._enforce_project_config_compatibility", fail_if_called)

    _cmd_phase(["list"], project_root=tmp_path, ext_dir=EXT_DIR)

    assert "phase1-constitution" in capsys.readouterr().out


def test_phase_run_rejects_unknown_phase(tmp_path: Path, capsys) -> None:
    with pytest.raises(SystemExit) as exc:
        _cmd_phase(["run", "phase-does-not-exist"], project_root=tmp_path, ext_dir=EXT_DIR)

    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "Unknown phase id" in err
    assert "phase1-constitution" in err


def test_phase_run_constitution_does_not_require_task_lexicon_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _initialize_active_run(tmp_path)
    spec_dir = tmp_path / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text("# Demo\n", encoding="utf-8")

    def fail_if_called(_project_root: Path) -> None:
        raise AssertionError("constitution replay must not enforce task Lexicon config")

    class FakeProvider:
        def __init__(self, _config: object) -> None:
            pass

        def exec_agent(
            self,
            project_root: str,
            _prompt: str,
            timeout_ms: int | None = None,
            **_kwargs: object,
        ) -> SquadAgentResult:
            constitution = Path(project_root) / ".specify" / "memory" / "constitution.md"
            constitution.parent.mkdir(parents=True, exist_ok=True)
            constitution.write_text("# Constitution\n\nReal governance.\n", encoding="utf-8")
            return SquadAgentResult(
                exit_code=0,
                echelon_result={
                    "verdict": "DONE",
                    "state_updates": {"constitution_status": "complete"},
                    "journal_entries": [],
                },
                raw_output="",
                duration_ms=10,
                timed_out=False,
            )

    monkeypatch.setattr("echelon.cli._enforce_project_config_compatibility", fail_if_called)
    monkeypatch.setattr("harness.squad_provider.SquadCliProvider", FakeProvider)

    _cmd_phase(
        ["run", "phase1-constitution", "--spec", "001"],
        project_root=tmp_path,
        ext_dir=EXT_DIR,
    )

    assert (spec_dir / "constitution.md").exists()


def test_phase_run_plan_enforces_task_lexicon_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def blocked(_project_root: Path) -> None:
        raise SystemExit(7)

    monkeypatch.setattr("echelon.cli._enforce_project_config_compatibility", blocked)

    with pytest.raises(SystemExit) as exc:
        _cmd_phase(["run", "phase3-plan"], project_root=tmp_path, ext_dir=EXT_DIR)

    assert exc.value.code == 7


def test_phase_run_records_manual_replay_and_targets_spec_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _initialize_active_run(tmp_path)
    spec_dir = tmp_path / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text("# Demo\n", encoding="utf-8")

    class FakeProvider:
        def __init__(self, _config: object) -> None:
            pass

        def exec_agent(
            self,
            project_root: str,
            _prompt: str,
            timeout_ms: int | None = None,
            **_kwargs: object,
        ) -> SquadAgentResult:
            constitution = Path(project_root) / ".specify" / "memory" / "constitution.md"
            constitution.parent.mkdir(parents=True, exist_ok=True)
            constitution.write_text("# Constitution\n\nReal governance.\n", encoding="utf-8")
            return SquadAgentResult(
                exit_code=0,
                echelon_result={
                    "verdict": "DONE",
                    "state_updates": {"constitution_status": "complete"},
                    "journal_entries": [],
                },
                raw_output="",
                duration_ms=10,
                timed_out=False,
            )

    monkeypatch.setattr("harness.squad_provider.SquadCliProvider", FakeProvider)

    _cmd_phase(
        ["run", "phase1-constitution", "--spec", "001"],
        project_root=tmp_path,
        ext_dir=EXT_DIR,
    )

    run_dir = tmp_path / "runs"
    current = (run_dir / ".current").read_text(encoding="utf-8").strip()
    state = json.loads((run_dir / current / "state.json").read_text(encoding="utf-8"))

    assert state["phase"] == "phase1-what"
    assert state["spec_dir"] == "specs/001-demo"
    assert state["published_spec_dir"] == "specs/001-demo"
    assert state["last_dispatch"]["phase_id"] == "phase1-constitution"
    assert state["last_dispatch"]["manual_phase_run"] is True
    assert state["manual_phase_runs"][0]["phase_id"] == "phase1-constitution"
    assert "phase1-constitution" in state["completed_phases"]
    assert (spec_dir / "constitution.md").read_text(encoding="utf-8").startswith("# Constitution")
    assert (spec_dir / "ARTIFACTS.md").exists()


@pytest.mark.parametrize(
    ("phase_id", "state_key", "report_name"),
    [
        ("phase-exp-constitution-quality", "constitution_quality_pass", "constitution-quality-report.md"),
        ("phase-exp-tasks-quality", "tasks_quality_pass", "tasks-quality-report.md"),
        ("phase-exp-adr-quality", "adr_quality_pass", "adr-quality-report.md"),
    ],
)
def test_phase_run_experimental_artifact_quality_phases(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    phase_id: str,
    state_key: str,
    report_name: str,
) -> None:
    _initialize_active_run(tmp_path)
    spec_dir = tmp_path / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text("# Demo\n", encoding="utf-8")
    (spec_dir / "plan.md").write_text("# Plan\n", encoding="utf-8")
    (spec_dir / "tasks.md").write_text("# Tasks\n", encoding="utf-8")
    (spec_dir / "constitution.md").write_text("# Constitution\n", encoding="utf-8")
    (spec_dir / "adr").mkdir()
    (spec_dir / "adr" / "ADR-001-demo.md").write_text("# ADR-001\n", encoding="utf-8")

    class FakeProvider:
        def __init__(self, _config: object) -> None:
            pass

        def exec_agent(
            self,
            project_root: str,
            _prompt: str,
            timeout_ms: int | None = None,
            **_kwargs: object,
        ) -> SquadAgentResult:
            target = Path(project_root) / "specs" / "001-demo" / report_name
            target.write_text("# Quality Report\n\nPass.\n", encoding="utf-8")
            return SquadAgentResult(
                exit_code=0,
                echelon_result={
                    "verdict": "DONE",
                    "state_updates": {
                        state_key: True,
                        state_key.replace("_pass", "_attempts"): 1,
                        state_key.replace("_pass", "_findings"): 0,
                    },
                    "journal_entries": [],
                },
                raw_output="",
                duration_ms=10,
                timed_out=False,
            )

    monkeypatch.setattr("harness.squad_provider.SquadCliProvider", FakeProvider)

    _cmd_phase(["run", phase_id, "--spec", "001"], project_root=tmp_path, ext_dir=EXT_DIR)

    current = (tmp_path / "runs" / ".current").read_text(encoding="utf-8").strip()
    state = json.loads((tmp_path / "runs" / current / "state.json").read_text(encoding="utf-8"))
    assert state[state_key] is True
    assert state["last_dispatch"]["manual_phase_run"] is True
    assert (spec_dir / report_name).exists()
