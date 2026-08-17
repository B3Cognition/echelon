"""Content and authority contracts for explicit Phase 1 quality debt."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
import hashlib
import json
import os
from pathlib import Path

import pytest

import harness.phase1_quality_debt as debt_module
import harness.squad_completion as completion_module
from harness.blocked_decision import (
    build_blocked_decision_v2,
    validate_blocked_decision_v2,
)
from harness.phase1_quality_debt import (
    apply_or_verify_quality_debt_effect,
    build_quality_debt_authorization,
    has_current_quality_debt_authorization,
)
from harness.proportional_quality import (
    QualityCandidateIntegrityError,
    QualityCandidateManifest,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _candidate_payload(candidate: QualityCandidateManifest) -> dict[str, object]:
    return {
        "schema_version": candidate.schema_version,
        "candidate_id": candidate.candidate_id,
        "checkpoint_commit": candidate.checkpoint_commit,
        "owned_artifact_digests": dict(candidate.owned_artifact_digests),
        "run_artifact_root": candidate.run_artifact_root,
        "understanding_evidence": candidate.understanding_evidence,
        "understanding_evidence_digest": candidate.understanding_evidence_digest,
        "normalized_gates": [
            {
                "name": name,
                "score": score,
                "threshold": threshold,
                "pass": passed,
            }
            for name, score, threshold, passed in candidate.normalized_gates
        ],
        "sage_finding_routes": [
            dict(finding) for finding in candidate.sage_finding_routes
        ],
        "failed_gate_count": candidate.failed_gate_count,
        "worst_gate_margin": candidate.worst_gate_margin,
        "overall_score": candidate.overall_score,
        "formal_statement_count": candidate.formal_statement_count,
        "byte_count": candidate.byte_count,
        "repair_number": candidate.repair_number,
        "assessment_index": candidate.assessment_index,
        "eligibility_reasons": list(candidate.eligibility_reasons),
    }


def _sealed_decision(*, status: str = "awaiting_human") -> dict[str, object]:
    active = build_blocked_decision_v2(
        decision_id="dec-123",
        status="awaiting_human",
        source_kind="controller_safeguard",
        producer_id="proportional_quality_budget_exhausted",
        source_phase="phase1-why2",
        reason_code="proportional_quality_budget_exhausted",
        classification="material",
        question="Accept the restored candidate with residual quality debt?",
        options=[
            {
                "id": "extend_once",
                "label": "Extend once",
                "description": "Authorize one final repair.",
                "recommended": False,
                "risk_level": "medium",
                "next_phase": "phase1-what",
                "outcome": None,
            },
            {
                "id": "continue_with_debt",
                "label": "Continue with debt",
                "description": "Accept explicit quality debt.",
                "recommended": True,
                "risk_level": "high",
                "next_phase": None,
                "outcome": None,
            },
            {
                "id": "stop",
                "label": "Stop",
                "description": "Preserve the blocked run.",
                "recommended": False,
                "risk_level": "low",
                "next_phase": "terminal-blocked",
                "outcome": None,
            },
        ],
        recommended_answer=None,
        risk_level=None,
        resolution_handler="proportional_quality_debt",
        autonomy_mode="semi",
        source_state_revision=4,
        now="2026-08-14T08:00:00+00:00",
    )
    if status == "awaiting_human":
        return active
    assert status == "resolved"
    return validate_blocked_decision_v2(
        {
            **active,
            "status": "resolved",
            "selected_option_id": "continue_with_debt",
            "resolved_by": "user",
            "resolved_at": "2099-08-14T08:01:00+00:00",
        }
    )


def _debt_fixture(
    tmp_path: Path,
    *,
    eligibility_reasons: tuple[str, ...] = (),
    apply_effect: bool = True,
    qualitative_only: bool = False,
) -> tuple[
    dict[str, object],
    QualityCandidateManifest,
    object,
    dict[str, Path],
]:
    spec_dir = tmp_path / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    artifacts = {
        "spec.md": "# Restored candidate\n\n- FR-001: Render the greeting.\n",
        "requirements-overview.md": "# Requirements overview\n",
        "quality-gates.md": "# Quality gates\n\nOverall: 0.70 / 0.80\n",
        "issues.md": """# Issues — WHY2

## Summary
- **CRITICAL:** 0
- **HIGH:** 0
- **MEDIUM:** 0
- **LOW:** 1
- **Verdict:** FAIL

## Issues

### ISS-QUALITY: Residual quality debt
- **Severity:** LOW
- **Type:** incompleteness
- **Description:** The overall gate remains below threshold.
- **Affected artifact:** spec.md
- **Affected section:** Requirements
- **Evidence:** Immutable Understanding evidence.
- **Recommendation:** Repair the failing gate.
- **Responsible agent:** WHAT
- **Action Required:** Amend the specification.
""",
    }
    for name, content in artifacts.items():
        (spec_dir / name).write_text(content, encoding="utf-8")

    evidence = tmp_path / "runs" / "run-1" / "evidence" / "why2.json"
    score = 0.90 if qualitative_only else 0.70
    passed = qualitative_only
    report = {
        "schema_version": 1,
        "status": "completed",
        "phase": "phase1-why2",
        "iteration": 0,
        "spec": {
            "path": "specs/001-demo/spec.md",
            "sha256": _sha256(spec_dir / "spec.md"),
        },
        "thresholds": {"overall": 0.80},
        "scores": {"overall": score},
        "gates": {
            "overall": {
                "score": score,
                "threshold": 0.80,
                "pass": passed,
            }
        },
        "pass": passed,
        "requirement_count": 1,
    }
    _write_json(evidence, report)
    margin = score - 0.80
    finding = {
        "issue_id": "ISS-QUALITY",
        "route": "spec_repair",
        "rationale": "Residual non-critical quality debt.",
        "severity": "LOW",
        "type": "incompleteness",
        "title": "Residual quality debt",
    }
    candidate = QualityCandidateManifest(
        schema_version=1,
        candidate_id="quality-candidate-0",
        checkpoint_commit="a" * 40,
        owned_artifact_digests=tuple(
            (name, _sha256(spec_dir / name)) for name in sorted(artifacts)
        ),
        run_artifact_root=str(tmp_path / "runs" / "run-1"),
        understanding_evidence=str(evidence),
        understanding_evidence_digest=_sha256(evidence),
        normalized_gates=(("overall", score, 0.80, passed),),
        sage_finding_routes=(finding,),
        failed_gate_count=0 if qualitative_only else 1,
        worst_gate_margin=margin,
        overall_score=score,
        formal_statement_count=1,
        byte_count=len((spec_dir / "spec.md").read_bytes()),
        repair_number=3,
        assessment_index=0,
        eligibility_reasons=eligibility_reasons,
    )
    manifest_path = (
        tmp_path
        / "runs"
        / "run-1"
        / "quality-candidates"
        / "quality-candidate-0.json"
    )
    _write_json(manifest_path, _candidate_payload(candidate))
    repair_state = {
        "schema_version": 1,
        "authoring_mode": "proportional",
        "automatic_limit": 3,
        "automatic_consumed": 3,
        "extension_limit": 1,
        "extension_authorized": 0,
        "extension_consumed": 0,
        "migration_basis": "fresh",
        "baseline_candidate_id": "quality-candidate-0",
        "candidate_ids": ["quality-candidate-0"],
    }
    understanding_state = {
        "phase": "phase1-why2",
        "iteration": 0,
        "status": "completed",
        "path": str(evidence),
        "digest": _sha256(evidence),
        "pass": passed,
        "failing_gates": [] if qualitative_only else ["overall"],
        "error": None,
    }
    candidate_evidence_state = {
        "schema_version": 1,
        "current_candidate_id": "quality-candidate-0",
        "selected_candidate_id": "quality-candidate-0",
        "candidate_manifest": str(manifest_path),
        "candidate_manifest_sha256": _sha256(manifest_path),
        "selected_spec_sha256": _sha256(spec_dir / "spec.md"),
        "eligibility_reasons": [],
        "failed_gates": (
            []
            if qualitative_only
            else [
                {
                    "name": "overall",
                    "score": 0.70,
                    "threshold": 0.80,
                    "pass": False,
                }
            ]
        ),
        "sage_finding_routes": [finding],
        "last_repair_outcome": None,
    }
    active_decision = _sealed_decision()
    completion_id = "1" * 32
    resolved_at = "2099-08-14T08:01:00+00:00"
    prepared = build_quality_debt_authorization(
        project_root=tmp_path,
        spec_dir=spec_dir,
        candidate=candidate,
        candidate_manifest=manifest_path,
        repair_state=repair_state,
        understanding_state=understanding_state,
        candidate_evidence_state=candidate_evidence_state,
        decision=active_decision,
        decision_id="dec-123",
        resolved_by="user",
        resolved_at=resolved_at,
        completion_id=completion_id,
        from_phase="terminal-blocked",
        to_phase="checkpoint-assess",
    )
    receipt = (
        apply_or_verify_quality_debt_effect(
            tmp_path,
            prepared.effect_payload(),
        )
        if apply_effect
        else None
    )
    authorization = prepared.authorization
    state: dict[str, object] = {
        "spec_dir": "specs/001-demo",
        "completed_phases": ["phase1-why2"],
        "understanding_evidence": understanding_state,
        "quality_scores": [
            {
                "pass": passed,
                "pass_id": "WHY2-iter-0",
                "source": "harness:understanding",
                "evidence": str(evidence),
                "evidence_digest": _sha256(evidence),
            }
        ],
        "phase1_quality_repair": repair_state,
        "proportional_quality_candidate_evidence": candidate_evidence_state,
        "blocked_decision": _sealed_decision(status="resolved"),
        "spec_quality_debt_authorization": authorization,
    }
    intent = {
        "schema_version": 1,
        "completion_id": completion_id,
        "origin": "resolution",
        "publication": {"kind": "none"},
        "route": {
            "kind": "resolution",
            "decision_id": "dec-123",
            "from_phase": "terminal-blocked",
            "to_phase": "checkpoint-assess",
        },
        "effect_plan": ["quality"],
        "checkpoint_prestate": {"kind": "none"},
        "quality_effect": {
            "kind": "proportional_quality",
            "operation": "debt_write",
            "payload": prepared.effect_payload(),
        },
        "context_reason": "human-input proportional quality resolution",
        "mine_phase_a": False,
        "judgment_payload_sha256": [],
        "judgments": [],
    }
    debt_receipt = {
        "schema_version": 1,
        "operation": "debt_write",
        "debt_path": prepared.debt_path,
        "debt_artifact_sha256": authorization["debt_artifact_sha256"],
        "previous_debt_artifact_sha256": authorization[
            "previous_debt_artifact_sha256"
        ],
    }
    receipts = {
        "schema_version": 1,
        "completion_id": completion_id,
        "effects": {
            "quality": {
                "schema_version": 1,
                "operation": "debt_write",
                "debt": debt_receipt,
            }
        },
    }
    canonical = lambda value: (
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")
    state["last_human_input_completion"] = {
        "schema_version": 1,
        "completion_id": completion_id,
        "intent_sha256": hashlib.sha256(canonical(intent)).hexdigest(),
        "receipts_sha256": hashlib.sha256(canonical(receipts)).hexdigest(),
        "decision_id": "dec-123",
    }
    paths = {
        "spec": spec_dir / "spec.md",
        "overview": spec_dir / "requirements-overview.md",
        "quality_gates": spec_dir / "quality-gates.md",
        "issues": spec_dir / "issues.md",
        "evidence": evidence,
        "manifest": manifest_path,
        "debt": spec_dir / "quality-debt.json",
    }
    if receipt is not None:
        assert receipt["debt_artifact_sha256"] == authorization[
            "debt_artifact_sha256"
        ]
    return state, candidate, prepared, paths


def _builder_authority_kwargs(
    state: dict[str, object],
) -> dict[str, object]:
    return {
        "understanding_state": state["understanding_evidence"],
        "candidate_evidence_state": state[
            "proportional_quality_candidate_evidence"
        ],
        "resolved_at": "2099-08-14T08:01:00+00:00",
        "completion_id": "1" * 32,
        "from_phase": "terminal-blocked",
        "to_phase": "checkpoint-assess",
    }


def test_builder_prepares_complete_content_bound_schema_v1_debt(
    tmp_path: Path,
) -> None:
    state, _candidate, prepared, paths = _debt_fixture(
        tmp_path,
        apply_effect=False,
    )
    authorization = prepared.authorization
    assert not paths["debt"].exists()
    receipt = apply_or_verify_quality_debt_effect(
        tmp_path,
        prepared.effect_payload(),
    )
    debt = json.loads(paths["debt"].read_text(encoding="utf-8"))

    assert authorization == state["spec_quality_debt_authorization"]
    assert authorization["schema_version"] == 1
    assert authorization["status"] == "accepted_with_debt"
    assert authorization["source_path"] == "specs/001-demo/spec.md"
    assert authorization["source_sha256"] == _sha256(paths["spec"])
    assert authorization["understanding_evidence"] == (
        "runs/run-1/evidence/why2.json"
    )
    assert authorization["understanding_evidence_sha256"] == _sha256(
        paths["evidence"]
    )
    assert authorization["candidate_manifest"] == (
        "runs/run-1/quality-candidates/quality-candidate-0.json"
    )
    assert authorization["candidate_manifest_sha256"] == _sha256(
        paths["manifest"]
    )
    assert authorization["debt_artifact"] == "specs/001-demo/quality-debt.json"
    assert authorization["debt_artifact_sha256"] == _sha256(paths["debt"])
    assert receipt["debt_artifact_sha256"] == authorization[
        "debt_artifact_sha256"
    ]
    assert apply_or_verify_quality_debt_effect(
        tmp_path,
        prepared.effect_payload(),
        expected_receipt=receipt,
    ) == receipt
    assert authorization["decision_id"] == debt["decision_id"] == "dec-123"
    assert authorization["resolved_by"] == debt["resolved_by"] == "user"
    assert authorization["selected_candidate_id"] == debt[
        "selected_candidate_id"
    ] == "quality-candidate-0"
    assert authorization["failed_gates"] == debt["failed_gates"] == [
        {
            "name": "overall",
            "score": 0.70,
            "threshold": 0.80,
            "margin": pytest.approx(-0.10),
        }
    ]
    assert authorization["qualitative_debt"] == debt["qualitative_debt"]
    accepted_at = datetime.fromisoformat(str(authorization["accepted_at"]))
    assert accepted_at.utcoffset() == timedelta(0)
    assert "spec_quality_certificate" not in authorization
    assert "spec_quality_certificate" not in debt
    assert has_current_quality_debt_authorization(state, project_root=tmp_path)


def test_qualitative_only_debt_keeps_empty_failed_gates_and_current_sage_issues(
    tmp_path: Path,
) -> None:
    state, _candidate, prepared, paths = _debt_fixture(
        tmp_path,
        qualitative_only=True,
    )

    assert prepared.authorization["failed_gates"] == []
    assert prepared.authorization["qualitative_debt"] == [
        {
            "issue_id": "ISS-QUALITY",
            "route": "spec_repair",
            "rationale": "Residual non-critical quality debt.",
            "severity": "LOW",
            "type": "incompleteness",
            "title": "Residual quality debt",
        }
    ]
    assert has_current_quality_debt_authorization(
        state,
        project_root=tmp_path,
    )

    paths["issues"].write_bytes(paths["issues"].read_bytes() + b"\n")

    assert not has_current_quality_debt_authorization(
        state,
        project_root=tmp_path,
    )


@pytest.mark.parametrize(
    "changed",
    [
        "spec",
        "overview",
        "quality_gates",
        "issues",
        "evidence",
        "manifest",
        "debt",
        "decision",
        "decision_completion",
        "selected_candidate",
        "repair_accounting",
        "understanding_state",
    ],
)
def test_authorization_fails_closed_when_any_bound_input_changes(
    tmp_path: Path,
    changed: str,
) -> None:
    state, _candidate, _prepared, paths = _debt_fixture(tmp_path)

    if changed in {
        "spec",
        "overview",
        "quality_gates",
        "issues",
        "evidence",
        "manifest",
        "debt",
    }:
        paths[changed].write_bytes(paths[changed].read_bytes() + b"\n")
    elif changed == "decision":
        decision = dict(state["blocked_decision"])
        decision["resolved_by"] = "COMMANDER"
        state["blocked_decision"] = decision
    elif changed == "decision_completion":
        completion = dict(state["last_human_input_completion"])
        completion["decision_id"] = "dec-other"
        state["last_human_input_completion"] = completion
    elif changed == "selected_candidate":
        evidence = dict(state["proportional_quality_candidate_evidence"])
        evidence["selected_candidate_id"] = "quality-candidate-1"
        state["proportional_quality_candidate_evidence"] = evidence
    elif changed == "repair_accounting":
        repair = dict(state["phase1_quality_repair"])
        repair["automatic_consumed"] = 2
        state["phase1_quality_repair"] = repair
    else:
        evidence = dict(state["understanding_evidence"])
        evidence["digest"] = "f" * 64
        state["understanding_evidence"] = evidence

    assert not has_current_quality_debt_authorization(
        state,
        project_root=tmp_path,
    )


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("question", "Accept a different residual debt decision?"),
        ("source_state_revision", 5),
        ("resolved_at", "2099-08-14T08:02:00+00:00"),
    ],
)
def test_authorization_binds_every_resolved_decision_field(
    tmp_path: Path,
    field: str,
    replacement: object,
) -> None:
    state, _candidate, _prepared, _paths = _debt_fixture(tmp_path)
    decision = dict(state["blocked_decision"])
    decision[field] = replacement
    state["blocked_decision"] = decision

    assert not has_current_quality_debt_authorization(
        state,
        project_root=tmp_path,
    )


def test_authorization_binds_exact_resolved_decision_options(
    tmp_path: Path,
) -> None:
    state, _candidate, _prepared, _paths = _debt_fixture(tmp_path)
    decision = dict(state["blocked_decision"])
    options = [dict(option) for option in decision["options"]]
    options[1]["description"] = "Accept a differently described debt."
    decision["options"] = options
    state["blocked_decision"] = decision

    assert not has_current_quality_debt_authorization(
        state,
        project_root=tmp_path,
    )


def test_authorization_binds_exact_resolved_decision_status(
    tmp_path: Path,
) -> None:
    state, _candidate, _prepared, _paths = _debt_fixture(tmp_path)
    decision = dict(state["blocked_decision"])
    decision.update(
        {
            "status": "failed",
            "selected_option_id": None,
            "resolved_by": None,
            "resolved_at": None,
            "failure_code": "provider_error",
        }
    )
    state["blocked_decision"] = validate_blocked_decision_v2(decision)

    assert not has_current_quality_debt_authorization(
        state,
        project_root=tmp_path,
    )


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("completion_id", "4" * 32),
        ("intent_sha256", "5" * 64),
        ("receipts_sha256", "6" * 64),
    ],
)
def test_authorization_binds_exact_durable_completion(
    tmp_path: Path,
    field: str,
    replacement: str,
) -> None:
    state, _candidate, _prepared, _paths = _debt_fixture(tmp_path)
    completion = dict(state["last_human_input_completion"])
    completion[field] = replacement
    state["last_human_input_completion"] = completion

    assert not has_current_quality_debt_authorization(
        state,
        project_root=tmp_path,
    )


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("iteration", 1),
        ("failing_gates", ["overall", "traceability"]),
        ("error", "valid-shaped but stale error"),
    ],
)
def test_authorization_binds_exact_understanding_state(
    tmp_path: Path,
    field: str,
    replacement: object,
) -> None:
    state, _candidate, _prepared, _paths = _debt_fixture(tmp_path)
    evidence = dict(state["understanding_evidence"])
    evidence[field] = replacement
    state["understanding_evidence"] = evidence

    assert not has_current_quality_debt_authorization(
        state,
        project_root=tmp_path,
    )


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("schema_version", 2),
        ("current_candidate_id", "quality-candidate-other"),
        ("last_repair_outcome", "artifact_changed"),
    ],
)
def test_authorization_binds_exact_candidate_evidence_state(
    tmp_path: Path,
    field: str,
    replacement: object,
) -> None:
    state, _candidate, _prepared, _paths = _debt_fixture(tmp_path)
    evidence = dict(state["proportional_quality_candidate_evidence"])
    evidence[field] = replacement
    state["proportional_quality_candidate_evidence"] = evidence

    assert not has_current_quality_debt_authorization(
        state,
        project_root=tmp_path,
    )


@pytest.mark.parametrize(
    "hard_failure",
    [
        "critical_sage_issue",
        "sage_contradiction",
        "unresolved_evidence_or_product_decision",
        "invalid_product_input_mapping",
        "non_quality_finding_route",
        "invalid_traceability_contract",
        "mandatory_artifact_invalid",
        "provider_failure",
        "agent_timeout",
        "controller_contract_failure",
        "checkpoint_failure",
        "state_integrity_failure",
        "hard_structural_contract",
    ],
)
def test_builder_rejects_every_hard_failure_class(
    tmp_path: Path,
    hard_failure: str,
) -> None:
    state, candidate, _prepared, paths = _debt_fixture(tmp_path)
    ineligible = replace(candidate, eligibility_reasons=(hard_failure,))

    with pytest.raises(QualityCandidateIntegrityError, match="not eligible"):
        build_quality_debt_authorization(
            project_root=tmp_path,
            spec_dir=paths["spec"].parent,
            candidate=ineligible,
            candidate_manifest=paths["manifest"],
            repair_state=state["phase1_quality_repair"],
            decision=_sealed_decision(),
            decision_id="dec-123",
            resolved_by="user",
            **_builder_authority_kwargs(state),
        )


def test_builder_rejects_missing_mandatory_candidate_artifact(
    tmp_path: Path,
) -> None:
    state, candidate, _prepared, paths = _debt_fixture(tmp_path)
    (paths["spec"].parent / "issues.md").unlink()

    with pytest.raises(QualityCandidateIntegrityError):
        build_quality_debt_authorization(
            project_root=tmp_path,
            spec_dir=paths["spec"].parent,
            candidate=candidate,
            candidate_manifest=paths["manifest"],
            repair_state=state["phase1_quality_repair"],
            decision=_sealed_decision(),
            decision_id="dec-123",
            resolved_by="user",
            **_builder_authority_kwargs(state),
        )


@pytest.mark.parametrize(
    ("severity", "issue_type"),
    [
        ("CRITICAL", "incompleteness"),
        ("LOW", "contradiction"),
    ],
)
def test_builder_rejects_authoritative_hard_sage_blocker_even_if_manifest_lies(
    tmp_path: Path,
    severity: str,
    issue_type: str,
) -> None:
    state, candidate, _prepared, paths = _debt_fixture(tmp_path)
    issues = paths["issues"]
    content = issues.read_text(encoding="utf-8")
    if severity == "CRITICAL":
        content = content.replace("**CRITICAL:** 0", "**CRITICAL:** 1")
        content = content.replace("**LOW:** 1", "**LOW:** 0")
    content = content.replace("**Severity:** LOW", f"**Severity:** {severity}")
    content = content.replace(
        "**Type:** incompleteness",
        f"**Type:** {issue_type}",
    )
    issues.write_text(content, encoding="utf-8")
    digests = dict(candidate.owned_artifact_digests)
    digests["issues.md"] = _sha256(issues)
    forged = replace(
        candidate,
        owned_artifact_digests=tuple(sorted(digests.items())),
        sage_finding_routes=(
            {
                **dict(candidate.sage_finding_routes[0]),
                "severity": severity,
                "type": issue_type,
            },
        ),
        eligibility_reasons=(),
    )
    _write_json(paths["manifest"], _candidate_payload(forged))

    with pytest.raises(QualityCandidateIntegrityError, match="hard SAGE blocker"):
        build_quality_debt_authorization(
            project_root=tmp_path,
            spec_dir=paths["spec"].parent,
            candidate=forged,
            candidate_manifest=paths["manifest"],
            repair_state=state["phase1_quality_repair"],
            decision=_sealed_decision(),
            decision_id="dec-123",
            resolved_by="user",
            **_builder_authority_kwargs(state),
        )


@pytest.mark.parametrize("route_problem", ["duplicate", "non_spec_repair"])
def test_builder_rejects_non_exact_authoritative_sage_routes(
    tmp_path: Path,
    route_problem: str,
) -> None:
    state, candidate, _prepared, paths = _debt_fixture(tmp_path)
    finding = dict(candidate.sage_finding_routes[0])
    routes = (
        (finding, dict(finding))
        if route_problem == "duplicate"
        else ({**finding, "route": "human_decision"},)
    )
    forged = replace(candidate, sage_finding_routes=routes)
    _write_json(paths["manifest"], _candidate_payload(forged))

    with pytest.raises(
        QualityCandidateIntegrityError,
        match="SAGE finding route|SAGE findings",
    ):
        build_quality_debt_authorization(
            project_root=tmp_path,
            spec_dir=paths["spec"].parent,
            candidate=forged,
            candidate_manifest=paths["manifest"],
            repair_state=state["phase1_quality_repair"],
            decision=_sealed_decision(),
            decision_id="dec-123",
            resolved_by="user",
            **_builder_authority_kwargs(state),
        )


def test_builder_requires_the_registered_sealed_debt_decision(
    tmp_path: Path,
) -> None:
    state, candidate, _prepared, paths = _debt_fixture(tmp_path)
    wrong_decision = {
        **_sealed_decision(),
        "resolution_handler": "clarification_resume",
    }

    with pytest.raises(QualityCandidateIntegrityError, match="decision"):
        build_quality_debt_authorization(
            project_root=tmp_path,
            spec_dir=paths["spec"].parent,
            candidate=candidate,
            candidate_manifest=paths["manifest"],
            repair_state=state["phase1_quality_repair"],
            decision=wrong_decision,
            decision_id="dec-123",
            resolved_by="user",
            **_builder_authority_kwargs(state),
        )


def test_builder_accepts_a_claimed_commander_resolution(
    tmp_path: Path,
) -> None:
    state, candidate, _prepared, paths = _debt_fixture(tmp_path)
    commander_decision = validate_blocked_decision_v2(
        {
            **_sealed_decision(),
            "status": "resolving",
            "attempts": 1,
        }
    )

    prepared = build_quality_debt_authorization(
        project_root=tmp_path,
        spec_dir=paths["spec"].parent,
        candidate=candidate,
        candidate_manifest=paths["manifest"],
        repair_state=state["phase1_quality_repair"],
        decision=commander_decision,
        decision_id="dec-123",
        resolved_by="COMMANDER",
        **_builder_authority_kwargs(state),
    )

    assert prepared.authorization["resolved_by"] == "COMMANDER"


@pytest.mark.parametrize("resolver", ["semi", "commander", "USER", ""])
def test_builder_rejects_any_unregistered_resolver(
    tmp_path: Path,
    resolver: str,
) -> None:
    state, candidate, _prepared, paths = _debt_fixture(tmp_path)

    with pytest.raises(QualityCandidateIntegrityError, match="resolver"):
        build_quality_debt_authorization(
            project_root=tmp_path,
            spec_dir=paths["spec"].parent,
            candidate=candidate,
            candidate_manifest=paths["manifest"],
            repair_state=state["phase1_quality_repair"],
            decision=_sealed_decision(),
            decision_id="dec-123",
            resolved_by=resolver,
            **_builder_authority_kwargs(state),
        )


def test_debt_remove_unlinks_lexical_symlink_without_following_target(
    tmp_path: Path,
) -> None:
    _state, _candidate, prepared, paths = _debt_fixture(
        tmp_path,
        apply_effect=False,
    )
    target = tmp_path / "src" / "important.py"
    target.parent.mkdir()
    target.write_bytes(b"important bytes\n")
    paths["debt"].symlink_to(
        os.path.relpath(target, start=paths["debt"].parent)
    )

    receipt = apply_or_verify_quality_debt_effect(
        tmp_path,
        {
            "operation": "debt_remove",
            "debt_path": prepared.debt_path,
        },
    )

    assert receipt["removed"] is True
    assert not paths["debt"].is_symlink()
    assert target.read_bytes() == b"important bytes\n"


def test_debt_write_rejects_lexical_symlink_without_touching_target(
    tmp_path: Path,
) -> None:
    _state, _candidate, prepared, paths = _debt_fixture(
        tmp_path,
        apply_effect=False,
    )
    target = tmp_path / "src" / "important.py"
    target.parent.mkdir()
    target.write_bytes(b"important bytes\n")
    paths["debt"].symlink_to(
        os.path.relpath(target, start=paths["debt"].parent)
    )

    with pytest.raises(QualityCandidateIntegrityError):
        apply_or_verify_quality_debt_effect(
            tmp_path,
            prepared.effect_payload(),
        )

    assert paths["debt"].is_symlink()
    assert target.read_bytes() == b"important bytes\n"


def test_currentness_rejects_lexical_debt_symlink_even_with_exact_target_bytes(
    tmp_path: Path,
) -> None:
    state, _candidate, _prepared, paths = _debt_fixture(tmp_path)
    target = tmp_path / "src" / "important.py"
    target.parent.mkdir()
    target.write_bytes(paths["debt"].read_bytes())
    paths["debt"].unlink()
    paths["debt"].symlink_to(
        os.path.relpath(target, start=paths["debt"].parent)
    )

    assert not has_current_quality_debt_authorization(
        state,
        project_root=tmp_path,
    )
    assert target.read_bytes().startswith(b"{\n")


def test_debt_write_replaces_only_the_exact_regular_preimage(
    tmp_path: Path,
) -> None:
    state, candidate, _prepared, paths = _debt_fixture(
        tmp_path,
        apply_effect=False,
    )
    stale = b'{"stale":true}\n'
    paths["debt"].write_bytes(stale)
    prepared = build_quality_debt_authorization(
        project_root=tmp_path,
        spec_dir=paths["spec"].parent,
        candidate=candidate,
        candidate_manifest=paths["manifest"],
        repair_state=state["phase1_quality_repair"],
        decision=_sealed_decision(),
        decision_id="dec-123",
        resolved_by="user",
        **_builder_authority_kwargs(state),
    )

    receipt = apply_or_verify_quality_debt_effect(
        tmp_path,
        prepared.effect_payload(),
    )

    assert paths["debt"].read_bytes() != stale
    assert receipt["previous_debt_artifact_sha256"] == hashlib.sha256(
        stale
    ).hexdigest()
    assert apply_or_verify_quality_debt_effect(
        tmp_path,
        prepared.effect_payload(),
        expected_receipt=receipt,
    ) == receipt


def test_debt_write_rejects_regular_preimage_changed_after_preparation(
    tmp_path: Path,
) -> None:
    state, candidate, _prepared, paths = _debt_fixture(
        tmp_path,
        apply_effect=False,
    )
    paths["debt"].write_bytes(b'{"stale":true}\n')
    prepared = build_quality_debt_authorization(
        project_root=tmp_path,
        spec_dir=paths["spec"].parent,
        candidate=candidate,
        candidate_manifest=paths["manifest"],
        repair_state=state["phase1_quality_repair"],
        decision=_sealed_decision(),
        decision_id="dec-123",
        resolved_by="user",
        **_builder_authority_kwargs(state),
    )
    changed = b'{"changed":true}\n'
    paths["debt"].write_bytes(changed)

    with pytest.raises(QualityCandidateIntegrityError, match="preimage"):
        apply_or_verify_quality_debt_effect(
            tmp_path,
            prepared.effect_payload(),
        )

    assert paths["debt"].read_bytes() == changed


@pytest.mark.parametrize("drift_kind", ["regular", "symlink", "directory"])
def test_debt_write_final_exchange_preserves_last_moment_preimage_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    drift_kind: str,
) -> None:
    state, candidate, _prepared, paths = _debt_fixture(
        tmp_path,
        apply_effect=False,
    )
    paths["debt"].write_bytes(b'{"stale":true}\n')
    prepared = build_quality_debt_authorization(
        project_root=tmp_path,
        spec_dir=paths["spec"].parent,
        candidate=candidate,
        candidate_manifest=paths["manifest"],
        repair_state=state["phase1_quality_repair"],
        decision=_sealed_decision(),
        decision_id="dec-123",
        resolved_by="user",
        **_builder_authority_kwargs(state),
    )
    target = tmp_path / "src" / "important.py"
    target.parent.mkdir()
    target.write_bytes(b"important bytes\n")
    injected = False

    def inject_at_exchange(
        directory_fd: int,
        first_name: str,
        second_name: str,
    ) -> None:
        nonlocal injected
        if second_name == paths["debt"].name and not injected:
            injected = True
            paths["debt"].unlink()
            if drift_kind == "regular":
                paths["debt"].write_bytes(b"last-moment drift\n")
            elif drift_kind == "symlink":
                paths["debt"].symlink_to(
                    os.path.relpath(target, start=paths["debt"].parent)
                )
            else:
                paths["debt"].mkdir()
        completion_module._atomic_exchange_files(
            directory_fd,
            first_name,
            second_name,
        )

    monkeypatch.setattr(
        debt_module,
        "_atomic_exchange_files",
        inject_at_exchange,
        raising=False,
    )

    with pytest.raises(QualityCandidateIntegrityError, match="preimage"):
        apply_or_verify_quality_debt_effect(
            tmp_path,
            prepared.effect_payload(),
        )

    assert injected
    if drift_kind == "regular":
        assert paths["debt"].read_bytes() == b"last-moment drift\n"
    elif drift_kind == "symlink":
        assert paths["debt"].is_symlink()
        assert target.read_bytes() == b"important bytes\n"
    else:
        assert paths["debt"].is_dir()
    assert not list(paths["debt"].parent.glob(".quality-debt.json-*.tmp"))


def test_debt_write_retry_syncs_directory_after_postimage_fsync_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state, candidate, _prepared, paths = _debt_fixture(
        tmp_path,
        apply_effect=False,
    )
    paths["debt"].write_bytes(b'{"stale":true}\n')
    prepared = build_quality_debt_authorization(
        project_root=tmp_path,
        spec_dir=paths["spec"].parent,
        candidate=candidate,
        candidate_manifest=paths["manifest"],
        repair_state=state["phase1_quality_repair"],
        decision=_sealed_decision(),
        decision_id="dec-123",
        resolved_by="user",
        **_builder_authority_kwargs(state),
    )
    attempts = 0

    def fail_first_sync(_path: Path) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise OSError("injected post-replace directory fsync failure")

    monkeypatch.setattr(debt_module, "_fsync_directory", fail_first_sync)

    with pytest.raises(QualityCandidateIntegrityError, match="persistence"):
        apply_or_verify_quality_debt_effect(
            tmp_path,
            prepared.effect_payload(),
        )

    assert _sha256(paths["debt"]) == prepared.authorization[
        "debt_artifact_sha256"
    ]
    synced: list[Path] = []
    monkeypatch.setattr(
        debt_module,
        "_fsync_directory",
        lambda path: synced.append(path),
    )

    receipt = apply_or_verify_quality_debt_effect(
        tmp_path,
        prepared.effect_payload(),
    )

    assert receipt["debt_artifact_sha256"] == _sha256(paths["debt"])
    assert synced == [paths["debt"].parent]


def test_debt_remove_retry_syncs_directory_after_unlink_fsync_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _state, _candidate, prepared, paths = _debt_fixture(tmp_path)
    attempts = 0

    def fail_first_sync(_path: Path) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise OSError("injected post-unlink directory fsync failure")

    monkeypatch.setattr(debt_module, "_fsync_directory", fail_first_sync)
    payload = {
        "operation": "debt_remove",
        "debt_path": prepared.debt_path,
    }

    with pytest.raises(QualityCandidateIntegrityError, match="removal"):
        apply_or_verify_quality_debt_effect(tmp_path, payload)

    assert not paths["debt"].exists()
    synced: list[Path] = []
    monkeypatch.setattr(
        debt_module,
        "_fsync_directory",
        lambda path: synced.append(path),
    )

    receipt = apply_or_verify_quality_debt_effect(tmp_path, payload)

    assert receipt["removed"] is True
    assert synced == [paths["debt"].parent]
