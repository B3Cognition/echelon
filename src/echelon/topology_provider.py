"""Strict schema-2 provider loading and bounded, provider-neutral reads."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from types import MappingProxyType
from typing import Iterable, Mapping

from echelon.topology_model import (
    NODE_TYPES,
    RELATIONSHIP_TYPES,
    TopologyExplainResult,
    TopologyDiagnostic,
    TopologyFile,
    TopologyReceipt,
    TopologyRelationship,
    TopologySearchResult,
    TopologySource,
    TopologySymbol,
    TopologyTraversalResult,
    TopologyTraversalStep,
    TopologyValidationError,
    normalize_source_path,
    validate_generation,
    validate_provider,
    validate_source_id,
    validate_symbol_key,
)


DEFAULT_LIMIT = 50
MAX_LIMIT = 500
DEFAULT_IMPACT_DEPTH = 3
MAX_IMPACT_DEPTH = 10
NORMALIZED_STATUSES = frozenset({"ready", "degraded", "empty", "unsupported", "unavailable"})
IMPACT_DIRECTIONS: Mapping[str, str] = MappingProxyType(
    {
        "CONTAINS": "out",
        "DECLARES": "out",
        "IMPORTS": "in",
        "REQUIRES": "in",
        "CALLS": "in",
        "EXTENDS": "in",
        "IMPLEMENTS": "in",
        "USES_ROLE": "in",
        "TESTS": "in",
        "REFERENCES": "in",
        "INSTANTIATES": "in",
        "DECORATES": "in",
        "OTHER": "both",
    }
)

_CODEGRAPH_NATIVE_STATUSES = frozenset({"complete", "partial"})
_PERLGRAPH_NATIVE_STATUSES = frozenset({"ready", "degraded", "empty", "unsupported"})
_RELATIONSHIP_MAP: Mapping[str, Mapping[str, str]] = MappingProxyType(
    {
        "codegraph": MappingProxyType(
            {
                "contains": "CONTAINS",
                "declares": "DECLARES",
                "import": "IMPORTS",
                "imports": "IMPORTS",
                "require": "REQUIRES",
                "requires": "REQUIRES",
                "calls": "CALLS",
                "extends": "EXTENDS",
                "implements": "IMPLEMENTS",
                "uses_role": "USES_ROLE",
                "tests": "TESTS",
                "references": "REFERENCES",
                "instantiates": "INSTANTIATES",
                "decorates": "DECORATES",
            }
        ),
        "perlgraph": MappingProxyType(
            {
                "declares": "DECLARES",
                "imports": "IMPORTS",
                "requires": "REQUIRES",
                "inherits": "EXTENDS",
                "uses_role": "USES_ROLE",
                "calls": "CALLS",
                "tests": "TESTS",
                "references": "REFERENCES",
            }
        ),
    }
)
RelationshipIdentity = tuple[
    str,
    str,
    str,
    str,
    str,
    str,
    int | None,
    str | None,
    tuple[str, ...],
    str | None,
]
RelationshipSortKey = tuple[
    str,
    str,
    str,
    str,
    str,
    str,
    int,
    bool,
    str,
    tuple[str, ...],
    bool,
    str,
]


class TopologyProviderError(RuntimeError):
    """Raised when a native provider artifact violates its schema-2 contract."""


class TopologyNodeResolutionError(TopologyProviderError):
    """Raised when a topology node selector is missing or ambiguous."""

    def __init__(
        self,
        message: str,
        *,
        candidates: Iterable[str] = (),
        candidate_count: int | None = None,
        candidates_truncated: bool = False,
    ) -> None:
        ordered = tuple(sorted(candidates))
        self.candidates = ordered[:10]
        self.candidate_count = max(len(ordered), candidate_count or 0)
        self.candidates_truncated = (
            candidates_truncated
            or self.candidate_count > len(self.candidates)
            or (candidate_count is None and len(ordered) >= 10)
        )
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class LoadedTopologyProvider:
    """Validated normalized output from one native provider artifact."""

    source_id: str
    provider: str
    status: str
    native_status: str
    complete: bool
    tool_version: str
    artifact_hash: str
    files: tuple[TopologyFile, ...]
    symbols: tuple[TopologySymbol, ...]
    relationships: tuple[TopologyRelationship, ...]
    diagnostics: tuple[TopologyDiagnostic, ...]
    diagnostic_count: int

    def __post_init__(self) -> None:
        source_id = validate_source_id(self.source_id)
        provider = validate_provider(self.provider)
        if self.status not in NORMALIZED_STATUSES:
            raise TopologyValidationError("unknown normalized provider status")
        validate_symbol_key(self.artifact_hash)
        if any(file.source_id != source_id for file in self.files):
            raise TopologyValidationError("loaded provider file has the wrong source")
        if any(
            symbol.source_id != source_id or symbol.provider != provider
            for symbol in self.symbols
        ):
            raise TopologyValidationError("loaded provider symbol has the wrong source or provider")
        symbol_ids = {symbol.id for symbol in self.symbols}
        if any(
            relationship.provider != provider
            or relationship.source_id not in symbol_ids
            or relationship.target_id not in symbol_ids
            for relationship in self.relationships
        ):
            raise TopologyValidationError("loaded provider relationship has an invalid endpoint")
        if self.diagnostic_count != len(self.diagnostics):
            raise TopologyValidationError("loaded provider diagnostic count does not reconcile")


def load_provider_artifact(
    path: Path, *, provider: str, source_id: str
) -> LoadedTopologyProvider:
    """Read and strictly normalize one schema-2 provider artifact without mutation."""
    artifact_path = Path(path)
    try:
        raw = artifact_path.read_bytes()
        document = json.loads(raw)
    except FileNotFoundError as exc:
        raise TopologyProviderError(f"provider artifact is missing: {artifact_path}") from exc
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TopologyProviderError(f"provider artifact is unreadable: {artifact_path}") from exc
    loaded = load_provider_document(document, provider=provider, source_id=source_id)
    return LoadedTopologyProvider(
        source_id=loaded.source_id,
        provider=loaded.provider,
        status=loaded.status,
        native_status=loaded.native_status,
        complete=loaded.complete,
        tool_version=loaded.tool_version,
        artifact_hash="sha256:" + hashlib.sha256(raw).hexdigest(),
        files=loaded.files,
        symbols=loaded.symbols,
        relationships=loaded.relationships,
        diagnostics=loaded.diagnostics,
        diagnostic_count=loaded.diagnostic_count,
    )


def load_provider_document(
    document: object, *, provider: str, source_id: str
) -> LoadedTopologyProvider:
    """Validate and normalize an in-memory schema-2 provider document.

    This is intentionally registry-free. The canonical registry supplies
    publication generation, source fingerprints, receipt hashes, and relative
    artifact paths when it constructs ``PublishedTopology``.
    """
    try:
        provider = validate_provider(provider)
        source_id = validate_source_id(source_id)
        if provider not in _RELATIONSHIP_MAP:
            raise TopologyProviderError(f"unsupported topology provider: {provider!r}")
        if not isinstance(document, dict):
            raise TopologyProviderError("provider artifact must be an object")
        _validate_common_document(document, provider)
        native_status = _require_string(document, "provider_status")
        _validate_native_status(provider, native_status)
        complete = _require_bool(document, "complete")
        symbols_raw = _require_list(document, "symbols")
        relationships_raw = _require_list(document, "relationships")
        counts = _require_object(document, "counts")
        diagnostic_count = _validate_counts(
            provider,
            document,
            counts,
            symbols_raw,
            relationships_raw,
            complete,
            native_status,
        )
        symbols = _load_symbols(symbols_raw, provider=provider, source_id=source_id)
        symbol_by_key = {symbol.symbol_key: symbol for symbol in symbols}
        if len(symbol_by_key) != len(symbols):
            raise TopologyProviderError("duplicate provider symbol key")
        relationships = _load_relationships(
            relationships_raw,
            provider=provider,
            symbols_by_key=symbol_by_key,
        )
        _validate_derived_endpoint_collections(document, provider, symbol_by_key)
        diagnostics = _load_diagnostics(
            document,
            provider=provider,
            symbols_by_key=symbol_by_key,
        )
        if len(diagnostics) != diagnostic_count:
            raise TopologyProviderError("provider unresolved diagnostic count does not match observations")
        status = _normalize_status(
            provider,
            document=document,
            native_status=native_status,
            complete=complete,
            symbol_count=len(symbols),
            relationship_count=len(relationships),
        )
        files = tuple(
            TopologyFile(source_id=source_id, path=path)
            for path in sorted({symbol.path for symbol in symbols})
        )
        return LoadedTopologyProvider(
            source_id=source_id,
            provider=provider,
            status=status,
            native_status=native_status,
            complete=complete,
            tool_version=_require_string(document, "tool_version"),
            artifact_hash="sha256:" + "0" * 64,
            files=files,
            symbols=symbols,
            relationships=relationships,
            diagnostics=diagnostics,
            diagnostic_count=diagnostic_count,
        )
    except TopologyValidationError as exc:
        raise TopologyProviderError(str(exc)) from exc


class PublishedTopology:
    """Immutable in-memory indexes with bounded deterministic topology reads."""

    def __init__(
        self,
        *,
        sources: Iterable[TopologySource],
        files: Iterable[TopologyFile],
        symbols: Iterable[TopologySymbol],
        relationships: Iterable[TopologyRelationship],
        generation: int,
        source_fingerprints: Mapping[str, str] | None = None,
        provider_receipt_hashes: Mapping[str, Mapping[str, str]] | None = None,
        provider_artifact_paths: Mapping[str, Mapping[str, str]] | None = None,
        provider_statuses: Mapping[str, Mapping[str, str]] | None = None,
        loaded_providers: Iterable[LoadedTopologyProvider] = (),
    ) -> None:
        self.generation = validate_generation(generation)
        self._loaded_providers = tuple(
            sorted(loaded_providers, key=lambda item: (item.source_id, item.provider))
        )
        _reject_duplicate_loaded_providers(self._loaded_providers)
        self._source_fingerprints = _immutable_nested_scalar_map(source_fingerprints or {})
        explicit_provenance = any(
            value is not None
            for value in (
                provider_receipt_hashes,
                provider_artifact_paths,
                provider_statuses,
            )
        )
        if explicit_provenance and any(
            value is None
            for value in (
                provider_receipt_hashes,
                provider_artifact_paths,
                provider_statuses,
            )
        ):
            raise TopologyProviderError(
                "explicit provider provenance requires hashes, paths, and statuses"
            )
        default_hashes = _receipt_hashes_for_loaded(self._loaded_providers)
        self._provider_receipt_hashes = _immutable_nested_hashes(
            provider_receipt_hashes if explicit_provenance else default_hashes
        )
        self._provider_artifact_paths = _immutable_nested_paths(
            provider_artifact_paths if explicit_provenance else {}
        )
        statuses = provider_statuses if explicit_provenance else _statuses_for_loaded(self._loaded_providers)
        self._provider_statuses = _immutable_nested_statuses(statuses)
        if explicit_provenance:
            _validate_explicit_provider_provenance(
                self._loaded_providers,
                self._provider_receipt_hashes,
                self._provider_artifact_paths,
                self._provider_statuses,
            )
        nodes = [*sources, *files, *symbols]
        self.nodes_by_id = _node_index(nodes)
        self._validate_source_nodes()
        self.relationships = _relationship_tuple(relationships, self.nodes_by_id)
        self.outgoing, self.incoming = _relationship_indexes(
            self.relationships, self.nodes_by_id
        )
        self._selectors = _selector_indexes(self.nodes_by_id)

    @classmethod
    def from_loaded_providers(
        cls,
        providers: Iterable[LoadedTopologyProvider],
        *,
        generation: int,
        source_fingerprints: Mapping[str, str] | None = None,
        provider_receipt_hashes: Mapping[str, Mapping[str, str]] | None = None,
        provider_artifact_paths: Mapping[str, Mapping[str, str]] | None = None,
        provider_statuses: Mapping[str, Mapping[str, str]] | None = None,
        sources: Iterable[TopologySource] = (),
    ) -> "PublishedTopology":
        """Compose selected provider outputs; publication provenance is injected here."""
        loaded = tuple(sorted(providers, key=lambda item: (item.source_id, item.provider)))
        source_map = {source.source_id: source for source in sources}
        source_map.update({item.source_id: TopologySource(item.source_id) for item in loaded})
        files = {item.id: item for loaded_item in loaded for item in loaded_item.files}
        symbols = {item.id: item for loaded_item in loaded for item in loaded_item.symbols}
        relationships = [
            relation for loaded_item in loaded for relation in loaded_item.relationships
        ]
        for file in files.values():
            relationships.append(
                TopologyRelationship(
                    source_id=source_map[file.source_id].id,
                    target_id=file.id,
                    type="CONTAINS",
                    provider="topology",
                    provider_kind="contains",
                )
            )
        for symbol in symbols.values():
            relationships.append(
                TopologyRelationship(
                    source_id=TopologyFile(symbol.source_id, symbol.path).id,
                    target_id=symbol.id,
                    type="DECLARES",
                    provider="topology",
                    provider_kind="declares",
                )
            )
        return cls(
            sources=source_map.values(),
            files=files.values(),
            symbols=symbols.values(),
            relationships=relationships,
            generation=generation,
            source_fingerprints=source_fingerprints,
            provider_receipt_hashes=provider_receipt_hashes,
            provider_artifact_paths=provider_artifact_paths,
            provider_statuses=provider_statuses,
            loaded_providers=loaded,
        )

    def receipt(self, source_id: str) -> TopologyReceipt:
        """Return bounded publication provenance for one configured source."""
        source_id = validate_source_id(source_id)
        if source_id not in {source.source_id for source in self.nodes_by_id.values() if isinstance(source, TopologySource)}:
            raise TopologyNodeResolutionError(f"unknown topology source: {source_id}")
        return self._receipt_for_sources({source_id})

    def search(
        self,
        source_id: str | None,
        query: str,
        types: frozenset[str],
        limit: int,
    ) -> TopologySearchResult:
        """Return bounded deterministic lexical matches without copying provider graphs."""
        source_ids = self._validate_source_filter(source_id)
        normalized_types = _validate_types(types, NODE_TYPES, "node type")
        _validate_limit(limit)
        if not isinstance(query, str) or not (needle := query.strip().casefold()):
            raise ValueError("topology search query must not be blank")
        candidates = [
            node
            for node in self.nodes_by_id.values()
            if _node_source_id(node) in source_ids
            and (not normalized_types or node.type in normalized_types)
            and needle in _search_text(node).casefold()
        ]
        candidates.sort(key=lambda node: (node.type, node.id))
        returned = tuple(candidates[:limit])
        return TopologySearchResult(
            receipt=self._receipt_for_sources(source_ids),
            nodes=returned,
            truncated=len(candidates) > limit,
        )

    def explain(self, source_id: str | None, node: str) -> TopologyExplainResult:
        """Return one exact or unambiguous selected node and all direct edges."""
        source_ids = self._validate_source_filter(source_id)
        selected_id = self._resolve_node_id(node, source_ids)
        relationships = tuple(
            sorted(
                {*(self.incoming[selected_id]), *(self.outgoing[selected_id])},
                key=_relationship_sort_key,
            )
        )
        return TopologyExplainResult(
            receipt=self._receipt_for_sources({_node_source_id(self.nodes_by_id[selected_id])}),
            node=self.nodes_by_id[selected_id],
            relationships=relationships[:DEFAULT_LIMIT],
            truncated=len(relationships) > DEFAULT_LIMIT,
        )

    def neighbors(
        self,
        source_id: str | None,
        node: str,
        direction: str,
        relations: frozenset[str],
        limit: int,
    ) -> TopologyTraversalResult:
        """Return direct directional neighbors with a bounded edge limit."""
        _validate_direction(direction)
        relation_filter = _validate_types(relations, RELATIONSHIP_TYPES, "relationship")
        _validate_limit(limit)
        source_ids = self._validate_source_filter(source_id)
        selected_id = self._resolve_node_id(node, source_ids)
        adjacent = self._adjacent(selected_id, direction, relation_filter)
        returned = adjacent[:limit]
        nodes = {selected_id, *(step.node_id for step in returned)}
        involved_sources = {_node_source_id(self.nodes_by_id[node_id]) for node_id in nodes}
        return TopologyTraversalResult(
            receipt=self._receipt_for_sources(involved_sources),
            nodes=tuple(self.nodes_by_id[node_id] for node_id in sorted(nodes)),
            relationships=tuple(step.relationship for step in returned),
            steps=tuple(returned),
            truncated=len(adjacent) > limit,
        )

    def impact(
        self,
        source_id: str | None,
        node: str,
        max_depth: int,
        relations: frozenset[str],
    ) -> TopologyTraversalResult:
        """Return cycle-safe bounded impact traversal, excluding OTHER by default."""
        _validate_depth(max_depth)
        relation_filter = _validate_types(relations, RELATIONSHIP_TYPES, "relationship")
        source_ids = self._validate_source_filter(source_id)
        selected_id = self._resolve_node_id(node, source_ids)
        if not relation_filter:
            relation_filter = frozenset(RELATIONSHIP_TYPES - {"OTHER"})
        queue: deque[tuple[str, int]] = deque([(selected_id, 0)])
        visited = {selected_id}
        seen_relationships: set[RelationshipIdentity] = set()
        steps: list[TopologyTraversalStep] = []
        truncated = False
        while queue:
            current, depth = queue.popleft()
            adjacent = self._impact_adjacent(current, relation_filter)
            if depth >= max_depth:
                if any(
                    _relationship_identity(step.relationship) not in seen_relationships
                    for step in adjacent
                ):
                    truncated = True
                continue
            for step in adjacent:
                relationship_identity = _relationship_identity(step.relationship)
                if relationship_identity in seen_relationships:
                    continue
                if len(steps) >= DEFAULT_LIMIT:
                    truncated = True
                    break
                seen_relationships.add(relationship_identity)
                observed = TopologyTraversalStep(
                    relationship=step.relationship,
                    direction=step.direction,
                    node_id=step.node_id,
                    depth=depth + 1,
                )
                steps.append(observed)
                if step.node_id not in visited:
                    visited.add(step.node_id)
                    queue.append((step.node_id, depth + 1))
            if truncated:
                break
        involved_sources = {_node_source_id(self.nodes_by_id[node_id]) for node_id in visited}
        return TopologyTraversalResult(
            receipt=self._receipt_for_sources(involved_sources),
            nodes=tuple(self.nodes_by_id[node_id] for node_id in sorted(visited)),
            relationships=tuple(step.relationship for step in steps),
            steps=tuple(steps),
            truncated=truncated,
        )

    def _validate_source_filter(self, source_id: str | None) -> set[str]:
        available = {
            source.source_id
            for source in self.nodes_by_id.values()
            if isinstance(source, TopologySource)
        }
        if source_id is None:
            return available
        source_id = validate_source_id(source_id)
        if source_id not in available:
            raise TopologyNodeResolutionError(f"unknown topology source: {source_id}")
        return {source_id}

    def _resolve_node_id(self, selector: str, source_ids: set[str]) -> str:
        if not isinstance(selector, str) or not (value := selector.strip()):
            raise TopologyNodeResolutionError("topology node selector must not be blank")
        if value in self.nodes_by_id:
            if _node_source_id(self.nodes_by_id[value]) not in source_ids:
                raise TopologyNodeResolutionError(f"unknown topology node selector: {value}")
            return value
        normalized = value.casefold()
        candidate_ids = {
            candidate
            for index in self._selectors.values()
            for candidate in index.get(normalized, ())
            if _node_source_id(self.nodes_by_id[candidate]) in source_ids
        }
        if len(candidate_ids) == 1:
            return next(iter(candidate_ids))
        if not candidate_ids:
            raise TopologyNodeResolutionError(f"unknown topology node selector: {value}")
        shown = tuple(sorted(candidate_ids))[:10]
        raise TopologyNodeResolutionError(
            f"ambiguous topology node selector {value!r}: {', '.join(shown)}",
            candidates=shown,
            candidate_count=len(candidate_ids),
            candidates_truncated=len(candidate_ids) > len(shown),
        )

    def _adjacent(
        self, node_id: str, direction: str, relations: frozenset[str]
    ) -> tuple[TopologyTraversalStep, ...]:
        pairs: list[tuple[str, TopologyRelationship]] = []
        if direction in {"out", "both"}:
            pairs.extend(("out", relation) for relation in self.outgoing[node_id])
        if direction in {"in", "both"}:
            pairs.extend(("in", relation) for relation in self.incoming[node_id])
        return self._steps_from_pairs(pairs, relations)

    def _impact_adjacent(
        self, node_id: str, relations: frozenset[str]
    ) -> tuple[TopologyTraversalStep, ...]:
        """Walk outward for containment and inward for affected dependents."""
        pairs: list[tuple[str, TopologyRelationship]] = []
        for relation in self.outgoing[node_id]:
            if IMPACT_DIRECTIONS.get(relation.type) in {"out", "both"}:
                pairs.append(("out", relation))
        for relation in self.incoming[node_id]:
            if IMPACT_DIRECTIONS.get(relation.type) in {"in", "both"}:
                pairs.append(("in", relation))
        return self._steps_from_pairs(pairs, relations)

    @staticmethod
    def _steps_from_pairs(
        pairs: Iterable[tuple[str, TopologyRelationship]], relations: frozenset[str]
    ) -> tuple[TopologyTraversalStep, ...]:
        """Normalize deterministic adjacent observations without self-loop doubles."""
        steps_by_identity: dict[
            RelationshipIdentity, TopologyTraversalStep
        ] = {}
        for step_direction, relation in pairs:
            if relations and relation.type not in relations:
                continue
            step = TopologyTraversalStep(
                relationship=relation,
                direction=step_direction,
                node_id=relation.target_id if step_direction == "out" else relation.source_id,
                depth=1,
            )
            identity = _relationship_identity(relation)
            existing = steps_by_identity.get(identity)
            if existing is None or step.direction < existing.direction:
                steps_by_identity[identity] = step
        return tuple(
            sorted(
                steps_by_identity.values(),
                key=lambda step: (
                    step.direction,
                    _relationship_sort_key(step.relationship),
                    step.node_id,
                ),
            )
        )

    def _receipt_for_sources(self, source_ids: set[str]) -> TopologyReceipt:
        ordered_sources = sorted(source_ids)
        if len(ordered_sources) == 1:
            source_id = ordered_sources[0]
            return TopologyReceipt(
                generation=self.generation,
                source_id=source_id,
                source_fingerprint=self._source_fingerprints.get(source_id),
                source_fingerprints={
                    source_id: self._source_fingerprints[source_id]
                }
                if source_id in self._source_fingerprints
                else {},
                provider_receipt_hashes=self._provider_receipt_hashes.get(source_id, {}),
                provider_artifact_paths=tuple(self._provider_artifact_paths.get(source_id, {}).values()),
                provider_statuses=self._provider_statuses.get(source_id, {}),
            )
        hashes: dict[str, str] = {}
        statuses: dict[str, str] = {}
        paths: list[str] = []
        fingerprints = {
            source_id: self._source_fingerprints[source_id]
            for source_id in ordered_sources
            if source_id in self._source_fingerprints
        }
        for source_id in ordered_sources:
            hashes.update({f"{source_id}:{provider}": value for provider, value in self._provider_receipt_hashes.get(source_id, {}).items()})
            statuses.update({f"{source_id}:{provider}": value for provider, value in self._provider_statuses.get(source_id, {}).items()})
            paths.extend(self._provider_artifact_paths.get(source_id, {}).values())
        return TopologyReceipt(
            generation=self.generation,
            source_id=None,
            source_fingerprints=fingerprints,
            provider_receipt_hashes=hashes,
            provider_artifact_paths=tuple(paths),
            provider_statuses=statuses,
        )

    def _validate_source_nodes(self) -> None:
        sources = {source.source_id for source in self.nodes_by_id.values() if isinstance(source, TopologySource)}
        for node in self.nodes_by_id.values():
            if _node_source_id(node) not in sources:
                raise TopologyProviderError(f"topology node has no source node: {node.id}")


def _validate_common_document(document: Mapping[str, object], provider: str) -> None:
    if document.get("schema_version") != 2:
        raise TopologyProviderError("unsupported provider schema version")
    if document.get("tool") != provider:
        raise TopologyProviderError(f"provider artifact tool does not match {provider!r}")
    tool_version = _require_string(document, "tool_version")
    if provider == "codegraph" and tool_version != "1.4.1":
        raise TopologyProviderError("unsupported CodeGraph tool version")
    if provider == "codegraph" and document.get("version") != "2.0.0":
        raise TopologyProviderError("unsupported CodeGraph artifact version")
    _require_bool(document, "complete")
    _require_bool(document, "supported")


def _validate_native_status(provider: str, status: str) -> None:
    allowed = _CODEGRAPH_NATIVE_STATUSES if provider == "codegraph" else _PERLGRAPH_NATIVE_STATUSES
    if status not in allowed:
        raise TopologyProviderError(
            f"unsupported native {provider} provider_status: {status!r}"
        )


def _validate_counts(
    provider: str,
    document: Mapping[str, object],
    counts: Mapping[str, object],
    symbols: list[object],
    relationships: list[object],
    complete: bool,
    native_status: str,
) -> int:
    if provider == "codegraph":
        _require_object(document, "diagnostics")
        unresolved = _require_list(_require_object(document, "diagnostics"), "unresolved_relationships")
        fields = (
            "discovered_symbols",
            "emitted_symbols",
            "excluded_symbols",
            "discovered_relationships",
            "emitted_relationships",
            "excluded_relationships",
        )
        values = {field: _require_nonnegative_int(counts, field) for field in fields}
        if values["emitted_symbols"] != len(symbols) or values["emitted_relationships"] != len(relationships):
            raise TopologyProviderError("CodeGraph emitted counts do not match collections")
        if values["discovered_symbols"] != values["emitted_symbols"] + values["excluded_symbols"]:
            raise TopologyProviderError("CodeGraph symbol counts do not reconcile")
        if values["discovered_relationships"] != values["emitted_relationships"] + values["excluded_relationships"]:
            raise TopologyProviderError("CodeGraph relationship counts do not reconcile")
        failed_extractions = _codegraph_failed_extractions(document)
        if failed_extractions and (native_status != "partial" or complete):
            raise TopologyProviderError(
                "CodeGraph failed extraction requires partial status and complete=false"
            )
        if native_status == "complete" and not complete:
            raise TopologyProviderError("complete CodeGraph status requires complete=true")
        if native_status == "partial" and complete:
            raise TopologyProviderError("partial CodeGraph status requires complete=false")
        return len(unresolved)

    capabilities = _require_object(document, "capabilities")
    for key in ("exact_symbol_keys", "exact_relationship_endpoints", "unresolved_relationship_diagnostics"):
        if capabilities.get(key) is not True:
            raise TopologyProviderError(f"PerlGraph capability {key} must be true")
    unresolved = _require_list(document, "unresolved_relationships")
    fields = (
        "discovered_files",
        "emitted_files",
        "discovered_symbols",
        "emitted_symbols",
        "discovered_relationships",
        "emitted_relationships",
        "unresolved_relationships",
        "parse_failures",
        "parse_diagnostics",
        "dynamic_patterns",
    )
    values = {field: _require_nonnegative_int(counts, field) for field in fields}
    if values["emitted_symbols"] != len(symbols) or values["emitted_relationships"] != len(relationships):
        raise TopologyProviderError("PerlGraph emitted counts do not match collections")
    if values["unresolved_relationships"] != len(unresolved):
        raise TopologyProviderError("PerlGraph unresolved count does not match diagnostics")
    if values["discovered_relationships"] != values["emitted_relationships"] + values["unresolved_relationships"]:
        raise TopologyProviderError("PerlGraph relationship counts do not reconcile")
    parse_failures = _require_list(document, "parse_failures")
    parse_diagnostics = _require_list(document, "parse_diagnostics")
    unsupported_patterns = _require_list(document, "unsupported_patterns")
    if values["discovered_files"] != values["emitted_files"] + values["parse_failures"]:
        raise TopologyProviderError("PerlGraph file counts do not reconcile")
    if values["discovered_symbols"] != values["emitted_symbols"]:
        raise TopologyProviderError("PerlGraph symbol counts do not reconcile")
    if len(parse_failures) != values["parse_failures"]:
        raise TopologyProviderError("PerlGraph parse failure count does not match collection")
    if len(unsupported_patterns) != values["dynamic_patterns"]:
        raise TopologyProviderError("PerlGraph dynamic pattern count does not match collection")
    if len(parse_diagnostics) > values["parse_diagnostics"]:
        raise TopologyProviderError("PerlGraph parse diagnostic count does not match collection")
    supported = _require_bool(document, "supported")
    expected_status = _expected_perlgraph_status(
        values,
        symbols=symbols,
        parse_failures=parse_failures,
        parse_diagnostics=parse_diagnostics,
        unsupported_patterns=unsupported_patterns,
    )
    if native_status != expected_status:
        raise TopologyProviderError(
            f"PerlGraph provider_status {native_status!r} contradicts producer rules; expected {expected_status!r}"
        )
    if supported is not (values["discovered_files"] > 0):
        raise TopologyProviderError("PerlGraph supported claim contradicts discovered files")
    return len(unresolved)


def _codegraph_failed_extractions(document: Mapping[str, object]) -> int:
    counts: list[int] = []
    for section, field in (
        ("index_stats", "failed_files"),
        ("extraction_summary", "total_skipped_error"),
    ):
        if section not in document:
            continue
        section_data = _require_object(document, section)
        if field not in section_data:
            continue
        counts.append(_require_nonnegative_int(section_data, field))
    if len(counts) == 2 and counts[0] != counts[1]:
        raise TopologyProviderError(
            "CodeGraph failed extraction counts do not reconcile"
        )
    return counts[0] if counts else 0


def _load_symbols(
    raw_symbols: list[object], *, provider: str, source_id: str
) -> tuple[TopologySymbol, ...]:
    symbols: list[TopologySymbol] = []
    locators: set[tuple[str, str, str, str]] = set()
    keys: set[str] = set()
    for raw_symbol in raw_symbols:
        symbol = _require_object_value(raw_symbol, "provider symbol")
        path = _require_string(symbol, "file_path")
        qualified_name = _require_string(symbol, "qualified_name")
        kind = _require_string(symbol, "kind")
        signature = symbol.get("signature") or ""
        if not isinstance(signature, str):
            raise TopologyProviderError("provider symbol signature must be a string or null")
        name = symbol.get("name", "")
        if not isinstance(name, str):
            raise TopologyProviderError("provider symbol name must be a string")
        key = validate_symbol_key(_require_string(symbol, "symbol_key"))
        normalized_path = normalize_source_path(path)
        locator = (normalized_path, qualified_name, kind, signature)
        if locator in locators:
            raise TopologyProviderError("duplicate canonical provider symbol locator")
        if key in keys:
            raise TopologyProviderError("duplicate provider symbol key")
        locators.add(locator)
        keys.add(key)
        symbols.append(
            TopologySymbol(
                source_id=source_id,
                provider=provider,
                symbol_key=key,
                path=normalized_path,
                qualified_name=qualified_name,
                kind=kind,
                signature=signature,
                name=name,
                line_start=_optional_positive_int(symbol, "line_start"),
                line_end=_optional_positive_int(symbol, "line_end"),
            )
        )
    return tuple(sorted(symbols, key=lambda symbol: (symbol.path, symbol.qualified_name, symbol.kind, symbol.symbol_key)))


def _load_relationships(
    raw_relationships: list[object],
    *,
    provider: str,
    symbols_by_key: Mapping[str, TopologySymbol],
) -> tuple[TopologyRelationship, ...]:
    relationships: list[TopologyRelationship] = []
    identities: set[RelationshipIdentity] = set()
    for raw_relationship in raw_relationships:
        relation = _require_object_value(raw_relationship, "provider relationship")
        source_key = validate_symbol_key(_require_string(relation, "source_key"))
        target_key = validate_symbol_key(_require_string(relation, "target_key"))
        if source_key not in symbols_by_key or target_key not in symbols_by_key:
            raise TopologyProviderError("provider relationship has missing emitted endpoint")
        provider_kind = _require_string(relation, "kind")
        normalized_type = _RELATIONSHIP_MAP[provider].get(provider_kind, "OTHER")
        path = relation.get("file_path")
        if path is not None and not isinstance(path, str):
            raise TopologyProviderError("provider relationship file_path must be a string")
        normalized = TopologyRelationship(
            source_id=symbols_by_key[source_key].id,
            target_id=symbols_by_key[target_key].id,
            type=normalized_type,
            provider=provider,
            provider_kind=provider_kind,
            path=normalize_source_path(path) if path is not None else None,
            line_start=_optional_positive_int(relation, "line_start"),
            confidence=_optional_confidence(relation, label="relationship"),
            provenance=_optional_provenance(relation, label="relationship"),
            notes=_optional_notes(relation, label="relationship"),
        )
        identity = _relationship_identity(normalized)
        if identity in identities:
            raise TopologyProviderError("duplicate traversable provider relationship")
        identities.add(identity)
        relationships.append(normalized)
    return tuple(sorted(relationships, key=_relationship_sort_key))


def _load_diagnostics(
    document: Mapping[str, object],
    *,
    provider: str,
    symbols_by_key: Mapping[str, TopologySymbol],
) -> tuple[TopologyDiagnostic, ...]:
    if provider == "codegraph":
        raw_diagnostics = _require_list(
            _require_object(document, "diagnostics"), "unresolved_relationships"
        )
    else:
        raw_diagnostics = _require_list(document, "unresolved_relationships")
    diagnostics: list[TopologyDiagnostic] = []
    for raw_diagnostic in raw_diagnostics:
        diagnostic = _require_object_value(raw_diagnostic, "provider unresolved diagnostic")
        source_key = diagnostic.get("source_key")
        target_key = diagnostic.get("target_key")
        if source_key is not None and not isinstance(source_key, str):
            raise TopologyProviderError("diagnostic source_key must be a string")
        if target_key is not None and not isinstance(target_key, str):
            raise TopologyProviderError("diagnostic target_key must be a string")
        path = diagnostic.get("file_path")
        if path is not None and not isinstance(path, str):
            raise TopologyProviderError("diagnostic file_path must be a string")
        kind = _require_string(diagnostic, "kind")
        diagnostics.append(
            TopologyDiagnostic(
                provider=provider,
                provider_kind=kind,
                source_key=validate_symbol_key(source_key) if source_key else None,
                target_key=validate_symbol_key(target_key) if target_key else None,
                source_name=_diagnostic_name(diagnostic, "source"),
                target_name=_diagnostic_name(diagnostic, "target"),
                path=normalize_source_path(path) if path is not None else None,
                line_start=_optional_positive_int(diagnostic, "line_start"),
                confidence=_optional_confidence(diagnostic),
                provenance=_optional_provenance(diagnostic),
                notes=_optional_notes(diagnostic),
            )
        )
    return tuple(
        sorted(
            diagnostics,
            key=lambda item: (
                item.provider_kind,
                item.source_key or "",
                item.target_key or "",
                item.path or "",
                item.line_start or 0,
                item.confidence or "",
                item.provenance,
                item.notes or "",
            ),
        )
    )


def _diagnostic_name(diagnostic: Mapping[str, object], stem: str) -> str:
    value = diagnostic.get(stem)
    if value is None:
        value = diagnostic.get(f"{stem}_name")
    if value is None:
        return ""
    if not isinstance(value, str):
        raise TopologyProviderError(f"diagnostic {stem} name must be a string")
    return value


def _optional_confidence(
    observation: Mapping[str, object], *, label: str = "diagnostic"
) -> str | None:
    value = observation.get("confidence")
    if value is None:
        return None
    if not isinstance(value, str) or value not in {
        "high",
        "medium",
        "low",
        "dynamic",
    }:
        raise TopologyProviderError(f"{label} confidence is unsupported")
    return value


def _optional_provenance(
    observation: Mapping[str, object], *, label: str = "diagnostic"
) -> tuple[str, ...]:
    value = observation.get("provenance")
    if value is None:
        return ()
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item for item in value
    ):
        raise TopologyProviderError(
            f"{label} provenance must be a list of non-empty strings"
        )
    return tuple(value)


def _optional_notes(
    observation: Mapping[str, object], *, label: str = "diagnostic"
) -> str | None:
    value = observation.get("notes")
    if value is None:
        return None
    if not isinstance(value, str):
        raise TopologyProviderError(f"{label} notes must be a string")
    return value


def _validate_derived_endpoint_collections(
    document: Mapping[str, object],
    provider: str,
    symbols_by_key: Mapping[str, TopologySymbol],
) -> None:
    """Reject stale exact-key references in provider-native derived views."""
    symbol_keys = set(symbols_by_key)
    if provider == "codegraph":
        for collection_name, source_name, target_name in (
            ("call_graph", "caller_key", "callee_key"),
            ("type_hierarchy", "child_key", "parent_key"),
        ):
            for entry in _require_list(document, collection_name):
                edge = _require_object_value(entry, collection_name)
                if (
                    _require_string(edge, source_name) not in symbol_keys
                    or _require_string(edge, target_name) not in symbol_keys
                ):
                    raise TopologyProviderError(
                        f"CodeGraph {collection_name} has missing emitted endpoint"
                    )
        for entry in _require_list(document, "impact_radius"):
            impact = _require_object_value(entry, "impact_radius")
            if _require_string(impact, "symbol_key") not in symbol_keys:
                raise TopologyProviderError(
                    "CodeGraph impact_radius has missing emitted symbol"
                )
            affected = _require_list(impact, "affected_keys")
            if any(not isinstance(key, str) or key not in symbol_keys for key in affected):
                raise TopologyProviderError(
                    "CodeGraph impact_radius has missing emitted endpoint"
                )
        return

    for entry in _require_list(document, "call_graph"):
        edge = _require_object_value(entry, "PerlGraph call_graph")
        if (
            _require_string(edge, "source_key") not in symbol_keys
            or _require_string(edge, "target_key") not in symbol_keys
        ):
            raise TopologyProviderError(
                "PerlGraph call_graph has missing emitted endpoint"
            )
    parse_failures = _require_list(document, "parse_failures")
    unsupported_patterns = _require_list(document, "unsupported_patterns")
    parse_diagnostics = _require_list(document, "parse_diagnostics")
    counts = _require_object(document, "counts")
    if len(parse_failures) != _require_nonnegative_int(counts, "parse_failures"):
        raise TopologyProviderError("PerlGraph parse failure count does not match collection")
    if len(unsupported_patterns) != _require_nonnegative_int(counts, "dynamic_patterns"):
        raise TopologyProviderError("PerlGraph dynamic pattern count does not match collection")
    diagnostic_errors = 0
    for diagnostic in parse_diagnostics:
        diagnostic_object = _require_object_value(diagnostic, "PerlGraph parse diagnostic")
        diagnostic_errors += _require_nonnegative_int(diagnostic_object, "error_count")
    if diagnostic_errors != _require_nonnegative_int(counts, "parse_diagnostics"):
        raise TopologyProviderError(
            "PerlGraph parse diagnostic count does not match collection"
        )


def _normalize_status(
    provider: str,
    *,
    document: Mapping[str, object],
    native_status: str,
    complete: bool,
    symbol_count: int,
    relationship_count: int,
) -> str:
    if provider == "perlgraph":
        return native_status
    if native_status == "partial":
        return "degraded"
    supported = document.get("supported")
    if supported is not None and not isinstance(supported, bool):
        raise TopologyProviderError("CodeGraph supported must be a boolean when present")
    if supported is False:
        if symbol_count or relationship_count:
            raise TopologyProviderError(
                "unsupported CodeGraph artifact must not emit graph data"
            )
        return "unsupported"
    if symbol_count == 0 and relationship_count == 0:
        capabilities = document.get("capabilities")
        explicitly_unsupported = isinstance(capabilities, dict) and capabilities.get("provider_available") is False
        return "unsupported" if explicitly_unsupported else "empty"
    return "ready" if complete else "degraded"


def _expected_perlgraph_status(
    counts: Mapping[str, int],
    *,
    symbols: list[object],
    parse_failures: list[object],
    parse_diagnostics: list[object],
    unsupported_patterns: list[object],
) -> str:
    """Mirror Task 2's capability-aware PerlGraph producer status rules."""
    if counts["discovered_files"] == 0:
        return "unsupported"
    if parse_failures or parse_diagnostics or unsupported_patterns:
        return "degraded"
    if not symbols:
        return "empty"
    return "ready"


def _node_index(
    nodes: Iterable[TopologySource | TopologyFile | TopologySymbol],
) -> Mapping[str, TopologySource | TopologyFile | TopologySymbol]:
    indexed: dict[str, TopologySource | TopologyFile | TopologySymbol] = {}
    for node in nodes:
        if node.id in indexed:
            raise TopologyProviderError(f"duplicate topology node id: {node.id}")
        indexed[node.id] = node
    return MappingProxyType(dict(sorted(indexed.items())))


def _relationship_tuple(
    relationships: Iterable[TopologyRelationship],
    nodes: Mapping[str, object],
) -> tuple[TopologyRelationship, ...]:
    indexed: dict[RelationshipIdentity, TopologyRelationship] = {}
    for relationship in relationships:
        if relationship.source_id not in nodes or relationship.target_id not in nodes:
            raise TopologyProviderError(
                f"topology relationship has missing endpoint: {relationship.source_id} {relationship.type} {relationship.target_id}"
            )
        identity = _relationship_identity(relationship)
        if identity in indexed:
            raise TopologyProviderError("duplicate topology relationship")
        indexed[identity] = relationship
    return tuple(sorted(indexed.values(), key=_relationship_sort_key))


def _relationship_indexes(
    relationships: tuple[TopologyRelationship, ...], nodes: Mapping[str, object]
) -> tuple[Mapping[str, tuple[TopologyRelationship, ...]], Mapping[str, tuple[TopologyRelationship, ...]]]:
    outgoing: dict[str, list[TopologyRelationship]] = {node_id: [] for node_id in nodes}
    incoming: dict[str, list[TopologyRelationship]] = {node_id: [] for node_id in nodes}
    for relationship in relationships:
        outgoing[relationship.source_id].append(relationship)
        incoming[relationship.target_id].append(relationship)
    return (
        MappingProxyType({node_id: tuple(sorted(edges, key=_relationship_sort_key)) for node_id, edges in outgoing.items()}),
        MappingProxyType({node_id: tuple(sorted(edges, key=_relationship_sort_key)) for node_id, edges in incoming.items()}),
    )


def _selector_indexes(
    nodes: Mapping[str, TopologySource | TopologyFile | TopologySymbol]
) -> Mapping[str, Mapping[str, tuple[str, ...]]]:
    indexes: dict[str, dict[str, set[str]]] = {
        "key": {}, "qualified_name": {}, "basename": {}, "path": {},
    }
    for node in nodes.values():
        values: list[tuple[str, str]] = [("basename", node.id.rpartition(":")[2])]
        if isinstance(node, TopologyFile):
            values.extend((("path", node.path), ("basename", node.path.rpartition("/")[2])))
        elif isinstance(node, TopologySymbol):
            values.extend(
                (("key", node.symbol_key), ("key", node.symbol_key[7:]), ("qualified_name", node.qualified_name), ("path", node.path), ("basename", node.path.rpartition("/")[2]))
            )
        elif isinstance(node, TopologySource):
            values.append(("basename", node.source_id))
        for index_name, value in values:
            indexes[index_name].setdefault(value.casefold(), set()).add(node.id)
    return MappingProxyType(
        {
            name: MappingProxyType({key: tuple(sorted(value)) for key, value in sorted(index.items())})
            for name, index in indexes.items()
        }
    )


def _immutable_nested_scalar_map(values: Mapping[str, str]) -> Mapping[str, str]:
    normalized: dict[str, str] = {}
    for key, value in sorted(values.items()):
        if not isinstance(value, str) or not value:
            raise TopologyProviderError("source fingerprint must be a non-empty string")
        normalized[validate_source_id(key)] = value
    return MappingProxyType(normalized)


def _immutable_nested_map(values: Mapping[str, Mapping[str, str]]) -> Mapping[str, Mapping[str, str]]:
    return MappingProxyType(
        {
            validate_source_id(source_id): MappingProxyType(
                {validate_provider(provider): value for provider, value in sorted(provider_values.items())}
            )
            for source_id, provider_values in sorted(values.items())
        }
    )


def _immutable_nested_hashes(values: Mapping[str, Mapping[str, str]]) -> Mapping[str, Mapping[str, str]]:
    return MappingProxyType(
        {
            validate_source_id(source_id): MappingProxyType(
                {
                    validate_provider(provider): _validate_artifact_hash(value)
                    for provider, value in sorted(provider_values.items())
                }
            )
            for source_id, provider_values in sorted(values.items())
        }
    )


def _immutable_nested_statuses(values: Mapping[str, Mapping[str, str]]) -> Mapping[str, Mapping[str, str]]:
    normalized = _immutable_nested_map(values)
    if any(
        status not in NORMALIZED_STATUSES
        for provider_values in normalized.values()
        for status in provider_values.values()
    ):
        raise TopologyProviderError("unknown normalized provider status")
    return normalized


def _receipt_hashes_for_loaded(
    providers: Iterable[LoadedTopologyProvider],
) -> Mapping[str, Mapping[str, str]]:
    rows: dict[str, dict[str, str]] = {}
    for provider in providers:
        rows.setdefault(provider.source_id, {})[provider.provider] = provider.artifact_hash
    return rows


def _statuses_for_loaded(
    providers: Iterable[LoadedTopologyProvider],
) -> Mapping[str, Mapping[str, str]]:
    rows: dict[str, dict[str, str]] = {}
    for provider in providers:
        rows.setdefault(provider.source_id, {})[provider.provider] = provider.status
    return rows


def _reject_duplicate_loaded_providers(
    providers: Iterable[LoadedTopologyProvider],
) -> None:
    seen: set[tuple[str, str]] = set()
    for provider in providers:
        identity = (provider.source_id, provider.provider)
        if identity in seen:
            raise TopologyProviderError(
                f"duplicate loaded topology provider: {provider.source_id}/{provider.provider}"
            )
        seen.add(identity)


def _validate_explicit_provider_provenance(
    providers: Iterable[LoadedTopologyProvider],
    hashes: Mapping[str, Mapping[str, str]],
    paths: Mapping[str, Mapping[str, str]],
    statuses: Mapping[str, Mapping[str, str]],
) -> None:
    expected = {(provider.source_id, provider.provider) for provider in providers}
    for label, entries in (("hashes", hashes), ("paths", paths), ("statuses", statuses)):
        actual = {
            (source_id, provider)
            for source_id, provider_entries in entries.items()
            for provider in provider_entries
        }
        if label == "statuses":
            unavailable = {
                (source_id, provider)
                for source_id, provider_entries in entries.items()
                for provider, status in provider_entries.items()
                if status == "unavailable"
            }
            if actual != expected | unavailable:
                raise TopologyProviderError(
                    f"provider provenance {label} must match loaded and unavailable providers"
                )
            continue
        if actual != expected:
            raise TopologyProviderError(
                f"provider provenance {label} must exactly match loaded providers"
            )


def _validate_artifact_hash(value: str) -> str:
    try:
        return validate_symbol_key(value)
    except TopologyValidationError as exc:
        raise TopologyProviderError(f"invalid provider receipt hash: {value!r}") from exc


def _immutable_nested_paths(values: Mapping[str, Mapping[str, str]]) -> Mapping[str, Mapping[str, str]]:
    return MappingProxyType(
        {
            validate_source_id(source_id): MappingProxyType(
                {validate_provider(provider): normalize_source_path(value) for provider, value in sorted(provider_values.items())}
            )
            for source_id, provider_values in sorted(values.items())
        }
    )


def _node_source_id(node: TopologySource | TopologyFile | TopologySymbol) -> str:
    return node.source_id


def _search_text(node: TopologySource | TopologyFile | TopologySymbol) -> str:
    if isinstance(node, TopologySymbol):
        return " ".join((node.id, node.path, node.qualified_name, node.name, node.kind, node.provider))
    if isinstance(node, TopologyFile):
        return " ".join((node.id, node.path))
    return " ".join((node.id, node.source_id))


def _relationship_identity(
    relationship: TopologyRelationship,
) -> RelationshipIdentity:
    return (
        relationship.source_id,
        relationship.target_id,
        relationship.type,
        relationship.provider_kind,
        relationship.provider,
        relationship.path or "",
        relationship.line_start,
        relationship.confidence,
        relationship.provenance,
        relationship.notes,
    )


def _relationship_sort_key(
    relationship: TopologyRelationship,
) -> RelationshipSortKey:
    return (
        relationship.type,
        relationship.source_id,
        relationship.target_id,
        relationship.provider,
        relationship.provider_kind,
        relationship.path or "",
        relationship.line_start or 0,
        relationship.confidence is not None,
        relationship.confidence or "",
        relationship.provenance,
        relationship.notes is not None,
        relationship.notes or "",
    )


def _validate_types(values: frozenset[str], allowed: frozenset[str], label: str) -> frozenset[str]:
    if not isinstance(values, frozenset) or not all(isinstance(value, str) for value in values):
        raise ValueError(f"{label} filter must be a frozenset of strings")
    normalized = frozenset(value.upper() for value in values)
    unknown = normalized - allowed
    if unknown:
        raise ValueError(f"unsupported {label} filter: {', '.join(sorted(unknown))}")
    return normalized


def _validate_limit(limit: int) -> None:
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= MAX_LIMIT:
        raise ValueError(f"topology result limit must be between 1 and {MAX_LIMIT}")


def _validate_depth(depth: int) -> None:
    if not isinstance(depth, int) or isinstance(depth, bool) or not 1 <= depth <= MAX_IMPACT_DEPTH:
        raise ValueError(f"topology impact depth must be between 1 and {MAX_IMPACT_DEPTH}")


def _validate_direction(direction: str) -> None:
    if direction not in {"in", "out", "both"}:
        raise ValueError(f"unsupported topology direction: {direction!r}")


def _require_object(document: Mapping[str, object], name: str) -> Mapping[str, object]:
    value = document.get(name)
    if not isinstance(value, dict):
        raise TopologyProviderError(f"provider artifact {name} must be an object")
    return value


def _require_object_value(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise TopologyProviderError(f"{label} must be an object")
    return value


def _require_list(document: Mapping[str, object], name: str) -> list[object]:
    value = document.get(name)
    if not isinstance(value, list):
        raise TopologyProviderError(f"provider artifact {name} must be a list")
    return value


def _require_string(document: Mapping[str, object], name: str) -> str:
    value = document.get(name)
    if not isinstance(value, str) or not value:
        raise TopologyProviderError(f"provider artifact {name} must be a non-empty string")
    return value


def _require_bool(document: Mapping[str, object], name: str) -> bool:
    value = document.get(name)
    if not isinstance(value, bool):
        raise TopologyProviderError(f"provider artifact {name} must be a boolean")
    return value


def _require_nonnegative_int(document: Mapping[str, object], name: str) -> int:
    value = document.get(name)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise TopologyProviderError(f"provider count {name} must be a non-negative integer")
    return value


def _optional_positive_int(document: Mapping[str, object], name: str) -> int | None:
    value = document.get(name)
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise TopologyProviderError(f"provider {name} must be a positive integer")
    return value
