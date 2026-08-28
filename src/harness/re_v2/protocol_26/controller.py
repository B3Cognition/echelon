"""Protocol-2.6 retry-authority bridge over the frozen layer controllers."""

from __future__ import annotations

from harness.re_v2.protocol_22.budget import evaluate_budget_v22
from harness.re_v2.protocol_22.controller import Protocol22Controller, _fault
from harness.re_v2.protocol_22.ledger import WorkItemFailureReceiptV1
from harness.re_v2.protocol_24.controller import Protocol24Controller
from harness.re_v2.protocol_25.controller import Protocol25Controller

from .authority import resolve_run_authority


class _Protocol26RetryAuthorityMixin:
    """Resolve retry limits from the embedded layer manifest only for schema 5."""

    def _retry_or_fail_work_item(
        self,
        item: object,
        committed: object,
        *,
        candidate_id: str | None,
        candidate_assessment_id: str | None,
        failure_class: str,
        reason_code: str,
        diagnostics: tuple[str, ...],
    ) -> None:
        events = self.context.event_store.replay()
        manifest = resolve_run_authority(self.context).layer_manifest
        budget = evaluate_budget_v22(
            manifest.initial_budget_policy,
            events,
            (),
            self.context.clock(),
            event_protocol=self.context.event_store.protocol,
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


class Protocol26L1Controller(_Protocol26RetryAuthorityMixin, Protocol22Controller):
    """Protocol-2.2 behavior with schema-5 retry authority resolution."""


class Protocol26L2Controller(_Protocol26RetryAuthorityMixin, Protocol24Controller):
    """Protocol-2.4 behavior with schema-5 retry authority resolution."""


class Protocol26L3Controller(_Protocol26RetryAuthorityMixin, Protocol25Controller):
    """Protocol-2.5 behavior with schema-5 retry authority resolution."""


__all__ = (
    "Protocol26L1Controller",
    "Protocol26L2Controller",
    "Protocol26L3Controller",
)
