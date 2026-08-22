from __future__ import annotations

from dataclasses import replace
import json

import pytest

from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.protocol_22.artifacts import (
    AcceptedDependencySetV2,
    ArtifactEnvelopeV1,
    SourceBaselineDomainV1,
    SourceBaselineRootV1,
)
from harness.re_v2.protocol_22.graph import (
    AcceptedArtifactV2,
    build_protocol_22_graph,
    instantiate_ready_item,
)
from harness.re_v2.protocol_22.inputs import ValidatedProtocol22Inputs
from harness.re_v2.protocol_22.inventory import (
    InventoryArtifactV1,
    Protocol22InventoryError,
    SourcePartitionArtifactV1,
    produce_domain_inventory,
    produce_source_inventory,
    produce_source_partition,
    validate_deterministic_artifact,
)
from harness.re_v2.protocol_22.model import CatalogReferenceV1, RunManifestV2, WorkItemV2
from harness.re_v2.protocol_22.partition import (
    FileRecordV1,
    SourcePartitionIdentityInputV1,
    domain_content_id,
    domain_partition_id,
    source_content_id,
    source_partition_id,
)
from harness.re_v2.protocol_22.schema import load_canonical_object
from tests.re_v2_protocol_22_fixtures import digest
from tests.unit.test_re_v2_protocol_22_graph import _fixture, _template


def _item(
    manifest: RunManifestV2,
    inputs: ValidatedProtocol22Inputs,
    artifact_kind: str,
) -> WorkItemV2:
    graph = build_protocol_22_graph(manifest, inputs)
    if artifact_kind.startswith("domain-"):
        domain_key_value = inputs.workspace_partition.sources[0].domains[0].domain_key
    else:
        domain_key_value = None
    template = _template(
        graph,
        inputs.workspace_partition.sources[0].source_id,
        artifact_kind,
        domain_key_value=domain_key_value,
    )
    return instantiate_ready_item(template, {}, inputs)


def _workspace_dependency(
    inputs: ValidatedProtocol22Inputs,
) -> AcceptedDependencySetV2:
    identity = inputs.workspace_partition.identity
    return AcceptedDependencySetV2(
        by_role={
            "workspace_partition": AcceptedArtifactV2(
                artifact_key_id=identity,
                artifact_hash=identity,
            )
        }
    )


def _source_root_fixture() -> tuple[
    WorkItemV2,
    ValidatedProtocol22Inputs,
    AcceptedDependencySetV2,
    bytes,
]:
    manifest, inputs = _fixture({"api": ("orders", "users")})
    graph = build_protocol_22_graph(manifest, inputs)
    root = next(
        template
        for template in graph.templates
        if template.artifact_kind == "source-baseline-root"
    )
    templates = {template.template_id: template for template in graph.templates}
    accepted_by_template: dict[str, AcceptedArtifactV2] = {}
    accepted_by_role: dict[str, AcceptedArtifactV2] = {}
    for template_id in root.required_template_ids:
        dependency = templates[template_id]
        artifact = AcceptedArtifactV2(
            artifact_key_id=digest(f"key:{template_id}"),
            artifact_hash=digest(f"artifact:{template_id}"),
        )
        accepted_by_template[template_id] = artifact
        role = (
            "source_overview"
            if dependency.artifact_kind == "source-overview"
            else f"domain:{dependency.scope.domain_key}"
        )
        accepted_by_role[role] = artifact
    item = instantiate_ready_item(root, accepted_by_template, inputs)
    source = inputs.workspace_partition.sources[0]
    dependencies = AcceptedDependencySetV2(by_role=accepted_by_role)
    root_value = SourceBaselineRootV1(
        schema_version=1,
        artifact=ArtifactEnvelopeV1(
            artifact_kind=item.output_key.artifact_kind,
            layer=item.output_key.layer,
            scope=item.output_key.scope,
            partition_id=item.output_key.partition_id,
            layer_policy_hash=item.output_key.layer_policy_hash,
            dependency_hashes=item.output_key.dependency_hashes,
        ),
        overview_artifact_hash=accepted_by_role["source_overview"].artifact_hash,
        domains=tuple(
            SourceBaselineDomainV1(
                domain_key=domain.domain_key,
                presentation_domain_id=domain.presentation_domain_id,
                baseline_artifact_hash=accepted_by_role[
                    f"domain:{domain.domain_key}"
                ].artifact_hash,
            )
            for domain in source.domains
        ),
    )
    return item, inputs, dependencies, canonical_json_bytes(root_value.to_json_dict())


def _fixture_with_shared_support() -> tuple[RunManifestV2, ValidatedProtocol22Inputs]:
    manifest, inputs = _fixture({"api": ("orders",)})
    workspace = inputs.workspace_partition
    source = workspace.sources[0]
    domain = source.domains[0]
    owned = source.files[0]
    shared_payload = b"enabled: true\n"
    shared = FileRecordV1(
        source_relative_path="shared/config.yml",
        mode="100644",
        object_kind="regular",
        content_hash=content_digest(shared_payload),
        byte_count=len(shared_payload),
        line_count=1,
        text_status="eligible_utf8",
    )
    changed_domain = replace(
        domain,
        supporting_file_count=1,
        domain_content_id=domain_content_id(
            workspace.ownership_policy.version,
            domain.domain_key,
            domain.source_relative_root,
            (owned,),
            (shared,),
        ),
        domain_partition_id=domain_partition_id(
            workspace.partitioner,
            workspace.ownership_policy,
            domain.domain_key,
            domain.source_relative_root,
            domain.owned_domain_relative_paths,
            (shared.source_relative_path,),
        ),
        supporting_source_relative_paths=(shared.source_relative_path,),
    )
    files = tuple(sorted((owned, shared), key=lambda item: item.source_relative_path))
    partition_input = SourcePartitionIdentityInputV1(
        source_id=source.source_id,
        partitioner=workspace.partitioner,
        ownership_policy=workspace.ownership_policy,
        source_supporting_paths=(shared.source_relative_path,),
        domains=(changed_domain.partition_projection(),),
    )
    changed_source = replace(
        source,
        source_content_id=source_content_id(
            workspace.source_selection_policy_version,
            files,
        ),
        source_partition_id=source_partition_id(partition_input),
        source_supporting_paths=(shared.source_relative_path,),
        files=files,
        domains=(changed_domain,),
    )
    changed_workspace = replace(workspace, sources=(changed_source,))
    changed_inputs = replace(inputs, workspace_partition=changed_workspace)
    changed_manifest = replace(
        manifest,
        workspace_partition_catalog=CatalogReferenceV1(
            object_hash=changed_workspace.identity,
            relative_path=manifest.workspace_partition_catalog.relative_path,
        ),
    )
    return changed_manifest, changed_inputs


@pytest.mark.unit
def test_source_partition_copies_catalog_without_content_fields() -> None:
    manifest, inputs = _fixture({"api": ("orders", "users")})
    item = _item(manifest, inputs, "source-partition")

    payload = json.loads(produce_source_partition(item, inputs))
    source = inputs.workspace_partition.sources[0]

    assert payload["source_partition_id"] == source.source_partition_id
    assert payload["domains"] == [
        domain.partition_projection().to_json_dict() for domain in source.domains
    ]
    serialized = canonical_json_bytes(payload).decode("utf-8")
    assert "domain_content_id" not in serialized
    assert "owned_line_count" not in serialized
    assert "content_hash" not in serialized


@pytest.mark.unit
def test_domain_inventory_has_exact_owned_and_supporting_rows() -> None:
    manifest, inputs = _fixture_with_shared_support()
    item = _item(manifest, inputs, "domain-inventory")

    payload = json.loads(produce_domain_inventory(item, inputs))

    assert [
        (row["source_relative_path"], row["ownership"])
        for row in payload["files"]
    ] == [
        ("orders/main.py", "owned"),
        ("shared/config.yml", "shared_supporting"),
    ]


@pytest.mark.unit
def test_source_inventory_copies_every_catalog_file_as_source_owned() -> None:
    manifest, inputs = _fixture_with_shared_support()
    item = _item(manifest, inputs, "source-inventory")

    artifact = load_canonical_object(
        produce_source_inventory(item, inputs),
        InventoryArtifactV1.from_json_dict,
    )

    assert [row.source_relative_path for row in artifact.files] == [
        "orders/main.py",
        "shared/config.yml",
    ]
    assert {row.ownership for row in artifact.files} == {"source"}
    assert artifact.partition_id is None


@pytest.mark.unit
def test_inventory_and_partition_payloads_are_byte_stable() -> None:
    manifest, inputs = _fixture_with_shared_support()

    for kind, producer, decoder in (
        ("source-inventory", produce_source_inventory, InventoryArtifactV1.from_json_dict),
        ("domain-inventory", produce_domain_inventory, InventoryArtifactV1.from_json_dict),
        (
            "source-partition",
            produce_source_partition,
            SourcePartitionArtifactV1.from_json_dict,
        ),
    ):
        item = _item(manifest, inputs, kind)
        first = producer(item, inputs)
        second = producer(item, inputs)
        assert first == second
        assert canonical_json_bytes(load_canonical_object(first, decoder).to_json_dict()) == first


@pytest.mark.unit
def test_content_only_edit_preserves_source_partition_bytes() -> None:
    manifest, inputs = _fixture({"api": ("orders",)})
    item = _item(manifest, inputs, "source-partition")
    source = inputs.workspace_partition.sources[0]
    record = source.files[0]
    changed_record = replace(record, content_hash=digest("changed content"))
    domain = source.domains[0]
    changed_domain = replace(
        domain,
        domain_content_id=domain_content_id(
            inputs.workspace_partition.ownership_policy.version,
            domain.domain_key,
            domain.source_relative_root,
            (changed_record,),
            (),
        ),
    )
    changed_source = replace(
        source,
        source_content_id=source_content_id(
            inputs.workspace_partition.source_selection_policy_version,
            (changed_record,),
        ),
        files=(changed_record,),
        domains=(changed_domain,),
    )
    changed_workspace = replace(
        inputs.workspace_partition,
        sources=(changed_source,),
    )
    changed_inputs = replace(inputs, workspace_partition=changed_workspace)

    assert changed_source.source_partition_id == source.source_partition_id
    assert produce_source_partition(item, changed_inputs) == produce_source_partition(
        item, inputs
    )


@pytest.mark.unit
def test_producer_rejects_scope_and_policy_mismatch() -> None:
    manifest, inputs = _fixture({"api": ("orders",)})
    item = _item(manifest, inputs, "source-inventory")
    wrong_policy = replace(
        item,
        output_key=replace(item.output_key, layer_policy_hash=digest("wrong policy")),
    )
    wrong_scope = replace(
        item,
        output_key=replace(
            item.output_key,
            scope=replace(item.output_key.scope, source_id="other"),
        ),
    )

    with pytest.raises(Protocol22InventoryError, match="policy"):
        produce_source_inventory(wrong_policy, inputs)
    with pytest.raises(Protocol22InventoryError, match="scope|source"):
        produce_source_inventory(wrong_scope, inputs)


@pytest.mark.unit
def test_inventory_decoder_rejects_unsorted_rows() -> None:
    manifest, inputs = _fixture_with_shared_support()
    item = _item(manifest, inputs, "source-inventory")
    raw = json.loads(produce_source_inventory(item, inputs))
    raw["files"].reverse()

    with pytest.raises(Protocol22InventoryError, match="sorted"):
        InventoryArtifactV1.from_json_dict(raw)


@pytest.mark.unit
def test_deterministic_validation_requires_exact_invocation_role() -> None:
    manifest, inputs = _fixture({"api": ("orders",)})
    item = _item(manifest, inputs, "source-inventory")
    payload = produce_source_inventory(item, inputs)

    accepted = validate_deterministic_artifact(
        item,
        payload,
        inputs,
        _workspace_dependency(inputs),
    )
    missing = validate_deterministic_artifact(
        item,
        payload,
        inputs,
        AcceptedDependencySetV2(by_role={}),
    )

    assert accepted.canonical_schema_valid
    assert accepted.dependency_closure_valid
    assert accepted.policy_conformance_valid
    assert accepted.normalized_diagnostics == ()
    assert missing.canonical_schema_valid
    assert not missing.dependency_closure_valid
    assert "dependency_closure_invalid" in missing.normalized_diagnostics


@pytest.mark.unit
def test_deterministic_validation_detects_altered_catalog_projection() -> None:
    manifest, inputs = _fixture({"api": ("orders",)})
    item = _item(manifest, inputs, "source-inventory")
    raw = json.loads(produce_source_inventory(item, inputs))
    raw["files"][0]["byte_count"] += 1
    altered = canonical_json_bytes(raw)

    assessment = validate_deterministic_artifact(
        item,
        altered,
        inputs,
        _workspace_dependency(inputs),
    )

    assert assessment.canonical_schema_valid
    assert not assessment.policy_conformance_valid
    assert "catalog_projection_mismatch" in assessment.normalized_diagnostics


@pytest.mark.unit
def test_deterministic_validation_marks_noncanonical_payload_invalid() -> None:
    manifest, inputs = _fixture({"api": ("orders",)})
    item = _item(manifest, inputs, "source-inventory")
    payload = produce_source_inventory(item, inputs).rstrip(b"\n")

    assessment = validate_deterministic_artifact(
        item,
        payload,
        inputs,
        _workspace_dependency(inputs),
    )

    assert not assessment.canonical_schema_valid
    assert not assessment.policy_conformance_valid
    assert "canonical_schema_invalid" in assessment.normalized_diagnostics


@pytest.mark.unit
def test_source_root_validation_requires_exact_overview_and_domain_roles() -> None:
    item, inputs, dependencies, payload = _source_root_fixture()

    accepted = validate_deterministic_artifact(item, payload, inputs, dependencies)
    missing = validate_deterministic_artifact(
        item,
        payload,
        inputs,
        AcceptedDependencySetV2(
            by_role={
                role: artifact
                for role, artifact in dependencies.by_role.items()
                if role != "source_overview"
            }
        ),
    )
    unknown = validate_deterministic_artifact(
        item,
        payload,
        inputs,
        AcceptedDependencySetV2(
            by_role={**dependencies.by_role, "unknown": next(iter(dependencies.by_role.values()))}
        ),
    )

    assert accepted.normalized_diagnostics == ()
    assert not missing.dependency_closure_valid
    assert "dependency_closure_invalid" in missing.normalized_diagnostics
    assert not unknown.dependency_closure_valid
    assert "dependency_closure_invalid" in unknown.normalized_diagnostics
