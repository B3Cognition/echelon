"""Disposable run-local projections of authenticated protocol-2.5 authority."""

from __future__ import annotations

from contextlib import contextmanager
import fcntl
import os
from pathlib import Path
import stat
from types import SimpleNamespace
from typing import Iterator

from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.protocol_22.materialization import (
    MaterializationReportV1,
    MaterializedProjectionV1,
    Protocol22MaterializationError,
    _ProjectionSpec,
    _fault,
    _open_directory_path_nofollow,
    _open_or_create_parents,
    _projection_state,
    _publish_projection,
    _quarantine_entry,
    _root_staging_state,
)
from harness.re_v2.protocol_22.schema import load_canonical_object

from .artifacts import AuditCandidateV1, SemanticResolutionOverlayV1
from .recovery import Protocol25RunContext, recover_protocol_25_run


class Protocol25MaterializationError(Protocol22MaterializationError):
    """Raised when an L3 projection cannot be safely rebuilt."""


def materialize_accepted_l3(
    context: Protocol25RunContext,
    fault_hook=None,  # type: ignore[no-untyped-def]
) -> MaterializationReportV1:
    """Verify or rebuild exact L3 views below ``runs/<run-id>/re/l3``."""
    if not isinstance(context, Protocol25RunContext):
        raise Protocol25MaterializationError(
            "L3 materialization requires Protocol25RunContext"
        )
    if fault_hook is not None and not callable(fault_hook):
        raise Protocol25MaterializationError(
            "materialization fault hook must be callable or null"
        )
    recovered = recover_protocol_25_run(context)
    specs = _projection_specs(context, recovered.ledger)
    reused = 0
    rebuilt = 0
    quarantined: list[Path] = []
    run_root = context.paths.root.parent
    fake_context = SimpleNamespace(paths=SimpleNamespace(root=run_root))
    with _l3_materialization_lock(run_root) as run_fd:
        for spec in specs:
            parent_fd = _open_or_create_parents(run_fd, spec.relative_parts[:-1])
            try:
                name = spec.relative_parts[-1]
                staging = f".{name}.staging"
                staging_state = _root_staging_state(
                    parent_fd,
                    name,
                    staging,
                    spec.payloads[0][1],
                )
                if staging_state == "altered":
                    quarantined.append(
                        _quarantine_entry(
                            fake_context,
                            run_fd,
                            parent_fd,
                            staging,
                            spec.projection.artifact_hash,
                        )
                    )
                    _fault(
                        fault_hook,
                        "materialization_quarantined:"
                        + spec.projection.artifact_hash,
                    )
                state = _projection_state(parent_fd, name, spec)
                if state == "exact":
                    reused += 1
                    continue
                if state == "altered":
                    quarantined.append(
                        _quarantine_entry(
                            fake_context,
                            run_fd,
                            parent_fd,
                            name,
                            spec.projection.artifact_hash,
                        )
                    )
                    _fault(
                        fault_hook,
                        "materialization_quarantined:"
                        + spec.projection.artifact_hash,
                    )
                _publish_projection(parent_fd, name, spec, fault_hook)
                rebuilt += 1
            finally:
                os.close(parent_fd)
        os.fsync(run_fd)
    return MaterializationReportV1(
        projections=tuple(item.projection for item in specs),
        reused_count=reused,
        rebuilt_count=rebuilt,
        quarantine_paths=tuple(quarantined),
    )


def _projection_specs(context: Protocol25RunContext, ledger) -> tuple[_ProjectionSpec, ...]:  # type: ignore[no-untyped-def]
    root = context.paths.root.parent / "re" / "l3"
    specs: list[_ProjectionSpec] = []

    def add(
        path: Path,
        payload: bytes,
        *,
        kind: str,
        authority_id: str,
    ) -> None:
        try:
            relative = path.relative_to(context.paths.root.parent)
        except ValueError as exc:  # pragma: no cover - paths are closed above
            raise Protocol25MaterializationError(
                "L3 materialization escaped the run directory"
            ) from exc
        projection = MaterializedProjectionV1(
            artifact_kind=kind,  # type: ignore[arg-type]
            artifact_hash=content_digest(payload),
            artifact_key_id=authority_id,
            path=path,
        )
        specs.append(
            _ProjectionSpec(
                projection,
                tuple(relative.parts),
                ((path.name, payload),),
                directory=False,
            )
        )

    epochs = tuple(ledger.audit_epochs.values())
    if epochs:
        if len(epochs) != 1:
            raise Protocol25MaterializationError(
                "L3 projection requires at most one audit epoch"
            )
        epoch = epochs[0]
        epoch_bytes = context.object_store.read_blob(epoch.identity)
        add(root / "epoch.json", epoch_bytes, kind="audit-epoch", authority_id=epoch.identity)
        add(
            root / "epoch.md",
            _render_epoch(epoch),
            kind="audit-epoch-summary",
            authority_id=epoch.identity,
        )

    candidates: dict[str, AuditCandidateV1] = {}
    for acceptance in ledger.accepted_artifacts.values():
        if acceptance.artifact_key.artifact_kind != "semantic-audit-findings":
            continue
        payload = context.object_store.read_blob(acceptance.artifact_hash)
        candidate = load_canonical_object(payload, AuditCandidateV1.from_json_dict)
        candidates[candidate.audit_target_id] = candidate
        for finding in candidate.findings:
            finding_payload = canonical_json_bytes(finding.to_json_dict())
            add(
                root / "findings" / f"{_hex(finding.finding_key_id)}.json",
                finding_payload,
                kind="semantic-finding",
                authority_id=finding.finding_key_id,
            )

    overlays: list[SemanticResolutionOverlayV1] = []
    for acceptance in ledger.accepted_artifacts.values():
        if acceptance.artifact_key.artifact_kind != "semantic-resolution-overlay":
            continue
        payload = context.object_store.read_blob(acceptance.artifact_hash)
        overlay = load_canonical_object(
            payload,
            SemanticResolutionOverlayV1.from_json_dict,
        )
        overlays.append(overlay)
        add(
            root
            / "resolutions"
            / _hex(overlay.audit_target_id)
            / f"{overlay.semantic_round}.json",
            payload,
            kind="semantic-resolution-overlay",
            authority_id=overlay.identity,
        )

    for finding_id, receipt in sorted(ledger.latest_finding_closures.items()):
        add(
            root / "closure" / f"{_hex(finding_id)}.json",
            context.object_store.read_blob(receipt.identity),
            kind="finding-closure",
            authority_id=receipt.identity,
        )

    for source_id, source_root in sorted(ledger.l3_source_roots.items()):
        source_path = root / "sources" / _component(source_id)
        add(
            source_path / "root.json",
            context.object_store.read_blob(source_root.identity),
            kind="l3-source-root",
            authority_id=source_root.identity,
        )
        source_overlays = tuple(
            item
            for item in overlays
            if candidates.get(item.audit_target_id) is not None
            and candidates[item.audit_target_id].audit_target.scope.source_id
            == source_id
        )
        add(
            source_path / "overview.md",
            _render_source_overview(source_root, source_overlays),
            kind="l3-composed-overview",
            authority_id=source_root.identity,
        )
    return tuple(sorted(specs, key=lambda item: item.relative_parts))


def _render_epoch(epoch) -> bytes:  # type: ignore[no-untyped-def]
    lines = [
        "# L3 semantic audit epoch",
        "",
        f"Epoch: `{epoch.identity}`",
        f"Audit targets: {len(epoch.audit_target_ids)}",
        f"Frozen findings: {len(epoch.finding_key_ids)}",
        "workspace synthesis: not run",
        "",
    ]
    return "\n".join(lines).encode()


def _render_source_overview(source_root, overlays) -> bytes:  # type: ignore[no-untyped-def]
    lines = [
        f"# L3 composed semantic view — {source_root.source_id}",
        "",
        "The lower-layer authority remains immutable; this view applies explicit L3 refinements.",
        f"State: {source_root.state}",
        f"Unresolved findings: {len(source_root.unresolved_finding_ids)}",
        f"Deferred observations: {len(source_root.deferred_observation_ids)}",
    ]
    for overlay in sorted(overlays, key=lambda item: (item.audit_target_id, item.semantic_round)):
        lines.extend(
            (
                "",
                f"## Target `{overlay.audit_target_id}` — round {overlay.semantic_round}",
            )
        )
        for entry in overlay.entries:
            lines.append(
                "- refines lower-layer subjects: "
                + (", ".join(entry.refines_subject_refs) or "none")
            )
            lines.append(
                "- supersedes claim anchors: "
                + (", ".join(entry.supersedes_claim_anchor_ids) or "none")
            )
            lines.extend(f"- semantic claim: {claim}" for claim in entry.semantic_claims)
    lines.extend(("", "workspace synthesis: not run", ""))
    return "\n".join(lines).encode()


def _hex(value: str) -> str:
    if not value.startswith("sha256:") or len(value) != 71:
        raise Protocol25MaterializationError("L3 authority ID is not a digest")
    return value.removeprefix("sha256:")


def _component(value: str) -> str:
    if not value or value in {".", ".."} or any(
        not (character.isalnum() or character in "._-") for character in value
    ):
        raise Protocol25MaterializationError("unsafe L3 path component")
    return value


@contextmanager
def _l3_materialization_lock(run_root: Path) -> Iterator[int]:
    run_fd = _open_directory_path_nofollow(run_root, "RE run root")
    lock_fd = None
    try:
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_CLOEXEC", 0) | os.O_NOFOLLOW
        lock_fd = os.open(".l3-materialization.lock", flags, 0o600, dir_fd=run_fd)
        metadata = os.fstat(lock_fd)
        if not stat.S_ISREG(metadata.st_mode):
            raise Protocol25MaterializationError(
                "L3 materialization lock is not a regular file"
            )
        os.fchmod(lock_fd, 0o600)
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        yield run_fd
    finally:
        if lock_fd is not None:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
            finally:
                os.close(lock_fd)
        os.close(run_fd)


__all__ = (
    "Protocol25MaterializationError",
    "materialize_accepted_l3",
)
