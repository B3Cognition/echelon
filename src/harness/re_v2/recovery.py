"""Deterministic recovery for one pinned RE v2 run.

Recovery deliberately rebuilds from the immutable manifest, snapshot, event
history, object store, ledger, and committed candidates.  ``projection.json``
is output only; it is never read as authority here.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import Enum
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
from typing import Callable, Mapping

from .budget import ReV2BudgetError, evaluate_budget
from .candidates import (
    CandidateStore,
    DispatchLease,
    PersistedCandidate,
    ProcessIdentity,
    ReV2CandidateError,
)
from .canonical import canonical_json_bytes, content_digest
from .events import EventRecord, EventStore, ReV2EventError
from .ledger import (
    Certifier,
    CertificationDecision,
    Ledger,
    LedgerView,
    ObjectStore,
    ReV2LedgerError,
)
from .model import (
    ArtifactReceipt,
    CertificationReceipt,
    ExecutionObservation,
    ReV2ModelError,
    RunManifest,
    WorkItem,
)
from .planner import ReV2PlanError, WorkGraph, plan_next
from .projection import (
    ReV2ProjectionError,
    project_run,
    rebuild_projection,
)
from .run_store import (
    ReV2Paths,
    ReV2RunStoreError,
    load_run_manifest,
)
from .snapshot import CapturedSnapshot, ReV2SnapshotError, validate_source_snapshot


class ReV2RecoveryError(RuntimeError):
    """Raised before redispatch when persisted run authority is unsafe."""

    def __init__(self, message: str, *, reason_code: str = "recovery_failed") -> None:
        super().__init__(message)
        self.reason_code = reason_code


class ProcessState(str, Enum):
    """The only safe conclusions about a leased process identity."""

    SAME_PROCESS_LIVE = "same_process_live"
    DEAD = "dead"
    PID_REUSED_OR_AMBIGUOUS = "pid_reused_or_ambiguous"


class ProcessInspector:
    """Classify a PID by its stable process-start identity without signaling it."""

    def __init__(
        self, probe: Callable[[int], str | None] | None = None
    ) -> None:
        self._probe = probe or _default_process_probe

    def inspect(self, identity: ProcessIdentity) -> ProcessState:
        if not isinstance(identity, ProcessIdentity):
            raise ReV2RecoveryError("process inspection requires a ProcessIdentity")
        try:
            observed = self._probe(identity.pid)
        except Exception:
            return ProcessState.PID_REUSED_OR_AMBIGUOUS
        if observed is None:
            return ProcessState.DEAD
        if observed == identity.process_start_identity:
            return ProcessState.SAME_PROCESS_LIVE
        return ProcessState.PID_REUSED_OR_AMBIGUOUS


@dataclass(frozen=True, slots=True)
class ReV2RunContext:
    """Explicit authorities and injected seams for one pinned controller run."""

    paths: ReV2Paths
    snapshot: CapturedSnapshot
    graph: WorkGraph
    event_store: EventStore
    object_store: ObjectStore
    ledger: Ledger
    candidate_store: CandidateStore
    certifier: Certifier

    @property
    def manifest(self) -> RunManifest:
        return load_run_manifest(self.paths.root.parent)


@dataclass(frozen=True, slots=True)
class ReV2RecoveryResult:
    """Fresh replay results after all recoverable candidates are reconciled."""

    manifest: RunManifest
    events: tuple[EventRecord, ...]
    ledger: LedgerView
    projection: Mapping[str, object]
    reconciled_candidate_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _CandidateFacts:
    persisted_by_candidate: Mapping[str, EventRecord]
    outcome_by_candidate: Mapping[str, EventRecord]
    accepted_by_certification: Mapping[str, EventRecord]
    checkpoint_by_certification: Mapping[str, EventRecord]


def recover_run(
    context: ReV2RunContext,
    *,
    process_inspector: ProcessInspector | object | None = None,
    clock: Callable[[], str] | None = None,
    fault_hook: Callable[[str], None] | None = None,
) -> ReV2RecoveryResult:
    """Recover one run in fail-closed order before any planner is consulted."""
    inspector = process_inspector or ProcessInspector()
    now = clock or _canonical_utc_now
    manifest, events, ledger_view = _validate_authorities(context)

    # Validate projection inputs without consulting an existing projection.
    _project(manifest, events, ledger_view)
    leases = _discover_leases(context)
    try:
        candidates = context.candidate_store.discover()
    except ReV2CandidateError as exc:
        raise ReV2RecoveryError(f"committed candidate validation failed: {exc}") from exc
    _validate_persisted_candidate_events(events, candidates)
    _validate_candidates_against_authorities(
        events,
        leases,
        candidates,
        expected_provider=str(manifest.provider_contract["provider"]),
    )
    _validate_recovered_work_items(
        manifest,
        context.graph,
        ledger_view,
        leases,
        candidates,
    )

    outstanding = _outstanding_leases(events, leases)
    retired_dispatches = {
        str(event.payload["dispatch_id"])
        for event in events
        if event.type == "dispatch_lease_retired"
    }
    outstanding_dispatches = {lease.dispatch_id for lease in outstanding}
    inspectable = tuple(
        lease
        for lease in leases
        if lease.dispatch_id in outstanding_dispatches
        or lease.dispatch_id in retired_dispatches
    )
    inspected: list[tuple[DispatchLease, ProcessState]] = []
    for lease in inspectable:
        state = _inspect_process(inspector, lease.process_identity)
        inspected.append((lease, state))

    ambiguous = tuple(
        lease
        for lease, state in inspected
        if state is ProcessState.PID_REUSED_OR_AMBIGUOUS
        and lease.dispatch_id not in retired_dispatches
    )
    live = tuple(
        lease for lease, state in inspected if state is ProcessState.SAME_PROCESS_LIVE
    )
    if ambiguous:
        dispatches = ", ".join(lease.dispatch_id for lease in ambiguous)
        raise ReV2RecoveryError(
            f"leased process identity is PID-reused or ambiguous: {dispatches}",
            reason_code="lease_process_ambiguous",
        )
    if live:
        dispatches = ", ".join(lease.dispatch_id for lease in live)
        raise ReV2RecoveryError(
            f"leased process is still running: {dispatches}",
            reason_code="lease_process_live",
        )

    _audit_ledger_receipts(context, ledger_view, candidates)

    if not events:
        context.event_store.append(
            "run_created",
            {"run_manifest_id": manifest.run_manifest_id},
            occurred_at=manifest.created_at,
        )
        events = context.event_store.replay()
        _project(manifest, events, ledger_view)

    if _is_terminal(events) and outstanding:
        raise ReV2RecoveryError(
            "terminal run has an unresolved dead lease",
            reason_code="terminal_with_unresolved_lease",
        )
    if not _is_terminal(events):
        _resolve_eventless_dead_leases(
            context, events, outstanding, candidates
        )
        events = context.event_store.replay()
        _close_dead_active_dispatch(
            context,
            events,
            leases,
            candidates,
            now,
            expected_provider=str(manifest.provider_contract["provider"]),
        )
        events = context.event_store.replay()
        unresolved = _outstanding_leases(events, leases)
        if unresolved:
            dispatches = ", ".join(lease.dispatch_id for lease in unresolved)
            raise ReV2RecoveryError(
                f"dead leases remain unresolved after recovery: {dispatches}"
            )

    reconciled: list[str] = []
    for candidate in candidates:
        needs_recovery = _candidate_needs_recovery(events, candidate)
        if needs_recovery:
            if _is_terminal(events):
                raise ReV2RecoveryError(
                    "terminal run contains an unhandled committed candidate"
                )
            reconciled.append(candidate.candidate_id)
        # Handled candidates are still cross-checked against ledger authority.
        # The reconciler is idempotent when every receipt/event already exists.
        _reconcile_candidate(context, candidate, events, fault_hook)
        events = context.event_store.replay()

    try:
        ledger_view = context.ledger.replay()
        events = context.event_store.replay()
        projection = _project(manifest, events, ledger_view)
        rebuilt = rebuild_projection(context.paths, ledger_view)
    except (ReV2EventError, ReV2LedgerError, ReV2ProjectionError) as exc:
        raise ReV2RecoveryError(f"recovery replay failed: {exc}") from exc
    if rebuilt != projection:
        raise ReV2RecoveryError("projection rebuild changed validated replay output")
    return ReV2RecoveryResult(
        manifest=manifest,
        events=events,
        ledger=ledger_view,
        projection=projection,
        reconciled_candidate_ids=tuple(reconciled),
    )


def _validate_authorities(
    context: ReV2RunContext,
) -> tuple[RunManifest, tuple[EventRecord, ...], LedgerView]:
    if not isinstance(context, ReV2RunContext):
        raise ReV2RecoveryError("recovery requires a ReV2RunContext")
    try:
        manifest = load_run_manifest(context.paths.root.parent)
    except ReV2RunStoreError as exc:
        raise ReV2RecoveryError(f"immutable manifest validation failed: {exc}") from exc
    if (
        context.snapshot.snapshot_id != manifest.source_snapshot_id
        or context.snapshot.kind != manifest.source_snapshot_kind
    ):
        raise ReV2RecoveryError("snapshot handle does not match immutable run manifest")
    try:
        validate_source_snapshot(context.snapshot)
    except ReV2SnapshotError as exc:
        raise ReV2RecoveryError(f"source snapshot validation failed: {exc}") from exc

    expected = ReV2Paths.for_run(context.paths.root.parent)
    if context.paths != expected:
        raise ReV2RecoveryError("run context paths do not match immutable run directory")
    if context.event_store.path != context.paths.events:
        raise ReV2RecoveryError("event store is not bound to the run event path")
    if context.candidate_store.paths != context.paths:
        raise ReV2RecoveryError("candidate store is not bound to the run paths")
    if context.ledger.path != context.paths.ledger:
        raise ReV2RecoveryError("ledger is not bound to the run ledger path")
    if context.ledger.object_store is not context.object_store:
        raise ReV2RecoveryError("ledger and context do not share the object store")
    object_root = context.object_store.root
    expected_objects = context.paths.objects
    if (
        object_root.is_symlink()
        or expected_objects.is_symlink()
        or not object_root.is_dir()
        or object_root.resolve() != expected_objects.resolve()
        or object_root != object_root.resolve()
    ):
        raise ReV2RecoveryError(
            "object store is not the safe run-local object authority"
        )
    if context.ledger.pinned_source_snapshot_id != manifest.source_snapshot_id:
        raise ReV2RecoveryError("ledger is not pinned to the manifest snapshot")
    if (
        context.ledger.pinned_partition_manifest_id
        != manifest.partition_manifest_id
        or context.ledger.pinned_requested_goals != frozenset(manifest.requested_goals)
        or dict(context.ledger.pinned_artifact_policy_versions or {})
        != dict(manifest.artifact_policy_versions)
    ):
        raise ReV2RecoveryError("ledger is not pinned to the full run manifest scope")
    if (
        context.graph.source_snapshot_id != manifest.source_snapshot_id
        or context.graph.partition_manifest_id != manifest.partition_manifest_id
        or context.graph.requested_goals != manifest.requested_goals
    ):
        raise ReV2RecoveryError("work graph does not match immutable run inputs")
    for template in context.graph.templates:
        pinned_policy_version = manifest.artifact_policy_versions.get(template.layer)
        if pinned_policy_version is None:
            raise ReV2RecoveryError(
                f"graph layer {template.layer} has no manifest artifact policy"
            )
        expected_policy_hash = content_digest(
            {
                "artifact_kind": template.artifact_kind,
                "policy_version": pinned_policy_version,
            }
        )
        if template.layer_policy_hash != expected_policy_hash:
            raise ReV2RecoveryError(
                "graph layer policy hash does not match manifest artifact policy"
            )
    try:
        events = context.event_store.replay()
        ledger_view = context.ledger.replay()
    except (ReV2EventError, ReV2LedgerError) as exc:
        raise ReV2RecoveryError(f"authoritative replay failed: {exc}") from exc
    if events and (
        events[0].type != "run_created"
        or events[0].payload["run_manifest_id"] != manifest.run_manifest_id
    ):
        raise ReV2RecoveryError("run_created does not match immutable run manifest")
    _validate_observation_providers(
        events, str(manifest.provider_contract["provider"])
    )
    return manifest, events, ledger_view


def _validate_recovered_work_items(
    manifest: RunManifest,
    graph: WorkGraph,
    ledger: LedgerView,
    leases: tuple[DispatchLease, ...],
    candidates: tuple[PersistedCandidate, ...],
) -> None:
    """Require exact canonical graph materialization for every durable WorkItem."""
    work_items = {
        work_item.work_item_id: work_item
        for work_item in (
            *ledger.certification_work_items.values(),
            *(lease.work_item for lease in leases),
            *(candidate.work_item for candidate in candidates),
        )
    }
    for work_item in sorted(
        work_items.values(), key=lambda item: (item.template_id, item.work_item_id)
    ):
        expected = _materialize_graph_work_item(manifest, graph, ledger, work_item)
        if work_item != expected:
            raise ReV2RecoveryError(
                "recovered WorkItem does not exactly match canonical graph materialization",
                reason_code="foreign_work_item",
            )


def _materialize_graph_work_item(
    manifest: RunManifest,
    graph: WorkGraph,
    ledger: LedgerView,
    work_item: WorkItem,
) -> WorkItem:
    template_ids = {template.template_id for template in graph.templates}
    if work_item.template_id not in template_ids:
        raise ReV2RecoveryError(
            "recovered WorkItem template is not authorized by the run graph",
            reason_code="foreign_work_item",
        )

    target_certifications = {
        certification_id
        for certification_id, certified_item in ledger.certification_work_items.items()
        if certified_item.template_id == work_item.template_id
    }
    materialization_view = LedgerView(
        accepted_artifacts={
            key_id: receipt
            for key_id, receipt in ledger.accepted_artifacts.items()
            if receipt.certification_id not in target_certifications
        },
        certifications=ledger.certifications,
        certification_work_items=ledger.certification_work_items,
    )
    try:
        budget = replace(
            evaluate_budget(
                manifest.initial_budget_policy,
                (),
                now=manifest.created_at,
            ),
            exhausted_dimensions=(),
        )
        decision = plan_next(
            graph,
            materialization_view,
            budget,
            requested_goals=manifest.requested_goals,
        )
    except (ReV2BudgetError, ReV2PlanError) as exc:
        raise ReV2RecoveryError(
            f"cannot materialize authoritative WorkItem from graph: {exc}",
            reason_code="foreign_work_item",
        ) from exc
    expected = next(
        (
            candidate
            for candidate in decision.ready
            if candidate.template_id == work_item.template_id
        ),
        None,
    )
    if expected is None:
        raise ReV2RecoveryError(
            "recovered WorkItem is not dependency-complete in the canonical graph",
            reason_code="foreign_work_item",
        )
    return expected


def _project(
    manifest: RunManifest,
    events: tuple[EventRecord, ...],
    ledger: LedgerView,
) -> dict[str, object]:
    try:
        return project_run(manifest, events, ledger)
    except ReV2ProjectionError as exc:
        raise ReV2RecoveryError(f"projection input validation failed: {exc}") from exc


def _discover_leases(context: ReV2RunContext) -> tuple[DispatchLease, ...]:
    lock_path = context.paths.candidates / ".store.lock"
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        lock_fd = os.open(lock_path, flags, 0o600)
    except OSError as exc:
        raise ReV2RecoveryError(f"cannot lock lease inventory: {exc}") from exc
    leases: list[DispatchLease] = []
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        directory_flags = (
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        try:
            root_fd = _open_descriptor(context.paths.candidates, directory_flags)
        except OSError as exc:
            raise ReV2RecoveryError(f"cannot open candidate root for leases: {exc}") from exc
        try:
            try:
                lease_fd = _open_descriptor(
                    ".leases", directory_flags, dir_fd=root_fd
                )
            except FileNotFoundError:
                return ()
            except OSError as exc:
                raise ReV2RecoveryError(f"lease root is unsafe: {exc}") from exc
            try:
                names = tuple(sorted(_list_directory(lease_fd)))
                for name in names:
                    if name.startswith("."):
                        continue
                    if not name.endswith(".json"):
                        raise ReV2RecoveryError(f"invalid lease filename: {name}")
                    try:
                        payload, info = _read_regular_at(lease_fd, name)
                        raw = json.loads(payload)
                    except (OSError, ValueError) as exc:
                        raise ReV2RecoveryError(f"invalid lease {name}: {exc}") from exc
                    if not isinstance(raw, dict) or set(raw) != {
                        "lease",
                        "schema_version",
                    }:
                        raise ReV2RecoveryError(f"invalid lease envelope: {name}")
                    if raw["schema_version"] != 1 or isinstance(
                        raw["schema_version"], bool
                    ):
                        raise ReV2RecoveryError(f"unsupported lease schema: {name}")
                    try:
                        lease = DispatchLease.from_json_dict(raw["lease"])
                    except (ReV2CandidateError, ReV2ModelError) as exc:
                        raise ReV2RecoveryError(f"invalid lease {name}: {exc}") from exc
                    if payload != canonical_json_bytes(raw):
                        raise ReV2RecoveryError(f"lease is not canonical JSON: {name}")
                    if name != f"{lease.dispatch_id}.json":
                        raise ReV2RecoveryError(
                            f"lease filename does not match dispatch: {name}"
                        )
                    if not stat.S_ISREG(info.st_mode):
                        raise ReV2RecoveryError(f"lease is not a regular file: {name}")
                    leases.append(lease)
                if tuple(sorted(_list_directory(lease_fd))) != names:
                    raise ReV2RecoveryError("lease inventory changed while reading")
            finally:
                os.close(lease_fd)
        finally:
            os.close(root_fd)
    finally:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
        finally:
            os.close(lock_fd)
    dispatch_ids = [lease.dispatch_id for lease in leases]
    if len(dispatch_ids) != len(set(dispatch_ids)):
        raise ReV2RecoveryError("lease inventory contains duplicate dispatch IDs")
    return tuple(leases)


def _open_descriptor(
    path: object, flags: int, *, dir_fd: int | None = None
) -> int:
    while True:
        try:
            if dir_fd is None:
                return os.open(path, flags)  # type: ignore[arg-type]
            return os.open(path, flags, dir_fd=dir_fd)  # type: ignore[arg-type]
        except InterruptedError:
            continue


def _list_directory(fd: int) -> list[str]:
    while True:
        try:
            return os.listdir(fd)
        except InterruptedError:
            continue


def _read_regular_at(directory_fd: int, name: str) -> tuple[bytes, os.stat_result]:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    fd = _open_descriptor(name, flags, dir_fd=directory_fd)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode):
            raise ReV2RecoveryError(f"lease is not a regular file: {name}")
        chunks: list[bytes] = []
        while True:
            try:
                chunk = os.read(fd, 1024 * 1024)
            except InterruptedError:
                continue
            if not chunk:
                break
            chunks.append(chunk)
        payload = b"".join(chunks)
        after = os.fstat(fd)
        current = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        stable = (
            before.st_dev,
            before.st_ino,
            before.st_mode,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        )
        if stable != (
            after.st_dev,
            after.st_ino,
            after.st_mode,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        ) or (after.st_dev, after.st_ino) != (current.st_dev, current.st_ino):
            raise ReV2RecoveryError(f"lease changed while reading: {name}")
        if len(payload) != after.st_size:
            raise ReV2RecoveryError(f"lease size changed while reading: {name}")
        return payload, after
    finally:
        os.close(fd)


def _outstanding_leases(
    events: tuple[EventRecord, ...], leases: tuple[DispatchLease, ...]
) -> tuple[DispatchLease, ...]:
    lease_by_dispatch = {lease.dispatch_id: lease for lease in leases}
    observed = {
        str(event.payload["dispatch_id"])
        for event in events
        if event.type == "dispatch_observed"
    }
    retired = {
        str(event.payload["dispatch_id"]): (
            str(event.payload["work_item_id"]),
            str(event.payload["lease_id"]),
        )
        for event in events
        if event.type == "dispatch_lease_retired"
    }
    event_leases = {
        str(event.payload["dispatch_id"]): str(event.payload["work_item_id"])
        for event in events
        if event.type == "dispatch_leased"
    }
    for dispatch_id, work_item_id in event_leases.items():
        lease = lease_by_dispatch.get(dispatch_id)
        if lease is None:
            raise ReV2RecoveryError(
                f"event history references a missing dispatch lease: {dispatch_id}"
            )
        if lease.work_item_id != work_item_id:
            raise ReV2RecoveryError(
                f"dispatch lease does not match event work item: {dispatch_id}"
            )
    for dispatch_id, (work_item_id, lease_id) in retired.items():
        lease = lease_by_dispatch.get(dispatch_id)
        if lease is None:
            raise ReV2RecoveryError(
                f"retirement event references a missing dispatch lease: {dispatch_id}"
            )
        if lease.work_item_id != work_item_id:
            raise ReV2RecoveryError(
                f"retirement event does not match lease work item: {dispatch_id}"
            )
        if lease.lease_id != lease_id:
            raise ReV2RecoveryError(
                f"retirement event does not match the exact lease: {dispatch_id}"
            )
    resolved = observed | set(retired)
    return tuple(
        lease for lease in leases if lease.dispatch_id not in resolved
    )


def _inspect_process(inspector: object, identity: ProcessIdentity) -> ProcessState:
    method = getattr(inspector, "inspect", None)
    if not callable(method):
        raise ReV2RecoveryError("process_inspector must provide inspect(identity)")
    try:
        state = method(identity)
        return state if isinstance(state, ProcessState) else ProcessState(state)
    except ReV2RecoveryError:
        raise
    except (TypeError, ValueError) as exc:
        raise ReV2RecoveryError("process inspector returned an invalid state") from exc


def _resolve_eventless_dead_leases(
    context: ReV2RunContext,
    events: tuple[EventRecord, ...],
    outstanding: tuple[DispatchLease, ...],
    candidates: tuple[PersistedCandidate, ...],
) -> None:
    leased_dispatches = {
        str(event.payload["dispatch_id"])
        for event in events
        if event.type == "dispatch_leased"
    }
    candidates_by_dispatch = {
        candidate.dispatch_id: candidate for candidate in candidates
    }
    history = events
    for lease in outstanding:
        if lease.dispatch_id in leased_dispatches:
            continue
        candidate = candidates_by_dispatch.get(lease.dispatch_id)
        if candidate is None:
            context.event_store.append(
                "dispatch_lease_retired",
                {
                    "dispatch_id": lease.dispatch_id,
                    "lease_id": lease.lease_id,
                    "reason": "dead process without a committed candidate",
                    "work_item_id": lease.work_item_id,
                },
                occurred_at=lease.leased_at,
            )
            history = context.event_store.replay()
            continue

        attempt_kind, attempt_index = next_dispatch_attempt(
            history, lease.work_item
        )
        context.event_store.append(
            "dispatch_leased",
            {
                "dispatch_id": lease.dispatch_id,
                "work_item_id": lease.work_item_id,
            },
            occurred_at=lease.leased_at,
        )
        context.event_store.append(
            "dispatch_started",
            {
                "attempt_index": attempt_index,
                "attempt_kind": attempt_kind,
                "dispatch_id": lease.dispatch_id,
                "work_item_id": lease.work_item_id,
            },
            occurred_at=candidate.observation.started_at,
        )
        context.event_store.append(
            "dispatch_observed",
            {
                "dispatch_id": lease.dispatch_id,
                "observation": candidate.observation.to_json_dict(),
                "work_item_id": lease.work_item_id,
            },
            occurred_at=candidate.observation.ended_at,
        )
        context.event_store.append(
            "candidate_persisted",
            {
                "candidate_id": candidate.candidate_id,
                "dispatch_id": candidate.dispatch_id,
                "work_item_id": candidate.work_item_id,
            },
            occurred_at=candidate.persisted_at,
        )
        history = context.event_store.replay()


def _close_dead_active_dispatch(
    context: ReV2RunContext,
    events: tuple[EventRecord, ...],
    leases: tuple[DispatchLease, ...],
    candidates: tuple[PersistedCandidate, ...],
    clock: Callable[[], str],
    *,
    expected_provider: str,
) -> None:
    observed = {
        str(event.payload["dispatch_id"])
        for event in events
        if event.type == "dispatch_observed"
    }
    active_event = next(
        (
            event
            for event in reversed(events)
            if event.type == "dispatch_leased"
            and str(event.payload["dispatch_id"]) not in observed
        ),
        None,
    )
    if active_event is None:
        return
    dispatch_id = str(active_event.payload["dispatch_id"])
    lease = next(
        (item for item in leases if item.dispatch_id == dispatch_id), None
    )
    if lease is None:
        raise ReV2RecoveryError(f"active dispatch has no lease: {dispatch_id}")
    candidate = next(
        (item for item in candidates if item.dispatch_id == dispatch_id), None
    )
    if candidate is not None and candidate.lease != lease:
        raise ReV2RecoveryError(
            f"committed candidate does not match active lease: {dispatch_id}"
        )
    started = next(
        (
            event
            for event in events
            if event.type == "dispatch_started"
            and event.payload["dispatch_id"] == dispatch_id
        ),
        None,
    )
    if started is None:
        attempt_kind, attempt_index = next_dispatch_attempt(events, lease.work_item)
        started = context.event_store.append(
            "dispatch_started",
            {
                "attempt_index": attempt_index,
                "attempt_kind": attempt_kind,
                "dispatch_id": dispatch_id,
                "work_item_id": lease.work_item_id,
            },
            occurred_at=lease.leased_at,
        )
    if candidate is None:
        ended_at = _utc(clock(), "recovery clock")
        started_at = started.occurred_at
        duration = _elapsed_ms(started_at, ended_at)
        observation = ExecutionObservation(
            started_at=started_at,
            ended_at=ended_at,
            duration_ms=duration,
            exit_code=None,
            timed_out=False,
            output_truncated=False,
            result_contract_valid=False,
            token_usage=None,
            provider_name=expected_provider,
            model_name="unknown",
            stderr_digest=None,
        )
    else:
        observation = candidate.observation
        ended_at = observation.ended_at
    context.event_store.append(
        "dispatch_observed",
        {
            "dispatch_id": dispatch_id,
            "observation": observation.to_json_dict(),
            "work_item_id": lease.work_item_id,
        },
        occurred_at=ended_at,
    )


def next_dispatch_attempt(
    events: tuple[EventRecord, ...], work_item: object
) -> tuple[str, int]:
    """Return the sole lifecycle-authorized next attempt for one WorkItem."""
    work_item_id = getattr(work_item, "work_item_id", None)
    if not isinstance(work_item_id, str):
        raise ReV2RecoveryError("attempt selection requires a WorkItem")
    all_starts = [event for event in events if event.type == "dispatch_started"]
    starts = [
        event
        for event in all_starts
        if event.payload["work_item_id"] == work_item_id
    ]
    if not starts:
        kind = "initial_generation"
    else:
        latest_start = all_starts[-1]
        if latest_start.payload["work_item_id"] != work_item_id:
            raise ReV2RecoveryError(
                "a newer dispatch does not authorize stale repair debt",
                reason_code="retry_not_authorized",
            )
        dispatch_id = str(latest_start.payload["dispatch_id"])
        observed = next(
            (
                event
                for event in events
                if event.type == "dispatch_observed"
                and event.payload["dispatch_id"] == dispatch_id
            ),
            None,
        )
        if observed is None:
            raise ReV2RecoveryError("prior dispatch has no retry-authorizing outcome")
        observation = ExecutionObservation.from_json_dict(
            observed.payload["observation"]
        )
        persisted = next(
            (
                event
                for event in events
                if event.type == "candidate_persisted"
                and event.payload["dispatch_id"] == dispatch_id
            ),
            None,
        )
        outcome = (
            None
            if persisted is None
            else next(
                (
                    event
                    for event in events
                    if event.type in {"candidate_certified", "candidate_rejected"}
                    and event.payload["candidate_id"]
                    == persisted.payload["candidate_id"]
                ),
                None,
            )
        )
        if outcome is None and persisted is None and not observation.result_contract_valid:
            kind = "result_contract_retry"
        elif outcome is not None and outcome.type == "candidate_rejected":
            prior_kind = str(latest_start.payload["attempt_kind"])
            if prior_kind in {"initial_generation", "semantic_repair"}:
                kind = "semantic_repair"
            elif not observation.result_contract_valid:
                kind = "result_contract_retry"
            else:
                raise ReV2RecoveryError(
                    "rejected valid retry does not authorize another dispatch",
                    reason_code="retry_not_authorized",
                )
        else:
            raise ReV2RecoveryError(
                "latest outcome does not authorize redispatch",
                reason_code="retry_not_authorized",
            )
    index = 1 + sum(
        event.payload["attempt_kind"] == kind for event in starts
    )
    return kind, index


def _validate_persisted_candidate_events(
    events: tuple[EventRecord, ...], candidates: tuple[PersistedCandidate, ...]
) -> None:
    by_id = {candidate.candidate_id: candidate for candidate in candidates}
    for event in events:
        if event.type != "candidate_persisted":
            continue
        candidate = by_id.get(str(event.payload["candidate_id"]))
        if candidate is None:
            raise ReV2RecoveryError(
                "candidate_persisted event has no committed candidate"
            )
        if (
            event.payload["dispatch_id"] != candidate.dispatch_id
            or event.payload["work_item_id"] != candidate.work_item_id
        ):
            raise ReV2RecoveryError(
                "candidate_persisted event does not match committed candidate"
            )


def _validate_candidates_against_authorities(
    events: tuple[EventRecord, ...],
    leases: tuple[DispatchLease, ...],
    candidates: tuple[PersistedCandidate, ...],
    *,
    expected_provider: str,
) -> None:
    lease_by_dispatch = {lease.dispatch_id: lease for lease in leases}
    for candidate in candidates:
        if candidate.observation.provider_name != expected_provider:
            raise ReV2RecoveryError(
                "committed candidate observation provider does not match manifest"
            )
        lease = lease_by_dispatch.get(candidate.dispatch_id)
        if (
            lease is None
            or candidate.lease != lease
            or candidate.work_item != lease.work_item
            or candidate.work_item_id != lease.work_item_id
        ):
            raise ReV2RecoveryError(
                "committed candidate does not match its exact dispatch lease"
            )
        leased_event = next(
            (
                event
                for event in events
                if event.type == "dispatch_leased"
                and event.payload["dispatch_id"] == candidate.dispatch_id
            ),
            None,
        )
        if leased_event is not None and (
            leased_event.payload["work_item_id"] != candidate.work_item_id
        ):
            raise ReV2RecoveryError(
                "committed candidate does not match dispatch lease event"
            )
        observation_event = next(
            (
                event
                for event in events
                if event.type == "dispatch_observed"
                and event.payload["dispatch_id"] == candidate.dispatch_id
            ),
            None,
        )
        if observation_event is not None:
            _validate_candidate_observation(events, candidate)


def _validate_observation_providers(
    events: tuple[EventRecord, ...], expected_provider: str
) -> None:
    for event in events:
        if event.type != "dispatch_observed":
            continue
        observation = ExecutionObservation.from_json_dict(
            event.payload["observation"]
        )
        if observation.provider_name != expected_provider:
            raise ReV2RecoveryError(
                "dispatch observation provider does not match manifest"
            )


def _audit_ledger_receipts(
    context: ReV2RunContext,
    ledger: LedgerView,
    candidates: tuple[PersistedCandidate, ...],
) -> None:
    by_candidate = {candidate.candidate_id: candidate for candidate in candidates}
    if set(ledger.certification_work_items) != set(ledger.certifications):
        raise ReV2RecoveryError(
            "ledger certification is missing its durable WorkItem"
        )
    for certification_id, receipt in sorted(ledger.certifications.items()):
        candidate = by_candidate.get(receipt.candidate_id)
        if candidate is None:
            raise ReV2RecoveryError(
                "ledger certification has no exact committed candidate"
            )
        work_item = ledger.certification_work_items[certification_id]
        if work_item != candidate.work_item:
            raise ReV2RecoveryError(
                "ledger certification WorkItem does not match committed candidate"
            )
        _validate_certification(receipt, candidate)
        try:
            context.object_store.verify(
                receipt.certification_key.artifact_hash
            )
        except ReV2LedgerError as exc:
            raise ReV2RecoveryError(
                f"ledger certification object is invalid: {exc}"
            ) from exc

    for artifact in ledger.accepted_artifacts.values():
        certification = ledger.certifications.get(artifact.certification_id)
        if certification is None:
            raise ReV2RecoveryError(
                "ledger artifact has no matching certification"
            )
        candidate = by_candidate.get(artifact.candidate_id)
        if candidate is None:
            raise ReV2RecoveryError(
                "ledger artifact has no exact committed candidate"
            )
        _validate_artifact(artifact, certification, candidate)


def _candidate_needs_recovery(
    events: tuple[EventRecord, ...], candidate: PersistedCandidate
) -> bool:
    facts = _candidate_facts(events)
    outcome = facts.outcome_by_candidate.get(candidate.candidate_id)
    if outcome is None:
        return True
    if outcome.type == "candidate_rejected":
        return False
    certification_id = str(outcome.payload["certification_id"])
    accepted = facts.accepted_by_certification.get(certification_id)
    checkpoint = facts.checkpoint_by_certification.get(certification_id)
    return accepted is None or checkpoint is None


def _reconcile_candidate(
    context: ReV2RunContext,
    candidate: PersistedCandidate,
    events: tuple[EventRecord, ...],
    fault_hook: Callable[[str], None] | None,
) -> None:
    facts = _candidate_facts(events)
    persisted = facts.persisted_by_candidate.get(candidate.candidate_id)
    if persisted is None:
        _validate_candidate_observation(events, candidate)
        context.event_store.append(
            "candidate_persisted",
            {
                "candidate_id": candidate.candidate_id,
                "dispatch_id": candidate.dispatch_id,
                "work_item_id": candidate.work_item_id,
            },
            occurred_at=candidate.persisted_at,
        )
        _fault(fault_hook, "candidate_event_reconciled")
        events = context.event_store.replay()
        facts = _candidate_facts(events)

    ledger_view = context.ledger.replay()
    outcome = facts.outcome_by_candidate.get(candidate.candidate_id)
    certification = _certification_for_candidate(
        ledger_view, candidate, outcome
    )
    decision: CertificationDecision | None = None
    if certification is None:
        _validate_pinned_certifier(context.certifier, candidate)
        decision = context.certifier.certify(candidate, candidate.work_item)
        _validate_decision(decision, candidate)
        certification = decision.certification_receipt
        context.ledger.record_certification(certification, candidate.work_item)
        _fault(fault_hook, "certification_written")

    if outcome is None:
        event_type = (
            "candidate_certified"
            if certification.verdict == "accepted" and certification.scope_verified
            else "candidate_rejected"
        )
        payload: dict[str, object] = {
            "candidate_id": candidate.candidate_id,
            "certification_id": certification.identity,
            "work_item_id": candidate.work_item_id,
        }
        if event_type == "candidate_rejected":
            payload["reason"] = _rejection_reason(certification)
        context.event_store.append(
            event_type,
            payload,
            occurred_at=certification.certified_at,
        )
        _fault(fault_hook, "certification_event_written")
        events = context.event_store.replay()
        facts = _candidate_facts(events)
        outcome = facts.outcome_by_candidate[candidate.candidate_id]
    _validate_outcome(outcome, certification, candidate)
    if outcome.type == "candidate_rejected":
        return

    ledger_view = context.ledger.replay()
    artifact = ledger_view.accepted_artifacts.get(
        candidate.work_item.output_key.identity
    )
    if artifact is None:
        artifact = (
            decision.artifact_receipt
            if decision is not None
            else ArtifactReceipt(
                artifact_key=candidate.work_item.output_key,
                artifact_hash=certification.certification_key.artifact_hash,
                certification_id=certification.identity,
                candidate_id=candidate.candidate_id,
                work_item_id=candidate.work_item_id,
                accepted_at=certification.certified_at,
            )
        )
        if artifact is None:
            raise ReV2RecoveryError("accepted certification has no artifact receipt")
        context.ledger.record_artifact(artifact)
        _fault(fault_hook, "artifact_written")
    _validate_artifact(artifact, certification, candidate)

    acceptance = facts.accepted_by_certification.get(certification.identity)
    if acceptance is None:
        context.event_store.append(
            "artifact_accepted",
            {
                "artifact_hash": artifact.artifact_hash,
                "artifact_key_id": artifact.artifact_key.identity,
                "certification_id": certification.identity,
                "work_item_id": candidate.work_item_id,
            },
            occurred_at=artifact.accepted_at,
        )
        _fault(fault_hook, "artifact_acceptance_written")
        events = context.event_store.replay()
        facts = _candidate_facts(events)
        acceptance = facts.accepted_by_certification[certification.identity]
    _validate_acceptance(acceptance, artifact, candidate)

    checkpoint = facts.checkpoint_by_certification.get(certification.identity)
    if checkpoint is None:
        context.event_store.append(
            "checkpoint_recorded",
            {
                "artifact_hash": artifact.artifact_hash,
                "certification_id": certification.identity,
                "work_item_id": candidate.work_item_id,
            },
            occurred_at=artifact.accepted_at,
        )
        _fault(fault_hook, "checkpoint_recorded")
    else:
        _validate_checkpoint(checkpoint, artifact, candidate)


def _candidate_facts(events: tuple[EventRecord, ...]) -> _CandidateFacts:
    persisted: dict[str, EventRecord] = {}
    outcomes: dict[str, EventRecord] = {}
    accepted: dict[str, EventRecord] = {}
    checkpoints: dict[str, EventRecord] = {}
    for event in events:
        if event.type == "candidate_persisted":
            persisted[str(event.payload["candidate_id"])] = event
        elif event.type in {"candidate_certified", "candidate_rejected"}:
            outcomes[str(event.payload["candidate_id"])] = event
        elif event.type == "artifact_accepted":
            accepted[str(event.payload["certification_id"])] = event
        elif event.type == "checkpoint_recorded":
            checkpoints[str(event.payload["certification_id"])] = event
    return _CandidateFacts(persisted, outcomes, accepted, checkpoints)


def _validate_candidate_observation(
    events: tuple[EventRecord, ...], candidate: PersistedCandidate
) -> None:
    observation_event = next(
        (
            event
            for event in events
            if event.type == "dispatch_observed"
            and event.payload["dispatch_id"] == candidate.dispatch_id
        ),
        None,
    )
    if observation_event is None:
        raise ReV2RecoveryError(
            "committed candidate has no corresponding dispatch observation"
        )
    try:
        observed = ExecutionObservation.from_json_dict(
            observation_event.payload["observation"]
        )
    except ReV2ModelError as exc:
        raise ReV2RecoveryError(f"invalid candidate observation event: {exc}") from exc
    if (
        observed != candidate.observation
        or observation_event.payload["work_item_id"] != candidate.work_item_id
    ):
        raise ReV2RecoveryError(
            "committed candidate does not match dispatch observation"
        )


def _certification_for_candidate(
    ledger: LedgerView,
    candidate: PersistedCandidate,
    outcome: EventRecord | None,
) -> CertificationReceipt | None:
    matches = tuple(
        receipt
        for receipt in ledger.certifications.values()
        if receipt.candidate_id == candidate.candidate_id
        and receipt.work_item_id == candidate.work_item_id
    )
    if len(matches) > 1:
        raise ReV2RecoveryError("candidate has conflicting certification receipts")
    certification = matches[0] if matches else None
    if outcome is not None:
        expected_id = str(outcome.payload["certification_id"])
        if certification is None or certification.identity != expected_id:
            raise ReV2RecoveryError(
                "candidate outcome has no matching ledger certification"
            )
    if certification is not None:
        _validate_certification(certification, candidate)
    return certification


def _validate_pinned_certifier(
    certifier: Certifier, candidate: PersistedCandidate
) -> None:
    verifier_id = getattr(certifier, "verifier_id", None)
    verifier_version = getattr(certifier, "verifier_version", None)
    item = candidate.work_item
    if verifier_id != item.verifier_id or verifier_version != item.verifier_version:
        raise ReV2RecoveryError(
            "pinned certifier does not match immutable WorkItem verifier"
        )


def _validate_decision(
    decision: CertificationDecision, candidate: PersistedCandidate
) -> None:
    if not isinstance(decision, CertificationDecision):
        raise ReV2RecoveryError("certifier returned an invalid decision")
    _validate_certification(decision.certification_receipt, candidate)
    if decision.artifact_receipt is not None:
        _validate_artifact(
            decision.artifact_receipt,
            decision.certification_receipt,
            candidate,
        )


def _validate_certification(
    receipt: CertificationReceipt, candidate: PersistedCandidate
) -> None:
    item = candidate.work_item
    key = receipt.certification_key
    if (
        receipt.candidate_id != candidate.candidate_id
        or receipt.work_item_id != candidate.work_item_id
        or key.source_snapshot_id != item.output_key.source_snapshot_id
        or key.verifier_id != item.verifier_id
        or key.verifier_version != item.verifier_version
    ):
        raise ReV2RecoveryError(
            "certification receipt does not match exact candidate WorkItem"
        )


def _validate_outcome(
    outcome: EventRecord,
    certification: CertificationReceipt,
    candidate: PersistedCandidate,
) -> None:
    expected_type = (
        "candidate_certified"
        if certification.verdict == "accepted" and certification.scope_verified
        else "candidate_rejected"
    )
    if (
        outcome.type != expected_type
        or outcome.payload["candidate_id"] != candidate.candidate_id
        or outcome.payload["work_item_id"] != candidate.work_item_id
        or outcome.payload["certification_id"] != certification.identity
    ):
        raise ReV2RecoveryError("candidate outcome conflicts with certification")


def _validate_artifact(
    artifact: ArtifactReceipt,
    certification: CertificationReceipt,
    candidate: PersistedCandidate,
) -> None:
    if (
        artifact.artifact_key != candidate.work_item.output_key
        or artifact.artifact_hash != certification.certification_key.artifact_hash
        or artifact.certification_id != certification.identity
        or artifact.candidate_id != candidate.candidate_id
        or artifact.work_item_id != candidate.work_item_id
    ):
        raise ReV2RecoveryError("artifact receipt conflicts with certified WorkItem")


def _validate_acceptance(
    event: EventRecord, artifact: ArtifactReceipt, candidate: PersistedCandidate
) -> None:
    if dict(event.payload) != {
        "artifact_hash": artifact.artifact_hash,
        "artifact_key_id": artifact.artifact_key.identity,
        "certification_id": artifact.certification_id,
        "work_item_id": candidate.work_item_id,
    }:
        raise ReV2RecoveryError("artifact acceptance event conflicts with ledger")


def _validate_checkpoint(
    event: EventRecord, artifact: ArtifactReceipt, candidate: PersistedCandidate
) -> None:
    if dict(event.payload) != {
        "artifact_hash": artifact.artifact_hash,
        "certification_id": artifact.certification_id,
        "work_item_id": candidate.work_item_id,
    }:
        raise ReV2RecoveryError("checkpoint event conflicts with ledger")


def _rejection_reason(receipt: CertificationReceipt) -> str:
    return (
        "; ".join(receipt.normalized_diagnostics)
        if receipt.normalized_diagnostics
        else "controller certifier rejected candidate"
    )


def _is_paused(events: tuple[EventRecord, ...]) -> bool:
    paused = False
    for event in events:
        if event.type == "run_paused":
            paused = True
        elif event.type == "run_resumed":
            paused = False
    return paused


def _is_terminal(events: tuple[EventRecord, ...]) -> bool:
    return bool(events) and events[-1].type in {
        "run_completed",
        "run_finalized_partial",
        "run_failed",
    }


def _fault(hook: Callable[[str], None] | None, boundary: str) -> None:
    if hook is not None:
        hook(boundary)


def _utc(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise ReV2RecoveryError(f"{field} must be an RFC3339 timestamp")
    try:
        parsed = datetime.fromisoformat(
            value[:-1] + "+00:00" if value.endswith("Z") else value
        )
    except ValueError as exc:
        raise ReV2RecoveryError(f"{field} must be an RFC3339 timestamp") from exc
    if parsed.tzinfo is None:
        raise ReV2RecoveryError(f"{field} must be an RFC3339 timestamp")
    return value


def _elapsed_ms(started_at: str, ended_at: str) -> int:
    start = datetime.fromisoformat(
        started_at[:-1] + "+00:00" if started_at.endswith("Z") else started_at
    )
    end = datetime.fromisoformat(
        ended_at[:-1] + "+00:00" if ended_at.endswith("Z") else ended_at
    )
    if end < start:
        raise ReV2RecoveryError("recovery clock precedes dispatch start")
    delta = end - start
    return (
        delta.days * 86_400_000
        + delta.seconds * 1_000
        + delta.microseconds // 1_000
    )


def _canonical_utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


def _default_process_probe(pid: int) -> str | None:
    if sys.platform.startswith("linux"):
        path = Path(f"/proc/{pid}/stat")
        try:
            data = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        fields = data[data.rfind(")") + 2 :].split()
        if len(fields) <= 19:
            raise ReV2RecoveryError("Linux process identity is ambiguous")
        return f"linux:{fields[19]}"
    if sys.platform == "darwin":
        completed = subprocess.run(
            ["ps", "-o", "lstart=", "-p", str(pid)],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        started = completed.stdout.strip()
        if completed.returncode != 0 or not started:
            return None
        return "macos:" + hashlib.sha256(started.encode("utf-8")).hexdigest()
    raise ReV2RecoveryError("stable process inspection is unsupported")


__all__ = (
    "ProcessInspector",
    "ProcessState",
    "ReV2RecoveryError",
    "ReV2RecoveryResult",
    "ReV2RunContext",
    "next_dispatch_attempt",
    "recover_run",
)
