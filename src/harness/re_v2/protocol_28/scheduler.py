"""Bounded protocol-2.8 producer/verifier slice state machine."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from harness.re_v2.protocol_22.schema import digest_value
from harness.re_v2.protocol_28.policies import ExhaustivePolicyV1


ProducerOutcome = Literal["contract_failure", "candidate"]
VerifierOutcome = Literal["contract_failure", "PASS", "REPAIR"]
ActionKind = Literal[
    "reserve_producer_pair",
    "dispatch_producer",
    "dispatch_verifier",
    "reserve_verifier_retry",
    "dispatch_verifier_retry",
    "accept_candidate",
    "terminal_failure",
    "complete",
]


class Protocol28SchedulerError(ValueError):
    """Raised when an L4 attempt history violates the frozen state machine."""


def _digest(value: object, field: str) -> str:
    try:
        return digest_value(value, field)
    except ValueError as exc:
        raise Protocol28SchedulerError(str(exc)) from exc


def _attempt(value: object, field: str, *, maximum: int) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < 1
        or value > maximum
    ):
        raise Protocol28SchedulerError(f"{field} must be in [1, {maximum}]")
    return value


def _diagnostics(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise Protocol28SchedulerError(f"{field} must be an array")
    result = tuple(_digest(item, field) for item in value)
    if result != tuple(sorted(set(result))):
        raise Protocol28SchedulerError(f"{field} must be sorted and unique")
    return result


@dataclass(frozen=True, slots=True)
class ProducerAttemptV1:
    schema_version: int
    producer_attempt_number: int
    outcome: ProducerOutcome
    candidate_id: str | None

    def __post_init__(self) -> None:
        if self.schema_version != 1 or isinstance(self.schema_version, bool):
            raise Protocol28SchedulerError("producer attempt schema_version must be 1")
        _attempt(self.producer_attempt_number, "producer_attempt_number", maximum=3)
        if self.outcome not in {"contract_failure", "candidate"}:
            raise Protocol28SchedulerError("producer attempt outcome is invalid")
        if self.outcome == "candidate":
            _digest(self.candidate_id, "candidate_id")
        elif self.candidate_id is not None:
            raise Protocol28SchedulerError(
                "producer contract failure cannot contain a candidate"
            )


@dataclass(frozen=True, slots=True)
class VerifierAttemptV1:
    schema_version: int
    producer_attempt_number: int
    verifier_attempt_number: int
    candidate_id: str
    outcome: VerifierOutcome
    diagnostic_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.schema_version != 1 or isinstance(self.schema_version, bool):
            raise Protocol28SchedulerError("verifier attempt schema_version must be 1")
        _attempt(self.producer_attempt_number, "producer_attempt_number", maximum=3)
        _attempt(self.verifier_attempt_number, "verifier_attempt_number", maximum=2)
        _digest(self.candidate_id, "candidate_id")
        if self.outcome not in {"contract_failure", "PASS", "REPAIR"}:
            raise Protocol28SchedulerError("verifier attempt outcome is invalid")
        normalized = _diagnostics(self.diagnostic_ids, "diagnostic_ids")
        object.__setattr__(self, "diagnostic_ids", normalized)
        if self.outcome == "REPAIR" and not normalized:
            raise Protocol28SchedulerError("REPAIR verifier attempt requires diagnostics")
        if self.outcome != "REPAIR" and normalized:
            raise Protocol28SchedulerError(
                "PASS or contract-failure verifier attempt cannot contain diagnostics"
            )


@dataclass(frozen=True, slots=True)
class SliceScheduleStateV1:
    schema_version: int
    slice_spec_id: str
    producer_attempts: tuple[ProducerAttemptV1, ...]
    verifier_attempts: tuple[VerifierAttemptV1, ...]
    paired_attempt_number: int | None
    verifier_retry_reserved_for_attempt: int | None
    accepted_candidate_id: str | None

    def __post_init__(self) -> None:
        if self.schema_version != 1 or isinstance(self.schema_version, bool):
            raise Protocol28SchedulerError("slice schedule schema_version must be 1")
        _digest(self.slice_spec_id, "slice_spec_id")
        producers = tuple(self.producer_attempts)
        verifiers = tuple(self.verifier_attempts)
        if any(not isinstance(item, ProducerAttemptV1) for item in producers):
            raise Protocol28SchedulerError("producer_attempts are invalid")
        if any(not isinstance(item, VerifierAttemptV1) for item in verifiers):
            raise Protocol28SchedulerError("verifier_attempts are invalid")
        expected_producers = tuple(range(1, len(producers) + 1))
        if tuple(item.producer_attempt_number for item in producers) != expected_producers:
            raise Protocol28SchedulerError(
                "producer attempt numbers must be consecutive from one"
            )
        verifier_keys = tuple(
            (item.producer_attempt_number, item.verifier_attempt_number)
            for item in verifiers
        )
        if verifier_keys != tuple(sorted(set(verifier_keys))):
            raise Protocol28SchedulerError(
                "verifier attempt numbers must be ordered and unique"
            )
        producers_by_number = {
            item.producer_attempt_number: item for item in producers
        }
        grouped: dict[int, list[VerifierAttemptV1]] = {}
        for verifier in verifiers:
            producer = producers_by_number.get(verifier.producer_attempt_number)
            if (
                producer is None
                or producer.outcome != "candidate"
                or producer.candidate_id != verifier.candidate_id
            ):
                raise Protocol28SchedulerError(
                    "verifier attempt does not match a produced candidate"
                )
            grouped.setdefault(verifier.producer_attempt_number, []).append(verifier)
        for attempts in grouped.values():
            if tuple(item.verifier_attempt_number for item in attempts) != tuple(
                range(1, len(attempts) + 1)
            ):
                raise Protocol28SchedulerError(
                    "verifier attempt numbers must be consecutive from one"
                )
            if len(attempts) == 2 and attempts[0].outcome != "contract_failure":
                raise Protocol28SchedulerError(
                    "second verifier attempt requires first contract failure"
                )
        for producer in producers[:-1]:
            if producer.outcome == "contract_failure":
                continue
            attempts = grouped.get(producer.producer_attempt_number, [])
            if not attempts or attempts[-1].outcome != "REPAIR":
                raise Protocol28SchedulerError(
                    "a later producer attempt requires preceding semantic REPAIR"
                )
        if self.paired_attempt_number is not None:
            paired = _attempt(
                self.paired_attempt_number, "paired_attempt_number", maximum=3
            )
            if paired != len(producers) + 1:
                raise Protocol28SchedulerError(
                    "paired producer attempt must be the next consecutive attempt"
                )
            if producers and producers[-1].outcome == "candidate":
                attempts = grouped.get(producers[-1].producer_attempt_number, [])
                if not attempts or attempts[-1].outcome != "REPAIR":
                    raise Protocol28SchedulerError(
                        "future pair cannot be reserved for an unresolved candidate"
                    )
        if self.verifier_retry_reserved_for_attempt is not None:
            retry = _attempt(
                self.verifier_retry_reserved_for_attempt,
                "verifier_retry_reserved_for_attempt",
                maximum=3,
            )
            attempts = grouped.get(retry, [])
            if len(attempts) != 1 or attempts[0].outcome != "contract_failure":
                raise Protocol28SchedulerError(
                    "verifier retry reservation requires one contract failure"
                )
        if self.accepted_candidate_id is not None:
            accepted = _digest(self.accepted_candidate_id, "accepted_candidate_id")
            passed = any(
                item.candidate_id == accepted and item.outcome == "PASS"
                for item in verifiers
            )
            if not passed:
                raise Protocol28SchedulerError(
                    "accepted candidate requires a preceding verifier PASS"
                )
        object.__setattr__(self, "producer_attempts", producers)
        object.__setattr__(self, "verifier_attempts", verifiers)


@dataclass(frozen=True, slots=True)
class SliceScheduleActionV1:
    kind: ActionKind
    producer_attempt_number: int | None = None
    verifier_attempt_number: int | None = None
    candidate_id: str | None = None
    diagnostic_ids: tuple[str, ...] = ()
    reason: str | None = None
    producer_history: tuple[ProducerAttemptV1, ...] = ()


def next_slice_action(
    policy: ExhaustivePolicyV1,
    state: SliceScheduleStateV1,
) -> SliceScheduleActionV1:
    """Return the one legal next action under fixed attempts and plateau policy."""
    if not isinstance(policy, ExhaustivePolicyV1):
        raise Protocol28SchedulerError("scheduler requires ExhaustivePolicyV1")
    if not isinstance(state, SliceScheduleStateV1):
        raise Protocol28SchedulerError("scheduler requires SliceScheduleStateV1")
    history = state.producer_attempts
    if state.accepted_candidate_id is not None:
        return SliceScheduleActionV1(
            "complete",
            candidate_id=state.accepted_candidate_id,
            producer_history=history,
        )

    if not history:
        return _producer_action(state, 1, ())

    latest = history[-1]
    if latest.outcome == "contract_failure":
        if len(history) >= policy.producer_attempt_limit:
            return _terminal(
                "producer_result_contract_attempts_exhausted", history
            )
        return _producer_action(state, len(history) + 1, ())

    verifier_history = tuple(
        item
        for item in state.verifier_attempts
        if item.producer_attempt_number == latest.producer_attempt_number
    )
    if not verifier_history:
        return SliceScheduleActionV1(
            "dispatch_verifier",
            producer_attempt_number=latest.producer_attempt_number,
            verifier_attempt_number=1,
            candidate_id=latest.candidate_id,
            producer_history=history,
        )

    verifier = verifier_history[-1]
    if verifier.outcome == "contract_failure":
        if len(verifier_history) > policy.verifier_contract_retry_limit:
            return _terminal(
                "verifier_result_contract_attempts_exhausted", history
            )
        if (
            state.verifier_retry_reserved_for_attempt
            == latest.producer_attempt_number
        ):
            return SliceScheduleActionV1(
                "dispatch_verifier_retry",
                producer_attempt_number=latest.producer_attempt_number,
                verifier_attempt_number=2,
                candidate_id=latest.candidate_id,
                producer_history=history,
            )
        return SliceScheduleActionV1(
            "reserve_verifier_retry",
            producer_attempt_number=latest.producer_attempt_number,
            verifier_attempt_number=2,
            candidate_id=latest.candidate_id,
            producer_history=history,
        )

    if verifier.outcome == "PASS":
        return SliceScheduleActionV1(
            "accept_candidate",
            producer_attempt_number=latest.producer_attempt_number,
            candidate_id=latest.candidate_id,
            producer_history=history,
        )

    semantic_repairs = tuple(
        attempts[-1]
        for number in range(1, len(history) + 1)
        if (
            attempts := tuple(
                item
                for item in state.verifier_attempts
                if item.producer_attempt_number == number
            )
        )
        and attempts[-1].outcome == "REPAIR"
    )
    if (
        len(semantic_repairs) >= policy.identical_outcome_early_stop
        and semantic_repairs[-1].diagnostic_ids
        == semantic_repairs[-2].diagnostic_ids
    ):
        return _terminal(
            "non_improving_verification",
            history,
            semantic_repairs[-1].diagnostic_ids,
        )
    if len(history) >= policy.producer_attempt_limit:
        return _terminal(
            "semantic_repair_attempts_exhausted",
            history,
            verifier.diagnostic_ids,
        )
    return _producer_action(
        state, len(history) + 1, verifier.diagnostic_ids
    )


def _producer_action(
    state: SliceScheduleStateV1,
    attempt_number: int,
    diagnostics: tuple[str, ...],
) -> SliceScheduleActionV1:
    kind: ActionKind = (
        "dispatch_producer"
        if state.paired_attempt_number == attempt_number
        else "reserve_producer_pair"
    )
    return SliceScheduleActionV1(
        kind,
        producer_attempt_number=attempt_number,
        diagnostic_ids=diagnostics,
        producer_history=state.producer_attempts,
    )


def _terminal(
    reason: str,
    history: tuple[ProducerAttemptV1, ...],
    diagnostics: tuple[str, ...] = (),
) -> SliceScheduleActionV1:
    return SliceScheduleActionV1(
        "terminal_failure",
        diagnostic_ids=diagnostics,
        reason=reason,
        producer_history=history,
    )


__all__ = (
    "ProducerAttemptV1",
    "Protocol28SchedulerError",
    "SliceScheduleActionV1",
    "SliceScheduleStateV1",
    "VerifierAttemptV1",
    "next_slice_action",
)
