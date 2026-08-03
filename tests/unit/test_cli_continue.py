"""Tests for echelon spec continue phase selection."""

from __future__ import annotations

import json
import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from echelon.cli import (
    _classify_run_recovery,
    _cmd_continue,
    _ensure_active_continue_spec_context,
    _next_continue_phase,
    _phase_a_readiness_candidate_dirs,
    _reset_quality_remediation_dispatch_counts,
    _supersede_quality_guard_decision,
)
from harness.phase_checkpoints import PhaseCheckpoint, record_checkpoint_metadata
from harness.blocked_decision import build_blocked_decision_v2
from harness.recovery_instruction import RecoveryKind, RecoveryInstruction


@pytest.fixture(autouse=True)
def _git_backed_workspace(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()


def _write_run_state(project_root: Path, state: dict) -> Path:
    run_dir = project_root / "runs" / "spec-test"
    run_dir.mkdir(parents=True)
    (project_root / "runs" / ".current").write_text(run_dir.name, encoding="utf-8")
    (run_dir / "state.json").write_text(json.dumps(state), encoding="utf-8")
    return run_dir


def _write_real_constitution(project_root: Path) -> None:
    const = project_root / ".specify" / "memory" / "constitution.md"
    const.parent.mkdir(parents=True)
    const.write_text("# Constitution\n\nReal project rules.\n", encoding="utf-8")


def _valid_plan_conformance_json() -> str:
    return json.dumps(
        {
            "status": "pass",
            "findings": [],
            "sources": [
                "spec.md",
                "requirements-overview.md",
                "plan.md",
                "tasks.md",
            ],
        },
        indent=2,
    ) + "\n"


def _record_run_checkpoint(run_dir: Path, spec_id: str, phase: str) -> None:
    spec_dir = run_dir / "specs" / spec_id
    spec_dir.mkdir(parents=True, exist_ok=True)
    record_checkpoint_metadata(
        spec_dir,
        PhaseCheckpoint(
            id=phase,
            spec_id=spec_id,
            phase=phase,
            next_phase=phase,
            commit="abcdef0",
            metadata_commit="",
            source="auto",
            run_id=run_dir.name,
            created_at="2026-07-18T12:00:00Z",
        ),
    )


def _pending_v2_decision(*, autonomy_mode: str) -> dict[str, object]:
    return build_blocked_decision_v2(
        decision_id="dec-cli-continue",
        status="pending",
        source_kind="human_gate",
        producer_id="checkpoint-assess",
        source_phase="phase1-what",
        reason_code="checkpoint_assessment",
        classification="operational",
        question="Should the reviewed boundary be accepted?",
        options=[
            {
                "id": "accept",
                "label": "Accept the reviewed boundary",
                "description": "Continue with the reviewed scope.",
                "recommended": True,
                "risk_level": "low",
                "next_phase": "phase2-decide",
                "outcome": "approved",
            }
        ],
        recommended_answer=None,
        risk_level="low",
        resolution_handler="gate_outcome",
        autonomy_mode=autonomy_mode,
        source_state_revision=0,
        now="2026-07-28T10:00:00+00:00",
    )


def _v2_continue_decision(
    *,
    status: str,
    autonomy_mode: str,
    classification: str,
) -> dict[str, object]:
    return build_blocked_decision_v2(
        decision_id="dec-cli-continue-side-effect",
        status=status,
        source_kind="human_gate",
        producer_id="checkpoint-assess",
        source_phase="phase1-what",
        reason_code="checkpoint_assessment",
        classification=classification,
        question="Should the reviewed boundary be accepted?",
        options=[
            {
                "id": "accept",
                "label": "Accept the reviewed boundary",
                "description": "Continue with the reviewed scope.",
                "recommended": True,
                "risk_level": "low",
                "next_phase": "phase2-decide",
                "outcome": "approved",
            }
        ],
        recommended_answer=None,
        risk_level="low",
        resolution_handler="gate_outcome",
        autonomy_mode=autonomy_mode,
        source_state_revision=0,
        attempts=1 if status == "resolving" else 0,
        failure_code="resolution_attempts_exhausted" if status == "failed" else None,
        now="2026-07-28T10:00:00+00:00",
    )


def _v2_continue_instruction(status: str) -> dict[str, object]:
    kind, phase, requires_human_input = {
        "pending": (RecoveryKind.RESOLVE_DECISION, "phase1-what", False),
        "resolving": (RecoveryKind.RESOLVE_DECISION, "phase1-what", False),
        "awaiting_human": (RecoveryKind.AWAIT_HUMAN_ANSWER, "phase1-what", True),
        "failed": (RecoveryKind.MANUAL_DIAGNOSIS, "", False),
    }[status]
    return RecoveryInstruction(
        kind=kind,
        reason_code="checkpoint_assessment",
        phase=phase,
        requires_human_input=requires_human_input,
        schema_version=2,
        decision_id="dec-cli-continue-side-effect",
    ).to_dict()


def test_continue_uses_sealed_v2_decision_mode_not_cli_override(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir = _write_run_state(
        tmp_path,
        {
            "run_id": "spec-test",
            "status": "blocked",
            "phase": "phase1-what",
            "user_message": "prepare the release",
            "autonomy_mode": "banzai",
            "blocked_decision": _pending_v2_decision(autonomy_mode="banzai"),
            "recovery_instruction": RecoveryInstruction(
                kind=RecoveryKind.RESOLVE_DECISION,
                reason_code="checkpoint_assessment",
                phase="phase1-what",
                requires_human_input=False,
                schema_version=2,
                decision_id="dec-cli-continue",
            ).to_dict(),
        },
    )
    calls: list[list[str]] = []

    monkeypatch.setattr(
        "echelon.cli._cmd_run",
        lambda args, project_root, ext_dir: calls.append(args),
    )

    _cmd_continue(
        ["--mode", "guided"],
        project_root=tmp_path,
        ext_dir=tmp_path / ".specify/extensions/echelon",
    )

    assert calls == [["prepare the release", "--mode", "banzai"]]
    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    assert state["blocked_decision"]["status"] == "pending"
    assert state["recovery_instruction"]["kind"] == "resolve_decision"


@pytest.mark.parametrize("status", ("pending", "resolving"))
def test_continue_routes_eligible_semi_and_recovering_decisions_without_cli_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    status: str,
) -> None:
    run_dir = _write_run_state(
        tmp_path,
        {
            "run_id": "spec-test",
            "status": "blocked",
            "phase": "phase1-what",
            "user_message": "prepare the release",
            "autonomy_mode": "semi",
            "blocked_decision": _v2_continue_decision(
                status=status,
                autonomy_mode="semi",
                classification="operational",
            ),
            "recovery_instruction": _v2_continue_instruction(status),
        },
    )
    calls: list[list[str]] = []
    monkeypatch.setattr(
        "echelon.cli._cmd_run",
        lambda args, project_root, ext_dir: calls.append(args),
    )
    state_path = run_dir / "state.json"
    before = state_path.read_bytes()

    _cmd_continue(
        ["--mode", "guided"],
        project_root=tmp_path,
        ext_dir=tmp_path / ".specify/extensions/echelon",
    )

    assert calls == [["prepare the release", "--mode", "semi"]]
    assert state_path.read_bytes() == before


@pytest.mark.parametrize(
    ("status", "autonomy_mode", "classification"),
    [
        ("awaiting_human", "guided", "operational"),
        ("awaiting_human", "semi", "material"),
        ("awaiting_human", "banzai", "external_prerequisite"),
        ("failed", "banzai", "operational"),
    ],
)
def test_continue_nonautomatic_v2_decisions_are_filesystem_read_only(
    tmp_path: Path,
    status: str,
    autonomy_mode: str,
    classification: str,
) -> None:
    published = tmp_path / "specs" / "001-side-effect"
    published.mkdir(parents=True)
    (published / "spec.md").write_text("# Published\n", encoding="utf-8")
    run_dir = _write_run_state(
        tmp_path,
        {
            "run_id": "spec-test",
            "status": "blocked",
            "phase": "phase1-what",
            "user_message": "prepare the release",
            "autonomy_mode": autonomy_mode,
            "spec_id": "001-side-effect",
            "spec_dir": "runs/spec-test/specs/stale",
            "published_spec_dir": "specs/001-side-effect",
            "blocked_decision": _v2_continue_decision(
                status=status,
                autonomy_mode=autonomy_mode,
                classification=classification,
            ),
            "recovery_instruction": _v2_continue_instruction(status),
        },
    )
    state_path = run_dir / "state.json"
    before = state_path.read_bytes()
    assert not (run_dir / "specs").exists()

    _cmd_continue(
        [],
        project_root=tmp_path,
        ext_dir=tmp_path / ".specify/extensions/echelon",
    )

    assert state_path.read_bytes() == before
    assert not (run_dir / "specs").exists()


def test_continue_prefers_specify_feature_directory_over_stale_short_spec_id(
    tmp_path: Path,
) -> None:
    """A resume must keep the spec-kit slug, never fork into specs/<number>."""
    run_dir = tmp_path / "runs" / "spec-test"
    canonical = tmp_path / "specs" / "004-transform-selector-above-stat"
    canonical.mkdir(parents=True)
    (canonical / "spec.md").write_text("# Canonical spec\n", encoding="utf-8")

    stale = run_dir / "specs" / "004"
    stale.mkdir(parents=True)
    (stale / "spec.md").write_text("# Stale alias\n", encoding="utf-8")

    state, active = _ensure_active_continue_spec_context(
        tmp_path,
        run_dir,
        {
            "spec_id": "004",
            "spec_dir": "runs/spec-test/specs/004",
            "published_spec_dir": "specs/004",
            "specify_feature_directory": "specs/004-transform-selector-above-stat",
        },
        sync_missing=True,
    )

    assert active == run_dir / "specs" / "004-transform-selector-above-stat"
    assert state["spec_id"] == "004-transform-selector-above-stat"
    assert state["spec_dir"] == "runs/spec-test/specs/004-transform-selector-above-stat"
    assert state["published_spec_dir"] == "specs/004-transform-selector-above-stat"
    assert (active / "spec.md").read_text(encoding="utf-8") == "# Canonical spec\n"


def test_continue_derives_published_slug_from_run_local_specify_directory(
    tmp_path: Path,
) -> None:
    """A run-local canonical reference must not become the published path."""
    run_dir = tmp_path / "runs" / "spec-test"
    canonical = run_dir / "specs" / "004-transform-selector-above-stat"
    canonical.mkdir(parents=True)
    (canonical / "spec.md").write_text("# Canonical spec\n", encoding="utf-8")
    published = tmp_path / "specs" / "004-transform-selector-above-stat"
    published.mkdir(parents=True)

    state, active = _ensure_active_continue_spec_context(
        tmp_path,
        run_dir,
        {
            "spec_id": "004",
            "spec_dir": "runs/spec-test/specs/004",
            "published_spec_dir": "specs/004",
            "specify_feature_directory": "runs/spec-test/specs/004-transform-selector-above-stat",
        },
        sync_missing=True,
    )

    assert active == canonical
    assert state["published_spec_dir"] == "specs/004-transform-selector-above-stat"


def test_readiness_candidates_exclude_stale_short_spec_alias_when_slug_is_known(
    tmp_path: Path,
) -> None:
    """A full spec-kit slug must prevent readiness from inspecting specs/<number>."""
    run_dir = tmp_path / "runs" / "spec-test"
    active = run_dir / "specs" / "004-transform-selector-above-stat"
    published = tmp_path / "specs" / "004-transform-selector-above-stat"
    active.mkdir(parents=True)
    published.mkdir(parents=True)

    candidates = _phase_a_readiness_candidate_dirs(
        tmp_path,
        {
            "spec_id": "004",
            "spec_dir": "runs/spec-test/specs/004-transform-selector-above-stat",
            "published_spec_dir": "specs/004-transform-selector-above-stat",
            "specify_feature_directory": "runs/spec-test/specs/004-transform-selector-above-stat",
        },
        run_dir,
        active_spec_dir=active,
        published_spec_dir=published,
    )

    assert active in candidates
    assert published in candidates
    assert run_dir / "specs" / "004" not in candidates
    assert tmp_path / "specs" / "004" not in candidates


@pytest.mark.parametrize("last_dispatch_phase", ["phase1-what", "phase1-lexicon"])
def test_continue_does_not_rerun_exhausted_lexicon_gate_without_repair(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys,
    last_dispatch_phase: str,
) -> None:
    """An exhausted hard gate needs artifact repair, not another blind gate run."""
    _write_real_constitution(tmp_path)
    run_dir = _write_run_state(
        tmp_path,
        {
            "status": "blocked",
            "phase": "terminal-blocked",
            "blocked_reason": "lexicon_gate_exhausted",
            "spec_id": "001-demo",
            "spec_dir": "runs/spec-test/specs/001-demo",
            "completed_phases": ["phase1-constitution", "phase1-what"],
            "last_dispatch": {"phase_id": last_dispatch_phase},
            "user_message": "build the dashboard",
            "autonomy_mode": "semi",
        },
    )
    spec_dir = run_dir / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    source = """# Feature\n\n- **FR-001**: Render the dashboard.\n- **AC-001**: Given data, when rendering, then the dashboard is visible.\n"""
    (spec_dir / "spec.md").write_text(source, encoding="utf-8")
    (spec_dir / "glossary.md").write_text("", encoding="utf-8")
    digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
    (spec_dir / "requirements.lexicon.md").write_text(
        f"""# SOURCE: spec.md
# SOURCE_SHA256: {digest}
ARTIFACT: SPEC
TITLE: Dashboard

REQ: FR-001
GIVEN: data is available
WHEN: the user opens the dashboard
THEN: The system SHALL render the dashboard
OUTPUT: The dashboard is visible
DEPENDS: none
EXAMPLE: AC-001

AC: AC-001
GIVEN: data is available
WHEN: the user opens the dashboard
THEN: The dashboard is visible
""",
        encoding="utf-8",
    )
    calls: list[list[str]] = []
    monkeypatch.setattr("echelon.cli._cmd_run", lambda args, **_kwargs: calls.append(args))

    _cmd_continue([], project_root=tmp_path, ext_dir=tmp_path / ".specify/extensions/echelon")

    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    assert state["phase"] == "terminal-blocked"
    assert state["status"] == "blocked"
    assert state["blocked_reason"] == "lexicon_gate_exhausted"
    assert calls == []
    output = capsys.readouterr().out
    assert "Manual recovery required" in output
    assert "requirements.lexicon.md" in output
    assert "spec-lexicon-report.json" in output
    assert "echelon phase run phase1-lexicon-derive" in output
    assert "echelon phase run phase1-what" not in output
    assert "echelon phase run phase1-lexicon\n" not in output


def test_continue_honors_persisted_banzai_judgment_after_readiness_misroute(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A historic terminal block must honor COMMANDER's saved executable route."""
    _write_real_constitution(tmp_path)
    run_dir = _write_run_state(
        tmp_path,
        {
            "status": "blocked",
            "phase": "terminal-blocked",
            "blocked_reason": "phase_a_readiness_failed",
            "escalation_resolved": True,
            "escalation_resolver": "COMMANDER-banzai",
            "next_phase": "checkpoint-assess",
            "spec_id": "004-transform-selector-above-stat",
            "spec_dir": "runs/spec-test/specs/004-transform-selector-above-stat",
            "user_message": "add transform selector",
            "autonomy_mode": "banzai",
        },
    )
    spec_dir = run_dir / "specs" / "004-transform-selector-above-stat"
    spec_dir.mkdir(parents=True)
    calls: list[list[str]] = []
    monkeypatch.setattr("echelon.cli._cmd_run", lambda args, **_kwargs: calls.append(args))

    _cmd_continue([], project_root=tmp_path, ext_dir=tmp_path / ".specify/extensions/echelon")

    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    assert state["phase"] == "checkpoint-assess"
    assert state["status"] == "running"
    assert state["blocked_reason"] is None
    assert "next_phase" not in state
    assert calls == [["add transform selector", "--mode", "banzai"]]


def test_continue_routes_to_constitution_without_phase_provenance(tmp_path: Path) -> None:
    _write_real_constitution(tmp_path)
    _write_run_state(
        tmp_path,
        {
            "status": "done",
            "phase": "DONE",
            "completed_phases": ["phase1-what", "phase1-why2"],
        },
    )

    assert _next_continue_phase(tmp_path) == "phase1-constitution"


def test_continue_allows_ready_spec_after_constitution_provenance(tmp_path: Path) -> None:
    _write_real_constitution(tmp_path)
    _write_run_state(
        tmp_path,
        {
            "status": "done",
            "phase": "DONE",
            "spec_id": "001-demo",
            "published_spec_dir": "specs/001-demo",
            "completed_phases": ["phase1-constitution"],
        },
    )
    spec_dir = tmp_path / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    (spec_dir / "quality-gates.md").write_text("# Quality Gates\n\n## Verdict: PASS\n")
    for name in (
        "spec.md", "plan.md", "research.md", "data-model.md", "tasks.md",
        "00-overview.md", "requirements-overview.md",
        "plan-conformance.md", "plan-conformance.json",
        "test-strategy.md", "test-architecture.md", "coverage-map.md",
    ):
        content = (
            _valid_plan_conformance_json()
            if name == "plan-conformance.json"
            else f"# {name}\n"
        )
        (spec_dir / name).write_text(content, encoding="utf-8")
    (spec_dir / "constitution.md").write_text(
        "# Constitution\n\nReal project rules.\n",
        encoding="utf-8",
    )

    assert _next_continue_phase(tmp_path) is None


def test_continue_ignores_stale_ready_files_when_solution_phases_were_skipped(
    tmp_path: Path,
) -> None:
    _write_real_constitution(tmp_path)
    _write_run_state(
        tmp_path,
        {
            "status": "done",
            "phase": "done",
            "spec_id": "001-demo",
            "published_spec_dir": "specs/001-demo",
            "completed_phases": [
                "init",
                "phase1-constitution",
                "phase1-what",
                "phase1-why2",
                "phase2-decide",
                "phase2-strategic-overview",
                "phase2-tracker-alignment",
                "phase4-document",
            ],
        },
    )
    spec_dir = tmp_path / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    (spec_dir / "quality-gates.md").write_text("# Quality Gates\n\n## Verdict: PASS\n")
    (spec_dir / "constitution.md").write_text("# Constitution\n\nReal project rules.\n")
    for name in (
        "spec.md", "plan.md", "research.md", "data-model.md", "tasks.md",
        "00-overview.md", "requirements-overview.md",
        "plan-conformance.md", "plan-conformance.json",
        "test-strategy.md", "test-architecture.md", "coverage-map.md",
    ):
        (spec_dir / name).write_text(f"# stale {name}\n", encoding="utf-8")

    assert _next_continue_phase(tmp_path) == "phase3-specialists"


def test_continue_resumes_next_missing_solution_phase_even_with_ready_files(
    tmp_path: Path,
) -> None:
    _write_real_constitution(tmp_path)
    _write_run_state(
        tmp_path,
        {
            "status": "done",
            "phase": "done",
            "spec_id": "001-demo",
            "published_spec_dir": "specs/001-demo",
            "completed_phases": [
                "phase1-constitution",
                "phase2-tracker-alignment",
                "phase3-specialists",
                "phase4-document",
            ],
        },
    )
    spec_dir = tmp_path / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    (spec_dir / "quality-gates.md").write_text("# Quality Gates\n\n## Verdict: PASS\n")
    (spec_dir / "constitution.md").write_text("# Constitution\n\nReal project rules.\n")
    for name in (
        "spec.md", "plan.md", "research.md", "data-model.md", "tasks.md",
        "test-strategy.md", "test-architecture.md", "coverage-map.md",
    ):
        (spec_dir / name).write_text(f"# stale {name}\n", encoding="utf-8")

    assert _next_continue_phase(tmp_path) == "phase3-how"


def test_continue_reopens_done_run_to_publish_complete_run_local_artifacts(
    tmp_path: Path,
) -> None:
    _write_real_constitution(tmp_path)
    run_dir = _write_run_state(
        tmp_path,
        {
            "status": "done",
            "phase": "DONE",
            "spec_id": "001",
            "spec_dir": "runs/spec-test/specs/001",
            "completed_phases": ["phase1-constitution"],
        },
    )
    active_spec_dir = run_dir / "specs" / "001"
    active_spec_dir.mkdir(parents=True)
    for name in (
        "spec.md", "plan.md", "research.md", "data-model.md", "tasks.md",
        "test-strategy.md", "test-architecture.md", "coverage-map.md",
    ):
        (active_spec_dir / name).write_text(f"# {name}\n", encoding="utf-8")

    published_spec_dir = tmp_path / "specs" / "001-themed-ascii-animation"
    published_spec_dir.mkdir(parents=True)
    (published_spec_dir / "spec.md").write_text("# stale published spec\n", encoding="utf-8")

    assert _next_continue_phase(tmp_path) == "phase4-document"


def test_continue_reopens_done_run_when_explicit_run_local_spec_has_unpublished_artifact(
    tmp_path: Path,
) -> None:
    _write_real_constitution(tmp_path)
    run_dir = _write_run_state(
        tmp_path,
        {
            "status": "done",
            "phase": "DONE",
            "spec_id": "001-demo",
            "spec_dir": "runs/spec-test/specs/001-demo",
            "published_spec_dir": "specs/001-demo",
            "completed_phases": ["phase1-constitution"],
        },
    )
    active_spec_dir = run_dir / "specs" / "001-demo"
    active_spec_dir.mkdir(parents=True)
    for name in (
        "spec.md",
        "plan.md",
        "research.md",
        "data-model.md",
        "tasks.md",
        "constitution.md",
    ):
        (active_spec_dir / name).write_text(f"# {name}\n", encoding="utf-8")
    (active_spec_dir / "user-intent.md").write_text("# User Intent\n", encoding="utf-8")

    published_spec_dir = tmp_path / "specs" / "001-demo"
    published_spec_dir.mkdir(parents=True)
    for name in (
        "spec.md",
        "plan.md",
        "research.md",
        "data-model.md",
        "tasks.md",
        "constitution.md",
    ):
        (published_spec_dir / name).write_text(f"# {name}\n", encoding="utf-8")

    assert _next_continue_phase(tmp_path) == "phase4-document"


def test_continue_does_not_apply_retired_re_generation_recovery(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _write_real_constitution(tmp_path)
    run_dir = _write_run_state(
        tmp_path,
        {
            "status": "blocked",
            "phase": "terminal-blocked",
            "blocked_reason": "re_generation_mismatch",
            "spec_id": "001-demo",
            "spec_dir": "runs/spec-test/specs/001-demo",
            "published_spec_dir": "specs/001-demo",
            "re_generation": 0,
            "re_generation_expected": 0,
            "re_generation_actual": 1,
            "completed_phases": ["phase1-constitution"],
            "user_message": "build the dashboard",
            "autonomy_mode": "banzai",
        },
    )
    (tmp_path / "re").mkdir()
    (tmp_path / "re" / "index.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "generation": 1,
                "publication_status": "partial",
                "published_at": "2026-07-15T12:00:00+00:00",
                "published_from_run": run_dir.name,
                "sources": {},
                "workspace": {
                    "manifest": "re/workspace/manifest.json",
                    "overview": "re/workspace/overview.md",
                    "relationships": "re/workspace/relationships.md",
                    "contracts": "re/workspace/contracts.md",
                },
                "warnings": [],
            }
        ),
        encoding="utf-8",
    )
    active_spec_dir = run_dir / "specs" / "001-demo"
    active_spec_dir.mkdir(parents=True)
    for name in (
        "spec.md",
        "plan.md",
        "research.md",
        "data-model.md",
        "tasks.md",
        "constitution.md",
    ):
        (active_spec_dir / name).write_text(f"# {name}\n", encoding="utf-8")
    (active_spec_dir / "user-intent.md").write_text("# User Intent\n", encoding="utf-8")

    published_spec_dir = tmp_path / "specs" / "001-demo"
    published_spec_dir.mkdir(parents=True)
    for name in (
        "spec.md",
        "plan.md",
        "research.md",
        "data-model.md",
        "tasks.md",
        "constitution.md",
    ):
        (published_spec_dir / name).write_text(f"# {name}\n", encoding="utf-8")

    calls: list[list[str]] = []

    def fake_cmd_run(args, project_root, ext_dir):
        calls.append(args)

    monkeypatch.setattr("echelon.cli._cmd_run", fake_cmd_run)

    _cmd_continue([], project_root=tmp_path, ext_dir=tmp_path / ".specify/extensions/echelon")

    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    assert state["status"] == "blocked"
    assert state["phase"] == "terminal-blocked"
    assert state["re_generation"] == 0
    assert state["blocked_reason"] == "re_generation_mismatch"
    assert calls == []


def test_continue_does_not_honor_stale_recommendation_when_build_is_ready(
    tmp_path: Path,
) -> None:
    _write_real_constitution(tmp_path)
    _write_run_state(
        tmp_path,
        {
            "status": "done",
            "phase": "terminal-blocked",
            "spec_id": "071-rule-studio-narrative",
            "completed_phases": ["phase1-constitution"],
            "convergence_forced": True,
            "phase_recommendation": "advance_past_consensus_to_delivery",
        },
    )
    spec_dir = tmp_path / "runs" / "spec-test" / "specs" / "071-rule-studio-narrative"
    spec_dir.mkdir(parents=True)
    (spec_dir / "quality-gates.md").write_text(
        "# Quality Gates\n\n"
        "## Verdict: FAIL\n\n"
        "| Gate | Score | Threshold | Status | Notes |\n"
        "| --- | --- | --- | --- | --- |\n"
        "| Structure | 0.677 | 0.75 | FAIL | not borderline |\n",
        encoding="utf-8",
    )
    for name in (
        "spec.md", "plan.md", "research.md", "data-model.md", "tasks.md",
        "test-strategy.md", "test-architecture.md", "coverage-map.md",
    ):
        (spec_dir / name).write_text(f"# {name}\n", encoding="utf-8")
    published_spec_dir = tmp_path / "specs" / "071-rule-studio-narrative"
    published_spec_dir.mkdir(parents=True)
    for name in (
        "spec.md", "plan.md", "research.md", "data-model.md", "tasks.md",
        "00-overview.md", "requirements-overview.md",
        "plan-conformance.md", "plan-conformance.json",
        "test-strategy.md", "test-architecture.md", "coverage-map.md",
    ):
        content = (
            _valid_plan_conformance_json()
            if name == "plan-conformance.json"
            else f"# published {name}\n"
        )
        (published_spec_dir / name).write_text(content, encoding="utf-8")
    (published_spec_dir / "constitution.md").write_text(
        "# Constitution\n\nReal project rules.\n",
        encoding="utf-8",
    )

    assert _next_continue_phase(tmp_path) is None


def test_continue_reopens_completed_run_in_same_directory(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _write_real_constitution(tmp_path)
    run_dir = _write_run_state(
        tmp_path,
        {
            "status": "done",
            "phase": "DONE",
            "user_message": "build the dashboard",
            "autonomy_mode": "semi",
            "spec_id": "001-demo",
            "completed_phases": ["phase1-constitution"],
        },
    )
    spec_dir = tmp_path / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    (spec_dir / "quality-gates.md").write_text(
        "# Quality Gates\n\n## Verdict: PASS\n",
        encoding="utf-8",
    )

    calls: list[list[str]] = []

    def fake_cmd_run(args, project_root, ext_dir):
        calls.append(args)

    monkeypatch.setattr("echelon.cli._cmd_run", fake_cmd_run)

    _cmd_continue([], project_root=tmp_path, ext_dir=tmp_path / ".specify/extensions/echelon")

    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    assert state["status"] == "running"
    assert state["phase"] == "phase3-how"
    assert state["spec_dir"] == "runs/spec-test/specs/001-demo"
    assert state["published_spec_dir"] == "specs/001-demo"
    assert state["spec_id"] == "001-demo"
    assert (run_dir / "specs" / "001-demo" / "quality-gates.md").exists()
    assert calls == [["build the dashboard", "--mode", "semi"]]


def test_continue_sets_active_run_spec_context_for_phase3_resume_from_published_spec(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _write_real_constitution(tmp_path)
    run_dir = _write_run_state(
        tmp_path,
        {
            "status": "done",
            "phase": "DONE",
            "user_message": "build the dashboard",
            "autonomy_mode": "semi",
            "spec_dir": "specs/007-american-football-element",
            "completed_phases": ["phase1-constitution"],
        },
    )
    spec_dir = tmp_path / "specs" / "007-american-football-element"
    spec_dir.mkdir(parents=True)
    (spec_dir / "quality-gates.md").write_text("# Quality Gates\n\n## Verdict: PASS\n", encoding="utf-8")
    for name in ("plan.md", "research.md", "data-model.md"):
        (spec_dir / name).write_text(f"# {name}\n", encoding="utf-8")

    calls: list[list[str]] = []

    def fake_cmd_run(args, project_root, ext_dir):
        calls.append(args)

    monkeypatch.setattr("echelon.cli._cmd_run", fake_cmd_run)

    _cmd_continue([], project_root=tmp_path, ext_dir=tmp_path / ".specify/extensions/echelon")

    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    assert state["phase"] == "phase3-plan"
    assert state["status"] == "running"
    assert state["spec_dir"] == "runs/spec-test/specs/007-american-football-element"
    assert state["published_spec_dir"] == "specs/007-american-football-element"
    assert state["spec_id"] == "007-american-football-element"
    assert (run_dir / "specs" / "007-american-football-element" / "plan.md").exists()
    assert calls == [["build the dashboard", "--mode", "semi"]]


def test_continue_does_not_guess_latest_spec_when_multiple_specs_exist(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _write_real_constitution(tmp_path)
    run_dir = _write_run_state(
        tmp_path,
        {
            "status": "done",
            "phase": "DONE",
            "user_message": "build the dashboard",
            "autonomy_mode": "semi",
            "spec_id": "007-american-football-element",
            "completed_phases": ["phase1-constitution"],
        },
    )
    selected = tmp_path / "specs" / "007-american-football-element"
    selected.mkdir(parents=True)
    (selected / "quality-gates.md").write_text("# Quality Gates\n\n## Verdict: PASS\n", encoding="utf-8")
    newer = tmp_path / "specs" / "999-unrelated-latest"
    newer.mkdir(parents=True)
    for name in ("quality-gates.md", "plan.md", "research.md", "data-model.md", "tasks.md"):
        (newer / name).write_text(f"# {name}\n", encoding="utf-8")

    calls: list[list[str]] = []

    def fake_cmd_run(args, project_root, ext_dir):
        calls.append(args)

    monkeypatch.setattr("echelon.cli._cmd_run", fake_cmd_run)

    _cmd_continue([], project_root=tmp_path, ext_dir=tmp_path / ".specify/extensions/echelon")

    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    assert state["phase"] == "phase3-how"
    assert state["spec_dir"] == "runs/spec-test/specs/007-american-football-element"
    assert state["spec_id"] == "007-american-football-element"
    assert not (run_dir / "specs" / "999-unrelated-latest").exists()
    assert calls == [["build the dashboard", "--mode", "semi"]]


def test_continue_repairs_tracker_done_before_missing_how_artifacts(
    tmp_path: Path,
) -> None:
    _write_real_constitution(tmp_path)
    run_dir = _write_run_state(
        tmp_path,
        {
            "status": "done",
            "phase": "DONE",
            "user_message": "build the dashboard",
            "autonomy_mode": "semi",
            "spec_id": "001-demo",
            "completed_phases": [
                "phase1-constitution",
                "phase2-decide",
                "phase2-tracker-alignment",
            ],
        },
    )
    spec_dir = run_dir / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text("# Spec\n", encoding="utf-8")
    (spec_dir / "quality-gates.md").write_text(
        "# Quality Gates\n\n## Verdict: PASS\n",
        encoding="utf-8",
    )
    (spec_dir / "intent-alignment-check.md").write_text(
        "# Intent Alignment\n\n- Verdict: ALIGNED\n",
        encoding="utf-8",
    )

    assert _next_continue_phase(tmp_path) == "phase3-specialists"


def test_cmd_continue_resumes_tracker_repair_at_specialists(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _write_real_constitution(tmp_path)
    run_dir = _write_run_state(
        tmp_path,
        {
            "status": "done",
            "phase": "DONE",
            "user_message": "build the dashboard",
            "autonomy_mode": "semi",
            "spec_id": "001-demo",
            "completed_phases": [
                "phase1-constitution",
                "phase2-decide",
                "phase2-tracker-alignment",
            ],
        },
    )
    spec_dir = run_dir / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text("# Spec\n", encoding="utf-8")
    (spec_dir / "quality-gates.md").write_text(
        "# Quality Gates\n\n## Verdict: PASS\n",
        encoding="utf-8",
    )
    (spec_dir / "intent-alignment-check.md").write_text(
        "# Intent Alignment\n\n- Verdict: ALIGNED\n",
        encoding="utf-8",
    )

    calls: list[list[str]] = []

    def fake_cmd_run(args, project_root, ext_dir):
        calls.append(args)

    monkeypatch.setattr("echelon.cli._cmd_run", fake_cmd_run)

    _cmd_continue([], project_root=tmp_path, ext_dir=tmp_path / ".specify/extensions/echelon")

    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    assert state["status"] == "running"
    assert state["phase"] == "phase3-specialists"
    assert calls == [["build the dashboard", "--mode", "semi"]]


def test_continue_blocked_non_escalation_run_points_to_rewind(
    tmp_path: Path,
    capsys,
) -> None:
    _write_real_constitution(tmp_path)
    run_dir = _write_run_state(
        tmp_path,
        {
            "status": "blocked",
            "phase": "terminal-blocked",
            "blocked_reason": "missing_echelon_result",
            "last_dispatch": {"phase_id": "phase3-sentinel"},
            "completed_phases": ["phase1-constitution", "phase3-how"],
            "spec_dir": "runs/spec-test/specs/001-demo",
        },
    )
    _record_run_checkpoint(run_dir, "001-demo", "phase3-sentinel")

    _cmd_continue([], project_root=tmp_path, ext_dir=tmp_path / ".specify/extensions/echelon")

    captured = capsys.readouterr()
    assert 'echelon spec rewind phase3-sentinel' in captured.out
    assert 'echelon spec resume "<your answer>"' not in captured.out


def test_continue_retries_incomplete_phase_before_constitution(
    tmp_path: Path,
    monkeypatch,
) -> None:
    run_dir = _write_run_state(
        tmp_path,
        {
            "status": "blocked",
            "phase": "terminal-blocked",
            "blocked_reason": "missing_echelon_result",
            "last_dispatch": {"phase_id": "phase1-discover"},
            "completed_phases": ["init"],
            "user_message": "make terminal ascii art",
            "autonomy_mode": "semi",
            "implementation_targets": [
                "sources/pressbox-search",
                "sources/pressbox-search-api",
            ],
        },
    )

    calls: list[list[str]] = []

    def fake_cmd_run(args, project_root, ext_dir):
        calls.append(args)

    monkeypatch.setattr("echelon.cli._cmd_run", fake_cmd_run)

    assert _next_continue_phase(tmp_path) == "phase1-discover"

    _cmd_continue([], project_root=tmp_path, ext_dir=tmp_path / ".specify/extensions/echelon")

    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    assert state["phase"] == "phase1-discover"
    assert state["status"] == "running"
    assert state["blocked_reason"] is None
    assert state["escalation_question"] is None
    assert calls == [[
        "make terminal ascii art",
        "--mode",
        "semi",
        "--target",
        "sources/pressbox-search",
        "--target",
        "sources/pressbox-search-api",
    ]]


def test_continue_provider_session_limit_retries_incomplete_phase(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    _write_real_constitution(tmp_path)
    _write_run_state(
        tmp_path,
        {
            "status": "blocked",
            "phase": "terminal-blocked",
            "blocked_reason": "provider_session_limit",
            "provider_limit_message": "You've hit your session limit · resets 4am (Europe/Prague)",
            "last_dispatch": {"phase_id": "phase3-consensus"},
            "completed_phases": ["phase1-constitution", "phase3-plan"],
            "user_message": "style the CLI output",
            "autonomy_mode": "banzai",
        },
    )

    calls: list[list[str]] = []
    monkeypatch.setattr(
        "echelon.cli._cmd_run",
        lambda args, project_root, ext_dir: calls.append(args),
    )

    _cmd_continue([], project_root=tmp_path, ext_dir=tmp_path / ".specify/extensions/echelon")

    captured = capsys.readouterr()
    assert calls == [["style the CLI output", "--mode", "banzai"]]
    assert "Retrying incomplete phase" in captured.out


def test_continue_blocks_new_branchless_workspace(
    tmp_path: Path,
    capsys,
) -> None:
    (tmp_path / ".git").rmdir()
    source = tmp_path / "og-platform"
    source.mkdir()
    (source / ".git").mkdir()
    (source / "package.json").write_text("{}", encoding="utf-8")

    with pytest.raises(SystemExit) as exc:
        _cmd_continue(["--mode", "banzai"], project_root=tmp_path, ext_dir=tmp_path)

    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "workspace root is not a Git repo" in err
    assert "echelon spec continue --mode banzai" in err


def test_continue_allows_legacy_branchless_running_recovery(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    (tmp_path / ".git").rmdir()
    source = tmp_path / "og-platform"
    source.mkdir()
    (source / ".git").mkdir()
    (source / "package.json").write_text("{}", encoding="utf-8")
    _write_run_state(
        tmp_path,
        {
            "status": "running",
            "phase": "phase1-what",
            "user_message": "build the dashboard",
            "autonomy_mode": "semi",
        },
    )

    calls: list[list[str]] = []

    def fake_cmd_run(args, project_root, ext_dir):
        calls.append(args)

    monkeypatch.setattr("echelon.cli._cmd_run", fake_cmd_run)

    _cmd_continue([], project_root=tmp_path, ext_dir=tmp_path)

    assert calls == [["build the dashboard", "--mode", "semi"]]
    err = capsys.readouterr().err
    assert "legacy branchless run detected; continuing for recovery only" in err


def test_continue_retries_timeout_without_resume_dead_end(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    run_dir = _write_run_state(
        tmp_path,
        {
            "status": "blocked",
            "phase": "terminal-blocked",
            "blocked_reason": "agent_timeout",
            "last_dispatch": {"phase_id": "phase1-discover"},
            "completed_phases": ["init"],
            "user_message": "make terminal ascii art",
            "autonomy_mode": "semi",
        },
    )

    calls: list[list[str]] = []

    def fake_cmd_run(args, project_root, ext_dir):
        calls.append(args)

    monkeypatch.setattr("echelon.cli._cmd_run", fake_cmd_run)

    _cmd_continue([], project_root=tmp_path, ext_dir=tmp_path / ".specify/extensions/echelon")

    captured = capsys.readouterr()
    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    assert state["phase"] == "phase1-discover"
    assert state["status"] == "running"
    assert state["blocked_reason"] is None
    assert 'echelon spec resume "<your answer>"' not in captured.out
    assert calls == [["make terminal ascii art", "--mode", "semi"]]


def test_continue_ignores_legacy_nested_re_state_during_outer_escalation(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    run_dir = _write_run_state(
        tmp_path,
        {
            "status": "blocked",
            "phase": "terminal-blocked",
            "blocked_reason": "phase_dispatch_limit",
            "escalation_question": "Possible routing loop. How should I proceed?",
            "last_dispatch": {"phase_id": "phase1-discover"},
            "completed_phases": ["init"],
            "user_message": "reverse engineer the workspace",
            "autonomy_mode": "banzai",
        },
    )
    re_state = run_dir / "re" / "state.json"
    re_state.parent.mkdir(parents=True)
    re_state.write_text(
        json.dumps(
            {
                "status": "blocked",
                "phase": "re-extract-2-specify",
                "blocked_reason": "re_quality_repair_modified_non_target_output",
            }
        ),
        encoding="utf-8",
    )
    calls: list[list[str]] = []

    def fake_cmd_run(args, project_root, ext_dir):
        calls.append(args)

    monkeypatch.setattr("echelon.cli._cmd_run", fake_cmd_run)

    _cmd_continue([], project_root=tmp_path, ext_dir=tmp_path / ".specify/extensions/echelon")

    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    assert state["phase"] == "terminal-blocked"
    assert state["status"] == "blocked"
    assert state["blocked_reason"] == "phase_dispatch_limit"
    assert 'echelon spec resume "<your answer>"' in capsys.readouterr().out
    assert calls == []


def test_continue_explains_how_to_recover_from_phase_dispatch_limit(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    _write_run_state(
        tmp_path,
        {
            "status": "blocked",
            "phase": "terminal-blocked",
            "blocked_reason": "phase_dispatch_limit",
            "escalation_question": (
                "Phase 'phase1-what' has been dispatched 6 times (limit 5) "
                "without converging or advancing. Possible routing loop. "
                "How should I proceed?"
            ),
            "phase_dispatch_limit_phase": "phase1-what",
            "phase_dispatch_limit": 5,
            "phase_dispatch_counts": {"phase1-what": 6},
            "last_dispatch": {"phase_id": "phase1-why2"},
            "completed_phases": ["init"],
            "user_message": "reverse engineer the workspace",
            "autonomy_mode": "semi",
        },
    )

    monkeypatch.setattr("echelon.cli._cmd_run", lambda *args, **kwargs: None)

    _cmd_continue([], project_root=tmp_path, ext_dir=tmp_path / ".specify/extensions/echelon")

    output = capsys.readouterr().out
    assert 'echelon spec resolve ISS-<n> "<project decision>"' in output
    assert "No retry has been authorized" in output
    assert "Resolve the first unresolved issue" in output
    assert "targeted repair" in output
    assert "retain the remaining issue ledger" in output


def test_continue_ignores_legacy_nested_re_state_for_active_spec_run(
    tmp_path: Path,
    monkeypatch,
) -> None:
    run_dir = _write_run_state(
        tmp_path,
        {
            "status": "running",
            "phase": "phase1-what",
            "blocked_reason": None,
            "completed_phases": ["init", "phase1-constitution"],
            "user_message": "reverse engineer the workspace",
            "autonomy_mode": "banzai",
        },
    )
    re_state = run_dir / "re" / "state.json"
    re_state.parent.mkdir(parents=True)
    re_state.write_text(
        json.dumps({"status": "blocked", "phase": "re-extract-2-specify"}),
        encoding="utf-8",
    )
    calls: list[list[str]] = []
    monkeypatch.setattr(
        "echelon.cli._cmd_run",
        lambda args, project_root, ext_dir: calls.append(args),
    )

    _cmd_continue([], project_root=tmp_path, ext_dir=tmp_path / ".specify/extensions/echelon")

    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    assert state["phase"] == "phase1-what"
    assert calls == [["reverse engineer the workspace", "--mode", "banzai"]]


def test_continue_blocks_branchless_completed_run_from_starting_new_phase(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    (tmp_path / ".git").rmdir()
    source = tmp_path / "og-platform"
    source.mkdir()
    (source / ".git").mkdir()
    (source / "package.json").write_text("{}", encoding="utf-8")
    _write_real_constitution(tmp_path)
    run_dir = _write_run_state(
        tmp_path,
        {
            "status": "done",
            "phase": "DONE",
            "user_message": "build the dashboard",
            "autonomy_mode": "semi",
            "completed_phases": ["phase1-constitution"],
        },
    )
    spec_dir = tmp_path / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    (spec_dir / "quality-gates.md").write_text(
        "# Quality Gates\n\n## Verdict: PASS\n",
        encoding="utf-8",
    )

    calls: list[list[str]] = []

    def fake_cmd_run(args, project_root, ext_dir):
        calls.append(args)

    monkeypatch.setattr("echelon.cli._cmd_run", fake_cmd_run)

    with pytest.raises(SystemExit) as exc:
        _cmd_continue([], project_root=tmp_path, ext_dir=tmp_path)

    assert exc.value.code == 2
    assert calls == []
    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    assert state["status"] == "done"
    err = capsys.readouterr().err
    assert "workspace root is not a Git repo" in err


def test_continue_points_retryable_phase3_failure_to_rewind(
    tmp_path: Path,
    capsys,
) -> None:
    _write_real_constitution(tmp_path)
    run_dir = _write_run_state(
        tmp_path,
        {
            "status": "blocked",
            "phase": "terminal-blocked",
            "blocked_reason": "agent_exit_code_1",
            "last_dispatch": {"phase_id": "phase3-sentinel"},
            "completed_phases": ["phase1-constitution", "phase3-how"],
            "spec_dir": "runs/spec-test/specs/001-demo",
        },
    )
    _record_run_checkpoint(run_dir, "001-demo", "phase3-sentinel")

    _cmd_continue([], project_root=tmp_path, ext_dir=tmp_path / ".specify/extensions/echelon")

    captured = capsys.readouterr()
    assert "echelon spec rewind phase3-sentinel" in captured.out
    assert 'echelon spec resume "<your answer>"' not in captured.out


def test_recovery_suggests_any_checkpointed_phase_from_the_active_ledger(
    tmp_path: Path,
) -> None:
    run_dir = _write_run_state(
        tmp_path,
        {
            "status": "blocked",
            "phase": "terminal-blocked",
            "blocked_reason": "missing_echelon_result",
            "last_dispatch": {"phase_id": "phase1-what"},
            "spec_dir": "runs/spec-test/specs/004-transform-selector",
        },
    )
    _record_run_checkpoint(run_dir, "004-transform-selector", "phase1-what")

    action = _classify_run_recovery(
        json.loads((run_dir / "state.json").read_text(encoding="utf-8")),
        project_root=tmp_path,
    )

    assert action.kind == "safe_rewind"
    assert action.command == "echelon spec rewind phase1-what"


def test_recovery_retries_completed_phase_after_state_update_validation_failure(
    tmp_path: Path,
) -> None:
    """A rejected result is incomplete even if an earlier pass completed the phase."""
    run_dir = _write_run_state(
        tmp_path,
        {
            "status": "blocked",
            "phase": "terminal-blocked",
            "blocked_reason": (
                "echelon_result validation failed: echelon_result.state_updates key "
                "'phase3_plan_verdict' is not allowed for this phase"
            ),
            "last_dispatch": {"phase_id": "phase3-consensus", "verdict": "BLOCKED"},
            "completed_phases": ["phase3-plan", "phase3-consensus"],
        },
    )

    action = _classify_run_recovery(
        json.loads((run_dir / "state.json").read_text(encoding="utf-8")),
        project_root=tmp_path,
    )

    assert action.kind == "retry_phase"
    assert action.phase == "phase3-consensus"
    assert action.command == "echelon spec continue"


def test_contract_failure_without_recovery_instruction_requires_manual_recovery() -> None:
    action = _classify_run_recovery(
        {
            "status": "blocked",
            "phase": "phase1-why2",
            "blocked_reason": "controller_state_contract_validation_failed",
            "last_dispatch": {"phase_id": "phase1-understanding"},
            "controller_contract_error": {
                "phase_id": "phase1-why2",
                "contract": "preparation",
                "validator": "ownership",
            },
        }
    )

    assert action.kind == "manual_recovery"
    assert action.phase == "phase1-why2"
    assert action.command != "echelon spec continue"
    assert "no runtime-sync recovery instruction" in action.note


def test_recovery_after_exhausted_issue_resolutions_requests_quality_gate_decision() -> None:
    action = _classify_run_recovery(
        {
            "status": "blocked",
            "phase": "terminal-blocked",
            "blocked_reason": "quality_gates_failed_after_resolutions",
        }
    )

    assert action.kind == "human_resume"
    assert action.command == 'echelon spec resume "<quality-gate decision>"'
    assert "No further `spec resolve` command applies" in action.note


def test_legacy_issue_resolution_next_with_no_open_ledger_entries_is_reclassified() -> None:
    action = _classify_run_recovery(
        {
            "status": "blocked",
            "phase": "terminal-blocked",
            "blocked_reason": "issue_resolution_next",
            "issue_resolution_ledger": {
                "ISS-001": {"status": "validated"},
                "ISS-002": {"status": "validated"},
            },
        }
    )

    assert action.reason == "quality_gate_remediation"
    assert action.command == "echelon spec continue"


def test_consecutive_why_failure_after_all_resolutions_restarts_quality_remediation() -> None:
    action = _classify_run_recovery(
        {
            "status": "blocked",
            "phase": "terminal-blocked",
            "blocked_reason": "consecutive_why_fails",
            "issue_resolution_ledger": {
                "ISS-006": {"status": "validated"},
                "ISS-007": {"status": "validated"},
            },
        }
    )

    assert action.kind == "retry_phase"
    assert action.reason == "quality_gate_remediation"
    assert action.phase == "phase1-what"


def test_quality_remediation_supersedes_only_its_stale_why_safeguard() -> None:
    decision = build_blocked_decision_v2(
        decision_id="dec-quality-guard",
        status="awaiting_human",
        source_kind="controller_safeguard",
        producer_id="consecutive_why_fails",
        source_phase="phase1-why2",
        reason_code="consecutive_why_fails",
        classification="material",
        question="Provide a repair instruction.",
        options=[],
        recommended_answer=None,
        risk_level=None,
        resolution_handler="reset_why_fail_count",
        autonomy_mode="semi",
        source_state_revision=3,
        now="2026-07-29T00:00:00+00:00",
    )
    state = {
        "quality_gate_remediation": {"attempt": 1},
        "issue_resolution_ledger": {"ISS-042": {"status": "validated"}},
        "blocked_decision": decision,
        "recovery_instruction": {"stale": "instruction"},
    }

    assert _supersede_quality_guard_decision(state) is True
    assert state["blocked_decision"]["status"] == "resolved"
    assert state["blocked_decision"]["resolved_by"] == "COMMANDER"
    assert "recovery_instruction" not in state


def test_quality_remediation_no_progress_retries_authoring_without_resolve() -> None:
    action = _classify_run_recovery(
        {
            "status": "blocked",
            "phase": "terminal-blocked",
            "blocked_reason": "quality_gate_remediation_no_artifact_progress",
        }
    )

    assert action.kind == "retry_phase"
    assert action.reason == "quality_gate_remediation"
    assert action.command == "echelon spec continue"


def test_continue_preserves_finding_routes_for_quality_remediation_retry(
    tmp_path: Path,
    monkeypatch,
) -> None:
    findings = [
        {
            "issue_id": "ISS-001",
            "route": "spec_repair",
            "rationale": "FR-033 contradicts FR-034.",
        },
        {
            "issue_id": "ISS-002",
            "route": "spec_repair",
            "rationale": "AC-037 contradicts FR-038.",
        },
    ]
    spec_dir = tmp_path / "runs" / "spec-test" / "specs" / "001-demo"
    run_dir = _write_run_state(
        tmp_path,
        {
            "status": "blocked",
            "phase": "terminal-blocked",
            "blocked_reason": "quality_gate_remediation_no_artifact_progress",
            "spec_dir": str(spec_dir.relative_to(tmp_path)),
            "user_message": "build feature",
            "autonomy_mode": "semi",
            "understanding_evidence": {
                "phase": "phase1-why2",
                "status": "completed",
                "pass": True,
                "failing_gates": [],
                "path": "evidence/current.json",
            },
            "finding_routes": {"findings": findings},
            "quality_gate_remediation": {"attempt": 1},
        },
    )
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text(
        "# Spec\n\n**Status**: Planned\n\nFR-001: Existing requirement.\n",
        encoding="utf-8",
    )
    calls: list[list[str]] = []
    monkeypatch.setattr(
        "echelon.cli._cmd_run",
        lambda args, project_root, ext_dir: calls.append(args),
    )

    _cmd_continue([], project_root=tmp_path, ext_dir=tmp_path / ".specify/extensions/echelon")

    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    assert state["phase"] == "phase1-what"
    assert state["status"] == "running"
    assert state["blocked_reason"] is None
    remediation = state["quality_gate_remediation"]
    assert remediation["attempt"] == 2
    assert remediation["evidence"] == state["understanding_evidence"]
    assert remediation["qualitative_findings"] == findings
    assert calls == [["build feature", "--mode", "semi"]]


def test_dispatch_cap_missing_published_evidence_retries_active_spec(
    tmp_path: Path,
) -> None:
    active_spec = tmp_path / "runs" / "run" / "specs" / "001-demo"
    active_spec.mkdir(parents=True)
    (active_spec / "issues.md").write_text("# Issues\n", encoding="utf-8")

    action = _classify_run_recovery(
        {
            "status": "blocked",
            "phase": "phase1-understanding",
            "blocked_reason": "phase_dispatch_limit_evidence_missing",
            "spec_dir": str(active_spec),
            "published_spec_dir": "specs/001-demo",
        },
        project_root=tmp_path,
    )

    assert action.kind == "retry_phase"
    assert action.reason == "phase_dispatch_limit_evidence_retry"
    assert action.phase == "phase1-understanding"


def test_quality_remediation_resets_its_authoring_quality_phase_counts() -> None:
    state = {
        "phase_dispatch_counts": {
            "phase1-what": 8,
            "phase1-lexicon": 6,
            "phase1-understanding": 6,
            "phase1-why2": 5,
            "phase1-discover": 3,
        },
    }
    _reset_quality_remediation_dispatch_counts(state)

    assert state["phase_dispatch_counts"] == {"phase1-discover": 3}


def test_spec_continue_prints_start_and_end_timestamps(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _cmd_continue(
        [],
        project_root=tmp_path,
        ext_dir=tmp_path / ".specify/extensions/echelon",
    )

    output = capsys.readouterr().out
    assert "[squad] start:" in output
    assert "[squad] end:" in output


def test_persisted_runtime_sync_recovery_retries_after_compatible_sync(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "echelon.cli._runtime_extension_compatibility",
        lambda _project_root: SimpleNamespace(
            compatible=True,
            command="",
            note="runtime extension is compatible",
        ),
        raising=False,
    )

    action = _classify_run_recovery(
        {
            "status": "blocked",
            "phase": "phase1-why2",
            "blocked_reason": "controller_state_contract_validation_failed",
            "recovery_instruction": {
                "schema_version": 1,
                "kind": "sync_runtime_then_retry",
                "reason_code": "controller_state_contract_validation_failed",
                "phase": "phase1-why2",
                "requires_human_input": False,
            },
        },
        project_root=tmp_path,
    )

    assert action.kind == "retry_phase"
    assert action.phase == "phase1-why2"
    assert action.command == "echelon spec continue"


def test_stale_contract_instruction_reconciles_to_phase_output_recovery() -> None:
    action = _classify_run_recovery(
        {
            "status": "blocked",
            "phase": "terminal-blocked",
            "blocked_reason": "missing_phase_outputs",
            "recovery_instruction": {
                "schema_version": 1,
                "kind": "sync_runtime_then_retry",
                "reason_code": "controller_state_contract_validation_failed",
                "phase": "phase1-what",
                "requires_human_input": False,
            },
            "controller_contract_error": {
                "phase_id": "phase1-what",
                "contract": "preparation",
                "validator": "ownership",
            },
            "phase_output_recovery": {
                "phase": "phase1-what",
                "missing_outputs": ["requirements-overview.md"],
                "prior_state_updates": {
                    "spec_status": "planned",
                    "evidence_resolution_status": "not_required",
                },
            },
            "last_dispatch": {
                "phase_id": "phase1-what",
                "verdict": "BLOCKED",
            },
        }
    )

    assert action.kind == "retry_phase"
    assert action.reason == "missing_phase_outputs"
    assert action.phase == "phase1-what"
    assert action.command == "echelon spec continue"
    assert "runtime" not in action.note


def test_continue_prioritizes_phase_output_recovery_over_pending_issue(
    tmp_path: Path,
    monkeypatch,
) -> None:
    run_dir = _write_run_state(
        tmp_path,
        {
            "status": "blocked",
            "phase": "terminal-blocked",
            "blocked_reason": "missing_phase_outputs",
            "user_message": "Expose the supported machine-readable format",
            "recovery_instruction": {
                "schema_version": 1,
                "kind": "sync_runtime_then_retry",
                "reason_code": "controller_state_contract_validation_failed",
                "phase": "phase1-what",
                "requires_human_input": False,
            },
            "phase_output_recovery": {
                "phase": "phase1-what",
                "missing_outputs": ["requirements-overview.md"],
                "prior_state_updates": {
                    "spec_status": "planned",
                    "evidence_resolution_status": "not_required",
                },
            },
            "issue_resolution_recovery": {
                "issue_id": "ISS-003",
                "from_phase": "phase1-why2",
                "to_phase": "phase1-what",
                "reason": "issue_resolution",
            },
        },
    )
    calls: list[list[str]] = []
    monkeypatch.setattr(
        "echelon.cli._cmd_run",
        lambda args, **_kwargs: calls.append(args),
    )

    _cmd_continue(
        [],
        project_root=tmp_path,
        ext_dir=tmp_path / ".specify/extensions/echelon",
    )

    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    assert state["status"] == "running"
    assert state["phase"] == "phase1-what"
    assert state["blocked_reason"] is None
    assert "recovery_instruction" not in state
    assert state["phase_output_recovery"]["missing_outputs"] == [
        "requirements-overview.md"
    ]
    assert state["issue_resolution_recovery"]["issue_id"] == "ISS-003"
    assert len(calls) == 1


def test_continue_starts_controller_owned_issue_repair(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Issue resolution must leave terminal-blocked before invoking the controller."""
    run_dir = _write_run_state(
        tmp_path,
        {
            "status": "blocked",
            "phase": "terminal-blocked",
            "blocked_reason": "consecutive_why_fails",
            "user_message": "Expose the supported machine-readable format",
            "escalation_question": "Resolve ISS-001 before continuing.",
            "escalation_options": ["Use a project decision."],
            "selected_issue_resolution": "ISS-001",
            "issue_resolution_ledger": {
                "ISS-001": {"status": "selected", "decision": "Adopt JSON."}
            },
            "issue_resolution_recovery": {
                "issue_id": "ISS-001",
                "from_phase": "phase1-why2",
                "to_phase": "phase1-what",
                "reason": "issue_resolution",
            },
        },
    )
    calls: list[list[str]] = []
    monkeypatch.setattr(
        "echelon.cli._cmd_run",
        lambda args, **_kwargs: calls.append(args),
    )

    _cmd_continue(
        [],
        project_root=tmp_path,
        ext_dir=tmp_path / ".specify/extensions/echelon",
    )

    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    assert state["status"] == "running"
    assert state["phase"] == "phase1-what"
    assert state["blocked_reason"] is None
    assert state["escalation_question"] is None
    assert state["selected_issue_resolution"] == "ISS-001"
    assert state["issue_resolution_recovery"]["issue_id"] == "ISS-001"
    assert len(calls) == 1


def test_continue_revalidates_repaired_issue_before_requesting_new_decision(
    tmp_path: Path,
    monkeypatch,
) -> None:
    run_dir = _write_run_state(
        tmp_path,
        {
            "status": "blocked",
            "phase": "terminal-blocked",
            "blocked_reason": "consecutive_why_fails",
            "user_message": "Expose the supported machine-readable format",
            "escalation_question": "Resolve ISS-001 before continuing.",
            "selected_issue_resolution": "ISS-001",
            "issue_resolution_ledger": {
                "ISS-001": {"status": "repaired", "decision": "Adopt JSON."}
            },
            "issue_resolution_recovery": {
                "issue_id": "ISS-001",
                "status": "consumed",
            },
            "why_fail_count": 2,
            "why2_metric_stagnation_count": 2,
            "why_failure_baseline": {"recorded_at": "2026-01-01T00:00:00+00:00"},
        },
    )
    calls: list[list[str]] = []
    monkeypatch.setattr(
        "echelon.cli._cmd_run",
        lambda args, **_kwargs: calls.append(args),
    )

    _cmd_continue(
        [],
        project_root=tmp_path,
        ext_dir=tmp_path / ".specify/extensions/echelon",
    )

    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    assert state["status"] == "running"
    assert state["phase"] == "phase1-understanding"
    assert state["issue_resolution_revalidation_attempted"] == "ISS-001"
    assert state["why_fail_count"] == 0
    assert state["why2_metric_stagnation_count"] == 0
    assert "why_failure_baseline" not in state
    assert len(calls) == 1


def test_continue_consumes_controller_recovery_instruction(
    tmp_path: Path,
    monkeypatch,
) -> None:
    run_dir = _write_run_state(
        tmp_path,
        {
            "status": "blocked",
            "phase": "phase1-why2",
            "blocked_reason": "controller_state_contract_validation_failed",
            "user_message": "Expose the supported machine-readable format",
            "recovery_instruction": {
                "schema_version": 1,
                "kind": "sync_runtime_then_retry",
                "reason_code": "controller_state_contract_validation_failed",
                "phase": "phase1-why2",
                "requires_human_input": False,
            },
        },
    )
    monkeypatch.setattr(
        "echelon.cli._runtime_extension_compatibility",
        lambda _project_root: SimpleNamespace(
            compatible=True,
            command="",
            note="runtime extension is compatible",
        ),
        raising=False,
    )
    calls: list[list[str]] = []
    monkeypatch.setattr(
        "echelon.cli._cmd_run",
        lambda args, **_kwargs: calls.append(args),
    )

    _cmd_continue(
        [],
        project_root=tmp_path,
        ext_dir=tmp_path / ".specify/extensions/echelon",
    )

    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    assert state["status"] == "running"
    assert state["phase"] == "phase1-why2"
    assert "recovery_instruction" not in state
    assert state["blocked_reason"] is None
    assert len(calls) == 1


def test_continue_requires_runtime_sync_before_retry(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    _write_run_state(
        tmp_path,
        {
            "status": "blocked",
            "phase": "phase1-why2",
            "blocked_reason": "controller_state_contract_validation_failed",
            "user_message": "Expose the supported machine-readable format",
            "recovery_instruction": {
                "schema_version": 1,
                "kind": "sync_runtime_then_retry",
                "reason_code": "controller_state_contract_validation_failed",
                "phase": "phase1-why2",
                "requires_human_input": False,
            },
        },
    )
    update_command = (
        "specify extension update echelon --dev /checkout/echelon/extension"
    )
    monkeypatch.setattr(
        "echelon.cli._runtime_extension_compatibility",
        lambda _project_root: SimpleNamespace(
            compatible=False,
            command=update_command,
            note="installed runtime is missing shipped files",
        ),
        raising=False,
    )
    calls: list[list[str]] = []
    monkeypatch.setattr(
        "echelon.cli._cmd_run",
        lambda args, **_kwargs: calls.append(args),
    )

    _cmd_continue(
        [],
        project_root=tmp_path,
        ext_dir=tmp_path / ".specify/extensions/echelon",
    )

    captured = capsys.readouterr()
    assert update_command in captured.out
    assert calls == []


def test_continue_manual_block_does_not_claim_human_resume(
    tmp_path: Path,
    capsys,
) -> None:
    _write_run_state(
        tmp_path,
        {
            "status": "blocked",
            "phase": "terminal-blocked",
            "blocked_reason": "phase_a_readiness_failed",
            "completed_phases": ["phase1-constitution"],
        },
    )

    _cmd_continue([], project_root=tmp_path, ext_dir=tmp_path / ".specify/extensions/echelon")

    captured = capsys.readouterr()
    assert "Manual recovery required" in captured.out
    assert "inspect echelon spec status, then choose a recovery action" in captured.out
    assert 'echelon spec resume "<your answer>"' not in captured.out


def test_continue_displays_executable_escalation_options(
    tmp_path: Path,
    capsys,
) -> None:
    _write_run_state(
        tmp_path,
        {
            "status": "blocked",
            "phase": "checkpoint-assess",
            "blocked_reason": "checkpoint-assess human gate",
            "escalation_question": "Proceed to DECIDE or return to WHAT?",
            "escalation_options": [
                {
                    "id": "proceed_to_decide",
                    "label": "Proceed to DECIDE",
                    "next_phase": "phase2-decide",
                },
                {
                    "id": "route_back_to_what",
                    "label": "Return to WHAT",
                    "next_phase": "phase1-what",
                },
            ],
        },
    )

    _cmd_continue([], project_root=tmp_path, ext_dir=tmp_path / ".specify/extensions/echelon")

    captured = capsys.readouterr()
    assert "A: Proceed to DECIDE" in captured.out
    assert "B: Return to WHAT" in captured.out
    assert "Answer with A/B, the option id, or the option label." in captured.out


def test_continue_traceability_readiness_failure_offers_traceability_repair(tmp_path: Path, capsys) -> None:
    _write_run_state(
        tmp_path,
        {
            "status": "blocked",
            "phase": "terminal-blocked",
            "blocked_reason": "phase_a_readiness_failed",
            "phase_a_readiness_blockers": [
                "IN-REQ-1: task T-001 does not reference the mapped specification IDs"
            ],
            "completed_phases": ["phase1-constitution", "phase3-plan", "phase3-consensus"],
        },
    )

    _cmd_continue([], project_root=tmp_path, ext_dir=tmp_path / ".specify/extensions/echelon")

    captured = capsys.readouterr()
    assert "echelon spec repair-traceability" in captured.out
    assert "removes contextual task references" in captured.out


def test_continue_retries_external_blocker_phase_after_fix(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    run_dir = _write_run_state(
        tmp_path,
        {
            "status": "blocked",
            "phase": "terminal-blocked",
            "blocked_reason": "Understanding extension unavailable — required for WHY2/WHY3 spec validation",
            "last_dispatch": {"phase_id": "phase1-why2"},
            "completed_phases": ["phase1-constitution", "phase1-what"],
            "user_message": "build search dashboard",
            "autonomy_mode": "semi",
        },
    )

    calls: list[list[str]] = []

    def fake_cmd_run(args, project_root, ext_dir):
        calls.append(args)

    monkeypatch.setattr("echelon.cli._cmd_run", fake_cmd_run)

    _cmd_continue([], project_root=tmp_path, ext_dir=tmp_path / ".specify/extensions/echelon")

    captured = capsys.readouterr()
    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    assert state["phase"] == "phase1-why2"
    assert state["status"] == "running"
    assert state["blocked_reason"] is None
    assert "Retrying incomplete phase phase1-why2" in captured.out
    assert calls == [["build search dashboard", "--mode", "semi"]]


def test_continue_retries_interrupted_phase(
    tmp_path: Path,
    monkeypatch,
) -> None:
    run_dir = _write_run_state(
        tmp_path,
        {
            "status": "interrupted",
            "phase": "phase1-discover",
            "interrupted_phase": "phase1-discover",
            "completed_phases": ["init"],
            "user_message": "make terminal ascii art",
            "autonomy_mode": "semi",
        },
    )

    calls: list[list[str]] = []

    def fake_cmd_run(args, project_root, ext_dir):
        calls.append(args)

    monkeypatch.setattr("echelon.cli._cmd_run", fake_cmd_run)

    _cmd_continue([], project_root=tmp_path, ext_dir=tmp_path / ".specify/extensions/echelon")

    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    assert state["phase"] == "phase1-discover"
    assert state["status"] == "running"
    assert calls == [["make terminal ascii art", "--mode", "semi"]]
