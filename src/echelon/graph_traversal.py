"""Deterministic, read-only traversal of persisted artifact graphs."""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass
import re
from types import MappingProxyType
from typing import Mapping, cast
import unicodedata

from echelon.graph_read import GraphReadModel, resolve_node_id


QUERY_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "be",
        "by",
        "do",
        "does",
        "for",
        "from",
        "how",
        "in",
        "is",
        "of",
        "on",
        "or",
        "please",
        "show",
        "that",
        "the",
        "these",
        "this",
        "those",
        "to",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "with",
    }
)

NODE_TYPE_ALIASES: Mapping[str, str] = MappingProxyType(
    {
        "amendment": "Amendment",
        "amendments": "Amendment",
        "artifact": "Artifact",
        "artifacts": "Artifact",
        "deferral": "Deferral",
        "deferrals": "Deferral",
        "drawer": "MemPalaceDrawer",
        "drawers": "MemPalaceDrawer",
        "requirement": "Requirement",
        "requirements": "Requirement",
        "source": "SourceRoot",
        "sources": "SourceRoot",
        "spec": "Spec",
        "specification": "Spec",
        "specifications": "Spec",
        "specs": "Spec",
        "task": "Task",
        "tasks": "Task",
        "workspace": "Workspace",
        "workspaces": "Workspace",
    }
)

IMPACT_RELATIONS: Mapping[
    tuple[str, str], frozenset[tuple[str, str]]
] = MappingProxyType(
    {
        ("Artifact", "DERIVED_FROM"): frozenset({("in", "Requirement")}),
        ("Artifact", "STORED_AS"): frozenset({("out", "MemPalaceDrawer")}),
        ("Requirement", "IMPLEMENTS"): frozenset({("in", "Task")}),
        ("Requirement", "VERIFIED_BY"): frozenset({("out", "Artifact")}),
        ("Requirement", "DEFERRED_BY"): frozenset({("out", "Deferral")}),
        ("Requirement", "STORED_AS"): frozenset(
            {("out", "MemPalaceDrawer")}
        ),
        ("Task", "DEFERRED_BY"): frozenset({("out", "Deferral")}),
        ("Spec", "HAS_REQUIREMENT"): frozenset({("out", "Requirement")}),
        ("Spec", "AMENDED_BY"): frozenset({("out", "Amendment")}),
        ("Spec", "TARGETS"): frozenset({("out", "SourceRoot")}),
        ("Spec", "SUPERSEDES"): frozenset({("in", "Spec")}),
        ("Workspace", "CONTAINS_SPEC"): frozenset({("out", "Spec")}),
    }
)

_TOKEN_PATTERN = re.compile(r"[\w]+(?:-[\w]+)*", re.UNICODE)


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


@dataclass(frozen=True)
class _QueryMatch:
    node_id: str
    rank: tuple[int, int, int, int, int, int]
    path: GraphPath


def query_graph(
    model: GraphReadModel,
    question: str,
    node_type: str | None = None,
    depth: int = 2,
    limit: int = 20,
) -> GraphResult:
    """Return deterministic lexical matches with bounded expansion evidence."""
    _validate_depth(depth)
    _validate_limit(limit)
    raw_tokens = _tokens(question)
    inferred_type = next(
        (NODE_TYPE_ALIASES[token] for token in raw_tokens if token in NODE_TYPE_ALIASES),
        None,
    )
    output_type = (
        _resolve_node_type(model, node_type)
        if node_type is not None
        else inferred_type
    )
    if node_type is not None and output_type is None:
        return GraphResult((), (), ())

    query_tokens = tuple(
        token
        for token in raw_tokens
        if token not in QUERY_STOPWORDS and token not in NODE_TYPE_ALIASES
    )
    if not query_tokens:
        return GraphResult((), (), ())

    features_by_id = {
        node_id: _lexical_features(node_id, node, raw_tokens, query_tokens)
        for node_id, node in model.nodes_by_id.items()
    }
    lexical_seed_ids = {
        node_id
        for node_id, features in features_by_id.items()
        if features != (0, 0, 0, 0, 0)
    }
    if not lexical_seed_ids:
        return GraphResult((), (), ())

    paths = _bounded_paths(model, tuple(sorted(lexical_seed_ids)), depth)
    matches: list[_QueryMatch] = []
    for candidate_id, path in paths.items():
        node = model.nodes_by_id[candidate_id]
        if output_type is None:
            if candidate_id not in lexical_seed_ids:
                continue
        elif str(node["type"]).casefold() != output_type.casefold():
            continue
        base_rank = features_by_id[candidate_id]
        matches.append(
            _QueryMatch(
                candidate_id,
                (*base_rank, -len(path.steps)),
                path,
            )
        )

    matches.sort(key=lambda item: (*(-value for value in item.rank), item.node_id))
    returned = matches[:limit]
    returned_paths = tuple(item.path for item in returned)
    edge_index = _edge_index(model)
    edges = tuple(
        edge_index[_step_identity(step)]
        for item in returned
        for step in item.path.steps
    )
    return GraphResult(
        nodes=tuple(model.nodes_by_id[item.node_id] for item in returned),
        edges=_canonical_edges(edges),
        paths=returned_paths,
        truncated=len(matches) > limit,
    )


def impact(
    model: GraphReadModel,
    node_id: str,
    max_depth: int = 4,
    all_relations: bool = False,
) -> GraphResult:
    """Return cycle-safe downstream impact using approved typed directions."""
    start = resolve_node_id(model, node_id)
    _validate_depth(max_depth)
    start_path = GraphPath((start,), ())
    queue: deque[tuple[str, GraphPath]] = deque([(start, start_path)])
    visited = {start}
    paths: list[GraphPath] = []
    truncated = False

    while queue:
        current_id, current_path = queue.popleft()
        current_depth = len(current_path.steps)
        adjacent = _impact_adjacent(model, current_id, all_relations)
        if current_depth >= max_depth:
            if any(item.node_id not in visited for item in adjacent):
                truncated = True
            continue
        for item in adjacent:
            if item.node_id in visited:
                continue
            visited.add(item.node_id)
            path = GraphPath(
                (*current_path.node_ids, item.node_id),
                (*current_path.steps, item.step),
            )
            paths.append(path)
            queue.append((item.node_id, path))

    edge_index = _edge_index(model)
    edges = tuple(
        edge_index[_step_identity(step)] for path in paths for step in path.steps
    )
    return _result(
        model,
        tuple(visited - {start}),
        edges,
        tuple(paths),
        truncated=truncated,
    )


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


def _bounded_paths(
    model: GraphReadModel, seed_ids: tuple[str, ...], max_depth: int
) -> dict[str, GraphPath]:
    paths = {seed_id: GraphPath((seed_id,), ()) for seed_id in seed_ids}
    queue: deque[str] = deque(seed_ids)
    while queue:
        current_id = queue.popleft()
        current_path = paths[current_id]
        if len(current_path.steps) >= max_depth:
            continue
        for item in _adjacent(model, current_id, "both", path_order=True):
            if item.node_id in paths:
                continue
            paths[item.node_id] = GraphPath(
                (*current_path.node_ids, item.node_id),
                (*current_path.steps, item.step),
            )
            queue.append(item.node_id)
    return paths


def _lexical_features(
    node_id: str,
    node: Mapping[str, object],
    canonical_query_tokens: tuple[str, ...],
    query_tokens: tuple[str, ...],
) -> tuple[int, int, int, int, int]:
    properties = cast(Mapping[str, object], node["properties"])
    identity_values = tuple(
        value
        for key, property_value in properties.items()
        if key.endswith("_id")
        for value in _scalar_values(property_value)
    )
    source_values = tuple(_scalar_values(properties.get("source_text")))
    other_values = tuple(
        value
        for key, property_value in properties.items()
        if key != "source_text" and not key.endswith("_id")
        for value in _scalar_values(property_value)
    )
    identity_source_values = (*identity_values, *source_values)
    searchable_values = (*identity_source_values, *other_values)
    identity_source_tokens = {
        token for value in identity_source_values for token in _tokens(value)
    }
    other_tokens = {token for value in other_values for token in _tokens(value)}
    return (
        int(_tokens(node_id) == canonical_query_tokens),
        int(any(_tokens(value) == query_tokens for value in identity_values)),
        int(
            any(
                _contains_phrase(_tokens(value), query_tokens)
                for value in searchable_values
            )
        ),
        sum(token in identity_source_tokens for token in query_tokens),
        sum(token in other_tokens for token in query_tokens),
    )


def _scalar_values(value: object) -> tuple[str, ...]:
    if isinstance(value, (str, int, float, bool)):
        return (str(value),)
    if isinstance(value, (list, tuple)):
        return tuple(
            str(item) for item in value if isinstance(item, (str, int, float, bool))
        )
    return ()


def _contains_phrase(tokens: tuple[str, ...], phrase: tuple[str, ...]) -> bool:
    width = len(phrase)
    return any(
        tokens[index : index + width] == phrase
        for index in range(len(tokens) - width + 1)
    )


def _tokens(value: object) -> tuple[str, ...]:
    return tuple(_TOKEN_PATTERN.findall(_normalize(str(value))))


def _normalize(value: str) -> str:
    return unicodedata.normalize("NFKC", value).casefold()


def _resolve_node_type(model: GraphReadModel, requested: str) -> str | None:
    normalized = _normalize(requested.strip())
    aliased = NODE_TYPE_ALIASES.get(normalized)
    if aliased is not None:
        return aliased
    return next(
        (
            str(node["type"])
            for node in model.nodes_by_id.values()
            if _normalize(str(node["type"])) == normalized
        ),
        None,
    )


def _impact_adjacent(
    model: GraphReadModel, node_id: str, all_relations: bool
) -> tuple[_Adjacent, ...]:
    adjacent = _adjacent(model, node_id, "both", path_order=True)
    if all_relations:
        return adjacent
    current_type = str(model.nodes_by_id[node_id]["type"])
    return tuple(
        item
        for item in adjacent
        if (
            item.step.direction,
            str(model.nodes_by_id[item.node_id]["type"]),
        )
        in IMPACT_RELATIONS.get((current_type, item.step.type), frozenset())
    )


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


def _validate_depth(depth: int) -> None:
    if depth <= 0:
        raise ValueError("graph traversal depth must be positive")


def _validate_direction(direction: str) -> None:
    if direction not in {"both", "in", "out"}:
        raise ValueError(f"unsupported graph traversal direction: {direction!r}")
