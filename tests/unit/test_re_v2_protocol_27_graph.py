from __future__ import annotations

from dataclasses import replace
from typing import Mapping

import pytest

from harness.re_v2.protocol_27.model import (
    AcceptedSourceOverviewCatalogV1,
    AcceptedSourceOutcomeV1,
)
from tests.re_v2_protocol_27_fixtures import (
    accepted_source_outcome_v1,
    accepted_source_overview_projection_v1,
    digest,
)
from tests.unit.test_re_v2_protocol_22_graph import _partition


def _inputs(
    *,
    source_hashes: Mapping[str, str] | None = None,
    partial_sources: frozenset[str] = frozenset(),
    policy_seed: str = "policy",
    source_ids: tuple[str, ...] = ("api", "web"),
):
    from harness.re_v2.protocol_27.graph import (
        SynthesisGraphInputsV1,
        build_workspace_synthesis_topology,
    )
    from harness.re_v2.protocol_27.policies import (
        SynthesisImplementationAuthorityV1,
        build_synthesis_policy_catalog,
    )

    domain_paths = {
        source_id: (f"src/{source_id}-core", f"src/{source_id}-edge")
        for source_id in source_ids
    }
    partition = _partition(
        domain_paths,
        presentation_ids={
            (source_id, path): f"{index:03d}-re-{path.rsplit('/', 1)[-1]}"
            for source_id, paths in domain_paths.items()
            for index, path in enumerate(paths, start=1)
        },
    )
    hashes = dict(source_hashes or {})
    sources: list[AcceptedSourceOutcomeV1] = []
    projections = []
    for source_id in source_ids:
        base = accepted_source_outcome_v1(
            source_id,
            outcome="partial" if source_id in partial_sources else "complete",
        )
        if source_id in hashes:
            base = replace(base, source_root_hash=hashes[source_id])
        sources.append(base)
        projection = accepted_source_overview_projection_v1(source_id)
        projections.append(
            replace(
                projection,
                source_root_key_id=base.source_root_key_id,
                source_root_hash=base.source_root_hash,
            )
        )
    authority = SynthesisImplementationAuthorityV1(
        schema_version=1,
        producer_authority_hash=digest(f"{policy_seed}:producer"),
        executor_contract_hash=digest(f"{policy_seed}:executor"),
        verifier_authority_hash=digest(f"{policy_seed}:verifier"),
    )
    policy = build_synthesis_policy_catalog(authority)
    response_hashes = {
        entry.artifact_kind: digest(f"schema:{entry.artifact_kind}")
        for entry in policy.entries
    }
    return SynthesisGraphInputsV1(
        accepted_sources=tuple(sources),
        source_overviews=AcceptedSourceOverviewCatalogV1(1, tuple(projections)),
        topology=build_workspace_synthesis_topology(partition),
        policy_catalog=policy,
        response_schema_hashes=response_hashes,
        context_policy_hash=digest("context-policy"),
    )


def _node(graph, kind: str, *, source: str | None = None, domain: str | None = None):
    matches = [
        item
        for item in graph.required_nodes
        if item.artifact_kind == kind
        and item.scope.source_id == source
        and item.scope.workspace_domain_id == domain
    ]
    assert len(matches) == 1
    return matches[0]


@pytest.mark.unit
def test_graph_has_granular_source_domain_and_workspace_nodes() -> None:
    from harness.re_v2.protocol_27.graph import build_synthesis_graph

    graph = build_synthesis_graph(_inputs())
    kinds = tuple(item.artifact_kind for item in graph.required_nodes)

    assert kinds.count("source-architecture") == 2
    assert kinds.count("source-contracts") == 2
    assert kinds.count("source-components") == 2
    assert kinds.count("workspace-domain-summary") == 4
    assert "workspace-overview" in kinds
    assert "workspace-relationships" in kinds
    assert "workspace-contracts" in kinds
    assert len(graph.public_paths) == len(graph.required_nodes) + 2


@pytest.mark.unit
def test_graph_instantiates_only_dependency_ready_exact_work_items() -> None:
    from harness.re_v2.protocol_27.graph import build_synthesis_graph

    graph = build_synthesis_graph(_inputs())
    initial = graph.ready_work_items({})

    assert len(initial) == 6
    assert {item.output_key.scope.kind for item in initial} == {"source"}
    accepted = {
        graph.node_for_work_item(item).node_id: digest(item.work_item_id)
        for item in initial
    }
    domains = graph.ready_work_items(accepted)
    assert len(domains) == 4
    assert {item.output_key.artifact_kind for item in domains} == {
        "workspace-domain-summary"
    }
    accepted.update(
        {
            graph.node_for_work_item(item).node_id: digest(item.work_item_id)
            for item in domains
        }
    )
    workspace = graph.ready_work_items(accepted)
    assert {item.output_key.artifact_kind for item in workspace} == {
        "workspace-overview",
        "workspace-relationships",
    }
    relationships = next(
        item
        for item in workspace
        if item.output_key.artifact_kind == "workspace-relationships"
    )
    accepted[graph.node_for_work_item(relationships).node_id] = digest(
        relationships.work_item_id
    )
    final = graph.ready_work_items(accepted)
    assert "workspace-contracts" in {
        item.output_key.artifact_kind for item in final
    }


@pytest.mark.unit
def test_one_source_change_preserves_unrelated_domain_key() -> None:
    from harness.re_v2.protocol_27.graph import build_synthesis_graph

    before = build_synthesis_graph(
        _inputs(source_hashes={"api": digest("api-v1"), "web": digest("web-v1")})
    )
    after = build_synthesis_graph(
        _inputs(source_hashes={"api": digest("api-v2"), "web": digest("web-v1")})
    )
    before_web = _node(before, "source-architecture", source="web")
    after_web = _node(after, "source-architecture", source="web")
    before_items = {
        before.node_for_work_item(item).node_id: item
        for item in before.ready_work_items({})
    }
    after_items = {
        after.node_for_work_item(item).node_id: item
        for item in after.ready_work_items({})
    }

    assert before_web.node_id == after_web.node_id
    assert before_items[before_web.node_id].output_key == after_items[after_web.node_id].output_key
    web_domain = next(
        item
        for item in before.topology.workspace_domains
        if item.participants[0].source_id == "web"
    )
    assert _node(
        before, "workspace-domain-summary", domain=web_domain.workspace_domain_id
    ).node_id == _node(
        after, "workspace-domain-summary", domain=web_domain.workspace_domain_id
    ).node_id
    assert _node(before, "workspace-overview").node_id != _node(
        after, "workspace-overview"
    ).node_id


@pytest.mark.unit
def test_partial_debt_rekeys_only_affected_source_and_descendants() -> None:
    from harness.re_v2.protocol_27.graph import build_synthesis_graph

    complete = build_synthesis_graph(_inputs())
    partial = build_synthesis_graph(_inputs(partial_sources=frozenset({"api"})))

    assert _node(complete, "source-components", source="web").node_id == _node(
        partial, "source-components", source="web"
    ).node_id
    assert _node(complete, "source-components", source="api").node_id != _node(
        partial, "source-components", source="api"
    ).node_id
    assert _node(complete, "workspace-overview").node_id != _node(
        partial, "workspace-overview"
    ).node_id
    assert set(partial.affected_by_source("api")) > {
        _node(partial, "source-components", source="api").node_id
    }


@pytest.mark.unit
def test_policy_change_rekeys_every_generated_node() -> None:
    from harness.re_v2.protocol_27.graph import build_synthesis_graph

    before = build_synthesis_graph(_inputs(policy_seed="v1"))
    after = build_synthesis_graph(_inputs(policy_seed="v2"))

    before_by_shape = {
        (item.artifact_kind, item.scope.identity): item.node_id
        for item in before.required_nodes
    }
    after_by_shape = {
        (item.artifact_kind, item.scope.identity): item.node_id
        for item in after.required_nodes
    }
    assert set(before_by_shape) == set(after_by_shape)
    assert all(before_by_shape[key] != after_by_shape[key] for key in before_by_shape)


@pytest.mark.unit
def test_graph_is_canonical_across_mapping_order_and_round_trips() -> None:
    from harness.re_v2.protocol_27.graph import SynthesisGraph, build_synthesis_graph

    first = build_synthesis_graph(_inputs())
    raw = first.to_json_dict()
    raw["response_schema_hashes"] = dict(
        reversed(tuple(raw["response_schema_hashes"].items()))
    )
    restored = SynthesisGraph.from_json_dict(raw)

    assert restored == first
    assert restored.graph_id == first.graph_id


@pytest.mark.unit
def test_graph_rejects_no_sources_and_unknown_response_schema() -> None:
    from harness.re_v2.protocol_27.graph import (
        Protocol27GraphError,
        SynthesisGraphInputsV1,
    )

    inputs = _inputs()
    with pytest.raises(Protocol27GraphError, match="accepted source"):
        replace(
            inputs,
            accepted_sources=(),
            source_overviews=AcceptedSourceOverviewCatalogV1(1, ()),
        )
    with pytest.raises(Protocol27GraphError, match="response schema"):
        replace(inputs, response_schema_hashes={"source-architecture": digest("only")})


@pytest.mark.unit
def test_one_source_without_domains_has_closed_workspace_graph() -> None:
    from harness.re_v2.protocol_27.graph import (
        SynthesisGraphInputsV1,
        build_synthesis_graph,
        build_workspace_synthesis_topology,
    )

    inputs = _inputs()
    source = inputs.accepted_sources[0]
    projection = inputs.source_overviews.projections[0]
    partition = _partition({"api": ()})
    graph = build_synthesis_graph(
        SynthesisGraphInputsV1(
            accepted_sources=(source,),
            source_overviews=AcceptedSourceOverviewCatalogV1(1, (projection,)),
            topology=build_workspace_synthesis_topology(partition),
            policy_catalog=inputs.policy_catalog,
            response_schema_hashes=inputs.response_schema_hashes,
            context_policy_hash=inputs.context_policy_hash,
        )
    )

    assert len(graph.required_nodes) == 6
    assert not graph.topology.workspace_domains
    assert len(graph.ready_work_items({})) == 3


@pytest.mark.unit
def test_graph_rejects_duplicate_public_paths_and_open_dependency_prefix() -> None:
    from harness.re_v2.protocol_27.graph import Protocol27GraphError, build_synthesis_graph

    graph = build_synthesis_graph(_inputs())
    paths = dict(graph.public_paths)
    keys = tuple(paths)
    paths[keys[1]] = paths[keys[0]]
    with pytest.raises(Protocol27GraphError, match="public paths must be unique"):
        replace(graph, public_paths=paths)

    domain = next(
        item
        for item in graph.required_nodes
        if item.artifact_kind == "workspace-domain-summary"
    )
    with pytest.raises(Protocol27GraphError, match="dependency closed"):
        graph.ready_work_items({domain.node_id: digest("domain")})
