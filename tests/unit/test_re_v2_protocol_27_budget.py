from __future__ import annotations

from pathlib import Path

import pytest

from harness.re_v2.events import EventStore
from tests.re_v2_protocol_27_fixtures import digest
from tests.unit.test_re_v2_protocol_27_events import (
    NOW,
    _planned_source,
    append_dispatch_cycle,
)


def _abandon(store: EventStore, item, dispatch_id: str, index: int) -> None:
    store.append(
        "dispatch_abandoned",
        {
            "dispatch_id": dispatch_id,
            "execution_input_hash": digest(f"execution-{index}"),
            "executor_contract_hash": item.executor_contract_hash,
            "reason_code": "execution_outcome_indeterminate",
            "work_item_id": item.work_item_id,
        },
        occurred_at=NOW,
    )


@pytest.mark.unit
def test_adopted_artifact_consumes_no_synthesis_budget(tmp_path: Path) -> None:
    from harness.re_v2.protocol_27.budget import evaluate_synthesis_budget
    from harness.re_v2.protocol_27.ledger import Protocol27Ledger

    inputs, item, store = _planned_source(tmp_path)
    store.append(
        "checkpoint_adopted",
        {
            "acceptance_receipt_id": digest("acceptance"),
            "adoption_receipt_id": digest("adoption"),
            "artifact_hash": digest("artifact"),
            "artifact_key_id": item.output_key.artifact_key_id,
            "certification_id": digest("certification"),
            "work_item_id": item.work_item_id,
        },
        occurred_at=NOW,
    )

    decision = evaluate_synthesis_budget(
        inputs.manifest,
        store.replay(),
        Protocol27Ledger(inputs).replay(),
    )

    assert decision.known_tokens == 0
    assert decision.charged_tokens == 0
    assert decision.provider_attempts == 0


@pytest.mark.unit
def test_contract_retry_cannot_stack_into_third_dispatch(tmp_path: Path) -> None:
    from harness.re_v2.protocol_27.budget import (
        Protocol27BudgetError,
        evaluate_synthesis_budget,
    )
    from harness.re_v2.protocol_27.ledger import Protocol27Ledger

    inputs, item, store = _planned_source(tmp_path)
    for index, kind in (
        (1, "initial_generation"),
        (2, "result_contract_retry"),
        (3, "artifact_contract_retry"),
    ):
        dispatch_id = append_dispatch_cycle(store, item, index, kind)
        _abandon(store, item, dispatch_id, index)

    with pytest.raises(Protocol27BudgetError, match="provider attempt limit"):
        evaluate_synthesis_budget(
            inputs.manifest,
            store.replay(),
            Protocol27Ledger(inputs).replay(),
        )


@pytest.mark.unit
def test_trusted_usage_charges_observed_values(
    tmp_path: Path,
) -> None:
    from harness.re_v2.protocol_27.budget import evaluate_synthesis_budget
    from harness.re_v2.protocol_27.ledger import Protocol27Ledger

    inputs, item, store = _planned_source(tmp_path)
    dispatch_id = append_dispatch_cycle(store, item, 1, "initial_generation")
    store.append(
        "dispatch_observed",
        {
            "active_usage_status": "trusted_exact",
            "dispatch_id": dispatch_id,
            "execution_capture_hash": digest("capture"),
            "observed_active_ms": 25,
            "raw_result_contract_status": "valid",
            "reported_token_usage": 400,
            "token_usage_status": "trusted_exact",
            "work_item_id": item.work_item_id,
        },
        occurred_at=NOW,
    )

    decision = evaluate_synthesis_budget(
        inputs.manifest,
        store.replay(),
        Protocol27Ledger(inputs).replay(),
    )

    assert decision.known_tokens == 400
    assert decision.charged_tokens == 400
    assert decision.charged_active_ms == 25


@pytest.mark.unit
def test_untrusted_or_unavailable_usage_charges_reservation(tmp_path: Path) -> None:
    from harness.re_v2.protocol_27.budget import evaluate_synthesis_budget
    from harness.re_v2.protocol_27.ledger import Protocol27Ledger

    inputs, item, store = _planned_source(tmp_path)
    dispatch_id = append_dispatch_cycle(store, item, 1, "initial_generation")
    store.append(
        "dispatch_observed",
        {
            "active_usage_status": "unavailable",
            "dispatch_id": dispatch_id,
            "execution_capture_hash": digest("capture-untrusted"),
            "observed_active_ms": None,
            "raw_result_contract_status": "invalid",
            "reported_token_usage": 400,
            "token_usage_status": "untrusted",
            "work_item_id": item.work_item_id,
        },
        occurred_at=NOW,
    )

    decision = evaluate_synthesis_budget(
        inputs.manifest,
        store.replay(),
        Protocol27Ledger(inputs).replay(),
    )

    assert decision.known_tokens == 0
    assert decision.charged_tokens == 1000
    assert decision.charged_active_ms == 100
    assert decision.unknown_token_dispatches == 1
    assert decision.unknown_active_dispatches == 1
