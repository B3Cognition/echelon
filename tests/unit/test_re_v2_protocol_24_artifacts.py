from __future__ import annotations

from dataclasses import replace

import pytest

from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.protocol_22.artifacts import ContextBundleV1
from harness.re_v2.protocol_22.baseline import (
    CompactCandidateInputV1,
    certify_compact_candidate,
    parse_authorial_candidate,
)
from harness.re_v2.protocol_22.policies import layer_policy_hash, policy_for
from harness.re_v2.protocol_22.schema import load_canonical_object
from harness.re_v2.protocol_24.artifacts import (
    L2CompactBaselineArtifactV1,
    certify_l2_compact_candidate,
    parse_l2_authorial_candidate,
)
from harness.re_v2.protocol_24.policies import build_deepening_v1_policy_catalog
from tests.re_v2_protocol_22_fixtures import digest
from tests.unit.test_re_v2_protocol_22_certification import (
    _SnapshotReader,
    _valid_domain_candidate,
)
from tests.unit.test_re_v2_protocol_22_context import (
    _domain_baseline_bytes,
    _domain_fixture,
)


def _l2_fixture():
    fixture = _domain_fixture()
    l1_item, _unused = _domain_baseline_bytes(fixture, {})
    l1_context = load_canonical_object(
        fixture.context_bytes,
        ContextBundleV1.from_json_dict,
    )
    policies = build_deepening_v1_policy_catalog()
    context_policy = policy_for(policies, "L2", "domain-context-bundle")
    target_policy = policy_for(policies, "L2", "domain-baseline")
    context = replace(
        l1_context,
        context_policy_hash=layer_policy_hash(context_policy),
        target_policy_hash=layer_policy_hash(target_policy),
        target_artifact_policy=target_policy,
    )
    context_hash = content_digest(context.to_json_dict())
    key = replace(
        l1_item.output_key,
        layer="L2",
        layer_policy_hash=layer_policy_hash(target_policy),
        dependency_hashes=(context_hash,),
    )
    item = replace(
        l1_item,
        goal_id="selective-deepening",
        output_key=key,
        required_artifact_hashes=(context_hash,),
        producer_id="compact-deepening-producer-v1",
        producer_family="compact-deepening",
    )
    source = fixture.inputs.workspace_partition.sources[0]
    domain = source.domains[0]
    snapshot = _SnapshotReader(
        fixture.inputs.workspace_partition,
        {f"{domain.source_relative_root}/main.py": b"api:orders\n"},
    )
    raw = _valid_domain_candidate(context)
    candidate = CompactCandidateInputV1(
        candidate_id=digest("l2-candidate"),
        execution_capture_hash=digest("l2-capture"),
        authorial_payload=parse_l2_authorial_candidate(
            canonical_json_bytes(raw),
            "domain-baseline",
            target_policy,
        ),
    )
    verifier = fixture.inputs.executor_contract.entry_for("compact-baseline").verifier
    return fixture, l1_item, l1_context, item, context, candidate, snapshot, verifier


@pytest.mark.unit
def test_l2_candidate_reuses_compact_receipts_and_remains_unaudited() -> None:
    (
        _fixture,
        _l1_item,
        _l1_context,
        item,
        context,
        candidate,
        snapshot,
        verifier,
    ) = _l2_fixture()

    result = certify_l2_compact_candidate(
        candidate,
        item,
        context,
        snapshot,
        verifier,
    )
    artifact = load_canonical_object(
        result.artifact_bytes,
        L2CompactBaselineArtifactV1.from_json_dict,
    )

    assert result.certification.verdict == "accepted"
    assert result.certification.certification_key.artifact_key == item.output_key
    assert result.certification.assessment.semantic_status == "unaudited"
    assert artifact.artifact.layer == "L2"
    assert artifact.artifact.context_bundle_hash == content_digest(
        context.to_json_dict()
    )


@pytest.mark.unit
def test_l2_candidate_rejects_exact_l1_claim_and_evidence_duplicate() -> None:
    (
        _fixture,
        l1_item,
        l1_context,
        item,
        context,
        candidate,
        snapshot,
        verifier,
    ) = _l2_fixture()
    l1_candidate = replace(
        candidate,
        authorial_payload=parse_authorial_candidate(
            canonical_json_bytes(_valid_domain_candidate(l1_context)),
            "domain-baseline",
            l1_context.target_artifact_policy,
        ),
    )
    l1 = certify_compact_candidate(
        l1_candidate,
        l1_item,
        l1_context,
        snapshot,
        verifier,
    )

    result = certify_l2_compact_candidate(
        candidate,
        item,
        context,
        snapshot,
        verifier,
        adopted_l1_artifacts=(l1.artifact_bytes,),
    )

    assert result.certification.verdict == "rejected"
    assert result.certification.assessment.normalized_diagnostics == (
        "lower_layer_exact_duplicate",
    )
