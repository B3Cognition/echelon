from __future__ import annotations

import pytest

from harness.re_v2.protocol_28.policies import build_initial_exhaustive_policy
from harness.re_v2.protocol_28.scheduler import (
    ProducerAttemptV1,
    Protocol28SchedulerError,
    SliceScheduleStateV1,
    VerifierAttemptV1,
    next_slice_action,
)
from tests.re_v2_protocol_28_fixtures import digest


def _state(
    *,
    producers=(),
    verifiers=(),
    paired_attempt_number=None,
    verifier_retry_reserved_for_attempt=None,
    accepted_candidate_id=None,
):  # type: ignore[no-untyped-def]
    return SliceScheduleStateV1(
        1,
        digest("slice"),
        tuple(producers),
        tuple(verifiers),
        paired_attempt_number,
        verifier_retry_reserved_for_attempt,
        accepted_candidate_id,
    )


@pytest.mark.unit
def test_initial_producer_requires_pair_before_dispatch() -> None:
    policy = build_initial_exhaustive_policy()

    reserve = next_slice_action(policy, _state())
    dispatch = next_slice_action(policy, _state(paired_attempt_number=1))

    assert reserve.kind == "reserve_producer_pair"
    assert reserve.producer_attempt_number == 1
    assert dispatch.kind == "dispatch_producer"
    assert dispatch.producer_attempt_number == 1


@pytest.mark.unit
def test_malformed_producer_consumes_one_of_exactly_three_attempts() -> None:
    policy = build_initial_exhaustive_policy()
    attempts = tuple(
        ProducerAttemptV1(1, number, "contract_failure", None)
        for number in (1, 2, 3)
    )

    repair = next_slice_action(policy, _state(producers=attempts[:1]))
    terminal = next_slice_action(policy, _state(producers=attempts))

    assert repair.kind == "reserve_producer_pair"
    assert repair.producer_attempt_number == 2
    assert terminal.kind == "terminal_failure"
    assert terminal.reason == "producer_result_contract_attempts_exhausted"


@pytest.mark.unit
def test_verifier_contract_failure_retries_verifier_without_regenerating_candidate() -> None:
    policy = build_initial_exhaustive_policy()
    candidate_id = digest("candidate-1")
    producer = ProducerAttemptV1(1, 1, "candidate", candidate_id)
    failed = VerifierAttemptV1(
        1, 1, 1, candidate_id, "contract_failure", ()
    )

    reserve = next_slice_action(
        policy, _state(producers=(producer,), verifiers=(failed,))
    )
    dispatch = next_slice_action(
        policy,
        _state(
            producers=(producer,),
            verifiers=(failed,),
            verifier_retry_reserved_for_attempt=1,
        ),
    )
    exhausted = next_slice_action(
        policy,
        _state(
            producers=(producer,),
            verifiers=(
                failed,
                VerifierAttemptV1(1, 1, 2, candidate_id, "contract_failure", ()),
            ),
        ),
    )

    assert reserve.kind == "reserve_verifier_retry"
    assert dispatch.kind == "dispatch_verifier_retry"
    assert dispatch.verifier_attempt_number == 2
    assert exhausted.reason == "verifier_result_contract_attempts_exhausted"
    assert len(exhausted.producer_history) == 1


@pytest.mark.unit
def test_semantic_repair_requests_next_paired_producer_attempt() -> None:
    policy = build_initial_exhaustive_policy()
    candidate_id = digest("candidate-1")
    diagnostic_id = digest("diagnostic-a")
    producer = ProducerAttemptV1(1, 1, "candidate", candidate_id)
    repair = VerifierAttemptV1(
        1, 1, 1, candidate_id, "REPAIR", (diagnostic_id,)
    )

    action = next_slice_action(
        policy, _state(producers=(producer,), verifiers=(repair,))
    )

    assert action.kind == "reserve_producer_pair"
    assert action.producer_attempt_number == 2
    assert action.diagnostic_ids == (diagnostic_id,)


@pytest.mark.unit
def test_two_identical_nonempty_diagnostic_sets_stop_at_plateau() -> None:
    policy = build_initial_exhaustive_policy()
    diagnostic_id = digest("diagnostic-a")
    producers = (
        ProducerAttemptV1(1, 1, "candidate", digest("candidate-1")),
        ProducerAttemptV1(1, 2, "candidate", digest("candidate-2")),
    )
    verifiers = tuple(
        VerifierAttemptV1(1, number, 1, producer.candidate_id, "REPAIR", (diagnostic_id,))
        for number, producer in enumerate(producers, start=1)
    )

    action = next_slice_action(policy, _state(producers=producers, verifiers=verifiers))

    assert action.kind == "terminal_failure"
    assert action.reason == "non_improving_verification"
    assert action.diagnostic_ids == (diagnostic_id,)


@pytest.mark.unit
def test_different_diagnostics_allow_third_attempt_then_semantic_ceiling_blocks() -> None:
    policy = build_initial_exhaustive_policy()
    producers = tuple(
        ProducerAttemptV1(1, number, "candidate", digest(f"candidate-{number}"))
        for number in (1, 2, 3)
    )
    verifiers = (
        VerifierAttemptV1(1, 1, 1, producers[0].candidate_id, "REPAIR", (digest("a"),)),
        VerifierAttemptV1(1, 2, 1, producers[1].candidate_id, "REPAIR", (digest("b"),)),
        VerifierAttemptV1(1, 3, 1, producers[2].candidate_id, "REPAIR", (digest("c"),)),
    )

    third = next_slice_action(
        policy, _state(producers=producers[:2], verifiers=verifiers[:2])
    )
    terminal = next_slice_action(
        policy, _state(producers=producers, verifiers=verifiers)
    )

    assert third.kind == "reserve_producer_pair"
    assert third.producer_attempt_number == 3
    assert terminal.reason == "semantic_repair_attempts_exhausted"


@pytest.mark.unit
def test_pass_is_accepted_and_accepted_slice_never_reopens() -> None:
    policy = build_initial_exhaustive_policy()
    candidate_id = digest("candidate-1")
    producer = ProducerAttemptV1(1, 1, "candidate", candidate_id)
    passed = VerifierAttemptV1(1, 1, 1, candidate_id, "PASS", ())

    accept = next_slice_action(
        policy, _state(producers=(producer,), verifiers=(passed,))
    )
    complete = next_slice_action(
        policy,
        _state(
            producers=(producer,),
            verifiers=(passed,),
            accepted_candidate_id=candidate_id,
        ),
    )

    assert accept.kind == "accept_candidate"
    assert complete.kind == "complete"


@pytest.mark.unit
def test_history_rejects_skipped_or_duplicate_attempt_numbers() -> None:
    with pytest.raises(Protocol28SchedulerError, match="consecutive"):
        _state(
            producers=(
                ProducerAttemptV1(1, 1, "contract_failure", None),
                ProducerAttemptV1(1, 3, "contract_failure", None),
            )
        )


@pytest.mark.unit
def test_history_cannot_continue_past_pass_or_unresolved_verifier_failure() -> None:
    first = ProducerAttemptV1(1, 1, "candidate", digest("candidate-1"))
    second = ProducerAttemptV1(1, 2, "candidate", digest("candidate-2"))

    with pytest.raises(Protocol28SchedulerError, match="semantic REPAIR"):
        _state(
            producers=(first, second),
            verifiers=(
                VerifierAttemptV1(1, 1, 1, first.candidate_id, "PASS", ()),
            ),
        )


@pytest.mark.unit
def test_future_pair_cannot_be_reserved_while_candidate_awaits_verification() -> None:
    producer = ProducerAttemptV1(1, 1, "candidate", digest("candidate-1"))

    with pytest.raises(Protocol28SchedulerError, match="unresolved candidate"):
        _state(producers=(producer,), paired_attempt_number=2)
