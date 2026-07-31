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
def test_shortest_path_returns_deterministic_equal_shortest_branches_from_shuffled_indexes() -> None:
    from echelon.graph_traversal import shortest_path

    model = _model(
        ("source", "left", "right", "target", "isolated"),
        (
            _edge("right", "ROUTE", "target"),
            _edge("left", "CYCLE", "right"),
            _edge("source", "ROUTE", "right"),
            _edge("right", "CYCLE", "left"),
            _edge("left", "ROUTE", "target"),
            _edge("source", "ROUTE", "left"),
        ),
    )

    result = shortest_path(model, "source", "target")

    assert [path.node_ids for path in result.paths] == [
        ("source", "left", "target"),
        ("source", "right", "target"),
    ]
    assert [
        (step.source, step.type, step.target, step.direction)
        for step in result.paths[0].steps
    ] == [
        ("source", "ROUTE", "left", "out"),
        ("left", "ROUTE", "target", "out"),
    ]
    assert [node["id"] for node in result.nodes] == ["left", "right", "source", "target"]
    assert _identities(result.edges) == [
        ("left", "ROUTE", "target"),
        ("right", "ROUTE", "target"),
        ("source", "ROUTE", "left"),
        ("source", "ROUTE", "right"),
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

    assert [path.node_ids for path in result.paths] == [
        ("target", "left", "source"),
        ("target", "right", "source"),
    ]
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

    assert [path.node_ids for path in result.paths] == [
        ("source", "outgoing", "target"),
        ("source", "incoming", "target"),
    ]
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
