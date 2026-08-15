"""Pure, independent budget accounting for the RE v2 execution kernel."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import re
from types import MappingProxyType
from typing import Iterable, Mapping

from .canonical import content_digest
from .events import EventRecord, _validate_payload
from .model import BudgetPolicy, ExecutionObservation, ReV2ModelError


MAX_ACCOUNTING_VALUE = (1 << 63) - 1
_SAFE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]*\Z")
_DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")
_EVENT_RECORD_FIELDS = frozenset(
    {
        "schema_version",
        "seq",
        "previous_event_hash",
        "occurred_at",
        "type",
        "payload",
        "event_hash",
    }
)


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
    """Derived budget state; policy itself remains immutable."""

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
        """Resource-only exhaustion can be resumed with a valid authorization."""
        return bool(self.exhausted_dimensions) and all(
            dimension in {BudgetDimension.TOKENS.value, BudgetDimension.ACTIVE_MS.value}
            for dimension in self.exhausted_dimensions
        )

    @property
    def allowed(self) -> bool:
        return not self.exhausted_dimensions


def evaluate_budget(
    policy: BudgetPolicy,
    events: Iterable[EventRecord | Mapping[str, object]],
    *,
    now: str,
) -> BudgetDecision:
    """Replay validated execution facts into a dimension-specific budget view.

    ``dispatch_started`` is the sole provider-attempt authority,
    ``candidate_persisted`` the sole generation-attempt authority,
    ``candidate_rejected`` the current semantic-round authority, and an invalid
    ``dispatch_observed`` result contract the sole contract-retry authority.
    Tokens and provider-active time come only from ``dispatch_observed``.
    """
    _utc_timestamp(now, "now")
    limits = _initial_limits(policy)
    known_tokens = 0
    unknown_token_dispatches = 0
    active_ms = 0
    provider_attempts: dict[str, int] = {}
    generation_attempts: dict[str, int] = {}
    semantic_rounds: dict[str, int] = {}
    result_contract_retries: dict[str, int] = {}

    for event in events:
        event_type, payload = _event_fact(event)
        if event_type == "budget_authorized":
            _apply_authorization(limits, payload)
        elif event_type == "dispatch_started":
            _increment(provider_attempts, _work_item_id(payload), "provider attempts")
        elif event_type == "candidate_persisted":
            _increment(generation_attempts, _work_item_id(payload), "generation attempts")
        elif event_type == "candidate_rejected":
            _increment(semantic_rounds, _work_item_id(payload), "semantic rounds")
        elif event_type == "dispatch_observed":
            observation = _observation(payload)
            active_ms = _add(active_ms, observation.duration_ms, "active_ms")
            if observation.token_usage is None:
                unknown_token_dispatches = _add(
                    unknown_token_dispatches, 1, "unknown token dispatches"
                )
            else:
                known_tokens = _add(known_tokens, observation.token_usage, "known_tokens")
            if not observation.result_contract_valid:
                _increment(
                    result_contract_retries,
                    _work_item_id(payload),
                    "result contract retries",
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
        provider_attempt_limit=_require_limit(limits, BudgetDimension.PROVIDER_ATTEMPTS),
        generation_attempt_limit=_require_limit(limits, BudgetDimension.GENERATION_ATTEMPTS),
        semantic_round_limit=_require_limit(limits, BudgetDimension.SEMANTIC_ROUNDS),
        result_contract_retry_limit=_require_limit(
            limits, BudgetDimension.RESULT_CONTRACT_RETRIES
        ),
    )


def authorize_resource_increase(
    policy: BudgetPolicy,
    events: Iterable[EventRecord | Mapping[str, object]] = (),
    *,
    dimension: BudgetDimension | str,
    old_value: int | None,
    new_value: int,
    actor: str,
    reason: str,
) -> dict[str, object]:
    """Create one canonical ``budget_authorized`` EventStore fact.

    This function only validates and returns a fact; it never mutates
    ``BudgetPolicy``.  Existing authorization facts determine the effective
    limit that ``old_value`` must name.
    """
    selected = _resource_dimension(dimension)
    _safe_nonempty(actor, "actor")
    _nonempty(reason, "reason")
    _optional_limit(old_value, "old_value")
    _positive_accounting(new_value, "new_value")

    limits = _initial_limits(policy)
    for event in events:
        event_type, payload = _event_fact(event)
        if event_type == "budget_authorized":
            _apply_authorization(limits, payload)
    current = limits[selected]
    if old_value != current:
        raise ReV2BudgetError("old_value does not match the current effective limit")
    if current is not None and new_value <= current:
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


def _initial_limits(policy: BudgetPolicy) -> dict[BudgetDimension, int | None]:
    if not isinstance(policy, BudgetPolicy):
        raise ReV2BudgetError("policy must be a BudgetPolicy")
    return {
        BudgetDimension.TOKENS: _optional_limit(policy.token_limit, "token_limit"),
        BudgetDimension.ACTIVE_MS: _optional_limit(
            policy.active_ms_limit, "active_ms_limit"
        ),
        BudgetDimension.PROVIDER_ATTEMPTS: _accounting(
            policy.provider_attempt_limit, "provider_attempt_limit"
        ),
        BudgetDimension.GENERATION_ATTEMPTS: _accounting(
            policy.artifact_generation_attempt_limit,
            "artifact_generation_attempt_limit",
        ),
        BudgetDimension.SEMANTIC_ROUNDS: _accounting(
            policy.semantic_repair_round_limit, "semantic_repair_round_limit"
        ),
        BudgetDimension.RESULT_CONTRACT_RETRIES: _accounting(
            policy.result_contract_retry_limit, "result_contract_retry_limit"
        ),
    }


def _event_fact(event: EventRecord | Mapping[str, object]) -> tuple[str, Mapping[str, object]]:
    if isinstance(event, EventRecord):
        event_type, payload = event.type, event.payload
    elif isinstance(event, Mapping):
        keys = set(event)
        if keys == {"type", "payload"}:
            event_type, payload = event["type"], event["payload"]
        elif keys == _EVENT_RECORD_FIELDS:
            event_type, payload = _validate_full_event_record(event)
        else:
            raise ReV2BudgetError("event must be an EventRecord or a strict event fact")
    else:
        raise ReV2BudgetError("event must be an EventRecord or a mapping")
    if not isinstance(event_type, str) or not isinstance(payload, Mapping):
        raise ReV2BudgetError("event has malformed type or payload")
    try:
        _validate_payload(event_type, payload)
    except (TypeError, ValueError, RuntimeError) as exc:
        raise ReV2BudgetError(f"malformed {event_type!r} event: {exc}") from exc
    return event_type, payload


def _validate_full_event_record(event: Mapping[str, object]) -> tuple[object, object]:
    schema_version = event["schema_version"]
    seq = event["seq"]
    previous = event["previous_event_hash"]
    occurred_at = event["occurred_at"]
    event_type = event["type"]
    payload = event["payload"]
    event_hash = event["event_hash"]
    if schema_version != 1 or not isinstance(seq, int) or isinstance(seq, bool) or seq <= 0:
        raise ReV2BudgetError("event record has invalid schema_version or seq")
    _accounting(seq, "seq")
    if previous is not None and (not isinstance(previous, str) or not _DIGEST_RE.fullmatch(previous)):
        raise ReV2BudgetError("event record has invalid previous_event_hash")
    _utc_timestamp(occurred_at, "occurred_at")
    if not isinstance(payload, Mapping):
        raise ReV2BudgetError("event record payload must be an object")
    if not isinstance(event_hash, str) or not _DIGEST_RE.fullmatch(event_hash):
        raise ReV2BudgetError("event record has invalid event_hash")
    identity = {
        "occurred_at": occurred_at,
        "payload": dict(payload),
        "previous_event_hash": previous,
        "schema_version": schema_version,
        "seq": seq,
        "type": event_type,
    }
    if content_digest(identity) != event_hash:
        raise ReV2BudgetError("event record has invalid event_hash")
    return event_type, payload


def _observation(payload: Mapping[str, object]) -> ExecutionObservation:
    raw = payload.get("observation")
    try:
        observation = ExecutionObservation.from_json_dict(raw)
    except (ReV2ModelError, TypeError, ValueError) as exc:
        raise ReV2BudgetError(f"invalid observation: {exc}") from exc
    _accounting(observation.duration_ms, "duration_ms")
    if observation.token_usage is not None:
        _accounting(observation.token_usage, "token_usage")
    return observation


def _work_item_id(payload: Mapping[str, object]) -> str:
    value = payload.get("work_item_id")
    if not isinstance(value, str) or not _DIGEST_RE.fullmatch(value):
        raise ReV2BudgetError("work_item_id must be a lowercase sha256 digest")
    return value


def _apply_authorization(
    limits: dict[BudgetDimension, int | None], payload: Mapping[str, object]
) -> None:
    dimension = _resource_dimension(payload.get("dimension"))
    actor = payload.get("authorized_by")
    _safe_nonempty(actor, "authorized_by")
    reason = payload.get("reason")
    _nonempty(reason, "reason")
    old_value = payload.get("old_value")
    new_value = payload.get("new_value")
    _optional_limit(old_value, "old_value")
    _positive_accounting(new_value, "new_value")
    current = limits[dimension]
    if old_value != current:
        raise ReV2BudgetError("budget authorization old_value does not match effective limit")
    if current is not None and new_value <= current:
        raise ReV2BudgetError("budget authorization must increase the effective limit")
    limits[dimension] = new_value


def _exhausted_dimensions(
    *,
    known_tokens: int,
    active_ms: int,
    limits: Mapping[BudgetDimension, int | None],
    provider_attempts: Mapping[str, int],
    generation_attempts: Mapping[str, int],
    semantic_rounds: Mapping[str, int],
    result_contract_retries: Mapping[str, int],
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
        limit = _require_limit(limits, dimension)
        exhausted.extend(
            f"{dimension.value}:{work_item_id}"
            for work_item_id, count in sorted(counts.items())
            if count >= limit
        )
    return tuple(exhausted)


def _at_limit(value: int, limit: int | None) -> bool:
    return limit is not None and value >= limit


def _increment(counts: dict[str, int], work_item_id: str, label: str) -> None:
    counts[work_item_id] = _add(counts.get(work_item_id, 0), 1, label)


def _add(left: int, right: int, field: str) -> int:
    _accounting(left, field)
    _accounting(right, field)
    total = left + right
    if total > MAX_ACCOUNTING_VALUE:
        raise ReV2BudgetError(f"{field} exceeds signed 64-bit accounting bounds")
    return total


def _freeze_counts(counts: Mapping[str, int]) -> Mapping[str, int]:
    return MappingProxyType(dict(sorted(counts.items())))


def _require_limit(
    limits: Mapping[BudgetDimension, int | None], dimension: BudgetDimension
) -> int:
    value = limits[dimension]
    if value is None:
        raise ReV2BudgetError(f"{dimension.value} requires a finite limit")
    return value


def _resource_dimension(value: object) -> BudgetDimension:
    try:
        dimension = BudgetDimension(value)
    except (TypeError, ValueError) as exc:
        raise ReV2BudgetError("dimension must be a budget dimension") from exc
    if dimension not in {BudgetDimension.TOKENS, BudgetDimension.ACTIVE_MS}:
        raise ReV2BudgetError("only tokens or active_ms may be authorized")
    return dimension


def _optional_limit(value: object, field: str) -> int | None:
    if value is None:
        return None
    return _positive_accounting(value, field)


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


def _safe_nonempty(value: object, field: str) -> str:
    if not isinstance(value, str) or not _SAFE_ID_RE.fullmatch(value):
        raise ReV2BudgetError(f"{field} must be a nonempty safe ID")
    return value


def _nonempty(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ReV2BudgetError(f"{field} must be nonempty")
    return value


def _utc_timestamp(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ReV2BudgetError(f"{field} must be an RFC3339 UTC timestamp")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ReV2BudgetError(f"{field} must be an RFC3339 UTC timestamp") from exc
    if parsed.tzinfo != timezone.utc:
        raise ReV2BudgetError(f"{field} must be an RFC3339 UTC timestamp")
    return value


__all__ = (
    "MAX_ACCOUNTING_VALUE",
    "BudgetDecision",
    "BudgetDimension",
    "ReV2BudgetError",
    "authorize_resource_increase",
    "evaluate_budget",
)
