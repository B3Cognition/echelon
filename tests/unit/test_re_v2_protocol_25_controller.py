from __future__ import annotations

from types import SimpleNamespace

import pytest

from harness.re_v2.protocol_25 import controller as semantic_controller
from harness.re_v2.protocol_25.controller import Protocol25Controller
from harness.re_v2.protocol_25.events import PROTOCOL_25_EVENTS


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
    monkeypatch.setattr(
        semantic_controller,
        "load_run_manifest",
        lambda _root: SimpleNamespace(initial_budget_policy="budget-policy"),
    )
    controller = object.__new__(Protocol25Controller)
    controller.context = SimpleNamespace(  # type: ignore[assignment]
        event_store=SimpleNamespace(replay=lambda: events),
        paths=SimpleNamespace(root=SimpleNamespace(parent="run-root")),
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
        "event_protocol": PROTOCOL_25_EVENTS,
    }
