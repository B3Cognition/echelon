"""Focused contract for the Task 5 quality-debt authorization seam."""

import hashlib
import json
from pathlib import Path

from harness.phase1_quality_debt import build_quality_debt_authorization
from harness.proportional_quality import QualityCandidateManifest


def test_builder_writes_content_bound_schema_v1_debt_without_a_pass_certificate(
    tmp_path: Path,
) -> None:
    spec_dir = tmp_path / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    spec = spec_dir / "spec.md"
    spec.write_text("# Restored candidate\n", encoding="utf-8")
    evidence = tmp_path / "runs" / "run-1" / "evidence" / "why2.json"
    evidence.parent.mkdir(parents=True)
    evidence.write_text('{"pass":false}\n', encoding="utf-8")
    manifest_path = (
        tmp_path
        / "runs"
        / "run-1"
        / "quality-candidates"
        / "quality-candidate-0.json"
    )
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text('{"candidate_id":"quality-candidate-0"}\n')
    candidate = QualityCandidateManifest(
        schema_version=1,
        candidate_id="quality-candidate-0",
        checkpoint_commit="a" * 40,
        owned_artifact_digests=(
            ("spec.md", hashlib.sha256(spec.read_bytes()).hexdigest()),
        ),
        run_artifact_root=str(tmp_path / "runs" / "run-1"),
        understanding_evidence=str(evidence),
        understanding_evidence_digest=hashlib.sha256(
            evidence.read_bytes()
        ).hexdigest(),
        normalized_gates=(("overall", 0.70, 0.80, False),),
        sage_finding_routes=(
            {
                "issue_id": "ISS-QUALITY",
                "route": "spec_repair",
                "rationale": "Residual non-critical quality debt.",
            },
        ),
        failed_gate_count=1,
        worst_gate_margin=-0.10,
        overall_score=0.70,
        formal_statement_count=1,
        byte_count=len(spec.read_bytes()),
        repair_number=3,
        assessment_index=0,
        eligibility_reasons=(),
    )
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

    authorization = build_quality_debt_authorization(
        project_root=tmp_path,
        spec_dir=spec_dir,
        candidate=candidate,
        candidate_manifest=manifest_path,
        repair_state=repair_state,
        decision_id="dec-123",
        resolved_by="user",
    )

    debt_path = spec_dir / "quality-debt.json"
    debt = json.loads(debt_path.read_text(encoding="utf-8"))
    assert authorization["schema_version"] == 1
    assert authorization["status"] == "accepted_with_debt"
    assert authorization["source_sha256"] == hashlib.sha256(
        spec.read_bytes()
    ).hexdigest()
    assert authorization["understanding_evidence_sha256"] == hashlib.sha256(
        evidence.read_bytes()
    ).hexdigest()
    assert authorization["candidate_manifest_sha256"] == hashlib.sha256(
        manifest_path.read_bytes()
    ).hexdigest()
    assert authorization["debt_artifact_sha256"] == hashlib.sha256(
        debt_path.read_bytes()
    ).hexdigest()
    assert authorization["decision_id"] == debt["decision_id"] == "dec-123"
    assert authorization["resolved_by"] == debt["resolved_by"] == "user"
    assert debt["selected_candidate_id"] == "quality-candidate-0"
    assert debt["failed_gates"] == [
        {
            "name": "overall",
            "score": 0.70,
            "threshold": 0.80,
            "margin": -0.10,
        }
    ]
    assert "spec_quality_certificate" not in authorization
    assert "spec_quality_certificate" not in debt
