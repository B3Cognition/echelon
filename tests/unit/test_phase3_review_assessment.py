from dataclasses import asdict
from pathlib import Path

import pytest

from harness.phase3_repair import RepairContractError, RepairIdentity, review_from_result, validate_issue_review


def assessment(**changes):
    return dict(schema_version=2, selected_issue="ISS-002", outcome="resolved",
                rationale="The contract defines the arm geometry.",
                evidence_refs=["contracts/progress-authority.md#arm"], **changes)


def bind(payload, **changes):
    args = dict(agent_id="echelon.sage", mode="WHY3", expected=RepairIdentity("run", "a" * 64, 7),
                expected_manifest={"contracts/progress-authority.md": "b" * 64}, expected_selection="ISS-002")
    args.update(changes)
    return review_from_result({"phase3_issue_review": payload}, **args)


def test_assessment_binds_dispatch_provenance_without_model_copying_hashes():
    review = bind(assessment())
    assert asdict(review.identity) == dict(run_id="run", issue_fingerprint="a" * 64, selection_revision=7)
    assert dict(review.reviewed_artifacts) == {"contracts/progress-authority.md": "b" * 64}
    # The persisted format remains the strict historical receipt contract.
    receipt = dict(schema_version=1, identity=asdict(review.identity), outcome=review.outcome,
                   reviewed_artifacts=dict(review.reviewed_artifacts), rationale=review.rationale)
    assert validate_issue_review(receipt, expected=review.identity,
                                 expected_manifest=dict(review.reviewed_artifacts)) == review


@pytest.mark.parametrize("change", [
    {"selected_issue": "ISS-001"}, {"evidence_refs": ["missing.md"]},
    {"evidence_refs": ["../spec.md"]}, {"evidence_refs": []},
    {"identity": {"run_id": "foreign"}}, {"outcome": "PASS"}, {"schema_version": True},
])
def test_compact_assessment_rejects_wrong_or_invented_authority(change):
    with pytest.raises(RepairContractError):
        bind({**assessment(), **change})


@pytest.mark.parametrize("change", [{"agent_id": "echelon.orchestrator"}, {"mode": "WHY2"}])
def test_only_dispatched_why3_can_assess_selection(change):
    with pytest.raises(RepairContractError):
        bind(assessment(), **change)


def test_malformed_legacy_hash_is_not_repaired_or_accepted():
    with pytest.raises(RepairContractError, match="SHA256"):
        bind(dict(schema_version=1, identity=asdict(RepairIdentity("run", "a" * 64, 7)),
                  outcome="resolved", rationale="Legacy", reviewed_artifacts={
                      "contracts/progress-authority.md": "023a45f5f7052c5cbd1686a954bb9a5ef7de5f7052c5cbd1686a954bb9a5ef7de5"}))


@pytest.mark.parametrize("prefix", ["", "runs/run/specs/008-test/", "/workspace/runs/run/specs/008-test/"])
def test_review_references_identify_the_same_dispatched_file(prefix):
    review = bind({**assessment(), "evidence_refs": [prefix + "contracts/progress-authority.md#arm"]},
                  expected_spec_dir=Path("/workspace/runs/run/specs/008-test"), project_root=Path("/workspace"))
    assert dict(review.reviewed_artifacts) == {"contracts/progress-authority.md": "b" * 64}
    assert review.outcome == "resolved"


@pytest.mark.parametrize("reference", [
    "runs/other/specs/008-test/contracts/progress-authority.md",
    "/elsewhere/runs/run/specs/008-test/contracts/progress-authority.md",
    "specs/008-test/contracts/progress-authority.md",  # published copy is not the candidate
    "runs/run/specs/008-test/../008-test/contracts/progress-authority.md",
    "runs/run/specs/008-test/contracts/missing.md", "file:///workspace/runs/run/specs/008-test/contracts/progress-authority.md",
    "runs/run/specs/008-test/contracts\\progress-authority.md",
])
def test_path_aliases_do_not_admit_sibling_stale_or_escaping_evidence(reference):
    with pytest.raises(RepairContractError, match="outside dispatched inputs"):
        bind({**assessment(), "evidence_refs": [reference]},
             expected_spec_dir=Path("/workspace/runs/run/specs/008-test"), project_root=Path("/workspace"))
