"""Deterministic spec-scoped artifact graph."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from importlib.metadata import PackageNotFoundError, version
import json
from pathlib import Path
from typing import Any, Mapping

from echelon import artifact_index
from echelon.mempalace_requirements import (
    SUPPORTING_MEMORY_ARTIFACTS,
    resolve_spec_dir,
)
from harness.canonical_requirements import (
    _category_for,
    extract_canonical_requirements,
)
from harness.deferred_scope import read_ledger
from harness.task_progress import summarize_task_progress
from harness.verified_fulfillment_ledger import (
    UNRESOLVED_STATUSES,
    read_verified_ledger,
)
from kernel.task_contract import parse_task_rows, validate_tasks_markdown


GRAPH_SCHEMA_VERSION = 1
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
    path.write_bytes(render_spec_graph(graph))
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
                "source_path": _workspace_path(root, spec_dir / "spec.md"),
            },
        )
        edges.append(GraphEdge(spec_node_id, "HAS_REQUIREMENT", node_id, {}))

    _add_policy_artifacts(root, spec_dir, nodes, inputs)
    _add_tasks(root, spec_dir, requirement_ids, nodes, edges)
    _add_traceability(spec_dir, requirement_ids, nodes, edges)
    _add_deferrals(spec_dir, nodes, edges)
    _add_amendments(root, spec_dir, nodes, edges, inputs)
    _add_verified_ledger(root, spec_dir, requirement_ids, nodes, edges, inputs)

    return SpecArtifactGraph(
        spec_id=spec_id,
        generator_version=_generator_version(),
        inputs=tuple(inputs.values()),
        nodes=tuple(nodes.values()),
        edges=tuple(edges),
        memory_receipts=(),
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
        unresolved = sorted(set(task.requirements) - requirement_ids - {"UNMAPPED"})
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
            edges.append(
                GraphEdge(
                    f"req:{spec_dir.name}:{requirement_id}",
                    "DERIVED_FROM",
                    target,
                    {"input_unit_id": input_unit_id},
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
