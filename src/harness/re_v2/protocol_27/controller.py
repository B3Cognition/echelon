"""Deterministic bounded controller for protocol-2.7 synthesis closure."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import tempfile
import time
from types import MappingProxyType
from typing import Callable, Literal, Mapping

from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.events import EventRecord, EventStore
from harness.re_v2.ledger import ObjectStore
from harness.re_v2.protocol_22.provider import normalize_captured_provider_usage
from harness.squad_provider import SquadCliProvider

from .budget import SynthesisBudgetDecisionV1, evaluate_synthesis_budget
from .checkpoints import adopt_synthesis_checkpoints
from .context import SynthesisContextV1
from .events import PROTOCOL_27_EVENTS
from .execution import (
    Protocol27ExecutionError,
    Protocol27ExecutionStore,
    SquadCliSynthesisRenderer,
    build_synthesis_provider_dependencies,
    prepare_synthesis_execution,
    synthesis_candidate_bytes,
)
from .graph import SynthesisGraph
from .inputs import ValidatedProtocol27Inputs
from .ledger import Protocol27Ledger, Protocol27LedgerView
from .model import (
    SynthesisArtifactAuthorityV1,
    SynthesisRootV1,
    SynthesisWorkItemV1,
)
from .runtime import Protocol27DeterministicRuntime, Protocol27RuntimeError


ActionKind = Literal[
    "adopt",
    "dispatch",
    "recover_capture",
    "accept_candidate",
    "create_root",
    "closure_complete",
    "incomplete",
]


class Protocol27ControllerError(RuntimeError):
    """Raised when the synthesis controller cannot preserve durable authority."""


@dataclass(frozen=True, slots=True)
class SynthesisControllerStateV1:
    graph: SynthesisGraph
    accepted_node_hashes: Mapping[str, str]
    accepted_work_item_ids: tuple[str, ...]
    adopted_work_item_ids: tuple[str, ...]
    selected_checkpoint_work_item_ids: tuple[str, ...]
    attempts_by_work_item: Mapping[str, int]
    last_failure_by_work_item: Mapping[str, tuple[str, str]]
    pending_capture_work_item_id: str | None
    pending_candidate_work_item_id: str | None
    root_accepted: bool
    budget_allowed: bool

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "accepted_node_hashes",
            MappingProxyType(dict(sorted(self.accepted_node_hashes.items()))),
        )
        object.__setattr__(
            self,
            "attempts_by_work_item",
            MappingProxyType(dict(sorted(self.attempts_by_work_item.items()))),
        )
        object.__setattr__(
            self,
            "last_failure_by_work_item",
            MappingProxyType(dict(sorted(self.last_failure_by_work_item.items()))),
        )


@dataclass(frozen=True, slots=True)
class SynthesisControllerActionV1:
    kind: ActionKind
    work_item: SynthesisWorkItemV1 | None = None
    attempt_kind: str | None = None
    retry_diagnostics: tuple[str, ...] = ()
    reason: str | None = None

    @property
    def work_item_id(self) -> str | None:
        return None if self.work_item is None else self.work_item.work_item_id


@dataclass(frozen=True, slots=True)
class Protocol27ControllerResult:
    synthesis_closure_complete: bool
    terminal_kind: str
    accepted_artifact_count: int
    required_artifact_count: int
    provider_attempts: int
    contract_retries: int
    synthesis_root_id: str | None


def reconstruct_synthesis_controller_state(
    inputs: ValidatedProtocol27Inputs,
    ledger: Protocol27LedgerView,
    events: tuple[EventRecord, ...],
    budget: SynthesisBudgetDecisionV1,
    *,
    pending_capture_work_item_id: str | None = None,
    pending_candidate_work_item_id: str | None = None,
) -> SynthesisControllerStateV1:
    accepted_nodes: dict[str, str] = {}
    for key_id, work_item in ledger.accepted_work_items.items():
        node = inputs.graph.node_for_work_item(work_item)
        accepted_nodes[node.node_id] = ledger.accepted_artifacts[key_id].artifact_hash
    attempts: dict[str, int] = {}
    failures: dict[str, tuple[str, str]] = {}
    for event in events:
        if event.type == "dispatch_started":
            work_id = str(event.payload["work_item_id"])
            attempts[work_id] = attempts.get(work_id, 0) + 1
        elif event.type == "work_item_failed":
            failures[str(event.payload["work_item_id"])] = (
                str(event.payload["failure_class"]),
                str(event.payload["reason_code"]),
            )
    return SynthesisControllerStateV1(
        graph=inputs.graph,
        accepted_node_hashes=accepted_nodes,
        accepted_work_item_ids=tuple(
            sorted(item.work_item_id for item in ledger.accepted_work_items.values())
        ),
        adopted_work_item_ids=tuple(sorted(ledger.checkpoint_adoptions)),
        selected_checkpoint_work_item_ids=tuple(
            entry.work_item_id for entry in inputs.checkpoint_selection.entries
        ),
        attempts_by_work_item=attempts,
        last_failure_by_work_item=failures,
        pending_capture_work_item_id=pending_capture_work_item_id,
        pending_candidate_work_item_id=pending_candidate_work_item_id,
        root_accepted=ledger.synthesis_root is not None,
        budget_allowed=budget.allowed,
    )


def plan_next_synthesis(
    state: SynthesisControllerStateV1,
) -> SynthesisControllerActionV1:
    if state.pending_capture_work_item_id is not None:
        return SynthesisControllerActionV1("recover_capture")
    if state.pending_candidate_work_item_id is not None:
        return SynthesisControllerActionV1("accept_candidate")
    if set(state.selected_checkpoint_work_item_ids) - set(state.adopted_work_item_ids):
        return SynthesisControllerActionV1("adopt")
    if len(state.accepted_node_hashes) == len(state.graph.required_nodes):
        return SynthesisControllerActionV1(
            "closure_complete" if state.root_accepted else "create_root"
        )
    if not state.budget_allowed:
        return SynthesisControllerActionV1(
            "incomplete", reason="synthesis-budget-exhausted"
        )
    ready = state.graph.ready_work_items(state.accepted_node_hashes)
    for item in ready:
        attempts = state.attempts_by_work_item.get(item.work_item_id, 0)
        if attempts >= 2:
            continue
        failure = state.last_failure_by_work_item.get(item.work_item_id)
        if attempts == 0:
            return SynthesisControllerActionV1(
                "dispatch", item, "initial_generation", ()
            )
        if failure is None:
            return SynthesisControllerActionV1(
                "incomplete", reason="synthesis-attempt-has-no-failure-authority"
            )
        failure_class, reason = failure
        retry_kind = (
            "result_contract_retry"
            if failure_class == "result_contract"
            else "artifact_contract_retry"
        )
        return SynthesisControllerActionV1(
            "dispatch", item, retry_kind, (reason,)
        )
    return SynthesisControllerActionV1(
        "incomplete", reason="synthesis-dependency-closure-incomplete"
    )


class Protocol27Controller:
    def __init__(
        self,
        inputs: ValidatedProtocol27Inputs,
        *,
        provider_factory: Callable[[], SquadCliProvider],
        clock: Callable[[], str] | None = None,
    ) -> None:
        if not isinstance(inputs, ValidatedProtocol27Inputs) or not callable(
            provider_factory
        ):
            raise Protocol27ControllerError(
                "synthesis controller requires validated inputs and provider factory"
            )
        self.inputs = inputs
        self.objects = ObjectStore(inputs.paths.objects)
        self.events = EventStore(inputs.paths, protocol=PROTOCOL_27_EVENTS)
        self.ledger = Protocol27Ledger(inputs)
        self.execution = Protocol27ExecutionStore(inputs.paths, self.objects)
        self.runtime = Protocol27DeterministicRuntime(self.objects)
        self.provider_factory = provider_factory
        self.clock = clock or (
            lambda: datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        )
        self._renderer: SquadCliSynthesisRenderer | None = None

    def run_to_closure(self) -> Protocol27ControllerResult:
        self._initialize_authority()
        while True:
            events = self.events.replay()
            ledger = self.ledger.replay()
            budget = evaluate_synthesis_budget(self.inputs.manifest, events, ledger)
            state = reconstruct_synthesis_controller_state(
                self.inputs, ledger, events, budget
            )
            action = plan_next_synthesis(state)
            if action.kind == "adopt":
                self._plan_selected_checkpoints(events)
                adopt_synthesis_checkpoints(self)
                continue
            if action.kind == "dispatch":
                assert action.work_item is not None and action.attempt_kind is not None
                refusal = self._dispatch(action, budget)
                if refusal is not None:
                    return self._result("incomplete", refusal)
                continue
            if action.kind == "create_root":
                self._create_root()
                continue
            if action.kind in {"recover_capture", "accept_candidate"}:
                raise Protocol27ControllerError(
                    "durable boundary recovery is delegated to protocol-2.7 recovery"
                )
            return self._result(action.kind, action.reason)

    def _result(self, terminal_kind: str, reason: str | None) -> Protocol27ControllerResult:
        final = self.ledger.replay()
        final_budget = evaluate_synthesis_budget(
            self.inputs.manifest, self.events.replay(), final
        )
        return Protocol27ControllerResult(
            synthesis_closure_complete=terminal_kind == "closure_complete",
            terminal_kind=reason or terminal_kind,
            accepted_artifact_count=len(final.accepted_artifacts),
            required_artifact_count=len(self.inputs.graph.required_nodes),
            provider_attempts=final_budget.provider_attempts,
            contract_retries=(
                sum(final_budget.result_contract_retries.values())
                + sum(final_budget.artifact_contract_retries.values())
            ),
            synthesis_root_id=(
                None if final.synthesis_root is None else final.synthesis_root.identity
            ),
        )

    def _initialize_authority(self) -> None:
        events = self.events.replay()
        if not events:
            self.events.append(
                "run_created",
                {"run_manifest_id": self.inputs.manifest.run_manifest_id},
                occurred_at=self.inputs.manifest.created_at,
            )
            events = self.events.replay()
        if events[0].payload.get("run_manifest_id") != self.inputs.manifest.run_manifest_id:
            raise Protocol27ControllerError("run creation differs from manifest")
        if not any(item.type == "synthesis_request_frozen" for item in events):
            self.events.append(
                "synthesis_request_frozen",
                {"request_id": self.inputs.manifest.request_id},
                occurred_at=self.clock(),
            )
        for receipt in self.inputs.manifest.partial_acceptances:
            self.ledger.record_partial_acceptance(receipt)
            if receipt.source_id not in {
                str(item.payload["source_id"])
                for item in self.events.replay()
                if item.type == "partial_source_accepted"
            }:
                self.events.append(
                    "partial_source_accepted",
                    {
                        "receipt_id": receipt.receipt_id,
                        "request_id": receipt.operation_id,
                        "source_id": receipt.source_id,
                    },
                    occurred_at=self.clock(),
                )

    def _plan_selected_checkpoints(self, events: tuple[EventRecord, ...]) -> None:
        planned = {
            str(work_id)
            for event in events
            if event.type == "work_planned"
            for work_id in event.payload["work_item_ids"]
        }
        missing = sorted(
            entry.work_item_id
            for entry in self.inputs.checkpoint_selection.entries
            if entry.work_item_id not in planned
        )
        if missing:
            self.events.append(
                "work_planned", {"work_item_ids": missing}, occurred_at=self.clock()
            )

    def _dispatch(
        self,
        action: SynthesisControllerActionV1,
        budget: SynthesisBudgetDecisionV1,
    ) -> str | None:
        item = action.work_item
        assert item is not None and action.attempt_kind is not None
        self._ensure_work_planned(item)
        dependencies = build_synthesis_provider_dependencies(
            self.inputs, item, action.retry_diagnostics
        )
        prepared = prepare_synthesis_execution(
            self.execution, item, dependencies, action.attempt_kind
        )
        reservation = prepared.reservation
        if (
            budget.token_limit is not None
            and budget.charged_tokens + reservation.billable_tokens > budget.token_limit
        ) or (
            budget.active_ms_limit is not None
            and budget.charged_active_ms + reservation.active_ms > budget.active_ms_limit
        ):
            return "synthesis-reservation-exceeds-remaining-budget"
        attempt_index = budget.provider_attempts_by_work_item.get(item.work_item_id, 0) + 1
        self.events.append(
            "dispatch_started",
            {
                "active_ms_reservation": reservation.active_ms,
                "attempt_index": attempt_index,
                "attempt_kind": action.attempt_kind,
                "billable_token_reservation": reservation.billable_tokens,
                "dispatch_id": prepared.dispatch_id,
                "execution_input_hash": prepared.execution_input_hash,
                "executor_contract_hash": item.executor_contract_hash,
                "work_item_id": item.work_item_id,
            },
            occurred_at=self.clock(),
        )
        candidate_root = Path(
            tempfile.mkdtemp(prefix=f".{prepared.dispatch_id}.", dir=self.inputs.paths.root)
        )
        try:
            renderer = self._synthesis_renderer(dependencies.executor)
            raw = renderer.execute(
                prepared.execution_input,
                dependencies.agent_bytes,
                dependencies.context_bytes,
                dependencies.response_schema_bytes,
                reservation,
                candidate_root,
                time.monotonic() + reservation.active_ms / 1000,
                retry_diagnostics=dependencies.retry_diagnostics,
            )
            captured = self.execution.capture_provider_result(
                prepared, candidate_root, raw
            )
            committed = self.execution.commit_capture(captured)
            closure = committed.closure
            usage = normalize_captured_provider_usage(
                closure.capture.execution_mode,
                closure.provider_usage_bytes,
                dependencies.executor.token_accounting,
            )
            raw_status = "valid" if raw.outcome == "candidate_ready" else "invalid"
            self.events.append(
                "dispatch_observed",
                {
                    "active_usage_status": "trusted_exact",
                    "dispatch_id": prepared.dispatch_id,
                    "execution_capture_hash": closure.capture.identity,
                    "observed_active_ms": closure.capture.duration_ms,
                    "raw_result_contract_status": raw_status,
                    "reported_token_usage": usage.billable_tokens,
                    "token_usage_status": usage.status,
                    "work_item_id": item.work_item_id,
                },
                occurred_at=self.clock(),
            )
            if raw.outcome != "candidate_ready":
                failure_class = (
                    "result_contract"
                    if raw.outcome == "invalid_response"
                    else "execution_indeterminate"
                )
                reason = (
                    "result_unrecoverable"
                    if failure_class == "result_contract"
                    else "execution_outcome_indeterminate"
                )
                self._record_failure(item, failure_class, reason, closure.capture.identity)
                return None
            try:
                payload = synthesis_candidate_bytes(self.execution, closure)
            except Protocol27ExecutionError:
                self._record_failure(
                    item,
                    "artifact_contract",
                    "candidate_tree_invalid",
                    closure.capture.identity,
                )
                return None
            candidate_id = content_digest(payload)
            assert closure.candidate_inventory is not None
            self.events.append(
                "candidate_persisted",
                {
                    "candidate_id": candidate_id,
                    "candidate_inventory_hash": closure.candidate_inventory.identity,
                    "dispatch_id": prepared.dispatch_id,
                    "execution_capture_hash": closure.capture.identity,
                    "work_item_id": item.work_item_id,
                },
                occurred_at=self.clock(),
            )
            try:
                typed_context = SynthesisContextV1.from_json_dict(
                    json.loads(dependencies.context_bytes)
                )
                result = self.runtime.certify_candidate(item, typed_context, payload)
            except (Protocol27RuntimeError, ValueError) as exc:
                reason = _runtime_failure_reason(exc)
                self._record_failure(
                    item,
                    "artifact_contract",
                    reason,
                    closure.capture.identity,
                )
                return None
            self.ledger.record_candidate_assessment(result.assessment)
            self.ledger.record_synthesis_certification(result.certification)
            self.ledger.record_synthesis_acceptance(result.acceptance)
            generated = _generated_dependency_key_ids(self.inputs, item)
            self.events.append(
                "synthesis_candidate_certified",
                {
                    "artifact_hash": result.acceptance.artifact_hash,
                    "artifact_key_id": result.acceptance.artifact_key.artifact_key_id,
                    "candidate_assessment_id": result.assessment.identity,
                    "candidate_id": candidate_id,
                    "certification_id": result.certification.identity,
                    "generated_dependency_key_ids": list(generated),
                    "work_item_id": item.work_item_id,
                },
                occurred_at=self.clock(),
            )
            self.events.append(
                "synthesis_artifact_accepted",
                {
                    "acceptance_receipt_id": result.acceptance.identity,
                    "adopted": False,
                    "artifact_hash": result.acceptance.artifact_hash,
                    "artifact_key_id": result.acceptance.artifact_key.artifact_key_id,
                    "certification_id": result.certification.identity,
                    "generated_dependency_key_ids": list(generated),
                    "work_item_id": item.work_item_id,
                },
                occurred_at=self.clock(),
            )
            return None
        finally:
            shutil.rmtree(candidate_root, ignore_errors=True)

    def _ensure_work_planned(self, item: SynthesisWorkItemV1) -> None:
        planned = {
            str(work_id)
            for event in self.events.replay()
            if event.type == "work_planned"
            for work_id in event.payload["work_item_ids"]
        }
        if item.work_item_id not in planned:
            self.events.append(
                "work_planned",
                {"work_item_ids": [item.work_item_id]},
                occurred_at=self.clock(),
            )

    def _record_failure(
        self,
        item: SynthesisWorkItemV1,
        failure_class: str,
        reason: str,
        capture_hash: str,
    ) -> None:
        payload = canonical_json_bytes(
            {
                "capture_hash": capture_hash,
                "failure_class": failure_class,
                "reason_code": reason,
                "schema_version": 1,
                "work_item_id": item.work_item_id,
            }
        )
        receipt_id = self.objects.put_blob(payload)
        self.events.append(
            "work_item_failed",
            {
                "failure_class": failure_class,
                "failure_receipt_id": receipt_id,
                "reason_code": reason,
                "work_item_id": item.work_item_id,
            },
            occurred_at=self.clock(),
        )

    def _create_root(self) -> None:
        view = self.ledger.replay()
        if view.synthesis_root is not None:
            return
        graph = self.inputs.graph
        root = SynthesisRootV1(
            schema_version=1,
            accepted_source_outcome_ids=tuple(
                sorted(item.identity for item in self.inputs.manifest.accepted_sources)
            ),
            accepted_artifacts=tuple(
                sorted(
                    (
                        SynthesisArtifactAuthorityV1(
                            key_id,
                            acceptance.artifact_hash,
                            acceptance.identity,
                        )
                        for key_id, acceptance in view.accepted_artifacts.items()
                    ),
                    key=lambda item: item.identity,
                )
            ),
            partial_acceptance_receipt_ids=tuple(
                sorted(item.receipt_id for item in self.inputs.manifest.partial_acceptances)
            ),
            debt_manifest_hashes=graph.root_specification.debt_manifest_hashes,
            topology_id=graph.topology.identity,
            graph_id=graph.graph_id,
            materialization_policy_hash=content_digest(
                b"protocol-2.7-materialization-v1"
            ),
            producer_authority_hash=(
                graph.policy_catalog.implementation_authority.producer_authority_hash
            ),
            verifier_authority_hash=(
                graph.policy_catalog.implementation_authority.verifier_authority_hash
            ),
            synthesis_policy_hash=graph.policy_catalog.identity,
            input_quality=graph.root_specification.input_quality,
        )
        self.objects.put_blob(canonical_json_bytes(root.to_json_dict()))
        self.ledger.record_synthesis_root(root)
        self.events.append(
            "synthesis_root_accepted",
            {
                "required_artifact_key_ids": sorted(view.accepted_artifacts),
                "synthesis_root_id": root.identity,
            },
            occurred_at=self.clock(),
        )

    def _synthesis_renderer(
        self, executor
    ) -> SquadCliSynthesisRenderer:  # type: ignore[no-untyped-def]
        if self._renderer is None:
            self._renderer = SquadCliSynthesisRenderer(
                (executor,), provider_factory=self.provider_factory
            )
        return self._renderer


def _generated_dependency_key_ids(
    inputs: ValidatedProtocol27Inputs,
    item: SynthesisWorkItemV1,
) -> tuple[str, ...]:
    node = inputs.graph.node_for_work_item(item)
    fixed = {value.artifact_key_id for value in node.fixed_artifact_dependencies}
    return tuple(sorted(set(item.dependency_key_ids) - fixed))


def _runtime_failure_reason(exc: Exception) -> str:
    message = str(exc).lower()
    if "byte ceiling" in message or "exceeds" in message:
        return "artifact_bound_exceeded"
    if "evidence" in message or "citation" in message or "debt" in message:
        return "evidence_contract_invalid"
    return "authorial_schema_invalid"


__all__ = (
    "Protocol27Controller",
    "Protocol27ControllerError",
    "Protocol27ControllerResult",
    "SynthesisControllerActionV1",
    "SynthesisControllerStateV1",
    "plan_next_synthesis",
    "reconstruct_synthesis_controller_state",
)
