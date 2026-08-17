"""Pure, independent budget accounting for the RE v2 execution kernel."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from types import MappingProxyType
from typing import Iterable, Mapping

from .events import EventRecord, ReV2EventError, validate_event_history
from .model import BudgetPolicy, ExecutionObservation, ReV2ModelError


MAX_ACCOUNTING_VALUE = (1 << 63) - 1


class ReV2BudgetError(ValueError):
    """Raised when execution accounting cannot be derived safely."""


class BudgetDimension(str, Enum):
    """The six deliberately independent execution budget dimensions."""

    TOKENS = "tokens"
    ACTIVE_MS = "active_ms"
    PROVIDER_ATTEMPTS = "provider_attempts"
    GENERATION_ATTEMPTS = "generation_attempts"
    SEMANTIC_ROUNDS = "semantic_rounds"
    RESULT_CONTRACT_RETRIES = "result_contract_retries"


@dataclass(frozen=True, slots=True)
class BudgetDecision:
    known_tokens: int
    unknown_token_dispatches: int
    active_ms: int
    token_limit: int | None
    active_ms_limit: int | None
    provider_attempts: Mapping[str, int]
    generation_attempts: Mapping[str, int]
    semantic_rounds: Mapping[str, int]
    result_contract_retries: Mapping[str, int]
    exhausted_dimensions: tuple[str, ...]
    provider_attempt_limit: int
    generation_attempt_limit: int
    semantic_round_limit: int
    result_contract_retry_limit: int

    @property
    def token_coverage_complete(self) -> bool:
        return self.unknown_token_dispatches == 0

    @property
    def pause_required(self) -> bool:
        return any(
            dimension in {BudgetDimension.TOKENS.value, BudgetDimension.ACTIVE_MS.value}
            for dimension in self.exhausted_dimensions
        )

    @property
    def continuable(self) -> bool:
        return bool(self.exhausted_dimensions) and all(
            dimension in {BudgetDimension.TOKENS.value, BudgetDimension.ACTIVE_MS.value}
            for dimension in self.exhausted_dimensions
        )

    @property
    def allowed(self) -> bool:
        return not self.exhausted_dimensions


def evaluate_budget(
    policy: BudgetPolicy, events: Iterable[EventRecord], *, now: str
) -> BudgetDecision:
    """Replay one validated complete EventRecord history into budget state."""
    current_time = _timestamp(now, "now")
    history = _validated_history(events)
    limits = _initial_limits(policy)
    known_tokens = 0
    unknown_token_dispatches = 0
    active_ms = 0
    provider_attempts: dict[str, int] = {}
    generation_attempts: dict[str, int] = {}
    semantic_rounds: dict[str, int] = {}
    result_contract_retries: dict[str, int] = {}
    open_dispatches: dict[str, datetime] = {}

    for event in history:
        payload = event.payload
        if event.type == "budget_authorized":
            _apply_authorization(limits, payload)
        elif event.type == "dispatch_started":
            work_item_id = str(payload["work_item_id"])
            attempt_kind = str(payload["attempt_kind"])
            _increment(provider_attempts, work_item_id, "provider attempts")
            if attempt_kind == "initial_generation":
                _increment(generation_attempts, work_item_id, "generation attempts")
            elif attempt_kind == "semantic_repair":
                _increment(generation_attempts, work_item_id, "generation attempts")
                _increment(semantic_rounds, work_item_id, "semantic rounds")
            elif attempt_kind == "result_contract_retry":
                _increment(result_contract_retries, work_item_id, "result contract retries")
            else:  # Defensive; the shared validator has already rejected this.
                raise ReV2BudgetError("validated history has an invalid attempt kind")
            started_at = _timestamp(event.occurred_at, "dispatch_started occurred_at")
            if current_time < started_at:
                raise ReV2BudgetError("now is before dispatch_started")
            open_dispatches[str(payload["dispatch_id"])] = started_at
        elif event.type == "dispatch_observed":
            dispatch_id = str(payload["dispatch_id"])
            started_at = open_dispatches.pop(dispatch_id, None)
            if started_at is None:
                raise ReV2BudgetError("validated history observes an unopened dispatch")
            observation = _observation(payload)
            active_ms = _add(active_ms, observation.duration_ms, "active_ms")
            if observation.token_usage is None:
                unknown_token_dispatches = _add(
                    unknown_token_dispatches, 1, "unknown token dispatches"
                )
            else:
                known_tokens = _add(known_tokens, observation.token_usage, "known_tokens")

    for started_at in open_dispatches.values():
        if current_time < started_at:
            raise ReV2BudgetError("now is before dispatch_started")
        active_ms = _add(
            active_ms, _elapsed_ms(started_at, current_time), "active_ms"
        )

    exhausted = _exhausted_dimensions(
        known_tokens=known_tokens,
        active_ms=active_ms,
        limits=limits,
        provider_attempts=provider_attempts,
        generation_attempts=generation_attempts,
        semantic_rounds=semantic_rounds,
        result_contract_retries=result_contract_retries,
    )
    return BudgetDecision(
        known_tokens=known_tokens,
        unknown_token_dispatches=unknown_token_dispatches,
        active_ms=active_ms,
        token_limit=limits[BudgetDimension.TOKENS],
        active_ms_limit=limits[BudgetDimension.ACTIVE_MS],
        provider_attempts=_freeze_counts(provider_attempts),
        generation_attempts=_freeze_counts(generation_attempts),
        semantic_rounds=_freeze_counts(semantic_rounds),
        result_contract_retries=_freeze_counts(result_contract_retries),
        exhausted_dimensions=exhausted,
        provider_attempt_limit=_finite_limit(limits, BudgetDimension.PROVIDER_ATTEMPTS),
        generation_attempt_limit=_finite_limit(limits, BudgetDimension.GENERATION_ATTEMPTS),
        semantic_round_limit=_finite_limit(limits, BudgetDimension.SEMANTIC_ROUNDS),
        result_contract_retry_limit=_finite_limit(
            limits, BudgetDimension.RESULT_CONTRACT_RETRIES
        ),
    )


def authorize_resource_increase(
    policy: BudgetPolicy,
    events: Iterable[EventRecord] = (),
    *,
    dimension: BudgetDimension | str,
    old_value: int | None,
    new_value: int,
    actor: str,
    reason: str,
) -> dict[str, object]:
    """Return one canonical EventStore ``budget_authorized`` fact, never mutate policy."""
    selected = _resource_dimension(dimension)
    _safe_actor(actor)
    _nonempty(reason, "reason")
    _optional_limit(old_value, "old_value")
    _positive_accounting(new_value, "new_value")

    limits = _initial_limits(policy)
    for event in _validated_history(events):
        if event.type == "budget_authorized":
            _apply_authorization(limits, event.payload)
    current = limits[selected]
    if current is None:
        raise ReV2BudgetError("an unlimited resource limit cannot be authorized to a finite value")
    if old_value != current:
        raise ReV2BudgetError("old_value does not match the current effective limit")
    if new_value <= current:
        raise ReV2BudgetError("new_value must be an increase over old_value")
    return {
        "type": "budget_authorized",
        "payload": {
            "authorized_by": actor,
            "dimension": selected.value,
            "new_value": new_value,
            "old_value": old_value,
            "reason": reason,
        },
    }


def _validated_history(events: Iterable[EventRecord]) -> tuple[EventRecord, ...]:
    try:
        return validate_event_history(events)
    except ReV2EventError as exc:
        raise ReV2BudgetError(f"validated EventRecord history required: {exc}") from exc


def _initial_limits(policy: BudgetPolicy) -> dict[BudgetDimension, int | None]:
    if not isinstance(policy, BudgetPolicy):
        raise ReV2BudgetError("policy must be a BudgetPolicy")
    return {
        BudgetDimension.TOKENS: _optional_limit(policy.token_limit, "token_limit"),
        BudgetDimension.ACTIVE_MS: _optional_limit(policy.active_ms_limit, "active_ms_limit"),
        BudgetDimension.PROVIDER_ATTEMPTS: _accounting(policy.provider_attempt_limit, "provider_attempt_limit"),
        BudgetDimension.GENERATION_ATTEMPTS: _accounting(policy.artifact_generation_attempt_limit, "artifact_generation_attempt_limit"),
        BudgetDimension.SEMANTIC_ROUNDS: _accounting(policy.semantic_repair_round_limit, "semantic_repair_round_limit"),
        BudgetDimension.RESULT_CONTRACT_RETRIES: _accounting(policy.result_contract_retry_limit, "result_contract_retry_limit"),
    }


def _apply_authorization(
    limits: dict[BudgetDimension, int | None], payload: Mapping[str, object]
) -> None:
    selected = _resource_dimension(payload["dimension"])
    _safe_actor(payload["authorized_by"])
    _nonempty(payload["reason"], "reason")
    old_value = payload["old_value"]
    new_value = _positive_accounting(payload["new_value"], "new_value")
    _optional_limit(old_value, "old_value")
    current = limits[selected]
    if current is None:
        raise ReV2BudgetError("an unlimited resource limit cannot be authorized to a finite value")
    if old_value != current:
        raise ReV2BudgetError("budget authorization old_value does not match effective limit")
    if new_value <= current:
        raise ReV2BudgetError("budget authorization must increase the effective limit")
    limits[selected] = new_value


def _observation(payload: Mapping[str, object]) -> ExecutionObservation:
    try:
        observation = ExecutionObservation.from_json_dict(payload["observation"])
    except (KeyError, ReV2ModelError, TypeError, ValueError) as exc:
        raise ReV2BudgetError(f"invalid observation: {exc}") from exc
    _accounting(observation.duration_ms, "duration_ms")
    if observation.token_usage is not None:
        _accounting(observation.token_usage, "token_usage")
    return observation


def _exhausted_dimensions(
    *, known_tokens: int, active_ms: int, limits: Mapping[BudgetDimension, int | None],
    provider_attempts: Mapping[str, int], generation_attempts: Mapping[str, int],
    semantic_rounds: Mapping[str, int], result_contract_retries: Mapping[str, int],
) -> tuple[str, ...]:
    exhausted: list[str] = []
    if _at_limit(known_tokens, limits[BudgetDimension.TOKENS]):
        exhausted.append(BudgetDimension.TOKENS.value)
    if _at_limit(active_ms, limits[BudgetDimension.ACTIVE_MS]):
        exhausted.append(BudgetDimension.ACTIVE_MS.value)
    for dimension, counts in (
        (BudgetDimension.PROVIDER_ATTEMPTS, provider_attempts),
        (BudgetDimension.GENERATION_ATTEMPTS, generation_attempts),
        (BudgetDimension.SEMANTIC_ROUNDS, semantic_rounds),
        (BudgetDimension.RESULT_CONTRACT_RETRIES, result_contract_retries),
    ):
        limit = _finite_limit(limits, dimension)
        exhausted.extend(
            f"{dimension.value}:{work_item_id}"
            for work_item_id, count in sorted(counts.items())
            if count >= limit
        )
    return tuple(exhausted)


def _timestamp(value: object, field: str) -> datetime:
    if not isinstance(value, str):
        raise ReV2BudgetError(f"{field} must be an RFC3339 timestamp")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError as exc:
        raise ReV2BudgetError(f"{field} must be an RFC3339 timestamp") from exc
    if parsed.tzinfo is None:
        raise ReV2BudgetError(f"{field} must be an RFC3339 timestamp")
    return parsed.astimezone(timezone.utc)


def _elapsed_ms(started_at: datetime, now: datetime) -> int:
    delta = now - started_at
    milliseconds = delta.days * 86_400_000 + delta.seconds * 1_000 + delta.microseconds // 1_000
    return _accounting(milliseconds, "open provider active_ms")


def _at_limit(value: int, limit: int | None) -> bool:
    return limit is not None and value >= limit


def _increment(counts: dict[str, int], work_item_id: str, field: str) -> None:
    counts[work_item_id] = _add(counts.get(work_item_id, 0), 1, field)


def _add(left: int, right: int, field: str) -> int:
    _accounting(left, field)
    _accounting(right, field)
    total = left + right
    if total > MAX_ACCOUNTING_VALUE:
        raise ReV2BudgetError(f"{field} exceeds signed 64-bit accounting bounds")
    return total


def _freeze_counts(counts: Mapping[str, int]) -> Mapping[str, int]:
    return MappingProxyType(dict(sorted(counts.items())))


def _finite_limit(limits: Mapping[BudgetDimension, int | None], dimension: BudgetDimension) -> int:
    value = limits[dimension]
    if value is None:
        raise ReV2BudgetError(f"{dimension.value} requires a finite limit")
    return value


def _resource_dimension(value: object) -> BudgetDimension:
    try:
        selected = BudgetDimension(value)
    except (TypeError, ValueError) as exc:
        raise ReV2BudgetError("dimension must be a budget dimension") from exc
    if selected not in {BudgetDimension.TOKENS, BudgetDimension.ACTIVE_MS}:
        raise ReV2BudgetError("only tokens or active_ms may be authorized")
    return selected


def _optional_limit(value: object, field: str) -> int | None:
    return None if value is None else _positive_accounting(value, field)


def _positive_accounting(value: object, field: str) -> int:
    result = _accounting(value, field)
    if result == 0:
        raise ReV2BudgetError(f"{field} must be positive")
    return result


def _accounting(value: object, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ReV2BudgetError(f"{field} must be a nonnegative integer")
    if value > MAX_ACCOUNTING_VALUE:
        raise ReV2BudgetError(f"{field} exceeds signed 64-bit accounting bounds")
    return value


def _safe_actor(value: object) -> str:
    if not isinstance(value, str) or not value or not value[0].isalnum() or not all(
        char.isalnum() or char in "._:-" for char in value
    ):
        raise ReV2BudgetError("actor must be a nonempty safe ID")
    return value


def _nonempty(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ReV2BudgetError(f"{field} must be nonempty")
    return value


__all__ = (
    "MAX_ACCOUNTING_VALUE", "BudgetDecision", "BudgetDimension", "ReV2BudgetError",
    "authorize_resource_increase", "evaluate_budget",
)
