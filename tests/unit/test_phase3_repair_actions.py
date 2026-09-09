from dataclasses import asdict

import pytest

from harness.phase3_repair import RepairContractError, RepairIdentity


def action_fixture():
    identity = RepairIdentity("r", "f" * 64, 7)
    return identity, {
        "schema_version": 1, "identity": asdict(identity),
        "kind": "investigate_or_design", "owner_phase": "phase3-how",
        "affected_artifacts": ["contracts/internal-interfaces.md"],
        "evidence_refs": ["spec.md#NFR-001"],
        "action": "Inspect scene fixtures and propose a reproducible observation protocol.",
        "constraints": ["Preserve NFR-001; distinguish measurements from proposals."],
    }


def validate(payload, identity):
    from harness.phase3_repair import validate_repair_action
    return validate_repair_action(payload, expected=identity,
        allowed_owner_phases=frozenset({"phase3-how"}),
        allowed_artifacts=frozenset({"contracts/internal-interfaces.md"}))


@pytest.mark.parametrize("kind", ["investigate_or_design", "apply_evidenced_resolution", "human_decision", "external_prerequisite"])
def test_action_preserves_kind_without_granting_decision_authority(kind):
    identity, payload = action_fixture()
    payload["kind"] = kind
    action = validate(payload, identity)
    payload["constraints"].clear()
    assert action.kind == kind
    assert action.identity == identity
    assert action.constraints == ("Preserve NFR-001; distinguish measurements from proposals.",)


@pytest.mark.parametrize("field,value", [
    ("kind", "approve_anything"), ("owner_phase", "phase1-what"),
    ("affected_artifacts", ["../spec.md"]), ("affected_artifacts", ["/tmp/spec.md"]),
    ("affected_artifacts", ["spec.md"]), ("affected_artifacts", []),
    ("evidence_refs", ["../secret#fact"]), ("evidence_refs", []),
    ("constraints", []), ("constraints", "preserve"), ("action", ""),
    ("schema_version", True), ("identity", {"run_id": "other"}),
])
def test_invalid_action_cannot_become_work_assignment(field, value):
    identity, payload = action_fixture()
    payload[field] = value
    with pytest.raises(RepairContractError):
        validate(payload, identity)
