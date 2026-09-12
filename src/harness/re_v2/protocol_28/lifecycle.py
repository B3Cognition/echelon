"""Publication, exact reuse, continuation, and execution for protocol 2.8."""

from __future__ import annotations

from dataclasses import dataclass, replace
import json
from pathlib import Path
import os
from typing import Callable, Literal, Mapping, Protocol

from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.protocol_22.provider import DispatchReservationV1
from harness.re_v2.protocol_22.schema import load_canonical_object
from harness.re_v2.protocol_28.artifacts import (
    ExhaustiveDiagnosticV1,
    ExhaustiveEvidenceSliceV1,
    ExhaustiveRepairPacketV1,
    ExhaustiveVerificationV1,
    Protocol28ArtifactError,
)
from harness.re_v2.protocol_28.budget import PairedReservationCommitV1
from harness.re_v2.protocol_28.checkpoint_cache import (
    copy_selected_checkpoint_objects,
    load_checkpoint_cache_v2,
    publish_checkpoint_cache_v2,
)
from harness.re_v2.protocol_28.checkpoints import (
    CheckpointManifestV2,
    CheckpointSelectionBundleV2,
    Protocol28CheckpointError,
)
from harness.re_v2.protocol_28.context import (
    Protocol28RunContext,
    build_protocol_28_slice_context,
    initialize_protocol_28_run,
    load_protocol_28_run_context,
)
from harness.re_v2.protocol_28.execution import (
    L4ExecutionEnvelopeV1,
    L4CandidateReceiptV1,
    L4ExecutionCaptureV1,
    L4VerificationReceiptV1,
    PersistedL4ExecutionV1,
    Protocol28ExecutionError,
    certify_and_accept,
    persist_provider_result,
    record_candidate_result,
    record_verification_result,
)
from harness.re_v2.protocol_28.executors import RoleV1
from harness.re_v2.protocol_28.events import replay_protocol_28
from harness.re_v2.protocol_28.graph import (
    AcceptedExhaustiveSliceV1,
    L4SourceRootV1,
    L4TargetRootV1,
    build_run_root,
    build_source_root,
    build_target_root,
)
from harness.re_v2.protocol_28.inputs import (
    FaultHook,
    Protocol28CreationInputs,
    publish_protocol_28_run,
    stage_exhaustive_inputs,
)
from harness.re_v2.protocol_28.model import ExhaustiveRunManifestV7
from harness.re_v2.protocol_28.planning import (
    ExhaustiveTargetPlanV1,
    SlicePlanEntryV1,
    SliceSpecV1,
    realize_slice,
)
from harness.re_v2.protocol_28.preparation import (
    Protocol28PreparationOptions,
    prepare_protocol_28_request,
)
from harness.re_v2.run_store import load_run_manifest


class Protocol28LifecycleError(RuntimeError):
    """Raised when an exact protocol-2.8 child cannot be used safely."""


def _candidate_contract_failure_code(exc: Protocol28ExecutionError) -> str:
    """Classify a producer failure without exposing provider output or source data."""
    current: BaseException | None = exc
    while current is not None:
        if isinstance(current, Protocol28ArtifactError):
            return current.reason_code
        current = current.__cause__
    return "malformed-result-contract"


def _execution_failure_code(persisted: PersistedL4ExecutionV1, exc: Protocol28ExecutionError) -> str:
    if persisted.capture.result_kind == "provider_timeout":
        return "provider-timeout"
    if persisted.capture.result_kind == "provider_failure":
        return "provider-execution-failed"
    return _candidate_contract_failure_code(exc)


def _attempts_exhausted_reason(context, slice_spec, role, fallback):  # type: ignore[no-untyped-def]
    """Use the last durable outcome, including after interrupted capture recovery."""
    kinds = ({"candidate_rejected", "candidate_recorded"} if role == "producer"
             else {"verification_rejected", "verification_recorded"})
    for event in reversed(context.events.replay()):
        if (event.type in kinds and event.payload.get("output_artifact_key_id")
                == slice_spec.output_artifact_key_id):
            reason = event.payload.get("reason_code")
            if reason in {"provider-timeout", "provider-execution-failed"}:
                return f"{role}_{reason.replace('-', '_')}_attempts_exhausted"
            break
    return fallback


def _resource_block_reason(context, preview):  # type: ignore[no-untyped-def]
    if context.resources.decision.reservation_breaches:
        return "l4_reservation_breach"
    return "l4_" + "_and_".join(preview.exhausted_dimensions) + "_budget_exhausted"


def _producer_contract_failure_codes(
    context: Protocol28RunContext,
    slice_spec: SliceSpecV1,
) -> tuple[str, ...]:
    """Recover durable producer correction hints for one immutable slice."""
    return tuple(
        sorted(
            {
                str(event.payload["reason_code"])
                for event in context.events.replay()
                if event.type == "candidate_rejected"
                and event.payload["output_artifact_key_id"]
                == slice_spec.output_artifact_key_id
                and event.payload["reason_code"] in {
                    "malformed-result-contract",
                    "missing-primary-evidence-anchors",
                    "unresolved-findings-not-addressed",
                }
            }
        )
    )


@dataclass(frozen=True, slots=True)
class _VerifierRetryBlocked:
    reason_code: str


@dataclass(frozen=True, slots=True)
class L4DispatchResultV1:
    raw_result: bytes
    provider_name: str
    model_revision: str | None
    started_at: str
    ended_at: str
    duration_ms: int
    result_kind: Literal["provider_result", "provider_failure", "provider_timeout"] = "provider_result"
    token_status: Literal["trusted_exact", "unavailable", "untrusted"] = "unavailable"
    billable_tokens: int | None = None
    active_status: Literal["trusted_exact", "unavailable", "untrusted"] = "unavailable"
    active_ms: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.raw_result, bytes):
            raise Protocol28LifecycleError("L4 provider result bytes are invalid")
        if not isinstance(self.provider_name, str) or not self.provider_name:
            raise Protocol28LifecycleError("L4 provider name is required")
        if self.result_kind not in {"provider_result", "provider_failure", "provider_timeout"}:
            raise Protocol28LifecycleError("L4 provider result kind is invalid")


class L4ExecutionBackend(Protocol):
    def execute(
        self,
        role: RoleV1,
        agent_bytes: bytes,
        context_bytes: bytes,
        response_schema_bytes: bytes,
        reservation: DispatchReservationV1,
    ) -> L4DispatchResultV1: ...


@dataclass(frozen=True, slots=True)
class Protocol28RunResult:
    run_id: str
    state: str
    run_root_id: str | None
    reason_code: str | None
    accepted_slices: int
    planned_slices: int


@dataclass(frozen=True, slots=True)
class Protocol28CheckpointAdoptionV1:
    selection: CheckpointSelectionBundleV2
    manifests_by_id: Mapping[str, CheckpointManifestV2]
    authority_objects: Mapping[str, Mapping[str, bytes]]


def find_exact_protocol_28_child(
    workspace_root: Path,
    request_id: str,
) -> Path | None:
    """Find the only published exhaustive child for one semantic request."""
    runs = Path(workspace_root).resolve() / "runs"
    if not runs.is_dir() or runs.is_symlink():
        return None
    matches: list[Path] = []
    for candidate in sorted(runs.iterdir(), key=lambda item: item.name):
        if candidate.name.startswith(".") or candidate.is_symlink():
            continue
        manifest_path = candidate / "v2" / "run.json"
        if not manifest_path.is_file() or manifest_path.is_symlink():
            continue
        try:
            raw = json.loads(manifest_path.read_bytes())
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        if not isinstance(raw, dict) or (
            raw.get("schema_version"),
            raw.get("engine_protocol_version"),
            raw.get("run_mode"),
        ) != (7, "2.8", "exhaustive-depth"):
            continue
        try:
            manifest = load_run_manifest(candidate)
        except Exception as exc:
            raise Protocol28LifecycleError(
                f"invalid protocol-2.8 child manifest: {candidate.name}"
            ) from exc
        if (
            isinstance(manifest, ExhaustiveRunManifestV7)
            and manifest.exhaustive_request.request_id == request_id
        ):
            matches.append(candidate)
    if len(matches) > 1:
        raise Protocol28LifecycleError(
            "multiple protocol-2.8 exhaustive children share one exact request identity"
        )
    return matches[0] if matches else None


def create_or_reuse_protocol_28_child(
    workspace_root: Path,
    inputs: Protocol28CreationInputs,
    *,
    checkpoint_adoption: Protocol28CheckpointAdoptionV1 | None = None,
    fault_hook: FaultHook | None = None,
) -> Path:
    """Publish one immutable exhaustive child, initialize it, and activate it."""
    if not isinstance(inputs, Protocol28CreationInputs):
        raise Protocol28LifecycleError(
            "protocol-2.8 child creation requires validated creation inputs"
        )
    root = Path(workspace_root).resolve()
    request_id = inputs.manifest.exhaustive_request.request_id
    existing = find_exact_protocol_28_child(root, request_id)
    if existing is None:
        runs = root / "runs"
        final = runs / inputs.manifest.run_id
        stage = runs / f".{inputs.manifest.run_id}.stage"
        if stage.exists() or stage.is_symlink():
            raise Protocol28LifecycleError(
                f"private protocol-2.8 stage already exists: {stage.name}"
            )
        stage_exhaustive_inputs(stage, inputs, fault_hook=fault_hook)
        publish_protocol_28_run(stage, final, inputs.manifest)
        existing = final
    context = load_protocol_28_run_context(existing)
    initialize_protocol_28_run(context)
    if checkpoint_adoption is not None:
        adopt_protocol_28_checkpoints(context, checkpoint_adoption)
    from echelon.cli import _activate_re_v2_run

    _activate_re_v2_run(root, existing.name)
    return existing


def adopt_protocol_28_checkpoints(
    context: Protocol28RunContext,
    adoption: Protocol28CheckpointAdoptionV1,
) -> tuple[str, ...]:
    """Copy, reauthenticate, and ledger selected V2 checkpoints before dispatch."""
    if not isinstance(context, Protocol28RunContext) or not isinstance(
        adoption, Protocol28CheckpointAdoptionV1
    ):
        raise Protocol28LifecycleError("protocol-2.8 checkpoint adoption is invalid")
    selection = adoption.selection
    for item in selection.selected:
        context.controller.append_once(
            "checkpoint_discovered",
            {
                "checkpoint_manifest_id": item.checkpoint_manifest_id,
                "output_artifact_key_id": item.output_artifact_key_id,
            },
        )
    for items, event_type in (
        (selection.rejected, "checkpoint_rejected"),
        (selection.quarantined, "checkpoint_quarantined"),
    ):
        for item in items:
            context.controller.append_once(
                event_type,
                {
                    "checkpoint_manifest_id": item.checkpoint_manifest_id,
                    "output_artifact_key_id": item.output_artifact_key_id,
                    "reason_code": item.reason,
                },
            )
    copied = copy_selected_checkpoint_objects(
        selection,
        adoption.manifests_by_id,
        adoption.authority_objects,
        context.paths.objects,
    )
    for selected in selection.selected:
        checkpoint = adoption.manifests_by_id[selected.checkpoint_manifest_id]
        entry = checkpoint.plan_entry
        spec = checkpoint.slice_spec
        context.controller.append_once(
            "slice_realized",
            {
                "output_artifact_key_id": spec.output_artifact_key_id,
                "plan_entry_id": entry.identity,
                "slice_spec_id": spec.identity,
            },
        )
        context.controller.append_once(
            "checkpoint_staged",
            {
                "checkpoint_manifest_id": checkpoint.identity,
                "copied_object_count": len(checkpoint.immutable_object_hashes),
                "output_artifact_key_id": spec.output_artifact_key_id,
            },
        )
        producer_envelope, producer_capture = _checkpoint_execution(
            context, checkpoint.accepted_slice.producer_execution_capture_hash
        )
        verifier_envelope, verifier_capture = _checkpoint_execution(
            context, checkpoint.accepted_slice.verifier_execution_capture_hash
        )
        context.ledger.record_execution_capture(producer_envelope, producer_capture)
        context.ledger.record_execution_capture(verifier_envelope, verifier_capture)
        context.ledger.record_candidate(
            L4CandidateReceiptV1(
                1,
                spec.identity,
                entry.identity,
                checkpoint.candidate.identity,
                producer_capture.identity,
            )
        )
        context.ledger.record_verification(
            L4VerificationReceiptV1(
                1,
                spec.identity,
                entry.identity,
                checkpoint.candidate.identity,
                checkpoint.verification.identity,
                verifier_capture.identity,
                "PASS",
            )
        )
        context.ledger.record_certification(checkpoint.certification_receipt)
        context.ledger.record_acceptance(checkpoint.acceptance_receipt)
        context.ledger.record_accepted_slice(checkpoint.accepted_slice)
        avoided = DispatchReservationV1(
            max(entry.canonical_context_bytes, 1),
            max(entry.conservative_tokens, 1),
            300_000,
        )
        context.resources.record_adoption(
            spec.identity,
            producer_reservation=avoided,
            verifier_reservation=avoided,
        )
        _record_acceptance_events(context, checkpoint.accepted_slice)
        context.controller.append_once(
            "checkpoint_adopted",
            {
                "accepted_slice_id": checkpoint.accepted_slice.identity,
                "checkpoint_manifest_id": checkpoint.identity,
                "output_artifact_key_id": spec.output_artifact_key_id,
            },
        )
    return copied


def _checkpoint_execution(
    context: Protocol28RunContext,
    capture_id: str,
) -> tuple[L4ExecutionEnvelopeV1, L4ExecutionCaptureV1]:
    capture = load_canonical_object(
        context.objects.read_blob(capture_id),
        L4ExecutionCaptureV1.from_json_dict,
    )
    envelope = load_canonical_object(
        context.objects.read_blob(capture.execution_envelope_id),
        L4ExecutionEnvelopeV1.from_json_dict,
    )
    return envelope, capture


def run_protocol_28_exhaustive(
    run_dir: Path,
    provider_factory: Callable[[], L4ExecutionBackend],
) -> Protocol28RunResult:
    """Recover accepted work and execute only unresolved exact L4 slices."""
    context = load_protocol_28_run_context(Path(run_dir))
    if not isinstance(context, Protocol28RunContext):
        raise Protocol28LifecycleError(
            "exhaustive execution requires exhaustive-depth mode"
        )
    if replay_protocol_28(context.events.replay()).knowledge_authorization_id is not None:
        from harness.re_v2.protocol_22.recovery import protocol_22_run_lock
        with protocol_22_run_lock(context.paths):
            context = load_protocol_28_run_context(Path(run_dir))
            try:
                return _run_protocol_28_context(context, provider_factory)
            except Protocol28LifecycleError:
                state = replay_protocol_28(context.events.replay())
                if state.blocker_kind is None:
                    raise
                reason = next(e.payload['reason_code'] for e in reversed(context.events.replay()) if e.type == 'run_blocked')
                return _result(context, 'needs-attention', None, reason)
    return _run_protocol_28_context(context, provider_factory)


def _run_protocol_28_context(context, provider_factory):
    from harness.re_v2.knowledge_revision import load_knowledge_revision
    from harness.re_v2.protocol_28.reconciliation import (build_reconciliation_work, execute_reconciliation,
        build_reviewed_run_root, knowledge_completion_event_payload)
    reviewed = load_knowledge_revision(context)
    state = replay_protocol_28(context.events.replay())
    if reviewed is None and state.knowledge_activation_intent_id is not None:
        raise Protocol28LifecycleError('knowledge activation is incomplete; retry explicit activation')
    if state.knowledge_revision_intent_id is not None:
        raise Protocol28LifecycleError('knowledge revision is incomplete; retry explicit revision')
    if reviewed is not None and (state.terminal or state.blocker_kind is not None):
        # Authenticated terminal/status replay never repairs projections or exports caches.
        reason = next((e.payload['reason_code'] for e in reversed(context.events.replay()) if e.type == 'run_blocked'), None) if state.blocker_kind else None
        return _result(context, state.lifecycle_state, state.run_root_id, reason)
    initialize_protocol_28_run(context)
    _catch_up_ledger_events(context)
    state = replay_protocol_28(context.events.replay())
    if state.run_root_id is not None:
        if reviewed is not None:
            root = context.ledger.replay().knowledge_run_roots[state.run_root_id]
            context.controller.append_once('knowledge_run_completed', knowledge_completion_event_payload(root))
            state = replay_protocol_28(context.events.replay())
        return _result(context, state.lifecycle_state, state.run_root_id, None)
    provider_or_backend = provider_factory()
    if hasattr(provider_or_backend, "execute"):
        backend = provider_or_backend
    elif hasattr(provider_or_backend, "exec_agent"):
        if reviewed is not None:
            raise Protocol28LifecycleError('reviewed knowledge requires an explicit screened execution backend')
        from harness.re_v2.protocol_28.cli_provider import (
            SquadCliProtocol28Backend,
        )

        backend = SquadCliProtocol28Backend(lambda: provider_or_backend)  # type: ignore[arg-type]
    else:
        raise Protocol28LifecycleError("protocol-2.8 provider backend is invalid")

    if reviewed is not None:
        view = context.ledger.replay()
        target_roots = tuple(view.knowledge_roots[i] for i in state.target_root_ids)
        root_by_plan = {item.plan_id: item for item in target_roots}
    else:
        target_roots = _load_recorded_target_roots(context, state.target_root_ids)
        root_by_plan = {item.target_plan_id: item for item in target_roots}
    ordered_plans = tuple(
        sorted(
            context.inputs.exhaustive_plan.target_plans,
            key=lambda item: (item.target_kind == "source", item.sort_key),
        )
    )
    for target_plan in ordered_plans:
        if target_plan.identity in root_by_plan:
            continue
        dependency_plan_ids = {
            dependency
            for entry in target_plan.entries
            for dependency in entry.planned_dependency_root_ids
        }
        if not dependency_plan_ids <= set(root_by_plan):
            raise Protocol28LifecycleError(
                "source composition dependencies are not durably complete"
            )
        dependency_roots = {
            plan_id: root_by_plan[plan_id].identity
            for plan_id in dependency_plan_ids
        }
        accepted_for_target = []
        for entry in target_plan.entries:
            realize = realize_slice
            if reviewed is not None:
                from harness.re_v2.knowledge_revision import realize_knowledge_slice
                realize = lambda selected, roots: realize_knowledge_slice(context, reviewed, selected, roots)
            slice_spec = realize(
                entry,
                {
                    dependency: dependency_roots[dependency]
                    for dependency in entry.planned_dependency_root_ids
                },
            )
            context.controller.append_once(
                "slice_realized",
                {
                    "output_artifact_key_id": slice_spec.output_artifact_key_id,
                    "plan_entry_id": entry.identity,
                    "slice_spec_id": slice_spec.identity,
                },
            )
            accepted = context.ledger.replay().accepted_slices.get(
                slice_spec.output_artifact_key_id
            )
            if accepted is None:
                outcome = _execute_slice(
                    context, backend, target_plan, entry, slice_spec
                )
                if isinstance(outcome, str):
                    projection = context.controller.rebuild_projection()
                    return _result(
                        context,
                        projection.lifecycle_state,
                        projection.run_root_id,
                        outcome,
                    )
                accepted = outcome
            accepted_for_target.append(accepted)
        if reviewed is not None:
            work = build_reconciliation_work(context, target_plan, scope='target', input_results=tuple(accepted_for_target))
            root = execute_reconciliation(context, backend, work)
            if isinstance(root, str):
                return _result(context, 'needs-attention', None, root)
        else:
            root = build_target_root(target_plan, tuple(accepted_for_target))
            context.controller.record_root(root, root_kind="target")
        root_by_plan[target_plan.identity] = root

    if reviewed is not None:
        target_roots = tuple(sorted(root_by_plan.values(), key=lambda r: r.identity))
        sources = []
        for source_id in sorted({r.source_id for r in target_roots}):
            source_plan = next(t for t in ordered_plans if t.source_id == source_id and t.target_kind == 'source')
            work = build_reconciliation_work(context, source_plan, scope='source',
                input_results=tuple(r for r in target_roots if r.source_id == source_id))
            root = execute_reconciliation(context, backend, work)
            if isinstance(root, str):
                return _result(context, 'needs-attention', None, root)
            sources.append(root)
        run_root = build_reviewed_run_root(context, target_roots, tuple(sources))
        context.objects.put_blob(canonical_json_bytes(run_root.to_json_dict()))
        context.ledger.record_knowledge_run_root(run_root)
        context.controller.record_knowledge_root(run_root)
        context.controller.append_once('knowledge_run_completed', knowledge_completion_event_payload(run_root))
        return _result(context, 'complete-with-limitations' if run_root.debt_ids else 'complete', run_root.identity, None)

    target_roots = tuple(
        sorted(root_by_plan.values(), key=lambda item: item.sort_key)
    )
    source_roots = _build_source_roots(context, target_roots)
    run_root = build_run_root(
        context.inputs.exhaustive_plan,
        target_roots,
        source_roots,
        context.inputs.exhaustive_plan.completion_scope,
    )
    context.controller.record_root(run_root, root_kind="run")
    return _result(context, "evidence_complete", run_root.identity, None)


def continue_protocol_28_run(
    run_dir: Path,
    *,
    token_limit: int | None,
    active_ms_limit: int | None,
    provider_factory: Callable[[], L4ExecutionBackend],
) -> Protocol28RunResult:
    """Append only monotonic resource authority, then resume exact work."""
    context = load_protocol_28_run_context(Path(run_dir))
    if not isinstance(context, Protocol28RunContext):
        raise Protocol28LifecycleError(
            "L4 closure-successor mode does not accept resource authorization"
        )
    for dimension, value in (
        ("tokens", token_limit),
        ("active_ms", active_ms_limit),
    ):
        if value is None:
            continue
        authorization = context.resources.authorize(dimension, value)  # type: ignore[arg-type]
        context.controller.append_once(
            "resource_authorized",
            {
                "authorized_by": "operator",
                "dimension": dimension,
                "new_value": authorization.new_value,
                "old_value": authorization.old_value,
            },
        )
    return run_protocol_28_exhaustive(run_dir, provider_factory)


def _execute_slice(
    context: Protocol28RunContext,
    backend: L4ExecutionBackend,
    target_plan: ExhaustiveTargetPlanV1,
    entry: SlicePlanEntryV1,
    slice_spec: SliceSpecV1,
):  # type: ignore[no-untyped-def]
    events = context.events.replay()
    replayed = replay_protocol_28(events)
    if slice_spec.output_artifact_key_id in replayed.failed_output_ids:
        terminal = next(
            event
            for event in events
            if event.type == "slice_failed"
            and event.payload["output_artifact_key_id"]
            == slice_spec.output_artifact_key_id
        )
        return str(terminal.payload["reason_code"])
    diagnostics: tuple[ExhaustiveDiagnosticV1, ...] = ()
    previous_diagnostic_ids: tuple[str, ...] = ()
    policy = context.inputs.exhaustive_policy
    executors = context.inputs.executor_catalog
    producer_entry = executors.entry("producer")
    verifier_entry = executors.entry("verifier")
    producer_agent = _authority_bytes(context, producer_entry.agent_contract_hash)
    verifier_agent = _authority_bytes(context, verifier_entry.agent_contract_hash)
    producer_schema = _authority_bytes(context, producer_entry.response_schema_hash)
    verifier_schema = _authority_bytes(context, verifier_entry.response_schema_hash)

    _recover_captured_producer(context, entry, slice_spec)
    _catch_up_ledger_events(context)
    resumed = _resume_existing_candidate(
        context,
        backend,
        target_plan,
        entry,
        slice_spec,
        verifier_agent,
        verifier_schema,
    )
    if isinstance(resumed, tuple):
        diagnostics = resumed
        previous_diagnostic_ids = tuple(item.identity for item in resumed)
    elif resumed is not None:
        return resumed
    prior_pairs = tuple(
        item
        for item in context.resources.records
        if isinstance(item, PairedReservationCommitV1)
        and item.slice_spec_id == slice_spec.identity
    )
    start_attempt = len(prior_pairs) + 1
    from harness.re_v2.knowledge_revision import load_knowledge_revision, inherited_attempts
    active = load_knowledge_revision(context)
    if active is not None:
        obligations = tuple(r.obligation_id for r in active.dependencies.obligations if entry.identity in r.entry_ids)
        start_attempt = max(inherited_attempts(active, obligations, 'slice'),
            max((p.producer_attempt_number for p in prior_pairs), default=0)) + 1
    if start_attempt > policy.producer_attempt_limit:
        reason = _attempts_exhausted_reason(context, slice_spec, "producer", "producer_result_contract_attempts_exhausted")
        _fail_slice(context, slice_spec, reason)
        return reason

    for producer_attempt in range(start_attempt, policy.producer_attempt_limit + 1):
        producer_context = build_protocol_28_slice_context(
            context,
            target_plan,
            entry,
            slice_spec,
            role="producer",
            repair_diagnostic_ids=tuple(item.identity for item in diagnostics),
            repair_diagnostics=diagnostics,
            producer_contract_failure_codes=_producer_contract_failure_codes(
                context, slice_spec
            ),
            producer_attempt_number=producer_attempt,
        )
        producer_reservation = _reservation(
            entry, producer_agent, producer_context, producer_schema
        )
        verifier_reservation = _reservation(
            entry,
            verifier_agent,
            verifier_schema,
            extra_input_bytes=(
                max(entry.canonical_context_bytes, len(producer_context))
                + policy.max_candidate_output_bytes
            ),
        )
        preview = context.resources.preview_pair(
            slice_spec.identity,
            producer_attempt,
            producer_reservation,
            verifier_reservation,
        )
        if not preview.allowed:
            reason = _resource_block_reason(context, preview)
            context.controller.block_run("resource", reason)
            return reason
        producer_dispatch = _dispatch_id(
            slice_spec, "producer", producer_attempt, 1
        )
        verifier_dispatch = _dispatch_id(
            slice_spec, "verifier", producer_attempt, 1
        )
        pair = context.resources.commit_pair(
            preview,
            producer_dispatch_id=producer_dispatch,
            verifier_dispatch_id=verifier_dispatch,
        )
        for role, dispatch in (
            ("producer", producer_dispatch),
            ("verifier", verifier_dispatch),
        ):
            context.controller.append_once(
                "dispatch_reserved",
                {
                    "dispatch_id": dispatch,
                    "output_artifact_key_id": slice_spec.output_artifact_key_id,
                    "reservation_id": pair.identity,
                    "role": role,
                },
            )
        try:
            producer = _call_provider(
                context,
                backend,
                "producer",
                producer_dispatch,
                producer_attempt,
                entry,
                slice_spec,
                producer_agent,
                producer_context,
                producer_schema,
                producer_reservation,
                candidate_id=None,
            )
        except Protocol28LifecycleError:
            _release_paired_verifier(
                context,
                pair,
                reason="producer_abandoned",
            )
            raise
        try:
            candidate, _receipt = record_candidate_result(
                context.objects,
                context.ledger,
                slice_spec,
                entry,
                context.inputs.snapshot_evidence_catalog,
                policy,
                producer,
            )
        except Protocol28ExecutionError as exc:
            failure_code = _execution_failure_code(producer, exc)
            context.controller.append_once(
                "candidate_rejected",
                {
                    "dispatch_id": producer_dispatch,
                    "output_artifact_key_id": slice_spec.output_artifact_key_id,
                    "reason_code": failure_code,
                },
            )
            context.resources.release_verifier(
                pair.identity, reason="producer_contract_failure"
            )
            context.controller.append_once(
                "provider_abandoned",
                {
                    "dispatch_id": verifier_dispatch,
                    "reason_code": "producer-contract-failure",
                    "role": "verifier",
                },
            )
            continue
        context.controller.append_once(
            "candidate_recorded",
            {
                "candidate_id": candidate.identity,
                "dispatch_id": producer_dispatch,
                "output_artifact_key_id": slice_spec.output_artifact_key_id,
                "slice_spec_id": slice_spec.identity,
            },
        )
        verifier_context = build_protocol_28_slice_context(
            context,
            target_plan,
            entry,
            slice_spec,
            role="verifier",
            candidate=candidate,
            producer_attempt_number=producer_attempt,
            verifier_attempt_number=1,
        )
        verifier = _call_provider(
            context,
            backend,
            "verifier",
            verifier_dispatch,
            1,
            entry,
            slice_spec,
            verifier_agent,
            verifier_context,
            verifier_schema,
            verifier_reservation,
            candidate_id=candidate.identity,
        )
        parsed = _parse_verifier_with_retry(
            context,
            backend,
            target_plan,
            entry,
            slice_spec,
            candidate,
            producer_attempt,
            verifier_agent,
            verifier_schema,
            verifier_reservation,
            verifier_dispatch,
            verifier,
        )
        if isinstance(parsed, _VerifierRetryBlocked):
            context.controller.block_run("resource", parsed.reason_code)
            return parsed.reason_code
        if parsed is None:
            reason = _attempts_exhausted_reason(context, slice_spec, "verifier", "verifier_result_contract_attempts_exhausted")
            _fail_slice(context, slice_spec, reason)
            return reason
        verdict, persisted = parsed
        context.controller.append_once(
            "verification_recorded",
            {
                "candidate_id": candidate.identity,
                "dispatch_id": persisted.envelope.dispatch_id,
                "output_artifact_key_id": slice_spec.output_artifact_key_id,
                "verdict": verdict.verdict,
                "verification_id": verdict.identity,
            },
        )
        if verdict.verdict == "PASS":
            accepted = certify_and_accept(
                context.objects,
                context.ledger,
                slice_spec,
                entry,
                context.inputs.snapshot_evidence_catalog,
                policy,
                candidate,
                verdict,
                producer,
                persisted,
            )
            _record_acceptance_events(context, accepted)
            return accepted

        diagnostic_ids = tuple(item.identity for item in verdict.diagnostics)
        packet = ExhaustiveRepairPacketV1(
            1,
            slice_spec.identity,
            candidate.identity,
            diagnostic_ids,
            candidate.covered_primary_evidence_ids,
            min(producer_attempt + 1, policy.producer_attempt_limit),
        )
        packet_id = context.objects.put_blob(
            canonical_json_bytes(packet.to_json_dict())
        )
        diagnostic_set_id = content_digest(list(diagnostic_ids))
        context.controller.append_once(
            "repair_packet_recorded",
            {
                "diagnostic_set_id": diagnostic_set_id,
                "output_artifact_key_id": slice_spec.output_artifact_key_id,
                "repair_packet_id": packet_id,
            },
        )
        if diagnostic_ids and diagnostic_ids == previous_diagnostic_ids:
            context.controller.append_once(
                "plateau_reached",
                {
                    "diagnostic_set_id": diagnostic_set_id,
                    "output_artifact_key_id": slice_spec.output_artifact_key_id,
                },
            )
            reason = "non_improving_verification"
            _fail_slice(context, slice_spec, reason)
            return reason
        previous_diagnostic_ids = diagnostic_ids
        diagnostics = verdict.diagnostics

    reason = _attempts_exhausted_reason(context, slice_spec, "producer", "semantic_repair_attempts_exhausted")
    _fail_slice(context, slice_spec, reason)
    return reason


def _parse_verifier_with_retry(
    context: Protocol28RunContext,
    backend: L4ExecutionBackend,
    target_plan: ExhaustiveTargetPlanV1,
    entry: SlicePlanEntryV1,
    slice_spec: SliceSpecV1,
    candidate: ExhaustiveEvidenceSliceV1,
    producer_attempt: int,
    agent_bytes: bytes,
    schema_bytes: bytes,
    reservation: DispatchReservationV1,
    dispatch_id: str,
    persisted: PersistedL4ExecutionV1,
) -> (
    tuple[ExhaustiveVerificationV1, PersistedL4ExecutionV1]
    | _VerifierRetryBlocked
    | None
):
    for verifier_attempt in (1, 2):
        try:
            verification, _receipt = record_verification_result(
                context.objects,
                context.ledger,
                slice_spec,
                entry,
                candidate,
                persisted,
            )
            return verification, persisted
        except Protocol28ExecutionError as exc:
            context.controller.append_once(
                "verification_rejected",
                {
                    "dispatch_id": dispatch_id,
                    "output_artifact_key_id": slice_spec.output_artifact_key_id,
                    "reason_code": _execution_failure_code(persisted, exc),
                },
            )
        if verifier_attempt == 2:
            return None
        # Recovery must consume an already-reserved/captured second attempt,
        # never reserve or dispatch a third verifier for the same candidate.
        dispatch_id = _dispatch_id(
            slice_spec, "verifier", producer_attempt, verifier_attempt + 1
        )
        existing = replay_protocol_28(context.events.replay()).dispatches.get(dispatch_id)
        if existing is not None:
            view = context.ledger.replay()
            if dispatch_id in view.execution_captures:
                persisted = PersistedL4ExecutionV1(
                    view.execution_envelopes[dispatch_id], view.execution_captures[dispatch_id]
                )
                continue
            if existing.stage != "reserved":
                raise Protocol28LifecycleError("verifier retry has no recoverable capture")
            verifier_context = build_protocol_28_slice_context(
                context, target_plan, entry, slice_spec, role="verifier", candidate=candidate,
                producer_attempt_number=producer_attempt, verifier_attempt_number=2,
            )
            persisted = _call_provider(
                context, backend, "verifier", dispatch_id, 2, entry, slice_spec,
                agent_bytes, verifier_context, schema_bytes, reservation,
                candidate_id=candidate.identity,
            )
            continue
        preview = context.resources.preview_verifier_retry(
            slice_spec.identity, producer_attempt, reservation
        )
        if not preview.allowed:
            return _VerifierRetryBlocked(_resource_block_reason(context, preview))
        retry = context.resources.commit_verifier_retry(
            preview, dispatch_id=dispatch_id
        )
        context.controller.append_once(
            "dispatch_reserved",
            {
                "dispatch_id": dispatch_id,
                "output_artifact_key_id": slice_spec.output_artifact_key_id,
                "reservation_id": retry.identity,
                "role": "verifier",
            },
        )
        verifier_context = build_protocol_28_slice_context(
            context,
            target_plan,
            entry,
            slice_spec,
            role="verifier",
            candidate=candidate,
            producer_attempt_number=producer_attempt,
            verifier_attempt_number=verifier_attempt + 1,
        )
        persisted = _call_provider(
            context,
            backend,
            "verifier",
            dispatch_id,
            verifier_attempt + 1,
            entry,
            slice_spec,
            agent_bytes,
            verifier_context,
            schema_bytes,
            reservation,
            candidate_id=candidate.identity,
        )
    return None


def _catch_up_ledger_events(context: Protocol28RunContext) -> None:
    """Project durable capture/receipt authority before scheduling new work."""
    view = context.ledger.replay()
    state = replay_protocol_28(context.events.replay())
    if state.knowledge_authorization_id is not None:
        active_outputs = {row[1] for row in state.realized_by_entry.values()}
    else:
        active_outputs = None
    for dispatch_id, capture in sorted(view.execution_captures.items()):
        dispatch = state.dispatches.get(dispatch_id)
        if dispatch is not None and dispatch.stage == "started":
            envelope = view.execution_envelopes[dispatch_id]
            context.controller.append_once(
                "provider_capture_recorded",
                {
                    "dispatch_id": dispatch_id,
                    "execution_capture_id": capture.identity,
                    "raw_result_id": capture.raw_result_hash,
                    "role": envelope.role,
                },
            )
            state = replay_protocol_28(context.events.replay())
    if state.knowledge_authorization_id is not None:
        from harness.re_v2.protocol_28.budget import ResourceObservationV1, ResourceAbandonmentV1
        observed = {r.dispatch_id for r in context.resources.records if isinstance(r, (ResourceObservationV1, ResourceAbandonmentV1))}
        settled = {e.payload['dispatch_id'] for e in context.events.replay() if e.type == 'knowledge_resource_settled'}
        for dispatch_id in view.execution_captures:
            if dispatch_id not in observed:
                # The response is durable but usage was interrupted: retain its
                # exact reservation once; never invent or re-charge a provider call.
                context.resources.observe(dispatch_id, token_status='unavailable', billable_tokens=None,
                    active_status='unavailable', active_ms=None)
            if dispatch_id not in settled:
                _record_knowledge_resource_settlement(context, dispatch_id)
        for receipt in view.knowledge_artifacts.values():
            dispatch_id = _dispatch_for_capture(view, receipt.execution_capture_id)
            dispatch = replay_protocol_28(context.events.replay()).dispatches[dispatch_id]
            if dispatch.stage == 'captured':
                context.controller.append_once('knowledge_artifact_recorded', {'dispatch_id': dispatch_id,
                    'role': receipt.role, 'work_item_id': receipt.work_item_id, 'artifact_id': receipt.artifact_id})
        state = replay_protocol_28(context.events.replay())
    for candidate_id, receipt in sorted(view.candidate_receipts.items()):
        dispatch_id = _dispatch_for_capture(view, receipt.producer_execution_capture_hash)
        dispatch = state.dispatches.get(dispatch_id)
        realized = state.realized_by_entry.get(receipt.plan_entry_id)
        if dispatch is not None and dispatch.stage == "captured" and realized is not None:
            context.controller.append_once(
                "candidate_recorded",
                {
                    "candidate_id": candidate_id,
                    "dispatch_id": dispatch_id,
                    "output_artifact_key_id": realized[1],
                    "slice_spec_id": receipt.slice_spec_id,
                },
            )
            state = replay_protocol_28(context.events.replay())
    for verification_id, receipt in sorted(view.verification_receipts.items()):
        dispatch_id = _dispatch_for_capture(view, receipt.verifier_execution_capture_hash)
        dispatch = state.dispatches.get(dispatch_id)
        realized = state.realized_by_entry.get(receipt.plan_entry_id)
        if dispatch is not None and dispatch.stage == "captured" and realized is not None:
            context.controller.append_once(
                "verification_recorded",
                {
                    "candidate_id": receipt.candidate_id,
                    "dispatch_id": dispatch_id,
                    "output_artifact_key_id": realized[1],
                    "verdict": receipt.verdict,
                    "verification_id": verification_id,
                },
            )
            state = replay_protocol_28(context.events.replay())
    for receipt in sorted(view.certifications.values(), key=lambda item: item.identity):
        if active_outputs is not None and receipt.output_artifact_key_id not in active_outputs:
            continue
        if receipt.output_artifact_key_id not in state.certifications:
            context.controller.append_once(
                "certification_recorded",
                {
                    "certification_receipt_id": receipt.identity,
                    "output_artifact_key_id": receipt.output_artifact_key_id,
                    "slice_spec_id": receipt.slice_spec_id,
                },
            )
            state = replay_protocol_28(context.events.replay())
    for receipt in sorted(view.acceptances.values(), key=lambda item: item.identity):
        if active_outputs is not None and receipt.output_artifact_key_id not in active_outputs:
            continue
        if receipt.output_artifact_key_id not in state.acceptances:
            context.controller.append_once(
                "acceptance_recorded",
                {
                    "acceptance_receipt_id": receipt.identity,
                    "certification_receipt_id": receipt.certification_receipt_hash,
                    "output_artifact_key_id": receipt.output_artifact_key_id,
                    "slice_spec_id": receipt.slice_spec_id,
                },
            )
            state = replay_protocol_28(context.events.replay())
    for accepted in sorted(view.accepted_slices.values(), key=lambda item: item.identity):
        if active_outputs is not None and accepted.output_artifact_key_id not in active_outputs:
            continue
        if accepted.output_artifact_key_id not in state.accepted_slices:
            context.controller.append_once(
                "accepted_slice_recorded",
                {
                    "acceptance_receipt_id": accepted.acceptance_receipt_hash,
                    "accepted_slice_id": accepted.identity,
                    "output_artifact_key_id": accepted.output_artifact_key_id,
                    "slice_spec_id": accepted.slice_spec_id,
                },
            )
            state = replay_protocol_28(context.events.replay())


def _recover_captured_producer(
    context: Protocol28RunContext,
    entry: SlicePlanEntryV1,
    slice_spec: SliceSpecV1,
) -> None:
    view = context.ledger.replay()
    state = replay_protocol_28(context.events.replay())
    recorded_capture_ids = {
        item.producer_execution_capture_hash
        for item in view.candidate_receipts.values()
    }
    for dispatch_id, envelope in sorted(view.execution_envelopes.items()):
        capture = view.execution_captures[dispatch_id]
        dispatch = state.dispatches.get(dispatch_id)
        if (
            envelope.role != "producer"
            or envelope.slice_spec_id != slice_spec.identity
            or capture.identity in recorded_capture_ids
            or dispatch is None
            or dispatch.stage != "captured"
        ):
            continue
        persisted = PersistedL4ExecutionV1(envelope, capture)
        try:
            candidate, _receipt = record_candidate_result(
                context.objects,
                context.ledger,
                slice_spec,
                entry,
                context.inputs.snapshot_evidence_catalog,
                context.inputs.exhaustive_policy,
                persisted,
            )
        except Protocol28ExecutionError as exc:
            context.controller.append_once(
                "candidate_rejected",
                {
                    "dispatch_id": dispatch_id,
                    "output_artifact_key_id": slice_spec.output_artifact_key_id,
                    "reason_code": _execution_failure_code(persisted, exc),
                },
            )
            pair = next(
                (
                    item
                    for item in context.resources.records
                    if isinstance(item, PairedReservationCommitV1)
                    and item.producer_dispatch_id == dispatch_id
                ),
                None,
            )
            if pair is not None:
                context.resources.release_verifier(
                    pair.identity, reason="producer_contract_failure"
                )
                verifier_state = replay_protocol_28(
                    context.events.replay()
                ).dispatches.get(pair.verifier_dispatch_id)
                if verifier_state is not None and verifier_state.stage == "reserved":
                    context.controller.append_once(
                        "provider_abandoned",
                        {
                            "dispatch_id": pair.verifier_dispatch_id,
                            "reason_code": "producer-contract-failure",
                            "role": "verifier",
                        },
                    )
            continue
        context.controller.append_once(
            "candidate_recorded",
            {
                "candidate_id": candidate.identity,
                "dispatch_id": dispatch_id,
                "output_artifact_key_id": slice_spec.output_artifact_key_id,
                "slice_spec_id": slice_spec.identity,
            },
        )


def _resume_existing_candidate(
    context: Protocol28RunContext,
    backend: L4ExecutionBackend,
    target_plan: ExhaustiveTargetPlanV1,
    entry: SlicePlanEntryV1,
    slice_spec: SliceSpecV1,
    verifier_agent: bytes,
    verifier_schema: bytes,
):  # type: ignore[no-untyped-def]
    view = context.ledger.replay()
    candidates = []
    for candidate_id, receipt in view.candidate_receipts.items():
        if receipt.plan_entry_id != entry.identity or receipt.slice_spec_id != slice_spec.identity:
            continue
        dispatch_id = _dispatch_for_capture(
            view, receipt.producer_execution_capture_hash
        )
        envelope = view.execution_envelopes[dispatch_id]
        candidate = load_canonical_object(
            context.objects.read_blob(candidate_id),
            ExhaustiveEvidenceSliceV1.from_json_dict,
        )
        candidates.append((envelope.attempt_number, candidate, receipt, dispatch_id))
    if not candidates:
        return None
    producer_attempt, candidate, receipt, producer_dispatch = max(
        candidates, key=lambda item: item[0]
    )
    pair = next(
        (
            item
            for item in context.resources.records
            if isinstance(item, PairedReservationCommitV1)
            and item.producer_dispatch_id == producer_dispatch
        ),
        None,
    )
    if pair is None:
        raise Protocol28LifecycleError("candidate has no paired verifier reservation")
    verification_receipts = tuple(
        item
        for item in view.verification_receipts.values()
        if item.candidate_id == candidate.identity
    )
    persisted_verifier: PersistedL4ExecutionV1
    if verification_receipts:
        latest = max(
            verification_receipts,
            key=lambda item: view.execution_envelopes[
                _dispatch_for_capture(view, item.verifier_execution_capture_hash)
            ].attempt_number,
        )
        verifier_dispatch = _dispatch_for_capture(
            view, latest.verifier_execution_capture_hash
        )
        persisted_verifier = PersistedL4ExecutionV1(
            view.execution_envelopes[verifier_dispatch],
            view.execution_captures[verifier_dispatch],
        )
        verification = load_canonical_object(
            context.objects.read_blob(latest.verifier_result_hash),
            ExhaustiveVerificationV1.from_json_dict,
        )
    else:
        verifier_dispatch = pair.verifier_dispatch_id
        dispatch_state = replay_protocol_28(
            context.events.replay()
        ).dispatches.get(verifier_dispatch)
        verifier_context = build_protocol_28_slice_context(
            context,
            target_plan,
            entry,
            slice_spec,
            role="verifier",
            candidate=candidate,
            producer_attempt_number=producer_attempt,
            verifier_attempt_number=1,
        )
        if dispatch_state is not None and dispatch_state.stage == "reserved":
            persisted_verifier = _call_provider(
                context,
                backend,
                "verifier",
                verifier_dispatch,
                1,
                entry,
                slice_spec,
                verifier_agent,
                verifier_context,
                verifier_schema,
                pair.verifier_reservation,
                candidate_id=candidate.identity,
            )
        elif (
            dispatch_state is not None
            and dispatch_state.stage in {"captured", "rejected"}
            and verifier_dispatch in view.execution_captures
        ):
            persisted_verifier = PersistedL4ExecutionV1(
                view.execution_envelopes[verifier_dispatch],
                view.execution_captures[verifier_dispatch],
            )
        else:
            return None
        parsed = _parse_verifier_with_retry(
            context,
            backend,
            target_plan,
            entry,
            slice_spec,
            candidate,
            producer_attempt,
            verifier_agent,
            verifier_schema,
            pair.verifier_reservation,
            verifier_dispatch,
            persisted_verifier,
        )
        if isinstance(parsed, _VerifierRetryBlocked):
            context.controller.block_run("resource", parsed.reason_code)
            return parsed.reason_code
        if parsed is None:
            reason = _attempts_exhausted_reason(context, slice_spec, "verifier", "verifier_result_contract_attempts_exhausted")
            _fail_slice(context, slice_spec, reason)
            return reason
        verification, persisted_verifier = parsed
        context.controller.append_once(
            "verification_recorded",
            {
                "candidate_id": candidate.identity,
                "dispatch_id": persisted_verifier.envelope.dispatch_id,
                "output_artifact_key_id": slice_spec.output_artifact_key_id,
                "verdict": verification.verdict,
                "verification_id": verification.identity,
            },
        )
    if verification.verdict == "REPAIR":
        return verification.diagnostics
    producer = PersistedL4ExecutionV1(
        view.execution_envelopes[producer_dispatch],
        view.execution_captures[producer_dispatch],
    )
    accepted = certify_and_accept(
        context.objects,
        context.ledger,
        slice_spec,
        entry,
        context.inputs.snapshot_evidence_catalog,
        context.inputs.exhaustive_policy,
        candidate,
        verification,
        producer,
        persisted_verifier,
    )
    _record_acceptance_events(context, accepted)
    return accepted


def _dispatch_for_capture(view, capture_id: str) -> str:  # type: ignore[no-untyped-def]
    matches = tuple(
        dispatch_id
        for dispatch_id, capture in view.execution_captures.items()
        if capture.identity == capture_id
    )
    if len(matches) != 1:
        raise Protocol28LifecycleError("execution capture identity is missing or ambiguous")
    return matches[0]


def _release_paired_verifier(
    context: Protocol28RunContext,
    pair: PairedReservationCommitV1,
    *,
    reason: Literal["producer_contract_failure", "producer_abandoned"],
) -> None:
    context.resources.release_verifier(pair.identity, reason=reason)
    verifier_state = replay_protocol_28(context.events.replay()).dispatches.get(
        pair.verifier_dispatch_id
    )
    if verifier_state is not None and verifier_state.stage == "reserved":
        context.controller.append_once(
            "provider_abandoned",
            {
                "dispatch_id": pair.verifier_dispatch_id,
                "reason_code": reason.replace("_", "-"),
                "role": "verifier",
            },
        )


def _call_provider(
    context: Protocol28RunContext,
    backend: L4ExecutionBackend,
    role: RoleV1,
    dispatch_id: str,
    attempt_number: int,
    entry: SlicePlanEntryV1,
    slice_spec: SliceSpecV1,
    agent_bytes: bytes,
    context_bytes: bytes,
    schema_bytes: bytes,
    reservation: DispatchReservationV1,
    *,
    candidate_id: str | None,
) -> PersistedL4ExecutionV1:
    # Retained debt is provider-visible authority, not just a rendered hint.
    # Store its Safe slice context before capture so replay can reject omission.
    if 'inherited_knowledge_debt' in json.loads(context_bytes):
        context.objects.put_blob(context_bytes)
    lease_id = content_digest(
        {"dispatch_id": dispatch_id, "owner_id": "protocol-28-controller"}
    )
    context.controller.append_once(
        "dispatch_leased",
        {
            "dispatch_id": dispatch_id,
            "lease_id": lease_id,
            "owner_id": "protocol-28-controller",
            "role": role,
        },
    )
    context.controller.append_once(
        "provider_started", {"dispatch_id": dispatch_id, "role": role}
    )
    envelope = L4ExecutionEnvelopeV1(
        1,
        dispatch_id,
        role,
        slice_spec.identity,
        entry.identity,
        attempt_number,
        content_digest(agent_bytes),
        content_digest(context_bytes),
        content_digest(
            {
                "agent_contract_hash": content_digest(agent_bytes),
                "context_bundle_hash": content_digest(context_bytes),
                "response_schema_hash": content_digest(schema_bytes),
                "reservation": {
                    "initial_input_tokens": reservation.initial_input_tokens,
                    "billable_tokens": reservation.billable_tokens,
                    "active_ms": reservation.active_ms,
                },
            }
        ),
        candidate_id,
    )
    try:
        result = backend.execute(
            role, agent_bytes, context_bytes, schema_bytes, reservation
        )
    except Exception as exc:
        context.resources.abandon(dispatch_id)
        context.controller.append_once(
            "provider_abandoned",
            {
                "dispatch_id": dispatch_id,
                "reason_code": "provider-execution-error",
                "role": role,
            },
        )
        context.controller.block_run("execution", "provider_execution_error")
        if replay_protocol_28(context.events.replay()).knowledge_authorization_id is not None:
            raise Protocol28LifecycleError('reviewed provider execution failed') from None
        raise Protocol28LifecycleError("protocol-2.8 provider execution failed") from exc
    if not isinstance(result, L4DispatchResultV1):
        context.resources.abandon(dispatch_id)
        context.controller.append_once(
            "provider_abandoned",
            {
                "dispatch_id": dispatch_id,
                "reason_code": "invalid-provider-result",
                "role": role,
            },
        )
        context.controller.block_run("execution", "invalid_provider_result")
        raise Protocol28LifecycleError(
            "protocol-2.8 backend returned an invalid result"
        )
    unsafe_output = False
    if replay_protocol_28(context.events.replay()).knowledge_authorization_id is not None:
        from harness.re_v2.knowledge_evidence import screen_provider_output, KnowledgeEvidenceError
        from harness.re_v2.ledger import ObjectStore
        try:
            screen_provider_output(result.raw_result, ObjectStore(context.paths.root / 'knowledge-quarantine'))
        except KnowledgeEvidenceError:
            # Preserve the charge and a sanitized failure capture, never unsafe bytes.
            result = replace(result, raw_result=canonical_json_bytes({'failure': 'unsafe-or-uninspectable-provider-output'}),
                result_kind='provider_failure')
            unsafe_output = True
    persisted = persist_provider_result(
        context.objects,
        envelope,
        result.raw_result,
        provider_name=result.provider_name,
        model_revision=result.model_revision,
        started_at=result.started_at,
        ended_at=result.ended_at,
        duration_ms=result.duration_ms,
        result_kind=result.result_kind,
        ledger=context.ledger,
    )
    context.controller.append_once(
        "provider_capture_recorded",
        {
            "dispatch_id": dispatch_id,
            "execution_capture_id": persisted.capture.identity,
            "raw_result_id": persisted.capture.raw_result_hash,
            "role": role,
        },
    )
    context.resources.observe(
        dispatch_id,
        token_status=result.token_status,
        billable_tokens=result.billable_tokens,
        active_status=result.active_status,
        active_ms=result.active_ms,
    )
    if replay_protocol_28(context.events.replay()).knowledge_authorization_id is not None:
        _record_knowledge_resource_settlement(context, dispatch_id)
    if unsafe_output:
        context.controller.block_run('execution', 'unsafe_provider_output')
        raise Protocol28LifecycleError('reviewed provider output was refused')
    return persisted


def _record_knowledge_resource_settlement(context, dispatch_id):
    prefix_id = context.objects.put_blob(canonical_json_bytes([r.to_json_dict() for r in context.resources.records]))
    decision = context.resources.decision
    context.controller.append_once('knowledge_resource_settled', {'dispatch_id': dispatch_id,
        'resource_prefix_id': prefix_id, 'charged_tokens': decision.charged_tokens - decision.open_token_reservations,
        'charged_active_ms': decision.charged_active_ms - decision.open_active_ms_reservations})


def _reservation(
    entry: SlicePlanEntryV1,
    *payloads: bytes,
    extra_input_bytes: int = 0,
) -> DispatchReservationV1:
    initial = max(
        1, sum(len(item) for item in payloads) + extra_input_bytes + 1024
    )
    billable = max(initial, entry.conservative_tokens, 1)
    # Size the call allowance to the frozen work, including a verifier's
    # candidate payload. Reserve it from the existing run-wide budget first;
    # this does not append authorization or expand the bounded attempt count.
    context_bytes = max(entry.canonical_context_bytes, extra_input_bytes)
    time_units = max(1, min(3, (context_bytes + 131_071) // 131_072))
    return DispatchReservationV1(initial, billable, time_units * 300_000)


def _dispatch_id(
    slice_spec: SliceSpecV1,
    role: RoleV1,
    producer_attempt: int,
    role_attempt: int,
) -> str:
    suffix = content_digest(
        {
            "slice_spec_id": slice_spec.identity,
            "role": role,
            "producer_attempt": producer_attempt,
            "role_attempt": role_attempt,
        }
    ).removeprefix("sha256:")[:24]
    return f"l4-{role}-{suffix}-p{producer_attempt}-r{role_attempt}"


def _authority_bytes(context: Protocol28RunContext, object_id: str) -> bytes:
    payload = context.inputs.authority_objects.get(object_id)
    if payload is None or content_digest(payload) != object_id:
        raise Protocol28LifecycleError(
            f"protocol-2.8 execution authority is unavailable: {object_id}"
        )
    return payload


def _record_acceptance_events(
    context: Protocol28RunContext,
    accepted: AcceptedExhaustiveSliceV1,
) -> None:
    context.controller.append_once(
        "certification_recorded",
        {
            "certification_receipt_id": accepted.certification_receipt_hash,
            "output_artifact_key_id": accepted.output_artifact_key_id,
            "slice_spec_id": accepted.slice_spec_id,
        },
    )
    context.controller.append_once(
        "acceptance_recorded",
        {
            "acceptance_receipt_id": accepted.acceptance_receipt_hash,
            "certification_receipt_id": accepted.certification_receipt_hash,
            "output_artifact_key_id": accepted.output_artifact_key_id,
            "slice_spec_id": accepted.slice_spec_id,
        },
    )
    context.controller.append_once(
        "accepted_slice_recorded",
        {
            "acceptance_receipt_id": accepted.acceptance_receipt_hash,
            "accepted_slice_id": accepted.identity,
            "output_artifact_key_id": accepted.output_artifact_key_id,
            "slice_spec_id": accepted.slice_spec_id,
        },
    )


def _fail_slice(
    context: Protocol28RunContext,
    slice_spec: SliceSpecV1,
    reason: str,
) -> None:
    context.controller.append_once(
        "slice_failed",
        {
            "output_artifact_key_id": slice_spec.output_artifact_key_id,
            "reason_code": reason,
        },
    )
    context.controller.block_run("execution", reason)


def _load_recorded_target_roots(
    context: Protocol28RunContext,
    root_ids: set[str],
) -> tuple[L4TargetRootV1, ...]:
    return tuple(
        sorted(
            (
                load_canonical_object(
                    context.objects.read_blob(root_id),
                    L4TargetRootV1.from_json_dict,
                )
                for root_id in root_ids
            ),
            key=lambda item: item.sort_key,
        )
    )


def _load_recorded_source_roots(
    context: Protocol28RunContext,
    root_ids: set[str],
) -> tuple[L4SourceRootV1, ...]:
    return tuple(
        sorted(
            (
                load_canonical_object(
                    context.objects.read_blob(root_id),
                    L4SourceRootV1.from_json_dict,
                )
                for root_id in root_ids
            ),
            key=lambda item: item.source_id,
        )
    )


def _build_source_roots(
    context: Protocol28RunContext,
    target_roots: tuple[L4TargetRootV1, ...],
) -> tuple[L4SourceRootV1, ...]:
    state = replay_protocol_28(context.events.replay())
    existing = {
        item.source_id: item
        for item in _load_recorded_source_roots(context, state.source_root_ids)
    }
    target_by_plan = {item.target_plan_id: item for item in target_roots}
    for source_plan in (
        item
        for item in context.inputs.exhaustive_plan.target_plans
        if item.target_kind == "source"
    ):
        if source_plan.source_id in existing:
            continue
        composition = target_by_plan[source_plan.identity]
        domain_plan_ids = {
            dependency
            for entry in source_plan.entries
            for dependency in entry.planned_dependency_root_ids
        }
        domains = tuple(
            sorted(
                (target_by_plan[item] for item in domain_plan_ids),
                key=lambda item: item.target_id,
            )
        )
        root = build_source_root(
            source_plan,
            composition,
            domains,
            (),
            (
                "full-source"
                if context.inputs.exhaustive_plan.completion_scope == "all-scope"
                else "selected-domains"
            ),
        )
        context.controller.record_root(root, root_kind="source")
        existing[root.source_id] = root
    return tuple(sorted(existing.values(), key=lambda item: item.source_id))


def _result(
    context: Protocol28RunContext,
    state: str,
    run_root_id: str | None,
    reason: str | None,
) -> Protocol28RunResult:
    current = replay_protocol_28(context.events.replay())
    if current.knowledge_authorization_id is None:
        export_protocol_28_checkpoints(context)
    view = context.ledger.read_snapshot()[1] if current.knowledge_authorization_id is not None else context.ledger.replay()
    if current.knowledge_authorization_id is not None:
        if run_root_id is not None and run_root_id not in view.knowledge_run_roots:
            raise Protocol28LifecycleError('completion requires an authenticated reviewed run root')
        state = current.lifecycle_state
    return Protocol28RunResult(
        context.inputs.manifest.run_id,
        state,
        run_root_id,
        reason,
        len(current.accepted_slices) if current.knowledge_authorization_id else len(view.accepted_slices),
        sum(
            len(item.entries)
            for item in context.inputs.exhaustive_plan.target_plans
        ),
    )


def export_protocol_28_checkpoints(
    context: Protocol28RunContext,
) -> tuple[CheckpointManifestV2, ...]:
    """Project every durable accepted slice into the disposable V2 cache."""
    if not isinstance(context, Protocol28RunContext):
        raise Protocol28LifecycleError("checkpoint export requires an exhaustive run")
    events = context.events.replay()
    ledger_history, view = context.ledger.replay_with_history()
    if not view.accepted_slices:
        return ()
    manifest_bytes = _read_regular_bytes(context.paths.manifest)
    manifest_hash = context.objects.put_blob(manifest_bytes)
    entries = {
        entry.identity: entry
        for target in context.inputs.exhaustive_plan.target_plans
        for entry in target.entries
    }
    target_roots = _load_recorded_target_roots(
        context, replay_protocol_28(events).target_root_ids
    )
    root_by_plan = {item.target_plan_id: item.identity for item in target_roots}
    evidence = {
        item.identity: item
        for item in (
            *context.inputs.snapshot_evidence_catalog.shards,
            *context.inputs.snapshot_evidence_catalog.empty_receipts,
            *context.inputs.snapshot_evidence_catalog.nontext_dispositions,
        )
    }
    manifests: list[CheckpointManifestV2] = []
    for output_id, accepted in sorted(view.accepted_slices.items()):
        entry = entries.get(accepted.plan_entry_id)
        if entry is None:
            raise Protocol28LifecycleError(
                "accepted checkpoint has no frozen plan entry"
            )
        spec = realize_slice(
            entry,
            {
                dependency: root_by_plan[dependency]
                for dependency in entry.planned_dependency_root_ids
            },
        )
        if spec.identity != accepted.slice_spec_id:
            raise Protocol28LifecycleError(
                "accepted checkpoint slice realization changed"
            )
        context.objects.put_blob(canonical_json_bytes(spec.to_json_dict()))
        candidate = load_canonical_object(
            context.objects.read_blob(accepted.candidate_hash),
            ExhaustiveEvidenceSliceV1.from_json_dict,
        )
        verification = load_canonical_object(
            context.objects.read_blob(accepted.verifier_result_hash),
            ExhaustiveVerificationV1.from_json_dict,
        )
        certification = view.certifications[accepted.certification_receipt_hash]
        acceptance = view.acceptances[output_id]
        producer_envelope, producer_capture = _checkpoint_execution(
            context, accepted.producer_execution_capture_hash
        )
        verifier_envelope, verifier_capture = _checkpoint_execution(
            context, accepted.verifier_execution_capture_hash
        )
        terminal_event = next(
            (
                item
                for item in events
                if item.type == "accepted_slice_recorded"
                and item.payload["accepted_slice_id"] == accepted.identity
            ),
            None,
        )
        terminal_record = next(
            (
                item
                for item in ledger_history
                if item.type == "l4_accepted_slice"
                and item.payload["output_artifact_key_id"] == output_id
            ),
            None,
        )
        if terminal_event is None or terminal_record is None:
            raise Protocol28LifecycleError(
                "accepted checkpoint prefix authority is incomplete"
            )
        event_prefix = b"".join(
            canonical_json_bytes(item.to_json_dict())
            for item in events[: events.index(terminal_event) + 1]
        )
        ledger_prefix = b"".join(
            canonical_json_bytes(item.to_json_dict())
            for item in ledger_history[: ledger_history.index(terminal_record) + 1]
        )
        event_prefix_hash = context.objects.put_blob(event_prefix)
        ledger_prefix_hash = context.objects.put_blob(ledger_prefix)
        object_ids = {
            manifest_hash,
            event_prefix_hash,
            ledger_prefix_hash,
            spec.identity,
            entry.identity,
            context.inputs.exhaustive_policy.identity,
            context.inputs.manifest.inherited_artifact_policy_catalog_id,
            accepted.identity,
            candidate.identity,
            verification.identity,
            certification.identity,
            acceptance.identity,
            producer_envelope.identity,
            producer_capture.identity,
            producer_capture.raw_result_hash,
            verifier_envelope.identity,
            verifier_capture.identity,
            verifier_capture.raw_result_hash,
            entry.target_l3_projection_id,
            entry.target_evidence_projection_id,
            entry.producer_contract_hash,
            entry.verifier_contract_hash,
            *entry.primary_subject_ids,
            *entry.supporting_subject_ids,
            *entry.primary_source_record_ids,
            *entry.supporting_source_record_ids,
            *entry.primary_snapshot_evidence_ids,
            *entry.supporting_snapshot_evidence_ids,
            *entry.required_lower_authority_ids,
            *spec.accepted_dependency_artifact_ids,
        }
        for evidence_id in (
            *entry.primary_snapshot_evidence_ids,
            *entry.supporting_snapshot_evidence_ids,
        ):
            item = evidence.get(evidence_id)
            raw_object_hash = getattr(item, "raw_object_hash", None)
            if isinstance(raw_object_hash, str):
                object_ids.add(raw_object_hash)
            membership_proof_id = getattr(item, "membership_proof_id", None)
            if isinstance(membership_proof_id, str):
                object_ids.add(membership_proof_id)
        objects = {
            object_id: context.objects.read_blob(object_id)
            for object_id in sorted(object_ids)
        }
        manifests.append(
            CheckpointManifestV2(
                2,
                context.inputs.manifest.run_id,
                manifest_hash,
                event_prefix_hash,
                ledger_prefix_hash,
                spec,
                entry,
                context.inputs.exhaustive_policy.identity,
                context.inputs.manifest.inherited_artifact_policy_catalog_id,
                accepted,
                candidate,
                verification,
                certification,
                acceptance,
                tuple(objects),
                {key: len(value) for key, value in objects.items()},
                (2,),
            )
        )
    workspace = context.run_dir.parent.parent
    try:
        _index, cached, quarantine = load_checkpoint_cache_v2(workspace)
    except Protocol28CheckpointError:
        cached, quarantine = {}, ()
    merged = dict(cached)
    merged.update({item.identity: item for item in manifests})
    publish_checkpoint_cache_v2(
        workspace,
        tuple(sorted(merged.values(), key=lambda item: item.identity)),
        quarantine,
    )
    return tuple(sorted(manifests, key=lambda item: item.identity))


def _read_regular_bytes(path: Path) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise Protocol28LifecycleError("checkpoint origin manifest is unavailable") from exc
    try:
        return os.read(descriptor, os.fstat(descriptor).st_size)
    finally:
        os.close(descriptor)


__all__ = (
    "L4DispatchResultV1",
    "L4ExecutionBackend",
    "Protocol28LifecycleError",
    "Protocol28CheckpointAdoptionV1",
    "Protocol28PreparationOptions",
    "Protocol28RunResult",
    "continue_protocol_28_run",
    "adopt_protocol_28_checkpoints",
    "create_or_reuse_protocol_28_child",
    "export_protocol_28_checkpoints",
    "find_exact_protocol_28_child",
    "prepare_protocol_28_request",
    "run_protocol_28_exhaustive",
)
