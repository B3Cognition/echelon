from __future__ import annotations

from dataclasses import replace

import pytest

from harness.re_v2.protocol_28.artifacts import (
    EvidenceAnchorV1,
    ExhaustiveClaimV1,
    ExhaustiveDiagnosticV1,
    ExhaustiveEvidenceSliceV1,
    ExhaustiveObservationV1,
    ExhaustiveRepairPacketV1,
    ExhaustiveVerificationV1,
    Protocol28ArtifactError,
    validate_candidate,
    validate_verification,
)
from harness.re_v2.protocol_28.planning import realize_slice
from harness.re_v2.protocol_28.policies import build_initial_exhaustive_policy
from tests.re_v2_protocol_28_fixtures import digest
from tests.unit.test_re_v2_protocol_28_planning import _plan


def _candidate_fixture():  # type: ignore[no-untyped-def]
    plan, _, evidence = _plan()
    target = plan.target_plans[0]
    entry = next(item for item in target.entries if item.primary_snapshot_evidence_ids)
    spec = realize_slice(entry, {})
    shard_by_id = {item.identity: item for item in evidence.shards}
    anchors = tuple(sorted((
        EvidenceAnchorV1(
            1,
            evidence_id,
            shard_by_id[evidence_id].source_id,
            shard_by_id[evidence_id].source_relative_path,
            shard_by_id[evidence_id].byte_start,
            shard_by_id[evidence_id].byte_end,
            shard_by_id[evidence_id].raw_hash,
        )
        for evidence_id in entry.primary_snapshot_evidence_ids
    ), key=lambda item: item.identity))
    claim = ExhaustiveClaimV1(
        1,
        "behavioral",
        entry.primary_subject_ids,
        tuple(sorted(item.identity for item in anchors)),
        "The selected operation is represented by the cited immutable source range.",
    )
    observation = ExhaustiveObservationV1(
        1,
        "applicable",
        entry.category_id,
        entry.primary_subject_ids,
        entry.primary_snapshot_evidence_ids,
        (),
        "The category has authenticated behavioral evidence.",
    )
    candidate = ExhaustiveEvidenceSliceV1(
        1,
        spec.identity,
        entry.identity,
        entry.target_kind,
        entry.source_id,
        entry.target_id,
        entry.category_id,
        entry.primary_subject_ids,
        entry.primary_source_record_ids,
        entry.primary_snapshot_evidence_ids,
        anchors,
        (claim,),
        (observation,),
        entry.assigned_finding_ids,
        (),
        "Authenticated exhaustive evidence.",
    )
    return entry, spec, evidence, candidate


@pytest.mark.unit
def test_candidate_requires_exact_primary_evidence_acknowledgement() -> None:
    entry, spec, evidence, candidate = _candidate_fixture()
    missing = replace(candidate, covered_primary_evidence_ids=())

    with pytest.raises(Protocol28ArtifactError, match="primary evidence"):
        validate_candidate(
            spec, entry, evidence, missing.to_json_dict(), build_initial_exhaustive_policy()
        )


@pytest.mark.unit
def test_candidate_rejects_anchor_outside_staged_shard_range() -> None:
    entry, spec, evidence, candidate = _candidate_fixture()
    anchor = candidate.evidence_anchors[0]
    bad_anchor = replace(anchor, byte_end=anchor.byte_end + 1)
    bad_anchors = tuple(sorted(
        (bad_anchor, *candidate.evidence_anchors[1:]), key=lambda item: item.identity
    ))
    bad = replace(
        candidate,
        evidence_anchors=bad_anchors,
        claims=(
            replace(
                candidate.claims[0],
                evidence_anchor_ids=tuple(sorted(
                    (bad_anchor.identity, *(
                        item for item in candidate.claims[0].evidence_anchor_ids
                        if item != anchor.identity
                    ))
                )),
            ),
        ),
    )

    with pytest.raises(Protocol28ArtifactError, match="byte range"):
        validate_candidate(spec, entry, evidence, bad.to_json_dict(), build_initial_exhaustive_policy())


@pytest.mark.unit
def test_valid_candidate_closed_round_trip_and_validation() -> None:
    entry, spec, evidence, candidate = _candidate_fixture()

    validated = validate_candidate(
        spec, entry, evidence, candidate.to_json_dict(), build_initial_exhaustive_policy()
    )

    assert validated == candidate
    assert ExhaustiveEvidenceSliceV1.from_json_dict(candidate.to_json_dict()) == candidate


@pytest.mark.unit
def test_candidate_validation_normalizes_provider_nested_object_order() -> None:
    entry, spec, evidence, candidate = _candidate_fixture()
    second = ExhaustiveClaimV1(
        1,
        "boundary",
        entry.primary_subject_ids,
        candidate.claims[0].evidence_anchor_ids,
        "The selected boundary is explicitly represented.",
    )
    canonical = replace(
        candidate,
        claims=tuple(sorted((candidate.claims[0], second), key=lambda item: item.identity)),
    )
    raw = canonical.to_json_dict()
    raw["claims"] = list(reversed(raw["claims"]))

    assert validate_candidate(
        spec, entry, evidence, raw, build_initial_exhaustive_policy()
    ) == canonical


@pytest.mark.unit
def test_verifier_pass_requires_exact_coverage_and_no_unresolved_observations() -> None:
    entry, spec, evidence, candidate = _candidate_fixture()
    unresolved = replace(
        candidate,
        observations=(
            replace(candidate.observations[0], disposition="unresolved"),
        ),
    )
    unresolved = replace(unresolved, unresolved_finding_ids=entry.assigned_finding_ids)
    verification = ExhaustiveVerificationV1(
        1,
        spec.identity,
        unresolved.identity,
        entry.verifier_contract_hash,
        "PASS",
        (),
        unresolved.covered_primary_evidence_ids,
        unresolved.addressed_finding_ids,
    )

    with pytest.raises(Protocol28ArtifactError, match="unresolved"):
        validate_verification(spec, entry, unresolved, verification.to_json_dict())


@pytest.mark.unit
def test_verifier_repair_requires_normalized_diagnostic() -> None:
    entry, spec, _evidence, candidate = _candidate_fixture()
    verification = ExhaustiveVerificationV1(
        1,
        spec.identity,
        candidate.identity,
        entry.verifier_contract_hash,
        "REPAIR",
        (),
        candidate.covered_primary_evidence_ids,
        candidate.addressed_finding_ids,
    )

    with pytest.raises(Protocol28ArtifactError, match="diagnostic"):
        validate_verification(spec, entry, candidate, verification.to_json_dict())


@pytest.mark.unit
def test_verifier_pass_is_independent_closed_authority() -> None:
    entry, spec, _evidence, candidate = _candidate_fixture()
    verification = ExhaustiveVerificationV1(
        1,
        spec.identity,
        candidate.identity,
        entry.verifier_contract_hash,
        "PASS",
        (),
        candidate.covered_primary_evidence_ids,
        candidate.addressed_finding_ids,
    )

    assert validate_verification(spec, entry, candidate, verification.to_json_dict()) == verification
    assert ExhaustiveVerificationV1.from_json_dict(verification.to_json_dict()) == verification


@pytest.mark.unit
def test_repair_diagnostic_cannot_reference_out_of_scope_subject() -> None:
    entry, spec, _evidence, candidate = _candidate_fixture()
    diagnostic = ExhaustiveDiagnosticV1(
        1,
        candidate.identity,
        entry.verifier_contract_hash,
        "missing-planned-coverage",
        (digest("unknown-subject"),),
        candidate.covered_primary_evidence_ids,
        (),
        "A subject was omitted.",
    )
    verification = ExhaustiveVerificationV1(
        1,
        spec.identity,
        candidate.identity,
        entry.verifier_contract_hash,
        "REPAIR",
        (diagnostic,),
        candidate.covered_primary_evidence_ids,
        candidate.addressed_finding_ids,
    )

    with pytest.raises(Protocol28ArtifactError, match="diagnostic.*boundary"):
        validate_verification(spec, entry, candidate, verification.to_json_dict())


@pytest.mark.unit
def test_diagnostic_identity_ignores_explanatory_wording_and_repair_is_closed() -> None:
    entry, spec, _evidence, candidate = _candidate_fixture()
    diagnostic = ExhaustiveDiagnosticV1(
        1,
        candidate.identity,
        entry.verifier_contract_hash,
        "invalid-or-insufficient-evidence",
        candidate.covered_primary_subject_ids,
        candidate.covered_primary_evidence_ids,
        (),
        "Evidence is insufficient.",
    )
    reworded = replace(diagnostic, detail="The cited evidence remains insufficient.")
    packet = ExhaustiveRepairPacketV1(
        1,
        spec.identity,
        candidate.identity,
        (diagnostic.identity,),
        candidate.covered_primary_evidence_ids,
        2,
    )

    assert diagnostic.identity == reworded.identity
    assert ExhaustiveRepairPacketV1.from_json_dict(packet.to_json_dict()) == packet


@pytest.mark.unit
def test_candidate_rejects_unknown_result_field() -> None:
    _entry, _spec, _evidence, candidate = _candidate_fixture()
    raw = candidate.to_json_dict()
    raw["trust_me"] = True

    with pytest.raises(Protocol28ArtifactError, match="unknown fields"):
        ExhaustiveEvidenceSliceV1.from_json_dict(raw)


@pytest.mark.unit
def test_candidate_rejects_duplicate_claim_and_oversized_structured_output() -> None:
    entry, spec, evidence, candidate = _candidate_fixture()
    with pytest.raises(Protocol28ArtifactError, match="sorted and unique"):
        replace(candidate, claims=(candidate.claims[0], candidate.claims[0]))

    observations = tuple(sorted(
        (
            replace(
                candidate.observations[0],
                detail=f"{index:02d}:" + ("x" * 4000),
            )
            for index in range(20)
        ),
        key=lambda item: item.identity,
    ))
    oversized = replace(candidate, observations=observations)
    with pytest.raises(Protocol28ArtifactError, match="canonical output"):
        validate_candidate(
            spec, entry, evidence, oversized.to_json_dict(), build_initial_exhaustive_policy()
        )
