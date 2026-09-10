"""Single-step versioned discovery execution under the existing RE controller lock.

The backend seam is intentionally not installed routing. A production backend
must enforce a tools-free, bounded, non-logging request before it can be enabled.
Only screened bytes cross the seam; schema-2 category proposals remain passive
and provider output has no ledger or plan-activation authority.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import time
from typing import Callable, Protocol

from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.knowledge_accounting import KnowledgeDispatchAccount, KnowledgeDispatchPolicy, KnowledgeProviderContract
from harness.re_v2.knowledge_acquisition import DiscoveryAcquisition
from harness.re_v2.knowledge_discovery import DiscoveryAdmissionError, DiscoveryError, _closed_errors, _load
from harness.re_v2.knowledge_evidence import KnowledgeEvidenceError
from harness.re_v2.protocol_22.provider import (
    DispatchReservationV1, NormalizedUsageV1, canonical_normalized_usage_bytes,
)
from harness.re_v2.protocol_22.recovery import protocol_22_run_lock


@dataclass(frozen=True, slots=True)
class ProviderReply:
    output: bytes
    usage: NormalizedUsageV1
    reason_code: str | None = None


class DiscoveryBackend(Protocol):
    """Accounted transport only: no ordinary logs, artifacts, tools or retries.

    Implementations must count the entire request (including wrappers) against
    initial_input_tokens and honor the capture/deadline controls. Billable token
    reservations are charged observations, not a hard native in-flight ceiling.
    """

    contract_id: str

    def __call__(self, agent: bytes, context: bytes, reservation: DispatchReservationV1) -> ProviderReply: ...


@dataclass(frozen=True, slots=True)
class DiscoveryStep:
    state: str
    receipt_id: str | None = None
    reason_code: str | None = None


def _capture_dispatch(account, screen_output, backend, agent_bytes, context,
                      reservation, dispatch_id):
    """Invoke one already-reserved dispatch and durably capture its outcome."""
    usage = NormalizedUsageV1("unavailable", None, {})
    output_id, reason = None, None
    active_ms, active_status = None, "unavailable"
    started = time.monotonic_ns()
    try:
        reply = backend(agent_bytes, context, reservation)
    except Exception:
        # The call may have spent resources before failing. Never refund it
        # or expose exception text (which can contain source/provider data).
        reason = "provider-failed"
    else:
        active_ms = max(0, (time.monotonic_ns() - started + 999_999) // 1_000_000)
        active_status = "trusted_exact"
        if (not isinstance(reply, ProviderReply) or not isinstance(reply.usage, NormalizedUsageV1)
                or not isinstance(reply.output, bytes)
                or reply.reason_code not in {
                    None, "provider-failed", "unsafe-provider-output",
                    "invalid-provider-result",
                }):
            reason = "invalid-provider-result"
            active_ms, active_status = None, "unavailable"
        else:
            usage = reply.usage
            reason = reply.reason_code
            if reason is None:
                try:
                    output = screen_output(reply.output)
                except KnowledgeEvidenceError as exc:
                    if str(exc) == "unsafe-quarantine-store":
                        raise
                    reason = "unsafe-provider-output"
                else:
                    output_id = account.objects.put_blob(output)
    account._record("dispatch_captured", {
        "dispatch_id": dispatch_id, "output_id": output_id, "reason_code": reason,
        "usage": _load(canonical_normalized_usage_bytes(usage)),
        "active_ms": active_ms, "active_status": active_status,
    })


class DiscoveryController:
    @staticmethod
    def _matches_run(acquisition, account):
        declared = acquisition.boundary.run_authority()
        selected = account.opening["run_authority"]
        source_id = acquisition.opening["evidence_scope"]["source_id"]
        return (all(selected[key] == declared[key] for key in ("snapshot_id", "partition_id", "security_policy_id"))
                and set(selected["source_ids"]).issubset(declared["source_ids"])
                and source_id in selected["source_ids"])

    @_closed_errors
    def __init__(self, acquisition: DiscoveryAcquisition, account: KnowledgeDispatchAccount,
                 agent_bytes: bytes, backend: DiscoveryBackend, reservation: DispatchReservationV1,
                 *, fault_hook: Callable[[str], None] | None = None):
        if acquisition.paths.root.resolve() != account.paths.root.resolve():
            raise DiscoveryError("discovery-account-run-mismatch")
        if not self._matches_run(acquisition, account):
            raise DiscoveryError("knowledge-run-authority-mismatch")
        if not isinstance(agent_bytes, bytes) or not agent_bytes or len(agent_bytes) > 65_536:
            raise DiscoveryError("invalid-discovery-agent")
        if not callable(backend) or not isinstance(reservation, DispatchReservationV1):
            raise DiscoveryError("invalid-discovery-backend")
        if getattr(backend, "contract_id", None) != account.opening["provider_contract_id"]:
            raise DiscoveryError("discovery-provider-contract-mismatch")
        self.acquisition, self.account = acquisition, account
        self.agent_bytes, self.backend, self.reservation = agent_bytes, backend, reservation
        self.fault_hook = fault_hook

    def _fault(self, point):
        if self.fault_hook is not None:
            self.fault_hook(point)

    @_closed_errors
    def step(self) -> DiscoveryStep:
        """One provider turn, or recovery of one recorded turn. Never a retry loop."""
        with protocol_22_run_lock(self.acquisition.paths):
            self.account._require_new_knowledge_store()
            if not self._matches_run(self.acquisition, self.account):
                raise DiscoveryError("knowledge-run-authority-mismatch")
            if getattr(self.backend, "contract_id", None) != self.account.opening["provider_contract_id"]:
                raise DiscoveryError("discovery-provider-contract-mismatch")
            state = self.account._state()
            source = self.acquisition.opening["evidence_scope"]["source_id"]
            history = state.discovery_sources.get(source, [])
            if history:
                first = state.dispatches[history[0]]
                if (first["scope_id"] != content_digest(self.acquisition.opening)
                        or first["agent_id"] != content_digest(self.agent_bytes)
                        or first["reservation"] != asdict(self.reservation)):
                    raise DiscoveryError("discovery-dispatch-authority-mismatch")
                last = history[-1]
                self._authenticate_request(state.dispatches[last])
                if last not in state.captures:
                    return DiscoveryStep("blocked", reason_code="dispatch-outcome-indeterminate")
                if last not in state.applied:
                    return self._apply(last)
                applied = state.applied[last]
                if applied["state"] != "evidence_ready":
                    return self._result(applied)
            self.acquisition._recover_locked()
            progress = self.acquisition.status()
            context = self.acquisition._provider_bytes_locked()
            # This offline contract freezes byte-upper-bound accounting, not an
            # exact tokenizer. This is a necessary lower bound; the backend must
            # additionally fit its complete framing in that same reservation.
            if len(self.agent_bytes) + len(context) > self.reservation.initial_input_tokens:
                return DiscoveryStep("blocked", reason_code="discovery-input-reservation-exceeded")
            request = {"source_id": source, "scope_id": content_digest(self.acquisition.opening),
                       "agent_id": content_digest(self.agent_bytes), "binding_id": progress.binding_id,
                       "revision_id": progress.revision_id, "context_id": content_digest(context),
                       "reservation": asdict(self.reservation), "turn": len(history) + 1}
            refusal = state.refusal(request)
            if refusal:
                return DiscoveryStep("blocked", reason_code=refusal)
            self.account.objects.put_blob(self.agent_bytes)
            self.account.objects.put_blob(context)
            dispatch_id = self.account._record("dispatch_reserved", request)
            self._fault("dispatch_reserved")
            self._invoke(dispatch_id, context)
            self._fault("dispatch_captured")
            return self._apply(dispatch_id)

    def _authenticate_request(self, request):
        # Reusing a captured/completed turn is read-only but still authenticates
        # its actual committed input, not merely the existence of hashed blobs.
        history, _ = self.acquisition.ledger.replay_with_history()
        committed = {r.payload["receipt_id"] for r in history
                     if r.type in {"discovery_opened", "context_committed"}}
        if request["revision_id"] not in committed:
            raise DiscoveryError("uncommitted-discovery-dispatch")
        revision = _load(self.account.objects.read_blob(request["revision_id"]))
        binding = revision.get("binding_id", revision.get("initial_binding_id"))
        if request["binding_id"] != binding or request["context_id"] != revision["context_id"]:
            raise DiscoveryError("discovery-dispatch-context-mismatch")
        self.acquisition.boundary.provider_bytes(binding)

    def _invoke(self, dispatch_id, context):
        _capture_dispatch(
            self.account, self.acquisition.boundary.screen_output, self.backend,
            self.agent_bytes, context, self.reservation, dispatch_id,
        )

    def _apply(self, dispatch_id):
        state = self.account._state()
        request, capture = state.dispatches[dispatch_id], state.captures[dispatch_id]
        if dispatch_id in state.applied:
            return self._result(state.applied[dispatch_id])
        reason, receipt_id, result_state = capture["reason_code"], None, "blocked"
        if state.dispatch_breached(dispatch_id):
            reason = "reservation-exceeded"
        if reason is None:
            try:
                receipt_id = self.acquisition.boundary.admit(
                    request["binding_id"], self.account.objects.read_blob(capture["output_id"]), capture_bound=True)
            except DiscoveryAdmissionError:
                reason = "discovery-result-invalid"
            if receipt_id is not None:
                receipt = _load(self.account.objects.read_blob(receipt_id))
                if receipt["state"] == "proposal_validated":
                    # Every proposal version is staged only. Schema 2 adds
                    # category-aware input for independent review; it does not
                    # add plan-activation authority at this boundary.
                    result_state = "proposal_ready"
                else:
                    try:
                        progress = self.acquisition._resolve_locked(request["binding_id"], receipt_id)
                    except DiscoveryError as exc:
                        if str(exc) not in {"evidence-expansion-limit", "discovery-context-bound"}:
                            raise
                        reason = str(exc)
                    else:
                        if progress.revision_id == request["revision_id"]:
                            reason = "discovery-no-new-evidence"
                        else:
                            result_state = "evidence_ready"
        applied = {"dispatch_id": dispatch_id, "state": result_state, "receipt_id": receipt_id,
                   "reason_code": reason, "revision_id": self.acquisition.status().revision_id}
        self.account._record("discovery_applied", applied)
        self._fault("discovery_applied")
        return self._result(applied)

    @staticmethod
    def _result(applied):
        return DiscoveryStep(applied["state"], applied["receipt_id"], applied["reason_code"])
