"""Regression tests for removing an unused target from an active spec run."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness.blocked_decision import build_blocked_decision_v2
from harness.recovery_instruction import RecoveryInstruction, RecoveryKind
from harness.spec_frontmatter import read_targets, write_targets


def _write_spec(spec_dir: Path) -> None:
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text("# Video clips\n", encoding="utf-8")
    write_targets(spec_dir, ["sources/web", "sources/api"])
    for name in ("tasks.md", "critical-path.md", "risk-matrix.md", "dependencies.md"):
        (spec_dir / name).write_text(f"# {name}\n", encoding="utf-8")


def test_drop_target_reopens_active_run_at_planning_and_invalidates_task_outputs(
    tmp_path: Path,
) -> None:
    from echelon.cli import _cmd_drop_target

    run_dir = tmp_path / "runs" / "spec-run"
    active_spec = run_dir / "specs" / "002-video"
    published_spec = tmp_path / "specs" / "002-video"
    _write_spec(active_spec)
    _write_spec(published_spec)
    (tmp_path / "runs" / ".current").write_text(run_dir.name, encoding="utf-8")
    (run_dir / "state.json").write_text(
        json.dumps(
            {
                "run_id": run_dir.name,
                "spec_id": "002-video",
                "spec_dir": "runs/spec-run/specs/002-video",
                "published_spec_dir": "specs/002-video",
                "status": "blocked",
                "phase": "terminal-blocked",
                "blocked_reason": "unused declared target",
                "implementation_targets": ["sources/web", "sources/api"],
                "completed_phases": ["phase3-how", "phase3-sentinel"],
            }
        ),
        encoding="utf-8",
    )

    _cmd_drop_target(
        ["002-video", "sources/api", "--confirm"],
        project_root=tmp_path,
    )

    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    assert state["implementation_targets"] == ["sources/web"]
    assert state["phase"] == "phase3-plan"
    assert state["status"] == "running"
    assert state["blocked_reason"] is None
    assert read_targets(active_spec) == ["sources/web"]
    assert read_targets(published_spec) == ["sources/web"]
    for spec_dir in (active_spec, published_spec):
        for name in ("tasks.md", "critical-path.md", "risk-matrix.md", "dependencies.md"):
            assert not (spec_dir / name).exists()


def test_drop_target_refuses_while_same_spec_mutation_is_locked(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from echelon.cli import _cmd_drop_target
    from echelon.spec_lifecycle import SpecMutationLock

    run_dir = tmp_path / "runs" / "spec-run"
    active_spec = run_dir / "specs" / "002-video"
    published_spec = tmp_path / "specs" / "002-video"
    _write_spec(active_spec)
    _write_spec(published_spec)
    (tmp_path / "runs" / ".current").write_text(run_dir.name, encoding="utf-8")
    (run_dir / "state.json").write_text(
        json.dumps(
            {
                "run_id": run_dir.name,
                "spec_id": "002-video",
                "spec_dir": "runs/spec-run/specs/002-video",
                "published_spec_dir": "specs/002-video",
                "status": "blocked",
                "implementation_targets": ["sources/web", "sources/api"],
            }
        ),
        encoding="utf-8",
    )

    with SpecMutationLock.acquire(tmp_path, "002-video", "retarget-held"):
        with pytest.raises(SystemExit) as exc:
            _cmd_drop_target(
                ["002-video", "sources/api", "--confirm"],
                project_root=tmp_path,
            )

    assert exc.value.code == 1
    assert "retarget-held" in capsys.readouterr().err
    assert read_targets(active_spec) == ["sources/web", "sources/api"]


def test_drop_target_refuses_terminal_decision_without_mutating_files_or_state(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from echelon.cli import _cmd_drop_target

    run_dir = tmp_path / "runs" / "spec-run"
    active_spec = run_dir / "specs" / "002-video"
    published_spec = tmp_path / "specs" / "002-video"
    _write_spec(active_spec)
    _write_spec(published_spec)
    (tmp_path / "runs" / ".current").write_text(run_dir.name, encoding="utf-8")
    decision = build_blocked_decision_v2(
        decision_id="dec-unrelated-failure",
        status="failed",
        source_kind="provider_escalation",
        producer_id="phase1-tracker",
        source_phase="phase1-tracker",
        reason_code="human_clarification_required",
        classification="material",
        question="Which repository should be inspected?",
        options=[],
        recommended_answer="Inspect the application source.",
        risk_level="low",
        resolution_handler="clarification_resume",
        autonomy_mode="banzai",
        source_state_revision=1,
        attempts=2,
        failure_code="resolution_attempts_exhausted",
        now="2026-08-23T12:00:00+00:00",
    )
    state_path = run_dir / "state.json"
    state_path.write_text(
        json.dumps(
            {
                "run_id": run_dir.name,
                "state_revision": 2,
                "spec_id": "002-video",
                "spec_dir": "runs/spec-run/specs/002-video",
                "published_spec_dir": "specs/002-video",
                "status": "blocked",
                "phase": "phase1-tracker",
                "blocked_reason": decision["reason_code"],
                "autonomy_mode": "banzai",
                "implementation_targets": ["sources/web", "sources/api"],
                "blocked_decision": decision,
                "recovery_instruction": RecoveryInstruction(
                    kind=RecoveryKind.MANUAL_DIAGNOSIS,
                    reason_code=str(decision["reason_code"]),
                    phase="",
                    requires_human_input=False,
                    schema_version=2,
                    decision_id=str(decision["id"]),
                ).to_dict(),
                "escalation_question": decision["question"],
                "escalation_options": [],
            }
        ),
        encoding="utf-8",
    )
    before_state = state_path.read_bytes()
    before_active = {path.name: path.read_bytes() for path in active_spec.iterdir()}
    before_published = {
        path.name: path.read_bytes() for path in published_spec.iterdir()
    }

    with pytest.raises(SystemExit) as raised:
        _cmd_drop_target(
            ["002-video", "sources/api", "--confirm"],
            project_root=tmp_path,
        )

    assert raised.value.code == 1
    assert "decision authority" in capsys.readouterr().err.lower()
    assert state_path.read_bytes() == before_state
    assert {path.name: path.read_bytes() for path in active_spec.iterdir()} == before_active
    assert {
        path.name: path.read_bytes() for path in published_spec.iterdir()
    } == before_published
