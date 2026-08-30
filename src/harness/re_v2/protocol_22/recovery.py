"""Authority-first recovery for closed RE v2 protocol 2.2 runs.

The recovery pass is deliberately narrower than the controller: it authenticates
the pinned run, finishes durable transactions that were already started, and
reconciles receipt-before-event crashes.  It never invokes an executor or
producer and never reissues a dispatch once ``dispatch_started`` is durable.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field, replace
import fcntl
import os
import stat
from types import MappingProxyType
from typing import Callable, Iterator, Literal, Mapping, Protocol, TypeAlias

from harness.re_v2.candidates import ProcessIdentity
from harness.re_v2.events import EventRecord, EventStore, ReV2EventError
from harness.re_v2.ledger import ObjectStore, ReV2LedgerError
from harness.re_v2.recovery import ProcessInspector, ProcessState
from harness.re_v2.run_store import (
    ReV2Paths,
    ReV2RunStoreError,
)
from harness.re_v2.protocol_24.model import RunManifestV3
from harness.re_v2.protocol_25.model import RunManifestV4
from harness.re_v2.protocol_26.authority import (
    Protocol26AuthorityError,
    ResolvedRunAuthorityV1,
    resolve_run_authority,
)

from .authorities import (
    AuthorityMismatch,
    InstalledAuthorityRegistry,
    Protocol22AuthorityError,
    validate_installed_authorities,
)
from .baseline import (
    ArtifactAcceptanceReceiptV2,
    CandidateAssessmentReceiptV1,
    CompactCandidateError,
    CompactCertificationAssessmentV2,
    DeterministicCertificationAssessmentV2,
    expanded_retry_diagnostics,
    parse_authorial_candidate,
)
from .budget import BudgetDecisionV2, ReV2BudgetV22Error, evaluate_budget_v22
from .events import PROTOCOL_22_EVENTS
from .execution import (
    CapturedExecutionV1,
    Committed,
    Conflict,
    DeterministicExecutionDependenciesV1,
    Missing,
    PreparationDependenciesV1,
    PreparedExecutionV1,
    Protocol22ExecutionError,
    Protocol22ExecutionStore,
    ProviderExecutionDependenciesV1,
    StagingReady,
    ValidatedCaptureClosureV1,
)
from .graph import (
    AcceptedArtifactV2,
    PlanDecisionV2,
    Protocol22Graph,
    Protocol22GraphError,
    instantiate_ready_item,
    is_shared_planning_graph_v2,
    plan_next_v22,
)
from .inputs import (
    Protocol22InputStoreError,
    ValidatedProtocol22Inputs,
)
from .ledger import (
    ExecutorFailureReceiptV1,
    Protocol22Ledger,
    Protocol22LedgerView,
    WorkItemFailureReceiptV1,
)
from .model import (
    PersistedCandidateV2,
    RunManifestV2,
    WorkItemV2,
)
from .provider import (
    Protocol22ProviderError,
    normalize_captured_provider_usage,
)
from .policies import Protocol22PolicyError, policy_for
from .schema import Protocol22SchemaError, load_canonical_object


FaultHook = Callable[[str], None]
DependenciesResolver = Callable[[WorkItemV2, str], PreparationDependenciesV1]
OperationalState: TypeAlias = Literal[
    "ready",
    "pinned_authority_unavailable",
    "dispatch_owner_live",
    "dispatch_owner_ambiguous",
    "paused",
    "terminal",
]
DispatchAction: TypeAlias = Literal[
    "prepared",
    "adopt_committed",
    "finish_commit",
    "abandon",
    "live_owner",
    "ambiguous_owner",
]

_RESULT_STDOUT = b"echelon_result:\n  schema_version: 1\n  outcome: candidate_ready\n"


class Protocol22RecoveryError(RuntimeError):
    """Raised before execution when persisted protocol-2.2 authority is unsafe."""

    def __init__(self, message: str, *, reason_code: str = "recovery_failed") -> None:
        super().__init__(message)
        self.reason_code = reason_code


class _ProcessInspector(Protocol):
    def inspect(self, identity: ProcessIdentity) -> ProcessState: ...


@dataclass(frozen=True, slots=True)
class PinnedAuthorityUnavailable:
    """Every installed digest mismatch for an otherwise authenticated run."""

    mismatches: tuple[AuthorityMismatch, ...]
    reason_code: Literal["pinned_authority_unavailable"] = (
        "pinned_authority_unavailable"
    )

    def __post_init__(self) -> None:
        if not self.mismatches or any(
            not isinstance(value, AuthorityMismatch) for value in self.mismatches
        ):
            raise Protocol22RecoveryError(
                "pinned-authority unavailable state requires mismatches"
            )
        ordered = tuple(
            sorted(
                self.mismatches,
                key=lambda value: (value.authority_kind, value.authority_id),
            )
        )
        if len(
            {(value.authority_kind, value.authority_id) for value in ordered}
        ) != len(ordered):
            raise Protocol22RecoveryError(
                "pinned-authority mismatch identities must be unique"
            )
        object.__setattr__(self, "mismatches", ordered)


@dataclass(frozen=True, slots=True)
class Protocol22RunContext:
    """All immutable and installed seams required to recover one 2.2 run."""

    paths: ReV2Paths
    inputs: ValidatedProtocol22Inputs
    graph: Protocol22Graph
    event_store: EventStore
    object_store: ObjectStore
    ledger: Protocol22Ledger
    execution_store: Protocol22ExecutionStore
    installed_authorities: InstalledAuthorityRegistry
    dependencies_for: DependenciesResolver
    executors: Mapping[str, object]
    producers: Mapping[str, object]
    verifiers: Mapping[str, object]
    process_inspector: _ProcessInspector = field(default_factory=ProcessInspector)
    clock: Callable[[], str] = field(default_factory=lambda: _utc_now)
    snapshot_validator: Callable[[], None] | None = None
    materialization_validator: Callable[[], None] | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.paths, ReV2Paths):
            raise Protocol22RecoveryError("run context paths are invalid")
        if ReV2Paths.for_run(self.paths.root.parent) != self.paths:
            raise Protocol22RecoveryError("run context paths are not canonical")
        if not isinstance(self.inputs, ValidatedProtocol22Inputs):
            raise Protocol22RecoveryError("run context inputs are not authenticated")
        if not is_shared_planning_graph_v2(self.graph):
            raise Protocol22RecoveryError("run context graph is invalid")
        if not isinstance(self.event_store, EventStore) or (
            self.event_store.path.absolute() != self.paths.events.absolute()
            or not _is_supported_event_protocol(self.event_store.protocol)
        ):
            raise Protocol22RecoveryError("run context event store protocol is invalid")
        if not isinstance(self.object_store, ObjectStore) or (
            self.object_store.root.absolute() != self.paths.objects.absolute()
        ):
            raise Protocol22RecoveryError("run context object store is not run-local")
        if not isinstance(self.ledger, Protocol22Ledger) or (
            self.ledger.path.absolute() != self.paths.ledger.absolute()
            or self.ledger.object_store is not self.object_store
        ):
            raise Protocol22RecoveryError("run context ledger is not run-local")
        if not isinstance(self.execution_store, Protocol22ExecutionStore) or (
            self.execution_store.paths != self.paths
            or self.execution_store.object_store is not self.object_store
        ):
            raise Protocol22RecoveryError(
                "run context execution store is not run-local"
            )
        if not isinstance(self.installed_authorities, InstalledAuthorityRegistry):
            raise Protocol22RecoveryError("run context installed authority is invalid")
        if not callable(self.dependencies_for):
            raise Protocol22RecoveryError("run context has no dependency resolver")
        for name in ("executors", "producers", "verifiers"):
            value = getattr(self, name)
            if not isinstance(value, Mapping) or any(
                not isinstance(key, str) or not key for key in value
            ):
                raise Protocol22RecoveryError(f"run context {name} registry is invalid")
            object.__setattr__(
                self,
                name,
                MappingProxyType(dict(sorted(value.items()))),
            )
        if not callable(getattr(self.process_inspector, "inspect", None)):
            raise Protocol22RecoveryError("run context process inspector is invalid")
        if not callable(self.clock):
            raise Protocol22RecoveryError("run context clock is invalid")
        for callback_name in ("snapshot_validator", "materialization_validator"):
            callback = getattr(self, callback_name)
            if callback is not None and not callable(callback):
                raise Protocol22RecoveryError(f"run context {callback_name} is invalid")


@dataclass(frozen=True, slots=True)
class Protocol22RecoveryResult:
    manifest: RunManifestV2 | RunManifestV3 | RunManifestV4
    inputs: ValidatedProtocol22Inputs
    graph: Protocol22Graph
    events: tuple[EventRecord, ...]
    ledger: Protocol22LedgerView | None
    budget: BudgetDecisionV2 | None
    dispatch_actions: Mapping[str, DispatchAction]
    operational_state: OperationalState
    unavailable: PinnedAuthorityUnavailable | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "dispatch_actions",
            MappingProxyType(dict(sorted(self.dispatch_actions.items()))),
        )
        if (self.operational_state == "pinned_authority_unavailable") != (
            self.unavailable is not None
        ):
            raise Protocol22RecoveryError(
                "recovery unavailable detail does not match operational state"
            )


@dataclass(frozen=True, slots=True)
class _DispatchAuthority:
    started: EventRecord
    item: WorkItemV2
    dependencies: PreparationDependenciesV1
    prepared: PreparedExecutionV1


def recover_protocol_22_run(
    context: Protocol22RunContext,
    fault_hook: FaultHook | None = None,
) -> Protocol22RecoveryResult:
    """Authenticate and reconcile one run without executing unresolved work."""
    if not isinstance(context, Protocol22RunContext):
        raise Protocol22RecoveryError("recovery requires Protocol22RunContext")
    try:
        authority = _validate_immutable_authority(context)
        manifest = authority.layer_manifest
        inputs = authority.shared_inputs
        graph = authority.shared_graph
        _fault(fault_hook, "immutable_authority_validated")
        mismatches = _installed_mismatches(inputs, context.installed_authorities)
    except Protocol22RecoveryError:
        raise
    except (
        Protocol22AuthorityError,
        Protocol22GraphError,
        Protocol22InputStoreError,
        Protocol22SchemaError,
        Protocol26AuthorityError,
        ReV2RunStoreError,
    ) as exc:
        raise Protocol22RecoveryError(
            f"immutable protocol-2.2 authority is invalid: {exc}"
        ) from exc

    # This return deliberately precedes EventStore/Ledger replay: their shared
    # lock acquisition may create lock files, violating non-mutation on drift.
    if mismatches:
        unavailable = PinnedAuthorityUnavailable(mismatches)
        return Protocol22RecoveryResult(
            manifest=manifest,
            inputs=inputs,
            graph=graph,
            events=(),
            ledger=None,
            budget=None,
            dispatch_actions={},
            operational_state="pinned_authority_unavailable",
            unavailable=unavailable,
        )

    return _recover_with_valid_authority(
        context,
        authority,
        fault_hook,
    )


def installed_authority_mismatches(
    inputs: ValidatedProtocol22Inputs,
    registry: InstalledAuthorityRegistry,
) -> tuple[AuthorityMismatch, ...]:
    """Expose the pure installed-versus-pinned authority comparison."""
    if not isinstance(inputs, ValidatedProtocol22Inputs):
        raise Protocol22RecoveryError(
            "authority comparison requires authenticated protocol-2.2 inputs"
        )
    if not isinstance(registry, InstalledAuthorityRegistry):
        raise Protocol22RecoveryError(
            "authority comparison requires InstalledAuthorityRegistry"
        )
    return _installed_mismatches(inputs, registry)


def recover_protocol_22_run_locked(
    context: Protocol22RunContext,
    fault_hook: FaultHook | None = None,
) -> Protocol22RecoveryResult:
    """Recover while the caller owns :func:`protocol_22_run_lock`.

    The immutable and installed authority checks are deliberately repeated so
    callers cannot use this entry point to bypass the non-mutating pinned-
    authority boundary.  This function does not acquire the lock itself.
    """
    if not isinstance(context, Protocol22RunContext):
        raise Protocol22RecoveryError("recovery requires Protocol22RunContext")
    try:
        authority = _validate_immutable_authority(context)
        manifest = authority.layer_manifest
        inputs = authority.shared_inputs
        graph = authority.shared_graph
        mismatches = _installed_mismatches(inputs, context.installed_authorities)
        if mismatches:
            unavailable = PinnedAuthorityUnavailable(mismatches)
            return Protocol22RecoveryResult(
                manifest=manifest,
                inputs=inputs,
                graph=graph,
                events=(),
                ledger=None,
                budget=None,
                dispatch_actions={},
                operational_state="pinned_authority_unavailable",
                unavailable=unavailable,
            )
        return _recover_locked(context, authority, fault_hook)
    except Protocol22RecoveryError:
        raise
    except (
        OSError,
        ReV2BudgetV22Error,
        ReV2EventError,
        ReV2LedgerError,
        Protocol22AuthorityError,
        Protocol22ExecutionError,
        Protocol22GraphError,
        Protocol22InputStoreError,
        Protocol22ProviderError,
        Protocol22SchemaError,
        Protocol26AuthorityError,
        ReV2RunStoreError,
        ValueError,
    ) as exc:
        raise Protocol22RecoveryError(
            f"protocol-2.2 recovery authority is invalid: {exc}"
        ) from exc


def _recover_with_valid_authority(
    context: Protocol22RunContext,
    authority: ResolvedRunAuthorityV1,
    fault_hook: FaultHook | None,
) -> Protocol22RecoveryResult:
    try:
        with _exclusive_run_lock(context.paths):
            return _recover_locked(context, authority, fault_hook)
    except Protocol22RecoveryError:
        raise
    except (
        OSError,
        ReV2BudgetV22Error,
        ReV2EventError,
        ReV2LedgerError,
        Protocol22ExecutionError,
        Protocol22GraphError,
        Protocol22ProviderError,
        Protocol22SchemaError,
        Protocol26AuthorityError,
        ValueError,
    ) as exc:
        raise Protocol22RecoveryError(
            f"protocol-2.2 recovery authority is invalid: {exc}"
        ) from exc


def _recover_locked(
    context: Protocol22RunContext,
    authority: ResolvedRunAuthorityV1,
    fault_hook: FaultHook | None,
) -> Protocol22RecoveryResult:
    """Run the mutating half while one process owns the run lock."""
    manifest = authority.layer_manifest
    inputs = authority.shared_inputs
    graph = authority.shared_graph
    active_manifest = authority.active_manifest
    try:
        events = context.event_store.replay()
        ledger = context.ledger.replay()
        _fault(fault_hook, "event_and_ledger_authority_validated")
        if not events:
            context.event_store.append(
                "run_created",
                {"run_manifest_id": authority.run_manifest_id},
                occurred_at=active_manifest.created_at,
            )
            events = context.event_store.replay()
        _validate_manifest_event(active_manifest, events)
        known_items = _validate_graph_ledger(graph, inputs, ledger, events)
        _validate_event_work_items(events, known_items)
        _validate_materialization(context)
        actions, owner_state = _reconcile_dispatches(
            context,
            events,
            known_items,
            fault_hook,
        )
        events = context.event_store.replay()
        ledger = context.ledger.replay()
        known_items = _validate_graph_ledger(graph, inputs, ledger, events)
        _validate_event_work_items(events, known_items)
        _validate_candidate_events(context, events)
        _reconcile_orphan_receipts(context, events, ledger, known_items, fault_hook)
        events = context.event_store.replay()
        ledger = context.ledger.replay()
        known_items = _validate_graph_ledger(graph, inputs, ledger, events)
        _validate_event_work_items(events, known_items)
        _validate_candidate_events(context, events)
        open_dispatches = _open_dispatch_ids(events)
        budget = evaluate_budget_v22(
            manifest.initial_budget_policy,
            events,
            open_dispatches,
            context.clock(),
            event_protocol=context.event_store.protocol,
        )
        # Recovery finishes the interrupted transaction and yields.  Only a run
        # with no historical dispatch needs a prepared first action here; the
        # controller owns selection of later siblings and retries.
        if (
            owner_state is None
            and not actions
            and _is_pristine_preparation_state(events, ledger)
        ):
            _prepare_next_dispatch(
                context,
                graph,
                ledger,
                budget,
                actions,
                fault_hook,
            )
        state = _operational_state(events, budget, owner_state)
        return Protocol22RecoveryResult(
            manifest=manifest,
            inputs=inputs,
            graph=graph,
            events=events,
            ledger=ledger,
            budget=budget,
            dispatch_actions=actions,
            operational_state=state,
        )
    except Protocol22RecoveryError:
        raise


@contextmanager
def _exclusive_run_lock(paths: ReV2Paths) -> Iterator[None]:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        root_fd = os.open(paths.root, flags)
    except OSError as exc:
        raise Protocol22RecoveryError(
            f"cannot safely open protocol-2.2 run root: {exc}"
        ) from exc
    lock_fd: int | None = None
    try:
        lock_flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_CLOEXEC", 0)
        lock_flags |= getattr(os, "O_NOFOLLOW", 0)
        lock_fd = os.open("recovery.lock", lock_flags, 0o600, dir_fd=root_fd)
        metadata = os.fstat(lock_fd)
        if not stat.S_ISREG(metadata.st_mode):
            raise Protocol22RecoveryError("protocol-2.2 recovery lock is not regular")
        os.fchmod(lock_fd, 0o600)
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        yield
    except Protocol22RecoveryError:
        raise
    except OSError as exc:
        raise Protocol22RecoveryError(
            f"cannot acquire protocol-2.2 recovery lock: {exc}"
        ) from exc
    finally:
        if lock_fd is not None:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
            finally:
                os.close(lock_fd)
        os.close(root_fd)


@contextmanager
def protocol_22_run_lock(paths: ReV2Paths) -> Iterator[None]:
    """Own the one process-wide mutation lock for a protocol-2.2 run."""
    with _exclusive_run_lock(paths):
        yield


def _validate_immutable_authority(
    context: Protocol22RunContext,
) -> ResolvedRunAuthorityV1:
    authority = resolve_run_authority(context)
    if context.snapshot_validator is not None:
        context.snapshot_validator()
    if not _event_protocol_matches_authority(context.event_store.protocol, authority):
        raise Protocol22RecoveryError(
            "event protocol does not match immutable run authority"
        )
    return authority


def _is_supported_event_protocol(protocol: object) -> bool:
    if protocol is PROTOCOL_22_EVENTS:
        return True
    try:
        from harness.re_v2.protocol_24.events import PROTOCOL_24_EVENTS
    except ImportError:
        return False
    if protocol is PROTOCOL_24_EVENTS:
        return True
    try:
        from harness.re_v2.protocol_25.events import PROTOCOL_25_EVENTS
    except ImportError:
        return False
    if protocol is PROTOCOL_25_EVENTS:
        return True
    return getattr(protocol, "PROTOCOL_VERSION", None) == "2.6"


def _event_protocol_matches_authority(
    protocol: object,
    authority: ResolvedRunAuthorityV1,
) -> bool:
    active = authority.active_manifest
    if getattr(active, "engine_protocol_version", None) == "2.6":
        from harness.re_v2.protocol_26.events import protocol_26_events_for

        return protocol == protocol_26_events_for(active.target_layer)
    from harness.re_v2.protocol_24.events import PROTOCOL_24_EVENTS
    from harness.re_v2.protocol_25.events import PROTOCOL_25_EVENTS

    expected = {
        "2.2": PROTOCOL_22_EVENTS,
        "2.3": PROTOCOL_22_EVENTS,
        "2.4": PROTOCOL_24_EVENTS,
        "2.5": PROTOCOL_25_EVENTS,
    }.get(getattr(active, "engine_protocol_version", None))
    return protocol is expected


def _installed_mismatches(
    inputs: ValidatedProtocol22Inputs,
    registry: InstalledAuthorityRegistry,
) -> tuple[AuthorityMismatch, ...]:
    mismatches = list(
        validate_installed_authorities(inputs.executor_contract, registry)
    )
    for kind, authority in (
        ("partitioner", inputs.workspace_partition.partitioner),
        ("ownership", inputs.workspace_partition.ownership_policy),
    ):
        installed = registry.digest_for(kind, authority.id)
        if installed != authority.implementation_digest:
            mismatches.append(
                AuthorityMismatch(
                    authority_kind=kind,
                    authority_id=authority.id,
                    expected_digest=authority.implementation_digest,
                    installed_digest=installed,
                )
            )
    return tuple(
        sorted(
            mismatches,
            key=lambda value: (value.authority_kind, value.authority_id),
        )
    )


def _validate_manifest_event(
    manifest: object,
    events: tuple[EventRecord, ...],
) -> None:
    if (
        not events
        or events[0].type != "run_created"
        or (
            events[0].payload["run_manifest_id"]
            != getattr(manifest, "run_manifest_id", None)
        )
    ):
        raise Protocol22RecoveryError(
            "run_created does not match immutable run manifest"
        )


def _validate_graph_ledger(
    graph: Protocol22Graph,
    inputs: ValidatedProtocol22Inputs,
    ledger: Protocol22LedgerView,
    events: tuple[EventRecord, ...],
) -> Mapping[str, WorkItemV2]:
    by_template = {value.template_id: value for value in graph.templates}
    accepted_by_template: dict[str, AcceptedArtifactV2] = {}
    items: dict[str, WorkItemV2] = {}
    remaining = set(by_template)
    progressed = True
    while remaining and progressed:
        progressed = False
        for template_id in tuple(sorted(remaining)):
            template = by_template[template_id]
            if any(
                dependency not in accepted_by_template
                for dependency in template.required_template_ids
            ):
                continue
            dependencies = {
                dependency: accepted_by_template[dependency]
                for dependency in template.required_template_ids
            }
            item = instantiate_ready_item(template, dependencies, inputs)
            items[item.work_item_id] = item
            accepted = ledger.artifact_for_key(item.output_key.identity)
            if accepted is not None:
                accepted_by_template[template_id] = accepted
            remaining.remove(template_id)
            progressed = True
    adopted_work, adopted_keys = _adopted_graph_exceptions(events)
    for receipt_id, work_item in ledger.certification_work_items.items():
        expected = items.get(work_item.work_item_id)
        if expected is None and work_item.work_item_id in adopted_work:
            items[work_item.work_item_id] = work_item
            continue
        if expected != work_item:
            raise Protocol22RecoveryError(
                f"certification {receipt_id} does not materialize the immutable graph"
            )
    known_keys = {item.output_key.identity for item in items.values()}
    unknown_keys = set(ledger.accepted_artifacts) - known_keys - adopted_keys
    if unknown_keys:
        raise Protocol22RecoveryError(
            "ledger contains an artifact outside the immutable graph"
        )
    known_work = set(items)
    for work_id in ledger.work_item_failures:
        if work_id not in known_work:
            raise Protocol22RecoveryError(
                "ledger contains a work-item failure outside the immutable graph"
            )
    for failure in ledger.executor_failures.values():
        item = items.get(failure.trigger_work_item_id)
        if (
            item is None
            or item.executor_contract_hash != failure.executor_contract_hash
        ):
            raise Protocol22RecoveryError(
                "ledger executor failure does not match immutable work"
            )
    return MappingProxyType(dict(sorted(items.items())))


def _adopted_graph_exceptions(
    events: tuple[EventRecord, ...],
) -> tuple[frozenset[str], frozenset[str]]:
    """Return only event-bound imported work allowed outside selected scope."""
    work_ids: set[str] = set()
    artifact_keys: set[str] = set()
    for event in events:
        if event.type not in {"artifact_adopted", "checkpoint_artifact_adopted"}:
            continue
        from harness.re_v2.protocol_24.model import AdoptedArtifactAuthorityV1

        authority = AdoptedArtifactAuthorityV1.from_json_dict(
            event.payload["adopted_artifact_authority"]
        )
        work_ids.add(str(event.payload["work_item_id"]))
        artifact_keys.add(authority.artifact_key_id)
    return frozenset(work_ids), frozenset(artifact_keys)


def _validate_event_work_items(
    events: tuple[EventRecord, ...],
    known_items: Mapping[str, WorkItemV2],
) -> None:
    for event in events:
        payload = event.payload
        ids: list[str] = []
        if "work_item_id" in payload:
            ids.append(str(payload["work_item_id"]))
        if "trigger_work_item_id" in payload:
            ids.append(str(payload["trigger_work_item_id"]))
        if event.type == "work_planned":
            ids.extend(str(value) for value in payload["work_item_ids"])
        if any(work_id not in known_items for work_id in ids):
            raise Protocol22RecoveryError(
                f"{event.type} references work outside the immutable graph"
            )


def _validate_materialization(context: Protocol22RunContext) -> None:
    if context.materialization_validator is not None:
        context.materialization_validator()


def _dispatch_events(
    events: tuple[EventRecord, ...],
) -> tuple[
    Mapping[str, EventRecord],
    Mapping[str, EventRecord],
    Mapping[str, EventRecord],
]:
    started = {
        str(event.payload["dispatch_id"]): event
        for event in events
        if event.type == "dispatch_started"
    }
    observed = {
        str(event.payload["dispatch_id"]): event
        for event in events
        if event.type == "dispatch_observed"
    }
    abandoned = {
        str(event.payload["dispatch_id"]): event
        for event in events
        if event.type == "dispatch_abandoned"
    }
    return started, observed, abandoned


def _reconcile_dispatches(
    context: Protocol22RunContext,
    events: tuple[EventRecord, ...],
    known_items: Mapping[str, WorkItemV2],
    fault_hook: FaultHook | None,
) -> tuple[dict[str, DispatchAction], OperationalState | None]:
    started, observed, abandoned = _dispatch_events(events)
    actions: dict[str, DispatchAction] = {}
    owner_state: OperationalState | None = None
    _validate_capture_directory_names(context.execution_store, set(started))
    for dispatch_id, start in sorted(started.items(), key=lambda value: value[1].seq):
        authority = _dispatch_authority(context, start, known_items)
        state = context.execution_store.capture_state(dispatch_id)
        if isinstance(state, Conflict):
            raise Protocol22RecoveryError(
                f"capture authority conflicts for {dispatch_id}: {state.reason}"
            )
        if isinstance(state, StagingReady):
            committed = context.execution_store.commit_capture(
                CapturedExecutionV1(
                    capture=state.closure.capture,
                    capture_hash=state.commit.execution_capture_hash,
                    commit=state.commit,
                ),
                fault_hook,
            )
            actions[dispatch_id] = "finish_commit"
            _fault(fault_hook, f"capture_commit_finished:{dispatch_id}")
            state = committed
        elif isinstance(state, Committed):
            actions[dispatch_id] = "adopt_committed"

        if dispatch_id in observed:
            if not isinstance(state, Committed):
                raise Protocol22RecoveryError(
                    f"observed dispatch {dispatch_id} has no committed capture"
                )
            _validate_observation_event(
                observed[dispatch_id],
                state.closure,
                authority.dependencies,
            )
            _reconcile_candidate(
                context,
                state,
                authority.item,
                events,
                fault_hook,
            )
            continue
        if dispatch_id in abandoned:
            if isinstance(state, Committed):
                raise Protocol22RecoveryError(
                    f"abandoned dispatch {dispatch_id} has committed capture authority"
                )
            _validate_abandonment_event(abandoned[dispatch_id], authority)
            actions[dispatch_id] = "abandon"
            continue
        if isinstance(state, Committed):
            _append_observation(
                context,
                state,
                authority.dependencies,
                fault_hook,
            )
            events = context.event_store.replay()
            _reconcile_candidate(
                context,
                state,
                authority.item,
                events,
                fault_hook,
            )
            continue

        assert isinstance(state, Missing)
        lease = context.execution_store.load_started_lease(dispatch_id)
        if lease is not None:
            _validate_started_lease(lease, authority)
            inspected = context.process_inspector.inspect(lease.process_identity)
        else:
            inspected = ProcessState.DEAD
        if inspected is ProcessState.SAME_PROCESS_LIVE:
            actions[dispatch_id] = "live_owner"
            owner_state = "dispatch_owner_live"
            continue
        if inspected is ProcessState.PID_REUSED_OR_AMBIGUOUS:
            actions[dispatch_id] = "ambiguous_owner"
            owner_state = "dispatch_owner_ambiguous"
            continue
        context.event_store.append(
            "dispatch_abandoned",
            {
                "dispatch_id": dispatch_id,
                "execution_input_hash": authority.prepared.execution_input_hash,
                "executor_contract_hash": authority.item.executor_contract_hash,
                "reason_code": "execution_outcome_indeterminate",
                "work_item_id": authority.item.work_item_id,
            },
            occurred_at=context.clock(),
        )
        actions[dispatch_id] = "abandon"
        _fault(fault_hook, f"dispatch_abandoned:{dispatch_id}")
    return actions, owner_state


def _dispatch_authority(
    context: Protocol22RunContext,
    started: EventRecord,
    known_items: Mapping[str, WorkItemV2],
) -> _DispatchAuthority:
    payload = started.payload
    work_item_id = str(payload["work_item_id"])
    item = known_items.get(work_item_id)
    if item is None:
        raise Protocol22RecoveryError(
            "started dispatch work item is outside the immutable graph"
        )
    attempt_kind = str(payload["attempt_kind"])
    dependencies = resolve_execution_dependencies(context, item, attempt_kind)
    if not isinstance(
        dependencies,
        (ProviderExecutionDependenciesV1, DeterministicExecutionDependenciesV1),
    ):
        raise Protocol22RecoveryError(
            "dependency resolver returned no closed execution branch"
        )
    if dependencies.registry != context.installed_authorities:
        raise Protocol22RecoveryError(
            "dispatch dependencies do not use the validated installed authority"
        )
    prepared = context.execution_store.prepare_execution(
        item,
        attempt_kind,
        dependencies,
    )
    context.execution_store.validate_prepared_execution(
        prepared,
        item,
        dependencies,
    )
    expected = {
        "active_ms_reservation": prepared.reservation.active_ms,
        "attempt_index": _expected_attempt_index(
            context.event_store.replay(), item.work_item_id, attempt_kind, started.seq
        ),
        "attempt_kind": attempt_kind,
        "billable_token_reservation": prepared.reservation.billable_tokens,
        "dispatch_id": prepared.dispatch_id,
        "execution_input_hash": prepared.execution_input_hash,
        "executor_contract_hash": item.executor_contract_hash,
        "work_item_id": item.work_item_id,
    }
    if dict(payload) != expected:
        raise Protocol22RecoveryError(
            f"dispatch_started authority mismatch for {prepared.dispatch_id}"
        )
    return _DispatchAuthority(started, item, dependencies, prepared)


def _expected_attempt_index(
    events: tuple[EventRecord, ...],
    work_item_id: str,
    attempt_kind: str,
    through_seq: int,
) -> int:
    return sum(
        1
        for event in events
        if event.seq <= through_seq
        and event.type == "dispatch_started"
        and event.payload["work_item_id"] == work_item_id
        and event.payload["attempt_kind"] == attempt_kind
    )


def _validate_started_lease(lease: object, authority: _DispatchAuthority) -> None:
    expected = (
        authority.prepared.dispatch_id,
        authority.item.work_item_id,
        authority.prepared.execution_input_hash,
        authority.item.executor_contract_hash,
    )
    actual = (
        getattr(lease, "dispatch_id", None),
        getattr(lease, "work_item_id", None),
        getattr(lease, "execution_input_hash", None),
        getattr(lease, "executor_contract_hash", None),
    )
    if actual != expected:
        raise Protocol22RecoveryError("started lease conflicts with dispatch authority")


def _observation_payload(
    closure: ValidatedCaptureClosureV1,
    dependencies: PreparationDependenciesV1,
) -> dict[str, object]:
    capture = closure.capture
    if isinstance(dependencies, DeterministicExecutionDependenciesV1):
        if capture.execution_mode != "in_process":
            raise Protocol22RecoveryError(
                "deterministic dependencies disagree with capture mode"
            )
        raw_status = "not_applicable"
        token_status = "trusted_exact"
        token_usage: int | None = 0
    else:
        if capture.execution_mode not in {"api", "cli"}:
            raise Protocol22RecoveryError(
                "provider dependencies disagree with capture mode"
            )
        raw_status = "valid" if closure.stdout_bytes == _RESULT_STDOUT else "invalid"
        normalized = normalize_captured_provider_usage(
            capture.execution_mode,
            closure.provider_usage_bytes,
            dependencies.executor.token_accounting,
        )
        token_status = normalized.status
        token_usage = normalized.billable_tokens
    return {
        "active_usage_status": "trusted_exact",
        "dispatch_id": capture.dispatch_id,
        "execution_capture_hash": capture.identity,
        "observed_active_ms": capture.duration_ms,
        "raw_result_contract_status": raw_status,
        "reported_token_usage": token_usage,
        "token_usage_status": token_status,
        "work_item_id": capture.work_item_id,
    }


def _append_observation(
    context: Protocol22RunContext,
    committed: Committed,
    dependencies: PreparationDependenciesV1,
    fault_hook: FaultHook | None,
) -> EventRecord:
    event = context.event_store.append(
        "dispatch_observed",
        _observation_payload(committed.closure, dependencies),
        occurred_at=context.clock(),
    )
    _fault(fault_hook, f"dispatch_observed:{committed.dispatch_id}")
    return event


def _validate_observation_event(
    event: EventRecord,
    closure: ValidatedCaptureClosureV1,
    dependencies: PreparationDependenciesV1,
) -> None:
    if dict(event.payload) != _observation_payload(closure, dependencies):
        raise Protocol22RecoveryError(
            f"dispatch_observed disagrees with capture {closure.capture.identity}"
        )


def _validate_abandonment_event(
    event: EventRecord,
    authority: _DispatchAuthority,
) -> None:
    expected = {
        "dispatch_id": authority.prepared.dispatch_id,
        "execution_input_hash": authority.prepared.execution_input_hash,
        "executor_contract_hash": authority.item.executor_contract_hash,
        "reason_code": "execution_outcome_indeterminate",
        "work_item_id": authority.item.work_item_id,
    }
    if dict(event.payload) != expected:
        raise Protocol22RecoveryError("dispatch abandonment authority mismatch")


def _reconcile_candidate(
    context: Protocol22RunContext,
    committed: Committed,
    work_item: WorkItemV2,
    events: tuple[EventRecord, ...],
    fault_hook: FaultHook | None,
) -> None:
    capture = committed.closure.capture
    matching = tuple(
        event
        for event in events
        if event.type == "candidate_persisted"
        and event.payload["dispatch_id"] == capture.dispatch_id
    )
    if capture.execution_mode == "in_process":
        if matching:
            raise Protocol22RecoveryError(
                "deterministic capture has provider candidate authority"
            )
        return
    if len(matching) > 1:
        raise Protocol22RecoveryError("dispatch has duplicate candidate events")
    if matching:
        candidate = _validate_candidate_event(context, matching[0], committed)
    else:
        candidate = context.execution_store.persist_candidate(committed, fault_hook)
        context.event_store.append(
            "candidate_persisted",
            {
                "candidate_id": candidate.candidate_id,
                "candidate_inventory_hash": candidate.candidate_inventory_hash,
                "dispatch_id": candidate.dispatch_id,
                "execution_capture_hash": candidate.execution_capture_hash,
                "work_item_id": candidate.work_item_id,
            },
            occurred_at=context.clock(),
        )
        _fault(fault_hook, f"candidate_persisted:{candidate.candidate_id}")
        events = context.event_store.replay()
    _reconcile_result_reconstruction(
        context,
        work_item,
        committed.closure,
        candidate,
        events,
        fault_hook,
    )


def candidate_reconstructs_result_contract(
    work_item: WorkItemV2,
    closure: ValidatedCaptureClosureV1,
    object_store: ObjectStore,
    inputs: ValidatedProtocol22Inputs,
) -> bool:
    """Return whether one exact provider artifact proves candidate readiness."""
    if not isinstance(work_item, WorkItemV2):
        raise Protocol22RecoveryError("result reconstruction requires WorkItemV2")
    if not isinstance(closure, ValidatedCaptureClosureV1):
        raise Protocol22RecoveryError(
            "result reconstruction requires a validated capture closure"
        )
    if not isinstance(object_store, ObjectStore) or not isinstance(
        inputs, ValidatedProtocol22Inputs
    ):
        raise Protocol22RecoveryError(
            "result reconstruction requires authenticated run authority"
        )
    capture = closure.capture
    inventory = closure.candidate_inventory
    if (
        capture.execution_mode not in {"api", "cli"}
        or capture.work_item_id != work_item.work_item_id
        or inventory is None
        or len(inventory.entries) != 1
    ):
        return False
    entry = inventory.entries[0]
    if (
        entry.relative_path != "baseline.json"
        or entry.object_kind != "regular"
        or entry.content_hash is None
    ):
        return False
    try:
        payload = object_store.read_blob(entry.content_hash)
        policy = policy_for(
            inputs.artifact_policy,
            work_item.output_key.layer,
            work_item.output_key.artifact_kind,
        )
        parse_authorial_candidate(
            payload,
            work_item.output_key.artifact_kind,
            policy,
        )
    except CompactCandidateError:
        return False
    except (ReV2LedgerError, Protocol22PolicyError) as exc:
        raise Protocol22RecoveryError(
            f"candidate reconstruction authority is invalid: {exc}"
        ) from exc
    return True


def _reconcile_result_reconstruction(
    context: Protocol22RunContext,
    work_item: WorkItemV2,
    closure: ValidatedCaptureClosureV1,
    candidate: PersistedCandidateV2,
    events: tuple[EventRecord, ...],
    fault_hook: FaultHook | None,
) -> None:
    observation = next(
        (
            event
            for event in events
            if event.type == "dispatch_observed"
            and event.payload["dispatch_id"] == candidate.dispatch_id
        ),
        None,
    )
    if observation is None:
        raise Protocol22RecoveryError(
            "candidate result reconstruction requires dispatch observation"
        )
    reconstructions = tuple(
        event
        for event in events
        if event.type == "result_contract_reconstructed"
        and event.payload["dispatch_id"] == candidate.dispatch_id
    )
    reconstructable = candidate_reconstructs_result_contract(
        work_item,
        closure,
        context.object_store,
        context.inputs,
    )
    expected = {
        "candidate_id": candidate.candidate_id,
        "dispatch_id": candidate.dispatch_id,
        "result_contract_id": work_item.result_contract_id,
        "work_item_id": work_item.work_item_id,
    }
    if reconstructions:
        if len(reconstructions) != 1 or dict(reconstructions[0].payload) != expected:
            raise Protocol22RecoveryError(
                "result reconstruction event conflicts with candidate authority"
            )
        if (
            not reconstructable
            or observation.payload["raw_result_contract_status"] != "invalid"
        ):
            raise Protocol22RecoveryError(
                "result reconstruction lacks invalid-result candidate authority"
            )
        return
    if (
        reconstructable
        and observation.payload["raw_result_contract_status"] == "invalid"
    ):
        context.event_store.append(
            "result_contract_reconstructed",
            expected,
            occurred_at=context.clock(),
        )
        _fault(fault_hook, f"result_contract_reconstructed:{candidate.candidate_id}")


def _validate_candidate_event(
    context: Protocol22RunContext,
    event: EventRecord,
    committed: Committed,
) -> PersistedCandidateV2:
    candidate_id = str(event.payload["candidate_id"])
    try:
        candidate = load_canonical_object(
            context.object_store.read_blob(candidate_id),
            PersistedCandidateV2.from_json_dict,
        )
    except (Protocol22SchemaError, ReV2LedgerError) as exc:
        raise Protocol22RecoveryError(
            f"persisted candidate {candidate_id} is invalid: {exc}"
        ) from exc
    expected = {
        "candidate_id": candidate.candidate_id,
        "candidate_inventory_hash": candidate.candidate_inventory_hash,
        "dispatch_id": candidate.dispatch_id,
        "execution_capture_hash": candidate.execution_capture_hash,
        "work_item_id": candidate.work_item_id,
    }
    capture = committed.closure.capture
    if dict(event.payload) != expected or (
        candidate.dispatch_id != capture.dispatch_id
        or candidate.work_item_id != capture.work_item_id
        or candidate.execution_capture_hash != capture.identity
        or candidate.candidate_inventory_hash != capture.candidate_inventory_hash
    ):
        raise Protocol22RecoveryError(
            f"candidate {candidate_id} disagrees with committed capture"
        )
    return candidate


def _validate_candidate_events(
    context: Protocol22RunContext,
    events: tuple[EventRecord, ...],
) -> None:
    for event in events:
        if event.type != "candidate_persisted":
            continue
        dispatch_id = str(event.payload["dispatch_id"])
        state = context.execution_store.capture_state(dispatch_id)
        if not isinstance(state, Committed):
            raise Protocol22RecoveryError(
                f"candidate {event.payload['candidate_id']} has no committed capture"
            )
        _validate_candidate_event(context, event, state)


def _reconcile_orphan_receipts(
    context: Protocol22RunContext,
    events: tuple[EventRecord, ...],
    ledger: Protocol22LedgerView,
    known_items: Mapping[str, WorkItemV2],
    fault_hook: FaultHook | None,
) -> None:
    adopted_assessments, adopted_acceptances = _validate_existing_receipt_events(
        context,
        events,
        ledger,
    )
    event_assessments = {
        str(event.payload["candidate_assessment_id"])
        for event in events
        if event.type in {"candidate_certified", "candidate_rejected"}
    } | adopted_assessments
    for receipt_id, receipt in sorted(ledger.candidate_assessments.items()):
        if receipt_id in event_assessments:
            continue
        _validate_orphan_candidate_assessment(events, receipt, ledger, known_items)
        event_type = (
            "candidate_certified"
            if receipt.outcome == "certified"
            else "candidate_rejected"
        )
        context.event_store.append(
            event_type,
            {
                "candidate_assessment_id": receipt.identity,
                "candidate_id": receipt.candidate_id,
                "certification_receipt_id": receipt.certification_receipt_id,
                "work_item_id": receipt.work_item_id,
            },
            occurred_at=context.clock(),
        )
        _fault(fault_hook, f"orphan_receipt_reconciled:{receipt.identity}")
        events = context.event_store.replay()

    event_acceptances = {
        str(event.payload["artifact_acceptance_receipt_id"])
        for event in events
        if event.type == "artifact_accepted"
    } | adopted_acceptances
    for receipt in sorted(
        ledger.accepted_artifacts.values(), key=lambda value: value.identity
    ):
        if receipt.identity in event_acceptances:
            continue
        work_item = ledger.certification_work_items.get(
            receipt.certification_receipt_id
        )
        if work_item is None or known_items.get(work_item.work_item_id) != work_item:
            raise Protocol22RecoveryError(
                "orphan artifact acceptance does not match immutable work"
            )
        assessment_id = _acceptance_assessment_id(ledger, receipt, work_item)
        context.event_store.append(
            "artifact_accepted",
            {
                "artifact_acceptance_receipt_id": receipt.identity,
                "artifact_hash": receipt.artifact_hash,
                "artifact_key_id": receipt.artifact_key.identity,
                "candidate_assessment_id": assessment_id,
                "certification_receipt_id": receipt.certification_receipt_id,
                "work_item_id": work_item.work_item_id,
            },
            occurred_at=context.clock(),
        )
        _fault(fault_hook, f"orphan_receipt_reconciled:{receipt.identity}")
        events = context.event_store.replay()

    event_failures = {
        str(event.payload["failure_receipt_id"])
        for event in events
        if event.type == "work_item_failed"
    }
    for receipt in sorted(
        ledger.work_item_failures.values(), key=lambda value: value.identity
    ):
        if receipt.identity in event_failures:
            continue
        _validate_orphan_work_failure(events, receipt, known_items)
        context.event_store.append(
            "work_item_failed",
            {
                "failure_class": receipt.failure_class,
                "failure_receipt_id": receipt.identity,
                "reason_code": receipt.reason_code,
                "work_item_id": receipt.work_item_id,
            },
            occurred_at=context.clock(),
        )
        _fault(fault_hook, f"orphan_receipt_reconciled:{receipt.identity}")
        events = context.event_store.replay()

    event_executor_failures = {
        str(event.payload["executor_failure_receipt_id"])
        for event in events
        if event.type == "executor_failed"
    }
    for receipt in sorted(
        ledger.executor_failures.values(), key=lambda value: value.identity
    ):
        if receipt.identity in event_executor_failures:
            continue
        _validate_orphan_executor_failure(events, receipt, known_items)
        context.event_store.append(
            "executor_failed",
            {
                "executor_contract_hash": receipt.executor_contract_hash,
                "executor_failure_receipt_id": receipt.identity,
                "trigger_work_item_id": receipt.trigger_work_item_id,
            },
            occurred_at=context.clock(),
        )
        _fault(fault_hook, f"orphan_receipt_reconciled:{receipt.identity}")
        events = context.event_store.replay()


def _validate_existing_receipt_events(
    context: Protocol22RunContext,
    events: tuple[EventRecord, ...],
    ledger: Protocol22LedgerView,
) -> tuple[set[str], set[str]]:
    adopted_assessments: set[str] = set()
    adopted_acceptances: set[str] = set()
    for event in events:
        payload = event.payload
        if event.type in {"artifact_adopted", "checkpoint_artifact_adopted"}:
            from harness.re_v2.protocol_24.model import AdoptedArtifactAuthorityV1

            authority = AdoptedArtifactAuthorityV1.from_json_dict(
                payload["adopted_artifact_authority"]
            )
            if event.type == "artifact_adopted":
                bundle = getattr(context.inputs, "parent_authority_bundle", None)
                if (
                    bundle is None
                    or payload["parent_authority_bundle_hash"] != bundle.identity
                    or authority not in bundle.artifacts
                ):
                    raise Protocol22RecoveryError(
                        "artifact_adopted is outside immutable parent authority"
                    )
            else:
                from harness.re_v2.protocol_26.inputs import load_protocol_26_inputs
                from harness.re_v2.protocol_26.model import RunManifestV5
                from harness.re_v2.run_store import load_run_manifest

                outer = load_run_manifest(context.paths.root.parent)
                if not isinstance(outer, RunManifestV5):
                    raise Protocol22RecoveryError(
                        "checkpoint adoption requires schema-5 authority"
                    )
                frozen = load_protocol_26_inputs(context.paths, outer)
                expected = next(
                    (
                        selected
                        for selected in frozen.checkpoint_selection.selected
                        if selected.source_kind == "workspace_checkpoint"
                        and selected.expected_work_item_id == payload["work_item_id"]
                    ),
                    None,
                )
                if (
                    expected is None
                    or expected.to_event_payload(
                        frozen.checkpoint_selection.identity
                    )
                    != event.to_json_dict()["payload"]
                ):
                    raise Protocol22RecoveryError(
                        "checkpoint adoption is outside immutable selection authority"
                    )
            receipt = ledger.accepted_artifacts.get(authority.artifact_key_id)
            certification = ledger.certifications.get(
                authority.certification_receipt_id
            )
            work_item = ledger.certification_work_items.get(
                authority.certification_receipt_id
            )
            assessment = (
                None
                if authority.candidate_assessment_id is None
                else ledger.candidate_assessments.get(
                    authority.candidate_assessment_id
                )
            )
            if (
                receipt is None
                or receipt.identity != authority.artifact_acceptance_receipt_id
                or receipt.artifact_hash != authority.artifact_hash
                or receipt.certification_receipt_id
                != authority.certification_receipt_id
                or certification is None
                or work_item is None
                or work_item.work_item_id != payload["work_item_id"]
                or work_item.output_key.dependency_hashes
                != authority.dependency_hashes
                or (
                    authority.candidate_assessment_id is not None
                    and assessment is None
                )
            ):
                raise Protocol22RecoveryError(
                    f"{event.type} disagrees with imported receipt authority"
                )
            adopted_acceptances.add(receipt.identity)
            if assessment is not None:
                adopted_assessments.add(assessment.identity)
        elif event.type in {"candidate_certified", "candidate_rejected"}:
            receipt = ledger.candidate_assessments.get(
                str(payload["candidate_assessment_id"])
            )
            if receipt is None or dict(payload) != {
                "candidate_assessment_id": receipt.identity,
                "candidate_id": receipt.candidate_id,
                "certification_receipt_id": receipt.certification_receipt_id,
                "work_item_id": receipt.work_item_id,
            }:
                raise Protocol22RecoveryError(
                    f"{event.type} has no exact candidate-assessment receipt"
                )
        elif event.type == "artifact_accepted":
            receipt = next(
                (
                    value
                    for value in ledger.accepted_artifacts.values()
                    if value.identity == payload["artifact_acceptance_receipt_id"]
                ),
                None,
            )
            if receipt is None:
                raise Protocol22RecoveryError(
                    "artifact_accepted has no exact acceptance receipt"
                )
            work_item = ledger.certification_work_items.get(
                receipt.certification_receipt_id
            )
            if work_item is None or dict(payload) != {
                "artifact_acceptance_receipt_id": receipt.identity,
                "artifact_hash": receipt.artifact_hash,
                "artifact_key_id": receipt.artifact_key.identity,
                "candidate_assessment_id": _acceptance_assessment_id(
                    ledger, receipt, work_item
                ),
                "certification_receipt_id": receipt.certification_receipt_id,
                "work_item_id": work_item.work_item_id,
            }:
                raise Protocol22RecoveryError(
                    "artifact_accepted disagrees with its receipt"
                )
        elif event.type == "work_item_failed":
            receipt = ledger.work_item_failures.get(str(payload["work_item_id"]))
            if receipt is None or dict(payload) != {
                "failure_class": receipt.failure_class,
                "failure_receipt_id": receipt.identity,
                "reason_code": receipt.reason_code,
                "work_item_id": receipt.work_item_id,
            }:
                raise Protocol22RecoveryError(
                    "work_item_failed has no exact failure receipt"
                )
        elif event.type == "executor_failed":
            receipt = ledger.executor_failures.get(
                str(payload["executor_contract_hash"])
            )
            if receipt is None or dict(payload) != {
                "executor_contract_hash": receipt.executor_contract_hash,
                "executor_failure_receipt_id": receipt.identity,
                "trigger_work_item_id": receipt.trigger_work_item_id,
            }:
                raise Protocol22RecoveryError(
                    "executor_failed has no exact executor-failure receipt"
                )
    return adopted_assessments, adopted_acceptances


def _validate_orphan_candidate_assessment(
    events: tuple[EventRecord, ...],
    receipt: CandidateAssessmentReceiptV1,
    ledger: Protocol22LedgerView,
    known_items: Mapping[str, WorkItemV2],
) -> None:
    if receipt.work_item_id not in known_items:
        raise Protocol22RecoveryError(
            "orphan candidate assessment is outside immutable work"
        )
    candidate = next(
        (
            event
            for event in events
            if event.type == "candidate_persisted"
            and event.payload["candidate_id"] == receipt.candidate_id
        ),
        None,
    )
    if candidate is None or (
        candidate.payload["work_item_id"] != receipt.work_item_id
        or candidate.payload["execution_capture_hash"] != receipt.execution_capture_hash
    ):
        raise Protocol22RecoveryError(
            "orphan candidate assessment is premature or conflicts with capture"
        )
    if receipt.certification_receipt_id is not None and (
        receipt.certification_receipt_id not in ledger.certifications
    ):
        raise Protocol22RecoveryError(
            "orphan candidate assessment has no certification authority"
        )


def _acceptance_assessment_id(
    ledger: Protocol22LedgerView,
    receipt: ArtifactAcceptanceReceiptV2,
    work_item: WorkItemV2,
) -> str | None:
    certification = ledger.certifications[receipt.certification_receipt_id]
    if isinstance(certification.assessment, DeterministicCertificationAssessmentV2):
        return None
    if not isinstance(certification.assessment, CompactCertificationAssessmentV2):
        raise Protocol22RecoveryError("acceptance has unsupported certification branch")
    matches = tuple(
        assessment.identity
        for assessment in ledger.candidate_assessments.values()
        if assessment.certification_receipt_id == certification.identity
        and assessment.work_item_id == work_item.work_item_id
        and assessment.outcome == "certified"
    )
    if len(matches) != 1:
        raise Protocol22RecoveryError(
            "provider acceptance requires one exact candidate assessment"
        )
    return matches[0]


def _validate_orphan_work_failure(
    events: tuple[EventRecord, ...],
    receipt: WorkItemFailureReceiptV1,
    known_items: Mapping[str, WorkItemV2],
) -> None:
    item = known_items.get(receipt.work_item_id)
    if item is None:
        raise Protocol22RecoveryError("orphan work failure is outside immutable work")
    dispatch = next(
        (
            event
            for event in events
            if event.type == "dispatch_started"
            and event.payload["dispatch_id"] == receipt.dispatch_id
        ),
        None,
    )
    if dispatch is None or dispatch.payload["work_item_id"] != item.work_item_id:
        raise Protocol22RecoveryError(
            "orphan work failure does not match a final dispatch"
        )
    if receipt.dispatch_abandonment_event_hash is not None:
        abandonment = next(
            (
                event
                for event in events
                if event.type == "dispatch_abandoned"
                and event.payload["dispatch_id"] == receipt.dispatch_id
            ),
            None,
        )
        if (
            abandonment is None
            or abandonment.event_hash != receipt.dispatch_abandonment_event_hash
        ):
            raise Protocol22RecoveryError(
                "orphan work failure abandonment authority mismatch"
            )
    elif not any(
        event.type == "dispatch_observed"
        and event.payload["dispatch_id"] == receipt.dispatch_id
        and event.payload["execution_capture_hash"] == receipt.execution_capture_hash
        for event in events
    ):
        raise Protocol22RecoveryError("orphan work failure capture authority mismatch")
    if receipt.candidate_id is not None and not any(
        event.type == "candidate_persisted"
        and event.payload["candidate_id"] == receipt.candidate_id
        and event.payload["work_item_id"] == receipt.work_item_id
        and event.payload["execution_capture_hash"] == receipt.execution_capture_hash
        for event in events
    ):
        raise Protocol22RecoveryError(
            "orphan work failure candidate authority mismatch"
        )


def _validate_orphan_executor_failure(
    events: tuple[EventRecord, ...],
    receipt: ExecutorFailureReceiptV1,
    known_items: Mapping[str, WorkItemV2],
) -> None:
    item = known_items.get(receipt.trigger_work_item_id)
    if item is None or item.executor_contract_hash != receipt.executor_contract_hash:
        raise Protocol22RecoveryError(
            "orphan executor failure is outside immutable executor work"
        )
    if receipt.dispatch_id is None:
        return
    if not any(
        event.type == "dispatch_observed"
        and event.payload["dispatch_id"] == receipt.dispatch_id
        and event.payload["work_item_id"] == receipt.trigger_work_item_id
        and event.payload["execution_capture_hash"] == receipt.execution_capture_hash
        for event in events
    ):
        raise Protocol22RecoveryError(
            "orphan executor failure is premature or conflicts with capture"
        )


def _prepare_next_dispatch(
    context: Protocol22RunContext,
    graph: Protocol22Graph,
    ledger: Protocol22LedgerView,
    budget: BudgetDecisionV2,
    actions: dict[str, DispatchAction],
    fault_hook: FaultHook | None,
) -> None:
    decision: PlanDecisionV2 = plan_next_v22(graph, ledger, budget)
    if not decision.ready:
        return
    item = decision.ready[0]
    generation_count = budget.generation_attempts.get(item.work_item_id, 0)
    attempt_kind = (
        "initial_generation"
        if generation_count == 0
        else budget.retry_eligibility.get(item.work_item_id)
    )
    if attempt_kind is None:
        return
    dependencies = resolve_execution_dependencies(context, item, attempt_kind)
    if dependencies.registry != context.installed_authorities:
        raise Protocol22RecoveryError(
            "prepared dependencies do not use validated installed authority"
        )
    prepared = context.execution_store.prepare_execution(
        item,
        attempt_kind,
        dependencies,
        fault_hook,
    )
    context.execution_store.validate_prepared_execution(
        prepared,
        item,
        dependencies,
    )
    actions.setdefault(prepared.dispatch_id, "prepared")


def resolve_execution_dependencies(
    context: Protocol22RunContext,
    item: WorkItemV2,
    attempt_kind: str,
) -> PreparationDependenciesV1:
    """Bind retry diagnostics to the immutable dependency resolver output."""
    dependencies = context.dependencies_for(item, attempt_kind)
    if not isinstance(
        dependencies,
        (ProviderExecutionDependenciesV1, DeterministicExecutionDependenciesV1),
    ):
        raise Protocol22RecoveryError(
            "dependency resolver returned no closed execution branch"
        )
    if not isinstance(dependencies, ProviderExecutionDependenciesV1):
        if attempt_kind != "initial_generation":
            raise Protocol22RecoveryError(
                "deterministic execution cannot consume retry diagnostics"
            )
        return dependencies
    diagnostics = _retry_diagnostics(context, item, attempt_kind)
    if dependencies.retry_diagnostics not in {(), diagnostics}:
        raise Protocol22RecoveryError(
            "dependency resolver supplied conflicting retry diagnostics"
        )
    return replace(dependencies, retry_diagnostics=diagnostics)


def _retry_diagnostics(
    context: Protocol22RunContext,
    item: WorkItemV2,
    attempt_kind: str,
) -> tuple[str, ...]:
    if attempt_kind == "initial_generation":
        return ()
    events = context.event_store.replay()
    if attempt_kind == "result_contract_retry":
        abandoned = any(
            event.type == "dispatch_abandoned"
            and event.payload["work_item_id"] == item.work_item_id
            for event in events
        )
        return (
            "execution_outcome_indeterminate" if abandoned else "result_unrecoverable",
        )
    if attempt_kind != "artifact_contract_retry":
        raise Protocol22RecoveryError("unsupported provider retry kind")
    rejected = next(
        (
            event
            for event in reversed(events)
            if event.type == "candidate_rejected"
            and event.payload["work_item_id"] == item.work_item_id
        ),
        None,
    )
    if rejected is None:
        raise Protocol22RecoveryError(
            "artifact retry has no preceding candidate rejection"
        )
    assessment_id = str(rejected.payload["candidate_assessment_id"])
    ledger = context.ledger.replay()
    assessment = next(
        (
            value
            for value in ledger.candidate_assessments.values()
            if value.identity == assessment_id
        ),
        None,
    )
    if assessment is None or not assessment.normalized_diagnostics:
        raise Protocol22RecoveryError(
            "artifact retry has no exact normalized diagnostics"
        )
    return expanded_retry_diagnostics(assessment, ledger.certifications)


def _is_pristine_preparation_state(
    events: tuple[EventRecord, ...],
    ledger: Protocol22LedgerView,
) -> bool:
    return (
        all(event.type in {"run_created", "work_planned"} for event in events)
        and not ledger.certifications
        and not ledger.candidate_assessments
        and not ledger.accepted_artifacts
        and not ledger.work_item_failures
        and not ledger.executor_failures
    )


def _open_dispatch_ids(events: tuple[EventRecord, ...]) -> frozenset[str]:
    started, observed, abandoned = _dispatch_events(events)
    return frozenset(set(started) - set(observed) - set(abandoned))


def _operational_state(
    events: tuple[EventRecord, ...],
    budget: BudgetDecisionV2,
    owner_state: OperationalState | None,
) -> OperationalState:
    if owner_state is not None:
        return owner_state
    if events[-1].type in {"run_completed", "run_failed"}:
        return "terminal"
    last_pause = max(
        (event.seq for event in events if event.type == "run_paused"),
        default=0,
    )
    last_resume = max(
        (event.seq for event in events if event.type == "run_resumed"),
        default=0,
    )
    if last_pause > last_resume:
        return "paused"
    if budget.pause_required:
        return "paused"
    return "ready"


def _validate_capture_directory_names(
    store: Protocol22ExecutionStore,
    started_dispatches: set[str],
) -> None:
    for root, committed in ((store.committed_root, True), (store.staging_root, False)):
        for path in root.iterdir():
            if path.name.startswith("."):
                continue
            dispatch_id = path.name.removesuffix(".json") if committed else path.name
            if dispatch_id not in started_dispatches:
                state = store.capture_state(dispatch_id)
                if isinstance(state, (Committed, StagingReady, Conflict)):
                    raise Protocol22RecoveryError(
                        f"capture authority exists without dispatch_started: {dispatch_id}"
                    )


def _fault(fault_hook: FaultHook | None, boundary: str) -> None:
    if fault_hook is not None:
        fault_hook(boundary)


def _utc_now() -> str:
    from datetime import datetime, timezone

    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


__all__ = (
    "DependenciesResolver",
    "DispatchAction",
    "OperationalState",
    "PinnedAuthorityUnavailable",
    "Protocol22RecoveryError",
    "Protocol22RecoveryResult",
    "Protocol22RunContext",
    "candidate_reconstructs_result_contract",
    "installed_authority_mismatches",
    "protocol_22_run_lock",
    "recover_protocol_22_run",
    "recover_protocol_22_run_locked",
    "resolve_execution_dependencies",
)
