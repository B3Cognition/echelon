"""Tests for safe squad rewind checkpoints."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from echelon.cli import (
    _ROADMAP_PHASES,
    _cmd_repair_traceability,
    _cmd_rewind,
    _reset_rewind_state,
)
from echelon.rewind import RewindResult
from echelon.spec_lifecycle import PhaseAExecutionLock
from harness.phase_checkpoints import (
    PhaseCheckpoint,
    checkpoint_targets,
    load_checkpoint_ledger,
    record_checkpoint_metadata,
)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _write_real_constitution(project_root: Path) -> None:
    const = project_root / ".specify" / "memory" / "constitution.md"
    const.parent.mkdir(parents=True)
    const.write_text("# Constitution\n\nReal project rules.\n", encoding="utf-8")


def _write_run_state(project_root: Path, state: dict) -> Path:
    run_dir = project_root / "runs" / "spec-20260618-073106-635192"
    run_dir.mkdir(parents=True)
    (project_root / "runs" / ".current").write_text(run_dir.name, encoding="utf-8")
    (run_dir / "state.json").write_text(json.dumps(state), encoding="utf-8")
    return run_dir


def _write_phase3_spec(project_root: Path) -> Path:
    spec_dir = project_root / "specs" / "006-element-creator"
    contracts = spec_dir / "contracts"
    contracts.mkdir(parents=True)
    (spec_dir / "spec.md").write_text("# Spec\n", encoding="utf-8")
    (spec_dir / "plan.md").write_text("# Plan\n", encoding="utf-8")
    (spec_dir / "research.md").write_text("# Research\n", encoding="utf-8")
    (spec_dir / "data-model.md").write_text("# Data Model\n", encoding="utf-8")
    (contracts / "elements-crud.md").write_text("# Contract\n", encoding="utf-8")
    (spec_dir / "test-strategy.md").write_text("# Test Strategy\n", encoding="utf-8")
    (spec_dir / "test-architecture.md").write_text("# Test Architecture\n", encoding="utf-8")
    (spec_dir / "coverage-map.md").write_text("# Coverage Map\n", encoding="utf-8")
    (spec_dir / "tasks.md").write_text("# Tasks\n", encoding="utf-8")
    (spec_dir / "critical-path.md").write_text("# Critical Path\n", encoding="utf-8")
    (spec_dir / "risk-matrix.md").write_text("# Risk Matrix\n", encoding="utf-8")
    (spec_dir / "dependencies.md").write_text("# Dependencies\n", encoding="utf-8")
    return spec_dir


def _record_checkpoints(
    spec_dir: Path,
    *phases: str,
    commit: str = "abcdef0",
) -> None:
    for phase in phases:
        record_checkpoint_metadata(
            spec_dir,
            PhaseCheckpoint(
                id=phase,
                spec_id=spec_dir.name,
                phase=phase,
                next_phase=phase,
                commit=commit,
                metadata_commit="",
                source="auto",
                run_id="squad-1",
                created_at="2026-07-18T12:00:00Z",
            ),
        )


def _traceability_repair_run(project_root: Path) -> tuple[Path, Path]:
    from echelon.product_inputs import (
        immutable_product_input_tree_digest,
        parse_input_declaration,
        resolve_product_inputs,
    )

    run_dir = project_root / "runs" / "spec-20260618-073106-635192"
    source = project_root / "requirements.md"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("A requirement.\n", encoding="utf-8")
    resolution = resolve_product_inputs(
        project_root,
        run_dir,
        [parse_input_declaration("requirement:requirements.md")],
    )
    spec_dir = run_dir / "specs" / "006-element-creator"
    spec_dir.mkdir(parents=True)
    (spec_dir / "tasks.md").write_text(
        "- [ ] T-001 complexity=standard phase=foundation req=FR-1 depends=none target=sources/web\n"
        "- [ ] T-S01 complexity=standard phase=foundation req=INFRA depends=none target=sources/web\n",
        encoding="utf-8",
    )
    resolution.traceability_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "requirements": [
                    {
                        "input_unit_id": "IN-REQ-1",
                        "disposition": "included",
                        "rationale": "Mapped.",
                        "spec_ids": ["FR-1"],
                        "task_ids": ["T-001", "T-S01"],
                        "targets": ["sources/web"],
                    }
                ],
                "references": [],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    resolution.traceability_markdown_path.write_text(
        "# Product Input Traceability\n\nlegacy\n",
        encoding="utf-8",
    )
    product_inputs = resolution.state_payload(project_root)
    product_inputs["tree_hash"] = immutable_product_input_tree_digest(
        resolution.inputs_dir
    )
    state = {
        "run_id": run_dir.name,
        "state_revision": 0,
        "status": "blocked",
        "phase": "terminal-blocked",
        "blocked_reason": "phase_a_readiness_failed",
        "phase_a_readiness_blockers": [
            "IN-REQ-1: task T-S01 does not reference the mapped specification IDs"
        ],
        "spec_dir": spec_dir.relative_to(project_root).as_posix(),
        "product_inputs": product_inputs,
        "implementation_targets": ["sources/web"],
        "completed_phases": [
            "phase3-plan",
            "phase3-consensus",
            "checkpoint-plan",
        ],
    }
    (project_root / "runs" / ".current").write_text(
        run_dir.name,
        encoding="utf-8",
    )
    (run_dir / "state.json").write_text(json.dumps(state), encoding="utf-8")
    return run_dir, resolution.traceability_path


def test_rewind_phase3_sentinel_resets_state_and_cleans_downstream_artifacts(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    _write_real_constitution(tmp_path)
    spec_dir = _write_phase3_spec(tmp_path)
    _record_checkpoints(spec_dir, "phase3-how", "phase3-sentinel")
    poisoned_spec_dir = (
        tmp_path
        / "runs"
        / "spec-20260618-073106-635192"
        / "specs"
        / "006-element-creator"
    )
    run_dir = _write_run_state(
        tmp_path,
        {
            "status": "done",
            "phase": "phase4-document",
            "spec_dir": str(poisoned_spec_dir),
            "completed_phases": [
                "phase3-how",
                "phase3-sentinel",
                "phase3-plan",
                "phase3-consensus",
                "checkpoint-plan",
                "phase4-document",
            ],
            "phase_dispatch_counts": {
                "phase3-how": 1,
                "phase3-sentinel": 2,
                "phase3-plan": 3,
                "phase3-consensus": 4,
                "checkpoint-plan": 1,
                "phase4-document": 1,
            },
        },
    )

    monkeypatch.setattr(
        "echelon.rewind.prepare_rewind",
        lambda **_kwargs: RewindResult(
            applied=True,
            spec_id=spec_dir.name,
            checkpoint_id="phase3-sentinel",
            from_commit="abcdef0",
            to_commit="1234567",
            backup_ref="echelon/backup/test",
            message="Rewind complete.",
        ),
    )

    _cmd_rewind(["phase3-sentinel"], project_root=tmp_path)

    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    assert state["status"] == "running"
    assert state["phase"] == "phase3-sentinel"
    assert state["spec_dir"] == "specs/006-element-creator"
    assert state["completed_phases"] == _ROADMAP_PHASES[:_ROADMAP_PHASES.index("phase3-sentinel")]
    assert state["phase_dispatch_counts"] == {"phase3-how": 1}
    assert not (spec_dir / "test-strategy.md").exists()
    assert not (spec_dir / "test-architecture.md").exists()
    assert not (spec_dir / "coverage-map.md").exists()

    captured = capsys.readouterr()
    assert "REWIND COMPLETE" in captured.out
    assert "phase3-sentinel" in captured.out
    assert "echelon spec continue" in captured.out


def test_rewind_phase3_sentinel_cleans_run_local_shadow_outputs(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    _write_real_constitution(tmp_path)
    spec_dir = _write_phase3_spec(tmp_path)
    _record_checkpoints(spec_dir, "phase3-sentinel")
    run_dir = _write_run_state(
        tmp_path,
        {
            "status": "blocked",
            "phase": "terminal-blocked",
            "spec_dir": "specs/006-element-creator",
            "last_dispatch": {"phase_id": "phase3-sentinel"},
            "blocked_reason": "missing_echelon_result",
        },
    )
    run_shadow = run_dir / "specs" / "006-element-creator"
    run_shadow.mkdir(parents=True)
    for name in ("test-strategy.md", "test-architecture.md", "coverage-map.md"):
        (run_shadow / name).write_text(f"# {name}\n", encoding="utf-8")

    monkeypatch.setattr(
        "echelon.rewind.prepare_rewind",
        lambda **_kwargs: RewindResult(
            applied=True,
            spec_id=spec_dir.name,
            checkpoint_id="phase3-sentinel",
            from_commit="abcdef0",
            to_commit="1234567",
            backup_ref="echelon/backup/test",
            message="Rewind complete.",
        ),
    )

    _cmd_rewind(["phase3-sentinel"], project_root=tmp_path)

    assert not (run_shadow / "test-strategy.md").exists()
    assert not (run_shadow / "test-architecture.md").exists()
    assert not (run_shadow / "coverage-map.md").exists()


def test_rewind_refuses_a_target_missing_from_the_active_ledger(
    tmp_path: Path,
    capsys,
) -> None:
    spec_dir = tmp_path / "specs" / "006-element-creator"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text("# Spec\n", encoding="utf-8")
    _write_run_state(
        tmp_path,
        {
            "status": "done",
            "phase": "phase4-document",
            "spec_dir": "specs/006-element-creator",
        },
    )

    with pytest.raises(SystemExit) as exc:
        _cmd_rewind(["phase3-sentinel"], project_root=tmp_path)

    assert exc.value.code == 1
    captured = capsys.readouterr()
    assert "Cannot rewind to phase3-sentinel" in captured.err
    assert "No checkpoints are recorded for this spec" in captured.err


def test_rewind_reports_targets_from_the_active_ledger(
    tmp_path: Path,
    capsys,
) -> None:
    spec_dir = _write_phase3_spec(tmp_path)
    _record_checkpoints(spec_dir, "phase3-plan")
    _write_run_state(
        tmp_path,
        {
            "status": "done",
            "phase": "phase4-document",
            "spec_dir": "specs/006-element-creator",
        },
    )

    with pytest.raises(SystemExit) as exc:
        _cmd_rewind(["phase3-consensus"], project_root=tmp_path)

    assert exc.value.code == 1
    captured = capsys.readouterr()
    assert "checkpoint not found for spec 006-element-creator: phase3-consensus" in captured.err
    assert "phase3-consensus" in captured.err
    assert "Available checkpoints: phase3-plan" in captured.err


def test_rewind_rejects_empty_commit_selector_before_resolving_run(
    tmp_path: Path,
    capsys,
) -> None:
    with pytest.raises(SystemExit) as exc:
        _cmd_rewind(
            ["phase1-what", "--commit", ""],
            project_root=tmp_path,
        )

    assert exc.value.code == 1
    captured = capsys.readouterr()
    assert "Usage: echelon spec rewind" in captured.err
    assert "No active squad run found" not in captured.err


def test_rewind_accepts_and_resets_to_any_active_ledger_checkpoint(
    tmp_path: Path,
    monkeypatch,
) -> None:
    run_dir = _write_run_state(
        tmp_path,
        {
            "status": "blocked",
            "phase": "terminal-blocked",
            "spec_dir": "runs/spec-20260618-073106-635192/specs/004-transform-selector",
            "completed_phases": ["phase1-why1", "phase1-what", "phase2-decide"],
            "phase_dispatch_counts": {
                "phase1-why1": 1,
                "phase1-what": 1,
                "phase2-decide": 1,
            },
        },
    )
    spec_dir = run_dir / "specs" / "004-transform-selector"
    spec_dir.mkdir(parents=True)
    for phase in ("phase1-why1", "phase1-what", "phase2-decide"):
        record_checkpoint_metadata(
            spec_dir,
            PhaseCheckpoint(
                id=phase,
                spec_id="004-transform-selector",
                phase=phase,
                next_phase=phase,
                commit="abcdef0",
                metadata_commit="",
                source="auto",
                run_id="squad-4",
                created_at="2026-07-18T12:00:00Z",
            ),
        )

    received: dict[str, object] = {}

    def fake_prepare_rewind(**kwargs):
        received.update(kwargs)
        return RewindResult(
            applied=True,
            spec_id="004-transform-selector",
            checkpoint_id="phase1-what",
            from_commit="abcdef0",
            to_commit="1234567",
            backup_ref="echelon/backup/test",
            message="Rewind complete.",
        )

    monkeypatch.setattr("echelon.rewind.prepare_rewind", fake_prepare_rewind)

    _cmd_rewind(["phase1-what", "--confirm"], project_root=tmp_path)

    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    assert received["target"] == "phase1-what"
    assert state["phase"] == "phase1-what"
    assert state["completed_phases"] == _ROADMAP_PHASES[:_ROADMAP_PHASES.index("phase1-what")]
    assert state["phase_dispatch_counts"] == {"phase1-why1": 1}


def test_rewind_phase1_what_uses_the_active_ledger_for_preview_and_confirm(
    tmp_path: Path,
) -> None:
    _git(tmp_path, "init", "-b", "004-transform-selector")
    _git(tmp_path, "config", "user.email", "tests@example.com")
    _git(tmp_path, "config", "user.name", "Echelon Tests")
    (tmp_path / ".gitignore").write_text(
        "/runs/.current\n/runs/*/state.json\n/specs/*/.echelon/checkpoints.json\n",
        encoding="utf-8",
    )
    spec_dir = tmp_path / "specs" / "004-transform-selector"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text("# Initial\n", encoding="utf-8")
    _git(tmp_path, "add", ".gitignore", "specs/004-transform-selector/spec.md")
    _git(tmp_path, "commit", "-m", "checkpoint")
    checkpoint = _git(tmp_path, "rev-parse", "HEAD")
    _record_checkpoints(spec_dir, "phase1-what", commit=checkpoint)
    (spec_dir / "spec.md").write_text("# Later\n", encoding="utf-8")
    _git(tmp_path, "add", "specs/004-transform-selector/spec.md")
    _git(tmp_path, "commit", "-m", "later")
    later = _git(tmp_path, "rev-parse", "HEAD")
    run_dir = _write_run_state(
        tmp_path,
        {
            "status": "blocked",
            "phase": "terminal-blocked",
            "spec_dir": "specs/004-transform-selector",
            "completed_phases": ["phase1-what", "phase2-decide"],
            "phase_dispatch_counts": {"phase1-what": 1, "phase2-decide": 1},
        },
    )

    _cmd_rewind(["phase1-what"], project_root=tmp_path)

    assert _git(tmp_path, "rev-parse", "HEAD") == later
    preview_state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    assert preview_state["phase"] == "terminal-blocked"

    _cmd_rewind(["phase1-what", "--confirm"], project_root=tmp_path)

    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    assert _git(tmp_path, "rev-parse", "HEAD") == checkpoint
    assert state["phase"] == "phase1-what"
    assert state["completed_phases"] == _ROADMAP_PHASES[:_ROADMAP_PHASES.index("phase1-what")]
    assert state["phase_dispatch_counts"] == {}


def test_rewind_selects_historical_duplicate_phase_by_commit_and_truncates_there(
    tmp_path: Path,
) -> None:
    _git(tmp_path, "init", "-b", "004-transform-selector")
    _git(tmp_path, "config", "user.email", "tests@example.com")
    _git(tmp_path, "config", "user.name", "Echelon Tests")
    (tmp_path / ".gitignore").write_text(
        "/runs/.current\n/runs/*/state.json\n/specs/*/.echelon/checkpoints.json\n",
        encoding="utf-8",
    )
    spec_dir = tmp_path / "specs" / "004-transform-selector"
    spec_dir.mkdir(parents=True)

    checkpoints: list[PhaseCheckpoint] = []
    for index, content in enumerate(("# First\n", "# Second\n", "# Third\n"), start=1):
        (spec_dir / "spec.md").write_text(content, encoding="utf-8")
        _git(tmp_path, "add", ".gitignore", "specs/004-transform-selector/spec.md")
        _git(tmp_path, "commit", "-m", f"checkpoint {index}")
        commit = _git(tmp_path, "rev-parse", "HEAD")
        checkpoint = PhaseCheckpoint(
            id="phase1-what",
            spec_id="004-transform-selector",
            phase="phase1-what",
            next_phase="phase1-understanding",
            commit=commit,
            metadata_commit="",
            source="auto",
            run_id="spec-run",
            created_at=f"2026-07-26T0{index}:00:00Z",
            completion_id=f"{index:032x}",
        )
        record_checkpoint_metadata(spec_dir, checkpoint)
        checkpoints.append(checkpoint)

    _write_run_state(
        tmp_path,
        {
            "status": "blocked",
            "phase": "terminal-blocked",
            "spec_dir": "specs/004-transform-selector",
            "completed_phases": ["phase1-what", "phase1-lexicon"],
        },
    )
    selected = checkpoints[1]

    _cmd_rewind(
        ["phase1-what", "--commit", selected.commit[:8], "--confirm"],
        project_root=tmp_path,
    )

    assert _git(tmp_path, "rev-parse", "HEAD") == selected.commit
    retained = load_checkpoint_ledger(spec_dir).checkpoints
    assert retained == checkpoints[:2]


def test_rewind_refuses_a_run_that_is_still_running(tmp_path: Path, capsys) -> None:
    """A live controller must not be able to overwrite a completed rewind."""
    run_dir = _write_run_state(
        tmp_path,
        {
            "status": "running",
            "phase": "phase2-decide",
            "spec_dir": "specs/004-transform-selector",
        },
    )
    spec_dir = tmp_path / "specs" / "004-transform-selector"
    spec_dir.mkdir(parents=True)
    _record_checkpoints(spec_dir, "phase1-what")
    with PhaseAExecutionLock.acquire(tmp_path, "live-controller"):
        with pytest.raises(SystemExit) as exc:
            _cmd_rewind(["phase1-what", "--confirm"], project_root=tmp_path)

    assert exc.value.code == 1
    assert "still running" in capsys.readouterr().err
    assert (run_dir / "state.json").exists()


def test_rewind_mutation_refuses_shared_spec_mutation_owner(
    tmp_path: Path,
    capsys,
) -> None:
    from echelon.spec_lifecycle import SpecMutationLock

    run_dir = _write_run_state(
        tmp_path,
        {
            "status": "blocked",
            "phase": "phase2-decide",
            "spec_dir": "specs/004-transform-selector",
        },
    )
    spec_dir = tmp_path / "specs" / "004-transform-selector"
    spec_dir.mkdir(parents=True)
    _record_checkpoints(spec_dir, "phase1-what")
    state_before = (run_dir / "state.json").read_bytes()

    with SpecMutationLock.acquire(
        tmp_path,
        "004-transform-selector",
        "retarget-held",
    ):
        with pytest.raises(SystemExit) as exc:
            _cmd_rewind(["phase1-what", "--confirm"], project_root=tmp_path)

    assert exc.value.code == 1
    assert "retarget-held" in capsys.readouterr().err
    assert (run_dir / "state.json").read_bytes() == state_before


def test_confirming_rewind_refuses_when_active_run_changes_before_lock(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    from echelon.spec_lifecycle import SpecMutationLock

    old_run = _write_run_state(
        tmp_path,
        {
            "status": "blocked",
            "phase": "phase2-decide",
            "spec_id": "004-transform-selector",
            "spec_dir": "specs/004-transform-selector",
        },
    )
    old_spec = tmp_path / "specs" / "004-transform-selector"
    old_spec.mkdir(parents=True)
    _record_checkpoints(old_spec, "phase1-what")
    old_state_before = (old_run / "state.json").read_bytes()

    new_run = tmp_path / "runs" / "spec-new-active"
    new_run.mkdir()
    (new_run / "state.json").write_text(
        json.dumps(
            {
                "status": "blocked",
                "phase": "phase2-decide",
                "spec_id": "005-new-active",
                "spec_dir": "specs/005-new-active",
            }
        ),
        encoding="utf-8",
    )

    original_acquire = SpecMutationLock.acquire.__func__

    def switch_before_acquire(cls, project_root, spec_id, operation_id):
        (tmp_path / "runs" / ".current").write_text(
            new_run.name,
            encoding="utf-8",
        )
        return original_acquire(cls, project_root, spec_id, operation_id)

    monkeypatch.setattr(
        SpecMutationLock,
        "acquire",
        classmethod(switch_before_acquire),
    )
    monkeypatch.setattr(
        "echelon.rewind.prepare_rewind",
        lambda **_kwargs: RewindResult(
            applied=True,
            spec_id=old_spec.name,
            checkpoint_id="phase1-what",
            from_commit="1234567",
            to_commit="abcdef0",
            backup_ref="backup",
            message="applied",
        ),
    )

    with pytest.raises(SystemExit) as exc:
        _cmd_rewind(["phase1-what", "--confirm"], project_root=tmp_path)

    assert exc.value.code == 1
    assert "active run changed" in capsys.readouterr().err.lower()
    assert (old_run / "state.json").read_bytes() == old_state_before


def test_rewind_reconstructs_primary_predecessors_for_the_roadmap() -> None:
    """A checkpoint ledger is sparse; the roadmap still needs its prior phases."""
    rewound = _reset_rewind_state(
        {
            "completed_phases": ["phase1-why2"],
            "phase_dispatch_counts": {"phase1-why2": 1},
            "iteration": 6,
        },
        "phase1-what",
        "runs/run-test/specs/001-demo",
        checkpoint_phases_before_target={
            "phase1-why1",
            "phase1-constitution",
            "phase1-why2",
        },
    )

    assert rewound["completed_phases"] == [
        "init",
        "phase1-discover",
        "phase1-synthesizer",
        "phase1-modeler",
        "phase1-tracker",
        "phase1-why1",
        "phase1-constitution",
    ]
    assert "phase1-why2" not in rewound["completed_phases"]
    assert rewound["iteration"] == 0


@pytest.mark.parametrize(
    "target_phase",
    ["phase1-what", "phase1-lexicon-derive", "phase1-lexicon"],
)
def test_rewind_to_spec_authoring_or_gate_resets_spec_lexicon_repair_state(
    target_phase: str,
) -> None:
    rewound = _reset_rewind_state(
        {
            "lexicon_evaluation": "failed",
            "lexicon_pass": False,
            "lexicon_attempts": 3,
            "lexicon_findings": 55,
            "lexicon_report": "runs/spec-1/specs/001-demo/lexicon-validation.json",
            "lexicon_warning_waiver": True,
            "lexicon_gate_exhausted": True,
        },
        target_phase,
        "runs/spec-1/specs/001-demo",
    )

    assert "lexicon_pass" not in rewound
    assert rewound["lexicon_attempts"] == 0
    assert "lexicon_findings" not in rewound
    assert "lexicon_report" not in rewound
    assert "lexicon_warning_waiver" not in rewound
    assert rewound["lexicon_evaluation"] == "pending"
    assert "lexicon_gate_exhausted" not in rewound


@pytest.mark.parametrize(
    "target_phase",
    ["phase1-what", "phase1-understanding", "phase1-why2"],
)
def test_rewind_to_spec_quality_sequence_clears_quality_certificate(
    target_phase: str,
) -> None:
    rewound = _reset_rewind_state(
        {
            "spec_quality_certificate": {
                "spec_sha256": "stale",
                "understanding_report_sha256": "stale",
            },
        },
        target_phase,
        "runs/spec-1/specs/001-demo",
    )

    assert "spec_quality_certificate" not in rewound


def test_rewind_to_lexicon_derivation_preserves_current_quality_certificate() -> None:
    certificate = {
        "spec_sha256": "current",
        "understanding_report_sha256": "current",
    }
    rewound = _reset_rewind_state(
        {"spec_quality_certificate": certificate},
        "phase1-lexicon-derive",
        "runs/spec-1/specs/001-demo",
    )

    assert rewound["spec_quality_certificate"] == certificate


def test_rewind_before_why2_clears_stale_issue_and_why_state() -> None:
    rewound = _reset_rewind_state(
        {
            "issue_resolution_ledger": {"ISS-002": {"status": "selected"}},
            "selected_issue_resolution": "ISS-002",
            "issue_resolution_recovery": {"issue_id": "ISS-002"},
            "issue_resolution_repair_baseline": {"issue_id": "ISS-002"},
            "phase_dispatch_limit_recovery": {"phase": "phase1-what"},
            "issues_log": [{"issue_id": "ISS-002"}],
            "why_fail_count": 2,
            "why2_metric_stagnation_count": 2,
            "why_failure_baseline": {"phase_id": "phase1-why2"},
        },
        "init",
        "runs/spec-1/specs/001-demo",
    )

    for key in (
        "issue_resolution_ledger",
        "selected_issue_resolution",
        "issue_resolution_recovery",
        "issue_resolution_repair_baseline",
        "phase_dispatch_limit_recovery",
        "issues_log",
        "why_failure_baseline",
    ):
        assert key not in rewound
    assert rewound["why_fail_count"] == 0
    assert rewound["why2_metric_stagnation_count"] == 0


def test_rewind_missing_checkpoint_exits_without_traceback(
    tmp_path: Path,
    capsys,
) -> None:
    spec_dir = tmp_path / "specs" / "013-vod-cms-modernization"
    spec_dir.mkdir(parents=True)
    record_checkpoint_metadata(
        spec_dir,
        PhaseCheckpoint(
            id="phase2-decide",
            spec_id="013-vod-cms-modernization",
            phase="phase2-decide",
            next_phase="phase2-strategic-overview",
            commit="397c8bb",
            metadata_commit="",
            source="auto",
            run_id="squad-1",
            created_at="2026-07-08T12:00:00Z",
        ),
    )
    _write_run_state(
        tmp_path,
        {
            "status": "blocked",
            "phase": "terminal-blocked",
            "spec_dir": "specs/013-vod-cms-modernization",
        },
    )

    with pytest.raises(SystemExit) as exc:
        _cmd_rewind(["phase3-plan"], project_root=tmp_path)

    assert exc.value.code == 1
    captured = capsys.readouterr()
    assert "Cannot rewind to phase3-plan" in captured.err
    assert "checkpoint not found for spec 013-vod-cms-modernization: phase3-plan" in captured.err
    assert "Available checkpoints: phase2-decide" in captured.err
    assert "Traceback" not in captured.err


def test_checkpoint_rewind_uses_run_local_ledger_and_resets_run_state(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    run_dir = _write_run_state(
        tmp_path,
        {
            "status": "blocked",
            "phase": "terminal-blocked",
            "blocked_reason": "phase_a_readiness_failed",
            "phase_a_readiness_blockers": ["broken mapping"],
            "spec_dir": "runs/spec-20260618-073106-635192/specs/006-element-creator",
            "completed_phases": ["phase3-how", "phase3-plan", "phase3-consensus"],
        },
    )
    run_spec_dir = run_dir / "specs" / "006-element-creator"
    run_spec_dir.mkdir(parents=True)
    _record_checkpoints(
        run_spec_dir,
        "phase3-how",
        "phase3-plan",
        "phase3-consensus",
    )

    received: dict[str, object] = {}

    def fake_prepare_rewind(**kwargs):
        received.update(kwargs)
        return RewindResult(
            applied=True,
            spec_id="006-element-creator",
            checkpoint_id="phase3-plan",
            from_commit="abcdef0",
            to_commit="1234567",
            backup_ref="echelon/backup/test",
            message="Rewind complete.",
        )

    monkeypatch.setattr("echelon.rewind.prepare_rewind", fake_prepare_rewind)

    _cmd_rewind(["phase3-plan", "--confirm"], project_root=tmp_path)

    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    assert received["spec_dir"] == run_spec_dir
    assert state["status"] == "running"
    assert state["phase"] == "phase3-plan"
    assert state["blocked_reason"] is None
    assert "phase_a_readiness_blockers" not in state
    assert state["completed_phases"] == _ROADMAP_PHASES[:_ROADMAP_PHASES.index("phase3-plan")]
    assert checkpoint_targets(load_checkpoint_ledger(run_spec_dir)) == [
        "phase3-how",
        "phase3-plan",
    ]
    assert "echelon spec continue" in capsys.readouterr().out


def test_retarget_checkpoint_routes_before_generic_cleanup_with_prereset_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir = _write_run_state(
        tmp_path,
        {
            "run_id": "squad-replacement",
            "spec_id": "006-element-creator",
            "feature_branch": "006-element-creator",
            "status": "blocked",
            "phase": "phase0-constitution",
            "spec_dir": "specs/006-element-creator",
            "retarget": {
                "revision_id": "retarget-1",
                "baseline_run_id": "squad-base",
                "replacement_run_id": "squad-replacement",
            },
        },
    )
    spec_dir = tmp_path / "specs" / "006-element-creator"
    spec_dir.mkdir(parents=True)
    checkpoint = PhaseCheckpoint(
        id="retarget-preflight-retarget-1",
        spec_id=spec_dir.name,
        phase="phase4-document",
        next_phase="phase0-constitution",
        commit="b" * 40,
        metadata_commit="b" * 40,
        source="retarget-preflight",
        run_id="squad-base",
        created_at="2026-08-05T00:00:00+00:00",
    )
    record_checkpoint_metadata(spec_dir, checkpoint)
    captured: dict[str, object] = {}

    def fake_prepare_rewind(**_kwargs: object) -> RewindResult:
        changed = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
        changed["run_id"] = "mutated-after-reset"
        (run_dir / "state.json").write_text(json.dumps(changed), encoding="utf-8")
        return RewindResult(
            applied=True,
            spec_id=spec_dir.name,
            checkpoint_id=checkpoint.id,
            from_commit="c" * 40,
            to_commit=checkpoint.commit,
            backup_ref="echelon/backup/test",
            message="Rewind complete.",
        )

    def fake_recover(
        project_root: Path,
        selected: PhaseCheckpoint,
        replacement_state: dict[str, object],
    ) -> object:
        captured.update(
            root=project_root,
            checkpoint=selected,
            state=replacement_state,
        )
        return SimpleNamespace(revision_id="retarget-1")

    monkeypatch.setattr("echelon.rewind.prepare_rewind", fake_prepare_rewind)
    monkeypatch.setattr(
        "echelon.spec_retarget_recovery.recover_retarget_checkpoint",
        fake_recover,
    )
    monkeypatch.setattr(
        "echelon.cli._cleanup_rewind_outputs",
        lambda *_args: pytest.fail("generic rewind cleanup must not run"),
    )
    monkeypatch.setattr(
        "echelon.cli._reset_rewind_state",
        lambda *_args, **_kwargs: pytest.fail("generic state reset must not run"),
    )

    _cmd_rewind([checkpoint.id, "--confirm"], project_root=tmp_path)

    assert captured["checkpoint"] == checkpoint
    assert captured["state"]["run_id"] == "squad-replacement"


def test_traceability_repair_resumes_finalization_without_replanning(
    tmp_path: Path,
    capsys,
) -> None:
    from echelon.product_inputs import immutable_product_input_tree_digest

    run_dir, traceability = _traceability_repair_run(tmp_path)

    _cmd_repair_traceability(["--confirm"], project_root=tmp_path)

    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    ledger = json.loads(traceability.read_text(encoding="utf-8"))
    assert ledger["requirements"][0]["task_ids"] == ["T-001"]
    assert state["status"] == "running"
    assert state["phase"] == "phase4-document"
    assert state["blocked_reason"] is None
    assert state["product_inputs"]["tree_hash"] == (
        immutable_product_input_tree_digest(run_dir / "inputs")
    )
    assert "pending_external_publication" not in state
    assert "product_input_mutation" not in state
    assert "TRACEABILITY REPAIRED" in capsys.readouterr().out


def test_traceability_repair_rejects_tampered_live_preimage_without_writes(
    tmp_path: Path,
) -> None:
    run_dir, traceability = _traceability_repair_run(tmp_path)
    (run_dir / "inputs/tamper.bin").write_bytes(b"unindexed")
    before_state = (run_dir / "state.json").read_bytes()
    before_traceability = traceability.read_bytes()

    with pytest.raises(SystemExit):
        _cmd_repair_traceability(["--confirm"], project_root=tmp_path)

    assert (run_dir / "state.json").read_bytes() == before_state
    assert traceability.read_bytes() == before_traceability


@pytest.mark.parametrize(
    "boundary",
    ["before_intent", "partial_publication", "before_finalize"],
)
def test_traceability_repair_recovers_transaction_crash_prefixes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    boundary: str,
) -> None:
    from echelon.product_inputs import immutable_product_input_tree_digest
    from harness.squad_publication import PreparedSquadPublication
    from harness.squad_state import SquadStateStore

    run_dir, traceability = _traceability_repair_run(tmp_path)
    if boundary == "before_intent":
        original = SquadStateStore.begin_traceability_repair_publication
        calls = 0

        def fail_first(self, *args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise OSError("injected intent crash")
            return original(self, *args, **kwargs)

        monkeypatch.setattr(
            SquadStateStore,
            "begin_traceability_repair_publication",
            fail_first,
        )
    elif boundary == "partial_publication":
        original = PreparedSquadPublication.publish
        calls = 0

        def fail_first(self, fault_hook=None):
            nonlocal calls
            calls += 1
            if calls != 1:
                return original(self, fault_hook=fault_hook)

            def fault(position: int) -> None:
                if position == 1:
                    raise OSError("injected publication crash")

            return original(self, fault_hook=fault)

        monkeypatch.setattr(PreparedSquadPublication, "publish", fail_first)
    else:
        original = SquadStateStore.complete_external_publication
        calls = 0

        def fail_first(self, *args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise OSError("injected finalization crash")
            return original(self, *args, **kwargs)

        monkeypatch.setattr(
            SquadStateStore,
            "complete_external_publication",
            fail_first,
        )

    with pytest.raises(SystemExit):
        _cmd_repair_traceability(["--confirm"], project_root=tmp_path)

    _cmd_repair_traceability(["--confirm"], project_root=tmp_path)

    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    assert json.loads(traceability.read_text(encoding="utf-8"))["requirements"][0][
        "task_ids"
    ] == ["T-001"]
    assert state["product_inputs"]["tree_hash"] == (
        immutable_product_input_tree_digest(run_dir / "inputs")
    )
    assert "pending_external_publication" not in state
    assert "product_input_mutation" not in state


def test_traceability_repair_authenticates_staged_package_before_copy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from harness.squad_state import SquadStateStore

    run_dir, traceability = _traceability_repair_run(tmp_path)
    before = traceability.read_bytes()
    original = SquadStateStore.begin_traceability_repair_publication

    def tamper_after_intent(self, *args, **kwargs):
        original(self, *args, **kwargs)
        stage = next(
            (run_dir / ".publication-outbox").glob("*/work/product-inputs")
        )
        (stage / "traceability.json").write_bytes(b"{}\n")

    monkeypatch.setattr(
        SquadStateStore,
        "begin_traceability_repair_publication",
        tamper_after_intent,
    )

    with pytest.raises(SystemExit):
        _cmd_repair_traceability(["--confirm"], project_root=tmp_path)

    assert traceability.read_bytes() == before
    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    assert "pending_external_publication" in state
    assert "product_input_mutation" in state
