"""Deterministic spec-scoped artifact graph."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from importlib.metadata import PackageNotFoundError, version
import json
import os
from pathlib import Path
import stat
import tempfile
from typing import Any, Mapping

from echelon import artifact_index
from echelon.mempalace_requirements import (
    SUPPORTING_MEMORY_ARTIFACTS,
    SpecMemoryError,
    load_canonical_spec_snapshot,
    load_supporting_artifact_snapshots,
    resolve_spec_dir,
)
from echelon.topology_registry import load_topology_index
from echelon.workspace_model import discover_workspace
from harness.canonical_requirements import (
    _category_for,
    extract_canonical_requirements,
)
from harness.deferred_scope import read_ledger
from harness.re_artifacts import ReArtifactDescriptor
from harness.re_registry import (
    canonical_re_artifact_descriptors,
    load_published_index,
)
from harness.task_progress import summarize_task_progress
from harness.verified_fulfillment_ledger import (
    UNRESOLVED_STATUSES,
    read_verified_ledger,
)
from kernel.task_contract import parse_task_rows, validate_tasks_markdown


GRAPH_SCHEMA_VERSION = 1
NODE_PROJECTION_VERSION = 2
GRAPH_FILENAME = "spec-artifact-graph.json"


class SpecGraphError(RuntimeError):
    """Raised when canonical inputs cannot produce a valid graph."""


@dataclass(frozen=True)
class GraphInput:
    path: str
    hash: str
    role: str
    required: bool
    status: str | None = None
    source_set_digest: str | None = None

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "path": self.path,
            "hash": self.hash,
            "role": self.role,
            "required": self.required,
        }
        if self.source_set_digest is not None:
            payload["source_set_digest"] = self.source_set_digest
        if self.status is not None:
            payload["status"] = self.status
        return payload


@dataclass(frozen=True)
class GraphNode:
    id: str
    type: str
    properties: Mapping[str, object]

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "type": self.type,
            "properties": dict(self.properties),
        }


@dataclass(frozen=True)
class GraphEdge:
    source: str
    type: str
    target: str
    properties: Mapping[str, object]

    def to_dict(self) -> dict[str, object]:
        return {
            "source": self.source,
            "type": self.type,
            "target": self.target,
            "properties": dict(self.properties),
        }


@dataclass(frozen=True)
class MemoryReceipt:
    domain: str
    source_set_digest: str
    audit_hash: str
    status: str

    def to_dict(self) -> dict[str, str]:
        return {
            "domain": self.domain,
            "source_set_digest": self.source_set_digest,
            "audit_hash": self.audit_hash,
            "status": self.status,
        }


@dataclass(frozen=True)
class SpecArtifactGraph:
    spec_id: str
    generator_version: str
    inputs: tuple[GraphInput, ...]
    nodes: tuple[GraphNode, ...]
    edges: tuple[GraphEdge, ...]
    memory_receipts: tuple[MemoryReceipt, ...]

    @property
    def source_set_digest(self) -> str:
        records = [
            item.to_dict()
            for item in sorted(self.inputs, key=lambda value: (value.role, value.path))
            if item.role != "memory_audit_report"
        ]
        return _canonical_digest(records)

    @property
    def memory_state_digest(self) -> str:
        records = [
            receipt.to_dict()
            for receipt in sorted(self.memory_receipts, key=lambda value: value.domain)
        ]
        return _canonical_digest(records)

    def to_dict(self) -> dict[str, object]:
        _validate_graph(self.nodes, self.edges)
        return {
            "schema_version": GRAPH_SCHEMA_VERSION,
            "node_projection_version": NODE_PROJECTION_VERSION,
            "generator_version": self.generator_version,
            "spec_id": self.spec_id,
            "source_set_digest": self.source_set_digest,
            "memory_state_digest": self.memory_state_digest,
            "inputs": [
                item.to_dict()
                for item in sorted(self.inputs, key=lambda value: (value.role, value.path))
            ],
            "nodes": [
                node.to_dict()
                for node in sorted(self.nodes, key=lambda value: value.id)
            ],
            "edges": [
                edge.to_dict()
                for edge in sorted(
                    self.edges,
                    key=lambda value: (value.source, value.type, value.target),
                )
            ],
        }


def render_spec_graph(graph: SpecArtifactGraph) -> bytes:
    return (
        json.dumps(graph.to_dict(), indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def write_spec_graph(graph: SpecArtifactGraph, spec_dir: Path) -> Path:
    path = spec_dir / GRAPH_FILENAME
    return _write_spec_graph_bytes(path, render_spec_graph(graph))


def _prepare_graph_output_path(
    path: Path,
    *,
    label: str,
    create_parent: bool,
) -> None:
    """Reject symlink/non-directory ancestors before graph publication."""
    absolute_parent = path.absolute().parent
    _validate_graph_output_ancestors(absolute_parent, label)
    if create_parent:
        path.parent.mkdir(parents=True, exist_ok=True)
        _validate_graph_output_ancestors(absolute_parent, label)
    try:
        parent_metadata = absolute_parent.lstat()
    except FileNotFoundError as exc:
        raise OSError(f"{label} parent must be a real directory") from exc
    if not stat.S_ISDIR(parent_metadata.st_mode):
        raise OSError(f"{label} parent must be a real directory")
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        metadata = None
    if metadata is not None and not stat.S_ISREG(metadata.st_mode):
        raise OSError(f"{label} target must be a regular file")


def _validate_graph_output_ancestors(parent: Path, label: str) -> None:
    ancestors: list[Path] = []
    current = parent
    while True:
        ancestors.append(current)
        if current.parent == current:
            break
        current = current.parent
    for ancestor in reversed(ancestors):
        try:
            metadata = ancestor.lstat()
        except FileNotFoundError:
            continue
        if not stat.S_ISDIR(metadata.st_mode):
            raise OSError(f"{label} ancestor must be a real directory")


def _write_spec_graph_bytes(path: Path, data: bytes) -> Path:
    parent = path.parent
    _prepare_graph_output_path(path, label="spec graph", create_parent=False)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temporary: Path | None = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = None
        directory_fd = os.open(
            parent,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
        )
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary is not None:
            try:
                temporary.unlink()
            except OSError:
                pass
    return path


def build_spec_graph(
    project_root: Path,
    selector: str | Path,
) -> SpecArtifactGraph:
    root = project_root.resolve()
    spec_dir = resolve_spec_dir(root, selector)
    spec_id = spec_dir.name
    nodes: dict[str, GraphNode] = {}
    edges: list[GraphEdge] = []
    inputs: dict[str, GraphInput] = {}

    from echelon.spec_graph_structure import _add_requirements, _add_spec

    _add_spec(
        spec_id, _workspace_path(root, spec_dir),
        artifact_index.infer_lifecycle_stage(spec_dir), nodes,
    )
    rows = extract_canonical_requirements(spec_dir)
    source_path = (
        _workspace_path(root, spec_dir / "spec.md")
        if any(row.source_kind == "spec" for row in rows) else ""
    )
    requirement_ids = _add_requirements(spec_id, source_path, rows, nodes, edges)

    _add_policy_artifacts(root, spec_dir, nodes, inputs)
    _add_tasks(root, spec_dir, requirement_ids, nodes, edges)
    _add_traceability(spec_dir, requirement_ids, nodes, edges)
    _add_deferrals(spec_dir, nodes, edges)
    _add_amendments(root, spec_dir, nodes, edges, inputs)
    _add_verified_ledger(root, spec_dir, requirement_ids, nodes, edges, inputs)
    memory_receipts: list[MemoryReceipt] = []
    _add_canonical_memory(
        root,
        spec_dir,
        nodes,
        edges,
        inputs,
        memory_receipts,
    )
    _add_evidence_memory(
        root,
        spec_dir,
        nodes,
        edges,
        inputs,
        memory_receipts,
    )
    _add_re_memory(
        root,
        spec_dir,
        nodes,
        edges,
        inputs,
        memory_receipts,
    )
    _add_re_topology(root, spec_dir, nodes, edges, inputs)

    return SpecArtifactGraph(
        spec_id=spec_id,
        generator_version=_generator_version(),
        inputs=tuple(inputs.values()),
        nodes=tuple(nodes.values()),
        edges=tuple(edges),
        memory_receipts=tuple(memory_receipts),
    )


def _add_policy_artifacts(
    root: Path,
    spec_dir: Path,
    nodes: dict[str, GraphNode],
    inputs: dict[str, GraphInput],
) -> None:
    from echelon.spec_graph_structure import _local_artifact_paths

    candidates: set[Path] = set()
    for relative in _local_artifact_paths():
        candidate = spec_dir / relative
        if candidate.is_file():
            candidates.add(candidate)

    try:
        from echelon.mempalace_spec_evidence import (
            load_spec_evidence_artifact_snapshots,
        )

        candidates.update(
            snapshot.artifact_file
            for snapshot in load_spec_evidence_artifact_snapshots(root, spec_dir)
        )
    except Exception:
        pass

    candidates.update(_linked_re_artifacts(root, spec_dir))
    for path in sorted(candidates):
        _add_artifact(root, spec_dir, path, nodes, inputs)


def _add_artifact(
    root: Path,
    spec_dir: Path,
    path: Path,
    nodes: dict[str, GraphNode],
    inputs: dict[str, GraphInput],
    *,
    role: str | None = None,
) -> str:
    from echelon.spec_graph_structure import _add_artifact_record

    workspace_path = _workspace_path(root, path)
    resolved_role = role or _artifact_role(spec_dir, path)
    digest = _file_hash(path)
    return _add_artifact_record(
        spec_dir.name, workspace_path, path.name, digest, resolved_role,
        _input_required(spec_dir, path), nodes, inputs,
    )


def _add_re_topology(
    root: Path,
    spec_dir: Path,
    nodes: dict[str, GraphNode],
    edges: list[GraphEdge],
    inputs: dict[str, GraphInput],
) -> None:
    context_path = spec_dir / "re-context.json"
    linked_artifacts = sorted(
        path
        for path in _linked_re_artifacts(root, spec_dir)
        if path != context_path
    )
    if not linked_artifacts:
        return
    stored_artifacts = {
        edge.source for edge in edges if edge.type == "STORED_AS"
    }
    re_index = load_published_index(root)
    if re_index is None:
        return
    descriptor_lookup = {
        descriptor.path: descriptor
        for descriptor in canonical_re_artifact_descriptors(root, re_index)
    }
    descriptors: list[tuple[Path, ReArtifactDescriptor]] = []
    for path in linked_artifacts:
        descriptor = descriptor_lookup.get(_workspace_path(root, path))
        if descriptor is not None:
            descriptors.append((path, descriptor))

    for path, descriptor in descriptors:
        artifact_id = f"artifact:{spec_dir.name}:{_workspace_path(root, path)}"
        artifact_node = nodes.get(artifact_id)
        if artifact_node is None:
            continue
        properties = dict(artifact_node.properties)
        properties.update(
            {
                "re_artifact_kind": descriptor.kind,
                "re_scope": descriptor.scope,
            }
        )
        if descriptor.source_id is not None:
            properties["re_source_id"] = descriptor.source_id
        if artifact_id in stored_artifacts:
            properties["mining_status"] = "mined"
        elif descriptor.kind != "re-decision":
            properties["mining_status"] = "eligible"
        nodes[artifact_id] = GraphNode(artifact_id, artifact_node.type, properties)

        if descriptor.scope != "workspace" or descriptor.kind != "re-decision":
            continue
        relative_path = descriptor.path.removeprefix("re/workspace/")
        decision_id = f"decision:workspace:{relative_path}"
        nodes[decision_id] = GraphNode(
            decision_id,
            "Decision",
            {
                "scope": "workspace",
                "path": _workspace_path(root, path),
                "title": _adr_title(path),
            },
        )
        edges.append(
            GraphEdge(
                f"spec:{spec_dir.name}",
                "INFORMED_BY_DECISION",
                decision_id,
                {},
            )
        )
        edges.append(GraphEdge(decision_id, "DOCUMENTED_BY", artifact_id, {}))

    if not descriptors:
        return

    by_source: dict[str, list[tuple[Path, ReArtifactDescriptor]]] = {}
    for path, descriptor in descriptors:
        if descriptor.scope != "source" or descriptor.source_id is None:
            continue
        by_source.setdefault(descriptor.source_id, []).append((path, descriptor))

    if not by_source:
        return
    workspace_sources = _canonical_workspace_sources(root)
    topology_index = load_topology_index(root)
    for source_id, source_artifacts in sorted(by_source.items()):
        source_node_id = f"source:{source_id}"
        workspace_source = workspace_sources.get(source_id)
        semantic_source = re_index.sources.get(source_id)
        if workspace_source is None or semantic_source is None:
            raise SpecGraphError(
                f"canonical source identity conflict: {source_node_id}"
            )
        semantic_path = _canonical_source_path(
            root,
            semantic_source.source_path,
            source_node_id,
        )
        if semantic_path != workspace_source:
            raise SpecGraphError(
                f"canonical source identity conflict: {source_node_id}"
            )
        source_properties: dict[str, object] = {
            "source_id": source_id,
            "path": workspace_source,
            "publication_status": semantic_source.status,
            "semantic_generation": re_index.generation,
            "semantic_fingerprint": semantic_source.fingerprint,
            "semantic_receipt_path": semantic_source.manifest,
        }

        topology_source = (
            topology_index.sources.get(source_id)
            if topology_index is not None
            else None
        )
        topology_receipt_id: str | None = None
        if topology_source is not None:
            topology_path = _canonical_source_path(
                root,
                topology_source.source_path,
                source_node_id,
            )
            if (
                topology_source.source_id != source_id
                or topology_path != workspace_source
            ):
                raise SpecGraphError(
                    f"canonical source identity conflict: {source_node_id}"
                )
            topology_receipt_path = topology_source.receipt.path
            source_properties.update(
                {
                    "topology_generation": topology_index.generation,
                    "topology_fingerprint": topology_source.source_fingerprint.value,
                    "topology_receipt_path": topology_receipt_path,
                }
            )
            topology_receipt_id = _add_artifact(
                root,
                spec_dir,
                root / topology_receipt_path,
                nodes,
                inputs,
                role="topology-receipt",
            )
        nodes[source_node_id] = GraphNode(
            source_node_id,
            "SourceRoot",
            source_properties,
        )
        edges.append(
            GraphEdge(f"spec:{spec_dir.name}", "USES_SOURCE", source_node_id, {})
        )
        if topology_receipt_id is not None:
            edges.append(
                GraphEdge(
                    source_node_id,
                    "HAS_TOPOLOGY_RECEIPT",
                    topology_receipt_id,
                    {},
                )
            )

        for path, descriptor in source_artifacts:
            artifact_id = f"artifact:{spec_dir.name}:{_workspace_path(root, path)}"
            if artifact_id not in nodes:
                continue
            if descriptor.kind != "re-decision":
                edges.append(
                    GraphEdge(source_node_id, "DESCRIBED_BY", artifact_id, {})
                )
                continue
            source_relative_path = descriptor.path.removeprefix(
                f"re/sources/{source_id}/"
            )
            decision_id = f"decision:{source_id}:{source_relative_path}"
            nodes[decision_id] = GraphNode(
                decision_id,
                "Decision",
                {
                    "source_id": source_id,
                    "path": _workspace_path(root, path),
                    "title": _adr_title(path),
                },
            )
            edges.append(GraphEdge(source_node_id, "HAS_DECISION", decision_id, {}))
            edges.append(GraphEdge(decision_id, "DOCUMENTED_BY", artifact_id, {}))


def _canonical_workspace_sources(root: Path) -> dict[str, str]:
    config_path = root / ".echelon" / "config.yml"
    if not config_path.is_file():
        raise SpecGraphError("canonical workspace config is missing")
    try:
        manifest = discover_workspace(root)
    except Exception as exc:
        raise SpecGraphError("canonical workspace config is invalid") from exc
    sources: dict[str, str] = {}
    for source in manifest.sources:
        if source.id in sources:
            raise SpecGraphError(f"duplicate workspace source id: {source.id}")
        sources[source.id] = _canonical_source_path(
            root,
            source.path,
            f"source:{source.id}",
        )
    return sources


def _canonical_source_path(root: Path, value: object, subject_id: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SpecGraphError(
            f"canonical source identity conflict: {subject_id}"
        )
    candidate = Path(value.strip())
    if candidate.is_absolute():
        raise SpecGraphError(
            f"canonical source identity conflict: {subject_id}"
        )
    resolved = (root / candidate).resolve()
    try:
        relative = resolved.relative_to(root)
    except ValueError as exc:
        raise SpecGraphError(
            f"canonical source identity conflict: {subject_id}"
        ) from exc
    if not resolved.is_dir():
        raise SpecGraphError(
            f"canonical source identity conflict: {subject_id}"
        )
    return relative.as_posix()


def _adr_title(path: Path) -> str:
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                title = stripped.lstrip("#").strip()
                if title:
                    return title
    except (OSError, UnicodeError):
        pass
    return path.stem


def _add_tasks(
    root: Path,
    spec_dir: Path,
    requirement_ids: set[str],
    nodes: dict[str, GraphNode],
    edges: list[GraphEdge],
) -> None:
    path = spec_dir / "tasks.md"
    if not path.is_file():
        return
    markdown = path.read_text(encoding="utf-8")
    from echelon.spec_graph_structure import _add_task_text

    _add_task_text(spec_dir.name, markdown, requirement_ids, nodes, edges)


def _add_traceability(
    spec_dir: Path,
    requirement_ids: set[str],
    nodes: dict[str, GraphNode],
    edges: list[GraphEdge],
) -> None:
    path = spec_dir / "inputs" / "traceability.json"
    catalog_path = spec_dir / "inputs" / "catalog.json"
    if not path.is_file() or not catalog_path.is_file():
        return
    payload = _read_json_object(path, "product input traceability")
    from echelon.spec_graph_structure import _add_traceability_payload

    _add_traceability_payload(spec_dir.name, payload, requirement_ids, nodes, edges)


def _add_deferrals(
    spec_dir: Path,
    nodes: dict[str, GraphNode],
    edges: list[GraphEdge],
) -> None:
    ledger = read_ledger(spec_dir)
    from echelon.spec_graph_structure import _add_deferral_records

    _add_deferral_records(spec_dir.name, ledger, nodes, edges)


def _add_amendments(
    root: Path,
    spec_dir: Path,
    nodes: dict[str, GraphNode],
    edges: list[GraphEdge],
    inputs: dict[str, GraphInput],
) -> None:
    from echelon.spec_graph_structure import (
        AMENDMENT_CONTROL_PATHS, _add_amendment_record,
    )

    amendment_root = spec_dir / "amendments"
    if not amendment_root.is_dir():
        return
    for revision_dir in sorted(
        (path for path in amendment_root.iterdir() if path.is_dir()),
        key=lambda path: path.name,
    ):
        if not revision_dir.name.isdigit():
            continue
        revision = revision_dir.name
        _add_amendment_record(
            spec_dir.name, revision, _workspace_path(root, revision_dir), nodes, edges,
        )
        for relative in AMENDMENT_CONTROL_PATHS:
            artifact = revision_dir / relative
            if artifact.is_file():
                _add_artifact(
                    root,
                    spec_dir,
                    artifact,
                    nodes,
                    inputs,
                    role="amendment-control",
                )


def _add_verified_ledger(
    root: Path,
    spec_dir: Path,
    requirement_ids: set[str],
    nodes: dict[str, GraphNode],
    edges: list[GraphEdge],
    inputs: dict[str, GraphInput],
) -> None:
    path = spec_dir / "verified-fulfillment-ledger.json"
    if not path.is_file():
        return
    target = _add_artifact(
        root,
        spec_dir,
        path,
        nodes,
        inputs,
        role="verification-evidence",
    )
    from echelon.spec_graph_structure import _add_verified_records

    _add_verified_records(
        spec_dir.name, read_verified_ledger(path), target, requirement_ids, edges,
    )


def _add_canonical_memory(
    root: Path,
    spec_dir: Path,
    nodes: dict[str, GraphNode],
    edges: list[GraphEdge],
    inputs: dict[str, GraphInput],
    receipts: list[MemoryReceipt],
) -> None:
    snapshot = load_canonical_spec_snapshot(root, spec_dir)
    support_snapshots = load_supporting_artifact_snapshots(root, spec_dir)
    for support in support_snapshots:
        _add_artifact(
            root,
            spec_dir,
            support.spec_file,
            nodes,
            inputs,
            role="supporting-context",
        )
    snapshots = [snapshot, *support_snapshots]
    source_set_digest = _memory_source_set_digest(snapshots)
    virtual_path = f"mempalace://canonical-spec/{spec_dir.name}/audit"

    try:
        from echelon.mempalace_requirements import (
            create_requirement_memory_adapter,
        )

        adapter = create_requirement_memory_adapter(root, run_id="graph")
        planned_rows = list(
            adapter.plan_canonical_rows(
                snapshot.content,
                source=snapshot.source,
                artifact_metadata=snapshot.artifact_metadata,
            )
        )
        for support in support_snapshots:
            planned_rows.extend(
                adapter.plan_canonical_support_rows(
                    support.content,
                    source=support.source,
                    artifact_metadata=support.artifact_metadata,
                )
            )
        from echelon.mempalace_audit import audit_spec_memory

        report = audit_spec_memory(root, spec_dir)
    except SpecMemoryError as exc:
        report = _UnavailableMemoryReport(type(exc).__name__)
        planned_rows = []
    except (Exception, SystemExit) as exc:
        report = _UnavailableMemoryReport(type(exc).__name__)
        planned_rows = locals().get("planned_rows", [])

    from echelon.spec_graph_memory import _memory_receipt_records

    receipt, audit_input = _memory_receipt_records(
        domain="canonical-spec", virtual_path=virtual_path,
        source_set_digest=source_set_digest, report=report, required=True,
    )
    receipts.append(receipt)
    inputs[virtual_path] = audit_input
    _add_drawer_rows(
        spec_dir,
        planned_rows,
        report,
        nodes,
        edges,
        source_artifact_kind={
            item.source: str(
                item.artifact_metadata.get("artifact_kind")
                or (
                    "requirement"
                    if item.source == snapshot.source
                    else "supporting-context"
                )
            )
            for item in snapshots
        },
    )


def _add_evidence_memory(
    root: Path,
    spec_dir: Path,
    nodes: dict[str, GraphNode],
    edges: list[GraphEdge],
    inputs: dict[str, GraphInput],
    receipts: list[MemoryReceipt],
) -> None:
    from echelon.mempalace_spec_evidence import (
        audit_spec_evidence_memory,
        create_spec_evidence_memory_adapter,
        load_spec_evidence_artifact_snapshots,
    )

    snapshots = load_spec_evidence_artifact_snapshots(
        root,
        spec_dir,
        allow_unlanded=True,
    )
    if not snapshots:
        return
    _add_artifact_memory_domain(
        root=root,
        spec_dir=spec_dir,
        domain="spec-evidence",
        virtual_path=f"mempalace://spec-evidence/{spec_dir.name}/audit",
        snapshots=snapshots,
        planner_name="plan_spec_evidence_artifact_rows",
        adapter_factory=lambda: create_spec_evidence_memory_adapter(
            root,
            run_id="graph",
        ),
        audit=lambda: audit_spec_evidence_memory(root, spec_dir),
        required=False,
        nodes=nodes,
        edges=edges,
        inputs=inputs,
        receipts=receipts,
    )


def _add_re_memory(
    root: Path,
    spec_dir: Path,
    nodes: dict[str, GraphNode],
    edges: list[GraphEdge],
    inputs: dict[str, GraphInput],
    receipts: list[MemoryReceipt],
) -> None:
    linked_sources = {
        _workspace_path(root, path)
        for path in _linked_re_artifacts(root, spec_dir)
        if path.name != "re-context.json"
    }
    if not linked_sources:
        return
    from echelon.mempalace_re import (
        audit_re_memory,
        create_re_memory_adapter,
        load_re_artifact_snapshots,
    )

    snapshots = [
        snapshot
        for snapshot in load_re_artifact_snapshots(root)
        if snapshot.source in linked_sources
    ]
    if not snapshots:
        return
    _add_artifact_memory_domain(
        root=root,
        spec_dir=spec_dir,
        domain="published-re",
        virtual_path="mempalace://published-re/audit",
        snapshots=snapshots,
        planner_name="plan_re_artifact_rows",
        adapter_factory=lambda: create_re_memory_adapter(root, run_id="graph"),
        audit=lambda: audit_re_memory(root),
        required=False,
        nodes=nodes,
        edges=edges,
        inputs=inputs,
        receipts=receipts,
        project_audit=True,
    )


def _add_artifact_memory_domain(
    *,
    root: Path,
    spec_dir: Path,
    domain: str,
    virtual_path: str,
    snapshots: list[object],
    planner_name: str,
    adapter_factory: object,
    audit: object,
    required: bool,
    nodes: dict[str, GraphNode],
    edges: list[GraphEdge],
    inputs: dict[str, GraphInput],
    receipts: list[MemoryReceipt],
    project_audit: bool = False,
) -> None:
    for snapshot in snapshots:
        _add_artifact(
            root,
            spec_dir,
            getattr(snapshot, "artifact_file"),
            nodes,
            inputs,
            role=(
                "verification-evidence"
                if domain == "spec-evidence"
                else "reverse-engineering"
            ),
        )
    source_set_digest = _memory_source_set_digest(snapshots)
    planned_rows: list[object] = []
    try:
        adapter = adapter_factory()  # type: ignore[operator]
        planner = getattr(adapter, planner_name)
        for snapshot in snapshots:
            planned_rows.extend(
                planner(
                    getattr(snapshot, "content"),
                    source=getattr(snapshot, "source"),
                    artifact_metadata=getattr(snapshot, "artifact_metadata"),
                )
            )
        report = audit()  # type: ignore[operator]
        if project_audit:
            report = _project_memory_audit(
                report,
                {str(getattr(row, "drawer_id")) for row in planned_rows},
            )
    except SpecMemoryError as exc:
        report = _UnavailableMemoryReport(type(exc).__name__)
    except (Exception, SystemExit) as exc:
        report = _UnavailableMemoryReport(type(exc).__name__)

    from echelon.spec_graph_memory import _memory_receipt_records

    receipt, audit_input = _memory_receipt_records(
        domain=domain, virtual_path=virtual_path,
        source_set_digest=source_set_digest, report=report, required=required,
    )
    receipts.append(receipt)
    inputs[virtual_path] = audit_input
    _add_drawer_rows(
        spec_dir,
        planned_rows,
        report,
        nodes,
        edges,
        source_artifact_kind={
            str(getattr(snapshot, "source")): str(
                getattr(snapshot, "artifact_metadata", {}).get(
                    "artifact_kind",
                    domain,
                )
            )
            for snapshot in snapshots
        },
    )


def _project_memory_audit(report: object, drawer_ids: set[str]) -> object:
    from echelon.spec_graph_memory import _project_memory_audit as project

    return project(report, drawer_ids)


def _add_drawer_rows(
    spec_dir: Path,
    planned_rows: list[object],
    report: object,
    nodes: dict[str, GraphNode],
    edges: list[GraphEdge],
    *,
    source_artifact_kind: Mapping[str, str],
) -> None:
    from echelon.spec_graph_memory import _drawer_records

    for record in _drawer_records(
        spec_dir.name, planned_rows, report, nodes.keys(),
        source_artifact_kind=source_artifact_kind,
    ):
        if isinstance(record, GraphNode):
            nodes[record.id] = record
        else:
            edges.append(record)


def _memory_source_set_digest(snapshots: list[object]) -> str:
    records = [
        {
            "path": str(getattr(snapshot, "source")),
            "hash": str(
                getattr(snapshot, "artifact_metadata", {}).get("artifact_hash")
            ),
            "artifact_kind": str(
                getattr(snapshot, "artifact_metadata", {}).get(
                    "artifact_kind",
                    "requirement",
                )
            ),
            "room": str(
                getattr(snapshot, "artifact_metadata", {}).get("room", "")
            ),
        }
        for snapshot in snapshots
    ]
    from echelon.spec_graph_memory import _source_records_digest

    return _source_records_digest(records)


def _normalized_memory_audit(report: object) -> dict[str, object]:
    from echelon.spec_graph_memory import _normalized_memory_audit as normalize

    return normalize(report)


class _UnavailableMemoryReport:
    schema_version = 1
    wing = None
    status = "unavailable"
    artifact_count = 0
    expected_count = 0
    present_current_count = 0
    missing: list[str] = []
    stale: list[str] = []
    wrong_wing: list[str] = []
    wrong_room: list[str] = []
    duplicate: list[str] = []
    non_canonical: list[str] = []
    lifecycle_excluded: list[str] = []

    def __init__(self, error: str) -> None:
        self.errors = [error]


def _linked_re_artifacts(root: Path, spec_dir: Path) -> set[Path]:
    context_path = spec_dir / "re-context.json"
    if not context_path.is_file():
        return set()
    payload = _read_json_object(context_path, "RE context")
    if payload.get("status") != "attached":
        return {context_path}
    result = {context_path}
    rows = payload.get("artifacts", [])
    if not isinstance(rows, list):
        raise SpecGraphError("RE context artifacts must be a list")
    for row in rows:
        if not isinstance(row, dict):
            raise SpecGraphError("RE context artifact must be an object")
        raw_path = str(row.get("path") or "")
        artifact = (root / raw_path).resolve()
        if not artifact.is_relative_to((root / "re").resolve()):
            raise SpecGraphError(f"RE context artifact escapes published RE: {raw_path}")
        if artifact.is_file() and _file_hash(artifact) == row.get("hash"):
            result.add(artifact)
    return result


def _artifact_role(spec_dir: Path, path: Path) -> str:
    from echelon.spec_graph_structure import _artifact_role as artifact_role

    return artifact_role(spec_dir, path)


def _input_role(role: str) -> str:
    return role.replace("-", "_")


def _input_required(spec_dir: Path, path: Path) -> bool:
    from echelon.spec_graph_structure import _artifact_required

    lifecycle = (
        artifact_index.infer_lifecycle_stage(spec_dir)
        if path.name == "tasks.md" and path.parent == spec_dir else ""
    )
    return _artifact_required(spec_dir, path, lifecycle)


def _scope_node_id(spec_id: str, item_id: str) -> str:
    if item_id.startswith("T-"):
        return f"task:{spec_id}:{item_id}"
    return f"req:{spec_id}:{item_id}"


def _workspace_path(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError as exc:
        raise SpecGraphError(f"graph artifact is outside workspace: {path}") from exc


def _file_hash(path: Path) -> str:
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


def _read_json_object(path: Path, label: str) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SpecGraphError(f"invalid {label}: {path}") from exc
    if not isinstance(payload, dict):
        raise SpecGraphError(f"invalid {label}: {path}")
    return payload


def _generator_version() -> str:
    try:
        return version("echelon")
    except PackageNotFoundError:
        return "unknown"


def _canonical_digest(value: Any) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _validate_graph(
    nodes: tuple[GraphNode, ...],
    edges: tuple[GraphEdge, ...],
) -> None:
    node_ids = [node.id for node in nodes]
    if len(set(node_ids)) != len(node_ids):
        raise SpecGraphError("duplicate node id")

    identities = [(edge.source, edge.type, edge.target) for edge in edges]
    if len(set(identities)) != len(identities):
        raise SpecGraphError("duplicate edge")

    known = set(node_ids)
    for edge in edges:
        if edge.source not in known or edge.target not in known:
            raise SpecGraphError(
                f"missing edge endpoint: {edge.source} -> {edge.target}"
            )
