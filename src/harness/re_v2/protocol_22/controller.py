"""Single-dispatch orchestration for closed RE v2 protocol 2.2 runs."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import stat
import time
from typing import Callable, Literal, Mapping, Protocol

from harness.re_v2.candidates import ProcessIdentity
from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.events import EventRecord
from harness.re_v2.recovery import ProcessInspector
from harness.re_v2.run_store import load_run_manifest

from .artifacts import AcceptedDependencySetV2, ContextBundleV1
from .baseline import (
    ArtifactAcceptanceReceiptV2,
    CandidateAssessmentReceiptV1,
    CertificationReceiptV2,
    CompactCandidateError,
    CompactCandidateInputV1,
    CompactCertificationResultV2,
    parse_authorial_candidate,
)
from .budget import BudgetDecisionV2
from .execution import (
    Committed,
    DeterministicExecutionDependenciesV1,
    DeterministicRawResultV1,
    PreparedExecutionV1,
    Protocol22ExecutionError,
    ProviderExecutionDependenciesV1,
)
from .graph import (
    AcceptedArtifactV2,
    PlanDecisionV2,
    instantiate_ready_item,
    plan_next_v22,
)
from .ledger import (
    ExecutorFailureReceiptV1,
    Protocol22LedgerView,
    WorkItemFailureReceiptV1,
)
from .model import WorkItemV2
from .policies import policy_for
from .provider import (
    Protocol22ProviderError,
    RawExecutionResultV1,
    normalize_captured_provider_usage,
)
from .recovery import (
    PinnedAuthorityUnavailable,
    Protocol22RecoveryResult,
    Protocol22RunContext,
    candidate_reconstructs_result_contract,
    protocol_22_run_lock,
    recover_protocol_22_run,
    recover_protocol_22_run_locked,
    resolve_execution_dependencies,
)
from .schema import Protocol22SchemaError, load_canonical_object


ControllerStatus = Literal[
    "completed",
    "failed",
    "paused",
    "pinned_authority_unavailable",
    "dispatch_owner_live",
    "dispatch_owner_ambiguous",
]


@dataclass(frozen=True, slots=True)
class Protocol22ControllerResult:
    """Fresh replay authority at the point the controller stops."""

    status: ControllerStatus
    reason_code: str
    events: tuple[EventRecord, ...]
    ledger: Protocol22LedgerView | None
    plan: PlanDecisionV2 | None
    unavailable: PinnedAuthorityUnavailable | None = None


class Protocol22ControllerError(RuntimeError):
    """Raised when live execution cannot satisfy the pinned 2.2 contract."""


class _DeterministicProducer(Protocol):
    def produce(
        self,
        item: WorkItemV2,
        dependencies: AcceptedDependencySetV2,
    ) -> bytes: ...


class _DeterministicVerifier(Protocol):
    def certify_deterministic(
        self,
        item: WorkItemV2,
        payload: bytes,
        dependencies: AcceptedDependencySetV2,
    ) -> CertificationReceiptV2: ...


class Protocol22Controller:
    """Execute one protocol-2.2 graph serially until a durable stop state."""

    def __init__(
        self,
        context: Protocol22RunContext,
        fault_hook: Callable[[str], None] | None = None,
    ) -> None:
        if not isinstance(context, Protocol22RunContext):
            raise TypeError("Protocol22Controller requires Protocol22RunContext")
        if fault_hook is not None and not callable(fault_hook):
            raise TypeError("Protocol22Controller fault_hook must be callable or null")
        self.context = context
        self.fault_hook = fault_hook

    def run_until_stopped(self) -> Protocol22ControllerResult:
        # Preserve recovery's non-mutating pinned-authority return before the
        # run lock itself is allowed to create a lock file.
        initial = recover_protocol_22_run(self.context, self.fault_hook)
        if initial.operational_state in {"paused", "terminal"}:
            self._materialize_accepted_l1()
        stopped = _stopped_recovery(initial)
        if stopped is not None:
            return stopped

        with protocol_22_run_lock(self.context.paths):
            recovery = recover_protocol_22_run_locked(
                self.context,
                self.fault_hook,
            )
            maximum_steps = len(self.context.graph.templates) * 3 + 4
            for _step in range(maximum_steps):
                self._materialize_accepted_l1()
                stopped = _stopped_recovery(recovery)
                if stopped is not None:
                    return stopped
                if recovery.ledger is None or recovery.budget is None:
                    raise Protocol22ControllerError(
                        "ready recovery omitted ledger or budget authority"
                    )
                if self._resume_durable_dispatch(recovery):
                    recovery = recover_protocol_22_run_locked(
                        self.context,
                        self.fault_hook,
                    )
                    continue
                if self._record_exhausted_abandonment(recovery):
                    recovery = recover_protocol_22_run_locked(
                        self.context,
                        self.fault_hook,
                    )
                    continue
                decision = plan_next_v22(
                    recovery.graph,
                    recovery.ledger,
                    recovery.budget,
                )
                if decision.ready:
                    item = decision.ready[0]
                    self._execute_one(item, recovery)
                    recovery = recover_protocol_22_run_locked(
                        self.context,
                        self.fault_hook,
                    )
                    continue
                terminal = _terminal_event_for_fixed_point(decision)
                self.context.event_store.append(
                    terminal,
                    {
                        "reason": (
                            "all requested protocol-2.2 artifacts are accepted"
                            if terminal == "run_completed"
                            else "required protocol-2.2 work reached a terminal failure fixed point"
                        )
                    },
                    occurred_at=self.context.clock(),
                )
                recovery = recover_protocol_22_run_locked(
                    self.context,
                    self.fault_hook,
                )
            raise Protocol22ControllerError(
                "protocol-2.2 controller exceeded its closed dispatch bound"
            )

    def _materialize_accepted_l1(self) -> None:
        from .materialization import validate_or_repair_materialization

        validate_or_repair_materialization(self.context, self.fault_hook)

    def _resume_durable_dispatch(
        self,
        recovery: Protocol22RecoveryResult,
    ) -> bool:
        """Finish post-execution work solely from committed run authority."""
        if recovery.ledger is None or recovery.budget is None:
            return False
        ledger = recovery.ledger
        latest_by_work: dict[str, EventRecord] = {}
        for event in recovery.events:
            if event.type == "dispatch_started":
                latest_by_work[str(event.payload["work_item_id"])] = event
        for started in sorted(latest_by_work.values(), key=lambda event: event.seq):
            work_item_id = str(started.payload["work_item_id"])
            item = _reconstruct_work_item(self.context, ledger, work_item_id)
            if item is None:
                raise Protocol22ControllerError(
                    "durable dispatch cannot be reconstructed from graph authority"
                )
            if (
                ledger.artifact_for_key(item.output_key.identity) is not None
                or ledger.work_failure(item.work_item_id) is not None
                or ledger.executor_failure(item.executor_contract_hash) is not None
            ):
                continue
            dispatch_id = str(started.payload["dispatch_id"])
            observation = next(
                (
                    event
                    for event in recovery.events
                    if event.type == "dispatch_observed"
                    and event.payload["dispatch_id"] == dispatch_id
                ),
                None,
            )
            if observation is None:
                continue
            state = self.context.execution_store.capture_state(dispatch_id)
            if not isinstance(state, Committed):
                raise Protocol22ControllerError(
                    "observed durable dispatch has no committed capture"
                )
            attempt_kind = str(started.payload["attempt_kind"])
            dependencies = resolve_execution_dependencies(
                self.context,
                item,
                attempt_kind,
            )
            if isinstance(dependencies, DeterministicExecutionDependenciesV1):
                self._resume_deterministic_dispatch(item, state, ledger)
                return True
            if not isinstance(dependencies, ProviderExecutionDependenciesV1):
                raise Protocol22ControllerError(
                    "durable dispatch has no closed execution branch"
                )
            return self._resume_provider_dispatch(
                item,
                state,
                dependencies,
                observation,
                ledger,
                recovery.budget,
                attempt_kind,
            )
        return False

    def _resume_deterministic_dispatch(
        self,
        item: WorkItemV2,
        committed: Committed,
        ledger: Protocol22LedgerView,
    ) -> None:
        certifications = [
            receipt
            for receipt_id, receipt in ledger.certifications.items()
            if ledger.certification_work_items[receipt_id].work_item_id
            == item.work_item_id
        ]
        if len(certifications) > 1:
            raise Protocol22ControllerError(
                "deterministic dispatch has multiple certification receipts"
            )
        if certifications:
            certification = certifications[0]
            if certification.verdict == "accepted":
                self._accept_artifact(item, certification, None)
            else:
                self._record_executor_failure(
                    item,
                    committed,
                    "deterministic_artifact_invalid",
                    tuple(certification.assessment.normalized_diagnostics),
                )
            return
        self._certify_deterministic_capture(item, committed)

    def _resume_provider_dispatch(
        self,
        item: WorkItemV2,
        committed: Committed,
        dependencies: ProviderExecutionDependenciesV1,
        observation: EventRecord,
        ledger: Protocol22LedgerView,
        budget: BudgetDecisionV2,
        attempt_kind: str,
    ) -> bool:
        candidate_event = next(
            (
                event
                for event in self.context.event_store.replay()
                if event.type == "candidate_persisted"
                and event.payload["dispatch_id"] == committed.dispatch_id
            ),
            None,
        )
        if candidate_event is None:
            raise Protocol22ControllerError(
                "provider dispatch has no durable candidate event"
            )
        candidate_id = str(candidate_event.payload["candidate_id"])
        assessments = [
            assessment
            for assessment in ledger.candidate_assessments.values()
            if assessment.candidate_id == candidate_id
        ]
        if len(assessments) > 1:
            raise Protocol22ControllerError(
                "provider candidate has multiple assessment receipts"
            )
        if assessments:
            assessment = assessments[0]
            if assessment.outcome == "certified":
                if assessment.certification_receipt_id is None:
                    raise Protocol22ControllerError(
                        "certified candidate has no certification receipt"
                    )
                certification = ledger.certifications[
                    assessment.certification_receipt_id
                ]
                self._accept_artifact(item, certification, assessment.identity)
                return True
            if budget.item_attempt_available(item):
                return False
            failure_class, reason_code = _artifact_failure(
                tuple(assessment.normalized_diagnostics)
            )
            self._retry_or_fail_work_item(
                item,
                committed,
                candidate_id=candidate_id,
                candidate_assessment_id=assessment.identity,
                failure_class=failure_class,
                reason_code=reason_code,
                diagnostics=tuple(assessment.normalized_diagnostics),
            )
            return True

        prepared = self.context.execution_store.prepare_execution(
            item,
            attempt_kind,
            dependencies,
        )
        self.context.execution_store.validate_prepared_execution(
            prepared,
            item,
            dependencies,
        )
        if _usage_exceeds_reservation(observation.payload, prepared):
            self._record_provider_executor_failure(
                item,
                committed,
                candidate_id,
                "usage_exceeded_reservation",
            )
            return True
        raw_status = observation.payload["raw_result_contract_status"]
        if raw_status == "invalid" and not candidate_reconstructs_result_contract(
            item,
            committed.closure,
            self.context.object_store,
            self.context.inputs,
        ):
            if budget.item_attempt_available(item):
                return False
            self._retry_or_fail_work_item(
                item,
                committed,
                candidate_id=candidate_id,
                candidate_assessment_id=None,
                failure_class="result_contract",
                reason_code="result_unrecoverable",
                diagnostics=("result_unrecoverable",),
            )
            return True
        self._certify_provider_candidate(item, committed, candidate_id)
        return True

    def _execute_one(
        self,
        item: WorkItemV2,
        recovery: Protocol22RecoveryResult,
    ) -> None:
        assert recovery.budget is not None
        attempt_kind = _attempt_kind(item, recovery.budget)
        try:
            dependencies = resolve_execution_dependencies(
                self.context,
                item,
                attempt_kind,
            )
            if dependencies.registry != self.context.installed_authorities:
                raise Protocol22ControllerError(
                    "execution dependencies changed installed authority"
                )
            prepared = self.context.execution_store.prepare_execution(
                item,
                attempt_kind,
                dependencies,
                self.fault_hook,
            )
            self.context.execution_store.validate_prepared_execution(
                prepared,
                item,
                dependencies,
            )
        except (Protocol22ExecutionError, Protocol22ProviderError) as exc:
            if "reservation" not in str(exc):
                raise
            self._record_pre_dispatch_executor_failure(
                item,
                "reservation_mismatch",
            )
            return
        if not _prepared_fits_budget(prepared, recovery.budget):
            self.context.event_store.append(
                "run_paused",
                {
                    "reason": (
                        "next dispatch exceeds remaining token or active-time "
                        "authorization"
                    ),
                    "reason_code": "budget_authorization_required",
                },
                occurred_at=self.context.clock(),
            )
            return
        candidate_root = (
            _candidate_root(self.context, prepared.dispatch_id)
            if isinstance(dependencies, ProviderExecutionDependenciesV1)
            else None
        )
        process = _current_process_identity(item, attempt_kind, self.context.clock())
        self.context.execution_store.record_started_lease(
            prepared,
            item,
            dependencies,
            process,
            self.fault_hook,
        )
        self.context.event_store.append(
            "dispatch_leased",
            {"dispatch_id": prepared.dispatch_id, "work_item_id": item.work_item_id},
            occurred_at=self.context.clock(),
        )
        attempt_index = 1 + sum(
            1
            for event in recovery.events
            if event.type == "dispatch_started"
            and event.payload["work_item_id"] == item.work_item_id
            and event.payload["attempt_kind"] == attempt_kind
        )
        self.context.event_store.append(
            "dispatch_started",
            {
                "active_ms_reservation": prepared.reservation.active_ms,
                "attempt_index": attempt_index,
                "attempt_kind": attempt_kind,
                "billable_token_reservation": prepared.reservation.billable_tokens,
                "dispatch_id": prepared.dispatch_id,
                "execution_input_hash": prepared.execution_input_hash,
                "executor_contract_hash": item.executor_contract_hash,
                "work_item_id": item.work_item_id,
            },
            occurred_at=self.context.clock(),
        )
        _fault(self.fault_hook, f"dispatch_started:{prepared.dispatch_id}")
        if isinstance(dependencies, DeterministicExecutionDependenciesV1):
            self._execute_deterministic(item, prepared, dependencies)
            return
        if isinstance(dependencies, ProviderExecutionDependenciesV1):
            assert candidate_root is not None
            self._execute_provider(item, prepared, dependencies, candidate_root)
            return
        raise Protocol22ControllerError(
            "dependency resolver selected no execution branch"
        )

    def _execute_deterministic(
        self,
        item: WorkItemV2,
        prepared: PreparedExecutionV1,
        dependencies: DeterministicExecutionDependenciesV1,
    ) -> None:
        accepted = accepted_dependencies_for(self.context, item)
        producer = _runtime_for(
            self.context.producers,
            item.producer_family,
            "deterministic producer",
        )
        produce = getattr(producer, "produce", None)
        started_at = self.context.clock()
        started_ns = time.monotonic_ns()
        try:
            if not callable(produce):
                raise Protocol22ControllerError(
                    f"producer {item.producer_family} has no produce method"
                )
            payload = produce(item, accepted)
            if not isinstance(payload, bytes):
                raise Protocol22ControllerError(
                    "deterministic producer returned non-bytes"
                )
            stderr = b""
            exit_code = 0
        except Exception as exc:
            payload = None
            stderr = _diagnostic_bytes(exc)
            exit_code = 1
        ended_ns = time.monotonic_ns()
        ended_at = self.context.clock()
        duration_ms = max(0, (ended_ns - started_ns) // 1_000_000)
        raw = DeterministicRawResultV1(
            artifact_bytes=payload,
            stdout=b"",
            stderr=stderr,
            started_at=started_at,
            ended_at=ended_at,
            duration_ms=duration_ms,
            exit_code=exit_code,
            timed_out=False,
        )
        captured = self.context.execution_store.capture_deterministic_result(
            prepared,
            raw,
            self.fault_hook,
        )
        committed = self.context.execution_store.commit_capture(
            captured,
            self.fault_hook,
        )
        self._append_deterministic_observation(committed)
        self._certify_deterministic_capture(item, committed)

    def _certify_deterministic_capture(
        self,
        item: WorkItemV2,
        committed: Committed,
    ) -> None:
        payload = committed.closure.deterministic_artifact_bytes
        if payload is None:
            self._record_executor_failure(
                item,
                committed,
                "deterministic_execution_failed",
                ("deterministic_execution_failed",),
            )
            return
        accepted = accepted_dependencies_for(self.context, item)
        verifier = _runtime_for(
            self.context.verifiers,
            item.verifier_id,
            "deterministic verifier",
        )
        certify = getattr(verifier, "certify_deterministic", None)
        if not callable(certify):
            raise Protocol22ControllerError(
                f"verifier {item.verifier_id} has no certify_deterministic method"
            )
        try:
            certification = certify(item, payload, accepted)
        except Exception:
            self._record_executor_failure(
                item,
                committed,
                "deterministic_artifact_invalid",
                ("deterministic_artifact_invalid",),
            )
            return
        if not isinstance(certification, CertificationReceiptV2):
            raise Protocol22ControllerError(
                "deterministic verifier returned no CertificationReceiptV2"
            )
        self.context.ledger.record_certification(certification, item)
        _fault(self.fault_hook, f"certification_receipt:{certification.identity}")
        if certification.verdict != "accepted":
            self._record_executor_failure(
                item,
                committed,
                "deterministic_artifact_invalid",
                tuple(certification.assessment.normalized_diagnostics),
            )
            return
        self._accept_artifact(item, certification, None)

    def _execute_provider(
        self,
        item: WorkItemV2,
        prepared: PreparedExecutionV1,
        dependencies: ProviderExecutionDependenciesV1,
        candidate_root: Path,
    ) -> None:
        executor = _runtime_for(
            self.context.executors,
            dependencies.executor.adapter_id,
            "provider executor",
        )
        execute = getattr(executor, "execute", None)
        if not callable(execute):
            raise Protocol22ControllerError(
                f"provider executor {dependencies.executor.adapter_id} has no execute method"
            )
        deadline = time.monotonic() + prepared.reservation.active_ms / 1000
        if dependencies.executor.execution_mode == "api":
            if prepared.provider_envelope is None:
                raise Protocol22ControllerError(
                    "API provider execution has no request envelope"
                )
            result = execute(
                prepared.execution_input,
                prepared.provider_envelope,
                prepared.reservation,
                candidate_root,
                deadline,
            )
        elif dependencies.executor.execution_mode == "cli":
            result = execute(
                prepared.execution_input,
                dependencies.agent_bytes,
                dependencies.context_bytes,
                dependencies.response_schema_bytes,
                prepared.reservation,
                candidate_root,
                deadline,
                retry_diagnostics=dependencies.retry_diagnostics,
            )
        else:
            raise Protocol22ControllerError(
                "provider dependencies have no provider-backed execution mode"
            )
        if not isinstance(result, RawExecutionResultV1):
            raise Protocol22ControllerError(
                "provider executor returned no RawExecutionResultV1"
            )
        captured = self.context.execution_store.capture_provider_result(
            prepared,
            candidate_root,
            result,
            self.fault_hook,
        )
        committed = self.context.execution_store.commit_capture(
            captured,
            self.fault_hook,
        )
        observation = self._append_provider_observation(committed, dependencies)
        candidate = self.context.execution_store.persist_candidate(
            committed,
            self.fault_hook,
        )
        self.context.event_store.append(
            "candidate_persisted",
            {
                "candidate_id": candidate.candidate_id,
                "candidate_inventory_hash": candidate.candidate_inventory_hash,
                "dispatch_id": candidate.dispatch_id,
                "execution_capture_hash": candidate.execution_capture_hash,
                "work_item_id": candidate.work_item_id,
            },
            occurred_at=self.context.clock(),
        )
        _fault(self.fault_hook, f"candidate_persisted:{candidate.candidate_id}")
        if _usage_exceeds_reservation(observation, prepared):
            self._record_provider_executor_failure(
                item,
                committed,
                candidate.candidate_id,
                "usage_exceeded_reservation",
            )
            return

        raw_status = observation["raw_result_contract_status"]
        if raw_status == "invalid":
            reconstructable = candidate_reconstructs_result_contract(
                item,
                committed.closure,
                self.context.object_store,
                self.context.inputs,
            )
            if reconstructable:
                self.context.event_store.append(
                    "result_contract_reconstructed",
                    {
                        "candidate_id": candidate.candidate_id,
                        "dispatch_id": candidate.dispatch_id,
                        "result_contract_id": item.result_contract_id,
                        "work_item_id": item.work_item_id,
                    },
                    occurred_at=self.context.clock(),
                )
                _fault(
                    self.fault_hook,
                    f"result_contract_reconstructed:{candidate.candidate_id}",
                )
            else:
                self._retry_or_fail_work_item(
                    item,
                    committed,
                    candidate_id=candidate.candidate_id,
                    candidate_assessment_id=None,
                    failure_class="result_contract",
                    reason_code="result_unrecoverable",
                    diagnostics=("result_unrecoverable",),
                )
                return
        self._certify_provider_candidate(item, committed, candidate.candidate_id)

    def _append_provider_observation(
        self,
        committed: Committed,
        dependencies: ProviderExecutionDependenciesV1,
    ) -> dict[str, object]:
        closure = committed.closure
        capture = closure.capture
        normalized = normalize_captured_provider_usage(
            capture.execution_mode,
            closure.provider_usage_bytes,
            dependencies.executor.token_accounting,
        )
        payload: dict[str, object] = {
            "active_usage_status": "trusted_exact",
            "dispatch_id": capture.dispatch_id,
            "execution_capture_hash": capture.identity,
            "observed_active_ms": capture.duration_ms,
            "raw_result_contract_status": (
                "valid" if closure.stdout_bytes == _RESULT_STDOUT else "invalid"
            ),
            "reported_token_usage": normalized.billable_tokens,
            "token_usage_status": normalized.status,
            "work_item_id": capture.work_item_id,
        }
        self.context.event_store.append(
            "dispatch_observed",
            payload,
            occurred_at=self.context.clock(),
        )
        _fault(self.fault_hook, f"dispatch_observed:{capture.dispatch_id}")
        return payload

    def _certify_provider_candidate(
        self,
        item: WorkItemV2,
        committed: Committed,
        candidate_id: str,
    ) -> None:
        inventory = committed.closure.candidate_inventory
        entry = (
            inventory.entries[0]
            if inventory is not None and len(inventory.entries) == 1
            else None
        )
        if (
            entry is None
            or entry.relative_path != "baseline.json"
            or entry.object_kind != "regular"
            or entry.content_hash is None
        ):
            self._reject_candidate_before_artifact(
                item,
                committed,
                candidate_id,
                "candidate_tree_invalid",
            )
            return
        raw = self.context.object_store.read_blob(entry.content_hash)
        try:
            policy = policy_for(
                self.context.inputs.artifact_policy,
                item.output_key.layer,
                item.output_key.artifact_kind,
            )
            authorial = parse_authorial_candidate(
                raw,
                item.output_key.artifact_kind,
                policy,
            )
        except (CompactCandidateError, Protocol22SchemaError):
            self._reject_candidate_before_artifact(
                item,
                committed,
                candidate_id,
                "authorial_schema_invalid",
            )
            return
        normalized_bytes = canonical_json_bytes(authorial.to_json_dict())
        normalized_hash = self.context.object_store.put_blob(normalized_bytes)
        candidate_input = CompactCandidateInputV1(
            candidate_id=candidate_id,
            execution_capture_hash=committed.closure.capture.identity,
            authorial_payload=authorial,
        )
        verifier = _runtime_for(
            self.context.verifiers,
            item.verifier_id,
            "compact verifier",
        )
        certify = getattr(verifier, "certify_candidate", None)
        if not callable(certify):
            raise Protocol22ControllerError(
                f"verifier {item.verifier_id} has no certify_candidate method"
            )
        context_hash = committed.closure.execution_input.context_bundle_hash
        if context_hash is None:
            raise Protocol22ControllerError(
                "provider candidate has no pinned context bundle"
            )
        context = load_canonical_object(
            self.context.object_store.read_blob(context_hash),
            ContextBundleV1.from_json_dict,
        )
        result = certify(candidate_input, item, context)
        if not isinstance(result, CompactCertificationResultV2):
            raise Protocol22ControllerError(
                "compact verifier returned no CompactCertificationResultV2"
            )
        if (
            result.candidate_assessment.normalized_authorial_payload_hash
            != normalized_hash
        ):
            raise Protocol22ControllerError(
                "candidate assessment normalized payload authority mismatch"
            )
        artifact_hash = self.context.object_store.put_blob(result.artifact_bytes)
        if artifact_hash != result.certification.certification_key.artifact_hash:
            raise Protocol22ControllerError(
                "compact certification artifact hash mismatch"
            )
        self.context.ledger.record_certification(result.certification, item)
        _fault(
            self.fault_hook,
            f"certification_receipt:{result.certification.identity}",
        )
        self.context.ledger.record_candidate_assessment(result.candidate_assessment)
        _fault(
            self.fault_hook,
            f"candidate_assessment:{result.candidate_assessment.identity}",
        )
        event_type = (
            "candidate_certified"
            if result.candidate_assessment.outcome == "certified"
            else "candidate_rejected"
        )
        self.context.event_store.append(
            event_type,
            {
                "candidate_assessment_id": result.candidate_assessment.identity,
                "candidate_id": candidate_id,
                "certification_receipt_id": result.certification.identity,
                "work_item_id": item.work_item_id,
            },
            occurred_at=self.context.clock(),
        )
        _fault(
            self.fault_hook,
            f"{event_type}:{result.candidate_assessment.identity}",
        )
        if result.certification.verdict == "accepted":
            self._accept_artifact(
                item,
                result.certification,
                result.candidate_assessment.identity,
            )
            return
        diagnostics = tuple(result.candidate_assessment.normalized_diagnostics)
        failure_class, reason_code = _artifact_failure(diagnostics)
        self._retry_or_fail_work_item(
            item,
            committed,
            candidate_id=candidate_id,
            candidate_assessment_id=result.candidate_assessment.identity,
            failure_class=failure_class,
            reason_code=reason_code,
            diagnostics=diagnostics,
        )

    def _reject_candidate_before_artifact(
        self,
        item: WorkItemV2,
        committed: Committed,
        candidate_id: str,
        reason_code: Literal["candidate_tree_invalid", "authorial_schema_invalid"],
    ) -> None:
        assessment = CandidateAssessmentReceiptV1(
            schema_version=1,
            candidate_id=candidate_id,
            work_item_id=item.work_item_id,
            execution_capture_hash=committed.closure.capture.identity,
            normalized_authorial_payload_hash=None,
            artifact_hash=None,
            certification_receipt_id=None,
            outcome="rejected_before_artifact",
            normalized_diagnostics=(reason_code,),
        )
        self.context.ledger.record_candidate_assessment(assessment)
        _fault(self.fault_hook, f"candidate_assessment:{assessment.identity}")
        self.context.event_store.append(
            "candidate_rejected",
            {
                "candidate_assessment_id": assessment.identity,
                "candidate_id": candidate_id,
                "certification_receipt_id": None,
                "work_item_id": item.work_item_id,
            },
            occurred_at=self.context.clock(),
        )
        _fault(self.fault_hook, f"candidate_rejected:{assessment.identity}")
        self._retry_or_fail_work_item(
            item,
            committed,
            candidate_id=candidate_id,
            candidate_assessment_id=assessment.identity,
            failure_class="artifact_contract",
            reason_code=reason_code,
            diagnostics=(reason_code,),
        )

    def _retry_or_fail_work_item(
        self,
        item: WorkItemV2,
        committed: Committed,
        *,
        candidate_id: str | None,
        candidate_assessment_id: str | None,
        failure_class: Literal[
            "result_contract", "artifact_contract", "minimum_utility"
        ],
        reason_code: str,
        diagnostics: tuple[str, ...],
    ) -> None:
        events = self.context.event_store.replay()
        from .budget import evaluate_budget_v22

        manifest = load_run_manifest(self.context.paths.root.parent)
        budget = evaluate_budget_v22(
            manifest.initial_budget_policy,
            events,
            (),
            self.context.clock(),
        )
        if budget.item_attempt_available(item):
            return
        receipt = WorkItemFailureReceiptV1(
            schema_version=1,
            work_item_id=item.work_item_id,
            dispatch_id=committed.dispatch_id,
            candidate_id=candidate_id,
            candidate_assessment_id=candidate_assessment_id,
            execution_capture_hash=committed.closure.capture.identity,
            dispatch_abandonment_event_hash=None,
            failure_class=failure_class,
            reason_code=reason_code,
            normalized_diagnostics=diagnostics,
        )
        self.context.ledger.record_work_item_failure(receipt)
        _fault(self.fault_hook, f"work_item_failure_receipt:{receipt.identity}")
        self.context.event_store.append(
            "work_item_failed",
            {
                "failure_class": receipt.failure_class,
                "failure_receipt_id": receipt.identity,
                "reason_code": receipt.reason_code,
                "work_item_id": receipt.work_item_id,
            },
            occurred_at=self.context.clock(),
        )
        _fault(self.fault_hook, f"work_item_failed:{receipt.identity}")

    def _record_provider_executor_failure(
        self,
        item: WorkItemV2,
        committed: Committed,
        candidate_id: str,
        reason_code: Literal["usage_exceeded_reservation"],
    ) -> None:
        receipt = ExecutorFailureReceiptV1(
            schema_version=1,
            executor_contract_hash=item.executor_contract_hash,
            trigger_work_item_id=item.work_item_id,
            dispatch_id=committed.dispatch_id,
            candidate_id=candidate_id,
            execution_capture_hash=committed.closure.capture.identity,
            reason_code=reason_code,
            normalized_diagnostics=(reason_code,),
        )
        self.context.ledger.record_executor_failure(receipt)
        _fault(self.fault_hook, f"executor_failure_receipt:{receipt.identity}")
        self.context.event_store.append(
            "executor_failed",
            {
                "executor_contract_hash": receipt.executor_contract_hash,
                "executor_failure_receipt_id": receipt.identity,
                "trigger_work_item_id": receipt.trigger_work_item_id,
            },
            occurred_at=self.context.clock(),
        )
        _fault(self.fault_hook, f"executor_failed:{receipt.identity}")

    def _record_pre_dispatch_executor_failure(
        self,
        item: WorkItemV2,
        reason_code: Literal["reservation_mismatch", "limit_unenforceable"],
    ) -> None:
        receipt = ExecutorFailureReceiptV1(
            schema_version=1,
            executor_contract_hash=item.executor_contract_hash,
            trigger_work_item_id=item.work_item_id,
            dispatch_id=None,
            candidate_id=None,
            execution_capture_hash=None,
            reason_code=reason_code,
            normalized_diagnostics=(reason_code,),
        )
        self.context.ledger.record_executor_failure(receipt)
        _fault(self.fault_hook, f"executor_failure_receipt:{receipt.identity}")
        self.context.event_store.append(
            "executor_failed",
            {
                "executor_contract_hash": receipt.executor_contract_hash,
                "executor_failure_receipt_id": receipt.identity,
                "trigger_work_item_id": receipt.trigger_work_item_id,
            },
            occurred_at=self.context.clock(),
        )
        _fault(self.fault_hook, f"executor_failed:{receipt.identity}")

    def _record_exhausted_abandonment(
        self,
        recovery: Protocol22RecoveryResult,
    ) -> bool:
        assert recovery.ledger is not None
        assert recovery.budget is not None
        for event in recovery.events:
            if event.type != "dispatch_abandoned":
                continue
            work_item_id = str(event.payload["work_item_id"])
            if recovery.ledger.work_failure(work_item_id) is not None:
                continue
            if any(
                recovery.ledger.certification_work_items[
                    receipt.certification_receipt_id
                ].work_item_id
                == work_item_id
                for receipt in recovery.ledger.accepted_artifacts.values()
            ):
                continue
            item = _reconstruct_work_item(
                self.context,
                recovery.ledger,
                work_item_id,
            )
            if item is None or recovery.budget.item_attempt_available(item):
                continue
            receipt = WorkItemFailureReceiptV1(
                schema_version=1,
                work_item_id=item.work_item_id,
                dispatch_id=str(event.payload["dispatch_id"]),
                candidate_id=None,
                candidate_assessment_id=None,
                execution_capture_hash=None,
                dispatch_abandonment_event_hash=event.event_hash,
                failure_class="execution_indeterminate",
                reason_code="execution_outcome_indeterminate",
                normalized_diagnostics=("execution_outcome_indeterminate",),
            )
            self.context.ledger.record_work_item_failure(receipt)
            _fault(
                self.fault_hook,
                f"work_item_failure_receipt:{receipt.identity}",
            )
            self.context.event_store.append(
                "work_item_failed",
                {
                    "failure_class": receipt.failure_class,
                    "failure_receipt_id": receipt.identity,
                    "reason_code": receipt.reason_code,
                    "work_item_id": receipt.work_item_id,
                },
                occurred_at=self.context.clock(),
            )
            _fault(self.fault_hook, f"work_item_failed:{receipt.identity}")
            return True
        return False

    def _append_deterministic_observation(self, committed: Committed) -> None:
        capture = committed.closure.capture
        self.context.event_store.append(
            "dispatch_observed",
            {
                "active_usage_status": "trusted_exact",
                "dispatch_id": capture.dispatch_id,
                "execution_capture_hash": capture.identity,
                "observed_active_ms": capture.duration_ms,
                "raw_result_contract_status": "not_applicable",
                "reported_token_usage": 0,
                "token_usage_status": "trusted_exact",
                "work_item_id": capture.work_item_id,
            },
            occurred_at=self.context.clock(),
        )
        _fault(self.fault_hook, f"dispatch_observed:{capture.dispatch_id}")

    def _accept_artifact(
        self,
        item: WorkItemV2,
        certification: CertificationReceiptV2,
        candidate_assessment_id: str | None,
    ) -> None:
        receipt = ArtifactAcceptanceReceiptV2(
            schema_version=2,
            artifact_key=item.output_key,
            artifact_hash=certification.certification_key.artifact_hash,
            certification_receipt_id=certification.identity,
        )
        self.context.ledger.record_artifact_acceptance(receipt)
        _fault(self.fault_hook, f"artifact_acceptance_receipt:{receipt.identity}")
        self.context.event_store.append(
            "artifact_accepted",
            {
                "artifact_acceptance_receipt_id": receipt.identity,
                "artifact_hash": receipt.artifact_hash,
                "artifact_key_id": receipt.artifact_key.identity,
                "candidate_assessment_id": candidate_assessment_id,
                "certification_receipt_id": receipt.certification_receipt_id,
                "work_item_id": item.work_item_id,
            },
            occurred_at=self.context.clock(),
        )
        _fault(self.fault_hook, f"artifact_accepted:{item.work_item_id}")

    def _record_executor_failure(
        self,
        item: WorkItemV2,
        committed: Committed,
        reason_code: Literal[
            "deterministic_execution_failed", "deterministic_artifact_invalid"
        ],
        diagnostics: tuple[str, ...],
    ) -> None:
        receipt = ExecutorFailureReceiptV1(
            schema_version=1,
            executor_contract_hash=item.executor_contract_hash,
            trigger_work_item_id=item.work_item_id,
            dispatch_id=committed.dispatch_id,
            candidate_id=None,
            execution_capture_hash=committed.closure.capture.identity,
            reason_code=reason_code,
            normalized_diagnostics=diagnostics or (reason_code,),
        )
        self.context.ledger.record_executor_failure(receipt)
        _fault(self.fault_hook, f"executor_failure_receipt:{receipt.identity}")
        self.context.event_store.append(
            "executor_failed",
            {
                "executor_contract_hash": receipt.executor_contract_hash,
                "executor_failure_receipt_id": receipt.identity,
                "trigger_work_item_id": receipt.trigger_work_item_id,
            },
            occurred_at=self.context.clock(),
        )
        _fault(self.fault_hook, f"executor_failed:{receipt.identity}")


def _result_from_recovery(
    recovery: Protocol22RecoveryResult,
) -> Protocol22ControllerResult:
    state = recovery.operational_state
    if state == "pinned_authority_unavailable":
        return Protocol22ControllerResult(
            status="pinned_authority_unavailable",
            reason_code="pinned_authority_unavailable",
            events=recovery.events,
            ledger=recovery.ledger,
            plan=None,
            unavailable=recovery.unavailable,
        )
    if state == "dispatch_owner_live":
        status: ControllerStatus = "dispatch_owner_live"
        reason = "dispatch_owner_live"
    elif state == "dispatch_owner_ambiguous":
        status = "dispatch_owner_ambiguous"
        reason = "dispatch_owner_ambiguous"
    elif state == "paused":
        status = "paused"
        reason = "run_paused"
    elif recovery.events and recovery.events[-1].type == "run_completed":
        status = "completed"
        reason = "all_requested_artifacts_accepted"
    elif recovery.events and recovery.events[-1].type == "run_failed":
        status = "failed"
        reason = "terminal_work_item_failures"
    else:
        status = "paused"
        reason = "controller_not_yet_dispatched"
    return Protocol22ControllerResult(
        status=status,
        reason_code=reason,
        events=recovery.events,
        ledger=recovery.ledger,
        plan=None,
    )


def _stopped_recovery(
    recovery: Protocol22RecoveryResult,
) -> Protocol22ControllerResult | None:
    if recovery.operational_state in {
        "pinned_authority_unavailable",
        "dispatch_owner_live",
        "dispatch_owner_ambiguous",
        "paused",
        "terminal",
    }:
        return _result_from_recovery(recovery)
    return None


def accepted_dependencies_for(
    context: Protocol22RunContext,
    item: WorkItemV2,
) -> AcceptedDependencySetV2:
    """Resolve exact role-labelled accepted bytes for one instantiated item."""
    template = next(
        (
            value
            for value in context.graph.templates
            if value.template_id == item.template_id
        ),
        None,
    )
    if template is None:
        raise Protocol22ControllerError("work item template is outside the graph")
    ledger = context.ledger.replay()
    by_role: dict[str, AcceptedArtifactV2] = {}
    payloads: dict[str, bytes] = {}
    templates = {value.template_id: value for value in context.graph.templates}
    if not template.required_template_ids and item.output_key.artifact_kind in {
        "source-inventory",
        "domain-inventory",
        "source-partition",
    }:
        workspace_hash = context.inputs.workspace_partition.identity
        workspace_bytes = canonical_json_bytes(
            context.inputs.workspace_partition.to_json_dict()
        )
        if context.object_store.put_blob(workspace_bytes) != workspace_hash:
            raise Protocol22ControllerError(
                "workspace partition publication changed identity"
            )
        workspace = AcceptedArtifactV2(workspace_hash, workspace_hash)
        return AcceptedDependencySetV2(
            {"workspace_partition": workspace},
            {workspace_hash: workspace_bytes},
        )
    for dependency_id in template.required_template_ids:
        dependency_item = next(
            (
                value
                for value in ledger.certification_work_items.values()
                if value.template_id == dependency_id
            ),
            None,
        )
        if dependency_item is None:
            raise Protocol22ControllerError(
                "ready work item has no accepted dependency work item"
            )
        accepted = ledger.artifact_for_key(dependency_item.output_key.identity)
        if accepted is None:
            raise Protocol22ControllerError(
                "ready work item has no accepted dependency receipt"
            )
        role = _dependency_role(item, templates[dependency_id])
        if role in by_role:
            raise Protocol22ControllerError(f"duplicate dependency role: {role}")
        by_role[role] = accepted
        payloads[accepted.artifact_hash] = context.object_store.read_blob(
            accepted.artifact_hash
        )
    # Some deterministic assemblers validate a direct artifact's immutable
    # closure (for example a domain baseline's context bundle).  Those objects
    # are not additional graph edges, but their accepted bytes must be
    # retrievable by content address during reconstruction.
    for receipt in ledger.accepted_artifacts.values():
        payloads.setdefault(
            receipt.artifact_hash,
            context.object_store.read_blob(receipt.artifact_hash),
        )
    return AcceptedDependencySetV2(by_role, payloads)


def _reconstruct_work_item(
    context: Protocol22RunContext,
    ledger: Protocol22LedgerView,
    work_item_id: str,
) -> WorkItemV2 | None:
    accepted_by_template: dict[str, AcceptedArtifactV2] = {}
    for receipt in ledger.accepted_artifacts.values():
        dependency_item = ledger.certification_work_items.get(
            receipt.certification_receipt_id
        )
        if dependency_item is not None:
            accepted_by_template[dependency_item.template_id] = AcceptedArtifactV2(
                receipt.artifact_key.identity,
                receipt.artifact_hash,
            )
    for template in context.graph.templates:
        if not all(
            dependency_id in accepted_by_template
            for dependency_id in template.required_template_ids
        ):
            continue
        dependencies = {
            dependency_id: accepted_by_template[dependency_id]
            for dependency_id in template.required_template_ids
        }
        item = instantiate_ready_item(template, dependencies, context.inputs)
        if item.work_item_id == work_item_id:
            return item
    return None


def _dependency_role(item: WorkItemV2, dependency: object) -> str:
    kind = getattr(dependency, "artifact_kind", None)
    domain_key = getattr(getattr(dependency, "scope", None), "domain_key", None)
    static = {
        "source-inventory": "source_inventory",
        "source-partition": "source_partition",
        "source-evidence-pack": "source_evidence_pack",
        "domain-inventory": "domain_inventory",
        "domain-evidence-pack": "domain_evidence_pack",
        "domain-context-bundle": "context_bundle",
        "source-overview-context-bundle": "context_bundle",
        "source-overview": "source_overview",
    }
    if kind in static:
        return static[kind]
    if kind == "domain-baseline" and domain_key is not None:
        return f"domain:{domain_key}"
    raise Protocol22ControllerError(
        f"unsupported dependency role for {item.output_key.artifact_kind}: {kind}"
    )


def _attempt_kind(item: WorkItemV2, budget: BudgetDecisionV2) -> str:
    if budget.generation_attempts.get(item.work_item_id, 0) == 0:
        return "initial_generation"
    retry = budget.retry_eligibility.get(item.work_item_id)
    if retry not in {"result_contract_retry", "artifact_contract_retry"}:
        raise Protocol22ControllerError("ready retry has no exact retry eligibility")
    return retry


def _prepared_fits_budget(
    prepared: PreparedExecutionV1,
    budget: BudgetDecisionV2,
) -> bool:
    token_fits = budget.token_limit is None or (
        budget.charged_tokens + prepared.reservation.billable_tokens
        <= budget.token_limit
    )
    active_fits = budget.active_ms_limit is None or (
        budget.charged_active_ms + prepared.reservation.active_ms
        <= budget.active_ms_limit
    )
    return token_fits and active_fits


def _terminal_event_for_fixed_point(decision: PlanDecisionV2) -> str:
    actions = {value.action for value in decision.explanations.values()}
    if actions <= {"reuse"}:
        return "run_completed"
    if actions & {
        "failed",
        "blocked_executor",
        "blocked_dependency",
        "blocked_attempts",
    }:
        return "run_failed"
    raise Protocol22ControllerError(
        "planner reached a nonterminal fixed point without ready work"
    )


def _runtime_for(
    registry: Mapping[str, object],
    key: str,
    label: str,
) -> object:
    value = registry.get(key)
    if value is None:
        raise Protocol22ControllerError(f"{label} is not registered for {key}")
    return value


def _current_process_identity(
    item: WorkItemV2,
    attempt_kind: str,
    now: str,
) -> ProcessIdentity:
    pid = os.getpid()
    identity = ProcessInspector()._probe(pid)
    if identity is None:
        raise Protocol22ControllerError("current controller process is not inspectable")
    return ProcessIdentity(
        pid=pid,
        process_start_identity=identity,
        command_hash=content_digest(
            {
                "attempt_kind": attempt_kind,
                "producer_family": item.producer_family,
                "work_item_id": item.work_item_id,
            }
        ),
        provider_identity=content_digest(
            {
                "executor_contract_hash": item.executor_contract_hash,
                "producer_protocol_version": item.producer_protocol_version,
            }
        ),
        started_at=now,
    )


def _diagnostic_bytes(exc: Exception) -> bytes:
    return f"{type(exc).__name__}\n".encode("utf-8")


def _fault(fault_hook: Callable[[str], None] | None, boundary: str) -> None:
    if fault_hook is not None:
        fault_hook(boundary)


def _candidate_root(context: Protocol22RunContext, dispatch_id: str) -> Path:
    if (
        not dispatch_id.startswith("dispatch-")
        or len(dispatch_id) != len("dispatch-") + 64
        or any(character not in "0123456789abcdef" for character in dispatch_id[9:])
    ):
        raise Protocol22ControllerError("candidate workspace has an unsafe dispatch ID")
    directory_flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    if not getattr(os, "O_NOFOLLOW", 0) or os.mkdir not in os.supports_dir_fd:
        raise Protocol22ControllerError(
            "candidate-work requires directory-relative no-follow operations"
        )
    run_fd: int | None = None
    parent_fd: int | None = None
    candidate_fd: int | None = None
    try:
        run_fd = _open_directory_path_nofollow(context.paths.root, "v2 run root")
        try:
            os.mkdir("candidate-work", 0o700, dir_fd=run_fd)
            os.fsync(run_fd)
        except FileExistsError:
            pass
        parent_fd = os.open(
            "candidate-work",
            directory_flags,
            dir_fd=run_fd,
        )
        if not stat.S_ISDIR(os.fstat(parent_fd).st_mode):
            raise Protocol22ControllerError("candidate-work is not a directory")
        os.fchmod(parent_fd, 0o700)
        try:
            os.mkdir(dispatch_id, 0o700, dir_fd=parent_fd)
        except FileExistsError as exc:
            raise Protocol22ControllerError(
                f"candidate root already exists for unstarted dispatch: {dispatch_id}"
            ) from exc
        candidate_fd = os.open(dispatch_id, directory_flags, dir_fd=parent_fd)
        candidate_metadata = os.fstat(candidate_fd)
        if not stat.S_ISDIR(candidate_metadata.st_mode) or os.listdir(candidate_fd):
            raise Protocol22ControllerError(
                "new candidate workspace is not an empty directory"
            )
        os.fchmod(candidate_fd, 0o700)
        os.fsync(candidate_fd)
        os.fsync(parent_fd)
        root = context.paths.root / "candidate-work" / dispatch_id
        path_metadata = os.stat(root, follow_symlinks=False)
        if (
            not stat.S_ISDIR(path_metadata.st_mode)
            or path_metadata.st_dev != candidate_metadata.st_dev
            or path_metadata.st_ino != candidate_metadata.st_ino
        ):
            raise Protocol22ControllerError(
                "candidate workspace identity changed during creation"
            )
        return root
    except Protocol22ControllerError:
        raise
    except OSError as exc:
        raise Protocol22ControllerError(
            f"cannot establish safe candidate-work directory: {exc}"
        ) from exc
    finally:
        for descriptor in (candidate_fd, parent_fd, run_fd):
            if descriptor is not None:
                os.close(descriptor)


def _open_directory_path_nofollow(path: Path, label: str) -> int:
    absolute = path.absolute()
    if not absolute.is_absolute() or any(
        part in {".", ".."} for part in absolute.parts
    ):
        raise Protocol22ControllerError(f"unsafe {label}: {path}")
    flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    current = os.open("/", flags)
    try:
        for part in absolute.parts[1:]:
            next_fd = os.open(part, flags, dir_fd=current)
            os.close(current)
            current = next_fd
        if not stat.S_ISDIR(os.fstat(current).st_mode):
            raise Protocol22ControllerError(f"{label} is not a directory")
        return current
    except Exception:
        os.close(current)
        raise


def _usage_exceeds_reservation(
    observation: Mapping[str, object],
    prepared: PreparedExecutionV1,
) -> bool:
    tokens = observation["reported_token_usage"]
    active = observation["observed_active_ms"]
    return (
        observation["token_usage_status"] == "trusted_exact"
        and isinstance(tokens, int)
        and tokens > prepared.reservation.billable_tokens
    ) or (
        observation["active_usage_status"] == "trusted_exact"
        and isinstance(active, int)
        and active > prepared.reservation.active_ms
    )


def _artifact_failure(
    diagnostics: tuple[str, ...],
) -> tuple[
    Literal["artifact_contract", "minimum_utility"],
    str,
]:
    if diagnostics == ("minimum_utility_not_met",):
        return "minimum_utility", "minimum_utility_not_met"
    for reason in (
        "candidate_tree_invalid",
        "authorial_schema_invalid",
        "artifact_bound_exceeded",
        "evidence_contract_invalid",
    ):
        if reason in diagnostics:
            return "artifact_contract", reason
    return "artifact_contract", "evidence_contract_invalid"


_RESULT_STDOUT = b"echelon_result:\n  schema_version: 1\n  outcome: candidate_ready\n"


__all__ = (
    "ControllerStatus",
    "Protocol22Controller",
    "Protocol22ControllerError",
    "Protocol22ControllerResult",
    "accepted_dependencies_for",
)
