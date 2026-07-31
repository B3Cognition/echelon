"""Deterministic, read-only traversal of persisted artifact graphs."""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Mapping, cast

from echelon.graph_read import GraphReadModel, resolve_node_id


@dataclass(frozen=True)
class PathStep:
    source: str
    type: str
    target: str
    direction: str
    properties: Mapping[str, object]


@dataclass(frozen=True)
class GraphPath:
    node_ids: tuple[str, ...]
    steps: tuple[PathStep, ...]


@dataclass(frozen=True)
class GraphResult:
    nodes: tuple[Mapping[str, object], ...]
    edges: tuple[Mapping[str, object], ...]
    paths: tuple[GraphPath, ...]
    truncated: bool = False


@dataclass(frozen=True)
class _Adjacent:
    edge: Mapping[str, object]
    step: PathStep
    node_id: str


def explain_node(model: GraphReadModel, node_id: str, limit: int = 50) -> GraphResult:
    """Return one node together with its directly incident relationships."""
    selected_id = resolve_node_id(model, node_id)
    _validate_limit(limit)
    adjacent = _unique_relationships(_adjacent(model, selected_id, "both"))
    returned = adjacent[:limit]
    return _result(
        model,
        (selected_id, *(item.node_id for item in returned)),
        (item.edge for item in returned),
        (),
        truncated=len(adjacent) > limit,
    )


def neighbors(
    model: GraphReadModel,
    node_id: str,
    direction: str = "both",
    relation: str | None = None,
    limit: int = 50,
) -> GraphResult:
    """Return filtered, directional neighbors while retaining stored edge arrows."""
    selected_id = resolve_node_id(model, node_id)
    _validate_direction(direction)
    _validate_limit(limit)
    adjacent = _unique_relationships(_adjacent(model, selected_id, direction))
    if relation is not None:
        normalized_relation = relation.casefold()
        adjacent = tuple(
            item for item in adjacent if item.step.type.casefold() == normalized_relation
        )
    returned = adjacent[:limit]
    return _result(
        model,
        (selected_id, *(item.node_id for item in returned)),
        (item.edge for item in returned),
        (),
        truncated=len(adjacent) > limit,
    )


def shortest_path(
    model: GraphReadModel,
    source_id: str,
    target_id: str,
    max_hops: int = 8,
) -> GraphResult:
    """Return one deterministic shortest path up to ``max_hops``."""
    source = resolve_node_id(model, source_id)
    target = resolve_node_id(model, target_id)
    if source == target:
        path = GraphPath((source,), ())
        return _result(model, path.node_ids, (), (path,))

    queue: deque[tuple[str, GraphPath]] = deque(
        [(source, GraphPath((source,), ()))]
    )
    visited_depth = {source: 0}
    while queue:
        current_id, current_path = queue.popleft()
        depth = len(current_path.steps)
        if current_id == target:
            edge_index = _edge_index(model)
            path_edges = tuple(
                edge_index[_step_identity(step)] for step in current_path.steps
            )
            return _result(
                model,
                current_path.node_ids,
                path_edges,
                (current_path,),
            )
        if depth >= max_hops:
            continue

        for adjacent in _adjacent(model, current_id, "both", path_order=True):
            next_depth = depth + 1
            previous_depth = visited_depth.get(adjacent.node_id)
            if previous_depth is not None and previous_depth <= next_depth:
                continue
            visited_depth[adjacent.node_id] = next_depth
            queue.append(
                (
                    adjacent.node_id,
                    GraphPath(
                        (*current_path.node_ids, adjacent.node_id),
                        (*current_path.steps, adjacent.step),
                    ),
                )
            )

    return _result(model, (), (), ())


def _adjacent(
    model: GraphReadModel,
    node_id: str,
    direction: str,
    *,
    path_order: bool = False,
) -> tuple[_Adjacent, ...]:
    adjacent: list[_Adjacent] = []
    if direction in {"both", "out"}:
        adjacent.extend(
            _Adjacent(
                edge=edge,
                step=_path_step(edge, "out"),
                node_id=str(edge["target"]),
            )
            for edge in model.outgoing[node_id]
        )
    if direction in {"both", "in"}:
        adjacent.extend(
            _Adjacent(
                edge=edge,
                step=_path_step(edge, "in"),
                node_id=str(edge["source"]),
            )
            for edge in model.incoming[node_id]
        )
    key = _path_adjacent_sort_key if path_order else _neighbor_adjacent_sort_key
    return tuple(sorted(adjacent, key=key))


def _path_step(edge: Mapping[str, object], direction: str) -> PathStep:
    return PathStep(
        source=str(edge["source"]),
        type=str(edge["type"]),
        target=str(edge["target"]),
        direction=direction,
        properties=cast(Mapping[str, object], edge["properties"]),
    )


def _unique_relationships(adjacent: Iterable[_Adjacent]) -> tuple[_Adjacent, ...]:
    seen: set[tuple[str, str, str]] = set()
    unique: list[_Adjacent] = []
    for item in adjacent:
        identity = _edge_identity(item.edge)
        if identity in seen:
            continue
        seen.add(identity)
        unique.append(item)
    return tuple(unique)


def _neighbor_adjacent_sort_key(item: _Adjacent) -> tuple[object, ...]:
    return (
        0 if item.step.direction == "in" else 1,
        item.step.type,
        item.node_id,
        *_edge_identity(item.edge),
        item.step.direction,
    )


def _path_adjacent_sort_key(item: _Adjacent) -> tuple[str, str, str, str, str]:
    return (
        item.step.type,
        item.node_id,
        item.step.source,
        item.step.target,
        item.step.direction,
    )


def _result(
    model: GraphReadModel,
    node_ids: tuple[str, ...],
    edges: Iterable[Mapping[str, object]],
    paths: tuple[GraphPath, ...],
    *,
    truncated: bool = False,
) -> GraphResult:
    return GraphResult(
        nodes=tuple(model.nodes_by_id[node_id] for node_id in sorted(set(node_ids))),
        edges=_canonical_edges(edges),
        paths=paths,
        truncated=truncated,
    )


def _canonical_edges(
    edges: Iterable[Mapping[str, object]],
) -> tuple[Mapping[str, object], ...]:
    by_identity = {_edge_identity(edge): edge for edge in edges}
    return tuple(by_identity[identity] for identity in sorted(by_identity))


def _edge_index(
    model: GraphReadModel,
) -> Mapping[tuple[str, str, str], Mapping[str, object]]:
    return {
        _edge_identity(edge): edge
        for edges in model.outgoing.values()
        for edge in edges
    }


def _edge_identity(edge: Mapping[str, object]) -> tuple[str, str, str]:
    return (str(edge["source"]), str(edge["type"]), str(edge["target"]))


def _step_identity(step: PathStep) -> tuple[str, str, str]:
    return (step.source, step.type, step.target)


def _validate_limit(limit: int) -> None:
    if limit <= 0:
        raise ValueError("graph traversal limit must be positive")


def _validate_direction(direction: str) -> None:
    if direction not in {"both", "in", "out"}:
        raise ValueError(f"unsupported graph traversal direction: {direction!r}")
