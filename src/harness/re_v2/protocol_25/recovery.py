"""Schema-4 recovery strategy over the shared RE v2 durable kernel."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping

from harness.re_v2.events import EventRecord
from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.ledger import ReV2LedgerError
from harness.re_v2.protocol_22.graph import (
    AcceptedArtifactV2,
    plan_next_v2,
)
from harness.re_v2.protocol_22.recovery import Protocol22RunContext
from harness.re_v2.protocol_22.schema import load_canonical_object
from harness.re_v2.run_store import load_run_manifest

from .artifacts import AuditCandidateV1, AuditEpochV1
from .controller import (
    Protocol25ControllerActionV1,
    Protocol25ControllerStateV1,
    SemanticSourceCycleStateV1,
    SemanticTargetControllerStateV1,
)
from .events import Protocol25ReplayState
from .graph import Protocol25Graph
from .inputs import ValidatedProtocol25Inputs
from .ledger import Protocol25LedgerView
from .runtime import (
    Protocol25DeterministicRuntime,
    SemanticCertificationResultV1,
)


class Protocol25RecoveryError(RuntimeError):
    """Raised when schema-4 durable authority cannot be replayed exactly."""


@dataclass(frozen=True, slots=True, kw_only=True)
class Protocol25RunContext(Protocol22RunContext):
    """Shared run context plus authenticated schema-4 semantic authority."""

    semantic_inputs: ValidatedProtocol25Inputs
    semantic_graph: Protocol25Graph
    semantic_runtime: Protocol25DeterministicRuntime

    def __post_init__(self) -> None:
        Protocol22RunContext.__post_init__(self)
        if not isinstance(self.semantic_inputs, ValidatedProtocol25Inputs):
            raise Protocol25RecoveryError("semantic inputs are not authenticated")
        if not isinstance(self.semantic_graph, Protocol25Graph):
            raise Protocol25RecoveryError("semantic graph is invalid")
        if self.inputs != self.semantic_graph.inputs:
            raise Protocol25RecoveryError(
                "shared inputs differ from the semantic prerequisite adapter"
            )
        if self.graph != self.semantic_graph.prerequisite_graph:
            raise Protocol25RecoveryError(
                "shared graph differs from semantic prerequisite authority"
            )
        if self.semantic_inputs.graph_inputs != self.semantic_graph._inputs:
            raise Protocol25RecoveryError(
                "semantic inputs differ from immutable graph authority"
            )
        if not isinstance(self.semantic_runtime, Protocol25DeterministicRuntime):
            raise Protocol25RecoveryError("semantic runtime is invalid")

    def recover_controller_state(self) -> Protocol25ControllerStateV1:
        return recover_protocol_25_run(self).controller_state

    def apply_controller_action(self, action: Protocol25ControllerActionV1) -> None:
        _apply_controller_action(self, action)


@dataclass(frozen=True, slots=True)
class Protocol25RecoveryResult:
    controller_state: Protocol25ControllerStateV1
    events: tuple[EventRecord, ...]
    ledger: Protocol25LedgerView


def reconstruct_accepted_audit_results(
    context: Protocol25RunContext,
) -> tuple[SemanticCertificationResultV1, ...]:
    """Rebuild accepted audit certification envelopes from durable authority."""
    if not isinstance(context, Protocol25RunContext):
        raise Protocol25RecoveryError(
            "accepted audit reconstruction requires Protocol25RunContext"
        )
    ledger = context.ledger.replay()
    if not isinstance(ledger, Protocol25LedgerView):
        raise Protocol25RecoveryError("accepted audit has no protocol-2.5 ledger")
    replay = Protocol25ReplayState()
    for event in context.event_store.replay():
        replay.consume(event)
    results = []
    for audit_target_id, candidate_hash in sorted(replay.audit_candidates.items()):
        artifact_bytes = context.object_store.read_blob(candidate_hash)
        artifact = load_canonical_object(
            artifact_bytes,
            AuditCandidateV1.from_json_dict,
        )
        if (
            artifact.identity != candidate_hash
            or artifact.audit_target_id != audit_target_id
        ):
            raise Protocol25RecoveryError(
                "accepted audit event does not bind its candidate object"
            )
        certifications = tuple(
            item
            for item in ledger.semantic_certifications.values()
            if item.artifact_hash == candidate_hash
            and item.artifact_key_id == artifact.artifact_key.identity
            and item.audit_target_id == audit_target_id
            and item.audit_epoch_id is None
            and item.verdict == "accepted"
        )
        if len(certifications) != 1:
            raise Protocol25RecoveryError(
                "accepted audit candidate has no unique certification"
            )
        certification = certifications[0]
        assessments = tuple(
            item
            for item in ledger.candidate_assessments.values()
            if item.certification_receipt_id == certification.identity
            and item.artifact_hash == candidate_hash
            and item.outcome == "certified"
        )
        if len(assessments) != 1:
            raise Protocol25RecoveryError(
                "accepted audit candidate has no unique candidate assessment"
            )
        assessment = assessments[0]
        normalized_hash = assessment.normalized_authorial_payload_hash
        if normalized_hash is None:
            raise Protocol25RecoveryError(
                "accepted audit candidate omitted normalized payload authority"
            )
        acceptance = ledger.accepted_artifacts.get(artifact.artifact_key.identity)
        if (
            acceptance is None
            or acceptance.artifact_hash != candidate_hash
            or acceptance.certification_receipt_id != certification.identity
        ):
            raise Protocol25RecoveryError(
                "accepted audit candidate has no exact artifact acceptance"
            )
        results.append(
            SemanticCertificationResultV1(
                artifact=artifact,
                artifact_bytes=artifact_bytes,
                normalized_authorial_payload_bytes=context.object_store.read_blob(
                    normalized_hash
                ),
                certification=certification,
                candidate_assessment=assessment,
                acceptance=acceptance,
            )
        )
    return tuple(results)


def publish_audit_epoch(
    context: Protocol25RunContext,
    candidates: tuple[SemanticCertificationResultV1, ...],
    audited_l2_root_hashes: tuple[str, ...],
    *,
    fault_hook: Callable[[str], None] | None = None,
) -> AuditEpochV1:
    """Publish one deterministic audit epoch through object, ledger, and event.

    Every input candidate must already have its semantic certification, shared
    candidate assessment, artifact acceptance, object bytes, and
    ``audit_candidate_accepted`` event durably published.  Re-entry after a
    crash recomputes the same epoch and fills only the missing suffix.
    """
    if not isinstance(context, Protocol25RunContext):
        raise Protocol25RecoveryError("audit epoch requires Protocol25RunContext")
    if fault_hook is not None and not callable(fault_hook):
        raise Protocol25RecoveryError("audit epoch fault hook must be callable or null")
    if not candidates or any(
        not isinstance(item, SemanticCertificationResultV1)
        or not isinstance(item.artifact, AuditCandidateV1)
        for item in candidates
    ):
        raise Protocol25RecoveryError("audit epoch requires certified candidates")
    provided_roots = tuple(audited_l2_root_hashes)
    roots = tuple(sorted(set(provided_roots)))
    if not roots or provided_roots != roots:
        raise Protocol25RecoveryError(
            "audit epoch L2 roots must be nonempty, sorted, and unique"
        )
    for root_hash in roots:
        try:
            context.object_store.read_blob(root_hash)
        except ReV2LedgerError as exc:
            raise Protocol25RecoveryError(
                "audit epoch L2 root object is unavailable"
            ) from exc

    ordered = tuple(
        sorted(candidates, key=lambda item: item.artifact.audit_target_id)
    )
    target_ids = tuple(item.artifact.audit_target_id for item in ordered)
    if target_ids != tuple(sorted(set(target_ids))):
        raise Protocol25RecoveryError("audit epoch candidate targets are not unique")
    policies = {item.artifact.audit_target.audit_policy_hash for item in ordered}
    auditors = {item.artifact.audit_target.auditor_authority_hash for item in ordered}
    if len(policies) != 1 or len(auditors) != 1:
        raise Protocol25RecoveryError(
            "audit epoch candidates disagree on policy or auditor authority"
        )

    ledger = context.ledger.replay()
    if not isinstance(ledger, Protocol25LedgerView):
        raise Protocol25RecoveryError("audit epoch has no protocol-2.5 ledger")
    for result in ordered:
        artifact = result.artifact
        artifact_hash = content_digest(result.artifact_bytes)
        if (
            not isinstance(artifact, AuditCandidateV1)
            or artifact_hash != artifact.identity
            or context.object_store.read_blob(artifact_hash) != result.artifact_bytes
            or context.object_store.read_blob(
                content_digest(result.normalized_authorial_payload_bytes)
            )
            != result.normalized_authorial_payload_bytes
            or ledger.semantic_certifications.get(result.certification.identity)
            != result.certification
            or ledger.candidate_assessments.get(result.candidate_assessment.identity)
            != result.candidate_assessment
            or ledger.accepted_artifacts.get(result.acceptance.artifact_key.identity)
            != result.acceptance
        ):
            raise Protocol25RecoveryError(
                "audit epoch candidate durable receipt chain is not exact"
            )

    events = context.event_store.replay()
    replay = Protocol25ReplayState()
    for event in events:
        replay.consume(event)
    expected_candidates = {
        item.artifact.audit_target_id: item.artifact.identity for item in ordered
    }
    if replay.audit_candidates != expected_candidates:
        raise Protocol25RecoveryError(
            "audit epoch candidates differ from accepted event authority"
        )

    executor = context.semantic_inputs.executor_contract.entry_for("semantic-audit")
    epoch = context.semantic_runtime.freeze_epoch(
        ordered,
        selection_id=context.semantic_graph.manifest.selection.identity,
        audit_policy_hash=next(iter(policies)),
        auditor_authority_hash=next(iter(auditors)),
        executor_authority_hash=executor.executor_contract_hash,
        verifier_authority_hash=context.semantic_runtime.verifier_authority_hash,
        audited_l2_root_hashes=roots,
    )
    epoch_bytes = canonical_json_bytes(epoch.to_json_dict())
    if context.object_store.put_blob(epoch_bytes) != epoch.identity:
        raise Protocol25RecoveryError("audit epoch object hash is not canonical")
    if fault_hook is not None:
        fault_hook(f"audit_epoch_object:{epoch.identity}")

    durable_epochs = context.ledger.replay().audit_epochs
    if durable_epochs:
        if durable_epochs != {epoch.identity: epoch}:
            raise Protocol25RecoveryError("durable audit epoch conflicts with replay")
    else:
        context.ledger.record_audit_epoch(epoch)
        if fault_hook is not None:
            fault_hook(f"audit_epoch_ledger:{epoch.identity}")

    frozen_events = [
        item for item in context.event_store.replay() if item.type == "audit_epoch_frozen"
    ]
    payload = {
        "audit_epoch_id": epoch.identity,
        "audit_target_ids": list(target_ids),
    }
    if frozen_events:
        existing_payload = frozen_events[0].payload
        if (
            len(frozen_events) != 1
            or existing_payload["audit_epoch_id"] != epoch.identity
            or tuple(existing_payload["audit_target_ids"]) != target_ids
        ):
            raise Protocol25RecoveryError("durable audit epoch event conflicts with replay")
    else:
        context.event_store.append(
            "audit_epoch_frozen",
            payload,
            occurred_at=context.clock(),
        )
        if fault_hook is not None:
            fault_hook(f"audit_epoch_event:{epoch.identity}")
    return epoch


def recover_protocol_25_run(context: Protocol25RunContext) -> Protocol25RecoveryResult:
    """Authenticate and reconcile a protocol-2.5 run before controller routing."""
    if not isinstance(context, Protocol25RunContext):
        raise Protocol25RecoveryError("recovery requires Protocol25RunContext")
    manifest = load_run_manifest(context.paths.root.parent)
    if manifest != context.semantic_graph.manifest:
        raise Protocol25RecoveryError(
            "context graph differs from immutable schema-4 manifest authority"
        )
    if context.snapshot_validator is not None:
        context.snapshot_validator()
    events = context.event_store.replay()
    if (
        not events
        or events[0].type != "run_created"
        or events[0].payload["run_manifest_id"] != manifest.run_manifest_id
    ):
        raise Protocol25RecoveryError(
            "run_created does not match immutable schema-4 manifest"
        )
    ledger = context.ledger.replay()
    if not isinstance(ledger, Protocol25LedgerView):
        raise Protocol25RecoveryError("schema-4 run has no protocol-2.5 ledger")
    replay = Protocol25ReplayState()
    for event in events:
        replay.consume(event)

    accepted = _accepted_prerequisites(context, ledger)
    decision = plan_next_v2(
        context.semantic_graph.prerequisite_graph,
        ledger,
        _AvailablePlanningBudget(),
    )
    prerequisite_actions = {item.action for item in decision.explanations.values()}
    prerequisites_complete = not decision.ready and prerequisite_actions <= {"reuse"}
    prerequisites_failed = not decision.ready and bool(
        prerequisite_actions
        & {"failed", "blocked_executor", "blocked_dependency", "blocked_attempts"}
    )
    targets = (
        _target_states(context, ledger, replay, accepted)
        if prerequisites_complete
        else ()
    )
    cycles = _source_cycle_states(replay, targets)
    terminal = None
    if replay.shared.shared.terminal:
        if replay.shared.shared.last_type == "run_completed":
            terminal = (
                "next_epoch_required"
                if "next_epoch_required" in replay.l3_source_root_states.values()
                else "complete"
            )
        else:
            terminal = "blocked_plateau" if replay.plateau_targets else "blocked_incomplete"
    deferred = _deferred_ids(ledger)
    state = Protocol25ControllerStateV1(
        prerequisites_complete=prerequisites_complete,
        prerequisites_failed=prerequisites_failed,
        paused_resource=replay.shared.shared.paused,
        audit_epoch_id=replay.audit_epoch_id,
        targets=targets,
        source_cycles=cycles,
        rooted_source_ids=tuple(sorted(ledger.l3_source_roots)),
        deferred_observation_ids=deferred,
        terminal_state=terminal,
        indeterminate_execution=any(
            item.failure_class == "execution_indeterminate"
            for item in ledger.work_item_failures.values()
        ),
    )
    return Protocol25RecoveryResult(state, events, ledger)


class _AvailablePlanningBudget:
    @staticmethod
    def item_attempt_available(_item: object) -> bool:
        return True


def _accepted_prerequisites(
    context: Protocol25RunContext,
    ledger: Protocol25LedgerView,
) -> Mapping[str, AcceptedArtifactV2]:
    template_ids = {
        item.template_id for item in context.semantic_graph.prerequisite_graph.templates
    }
    result: dict[str, AcceptedArtifactV2] = {}
    for receipt in ledger.accepted_artifacts.values():
        item = ledger.certification_work_items.get(receipt.certification_receipt_id)
        if item is None or item.template_id not in template_ids:
            continue
        result[item.template_id] = AcceptedArtifactV2(
            receipt.artifact_key.identity,
            receipt.artifact_hash,
        )
    return result


def _target_states(
    context: Protocol25RunContext,
    ledger: Protocol25LedgerView,
    replay: Protocol25ReplayState,
    accepted: Mapping[str, AcceptedArtifactV2],
) -> tuple[SemanticTargetControllerStateV1, ...]:
    materialized = context.semantic_graph.ready_audit_targets(accepted)
    if len(materialized) != len(context.semantic_graph.audit_target_plans):
        raise Protocol25RecoveryError(
            "complete prerequisites did not materialize every audit target"
        )
    accepted_authorities = dict(replay.audit_candidates)
    epoch = (
        None
        if replay.audit_epoch_id is None
        else ledger.audit_epochs.get(replay.audit_epoch_id)
    )
    if replay.audit_epoch_id is not None and epoch is None:
        raise Protocol25RecoveryError("frozen audit event has no ledger epoch authority")
    by_epoch_target = {
        item.audit_target_id: item
        for item in (() if epoch is None else epoch.target_candidate_authorities)
    }
    states = []
    for target, template in zip(
        materialized,
        context.semantic_graph.audit_templates,
        strict=True,
    ):
        dependencies = {
            item: accepted[item] for item in template.required_template_ids
        }
        work_item = context.semantic_graph.instantiate_audit_item(
            template,
            target,
            dependencies,
        )
        failure = ledger.work_failure(work_item.work_item_id)
        authority_hash = accepted_authorities.get(target.audit_target_id)
        if authority_hash is not None:
            candidate = load_canonical_object(
                context.object_store.read_blob(authority_hash),
                AuditCandidateV1.from_json_dict,
            )
            if candidate.audit_target != target:
                raise Protocol25RecoveryError(
                    "accepted audit candidate does not match materialized target"
                )
            frozen = tuple(item.finding_key_id for item in candidate.findings)
            audit_state = "accepted"
        elif failure is not None:
            frozen = ()
            audit_state = "failed"
        else:
            frozen = ()
            audit_state = "pending"
        epoch_authority = by_epoch_target.get(target.audit_target_id)
        if epoch_authority is not None:
            if authority_hash != epoch_authority.candidate_hash:
                raise Protocol25RecoveryError(
                    "frozen target differs from accepted audit authority"
                )
            frozen = epoch_authority.finding_key_ids
        unresolved = tuple(
            finding_id
            for finding_id in frozen
            if finding_id not in ledger.latest_finding_closures
            or ledger.latest_finding_closures[finding_id].verdict != "closed"
        )
        stage = "idle"
        for cycle in replay.source_cycles.values():
            if target.audit_target_id in cycle.target_assessments:
                stage = "assessment_accepted"
            elif target.audit_target_id in cycle.accepted_resolution_targets:
                stage = "resolution_accepted"
        if target.audit_target_id in replay.plateau_targets:
            stage = "plateau_recorded"
        states.append(
            SemanticTargetControllerStateV1(
                audit_target_id=target.audit_target_id,
                source_id=target.scope.source_id,
                audit_state=audit_state,  # type: ignore[arg-type]
                frozen_finding_ids=frozen,
                unresolved_finding_ids=unresolved,
                semantic_round=replay.rounds_by_target.get(target.audit_target_id, 0),
                no_reduction_rounds=replay.no_reduction_rounds_by_target.get(
                    target.audit_target_id, 0
                ),
                stage=stage,  # type: ignore[arg-type]
            )
        )
    return tuple(sorted(states, key=lambda item: item.audit_target_id))


def _source_cycle_states(
    replay: Protocol25ReplayState,
    targets: tuple[SemanticTargetControllerStateV1, ...],
) -> tuple[SemanticSourceCycleStateV1, ...]:
    by_target = {item.audit_target_id: item for item in targets}
    result = []
    for cycle in replay.source_cycles.values():
        if cycle.complete:
            continue
        participants = tuple(
            sorted(
                item.audit_target_id
                for item in targets
                if item.source_id == cycle.source_id
                and item.unresolved_finding_ids
                and item.semantic_round + 1 == cycle.semantic_round
            )
        )
        if not participants:
            participants = tuple(sorted(cycle.resolution_targets))
        if not participants or any(item not in by_target for item in participants):
            raise Protocol25RecoveryError(
                "active source cycle has no reconstructable target batch"
            )
        if cycle.guard_passed is None:
            guard = "pending"
        elif cycle.guard_passed is False:
            guard = "failed"
        else:
            complete_receipts = all(
                set(cycle.closure_verdicts_by_target.get(target_id, {}))
                == set(by_target[target_id].unresolved_finding_ids)
                for target_id in participants
            )
            guard = "receipts_recorded" if complete_receipts else "passed"
        result.append(
            SemanticSourceCycleStateV1(
                source_id=cycle.source_id,
                source_cycle_id=cycle.source_cycle_id,
                semantic_round=cycle.semantic_round,
                participating_target_ids=participants,
                guard_stage=guard,  # type: ignore[arg-type]
            )
        )
    return tuple(sorted(result, key=lambda item: item.source_id))


def _deferred_ids(ledger: Protocol25LedgerView) -> tuple[str, ...]:
    values = {
        observation.observation_id
        for assessment in ledger.target_closure_assessments.values()
        for observation in assessment.deferred_observations
    }
    values.update(
        observation.observation_id
        for assessment in ledger.source_composition_assessments.values()
        for observation in assessment.deferred_observations
    )
    return tuple(sorted(values))


def _accepted_l2_root_hashes(
    context: Protocol25RunContext,
    ledger: Protocol25LedgerView,
) -> tuple[str, ...]:
    selected_sources = set(context.semantic_graph.selected_source_ids)
    template_ids = {
        item.template_id
        for item in context.semantic_graph.prerequisite_graph.templates
        if item.layer == "L2"
        and item.artifact_kind == "source-baseline-root"
        and item.scope.source_id in selected_sources
    }
    roots = []
    observed_sources = set()
    for certification_id, item in ledger.certification_work_items.items():
        if item.template_id not in template_ids:
            continue
        acceptance = ledger.accepted_artifacts.get(item.output_key.identity)
        if (
            acceptance is None
            or acceptance.certification_receipt_id != certification_id
        ):
            raise Protocol25RecoveryError(
                "selected L2 source root has no exact artifact acceptance"
            )
        roots.append(acceptance.artifact_hash)
        observed_sources.add(item.output_key.scope.source_id)
    if observed_sources != selected_sources or len(roots) != len(selected_sources):
        raise Protocol25RecoveryError(
            "audit epoch does not have one accepted L2 root per selected source"
        )
    return tuple(sorted(roots))


def _apply_controller_action(
    context: Protocol25RunContext,
    action: Protocol25ControllerActionV1,
) -> None:
    if not isinstance(action, Protocol25ControllerActionV1):
        raise Protocol25RecoveryError(
            "semantic action must be Protocol25ControllerActionV1"
        )
    if action.kind == "freeze_epoch":
        recovered = recover_protocol_25_run(context)
        state = recovered.controller_state
        if (
            not state.prerequisites_complete
            or state.prerequisites_failed
            or any(item.audit_state != "accepted" for item in state.targets)
        ):
            raise Protocol25RecoveryError(
                "audit epoch cannot freeze before every selected audit is accepted"
            )
        candidates = reconstruct_accepted_audit_results(context)
        if {item.artifact.audit_target_id for item in candidates} != {
            item.audit_target_id for item in state.targets
        }:
            raise Protocol25RecoveryError(
                "accepted audit candidates differ from recovered target authority"
            )
        epoch = publish_audit_epoch(
            context,
            candidates,
            _accepted_l2_root_hashes(context, recovered.ledger),
        )
        if state.audit_epoch_id is not None and state.audit_epoch_id != epoch.identity:
            raise Protocol25RecoveryError(
                "recovered audit epoch differs from deterministic publication"
            )
        return
    terminal = {
        "terminal_complete": (
            "run_completed",
            "all selected protocol-2.5 sources are closed",
        ),
        "terminal_next_epoch": (
            "run_completed",
            "audit epoch closed with deferred observations",
        ),
        "terminal_blocked_incomplete": (
            "run_failed",
            "semantic closure is incomplete",
        ),
        "terminal_blocked_plateau": (
            "run_failed",
            "semantic closure reached plateau",
        ),
    }.get(action.kind)
    if terminal is not None:
        events = context.event_store.replay()
        existing = next(
            (
                item
                for item in events
                if item.type in {"run_completed", "run_failed"}
            ),
            None,
        )
        if existing is not None:
            if existing.type != terminal[0] or existing.payload["reason"] != terminal[1]:
                raise Protocol25RecoveryError(
                    "durable terminal event conflicts with requested semantic state"
                )
            return
        context.event_store.append(
            terminal[0],
            {"reason": terminal[1]},
            occurred_at=context.clock(),
        )
        return
    raise Protocol25RecoveryError(
        f"protocol-2.5 action {action.kind!r} has no durable reconciler"
    )


__all__ = (
    "Protocol25RecoveryError",
    "Protocol25RecoveryResult",
    "Protocol25RunContext",
    "publish_audit_epoch",
    "reconstruct_accepted_audit_results",
    "recover_protocol_25_run",
)
