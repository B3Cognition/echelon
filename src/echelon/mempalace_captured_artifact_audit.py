"""Inactive native artifact audits over caller-selected captured source values.

Neither a supplied tree/catalog nor a coherent storage observation authenticates
physical provenance, catalog association, configuration, or publication authority.
"""

from __future__ import annotations

import hashlib
from pathlib import Path, PurePosixPath

from echelon import mempalace_re as re_memory, mempalace_spec_evidence as evidence
from echelon.mempalace_captured_audit import _acquire_captured_rows, _capture_logical_sources
from echelon.mempalace_memory_audit import (
    _CollectionRows, _classify_artifact_extras, _classify_artifact_memory,
    _collection_from_adapter, _plan_expected_rows, _report,
)
from echelon.mempalace_requirements import SpecMemoryError
from echelon.spec_graph_re import GraphReArtifact, _validate_artifact
from harness.re_artifacts import ReArtifactDescriptor
from harness.spec_frontmatter import _parse_frontmatter_text
from harness.squad_source_manifest import snapshot_source_manifest
from harness.squad_source_snapshot import ProjectTreeSnapshot


def _validate_options(project_root: Path, maximum_scan_rows: int) -> None:
    if (not isinstance(project_root, Path) or not project_root.is_absolute()
            or type(maximum_scan_rows) is not int or maximum_scan_rows <= 0):
        raise ValueError


def _capture_evidence(project_root, spec_id, tree, maximum_scan_rows, allow_unlanded):
    try:
        _validate_options(project_root, maximum_scan_rows)
        if type(allow_unlanded) is not bool:
            raise ValueError
        main, _, images = _capture_logical_sources(
            project_root, spec_id, tree, maximum_scan_rows, False,
        )
        # Match Path.read_text's universal newlines only for YAML status parsing.
        text = main.content.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
        if not allow_unlanded and str(_parse_frontmatter_text(text).get("status") or "").strip().lower() != "landed":
            raise ValueError
        logical_root = PurePosixPath("specs") / spec_id
        selected = {logical_root / name for name in evidence.CANONICAL_SPEC_EVIDENCE_ARTIFACTS}
        selected.update(logical_root / evidence.PUBLISHED_EVIDENCE_DIR / name for name in (
            *evidence.PUBLISHED_VERIFY_EVIDENCE_ARTIFACTS, "manifest.json",
        ))
        return [evidence._evidence_artifact_snapshot(
            spec_id=spec_id, spec_dir=main.spec_dir, artifact=project_root / path,
            content=images[path.as_posix()], source=path.as_posix(),
            digest="sha256:" + hashlib.sha256(images[path.as_posix()]).hexdigest(),
        ) for path in sorted(selected) if path.as_posix() in images]
    except Exception:
        pass
    raise SpecMemoryError("invalid captured artifact memory input") from None


def _capture_re(project_root, tree, descriptors, maximum_scan_rows):
    try:
        _validate_options(project_root, maximum_scan_rows)
        snapshot_source_manifest(trees=(tree,), files=())
        if tree.path != "re" or not tree.exists:
            raise ValueError
        images = {item.path: item.content for item in tree.files}
        re_root = project_root / "re"
        snapshots = []
        if descriptors is None:
            if "re/index.json" in images or any(d.path == "re/index.json" for d in tree.directories):
                raise ValueError
            for path in sorted(map(PurePosixPath, images)):
                relative = path.relative_to("re")
                if not re_memory._is_curated_re_artifact(relative):
                    continue
                kind, room = re_memory._re_artifact_classification(relative)
                content = images[path.as_posix()]
                snapshots.append(re_memory._re_artifact_snapshot(
                    re_root=re_root, artifact=project_root / path, content=content,
                    source=path.as_posix(), digest="sha256:" + hashlib.sha256(content).hexdigest(),
                    artifact_kind=kind, room=room,
                ))
        else:
            if type(descriptors) is not tuple or not descriptors or "re/index.json" not in images:
                raise ValueError
            for descriptor in descriptors:
                if type(descriptor) is not ReArtifactDescriptor:
                    raise ValueError
                _validate_artifact(GraphReArtifact(descriptor, images[descriptor.path]))
            paths = [descriptor.path for descriptor in descriptors]
            if paths != sorted(set(paths)):
                raise ValueError
            for descriptor in descriptors:
                room = re_memory.RE_ARTIFACT_ROOMS.get((descriptor.kind, descriptor.scope))
                if descriptor.kind not in re_memory.MINED_RE_ARTIFACT_KINDS or room is None:
                    continue
                snapshots.append(re_memory._re_artifact_snapshot(
                    re_root=re_root, artifact=project_root / descriptor.path,
                    content=images[descriptor.path], source=descriptor.path,
                    digest=descriptor.sha256, artifact_kind=descriptor.kind, room=room,
                    descriptor=descriptor,
                ))
        if not snapshots:
            raise ValueError
        return snapshots
    except Exception:
        pass
    raise SpecMemoryError("invalid captured artifact memory input") from None


def _audit_captured_artifacts(
    project_root, *, snapshots, maximum_scan_rows, root, label, factory,
    planner_name, artifact_kind, scope, spec_id=None,
):
    adapter = None
    try:
        adapter = factory(project_root, run_id="audit")
    except (Exception, SystemExit) as exc:
        return _report(label=label, root=root, adapter=None, status="unavailable",
                       artifact_count=len(snapshots), expected_count=0, errors=[type(exc).__name__])
    try:
        expected_rows = _plan_expected_rows(snapshots=snapshots, adapter=adapter, planner_name=planner_name)
    except (Exception, SystemExit) as exc:
        return _report(label=label, root=root, adapter=adapter, status="fail",
                       artifact_count=len(snapshots), expected_count=0, errors=[type(exc).__name__])
    try:
        parsed, wing_rows = _acquire_captured_rows(
            _collection_from_adapter(adapter), expected=[row.drawer_id for row in expected_rows],
            wing=adapter.wing, maximum_scan_rows=maximum_scan_rows,
        )
    except (Exception, SystemExit) as exc:
        return _report(label=label, root=root, adapter=adapter, status="unavailable",
                       artifact_count=len(snapshots), expected_count=len(expected_rows), errors=[type(exc).__name__])
    kinds = {snapshot.source: snapshot.artifact_metadata["artifact_kind"] for snapshot in snapshots}
    return _classify_artifact_memory(
        label=label, root=root, snapshots=snapshots, adapter=adapter,
        artifact_kind=artifact_kind, artifact_kinds_by_source=kinds, scope=scope, spec_id=spec_id,
        expected_rows=expected_rows, parsed=_CollectionRows(parsed.rows, parsed.malformed),
        scan_extras=lambda: _classify_artifact_extras(
            _CollectionRows(wing_rows, {}), expected_rows=expected_rows,
            artifact_kinds={artifact_kind} | set(kinds.values()), spec_id=spec_id,
        ),
    )


def audit_captured_spec_evidence_memory(
    project_root: Path, *, spec_id: str, tree: ProjectTreeSnapshot,
    maximum_scan_rows: int, allow_unlanded: bool = False,
) -> evidence.SpecEvidenceMemoryAuditReport:
    """Audit native selected evidence bytes; landed status is required by default."""
    snapshots = _capture_evidence(project_root, spec_id, tree, maximum_scan_rows, allow_unlanded)
    generic = _audit_captured_artifacts(
        project_root, snapshots=snapshots, maximum_scan_rows=maximum_scan_rows,
        root=project_root / "specs" / spec_id, label="Spec Evidence",
        factory=evidence.create_spec_evidence_memory_adapter,
        planner_name="plan_spec_evidence_artifact_rows", artifact_kind="spec-evidence",
        scope="spec-evidence", spec_id=spec_id,
    )
    return evidence._evidence_audit_report(generic, spec_id=spec_id)


def audit_captured_re_memory(
    project_root: Path, *, tree: ProjectTreeSnapshot,
    descriptors: tuple[ReArtifactDescriptor, ...] | None, maximum_scan_rows: int,
) -> re_memory.ReMemoryAuditReport:
    """Audit an explicit supplied catalog, or legacy curated sources when None."""
    snapshots = _capture_re(project_root, tree, descriptors, maximum_scan_rows)
    return re_memory._re_audit_report(_audit_captured_artifacts(
        project_root, snapshots=snapshots, maximum_scan_rows=maximum_scan_rows,
        root=project_root / "re", label="RE", factory=re_memory.create_re_memory_adapter,
        planner_name="plan_re_artifact_rows", artifact_kind="reverse-engineering",
        scope="reverse-engineering",
    ))
