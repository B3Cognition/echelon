from __future__ import annotations

from pathlib import Path

import pytest

from harness.re_v2.protocol_22.budget import (
    ReV2BudgetV22Error,
    conservative_charge,
    evaluate_budget_v22,
)
from harness.re_v2.protocol_22.model import BudgetPolicyV2
from tests.re_v2_protocol_22_fixtures import digest
from tests.unit.test_re_v2_protocol_22_context import (
    _domain_baseline_bytes,
    _domain_fixture,
)
from tests.unit.test_re_v2_protocol_22_events import (
    NOW,
    WORK,
    _observe,
    _persist,
    _run,
    _start,
    event_store_v22,
)


def _policy(
    *,
    token_limit: int | None = 10_000,
    active_ms_limit: int | None = 10_000,
) -> BudgetPolicyV2:
    return BudgetPolicyV2.for_goal(
        "baseline",
        token_limit=token_limit,
        active_ms_limit=active_ms_limit,
    )


def _reject(store, candidate: str, *, certification: bool = True) -> None:
    candidate_id = _persist(store, "d1", candidate)
    store.append(
        "candidate_rejected",
        {
            "candidate_assessment_id": digest(f"assessment:{candidate}"),
            "candidate_id": candidate_id,
            "certification_receipt_id": (
                digest(f"certification:{candidate}") if certification else None
            ),
            "work_item_id": WORK,
        },
        occurred_at=NOW,
    )


@pytest.mark.unit
def test_open_dispatch_charges_both_full_reservations(tmp_path: Path) -> None:
    store = event_store_v22(tmp_path)
    _run(store)
    _start(store, "d1", token_reservation=400, active_reservation=2_000)

    decision = evaluate_budget_v22(
        _policy(),
        store.replay(),
        {"d1"},
        NOW,
    )

    assert decision.charged_tokens == 400
    assert decision.charged_active_ms == 2_000
    assert decision.open_token_reservations == 400
    assert decision.open_active_ms_reservations == 2_000
    assert decision.unknown_token_dispatches == 1
    assert decision.unknown_active_dispatches == 1


@pytest.mark.unit
def test_trusted_observation_releases_unused_reservation(tmp_path: Path) -> None:
    store = event_store_v22(tmp_path)
    _run(store)
    _start(store, "d1", token_reservation=400, active_reservation=2_000)
    _observe(store, "d1", token_usage=25, active_ms=250)

    decision = evaluate_budget_v22(_policy(), store.replay(), (), NOW)

    assert decision.charged_tokens == 25
    assert decision.charged_active_ms == 250
    assert decision.trusted_observed_tokens == 25
    assert decision.trusted_observed_active_ms == 250
    assert decision.open_token_reservations == 0
    assert decision.unknown_token_dispatches == 0


@pytest.mark.unit
def test_unavailable_and_untrusted_usage_never_charge_unknown_as_zero(
    tmp_path: Path,
) -> None:
    unavailable = event_store_v22(tmp_path / "unavailable")
    unavailable.path.parent.mkdir()
    _run(unavailable)
    _start(unavailable, "d1", token_reservation=400, active_reservation=2_000)
    _observe(
        unavailable,
        "d1",
        token_usage=None,
        token_status="unavailable",
        active_ms=None,
        active_status="unavailable",
    )
    missing = evaluate_budget_v22(_policy(), unavailable.replay(), (), NOW)

    untrusted = event_store_v22(tmp_path / "untrusted")
    untrusted.path.parent.mkdir()
    _run(untrusted)
    _start(untrusted, "d2", token_reservation=400, active_reservation=2_000)
    _observe(
        untrusted,
        "d2",
        token_usage=550,
        token_status="untrusted",
        active_ms=2_500,
        active_status="untrusted",
    )
    suspect = evaluate_budget_v22(_policy(), untrusted.replay(), (), NOW)

    assert (missing.charged_tokens, missing.charged_active_ms) == (400, 2_000)
    assert (missing.unknown_token_dispatches, missing.unknown_active_dispatches) == (
        1,
        1,
    )
    assert (suspect.charged_tokens, suspect.charged_active_ms) == (550, 2_500)
    assert suspect.reservation_breaches == ()
    assert suspect.allowed is True


@pytest.mark.unit
def test_abandoned_dispatch_permanently_charges_reservations(tmp_path: Path) -> None:
    store = event_store_v22(tmp_path)
    _run(store)
    _start(store, "d1", token_reservation=400, active_reservation=2_000)
    store.append(
        "dispatch_abandoned",
        {
            "dispatch_id": "d1",
            "execution_input_hash": digest("input:d1"),
            "executor_contract_hash": digest("executor"),
            "reason_code": "execution_outcome_indeterminate",
            "work_item_id": WORK,
        },
        occurred_at=NOW,
    )

    decision = evaluate_budget_v22(_policy(), store.replay(), (), NOW)

    assert (decision.charged_tokens, decision.charged_active_ms) == (400, 2_000)
    assert decision.abandoned_dispatches == ("d1",)
    assert decision.open_token_reservations == 0


@pytest.mark.unit
@pytest.mark.parametrize(
    ("retry_kind", "counter"),
    (
        ("result_contract_retry", "result_contract_retries"),
        ("artifact_contract_retry", "artifact_contract_retries"),
    ),
)
def test_provider_retry_charges_generation_shared_and_specific_counter(
    tmp_path: Path,
    retry_kind: str,
    counter: str,
) -> None:
    store = event_store_v22(tmp_path)
    _run(store)
    _start(store, "d1")
    if retry_kind == "result_contract_retry":
        _observe(store, "d1", raw_status="invalid")
    else:
        _observe(store, "d1")
        _reject(store, "bad")
    _start(store, "d2", kind=retry_kind)

    decision = evaluate_budget_v22(_policy(), store.replay(), {"d2"}, NOW)

    assert decision.provider_attempts == {WORK: 2}
    assert decision.generation_attempts == {WORK: 2}
    assert decision.shared_retries == {WORK: 1}
    assert getattr(decision, counter) == {WORK: 1}
    assert decision.semantic_rounds == {}


@pytest.mark.unit
def test_deterministic_execution_charges_generation_but_not_provider(
    tmp_path: Path,
) -> None:
    store = event_store_v22(tmp_path)
    _run(store)
    _start(store, "d1", token_reservation=0)

    decision = evaluate_budget_v22(_policy(), store.replay(), {"d1"}, NOW)

    assert decision.provider_attempts == {}
    assert decision.generation_attempts == {WORK: 1}
    assert decision.charged_tokens == 0


@pytest.mark.unit
def test_budget_decision_implements_per_item_planning_contract(tmp_path: Path) -> None:
    fixture = _domain_fixture()
    item, _artifact = _domain_baseline_bytes(fixture, {})
    store = event_store_v22(tmp_path)
    _run(store)

    available = evaluate_budget_v22(_policy(), store.replay(), (), NOW)
    assert available.item_attempt_available(item) is True

    _start(store, "d1", work_item_id=item.work_item_id)
    _observe(store, "d1", work_item_id=item.work_item_id, raw_status="invalid")
    _start(
        store,
        "d2",
        work_item_id=item.work_item_id,
        kind="result_contract_retry",
    )
    exhausted = evaluate_budget_v22(_policy(), store.replay(), {"d2"}, NOW)
    assert exhausted.item_attempt_available(item) is False


@pytest.mark.unit
def test_exhausted_item_does_not_block_an_independent_sibling(tmp_path: Path) -> None:
    first_fixture = _domain_fixture("orders")
    first, _artifact = _domain_baseline_bytes(first_fixture, {})
    sibling_fixture = _domain_fixture("users")
    sibling, _artifact = _domain_baseline_bytes(sibling_fixture, {})
    store = event_store_v22(tmp_path)
    _run(store)
    _start(store, "d1", work_item_id=first.work_item_id)
    _observe(store, "d1", work_item_id=first.work_item_id, raw_status="invalid")
    _start(
        store,
        "d2",
        work_item_id=first.work_item_id,
        kind="result_contract_retry",
    )

    decision = evaluate_budget_v22(_policy(), store.replay(), {"d2"}, NOW)

    assert decision.item_attempt_available(first) is False
    assert decision.item_attempt_available(sibling) is True
    assert decision.allowed is True


@pytest.mark.unit
def test_budget_authorization_changes_only_resource_limit(tmp_path: Path) -> None:
    store = event_store_v22(tmp_path)
    _run(store)
    store.append(
        "run_paused",
        {"reason": "tokens exhausted", "reason_code": "tokens_exhausted"},
        occurred_at=NOW,
    )
    store.append(
        "budget_authorized",
        {
            "authorized_by": "operator",
            "dimension": "tokens",
            "new_value": 20_000,
            "old_value": 10_000,
            "reason": "continue immutable run",
        },
        occurred_at=NOW,
    )

    decision = evaluate_budget_v22(_policy(), store.replay(), (), NOW)

    assert decision.token_limit == 20_000
    assert decision.provider_attempt_limit == 2
    assert decision.shared_retry_limit == 1


@pytest.mark.unit
def test_budget_rejects_open_set_or_time_that_disagrees_with_history(
    tmp_path: Path,
) -> None:
    store = event_store_v22(tmp_path)
    _run(store)
    _start(store, "d1")

    with pytest.raises(ReV2BudgetV22Error, match="open dispatch"):
        evaluate_budget_v22(_policy(), store.replay(), (), NOW)
    with pytest.raises(ReV2BudgetV22Error, match="before event"):
        evaluate_budget_v22(
            _policy(),
            store.replay(),
            {"d1"},
            "2026-08-22T09:59:59Z",
        )


@pytest.mark.unit
@pytest.mark.parametrize(
    ("value", "status", "reservation", "expected"),
    (
        (3, "trusted_exact", 10, 3),
        (None, "unavailable", 10, 10),
        (3, "untrusted", 10, 10),
        (30, "untrusted", 10, 30),
        (None, "untrusted", 10, 10),
    ),
)
def test_conservative_charge_is_exact_integer_accounting(
    value: int | None,
    status: str,
    reservation: int,
    expected: int,
) -> None:
    assert conservative_charge(value, status, reservation) == expected
