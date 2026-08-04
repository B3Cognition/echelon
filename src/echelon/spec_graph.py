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

    spec_node_id = f"spec:{spec_id}"
    nodes[spec_node_id] = GraphNode(
        spec_node_id,
        "Spec",
        {
            "spec_id": spec_id,
            "path": _workspace_path(root, spec_dir),
            "lifecycle": artifact_index.infer_lifecycle_stage(spec_dir),
        },
    )

    canonical_requirements = [
        row
        for row in extract_canonical_requirements(spec_dir)
        if row.source_kind == "spec"
    ]
    requirement_ids = {row.id for row in canonical_requirements}
    for row in canonical_requirements:
        node_id = f"req:{spec_id}:{row.id}"
        nodes[node_id] = GraphNode(
            node_id,
            "Requirement",
            {
                "requirement_id": row.id,
                "category": _category_for(row.id),
                "source_line": row.source_line,
                "source_path": _workspace_path(root, spec_dir / "spec.md"),
                "source_text": row.source_text,
            },
        )
        edges.append(GraphEdge(spec_node_id, "HAS_REQUIREMENT", node_id, {}))

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
    _add_re_topology(root, spec_dir, nodes, edges)

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
    candidates: set[Path] = set()
    for definition in getattr(artifact_index, "_ARTIFACTS"):
        candidate = spec_dir / definition.path
        if candidate.is_file():
            candidates.add(candidate)
    for name in ("manifest.json", "catalog.json", "traceability.json"):
        candidate = spec_dir / "inputs" / name
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
    workspace_path = _workspace_path(root, path)
    node_id = f"artifact:{spec_dir.name}:{workspace_path}"
    resolved_role = role or _artifact_role(spec_dir, path)
    digest = _file_hash(path)
    nodes[node_id] = GraphNode(
        node_id,
        "Artifact",
        {
            "path": workspace_path,
            "role": resolved_role,
            "hash": digest,
            "mining_status": (
                "mined"
                if path.name in SUPPORTING_MEMORY_ARTIFACTS
                or resolved_role in {"requirements-source", "verification-evidence"}
                else "not-mined-by-policy"
            ),
        },
    )
    inputs[workspace_path] = GraphInput(
        path=workspace_path,
        hash=digest,
        role=_input_role(resolved_role),
        required=_input_required(spec_dir, path),
    )
    return node_id


def _add_re_topology(
    root: Path,
    spec_dir: Path,
    nodes: dict[str, GraphNode],
    edges: list[GraphEdge],
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
    descriptor_lookup = _re_artifact_descriptor_lookup(root)
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
        elif descriptor.kind in _RE_SEMANTIC_EDGE_TYPES:
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

    for source_id, source_artifacts in sorted(by_source.items()):
        source_node_id = f"re-source:{source_id}"
        source_properties: dict[str, object] = {"source_id": source_id}
        manifest_entry = next(
            (
                (path, descriptor)
                for path, descriptor in source_artifacts
                if descriptor.kind == "re-source-manifest"
            ),
            None,
        )
        if manifest_entry is not None:
            manifest_path = manifest_entry[0]
            source_properties["manifest_path"] = _workspace_path(root, manifest_path)
            try:
                manifest = _read_json_object(manifest_path, "RE source manifest")
            except SpecGraphError:
                manifest = {}
            for key in ("publication_status", "source_fingerprint"):
                value = manifest.get(key)
                if isinstance(value, str) and value:
                    source_properties[key] = value
        nodes[source_node_id] = GraphNode(
            source_node_id,
            "ReverseEngineeringSource",
            source_properties,
        )
        edges.append(
            GraphEdge(f"spec:{spec_dir.name}", "USES_RE_SOURCE", source_node_id, {})
        )

        for path, descriptor in source_artifacts:
            artifact_id = f"artifact:{spec_dir.name}:{_workspace_path(root, path)}"
            if artifact_id not in nodes:
                continue
            edge_type = _RE_SEMANTIC_EDGE_TYPES.get(
                descriptor.kind,
                "EVIDENCED_BY",
            )
            edges.append(GraphEdge(source_node_id, edge_type, artifact_id, {}))
            if descriptor.kind != "re-decision":
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


_RE_SEMANTIC_EDGE_TYPES = {
    "re-overview": "DESCRIBED_BY",
    "re-architecture": "DESCRIBED_BY",
    "re-contracts": "DECLARES_CONTRACTS_IN",
    "re-components": "CATALOGS_COMPONENTS_IN",
    "re-decision": "DECIDED_BY",
    "re-codegraph-summary": "SUMMARIZED_BY",
}


def _re_artifact_descriptor_lookup(
    root: Path,
) -> dict[str, ReArtifactDescriptor]:
    index = load_published_index(root)
    if index is None:
        return {}
    return {
        descriptor.path: descriptor
        for descriptor in canonical_re_artifact_descriptors(root, index)
    }


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
    validation = validate_tasks_markdown(markdown)
    if not validation.valid:
        raise SpecGraphError("invalid tasks.md: " + "; ".join(validation.errors))
    progress = summarize_task_progress(markdown)
    if not progress.valid:
        raise SpecGraphError("invalid task progress: " + "; ".join(progress.errors))
    for task in parse_task_rows(markdown):
        node_id = f"task:{spec_dir.name}:{task.task_id}"
        unresolved = sorted(
            set(task.requirements) - requirement_ids - {"INFRA", "UNMAPPED"}
        )
        nodes[node_id] = GraphNode(
            node_id,
            "Task",
            {
                "task_id": task.task_id,
                "status": progress.task_statuses.get(task.task_id, "PENDING"),
                "phase": task.phase,
                "target": task.target,
                "unresolved_requirement_ids": unresolved,
            },
        )
        for requirement_id in sorted(set(task.requirements).intersection(requirement_ids)):
            edges.append(
                GraphEdge(
                    node_id,
                    "IMPLEMENTS",
                    f"req:{spec_dir.name}:{requirement_id}",
                    {},
                )
            )


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
    target = f"artifact:{spec_dir.name}:specs/{spec_dir.name}/inputs/catalog.json"
    if target not in nodes:
        return
    rows = payload.get("requirements", [])
    if not isinstance(rows, list):
        raise SpecGraphError("product input traceability requirements must be a list")
    input_units_by_requirement: dict[str, set[str]] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise SpecGraphError("product input traceability entry must be an object")
        input_unit_id = str(row.get("input_unit_id") or "").strip()
        spec_ids = row.get("spec_ids", [])
        if not isinstance(spec_ids, list):
            raise SpecGraphError("product input traceability spec_ids must be a list")
        for requirement_id in sorted(
            requirement_ids.intersection(str(value) for value in spec_ids)
        ):
            input_units_by_requirement.setdefault(requirement_id, set()).add(
                input_unit_id
            )
    for requirement_id, input_unit_ids in sorted(
        input_units_by_requirement.items()
    ):
        edges.append(
            GraphEdge(
                f"req:{spec_dir.name}:{requirement_id}",
                "DERIVED_FROM",
                target,
                {"input_unit_ids": sorted(input_unit_ids)},
            )
        )


def _add_deferrals(
    spec_dir: Path,
    nodes: dict[str, GraphNode],
    edges: list[GraphEdge],
) -> None:
    ledger = read_ledger(spec_dir)
    for entry in ledger.entries:
        node_id = f"deferral:{spec_dir.name}:{entry.entry_id}"
        nodes[node_id] = GraphNode(
            node_id,
            "Deferral",
            {
                "entry_id": entry.entry_id,
                "status": entry.status,
                "selected_ids": list(entry.selected_ids),
                "derived_task_ids": list(entry.derived_task_ids),
                "reason": entry.reason,
            },
        )
        if entry.status != "deferred":
            continue
        for selected_id in entry.selected_ids:
            source = _scope_node_id(spec_dir.name, selected_id)
            if source in nodes:
                edges.append(GraphEdge(source, "DEFERRED_BY", node_id, {}))
        for task_id in entry.derived_task_ids:
            source = f"task:{spec_dir.name}:{task_id}"
            if source in nodes:
                edges.append(GraphEdge(source, "DEFERRED_BY", node_id, {}))


def _add_amendments(
    root: Path,
    spec_dir: Path,
    nodes: dict[str, GraphNode],
    edges: list[GraphEdge],
    inputs: dict[str, GraphInput],
) -> None:
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
        node_id = f"amendment:{spec_dir.name}:{revision}"
        nodes[node_id] = GraphNode(
            node_id,
            "Amendment",
            {
                "revision": revision,
                "path": _workspace_path(root, revision_dir),
                "status": "promoted",
            },
        )
        edges.append(
            GraphEdge(f"spec:{spec_dir.name}", "AMENDED_BY", node_id, {})
        )
        for relative in (
            Path("change-request.md"),
            Path("impact.md"),
            Path("inputs/manifest.json"),
            Path("inputs/catalog.json"),
            Path("inputs/traceability.json"),
        ):
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
    for row in read_verified_ledger(path).rows:
        if row.requirement_id not in requirement_ids:
            continue
        edges.append(
            GraphEdge(
                f"req:{spec_dir.name}:{row.requirement_id}",
                "VERIFIED_BY",
                target,
                {
                    "verification_status": row.status,
                    "evidence_refs": list(row.evidence_refs),
                    "verified_commit": row.verified_commit,
                    "verify_scope": row.verify_scope,
                    "complete": row.status not in UNRESOLVED_STATUSES,
                },
            )
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

    normalized = _normalized_memory_audit(report)
    audit_hash = _canonical_digest(normalized)
    status = str(getattr(report, "status", "unavailable"))
    receipt = MemoryReceipt(
        domain="canonical-spec",
        source_set_digest=source_set_digest,
        audit_hash=audit_hash,
        status=status,
    )
    receipts.append(receipt)
    inputs[virtual_path] = GraphInput(
        path=virtual_path,
        hash=audit_hash,
        role="memory_audit_report",
        required=True,
        status=status,
        source_set_digest=source_set_digest,
    )
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

    normalized = _normalized_memory_audit(report)
    audit_hash = _canonical_digest(normalized)
    status = str(getattr(report, "status", "unavailable"))
    receipts.append(
        MemoryReceipt(
            domain=domain,
            source_set_digest=source_set_digest,
            audit_hash=audit_hash,
            status=status,
        )
    )
    inputs[virtual_path] = GraphInput(
        path=virtual_path,
        hash=audit_hash,
        role="memory_audit_report",
        required=required,
        status=status,
        source_set_digest=source_set_digest,
    )
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
    projected: dict[str, list[str]] = {}
    fail_fields = (
        "missing",
        "stale",
        "wrong_wing",
        "wrong_room",
        "non_canonical",
        "lifecycle_excluded",
    )
    for field in (*fail_fields, "duplicate"):
        projected[field] = sorted(
            value
            for value in getattr(report, field, [])
            if value in drawer_ids
        )
    projected["errors"] = sorted(
        value
        for value in getattr(report, "errors", [])
        if any(str(value).startswith(drawer_id) for drawer_id in drawer_ids)
    )
    if str(getattr(report, "status", "")) == "unavailable":
        status = "unavailable"
    elif any(projected[field] for field in fail_fields):
        status = "fail"
    elif projected["duplicate"] or projected["errors"]:
        status = "warn"
    else:
        status = "pass"
    return _ProjectedMemoryReport(
        report=report,
        status=status,
        expected_count=len(drawer_ids),
        issues=projected,
    )


class _ProjectedMemoryReport:
    def __init__(
        self,
        *,
        report: object,
        status: str,
        expected_count: int,
        issues: Mapping[str, list[str]],
    ) -> None:
        self.schema_version = int(getattr(report, "schema_version", 1))
        self.wing = getattr(report, "wing", None)
        self.status = status
        self.artifact_count = 0
        self.expected_count = expected_count
        failed_ids: set[str] = set()
        for field in (
            "missing",
            "stale",
            "wrong_wing",
            "wrong_room",
            "non_canonical",
            "lifecycle_excluded",
        ):
            failed_ids.update(issues[field])
        self.present_current_count = expected_count - len(failed_ids)
        for field, values in issues.items():
            setattr(self, field, values)


def _add_drawer_rows(
    spec_dir: Path,
    planned_rows: list[object],
    report: object,
    nodes: dict[str, GraphNode],
    edges: list[GraphEdge],
    *,
    source_artifact_kind: Mapping[str, str],
) -> None:
    issue_fields = (
        "missing",
        "stale",
        "wrong_wing",
        "wrong_room",
        "non_canonical",
        "lifecycle_excluded",
        "duplicate",
    )
    issues_by_id: dict[str, list[str]] = {}
    for field in issue_fields:
        values = getattr(report, field, [])
        if not isinstance(values, list):
            continue
        for drawer_id in values:
            if isinstance(drawer_id, str):
                issues_by_id.setdefault(drawer_id, []).append(field)
    status = str(getattr(report, "status", "unavailable"))

    for row in planned_rows:
        drawer_id = str(getattr(row, "drawer_id"))
        source = str(getattr(row, "source"))
        requirement_id = str(getattr(row, "requirement_id", ""))
        issue_codes = sorted(issues_by_id.get(drawer_id, []))
        if status == "unavailable":
            presence = "unavailable"
            reconciliation_status = "unavailable"
        elif "missing" in issue_codes:
            presence = "missing"
            reconciliation_status = "fail"
        elif issue_codes:
            presence = "invalid"
            reconciliation_status = "fail"
        else:
            presence = "present"
            reconciliation_status = "pass"

        node_id = f"drawer:{spec_dir.name}:{drawer_id}"
        nodes[node_id] = GraphNode(
            node_id,
            "MemPalaceDrawer",
            {
                "drawer_id": drawer_id,
                "source_path": source,
                "room": str(getattr(row, "room", "")),
                "artifact_kind": source_artifact_kind.get(source, "unknown"),
                "artifact_hash": str(getattr(row, "artifact_hash", "")),
                "content_hash": str(
                    getattr(row, "requirement_content_sha256", "")
                ),
                "presence": presence,
                "reconciliation_status": reconciliation_status,
                "issue_codes": issue_codes,
            },
        )
        requirement_node = f"req:{spec_dir.name}:{requirement_id}"
        artifact_node = f"artifact:{spec_dir.name}:{source}"
        source_node = (
            requirement_node
            if requirement_node in nodes and source_artifact_kind.get(source) == "requirement"
            else artifact_node
        )
        if source_node not in nodes:
            raise SpecGraphError(
                f"memory planner source has no Artifact node: {source}"
            )
        edges.append(
            GraphEdge(
                source_node,
                "STORED_AS",
                node_id,
                {
                    "presence": presence,
                    "reconciliation_status": reconciliation_status,
                },
            )
        )


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
    return _canonical_digest(sorted(records, key=lambda item: item["path"]))


def _normalized_memory_audit(report: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": int(getattr(report, "schema_version", 1)),
        "wing": getattr(report, "wing", None),
        "status": str(getattr(report, "status", "unavailable")),
        "artifact_count": int(getattr(report, "artifact_count", 0)),
        "expected_count": int(getattr(report, "expected_count", 0)),
        "present_current_count": int(
            getattr(report, "present_current_count", 0)
        ),
    }
    for field in (
        "missing",
        "stale",
        "wrong_wing",
        "wrong_room",
        "duplicate",
        "non_canonical",
        "lifecycle_excluded",
        "errors",
    ):
        values = getattr(report, field, [])
        payload[field] = sorted(str(value) for value in values)
    return payload


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
    if path.name == "spec.md" and path.parent == spec_dir:
        return "requirements-source"
    if path.name == "tasks.md" and path.parent == spec_dir:
        return "task-source"
    if path.name == "deferred-scope.json":
        return "deferral-ledger"
    if path.name == "verified-fulfillment-ledger.json":
        return "verification-evidence"
    if path.parent == spec_dir / "inputs":
        return "product-input"
    if path.name == "re-context.json" or path.is_relative_to(spec_dir.parents[1] / "re"):
        return "reverse-engineering"
    if path.name in SUPPORTING_MEMORY_ARTIFACTS:
        return "supporting-context"
    return "spec-artifact"


def _input_role(role: str) -> str:
    return role.replace("-", "_")


def _input_required(spec_dir: Path, path: Path) -> bool:
    if path.name == "spec.md" and path.parent == spec_dir:
        return True
    if path.name == "tasks.md" and path.parent == spec_dir:
        return artifact_index.infer_lifecycle_stage(spec_dir) in {
            "build",
            "verified",
            "landed",
        }
    return False


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
