"""Recoverable separate dispatch of one passive review for a committed proposal.

The reviewer sees the authenticated candidate/safe-context payload only, never
producer reasoning. Schema-2 category review still cannot activate analysis.
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Callable

from harness.re_v2.canonical import content_digest
from harness.re_v2.knowledge_discovery import DiscoveryError, _closed_errors, _load
from harness.re_v2.knowledge_discovery_review import (
    DiscoveryReviewAdmissionError,
    DiscoveryReviewBoundary,
    DiscoveryReviewError,
    DiscoveryReviewStorageError,
)
from harness.re_v2.knowledge_dispatch import (
    DiscoveryBackend,
    DiscoveryController,
    DiscoveryStep,
    _capture_dispatch,
)
from harness.re_v2.protocol_22.provider import DispatchReservationV1
from harness.re_v2.protocol_22.recovery import protocol_22_run_lock


class DiscoveryReviewController:
    """Spend and recover one shared-account turn without advancing its producer."""

    @_closed_errors
    def __init__(self, producer: DiscoveryController, agent_bytes: bytes,
                 backend: DiscoveryBackend, reservation: DispatchReservationV1,
                 *, fault_hook: Callable[[str], None] | None = None):
        if not isinstance(producer, DiscoveryController):
            raise DiscoveryError("invalid-discovery-review-producer")
        if not isinstance(agent_bytes, bytes) or not agent_bytes or len(agent_bytes) > 65_536:
            raise DiscoveryError("invalid-discovery-review-agent")
        if content_digest(agent_bytes) == content_digest(producer.agent_bytes):
            raise DiscoveryError("discovery-review-agent-not-distinct")
        if not callable(backend) or not isinstance(reservation, DispatchReservationV1):
            raise DiscoveryError("invalid-discovery-review-backend")
        if getattr(backend, "contract_id", None) != producer.account.opening["provider_contract_id"]:
            raise DiscoveryError("discovery-review-provider-contract-mismatch")
        if producer.acquisition.paths.root.resolve() != producer.account.paths.root.resolve():
            raise DiscoveryError("discovery-account-run-mismatch")
        self.producer = producer
        self.acquisition, self.account = producer.acquisition, producer.account
        self.boundary = DiscoveryReviewBoundary(self.acquisition.boundary)
        self.agent_bytes, self.backend, self.reservation = agent_bytes, backend, reservation
        self.fault_hook = fault_hook

    def _fault(self, point):
        if self.fault_hook is not None:
            self.fault_hook(point)

    @_closed_errors
    def step(self) -> DiscoveryStep:
        if (self.producer.acquisition is not self.acquisition
                or self.producer.account is not self.account
                or self.acquisition.paths.root.resolve() != self.account.paths.root.resolve()):
            raise DiscoveryError("discovery-account-run-mismatch")
        with protocol_22_run_lock(self.acquisition.paths):
            self.account._require_new_knowledge_store()
            if not self.producer._matches_run(self.acquisition, self.account):
                raise DiscoveryError("knowledge-run-authority-mismatch")
            if getattr(self.backend, "contract_id", None) != self.account.opening["provider_contract_id"]:
                raise DiscoveryError("discovery-review-provider-contract-mismatch")
            state = self.account._state()
            source = self.acquisition.opening["evidence_scope"]["source_id"]
            reviews = state.review_sources.get(source, [])
            producers = state.discovery_sources.get(source, [])
            latest_producer = producers[-1] if producers else None
            matching_review = next(
                (
                    item
                    for item in reversed(reviews)
                    if state.dispatches[item].get("producer_dispatch_id")
                    == latest_producer
                ),
                None,
            )
            if matching_review is not None:
                dispatch_id = matching_review
                self._authenticate_request(state, state.dispatches[dispatch_id])
                if dispatch_id not in state.captures:
                    return DiscoveryStep("blocked", reason_code="dispatch-outcome-indeterminate")
                if dispatch_id not in state.applied:
                    return self._apply(dispatch_id)
                applied = state.applied[dispatch_id]
                if applied["receipt_id"] is not None:
                    self.boundary.read_review(
                        state.dispatches[dispatch_id]["binding_id"],
                        state.dispatches[dispatch_id]["proposal_receipt_id"],
                        applied["receipt_id"],
                    )
                return self._result(applied)

            # A breach is run-wide and must refuse every later native turn,
            # even when the breached producer did not yield an admissible
            # proposal. Already captured reviews above still recover without
            # spending or discarding their paid result.
            if state.usage().reservation_breached:
                return DiscoveryStep("blocked", reason_code="reservation-exceeded")

            if not producers:
                return DiscoveryStep("blocked", reason_code="discovery-review-proposal-required")
            producer_id = producers[-1]
            proposal = self._authenticate_producer(state, producer_id)
            if proposal is None:
                return DiscoveryStep("blocked", reason_code="discovery-review-proposal-required")
            producer_request, producer_application = state.dispatches[producer_id], state.applied[producer_id]
            try:
                context = self.boundary.provider_bytes(
                    producer_request["binding_id"], producer_application["receipt_id"],
                )
            except DiscoveryReviewStorageError:
                raise
            except DiscoveryReviewError as exc:
                if str(exc) in {"discovery-review-context-bound", "discovery-review-overlap-bound"}:
                    return DiscoveryStep("blocked", reason_code=str(exc))
                raise
            if len(self.agent_bytes) + len(context) > self.reservation.initial_input_tokens:
                return DiscoveryStep("blocked", reason_code="discovery-review-input-reservation-exceeded")
            request = {
                "source_id": source,
                "scope_id": producer_request["scope_id"],
                "agent_id": content_digest(self.agent_bytes),
                "binding_id": producer_request["binding_id"],
                "revision_id": producer_application["revision_id"],
                "context_id": content_digest(context),
                "reservation": asdict(self.reservation),
                "turn": len(state.sources.get(source, [])) + 1,
                "producer_dispatch_id": producer_id,
                "proposal_receipt_id": producer_application["receipt_id"],
            }
            refusal = state.review_refusal(request)
            if refusal:
                return DiscoveryStep("blocked", reason_code=refusal)
            self.account.objects.put_blob(self.agent_bytes)
            self.account.objects.put_blob(context)
            dispatch_id = self.account._record("review_reserved", request)
            self._fault("review_reserved")
            _capture_dispatch(
                self.account, self.acquisition.boundary.screen_output, self.backend,
                self.agent_bytes, context, self.reservation, dispatch_id,
            )
            self._fault("dispatch_captured")
            return self._apply(dispatch_id)

    def _authenticate_producer(self, state, dispatch_id):
        if state.dispatch_kinds.get(dispatch_id) != "discovery":
            raise DiscoveryError("invalid-discovery-review-producer")
        request = state.dispatches[dispatch_id]
        if (request["scope_id"] != content_digest(self.acquisition.opening)
                or request["agent_id"] != content_digest(self.producer.agent_bytes)
                or request["reservation"] != asdict(self.producer.reservation)
                or self.account.objects.read_blob(request["agent_id"]) != self.producer.agent_bytes):
            raise DiscoveryError("discovery-review-producer-authority-mismatch")
        self.producer._authenticate_request(state, request)
        application = state.applied.get(dispatch_id)
        if application is None or application["state"] != "proposal_ready":
            return None
        progress = self.acquisition.status()
        if (application["revision_id"] != request["revision_id"]
                or progress.revision_id != request["revision_id"]
                or progress.binding_id != request["binding_id"]):
            raise DiscoveryError("discovery-review-producer-authority-mismatch")
        proposal = self.acquisition.boundary.read_proposal(
            request["binding_id"], application["receipt_id"],
        )
        receipt = _load(self.account.objects.read_blob(application["receipt_id"]))
        capture = state.captures[dispatch_id]
        if (receipt.get("authorial_response_id") != capture["output_id"]
                or receipt.get("proposal_id") != content_digest(proposal)):
            raise DiscoveryError("discovery-review-producer-authority-mismatch")
        return proposal

    def _authenticate_request(self, state, request):
        if (request["agent_id"] != content_digest(self.agent_bytes)
                or request["reservation"] != asdict(self.reservation)
                or self.account.objects.read_blob(request["agent_id"]) != self.agent_bytes):
            raise DiscoveryError("discovery-review-dispatch-authority-mismatch")
        producer_id = request["producer_dispatch_id"]
        proposal = self._authenticate_producer(state, producer_id)
        application = state.applied[producer_id]
        if (proposal is None or request["proposal_receipt_id"] != application["receipt_id"]
                or any(request[key] != state.dispatches[producer_id][key]
                       for key in ("source_id", "scope_id", "binding_id", "revision_id"))):
            raise DiscoveryError("discovery-review-dispatch-authority-mismatch")
        context = self.boundary.provider_bytes(request["binding_id"], request["proposal_receipt_id"])
        if (request["context_id"] != content_digest(context)
                or self.account.objects.read_blob(request["context_id"]) != context):
            raise DiscoveryError("discovery-review-context-mismatch")

    def _apply(self, dispatch_id):
        state = self.account._state()
        request, capture = state.dispatches[dispatch_id], state.captures[dispatch_id]
        self._authenticate_request(state, request)
        if dispatch_id in state.applied:
            return self._result(state.applied[dispatch_id])
        reason, receipt_id, result_state = capture["reason_code"], None, "blocked"
        if state.dispatch_breached(dispatch_id):
            reason = "reservation-exceeded"
        if reason is None:
            try:
                receipt_id = self.boundary.admit(
                    request["binding_id"], request["proposal_receipt_id"],
                    self.account.objects.read_blob(capture["output_id"]),
                )
            except DiscoveryReviewAdmissionError:
                reason = "review-result-invalid"
            if receipt_id is not None:
                receipt = self.boundary.read_review(
                    request["binding_id"], request["proposal_receipt_id"], receipt_id,
                )
                # `review_ready` is dispatch completion, not analysis
                # certification; both schema branches retain the passive receipt.
                result_state = ("review_ready" if receipt["outcome"] == "ready_for_planning"
                                else "revision_required")
        applied = {
            "dispatch_id": dispatch_id,
            "state": result_state,
            "receipt_id": receipt_id,
            "reason_code": reason,
            "revision_id": request["revision_id"],
        }
        self.account._record("review_applied", applied)
        self._fault("review_applied")
        return self._result(applied)

    @staticmethod
    def _result(applied):
        return DiscoveryStep(
            applied["state"], applied["receipt_id"], applied["reason_code"],
        )
