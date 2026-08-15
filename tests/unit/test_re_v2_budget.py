from __future__ import annotations

import pytest

from harness.re_v2.budget import (
    MAX_ACCOUNTING_VALUE,
    BudgetDimension,
    ReV2BudgetError,
    authorize_resource_increase,
    evaluate_budget,
)
from harness.re_v2.events import EventStore
from harness.re_v2.model import BudgetPolicy


NOW = "2026-08-14T12:00:00Z"
WORK = "sha256:" + "a" * 64
RUN = "sha256:" + "b" * 64


def policy() -> BudgetPolicy:
    return BudgetPolicy(
        token_limit=10_000,
        active_ms_limit=1_000,
        provider_attempt_limit=2,
        artifact_generation_attempt_limit=3,
        semantic_repair_round_limit=1,
        result_contract_retry_limit=1,
    )


def observation(*, token_usage: int | None = 10, result_contract_valid: bool = True) -> dict[str, object]:
    return {
        "duration_ms": 100,
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


def fact(event_type: str, payload: dict[str, object]) -> dict[str, object]:
    return {"type": event_type, "payload": payload}


def dispatch_started() -> dict[str, object]:
    return fact("dispatch_started", {"dispatch_id": "dispatch-1", "work_item_id": WORK})


def dispatch_observed(
    *, token_usage: int | None = 10, result_contract_valid: bool = True
) -> dict[str, object]:
    return fact(
        "dispatch_observed",
        {
            "dispatch_id": "dispatch-1",
            "observation": observation(
                token_usage=token_usage, result_contract_valid=result_contract_valid
            ),
            "work_item_id": WORK,
        },
    )


def events_with_attempts(*, provider: int, semantic: int) -> list[dict[str, object]]:
    return [
        *(dispatch_started() for _ in range(provider)),
        *(
            fact(
                "candidate_rejected",
                {
                    "candidate_id": f"candidate-{index}",
                    "certification_id": "sha256:" + f"{index:x}".zfill(64),
                    "reason": "semantic finding remains open",
                    "work_item_id": WORK,
                },
            )
            for index in range(semantic)
        ),
    ]


def test_token_increase_does_not_raise_attempt_limits() -> None:
    before = evaluate_budget(policy(), events_with_attempts(provider=2, semantic=1), now=NOW)
    authorization = authorize_resource_increase(
        policy(),
        dimension=BudgetDimension.TOKENS,
        old_value=10_000,
        new_value=20_000,
        actor="operator",
        reason="continue pinned run",
    )
    after = evaluate_budget(policy(), [authorization], now=NOW)

    assert after.token_limit == 20_000
    assert after.provider_attempt_limit == before.provider_attempt_limit
    assert after.semantic_round_limit == before.semantic_round_limit


def test_unknown_usage_is_not_reported_as_exact_zero() -> None:
    decision = evaluate_budget(policy(), [dispatch_observed(token_usage=None)], now=NOW)

    assert decision.known_tokens == 0
    assert decision.unknown_token_dispatches == 1
    assert decision.token_coverage_complete is False


def test_each_budget_dimension_is_counted_only_from_its_authoritative_fact() -> None:
    decision = evaluate_budget(
        policy(),
        [
            dispatch_started(),
            fact(
                "candidate_persisted",
                {"candidate_id": "candidate-1", "dispatch_id": "dispatch-1", "work_item_id": WORK},
            ),
            fact(
                "candidate_rejected",
                {
                    "candidate_id": "candidate-1",
                    "certification_id": "sha256:" + "c" * 64,
                    "reason": "semantic finding remains open",
                    "work_item_id": WORK,
                },
            ),
            dispatch_observed(token_usage=19, result_contract_valid=False),
        ],
        now=NOW,
    )

    assert decision.known_tokens == 19
    assert decision.active_ms == 100
    assert decision.provider_attempts == {WORK: 1}
    assert decision.generation_attempts == {WORK: 1}
    assert decision.semantic_rounds == {WORK: 1}
    assert decision.result_contract_retries == {WORK: 1}


def test_resource_exhaustion_is_a_continuable_pause_with_exact_dimension() -> None:
    decision = evaluate_budget(policy(), [dispatch_observed(token_usage=10_000)], now=NOW)

    assert decision.exhausted_dimensions == ("tokens",)
    assert decision.pause_required is True
    assert decision.continuable is True


def test_semantic_exhaustion_is_not_cleared_by_resource_authorization() -> None:
    exhausted = evaluate_budget(policy(), events_with_attempts(provider=0, semantic=1), now=NOW)
    authorization = authorize_resource_increase(
        policy(),
        dimension="tokens",
        old_value=10_000,
        new_value=20_000,
        actor="operator",
        reason="more tokens cannot alter semantic policy",
    )
    after = evaluate_budget(
        policy(), events_with_attempts(provider=0, semantic=1) + [authorization], now=NOW
    )

    assert exhausted.exhausted_dimensions == (f"semantic_rounds:{WORK}",)
    assert after.exhausted_dimensions == (f"semantic_rounds:{WORK}",)
    assert after.continuable is False


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"dimension": "provider_attempts"}, "only tokens or active_ms"),
        ({"dimension": "tokens", "old_value": 9_999}, "old_value"),
        ({"dimension": "tokens", "new_value": 10_000}, "increase"),
        ({"dimension": "tokens", "actor": ""}, "actor"),
        ({"dimension": "tokens", "reason": ""}, "reason"),
    ],
)
def test_resource_authorization_rejects_non_resource_or_non_increase_facts(
    kwargs: dict[str, object], message: str
) -> None:
    values: dict[str, object] = {
        "dimension": "tokens",
        "old_value": 10_000,
        "new_value": 20_000,
        "actor": "operator",
        "reason": "continue pinned run",
    }
    values.update(kwargs)

    with pytest.raises(ReV2BudgetError, match=message):
        authorize_resource_increase(policy(), **values)  # type: ignore[arg-type]


def test_authorization_fact_is_accepted_by_the_event_store(tmp_path) -> None:
    store = EventStore(tmp_path / "events.jsonl")
    store.append("run_created", {"run_manifest_id": RUN}, occurred_at=NOW)
    store.append(
        "run_paused",
        {"reason": "token ceiling exhausted", "reason_code": "tokens_exhausted"},
        occurred_at=NOW,
    )
    authorization = authorize_resource_increase(
        policy(),
        dimension="tokens",
        old_value=10_000,
        new_value=20_000,
        actor="operator",
        reason="continue pinned run",
    )

    event = store.append(authorization["type"], authorization["payload"], occurred_at=NOW)

    assert event.type == "budget_authorized"
    assert event.payload == {
        "authorized_by": "operator",
        "dimension": "tokens",
        "new_value": 20_000,
        "old_value": 10_000,
        "reason": "continue pinned run",
    }


def test_malformed_or_overflowing_observations_fail_closed() -> None:
    negative = dispatch_observed()
    negative["payload"] = dict(negative["payload"])
    negative["payload"]["observation"] = observation(token_usage=-1)

    with pytest.raises(ReV2BudgetError, match="observation"):
        evaluate_budget(policy(), [negative], now=NOW)
    with pytest.raises(ReV2BudgetError, match="64-bit"):
        evaluate_budget(
            policy(), [dispatch_observed(token_usage=MAX_ACCOUNTING_VALUE + 1)], now=NOW
        )
