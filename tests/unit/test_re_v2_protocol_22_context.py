from __future__ import annotations

from dataclasses import dataclass, replace
import json
from typing import Mapping

import pytest

from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.protocol_22.artifacts import (
    AcceptedDependencySetV2,
    ClaimV1,
    ContextBundleV1,
    DepthDebtV1,
    DomainProjectionV1,
    EvidenceExcerptV1,
    EvidencePackV1,
    EvidenceReferenceV1,
    OmittedProjectedClaimDescriptorV1,
    SourceBaselineRootV1,
)
from harness.re_v2.protocol_22.context import (
    Protocol22ContextError,
    build_domain_context_bundle,
    build_source_baseline_root,
    build_source_overview_context_bundle,
)
from harness.re_v2.protocol_22.evidence import (
    EvidenceAuthorityDescriptorV1,
    evidence_authority_id,
)
from harness.re_v2.protocol_22.graph import (
    AcceptedArtifactV2,
    Protocol22Graph,
    build_protocol_22_graph,
    instantiate_ready_item,
)
from harness.re_v2.protocol_22.inputs import ValidatedProtocol22Inputs
from harness.re_v2.protocol_22.inventory import (
    InventoryArtifactV1,
    InventoryFileV1,
    SourcePartitionArtifactV1,
    produce_source_partition,
)
from harness.re_v2.protocol_22.model import WorkItemV2, WorkTemplateV2
from harness.re_v2.protocol_22.policies import (
    DOMAIN_SURFACES,
    ArtifactPolicyCatalogV1,
    ContextBundlePolicyParametersV1,
    build_compact_v1_policy_catalog,
    layer_policy_hash,
    policy_for,
)
from harness.re_v2.protocol_22.schema import load_canonical_object
from tests.re_v2_protocol_22_fixtures import digest
from tests.unit.test_re_v2_protocol_22_graph import _fixture, _template


def _selected_debt(*, inventory_count: int = 1) -> DepthDebtV1:
    return DepthDebtV1(
        inventory_file_count=inventory_count,
        fully_selected_file_count=inventory_count,
        partially_selected_file_count=0,
        omitted_file_count=0,
        omitted_range_count=0,
        omitted_descriptor_hash=None,
        domain_depth_debt_rollup=None,
        omitted_domain_summary_count=0,
        omitted_domain_descriptor_hash=None,
        retained_projected_claim_count=0,
        omitted_projected_claim_count=0,
        omitted_projected_claim_descriptor_hash=None,
    )


def _accepted(template_id: str, payload: bytes) -> AcceptedArtifactV2:
    return AcceptedArtifactV2(
        artifact_key_id=digest(f"key:{template_id}"),
        artifact_hash=content_digest(payload),
    )


def _template_by_id(graph: Protocol22Graph) -> dict[str, WorkTemplateV2]:
    return {template.template_id: template for template in graph.templates}


def _inventory_bytes(
    template: WorkTemplateV2,
    *,
    kind: str,
    path: str,
    ownership: str,
    payload: bytes,
    partition_id: str | None,
) -> bytes:
    record = InventoryFileV1(
        source_relative_path=path,
        mode="100644",
        object_kind="regular",
        content_hash=content_digest(payload),
        byte_count=len(payload),
        line_count=1,
        text_status="eligible_utf8",
        ownership=ownership,
    )
    value = InventoryArtifactV1(
        schema_version=1,
        artifact_kind=kind,
        scope=template.scope,
        partition_id=partition_id,
        files=(record,),
    )
    return canonical_json_bytes(value.to_json_dict())


def _evidence_pack_bytes(
    template: WorkTemplateV2,
    policies: ArtifactPolicyCatalogV1,
    inventory_bytes: bytes,
    *,
    path: str,
    ownership: str,
    payload: bytes,
    depth_debt: DepthDebtV1 | None = None,
) -> bytes:
    policy = policy_for(policies, "L0", template.artifact_kind)
    origin = template.scope.domain_key
    authority = EvidenceAuthorityDescriptorV1(
        source_id=template.scope.source_id,
        source_relative_path=path,
        authority_kind="direct",
        origin_domain_key=origin,
    )
    excerpt = EvidenceExcerptV1(
        evidence_authority_id=evidence_authority_id(authority),
        source_relative_path=path,
        ownership=ownership,
        origin_domain_key=origin,
        mode="100644",
        source_blob_hash=content_digest(payload),
        start_line=1,
        end_line=1,
        raw_excerpt_hash=content_digest(payload),
        text_lf=payload.decode("utf-8"),
        complete_file=True,
    )
    pack = EvidencePackV1(
        schema_version=1,
        artifact_kind=template.artifact_kind,
        scope=template.scope,
        layer_policy_hash=layer_policy_hash(policy),
        inventory_artifact_hash=content_digest(inventory_bytes),
        byte_estimator_id=policy.byte_estimator_id,
        max_canonical_json_bytes=policy.max_canonical_json_bytes,
        max_conservative_input_tokens=policy.max_conservative_input_tokens,
        excerpts=(excerpt,),
        depth_debt=depth_debt or _selected_debt(),
    )
    return canonical_json_bytes(pack.to_json_dict())


@dataclass(frozen=True)
class _DomainFixture:
    graph: Protocol22Graph
    inputs: ValidatedProtocol22Inputs
    context_item: WorkItemV2
    dependencies: AcceptedDependencySetV2
    context_bytes: bytes
    inventory_bytes: bytes
    evidence_bytes: bytes


def _domain_fixture(
    root: str = "orders",
    *,
    manifest_inputs: tuple[object, ValidatedProtocol22Inputs] | None = None,
    path: str | None = None,
    depth_debt: DepthDebtV1 | None = None,
) -> _DomainFixture:
    if manifest_inputs is None:
        relative_path = None
        if path is not None:
            prefix = root + "/"
            assert path.startswith(prefix)
            relative_path = path[len(prefix) :]
        manifest, inputs = _fixture(
            {"api": (root,)},
            domain_file_names=(
                None
                if relative_path is None
                else {("api", root): relative_path}
            ),
        )
    else:
        manifest, inputs = manifest_inputs
    graph = build_protocol_22_graph(manifest, inputs)
    source = inputs.workspace_partition.sources[0]
    domain = next(item for item in source.domains if item.source_relative_root == root)
    context_template = _template(
        graph,
        source.source_id,
        "domain-context-bundle",
        domain_key_value=domain.domain_key,
    )
    by_id = _template_by_id(graph)
    dependency_templates = {
        by_id[template_id].artifact_kind: by_id[template_id]
        for template_id in context_template.required_template_ids
    }
    inventory_template = dependency_templates["domain-inventory"]
    evidence_template = dependency_templates["domain-evidence-pack"]
    evidence_path = path or f"{root}/main.py"
    source_payload = f"{source.source_id}:{root}\n".encode()
    inventory_bytes = _inventory_bytes(
        inventory_template,
        kind="domain-inventory",
        path=evidence_path,
        ownership="owned",
        payload=source_payload,
        partition_id=domain.domain_partition_id,
    )
    evidence_bytes = _evidence_pack_bytes(
        evidence_template,
        inputs.artifact_policy,
        inventory_bytes,
        path=evidence_path,
        ownership="owned",
        payload=source_payload,
        depth_debt=depth_debt,
    )
    accepted_by_template = {
        inventory_template.template_id: _accepted(
            inventory_template.template_id, inventory_bytes
        ),
        evidence_template.template_id: _accepted(
            evidence_template.template_id, evidence_bytes
        ),
    }
    context_item = instantiate_ready_item(
        context_template,
        accepted_by_template,
        inputs,
    )
    by_role = {
        "domain_inventory": accepted_by_template[inventory_template.template_id],
        "domain_evidence_pack": accepted_by_template[evidence_template.template_id],
    }
    dependencies = AcceptedDependencySetV2(
        by_role=by_role,
        payloads_by_hash={
            content_digest(inventory_bytes): inventory_bytes,
            content_digest(evidence_bytes): evidence_bytes,
        },
    )
    context_bytes = build_domain_context_bundle(
        context_item,
        dependencies,
        inputs.artifact_policy,
    )
    return _DomainFixture(
        graph=graph,
        inputs=inputs,
        context_item=context_item,
        dependencies=dependencies,
        context_bytes=context_bytes,
        inventory_bytes=inventory_bytes,
        evidence_bytes=evidence_bytes,
    )


def _domain_baseline_bytes(
    fixture: _DomainFixture,
    claims_by_surface: Mapping[str, tuple[str, ...]],
) -> tuple[WorkItemV2, bytes]:
    graph = fixture.graph
    inputs = fixture.inputs
    domain_key = fixture.context_item.output_key.scope.domain_key
    template = _template(
        graph,
        fixture.context_item.output_key.scope.source_id,
        "domain-baseline",
        domain_key_value=domain_key,
    )
    accepted_context = _accepted(template.template_id, fixture.context_bytes)
    item = instantiate_ready_item(
        template,
        {template.required_template_ids[0]: accepted_context},
        inputs,
    )
    context = load_canonical_object(
        fixture.context_bytes,
        ContextBundleV1.from_json_dict,
    )
    excerpt = context.evidence[0]
    reference = EvidenceReferenceV1(
        evidence_authority_id=excerpt.evidence_authority_id,
        path=excerpt.source_relative_path,
        start_line=excerpt.start_line,
        end_line=excerpt.end_line,
    )
    surfaces: dict[str, object] = {}
    for surface in DOMAIN_SURFACES:
        statements = claims_by_surface.get(surface, ())
        surfaces[surface] = (
            {
                "status": "observed",
                "items": [
                    ClaimV1(statement, (reference,)).to_json_dict()
                    for statement in statements
                ],
                "not_established_reason_code": None,
            }
            if statements
            else {
                "status": "not_established",
                "items": [],
                "not_established_reason_code": "not_in_bounded_context",
            }
        )
    key = item.output_key
    value = {
        "schema_version": 1,
        "artifact": {
            "artifact_kind": "domain-baseline",
            "layer": "L1",
            "scope": key.scope.to_json_dict(),
            "partition_id": key.partition_id,
            "layer_policy_hash": key.layer_policy_hash,
            "dependency_hashes": list(key.dependency_hashes),
            "context_bundle_hash": content_digest(fixture.context_bytes),
        },
        "surfaces": surfaces,
        "unknowns": [],
        "depth_debt": context.depth_debt.to_json_dict(),
    }
    return item, canonical_json_bytes(value)


@dataclass(frozen=True)
class _SourceFixture:
    graph: Protocol22Graph
    inputs: ValidatedProtocol22Inputs
    item: WorkItemV2
    dependencies: AcceptedDependencySetV2
    baseline_bytes_by_domain: Mapping[str, bytes]
    context_bytes_by_domain: Mapping[str, bytes]


def _source_fixture(
    claims_by_root: Mapping[str, Mapping[str, tuple[str, ...]]],
    *,
    presentation_ids: Mapping[tuple[str, str], str] | None = None,
    shared_projection_path: str | None = None,
    debt_by_root: Mapping[str, DepthDebtV1] | None = None,
) -> _SourceFixture:
    roots = tuple(claims_by_root)
    manifest, inputs = _fixture(
        {"api": roots},
        presentation_ids=presentation_ids,
    )
    graph = build_protocol_22_graph(manifest, inputs)
    by_id = _template_by_id(graph)
    baselines: dict[str, tuple[WorkItemV2, bytes]] = {}
    contexts: dict[str, bytes] = {}
    for root in roots:
        domain = _domain_fixture(
            root,
            manifest_inputs=(manifest, inputs),
            path=shared_projection_path,
            depth_debt=(debt_by_root or {}).get(root),
        )
        baseline_item, baseline_bytes = _domain_baseline_bytes(
            domain,
            claims_by_root[root],
        )
        domain_key = baseline_item.output_key.scope.domain_key
        baselines[domain_key] = (baseline_item, baseline_bytes)
        contexts[domain_key] = domain.context_bytes

    source = inputs.workspace_partition.sources[0]
    source_context_template = _template(
        graph,
        source.source_id,
        "source-overview-context-bundle",
    )
    dependency_templates = {
        template_id: by_id[template_id]
        for template_id in source_context_template.required_template_ids
    }
    source_inventory_template = next(
        value
        for value in dependency_templates.values()
        if value.artifact_kind == "source-inventory"
    )
    source_partition_template = next(
        value
        for value in dependency_templates.values()
        if value.artifact_kind == "source-partition"
    )
    source_evidence_template = next(
        value
        for value in dependency_templates.values()
        if value.artifact_kind == "source-evidence-pack"
    )
    source_record = source.files[0]
    source_root = next(
        domain.source_relative_root
        for domain in source.domains
        if source_record.source_relative_path.startswith(
            f"{domain.source_relative_root}/"
        )
    )
    source_payload = f"{source.source_id}:{source_root}\n".encode()
    source_inventory = _inventory_bytes(
        source_inventory_template,
        kind="source-inventory",
        path=source_record.source_relative_path,
        ownership="source",
        payload=source_payload,
        partition_id=None,
    )
    source_evidence = _evidence_pack_bytes(
        source_evidence_template,
        inputs.artifact_policy,
        source_inventory,
        path=source_record.source_relative_path,
        ownership="source",
        payload=source_payload,
    )
    source_partition_item = instantiate_ready_item(
        source_partition_template,
        {},
        inputs,
    )
    source_partition = produce_source_partition(source_partition_item, inputs)

    accepted_by_template: dict[str, AcceptedArtifactV2] = {}
    direct_payloads: dict[str, bytes] = {}
    by_role: dict[str, AcceptedArtifactV2] = {}
    for template_id, dependency in dependency_templates.items():
        if dependency.artifact_kind == "source-inventory":
            payload = source_inventory
            role = "source_inventory"
        elif dependency.artifact_kind == "source-partition":
            payload = source_partition
            role = "source_partition"
        elif dependency.artifact_kind == "source-evidence-pack":
            payload = source_evidence
            role = "source_evidence_pack"
        else:
            domain_key = dependency.scope.domain_key
            payload = baselines[domain_key][1]
            role = f"domain:{domain_key}"
        accepted = _accepted(template_id, payload)
        accepted_by_template[template_id] = accepted
        by_role[role] = accepted
        direct_payloads[content_digest(payload)] = payload
    for context_bytes in contexts.values():
        direct_payloads[content_digest(context_bytes)] = context_bytes

    item = instantiate_ready_item(
        source_context_template,
        accepted_by_template,
        inputs,
    )
    return _SourceFixture(
        graph=graph,
        inputs=inputs,
        item=item,
        dependencies=AcceptedDependencySetV2(
            by_role=by_role,
            payloads_by_hash=direct_payloads,
        ),
        baseline_bytes_by_domain={key: value[1] for key, value in baselines.items()},
        context_bytes_by_domain=contexts,
    )


@pytest.mark.unit
def test_domain_bundle_has_only_exact_domain_dependencies() -> None:
    fixture = _domain_fixture()
    bundle = load_canonical_object(
        fixture.context_bytes,
        ContextBundleV1.from_json_dict,
    )

    assert bundle.domain_projections == ()
    assert {dependency.artifact_kind for dependency in bundle.dependencies} == {
        "domain-inventory",
        "domain-evidence-pack",
    }
    evidence_pack = load_canonical_object(
        fixture.evidence_bytes,
        EvidencePackV1.from_json_dict,
    )
    assert bundle.evidence == evidence_pack.excerpts
    assert bundle.depth_debt == evidence_pack.depth_debt


@pytest.mark.unit
def test_domain_bundle_rejects_missing_or_unrelated_dependency_role() -> None:
    fixture = _domain_fixture()
    missing = AcceptedDependencySetV2(
        by_role={
            role: artifact
            for role, artifact in fixture.dependencies.by_role.items()
            if role != "domain_inventory"
        },
        payloads_by_hash=fixture.dependencies.payloads_by_hash,
    )
    extra = AcceptedDependencySetV2(
        by_role={
            **fixture.dependencies.by_role,
            "unrelated": AcceptedArtifactV2(digest("extra-key"), digest("extra")),
        },
        payloads_by_hash=fixture.dependencies.payloads_by_hash,
    )

    with pytest.raises(Protocol22ContextError, match="roles|dependency"):
        build_domain_context_bundle(
            fixture.context_item,
            missing,
            fixture.inputs.artifact_policy,
        )
    with pytest.raises(Protocol22ContextError, match="roles|dependency"):
        build_domain_context_bundle(
            fixture.context_item,
            extra,
            fixture.inputs.artifact_policy,
        )


@pytest.mark.unit
def test_source_projection_preserves_materiality_order_and_rewrites_authority() -> None:
    fixture = _source_fixture(
        {
            "orders": {
                "responsibilities": ("z-most-material", "a-second"),
            }
        }
    )
    payload = build_source_overview_context_bundle(
        fixture.item,
        fixture.dependencies,
        fixture.inputs.artifact_policy,
    )
    bundle = load_canonical_object(payload, ContextBundleV1.from_json_dict)
    projection = bundle.domain_projections[0]
    source_context = load_canonical_object(
        fixture.context_bytes_by_domain[projection.domain_key],
        ContextBundleV1.from_json_dict,
    )

    assert [entry.claim.statement for entry in projection.claims] == [
        "z-most-material",
        "a-second",
    ]
    assert projection.evidence[0].source_relative_path == (
        source_context.evidence[0].source_relative_path
    )
    assert projection.evidence[0].raw_excerpt_hash == (
        source_context.evidence[0].raw_excerpt_hash
    )
    assert projection.evidence[0].ownership == "domain_projection"
    assert projection.evidence[0].evidence_authority_id != (
        source_context.evidence[0].evidence_authority_id
    )
    assert {
        ref.evidence_authority_id
        for claim in projection.claims
        for ref in claim.claim.evidence
    } == {projection.evidence[0].evidence_authority_id}
    assert projection.evidence[0].evidence_authority_id == evidence_authority_id(
        EvidenceAuthorityDescriptorV1(
            source_id="api",
            source_relative_path=projection.evidence[0].source_relative_path,
            authority_kind="domain_projection",
            origin_domain_key=projection.domain_key,
        )
    )


@pytest.mark.unit
def test_projection_omits_whole_uncitable_claim_and_hashes_original_claim() -> None:
    statement = "x" * 1024
    fixture = _source_fixture(
        {"orders": {"responsibilities": (statement,)}}
    )
    bundle = load_canonical_object(
        build_source_overview_context_bundle(
            fixture.item,
            fixture.dependencies,
            fixture.inputs.artifact_policy,
        ),
        ContextBundleV1.from_json_dict,
    )
    projection = bundle.domain_projections[0]
    baseline = next(iter(fixture.baseline_bytes_by_domain.values()))
    baseline_raw = json.loads(baseline)
    original_claim = ClaimV1.from_json_dict(
        baseline_raw["surfaces"]["responsibilities"]["items"][0]
    )
    descriptor = OmittedProjectedClaimDescriptorV1(
        domain_key=projection.domain_key,
        surface="responsibilities",
        claim_index=0,
        claim_hash=content_digest(original_claim.to_json_dict()),
        reason_code="capacity_exhausted",
    )

    assert projection.claims == ()
    assert projection.evidence == ()
    assert projection.omitted_claim_count == 1
    assert projection.omitted_claim_descriptor_hash == content_digest(
        [descriptor.to_json_dict()]
    )
    assert bundle.depth_debt.omitted_projected_claim_count == 1
    projection_policy = policy_for(
        fixture.inputs.artifact_policy,
        "L1",
        "source-overview-context-bundle",
    ).policy_parameters
    assert isinstance(projection_policy, ContextBundlePolicyParametersV1)
    assert projection_policy.projection is not None
    assert len(canonical_json_bytes(projection.to_json_dict())) <= (
        projection_policy.projection.max_canonical_bytes_per_domain
    )


@pytest.mark.unit
def test_duplicate_physical_path_in_domains_keeps_distinct_projected_authority() -> None:
    fixture = _source_fixture(
        {
            "orders": {"responsibilities": ("orders",)},
            "users": {"responsibilities": ("users",)},
        },
        shared_projection_path="shared/config.yml",
    )
    bundle = load_canonical_object(
        build_source_overview_context_bundle(
            fixture.item,
            fixture.dependencies,
            fixture.inputs.artifact_policy,
        ),
        ContextBundleV1.from_json_dict,
    )

    excerpts = [projection.evidence[0] for projection in bundle.domain_projections]
    assert {excerpt.source_relative_path for excerpt in excerpts} == {
        "shared/config.yml"
    }
    assert len({excerpt.evidence_authority_id for excerpt in excerpts}) == 2
    rollup = bundle.depth_debt.domain_depth_debt_rollup
    assert rollup is not None
    assert rollup.domain_count == 2
    assert rollup.inventory_read_set_entry_count == 2
    assert rollup.fully_selected_read_set_entry_count == 2
    assert bundle.depth_debt.retained_projected_claim_count == 2


@pytest.mark.unit
def test_domain_debt_rollup_sums_every_upstream_read_set_count() -> None:
    first_debt = DepthDebtV1(
        inventory_file_count=3,
        fully_selected_file_count=1,
        partially_selected_file_count=1,
        omitted_file_count=1,
        omitted_range_count=1,
        omitted_descriptor_hash=digest("first omissions"),
        domain_depth_debt_rollup=None,
        omitted_domain_summary_count=0,
        omitted_domain_descriptor_hash=None,
        retained_projected_claim_count=0,
        omitted_projected_claim_count=0,
        omitted_projected_claim_descriptor_hash=None,
    )
    second_debt = DepthDebtV1(
        inventory_file_count=4,
        fully_selected_file_count=2,
        partially_selected_file_count=0,
        omitted_file_count=2,
        omitted_range_count=0,
        omitted_descriptor_hash=digest("second omissions"),
        domain_depth_debt_rollup=None,
        omitted_domain_summary_count=0,
        omitted_domain_descriptor_hash=None,
        retained_projected_claim_count=0,
        omitted_projected_claim_count=0,
        omitted_projected_claim_descriptor_hash=None,
    )
    fixture = _source_fixture(
        {"orders": {}, "users": {}},
        debt_by_root={"orders": first_debt, "users": second_debt},
    )
    bundle = load_canonical_object(
        build_source_overview_context_bundle(
            fixture.item,
            fixture.dependencies,
            fixture.inputs.artifact_policy,
        ),
        ContextBundleV1.from_json_dict,
    )
    rollup = bundle.depth_debt.domain_depth_debt_rollup

    assert rollup is not None
    assert (
        rollup.domain_count,
        rollup.inventory_read_set_entry_count,
        rollup.fully_selected_read_set_entry_count,
        rollup.partially_selected_read_set_entry_count,
        rollup.omitted_read_set_entry_count,
        rollup.omitted_range_count,
    ) == (2, 7, 3, 1, 3, 1)
    debt_by_root = {"orders": first_debt, "users": second_debt}
    expected_descriptors = [
        {
            "domain_key": domain.domain_key,
            "baseline_depth_debt_hash": content_digest(
                debt_by_root[domain.source_relative_root].to_json_dict()
            ),
        }
        for domain in fixture.inputs.workspace_partition.sources[0].domains
    ]
    assert rollup.domain_debt_descriptor_hash == content_digest(expected_descriptors)


@pytest.mark.unit
def test_oversized_domain_projection_is_omitted_as_a_whole() -> None:
    presentation = "domain-" + "x" * 3_000
    fixture = _source_fixture(
        {"orders": {"responsibilities": ("orders",)}},
        presentation_ids={("api", "orders"): presentation},
    )
    bundle = load_canonical_object(
        build_source_overview_context_bundle(
            fixture.item,
            fixture.dependencies,
            fixture.inputs.artifact_policy,
        ),
        ContextBundleV1.from_json_dict,
    )

    assert bundle.domain_projections == ()
    assert bundle.depth_debt.omitted_domain_summary_count == 1
    assert bundle.depth_debt.omitted_domain_descriptor_hash is not None
    assert bundle.depth_debt.retained_projected_claim_count == 0
    assert bundle.depth_debt.omitted_projected_claim_count == 1
    assert bundle.depth_debt.omitted_projected_claim_descriptor_hash is not None
    rollup = bundle.depth_debt.domain_depth_debt_rollup
    assert rollup is not None and rollup.domain_count == 1


@pytest.mark.unit
def test_total_projection_bytes_never_exceed_32_kib() -> None:
    roots = tuple(f"domain{index:02d}" for index in range(28))
    fixture = _source_fixture(
        {root: {} for root in roots},
        presentation_ids={
            ("api", root): f"{index:03d}-" + "x" * 900
            for index, root in enumerate(roots)
        },
    )
    bundle = load_canonical_object(
        build_source_overview_context_bundle(
            fixture.item,
            fixture.dependencies,
            fixture.inputs.artifact_policy,
        ),
        ContextBundleV1.from_json_dict,
    )
    projection_bytes = canonical_json_bytes(
        [projection.to_json_dict() for projection in bundle.domain_projections]
    )

    assert len(projection_bytes) <= 32 * 1024
    assert len(bundle.domain_projections) < len(roots)
    assert (
        len(bundle.domain_projections)
        + bundle.depth_debt.omitted_domain_summary_count
        == len(roots)
    )
    assert bundle.depth_debt.omitted_projected_claim_count == 0
    assert bundle.depth_debt.omitted_projected_claim_descriptor_hash is None


@pytest.mark.unit
def test_source_context_rejects_target_policy_hash_mismatch() -> None:
    fixture = _source_fixture(
        {"orders": {"responsibilities": ("orders",)}}
    )
    base = fixture.inputs.artifact_policy
    changed_entries = []
    target = policy_for(base, "L1", "source-overview")
    changed_target = replace(
        target,
        max_canonical_json_bytes=target.max_canonical_json_bytes + 1,
    )
    for entry in base.entries:
        if entry.artifact_kind == "source-overview":
            changed_entries.append(changed_target)
        elif entry.artifact_kind == "source-overview-context-bundle":
            parameters = entry.policy_parameters
            assert isinstance(parameters, ContextBundlePolicyParametersV1)
            changed_entries.append(
                replace(
                    entry,
                    policy_parameters=replace(
                        parameters,
                        target_policy_hash=layer_policy_hash(changed_target),
                    ),
                )
            )
        else:
            changed_entries.append(entry)
    changed = ArtifactPolicyCatalogV1(
        schema_version=1,
        entries=tuple(changed_entries),
    )

    with pytest.raises(Protocol22ContextError, match="policy"):
        build_source_overview_context_bundle(
            fixture.item,
            fixture.dependencies,
            changed,
        )


@pytest.mark.unit
def test_source_context_rejects_domain_context_policy_mismatch() -> None:
    fixture = _source_fixture(
        {"orders": {"responsibilities": ("orders",)}}
    )
    domain_role = next(
        role for role in fixture.dependencies.by_role if role.startswith("domain:")
    )
    domain_key = domain_role.removeprefix("domain:")
    context_raw = json.loads(fixture.context_bytes_by_domain[domain_key])
    context_raw["context_policy_hash"] = digest("wrong domain context policy")
    changed_context = canonical_json_bytes(context_raw)
    changed_context_hash = content_digest(changed_context)
    baseline_raw = json.loads(fixture.baseline_bytes_by_domain[domain_key])
    baseline_raw["artifact"]["context_bundle_hash"] = changed_context_hash
    baseline_raw["artifact"]["dependency_hashes"] = [changed_context_hash]
    changed_baseline = canonical_json_bytes(baseline_raw)
    changed_baseline_hash = content_digest(changed_baseline)
    original = fixture.dependencies.by_role[domain_role]
    changed_artifact = AcceptedArtifactV2(
        artifact_key_id=original.artifact_key_id,
        artifact_hash=changed_baseline_hash,
    )
    changed_roles = {**fixture.dependencies.by_role, domain_role: changed_artifact}
    changed_hashes = tuple(
        sorted(artifact.artifact_hash for artifact in changed_roles.values())
    )
    changed_item = replace(
        fixture.item,
        output_key=replace(
            fixture.item.output_key,
            dependency_hashes=changed_hashes,
        ),
        required_artifact_hashes=changed_hashes,
    )
    changed_dependencies = AcceptedDependencySetV2(
        by_role=changed_roles,
        payloads_by_hash={
            **fixture.dependencies.payloads_by_hash,
            changed_context_hash: changed_context,
            changed_baseline_hash: changed_baseline,
        },
    )

    with pytest.raises(Protocol22ContextError, match="context closure"):
        build_source_overview_context_bundle(
            changed_item,
            changed_dependencies,
            fixture.inputs.artifact_policy,
        )


@pytest.mark.unit
def test_source_root_requires_overview_and_every_partition_domain() -> None:
    manifest, inputs = _fixture({"api": ("orders", "users")})
    graph = build_protocol_22_graph(manifest, inputs)
    source = inputs.workspace_partition.sources[0]
    root_template = _template(graph, source.source_id, "source-baseline-root")
    by_id = _template_by_id(graph)
    accepted_by_template: dict[str, AcceptedArtifactV2] = {}
    by_role: dict[str, AcceptedArtifactV2] = {}
    for template_id in root_template.required_template_ids:
        dependency = by_id[template_id]
        accepted = AcceptedArtifactV2(
            artifact_key_id=digest(f"key:{template_id}"),
            artifact_hash=digest(f"artifact:{template_id}"),
        )
        accepted_by_template[template_id] = accepted
        role = (
            "source_overview"
            if dependency.artifact_kind == "source-overview"
            else f"domain:{dependency.scope.domain_key}"
        )
        by_role[role] = accepted
    item = instantiate_ready_item(root_template, accepted_by_template, inputs)
    dependencies = AcceptedDependencySetV2(by_role=by_role)

    first = build_source_baseline_root(item, dependencies, inputs.workspace_partition)
    second = build_source_baseline_root(item, dependencies, inputs.workspace_partition)
    root = load_canonical_object(first, SourceBaselineRootV1.from_json_dict)

    assert first == second
    assert root.overview_artifact_hash == by_role["source_overview"].artifact_hash
    assert [domain.domain_key for domain in root.domains] == [
        domain.domain_key for domain in source.domains
    ]
    missing_role = next(role for role in by_role if role.startswith("domain:"))
    with pytest.raises(Protocol22ContextError, match="roles|dependency"):
        build_source_baseline_root(
            item,
            AcceptedDependencySetV2(
                by_role={
                    role: artifact
                    for role, artifact in by_role.items()
                    if role != missing_role
                }
            ),
            inputs.workspace_partition,
        )
