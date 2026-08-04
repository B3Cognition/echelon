"""Live, non-mutating audit of canonical published source topology."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess
from typing import Literal

from echelon.topology_model import TopologySource
from echelon.topology_provider import PublishedTopology, TopologyNodeResolutionError
from echelon.topology_registry import (
    TopologyIndex,
    TopologyRegistryError,
    TopologySourceRecord,
    load_published_topology_from_index,
    load_topology_index,
)
from harness.re_fingerprint import fingerprint_source, resolve_re_fingerprint_profile


AuditStatus = Literal["current", "degraded", "stale", "invalid"]


@dataclass(frozen=True, slots=True)
class TopologyAuditFinding:
    """One concise deterministic topology audit observation."""

    status: AuditStatus
    message: str
    source_id: str | None = None
    provider: str | None = None
    path: str | None = None


@dataclass(frozen=True, slots=True)
class TopologyAuditSource:
    """Audit result for one selected configured source."""

    source_id: str
    status: AuditStatus
    providers: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TopologyAuditSnapshotSource:
    """Publication identity for one source validated by an audit."""

    source_id: str
    source_path: str
    source_fingerprint: str
    receipt_sha256: str


@dataclass(frozen=True, slots=True)
class TopologyAuditSnapshot:
    """Canonical publication identity observed during one bounded audit."""

    generation: int
    sources: tuple[TopologyAuditSnapshotSource, ...]


@dataclass(frozen=True, slots=True)
class TopologyAuditReport:
    """Immutable audit report whose exit policy is safe for the later CLI."""

    status: AuditStatus
    exit_code: int
    sources: tuple[TopologyAuditSource, ...]
    findings: tuple[TopologyAuditFinding, ...]
    snapshot: TopologyAuditSnapshot | None = None


def audit_topology(project_root: Path, source_id: str | None = None) -> TopologyAuditReport:
    """Audit one coherent publication capture, then live source freshness."""
    root = Path(project_root).resolve()
    try:
        index = load_topology_index(root)
        if index is None:
            return _invalid("topology index is missing")
        selected = _select(index, source_id)
        snapshot = snapshot_topology_index(index, source_id)
        topology = load_published_topology_from_index(
            root, index, (source.source_id for source in selected)
        )
        _assert_topology_matches_snapshot(topology, snapshot)
        confirmed_index = load_topology_index(root)
        if (
            confirmed_index is None
            or snapshot_topology_index(confirmed_index, source_id) != snapshot
        ):
            raise TopologyRegistryError("topology publication changed during audit")
    except TopologyRegistryError as exc:
        return _invalid(str(exc), source_id=source_id)

    try:
        profile = resolve_re_fingerprint_profile(root)
    except (OSError, ValueError) as exc:
        return _invalid(f"cannot resolve RE fingerprint profile: {exc}", source_id=source_id)
    results: list[TopologyAuditSource] = []
    findings: list[TopologyAuditFinding] = []
    for source in selected:
        status, source_findings = _audit_source(root, source, profile)
        results.append(
            TopologyAuditSource(
                source_id=source.source_id,
                status=status,
                providers=tuple(source.providers),
            )
        )
        findings.extend(source_findings)
    overall = _overall_status(result.status for result in results)
    return TopologyAuditReport(
        status=overall,
        exit_code=0 if overall == "current" else 2 if overall == "invalid" else 1,
        sources=tuple(sorted(results, key=lambda result: result.source_id)),
        findings=tuple(sorted(findings, key=_finding_key)),
        snapshot=snapshot,
    )


def snapshot_topology_index(
    index: TopologyIndex, source_id: str | None = None
) -> TopologyAuditSnapshot:
    """Return the bounded publication identity used to validate one read."""
    selected = _select(index, source_id)
    return TopologyAuditSnapshot(
        generation=index.generation,
        sources=tuple(
            TopologyAuditSnapshotSource(
                source_id=source.source_id,
                source_path=source.source_path,
                source_fingerprint=source.source_fingerprint.value,
                receipt_sha256=source.receipt.sha256,
            )
            for source in selected
        ),
    )


def _assert_topology_matches_snapshot(
    topology: PublishedTopology, snapshot: TopologyAuditSnapshot
) -> None:
    source_ids = tuple(
        sorted(
            node.source_id
            for node in topology.nodes_by_id.values()
            if isinstance(node, TopologySource)
        )
    )
    expected_ids = tuple(source.source_id for source in snapshot.sources)
    if topology.generation != snapshot.generation or source_ids != expected_ids:
        raise TopologyRegistryError("topology publication changed during audit")
    try:
        for source in snapshot.sources:
            receipt = topology.receipt(source.source_id)
            if receipt.source_fingerprint != source.source_fingerprint:
                raise TopologyRegistryError(
                    "topology publication changed during audit"
                )
            if any(
                value != source.receipt_sha256
                for value in receipt.provider_receipt_hashes.values()
            ):
                raise TopologyRegistryError(
                    "topology publication changed during audit"
                )
    except TopologyNodeResolutionError as exc:
        raise TopologyRegistryError(
            "topology publication changed during audit"
        ) from exc


def _audit_source(root: Path, source: TopologySourceRecord, profile: object) -> tuple[AuditStatus, list[TopologyAuditFinding]]:
    source_path = root / source.source_path
    if not source_path.is_dir():
        return "invalid", [
            TopologyAuditFinding(
                "invalid", "configured source is unavailable", source.source_id, path=source.source_path
            )
        ]
    try:
        live = fingerprint_source(source_path, profile)  # type: ignore[arg-type]
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        return "invalid", [TopologyAuditFinding("invalid", f"cannot fingerprint source: {exc}", source.source_id, path=source.source_path)]
    findings: list[TopologyAuditFinding] = []
    stale = False
    if live.dirty:
        stale = True
        findings.append(TopologyAuditFinding("stale", "live source is dirty", source.source_id, path=source.source_path))
    if live != source.source_fingerprint:
        stale = True
        findings.append(TopologyAuditFinding("stale", "live source fingerprint differs from published snapshot", source.source_id, path=source.source_path))
    degraded = [
        provider
        for provider, receipt in source.providers.items()
        if receipt.status == "degraded" or not receipt.complete
    ]
    for provider in degraded:
        findings.append(TopologyAuditFinding("degraded", "provider evidence is degraded or incomplete", source.source_id, provider))
    if stale:
        return "stale", findings
    if degraded:
        return "degraded", findings
    return "current", findings


def _select(index: TopologyIndex, source_id: str | None) -> tuple[TopologySourceRecord, ...]:
    if source_id is None:
        return tuple(index.sources.values())
    if source_id not in index.sources:
        raise TopologyRegistryError(f"unknown topology source: {source_id}")
    return (index.sources[source_id],)


def _invalid(message: str, *, source_id: str | None = None) -> TopologyAuditReport:
    return TopologyAuditReport(
        status="invalid",
        exit_code=2,
        sources=(),
        findings=(TopologyAuditFinding("invalid", message, source_id),),
    )


def _overall_status(statuses: object) -> AuditStatus:
    values = tuple(statuses)
    if any(value == "invalid" for value in values):
        return "invalid"
    if any(value == "stale" for value in values):
        return "stale"
    if any(value == "degraded" for value in values):
        return "degraded"
    return "current"


def _finding_key(finding: TopologyAuditFinding) -> tuple[str, str, str, str, str]:
    return (
        finding.source_id or "",
        finding.provider or "",
        finding.path or "",
        finding.status,
        finding.message,
    )
