from __future__ import annotations

from dataclasses import replace

import pytest

from harness.re_v2.protocol_22.graph import (
    AcceptedArtifactV2,
    build_protocol_22_graph,
    instantiate_ready_item,
    plan_next_v22,
    plan_next_v2,
)
from harness.re_v2.protocol_22.inputs import ValidatedProtocol22Inputs
from harness.re_v2.protocol_22.model import CatalogReferenceV1, WorkTemplateV2
from harness.re_v2.protocol_22.schema import Protocol22SchemaError
from harness.re_v2.protocol_24.artifacts import build_deepening_executor_catalog
from harness.re_v2.protocol_24.graph import (
    build_protocol_24_graph,
    validate_protocol_24_graph_authority,
)
from harness.re_v2.protocol_24.policies import build_deepening_v1_policy_catalog
from tests.re_v2_protocol_24_fixtures import manifest_v3
from tests.unit.test_re_v2_protocol_22_graph import _Authority, _Budget, _fixture


def _accepted_parent_fixture() -> tuple[
    object,
    dict[str, tuple[WorkTemplateV2, AcceptedArtifactV2]],
    _Authority,
    dict[str, object],
]:
    parent_manifest, parent_inputs = _fixture({"api": ("orders", "users")})
    parent_graph = build_protocol_22_graph(parent_manifest, parent_inputs)
    authority = _Authority()
    accepted_by_template: dict[str, AcceptedArtifactV2] = {}
    work_by_template: dict[str, object] = {}
    for _round in range(8):
        decision = plan_next_v22(parent_graph, authority, _Budget())
        if not decision.ready:
            break
        for item in decision.ready:
            artifact = AcceptedArtifactV2(
                artifact_key_id=item.output_key.identity,
                artifact_hash=item.work_item_id,
            )
            authority.artifacts[artifact.artifact_key_id] = artifact
            accepted_by_template[item.template_id] = artifact
            work_by_template[item.template_id] = item
    assert len(accepted_by_template) == len(parent_graph.templates)
    closure = {
        template.template_id: (template, accepted_by_template[template.template_id])
        for template in parent_graph.templates
    }
    return parent_inputs, closure, authority, work_by_template


def _deepening_fixture() -> tuple[object, object, _Authority, object, object]:
    (
        parent_inputs,
        accepted_parent,
        authority,
        parent_work,
    ) = _accepted_parent_fixture()
    policy = build_deepening_v1_policy_catalog()
    executors = build_deepening_executor_catalog(
        parent_inputs.executor_contract,
        "sha256:" + "a" * 64,
    )
    inputs = ValidatedProtocol22Inputs(
        workspace_partition=parent_inputs.workspace_partition,
        artifact_policy=policy,
        executor_contract=executors,
        immutable_objects={},
    )
    orders = next(
        domain
        for domain in inputs.workspace_partition.sources[0].domains
        if domain.source_relative_root == "orders"
    )
    manifest = replace(
        manifest_v3(),
        source_snapshot_id=inputs.workspace_partition.snapshot_id,
        workspace_partition_catalog=CatalogReferenceV1(
            inputs.workspace_partition.identity, "workspace-partition.json"
        ),
        artifact_policy_catalog=CatalogReferenceV1(
            policy.identity, "artifact-policy.json"
        ),
        executor_contract_catalog=CatalogReferenceV1(
            inputs.executor_contract.identity, "executor-contract.json"
        ),
        selection=replace(
            manifest_v3().selection,
            source_ids=("api",),
            domain_keys=(orders.domain_key,),
        ),
    )
    graph = build_protocol_24_graph(manifest, inputs, accepted_parent)
    return graph, inputs, authority, accepted_parent, parent_work


def test_domain_selection_plans_only_selected_l2_delta() -> None:
    graph, _inputs, authority, _accepted_parent, _parent_work = _deepening_fixture()
    decision = plan_next_v2(graph, authority, _Budget())

    assert {item.output_key.layer for item in decision.ready} == {"L2"}
    assert {item.output_key.artifact_kind for item in decision.ready} == {
        "domain-evidence-pack"
    }
    orders_key = next(
        item.scope.domain_key
        for item in graph.templates
        if item.layer == "L2" and item.artifact_kind == "domain-evidence-pack"
    )
    assert {item.output_key.scope.domain_key for item in decision.ready} == {
        orders_key
    }


def test_protocol_22_planner_facade_accepts_closed_protocol_24_graph() -> None:
    graph, _inputs, authority, _accepted_parent, _parent_work = _deepening_fixture()

    assert plan_next_v22(graph, authority, _Budget()) == plan_next_v2(
        graph, authority, _Budget()
    )


def test_protocol_24_graph_authority_binds_manifest_selection_and_inputs() -> None:
    graph, inputs, _authority, _accepted_parent, _parent_work = _deepening_fixture()
    manifest = replace(
        manifest_v3(),
        source_snapshot_id=inputs.workspace_partition.snapshot_id,
        workspace_partition_catalog=CatalogReferenceV1(
            inputs.workspace_partition.identity, "workspace-partition.json"
        ),
        artifact_policy_catalog=CatalogReferenceV1(
            inputs.artifact_policy.identity, "artifact-policy.json"
        ),
        executor_contract_catalog=CatalogReferenceV1(
            inputs.executor_contract.identity, "executor-contract.json"
        ),
        selection=replace(
            manifest_v3().selection,
            source_ids=graph.selected_source_ids,
            domain_keys=graph.selected_domain_keys,
        ),
    )

    assert validate_protocol_24_graph_authority(manifest, inputs, graph) is graph
    with pytest.raises(Protocol22SchemaError, match="selection"):
        validate_protocol_24_graph_authority(
            replace(
                manifest,
                selection=replace(manifest.selection, domain_keys=()),
            ),
            inputs,
            graph,
        )


def test_graph_preserves_parent_templates_and_limits_l2_to_selection() -> None:
    graph, inputs, _authority, accepted_parent, parent_work = _deepening_fixture()
    imported = [item for item in graph.templates if item.layer != "L2"]
    l2 = [item for item in graph.templates if item.layer == "L2"]

    assert all(item.goal_id == "baseline" for item in imported)
    assert {item.goal_id for item in l2} == {"selective-deepening"}
    assert {
        item.artifact_kind for item in l2 if item.scope.domain_key is not None
    } == {"domain-evidence-pack", "domain-context-bundle", "domain-baseline"}
    assert {
        item.artifact_kind for item in l2 if item.scope.domain_key is None
    } == {
        "source-overview-context-bundle",
        "source-overview",
        "source-baseline-root",
    }
    assert len({item.scope.domain_key for item in l2 if item.scope.domain_key}) == 1
    assert {
        item.producer_family
        for item in l2
        if item.artifact_kind in {"domain-baseline", "source-overview"}
    } == {"compact-deepening"}
    assert all(
        accepted_parent[item.template_id][0] == item for item in imported
    )

    accepted_by_template = {
        template_id: pair[1] for template_id, pair in accepted_parent.items()
    }
    for template in imported:
        item = instantiate_ready_item(
            template,
            {
                dependency_id: accepted_by_template[dependency_id]
                for dependency_id in template.required_template_ids
            },
            inputs,
        )
        assert item.work_item_id == parent_work[template.template_id].work_item_id


def test_l2_source_root_is_selection_relative_and_dependencies_are_unique() -> None:
    graph, _inputs, _authority, _accepted_parent, _parent_work = _deepening_fixture()
    root = next(
        item
        for item in graph.templates
        if item.layer == "L2" and item.artifact_kind == "source-baseline-root"
    )
    selected_domain = next(
        item
        for item in graph.templates
        if item.layer == "L2" and item.artifact_kind == "domain-baseline"
    )
    overview = next(
        item
        for item in graph.templates
        if item.layer == "L2" and item.artifact_kind == "source-overview"
    )

    assert root.required_template_ids == tuple(
        sorted((overview.template_id, selected_domain.template_id))
    )
    assert len(root.required_template_ids) == len(set(root.required_template_ids))
    with pytest.raises(Protocol22SchemaError, match="unique"):
        replace(
            root,
            required_template_ids=(overview.template_id, overview.template_id),
        )


def test_shared_values_reject_unregistered_future_layers() -> None:
    graph, _inputs, _authority, _accepted_parent, _parent_work = _deepening_fixture()
    l2 = next(item for item in graph.templates if item.layer == "L2")

    with pytest.raises(Protocol22SchemaError, match="layer"):
        replace(l2, layer="L3")
    with pytest.raises(Protocol22SchemaError, match="layer"):
        replace(l2, layer="L4")
