from __future__ import annotations

from collections.abc import Iterable, Mapping

import pytest

from echelon.graph_read import GraphReadModel


def _edge(source: str, relation: str, target: str) -> dict[str, object]:
    return {
        "source": source,
        "type": relation,
        "target": target,
        "properties": {"evidence": f"{source}-{relation}-{target}"},
    }


def _model(
    node_ids: Iterable[str], edges: Iterable[Mapping[str, object]]
) -> GraphReadModel:
    nodes = {
        node_id: {
            "id": node_id,
            "type": "TestNode",
            "properties": {"node_id": node_id},
        }
        for node_id in node_ids
    }
    outgoing = {node_id: [] for node_id in nodes}
    incoming = {node_id: [] for node_id in nodes}
    for edge in edges:
        outgoing[str(edge["source"])].append(edge)
        incoming[str(edge["target"])].append(edge)
    return GraphReadModel(
        scope="spec",
        graph_hash="sha256:test",
        document={},
        audit=object(),  # type: ignore[arg-type]
        nodes_by_id=nodes,
        outgoing={node_id: tuple(values) for node_id, values in outgoing.items()},
        incoming={node_id: tuple(values) for node_id, values in incoming.items()},
    )


def _typed_model(
    nodes: Iterable[Mapping[str, object]], edges: Iterable[Mapping[str, object]]
) -> GraphReadModel:
    nodes_by_id = {str(node["id"]): node for node in nodes}
    outgoing = {node_id: [] for node_id in nodes_by_id}
    incoming = {node_id: [] for node_id in nodes_by_id}
    for edge in edges:
        outgoing[str(edge["source"])].append(edge)
        incoming[str(edge["target"])].append(edge)
    return GraphReadModel(
        scope="spec",
        graph_hash="sha256:test",
        document={},
        audit=object(),  # type: ignore[arg-type]
        nodes_by_id=nodes_by_id,
        outgoing={node_id: tuple(values) for node_id, values in outgoing.items()},
        incoming={node_id: tuple(values) for node_id, values in incoming.items()},
    )


def _node(
    node_id: str, node_type: str, **properties: object
) -> dict[str, object]:
    return {"id": node_id, "type": node_type, "properties": properties}


def _identities(edges: Iterable[Mapping[str, object]]) -> list[tuple[str, str, str]]:
    return [
        (str(edge["source"]), str(edge["type"]), str(edge["target"]))
        for edge in edges
    ]


@pytest.mark.unit
def test_explain_includes_selected_node_and_canonically_ordered_incident_edges() -> None:
    from echelon.graph_traversal import explain_node

    model = _model(
        ("a", "b", "c", "d"),
        (
            _edge("d", "ALPHA", "a"),
            _edge("a", "ZETA", "c"),
            _edge("b", "REL", "a"),
            _edge("a", "CONNECT", "b"),
        ),
    )

    result = explain_node(model, "a")

    assert [node["id"] for node in result.nodes] == ["a", "b", "c", "d"]
    assert _identities(result.edges) == [
        ("a", "CONNECT", "b"),
        ("a", "ZETA", "c"),
        ("b", "REL", "a"),
        ("d", "ALPHA", "a"),
    ]
    assert result.nodes[0] is model.nodes_by_id["a"]
    assert result.edges[0] is model.outgoing["a"][1]
    assert result.paths == ()
    assert result.truncated is False


@pytest.mark.unit
def test_neighbors_filter_stored_edge_arrows_case_insensitively_before_limiting() -> None:
    from echelon.graph_traversal import neighbors

    model = _model(
        ("a", "b", "c", "d"),
        (
            _edge("d", "ALPHA", "a"),
            _edge("a", "ZETA", "c"),
            _edge("b", "REL", "a"),
            _edge("a", "CONNECT", "b"),
        ),
    )

    incoming = neighbors(model, "a", direction="in", relation="rel")
    outgoing = neighbors(model, "a", direction="out", relation="connect")
    missing = neighbors(model, "a", relation="missing")
    limited = neighbors(model, "a", limit=1)

    assert _identities(incoming.edges) == [("b", "REL", "a")]
    assert [node["id"] for node in incoming.nodes] == ["a", "b"]
    assert _identities(outgoing.edges) == [("a", "CONNECT", "b")]
    assert [node["id"] for node in missing.nodes] == ["a"]
    assert missing.edges == ()
    assert missing.truncated is False
    assert _identities(limited.edges) == [("d", "ALPHA", "a")]
    assert [node["id"] for node in limited.nodes] == ["a", "d"]
    assert limited.truncated is True


@pytest.mark.unit
def test_explain_and_neighbors_deduplicate_self_loop_before_limit_and_truncation() -> None:
    from echelon.graph_traversal import explain_node, neighbors

    model = _model(("a",), (_edge("a", "LOOP", "a"),))

    explained = explain_node(model, "a", limit=1)
    adjacent = neighbors(model, "a", limit=1)

    for result in (explained, adjacent):
        assert [node["id"] for node in result.nodes] == ["a"]
        assert _identities(result.edges) == [("a", "LOOP", "a")]
        assert result.truncated is False


@pytest.mark.unit
@pytest.mark.parametrize(
    ("direction", "limit", "message"),
    [
        ("sideways", 1, "direction"),
        ("both", 0, "limit"),
    ],
)
def test_neighbors_rejects_invalid_direction_or_limit(
    direction: str, limit: int, message: str
) -> None:
    from echelon.graph_traversal import neighbors

    model = _model(("a",), ())

    with pytest.raises(ValueError, match=message):
        neighbors(model, "a", direction=direction, limit=limit)


@pytest.mark.unit
def test_explain_rejects_nonpositive_limit() -> None:
    from echelon.graph_traversal import explain_node

    model = _model(("a",), ())

    with pytest.raises(ValueError, match="limit"):
        explain_node(model, "a", limit=0)


@pytest.mark.unit
@pytest.mark.parametrize(
    "edge_order",
    [
        (0, 1, 2, 3, 4, 5),
        (5, 4, 3, 2, 1, 0),
        (2, 5, 0, 4, 1, 3),
    ],
)
def test_shortest_path_selects_one_canonical_equal_shortest_branch_across_shuffled_indexes(
    edge_order: tuple[int, ...],
) -> None:
    from echelon.graph_traversal import shortest_path

    edges = (
        _edge("right", "ROUTE", "target"),
        _edge("left", "CYCLE", "right"),
        _edge("source", "ROUTE", "right"),
        _edge("right", "CYCLE", "left"),
        _edge("left", "ROUTE", "target"),
        _edge("source", "ROUTE", "left"),
    )
    model = _model(
        ("source", "left", "right", "target", "isolated"),
        tuple(edges[index] for index in edge_order),
    )

    result = shortest_path(model, "source", "target")

    assert [path.node_ids for path in result.paths] == [("source", "left", "target")]
    assert [
        (step.source, step.type, step.target, step.direction)
        for step in result.paths[0].steps
    ] == [
        ("source", "ROUTE", "left", "out"),
        ("left", "ROUTE", "target", "out"),
    ]
    assert [node["id"] for node in result.nodes] == ["left", "source", "target"]
    assert _identities(result.edges) == [
        ("left", "ROUTE", "target"),
        ("source", "ROUTE", "left"),
    ]


@pytest.mark.unit
def test_shortest_path_walks_reverse_edges_without_reversing_stored_arrows() -> None:
    from echelon.graph_traversal import shortest_path

    model = _model(
        ("source", "left", "right", "target"),
        (
            _edge("source", "ROUTE", "right"),
            _edge("left", "ROUTE", "target"),
            _edge("source", "ROUTE", "left"),
            _edge("right", "ROUTE", "target"),
        ),
    )

    result = shortest_path(model, "target", "source")

    assert [path.node_ids for path in result.paths] == [("target", "left", "source")]
    assert [
        (step.source, step.type, step.target, step.direction)
        for step in result.paths[0].steps
    ] == [
        ("left", "ROUTE", "target", "in"),
        ("source", "ROUTE", "left", "in"),
    ]


@pytest.mark.unit
def test_shortest_path_orders_mixed_direction_steps_by_relation_before_direction() -> None:
    from echelon.graph_traversal import shortest_path

    model = _model(
        ("source", "incoming", "outgoing", "target"),
        (
            _edge("source", "ALPHA", "outgoing"),
            _edge("outgoing", "ALPHA", "target"),
            _edge("incoming", "ZETA", "source"),
            _edge("incoming", "ZETA", "target"),
        ),
    )

    result = shortest_path(model, "source", "target")

    assert [path.node_ids for path in result.paths] == [("source", "outgoing", "target")]
    assert result.paths[0].steps[0].direction == "out"


@pytest.mark.unit
def test_shortest_path_handles_identity_absence_and_hop_bounds() -> None:
    from echelon.graph_traversal import shortest_path

    model = _model(
        ("source", "middle", "target", "isolated"),
        (
            _edge("source", "ROUTE", "middle"),
            _edge("middle", "ROUTE", "target"),
        ),
    )

    identity = shortest_path(model, "source", "source")
    absent = shortest_path(model, "source", "isolated")
    bounded = shortest_path(model, "source", "target", max_hops=1)

    assert [path.node_ids for path in identity.paths] == [("source",)]
    assert identity.paths[0].steps == ()
    assert _identities(identity.edges) == []
    assert [node["id"] for node in identity.nodes] == ["source"]
    assert absent.nodes == ()
    assert absent.edges == ()
    assert absent.paths == ()
    assert bounded.paths == ()


@pytest.fixture
def query_model() -> GraphReadModel:
    return _typed_model(
        (
            _node(
                "artifact:905-import-prose:catalog",
                "Artifact",
                path="inputs/import-validation.md",
                source_text="Import validation source",
                labels=["parser", "batch"],
            ),
            _node(
                "req:905-import-prose:FR-012",
                "Requirement",
                requirement_id="FR-012",
                source_text="Reject malformed uploads",
            ),
            _node(
                "req:905-import-prose:FR-013",
                "Requirement",
                requirement_id="FR-013",
                source_text="Archive checksum remains deterministic",
            ),
            _node(
                "req:905-import-prose:FR-014",
                "Requirement",
                requirement_id="FR-014",
                source_text="Archive checksum remains deterministic",
            ),
            _node(
                "task:905-import-prose:T-001",
                "Task",
                task_id="T-001",
                target="Batch parser",
            ),
            _node(
                "artifact:905-import-prose:unicode",
                "Artifact",
                path="docs/straße.md",
                title="Straße",
                compatibility_label="compatibilitytoken",
            ),
        ),
        (
            _edge(
                "req:905-import-prose:FR-012",
                "DERIVED_FROM",
                "artifact:905-import-prose:catalog",
            ),
            _edge(
                "task:905-import-prose:T-001",
                "IMPLEMENTS",
                "req:905-import-prose:FR-012",
            ),
        ),
    )


@pytest.mark.unit
def test_query_ranks_exact_id_identity_phrase_and_property_matches(
    query_model: GraphReadModel,
) -> None:
    from echelon.graph_traversal import query_graph

    exact_id = query_graph(query_model, "REQ:905-IMPORT-PROSE:fr-012")
    prefixed_exact_id = query_graph(
        query_model, "ARTIFACT:905-IMPORT-PROSE:unicode"
    )
    identity = query_graph(query_model, "fr-012")
    phrase = query_graph(query_model, "Import, validation!")
    properties = query_graph(query_model, "batch parser")

    assert exact_id.nodes[0]["id"] == "req:905-import-prose:FR-012"
    assert prefixed_exact_id.nodes[0]["id"] == "artifact:905-import-prose:unicode"
    assert identity.nodes[0]["id"] == "req:905-import-prose:FR-012"
    assert phrase.nodes[0]["id"] == "artifact:905-import-prose:catalog"
    assert [node["id"] for node in properties.nodes[:2]] == [
        "task:905-import-prose:T-001",
        "artifact:905-import-prose:catalog",
    ]


@pytest.mark.unit
def test_query_infers_plural_type_and_keeps_seed_only_in_evidence_path(
    query_model: GraphReadModel,
) -> None:
    from echelon.graph_traversal import query_graph

    result = query_graph(
        query_model,
        "which requirements depend on import validation?",
        depth=1,
    )

    assert [node["id"] for node in result.nodes] == [
        "req:905-import-prose:FR-012",
    ]
    assert result.paths[0].node_ids == (
        "artifact:905-import-prose:catalog",
        "req:905-import-prose:FR-012",
    )
    assert result.paths[0].steps[0].type == "DERIVED_FROM"
    assert result.paths[0].steps[0].direction == "in"
    assert all(node["type"] == "Requirement" for node in result.nodes)
    assert "artifact:905-import-prose:catalog" not in {
        str(node["id"]) for node in result.nodes
    }


@pytest.mark.unit
def test_query_explicit_type_precedes_inference_and_absent_type_is_empty(
    query_model: GraphReadModel,
) -> None:
    from echelon.graph_traversal import query_graph

    explicit = query_graph(
        query_model,
        "requirements import validation",
        node_type="artifact",
    )
    absent = query_graph(query_model, "import validation", node_type="Decision")

    assert [node["id"] for node in explicit.nodes] == [
        "artifact:905-import-prose:catalog"
    ]
    assert absent.nodes == ()
    assert absent.edges == ()
    assert absent.paths == ()


@pytest.mark.unit
def test_query_is_unicode_casefolded_deterministic_and_visibly_limited(
    query_model: GraphReadModel,
) -> None:
    from echelon.graph_traversal import query_graph

    unicode_match = query_graph(query_model, "STRASSE")
    tied = query_graph(
        query_model,
        "ARCHIVE CHECKSUM",
        node_type="requirements",
        limit=1,
    )

    assert unicode_match.nodes[0]["id"] == "artifact:905-import-prose:unicode"
    assert [node["id"] for node in tied.nodes] == [
        "req:905-import-prose:FR-013"
    ]
    assert tied.truncated is True


@pytest.mark.unit
def test_query_nfkc_normalizes_full_width_latin_to_ascii(
    query_model: GraphReadModel,
) -> None:
    from echelon.graph_traversal import query_graph

    result = query_graph(query_model, "ｃｏｍｐａｔｉｂｉｌｉｔｙｔｏｋｅｎ")

    assert [node["id"] for node in result.nodes] == [
        "artifact:905-import-prose:unicode"
    ]


@pytest.mark.unit
def test_query_empty_stopwords_no_matches_and_depth_bounds_are_successful(
    query_model: GraphReadModel,
) -> None:
    from echelon.graph_traversal import query_graph

    for result in (
        query_graph(query_model, "which and the?"),
        query_graph(query_model, "missing vocabulary"),
        query_graph(query_model, "import validation", depth=1, node_type="Task"),
    ):
        assert result.nodes == ()
        assert result.edges == ()
        assert result.paths == ()
        assert result.truncated is False

    with pytest.raises(ValueError, match="depth"):
        query_graph(query_model, "import", depth=0)
    with pytest.raises(ValueError, match="limit"):
        query_graph(query_model, "import", limit=0)


@pytest.fixture
def impact_model() -> GraphReadModel:
    nodes = (
        _node("workspace:current", "Workspace"),
        _node("spec:old", "Spec"),
        _node("spec:new", "Spec"),
        _node("req:one", "Requirement"),
        _node("req:two", "Requirement"),
        _node("task:one", "Task"),
        _node("artifact:source", "Artifact"),
        _node("artifact:verified", "Artifact"),
        _node("deferral:req", "Deferral"),
        _node("deferral:task", "Deferral"),
        _node("drawer:one", "MemPalaceDrawer"),
        _node("amendment:one", "Amendment"),
        _node("source:app", "SourceRoot"),
        _node("excluded", "Other"),
        _node("incoming-excluded", "Other"),
    )
    edges = (
        _edge("workspace:current", "CONTAINS_SPEC", "spec:old"),
        _edge("spec:new", "SUPERSEDES", "spec:old"),
        _edge("spec:old", "HAS_REQUIREMENT", "req:one"),
        _edge("spec:old", "AMENDED_BY", "amendment:one"),
        _edge("spec:old", "TARGETS", "source:app"),
        _edge("req:one", "DERIVED_FROM", "artifact:source"),
        _edge("task:one", "IMPLEMENTS", "req:one"),
        _edge("req:one", "VERIFIED_BY", "artifact:verified"),
        _edge("req:one", "DEFERRED_BY", "deferral:req"),
        _edge("task:one", "DEFERRED_BY", "deferral:task"),
        _edge("artifact:source", "STORED_AS", "drawer:one"),
        _edge("req:one", "STORED_AS", "drawer:one"),
        _edge("req:one", "UNAPPROVED", "excluded"),
        _edge("incoming-excluded", "UNAPPROVED", "req:one"),
        _edge("req:two", "IMPLEMENTS", "req:one"),
        _edge("req:one", "IMPLEMENTS", "req:two"),
    )
    return _typed_model(nodes, edges)


@pytest.mark.unit
def test_impact_default_follows_only_the_approved_typed_directions(
    impact_model: GraphReadModel,
) -> None:
    from echelon.graph_traversal import impact

    cases = {
        "workspace:current": {"spec:old"},
        "spec:old": {
            "amendment:one",
            "req:one",
            "source:app",
            "spec:new",
        },
        "artifact:source": {"drawer:one", "req:one"},
        "req:one": {
            "artifact:verified",
            "deferral:req",
            "drawer:one",
            "task:one",
        },
        "task:one": {"deferral:task"},
    }

    for start, expected in cases.items():
        result = impact(impact_model, start, max_depth=1)
        assert {str(node["id"]) for node in result.nodes} == expected
        assert start not in {str(node["id"]) for node in result.nodes}


@pytest.mark.unit
def test_impact_reverse_supersedes_preserves_stored_arrow(
    impact_model: GraphReadModel,
) -> None:
    from echelon.graph_traversal import impact

    result = impact(impact_model, "spec:old", max_depth=1)
    path = next(path for path in result.paths if path.node_ids[-1] == "spec:new")

    assert path.node_ids == ("spec:old", "spec:new")
    assert (
        path.steps[0].source,
        path.steps[0].type,
        path.steps[0].target,
        path.steps[0].direction,
    ) == ("spec:new", "SUPERSEDES", "spec:old", "in")


@pytest.mark.unit
def test_impact_is_cycle_safe_uses_shortest_paths_and_marks_depth_truncation(
    impact_model: GraphReadModel,
) -> None:
    from echelon.graph_traversal import impact

    result = impact(impact_model, "artifact:source", max_depth=2)
    cycle = impact(
        impact_model, "req:one", max_depth=10, all_relations=True
    )

    paths = {path.node_ids[-1]: path for path in result.paths}
    assert paths["drawer:one"].node_ids == ("artifact:source", "drawer:one")
    assert paths["task:one"].node_ids == (
        "artifact:source",
        "req:one",
        "task:one",
    )
    assert len(paths) == len(result.nodes)
    assert result.truncated is True
    assert len(cycle.paths) == len(cycle.nodes)
    assert cycle.truncated is False


@pytest.mark.unit
def test_impact_all_relations_is_explicit_both_direction_escape_hatch(
    impact_model: GraphReadModel,
) -> None:
    from echelon.graph_traversal import impact

    default = impact(impact_model, "req:one", max_depth=1)
    unrestricted = impact(
        impact_model, "req:one", max_depth=1, all_relations=True
    )

    assert "excluded" not in {str(node["id"]) for node in default.nodes}
    assert "excluded" in {str(node["id"]) for node in unrestricted.nodes}
    assert "incoming-excluded" not in {
        str(node["id"]) for node in default.nodes
    }
    assert "incoming-excluded" in {
        str(node["id"]) for node in unrestricted.nodes
    }
    excluded_path = next(
        path for path in unrestricted.paths if path.node_ids[-1] == "excluded"
    )
    assert excluded_path.steps[0].direction == "out"
    incoming_path = next(
        path
        for path in unrestricted.paths
        if path.node_ids[-1] == "incoming-excluded"
    )
    assert (
        incoming_path.steps[0].source,
        incoming_path.steps[0].target,
        incoming_path.steps[0].direction,
    ) == ("incoming-excluded", "req:one", "in")


@pytest.mark.unit
def test_impact_rejects_nonpositive_depth() -> None:
    from echelon.graph_traversal import impact

    with pytest.raises(ValueError, match="depth"):
        impact(_model(("a",), ()), "a", max_depth=0)
