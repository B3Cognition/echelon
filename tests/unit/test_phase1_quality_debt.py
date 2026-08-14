"""Content and authority contracts for explicit Phase 1 quality debt."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path

import pytest

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
        "scores": {"overall": 0.70},
        "gates": {
            "overall": {
                "score": 0.70,
                "threshold": 0.80,
                "pass": False,
            }
        },
        "pass": False,
        "requirement_count": 1,
    }
    _write_json(evidence, report)
    margin = 0.70 - 0.80
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
        normalized_gates=(("overall", 0.70, 0.80, False),),
        sage_finding_routes=(finding,),
        failed_gate_count=1,
        worst_gate_margin=margin,
        overall_score=0.70,
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
    active_decision = _sealed_decision()
    prepared = build_quality_debt_authorization(
        project_root=tmp_path,
        spec_dir=spec_dir,
        candidate=candidate,
        candidate_manifest=manifest_path,
        repair_state=repair_state,
        decision=active_decision,
        decision_id="dec-123",
        resolved_by="user",
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
        "understanding_evidence": {
            "phase": "phase1-why2",
            "iteration": 0,
            "status": "completed",
            "path": str(evidence),
            "digest": _sha256(evidence),
            "pass": False,
            "failing_gates": ["overall"],
            "error": None,
        },
        "quality_scores": [
            {
                "pass": False,
                "pass_id": "WHY2-iter-0",
                "source": "harness:understanding",
                "evidence": str(evidence),
                "evidence_digest": _sha256(evidence),
            }
        ],
        "phase1_quality_repair": repair_state,
        "proportional_quality_candidate_evidence": {
            "schema_version": 1,
            "current_candidate_id": "quality-candidate-0",
            "selected_candidate_id": "quality-candidate-0",
            "candidate_manifest": str(manifest_path),
            "candidate_manifest_sha256": _sha256(manifest_path),
            "selected_spec_sha256": _sha256(spec_dir / "spec.md"),
            "eligibility_reasons": [],
            "failed_gates": [
                {
                    "name": "overall",
                    "score": 0.70,
                    "threshold": 0.80,
                    "pass": False,
                }
            ],
            "sage_finding_routes": [finding],
            "last_repair_outcome": None,
        },
        "blocked_decision": _sealed_decision(status="resolved"),
        "last_human_input_completion": {
            "schema_version": 1,
            "completion_id": "1" * 32,
            "intent_sha256": "2" * 64,
            "receipts_sha256": "3" * 64,
            "decision_id": "dec-123",
        },
        "spec_quality_debt_authorization": authorization,
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
        )
