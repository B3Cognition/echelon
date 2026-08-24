from __future__ import annotations

from dataclasses import replace

import pytest

from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.protocol_22.artifacts import (
    AcceptedDependencySetV2,
    ContextBundleV1,
    DepthDebtV1,
    EvidenceExcerptV1,
    EvidencePackV1,
)
from harness.re_v2.protocol_22.baseline import (
    CompactCandidateInputV1,
    certify_compact_candidate,
    parse_authorial_candidate,
)
from harness.re_v2.protocol_22.evidence import (
    EvidenceAuthorityDescriptorV1,
    evidence_authority_id,
)
from harness.re_v2.protocol_22.graph import (
    AcceptedArtifactV2,
    build_work_template_v2,
    instantiate_ready_item,
)
from harness.re_v2.protocol_22.inputs import ValidatedProtocol22Inputs
from harness.re_v2.protocol_22.inventory import InventoryArtifactV1, InventoryFileV1
from harness.re_v2.protocol_22.policies import layer_policy_hash, policy_for
from harness.re_v2.protocol_22.schema import load_canonical_object
from harness.re_v2.protocol_24.artifacts import (
    L2CompactBaselineArtifactV1,
    L2SourceBaselineRootV1,
    build_l2_domain_context_bundle,
    build_l2_domain_evidence_pack,
    build_l2_source_baseline_root,
    certify_l2_compact_candidate,
    parse_l2_authorial_candidate,
)
from harness.re_v2.protocol_24.artifacts import build_deepening_executor_catalog
from harness.re_v2.protocol_24.policies import build_deepening_v1_policy_catalog
from tests.re_v2_protocol_22_fixtures import digest
from tests.re_v2_protocol_24_fixtures import manifest_v3
from tests.unit.test_re_v2_protocol_22_certification import (
    _SnapshotReader,
    _valid_domain_candidate,
)
from tests.unit.test_re_v2_protocol_22_context import (
    _domain_baseline_bytes,
    _domain_fixture,
)


class _LooseSnapshot:
    def __init__(self, partition: object, payload: bytes) -> None:
        self.partition = partition
        self.payload = payload

    def read_file(self, _source_id: str, _path: str, _expected: object) -> bytes:
        return self.payload


def _l2_inputs(fixture: object) -> ValidatedProtocol22Inputs:
    return ValidatedProtocol22Inputs(
        workspace_partition=fixture.inputs.workspace_partition,
        artifact_policy=build_deepening_v1_policy_catalog(),
        executor_contract=build_deepening_executor_catalog(
            fixture.inputs.executor_contract,
            digest("deepener-agent"),
        ),
        immutable_objects={},
    )


def _accepted(payload: bytes, seed: str) -> AcceptedArtifactV2:
    return AcceptedArtifactV2(digest(seed), content_digest(payload))


def _l2_item(
    inputs: ValidatedProtocol22Inputs,
    artifact_kind: str,
    dependencies: tuple[tuple[str, bytes], ...],
):
    source = inputs.workspace_partition.sources[0]
    domain = source.domains[0] if artifact_kind.startswith("domain-") else None
    dependency_ids = {name: digest(name) for name, _payload in dependencies}
    template = build_work_template_v2(
        goal_id="selective-deepening",
        budget=manifest_v3().initial_budget_policy,
        inputs=inputs,
        source=source,
        domain=domain,
        artifact_kind=artifact_kind,
        layer="L2",
        required_template_ids=tuple(dependency_ids.values()),
    )
    accepted = {
        dependency_ids[name]: _accepted(payload, f"key-{name}")
        for name, payload in dependencies
    }
    return instantiate_ready_item(template, accepted, inputs), accepted


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


@pytest.mark.unit
def test_l2_domain_evidence_extends_l0_without_duplicating_snapshot_lines() -> None:
    fixture = _domain_fixture()
    inputs = _l2_inputs(fixture)
    l1_item, l1_baseline = _domain_baseline_bytes(
        fixture,
        {"responsibilities": ("Owns order behavior",)},
    )
    path = "orders/main.py"
    payload = b"api:orders\nretry:bounded\nfailure:propagates\n"
    inventory = InventoryArtifactV1(
        schema_version=1,
        artifact_kind="domain-inventory",
        scope=l1_item.output_key.scope,
        partition_id=l1_item.output_key.partition_id,
        files=(
            InventoryFileV1(
                source_relative_path=path,
                mode="100644",
                object_kind="regular",
                content_hash=content_digest(payload),
                byte_count=len(payload),
                line_count=3,
                text_status="eligible_utf8",
                ownership="owned",
            ),
        ),
    )
    inventory_bytes = canonical_json_bytes(inventory.to_json_dict())
    descriptor = EvidenceAuthorityDescriptorV1(
        source_id=l1_item.output_key.scope.source_id,
        source_relative_path=path,
        authority_kind="direct",
        origin_domain_key=l1_item.output_key.scope.domain_key,
    )
    first_line = b"api:orders\n"
    l0_policy = policy_for(inputs.artifact_policy, "L0", "domain-evidence-pack")
    l0_evidence = EvidencePackV1(
        schema_version=1,
        artifact_kind="domain-evidence-pack",
        scope=l1_item.output_key.scope,
        layer_policy_hash=layer_policy_hash(l0_policy),
        inventory_artifact_hash=content_digest(inventory_bytes),
        byte_estimator_id=l0_policy.byte_estimator_id,
        max_canonical_json_bytes=l0_policy.max_canonical_json_bytes,
        max_conservative_input_tokens=l0_policy.max_conservative_input_tokens,
        excerpts=(
            EvidenceExcerptV1(
                evidence_authority_id=evidence_authority_id(descriptor),
                source_relative_path=path,
                ownership="owned",
                origin_domain_key=l1_item.output_key.scope.domain_key,
                mode="100644",
                source_blob_hash=content_digest(payload),
                start_line=1,
                end_line=1,
                raw_excerpt_hash=content_digest(first_line),
                text_lf=first_line.decode(),
                complete_file=False,
            ),
        ),
        depth_debt=DepthDebtV1(
            inventory_file_count=1,
            fully_selected_file_count=0,
            partially_selected_file_count=1,
            omitted_file_count=0,
            omitted_range_count=1,
            omitted_descriptor_hash=digest("l0-debt"),
            domain_depth_debt_rollup=None,
            omitted_domain_summary_count=0,
            omitted_domain_descriptor_hash=None,
            retained_projected_claim_count=0,
            omitted_projected_claim_count=0,
            omitted_projected_claim_descriptor_hash=None,
        ),
    )
    l0_evidence_bytes = canonical_json_bytes(l0_evidence.to_json_dict())
    dependency_payloads = (
        ("parent-domain-inventory", inventory_bytes),
        ("parent-domain-evidence", l0_evidence_bytes),
        ("parent-domain-context", fixture.context_bytes),
        ("parent-domain-baseline", l1_baseline),
    )
    item, accepted = _l2_item(
        inputs,
        "domain-evidence-pack",
        (("parent-domain-inventory", inventory_bytes),),
    )
    dependencies = AcceptedDependencySetV2(
        by_role={
            "domain_inventory": accepted[digest("parent-domain-inventory")]
        },
        payloads_by_hash={
            content_digest(value): value for _name, value in dependency_payloads
        },
    )

    result = load_canonical_object(
        build_l2_domain_evidence_pack(
            item,
            dependencies,
            inputs.artifact_policy,
            _LooseSnapshot(inputs.workspace_partition, payload),
            {
                (
                    item.output_key.scope.source_id,
                    item.output_key.scope.domain_key,
                    layer,
                    kind,
                ): value
                for layer, kind, value in (
                    ("L0", "domain-evidence-pack", l0_evidence_bytes),
                    ("L1", "domain-context-bundle", fixture.context_bytes),
                    ("L1", "domain-baseline", l1_baseline),
                )
            },
        ),
        EvidencePackV1.from_json_dict,
    )

    assert result.layer_policy_hash == item.output_key.layer_policy_hash
    assert len(result.excerpts) == 1
    assert (result.excerpts[0].start_line, result.excerpts[0].end_line) == (1, 3)
    assert result.excerpts[0].text_lf == payload.decode()
    assert result.excerpts[0].text_lf.count("api:orders") == 1
    assert result.depth_debt.fully_selected_file_count == 1


@pytest.mark.unit
def test_l2_domain_context_binds_only_targeted_evidence() -> None:
    fixture = _domain_fixture()
    inputs = _l2_inputs(fixture)
    l2_policy = policy_for(inputs.artifact_policy, "L2", "domain-evidence-pack")
    evidence_value = load_canonical_object(
        fixture.evidence_bytes,
        EvidencePackV1.from_json_dict,
    )
    evidence = canonical_json_bytes(
        replace(
            evidence_value,
            layer_policy_hash=layer_policy_hash(l2_policy),
            max_canonical_json_bytes=l2_policy.max_canonical_json_bytes,
            max_conservative_input_tokens=l2_policy.max_conservative_input_tokens,
        ).to_json_dict()
    )
    context_item, accepted = _l2_item(
        inputs,
        "domain-context-bundle",
        (("domain-inventory", fixture.inventory_bytes), ("l2-evidence", evidence)),
    )
    dependencies = AcceptedDependencySetV2(
        by_role={
            "domain_inventory": accepted[digest("domain-inventory")],
            "domain_evidence_pack": accepted[digest("l2-evidence")],
        },
        payloads_by_hash={
            content_digest(fixture.inventory_bytes): fixture.inventory_bytes,
            content_digest(evidence): evidence,
        },
    )

    bundle = load_canonical_object(
        build_l2_domain_context_bundle(
            context_item,
            dependencies,
            inputs.artifact_policy,
        ),
        ContextBundleV1.from_json_dict,
    )

    assert bundle.target_artifact_policy.layer == "L2"
    assert bundle.dependencies[0].artifact_hash == content_digest(evidence)
    assert bundle.evidence_pack_hash == content_digest(evidence)
    assert bundle.domain_projections == ()


@pytest.mark.unit
def test_l2_source_root_binds_only_selected_domain_baselines() -> None:
    fixture = _domain_fixture()
    inputs = _l2_inputs(fixture)
    overview = b'{"selected":"overview"}'
    domain = b'{"selected":"domain"}'
    item, accepted = _l2_item(
        inputs,
        "source-baseline-root",
        (("source-overview", overview), ("domain-baseline", domain)),
    )
    domain_key = inputs.workspace_partition.sources[0].domains[0].domain_key
    dependencies = AcceptedDependencySetV2(
        by_role={
            "source_overview": accepted[digest("source-overview")],
            f"domain:{domain_key}": accepted[digest("domain-baseline")],
        },
        payloads_by_hash={
            content_digest(overview): overview,
            content_digest(domain): domain,
        },
    )

    root = load_canonical_object(
        build_l2_source_baseline_root(
            item,
            dependencies,
            inputs.workspace_partition,
        ),
        L2SourceBaselineRootV1.from_json_dict,
    )

    assert root.artifact.layer == "L2"
    assert root.overview_artifact_hash == content_digest(overview)
    assert [entry.domain_key for entry in root.domains] == [domain_key]
