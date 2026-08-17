from __future__ import annotations

from dataclasses import replace

import pytest

from harness.re_v2.budget import (
    MAX_ACCOUNTING_VALUE,
    BudgetDimension,
    ReV2BudgetError,
    authorize_resource_increase,
    evaluate_budget,
)
from harness.re_v2.events import EventRecord, EventStore, ReV2EventError, validate_event_history
from harness.re_v2.model import BudgetPolicy


NOW = "2026-08-14T12:00:00Z"
LATER = "2026-08-14T12:00:05Z"
WORK = "sha256:" + "a" * 64
RUN = "sha256:" + "b" * 64


def policy(*, token_limit: int | None = 10_000) -> BudgetPolicy:
    return BudgetPolicy(
        token_limit=token_limit,
        active_ms_limit=1_000,
        provider_attempt_limit=3,
        artifact_generation_attempt_limit=3,
        semantic_repair_round_limit=1,
        result_contract_retry_limit=1,
    )


def observation(
    *, token_usage: int | None = 10, result_contract_valid: bool = True, duration_ms: int = 100
) -> dict[str, object]:
    return {
        "duration_ms": duration_ms,
        "ended_at": NOW,
        "exit_code": 0,
        "model_name": "fixture-model",
        "output_truncated": False,
        "provider_name": "fixture",
        "result_contract_valid": result_contract_valid,
        "started_at": NOW,
        "stderr_digest": None,
        "timed_out": False,
        "token_usage": token_usage,
    }


def store_with_run(tmp_path) -> EventStore:
    store = EventStore(tmp_path / "events.jsonl")
    store.append("run_created", {"run_manifest_id": RUN}, occurred_at=NOW)
    return store


def start(
    store: EventStore, *, dispatch_id: str, kind: str, index: int, occurred_at: str = NOW
) -> None:
    store.append(
        "dispatch_leased", {"dispatch_id": dispatch_id, "work_item_id": WORK}, occurred_at=occurred_at
    )
    store.append(
        "dispatch_started",
        {
            "attempt_index": index,
            "attempt_kind": kind,
            "dispatch_id": dispatch_id,
            "work_item_id": WORK,
        },
        occurred_at=occurred_at,
    )


def observe_and_reject(
    store: EventStore,
    *,
    dispatch_id: str,
    candidate_id: str,
    observation_value: dict[str, object],
) -> None:
    store.append(
        "dispatch_observed",
        {"dispatch_id": dispatch_id, "observation": observation_value, "work_item_id": WORK},
        occurred_at=NOW,
    )
    store.append(
        "candidate_persisted",
        {"candidate_id": candidate_id, "dispatch_id": dispatch_id, "work_item_id": WORK},
        occurred_at=NOW,
    )
    store.append(
        "candidate_rejected",
        {
            "candidate_id": candidate_id,
            "certification_id": "sha256:" + candidate_id[-1] * 64,
            "reason": "candidate rejected",
            "work_item_id": WORK,
        },
        occurred_at=NOW,
    )


def test_token_increase_does_not_raise_attempt_limits(tmp_path) -> None:
    before = evaluate_budget(policy(), store_with_run(tmp_path).replay(), now=NOW)
    after_path = tmp_path / "after"
    after_path.mkdir()
    store = store_with_run(after_path)
    store.append("run_paused", {"reason": "tokens exhausted", "reason_code": "tokens_exhausted"}, occurred_at=NOW)
    authorization = authorize_resource_increase(
        policy(), store.replay(), dimension=BudgetDimension.TOKENS, old_value=10_000,
        new_value=20_000, actor="operator", reason="continue pinned run",
    )
    store.append(authorization["type"], authorization["payload"], occurred_at=NOW)
    after = evaluate_budget(policy(), store.replay(), now=NOW)

    assert after.token_limit == 20_000
    assert after.provider_attempt_limit == before.provider_attempt_limit
    assert after.semantic_round_limit == before.semantic_round_limit


def test_unknown_usage_is_not_reported_as_exact_zero(tmp_path) -> None:
    store = store_with_run(tmp_path)
    start(store, dispatch_id="dispatch-1", kind="initial_generation", index=1)
    observe_and_reject(store, dispatch_id="dispatch-1", candidate_id="candidate-1", observation_value=observation(token_usage=None))

    decision = evaluate_budget(policy(), store.replay(), now=NOW)

    assert decision.known_tokens == 0
    assert decision.unknown_token_dispatches == 1
    assert decision.token_coverage_complete is False


def test_attempt_kinds_charge_only_their_durable_dispatch_starts(tmp_path) -> None:
    store = store_with_run(tmp_path)
    start(store, dispatch_id="dispatch-1", kind="initial_generation", index=1)
    observe_and_reject(store, dispatch_id="dispatch-1", candidate_id="candidate-1", observation_value=observation())
    start(store, dispatch_id="dispatch-2", kind="semantic_repair", index=1)
    observe_and_reject(store, dispatch_id="dispatch-2", candidate_id="candidate-2", observation_value=observation(result_contract_valid=False))
    start(store, dispatch_id="dispatch-3", kind="result_contract_retry", index=1)
    store.append("dispatch_observed", {"dispatch_id": "dispatch-3", "observation": observation(token_usage=19), "work_item_id": WORK}, occurred_at=NOW)

    decision = evaluate_budget(policy(), store.replay(), now=NOW)

    assert decision.known_tokens == 39
    assert decision.active_ms == 300
    assert decision.provider_attempts == {WORK: 3}
    assert decision.generation_attempts == {WORK: 2}
    assert decision.semantic_rounds == {WORK: 1}
    assert decision.result_contract_retries == {WORK: 1}


def test_initial_rejection_does_not_charge_semantic_until_semantic_retry_starts(tmp_path) -> None:
    store = store_with_run(tmp_path)
    start(store, dispatch_id="dispatch-1", kind="initial_generation", index=1)
    observe_and_reject(store, dispatch_id="dispatch-1", candidate_id="candidate-1", observation_value=observation())

    assert evaluate_budget(policy(), store.replay(), now=NOW).semantic_rounds == {}

    start(store, dispatch_id="dispatch-2", kind="semantic_repair", index=1)
    assert evaluate_budget(policy(), store.replay(), now=NOW).semantic_rounds == {WORK: 1}


def test_invalid_initial_contract_does_not_charge_retry_until_retry_dispatch_starts(tmp_path) -> None:
    store = store_with_run(tmp_path)
    start(store, dispatch_id="dispatch-1", kind="initial_generation", index=1)
    observe_and_reject(store, dispatch_id="dispatch-1", candidate_id="candidate-1", observation_value=observation(result_contract_valid=False))

    assert evaluate_budget(policy(), store.replay(), now=NOW).result_contract_retries == {}

    start(store, dispatch_id="dispatch-2", kind="result_contract_retry", index=1)
    assert evaluate_budget(policy(), store.replay(), now=NOW).result_contract_retries == {WORK: 1}


def test_resource_exhaustion_is_a_continuable_pause_with_exact_dimension(tmp_path) -> None:
    store = store_with_run(tmp_path)
    start(store, dispatch_id="dispatch-1", kind="initial_generation", index=1)
    observe_and_reject(store, dispatch_id="dispatch-1", candidate_id="candidate-1", observation_value=observation(token_usage=10_000))

    decision = evaluate_budget(policy(), store.replay(), now=NOW)

    assert decision.exhausted_dimensions == ("tokens",)
    assert decision.pause_required is True
    assert decision.continuable is True


def test_semantic_exhaustion_is_not_cleared_by_resource_authorization(tmp_path) -> None:
    store = store_with_run(tmp_path)
    start(store, dispatch_id="dispatch-1", kind="initial_generation", index=1)
    observe_and_reject(store, dispatch_id="dispatch-1", candidate_id="candidate-1", observation_value=observation())
    start(store, dispatch_id="dispatch-2", kind="semantic_repair", index=1)
    observe_and_reject(store, dispatch_id="dispatch-2", candidate_id="candidate-2", observation_value=observation())
    store.append("run_paused", {"reason": "semantic exhausted", "reason_code": "semantic_exhausted"}, occurred_at=NOW)
    authorization = authorize_resource_increase(policy(), store.replay(), dimension="tokens", old_value=10_000, new_value=20_000, actor="operator", reason="resource-only change")
    store.append(authorization["type"], authorization["payload"], occurred_at=NOW)

    decision = evaluate_budget(policy(), store.replay(), now=NOW)
    assert decision.exhausted_dimensions == (f"semantic_rounds:{WORK}",)
    assert decision.continuable is False


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"dimension": "provider_attempts"}, "only tokens or active_ms"),
        ({"dimension": "tokens", "old_value": 9_999}, "old_value"),
        ({"dimension": "tokens", "new_value": 10_000}, "increase"),
        ({"dimension": "tokens", "actor": ""}, "actor"),
        ({"dimension": "tokens", "actor": ".operator"}, "actor"),
        ({"dimension": "tokens", "reason": ""}, "reason"),
    ],
)
def test_resource_authorization_rejects_non_resource_or_non_increase_facts(tmp_path, kwargs: dict[str, object], message: str) -> None:
    values: dict[str, object] = {"dimension": "tokens", "old_value": 10_000, "new_value": 20_000, "actor": "operator", "reason": "continue pinned run"}
    values.update(kwargs)
    with pytest.raises(ReV2BudgetError, match=message):
        authorize_resource_increase(policy(), store_with_run(tmp_path).replay(), **values)  # type: ignore[arg-type]


def test_unlimited_resource_limit_cannot_be_replaced_by_a_finite_authorization(tmp_path) -> None:
    with pytest.raises(ReV2BudgetError, match="unlimited"):
        authorize_resource_increase(policy(token_limit=None), store_with_run(tmp_path).replay(), dimension="tokens", old_value=None, new_value=20_000, actor="operator", reason="not an increase")


def test_history_validator_rejects_forged_or_duplicate_facts_before_budget_charge(tmp_path) -> None:
    store = store_with_run(tmp_path)
    start(store, dispatch_id="dispatch-1", kind="initial_generation", index=1)
    history = store.replay()
    forged: EventRecord = replace(history[-1], event_hash="sha256:" + "0" * 64)

    with pytest.raises(ReV2EventError, match="event hash"):
        validate_event_history((*history[:-1], forged))
    with pytest.raises(ReV2BudgetError, match="validated EventRecord history"):
        evaluate_budget(policy(), [history[0], history[-1], history[-1]], now=NOW)


def test_open_provider_time_is_counted_once_until_observation(tmp_path) -> None:
    store = store_with_run(tmp_path)
    start(store, dispatch_id="dispatch-1", kind="initial_generation", index=1)

    assert evaluate_budget(policy(), store.replay(), now=LATER).active_ms == 5_000
    with pytest.raises(ReV2BudgetError, match="before dispatch_started"):
        evaluate_budget(policy(), store.replay(), now="2026-08-14T11:59:59Z")
    store.append("dispatch_observed", {"dispatch_id": "dispatch-1", "observation": observation(duration_ms=123), "work_item_id": WORK}, occurred_at=LATER)
    assert evaluate_budget(policy(), store.replay(), now=LATER).active_ms == 123
    with pytest.raises(ReV2BudgetError, match="before dispatch_started"):
        evaluate_budget(policy(), store.replay(), now="2026-08-14T11:59:59Z")


def test_budget_accepts_valid_offset_event_timestamps(tmp_path) -> None:
    store = store_with_run(tmp_path)
    start(
        store,
        dispatch_id="dispatch-1",
        kind="initial_generation",
        index=1,
        occurred_at="2026-08-14T14:00:00+02:00",
    )

    assert evaluate_budget(policy(), store.replay(), now=NOW).active_ms == 0


def test_malformed_or_overflowing_observations_fail_closed(tmp_path) -> None:
    store = store_with_run(tmp_path)
    start(store, dispatch_id="dispatch-1", kind="initial_generation", index=1)
    with pytest.raises(ReV2EventError, match="observation"):
        store.append("dispatch_observed", {"dispatch_id": "dispatch-1", "observation": observation(token_usage=-1), "work_item_id": WORK}, occurred_at=NOW)
    store.append("dispatch_observed", {"dispatch_id": "dispatch-1", "observation": observation(token_usage=MAX_ACCOUNTING_VALUE + 1), "work_item_id": WORK}, occurred_at=NOW)
    with pytest.raises(ReV2BudgetError, match="64-bit"):
        evaluate_budget(policy(), store.replay(), now=NOW)
