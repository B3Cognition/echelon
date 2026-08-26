"""Schema-4 recovery strategy over the shared RE v2 durable kernel."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Callable, Mapping

from harness.re_v2.events import EventRecord
from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.ledger import ReV2LedgerError
from harness.re_v2.protocol_22.graph import (
    AcceptedArtifactV2,
    plan_next_v2,
)
from harness.re_v2.protocol_22.model import WorkItemV2
from harness.re_v2.protocol_22.budget import evaluate_budget_v22
from harness.re_v2.protocol_22.execution import ProviderExecutionDependenciesV1
from harness.re_v2.protocol_22.recovery import (
    Protocol22RecoveryResult,
    Protocol22RunContext,
)
from harness.re_v2.protocol_22.schema import load_canonical_object
from harness.re_v2.run_store import load_run_manifest

from .artifacts import AuditCandidateV1, AuditEpochV1
from .controller import (
    Protocol25Controller,
    Protocol25ControllerActionV1,
    Protocol25ControllerStateV1,
    SemanticSourceCycleStateV1,
    SemanticTargetControllerStateV1,
    plan_next_protocol_25,
)
from .events import PROTOCOL_25_EVENTS, Protocol25ReplayState
from .graph import Protocol25Graph, Protocol25GraphError
from .inputs import ValidatedProtocol25Inputs
from .ledger import Protocol25LedgerView
from .runtime import (
    Protocol25DeterministicRuntime,
    Protocol25RuntimeError,
    SemanticCertificationResultV1,
    SemanticContextV1,
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
        inherited_dependencies = self.dependencies_for
        semantic_bindings: dict[
            str,
            tuple[WorkItemV2, Protocol25ControllerActionV1],
        ] = {}
        if not getattr(inherited_dependencies, "_protocol_25_specialized", False):
            def semantic_dependencies(
                item: WorkItemV2,
                attempt_kind: str,
            ) -> object:
                if item.output_key.layer != "L3":
                    return inherited_dependencies(item, attempt_kind)
                if item.output_key.artifact_kind == "semantic-audit-findings":
                    if len(item.output_key.dependency_hashes) != 1:
                        raise Protocol25RecoveryError(
                            "semantic audit item has no unique target dependency"
                        )
                    authorized_item, semantic_context = build_audit_dispatch_authority(
                        self,
                        item.output_key.dependency_hashes[0],
                    )
                elif item.output_key.artifact_kind == "semantic-resolution-overlay":
                    action = plan_next_protocol_25(
                        recover_protocol_25_run(self).controller_state
                    )
                    if action is None or action.kind != "resolve_target":
                        raise Protocol25RecoveryError(
                            "resolution item has no current controller authority"
                        )
                    authorized_item, semantic_context = (
                        build_resolution_dispatch_authority(self, action)
                    )
                    semantic_bindings[item.work_item_id] = (item, action)
                elif item.output_key.artifact_kind == "target-closure-assessment":
                    action = plan_next_protocol_25(
                        recover_protocol_25_run(self).controller_state
                    )
                    if action is None or action.kind != "recheck_target":
                        raise Protocol25RecoveryError(
                            "closure recheck item has no current controller authority"
                        )
                    authorized_item, semantic_context = (
                        build_recheck_dispatch_authority(self, action)
                    )
                    semantic_bindings[item.work_item_id] = (item, action)
                elif item.output_key.artifact_kind == "source-composition-assessment":
                    action = plan_next_protocol_25(
                        recover_protocol_25_run(self).controller_state
                    )
                    if action is None or action.kind != "guard_source":
                        raise Protocol25RecoveryError(
                            "source guard item has no current controller authority"
                        )
                    authorized_item, semantic_context = (
                        build_source_guard_dispatch_authority(self, action)
                    )
                    semantic_bindings[item.work_item_id] = (item, action)
                else:
                    raise Protocol25RecoveryError(
                        "semantic dependency specialization is not implemented "
                        f"for {item.output_key.artifact_kind!r}"
                    )
                if authorized_item != item:
                    raise Protocol25RecoveryError(
                        "semantic item differs from reconstructed authority"
                    )
                return build_semantic_provider_dependencies(
                    self,
                    item,
                    semantic_context,
                )

            setattr(semantic_dependencies, "_protocol_25_specialized", True)
            setattr(
                semantic_dependencies,
                "_protocol_25_semantic_bindings",
                semantic_bindings,
            )
            object.__setattr__(self, "dependencies_for", semantic_dependencies)

    def bind_semantic_dispatch(self, dispatch_id: str) -> None:
        """Bind an L3 operation at the inherited controller's durable fault seam."""
        if not isinstance(dispatch_id, str) or not dispatch_id:
            raise Protocol25RecoveryError("semantic dispatch ID must be nonempty")
        bindings = getattr(
            self.dependencies_for,
            "_protocol_25_semantic_bindings",
            None,
        )
        if not isinstance(bindings, dict):
            return
        matches = tuple(
            event
            for event in self.event_store.replay()
            if event.type == "dispatch_started"
            and event.payload["dispatch_id"] == dispatch_id
        )
        if len(matches) != 1:
            raise Protocol25RecoveryError(
                "semantic dispatch boundary has no unique durable start"
            )
        work_item_id = str(matches[0].payload["work_item_id"])
        binding = bindings.pop(work_item_id, None)
        if binding is None:
            return
        item, action = binding
        _bind_semantic_dispatch(self, item, action, dispatch_id)

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


def build_audit_dispatch_authority(
    context: Protocol25RunContext,
    audit_target_id: str,
) -> tuple[WorkItemV2, SemanticContextV1]:
    """Materialize one audit work item and its exact bounded provider context."""
    if not isinstance(context, Protocol25RunContext):
        raise Protocol25RecoveryError(
            "audit dispatch authority requires Protocol25RunContext"
        )
    ledger = context.ledger.replay()
    if not isinstance(ledger, Protocol25LedgerView):
        raise Protocol25RecoveryError("audit dispatch has no protocol-2.5 ledger")
    accepted = _accepted_prerequisites(context, ledger)
    materialized = context.semantic_graph.ready_audit_targets(accepted)
    selected = tuple(
        (target, template)
        for target, template in zip(
            materialized,
            context.semantic_graph.audit_templates,
            strict=True,
        )
        if target.audit_target_id == audit_target_id
    )
    if len(selected) != 1:
        raise Protocol25RecoveryError(
            "audit action has no unique ready target authority"
        )
    target, template = selected[0]
    dependencies = {
        template_id: accepted[template_id]
        for template_id in template.required_template_ids
    }
    item = context.semantic_graph.instantiate_audit_item(
        template,
        target,
        dependencies,
    )
    lower_hashes = tuple(
        sorted(
            {
                *(authority.artifact_hash for authority in target.audited_artifacts),
                *target.lower_dependency_hashes,
                *target.context_object_hashes,
                *target.evidence_object_hashes,
            }
        )
    )
    try:
        payloads = {
            object_hash: context.object_store.read_blob(object_hash)
            for object_hash in lower_hashes
        }
        semantic_context = context.semantic_runtime.build_audit_context(
            audit_target=target,
            workspace_partition=context.semantic_inputs.workspace_partition,
            authority_payloads=payloads,
        )
    except (ReV2LedgerError, Protocol25GraphError, Protocol25RuntimeError) as exc:
        raise Protocol25RecoveryError(
            "audit provider context cannot be reconstructed from accepted L2 authority"
        ) from exc
    context_bytes = canonical_json_bytes(semantic_context.to_json_dict())
    context.object_store.put_blob(context_bytes)
    return item, semantic_context


def build_resolution_dispatch_authority(
    context: Protocol25RunContext,
    action: Protocol25ControllerActionV1,
) -> tuple[WorkItemV2, SemanticContextV1]:
    """Materialize one frozen-target resolution through existing L3 authority."""
    from .artifacts import SemanticResolutionOverlayV1

    if (
        not isinstance(context, Protocol25RunContext)
        or not isinstance(action, Protocol25ControllerActionV1)
        or action.kind != "resolve_target"
        or action.audit_target_id is None
        or action.source_id is None
        or action.semantic_round is None
    ):
        raise Protocol25RecoveryError(
            "resolution dispatch requires exact controller action authority"
        )
    ledger = context.ledger.replay()
    if not isinstance(ledger, Protocol25LedgerView) or len(ledger.audit_epochs) != 1:
        raise Protocol25RecoveryError("resolution dispatch requires one frozen epoch")
    epoch = next(iter(ledger.audit_epochs.values()))
    frozen_reference = context.semantic_graph.manifest.frozen_audit_epoch
    if frozen_reference is not None and epoch.identity != frozen_reference.object_hash:
        raise Protocol25RecoveryError("resolution epoch differs from successor authority")
    target_authority = next(
        (
            item
            for item in epoch.target_candidate_authorities
            if item.audit_target_id == action.audit_target_id
        ),
        None,
    )
    if target_authority is None:
        raise Protocol25RecoveryError("resolution target is outside the frozen epoch")
    candidate = load_canonical_object(
        context.object_store.read_blob(target_authority.candidate_hash),
        AuditCandidateV1.from_json_dict,
    )
    if candidate.audit_target.scope.source_id != action.source_id:
        raise Protocol25RecoveryError("resolution action source differs from target")
    unresolved = tuple(
        finding
        for finding in candidate.findings
        if finding.finding_key_id not in ledger.latest_finding_closures
        or ledger.latest_finding_closures[finding.finding_key_id].verdict != "closed"
    )
    if not unresolved:
        raise Protocol25RecoveryError("resolution action has no unresolved findings")

    prior: list[SemanticResolutionOverlayV1] = []
    for acceptance in ledger.accepted_artifacts.values():
        if acceptance.artifact_key.artifact_kind != "semantic-resolution-overlay":
            continue
        overlay = load_canonical_object(
            context.object_store.read_blob(acceptance.artifact_hash),
            SemanticResolutionOverlayV1.from_json_dict,
        )
        if overlay.audit_epoch_id == epoch.identity and overlay.audit_target_id == action.audit_target_id:
            prior.append(overlay)
    prior.sort(key=lambda item: (item.semantic_round, item.identity))
    if tuple(item.semantic_round for item in prior) != tuple(range(1, action.semantic_round)):
        raise Protocol25RecoveryError(
            "resolution prior overlay chain is not consecutive"
        )
    prior_hashes = tuple(item.identity for item in prior)

    audit_item, base_context = build_audit_dispatch_authority(
        context,
        action.audit_target_id,
    )
    authority_payloads = {
        item.object_hash: item.payload_bytes for item in base_context.authority_objects
    }
    for overlay in prior:
        authority_payloads[overlay.identity] = context.object_store.read_blob(
            overlay.identity
        )
    semantic_context = context.semantic_runtime.build_context(
        mode="SEMANTIC_RESOLUTION",
        audit_target=candidate.audit_target,
        vocabulary=base_context.vocabulary,
        authorized_evidence=base_context.authorized_evidence,
        authority_payloads=authority_payloads,
        lower_authority_hashes=base_context.lower_authority_hashes,
        unresolved_findings=unresolved,
        overlay_hashes=prior_hashes,
        target_assessment_hashes=(),
        active_sibling_authority_hashes=(),
    )
    context.object_store.put_blob(canonical_json_bytes(semantic_context.to_json_dict()))

    manifest = context.semantic_graph.manifest
    guidance_hash = (
        None
        if manifest.human_guidance is None
        else manifest.human_guidance.object_hash
    )
    dependencies = tuple(
        sorted(
            (
                epoch.identity,
                action.audit_target_id,
                *prior_hashes,
                *((guidance_hash,) if guidance_hash is not None else ()),
            )
        )
    )
    return (
        _semantic_operation_item(
            context,
            audit_item,
            candidate.audit_target,
            "semantic-resolution-overlay",
            dependencies,
        ),
        semantic_context,
    )


def build_recheck_dispatch_authority(
    context: Protocol25RunContext,
    action: Protocol25ControllerActionV1,
) -> tuple[WorkItemV2, SemanticContextV1]:
    """Materialize one closure recheck over its accepted resolution overlay."""
    from .artifacts import SemanticResolutionOverlayV1

    if (
        not isinstance(context, Protocol25RunContext)
        or not isinstance(action, Protocol25ControllerActionV1)
        or action.kind != "recheck_target"
        or action.audit_target_id is None
        or action.source_id is None
        or action.semantic_round is None
    ):
        raise Protocol25RecoveryError(
            "closure recheck requires exact controller action authority"
        )
    ledger = context.ledger.replay()
    if not isinstance(ledger, Protocol25LedgerView) or len(ledger.audit_epochs) != 1:
        raise Protocol25RecoveryError("closure recheck requires one frozen epoch")
    epoch = next(iter(ledger.audit_epochs.values()))
    target_authority = next(
        (
            item
            for item in epoch.target_candidate_authorities
            if item.audit_target_id == action.audit_target_id
        ),
        None,
    )
    if target_authority is None:
        raise Protocol25RecoveryError("closure recheck target is outside the epoch")
    candidate = load_canonical_object(
        context.object_store.read_blob(target_authority.candidate_hash),
        AuditCandidateV1.from_json_dict,
    )
    unresolved = tuple(
        finding
        for finding in candidate.findings
        if finding.finding_key_id not in ledger.latest_finding_closures
        or ledger.latest_finding_closures[finding.finding_key_id].verdict != "closed"
    )
    overlays = []
    for acceptance in ledger.accepted_artifacts.values():
        if acceptance.artifact_key.artifact_kind != "semantic-resolution-overlay":
            continue
        overlay = load_canonical_object(
            context.object_store.read_blob(acceptance.artifact_hash),
            SemanticResolutionOverlayV1.from_json_dict,
        )
        if (
            overlay.audit_epoch_id == epoch.identity
            and overlay.audit_target_id == action.audit_target_id
            and overlay.semantic_round == action.semantic_round
        ):
            overlays.append(overlay)
    if len(overlays) != 1:
        raise Protocol25RecoveryError(
            "closure recheck has no unique accepted resolution overlay"
        )
    overlay = overlays[0]
    audit_item, base_context = build_audit_dispatch_authority(
        context,
        action.audit_target_id,
    )
    authority_payloads = {
        item.object_hash: item.payload_bytes for item in base_context.authority_objects
    }
    authority_payloads[overlay.identity] = context.object_store.read_blob(
        overlay.identity
    )
    semantic_context = context.semantic_runtime.build_context(
        mode="CLOSURE_RECHECK",
        audit_target=candidate.audit_target,
        vocabulary=base_context.vocabulary,
        authorized_evidence=base_context.authorized_evidence,
        authority_payloads=authority_payloads,
        lower_authority_hashes=base_context.lower_authority_hashes,
        unresolved_findings=unresolved,
        overlay_hashes=(overlay.identity,),
        target_assessment_hashes=(),
        active_sibling_authority_hashes=(),
    )
    context.object_store.put_blob(canonical_json_bytes(semantic_context.to_json_dict()))
    item = _semantic_operation_item(
        context,
        audit_item,
        candidate.audit_target,
        "target-closure-assessment",
        (epoch.identity, overlay.identity),
    )
    return item, semantic_context


def build_source_guard_dispatch_authority(
    context: Protocol25RunContext,
    action: Protocol25ControllerActionV1,
) -> tuple[WorkItemV2, SemanticContextV1]:
    """Materialize one source-wide composed guard over a complete target batch."""
    from .artifacts import (
        FindingClosureReceiptV1,
        SemanticResolutionOverlayV1,
        TargetClosureAssessmentV1,
    )

    if (
        not isinstance(context, Protocol25RunContext)
        or not isinstance(action, Protocol25ControllerActionV1)
        or action.kind != "guard_source"
        or action.source_id is None
        or action.semantic_round is None
        or not action.participating_target_ids
    ):
        raise Protocol25RecoveryError(
            "source guard requires exact controller action authority"
        )
    ledger = context.ledger.replay()
    if not isinstance(ledger, Protocol25LedgerView) or len(ledger.audit_epochs) != 1:
        raise Protocol25RecoveryError("source guard requires one frozen epoch")
    epoch = next(iter(ledger.audit_epochs.values()))
    candidates: dict[str, AuditCandidateV1] = {}
    for authority in epoch.target_candidate_authorities:
        candidate = load_canonical_object(
            context.object_store.read_blob(authority.candidate_hash),
            AuditCandidateV1.from_json_dict,
        )
        candidates[authority.audit_target_id] = candidate
    source_candidates = tuple(
        candidate
        for candidate in candidates.values()
        if candidate.audit_target.target_kind == "source"
        and candidate.audit_target.scope.source_id == action.source_id
    )
    if len(source_candidates) != 1:
        raise Protocol25RecoveryError("source guard has no unique source audit target")
    source_candidate = source_candidates[0]
    participants = set(action.participating_target_ids)
    if any(
        target_id not in candidates
        or candidates[target_id].audit_target.scope.source_id != action.source_id
        for target_id in participants
    ):
        raise Protocol25RecoveryError("source guard participant is outside its source")

    overlays = []
    for acceptance in ledger.accepted_artifacts.values():
        if acceptance.artifact_key.artifact_kind != "semantic-resolution-overlay":
            continue
        overlay = load_canonical_object(
            context.object_store.read_blob(acceptance.artifact_hash),
            SemanticResolutionOverlayV1.from_json_dict,
        )
        if (
            overlay.audit_epoch_id == epoch.identity
            and overlay.audit_target_id in participants
            and overlay.semantic_round == action.semantic_round
        ):
            overlays.append(overlay)
    overlays.sort(key=lambda item: (item.audit_target_id, item.identity))
    if {item.audit_target_id for item in overlays} != participants:
        raise Protocol25RecoveryError(
            "source guard does not have one current overlay per participant"
        )
    assessments = tuple(
        sorted(
            (
                item
                for item in ledger.target_closure_assessments.values()
                if item.audit_epoch_id == epoch.identity
                and item.audit_target_id in participants
                and item.resolution_overlay_hash
                in {overlay.identity for overlay in overlays}
            ),
            key=lambda item: (item.audit_target_id, item.identity),
        )
    )
    if {item.audit_target_id for item in assessments} != participants:
        raise Protocol25RecoveryError(
            "source guard does not have one current assessment per participant"
        )
    findings_by_id = {
        finding.finding_key_id: finding
        for candidate in candidates.values()
        if candidate.audit_target.scope.source_id == action.source_id
        for finding in candidate.findings
    }
    active_ids = tuple(
        sorted(
            {
                finding_id
                for overlay in overlays
                for finding_id in overlay.finding_key_ids
            }
        )
    )
    try:
        unresolved = tuple(findings_by_id[item] for item in active_ids)
    except KeyError as exc:
        raise Protocol25RecoveryError(
            "source guard overlay finding is outside source candidates"
        ) from exc
    active_siblings = tuple(
        sorted(
            receipt.identity
            for finding_id, receipt in ledger.latest_finding_closures.items()
            if receipt.verdict == "closed"
            and finding_id in findings_by_id
            and finding_id not in active_ids
        )
    )
    audit_item, base_context = build_audit_dispatch_authority(
        context,
        source_candidate.audit_target_id,
    )
    authority_payloads = {
        item.object_hash: item.payload_bytes for item in base_context.authority_objects
    }
    for authority in (*overlays, *assessments):
        authority_payloads[authority.identity] = context.object_store.read_blob(
            authority.identity
        )
    for receipt_id in active_siblings:
        receipt = ledger.finding_closures[receipt_id]
        if not isinstance(receipt, FindingClosureReceiptV1):
            raise Protocol25RecoveryError("source guard sibling receipt is invalid")
        authority_payloads[receipt_id] = context.object_store.read_blob(receipt_id)
    semantic_context = context.semantic_runtime.build_context(
        mode="SOURCE_COMPOSITION_GUARD",
        audit_target=source_candidate.audit_target,
        vocabulary=base_context.vocabulary,
        authorized_evidence=base_context.authorized_evidence,
        authority_payloads=authority_payloads,
        lower_authority_hashes=base_context.lower_authority_hashes,
        unresolved_findings=unresolved,
        overlay_hashes=tuple(item.identity for item in overlays),
        target_assessment_hashes=tuple(item.identity for item in assessments),
        active_sibling_authority_hashes=active_siblings,
    )
    context.object_store.put_blob(canonical_json_bytes(semantic_context.to_json_dict()))
    composed = context.semantic_runtime.build_composed_view(
        context=semantic_context,
        epoch=epoch,
        source_id=action.source_id,
        overlays=tuple(overlays),
        target_assessments=assessments,
    )
    context.object_store.put_blob(canonical_json_bytes(composed.to_json_dict()))
    dependencies = tuple(
        sorted(
            (
                epoch.identity,
                *(item.identity for item in overlays),
                *(item.identity for item in assessments),
            )
        )
    )
    return (
        _semantic_operation_item(
            context,
            audit_item,
            source_candidate.audit_target,
            "source-composition-assessment",
            dependencies,
        ),
        semantic_context,
    )


def _semantic_operation_item(
    context: Protocol25RunContext,
    audit_item: WorkItemV2,
    audit_target: object,
    artifact_kind: str,
    dependencies: tuple[str, ...],
) -> WorkItemV2:
    from harness.re_v2.protocol_22.model import (
        ArtifactKeyV2,
        WorkTemplateV2,
        instantiate_work_item_v2,
    )

    from .findings import AuditTargetV1
    from .policies import SEMANTIC_PRODUCER_PROTOCOL_BY_ARTIFACT

    if not isinstance(audit_target, AuditTargetV1):
        raise Protocol25RecoveryError("semantic operation audit target is invalid")
    family = {
        "semantic-resolution-overlay": "semantic-resolution",
        "target-closure-assessment": "closure-recheck",
        "source-composition-assessment": "source-composition-guard",
    }.get(artifact_kind)
    if family is None:
        raise Protocol25RecoveryError("semantic operation artifact kind is unsupported")
    policy = context.semantic_inputs.artifact_policy.entry_for("L3", artifact_kind)
    executor = context.semantic_inputs.executor_contract.entry_for(family)
    manifest = context.semantic_graph.manifest
    template = WorkTemplateV2(
        identity_schema_version=2,
        goal_id="semantic-audit-closure",
        scope=audit_target.scope,
        artifact_kind=artifact_kind,
        layer="L3",
        producer_id=(
            "echelon.re-resolver"
            if family == "semantic-resolution"
            else "echelon.re-validator"
        ),
        producer_family=family,
        producer_protocol_version=SEMANTIC_PRODUCER_PROTOCOL_BY_ARTIFACT[
            artifact_kind
        ],
        layer_policy_hash=policy.identity,
        required_template_ids=(),
        executor_contract_hash=executor.executor_contract_hash,
        verifier_id=executor.verifier.verifier_id,
        verifier_version=executor.verifier.verifier_version,
        verifier_implementation_digest=executor.verifier.implementation_digest,
        result_contract_id=executor.result_contract_id,
        max_provider_attempts=manifest.semantic_closure_policy.provider_attempt_limit,
        max_generation_attempts=manifest.semantic_closure_policy.provider_attempt_limit,
        max_semantic_rounds=0,
        max_result_contract_retries=manifest.semantic_closure_policy.contract_retry_limit,
        max_shared_retries=manifest.initial_budget_policy.shared_retry_limit,
        max_artifact_contract_retries=manifest.semantic_closure_policy.contract_retry_limit,
    )
    key = ArtifactKeyV2(
        identity_schema_version=2,
        scope=audit_target.scope,
        partition_id=audit_item.output_key.partition_id,
        artifact_kind=artifact_kind,
        layer="L3",
        producer_protocol_version=template.producer_protocol_version,
        layer_policy_hash=policy.identity,
        dependency_hashes=dependencies,
    )
    return instantiate_work_item_v2(template, key, dependencies)


def _bind_semantic_dispatch(
    context: Protocol25RunContext,
    item: WorkItemV2,
    action: Protocol25ControllerActionV1,
    dispatch_id: str,
) -> None:
    event_by_action = {
        "resolve_target": "semantic_resolution_started",
        "recheck_target": "closure_recheck_started",
        "guard_source": "source_composition_guard_started",
    }
    event_type = event_by_action.get(action.kind)
    if event_type is None or (
        action.kind != "guard_source" and action.audit_target_id is None
    ):
        raise Protocol25RecoveryError("semantic dispatch binding is unsupported")
    payload = {
        "dispatch_id": dispatch_id,
        "semantic_round": action.semantic_round,
        "source_cycle_id": action.source_cycle_id,
        "source_id": action.source_id,
        "work_item_id": item.work_item_id,
    }
    if action.kind == "guard_source":
        payload["participating_target_ids"] = list(
            action.participating_target_ids
        )
    else:
        payload["audit_target_id"] = action.audit_target_id
    context.event_store.append(
        event_type,
        payload,
        occurred_at=context.clock(),
    )


def build_semantic_provider_dependencies(
    context: Protocol25RunContext,
    item: WorkItemV2,
    semantic_context: SemanticContextV1,
) -> ProviderExecutionDependenciesV1:
    """Bind semantic authority to the inherited Prosaic provider contract."""
    if not isinstance(context, Protocol25RunContext):
        raise Protocol25RecoveryError(
            "semantic provider dependencies require Protocol25RunContext"
        )
    if not isinstance(item, WorkItemV2) or item.output_key.layer != "L3":
        raise Protocol25RecoveryError(
            "semantic provider dependencies require an L3 work item"
        )
    if not isinstance(semantic_context, SemanticContextV1):
        raise Protocol25RecoveryError("semantic provider context is invalid")
    executor = context.semantic_inputs.executor_contract.entry_for(
        item.producer_family
    )
    renderer = executor.request_renderer
    if (
        executor.execution_mode != "cli"
        or renderer is None
        or len(renderer.response_schemas) != 1
        or renderer.response_schemas[0].artifact_kind
        != item.output_key.artifact_kind
    ):
        raise Protocol25RecoveryError(
            "semantic executor does not expose the shared Prosaic CLI contract"
        )
    try:
        agent_bytes = context.object_store.read_blob(renderer.agent_contract_hash)
        response_schema_bytes = context.object_store.read_blob(
            renderer.response_schemas[0].schema_hash
        )
    except ReV2LedgerError as exc:
        raise Protocol25RecoveryError(
            "semantic Prosaic agent or response schema is unavailable"
        ) from exc
    return ProviderExecutionDependenciesV1(
        executor=executor,
        registry=context.installed_authorities,
        agent_bytes=agent_bytes,
        context_bytes=canonical_json_bytes(semantic_context.to_json_dict()),
        response_schema_bytes=response_schema_bytes,
        tokenizer=None,
    )


def _shared_action_recovery(
    context: Protocol25RunContext,
    recovered: Protocol25RecoveryResult,
) -> Protocol22RecoveryResult:
    manifest = context.semantic_graph.manifest
    budget = evaluate_budget_v22(
        manifest.initial_budget_policy,
        recovered.events,
        (),
        context.clock(),
        event_protocol=PROTOCOL_25_EVENTS,
    )
    return Protocol22RecoveryResult(
        manifest=manifest,  # type: ignore[arg-type]
        inputs=context.inputs,
        graph=context.graph,
        events=recovered.events,
        ledger=recovered.ledger,
        budget=budget,
        dispatch_actions={},
        operational_state="ready",
    )


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


def _accepted_l2_root_hash_by_source(
    context: Protocol25RunContext,
    ledger: Protocol25LedgerView,
) -> Mapping[str, str]:
    selected_sources = set(context.semantic_graph.selected_source_ids)
    template_by_id = {
        item.template_id: item
        for item in context.semantic_graph.prerequisite_graph.templates
        if item.layer == "L2" and item.artifact_kind == "source-baseline-root"
    }
    result = {}
    for certification_id, item in ledger.certification_work_items.items():
        template = template_by_id.get(item.template_id)
        if template is None or template.scope.source_id not in selected_sources:
            continue
        acceptance = ledger.accepted_artifacts.get(item.output_key.identity)
        if acceptance is None or acceptance.certification_receipt_id != certification_id:
            raise Protocol25RecoveryError(
                "selected L2 source root has no exact artifact acceptance"
            )
        source_id = template.scope.source_id
        if source_id in result:
            raise Protocol25RecoveryError("selected source has multiple L2 roots")
        result[source_id] = acceptance.artifact_hash
    if set(result) != selected_sources:
        raise Protocol25RecoveryError("selected source is missing its accepted L2 root")
    return MappingProxyType(dict(sorted(result.items())))


def _apply_controller_action(
    context: Protocol25RunContext,
    action: Protocol25ControllerActionV1,
) -> None:
    if not isinstance(action, Protocol25ControllerActionV1):
        raise Protocol25RecoveryError(
            "semantic action must be Protocol25ControllerActionV1"
        )
    if action.kind == "run_prerequisite":
        recovered = recover_protocol_25_run(context)
        recovery = _shared_action_recovery(context, recovered)
        decision = plan_next_v2(
            context.semantic_graph.prerequisite_graph,
            recovered.ledger,
            recovery.budget,
        )
        if not decision.ready:
            raise Protocol25RecoveryError(
                "prerequisite action has no shared ready work item"
            )
        Protocol25Controller(context)._execute_one(decision.ready[0], recovery)
        return
    if action.kind == "audit_target":
        recovered = recover_protocol_25_run(context)
        if (
            not recovered.controller_state.prerequisites_complete
            or recovered.controller_state.audit_epoch_id is not None
            or action.audit_target_id is None
        ):
            raise Protocol25RecoveryError(
                "audit action is outside the pre-freeze ready state"
            )
        item, semantic_context = build_audit_dispatch_authority(
            context,
            action.audit_target_id,
        )
        dependencies = context.dependencies_for(item, "initial_generation")
        expected_context_bytes = canonical_json_bytes(semantic_context.to_json_dict())
        if (
            not isinstance(dependencies, ProviderExecutionDependenciesV1)
            or dependencies.context_bytes != expected_context_bytes
            or dependencies.executor
            != context.semantic_inputs.executor_contract.entry_for(
                item.producer_family
            )
        ):
            raise Protocol25RecoveryError(
                "semantic dependency resolver differs from audit authority"
            )
        Protocol25Controller(context)._execute_one(
            item,
            _shared_action_recovery(context, recovered),
        )
        return
    if action.kind == "record_finding_receipts":
        _record_finding_receipts(context, action)
        return
    if action.kind == "record_progress":
        _record_semantic_progress(context, action)
        return
    if action.kind == "record_plateau":
        recovered = recover_protocol_25_run(context)
        if plan_next_protocol_25(recovered.controller_state) != action:
            raise Protocol25RecoveryError(
                "plateau action differs from fresh controller authority"
            )
        target = next(
            item
            for item in recovered.controller_state.targets
            if item.audit_target_id == action.audit_target_id
        )
        context.event_store.append(
            "semantic_plateau_reached",
            {
                "audit_target_id": target.audit_target_id,
                "semantic_round": target.semantic_round,
                "unresolved_finding_ids": list(target.unresolved_finding_ids),
            },
            occurred_at=context.clock(),
        )
        return
    if action.kind == "accept_roots":
        _accept_semantic_roots(context, action)
        return
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
    if action.kind == "resolve_target":
        recovered = recover_protocol_25_run(context)
        if plan_next_protocol_25(recovered.controller_state) != action:
            raise Protocol25RecoveryError(
                "resolution action differs from fresh controller authority"
            )
        item, semantic_context = build_resolution_dispatch_authority(
            context,
            action,
        )
        dependencies = context.dependencies_for(item, "initial_generation")
        if (
            not isinstance(dependencies, ProviderExecutionDependenciesV1)
            or dependencies.context_bytes
            != canonical_json_bytes(semantic_context.to_json_dict())
            or dependencies.executor
            != context.semantic_inputs.executor_contract.entry_for(
                "semantic-resolution"
            )
        ):
            raise Protocol25RecoveryError(
                "semantic dependency resolver differs from resolution authority"
            )
        Protocol25Controller(context)._execute_one(
            item,
            _shared_action_recovery(context, recovered),
        )
        return
    if action.kind == "recheck_target":
        recovered = recover_protocol_25_run(context)
        if plan_next_protocol_25(recovered.controller_state) != action:
            raise Protocol25RecoveryError(
                "closure recheck action differs from fresh controller authority"
            )
        item, semantic_context = build_recheck_dispatch_authority(context, action)
        dependencies = context.dependencies_for(item, "initial_generation")
        if (
            not isinstance(dependencies, ProviderExecutionDependenciesV1)
            or dependencies.context_bytes
            != canonical_json_bytes(semantic_context.to_json_dict())
            or dependencies.executor
            != context.semantic_inputs.executor_contract.entry_for(
                "closure-recheck"
            )
        ):
            raise Protocol25RecoveryError(
                "semantic dependency resolver differs from closure recheck authority"
            )
        Protocol25Controller(context)._execute_one(
            item,
            _shared_action_recovery(context, recovered),
        )
        return
    if action.kind == "guard_source":
        recovered = recover_protocol_25_run(context)
        if plan_next_protocol_25(recovered.controller_state) != action:
            raise Protocol25RecoveryError(
                "source guard action differs from fresh controller authority"
            )
        item, semantic_context = build_source_guard_dispatch_authority(
            context,
            action,
        )
        dependencies = context.dependencies_for(item, "initial_generation")
        if (
            not isinstance(dependencies, ProviderExecutionDependenciesV1)
            or dependencies.context_bytes
            != canonical_json_bytes(semantic_context.to_json_dict())
            or dependencies.executor
            != context.semantic_inputs.executor_contract.entry_for(
                "source-composition-guard"
            )
        ):
            raise Protocol25RecoveryError(
                "semantic dependency resolver differs from source guard authority"
            )
        Protocol25Controller(context)._execute_one(
            item,
            _shared_action_recovery(context, recovered),
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


def _source_assessment_for_action(
    context: Protocol25RunContext,
    action: Protocol25ControllerActionV1,
    ledger: Protocol25LedgerView,
) -> object:
    from .artifacts import SourceCompositionAssessmentV1

    replay = Protocol25ReplayState()
    for event in context.event_store.replay():
        replay.consume(event)
    cycle = replay.source_cycles.get(action.source_cycle_id or "")
    if cycle is None or cycle.source_assessment_id is None:
        raise Protocol25RecoveryError("semantic cycle has no source assessment")
    assessment = ledger.source_composition_assessments.get(
        cycle.source_assessment_id
    )
    if not isinstance(assessment, SourceCompositionAssessmentV1):
        raise Protocol25RecoveryError("source assessment ledger authority is missing")
    return assessment


def _record_finding_receipts(
    context: Protocol25RunContext,
    action: Protocol25ControllerActionV1,
) -> None:
    from .artifacts import build_finding_closure_receipt

    recovered = recover_protocol_25_run(context)
    if plan_next_protocol_25(recovered.controller_state) != action:
        raise Protocol25RecoveryError(
            "finding receipt action differs from fresh controller authority"
        )
    ledger = recovered.ledger
    if len(ledger.audit_epochs) != 1 or action.semantic_round is None:
        raise Protocol25RecoveryError("finding receipts require one frozen epoch")
    epoch = next(iter(ledger.audit_epochs.values()))
    source_assessment = _source_assessment_for_action(context, action, ledger)
    for target_id in action.participating_target_ids:
        assessments = tuple(
            item
            for item in ledger.target_closure_assessments.values()
            if item.identity in source_assessment.target_assessment_hashes
            and item.audit_target_id == target_id
        )
        if len(assessments) != 1:
            raise Protocol25RecoveryError(
                "finding receipts require one target assessment per participant"
            )
        target_assessment = assessments[0]
        for verdict in target_assessment.verdicts:
            previous = ledger.latest_finding_closures.get(verdict.finding_key_id)
            receipt = build_finding_closure_receipt(
                epoch=epoch,
                target_assessment=target_assessment,
                source_assessment=source_assessment,
                schema_version=1,
                finding_key_id=verdict.finding_key_id,
                audit_target_id=target_id,
                resolution_overlay_hash=target_assessment.resolution_overlay_hash,
                closure_verifier_authority_hash=(
                    target_assessment.verifier_authority_hash
                ),
                context_authority_hash=target_assessment.context_authority_hash,
                semantic_round=action.semantic_round,
                verdict=verdict.verdict,
                reason_code=verdict.reason_code,
                diagnostic=f"Target recheck verdict: {verdict.reason_code}.",
                previous_closure_receipt_id=(
                    None if previous is None else previous.identity
                ),
            )
            context.object_store.put_blob(canonical_json_bytes(receipt.to_json_dict()))
            context.ledger.record_finding_closure(receipt)
            context.event_store.append(
                "finding_closure_recorded",
                {
                    "audit_target_id": target_id,
                    "finding_closure_receipt_id": receipt.identity,
                    "finding_key_id": verdict.finding_key_id,
                    "semantic_round": action.semantic_round,
                    "source_composition_assessment_id": source_assessment.identity,
                    "source_cycle_id": action.source_cycle_id,
                    "verdict": verdict.verdict,
                },
                occurred_at=context.clock(),
            )


def _record_semantic_progress(
    context: Protocol25RunContext,
    action: Protocol25ControllerActionV1,
) -> None:
    recovered = recover_protocol_25_run(context)
    if plan_next_protocol_25(recovered.controller_state) != action:
        raise Protocol25RecoveryError(
            "semantic progress action differs from fresh controller authority"
        )
    ledger = recovered.ledger
    source_assessment = _source_assessment_for_action(context, action, ledger)
    for target_id in action.participating_target_ids:
        assessment = next(
            item
            for item in ledger.target_closure_assessments.values()
            if item.identity in source_assessment.target_assessment_hashes
            and item.audit_target_id == target_id
        )
        before = assessment.assessed_finding_ids
        if source_assessment.outcome == "passed":
            after = tuple(
                item.finding_key_id
                for item in assessment.verdicts
                if item.verdict == "open"
            )
        else:
            after = before
        context.event_store.append(
            "semantic_progress_recorded",
            {
                "audit_target_id": target_id,
                "semantic_round": action.semantic_round,
                "source_cycle_id": action.source_cycle_id,
                "unresolved_after_ids": list(after),
                "unresolved_before_ids": list(before),
            },
            occurred_at=context.clock(),
        )


def _accept_semantic_roots(
    context: Protocol25RunContext,
    action: Protocol25ControllerActionV1,
) -> None:
    recovered = recover_protocol_25_run(context)
    if plan_next_protocol_25(recovered.controller_state) != action or action.source_id is None:
        raise Protocol25RecoveryError(
            "root acceptance action differs from fresh controller authority"
        )
    ledger = recovered.ledger
    if len(ledger.audit_epochs) != 1:
        raise Protocol25RecoveryError("semantic roots require one frozen epoch")
    epoch = next(iter(ledger.audit_epochs.values()))
    replay = Protocol25ReplayState()
    for event in recovered.events:
        replay.consume(event)
    deferred = {
        item.observation_id: item
        for assessment in (
            *ledger.target_closure_assessments.values(),
            *ledger.source_composition_assessments.values(),
        )
        for item in assessment.deferred_observations
    }
    closure_root = context.semantic_runtime.build_closure_root(
        epoch,
        latest_receipts=tuple(ledger.latest_finding_closures.values()),
        target_rounds=tuple(
            sorted(
                (target.audit_target_id, target.semantic_round)
                for target in recovered.controller_state.targets
            )
        ),
        plateau_counts=tuple(
            sorted(
                (target.audit_target_id, target.no_reduction_rounds)
                for target in recovered.controller_state.targets
            )
        ),
        deferred_observations=tuple(deferred[key] for key in sorted(deferred)),
    )
    if not ledger.audit_closure_roots:
        context.object_store.put_blob(
            canonical_json_bytes(closure_root.to_json_dict())
        )
        context.ledger.record_audit_closure_root(closure_root)
        context.event_store.append(
            "audit_closure_root_accepted",
            {
                "audit_closure_root_id": closure_root.identity,
                "audit_epoch_id": epoch.identity,
                "deferred_observation_ids": list(
                    item.observation_id for item in closure_root.deferred_observations
                ),
                "unresolved_finding_ids": list(
                    closure_root.unresolved_finding_ids
                ),
            },
            occurred_at=context.clock(),
        )
    elif ledger.audit_closure_roots != {closure_root.identity: closure_root}:
        raise Protocol25RecoveryError("existing audit closure root conflicts")

    source_plans = tuple(
        item
        for item in context.semantic_graph.audit_target_plans
        if item.scope.source_id == action.source_id
    )
    source_plan = next(
        (item for item in source_plans if item.target_kind == "source"),
        None,
    )
    if source_plan is None:
        raise Protocol25RecoveryError("L3 root has no source audit plan")
    source_targets_list = []
    for authority in epoch.target_candidate_authorities:
        candidate = load_canonical_object(
            context.object_store.read_blob(authority.candidate_hash),
            AuditCandidateV1.from_json_dict,
        )
        if candidate.audit_target.scope.source_id == action.source_id:
            source_targets_list.append(candidate.audit_target)
    source_targets = tuple(source_targets_list)
    if not source_targets:
        raise Protocol25RecoveryError("L3 root has no frozen source targets")
    root_hashes = _accepted_l2_root_hash_by_source(context, ledger)
    source_root = context.semantic_runtime.build_source_root(
        source_id=action.source_id,
        selected_domain_keys=tuple(
            sorted(
                item.scope.domain_key
                for item in source_targets
                if item.scope.domain_key is not None
            )
        ),
        full_source_coverage=not source_plan.not_requested_domain_keys,
        audit_target_ids=tuple(sorted(item.identity for item in source_targets)),
        closure_roots=(closure_root,),
        adopted_l2_root_hash=root_hashes[action.source_id],
    )
    context.object_store.put_blob(canonical_json_bytes(source_root.to_json_dict()))
    context.ledger.record_l3_source_root(source_root)
    context.event_store.append(
        "l3_source_root_accepted",
        {
            "l3_source_root_id": source_root.identity,
            "scope_state": source_root.state,
            "source_id": action.source_id,
        },
        occurred_at=context.clock(),
    )


__all__ = (
    "Protocol25RecoveryError",
    "Protocol25RecoveryResult",
    "Protocol25RunContext",
    "publish_audit_epoch",
    "reconstruct_accepted_audit_results",
    "recover_protocol_25_run",
)
