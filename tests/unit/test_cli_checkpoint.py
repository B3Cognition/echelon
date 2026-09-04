from pathlib import Path
import json
import shlex
import subprocess
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from echelon.checkpoint_cli import run_checkpoint_command
from echelon.cli import _classify_run_recovery, _cmd_rewind
from echelon.checkpoint_coverage import (
    CheckpointCoverageError,
    compute_spec_checkpoint_coverage,
)
from harness.blocked_decision import build_blocked_decision_v2
from harness.phase_checkpoints import (
    CheckpointLedger,
    PhaseCheckpoint,
    load_checkpoint_ledger,
    record_checkpoint_metadata,
)
from echelon.rewind import RewindResult


class _CoverageGraph:
    def __init__(self, policies: dict[str, tuple[str, str]]) -> None:
        self._policies = policies

    def get(self, phase: str) -> SimpleNamespace:
        checkpoint, rewind = self._policies[phase]
        return SimpleNamespace(checkpoint=checkpoint, rewind=rewind)


def _write_switchable_run(
    root: Path,
    run_name: str,
    *,
    spec_id: str = "001-demo",
    state_updates: dict[str, object] | None = None,
) -> tuple[Path, Path]:
    run_dir = root / "runs" / run_name
    spec_dir = run_dir / "specs" / spec_id
    spec_dir.mkdir(parents=True)
    state = {
        "run_id": run_name,
        "spec_id": spec_id,
        "feature_branch": spec_id,
        "spec_dir": spec_dir.relative_to(root).as_posix(),
    }
    state.update(state_updates or {})
    (run_dir / "state.json").write_text(json.dumps(state), encoding="utf-8")
    return run_dir, spec_dir


@pytest.fixture(autouse=True)
def _workspace_checkpoint_graph(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "harness.phase_graph.load_workspace_phase_graph",
        lambda _root: (_CoverageGraph({}), tmp_path / ".echelon" / "runtime"),
    )


def test_checkpoint_coverage_joins_versioned_rows_by_completion_id() -> None:
    graph = _CoverageGraph(
        {
            "phase1-discover": ("required", "supported"),
            "phase1-modeler": ("required", "supported"),
            "human-spec": ("none", "none"),
        }
    )
    state = {
        "checkpoint_policy_version": 2,
        "run_id": "run-1",
        "spec_id": "001-demo",
        "phase_completion_outcomes": [
            {"completion_id": "a" * 32, "phase": "phase1-discover", "outcome": "executed", "checkpoint": "required"},
            {"completion_id": "b" * 32, "phase": "phase1-discover", "outcome": "executed", "checkpoint": "required"},
            {"completion_id": "c" * 32, "phase": "phase1-modeler", "outcome": "skipped", "checkpoint": "required"},
            {"completion_id": "d" * 32, "phase": "human-spec", "outcome": "executed", "checkpoint": "none"},
            {"completion_id": "e" * 32, "phase": "phase1-modeler", "outcome": "executed", "checkpoint": "required", "legacy": True},
        ],
    }
    ledger = CheckpointLedger(
        spec_id="001-demo",
        checkpoints=[
            PhaseCheckpoint(
                id="phase1-discover",
                spec_id="001-demo",
                phase="phase1-discover",
                next_phase="phase1-synthesizer",
                commit="1" * 40,
                metadata_commit="",
                source="auto",
                run_id="run-1",
                created_at="2026-08-20T00:00:00Z",
                completion_id="a" * 32,
                boundary_completion_id="a" * 32,
            )
        ],
    )

    coverage = compute_spec_checkpoint_coverage(graph, state, ledger)

    assert [row.status for row in coverage] == [
        "recorded",
        "missing",
        "skipped",
        "not-checkpointed",
        "legacy-migrated",
    ]
    assert [row.completion_id for row in coverage[:2]] == ["a" * 32, "b" * 32]


def test_checkpoint_coverage_never_marks_legacy_untracked_as_missing() -> None:
    graph = _CoverageGraph({"phase1-discover": ("required", "supported")})

    coverage = compute_spec_checkpoint_coverage(
        graph,
        {"completed_phases": ["phase1-discover", "phase1-discover"]},
        CheckpointLedger(spec_id="001-demo", checkpoints=[]),
    )

    assert [(row.phase, row.status) for row in coverage] == [
        ("phase1-discover", "legacy-untracked")
    ]


def test_checkpoint_coverage_rejects_duplicate_completion_ids() -> None:
    graph = _CoverageGraph({"phase1-discover": ("required", "supported")})
    outcome = {
        "completion_id": "a" * 32,
        "phase": "phase1-discover",
        "outcome": "executed",
        "checkpoint": "required",
    }

    with pytest.raises(CheckpointCoverageError, match="duplicate phase completion"):
        compute_spec_checkpoint_coverage(
            graph,
            {
                "checkpoint_policy_version": 2,
                "phase_completion_outcomes": [outcome, dict(outcome)],
            },
            CheckpointLedger(spec_id="001-demo", checkpoints=[]),
        )


def test_checkpoint_coverage_rejects_checkpoint_identity_drift() -> None:
    graph = _CoverageGraph({"phase1-discover": ("required", "supported")})
    checkpoint = PhaseCheckpoint(
        id="phase1-modeler",
        spec_id="001-demo",
        phase="phase1-modeler",
        next_phase="phase1-tracker",
        commit="1" * 40,
        metadata_commit="",
        source="auto",
        run_id="run-1",
        created_at="2026-08-20T00:00:00Z",
        completion_id="a" * 32,
    )

    with pytest.raises(CheckpointCoverageError, match="identity drift"):
        compute_spec_checkpoint_coverage(
            graph,
            {
                "checkpoint_policy_version": 2,
                "run_id": "run-1",
                "spec_id": "001-demo",
                "phase_completion_outcomes": [
                    {
                        "completion_id": "a" * 32,
                        "phase": "phase1-discover",
                        "outcome": "executed",
                        "checkpoint": "required",
                    }
                ],
            },
            CheckpointLedger(spec_id="001-demo", checkpoints=[checkpoint]),
        )


def test_checkpoint_list_strict_reports_missing_from_empty_ledger(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys,
) -> None:
    run_dir, _ = _write_switchable_run(
        tmp_path,
        "spec-run-1",
        state_updates={
            "checkpoint_policy_version": 2,
            "phase_completion_outcomes": [
                {"completion_id": "a" * 32, "phase": "phase1-discover", "outcome": "executed", "checkpoint": "required"}
            ],
        },
    )
    (tmp_path / "runs" / ".current").write_text(run_dir.name, encoding="utf-8")
    monkeypatch.setattr(
        "harness.phase_graph.load_workspace_phase_graph",
        lambda _root: (
            _CoverageGraph({"phase1-discover": ("required", "supported")}),
            tmp_path / ".echelon" / "runtime",
        ),
    )

    with pytest.raises(SystemExit) as exc:
        run_checkpoint_command(["list", "--strict"], project_root=tmp_path)

    assert exc.value.code == 2
    output = capsys.readouterr().out
    assert "(none)" in output
    assert "COVERAGE" in output
    assert "missing" in output


def test_checkpoint_list_rejects_ambiguous_numeric_spec_run(
    tmp_path: Path,
    capsys,
) -> None:
    _write_switchable_run(tmp_path, "spec-run-a", spec_id="001-alpha")
    _write_switchable_run(tmp_path, "spec-run-b", spec_id="001-beta")

    with pytest.raises(SystemExit) as exc:
        run_checkpoint_command(["list", "--spec", "001"], project_root=tmp_path)

    assert exc.value.code == 1
    error = capsys.readouterr().err
    assert "spec-run-a" in error
    assert "spec-run-b" in error


def test_checkpoint_list_strict_does_not_fail_legacy_untracked(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys,
) -> None:
    run_dir, _ = _write_switchable_run(
        tmp_path,
        "spec-run-1",
        state_updates={"completed_phases": ["phase1-discover"]},
    )
    (tmp_path / "runs" / ".current").write_text(run_dir.name, encoding="utf-8")
    monkeypatch.setattr(
        "harness.phase_graph.load_workspace_phase_graph",
        lambda _root: (
            _CoverageGraph({"phase1-discover": ("required", "supported")}),
            tmp_path / ".echelon" / "runtime",
        ),
    )

    run_checkpoint_command(["list", "--strict"], project_root=tmp_path)

    assert "legacy-untracked" in capsys.readouterr().out


def test_checkpoint_list_rejects_unknown_arguments(
    tmp_path: Path,
    capsys,
) -> None:
    run_dir, _ = _write_switchable_run(tmp_path, "spec-run-1")
    (tmp_path / "runs" / ".current").write_text(run_dir.name, encoding="utf-8")

    with pytest.raises(SystemExit) as exc:
        run_checkpoint_command(["list", "--unknown"], project_root=tmp_path)

    assert exc.value.code == 1
    assert "Usage:" in capsys.readouterr().err


def test_checkpoint_list_requires_spec_when_no_active_spec(tmp_path: Path, capsys) -> None:
    with pytest.raises(SystemExit) as exc:
        run_checkpoint_command(["list"], project_root=tmp_path)

    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "No active spec resolved" in err
    assert "echelon spec checkpoint list --spec 001" in err


def test_checkpoint_list_prints_spec_scoped_ledger(tmp_path: Path, capsys) -> None:
    _, spec_dir = _write_switchable_run(tmp_path, "spec-run-1")
    record_checkpoint_metadata(
        spec_dir,
        PhaseCheckpoint(
            id="phase3-plan",
            spec_id="001-demo",
            phase="phase3-plan",
            next_phase="phase3-consensus",
            commit="abcdef123456",
            metadata_commit="",
            source="auto",
            run_id="squad-1",
            created_at="2026-07-04T12:00:00Z",
        ),
    )

    run_checkpoint_command(["list", "--spec", "001"], project_root=tmp_path)

    out = capsys.readouterr().out
    assert "CHECKPOINTS - spec 001-demo" in out
    assert "phase3-plan" in out
    assert "abcdef1" in out


def test_checkpoint_list_explains_ledger_order_and_marks_latest_phase_occurrence(
    tmp_path: Path,
    capsys,
) -> None:
    _, spec_dir = _write_switchable_run(tmp_path, "spec-run-1")
    checkpoints = [
        PhaseCheckpoint(
            id="phase1-what",
            spec_id="001-demo",
            phase="phase1-what",
            next_phase="phase1-understanding",
            commit="1111111" + ("a" * 33),
            metadata_commit="",
            source="auto",
            run_id="squad-1",
            created_at="2026-07-26T03:00:00+00:00",
            completion_id="1" * 32,
        ),
        PhaseCheckpoint(
            id="phase1-lexicon",
            spec_id="001-demo",
            phase="phase1-lexicon",
            next_phase="checkpoint-assess",
            commit="2222222" + ("b" * 33),
            metadata_commit="",
            source="auto",
            run_id="squad-1",
            created_at="2026-07-26T02:00:00Z",
            completion_id="2" * 32,
        ),
        PhaseCheckpoint(
            id="phase1-what",
            spec_id="001-demo",
            phase="phase1-what",
            next_phase="phase1-understanding",
            commit="3333333" + ("c" * 33),
            metadata_commit="",
            source="auto",
            run_id="squad-1",
            created_at="2026-07-26T01:00:00Z",
            completion_id="3" * 32,
        ),
    ]
    for checkpoint in checkpoints:
        record_checkpoint_metadata(spec_dir, checkpoint)

    run_checkpoint_command(["list", "--spec", "001"], project_root=tmp_path)

    out = capsys.readouterr().out
    assert "Order: oldest -> newest (ledger order)" in out
    assert "phase-only rewind selects the last matching row" in out
    assert "CREATED UTC" in out
    assert "LATEST" in out
    assert "2026-07-26 03:00:00" in out
    assert out.index("1111111") < out.index("2222222") < out.index("3333333")
    lines = out.splitlines()
    first_what = next(line for line in lines if "1111111" in line)
    lexicon = next(line for line in lines if "2222222" in line)
    last_what = next(line for line in lines if "3333333" in line)
    assert " yes " not in first_what
    assert " yes " in lexicon
    assert " yes " in last_what


def test_terminal_gate_recovery_uses_latest_registered_predecessor_commit(
    tmp_path: Path,
) -> None:
    run_dir, spec_dir = _write_switchable_run(tmp_path, "spec-run-1")
    (tmp_path / "runs" / ".current").write_text(
        run_dir.name,
        encoding="utf-8",
    )
    for index, commit in enumerate(("1" * 40, "2" * 40), start=1):
        record_checkpoint_metadata(
            spec_dir,
            PhaseCheckpoint(
                id="phase1-lexicon",
                spec_id="001-demo",
                phase="phase1-lexicon",
                next_phase="checkpoint-assess",
                commit=commit,
                metadata_commit="",
                source="auto",
                run_id=run_dir.name,
                created_at=f"2026-08-23T12:0{index}:00+00:00",
                completion_id=str(index) * 32,
            ),
        )
    decision = build_blocked_decision_v2(
        decision_id="dec-terminal-gate",
        status="resolved",
        source_kind="human_gate",
        producer_id="checkpoint-assess",
        source_phase="checkpoint-assess",
        reason_code="checkpoint_assess_decision_required",
        classification="material",
        question="Approve the reviewed Phase 1 boundary?",
        options=[
            {
                "id": "approve",
                "label": "Approve",
                "description": "Continue to feasibility assessment.",
                "recommended": True,
                "risk_level": "low",
                "next_phase": "phase2-decide",
                "outcome": "approved",
            },
            {
                "id": "reject",
                "label": "Reject",
                "description": "Stop for specification revision.",
                "recommended": False,
                "risk_level": "low",
                "next_phase": "terminal-blocked",
                "outcome": "rejected",
            },
        ],
        recommended_answer=None,
        risk_level="low",
        resolution_handler="gate_outcome",
        autonomy_mode="banzai",
        source_state_revision=3,
        selected_option_id="reject",
        resolved_by="user",
        now="2026-08-23T12:00:00+00:00",
        resolved_at="2026-08-23T12:05:00+00:00",
    )
    state_path = run_dir / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state.update(
        {
            "status": "blocked",
            "phase": "terminal-blocked",
            "blocked_reason": "gate_rejected",
            "blocked_decision": decision,
            "escalation_question": decision["question"],
            "escalation_options": decision["options"],
            "escalation_resolved": True,
        }
    )
    state_path.write_text(json.dumps(state), encoding="utf-8")

    action = _classify_run_recovery(state, project_root=tmp_path)

    assert action.kind == "safe_rewind"
    assert action.phase == "phase1-lexicon"
    assert action.command == (
        "echelon spec rewind phase1-lexicon --commit "
        + "2" * 40
        + " --next-phase checkpoint-assess"
        + " --confirm"
    )


def test_terminal_gate_displayed_rewind_selects_exact_colliding_ledger_row(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from echelon.cli_app import app

    run_dir, spec_dir = _write_switchable_run(tmp_path, "spec-run-collision")
    (tmp_path / "runs" / ".current").write_text(run_dir.name, encoding="utf-8")
    (spec_dir / "spec.md").write_text("# Intended checkpoint\n", encoding="utf-8")
    (tmp_path / ".gitignore").write_text(
        "/.echelon/\n"
        "/runs/.current\n"
        "/runs/*/state.json*\n"
        "/runs/*/state.lock\n"
        "/runs/*/.echelon/\n"
        "/runs/*/specs/*/.echelon/\n",
        encoding="utf-8",
    )
    _git(tmp_path, "init", "-b", spec_dir.name)
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test User")
    _git(tmp_path, "add", ".gitignore", spec_dir.relative_to(tmp_path).as_posix())
    _git(tmp_path, "commit", "-m", "intended checkpoint")
    shared_commit = _git(tmp_path, "rev-parse", "HEAD")
    intended = PhaseCheckpoint(
        id="phase1-lexicon",
        spec_id=spec_dir.name,
        phase="phase1-lexicon",
        next_phase="checkpoint-assess",
        commit=shared_commit,
        metadata_commit="",
        source="auto",
        run_id=run_dir.name,
        created_at="2026-08-23T12:00:00+00:00",
        completion_id="1" * 32,
    )
    collision = PhaseCheckpoint(
        id="phase1-lexicon",
        spec_id=spec_dir.name,
        phase="phase1-lexicon",
        next_phase="checkpoint-plan",
        commit=shared_commit,
        metadata_commit="",
        source="legacy-migration",
        run_id=run_dir.name,
        created_at="2026-08-23T12:01:00+00:00",
        completion_id="2" * 32,
        rewind="none",
        rewind_reason="legacy-migration-boundary",
    )
    for checkpoint in (intended, collision):
        record_checkpoint_metadata(spec_dir, checkpoint)
    (spec_dir / "spec.md").write_text("# Later work\n", encoding="utf-8")
    _git(tmp_path, "add", spec_dir.relative_to(tmp_path).as_posix())
    _git(tmp_path, "commit", "-m", "later work")
    later_commit = _git(tmp_path, "rev-parse", "HEAD")
    decision = build_blocked_decision_v2(
        decision_id="dec-colliding-gate",
        status="resolved",
        source_kind="human_gate",
        producer_id="checkpoint-assess",
        source_phase="checkpoint-assess",
        reason_code="checkpoint_assess_decision_required",
        classification="material",
        question="Approve the reviewed Phase 1 boundary?",
        options=[
            {
                "id": "reject",
                "label": "Reject",
                "description": "Return to specification authoring.",
                "recommended": True,
                "risk_level": "low",
                "next_phase": "terminal-blocked",
                "outcome": "rejected",
            }
        ],
        recommended_answer=None,
        risk_level="low",
        resolution_handler="gate_outcome",
        autonomy_mode="banzai",
        source_state_revision=1,
        selected_option_id="reject",
        resolved_by="user",
        now="2026-08-23T12:00:00+00:00",
        resolved_at="2026-08-23T12:00:01+00:00",
    )
    state_path = run_dir / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state.update(
        {
            "state_revision": 2,
            "status": "blocked",
            "phase": "terminal-blocked",
            "blocked_reason": "gate_rejected",
            "autonomy_mode": "banzai",
            "blocked_decision": decision,
            "escalation_question": decision["question"],
            "escalation_options": decision["options"],
            "escalation_resolved": True,
        }
    )
    state_path.write_text(json.dumps(state), encoding="utf-8")
    action = _classify_run_recovery(state, project_root=tmp_path)

    assert action.command == (
        f"echelon spec rewind phase1-lexicon --commit {shared_commit} "
        "--next-phase checkpoint-assess --confirm"
    )
    command_args = shlex.split(action.command)[1:]
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(app, command_args)

    assert result.exit_code == 0, result.output
    assert later_commit != shared_commit
    assert _git(tmp_path, "rev-parse", "HEAD") == shared_commit
    assert (spec_dir / "spec.md").read_text(encoding="utf-8") == "# Intended checkpoint\n"
    assert load_checkpoint_ledger(spec_dir).checkpoints == [intended]

def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _repo_with_spec(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "001-demo")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")
    spec_dir = repo / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text("# Demo\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "base")
    return repo, spec_dir


def test_checkpoint_accept_refuses_dirty_files(tmp_path: Path) -> None:
    from harness.phase_checkpoints import accept_checkpoint_baseline

    repo, spec_dir = _repo_with_spec(tmp_path)
    (spec_dir / "tasks.md").write_text("# Dirty Tasks\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="dirty worktree"):
        accept_checkpoint_baseline(
            project_root=repo,
            spec_dir=spec_dir,
            phase="phase3-plan",
            run_id="squad-1",
        )


def test_checkpoint_accept_moves_ledger_without_creating_commit(tmp_path: Path) -> None:
    from harness.phase_checkpoints import accept_checkpoint_baseline

    repo, spec_dir = _repo_with_spec(tmp_path)
    head = _git(repo, "rev-parse", "HEAD")

    checkpoint = accept_checkpoint_baseline(
        project_root=repo,
        spec_dir=spec_dir,
        phase="phase3-plan",
        run_id="squad-1",
        boundary_completion_id="a" * 32,
    )

    assert _git(repo, "rev-parse", "HEAD") == head
    assert checkpoint.commit == head
    assert checkpoint.boundary_completion_id == "a" * 32


def test_checkpoint_commit_writes_echelon_trailers(tmp_path: Path) -> None:
    from harness.phase_checkpoints import commit_manual_checkpoint

    repo, spec_dir = _repo_with_spec(tmp_path)
    (spec_dir / "tasks.md").write_text("# Manual Tasks\n", encoding="utf-8")

    checkpoint = commit_manual_checkpoint(
        project_root=repo,
        spec_dir=spec_dir,
        phase="phase3-plan",
        run_id="squad-1",
        message="docs: accept manual Phase A checkpoint",
        boundary_completion_id="a" * 32,
    )

    body = _git(repo, "log", "-1", "--format=%B")
    assert checkpoint.source == "user-committed"
    assert "Co-authored-by: Echelon <echelon@b3cognition.dev>" in body
    assert "Echelon-Action: user-committed-checkpoint" in body
    assert "Echelon-Spec: 001-demo" in body
    assert "Echelon-Completion: " + ("a" * 32) in body
    assert "Echelon-Checkpoint-Source: user-committed" in body
    assert checkpoint.boundary_completion_id == "a" * 32


def test_checkpoint_accept_binds_latest_executed_phase_completion(
    tmp_path: Path,
) -> None:
    repo, spec_dir = _repo_with_spec(tmp_path)
    run_dir = repo / "runs" / "spec-20260820-000000"
    run_dir.mkdir(parents=True)
    (repo / "runs" / ".current").write_text(run_dir.name, encoding="utf-8")
    (run_dir / "state.json").write_text(
        json.dumps(
                {
                    "checkpoint_policy_version": 2,
                    "run_id": run_dir.name,
                    "spec_id": "001-demo",
                    "feature_branch": "001-demo",
                    "spec_dir": "specs/001-demo",
                "phase_completion_outcomes": [
                    {
                        "completion_id": "a" * 32,
                        "phase": "phase3-plan",
                        "outcome": "executed",
                    },
                    {
                        "completion_id": "b" * 32,
                        "phase": "phase3-plan",
                        "outcome": "executed",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    _git(repo, "add", "runs")
    _git(repo, "commit", "-m", "test: add run state")

    run_checkpoint_command(
        ["accept", "--phase", "phase3-plan", "--run-id", run_dir.name],
        project_root=repo,
    )

    checkpoint = json.loads(
        (spec_dir / ".echelon" / "checkpoints.json").read_text(encoding="utf-8")
    )["checkpoints"][-1]
    assert checkpoint["source"] == "user-accepted"
    assert checkpoint["boundary_completion_id"] == "b" * 32


def test_checkpoint_list_uses_active_spec_from_run_state(tmp_path: Path, capsys) -> None:
    spec_dir = (
        tmp_path
        / "runs"
        / "spec-20260704-120000"
        / "specs"
        / "001-demo"
    )
    spec_dir.mkdir(parents=True)
    record_checkpoint_metadata(
        spec_dir,
        PhaseCheckpoint(
            id="phase3-plan",
            spec_id="001-demo",
            phase="phase3-plan",
            next_phase="phase3-consensus",
            commit="abcdef123456",
            metadata_commit="",
            source="auto",
            run_id="squad-1",
            created_at="2026-07-04T12:00:00Z",
        ),
    )
    run_dir = tmp_path / "runs" / "spec-20260704-120000"
    (tmp_path / "runs" / ".current").write_text(run_dir.name, encoding="utf-8")
    (run_dir / "state.json").write_text(
        json.dumps(
            {
                "run_id": run_dir.name,
                "spec_id": "001-demo",
                "feature_branch": "001-demo",
                "spec_dir": "runs/spec-20260704-120000/specs/001-demo",
            }
        ),
        encoding="utf-8",
    )

    run_checkpoint_command(["list"], project_root=tmp_path)

    out = capsys.readouterr().out
    assert "CHECKPOINTS - spec 001-demo" in out
    assert "phase3-plan" in out


def test_checkpoint_list_spec_prefers_matching_active_staging_spec(
    tmp_path: Path,
    capsys,
) -> None:
    stale_spec_dir = tmp_path / "specs" / "001-old-feature"
    stale_spec_dir.mkdir(parents=True)
    record_checkpoint_metadata(
        stale_spec_dir,
        PhaseCheckpoint(
            id="phase3-plan",
            spec_id="001-old-feature",
            phase="phase3-plan",
            next_phase="phase3-consensus",
            commit="oldabcdef123",
            metadata_commit="",
            source="auto",
            run_id="old-run",
            created_at="2026-07-04T11:00:00Z",
        ),
    )
    active_spec_dir = tmp_path / "runs" / "spec-20260704-120000" / "staging"
    active_spec_dir.mkdir(parents=True)
    record_checkpoint_metadata(
        active_spec_dir,
        PhaseCheckpoint(
            id="phase1-why1",
            spec_id="001-simple-notes",
            phase="phase1-why1",
            next_phase="phase1-why1",
            commit="newabcdef123",
            metadata_commit="",
            source="auto",
            run_id="squad-1",
            created_at="2026-07-04T12:00:00Z",
        ),
    )
    run_dir = active_spec_dir.parent
    (tmp_path / "runs" / ".current").write_text(run_dir.name, encoding="utf-8")
    (run_dir / "state.json").write_text(
        json.dumps(
                {
                    "run_id": run_dir.name,
                    "spec_id": "001-simple-notes",
                    "feature_branch": "001-simple-notes",
                    "spec_dir": "runs/spec-20260704-120000/staging",
            }
        ),
        encoding="utf-8",
    )

    run_checkpoint_command(["list", "--spec", "001"], project_root=tmp_path)

    out = capsys.readouterr().out
    assert "CHECKPOINTS - spec 001-simple-notes" in out
    assert "phase1-why1" in out
    assert "oldabcd" not in out


def test_checkpoint_list_without_spec_uses_active_staging_spec(
    tmp_path: Path,
    capsys,
) -> None:
    active_spec_dir = tmp_path / "runs" / "spec-20260704-120000" / "staging"
    active_spec_dir.mkdir(parents=True)
    record_checkpoint_metadata(
        active_spec_dir,
        PhaseCheckpoint(
            id="phase1-why1",
            spec_id="001-simple-notes",
            phase="phase1-why1",
            next_phase="phase1-why1",
            commit="newabcdef123",
            metadata_commit="",
            source="auto",
            run_id="squad-1",
            created_at="2026-07-04T12:00:00Z",
        ),
    )
    run_dir = active_spec_dir.parent
    (tmp_path / "runs" / ".current").write_text(run_dir.name, encoding="utf-8")
    (run_dir / "state.json").write_text(
        json.dumps(
                {
                    "run_id": run_dir.name,
                    "spec_id": "001-simple-notes",
                    "feature_branch": "001-simple-notes",
                    "spec_dir": "runs/spec-20260704-120000/staging",
            }
        ),
        encoding="utf-8",
    )

    run_checkpoint_command(["list"], project_root=tmp_path)

    out = capsys.readouterr().out
    assert "CHECKPOINTS - spec 001-simple-notes" in out
    assert "phase1-why1" in out


def test_checkpoint_list_prefers_existing_active_run_spec_over_published(
    tmp_path: Path,
    capsys,
) -> None:
    published_spec_dir = tmp_path / "specs" / "001-simple-notes"
    published_spec_dir.mkdir(parents=True)

    active_spec_dir = tmp_path / "runs" / "spec-20260704-120000" / "specs" / "001-simple-notes"
    active_spec_dir.mkdir(parents=True)
    record_checkpoint_metadata(
        active_spec_dir,
        PhaseCheckpoint(
            id="phase3-sentinel",
            spec_id="001-simple-notes",
            phase="phase3-sentinel",
            next_phase="phase3-plan",
            commit="newabcdef123",
            metadata_commit="",
            source="auto",
            run_id="squad-1",
            created_at="2026-07-04T12:00:00Z",
        ),
    )
    run_dir = active_spec_dir.parents[1]
    (tmp_path / "runs" / ".current").write_text(run_dir.name, encoding="utf-8")
    (run_dir / "state.json").write_text(
        json.dumps(
                {
                    "run_id": run_dir.name,
                    "spec_id": "001-simple-notes",
                    "feature_branch": "001-simple-notes",
                    "spec_dir": "runs/spec-20260704-120000/specs/001-simple-notes",
                "published_spec_dir": "specs/001-simple-notes",
            }
        ),
        encoding="utf-8",
    )

    run_checkpoint_command(["list"], project_root=tmp_path)

    out = capsys.readouterr().out
    assert "CHECKPOINTS - spec 001-simple-notes" in out
    assert "phase3-sentinel" in out


def test_checkpoint_migrate_previews_then_confirms_exact_run(
    tmp_path: Path,
    capsys,
) -> None:
    repo, spec_dir = _repo_with_spec(tmp_path)
    run_dir = repo / "runs" / "spec-run-legacy"
    staging = run_dir / "staging"
    staging.mkdir(parents=True)
    (staging / "glossary.md").write_text("terms\n", encoding="utf-8")
    (run_dir / "state.json").write_text(
        json.dumps(
            {
                "run_id": run_dir.name,
                "spec_id": "001-demo",
                "feature_branch": "001-demo",
                "spec_dir": spec_dir.relative_to(repo).as_posix(),
                "state_revision": 0,
                "completed_phases": ["phase1-discover"],
                "phase": "phase1-why1",
            }
        ),
        encoding="utf-8",
    )
    _git(repo, "add", "runs/spec-run-legacy/state.json")
    _git(repo, "commit", "-m", "test: add legacy run")

    run_checkpoint_command(
        ["migrate", "--spec", run_dir.name],
        project_root=repo,
    )

    preview = capsys.readouterr().out
    assert "glossary.md" in preview
    assert (
        f"echelon spec checkpoint migrate --spec {run_dir.name} --confirm"
        in preview
    )
    assert not (spec_dir / "glossary.md").exists()

    run_checkpoint_command(
        ["migrate", "--spec", run_dir.name, "--confirm"],
        project_root=repo,
    )

    assert (spec_dir / "glossary.md").read_text(encoding="utf-8") == "terms\n"
    assert "Migration checkpoint" in capsys.readouterr().out
