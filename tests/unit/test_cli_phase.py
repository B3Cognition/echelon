"""Tests for manual squad phase replay commands."""

from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import subprocess

import pytest

from echelon.cli import _cmd_continue, _cmd_phase, _cmd_run
from harness.blocked_decision import build_blocked_decision_v2
from harness.phase_checkpoints import PhaseCheckpoint, record_checkpoint_metadata
from harness.recovery_instruction import RecoveryInstruction, RecoveryKind
from harness.squad_provider import SquadAgentResult
from harness.squad_state import SquadStateStore, StateAdvanceError


ROOT = Path(__file__).resolve().parent.parent.parent
EXT_DIR = ROOT / "runtime"


@pytest.fixture(autouse=True)
def _deploy_workspace_bundles(tmp_path: Path) -> None:
    echelon_dir = tmp_path / ".echelon"
    shutil.copytree(ROOT / "runtime", echelon_dir / "runtime")
    shutil.copytree(ROOT / "prosaic", echelon_dir / "prosaic")


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
    (project_root / ".gitignore").write_text(
        "/runs/\n/.echelon/prosaic/\n/.echelon/runtime/\n",
        encoding="utf-8",
    )
    source_root = project_root / "sources" / "app"
    source_root.mkdir(parents=True)
    (source_root / "package.json").write_text("{}\n", encoding="utf-8")
    (project_root / ".echelon" / "config.yml").write_text(
        "workspace:\n"
        "  git_role: orchestration\n"
        "sources:\n"
        "  - id: app\n"
        "    path: sources/app\n",
        encoding="utf-8",
    )
    subprocess.run(
        [
            "git",
            "add",
            ".gitignore",
            ".echelon/config.yml",
            "sources/app/package.json",
        ],
        cwd=project_root,
        check=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "base"], cwd=project_root, check=True, capture_output=True
    )
    run_dir = project_root / "runs" / "run-active"
    run_dir.mkdir(parents=True)
    (run_dir / "staging").mkdir()
    (project_root / "runs" / ".current").write_text("run-active\n", encoding="utf-8")
    return run_dir


def _seal_pending_v2_decision(
    run_dir: Path,
    *,
    status: str,
    autonomy_mode: str = "semi",
    seed_constitution: bool = False,
) -> None:
    store = SquadStateStore(run_dir)
    completed_phases = []
    if seed_constitution:
        project_root = run_dir.parents[1]
        constitution = project_root / ".echelon" / "constitution.md"
        constitution.parent.mkdir(parents=True, exist_ok=True)
        constitution.write_text(
            "# Constitution\n\nTest governance.\n",
            encoding="utf-8",
        )
        completed_phases.append("phase1-constitution")
    store.initialize(
        "run-active",
        "greenfield",
        "validate the pending decision",
        0,
        "checkpoint-plan",
        autonomy_mode=autonomy_mode,
    )
    state = store.load()
    spec_dir = run_dir / "specs" / "001-demo"
    spec_dir.mkdir(parents=True, exist_ok=True)
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=run_dir.parents[1],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    record_checkpoint_metadata(
        spec_dir,
        PhaseCheckpoint(
            id="checkpoint-test",
            spec_id="001-demo",
            phase="checkpoint-plan",
            next_phase="phase4-document",
            commit=commit,
            metadata_commit=commit,
            source="test",
            run_id="run-active",
            created_at="2026-07-28T10:00:00+00:00",
        ),
    )
    decision = build_blocked_decision_v2(
        decision_id="dec-cli-phase-bypass",
        status=status,
        source_kind="human_gate",
        producer_id="checkpoint-plan",
        source_phase="checkpoint-plan",
        reason_code="checkpoint_plan_decision_required",
        classification="operational",
        question="Approve the plan?",
        options=[
            {
                "id": "approve",
                "label": "Approve",
                "description": "Continue to finalization.",
                "recommended": True,
                "risk_level": "low",
                "next_phase": "phase4-document",
                "outcome": "approved",
            },
            {
                "id": "reject",
                "label": "Reject",
                "description": "Stop for plan revision.",
                "recommended": False,
                "risk_level": "low",
                "next_phase": "terminal-blocked",
                "outcome": "rejected",
            },
        ],
        recommended_answer=None,
        risk_level="low",
        resolution_handler="gate_outcome",
        autonomy_mode=autonomy_mode,
        source_state_revision=state["state_revision"],
        attempts=1 if status == "resolving" else 0,
        now="2026-07-28T10:00:00+00:00",
    )
    state.update(
        {
            "status": "blocked",
            "phase": "checkpoint-plan",
            "spec_id": "001-demo",
            "feature_branch": "main",
            "spec_dir": str(spec_dir),
            "completed_phases": completed_phases,
            "blocked_decision": decision,
            "recovery_instruction": RecoveryInstruction(
                kind=RecoveryKind.RESOLVE_DECISION,
                reason_code="checkpoint_plan_decision_required",
                phase="checkpoint-plan",
                requires_human_input=False,
                schema_version=2,
                decision_id="dec-cli-phase-bypass",
            ).to_dict(),
        }
    )
    store._path.write_text(json.dumps(state), encoding="utf-8")


def test_phase_list_prints_workflow_phases(tmp_path: Path, capsys) -> None:
    _cmd_phase(["list"], project_root=tmp_path, ext_dir=EXT_DIR)

    out = capsys.readouterr().out
    assert "PHASES" in out
    assert "phase1-constitution" in out
    assert "phase3-plan" in out
    assert "phase3-tasks-lexicon" in out
    assert "phase3-consensus-tasks-lexicon" in out


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


@pytest.mark.parametrize("status", ("pending", "resolving"))
@pytest.mark.parametrize("entrypoint", ("next_phase", "phase_run"))
def test_cli_bypass_entrypoints_reject_unresolved_v2_decisions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    status: str,
    entrypoint: str,
) -> None:
    run_dir = _initialize_active_run(tmp_path)
    _seal_pending_v2_decision(run_dir, status=status)
    before = (run_dir / "state.json").read_bytes()

    class PhysicalProvider:
        def __init__(self, _config: object) -> None:
            pass

        def exec_agent(self, *_args: object, **_kwargs: object) -> SquadAgentResult:
            raise AssertionError("unresolved decision must block before provider dispatch")

    monkeypatch.setattr("harness.squad_provider.SquadCliProvider", PhysicalProvider)
    if entrypoint == "next_phase":
        with pytest.raises(SystemExit) as exc:
            _cmd_run(
                ["--next-phase", "phase1-tracker"],
                project_root=tmp_path,
                ext_dir=EXT_DIR,
            )
        assert exc.value.code == 1
    else:
        _cmd_phase(
            ["run", "phase1-tracker"],
            project_root=tmp_path,
            ext_dir=EXT_DIR,
        )

    assert (run_dir / "state.json").read_bytes() == before


@pytest.mark.parametrize("autonomy_mode", ("semi", "banzai"))
def test_continue_resolves_eligible_v2_decisions_through_real_controller(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    autonomy_mode: str,
) -> None:
    run_dir = _initialize_active_run(tmp_path)
    switchable_run_dir = run_dir.with_name("spec-001")
    run_dir.rename(switchable_run_dir)
    (tmp_path / "runs" / ".current").write_text("spec-001\n", encoding="utf-8")
    run_dir = switchable_run_dir
    _seal_pending_v2_decision(
        run_dir,
        status="pending",
        autonomy_mode=autonomy_mode,
        seed_constitution=True,
    )

    class PhysicalProvider:
        def __init__(self, _config: object) -> None:
            self.calls = 0

        def exec_agent(self, *_args: object, **_kwargs: object) -> SquadAgentResult:
            self.calls += 1
            if autonomy_mode == "banzai" and self.calls == 1:
                return SquadAgentResult(
                    exit_code=0,
                    echelon_result={
                        "verdict": "DECISION_RESOLVED",
                        "state_updates": {},
                        "journal_entries": [],
                        "decision": {
                            "selected_option_id": "approve",
                            "answer_text": None,
                            "rationale": "The sealed low-risk option applies.",
                            "confidence": "high",
                        },
                    },
                    raw_output="",
                    duration_ms=1,
                    timed_out=False,
                )
            return SquadAgentResult(
                exit_code=1,
                echelon_result=None,
                raw_output="physical provider stopped after decision resolution",
                duration_ms=1,
                timed_out=False,
            )

    monkeypatch.setattr("harness.squad_provider.SquadCliProvider", PhysicalProvider)
    with pytest.raises((SystemExit, StateAdvanceError)):
        _cmd_continue(
            [],
            project_root=tmp_path,
            ext_dir=EXT_DIR,
        )

    decision = SquadStateStore(run_dir).load()["blocked_decision"]
    assert decision["status"] == "resolved"
    assert decision["resolved_by"] == ("semi" if autonomy_mode == "semi" else "COMMANDER")
    assert (tmp_path / "runs" / ".current").read_text(encoding="utf-8").strip() == run_dir.name


def test_direct_run_with_a_different_message_preserves_active_v2_decision_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir = _initialize_active_run(tmp_path)
    switchable_run_dir = run_dir.with_name("spec-001")
    run_dir.rename(switchable_run_dir)
    (tmp_path / "runs" / ".current").write_text("spec-001\n", encoding="utf-8")
    run_dir = switchable_run_dir
    _seal_pending_v2_decision(run_dir, status="pending")
    before = (run_dir / "state.json").read_bytes()

    class PhysicalProvider:
        def __init__(self, _config: object) -> None:
            pass

        def exec_agent(self, *_args: object, **_kwargs: object) -> SquadAgentResult:
            return SquadAgentResult(
                exit_code=1,
                echelon_result=None,
                raw_output="physical provider stopped the new run",
                duration_ms=1,
                timed_out=False,
            )

    monkeypatch.setattr("harness.squad_provider.SquadCliProvider", PhysicalProvider)
    with pytest.raises((SystemExit, StateAdvanceError)):
        _cmd_run(
            ["a different task"],
            project_root=tmp_path,
            ext_dir=EXT_DIR,
        )

    current = (tmp_path / "runs" / ".current").read_text(encoding="utf-8").strip()
    assert current != run_dir.name
    assert (run_dir / "state.json").read_bytes() == before
    assert SquadStateStore(run_dir).load()["user_message"] == "validate the pending decision"
    assert SquadStateStore(tmp_path / "runs" / current).load()["user_message"] == "a different task"


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
            constitution = Path(project_root) / "specs" / "001-demo" / "constitution.md"
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


@pytest.mark.parametrize(
    "phase_id",
    ["phase3-tasks-lexicon", "phase3-consensus-tasks-lexicon"],
)
def test_phase_run_tasks_lexicon_nodes_use_single_phase_controller(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    phase_id: str,
) -> None:
    run_dir = _initialize_active_run(tmp_path)
    spec_dir = tmp_path / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    state_path = run_dir / "state.json"
    state_path.write_text(
        json.dumps({
            "run_id": "run-active",
            "status": "running",
            "phase": phase_id,
            "spec_id": "001-demo",
            "spec_dir": "specs/001-demo",
            "user_message": "validate tasks",
        }),
        encoding="utf-8",
    )
    compatibility_checks: list[Path] = []
    calls: list[tuple[str, str, str]] = []

    monkeypatch.setattr(
        "echelon.cli._enforce_project_config_compatibility",
        lambda root: compatibility_checks.append(root),
    )
    monkeypatch.setattr(
        "harness.squad.SquadController.run_single_phase",
        lambda self, selected, user_message, mode, initial_state_updates: (
            calls.append((selected, user_message, mode))
            or type("Result", (), {"status": "running", "phase": selected})()
        ),
    )

    _cmd_phase(
        ["run", phase_id, "--spec", "001", "--mode", "banzai"],
        project_root=tmp_path,
        ext_dir=EXT_DIR,
    )

    assert compatibility_checks == [tmp_path]
    assert calls == [(phase_id, "validate tasks", "banzai")]


@pytest.mark.parametrize(
    "blocked_reason",
    ["lexicon_gate_exhausted", "lexicon_repair_no_artifact_progress"],
)
def test_phase_run_blocked_spec_lexicon_gate_prints_repair_guidance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys,
    blocked_reason: str,
) -> None:
    run_dir = _initialize_active_run(tmp_path)
    spec_dir = tmp_path / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    state_path = run_dir / "state.json"
    state_path.write_text(
        json.dumps(
            {
                "run_id": "run-active",
                "status": "blocked",
                "phase": "terminal-blocked",
                "blocked_reason": blocked_reason,
                "spec_id": "001-demo",
                "spec_dir": "specs/001-demo",
                "user_message": "validate lexicon",
            }
        ),
        encoding="utf-8",
    )

    def fake_run_single_phase(
        self,
        selected: str,
        user_message: str,
        mode: str,
        initial_state_updates: dict,
    ):
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state.update(
            {
                "status": "blocked",
                "phase": "terminal-blocked",
                "blocked_reason": blocked_reason,
                "last_dispatch": {"phase_id": selected},
            }
        )
        state_path.write_text(json.dumps(state), encoding="utf-8")
        return type("Result", (), {"status": "blocked", "phase": "terminal-blocked"})()

    monkeypatch.setattr(
        "harness.squad.SquadController.run_single_phase",
        fake_run_single_phase,
    )

    _cmd_phase(
        ["run", "phase1-lexicon", "--spec", "001"],
        project_root=tmp_path,
        ext_dir=EXT_DIR,
    )

    output = capsys.readouterr().out
    assert "repair requirements.lexicon.md" in output
    assert "spec-lexicon-report.json" in output
    assert "echelon phase run phase1-lexicon-derive" in output
    assert "echelon phase run phase1-what" not in output
    assert "echelon phase run phase1-lexicon\n" not in output


def test_successful_manual_lexicon_derivation_points_to_deterministic_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys,
) -> None:
    run_dir = _initialize_active_run(tmp_path)
    spec_dir = tmp_path / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    state_path = run_dir / "state.json"
    state_path.write_text(
        json.dumps(
            {
                "run_id": "run-active",
                "status": "running",
                "phase": "phase1-lexicon-derive",
                "spec_id": "001-demo",
                "spec_dir": "specs/001-demo",
                "user_message": "derive lexicon",
            }
        ),
        encoding="utf-8",
    )

    def fake_run_single_phase(
        self,
        selected: str,
        user_message: str,
        mode: str,
        initial_state_updates: dict,
    ):
        assert selected == "phase1-lexicon-derive"
        return type("Result", (), {"status": "running", "phase": selected})()

    monkeypatch.setattr(
        "harness.squad.SquadController.run_single_phase",
        fake_run_single_phase,
    )

    _cmd_phase(
        ["run", "phase1-lexicon-derive", "--spec", "001"],
        project_root=tmp_path,
        ext_dir=EXT_DIR,
    )

    output = capsys.readouterr().out
    assert "echelon phase run phase1-lexicon\n" in output
    assert "echelon spec continue" not in output


def test_phase_run_keeps_manual_replay_in_run_local_spec_copy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _initialize_active_run(tmp_path)
    published_spec_dir = tmp_path / "specs" / "001-demo"
    published_spec_dir.mkdir(parents=True)
    published_spec = published_spec_dir / "spec.md"
    published_spec.write_text("# Published Demo\n", encoding="utf-8")
    state_store = SquadStateStore(tmp_path / "runs" / "run-active")
    state_store.initialize("run-active", "banzai", "repair", 0, "phase1-what")
    state = state_store.load()
    state["completed_phases"] = ["phase1-constitution"]
    state_store.save(state)

    class FakeProvider:
        def __init__(self, _config: object) -> None:
            pass

        def exec_agent(
            self,
            project_root: str,
            prompt: str,
            timeout_ms: int | None = None,
            **_kwargs: object,
        ) -> SquadAgentResult:
            match = re.search(r"^ACTIVE_SPEC_DIR=(.+)$", prompt, re.MULTILINE)
            assert match is not None
            active_spec_dir = Path(match.group(1))
            active_spec_dir.mkdir(parents=True, exist_ok=True)
            (active_spec_dir / "spec.md").write_text(
                "# Run-local repair\n",
                encoding="utf-8",
            )
            (active_spec_dir / "requirements-overview.md").write_text(
                "# Requirements Overview\n",
                encoding="utf-8",
            )
            return SquadAgentResult(
                exit_code=0,
                echelon_result={
                    "verdict": "DONE",
                    "state_updates": {"evidence_resolution_status": "not_required"},
                    "journal_entries": [],
                },
                raw_output="",
                duration_ms=10,
                timed_out=False,
            )

    monkeypatch.setattr("harness.squad_provider.SquadCliProvider", FakeProvider)
    constitution = tmp_path / ".echelon" / "constitution.md"
    constitution.write_text("# Constitution\n\nReal governance.\n", encoding="utf-8")

    _cmd_phase(
        ["run", "phase1-what", "--spec", "001"],
        project_root=tmp_path,
        ext_dir=EXT_DIR,
    )

    run_dir = tmp_path / "runs"
    current = (run_dir / ".current").read_text(encoding="utf-8").strip()
    state = json.loads((run_dir / current / "state.json").read_text(encoding="utf-8"))

    assert state["phase"] == "phase1-understanding"
    assert state["spec_dir"] == "runs/run-active/specs/001-demo"
    assert state["published_spec_dir"] == "specs/001-demo"
    assert state["last_dispatch"]["phase_id"] == "phase1-what"
    assert state["last_dispatch"]["manual_phase_run"] is True
    assert state["manual_phase_runs"][0]["phase_id"] == "phase1-what"
    assert "phase1-what" in state["completed_phases"]
    run_local_spec_dir = tmp_path / state["spec_dir"]
    assert (run_local_spec_dir / "spec.md").read_text(encoding="utf-8") == "# Run-local repair\n"
    assert (run_local_spec_dir / "requirements-overview.md").exists()
    assert not (published_spec_dir / "constitution.md").exists()
    assert not (published_spec_dir / "ARTIFACTS.md").exists()
    assert published_spec.read_text(encoding="utf-8") == "# Published Demo\n"


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
    config_path = tmp_path / ".echelon" / "config.yml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text("lexicon_gate:\n  enabled: false\n", encoding="utf-8")
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
