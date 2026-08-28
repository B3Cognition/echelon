"""Replay-first recovery for protocol-2.7 workspace synthesis."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
from types import MappingProxyType
from typing import Callable, Mapping

from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.events import EventRecord, EventStore
from harness.re_v2.ledger import ObjectStore
from harness.re_v2.protocol_22.execution import (
    CapturedExecutionV1,
    Committed,
    Conflict,
    Missing,
    Protocol22ExecutionError,
    StagingReady,
)
from harness.re_v2.protocol_22.model import (
    ExecutionCaptureCommitV1,
    ExecutionCaptureV1,
)
from harness.re_v2.protocol_22.provider import (
    _RESULT_STDOUT,
    normalize_captured_provider_usage,
)
from harness.re_v2.recovery import ProcessInspector, ProcessState
from harness.re_v2.run_store import ReV2Paths
from harness.re_v2.protocol_22.schema import load_canonical_object

from .budget import evaluate_synthesis_budget
from .context import SynthesisContextV1
from .controller import (
    SynthesisControllerStateV1,
    build_synthesis_root,
    plan_next_synthesis,
    reconstruct_synthesis_controller_state,
    synthesis_process_command_hash,
    synthesis_provider_identity_hash,
    synthesis_runtime_failure_reason,
)
from .events import PROTOCOL_27_EVENTS, Protocol27ReplayState
from .execution import (
    Protocol27ExecutionStore,
    build_synthesis_provider_dependencies,
    prepare_synthesis_execution,
    synthesis_candidate_bytes,
)
from .inputs import ValidatedProtocol27Inputs, load_protocol_27_inputs
from .ledger import Protocol27Ledger, Protocol27LedgerView
from .model import SynthesisWorkItemV1
from .runtime import Protocol27DeterministicRuntime, Protocol27RuntimeError


class Protocol27RecoveryError(RuntimeError):
    """Raised when durable synthesis authority cannot be reconciled safely."""


@dataclass(frozen=True, slots=True)
class Protocol27RunContext:
    paths: ReV2Paths
    inputs: ValidatedProtocol27Inputs
    object_store: ObjectStore
    events: EventStore
    ledger: Protocol27Ledger
    execution_store: Protocol27ExecutionStore
    runtime: Protocol27DeterministicRuntime
    process_inspector: object = field(default_factory=ProcessInspector)
    clock: Callable[[], str] = field(
        default_factory=lambda: (
            lambda: datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        )
    )

    def __post_init__(self) -> None:
        if not isinstance(self.paths, ReV2Paths) or self.paths != self.inputs.paths:
            raise Protocol27RecoveryError("synthesis recovery paths are not canonical")
        if not isinstance(self.inputs, ValidatedProtocol27Inputs):
            raise Protocol27RecoveryError("synthesis recovery inputs are not authenticated")
        if (
            not isinstance(self.object_store, ObjectStore)
            or self.object_store.root.absolute() != self.paths.objects.absolute()
        ):
            raise Protocol27RecoveryError("synthesis recovery object store is not run-local")
        if (
            not isinstance(self.events, EventStore)
            or self.events.path.absolute() != self.paths.events.absolute()
        ):
            raise Protocol27RecoveryError("synthesis recovery event store is not run-local")
        if (
            not isinstance(self.ledger, Protocol27Ledger)
            or self.ledger.path.absolute() != self.paths.ledger.absolute()
            or self.ledger.object_store.root.absolute()
            != self.object_store.root.absolute()
        ):
            raise Protocol27RecoveryError("synthesis recovery ledger is not run-local")
        if (
            not isinstance(self.execution_store, Protocol27ExecutionStore)
            or self.execution_store.paths != self.paths
            or self.execution_store.object_store is not self.object_store
        ):
            raise Protocol27RecoveryError("synthesis execution store is not run-local")
        if not isinstance(self.runtime, Protocol27DeterministicRuntime):
            raise Protocol27RecoveryError("synthesis runtime is invalid")
        if not callable(getattr(self.process_inspector, "inspect", None)):
            raise Protocol27RecoveryError("synthesis process inspector is invalid")
        if not callable(self.clock):
            raise Protocol27RecoveryError("synthesis recovery clock is invalid")


@dataclass(frozen=True, slots=True)
class Protocol27RecoveryResult:
    state: SynthesisControllerStateV1
    accepted_artifact_hashes: Mapping[str, str]
    pending_action: str | None
    repaired_boundaries: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "accepted_artifact_hashes",
            MappingProxyType(dict(sorted(self.accepted_artifact_hashes.items()))),
        )


def load_protocol_27_run_context(
    run_dir: Path,
    *,
    process_inspector: object | None = None,
    clock: Callable[[], str] | None = None,
) -> Protocol27RunContext:
    """Load one self-contained child into the established run-local stores."""
    inputs = load_protocol_27_inputs(run_dir)
    objects = ObjectStore(inputs.paths.objects)
    return Protocol27RunContext(
        paths=inputs.paths,
        inputs=inputs,
        object_store=objects,
        events=EventStore(inputs.paths, protocol=PROTOCOL_27_EVENTS),
        ledger=Protocol27Ledger(inputs),
        execution_store=Protocol27ExecutionStore(inputs.paths, objects),
        runtime=Protocol27DeterministicRuntime(objects),
        process_inspector=process_inspector or ProcessInspector(),
        clock=clock or (
            lambda: datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        ),
    )


def recover_protocol_27_run(
    context: Protocol27RunContext,
    fault_hook: Callable[[str], None] | None = None,
) -> Protocol27RecoveryResult:
    """Authenticate and reconcile one synthesis child without provider execution."""
    if not isinstance(context, Protocol27RunContext):
        raise Protocol27RecoveryError("recovery requires Protocol27RunContext")
    repaired: list[str] = []
    _initialize_run(context, repaired, fault_hook)
    events = context.events.replay()
    ledger = context.ledger.replay()
    replay = _replay(events)

    pending = _reconcile_pending_lease(
        context,
        events,
        ledger,
        replay,
        repaired,
        fault_hook,
    )
    events = context.events.replay()
    ledger = context.ledger.replay()
    replay = _replay(events)
    if pending is None:
        pending = _reconcile_active_dispatch(
            context,
            events,
            ledger,
            replay,
            repaired,
            fault_hook,
        )
    events = context.events.replay()
    ledger = context.ledger.replay()
    replay = _replay(events)
    if pending is None:
        _reconcile_root(context, ledger, replay, repaired, fault_hook)
        events = context.events.replay()
        ledger = context.ledger.replay()
        if ledger.synthesis_root is not None:
            from .materialization import (
                validate_or_repair_synthesis_materialization,
            )

            before_materialization = ledger.materialization
            validate_or_repair_synthesis_materialization(context, fault_hook)
            if before_materialization is None:
                repaired.append("synthesis-materialization")
            events = context.events.replay()
            ledger = context.ledger.replay()
    budget = evaluate_synthesis_budget(context.inputs.manifest, events, ledger)
    state = reconstruct_synthesis_controller_state(
        context.inputs,
        ledger,
        events,
        budget,
    )
    return Protocol27RecoveryResult(
        state=state,
        accepted_artifact_hashes={
            key: value.artifact_hash for key, value in ledger.accepted_artifacts.items()
        },
        pending_action=pending,
        repaired_boundaries=tuple(repaired),
    )


def _reconcile_pending_lease(
    context: Protocol27RunContext,
    events: tuple[EventRecord, ...],
    ledger: Protocol27LedgerView,
    replay: Protocol27ReplayState,
    repaired: list[str],
    fault_hook: Callable[[str], None] | None,
) -> str | None:
    if replay.active is not None:
        return None
    referenced = {
        str(event.payload["dispatch_id"])
        for event in events
        if event.type in {"dispatch_leased", "dispatch_lease_retired", "dispatch_started"}
    }
    orphan_ids = tuple(
        sorted(
            path.stem
            for path in context.execution_store.leases_root.glob("*.json")
            if path.is_file() and not path.is_symlink() and path.stem not in referenced
        )
    )
    if replay.lease_dispatch_id is not None and orphan_ids:
        raise Protocol27RecoveryError("active and orphan synthesis leases conflict")
    if len(orphan_ids) > 1:
        raise Protocol27RecoveryError("multiple orphan synthesis leases exist")
    dispatch_id = replay.lease_dispatch_id or (orphan_ids[0] if orphan_ids else None)
    if dispatch_id is None:
        return None
    lease = context.execution_store.load_started_lease(dispatch_id)
    if lease is None:
        raise Protocol27RecoveryError("durable dispatch lease file is missing")
    budget = evaluate_synthesis_budget(context.inputs.manifest, events, ledger)
    state = reconstruct_synthesis_controller_state(
        context.inputs,
        ledger,
        events,
        budget,
    )
    action = plan_next_synthesis(state)
    if action.kind != "dispatch" or action.work_item is None or action.attempt_kind is None:
        raise Protocol27RecoveryError("orphan lease has no exact planner authority")
    item = action.work_item
    dependencies = build_synthesis_provider_dependencies(
        context.inputs,
        item,
        action.retry_diagnostics,
    )
    prepared = prepare_synthesis_execution(
        context.execution_store,
        item,
        dependencies,
        action.attempt_kind,
    )
    _validate_lease(lease, prepared, item)
    if replay.lease_dispatch_id is None:
        context.events.append(
            "dispatch_leased",
            {"dispatch_id": dispatch_id, "work_item_id": item.work_item_id},
            occurred_at=context.clock(),
        )
        repaired.append(f"dispatch-lease-event:{dispatch_id}")
        _fault(fault_hook, "recovery_dispatch_lease_event")
    owner = context.process_inspector.inspect(lease.process_identity)
    if owner is ProcessState.SAME_PROCESS_LIVE:
        return "dispatch-owner-live"
    if owner is ProcessState.PID_REUSED_OR_AMBIGUOUS:
        return "dispatch-owner-ambiguous"
    attempt_index = budget.provider_attempts_by_work_item.get(item.work_item_id, 0) + 1
    context.events.append(
        "dispatch_started",
        {
            "active_ms_reservation": prepared.reservation.active_ms,
            "attempt_index": attempt_index,
            "attempt_kind": action.attempt_kind,
            "billable_token_reservation": prepared.reservation.billable_tokens,
            "dispatch_id": prepared.dispatch_id,
            "execution_input_hash": prepared.execution_input_hash,
            "executor_contract_hash": item.executor_contract_hash,
            "work_item_id": item.work_item_id,
        },
        occurred_at=context.clock(),
    )
    repaired.append(f"dispatch-started:{dispatch_id}")
    _fault(fault_hook, "recovery_dispatch_started")
    _abandon_dispatch(context, prepared, item, repaired, fault_hook)
    return None


def _initialize_run(
    context: Protocol27RunContext,
    repaired: list[str],
    fault_hook: Callable[[str], None] | None,
) -> None:
    events = context.events.replay()
    manifest = context.inputs.manifest
    if not events:
        context.events.append(
            "run_created",
            {"run_manifest_id": manifest.run_manifest_id},
            occurred_at=manifest.created_at,
        )
        repaired.append("run-created")
        _fault(fault_hook, "recovery_run_created")
        events = context.events.replay()
    if (
        events[0].type != "run_created"
        or events[0].payload["run_manifest_id"] != manifest.run_manifest_id
    ):
        raise Protocol27RecoveryError("run creation differs from immutable manifest")
    if not any(event.type == "synthesis_request_frozen" for event in events):
        context.events.append(
            "synthesis_request_frozen",
            {"request_id": manifest.request_id},
            occurred_at=context.clock(),
        )
        repaired.append("request-frozen")
        _fault(fault_hook, "recovery_request_frozen")
    for receipt in manifest.partial_acceptances:
        context.ledger.record_partial_acceptance(receipt)
        existing = {
            str(event.payload["source_id"])
            for event in context.events.replay()
            if event.type == "partial_source_accepted"
        }
        if receipt.source_id not in existing:
            context.events.append(
                "partial_source_accepted",
                {
                    "receipt_id": receipt.receipt_id,
                    "request_id": receipt.operation_id,
                    "source_id": receipt.source_id,
                },
                occurred_at=context.clock(),
            )
            repaired.append(f"partial-source:{receipt.source_id}")
            _fault(fault_hook, f"recovery_partial_source:{receipt.source_id}")


def _reconcile_active_dispatch(
    context: Protocol27RunContext,
    events: tuple[EventRecord, ...],
    ledger: Protocol27LedgerView,
    replay: Protocol27ReplayState,
    repaired: list[str],
    fault_hook: Callable[[str], None] | None,
) -> str | None:
    active = replay.active
    if active is None:
        if replay.lease_dispatch_id is not None:
            lease = context.execution_store.load_started_lease(
                replay.lease_dispatch_id
            )
            if lease is None:
                raise Protocol27RecoveryError("durable dispatch lease file is missing")
            state = context.process_inspector.inspect(lease.process_identity)
            if state is ProcessState.SAME_PROCESS_LIVE:
                return "dispatch-owner-live"
            if state is ProcessState.PID_REUSED_OR_AMBIGUOUS:
                return "dispatch-owner-ambiguous"
            raise Protocol27RecoveryError(
                "dead pre-dispatch lease requires attempt reconciliation"
            )
        return None
    started = next(
        (
            event
            for event in events
            if event.type == "dispatch_started"
            and event.payload["dispatch_id"] == active.dispatch_id
        ),
        None,
    )
    if started is None:
        raise Protocol27RecoveryError("active synthesis dispatch has no durable start")
    item = _work_item_for(context, ledger, active.work_item_id)
    attempt_kind = str(started.payload["attempt_kind"])
    diagnostics = _retry_diagnostics(events, item.work_item_id, started.seq)
    dependencies = build_synthesis_provider_dependencies(
        context.inputs,
        item,
        diagnostics if attempt_kind != "initial_generation" else (),
    )
    prepared = prepare_synthesis_execution(
        context.execution_store,
        item,
        dependencies,
        attempt_kind,
    )
    context.execution_store.validate_prepared_execution(prepared, item, dependencies)
    _validate_started(started, prepared, item, events)
    capture_state = context.execution_store.capture_state(prepared.dispatch_id)
    if isinstance(capture_state, Conflict):
        raise Protocol27RecoveryError(
            f"synthesis capture authority conflicts: {capture_state.reason}"
        )
    if isinstance(capture_state, StagingReady):
        capture_state = context.execution_store.commit_capture(
            CapturedExecutionV1(
                capture=capture_state.closure.capture,
                capture_hash=capture_state.commit.execution_capture_hash,
                commit=capture_state.commit,
            ),
            fault_hook,
        )
        repaired.append(f"capture-commit:{prepared.dispatch_id}")
        _fault(fault_hook, "recovery_capture_committed")
    if isinstance(capture_state, Missing):
        discovered = _discover_uncommitted_capture(context, prepared, item)
        if discovered is not None:
            capture_state = context.execution_store.commit_capture(
                discovered,
                fault_hook,
            )
            repaired.append(f"capture-discovered:{prepared.dispatch_id}")
            _fault(fault_hook, "recovery_capture_discovered")
    if isinstance(capture_state, Missing):
        lease = context.execution_store.load_started_lease(prepared.dispatch_id)
        if lease is None:
            owner = ProcessState.DEAD
        else:
            _validate_lease(lease, prepared, item)
            owner = context.process_inspector.inspect(lease.process_identity)
        if owner is ProcessState.SAME_PROCESS_LIVE:
            return "dispatch-owner-live"
        if owner is ProcessState.PID_REUSED_OR_AMBIGUOUS:
            return "dispatch-owner-ambiguous"
        _abandon_dispatch(context, prepared, item, repaired, fault_hook)
        return None
    assert isinstance(capture_state, Committed)
    closure = capture_state.closure
    observation = _observation_payload(closure, dependencies)
    observed = next(
        (
            event
            for event in events
            if event.type == "dispatch_observed"
            and event.payload["dispatch_id"] == prepared.dispatch_id
        ),
        None,
    )
    if observed is None:
        context.events.append("dispatch_observed", observation, occurred_at=context.clock())
        repaired.append(f"dispatch-observed:{prepared.dispatch_id}")
        _fault(fault_hook, "recovery_dispatch_observed")
    elif not _same_payload(observed.payload, observation):
        raise Protocol27RecoveryError("dispatch observation differs from capture authority")
    if closure.stdout_bytes != _RESULT_STDOUT:
        if not _has_failure_after(
            context.events.replay(), item.work_item_id, started.seq
        ):
            _record_failure(
                context,
                item,
                "execution_indeterminate",
                "execution_outcome_indeterminate",
                closure.capture.identity,
            )
            repaired.append(f"work-failed:{item.work_item_id}")
            _fault(fault_hook, "recovery_work_failed")
        return None
    try:
        payload = synthesis_candidate_bytes(context.execution_store, closure)
    except Protocol22ExecutionError:
        if not _has_failure_after(
            context.events.replay(), item.work_item_id, started.seq
        ):
            _record_failure(
                context,
                item,
                "artifact_contract",
                "candidate_tree_invalid",
                closure.capture.identity,
            )
            repaired.append(f"work-failed:{item.work_item_id}")
        return None
    candidate_id = content_digest(payload)
    assert closure.candidate_inventory is not None
    candidate_event_payload = {
        "candidate_id": candidate_id,
        "candidate_inventory_hash": closure.candidate_inventory.identity,
        "dispatch_id": prepared.dispatch_id,
        "execution_capture_hash": closure.capture.identity,
        "work_item_id": item.work_item_id,
    }
    candidate_event = next(
        (
            event
            for event in context.events.replay()
            if event.type == "candidate_persisted"
            and event.payload["dispatch_id"] == prepared.dispatch_id
        ),
        None,
    )
    if candidate_event is None:
        context.events.append(
            "candidate_persisted",
            candidate_event_payload,
            occurred_at=context.clock(),
        )
        repaired.append(f"candidate-persisted:{item.work_item_id}")
        _fault(fault_hook, "recovery_candidate_persisted")
    elif not _same_payload(candidate_event.payload, candidate_event_payload):
        raise Protocol27RecoveryError("candidate event differs from capture authority")
    typed_context = SynthesisContextV1.from_json_dict(json.loads(dependencies.context_bytes))
    try:
        result = context.runtime.certify_candidate(item, typed_context, payload)
    except (Protocol27RuntimeError, ValueError) as exc:
        if not _has_failure_after(
            context.events.replay(), item.work_item_id, started.seq
        ):
            _record_failure(
                context,
                item,
                "artifact_contract",
                synthesis_runtime_failure_reason(exc),
                closure.capture.identity,
            )
            repaired.append(f"work-failed:{item.work_item_id}")
        return None
    before = context.ledger.replay()
    context.ledger.record_candidate_assessment(result.assessment)
    if item.work_item_id not in before.candidate_assessments:
        repaired.append(f"assessment:{item.work_item_id}")
        _fault(fault_hook, "recovery_assessment")
    before = context.ledger.replay()
    context.ledger.record_synthesis_certification(result.certification)
    if result.certification.artifact_key_id not in before.certifications:
        repaired.append(f"certification:{item.work_item_id}")
        _fault(fault_hook, "recovery_certification")
    before = context.ledger.replay()
    context.ledger.record_synthesis_acceptance(result.acceptance)
    key_id = result.acceptance.artifact_key.artifact_key_id
    if key_id not in before.accepted_artifacts:
        repaired.append(f"acceptance:{item.work_item_id}")
        _fault(fault_hook, "recovery_acceptance")
    generated = _generated_dependency_key_ids(context.inputs, item)
    certification_payload = {
        "artifact_hash": result.acceptance.artifact_hash,
        "artifact_key_id": key_id,
        "candidate_assessment_id": result.assessment.identity,
        "candidate_id": candidate_id,
        "certification_id": result.certification.identity,
        "generated_dependency_key_ids": list(generated),
        "work_item_id": item.work_item_id,
    }
    current_events = context.events.replay()
    certification_event = next(
        (
            event
            for event in current_events
            if event.type == "synthesis_candidate_certified"
            and event.payload["work_item_id"] == item.work_item_id
        ),
        None,
    )
    if certification_event is None:
        context.events.append(
            "synthesis_candidate_certified",
            certification_payload,
            occurred_at=context.clock(),
        )
        repaired.append(f"certification-event:{item.work_item_id}")
        _fault(fault_hook, "recovery_certification_event")
    elif not _same_payload(certification_event.payload, certification_payload):
        raise Protocol27RecoveryError("certification event differs from ledger authority")
    acceptance_payload = {
        "acceptance_receipt_id": result.acceptance.identity,
        "adopted": False,
        "artifact_hash": result.acceptance.artifact_hash,
        "artifact_key_id": key_id,
        "certification_id": result.certification.identity,
        "generated_dependency_key_ids": list(generated),
        "work_item_id": item.work_item_id,
    }
    acceptance_event = next(
        (
            event
            for event in context.events.replay()
            if event.type == "synthesis_artifact_accepted"
            and event.payload["work_item_id"] == item.work_item_id
        ),
        None,
    )
    if acceptance_event is None:
        context.events.append(
            "synthesis_artifact_accepted",
            acceptance_payload,
            occurred_at=context.clock(),
        )
        repaired.append(f"acceptance-event:{item.work_item_id}")
        _fault(fault_hook, "recovery_acceptance_event")
    elif not _same_payload(acceptance_event.payload, acceptance_payload):
        raise Protocol27RecoveryError("acceptance event differs from ledger authority")
    return None


def _reconcile_root(
    context: Protocol27RunContext,
    ledger: Protocol27LedgerView,
    replay: Protocol27ReplayState,
    repaired: list[str],
    fault_hook: Callable[[str], None] | None,
) -> None:
    root = ledger.synthesis_root
    if root is None and len(ledger.accepted_artifacts) == len(
        context.inputs.graph.required_nodes
    ):
        root = build_synthesis_root(context.inputs, ledger)
        context.object_store.put_blob(canonical_json_bytes(root.to_json_dict()))
        context.ledger.record_synthesis_root(root)
        repaired.append("synthesis-root-ledger")
        _fault(fault_hook, "recovery_root_ledger")
    if replay.synthesis_root_id is not None:
        if root is None or replay.synthesis_root_id != root.identity:
            raise Protocol27RecoveryError("root event differs from ledger authority")
        return
    if root is not None:
        context.events.append(
            "synthesis_root_accepted",
            {
                "required_artifact_key_ids": sorted(ledger.accepted_artifacts),
                "synthesis_root_id": root.identity,
            },
            occurred_at=context.clock(),
        )
        repaired.append("synthesis-root-event")
        _fault(fault_hook, "recovery_root_event")


def _work_item_for(
    context: Protocol27RunContext,
    ledger: Protocol27LedgerView,
    work_item_id: str,
) -> SynthesisWorkItemV1:
    accepted = next(
        (
            item
            for item in ledger.accepted_work_items.values()
            if item.work_item_id == work_item_id
        ),
        None,
    )
    if accepted is not None:
        return accepted
    accepted_nodes = {
        context.inputs.graph.node_for_work_item(item).node_id:
        ledger.accepted_artifacts[key].artifact_hash
        for key, item in ledger.accepted_work_items.items()
    }
    matches = tuple(
        item
        for item in context.inputs.graph.ready_work_items(accepted_nodes)
        if item.work_item_id == work_item_id
    )
    if len(matches) != 1:
        raise Protocol27RecoveryError(
            "active work item cannot be reconstructed from graph authority"
        )
    return matches[0]


def _validate_started(
    event: EventRecord,
    prepared,
    item: SynthesisWorkItemV1,
    events: tuple[EventRecord, ...],
) -> None:
    expected_index = sum(
        1
        for candidate in events
        if candidate.seq <= event.seq
        and candidate.type == "dispatch_started"
        and candidate.payload["work_item_id"] == item.work_item_id
    )
    expected = {
        "active_ms_reservation": prepared.reservation.active_ms,
        "attempt_index": expected_index,
        "attempt_kind": prepared.execution_input.attempt_kind,
        "billable_token_reservation": prepared.reservation.billable_tokens,
        "dispatch_id": prepared.dispatch_id,
        "execution_input_hash": prepared.execution_input_hash,
        "executor_contract_hash": item.executor_contract_hash,
        "work_item_id": item.work_item_id,
    }
    if not _same_payload(event.payload, expected):
        raise Protocol27RecoveryError("dispatch start differs from prepared authority")


def _validate_lease(lease, prepared, item: SynthesisWorkItemV1) -> None:  # type: ignore[no-untyped-def]
    if (
        lease.dispatch_id,
        lease.work_item_id,
        lease.execution_input_hash,
        lease.executor_contract_hash,
    ) != (
        prepared.dispatch_id,
        item.work_item_id,
        prepared.execution_input_hash,
        item.executor_contract_hash,
    ):
        raise Protocol27RecoveryError("started lease differs from dispatch authority")
    if (
        lease.process_identity.command_hash
        != synthesis_process_command_hash(item, prepared.execution_input.attempt_kind)
        or lease.process_identity.provider_identity
        != synthesis_provider_identity_hash(item)
    ):
        raise Protocol27RecoveryError("started lease process authority is invalid")


def _discover_uncommitted_capture(
    context: Protocol27RunContext,
    prepared,
    item: SynthesisWorkItemV1,
) -> CapturedExecutionV1 | None:
    matches: list[CapturedExecutionV1] = []
    namespace = context.object_store.root / "sha256"
    for path in namespace.glob("[0-9a-f][0-9a-f]/*"):
        if not path.is_file() or path.is_symlink():
            continue
        digest = f"sha256:{path.parent.name}{path.name}"
        try:
            payload = context.object_store.read_blob(digest)
            capture = load_canonical_object(payload, ExecutionCaptureV1.from_json_dict)
        except Exception:
            continue
        if (
            capture.dispatch_id != prepared.dispatch_id
            or capture.work_item_id != item.work_item_id
            or capture.execution_input_hash != prepared.execution_input_hash
            or capture.executor_contract_hash != item.executor_contract_hash
        ):
            continue
        commit = ExecutionCaptureCommitV1(
            schema_version=1,
            dispatch_id=capture.dispatch_id,
            work_item_id=capture.work_item_id,
            execution_input_hash=capture.execution_input_hash,
            execution_capture_hash=capture.identity,
        )
        context.execution_store.validate_capture_closure(commit)
        matches.append(CapturedExecutionV1(capture, capture.identity, commit))
    unique = {value.capture_hash: value for value in matches}
    if len(unique) > 1:
        raise Protocol27RecoveryError(
            "multiple durable provider captures exist for one synthesis dispatch"
        )
    return next(iter(unique.values()), None)


def _observation_payload(closure, dependencies) -> dict[str, object]:  # type: ignore[no-untyped-def]
    normalized = normalize_captured_provider_usage(
        closure.capture.execution_mode,
        closure.provider_usage_bytes,
        dependencies.executor.token_accounting,
    )
    return {
        "active_usage_status": "trusted_exact",
        "dispatch_id": closure.capture.dispatch_id,
        "execution_capture_hash": closure.capture.identity,
        "observed_active_ms": closure.capture.duration_ms,
        "raw_result_contract_status": (
            "valid" if closure.stdout_bytes == _RESULT_STDOUT else "invalid"
        ),
        "reported_token_usage": normalized.billable_tokens,
        "token_usage_status": normalized.status,
        "work_item_id": closure.capture.work_item_id,
    }


def _retry_diagnostics(
    events: tuple[EventRecord, ...],
    work_item_id: str,
    before_seq: int,
) -> tuple[str, ...]:
    failures = [
        event
        for event in events
        if event.seq < before_seq
        and event.type == "work_item_failed"
        and event.payload["work_item_id"] == work_item_id
    ]
    return () if not failures else (str(failures[-1].payload["reason_code"]),)


def _has_failure_after(
    events: tuple[EventRecord, ...],
    work_item_id: str,
    after_seq: int,
) -> bool:
    return any(
        event.seq > after_seq
        and event.type == "work_item_failed"
        and event.payload["work_item_id"] == work_item_id
        for event in events
    )


def _record_failure(
    context: Protocol27RunContext,
    item: SynthesisWorkItemV1,
    failure_class: str,
    reason: str,
    capture_hash: str,
) -> None:
    receipt_id = context.object_store.put_blob(
        canonical_json_bytes(
            {
                "capture_hash": capture_hash,
                "failure_class": failure_class,
                "reason_code": reason,
                "schema_version": 1,
                "work_item_id": item.work_item_id,
            }
        )
    )
    context.events.append(
        "work_item_failed",
        {
            "failure_class": failure_class,
            "failure_receipt_id": receipt_id,
            "reason_code": reason,
            "work_item_id": item.work_item_id,
        },
        occurred_at=context.clock(),
    )


def _abandon_dispatch(
    context: Protocol27RunContext,
    prepared,
    item: SynthesisWorkItemV1,
    repaired: list[str],
    fault_hook: Callable[[str], None] | None,
) -> None:
    context.events.append(
        "dispatch_abandoned",
        {
            "dispatch_id": prepared.dispatch_id,
            "execution_input_hash": prepared.execution_input_hash,
            "executor_contract_hash": item.executor_contract_hash,
            "reason_code": "execution_outcome_indeterminate",
            "work_item_id": item.work_item_id,
        },
        occurred_at=context.clock(),
    )
    _record_failure(
        context,
        item,
        "execution_indeterminate",
        "execution_outcome_indeterminate",
        prepared.execution_input_hash,
    )
    repaired.append(f"dispatch-abandoned:{prepared.dispatch_id}")
    _fault(fault_hook, "recovery_dispatch_abandoned")


def _generated_dependency_key_ids(
    inputs: ValidatedProtocol27Inputs,
    item: SynthesisWorkItemV1,
) -> tuple[str, ...]:
    node = inputs.graph.node_for_work_item(item)
    fixed = {value.artifact_key_id for value in node.fixed_artifact_dependencies}
    return tuple(sorted(set(item.dependency_key_ids) - fixed))


def _replay(events: tuple[EventRecord, ...]) -> Protocol27ReplayState:
    replay = Protocol27ReplayState()
    for event in events:
        replay.consume(event)
    return replay


def _fault(fault_hook: Callable[[str], None] | None, boundary: str) -> None:
    if fault_hook is not None:
        fault_hook(boundary)


def _same_payload(left: Mapping[str, object], right: Mapping[str, object]) -> bool:
    return canonical_json_bytes(dict(left)) == canonical_json_bytes(dict(right))


__all__ = (
    "Protocol27RecoveryError",
    "Protocol27RecoveryResult",
    "Protocol27RunContext",
    "load_protocol_27_run_context",
    "recover_protocol_27_run",
)
