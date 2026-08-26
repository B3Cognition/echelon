"""Independent semantic resource and progress accounting for protocol 2.5."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Iterable, Mapping

from harness.re_v2.events import EventRecord, ReV2EventError, validate_event_history
from harness.re_v2.protocol_22.budget import MAX_ACCOUNTING_VALUE, conservative_charge
from harness.re_v2.protocol_22.provider import DispatchReservationV1

from .events import PROTOCOL_25_EVENTS, Protocol25ReplayState
from .model import SemanticClosurePolicyV1


class ReV2SemanticBudgetError(ValueError):
    """Raised when semantic accounting cannot be derived exactly."""


@dataclass(frozen=True, slots=True)
class InitialSemanticPoolReservationV1:
    billable_tokens: int
    active_ms: int
    target_count: int
    source_count: int


@dataclass(frozen=True, slots=True)
class TargetProgressReplayV1:
    rounds_by_target: Mapping[str, int]
    no_reduction_rounds_by_target: Mapping[str, int]
    unresolved_by_target: Mapping[str, frozenset[str]]


@dataclass(frozen=True, slots=True)
class SemanticBudgetDecisionV1:
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
    rounds_by_target: Mapping[str, int]
    no_reduction_rounds_by_target: Mapping[str, int]
    unresolved_by_target: Mapping[str, frozenset[str]]
    exhausted_dimensions: tuple[str, ...]
    reservation_breaches: tuple[str, ...]
    max_rounds_per_target: int
    consecutive_no_reduction_limit: int
    provider_attempt_limit: int
    contract_retry_limit: int

    @property
    def resources_exhausted(self) -> bool:
        return any(item in {"tokens", "active_ms"} for item in self.exhausted_dimensions)

    @property
    def pause_required(self) -> bool:
        return self.resources_exhausted and not self.reservation_breaches

    @property
    def allowed(self) -> bool:
        return not self.exhausted_dimensions and not self.reservation_breaches

    def can_reserve(self, reservation: DispatchReservationV1) -> bool:
        if not isinstance(reservation, DispatchReservationV1) or self.reservation_breaches:
            return False
        return _within_limit(
            self.charged_tokens, reservation.billable_tokens, self.token_limit
        ) and _within_limit(
            self.charged_active_ms, reservation.active_ms, self.active_ms_limit
        )


@dataclass(frozen=True, slots=True)
class _Started:
    tokens: int
    active_ms: int


def evaluate_semantic_budget(
    policy: SemanticClosurePolicyV1,
    events: Iterable[EventRecord],
    open_dispatches: Iterable[str] | Mapping[str, object] | None = None,
) -> SemanticBudgetDecisionV1:
    """Charge only L3 resolution, recheck, and composition-guard dispatches."""
    if not isinstance(policy, SemanticClosurePolicyV1):
        raise ReV2SemanticBudgetError("policy must be SemanticClosurePolicyV1")
    try:
        history = validate_event_history(tuple(events), protocol=PROTOCOL_25_EVENTS)
    except ReV2EventError as exc:
        raise ReV2SemanticBudgetError(
            f"validated protocol-2.5 EventRecord history required: {exc}"
        ) from exc

    started: dict[str, _Started] = {}
    semantic_dispatches: set[str] = set()
    observed: set[str] = set()
    abandoned: set[str] = set()
    token_limit = policy.token_limit
    active_limit = policy.active_ms_limit
    charged_tokens = 0
    charged_active = 0
    trusted_tokens = 0
    trusted_active = 0
    unknown_tokens = 0
    unknown_active = 0
    breaches: set[str] = set()

    for event in history:
        payload = event.payload
        if event.type == "dispatch_started":
            started[str(payload["dispatch_id"])] = _Started(
                _accounting(payload["billable_token_reservation"], "token reservation"),
                _accounting(payload["active_ms_reservation"], "active reservation"),
            )
        elif event.type in {
            "semantic_resolution_started",
            "closure_recheck_started",
            "source_composition_guard_started",
        }:
            dispatch_id = str(payload["dispatch_id"])
            if dispatch_id not in started:
                raise ReV2SemanticBudgetError(
                    "semantic dispatch classification has no shared reservation"
                )
            semantic_dispatches.add(dispatch_id)
        elif event.type == "dispatch_observed":
            dispatch_id = str(payload["dispatch_id"])
            observed.add(dispatch_id)
            if dispatch_id not in semantic_dispatches:
                continue
            reservation = started[dispatch_id]
            token_charge = conservative_charge(
                payload["reported_token_usage"],
                str(payload["token_usage_status"]),
                reservation.tokens,
            )
            active_charge = conservative_charge(
                payload["observed_active_ms"],
                str(payload["active_usage_status"]),
                reservation.active_ms,
            )
            charged_tokens = _add(charged_tokens, token_charge, "charged tokens")
            charged_active = _add(charged_active, active_charge, "charged active_ms")
            if payload["token_usage_status"] == "trusted_exact":
                trusted_tokens = _add(
                    trusted_tokens,
                    _accounting(payload["reported_token_usage"], "trusted tokens"),
                    "trusted tokens",
                )
            else:
                unknown_tokens = _add(unknown_tokens, 1, "unknown token dispatches")
            if payload["active_usage_status"] == "trusted_exact":
                trusted_active = _add(
                    trusted_active,
                    _accounting(payload["observed_active_ms"], "trusted active_ms"),
                    "trusted active_ms",
                )
            else:
                unknown_active = _add(unknown_active, 1, "unknown active dispatches")
            if (
                payload["reported_token_usage"] is not None
                and int(payload["reported_token_usage"]) > reservation.tokens
            ) or (
                payload["observed_active_ms"] is not None
                and int(payload["observed_active_ms"]) > reservation.active_ms
            ):
                breaches.add(dispatch_id)
        elif event.type == "dispatch_abandoned":
            dispatch_id = str(payload["dispatch_id"])
            abandoned.add(dispatch_id)
            if dispatch_id not in semantic_dispatches:
                continue
            reservation = started[dispatch_id]
            charged_tokens = _add(charged_tokens, reservation.tokens, "charged tokens")
            charged_active = _add(charged_active, reservation.active_ms, "charged active_ms")
            unknown_tokens = _add(unknown_tokens, 1, "unknown token dispatches")
            unknown_active = _add(unknown_active, 1, "unknown active dispatches")
        elif event.type == "semantic_budget_authorized":
            token_limit, active_limit = _apply_authorization(
                token_limit, active_limit, payload
            )

    actual_open = semantic_dispatches - observed - abandoned
    if open_dispatches is not None:
        raw_open = (
            tuple(open_dispatches.keys())
            if isinstance(open_dispatches, Mapping)
            else tuple(open_dispatches)
        )
        if frozenset(raw_open) != frozenset(actual_open):
            raise ReV2SemanticBudgetError(
                "open semantic dispatch authority does not match event history"
            )
    open_tokens = 0
    open_active = 0
    for dispatch_id in sorted(actual_open):
        reservation = started[dispatch_id]
        charged_tokens = _add(charged_tokens, reservation.tokens, "charged tokens")
        charged_active = _add(charged_active, reservation.active_ms, "charged active_ms")
        open_tokens = _add(open_tokens, reservation.tokens, "open token reservations")
        open_active = _add(open_active, reservation.active_ms, "open active reservations")
        unknown_tokens = _add(unknown_tokens, 1, "unknown token dispatches")
        unknown_active = _add(unknown_active, 1, "unknown active dispatches")

    replay = Protocol25ReplayState()
    for event in history:
        replay.consume(event)
    exhausted: list[str] = []
    if token_limit is not None and charged_tokens >= token_limit:
        exhausted.append("tokens")
    if active_limit is not None and charged_active >= active_limit:
        exhausted.append("active_ms")
    exhausted.extend(
        f"semantic_rounds:{target}"
        for target, count in sorted(replay.rounds_by_target.items())
        if count >= policy.max_rounds_per_target
    )
    exhausted.extend(
        f"semantic_plateau:{target}"
        for target, count in sorted(replay.no_reduction_rounds_by_target.items())
        if count >= policy.consecutive_no_reduction_limit
    )
    return SemanticBudgetDecisionV1(
        charged_tokens=charged_tokens,
        charged_active_ms=charged_active,
        trusted_observed_tokens=trusted_tokens,
        trusted_observed_active_ms=trusted_active,
        unknown_token_dispatches=unknown_tokens,
        unknown_active_dispatches=unknown_active,
        open_token_reservations=open_tokens,
        open_active_ms_reservations=open_active,
        token_limit=token_limit,
        active_ms_limit=active_limit,
        rounds_by_target=_freeze_ints(replay.rounds_by_target),
        no_reduction_rounds_by_target=_freeze_ints(
            replay.no_reduction_rounds_by_target
        ),
        unresolved_by_target=MappingProxyType(dict(sorted(replay.unresolved_by_target.items()))),
        exhausted_dimensions=tuple(exhausted),
        reservation_breaches=tuple(sorted(breaches)),
        max_rounds_per_target=policy.max_rounds_per_target,
        consecutive_no_reduction_limit=policy.consecutive_no_reduction_limit,
        provider_attempt_limit=policy.provider_attempt_limit,
        contract_retry_limit=policy.contract_retry_limit,
    )


def replay_target_progress(events: Iterable[EventRecord]) -> TargetProgressReplayV1:
    """Replay source-cycle progress without deriving provider resource charges."""
    try:
        history = validate_event_history(tuple(events), protocol=PROTOCOL_25_EVENTS)
    except ReV2EventError as exc:
        raise ReV2SemanticBudgetError(
            f"validated protocol-2.5 EventRecord history required: {exc}"
        ) from exc
    replay = Protocol25ReplayState()
    for event in history:
        replay.consume(event)
    return TargetProgressReplayV1(
        rounds_by_target=_freeze_ints(replay.rounds_by_target),
        no_reduction_rounds_by_target=_freeze_ints(
            replay.no_reduction_rounds_by_target
        ),
        unresolved_by_target=MappingProxyType(
            dict(sorted(replay.unresolved_by_target.items()))
        ),
    )


def initial_semantic_pool_reservation(
    target_cycles: Mapping[
        str, tuple[DispatchReservationV1, DispatchReservationV1]
    ],
    source_guards: Mapping[str, DispatchReservationV1],
) -> InitialSemanticPoolReservationV1:
    """Reserve one resolution/recheck per target and one guard per source."""
    if not isinstance(target_cycles, Mapping) or not isinstance(source_guards, Mapping):
        raise ReV2SemanticBudgetError("semantic initial reservation inputs must be mappings")
    reservations: list[DispatchReservationV1] = []
    for target, pair in target_cycles.items():
        if not isinstance(target, str) or not target or not isinstance(pair, tuple) or len(pair) != 2:
            raise ReV2SemanticBudgetError(
                "each target requires exactly one resolution and recheck reservation"
            )
        reservations.extend(pair)
    for source, reservation in source_guards.items():
        if not isinstance(source, str) or not source:
            raise ReV2SemanticBudgetError("source reservation IDs must be nonempty strings")
        reservations.append(reservation)
    if any(not isinstance(item, DispatchReservationV1) for item in reservations):
        raise ReV2SemanticBudgetError("semantic reservation must be DispatchReservationV1")
    tokens = 0
    active_ms = 0
    for reservation in reservations:
        # Unknown provider usage is reserved through the same shared conservative rule.
        tokens = _add(
            tokens,
            conservative_charge(None, "unavailable", reservation.billable_tokens),
            "initial semantic tokens",
        )
        active_ms = _add(
            active_ms,
            conservative_charge(None, "unavailable", reservation.active_ms),
            "initial semantic active_ms",
        )
    return InitialSemanticPoolReservationV1(
        billable_tokens=tokens,
        active_ms=active_ms,
        target_count=len(target_cycles),
        source_count=len(source_guards),
    )


def _apply_authorization(
    token_limit: int | None,
    active_limit: int | None,
    payload: Mapping[str, object],
) -> tuple[int | None, int | None]:
    dimension = str(payload["dimension"])
    current = token_limit if dimension == "tokens" else active_limit
    if current is None:
        raise ReV2SemanticBudgetError(
            "an unlimited semantic resource cannot become finite"
        )
    if payload["old_value"] != current:
        raise ReV2SemanticBudgetError(
            "semantic authorization old_value does not match effective limit"
        )
    new_value = _accounting(payload["new_value"], "semantic authorization")
    if new_value <= current:
        raise ReV2SemanticBudgetError("semantic authorization must increase its limit")
    if dimension == "tokens":
        return new_value, active_limit
    return token_limit, new_value


def _within_limit(current: int, reserved: int, limit: int | None) -> bool:
    return limit is None or current + reserved <= limit


def _accounting(value: object, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ReV2SemanticBudgetError(f"{field_name} must be a nonnegative integer")
    if value > MAX_ACCOUNTING_VALUE:
        raise ReV2SemanticBudgetError(
            f"{field_name} exceeds signed 64-bit accounting bounds"
        )
    return value


def _add(left: int, right: int, field_name: str) -> int:
    result = _accounting(left, field_name) + _accounting(right, field_name)
    if result > MAX_ACCOUNTING_VALUE:
        raise ReV2SemanticBudgetError(
            f"{field_name} exceeds signed 64-bit accounting bounds"
        )
    return result


def _freeze_ints(values: Mapping[str, int]) -> Mapping[str, int]:
    return MappingProxyType(dict(sorted(values.items())))


__all__ = (
    "InitialSemanticPoolReservationV1",
    "ReV2SemanticBudgetError",
    "SemanticBudgetDecisionV1",
    "TargetProgressReplayV1",
    "evaluate_semantic_budget",
    "initial_semantic_pool_reservation",
    "replay_target_progress",
)
