"""Independent conservative resource accounting for synthesis work."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Iterable, Mapping

from harness.re_v2.events import EventRecord, ReV2EventError, validate_event_history
from harness.re_v2.protocol_22.budget import (
    MAX_ACCOUNTING_VALUE,
    ReV2BudgetV22Error,
    conservative_charge,
)

from .events import PROTOCOL_27_EVENTS, Protocol27ReplayState
from .ledger import Protocol27LedgerView
from .model import RunManifestV6


class Protocol27BudgetError(ValueError):
    """Raised when synthesis resource authority cannot be replayed exactly."""


@dataclass(frozen=True, slots=True)
class _StartedDispatch:
    work_item_id: str
    token_reservation: int
    active_ms_reservation: int


@dataclass(frozen=True, slots=True)
class SynthesisBudgetDecisionV1:
    known_tokens: int
    known_active_ms: int
    charged_tokens: int
    charged_active_ms: int
    unknown_token_dispatches: int
    unknown_active_dispatches: int
    open_token_reservations: int
    open_active_ms_reservations: int
    provider_attempts_by_work_item: Mapping[str, int]
    result_contract_retries: Mapping[str, int]
    artifact_contract_retries: Mapping[str, int]
    abandoned_dispatch_ids: tuple[str, ...]
    reservation_breaches: tuple[str, ...]
    exhausted_dimensions: tuple[str, ...]
    token_limit: int | None
    active_ms_limit: int | None
    adopted_artifact_count: int
    accepted_artifact_count: int

    @property
    def provider_attempts(self) -> int:
        return sum(self.provider_attempts_by_work_item.values())

    @property
    def resources_exhausted(self) -> bool:
        return bool(self.exhausted_dimensions)

    @property
    def allowed(self) -> bool:
        return not self.resources_exhausted and not self.reservation_breaches


def evaluate_synthesis_budget(
    manifest: RunManifestV6,
    events: Iterable[EventRecord],
    ledger: Protocol27LedgerView,
) -> SynthesisBudgetDecisionV1:
    if not isinstance(manifest, RunManifestV6):
        raise Protocol27BudgetError("synthesis budget requires a schema-6 manifest")
    if not isinstance(ledger, Protocol27LedgerView):
        raise Protocol27BudgetError("synthesis budget requires a protocol-2.7 ledger view")
    try:
        history = validate_event_history(tuple(events), protocol=PROTOCOL_27_EVENTS)
    except ReV2EventError as exc:
        raise Protocol27BudgetError(
            f"validated protocol-2.7 EventRecord history required: {exc}"
        ) from exc
    replay = Protocol27ReplayState()
    for event in history:
        replay.consume(event)
    expected_partials = {
        item.source_id: item.receipt_id for item in manifest.partial_acceptances
    }
    if replay.request_id != manifest.request_id:
        raise Protocol27BudgetError("event history synthesis request differs from manifest")
    if replay.partial_acceptances != expected_partials:
        raise Protocol27BudgetError(
            "event history partial acceptances differ from manifest"
        )
    ledger_artifacts = {
        key: item.artifact_hash for key, item in ledger.accepted_artifacts.items()
    }
    if replay.accepted_artifacts != ledger_artifacts:
        raise Protocol27BudgetError(
            "event and ledger accepted synthesis authority disagree"
        )
    policy = manifest.budget_policy
    started: dict[str, _StartedDispatch] = {}
    observed: set[str] = set()
    abandoned: set[str] = set()
    attempts: dict[str, int] = {}
    result_retries: dict[str, int] = {}
    artifact_retries: dict[str, int] = {}
    known_tokens = 0
    known_active = 0
    charged_tokens = 0
    charged_active = 0
    unknown_tokens = 0
    unknown_active = 0
    breaches: set[str] = set()
    token_limit = policy.token_limit
    active_limit = policy.active_ms_limit

    for event in history:
        payload = event.payload
        if event.type == "dispatch_started":
            dispatch_id = str(payload["dispatch_id"])
            if dispatch_id in started:
                raise Protocol27BudgetError("duplicate synthesis dispatch charge")
            work_item_id = str(payload["work_item_id"])
            started[dispatch_id] = _StartedDispatch(
                work_item_id,
                _accounting(
                    payload["billable_token_reservation"],
                    "token reservation",
                ),
                _accounting(
                    payload["active_ms_reservation"],
                    "active_ms reservation",
                ),
            )
            attempts[work_item_id] = _increment(
                attempts.get(work_item_id, 0),
                "provider attempts",
            )
            if attempts[work_item_id] > policy.provider_attempt_limit:
                raise Protocol27BudgetError(
                    f"provider attempt limit exceeded: {work_item_id}"
                )
            if attempts[work_item_id] > policy.generation_attempt_limit:
                raise Protocol27BudgetError(
                    f"generation attempt limit exceeded: {work_item_id}"
                )
            attempt_kind = str(payload["attempt_kind"])
            if attempt_kind == "result_contract_retry":
                result_retries[work_item_id] = _increment(
                    result_retries.get(work_item_id, 0),
                    "result contract retries",
                )
                if (
                    result_retries[work_item_id]
                    > policy.result_contract_retry_limit
                ):
                    raise Protocol27BudgetError(
                        f"result contract retry limit exceeded: {work_item_id}"
                    )
            elif attempt_kind == "artifact_contract_retry":
                artifact_retries[work_item_id] = _increment(
                    artifact_retries.get(work_item_id, 0),
                    "artifact contract retries",
                )
                if (
                    artifact_retries[work_item_id]
                    > policy.artifact_contract_retry_limit
                ):
                    raise Protocol27BudgetError(
                        f"artifact contract retry limit exceeded: {work_item_id}"
                    )
        elif event.type == "dispatch_observed":
            dispatch_id = str(payload["dispatch_id"])
            dispatch = started.get(dispatch_id)
            if dispatch is None or dispatch_id in observed or dispatch_id in abandoned:
                raise Protocol27BudgetError(
                    "observed synthesis usage has no unique reservation"
                )
            observed.add(dispatch_id)
            token_charge = _conservative(
                payload["reported_token_usage"],
                str(payload["token_usage_status"]),
                dispatch.token_reservation,
            )
            active_charge = _conservative(
                payload["observed_active_ms"],
                str(payload["active_usage_status"]),
                dispatch.active_ms_reservation,
            )
            charged_tokens = _add(charged_tokens, token_charge, "charged tokens")
            charged_active = _add(charged_active, active_charge, "charged active_ms")
            if payload["token_usage_status"] == "trusted_exact":
                known_tokens = _add(
                    known_tokens,
                    _accounting(payload["reported_token_usage"], "known tokens"),
                    "known tokens",
                )
            else:
                unknown_tokens = _increment(unknown_tokens, "unknown token dispatches")
            if payload["active_usage_status"] == "trusted_exact":
                known_active = _add(
                    known_active,
                    _accounting(payload["observed_active_ms"], "known active_ms"),
                    "known active_ms",
                )
            else:
                unknown_active = _increment(
                    unknown_active,
                    "unknown active dispatches",
                )
            if (
                payload["reported_token_usage"] is not None
                and int(payload["reported_token_usage"]) > dispatch.token_reservation
            ) or (
                payload["observed_active_ms"] is not None
                and int(payload["observed_active_ms"])
                > dispatch.active_ms_reservation
            ):
                breaches.add(dispatch_id)
        elif event.type == "dispatch_abandoned":
            dispatch_id = str(payload["dispatch_id"])
            dispatch = started.get(dispatch_id)
            if dispatch is None or dispatch_id in observed or dispatch_id in abandoned:
                raise Protocol27BudgetError(
                    "abandoned synthesis dispatch has no unique reservation"
                )
            abandoned.add(dispatch_id)
            charged_tokens = _add(
                charged_tokens,
                dispatch.token_reservation,
                "charged tokens",
            )
            charged_active = _add(
                charged_active,
                dispatch.active_ms_reservation,
                "charged active_ms",
            )
            unknown_tokens = _increment(unknown_tokens, "unknown token dispatches")
            unknown_active = _increment(unknown_active, "unknown active dispatches")
        elif event.type == "synthesis_budget_authorized":
            token_limit, active_limit = _apply_authorization(
                token_limit,
                active_limit,
                payload,
            )

    open_dispatches = set(started) - observed - abandoned
    open_tokens = 0
    open_active = 0
    for dispatch_id in sorted(open_dispatches):
        dispatch = started[dispatch_id]
        charged_tokens = _add(
            charged_tokens,
            dispatch.token_reservation,
            "charged tokens",
        )
        charged_active = _add(
            charged_active,
            dispatch.active_ms_reservation,
            "charged active_ms",
        )
        open_tokens = _add(
            open_tokens,
            dispatch.token_reservation,
            "open token reservations",
        )
        open_active = _add(
            open_active,
            dispatch.active_ms_reservation,
            "open active_ms reservations",
        )
        unknown_tokens = _increment(unknown_tokens, "unknown token dispatches")
        unknown_active = _increment(unknown_active, "unknown active dispatches")

    exhausted = []
    if token_limit is not None and charged_tokens >= token_limit:
        exhausted.append("tokens")
    if active_limit is not None and charged_active >= active_limit:
        exhausted.append("active_ms")
    return SynthesisBudgetDecisionV1(
        known_tokens=known_tokens,
        known_active_ms=known_active,
        charged_tokens=charged_tokens,
        charged_active_ms=charged_active,
        unknown_token_dispatches=unknown_tokens,
        unknown_active_dispatches=unknown_active,
        open_token_reservations=open_tokens,
        open_active_ms_reservations=open_active,
        provider_attempts_by_work_item=_freeze_counts(attempts),
        result_contract_retries=_freeze_counts(result_retries),
        artifact_contract_retries=_freeze_counts(artifact_retries),
        abandoned_dispatch_ids=tuple(sorted(abandoned)),
        reservation_breaches=tuple(sorted(breaches)),
        exhausted_dimensions=tuple(exhausted),
        token_limit=token_limit,
        active_ms_limit=active_limit,
        adopted_artifact_count=len(ledger.checkpoint_adoptions),
        accepted_artifact_count=len(ledger.accepted_artifacts),
    )


def _apply_authorization(
    token_limit: int | None,
    active_limit: int | None,
    payload: Mapping[str, object],
) -> tuple[int | None, int | None]:
    dimension = str(payload["dimension"])
    old = token_limit if dimension == "tokens" else active_limit
    if payload["old_value"] != old:
        raise Protocol27BudgetError("synthesis budget authorization old value mismatch")
    new = _accounting(payload["new_value"], "authorized budget")
    if old is not None and new <= old:
        raise Protocol27BudgetError("synthesis budget authorization must increase its limit")
    return (new, active_limit) if dimension == "tokens" else (token_limit, new)


def _conservative(value: object, status: str, reservation: int) -> int:
    try:
        return conservative_charge(value, status, reservation)  # type: ignore[arg-type]
    except ReV2BudgetV22Error as exc:
        raise Protocol27BudgetError(str(exc)) from exc


def _accounting(value: object, field: str) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < 0
        or value > MAX_ACCOUNTING_VALUE
    ):
        raise Protocol27BudgetError(
            f"{field} must fit nonnegative signed 64-bit accounting"
        )
    return value


def _add(left: int, right: int, field: str) -> int:
    total = _accounting(left, field) + _accounting(right, field)
    if total > MAX_ACCOUNTING_VALUE:
        raise Protocol27BudgetError(f"{field} exceeds signed 64-bit accounting bounds")
    return total


def _increment(value: int, field: str) -> int:
    return _add(value, 1, field)


def _freeze_counts(values: Mapping[str, int]) -> Mapping[str, int]:
    return MappingProxyType(dict(sorted(values.items())))


__all__ = (
    "Protocol27BudgetError",
    "SynthesisBudgetDecisionV1",
    "evaluate_synthesis_budget",
)
