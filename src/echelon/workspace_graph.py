"""Deterministic composition of persisted spec artifact graphs."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from importlib.metadata import PackageNotFoundError, version
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Mapping

import yaml

from echelon.spec_graph import (
    GRAPH_FILENAME,
    GRAPH_SCHEMA_VERSION,
    GraphEdge,
    GraphInput,
    GraphNode,
    SpecGraphError,
    _prepare_graph_output_path,
    _validate_graph,
    build_spec_graph,
)
from echelon.spec_graph_audit import audit_spec_graph, classify_spec_graph_audit
from harness.spec_frontmatter import read_frontmatter, read_target_entries


WORKSPACE_GRAPH_FILENAME = "workspace-artifact-graph.json"


class WorkspaceGraphError(RuntimeError):
    """Raised when a workspace cannot produce a deterministic graph."""


@dataclass(frozen=True)
class WorkspaceCompositionIssue:
    severity: str
    code: str
    message: str
    subject_id: str | None = None

    def to_dict(self) -> dict[str, str]:
        payload = {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
        }
        if self.subject_id is not None:
            payload["subject_id"] = self.subject_id
        return payload


@dataclass(frozen=True)
class WorkspaceGraphMember:
    spec_id: str
    graph_path: str
    graph_hash: str | None
    member_source_set_digest: str | None
    member_memory_state_digest: str | None
    audit_hash: str
    audit_status: str
    included: bool
    exclusion_reason: str | None = None

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "spec_id": self.spec_id,
            "graph_path": self.graph_path,
            "graph_hash": self.graph_hash,
            "member_source_set_digest": self.member_source_set_digest,
            "member_memory_state_digest": self.member_memory_state_digest,
            "audit_hash": self.audit_hash,
            "audit_status": self.audit_status,
            "included": self.included,
        }
        if self.exclusion_reason is not None:
            payload["exclusion_reason"] = self.exclusion_reason
        return payload


@dataclass(frozen=True)
class WorkspaceArtifactGraph:
    workspace_name: str
    generator_version: str
    members: tuple[WorkspaceGraphMember, ...]
    inputs: tuple[GraphInput, ...]
    nodes: tuple[GraphNode, ...]
    edges: tuple[GraphEdge, ...]

    @property
    def source_set_digest(self) -> str:
        return _canonical_digest(
            [
                item.to_dict()
                for item in sorted(self.inputs, key=lambda value: (value.role, value.path))
            ]
        )

    @property
    def member_state_digest(self) -> str:
        return _canonical_digest(
            [
                member.to_dict()
                for member in sorted(self.members, key=lambda value: value.spec_id)
            ]
        )

    def to_dict(self) -> dict[str, object]:
        try:
            _validate_graph(self.nodes, self.edges)
        except Exception as exc:
            raise WorkspaceGraphError(str(exc)) from exc
        return {
            "schema_version": GRAPH_SCHEMA_VERSION,
            "generator_version": self.generator_version,
            "scope": "workspace",
            "workspace_name": self.workspace_name,
            "source_set_digest": self.source_set_digest,
            "member_state_digest": self.member_state_digest,
            "members": [
                member.to_dict()
                for member in sorted(self.members, key=lambda value: value.spec_id)
            ],
            "inputs": [
                item.to_dict()
                for item in sorted(self.inputs, key=lambda value: (value.role, value.path))
            ],
            "nodes": [node.to_dict() for node in sorted(self.nodes, key=lambda value: value.id)],
            "edges": [
                edge.to_dict()
                for edge in sorted(
                    self.edges,
                    key=lambda value: (value.source, value.type, value.target),
                )
            ],
        }


@dataclass(frozen=True)
class WorkspaceGraphBuildResult:
    graph: WorkspaceArtifactGraph
    issues: tuple[WorkspaceCompositionIssue, ...]


@dataclass(frozen=True)
class _Source:
    id: str
    path: str


def discover_canonical_spec_dirs(project_root: Path) -> tuple[Path, ...]:
    """Return direct, non-symlink canonical spec directories in stable order."""
    root = project_root.resolve()
    _load_workspace_config(root)
    specs_root = root / "specs"
    if not specs_root.is_dir():
        return ()
    return tuple(
        candidate
        for candidate in sorted(specs_root.iterdir(), key=lambda value: value.name)
        if candidate.is_dir()
        and not candidate.is_symlink()
        and (candidate / "spec.md").is_file()
        and not (candidate / "spec.md").is_symlink()
    )


def build_workspace_graph(project_root: Path) -> WorkspaceGraphBuildResult:
    """Compose persisted member graphs using authoritative live audits."""
    root = project_root.resolve()
    workspace_role, sources, config_digest = _load_workspace_config(root)
    spec_dirs = discover_canonical_spec_dirs(root)
    if not spec_dirs:
        raise WorkspaceGraphError("no canonical spec directories were found")

    node_records: dict[str, tuple[GraphNode, set[str]]] = {}
    edge_records: dict[tuple[str, str, str], tuple[GraphEdge, set[str]]] = {}
    members: list[WorkspaceGraphMember] = []
    issues: list[WorkspaceCompositionIssue] = []
    metadata: list[tuple[Path, str]] = []

    for spec_dir in spec_dirs:
        spec_id = spec_dir.name
        (
            graph_hash,
            member_source_set_digest,
            member_memory_state_digest,
            nodes,
            edges,
            invalid_reason,
        ) = _read_member_graph(spec_dir, spec_id)
        (
            audit_status,
            audit_hash,
            audited_graph_hash,
            audit_classification,
        ) = _audit_receipt(root, spec_dir)
        snapshot_mismatch = graph_hash is not None and audited_graph_hash != graph_hash
        included = invalid_reason is None and audit_status in {"pass", "warn"}
        exclusion_reason = (
            invalid_reason
            or ("member_graph_changed" if snapshot_mismatch else None)
            or _audit_exclusion_reason(audit_classification)
        )
        included = included and exclusion_reason is None
        members.append(
            WorkspaceGraphMember(
                spec_id=spec_id,
                graph_path=_relative_path(root, spec_dir / GRAPH_FILENAME),
                graph_hash=graph_hash,
                member_source_set_digest=member_source_set_digest,
                member_memory_state_digest=member_memory_state_digest,
                audit_hash=audit_hash,
                audit_status=audit_status,
                included=included,
                exclusion_reason=None if included else exclusion_reason,
            )
        )
        metadata.append((spec_dir, spec_id))

        if not included:
            issue_code = exclusion_reason or "member_graph_unavailable"
            issues.append(
                WorkspaceCompositionIssue(
                    "error",
                    issue_code,
                    f"spec member is excluded from workspace composition: {spec_id}",
                    f"spec:{spec_id}",
                )
            )
            _merge_node(
                node_records,
                GraphNode(
                    f"spec:{spec_id}",
                    "Spec",
                    {
                        "spec_id": spec_id,
                        "composition_status": "excluded",
                        "member_audit_status": audit_status,
                        "exclusion_reason": exclusion_reason,
                    },
                ),
                spec_id,
            )
            continue

        assert nodes is not None and edges is not None
        remapped_ids: dict[str, str] = {}
        for node in nodes:
            _ensure_member_node_identity_is_not_reserved(node.id)
            normalized = _normalized_node_id(node)
            remapped_ids[node.id] = normalized
            properties = dict(node.properties)
            if node.type == "Spec":
                properties["composition_status"] = "included"
                properties["member_audit_status"] = audit_status
            _merge_node(
                node_records,
                GraphNode(normalized, node.type, properties),
                spec_id,
            )
        for edge in edges:
            _merge_edge(
                edge_records,
                GraphEdge(
                    remapped_ids[edge.source],
                    edge.type,
                    remapped_ids[edge.target],
                    dict(edge.properties),
                ),
                spec_id,
            )

    _add_workspace_nodes(node_records, root.name, workspace_role, sources)
    _add_workspace_relationships(
        node_records,
        edge_records,
        metadata,
        sources,
        issues,
    )
    inputs = _workspace_inputs(root, spec_dirs, members, config_digest)
    graph = WorkspaceArtifactGraph(
        workspace_name=root.name,
        generator_version=_generator_version(),
        members=tuple(sorted(members, key=lambda value: value.spec_id)),
        inputs=inputs,
        nodes=tuple(record[0] for _, record in sorted(node_records.items())),
        edges=tuple(record[0] for _, record in sorted(edge_records.items())),
    )
    return WorkspaceGraphBuildResult(
        graph=graph,
        issues=tuple(sorted(issues, key=lambda value: (value.code, value.subject_id or ""))),
    )


def render_workspace_graph(graph: WorkspaceArtifactGraph) -> bytes:
    return (json.dumps(graph.to_dict(), indent=2, sort_keys=True) + "\n").encode("utf-8")


def workspace_graph_path(project_root: Path) -> Path:
    return (
        project_root.resolve()
        / ".echelon"
        / "runtime"
        / "graph"
        / WORKSPACE_GRAPH_FILENAME
    )


def write_workspace_graph(graph: WorkspaceArtifactGraph, project_root: Path) -> Path:
    """Atomically publish a rendered workspace graph beside its project root."""
    path = workspace_graph_path(project_root)
    return write_workspace_graph_bytes(path, render_workspace_graph(graph))


def write_workspace_graph_bytes(path: Path, data: bytes) -> Path:
    """Atomically replace one workspace-derived output with exact bytes."""
    _prepare_graph_output_path(
        path,
        label="workspace graph",
        create_parent=True,
    )
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
        temporary_path = None
        directory_fd = os.open(
            path.parent,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
        )
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink()
            except OSError:
                pass
    return path


def load_workspace_graph_document(project_root: Path) -> dict[str, object]:
    path = workspace_graph_path(project_root)
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise WorkspaceGraphError(f"workspace graph artifact is missing: {path}") from exc
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WorkspaceGraphError(f"workspace graph artifact is unreadable: {path}") from exc
    if not isinstance(document, dict):
        raise WorkspaceGraphError("workspace graph document must be an object")
    if document.get("schema_version") != GRAPH_SCHEMA_VERSION:
        raise WorkspaceGraphError("unsupported workspace graph schema version")
    if document.get("scope") != "workspace":
        raise WorkspaceGraphError("workspace graph scope must be workspace")
    return document


def _load_workspace_config(root: Path) -> tuple[str | None, tuple[_Source, ...], str]:
    path = root / ".echelon" / "config.yml"
    if not path.is_file():
        raise WorkspaceGraphError("canonical workspace config is missing")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise WorkspaceGraphError("canonical workspace config is invalid") from exc
    if not isinstance(raw, dict):
        raise WorkspaceGraphError("canonical workspace config must be an object")
    workspace = raw.get("workspace", {})
    if not isinstance(workspace, dict):
        raise WorkspaceGraphError("workspace config must be an object")
    git_role = workspace.get("git_role")
    if git_role is not None and not isinstance(git_role, str):
        raise WorkspaceGraphError("workspace git_role must be a string")
    raw_sources = raw.get("sources", [])
    if not isinstance(raw_sources, list):
        raise WorkspaceGraphError("workspace sources must be a list")
    source_ids: set[str] = set()
    sources: list[_Source] = []
    for item in raw_sources:
        if not isinstance(item, dict):
            raise WorkspaceGraphError("workspace source must be an object")
        source_id = item.get("id")
        source_path = item.get("path")
        if not isinstance(source_id, str) or not source_id.strip():
            raise WorkspaceGraphError("workspace source id is missing")
        if not isinstance(source_path, str) or not source_path.strip():
            raise WorkspaceGraphError("workspace source path is missing")
        source_id = source_id.strip()
        source_path = source_path.strip()
        if source_id in source_ids:
            raise WorkspaceGraphError(f"duplicate workspace source id: {source_id}")
        resolved_source_path = _resolve_workspace_path(root, source_path)
        if not resolved_source_path.exists():
            raise WorkspaceGraphError(
                f"workspace source path does not exist: {source_path}"
            )
        if not resolved_source_path.is_dir():
            raise WorkspaceGraphError(
                f"workspace source path is not a directory: {source_path}"
            )
        source_ids.add(source_id)
        sources.append(_Source(source_id, source_path))
    projection = {
        "workspace": {"git_role": git_role},
        "sources": [
            {"id": source.id, "path": source.path}
            for source in sorted(sources, key=lambda value: (value.id, value.path))
        ],
    }
    return git_role, tuple(sorted(sources, key=lambda value: (value.id, value.path))), _canonical_digest(projection)


def _read_member_graph(
    spec_dir: Path,
    spec_id: str,
) -> tuple[
    str | None,
    str | None,
    str | None,
    tuple[GraphNode, ...] | None,
    tuple[GraphEdge, ...] | None,
    str | None,
]:
    path = spec_dir / GRAPH_FILENAME
    try:
        graph_bytes = path.read_bytes()
    except OSError:
        return None, None, None, None, None, "member_graph_invalid"
    graph_hash = _sha256(graph_bytes)
    try:
        document = json.loads(graph_bytes)
        if not isinstance(document, dict):
            raise ValueError("document")
        if document.get("schema_version") != GRAPH_SCHEMA_VERSION:
            raise ValueError("schema")
        if document.get("spec_id") != spec_id:
            raise ValueError("spec id")
        source_set_digest = document.get("source_set_digest")
        memory_state_digest = document.get("memory_state_digest")
        if not isinstance(source_set_digest, str) or not isinstance(
            memory_state_digest, str
        ):
            raise ValueError("member digests")
        nodes, edges = _parse_member_graph(document)
        spec_nodes = [node for node in nodes if node.type == "Spec"]
        if len(spec_nodes) != 1:
            raise ValueError("spec node")
        spec_node = spec_nodes[0]
        if spec_node.id != f"spec:{spec_id}" or spec_node.properties.get("spec_id") != spec_id:
            raise ValueError("spec node identity")
        _validate_graph(nodes, edges)
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        KeyError,
        TypeError,
        ValueError,
        SpecGraphError,
    ):
        return graph_hash, None, None, None, None, "member_graph_invalid"
    return graph_hash, source_set_digest, memory_state_digest, nodes, edges, None


def _workspace_inputs(
    root: Path,
    spec_dirs: tuple[Path, ...],
    members: list[WorkspaceGraphMember],
    config_digest: str,
) -> tuple[GraphInput, ...]:
    inputs = [
        GraphInput(".echelon/config.yml", config_digest, "workspace_config", True),
        GraphInput(
            "specs",
            _canonical_digest([spec_dir.name for spec_dir in spec_dirs]),
            "canonical_spec_set",
            True,
        ),
    ]
    for member in members:
        inputs.append(
            GraphInput(
                member.graph_path,
                member.graph_hash or "sha256:missing",
                "member_graph",
                True,
            )
        )
    for spec_dir in spec_dirs:
        inputs.append(
            _workspace_file_input(root, spec_dir / "spec.md", "workspace_spec")
        )
        targets_path = spec_dir / "targets.yml"
        if targets_path.is_file():
            inputs.append(
                _workspace_file_input(root, targets_path, "workspace_targets")
            )
    return tuple(inputs)


def _workspace_file_input(root: Path, path: Path, role: str) -> GraphInput:
    try:
        digest = _sha256(path.read_bytes())
    except OSError as exc:
        raise WorkspaceGraphError(f"workspace input is unreadable: {path}") from exc
    return GraphInput(_relative_path(root, path), digest, role, True)


def _parse_member_graph(document: Mapping[str, object]) -> tuple[tuple[GraphNode, ...], tuple[GraphEdge, ...]]:
    raw_nodes = document.get("nodes")
    raw_edges = document.get("edges")
    if not isinstance(raw_nodes, list) or not isinstance(raw_edges, list):
        raise ValueError("graph contract")
    nodes = tuple(
        GraphNode(str(item["id"]), str(item["type"]), _properties(item.get("properties")))
        for item in raw_nodes
        if isinstance(item, dict)
    )
    edges = tuple(
        GraphEdge(
            str(item["source"]),
            str(item["type"]),
            str(item["target"]),
            _properties(item.get("properties")),
        )
        for item in raw_edges
        if isinstance(item, dict)
    )
    if len(nodes) != len(raw_nodes) or len(edges) != len(raw_edges):
        raise ValueError("graph members")
    return nodes, edges


def _properties(value: object) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise TypeError("graph properties")
    return value


def _audit_receipt(
    root: Path,
    spec_dir: Path,
) -> tuple[str, str, str | None, str]:
    try:
        report = audit_spec_graph(root, spec_dir)
        status = str(report.status)
        payload = report.to_dict()
        graph_hash = report.graph_hash if isinstance(report.graph_hash, str) else None
        classification = classify_spec_graph_audit(report)
    except Exception as exc:
        status = "unavailable"
        payload = {"schema_version": 1, "status": status, "error": type(exc).__name__}
        graph_hash = None
        classification = "unavailable"
    return status, _canonical_digest(payload), graph_hash, classification


def _audit_exclusion_reason(classification: str) -> str | None:
    if classification == "current":
        return None
    if classification == "stale":
        return "member_graph_stale"
    if classification == "unhealthy":
        return "member_graph_unhealthy"
    return "member_graph_unavailable"


def _normalized_node_id(node: GraphNode) -> str:
    if node.type == "Artifact":
        path = node.properties.get("path")
        if not isinstance(path, str) or not path:
            raise WorkspaceGraphError(f"artifact node has invalid path: {node.id}")
        return f"artifact:{path}"
    if node.type == "MemPalaceDrawer":
        drawer_id = node.properties.get("drawer_id")
        if not isinstance(drawer_id, str) or not drawer_id:
            raise WorkspaceGraphError(f"drawer node has invalid drawer_id: {node.id}")
        return f"drawer:{drawer_id}"
    return node.id


def _merge_node(
    records: dict[str, tuple[GraphNode, set[str]]],
    node: GraphNode,
    spec_id: str,
) -> None:
    existing = records.get(node.id)
    if existing is None:
        properties = dict(node.properties)
        properties["member_specs"] = [spec_id]
        records[node.id] = (GraphNode(node.id, node.type, properties), {spec_id})
        return
    current, member_specs = existing
    if current.type != node.type or _without_member_specs(current.properties) != _without_member_specs(node.properties):
        raise WorkspaceGraphError(f"conflicting normalized node properties: {node.id}")
    member_specs.add(spec_id)
    properties = dict(current.properties)
    properties["member_specs"] = sorted(member_specs)
    records[node.id] = (GraphNode(current.id, current.type, properties), member_specs)


def _merge_edge(
    records: dict[tuple[str, str, str], tuple[GraphEdge, set[str]]],
    edge: GraphEdge,
    spec_id: str,
) -> None:
    identity = (edge.source, edge.type, edge.target)
    existing = records.get(identity)
    if existing is None:
        records[identity] = (
            GraphEdge(edge.source, edge.type, edge.target, {**edge.properties, "member_specs": [spec_id]}),
            {spec_id},
        )
        return
    current, member_specs = existing
    if _without_member_specs(current.properties) != _without_member_specs(edge.properties):
        raise WorkspaceGraphError(
            f"conflicting normalized edge properties: {edge.source} {edge.type} {edge.target}"
        )
    member_specs.add(spec_id)
    records[identity] = (
        GraphEdge(current.source, current.type, current.target, {**_without_member_specs(current.properties), "member_specs": sorted(member_specs)}),
        member_specs,
    )


def _without_member_specs(properties: Mapping[str, object]) -> dict[str, object]:
    return {key: value for key, value in properties.items() if key != "member_specs"}


def _add_workspace_nodes(
    records: dict[str, tuple[GraphNode, set[str]]],
    workspace_name: str,
    git_role: str | None,
    sources: tuple[_Source, ...],
) -> None:
    properties: dict[str, object] = {"workspace_name": workspace_name}
    if git_role is not None:
        properties["git_role"] = git_role
    _add_workspace_node(
        records,
        GraphNode("workspace:current", "Workspace", properties),
    )
    for source in sources:
        _add_workspace_node(
            records,
            GraphNode(
                f"source:{source.id}",
                "SourceRoot",
                {"source_id": source.id, "path": source.path},
            ),
        )


def _ensure_member_node_identity_is_not_reserved(node_id: str) -> None:
    if node_id == "workspace:current" or node_id.startswith("source:"):
        raise WorkspaceGraphError(f"reserved workspace node identity: {node_id}")


def _add_workspace_node(
    records: dict[str, tuple[GraphNode, set[str]]],
    node: GraphNode,
) -> None:
    if node.id in records:
        raise WorkspaceGraphError(f"reserved workspace node identity: {node.id}")
    records[node.id] = (node, set())


def _add_workspace_relationships(
    nodes: dict[str, tuple[GraphNode, set[str]]],
    edges: dict[tuple[str, str, str], tuple[GraphEdge, set[str]]],
    metadata: list[tuple[Path, str]],
    sources: tuple[_Source, ...],
    issues: list[WorkspaceCompositionIssue],
) -> None:
    source_by_id = {source.id: source for source in sources}
    source_by_path = {source.path: source for source in sources}
    known_specs = {spec_id for _, spec_id in metadata}
    for spec_dir, spec_id in metadata:
        _add_workspace_edge(edges, "workspace:current", "CONTAINS_SPEC", f"spec:{spec_id}")
        for entry in read_target_entries(spec_dir):
            target_id = entry.get("id")
            target_path = entry.get("path")
            source = source_by_id.get(str(target_id)) if isinstance(target_id, str) else None
            if source is None and isinstance(target_path, str):
                source = source_by_path.get(target_path)
            if source is None:
                issues.append(
                    WorkspaceCompositionIssue(
                        "warning",
                        "target_unresolved",
                        f"spec target is not configured: {target_id or target_path}",
                        f"spec:{spec_id}",
                    )
                )
                continue
            _add_workspace_edge(edges, f"spec:{spec_id}", "TARGETS", f"source:{source.id}")
        frontmatter = read_frontmatter(spec_dir)
        for superseded in _superseded_spec_ids(frontmatter.get("supersedes")):
            if superseded not in known_specs:
                issues.append(
                    WorkspaceCompositionIssue(
                        "warning",
                        "superseded_spec_missing",
                        f"superseded spec is not canonical: {superseded}",
                        f"spec:{spec_id}",
                    )
                )
                continue
            _add_workspace_edge(edges, f"spec:{spec_id}", "SUPERSEDES", f"spec:{superseded}")


def _add_workspace_edge(
    records: dict[tuple[str, str, str], tuple[GraphEdge, set[str]]],
    source: str,
    edge_type: str,
    target: str,
) -> None:
    identity = (source, edge_type, target)
    existing = records.get(identity)
    if existing is not None:
        _, member_specs = existing
        if member_specs:
            raise WorkspaceGraphError(
                "reserved workspace edge identity: "
                f"{source} {edge_type} {target}"
            )
        return
    records[identity] = (GraphEdge(source, edge_type, target, {}), set())


def _superseded_spec_ids(value: object) -> tuple[str, ...]:
    if isinstance(value, str) and value.strip():
        return (value.strip(),)
    if isinstance(value, list):
        return tuple(sorted({str(item).strip() for item in value if str(item).strip()}))
    return ()


def _resolve_workspace_path(root: Path, value: str) -> Path:
    candidate = Path(value).expanduser()
    resolved = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise WorkspaceGraphError(f"workspace source path escapes project root: {value}") from exc
    return resolved


def _relative_path(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError as exc:
        raise WorkspaceGraphError(f"workspace path escapes project root: {path}") from exc


def _sha256(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _canonical_digest(value: object) -> str:
    return _sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def _generator_version() -> str:
    try:
        return version("echelon")
    except PackageNotFoundError:
        return "unknown"
