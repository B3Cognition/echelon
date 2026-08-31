from __future__ import annotations

import pytest

from harness.re_v2.protocol_22.provider import DispatchReservationV1
from harness.re_v2.protocol_28.budget import (
    L4ResourceLedger,
    Protocol28BudgetError,
)
from tests.re_v2_protocol_28_fixtures import digest, exhaustive_budget_policy_v1


def _reservation(tokens: int, active_ms: int = 1000) -> DispatchReservationV1:
    return DispatchReservationV1(max(1, tokens // 2), tokens, active_ms)


@pytest.mark.unit
def test_producer_cannot_reserve_without_retained_verifier_capacity() -> None:
    ledger = L4ResourceLedger(
        exhaustive_budget_policy_v1(token_limit=100, active_ms_limit=10_000)
    )
    preview = ledger.preview_pair(
        digest("slice"), 1, _reservation(70), _reservation(40)
    )

    assert preview.allowed is False
    assert preview.exhausted_dimensions == ("tokens",)
    with pytest.raises(Protocol28BudgetError, match="paired reservation"):
        ledger.commit_pair(
            preview,
            producer_dispatch_id="producer-1",
            verifier_dispatch_id="verifier-1",
        )
    assert ledger.records == ()


@pytest.mark.unit
def test_pair_commit_is_atomic_and_prefix_authenticated() -> None:
    ledger = L4ResourceLedger(
        exhaustive_budget_policy_v1(token_limit=200, active_ms_limit=10_000)
    )
    stale = ledger.preview_pair(
        digest("slice-a"), 1, _reservation(70), _reservation(40)
    )
    other = ledger.preview_pair(
        digest("slice-b"), 1, _reservation(20), _reservation(10)
    )
    ledger.commit_pair(
        other,
        producer_dispatch_id="producer-b",
        verifier_dispatch_id="verifier-b",
    )

    with pytest.raises(Protocol28BudgetError, match="ledger prefix"):
        ledger.commit_pair(
            stale,
            producer_dispatch_id="producer-a",
            verifier_dispatch_id="verifier-a",
        )
    assert len(ledger.records) == 1


@pytest.mark.unit
def test_unknown_usage_charges_conservative_reservation_by_role() -> None:
    ledger = L4ResourceLedger(
        exhaustive_budget_policy_v1(token_limit=200, active_ms_limit=10_000)
    )
    preview = ledger.preview_pair(
        digest("slice"), 1, _reservation(70, 2000), _reservation(40, 1000)
    )
    pair = ledger.commit_pair(
        preview,
        producer_dispatch_id="producer-1",
        verifier_dispatch_id="verifier-1",
    )
    ledger.observe(
        "producer-1",
        token_status="trusted_exact",
        billable_tokens=30,
        active_status="trusted_exact",
        active_ms=500,
    )
    ledger.observe(
        "verifier-1",
        token_status="unavailable",
        billable_tokens=None,
        active_status="untrusted",
        active_ms=700,
    )

    decision = ledger.decision
    assert decision.charged_tokens == 70
    assert decision.charged_active_ms == 1500
    assert decision.trusted_observed_tokens == 30
    assert decision.unknown_token_dispatches_by_role == {"producer": 0, "verifier": 1}
    assert decision.unknown_active_dispatches_by_role == {"producer": 0, "verifier": 1}
    assert decision.generated_dispatches_by_role == {"producer": 1, "verifier": 1}
    assert pair.slice_spec_id == digest("slice")


@pytest.mark.unit
def test_authorization_raise_changes_capacity_not_attempt_or_pair_identity() -> None:
    ledger = L4ResourceLedger(
        exhaustive_budget_policy_v1(token_limit=100, active_ms_limit=10_000)
    )
    before = ledger.preview_pair(
        digest("slice"), 3, _reservation(70), _reservation(40)
    )
    assert before.allowed is False

    ledger.authorize("tokens", 120)
    after = ledger.preview_pair(
        digest("slice"), 3, _reservation(70), _reservation(40)
    )

    assert after.allowed is True
    assert after.pair_work_id == before.pair_work_id
    assert ledger.decision.producer_attempt_limit == 3
    assert ledger.decision.verifier_contract_retry_limit == 1


@pytest.mark.unit
def test_adoption_records_avoided_dispatches_without_resource_charge() -> None:
    ledger = L4ResourceLedger(exhaustive_budget_policy_v1())
    ledger.record_adoption(
        digest("slice"),
        producer_reservation=_reservation(70, 2000),
        verifier_reservation=_reservation(40, 1000),
    )

    decision = ledger.decision
    assert decision.charged_tokens == 0
    assert decision.adopted_slices == 1
    assert decision.avoided_dispatches_by_role == {"producer": 1, "verifier": 1}
    assert decision.avoided_tokens == 110
    assert decision.avoided_active_ms == 3000


@pytest.mark.unit
def test_release_of_unused_verifier_retention_is_visible_not_charged() -> None:
    ledger = L4ResourceLedger(
        exhaustive_budget_policy_v1(token_limit=200, active_ms_limit=10_000)
    )
    pair = ledger.commit_pair(
        ledger.preview_pair(digest("slice"), 1, _reservation(70), _reservation(40)),
        producer_dispatch_id="producer-1",
        verifier_dispatch_id="verifier-1",
    )
    ledger.observe(
        "producer-1",
        token_status="trusted_exact",
        billable_tokens=30,
        active_status="trusted_exact",
        active_ms=500,
    )
    ledger.release_verifier(pair.identity, reason="producer_contract_failure")

    decision = ledger.decision
    assert decision.charged_tokens == 30
    assert decision.open_token_reservations == 0
    assert decision.avoided_dispatches_by_role == {"producer": 0, "verifier": 1}
    assert decision.avoided_tokens == 40
    assert decision.avoided_active_ms == 1000


@pytest.mark.unit
def test_verifier_contract_retry_reserves_only_verifier_capacity_once() -> None:
    ledger = L4ResourceLedger(
        exhaustive_budget_policy_v1(token_limit=200, active_ms_limit=10_000)
    )
    pair = ledger.commit_pair(
        ledger.preview_pair(digest("slice"), 1, _reservation(70), _reservation(40)),
        producer_dispatch_id="producer-1",
        verifier_dispatch_id="verifier-1",
    )
    for dispatch_id, tokens in ((pair.producer_dispatch_id, 30), (pair.verifier_dispatch_id, 20)):
        ledger.observe(
            dispatch_id,
            token_status="trusted_exact",
            billable_tokens=tokens,
            active_status="trusted_exact",
            active_ms=500,
        )

    preview = ledger.preview_verifier_retry(
        digest("slice"), 1, _reservation(40)
    )
    retry = ledger.commit_verifier_retry(preview, dispatch_id="verifier-1-retry")
    ledger.observe(
        retry.dispatch_id,
        token_status="unavailable",
        billable_tokens=None,
        active_status="unavailable",
        active_ms=None,
    )

    decision = ledger.decision
    assert decision.charged_tokens == 90
    assert decision.generated_dispatches_by_role == {"producer": 1, "verifier": 2}
    with pytest.raises(Protocol28BudgetError, match="already reserved"):
        ledger.preview_verifier_retry(digest("slice"), 1, _reservation(40))


@pytest.mark.unit
def test_untrusted_usage_above_reservation_is_conservative_not_a_fatal_breach() -> None:
    ledger = L4ResourceLedger(
        exhaustive_budget_policy_v1(token_limit=300, active_ms_limit=10_000)
    )
    ledger.commit_pair(
        ledger.preview_pair(digest("slice"), 1, _reservation(70), _reservation(40)),
        producer_dispatch_id="producer-1",
        verifier_dispatch_id="verifier-1",
    )
    ledger.observe(
        "producer-1",
        token_status="untrusted",
        billable_tokens=90,
        active_status="untrusted",
        active_ms=1500,
    )

    decision = ledger.decision
    assert decision.charged_tokens == 130
    assert decision.charged_active_ms == 2500
    assert decision.reservation_breaches == ()


@pytest.mark.unit
def test_abandoned_producer_charges_unknown_reservation_and_releases_verifier() -> None:
    ledger = L4ResourceLedger(
        exhaustive_budget_policy_v1(token_limit=200, active_ms_limit=10_000)
    )
    pair = ledger.commit_pair(
        ledger.preview_pair(digest("slice"), 1, _reservation(70), _reservation(40)),
        producer_dispatch_id="producer-1",
        verifier_dispatch_id="verifier-1",
    )

    ledger.abandon("producer-1")
    ledger.release_verifier(pair.identity, reason="producer_abandoned")

    decision = ledger.decision
    assert decision.charged_tokens == 70
    assert decision.unknown_token_dispatches_by_role == {"producer": 1, "verifier": 0}
    assert decision.generated_dispatches_by_role == {"producer": 1, "verifier": 0}
    assert decision.open_token_reservations == 0


@pytest.mark.unit
def test_resource_records_replay_to_identical_decision() -> None:
    policy = exhaustive_budget_policy_v1(token_limit=200, active_ms_limit=10_000)
    ledger = L4ResourceLedger(policy)
    ledger.commit_pair(
        ledger.preview_pair(digest("slice"), 1, _reservation(70), _reservation(40)),
        producer_dispatch_id="producer-1",
        verifier_dispatch_id="verifier-1",
    )
    ledger.observe(
        "producer-1",
        token_status="trusted_exact",
        billable_tokens=30,
        active_status="trusted_exact",
        active_ms=500,
    )

    replayed = L4ResourceLedger.from_records(policy, ledger.records)

    assert replayed.records == ledger.records
    assert replayed.prefix_id == ledger.prefix_id
    assert replayed.decision == ledger.decision


@pytest.mark.unit
def test_retained_verifier_cannot_be_observed_before_paired_producer() -> None:
    ledger = L4ResourceLedger(
        exhaustive_budget_policy_v1(token_limit=200, active_ms_limit=10_000)
    )
    pair = ledger.commit_pair(
        ledger.preview_pair(digest("slice"), 1, _reservation(70), _reservation(40)),
        producer_dispatch_id="producer-1",
        verifier_dispatch_id="verifier-1",
    )

    with pytest.raises(Protocol28BudgetError, match="paired producer"):
        ledger.observe(
            pair.verifier_dispatch_id,
            token_status="trusted_exact",
            billable_tokens=20,
            active_status="trusted_exact",
            active_ms=500,
        )


@pytest.mark.unit
def test_exact_resource_ceiling_is_visible_as_exhausted() -> None:
    ledger = L4ResourceLedger(
        exhaustive_budget_policy_v1(token_limit=110, active_ms_limit=2000)
    )
    ledger.commit_pair(
        ledger.preview_pair(digest("slice"), 1, _reservation(70), _reservation(40)),
        producer_dispatch_id="producer-1",
        verifier_dispatch_id="verifier-1",
    )

    decision = ledger.decision
    assert decision.exhausted_dimensions == ("tokens", "active_ms")
    assert decision.pause_required is True
