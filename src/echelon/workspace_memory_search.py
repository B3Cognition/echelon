from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from echelon.mempalace_requirements import create_requirement_memory_adapter

MAX_MEMORY_SCAN_ROWS = 5_000
DEFAULT_SEARCH_LIMIT = 10
DEFAULT_SEARCH_OVERFETCH = 8


class WorkspaceMemorySearchError(RuntimeError):
    """Bounded operator-facing error for workspace memory search commands."""


@dataclass(frozen=True)
class WorkspaceMemorySearchHit:
    drawer_id: str
    content: str
    room: str
    spec_id: str
    artifact_path: str
    requirement_id: str
    kind: str
    distance: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "drawer_id": self.drawer_id,
            "content": self.content,
            "room": self.room,
            "spec_id": self.spec_id,
            "artifact_path": self.artifact_path,
            "requirement_id": self.requirement_id,
            "kind": self.kind,
            "distance": self.distance,
        }


@dataclass(frozen=True)
class WorkspaceMemorySearchReport:
    query: str
    wing: str
    room: str | None
    spec: str | None
    kind: str | None
    limit: int
    hits: list[WorkspaceMemorySearchHit] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "wing": self.wing,
            "room": self.room,
            "spec": self.spec,
            "kind": self.kind,
            "limit": self.limit,
            "hits": [hit.to_dict() for hit in self.hits],
        }


@dataclass(frozen=True)
class WorkspaceMemoryFacetReport:
    wing: str
    rooms: dict[str, int] = field(default_factory=dict)
    specs: dict[str, int] = field(default_factory=dict)
    kinds: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "wing": self.wing,
            "rooms": dict(sorted(self.rooms.items())),
            "specs": dict(sorted(self.specs.items())),
            "kinds": dict(sorted(self.kinds.items())),
        }


def search_workspace_memory(
    project_root: Path,
    query: str,
    *,
    room: str | None = None,
    spec: str | None = None,
    kind: str | None = None,
    limit: int = DEFAULT_SEARCH_LIMIT,
) -> WorkspaceMemorySearchReport:
    if not query.strip():
        raise WorkspaceMemorySearchError("query must not be empty")
    bounded_limit = max(1, min(limit, 100))
    adapter = create_requirement_memory_adapter(project_root, run_id="search")
    collection = adapter.open_collection_read_only()
    where = _search_where(getattr(adapter, "wing"), room=room, kind=kind)
    try:
        raw = collection.query(  # type: ignore[attr-defined]
            query_texts=[query],
            n_results=bounded_limit * DEFAULT_SEARCH_OVERFETCH
            if spec
            else bounded_limit,
            where=where,
            include=["documents", "metadatas", "distances"],
        )
    except (Exception, SystemExit) as exc:
        raise WorkspaceMemorySearchError(type(exc).__name__) from exc

    hits: list[WorkspaceMemorySearchHit] = []
    ids = _first_list(raw.get("ids"))
    documents = _first_list(raw.get("documents"))
    metadatas = _first_list(raw.get("metadatas"))
    distances = _first_list(raw.get("distances"))
    for drawer_id, document, metadata, distance in zip(
        ids,
        documents,
        metadatas,
        distances,
    ):
        if not isinstance(drawer_id, str) or not isinstance(metadata, dict):
            continue
        artifact_path = _artifact_path(metadata)
        spec_id = _spec_id_from_artifact_path(artifact_path)
        actual_kind = _kind_from_metadata(metadata)
        if spec and spec_id != spec:
            continue
        if kind and actual_kind != kind:
            continue
        hits.append(
            WorkspaceMemorySearchHit(
                drawer_id=drawer_id,
                content=document if isinstance(document, str) else "",
                room=str(metadata.get("room") or ""),
                spec_id=spec_id,
                artifact_path=artifact_path,
                requirement_id=str(metadata.get("requirement_id") or ""),
                kind=actual_kind,
                distance=round(float(distance), 4)
                if isinstance(distance, int | float)
                else 0.0,
            )
        )
        if len(hits) >= bounded_limit:
            break

    return WorkspaceMemorySearchReport(
        query=query,
        wing=str(getattr(adapter, "wing")),
        room=room,
        spec=spec,
        kind=kind,
        limit=bounded_limit,
        hits=hits,
    )


def list_workspace_memory_facets(project_root: Path) -> WorkspaceMemoryFacetReport:
    adapter = create_requirement_memory_adapter(project_root, run_id="list")
    collection = adapter.open_collection_read_only()
    rooms: dict[str, int] = {}
    specs: dict[str, int] = {}
    kinds: dict[str, int] = {}
    for metadata in _iter_facet_metadatas(collection, str(getattr(adapter, "wing"))):
        if not isinstance(metadata, dict):
            continue
        _increment(rooms, str(metadata.get("room") or ""))
        _increment(specs, _spec_id_from_artifact_path(_artifact_path(metadata)))
        _increment(kinds, _kind_from_metadata(metadata))
    return WorkspaceMemoryFacetReport(
        wing=str(getattr(adapter, "wing")),
        rooms=_without_empty_key(rooms),
        specs=_without_empty_key(specs),
        kinds=_without_empty_key(kinds),
    )


def _search_where(wing: str, *, room: str | None, kind: str | None) -> dict[str, Any]:
    clauses: list[dict[str, Any]] = [{"wing": {"$eq": wing}}]
    if room:
        clauses.append({"room": {"$eq": room}})
    if kind and kind != "requirement":
        clauses.append({"artifact_kind": {"$eq": kind}})
    if len(clauses) == 1:
        return clauses[0]
    return {"$and": clauses}


def _iter_facet_metadatas(collection: Any, wing: str) -> list[Any]:
    metadatas: list[Any] = []
    offset = 0
    while True:
        try:
            raw = collection.get(  # type: ignore[attr-defined]
                where={"wing": {"$eq": wing}},
                include=["metadatas"],
                limit=MAX_MEMORY_SCAN_ROWS,
                offset=offset,
            )
        except TypeError as exc:
            if offset:
                raise WorkspaceMemorySearchError(type(exc).__name__) from exc
            raw = _get_first_facet_page_without_offset(collection, wing)
            page = raw.get("metadatas") or []
            if len(page) >= MAX_MEMORY_SCAN_ROWS:
                raise WorkspaceMemorySearchError(
                    "MemPalace backend does not support complete facet scans"
                ) from exc
            metadatas.extend(page)
            break
        except (Exception, SystemExit) as exc:
            raise WorkspaceMemorySearchError(type(exc).__name__) from exc

        page = raw.get("metadatas") or []
        metadatas.extend(page)
        if len(page) < MAX_MEMORY_SCAN_ROWS:
            break
        offset += len(page)
    return metadatas


def _get_first_facet_page_without_offset(collection: Any, wing: str) -> dict[str, Any]:
    try:
        return collection.get(  # type: ignore[attr-defined]
            where={"wing": {"$eq": wing}},
            include=["metadatas"],
            limit=MAX_MEMORY_SCAN_ROWS,
        )
    except (Exception, SystemExit) as exc:
        raise WorkspaceMemorySearchError(type(exc).__name__) from exc


def _first_list(value: object) -> list[Any]:
    if isinstance(value, list) and value and isinstance(value[0], list):
        return value[0]
    return []


def _artifact_path(metadata: dict[str, Any]) -> str:
    value = metadata.get("artifact_path") or metadata.get("source_file") or ""
    return str(value).replace("\\", "/").lstrip("./")


def _spec_id_from_artifact_path(artifact_path: str) -> str:
    parts = Path(artifact_path).parts
    if len(parts) >= 2 and parts[0] == "specs":
        return parts[1]
    return ""


def _kind_from_metadata(metadata: dict[str, Any]) -> str:
    kind = metadata.get("artifact_kind")
    if isinstance(kind, str) and kind:
        return kind
    requirement_id = metadata.get("requirement_id")
    if isinstance(requirement_id, str) and requirement_id.startswith("CTX-"):
        return "supporting-context"
    return "requirement"


def _increment(counts: dict[str, int], key: str) -> None:
    counts[key] = counts.get(key, 0) + 1


def _without_empty_key(counts: dict[str, int]) -> dict[str, int]:
    return {key: value for key, value in counts.items() if key}
