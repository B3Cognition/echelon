from __future__ import annotations

from types import SimpleNamespace

import pytest

from harness.re_v2.protocol_25 import controller as semantic_controller
from harness.re_v2.protocol_25.controller import (
    Protocol25Controller,
    _semantic_authorial_rejection_diagnostics,
)


@pytest.mark.unit
def test_semantic_authorial_rejection_preserves_actionable_retry_diagnostic() -> None:
    diagnostics = _semantic_authorial_rejection_diagnostics(
        RuntimeError(
            "finding subject_kind does not match the controller-issued subject_ref"
        )
    )

    assert diagnostics == (
        "authorial_schema_invalid",
        "finding_subject_kind_must_match_controller_issued_subject_ref",
    )


@pytest.mark.unit
def test_semantic_retry_accounting_uses_protocol_25_event_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events = ("audit_candidate_accepted",)
    observed: dict[str, object] = {}

    def evaluate(policy, history, open_dispatches, now, *, event_protocol):  # type: ignore[no-untyped-def]
        observed.update(
            policy=policy,
            history=history,
            open_dispatches=open_dispatches,
            now=now,
            event_protocol=event_protocol,
        )
        return SimpleNamespace(item_attempt_available=lambda _item: True)

    monkeypatch.setattr(semantic_controller, "evaluate_budget_v22", evaluate)
    controller = object.__new__(Protocol25Controller)
    outer_event_protocol = object()
    controller.context = SimpleNamespace(  # type: ignore[assignment]
        event_store=SimpleNamespace(
            replay=lambda: events,
            protocol=outer_event_protocol,
        ),
        semantic_graph=SimpleNamespace(
            manifest=SimpleNamespace(initial_budget_policy="budget-policy")
        ),
        clock=lambda: "2026-08-26T20:00:00Z",
    )
    controller.fault_hook = None

    controller._retry_or_fail_work_item(  # type: ignore[arg-type]
        object(),
        object(),
        candidate_id="candidate",
        candidate_assessment_id="assessment",
        failure_class="artifact_contract",
        reason_code="candidate_tree_invalid",
        diagnostics=("candidate_tree_invalid",),
    )

    assert observed == {
        "policy": "budget-policy",
        "history": events,
        "open_dispatches": (),
        "now": "2026-08-26T20:00:00Z",
        "event_protocol": outer_event_protocol,
    }
