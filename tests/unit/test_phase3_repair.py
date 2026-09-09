"""Explicit reviews cannot close a different issue or a different candidate."""
from dataclasses import asdict

import pytest


def review_fixture():
    from harness.phase3_repair import RepairIdentity
    identity = RepairIdentity("run-1", "f" * 64, 7)
    manifest = {"data-model.md": "a" * 64}
    return identity, manifest, {
        "schema_version": 1,
        "identity": asdict(identity),
        "outcome": "resolved",
        "reviewed_artifacts": dict(manifest),
        "rationale": "The enum now declares the transition target.",
    }


@pytest.mark.parametrize("outcome", ["resolved", "unresolved", "unverifiable"])
def test_explicit_review_is_detached_from_provider_payload(outcome):
    from harness.phase3_repair import validate_issue_review
    identity, manifest, payload = review_fixture()
    payload["outcome"] = outcome
    review = validate_issue_review(payload, expected=identity, expected_manifest=manifest)
    payload["reviewed_artifacts"].clear()
    assert review.outcome == outcome
    assert dict(review.reviewed_artifacts) == {"data-model.md": "a" * 64}


@pytest.mark.parametrize("mutation", [
    "run", "fingerprint", "revision", "boolean_revision", "missing_artifact",
    "changed_hash", "extra_path", "traversal", "absolute", "backslash",
    "outcome", "rationale", "extra_field", "empty_manifest", "schema_bool",
])
def test_review_rejects_wrong_identity_or_incomplete_evidence(mutation):
    from harness.phase3_repair import RepairContractError, validate_issue_review
    identity, manifest, payload = review_fixture()
    if mutation in {"run", "fingerprint", "revision", "boolean_revision"}:
        key, value = {
            "run": ("run_id", "other"), "fingerprint": ("issue_fingerprint", "e" * 64),
            "revision": ("selection_revision", 8), "boolean_revision": ("selection_revision", True),
        }[mutation]
        payload["identity"][key] = value
    elif mutation == "missing_artifact":
        payload["reviewed_artifacts"] = {}
    elif mutation == "changed_hash":
        payload["reviewed_artifacts"]["data-model.md"] = "b" * 64
    elif mutation in {"extra_path", "traversal", "absolute", "backslash"}:
        path = {"extra_path": "other.md", "traversal": "../secret", "absolute": "/tmp/a", "backslash": "..\\secret"}[mutation]
        payload["reviewed_artifacts"][path] = "a" * 64
    elif mutation == "outcome":
        payload["outcome"] = "PASS"
    elif mutation == "rationale":
        payload["rationale"] = " "
    elif mutation == "extra_field":
        payload["waive_gate"] = True
    elif mutation == "empty_manifest":
        manifest.clear()
        payload["reviewed_artifacts"] = {}
    elif mutation == "schema_bool":
        payload["schema_version"] = True
    with pytest.raises(RepairContractError):
        validate_issue_review(payload, expected=identity, expected_manifest=manifest)


def test_only_sage_why3_can_supply_review_and_legacy_missing_is_unvalidated():
    from harness.phase3_repair import RepairContractError, review_from_result
    identity, manifest, payload = review_fixture()
    kwargs = {"expected": identity, "expected_manifest": manifest}
    result = {"verdict": "FAIL", "phase3_issue_review": payload}
    assert review_from_result(result, agent_id="echelon.sage", mode="WHY3", **kwargs).outcome == "resolved"
    assert review_from_result({"verdict": "PASS"}, agent_id="echelon.sage", mode="WHY3", **kwargs) is None
    for agent, mode in [("echelon.architect", "HOW"), ("echelon.sage", "WHY2"), ("echelon.orchestrator", "PLAN2")]:
        with pytest.raises(RepairContractError):
            review_from_result(result, agent_id=agent, mode=mode, **kwargs)
    with pytest.raises(RepairContractError):
        review_from_result({"phase3_issue_review": [payload, payload]}, agent_id="echelon.sage", mode="WHY3", **kwargs)
