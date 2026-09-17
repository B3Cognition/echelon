"""Deterministic preparation for an explicitly bound, caller-owned verify run.

The controlled delivery runner composes this callable with semantic inspection.
Preparation itself neither dispatches roles nor publishes or completes a run.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path

from echelon.workspace_model import discover_workspace
from harness.canonical_requirements import REQ_ID_RE
from harness.codegraph_evidence import CodeGraphEvidenceError
from harness.perlgraph_evidence import PerlGraphEvidenceError
from harness.fulfillment_preparation_steps import (
    load_preparation_observation, prepare_canonical_requirements, prepare_codegraph,
    prepare_coverage, prepare_evidence_map, prepare_perlgraph,
    prepare_product_inventory, prepare_requirement_audit,
)
from harness.topology_evidence import (
    _validate_harness_managed_worktree, write_topology_evidence_receipt,
)
from kernel.spec_identity import spec_identity_aliases


@dataclass(frozen=True)
class FulfillmentPreparationContext:
    project_root: Path
    workspace_root: Path
    source_id: str
    source_root: Path
    spec_id: str
    spec_dir: Path
    verify_run_dir: Path
    scope: str = "full"
    scoped_ids: tuple[str, ...] = ()
    base_full_verify_commit: str = ""
    observer_required: bool = False
    observation_path: Path | None = None


@dataclass(frozen=True)
class PreparedFulfillmentInputs:
    verify_run_dir: Path
    canonical_ids: tuple[str, ...]
    scoped_ids: tuple[str, ...]
    topology_status: str


class FulfillmentPreparationError(ValueError):
    """The explicit run cannot safely produce deterministic preparation inputs."""


_OUTPUTS = (
    "state.json", "codegraph-analysis.json", "codegraph-summary.json", "codegraph-error.txt",
    "perlgraph-analysis.json", "perlgraph-summary.json", "perlgraph-error.txt",
    "topology-receipt.json", "canonical-requirements.json", "canonical-requirements.md",
    "product-inventory.json", "product-inventory.md", "requirement-audit.md",
    "coverage-evidence.json", "coverage-evidence.md",
    "codegraph-evidence-map.json", "codegraph-evidence-map.md",
)
_SEMANTIC_INPUTS = (
    "implementation-map.md", "judgment-prepass.json", "fulfillment-report.fallback.md",
)


def _contained_path(path: Path, root: Path, label: str) -> None:
    # Check lexical components as well as resolved containment: resolving first
    # would erase a symlinked output directory, even one pointing inside the root.
    absolute = Path(os.path.abspath(path))
    anchor = Path(os.path.abspath(root))
    try:
        relative = absolute.relative_to(anchor)
        absolute.resolve(strict=True).relative_to(anchor.resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise FulfillmentPreparationError(f"{label} escapes its authorized root") from exc
    cursor = anchor
    for part in relative.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise FulfillmentPreparationError(f"{label} is symlinked: {cursor}")
    if not relative.parts or not absolute.is_dir():
        raise FulfillmentPreparationError(f"{label} must be a child directory")


def _regular_file(path: Path, *, required: bool = False) -> None:
    if path.is_symlink():
        raise FulfillmentPreparationError(f"symlinked preparation destination/input: {path.name}")
    if (required or path.exists()) and not path.is_file():
        raise FulfillmentPreparationError(f"regular file required: {path.name}")


def _validate_source_binding(context: FulfillmentPreparationContext) -> None:
    workspace = context.workspace_root.resolve(strict=True)
    source = _step("source root", context.source_root.resolve, strict=True)
    project = context.project_root.resolve(strict=True)
    if not all(path.is_dir() for path in (workspace, source, project)):
        raise FulfillmentPreparationError("workspace/source/project must be directories")
    _contained_path(context.verify_run_dir, context.workspace_root, "verify run")
    # Do not accept a runs symlink pointing outside the workspace as the root.
    context.verify_run_dir.resolve().relative_to(workspace / "runs")
    if context.verify_run_dir.resolve() == workspace / "runs":
        raise FulfillmentPreparationError("verify run must be below runs")
    _contained_path(context.spec_dir, context.workspace_root, "spec")
    matches = [item for item in discover_workspace(workspace).sources
               if item.id == context.source_id and (workspace / item.path).resolve() == source]
    if len(matches) != 1:
        raise FulfillmentPreparationError("source identity does not match the workspace manifest")
    if project != source:
        _validate_harness_managed_worktree(project, workspace)
    if not (set(spec_identity_aliases(context.spec_id)) &
            set(spec_identity_aliases(context.spec_dir.name))):
        raise FulfillmentPreparationError("spec identity does not match its directory")


def _validate_context(context: FulfillmentPreparationContext) -> dict[str, object]:
    _validate_source_binding(context)
    workspace = context.workspace_root.resolve(strict=True)
    project = context.project_root.resolve(strict=True)
    for name in _OUTPUTS:
        _regular_file(context.verify_run_dir / name, required=name == "state.json")
    for name in ("spec.md", "tasks.md", "plan.md", "coverage-map.md"):
        _regular_file(context.spec_dir / name, required=name in {"spec.md", "tasks.md"})
    _regular_file(context.verify_run_dir / "coverage-observation-context.json")
    for name in _SEMANTIC_INPUTS:
        path = context.verify_run_dir / name
        if path.exists() or path.is_symlink():
            raise FulfillmentPreparationError(f"prior semantic artifact requires recovery: {name}")
    if context.scope not in {"full", "scoped"}:
        raise FulfillmentPreparationError("unsupported verify scope")
    if context.scope == "full" and (context.scoped_ids or context.base_full_verify_commit):
        raise FulfillmentPreparationError("scoped IDs/base commit require scoped verification")
    if context.scope == "scoped" and not context.scoped_ids:
        raise FulfillmentPreparationError("scoped verification requires scoped IDs")
    if any(not isinstance(item, str) or not REQ_ID_RE.fullmatch(item) for item in context.scoped_ids):
        raise FulfillmentPreparationError("invalid scoped ID")
    if len(set(context.scoped_ids)) != len(context.scoped_ids):
        raise FulfillmentPreparationError("duplicate scoped IDs")
    try:
        state = json.loads((context.verify_run_dir / "state.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise FulfillmentPreparationError("verify state is unavailable or malformed") from exc
    if not isinstance(state, dict):
        raise FulfillmentPreparationError("verify state must be a JSON object")
    if state.get("status") != "in_progress":
        raise FulfillmentPreparationError("verify state must be in_progress")
    expected = {
        "spec_id": context.spec_id, "project_root": str(project),
        "orchestration_root": str(workspace), "spec_dir": str(context.spec_dir.resolve()),
        "verify_run_dir": str(context.verify_run_dir.resolve()), "verify_scope": context.scope,
        "scoped_ids": list(context.scoped_ids), "base_full_verify_commit": context.base_full_verify_commit,
    }
    for key, value in expected.items():
        if state.get(key) != value:
            raise FulfillmentPreparationError(f"verify run {key} binding mismatch")
    _step("coverage observation", load_preparation_observation,
        spec_dir=context.spec_dir, verify_run_dir=context.verify_run_dir,
        observer_required=context.observer_required, observation_path=context.observation_path)
    return state


def _canonical_ids(run: Path) -> tuple[str, ...]:
    payload = json.loads((run / "canonical-requirements.json").read_text(encoding="utf-8"))
    rows = payload.get("requirements") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        raise FulfillmentPreparationError("canonical inventory requirements must be a list")
    ids = []
    seen = set()
    for row in rows:
        item = row.get("id") if isinstance(row, dict) else None
        if not isinstance(item, str) or not REQ_ID_RE.fullmatch(item):
            raise FulfillmentPreparationError("invalid canonical inventory row")
        if item in seen:
            raise FulfillmentPreparationError(f"duplicate canonical ID: {item}")
        seen.add(item)
        ids.append(item)
    return tuple(ids)


def _step(name, operation, *args, **kwargs):
    try:
        return operation(*args, **kwargs)
    except Exception as exc:
        raise FulfillmentPreparationError(f"{name}: {exc}") from exc


def prepare_fulfillment_inputs(context: FulfillmentPreparationContext) -> PreparedFulfillmentInputs:
    _step("preparation admission", _validate_context, context)
    for name, write_graph, degraded_error in (
        ("codegraph", prepare_codegraph, CodeGraphEvidenceError),
        ("perlgraph", prepare_perlgraph, PerlGraphEvidenceError),
    ):
        try:
            write_graph(project_root=context.project_root, verify_run_dir=context.verify_run_dir,
                        spec_dir=context.spec_dir)
        except degraded_error:
            pass  # The step already persisted the existing typed degraded result.
        except Exception as exc:
            raise FulfillmentPreparationError(f"{name}: {exc}") from exc
    topology = _step("topology", write_topology_evidence_receipt,
                     context.project_root, context.verify_run_dir, context.spec_dir,
                     workspace_root=context.workspace_root, source_id=context.source_id,
                     source_root=context.source_root)
    _step("canonical requirements", prepare_canonical_requirements,
          spec_dir=context.spec_dir, verify_run_dir=context.verify_run_dir)
    canonical_ids = _step("canonical inventory", _canonical_ids, context.verify_run_dir)
    unknown = set(context.scoped_ids) - set(canonical_ids)
    if unknown:
        raise FulfillmentPreparationError(f"unknown scoped IDs: {', '.join(sorted(unknown))}")
    _step("product inventory", prepare_product_inventory,
          project_root=context.project_root, verify_run_dir=context.verify_run_dir)
    _step("requirement audit", prepare_requirement_audit, verify_run_dir=context.verify_run_dir)
    _step("coverage", prepare_coverage, spec_dir=context.spec_dir, verify_run_dir=context.verify_run_dir,
          observer_required=context.observer_required, observation_path=context.observation_path)
    coverage_map = context.spec_dir / "coverage-map.md"
    _step("evidence map", prepare_evidence_map,
          requirement_audit_path=context.verify_run_dir / "requirement-audit.md",
          codegraph_analysis_path=context.verify_run_dir / "codegraph-analysis.json",
          tasks_path=context.spec_dir / "tasks.md",
          out_json_path=context.verify_run_dir / "codegraph-evidence-map.json",
          out_md_path=context.verify_run_dir / "codegraph-evidence-map.md",
          coverage_map_path=coverage_map if coverage_map.is_file() else None)
    return PreparedFulfillmentInputs(context.verify_run_dir, canonical_ids,
                                     context.scoped_ids, topology.status)
