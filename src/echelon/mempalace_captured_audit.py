"""Opt-in native memory audit from one complete, explicitly selected source tree.

The read interval and captured image confer no source/configuration provenance,
storage lease, identity authority, or permission to publish.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
from pathlib import Path, PurePosixPath
from typing import Any

from echelon.context_reconciliation import reconcile_captured_drawers
from echelon.mempalace_audit import (
    SpecMemoryAuditReport, _ParsedCollectionRows, _as_collection_rows,
    _classify_spec_extras, _classify_spec_memory_audit, _collection_from_adapter,
    _failure_report, _plan_expected_spec_memory_rows, _unavailable_report,
    scan_wing_rows_complete,
)
from echelon.mempalace_requirements import (
    SUPPORTING_MEMORY_ARTIFACTS, CanonicalSpecSnapshot, SpecMemoryError,
    _canonical_artifact_snapshot, create_requirement_memory_adapter,
)
from echelon.spec_graph_structure import _validate_scope
from harness.squad_source_manifest import snapshot_source_manifest
from harness.squad_source_snapshot import ProjectTreeSnapshot


def _capture_logical_sources(
    project_root: Path, spec_id: str, tree: ProjectTreeSnapshot,
    maximum_scan_rows: int, probe_retrieval: bool,
) -> tuple[CanonicalSpecSnapshot, tuple[CanonicalSpecSnapshot, ...], dict[str, bytes]]:
    try:
        if (
            not isinstance(project_root, Path) or not project_root.is_absolute()
            or type(maximum_scan_rows) is not int or maximum_scan_rows <= 0
            or type(probe_retrieval) is not bool
        ):
            raise ValueError
        logical_root = _validate_scope(spec_id, "phase_a")
        # Validate the full original selection, including entries ignored by mining.
        snapshot_source_manifest(trees=(tree,), files=())
        physical_root = PurePosixPath(tree.path)
        images = {
            (logical_root / PurePosixPath(item.path).relative_to(physical_root)).as_posix(): item.content
            for item in tree.files
        }
        if not tree.exists or (logical_root / "spec.md").as_posix() not in images:
            raise ValueError

        def snapshot(filename: str, *, supporting: bool) -> CanonicalSpecSnapshot:
            content = images[(logical_root / filename).as_posix()]
            return _canonical_artifact_snapshot(
                spec_id=spec_id, spec_dir=project_root / logical_root,
                filename=filename, content=content,
                digest="sha256:" + hashlib.sha256(content).hexdigest(), supporting=supporting,
            )

        main = snapshot("spec.md", supporting=False)
        supports = tuple(
            snapshot(filename, supporting=True)
            for filename in sorted(SUPPORTING_MEMORY_ARTIFACTS)
            if (logical_root / filename).as_posix() in images
        )
        return main, supports, images
    except Exception:
        pass
    # Outside the handler: do not retain source-bearing cause/context/tracebacks.
    raise SpecMemoryError("invalid captured spec memory input") from None


class _DetachedReadOnlyCollection:
    """Detach each response before any later get can mutate backend-owned data."""

    def __init__(self, collection: object) -> None:
        self._collection = collection

    def get(self, **kwargs: Any) -> object:
        return deepcopy(self._collection.get(**kwargs))  # type: ignore[attr-defined]


def audit_captured_spec_memory(
    project_root: Path,
    *,
    spec_id: str,
    tree: ProjectTreeSnapshot,
    maximum_scan_rows: int,
    probe_retrieval: bool = False,
) -> SpecMemoryAuditReport:
    """Acquire coherent bounded read-only storage observations for captured bytes."""
    snapshot, supports, images = _capture_logical_sources(
        project_root, spec_id, tree, maximum_scan_rows, probe_retrieval,
    )
    try:
        adapter = create_requirement_memory_adapter(project_root, run_id="audit")
    except (Exception, SystemExit) as exc:
        return _unavailable_report(snapshot=snapshot, adapter=None, expected=[], error=exc)
    try:
        expected_rows = _plan_expected_spec_memory_rows(
            project_root=project_root, spec_dir=snapshot.spec_dir, snapshot=snapshot,
            adapter=adapter, supplied_supports=supports,
        )
    except (Exception, SystemExit) as exc:
        return _failure_report(snapshot=snapshot, adapter=adapter, error=exc)
    expected = [row.drawer_id for row in expected_rows]
    try:
        collection = _DetachedReadOnlyCollection(_collection_from_adapter(adapter))
        raw = (
            collection.get(ids=expected, include=["documents", "metadatas"])
            if expected else {"ids": [], "documents": [], "metadatas": []}
        )
        parsed = _as_collection_rows(raw)
        expected_ids = set(expected)
        if (set(parsed.rows) | set(parsed.malformed)) - expected_ids:
            raise SpecMemoryError("unexpected expected-fetch drawer IDs")
        wing_rows = scan_wing_rows_complete(
            collection, wing=adapter.wing, maximum_rows=maximum_scan_rows,
        )
        expected_in_wing = {
            key: row for key, row in parsed.rows.items() if row[1].get("wing") == adapter.wing
        }
        scanned_expected = {key: row for key, row in wing_rows.items() if key in expected_ids}
        if expected_in_wing != scanned_expected:
            raise SpecMemoryError("expected drawer cohort changed during observation")
    except (Exception, SystemExit) as exc:
        return _unavailable_report(snapshot=snapshot, adapter=adapter, expected=expected, error=exc)
    return _classify_spec_memory_audit(
        snapshot=snapshot, adapter=adapter, expected_rows=expected_rows, parsed=parsed,
        probe_retrieval=probe_retrieval,
        reconcile=lambda drawers: reconcile_captured_drawers(drawers, images),
        scan_extras=lambda: _classify_spec_extras(
            _ParsedCollectionRows(wing_rows, {}), snapshot=snapshot, expected_rows=expected_rows,
        ),
    )
