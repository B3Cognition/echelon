from __future__ import annotations

from pathlib import Path

import pytest

from harness.re_v2.events import ReV2EventError
from harness.re_v2.protocol_22.provider import DispatchReservationV1
from harness.re_v2.protocol_25.budget import (
    ReV2SemanticBudgetError,
    evaluate_semantic_budget,
    initial_semantic_pool_reservation,
    replay_target_progress,
)
from harness.re_v2.protocol_25.model import SemanticClosurePolicyV1
from tests.re_v2_protocol_22_fixtures import digest
from tests.unit.test_re_v2_protocol_25_events import (
    NOW,
    SOURCE,
    TARGET_A,
    TARGET_B,
    _append,
    _finish_shared,
    _freeze,
    _guard,
    _recheck,
    _resolution,
    _run,
    _semantic_start_payload,
    _start_shared,
    _store,
)


def _policy(
    *, token_limit: int | None = 10_000, active_ms_limit: int | None = 20_000
) -> SemanticClosurePolicyV1:
    return SemanticClosurePolicyV1(
        schema_version=1,
        token_limit=token_limit,
        active_ms_limit=active_ms_limit,
        max_rounds_per_target=3,
        consecutive_no_reduction_limit=2,
        provider_attempt_limit=2,
        contract_retry_limit=1,
        unknown_usage_policy="shared-conservative-reservation-v1",
    )


def _semantic_observation_store(
    tmp_path: Path,
    *,
    token_usage: int | None,
    token_status: str,
    active_usage: int | None,
    active_status: str,
):
    store = _store(tmp_path)
    _run(store)
    _freeze(store, (TARGET_A,))
    work = digest("resolution")
    _start_shared(
        store,
        dispatch_id="resolution-1",
        work=work,
        tokens=400,
        active_ms=2_000,
    )
    _append(
        store,
        "semantic_resolution_started",
        _semantic_start_payload(dispatch_id="resolution-1", work=work),
    )
    _append(
        store,
        "dispatch_observed",
        {
            "active_usage_status": active_status,
            "dispatch_id": "resolution-1",
            "execution_capture_hash": digest("capture"),
            "observed_active_ms": active_usage,
            "raw_result_contract_status": "valid",
            "reported_token_usage": token_usage,
            "token_usage_status": token_status,
            "work_item_id": work,
        },
    )
    return store


@pytest.mark.unit
def test_audit_does_not_consume_semantic_pool(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _run(store)
    work = digest("audit")
    _start_shared(store, dispatch_id="audit-1", work=work, tokens=40_000)
    _append(
        store,
        "dispatch_observed",
        {
            "active_usage_status": "trusted_exact",
            "dispatch_id": "audit-1",
            "execution_capture_hash": digest("audit-capture"),
            "observed_active_ms": 1_000,
            "raw_result_contract_status": "valid",
            "reported_token_usage": 40_000,
            "token_usage_status": "trusted_exact",
            "work_item_id": work,
        },
    )

    decision = evaluate_semantic_budget(_policy(), store.replay())

    assert decision.charged_tokens == 0
    assert decision.charged_active_ms == 0
    assert decision.rounds_by_target == {}


@pytest.mark.unit
@pytest.mark.parametrize(
    ("token_usage", "token_status", "active_usage", "active_status", "expected"),
    (
        (25, "trusted_exact", 250, "trusted_exact", (25, 250, 0)),
        (None, "unavailable", None, "unavailable", (400, 2_000, 1)),
        (550, "untrusted", 2_500, "untrusted", (550, 2_500, 1)),
    ),
)
def test_semantic_usage_reuses_shared_conservative_charging(
    tmp_path: Path,
    token_usage: int | None,
    token_status: str,
    active_usage: int | None,
    active_status: str,
    expected: tuple[int, int, int],
) -> None:
    store = _semantic_observation_store(
        tmp_path,
        token_usage=token_usage,
        token_status=token_status,
        active_usage=active_usage,
        active_status=active_status,
    )

    decision = evaluate_semantic_budget(_policy(), store.replay())

    assert (
        decision.charged_tokens,
        decision.charged_active_ms,
        decision.unknown_token_dispatches,
    ) == expected


@pytest.mark.unit
def test_open_semantic_dispatch_charges_its_reservation(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _run(store)
    _freeze(store, (TARGET_A,))
    work = digest("resolution")
    _start_shared(store, dispatch_id="resolution-1", work=work, tokens=400, active_ms=2_000)
    _append(
        store,
        "semantic_resolution_started",
        _semantic_start_payload(dispatch_id="resolution-1", work=work),
    )

    decision = evaluate_semantic_budget(_policy(), store.replay(), {"resolution-1"})

    assert decision.charged_tokens == 400
    assert decision.open_token_reservations == 400
    assert decision.charged_active_ms == 2_000


@pytest.mark.unit
def test_source_cycle_increments_each_participating_target_once(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _run(store)
    _freeze(store)
    _resolution(store, TARGET_A, "a")
    _resolution(store, TARGET_B, "b")
    _recheck(store, TARGET_A, "a")
    _recheck(store, TARGET_B, "b")
    assessment = _guard(store, (TARGET_A, TARGET_B))
    for target in (TARGET_A, TARGET_B):
        finding = digest(f"finding:{target}")
        _append(
            store,
            "finding_closure_recorded",
            {
                "audit_target_id": target,
                "finding_closure_receipt_id": digest(f"receipt:{target}"),
                "finding_key_id": finding,
                "semantic_round": 1,
                "source_composition_assessment_id": assessment,
                "source_cycle_id": "cycle-1",
                "verdict": "closed",
            },
        )
        _append(
            store,
            "semantic_progress_recorded",
            {
                "audit_target_id": target,
                "semantic_round": 1,
                "source_cycle_id": "cycle-1",
                "unresolved_after_ids": [],
                "unresolved_before_ids": [finding],
            },
        )

    decision = evaluate_semantic_budget(_policy(), store.replay())
    progress = replay_target_progress(store.replay())

    assert decision.rounds_by_target == {TARGET_A: 1, TARGET_B: 1}
    assert progress.rounds_by_target == {TARGET_A: 1, TARGET_B: 1}
    assert decision.no_reduction_rounds_by_target == {TARGET_A: 0, TARGET_B: 0}
    assert decision.charged_tokens == 100
    assert decision.charged_active_ms == 1_000


@pytest.mark.unit
def test_progress_depends_only_on_unresolved_id_reduction(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _run(store)
    _freeze(store, (TARGET_A,))
    finding = digest("finding")

    # A failed guard completes the cycle without closure receipts. Changed prose or
    # overlay identities cannot appear in this projection, so the same ID set is no progress.
    _resolution(store, TARGET_A, "a")
    _recheck(store, TARGET_A, "a")
    _guard(store, (TARGET_A,), passed=False)
    _append(
        store,
        "semantic_progress_recorded",
        {
            "audit_target_id": TARGET_A,
            "semantic_round": 1,
            "source_cycle_id": "cycle-1",
            "unresolved_after_ids": [finding],
            "unresolved_before_ids": [finding],
        },
    )

    decision = evaluate_semantic_budget(_policy(), store.replay())
    assert decision.no_reduction_rounds_by_target == {TARGET_A: 1}


@pytest.mark.unit
def test_progress_rejects_closure_verdict_that_disagrees_with_unresolved_ids(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    _run(store)
    _freeze(store, (TARGET_A,))
    finding = digest("finding")
    _resolution(store, TARGET_A, "a")
    _recheck(store, TARGET_A, "a")
    assessment = _guard(store, (TARGET_A,))
    _append(
        store,
        "finding_closure_recorded",
        {
            "audit_target_id": TARGET_A,
            "finding_closure_receipt_id": digest("receipt"),
            "finding_key_id": finding,
            "semantic_round": 1,
            "source_composition_assessment_id": assessment,
            "source_cycle_id": "cycle-1",
            "verdict": "open",
        },
    )

    with pytest.raises(ReV2EventError, match="closure verdicts"):
        _append(
            store,
            "semantic_progress_recorded",
            {
                "audit_target_id": TARGET_A,
                "semantic_round": 1,
                "source_cycle_id": "cycle-1",
                "unresolved_after_ids": [],
                "unresolved_before_ids": [finding],
            },
        )


@pytest.mark.unit
def test_runwide_raise_does_not_raise_semantic_limit(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _run(store)
    _append(
        store,
        "run_paused",
        {"reason": "run tokens exhausted", "reason_code": "tokens_exhausted"},
    )
    _append(
        store,
        "budget_authorized",
        {
            "authorized_by": "operator",
            "dimension": "tokens",
            "new_value": 1_000_000,
            "old_value": 10_000,
            "reason": "raise runwide ceiling",
        },
    )

    decision = evaluate_semantic_budget(_policy(), store.replay())
    assert decision.token_limit == 10_000


@pytest.mark.unit
def test_semantic_authorization_changes_only_resource_limit(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _run(store)
    _append(
        store,
        "run_paused",
        {"reason": "semantic tokens exhausted", "reason_code": "semantic_tokens_exhausted"},
    )
    _append(
        store,
        "semantic_budget_authorized",
        {
            "authorized_by": "operator",
            "dimension": "tokens",
            "new_value": 20_000,
            "old_value": 10_000,
            "reason": "continue the same epoch",
        },
    )

    decision = evaluate_semantic_budget(_policy(), store.replay())

    assert decision.token_limit == 20_000
    assert decision.max_rounds_per_target == 3
    assert decision.consecutive_no_reduction_limit == 2
    assert decision.provider_attempt_limit == 2
    assert decision.contract_retry_limit == 1

    with pytest.raises(ReV2EventError, match="unknown fields"):
        _append(
            store,
            "semantic_budget_authorized",
            {
                "authorized_by": "operator",
                "dimension": "tokens",
                "max_rounds_per_target": 4,
                "new_value": 30_000,
                "old_value": 20_000,
                "reason": "not permitted",
            },
        )


@pytest.mark.unit
def test_initial_pool_reserves_one_target_cycle_and_one_guard_per_source() -> None:
    resolution = DispatchReservationV1(10, 100, 1_000)
    recheck = DispatchReservationV1(20, 200, 2_000)
    guard = DispatchReservationV1(30, 300, 3_000)

    reserved = initial_semantic_pool_reservation(
        {TARGET_A: (resolution, recheck), TARGET_B: (resolution, recheck)},
        {SOURCE: guard},
    )

    assert reserved.billable_tokens == 900
    assert reserved.active_ms == 9_000
    assert reserved.target_count == 2
    assert reserved.source_count == 1


@pytest.mark.unit
def test_budget_exhaustion_and_next_cycle_capacity_are_explicit(tmp_path: Path) -> None:
    store = _semantic_observation_store(
        tmp_path,
        token_usage=400,
        token_status="trusted_exact",
        active_usage=2_000,
        active_status="trusted_exact",
    )
    decision = evaluate_semantic_budget(
        _policy(token_limit=400, active_ms_limit=2_000), store.replay()
    )

    assert decision.exhausted_dimensions == ("tokens", "active_ms")
    assert decision.pause_required is True
    assert decision.can_reserve(DispatchReservationV1(1, 1, 1)) is False


@pytest.mark.unit
def test_budget_rejects_open_dispatch_set_disagreement(tmp_path: Path) -> None:
    store = _semantic_observation_store(
        tmp_path,
        token_usage=1,
        token_status="trusted_exact",
        active_usage=1,
        active_status="trusted_exact",
    )
    with pytest.raises(ReV2SemanticBudgetError, match="open semantic dispatch"):
        evaluate_semantic_budget(_policy(), store.replay(), {"resolution-1"})


def _record_cycle(
    store,
    *,
    cycle_id: str,
    round_index: int,
    before: tuple[str, ...],
    after: tuple[str, ...],
    passed: bool,
) -> None:
    suffix = str(round_index)
    _resolution(
        store,
        TARGET_A,
        suffix,
        cycle_id=cycle_id,
        round_index=round_index,
    )
    _recheck(
        store,
        TARGET_A,
        suffix,
        cycle_id=cycle_id,
        round_index=round_index,
    )
    assessment = _guard(
        store,
        (TARGET_A,),
        passed=passed,
        cycle_id=cycle_id,
        round_index=round_index,
    )
    if passed:
        for finding in before:
            _append(
                store,
                "finding_closure_recorded",
                {
                    "audit_target_id": TARGET_A,
                    "finding_closure_receipt_id": digest(
                        f"receipt:{cycle_id}:{finding}"
                    ),
                    "finding_key_id": finding,
                    "semantic_round": round_index,
                    "source_composition_assessment_id": assessment,
                    "source_cycle_id": cycle_id,
                    "verdict": "open" if finding in after else "closed",
                },
            )
    _append(
        store,
        "semantic_progress_recorded",
        {
            "audit_target_id": TARGET_A,
            "semantic_round": round_index,
            "source_cycle_id": cycle_id,
            "unresolved_after_ids": sorted(after),
            "unresolved_before_ids": sorted(before),
        },
    )


@pytest.mark.unit
def test_reduction_resets_consecutive_no_reduction_count(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _run(store)
    _freeze(store, (TARGET_A,))
    first = digest("finding:first")
    second = digest("finding:second")
    unresolved = tuple(sorted((first, second)))
    _record_cycle(
        store,
        cycle_id="cycle-1",
        round_index=1,
        before=unresolved,
        after=unresolved,
        passed=False,
    )
    _record_cycle(
        store,
        cycle_id="cycle-2",
        round_index=2,
        before=unresolved,
        after=(second,),
        passed=True,
    )

    decision = evaluate_semantic_budget(_policy(), store.replay())

    assert decision.rounds_by_target == {TARGET_A: 2}
    assert decision.no_reduction_rounds_by_target == {TARGET_A: 0}
    assert decision.unresolved_by_target == {TARGET_A: frozenset({second})}


@pytest.mark.unit
def test_two_no_reduction_rounds_reach_plateau_and_forbid_another_cycle(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    _run(store)
    _freeze(store, (TARGET_A,))
    finding = digest("finding")
    for round_index in (1, 2):
        _record_cycle(
            store,
            cycle_id=f"cycle-{round_index}",
            round_index=round_index,
            before=(finding,),
            after=(finding,),
            passed=False,
        )
    _append(
        store,
        "semantic_plateau_reached",
        {
            "audit_target_id": TARGET_A,
            "semantic_round": 2,
            "unresolved_finding_ids": [finding],
        },
    )

    decision = evaluate_semantic_budget(_policy(), store.replay())
    assert decision.no_reduction_rounds_by_target == {TARGET_A: 2}
    assert decision.exhausted_dimensions == (f"semantic_plateau:{TARGET_A}",)

    work = digest("resolution:forbidden")
    _start_shared(store, dispatch_id="resolution-forbidden", work=work)
    with pytest.raises(ReV2EventError, match="plateau"):
        _append(
            store,
            "semantic_resolution_started",
            _semantic_start_payload(
                dispatch_id="resolution-forbidden",
                work=work,
                cycle_id="cycle-3",
                round_index=3,
            ),
        )


@pytest.mark.unit
def test_third_round_is_absolute_semantic_limit(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _run(store)
    _freeze(store, (TARGET_A,))
    findings = tuple(digest(f"finding:{index}") for index in range(4))
    before = findings
    for round_index in (1, 2, 3):
        after = before[1:]
        _record_cycle(
            store,
            cycle_id=f"cycle-{round_index}",
            round_index=round_index,
            before=before,
            after=after,
            passed=True,
        )
        before = after

    decision = evaluate_semantic_budget(_policy(), store.replay())
    assert decision.rounds_by_target == {TARGET_A: 3}
    assert decision.exhausted_dimensions == (f"semantic_rounds:{TARGET_A}",)

    work = digest("resolution:four")
    _start_shared(store, dispatch_id="resolution-four", work=work)
    with pytest.raises(ReV2EventError, match="three semantic rounds"):
        _append(
            store,
            "semantic_resolution_started",
            _semantic_start_payload(
                dispatch_id="resolution-four",
                work=work,
                cycle_id="cycle-4",
                round_index=4,
            ),
        )
