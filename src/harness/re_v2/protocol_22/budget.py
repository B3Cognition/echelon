"""Conservative resource and attempt accounting for protocol 2.2."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Iterable, Literal, Mapping

from harness.re_v2.events import EventRecord, ReV2EventError, validate_event_history

from .events import PROTOCOL_22_EVENTS, Protocol22ReplayState
from .model import BudgetPolicyV2, WorkItemV2


MAX_ACCOUNTING_VALUE = (1 << 63) - 1
UsageStatus = Literal["trusted_exact", "unavailable", "untrusted"]
_USAGE_STATUSES = frozenset({"trusted_exact", "unavailable", "untrusted"})


class ReV2BudgetV22Error(ValueError):
    """Raised when protocol-2.2 accounting cannot be derived exactly."""


@dataclass(frozen=True, slots=True)
class _StartedDispatch:
    dispatch_id: str
    work_item_id: str
    token_reservation: int
    active_reservation: int
    provider_backed: bool


@dataclass(frozen=True, slots=True)
class BudgetDecisionV2:
    charged_tokens: int
    charged_active_ms: int
    trusted_observed_tokens: int
    trusted_observed_active_ms: int
    unknown_token_dispatches: int
    unknown_active_dispatches: int
    open_token_reservations: int
    open_active_ms_reservations: int
    token_limit: int | None
    active_ms_limit: int | None
    provider_attempts: Mapping[str, int]
    generation_attempts: Mapping[str, int]
    semantic_rounds: Mapping[str, int]
    result_contract_retries: Mapping[str, int]
    shared_retries: Mapping[str, int]
    artifact_contract_retries: Mapping[str, int]
    abandoned_dispatches: tuple[str, ...]
    reservation_breaches: tuple[str, ...]
    exhausted_dimensions: tuple[str, ...]
    provider_attempt_limit: int
    generation_attempt_limit: int
    semantic_round_limit: int
    result_contract_retry_limit: int
    shared_retry_limit: int
    artifact_contract_retry_limit: int
    retry_eligibility: Mapping[str, str]
    open_work_item_ids: frozenset[str]
    terminal_work_item_ids: frozenset[str]

    @property
    def token_coverage_complete(self) -> bool:
        return self.unknown_token_dispatches == 0

    @property
    def active_coverage_complete(self) -> bool:
        return self.unknown_active_dispatches == 0

    @property
    def resources_exhausted(self) -> bool:
        return any(
            value in {"tokens", "active_ms"}
            for value in self.exhausted_dimensions
        )

    @property
    def pause_required(self) -> bool:
        return not self.reservation_breaches and self.resources_exhausted

    @property
    def continuable(self) -> bool:
        return (
            not self.reservation_breaches
            and self.resources_exhausted
        )

    @property
    def allowed(self) -> bool:
        return not self.resources_exhausted and not self.reservation_breaches

    def item_attempt_available(self, work_item: WorkItemV2) -> bool:
        """Implement the graph planner's structural attempt-budget seam."""
        if not isinstance(work_item, WorkItemV2):
            raise ReV2BudgetV22Error(
                "item attempt availability requires WorkItemV2"
            )
        work_item_id = work_item.work_item_id
        if (
            not self.allowed
            or work_item_id in self.open_work_item_ids
            or work_item_id in self.terminal_work_item_ids
        ):
            return False
        generation_count = self.generation_attempts.get(work_item_id, 0)
        generation_limit = min(
            self.generation_attempt_limit,
            work_item.max_generation_attempts,
        )
        if generation_count >= generation_limit:
            return False
        if work_item.max_provider_attempts > 0:
            provider_limit = min(
                self.provider_attempt_limit,
                work_item.max_provider_attempts,
            )
            if self.provider_attempts.get(work_item_id, 0) >= provider_limit:
                return False
        if generation_count == 0:
            return True
        retry_kind = self.retry_eligibility.get(work_item_id)
        if retry_kind is None:
            return False
        if self.shared_retries.get(work_item_id, 0) >= min(
            self.shared_retry_limit,
            work_item.max_shared_retries,
        ):
            return False
        if retry_kind == "result_contract_retry":
            return self.result_contract_retries.get(work_item_id, 0) < min(
                self.result_contract_retry_limit,
                work_item.max_result_contract_retries,
            )
        if retry_kind == "artifact_contract_retry":
            return self.artifact_contract_retries.get(work_item_id, 0) < min(
                self.artifact_contract_retry_limit,
                work_item.max_artifact_contract_retries,
            )
        raise ReV2BudgetV22Error("replay produced unsupported retry eligibility")


def conservative_charge(
    value: int | None,
    status: UsageStatus | str,
    reservation: int,
) -> int:
    """Return the exact conservative charge for one usage observation."""
    reserved = _accounting(reservation, "reservation")
    if status not in _USAGE_STATUSES:
        raise ReV2BudgetV22Error("usage status is unsupported")
    if value is not None:
        observed = _accounting(value, "observed usage")
    else:
        observed = None
    if status == "trusted_exact":
        if observed is None:
            raise ReV2BudgetV22Error("trusted_exact usage requires a value")
        return observed
    if status == "unavailable":
        if observed is not None:
            raise ReV2BudgetV22Error("unavailable usage requires null")
        return reserved
    return max(reserved, 0 if observed is None else observed)


def evaluate_budget_v22(
    policy: BudgetPolicyV2,
    events: Iterable[EventRecord],
    open_dispatches: Iterable[str] | Mapping[str, object],
    now: str,
) -> BudgetDecisionV2:
    """Replay validated 2.2 events into conservative resource and attempt state."""
    if not isinstance(policy, BudgetPolicyV2):
        raise ReV2BudgetV22Error("policy must be BudgetPolicyV2")
    current_time = _timestamp(now, "now")
    try:
        history = validate_event_history(events, protocol=PROTOCOL_22_EVENTS)
    except ReV2EventError as exc:
        raise ReV2BudgetV22Error(
            f"validated protocol-2.2 EventRecord history required: {exc}"
        ) from exc
    for event in history:
        if current_time < _timestamp(event.occurred_at, "event occurred_at"):
            raise ReV2BudgetV22Error("now is before event history")

    token_limit = policy.token_limit
    active_limit = policy.active_ms_limit
    charged_tokens = 0
    charged_active = 0
    trusted_tokens = 0
    trusted_active = 0
    unknown_tokens = 0
    unknown_active = 0
    provider_attempts: dict[str, int] = {}
    generation_attempts: dict[str, int] = {}
    semantic_rounds: dict[str, int] = {}
    result_retries: dict[str, int] = {}
    shared_retries: dict[str, int] = {}
    artifact_retries: dict[str, int] = {}
    started: dict[str, _StartedDispatch] = {}
    abandoned: list[str] = []
    breaches: set[str] = set()

    for event in history:
        payload = event.payload
        if event.type == "budget_authorized":
            token_limit, active_limit = _apply_authorization(
                token_limit,
                active_limit,
                payload,
            )
        elif event.type == "dispatch_started":
            dispatch_id = str(payload["dispatch_id"])
            work_item_id = str(payload["work_item_id"])
            token_reservation = _accounting(
                payload["billable_token_reservation"],
                "billable token reservation",
            )
            active_reservation = _positive_accounting(
                payload["active_ms_reservation"],
                "active-ms reservation",
            )
            provider_backed = token_reservation > 0
            _increment(generation_attempts, work_item_id, "generation attempts")
            if provider_backed:
                _increment(provider_attempts, work_item_id, "provider attempts")
            kind = str(payload["attempt_kind"])
            if kind == "result_contract_retry":
                _increment(result_retries, work_item_id, "result retries")
                _increment(shared_retries, work_item_id, "shared retries")
            elif kind == "artifact_contract_retry":
                _increment(artifact_retries, work_item_id, "artifact retries")
                _increment(shared_retries, work_item_id, "shared retries")
            elif kind != "initial_generation":
                raise ReV2BudgetV22Error(
                    "validated history contains unsupported attempt kind"
                )
            if dispatch_id in started:
                raise ReV2BudgetV22Error("dispatch started more than once")
            started[dispatch_id] = _StartedDispatch(
                dispatch_id,
                work_item_id,
                token_reservation,
                active_reservation,
                provider_backed,
            )
        elif event.type == "dispatch_observed":
            dispatch_id = str(payload["dispatch_id"])
            dispatch = started.pop(dispatch_id, None)
            if dispatch is None:
                raise ReV2BudgetV22Error(
                    "observation has no open dispatch reservation"
                )
            token_value = payload["reported_token_usage"]
            token_status = str(payload["token_usage_status"])
            active_value = payload["observed_active_ms"]
            active_status = str(payload["active_usage_status"])
            token_charge = conservative_charge(
                token_value,
                token_status,
                dispatch.token_reservation,
            )
            active_charge = conservative_charge(
                active_value,
                active_status,
                dispatch.active_reservation,
            )
            charged_tokens = _add(charged_tokens, token_charge, "charged tokens")
            charged_active = _add(
                charged_active,
                active_charge,
                "charged active_ms",
            )
            if token_status == "trusted_exact":
                trusted_tokens = _add(
                    trusted_tokens,
                    _accounting(token_value, "trusted token usage"),
                    "trusted observed tokens",
                )
            else:
                unknown_tokens = _add(
                    unknown_tokens,
                    1,
                    "unknown token dispatches",
                )
            if active_status == "trusted_exact":
                trusted_active = _add(
                    trusted_active,
                    _accounting(active_value, "trusted active usage"),
                    "trusted observed active_ms",
                )
            else:
                unknown_active = _add(
                    unknown_active,
                    1,
                    "unknown active dispatches",
                )
            if (
                token_value is not None
                and _accounting(token_value, "reported token usage")
                > dispatch.token_reservation
            ) or (
                active_value is not None
                and _accounting(active_value, "observed active_ms")
                > dispatch.active_reservation
            ):
                breaches.add(dispatch_id)
        elif event.type == "dispatch_abandoned":
            dispatch_id = str(payload["dispatch_id"])
            dispatch = started.pop(dispatch_id, None)
            if dispatch is None:
                raise ReV2BudgetV22Error(
                    "abandonment has no open dispatch reservation"
                )
            charged_tokens = _add(
                charged_tokens,
                dispatch.token_reservation,
                "charged tokens",
            )
            charged_active = _add(
                charged_active,
                dispatch.active_reservation,
                "charged active_ms",
            )
            if dispatch.provider_backed:
                unknown_tokens = _add(
                    unknown_tokens,
                    1,
                    "unknown token dispatches",
                )
            unknown_active = _add(
                unknown_active,
                1,
                "unknown active dispatches",
            )
            abandoned.append(dispatch_id)

    expected_open = _open_dispatch_ids(open_dispatches)
    actual_open = frozenset(started)
    if expected_open != actual_open:
        raise ReV2BudgetV22Error(
            "open dispatch authority does not match event history"
        )
    open_token_reservations = 0
    open_active_reservations = 0
    for dispatch in started.values():
        charged_tokens = _add(
            charged_tokens,
            dispatch.token_reservation,
            "charged tokens",
        )
        charged_active = _add(
            charged_active,
            dispatch.active_reservation,
            "charged active_ms",
        )
        open_token_reservations = _add(
            open_token_reservations,
            dispatch.token_reservation,
            "open token reservations",
        )
        open_active_reservations = _add(
            open_active_reservations,
            dispatch.active_reservation,
            "open active_ms reservations",
        )
        if dispatch.provider_backed:
            unknown_tokens = _add(
                unknown_tokens,
                1,
                "unknown token dispatches",
            )
        unknown_active = _add(
            unknown_active,
            1,
            "unknown active dispatches",
        )

    exhausted = _exhausted_dimensions(
        charged_tokens,
        charged_active,
        token_limit,
        active_limit,
        policy,
        provider_attempts,
        generation_attempts,
        semantic_rounds,
        result_retries,
        shared_retries,
        artifact_retries,
    )
    replay_state = _protocol_state(history)
    terminal = frozenset(
        (*replay_state.accepted_work_items, *replay_state.failed_work_items)
    )
    return BudgetDecisionV2(
        charged_tokens=charged_tokens,
        charged_active_ms=charged_active,
        trusted_observed_tokens=trusted_tokens,
        trusted_observed_active_ms=trusted_active,
        unknown_token_dispatches=unknown_tokens,
        unknown_active_dispatches=unknown_active,
        open_token_reservations=open_token_reservations,
        open_active_ms_reservations=open_active_reservations,
        token_limit=token_limit,
        active_ms_limit=active_limit,
        provider_attempts=_freeze_counts(provider_attempts),
        generation_attempts=_freeze_counts(generation_attempts),
        semantic_rounds=_freeze_counts(semantic_rounds),
        result_contract_retries=_freeze_counts(result_retries),
        shared_retries=_freeze_counts(shared_retries),
        artifact_contract_retries=_freeze_counts(artifact_retries),
        abandoned_dispatches=tuple(sorted(abandoned)),
        reservation_breaches=tuple(sorted(breaches)),
        exhausted_dimensions=exhausted,
        provider_attempt_limit=policy.provider_attempt_limit,
        generation_attempt_limit=policy.artifact_generation_attempt_limit,
        semantic_round_limit=policy.semantic_repair_round_limit,
        result_contract_retry_limit=policy.result_contract_retry_limit,
        shared_retry_limit=policy.shared_retry_limit,
        artifact_contract_retry_limit=policy.artifact_contract_retry_limit,
        retry_eligibility=MappingProxyType(
            dict(sorted(replay_state.retry_eligibility.items()))
        ),
        open_work_item_ids=frozenset(
            dispatch.work_item_id for dispatch in started.values()
        ),
        terminal_work_item_ids=terminal,
    )


def _protocol_state(history: tuple[EventRecord, ...]) -> Protocol22ReplayState:
    state = Protocol22ReplayState()
    for event in history:
        state.consume(event)
    return state


def _apply_authorization(
    token_limit: int | None,
    active_limit: int | None,
    payload: Mapping[str, object],
) -> tuple[int | None, int | None]:
    dimension = str(payload["dimension"])
    current = token_limit if dimension == "tokens" else active_limit
    old = payload["old_value"]
    new = _positive_accounting(payload["new_value"], "authorized budget")
    if current is None:
        raise ReV2BudgetV22Error(
            "an unlimited resource cannot be replaced by finite authorization"
        )
    if old != current:
        raise ReV2BudgetV22Error(
            "budget authorization old_value does not match effective limit"
        )
    if new <= current:
        raise ReV2BudgetV22Error("budget authorization must increase its limit")
    if dimension == "tokens":
        return new, active_limit
    return token_limit, new


def _exhausted_dimensions(
    tokens: int,
    active_ms: int,
    token_limit: int | None,
    active_limit: int | None,
    policy: BudgetPolicyV2,
    provider_attempts: Mapping[str, int],
    generation_attempts: Mapping[str, int],
    semantic_rounds: Mapping[str, int],
    result_retries: Mapping[str, int],
    shared_retries: Mapping[str, int],
    artifact_retries: Mapping[str, int],
) -> tuple[str, ...]:
    exhausted: list[str] = []
    if token_limit is not None and tokens >= token_limit:
        exhausted.append("tokens")
    if active_limit is not None and active_ms >= active_limit:
        exhausted.append("active_ms")
    dimensions = (
        ("provider_attempts", provider_attempts, policy.provider_attempt_limit),
        (
            "generation_attempts",
            generation_attempts,
            policy.artifact_generation_attempt_limit,
        ),
        ("semantic_rounds", semantic_rounds, policy.semantic_repair_round_limit),
        (
            "result_contract_retries",
            result_retries,
            policy.result_contract_retry_limit,
        ),
        ("shared_retries", shared_retries, policy.shared_retry_limit),
        (
            "artifact_contract_retries",
            artifact_retries,
            policy.artifact_contract_retry_limit,
        ),
    )
    for name, counts, limit in dimensions:
        exhausted.extend(
            f"{name}:{work_item_id}"
            for work_item_id, count in sorted(counts.items())
            if count >= limit
        )
    return tuple(exhausted)


def _open_dispatch_ids(
    values: Iterable[str] | Mapping[str, object],
) -> frozenset[str]:
    raw = tuple(values.keys()) if isinstance(values, Mapping) else tuple(values)
    if any(not isinstance(value, str) or not value for value in raw):
        raise ReV2BudgetV22Error("open dispatch IDs must be nonempty strings")
    if len(raw) != len(set(raw)):
        raise ReV2BudgetV22Error("open dispatch IDs must be unique")
    return frozenset(raw)


def _timestamp(value: object, field_name: str) -> datetime:
    if not isinstance(value, str):
        raise ReV2BudgetV22Error(f"{field_name} must be an RFC3339 timestamp")
    try:
        parsed = datetime.fromisoformat(
            value[:-1] + "+00:00" if value.endswith("Z") else value
        )
    except ValueError as exc:
        raise ReV2BudgetV22Error(
            f"{field_name} must be an RFC3339 timestamp"
        ) from exc
    if parsed.tzinfo is None:
        raise ReV2BudgetV22Error(
            f"{field_name} must be an RFC3339 timestamp"
        )
    return parsed.astimezone(timezone.utc)


def _increment(counts: dict[str, int], key: str, field_name: str) -> None:
    counts[key] = _add(counts.get(key, 0), 1, field_name)


def _add(left: int, right: int, field_name: str) -> int:
    first = _accounting(left, field_name)
    second = _accounting(right, field_name)
    total = first + second
    if total > MAX_ACCOUNTING_VALUE:
        raise ReV2BudgetV22Error(
            f"{field_name} exceeds signed 64-bit accounting bounds"
        )
    return total


def _positive_accounting(value: object, field_name: str) -> int:
    result = _accounting(value, field_name)
    if result == 0:
        raise ReV2BudgetV22Error(f"{field_name} must be positive")
    return result


def _accounting(value: object, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ReV2BudgetV22Error(
            f"{field_name} must be a nonnegative integer"
        )
    if value > MAX_ACCOUNTING_VALUE:
        raise ReV2BudgetV22Error(
            f"{field_name} exceeds signed 64-bit accounting bounds"
        )
    return value


def _freeze_counts(values: Mapping[str, int]) -> Mapping[str, int]:
    return MappingProxyType(dict(sorted(values.items())))


__all__ = (
    "BudgetDecisionV2",
    "MAX_ACCOUNTING_VALUE",
    "ReV2BudgetV22Error",
    "UsageStatus",
    "conservative_charge",
    "evaluate_budget_v22",
)
