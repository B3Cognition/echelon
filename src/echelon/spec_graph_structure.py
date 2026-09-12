"""Deterministic spec-local structure from an explicitly supplied spec tree.

This fragment makes no external-domain observations and is not a complete graph.
The Path graph owner shares these transformations after its existing reads.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import json
from pathlib import PurePath, PurePosixPath
import unicodedata

from echelon import artifact_index
from echelon.mempalace_requirements import SUPPORTING_MEMORY_ARTIFACTS
from echelon.spec_graph import (
    GraphEdge, GraphInput, GraphNode, SpecGraphError, _input_role, _scope_node_id,
)
from harness.canonical_requirements import (
    CanonicalRequirement, _category_for, extract_canonical_requirements_from_texts,
)
from harness.deferred_scope import DeferredScopeLedger, parse_deferred_scope_ledger
from harness.squad_source_manifest import snapshot_source_manifest
from harness.squad_source_snapshot import ProjectTreeSnapshot
from harness.task_progress import summarize_task_progress
from harness.verified_fulfillment_ledger import (
    UNRESOLVED_STATUSES, VerifiedFulfillmentLedger, parse_verified_ledger,
)
from kernel.task_contract import parse_task_rows, validate_tasks_markdown


@dataclass(frozen=True, slots=True)
class SpecGraphStructure:
    spec_id: str
    inputs: tuple[GraphInput, ...]
    nodes: tuple[GraphNode, ...]
    edges: tuple[GraphEdge, ...]


AMENDMENT_CONTROL_PATHS = (
    "change-request.md", "impact.md", "inputs/manifest.json",
    "inputs/catalog.json", "inputs/traceability.json",
)


def _local_artifact_paths() -> tuple[str, ...]:
    return tuple(definition.path for definition in artifact_index.artifact_definitions()) + (
        "inputs/manifest.json", "inputs/catalog.json", "inputs/traceability.json",
    )


def _add_spec(
    spec_id: str, path: str, lifecycle: str, nodes: dict[str, GraphNode],
) -> None:
    node_id = f"spec:{spec_id}"
    nodes[node_id] = GraphNode(
        node_id, "Spec", {"spec_id": spec_id, "path": path, "lifecycle": lifecycle},
    )


def _add_requirements(
    spec_id: str, source_path: str, rows: list[CanonicalRequirement],
    nodes: dict[str, GraphNode], edges: list[GraphEdge],
) -> set[str]:
    canonical_requirements = [row for row in rows if row.source_kind == "spec"]
    for row in canonical_requirements:
        node_id = f"req:{spec_id}:{row.id}"
        nodes[node_id] = GraphNode(
            node_id, "Requirement",
            {
                "requirement_id": row.id,
                "category": _category_for(row.id),
                "source_line": row.source_line,
                "source_path": source_path,
                "source_text": row.source_text,
            },
        )
        edges.append(GraphEdge(f"spec:{spec_id}", "HAS_REQUIREMENT", node_id, {}))
    return {row.id for row in canonical_requirements}


def _add_artifact_record(
    spec_id: str, workspace_path: str, filename: str, digest: str,
    role: str, required: bool,
    nodes: dict[str, GraphNode], inputs: dict[str, GraphInput],
) -> str:
    node_id = f"artifact:{spec_id}:{workspace_path}"
    nodes[node_id] = GraphNode(
        node_id, "Artifact",
        {
            "path": workspace_path, "role": role, "hash": digest,
            "mining_status": (
                "mined"
                if filename in SUPPORTING_MEMORY_ARTIFACTS
                or role in {"requirements-source", "verification-evidence"}
                else "not-mined-by-policy"
            ),
        },
    )
    inputs[workspace_path] = GraphInput(
        path=workspace_path, hash=digest, role=_input_role(role),
        required=required,
    )
    return node_id


def _add_task_text(
    spec_id: str, markdown: str, requirement_ids: set[str],
    nodes: dict[str, GraphNode], edges: list[GraphEdge],
) -> None:
    validation = validate_tasks_markdown(markdown)
    if not validation.valid:
        raise SpecGraphError("invalid tasks.md: " + "; ".join(validation.errors))
    progress = summarize_task_progress(markdown)
    if not progress.valid:
        raise SpecGraphError("invalid task progress: " + "; ".join(progress.errors))
    for task in parse_task_rows(markdown):
        node_id = f"task:{spec_id}:{task.task_id}"
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
                    f"req:{spec_id}:{requirement_id}",
                    {},
                )
            )


def _add_traceability_payload(
    spec_id: str, payload: dict[str, object], requirement_ids: set[str],
    nodes: dict[str, GraphNode], edges: list[GraphEdge],
) -> None:
    target = f"artifact:{spec_id}:specs/{spec_id}/inputs/catalog.json"
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
                f"req:{spec_id}:{requirement_id}",
                "DERIVED_FROM",
                target,
                {"input_unit_ids": sorted(input_unit_ids)},
            )
        )


def _add_deferral_records(
    spec_id: str, ledger: DeferredScopeLedger,
    nodes: dict[str, GraphNode], edges: list[GraphEdge],
) -> None:
    for entry in ledger.entries:
        node_id = f"deferral:{spec_id}:{entry.entry_id}"
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
            source = _scope_node_id(spec_id, selected_id)
            if source in nodes:
                edges.append(GraphEdge(source, "DEFERRED_BY", node_id, {}))
        for task_id in entry.derived_task_ids:
            source = f"task:{spec_id}:{task_id}"
            if source in nodes:
                edges.append(GraphEdge(source, "DEFERRED_BY", node_id, {}))


def _add_amendment_record(
    spec_id: str, revision: str, path: str,
    nodes: dict[str, GraphNode], edges: list[GraphEdge],
) -> None:
    node_id = f"amendment:{spec_id}:{revision}"
    nodes[node_id] = GraphNode(
        node_id, "Amendment",
        {"revision": revision, "path": path, "status": "promoted"},
    )
    edges.append(GraphEdge(f"spec:{spec_id}", "AMENDED_BY", node_id, {}))


def _add_verified_records(
    spec_id: str, ledger: VerifiedFulfillmentLedger, target: str,
    requirement_ids: set[str], edges: list[GraphEdge],
) -> None:
    for row in ledger.rows:
        if row.requirement_id not in requirement_ids:
            continue
        edges.append(
            GraphEdge(
                f"req:{spec_id}:{row.requirement_id}",
                "VERIFIED_BY",
                target,
                {
                    "verification_status": row.status,
                    "evidence_refs": list(row.evidence_refs),
                    "verified_commit": row.verified_commit,
                    "verify_scope": row.verify_scope,
                    "selected_evidence": list(row.selected_evidence),
                    "receipt_refs": [dict(ref) for ref in row.receipt_refs],
                    "candidate_content_fingerprint": (
                        row.candidate_content_fingerprint
                    ),
                    "requirement_set_fingerprint": row.requirement_set_fingerprint,
                    "contract_hash": row.contract_hash,
                    "complete": row.status not in UNRESOLVED_STATUSES,
                },
            )
        )


def _artifact_role(spec_dir: PurePath, path: PurePath) -> str:
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


def _artifact_required(spec_dir: PurePath, path: PurePath, lifecycle: str) -> bool:
    if path.name == "spec.md" and path.parent == spec_dir:
        return True
    return path.name == "tasks.md" and path.parent == spec_dir and lifecycle in {
        "build", "verified", "landed",
    }


def _captured_text(files: dict[str, bytes], name: str, *, errors: str = "strict") -> str | None:
    if name not in files:
        return None
    # Match the Path adapters' universal-newline text decoding.
    return files[name].decode("utf-8", errors=errors).replace("\r\n", "\n").replace("\r", "\n")


def build_spec_graph_structure(
    *, spec_id: str, tree: ProjectTreeSnapshot, lifecycle: str,
) -> SpecGraphStructure:
    """Build detached local records; supplied lifecycle is only an observation."""
    try:
        return _build_spec_graph_structure(spec_id=spec_id, tree=tree, lifecycle=lifecycle)
    except Exception:
        # Leave the handler before raising: parser exceptions can retain JSON/source
        # documents even with "from None". Never expose them as context or cause.
        pass
    raise SpecGraphError("invalid captured spec graph structure")


def _build_spec_graph_structure(
    *, spec_id: str, tree: ProjectTreeSnapshot, lifecycle: str,
) -> SpecGraphStructure:
    if (
        type(spec_id) is not str or not spec_id or spec_id != spec_id.strip()
        or spec_id in {".", ".."} or "/" in spec_id or "\\" in spec_id
        or any(unicodedata.category(character) == "Cc" for character in spec_id)
    ):
        raise ValueError("invalid spec component")
    spec_id.encode("utf-8")
    if type(lifecycle) is not str or lifecycle not in {"phase_a", "build", "verified", "landed"}:
        raise ValueError("invalid lifecycle")
    snapshot_source_manifest(trees=(tree,), files=())

    root_parts = PurePosixPath(tree.path).parts
    files = {
        PurePosixPath(*PurePosixPath(item.path).parts[len(root_parts):]).as_posix(): item.content
        for item in tree.files
    }
    directories = {
        PurePosixPath(*PurePosixPath(item.path).parts[len(root_parts):]).as_posix()
        for item in tree.directories
    }
    spec_path = PurePosixPath("specs", spec_id)
    nodes: dict[str, GraphNode] = {}
    edges: list[GraphEdge] = []
    inputs: dict[str, GraphInput] = {}
    _add_spec(spec_id, spec_path.as_posix(), lifecycle, nodes)
    rows = extract_canonical_requirements_from_texts(
        spec_text=_captured_text(files, "spec.md", errors="replace"),
        plan_text=_captured_text(files, "plan.md", errors="replace"),
        coverage_text=_captured_text(files, "coverage-map.md", errors="replace"),
        tasks_text=_captured_text(files, "tasks.md", errors="replace"),
    )
    requirement_ids = _add_requirements(
        spec_id, (spec_path / "spec.md").as_posix(), rows, nodes, edges,
    )
    # Hashes were checked against bytes by the manifest factory above.
    hashes = {
        PurePosixPath(*PurePosixPath(item.path).parts[len(root_parts):]).as_posix():
        f"sha256:{item.image.sha256}" for item in tree.files
    }
    for relative in sorted(set(_local_artifact_paths()).intersection(files)):
        path = spec_path / relative
        _add_artifact_record(
            spec_id, path.as_posix(), path.name, hashes[relative],
            _artifact_role(spec_path, path),
            _artifact_required(spec_path, path, lifecycle), nodes, inputs,
        )
    tasks = _captured_text(files, "tasks.md")
    if tasks is not None:
        _add_task_text(spec_id, tasks, requirement_ids, nodes, edges)
    if "inputs/traceability.json" in files and "inputs/catalog.json" in files:
        payload = json.loads(_captured_text(files, "inputs/traceability.json"))
        if not isinstance(payload, dict):
            raise SpecGraphError("invalid product input traceability")
        _add_traceability_payload(spec_id, payload, requirement_ids, nodes, edges)
    deferred = _captured_text(files, "deferred-scope.json")
    if deferred is not None:
        _add_deferral_records(spec_id, parse_deferred_scope_ledger(deferred), nodes, edges)
    elif "deferred-scope.json" in directories:
        # read_ledger uses exists(), so a directory is an invalid present ledger.
        raise SpecGraphError("invalid deferred-scope ledger")
    for relative in sorted(directories):
        path = PurePosixPath(relative)
        if len(path.parts) != 2 or path.parts[0] != "amendments" or not path.name.isdigit():
            continue
        _add_amendment_record(spec_id, path.name, (spec_path / path).as_posix(), nodes, edges)
        for control in AMENDMENT_CONTROL_PATHS:
            name = (path / control).as_posix()
            if name in files:
                artifact = spec_path / name
                _add_artifact_record(
                    spec_id, artifact.as_posix(), artifact.name, hashes[name],
                    "amendment-control", False, nodes, inputs,
                )
    verified = _captured_text(files, "verified-fulfillment-ledger.json")
    if verified is not None:
        name = "verified-fulfillment-ledger.json"
        target = _add_artifact_record(
            spec_id, (spec_path / name).as_posix(), name, hashes[name],
            "verification-evidence", False, nodes, inputs,
        )
        _add_verified_records(
            spec_id, parse_verified_ledger(verified), target, requirement_ids, edges,
        )
    return SpecGraphStructure(
        spec_id, tuple(inputs.values()), deepcopy(tuple(nodes.values())),
        deepcopy(tuple(edges)),
    )
