from __future__ import annotations

from dataclasses import replace
import importlib

import pytest

from harness.re_v2.protocol_22.executors import ExecutorContractCatalogV1
from harness.re_v2.protocol_22.graph import AcceptedArtifactV2, plan_next_v2
from harness.re_v2.protocol_22.model import CatalogReferenceV1
from harness.re_v2.protocol_24.artifacts import build_deepening_executor_catalog
from harness.re_v2.protocol_25.policies import (
    SemanticExecutorContractCatalogV1,
    build_semantic_executor_catalog,
    build_semantic_v1_policy_catalog,
)
from tests.re_v2_protocol_22_fixtures import digest
from tests.re_v2_protocol_25_fixtures import manifest_v4
from tests.unit.test_re_v2_protocol_22_executors import _shared_cli_entry
from tests.unit.test_re_v2_protocol_22_graph import _Budget
from tests.unit.test_re_v2_protocol_24_graph import (
    _Authority,
    _accepted_parent_fixture,
)
from tests.unit.test_re_v2_protocol_25_policies import _authorities


def _graph_module():  # type: ignore[no-untyped-def]
    try:
        return importlib.import_module("harness.re_v2.protocol_25.graph")
    except ModuleNotFoundError:
        pytest.fail("protocol 2.5 ascending graph is not registered")


def _fixture(*, all_domains: bool = False):  # type: ignore[no-untyped-def]
    module = _graph_module()
    parent_inputs, accepted_parent, authority, _work = _accepted_parent_fixture()
    shared_parent = ExecutorContractCatalogV1(
        schema_version=1,
        entries=tuple(
            sorted(
                (
                    *(
                        entry
                        for entry in parent_inputs.executor_contract.entries
                        if entry.producer_family != "compact-baseline"
                    ),
                    _shared_cli_entry(),
                ),
                key=lambda entry: entry.producer_family,
            )
        ),
    )
    deepening = build_deepening_executor_catalog(
        parent_inputs.executor_contract,
        digest("deepener-agent"),
        digest("deepening-implementation"),
    )
    policies = build_semantic_v1_policy_catalog()
    semantic = build_semantic_executor_catalog(shared_parent, _authorities())
    executors = SemanticExecutorContractCatalogV1(
        schema_version=1,
        inherited_catalog=deepening,
        semantic_entries=semantic.semantic_entries,
    )
    inputs = module.Protocol25GraphInputsV1(
        workspace_partition=parent_inputs.workspace_partition,
        artifact_policy=policies,
        executor_contract=executors,
        audit_policy=policies.audit_taxonomy,
        immutable_objects={},
    )
    source = inputs.workspace_partition.sources[0]
    orders = next(
        item for item in source.domains if item.source_relative_root == "orders"
    )
    selection = replace(
        manifest_v4().selection,
        source_ids=("api",),
        domain_keys=(() if all_domains else (orders.domain_key,)),
    )
    manifest = replace(
        manifest_v4(),
        source_snapshot_id=inputs.workspace_partition.snapshot_id,
        workspace_partition_catalog=CatalogReferenceV1(
            inputs.workspace_partition.identity,
            "workspace-partition.json",
        ),
        artifact_policy_catalog=CatalogReferenceV1(
            policies.identity,
            "artifact-policy.json",
        ),
        executor_contract_catalog=CatalogReferenceV1(
            executors.identity,
            "executor-contract.json",
        ),
        audit_policy_catalog=CatalogReferenceV1(
            policies.audit_taxonomy.identity,
            "audit-policy.json",
        ),
        selection=selection,
    )
    graph = module.build_protocol_25_graph(manifest, inputs, accepted_parent)
    accepted_by_template = {
        template_id: pair[1] for template_id, pair in accepted_parent.items()
    }
    return graph, inputs, authority, accepted_parent, accepted_by_template


def _complete_l2(graph, authority, accepted_by_template):  # type: ignore[no-untyped-def]
    for _round in range(8):
        decision = plan_next_v2(graph.prerequisite_graph, authority, _Budget())
        if not decision.ready:
            break
        for item in decision.ready:
            artifact = AcceptedArtifactV2(
                artifact_key_id=item.output_key.identity,
                artifact_hash=item.work_item_id,
            )
            authority.artifacts[artifact.artifact_key_id] = artifact
            accepted_by_template[item.template_id] = artifact
    assert not plan_next_v2(graph.prerequisite_graph, authority, _Budget()).ready


def test_l1_parent_schedules_missing_l2_before_audit() -> None:
    graph, _inputs, authority, _parent, accepted = _fixture()

    first = plan_next_v2(graph.prerequisite_graph, authority, _Budget())

    assert first.ready
    assert {item.output_key.layer for item in first.ready} == {"L2"}
    assert graph.ready_audit_targets(accepted) == ()


def test_domain_selection_adds_domain_and_source_targets() -> None:
    graph, inputs, authority, _parent, accepted = _fixture()
    _complete_l2(graph, authority, accepted)

    targets = graph.ready_audit_targets(accepted)

    assert tuple((item.target_kind, item.scope.domain_key) for item in targets) == (
        ("domain", graph.selected_domain_keys[0]),
        ("source", None),
    )
    assert graph.source_target("api").coverage == "selected-domains"
    assert len(graph.not_requested_domain_keys) == 1
    assert {item.audit_policy_hash for item in targets} == {
        inputs.audit_policy.identity
    }


def test_all_source_selection_adds_every_nonempty_domain_and_full_source_target() -> None:
    graph, _inputs, authority, _parent, accepted = _fixture(all_domains=True)
    _complete_l2(graph, authority, accepted)

    targets = graph.ready_audit_targets(accepted)

    assert len([item for item in targets if item.target_kind == "domain"]) == 2
    assert len([item for item in targets if item.target_kind == "source"]) == 1
    assert graph.source_target("api").coverage == "full-source"
    assert graph.not_requested_domain_keys == ()


def test_audit_target_waits_for_every_exact_l2_dependency() -> None:
    graph, _inputs, authority, _parent, accepted = _fixture()
    _complete_l2(graph, authority, accepted)
    plan = graph.audit_target_plans[0]
    missing_id = next(
        item
        for item in plan.required_template_ids
        if graph.template_by_id[item].layer == "L2"
    )
    incomplete = dict(accepted)
    del incomplete[missing_id]

    ready_scopes = {
        (item.target_kind, item.scope) for item in graph.ready_audit_targets(incomplete)
    }

    assert (plan.target_kind, plan.scope) not in ready_scopes


def test_audit_target_rejects_wrong_accepted_artifact_key() -> None:
    graph, _inputs, authority, _parent, accepted = _fixture()
    _complete_l2(graph, authority, accepted)
    template_id = graph.audit_target_plans[0].required_template_ids[0]
    original = accepted[template_id]
    tampered = dict(accepted)
    tampered[template_id] = AcceptedArtifactV2(
        artifact_key_id=digest("wrong-artifact-key"),
        artifact_hash=original.artifact_hash,
    )

    with pytest.raises(_graph_module().Protocol25GraphError, match="artifact key"):
        graph.ready_audit_targets(tampered)


def test_source_target_binds_selected_domain_and_cross_domain_l2_authority() -> None:
    graph, _inputs, authority, _parent, accepted = _fixture(all_domains=True)
    _complete_l2(graph, authority, accepted)
    source_plan = graph.source_target("api")
    required = tuple(graph.template_by_id[item] for item in source_plan.required_template_ids)

    assert {
        item.scope.domain_key
        for item in required
        if item.layer == "L2" and item.artifact_kind == "domain-baseline"
    } == set(graph.selected_domain_keys)
    assert {
        item.artifact_kind
        for item in required
        if item.layer == "L2" and item.scope.domain_key is None
    } >= {"source-overview", "source-baseline-root"}


def test_target_plan_and_materialized_target_are_deterministic() -> None:
    first, _inputs, authority, _parent, accepted = _fixture()
    _complete_l2(first, authority, accepted)
    first_targets = first.ready_audit_targets(accepted)

    second, _inputs2, authority2, _parent2, accepted2 = _fixture()
    _complete_l2(second, authority2, accepted2)
    second_targets = second.ready_audit_targets(accepted2)

    assert tuple(item.audit_target_id for item in first.audit_target_plans) == tuple(
        item.audit_target_id for item in second.audit_target_plans
    )
    assert tuple(item.identity for item in first_targets) == tuple(
        item.identity for item in second_targets
    )


def test_unknown_domain_selection_fails_closed() -> None:
    graph, inputs, _authority, accepted_parent, _accepted = _fixture()
    manifest = replace(
        graph.manifest,
        selection=replace(
            graph.manifest.selection,
            domain_keys=(digest("unknown-domain"),),
        ),
    )

    with pytest.raises(_graph_module().Protocol25GraphError, match="unknown domain"):
        _graph_module().build_protocol_25_graph(manifest, inputs, accepted_parent)


def test_audit_templates_are_l3_and_depend_only_on_selected_closure() -> None:
    graph, _inputs, _authority, _parent, _accepted = _fixture()

    assert len(graph.audit_templates) == 2
    assert {item.layer for item in graph.audit_templates} == {"L3"}
    assert {item.goal_id for item in graph.audit_templates} == {
        "semantic-audit-closure"
    }
    assert {item.producer_family for item in graph.audit_templates} == {
        "semantic-audit"
    }


def test_audit_items_preserve_domain_and_source_template_scope() -> None:
    graph, _inputs, authority, _parent, accepted = _fixture()
    _complete_l2(graph, authority, accepted)

    targets = graph.ready_audit_targets(accepted)
    items = tuple(
        graph.instantiate_audit_item(
            template,
            target,
            {
                dependency: accepted[dependency]
                for dependency in template.required_template_ids
            },
        )
        for target, template in zip(targets, graph.audit_templates, strict=True)
    )

    assert tuple(item.output_key.scope for item in items) == tuple(
        template.scope for template in graph.audit_templates
    )
    assert {item.output_key.scope.is_domain for item in items} == {False, True}
    assert tuple(item.required_artifact_hashes for item in items) == tuple(
        (target.identity,) for target in targets
    )


def test_protocol_25_graph_uses_shared_planner_for_l2_prerequisites() -> None:
    graph, _inputs, authority, _parent, _accepted = _fixture()

    assert plan_next_v2(graph, authority, _Budget()) == plan_next_v2(
        graph.prerequisite_graph,
        authority,
        _Budget(),
    )


def test_l2_parent_reuses_selected_closure_without_new_prerequisite_work() -> None:
    graph, inputs, authority, parent, accepted = _fixture()
    _complete_l2(graph, authority, accepted)
    l2_parent = dict(parent)
    for template in graph.prerequisite_graph.templates:
        if template.layer == "L2":
            l2_parent[template.template_id] = (template, accepted[template.template_id])

    rebuilt = _graph_module().build_protocol_25_graph(
        graph.manifest,
        inputs,
        l2_parent,
    )

    assert not plan_next_v2(rebuilt, authority, _Budget()).ready
    assert len(rebuilt.ready_audit_targets(accepted)) == 2


def test_protocol_package_exports_graph_builder() -> None:
    protocol = importlib.import_module("harness.re_v2.protocol_25")
    module = _graph_module()

    assert protocol.build_protocol_25_graph is module.build_protocol_25_graph
