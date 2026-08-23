"""Tests for echelon spec status next-step selection."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from echelon.cli import (
    _cmd_phase,
    _cmd_status,
    _find_converged_harness_build,
    _print_next_steps,
)
from echelon.spec_switch import SpecSwitchError
from harness.blocked_decision import (
    build_blocked_decision_v2,
    validate_blocked_decision_v3,
)
from harness.recovery_instruction import RecoveryKind, RecoveryInstruction
from harness.phase_checkpoints import PhaseCheckpoint, record_checkpoint_metadata
from harness.squad_provider import SquadAgentResult


def _write_build_state(
    project: Path,
    build_id: str,
    *,
    status: str,
    spec_id: str = "001-demo",
    termination_reason: str | None = None,
    extra: dict | None = None,
) -> None:
    state_dir = project / "runs" / build_id / "state"
    state_dir.mkdir(parents=True)
    payload = {
        "spec_id": spec_id,
        "status": status,
        "termination_reason": termination_reason,
        "pr_url": None,
    }
    if extra:
        payload.update(extra)
    (state_dir / "default.json").write_text(
        json.dumps(payload),
        encoding="utf-8",
    )


def _write_switchable_spec_run(
    project: Path,
    run_name: str,
    *,
    spec_id: str,
    feature_branch: str | None = None,
) -> Path:
    run_dir = project / "runs" / run_name
    spec_dir = run_dir / "specs" / spec_id
    spec_dir.mkdir(parents=True)
    (run_dir / "state.json").write_text(
        json.dumps(
            {
                "run_id": f"runtime-{run_name}",
                "spec_id": spec_id,
                "feature_branch": feature_branch or spec_id,
                "spec_dir": spec_dir.relative_to(project).as_posix(),
                "published_spec_dir": f"specs/{spec_id}",
            }
        ),
        encoding="utf-8",
    )
    return run_dir


def _v2_decision(
    *,
    status: str,
    classification: str = "material",
    autonomy_mode: str = "guided",
) -> dict[str, object]:
    return build_blocked_decision_v2(
        decision_id="dec-cli-status",
        status=status,
        source_kind="human_gate",
        producer_id="checkpoint-assess",
        source_phase="phase1-what",
        reason_code="checkpoint_assessment",
        classification=classification,
        question="Which release boundary should be used?",
        options=[
            {
                "id": "ship-current",
                "label": "Ship the current boundary",
                "description": "Use the reviewed scope.",
                "recommended": True,
                "risk_level": "medium",
                "next_phase": "phase2-decide",
                "outcome": "approved",
            }
        ],
        recommended_answer=None,
        risk_level="medium",
        resolution_handler="gate_outcome",
        autonomy_mode=autonomy_mode,
        source_state_revision=0,
        attempts=1 if status == "resolving" else 0,
        failure_code="resolution_attempts_exhausted" if status == "failed" else None,
        now="2026-07-28T10:00:00+00:00",
    )


def _proportional_quality_decision() -> dict[str, object]:
    return build_blocked_decision_v2(
        decision_id="dec-quality-status",
        status="awaiting_human",
        source_kind="controller_safeguard",
        producer_id="proportional_quality_budget_exhausted",
        source_phase="phase1-why2",
        reason_code="proportional_quality_budget_exhausted",
        classification="material",
        question="Choose how to resolve the exhausted quality budget.",
        options=[
            {
                "id": "extend_once",
                "label": "Extend once",
                "description": "Authorize one final specification quality repair.",
                "recommended": True,
                "risk_level": "medium",
                "next_phase": "phase1-what",
                "outcome": None,
            },
            {
                "id": "continue_with_debt",
                "label": "Continue with debt",
                "description": "Accept the restored candidate with explicit quality debt.",
                "recommended": False,
                "risk_level": "high",
                "next_phase": None,
                "outcome": None,
            },
            {
                "id": "stop",
                "label": "Stop",
                "description": "Preserve the blocked run without accepting quality debt.",
                "recommended": False,
                "risk_level": "low",
                "next_phase": "terminal-blocked",
                "outcome": None,
            },
        ],
        recommended_answer=None,
        risk_level="medium",
        resolution_handler="proportional_quality_debt",
        autonomy_mode="guided",
        source_state_revision=0,
        now="2026-08-14T10:00:00+00:00",
    )


def _failed_provider_decision(
    *,
    schema_version: int = 3,
) -> dict[str, object]:
    legacy = build_blocked_decision_v2(
        decision_id="dec-provider-replay",
        status="failed",
        source_kind="provider_escalation",
        producer_id="phase1-tracker",
        source_phase="phase1-tracker",
        reason_code="human_clarification_required",
        classification="material",
        question="Which target repository should Echelon inspect?",
        options=[],
        recommended_answer="Inspect the registered application source.",
        risk_level="low",
        resolution_handler="clarification_resume",
        autonomy_mode="banzai",
        source_state_revision=2,
        attempts=2,
        failure_code="resolution_attempts_exhausted",
        now="2026-08-23T11:00:00+00:00",
    )
    if schema_version == 2:
        return legacy
    return validate_blocked_decision_v3(
        {
            **legacy,
            "schema_version": 3,
            "recommended_option_id": None,
            "recommended_action": None,
            "automatic_eligible": True,
            "recommendation_rationale": "The provider supplied a bounded source recommendation.",
            "recommendation_confidence": "medium",
            "recommendation_authority": "provider_evidence",
            "recommendation_evidence": [
                {
                    "id": "phase1-tracker:clarification",
                    "kind": "provider_evidence",
                    "reference": "phase1-tracker:human_clarification_required",
                    "digest": "b" * 64,
                }
            ],
            "resolution_rationale": None,
            "resolution_confidence": None,
            "recommendation_followed": None,
            "override_reason": None,
        }
    )


def _failed_v3_human_gate_decision() -> dict[str, object]:
    legacy = build_blocked_decision_v2(
        decision_id="dec-human-gate-rewind",
        status="failed",
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
        source_state_revision=4,
        attempts=2,
        failure_code="resolution_attempts_exhausted",
        now="2026-08-23T11:00:00+00:00",
    )
    return validate_blocked_decision_v3(
        {
            **legacy,
            "schema_version": 3,
            "recommended_option_id": "approve",
            "recommended_action": None,
            "automatic_eligible": True,
            "recommendation_rationale": "The current Phase 1 evidence supports approval.",
            "recommendation_confidence": "high",
            "recommendation_authority": "controller_evidence",
            "recommendation_evidence": [
                {
                    "id": "checkpoint-assess:quality",
                    "kind": "phase1_quality_certificate",
                    "reference": "state:spec_quality_certificate",
                    "digest": "c" * 64,
                }
            ],
            "resolution_rationale": None,
            "resolution_confidence": None,
            "recommendation_followed": None,
            "override_reason": None,
        }
    )


def test_status_shows_current_authorized_quality_debt_without_calling_it_passed(
    tmp_path: Path,
    capsys,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir = tmp_path / "runs/spec-debt"
    spec_dir = tmp_path / "specs/001-demo"
    run_dir.mkdir(parents=True)
    spec_dir.mkdir(parents=True)
    (tmp_path / "runs/.current").write_text(run_dir.name, encoding="utf-8")
    debt = {
        "status": "accepted_with_debt",
        "resolved_by": "COMMANDER",
        "failed_gates": [
            {"name": "overall", "score": 0.70, "threshold": 0.80, "margin": -0.10},
            {"name": "atomicity", "score": 0.72, "threshold": 0.85, "margin": -0.13},
        ],
    }
    (spec_dir / "quality-debt.json").write_text(json.dumps(debt), encoding="utf-8")
    state = {
        "run_id": run_dir.name,
        "status": "done",
        "phase": "DONE",
        "spec_dir": "specs/001-demo",
        "published_spec_dir": "specs/001-demo",
        "provider_limit_message": "Provider limit reached; resets at 21:10.",
        "spec_quality_debt_authorization": {
            "status": "accepted_with_debt",
            "debt_artifact": "specs/001-demo/quality-debt.json",
            "debt_artifact_sha256": "a" * 64,
            "resolved_by": "COMMANDER",
            "failed_gates": debt["failed_gates"],
        },
    }
    (run_dir / "state.json").write_text(json.dumps(state), encoding="utf-8")
    monkeypatch.setattr(
        "harness.phase1_quality_debt.has_current_quality_debt_authorization",
        lambda *_args, **_kwargs: True,
    )

    _cmd_status(tmp_path)

    output = capsys.readouterr().out
    assert "accepted with quality debt" in output.lower()
    assert "overall 0.70 < 0.80" in output
    assert "atomicity 0.72 < 0.85" in output
    assert "COMMANDER" in output
    assert "quality-debt.json" in output
    assert "Provider limit reached" in output
    assert "quality passed" not in output.lower()


def test_status_shows_sealed_proportional_choice_evidence_and_exact_resume_syntax(
    tmp_path: Path,
    capsys,
) -> None:
    run_dir = tmp_path / "runs/spec-quality-choice"
    run_dir.mkdir(parents=True)
    (tmp_path / "runs/.current").write_text(run_dir.name, encoding="utf-8")
    decision = _proportional_quality_decision()
    (run_dir / "state.json").write_text(
        json.dumps(
            {
                "run_id": run_dir.name,
                "status": "blocked",
                "phase": "terminal-blocked",
                "blocked_reason": "proportional_quality_budget_exhausted",
                "blocked_decision": decision,
                "recovery_instruction": RecoveryInstruction(
                    kind=RecoveryKind.AWAIT_HUMAN_ANSWER,
                    reason_code="proportional_quality_budget_exhausted",
                    phase="phase1-why2",
                    requires_human_input=True,
                    schema_version=2,
                    decision_id="dec-quality-status",
                ).to_dict(),
                "phase1_quality_repair": {
                    "schema_version": 1,
                    "automatic_limit": 3,
                    "automatic_consumed": 3,
                    "extension_limit": 1,
                    "extension_authorized": 0,
                    "extension_consumed": 0,
                },
                "proportional_quality_candidate_evidence": {
                    "selected_candidate_id": "quality-candidate-2",
                    "failed_gates": [
                        {"name": "overall", "score": 0.70, "threshold": 0.80},
                        {"name": "atomicity", "score": 0.72, "threshold": 0.85},
                    ],
                    "sage_finding_routes": [
                        {
                            "issue_id": "ISS-QUALITY-7",
                            "severity": "MEDIUM",
                            "type": "incompleteness",
                            "rationale": "The failure path is not observable.",
                        }
                    ],
                    "recommendation_evidence": {
                        "baseline_candidate_id": "quality-candidate-0",
                        "current_candidate_id": "quality-candidate-2",
                        "comparison_previous_candidate_id": (
                            "quality-candidate-1"
                        ),
                        "comparison_current_candidate_id": (
                            "quality-candidate-2"
                        ),
                        "baseline_formal_statement_count": 8,
                        "formal_statement_count": 14,
                        "formal_statement_growth": 6,
                        "baseline_byte_count": 700,
                        "byte_count": 1320,
                        "byte_growth": 620,
                        "score_history": [
                            {
                                "repair_number": 0,
                                "candidate_id": "quality-candidate-0",
                                "scores": [
                                    {
                                        "name": "overall",
                                        "score": 0.68,
                                        "threshold": 0.80,
                                        "pass": False,
                                    }
                                ],
                                "formal_statement_count": 8,
                                "byte_count": 700,
                            },
                            {
                                "repair_number": 1,
                                "candidate_id": "quality-candidate-2",
                                "scores": [
                                    {
                                        "name": "overall",
                                        "score": 0.70,
                                        "threshold": 0.80,
                                        "pass": False,
                                    }
                                ],
                                "formal_statement_count": 14,
                                "byte_count": 1320,
                            },
                        ],
                        "per_repair_deltas": [
                            {
                                "repair_number": 1,
                                "previous_repair_number": 0,
                                "previous_candidate_id": "quality-candidate-0",
                                "current_candidate_id": "quality-candidate-2",
                                "score_deltas": [
                                    {"name": "overall", "delta": 0.02}
                                ],
                                "formal_statement_delta": 6,
                                "byte_delta": 620,
                            }
                        ],
                        "recommended_option_id": "extend_once",
                        "rationale": (
                            "Residual gates improved within the borderline margin."
                        ),
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    _cmd_status(tmp_path)

    output = capsys.readouterr().out
    assert "Automatic repairs" in output and "3 of 3" in output
    assert "0 remaining" in output
    assert "Extension repairs" in output and "0 of 1" in output
    assert "1 remaining; 0 authorized" in output
    assert "quality-candidate-2" in output
    assert "overall 0.70 < 0.80" in output
    assert "atomicity 0.72 < 0.85" in output
    assert "ISS-QUALITY-7" in output
    assert "MEDIUM/incompleteness" in output
    assert "The failure path is not observable." in output
    assert "quality-candidate-0 → quality-candidate-2" in output
    assert "Repair comparison" in output
    assert "quality-candidate-1 → quality-candidate-2" in output
    assert "Score history" in output
    assert "repair 0 quality-candidate-0: overall 0.68/0.80" in output
    assert "repair 1 quality-candidate-2: overall 0.70/0.80" in output
    assert "Per-repair deltas" in output
    assert "repair 1: overall +0.02; statements +6; bytes +620" in output
    assert "8 → 14 (+6)" in output
    assert "700 → 1,320 (+620 bytes)" in output
    assert "Residual gates improved within the borderline margin." in output
    assert "extend_once: Extend once" in output
    assert "continue_with_debt: Continue with debt" in output
    assert "stop: Stop" in output
    assert "extend_once (Extend once)" in output
    assert 'echelon spec resume "extend_once"' in output
    assert 'echelon spec resume "continue_with_debt"' in output
    assert 'echelon spec resume "stop"' in output


def test_status_roadmap_reads_the_deployed_runtime_workflow(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "run-status"
    run_dir.mkdir(parents=True)
    (tmp_path / "runs" / ".current").write_text(run_dir.name, encoding="utf-8")
    (run_dir / "state.json").write_text(
        json.dumps({"run_id": run_dir.name, "status": "running", "phase": "init"}),
        encoding="utf-8",
    )

    with patch("echelon.cli._print_roadmap") as print_roadmap:
        _cmd_status(tmp_path)

    assert print_roadmap.call_args.args[1] == (
        tmp_path / ".echelon" / "runtime" / "workflow" / "definition.yaml"
    )


def test_status_renders_active_v2_awaiting_human_decision_read_only(
    tmp_path: Path,
    capsys,
) -> None:
    run_dir = tmp_path / "runs" / "spec-decision"
    run_dir.mkdir(parents=True)
    (tmp_path / "runs" / ".current").write_text(run_dir.name, encoding="utf-8")
    decision = _v2_decision(status="awaiting_human")
    (run_dir / "state.json").write_text(
        json.dumps(
            {
                "run_id": run_dir.name,
                "status": "blocked",
                "phase": "phase1-what",
                "blocked_decision": decision,
                "recovery_instruction": RecoveryInstruction(
                    kind=RecoveryKind.AWAIT_HUMAN_ANSWER,
                    reason_code="checkpoint_assessment",
                    phase="phase1-what",
                    requires_human_input=True,
                    schema_version=2,
                    decision_id="dec-cli-status",
                ).to_dict(),
            }
        ),
        encoding="utf-8",
    )

    _cmd_status(tmp_path)

    output = capsys.readouterr().out
    assert "Decision mode" in output
    assert "guided" in output
    assert "Classification" in output
    assert "material" in output
    assert "Which release boundary should be used?" in output
    assert "ship-current: Ship the current boundary" in output
    assert "Recommendation" in output
    assert "Risk" in output
    assert 'echelon spec resume "<your answer>"' in output


@pytest.mark.parametrize(
    ("decision_status", "recovery_kind", "phase", "requires_human_input", "action"),
    [
        ("pending", RecoveryKind.RESOLVE_DECISION, "phase1-what", False, "echelon spec continue"),
        ("resolving", RecoveryKind.RESOLVE_DECISION, "phase1-what", False, "echelon spec continue"),
        ("awaiting_human", RecoveryKind.AWAIT_HUMAN_ANSWER, "phase1-what", True, 'echelon spec resume "<your answer>"'),
        ("failed", RecoveryKind.MANUAL_DIAGNOSIS, "", False, "diagnose the failed decision"),
    ],
)
def test_status_renders_v2_action_without_changing_state(
    tmp_path: Path,
    capsys,
    decision_status: str,
    recovery_kind: RecoveryKind,
    phase: str,
    requires_human_input: bool,
    action: str,
) -> None:
    run_dir = tmp_path / "runs" / "spec-decision"
    run_dir.mkdir(parents=True)
    (tmp_path / "runs" / ".current").write_text(run_dir.name, encoding="utf-8")
    state_path = run_dir / "state.json"
    state_path.write_text(
        json.dumps(
            {
                "run_id": run_dir.name,
                "status": "blocked",
                "phase": "phase1-what",
                "blocked_decision": _v2_decision(status=decision_status),
                "recovery_instruction": RecoveryInstruction(
                    kind=recovery_kind,
                    reason_code="checkpoint_assessment",
                    phase=phase,
                    requires_human_input=requires_human_input,
                    schema_version=2,
                    decision_id="dec-cli-status",
                ).to_dict(),
            }
        ),
        encoding="utf-8",
    )
    before = state_path.read_bytes()

    _cmd_status(tmp_path)

    assert action in capsys.readouterr().out
    assert state_path.read_bytes() == before


def test_failed_human_gate_status_renders_ledger_rewind_without_mutation(
    tmp_path: Path,
    capsys,
) -> None:
    run_dir = tmp_path / "runs" / "spec-human-gate-rewind"
    spec_dir = run_dir / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    (tmp_path / "runs" / ".current").write_text(
        run_dir.name,
        encoding="utf-8",
    )
    record_checkpoint_metadata(
        spec_dir,
        PhaseCheckpoint(
            id="phase1-lexicon",
            spec_id=spec_dir.name,
            phase="phase1-lexicon",
            next_phase="checkpoint-assess",
            commit="a" * 40,
            metadata_commit="",
            source="auto",
            run_id=run_dir.name,
            created_at="2026-08-23T11:00:00+00:00",
        ),
    )
    decision = _failed_v3_human_gate_decision()
    state_path = run_dir / "state.json"
    state_path.write_text(
        json.dumps(
            {
                "run_id": run_dir.name,
                "state_revision": 5,
                "status": "blocked",
                "phase": "checkpoint-assess",
                "blocked_reason": decision["reason_code"],
                "autonomy_mode": "banzai",
                "spec_id": spec_dir.name,
                "spec_dir": spec_dir.relative_to(tmp_path).as_posix(),
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
                "escalation_options": decision["options"],
            }
        ),
        encoding="utf-8",
    )
    before = state_path.read_bytes()

    _cmd_status(tmp_path)

    output = capsys.readouterr().out
    assert "echelon spec rewind phase1-lexicon --confirm" in output
    assert "diagnose" not in output.lower()
    assert "echelon spec continue" not in output
    assert state_path.read_bytes() == before


@pytest.mark.parametrize("schema_version", [2, 3])
def test_failed_provider_status_command_retires_authority_and_executes_source_phase(
    tmp_path: Path,
    capsys,
    monkeypatch: pytest.MonkeyPatch,
    schema_version: int,
) -> None:
    root = Path(__file__).resolve().parent.parent.parent
    shutil.copytree(root / "runtime", tmp_path / ".echelon/runtime")
    shutil.copytree(root / "prosaic", tmp_path / ".echelon/prosaic")
    subprocess.run(
        ["git", "init", "-b", "main"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    run_dir = tmp_path / "runs" / "spec-provider-replay"
    spec_dir = run_dir / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    (tmp_path / "runs" / ".current").write_text(
        run_dir.name,
        encoding="utf-8",
    )
    decision = _failed_provider_decision(schema_version=schema_version)
    state_path = run_dir / "state.json"
    state_path.write_text(
        json.dumps(
            {
                "run_id": run_dir.name,
                "state_revision": 3,
                "status": "blocked",
                "phase": "phase1-tracker",
                "blocked_reason": decision["reason_code"],
                "autonomy_mode": "banzai",
                "mode": "greenfield",
                "user_message": "capture the application intent",
                "spec_id": "001-demo",
                "spec_dir": spec_dir.relative_to(tmp_path).as_posix(),
                "completed_phases": ["phase1-discover"],
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

    _cmd_status(tmp_path)

    assert "echelon phase run phase1-tracker" in capsys.readouterr().out

    provider_calls: list[str] = []

    class PhysicalProvider:
        def __init__(self, _config: object) -> None:
            pass

        def exec_agent(
            self,
            _project_root: str,
            prompt: str,
            **_kwargs: object,
        ) -> SquadAgentResult:
            provider_calls.append(prompt)
            (spec_dir / "user-intent.md").write_text(
                "# User intent\n\nCapture the registered application intent.\n",
                encoding="utf-8",
            )
            return SquadAgentResult(
                exit_code=0,
                echelon_result={
                    "verdict": "ALIGNED",
                    "state_updates": {},
                    "journal_entries": [],
                },
                raw_output="",
                duration_ms=1,
                timed_out=False,
            )

    monkeypatch.setattr(
        "harness.squad_provider.SquadCliProvider",
        PhysicalProvider,
    )

    _cmd_phase(
        ["run", "phase1-tracker"],
        project_root=tmp_path,
        ext_dir=tmp_path / ".echelon/runtime",
    )

    replayed = json.loads(state_path.read_text(encoding="utf-8"))
    assert len(provider_calls) == 1
    assert "blocked_decision" not in replayed
    assert "recovery_instruction" not in replayed
    assert (spec_dir / "user-intent.md").is_file()


def test_failed_provider_wrong_phase_cannot_retire_or_execute_authority(
    tmp_path: Path,
    capsys,
) -> None:
    root = Path(__file__).resolve().parent.parent.parent
    shutil.copytree(root / "runtime", tmp_path / ".echelon/runtime")
    shutil.copytree(root / "prosaic", tmp_path / ".echelon/prosaic")
    subprocess.run(
        ["git", "init", "-b", "main"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    run_dir = tmp_path / "runs" / "spec-provider-wrong-phase"
    spec_dir = run_dir / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    (tmp_path / "runs" / ".current").write_text(
        run_dir.name,
        encoding="utf-8",
    )
    decision = _failed_provider_decision()
    state_path = run_dir / "state.json"
    state_path.write_text(
        json.dumps(
            {
                "run_id": run_dir.name,
                "state_revision": 3,
                "status": "blocked",
                "phase": "phase1-tracker",
                "blocked_reason": decision["reason_code"],
                "autonomy_mode": "banzai",
                "mode": "greenfield",
                "spec_id": spec_dir.name,
                "spec_dir": spec_dir.relative_to(tmp_path).as_posix(),
                "blocked_decision": decision,
                "recovery_instruction": RecoveryInstruction(
                    kind=RecoveryKind.MANUAL_DIAGNOSIS,
                    reason_code=str(decision["reason_code"]),
                    phase="",
                    requires_human_input=False,
                    schema_version=2,
                    decision_id=str(decision["id"]),
                ).to_dict(),
            }
        ),
        encoding="utf-8",
    )
    before = state_path.read_bytes()

    with pytest.raises(SystemExit) as raised:
        _cmd_phase(
            ["run", "phase1-discover"],
            project_root=tmp_path,
            ext_dir=tmp_path / ".echelon/runtime",
        )

    assert raised.value.code == 1
    assert "echelon phase run phase1-tracker" in capsys.readouterr().err
    assert state_path.read_bytes() == before


def test_newer_blocked_harness_build_masks_older_converged_build(
    tmp_path: Path,
) -> None:
    _write_build_state(tmp_path, "build-20260531-222514-882423", status="converged")
    _write_build_state(
        tmp_path,
        "build-20260606-221522-964255",
        status="blocked",
        termination_reason="build_incomplete",
    )

    assert _find_converged_harness_build(tmp_path) is None


def test_newer_running_harness_build_masks_older_converged_build(
    tmp_path: Path,
) -> None:
    _write_build_state(tmp_path, "build-20260531-222514-882423", status="converged")
    _write_build_state(tmp_path, "build-20260606-144357-753380", status="running")

    assert _find_converged_harness_build(tmp_path) is None


def test_latest_converged_harness_build_is_ready_to_land(tmp_path: Path) -> None:
    _write_build_state(
        tmp_path,
        "build-20260606-221522-964255",
        status="converged",
        spec_id="001-demo",
    )

    assert _find_converged_harness_build(tmp_path) == ("001-demo", None)


def test_next_steps_report_latest_blocked_harness_build_before_phase_a_blockers(
    tmp_path: Path,
    capsys,
) -> None:
    _write_build_state(
        tmp_path,
        "build-20260606-221522-964255",
        status="blocked",
        spec_id="001-demo",
        termination_reason="build_incomplete",
    )

    _print_next_steps(tmp_path, "done")

    captured = capsys.readouterr()
    assert "HARNESS BUILD CHECKPOINTED" in captured.out
    assert "build_incomplete" in captured.out
    assert "echelon delivery continue 001-demo" in captured.out
    assert "constitution.md absent" not in captured.out


def test_next_steps_warn_when_dirty_checkout_blocks_harness_recovery(
    tmp_path: Path,
    capsys,
) -> None:
    _write_build_state(
        tmp_path,
        "build-20260606-221522-964255",
        status="blocked",
        spec_id="001-demo",
        termination_reason="build_incomplete",
    )
    (tmp_path / "tracked.txt").write_text("before\n", encoding="utf-8")
    import subprocess

    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "add", "tracked.txt"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "commit", "-m", "initial"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        env={
            "GIT_AUTHOR_NAME": "Test",
            "GIT_AUTHOR_EMAIL": "test@example.com",
            "GIT_COMMITTER_NAME": "Test",
            "GIT_COMMITTER_EMAIL": "test@example.com",
        },
    )
    (tmp_path / "tracked.txt").write_text("after\n", encoding="utf-8")

    _print_next_steps(tmp_path, "done")

    captured = capsys.readouterr()
    assert "tracked checkout changes block harness recovery" in captured.out
    assert "commit or stash tracked changes, then echelon delivery continue 001-demo" in captured.out


def test_next_steps_report_salvage_commit_for_blocked_harness_build(
    tmp_path: Path,
    capsys,
) -> None:
    _write_build_state(
        tmp_path,
        "build-20260606-221522-964255",
        status="blocked",
        spec_id="001-demo",
        termination_reason="build_incomplete",
        extra={
            "salvage_commit": "abcdef1234567890abcdef1234567890abcdef12",
            "salvage_branch": "harness/001-demo/default/iter-0",
            "salvage_verified": "not_run",
        },
    )

    _print_next_steps(tmp_path, "done")

    captured = capsys.readouterr()
    assert "salvage commit" in captured.out
    assert "abcdef123456" in captured.out
    assert "harness/001-demo/default/iter-0" in captured.out
    assert "not_run" in captured.out


def test_next_steps_report_provider_session_limit_as_first_class_block(
    tmp_path: Path,
    capsys,
) -> None:
    _write_build_state(
        tmp_path,
        "build-20260606-221522-964255",
        status="blocked",
        spec_id="001-demo",
        termination_reason="build_incomplete",
        extra={
            "build_status": "provider_session_limit",
            "build_reason": "LLM provider session limit reached before COMMANDER finalized",
            "provider_limit_message": "You've hit your session limit · resets 9:10pm",
            "provider_reset_hint": "9:10pm",
            "salvage_commit": "abcdef1234567890abcdef1234567890abcdef12",
            "salvage_branch": "harness/001-demo/default/iter-0",
            "salvage_verified": "not_run",
            "tokens_used": 1234,
        },
    )

    _print_next_steps(tmp_path, "done")

    captured = capsys.readouterr()
    assert "HARNESS PROVIDER SESSION LIMIT" in captured.out
    assert "HARNESS BUILD CHECKPOINTED" not in captured.out
    assert "You've hit your session limit" in captured.out
    assert "9:10pm" in captured.out
    assert "1,234 tokens recorded before provider stop" in captured.out
    assert "abcdef123456" in captured.out
    assert "harness/001-demo/default/iter-0" in captured.out
    assert "not_run" in captured.out
    assert "wait for provider reset, then echelon delivery continue 001-demo" in captured.out


def test_next_steps_report_build_blocker_without_recommending_a_retry(
    tmp_path: Path,
    capsys,
) -> None:
    _write_build_state(
        tmp_path,
        "build-20260606-221522-964255",
        status="blocked",
        spec_id="001-demo",
        termination_reason="build_blocked",
        extra={
            "build_status": "blocked",
            "build_reason": "NFR-008 requires an owner spec decision",
        },
    )

    _print_next_steps(tmp_path, "done")

    captured = capsys.readouterr()
    assert "HARNESS BUILD BLOCKED" in captured.out
    assert "NFR-008 requires an owner spec decision" in captured.out
    assert "echelon spec reopen 001-demo" in captured.out
    assert "echelon delivery continue 001-demo" not in captured.out


def test_next_steps_labels_running_harness_build_as_in_progress(
    tmp_path: Path,
    capsys,
) -> None:
    _write_build_state(
        tmp_path,
        "build-20260607-170743-443653",
        status="running",
        spec_id="001-demo",
    )

    _print_next_steps(tmp_path, "done")

    captured = capsys.readouterr()
    assert "HARNESS BUILD IN PROGRESS" in captured.out
    assert "HARNESS BUILD BLOCKED" not in captured.out
    assert "echelon spec status" in captured.out


def test_next_steps_for_docker_unavailable_tells_user_to_start_container_runtime(
    tmp_path: Path,
    capsys,
) -> None:
    _write_build_state(
        tmp_path,
        "build-20260607-170743-443653",
        status="blocked",
        spec_id="001-demo",
        termination_reason="docker_unavailable",
    )

    _print_next_steps(tmp_path, "done")

    captured = capsys.readouterr()
    assert "docker_unavailable" in captured.out
    assert "start the configured container runtime" in captured.out
    assert "echelon delivery continue 001-demo" in captured.out
    assert "--reset" not in captured.out


def test_status_prints_authoritative_spec_dir_for_active_squad_run(
    tmp_path: Path,
    capsys,
) -> None:
    run_id = "spec-20260616-204126-899927"
    run_dir = tmp_path / "runs" / run_id
    run_dir.mkdir(parents=True)
    (tmp_path / "runs" / ".current").write_text(run_id, encoding="utf-8")
    (run_dir / "state.json").write_text(
        json.dumps(
            {
                "run_id": "squad-1781635287",
                "status": "blocked",
                "phase": "phase3-consensus",
                "spec_dir": "specs/071-rule-studio-narrative",
                "user_message": "prepare me the proper design",
            }
        ),
        encoding="utf-8",
    )

    _cmd_status(tmp_path)

    captured = capsys.readouterr()
    assert "RUN STATE" in captured.out
    assert "Spec" in captured.out
    assert "specs/071-rule-studio-narrative" in captured.out


def test_status_uses_phase_instead_of_stale_last_dispatch(tmp_path: Path, capsys) -> None:
    run_id = "spec-20260718-000001"
    run_dir = tmp_path / "runs" / run_id
    run_dir.mkdir(parents=True)
    (tmp_path / "runs" / ".current").write_text(run_id, encoding="utf-8")
    (run_dir / "state.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "status": "running",
                "phase": "phase1-what",
                "last_dispatch": {"phase_id": "phase2-decide"},
            }
        ),
        encoding="utf-8",
    )

    _cmd_status(tmp_path)

    out = capsys.readouterr().out
    assert "Phase   phase1-what" in out
    assert "Phase   phase2-decide" not in out


def test_status_lists_active_spec_checkpoint_stash_and_other_runs(
    tmp_path: Path,
    capsys,
) -> None:
    active = _write_switchable_spec_run(
        tmp_path,
        "run-a",
        spec_id="001-spec-a",
        feature_branch="feature/001-spec-a",
    )
    _write_switchable_spec_run(tmp_path, "run-b", spec_id="002-spec-b")
    (tmp_path / "runs" / ".current").write_text("run-a", encoding="utf-8")
    state_path = active / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["phase_a_stash"] = {"commit": "stash-commit"}
    state_path.write_text(json.dumps(state), encoding="utf-8")

    with patch(
        "echelon.spec_switch.validate_spec_checkpoint",
        return_value=SimpleNamespace(
            checkpoint_id="cp-a",
            phase="plan",
            commit="abc123",
        ),
    ):
        _cmd_status(tmp_path)

    output = capsys.readouterr().out
    assert "ACTIVE SPEC" in output
    assert "001-spec-a" in output
    assert "feature/001-spec-a" in output
    assert "cp-a (plan)" in output
    assert "stash-commit" in output
    assert "002-spec-b" in output


def test_status_reports_checkpoint_not_yet_created_without_an_error(
    tmp_path: Path,
    capsys,
) -> None:
    _write_switchable_spec_run(tmp_path, "run-a", spec_id="001-spec-a")
    _write_switchable_spec_run(tmp_path, "run-b", spec_id="002-spec-b")
    (tmp_path / "runs" / ".current").write_text("run-a", encoding="utf-8")

    with patch(
        "echelon.spec_switch.validate_spec_checkpoint",
        side_effect=SpecSwitchError("no checkpoint for run 'run-a' (run-a, 001-spec-a)"),
    ):
        _cmd_status(tmp_path)

    output = capsys.readouterr().out
    assert "not yet created" in output
    assert "unavailable: no checkpoint" not in output


def test_status_reports_missing_deployed_runtime_not_legacy_extension_drift(
    tmp_path: Path,
    capsys,
) -> None:
    installed = tmp_path / ".specify" / "extensions" / "echelon"
    (installed / "agents" / "control").mkdir(parents=True)
    (installed / "extension.yml").write_text("name: echelon\n", encoding="utf-8")
    (installed / "agents" / "control" / "commander.md").write_text(
        "old\n",
        encoding="utf-8",
    )

    _cmd_status(tmp_path)

    captured = capsys.readouterr()
    assert "ECHELON RUNTIME" in captured.out
    assert "incomplete; run echelon workspace migrate-to-prosaic" in captured.out
    assert "EXTENSION DRIFT" not in captured.out
    assert "specify extension update" not in captured.out


def test_status_reports_ready_deployed_runtime(
    tmp_path: Path,
    capsys,
) -> None:
    (tmp_path / ".echelon" / "runtime" / "workflow").mkdir(parents=True)
    (tmp_path / ".echelon" / "runtime" / "workflow" / "definition.yaml").write_text(
        "phases: []\n", encoding="utf-8"
    )
    (tmp_path / ".echelon" / "prosaic" / "commands").mkdir(parents=True)
    (tmp_path / ".echelon" / "prosaic" / "subagents").mkdir()

    _cmd_status(tmp_path)

    captured = capsys.readouterr()
    assert "ECHELON RUNTIME" in captured.out
    assert "ready" in captured.out
    assert "migrate-to-prosaic" not in captured.out


def test_status_uses_controller_recovery_instruction_for_next_command(
    tmp_path: Path,
    capsys,
) -> None:
    run_dir = tmp_path / "runs" / "spec-20260726-075512-129608"
    run_dir.mkdir(parents=True)
    (tmp_path / "runs" / ".current").write_text(run_dir.name, encoding="utf-8")
    (run_dir / "state.json").write_text(
        json.dumps(
            {
                "status": "blocked",
                "phase": "phase1-why2",
                "blocked_reason": "controller_state_contract_validation_failed",
                "controller_contract_error": {
                    "phase_id": "phase1-why2",
                    "contract": "preparation",
                    "validator": "ownership",
                },
            }
        ),
        encoding="utf-8",
    )
    compatibility = SimpleNamespace(
        compatible=True,
        command="",
        note="runtime extension is compatible",
    )

    with patch(
        "echelon.cli._runtime_bundle_compatibility",
        return_value=compatibility,
    ):
        _cmd_status(tmp_path)

    output = capsys.readouterr().out
    assert "phase1-why2" in output
    assert "inspect echelon spec status, then choose a recovery action" in output
    assert "no runtime-sync recovery instruction was recorded" in output
    assert 'echelon spec resume "<your answer>"' not in output
    assert "echelon spec rewind" not in output
