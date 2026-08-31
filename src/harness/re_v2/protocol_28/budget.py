"""Protocol-2.8 paired reservations and role-aware resource accounting."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal, Mapping

from harness.re_v2.canonical import content_digest
from harness.re_v2.protocol_22.budget import MAX_ACCOUNTING_VALUE, conservative_charge
from harness.re_v2.protocol_22.provider import DispatchReservationV1
from harness.re_v2.protocol_22.schema import digest_value, safe_id
from harness.re_v2.protocol_28.model import ExhaustiveBudgetPolicyV1


Role = Literal["producer", "verifier"]
UsageStatus = Literal["trusted_exact", "unavailable", "untrusted"]
_USAGE_STATUSES = frozenset({"trusted_exact", "unavailable", "untrusted"})


class Protocol28BudgetError(ValueError):
    """Raised when paired L4 capacity or accounting authority is invalid."""


def _reservation_dict(value: DispatchReservationV1) -> dict[str, int]:
    if not isinstance(value, DispatchReservationV1):
        raise Protocol28BudgetError("reservation must be DispatchReservationV1")
    return {
        "initial_input_tokens": value.initial_input_tokens,
        "billable_tokens": value.billable_tokens,
        "active_ms": value.active_ms,
    }


def _identity(value: object) -> str:
    return content_digest(value)


@dataclass(frozen=True, slots=True)
class PairedReservationPreviewV1:
    ledger_prefix_id: str
    pair_work_id: str
    slice_spec_id: str
    producer_attempt_number: int
    producer_reservation: DispatchReservationV1
    verifier_reservation: DispatchReservationV1
    allowed: bool
    exhausted_dimensions: tuple[str, ...]

    @property
    def total_tokens(self) -> int:
        return _add(
            self.producer_reservation.billable_tokens,
            self.verifier_reservation.billable_tokens,
            "paired token reservation",
        )

    @property
    def total_active_ms(self) -> int:
        return _add(
            self.producer_reservation.active_ms,
            self.verifier_reservation.active_ms,
            "paired active_ms reservation",
        )


@dataclass(frozen=True, slots=True)
class PairedReservationCommitV1:
    schema_version: int
    pair_work_id: str
    slice_spec_id: str
    producer_attempt_number: int
    producer_dispatch_id: str
    verifier_dispatch_id: str
    producer_reservation: DispatchReservationV1
    verifier_reservation: DispatchReservationV1

    def __post_init__(self) -> None:
        if self.schema_version != 1 or isinstance(self.schema_version, bool):
            raise Protocol28BudgetError("paired reservation schema_version must be 1")
        for value, field in (
            (self.pair_work_id, "pair_work_id"),
            (self.slice_spec_id, "slice_spec_id"),
        ):
            try:
                digest_value(value, field)
            except ValueError as exc:
                raise Protocol28BudgetError(str(exc)) from exc
        if (
            not isinstance(self.producer_attempt_number, int)
            or isinstance(self.producer_attempt_number, bool)
            or not 1 <= self.producer_attempt_number <= 3
        ):
            raise Protocol28BudgetError("producer attempt number must be in [1, 3]")
        for value, field in (
            (self.producer_dispatch_id, "producer_dispatch_id"),
            (self.verifier_dispatch_id, "verifier_dispatch_id"),
        ):
            try:
                safe_id(value, field)
            except ValueError as exc:
                raise Protocol28BudgetError(str(exc)) from exc
        if self.producer_dispatch_id == self.verifier_dispatch_id:
            raise Protocol28BudgetError("paired dispatch IDs must be distinct")
        _reservation_dict(self.producer_reservation)
        _reservation_dict(self.verifier_reservation)

    @property
    def identity(self) -> str:
        return _identity(self.to_json_dict())

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "pair_work_id": self.pair_work_id,
            "slice_spec_id": self.slice_spec_id,
            "producer_attempt_number": self.producer_attempt_number,
            "producer_dispatch_id": self.producer_dispatch_id,
            "verifier_dispatch_id": self.verifier_dispatch_id,
            "producer_reservation": _reservation_dict(self.producer_reservation),
            "verifier_reservation": _reservation_dict(self.verifier_reservation),
        }


@dataclass(frozen=True, slots=True)
class VerifierRetryPreviewV1:
    ledger_prefix_id: str
    retry_work_id: str
    slice_spec_id: str
    producer_attempt_number: int
    verifier_reservation: DispatchReservationV1
    allowed: bool
    exhausted_dimensions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class VerifierRetryReservationV1:
    schema_version: int
    retry_work_id: str
    slice_spec_id: str
    producer_attempt_number: int
    dispatch_id: str
    verifier_reservation: DispatchReservationV1

    def __post_init__(self) -> None:
        if self.schema_version != 1 or isinstance(self.schema_version, bool):
            raise Protocol28BudgetError("verifier retry schema_version must be 1")
        for value, field in (
            (self.retry_work_id, "retry_work_id"),
            (self.slice_spec_id, "slice_spec_id"),
        ):
            try:
                digest_value(value, field)
            except ValueError as exc:
                raise Protocol28BudgetError(str(exc)) from exc
        if (
            not isinstance(self.producer_attempt_number, int)
            or isinstance(self.producer_attempt_number, bool)
            or not 1 <= self.producer_attempt_number <= 3
        ):
            raise Protocol28BudgetError("verifier retry producer attempt must be in [1, 3]")
        try:
            safe_id(self.dispatch_id, "dispatch_id")
        except ValueError as exc:
            raise Protocol28BudgetError(str(exc)) from exc
        _reservation_dict(self.verifier_reservation)

    @property
    def identity(self) -> str:
        return _identity(self.to_json_dict())

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "retry_work_id": self.retry_work_id,
            "slice_spec_id": self.slice_spec_id,
            "producer_attempt_number": self.producer_attempt_number,
            "dispatch_id": self.dispatch_id,
            "verifier_reservation": _reservation_dict(self.verifier_reservation),
        }


@dataclass(frozen=True, slots=True)
class ResourceObservationV1:
    dispatch_id: str
    token_status: UsageStatus
    billable_tokens: int | None
    active_status: UsageStatus
    active_ms: int | None

    def to_json_dict(self) -> dict[str, object]:
        return {
            "type": "observation",
            "dispatch_id": self.dispatch_id,
            "token_status": self.token_status,
            "billable_tokens": self.billable_tokens,
            "active_status": self.active_status,
            "active_ms": self.active_ms,
        }


@dataclass(frozen=True, slots=True)
class ResourceAbandonmentV1:
    dispatch_id: str

    def to_json_dict(self) -> dict[str, object]:
        return {"type": "abandonment", "dispatch_id": self.dispatch_id}


@dataclass(frozen=True, slots=True)
class VerifierReleaseV1:
    pair_id: str
    reason: Literal["producer_contract_failure", "producer_abandoned"]

    def to_json_dict(self) -> dict[str, object]:
        return {"type": "verifier_release", "pair_id": self.pair_id, "reason": self.reason}


@dataclass(frozen=True, slots=True)
class BudgetAuthorizationV1:
    dimension: Literal["tokens", "active_ms"]
    old_value: int
    new_value: int

    def to_json_dict(self) -> dict[str, object]:
        return {
            "type": "authorization",
            "dimension": self.dimension,
            "old_value": self.old_value,
            "new_value": self.new_value,
        }


@dataclass(frozen=True, slots=True)
class AdoptionAccountingV1:
    slice_spec_id: str
    producer_reservation: DispatchReservationV1
    verifier_reservation: DispatchReservationV1

    def to_json_dict(self) -> dict[str, object]:
        return {
            "type": "adoption",
            "slice_spec_id": self.slice_spec_id,
            "producer_reservation": _reservation_dict(self.producer_reservation),
            "verifier_reservation": _reservation_dict(self.verifier_reservation),
        }


ResourceRecordV1 = (
    PairedReservationCommitV1
    | VerifierRetryReservationV1
    | ResourceObservationV1
    | ResourceAbandonmentV1
    | VerifierReleaseV1
    | BudgetAuthorizationV1
    | AdoptionAccountingV1
)


@dataclass(frozen=True, slots=True)
class L4ResourceDecisionV1:
    charged_tokens: int
    charged_active_ms: int
    trusted_observed_tokens: int
    trusted_observed_active_ms: int
    open_token_reservations: int
    open_active_ms_reservations: int
    token_limit: int | None
    active_ms_limit: int | None
    unknown_token_dispatches_by_role: Mapping[str, int]
    unknown_active_dispatches_by_role: Mapping[str, int]
    generated_dispatches_by_role: Mapping[str, int]
    avoided_dispatches_by_role: Mapping[str, int]
    adopted_slices: int
    avoided_tokens: int
    avoided_active_ms: int
    exhausted_dimensions: tuple[str, ...]
    reservation_breaches: tuple[str, ...]
    producer_attempt_limit: int
    verifier_contract_retry_limit: int

    @property
    def resources_exhausted(self) -> bool:
        return bool(self.exhausted_dimensions)

    @property
    def pause_required(self) -> bool:
        return self.resources_exhausted and not self.reservation_breaches


@dataclass(slots=True)
class _OpenDispatch:
    role: Role
    reservation: DispatchReservationV1
    pair_id: str


class L4ResourceLedger:
    """Controller-local append-only accounting with atomic pair commits."""

    def __init__(self, policy: ExhaustiveBudgetPolicyV1) -> None:
        if not isinstance(policy, ExhaustiveBudgetPolicyV1):
            raise Protocol28BudgetError("resource ledger requires ExhaustiveBudgetPolicyV1")
        self.policy = policy
        self._records: list[ResourceRecordV1] = []

    @classmethod
    def from_records(
        cls,
        policy: ExhaustiveBudgetPolicyV1,
        records: tuple[ResourceRecordV1, ...],
    ) -> "L4ResourceLedger":
        if not isinstance(records, (list, tuple)):
            raise Protocol28BudgetError("resource records must be an array")
        allowed = (
            PairedReservationCommitV1,
            VerifierRetryReservationV1,
            ResourceObservationV1,
            ResourceAbandonmentV1,
            VerifierReleaseV1,
            BudgetAuthorizationV1,
            AdoptionAccountingV1,
        )
        copied = tuple(records)
        if any(not isinstance(record, allowed) for record in copied):
            raise Protocol28BudgetError("resource record type is invalid")
        ledger = cls(policy)
        ledger._records.extend(copied)
        # Both projections validate prefix order, dispatch lifecycle, authorization,
        # and accounting bounds before replayed authority is exposed.
        _replay_open(ledger.records)
        _evaluate(policy, ledger.records)
        return ledger

    @property
    def records(self) -> tuple[ResourceRecordV1, ...]:
        return tuple(self._records)

    @property
    def prefix_id(self) -> str:
        return _identity([record.to_json_dict() for record in self._records])

    @property
    def decision(self) -> L4ResourceDecisionV1:
        return _evaluate(self.policy, self.records)

    def preview_pair(
        self,
        slice_spec_id: str,
        producer_attempt_number: int,
        producer_reservation: DispatchReservationV1,
        verifier_reservation: DispatchReservationV1,
    ) -> PairedReservationPreviewV1:
        try:
            digest_value(slice_spec_id, "slice_spec_id")
        except ValueError as exc:
            raise Protocol28BudgetError(str(exc)) from exc
        if (
            not isinstance(producer_attempt_number, int)
            or isinstance(producer_attempt_number, bool)
            or not 1 <= producer_attempt_number <= self.policy.producer_attempt_limit
        ):
            raise Protocol28BudgetError("producer attempt number exceeds fixed policy")
        producer = _reservation_dict(producer_reservation)
        verifier = _reservation_dict(verifier_reservation)
        work = {
            "slice_spec_id": slice_spec_id,
            "producer_attempt_number": producer_attempt_number,
            "producer_reservation": producer,
            "verifier_reservation": verifier,
        }
        pair_work_id = _identity(work)
        decision = self.decision
        total_tokens = _add(
            producer_reservation.billable_tokens,
            verifier_reservation.billable_tokens,
            "paired token reservation",
        )
        total_active = _add(
            producer_reservation.active_ms,
            verifier_reservation.active_ms,
            "paired active_ms reservation",
        )
        exhausted: list[str] = []
        if decision.token_limit is not None and _add(
            decision.charged_tokens, total_tokens, "projected tokens"
        ) > decision.token_limit:
            exhausted.append("tokens")
        if decision.active_ms_limit is not None and _add(
            decision.charged_active_ms, total_active, "projected active_ms"
        ) > decision.active_ms_limit:
            exhausted.append("active_ms")
        return PairedReservationPreviewV1(
            self.prefix_id,
            pair_work_id,
            slice_spec_id,
            producer_attempt_number,
            producer_reservation,
            verifier_reservation,
            not exhausted and not decision.reservation_breaches,
            tuple(exhausted),
        )

    def commit_pair(
        self,
        preview: PairedReservationPreviewV1,
        *,
        producer_dispatch_id: str,
        verifier_dispatch_id: str,
    ) -> PairedReservationCommitV1:
        if not isinstance(preview, PairedReservationPreviewV1):
            raise Protocol28BudgetError("pair commit requires a paired reservation preview")
        if preview.ledger_prefix_id != self.prefix_id:
            raise Protocol28BudgetError("paired reservation preview has stale ledger prefix")
        if not preview.allowed:
            raise Protocol28BudgetError("paired reservation is not affordable")
        # Re-preview under the exact current prefix so authorization/accounting
        # cannot be changed between the affordability check and atomic append.
        current = self.preview_pair(
            preview.slice_spec_id,
            preview.producer_attempt_number,
            preview.producer_reservation,
            preview.verifier_reservation,
        )
        if current != preview or not current.allowed:
            raise Protocol28BudgetError("paired reservation preview no longer matches authority")
        used_dispatches = {
            dispatch_id
            for record in self._records
            if isinstance(record, PairedReservationCommitV1)
            for dispatch_id in (record.producer_dispatch_id, record.verifier_dispatch_id)
        }
        if producer_dispatch_id in used_dispatches or verifier_dispatch_id in used_dispatches:
            raise Protocol28BudgetError("paired reservation dispatch ID already exists")
        record = PairedReservationCommitV1(
            1,
            preview.pair_work_id,
            preview.slice_spec_id,
            preview.producer_attempt_number,
            producer_dispatch_id,
            verifier_dispatch_id,
            preview.producer_reservation,
            preview.verifier_reservation,
        )
        self._records.append(record)
        return record

    def observe(
        self,
        dispatch_id: str,
        *,
        token_status: UsageStatus,
        billable_tokens: int | None,
        active_status: UsageStatus,
        active_ms: int | None,
    ) -> ResourceObservationV1:
        try:
            safe_id(dispatch_id, "dispatch_id")
        except ValueError as exc:
            raise Protocol28BudgetError(str(exc)) from exc
        _usage(token_status, billable_tokens, "token")
        _usage(active_status, active_ms, "active")
        record = ResourceObservationV1(
            dispatch_id, token_status, billable_tokens, active_status, active_ms
        )
        existing = tuple(
            item
            for item in self._records
            if isinstance(item, ResourceObservationV1) and item.dispatch_id == dispatch_id
        )
        if existing:
            if existing[0] == record:
                return existing[0]
            raise Protocol28BudgetError("conflicting dispatch observation")
        open_dispatches, _pairs = _replay_open(self.records)
        if dispatch_id not in open_dispatches:
            raise Protocol28BudgetError("observation has no open paired reservation")
        pair = next(
            (
                item
                for item in self._records
                if isinstance(item, PairedReservationCommitV1)
                and item.verifier_dispatch_id == dispatch_id
            ),
            None,
        )
        if pair is not None:
            observed_ids = {
                item.dispatch_id
                for item in self._records
                if isinstance(item, ResourceObservationV1)
            }
            if pair.producer_dispatch_id not in observed_ids:
                raise Protocol28BudgetError(
                    "retained verifier requires its paired producer observation"
                )
        self._records.append(record)
        return record

    def abandon(self, dispatch_id: str) -> ResourceAbandonmentV1:
        try:
            safe_id(dispatch_id, "dispatch_id")
        except ValueError as exc:
            raise Protocol28BudgetError(str(exc)) from exc
        existing = tuple(
            item
            for item in self._records
            if isinstance(item, ResourceAbandonmentV1)
            and item.dispatch_id == dispatch_id
        )
        if existing:
            return existing[0]
        open_dispatches, _pairs = _replay_open(self.records)
        if dispatch_id not in open_dispatches:
            raise Protocol28BudgetError("abandonment has no open paired reservation")
        record = ResourceAbandonmentV1(dispatch_id)
        self._records.append(record)
        return record

    def preview_verifier_retry(
        self,
        slice_spec_id: str,
        producer_attempt_number: int,
        verifier_reservation: DispatchReservationV1,
    ) -> VerifierRetryPreviewV1:
        try:
            digest_value(slice_spec_id, "slice_spec_id")
        except ValueError as exc:
            raise Protocol28BudgetError(str(exc)) from exc
        _attempt_number = _accounting(
            producer_attempt_number, "producer attempt number"
        )
        if not 1 <= _attempt_number <= self.policy.producer_attempt_limit:
            raise Protocol28BudgetError("producer attempt number exceeds fixed policy")
        reservation = _reservation_dict(verifier_reservation)
        matching_pairs = tuple(
            item
            for item in self._records
            if isinstance(item, PairedReservationCommitV1)
            and item.slice_spec_id == slice_spec_id
            and item.producer_attempt_number == producer_attempt_number
        )
        if len(matching_pairs) != 1:
            raise Protocol28BudgetError(
                "verifier retry requires exactly one preceding producer pair"
            )
        observed = {
            item.dispatch_id
            for item in self._records
            if isinstance(item, ResourceObservationV1)
        }
        pair = matching_pairs[0]
        if pair.producer_dispatch_id not in observed or pair.verifier_dispatch_id not in observed:
            raise Protocol28BudgetError(
                "verifier retry requires observed producer and verifier dispatches"
            )
        if any(
            isinstance(item, VerifierRetryReservationV1)
            and item.slice_spec_id == slice_spec_id
            and item.producer_attempt_number == producer_attempt_number
            for item in self._records
        ):
            raise Protocol28BudgetError("verifier retry is already reserved")
        retry_work_id = _identity(
            {
                "slice_spec_id": slice_spec_id,
                "producer_attempt_number": producer_attempt_number,
                "verifier_reservation": reservation,
            }
        )
        decision = self.decision
        exhausted: list[str] = []
        if decision.token_limit is not None and _add(
            decision.charged_tokens,
            verifier_reservation.billable_tokens,
            "projected verifier retry tokens",
        ) > decision.token_limit:
            exhausted.append("tokens")
        if decision.active_ms_limit is not None and _add(
            decision.charged_active_ms,
            verifier_reservation.active_ms,
            "projected verifier retry active_ms",
        ) > decision.active_ms_limit:
            exhausted.append("active_ms")
        return VerifierRetryPreviewV1(
            self.prefix_id,
            retry_work_id,
            slice_spec_id,
            producer_attempt_number,
            verifier_reservation,
            not exhausted and not decision.reservation_breaches,
            tuple(exhausted),
        )

    def commit_verifier_retry(
        self,
        preview: VerifierRetryPreviewV1,
        *,
        dispatch_id: str,
    ) -> VerifierRetryReservationV1:
        if not isinstance(preview, VerifierRetryPreviewV1):
            raise Protocol28BudgetError("verifier retry commit requires a preview")
        if preview.ledger_prefix_id != self.prefix_id:
            raise Protocol28BudgetError("verifier retry preview has stale ledger prefix")
        if not preview.allowed:
            raise Protocol28BudgetError("verifier retry reservation is not affordable")
        current = self.preview_verifier_retry(
            preview.slice_spec_id,
            preview.producer_attempt_number,
            preview.verifier_reservation,
        )
        if current != preview or not current.allowed:
            raise Protocol28BudgetError("verifier retry preview no longer matches authority")
        used_dispatches = {
            item.producer_dispatch_id
            for item in self._records
            if isinstance(item, PairedReservationCommitV1)
        } | {
            item.verifier_dispatch_id
            for item in self._records
            if isinstance(item, PairedReservationCommitV1)
        } | {
            item.dispatch_id
            for item in self._records
            if isinstance(item, VerifierRetryReservationV1)
        }
        if dispatch_id in used_dispatches:
            raise Protocol28BudgetError("verifier retry dispatch ID already exists")
        record = VerifierRetryReservationV1(
            1,
            preview.retry_work_id,
            preview.slice_spec_id,
            preview.producer_attempt_number,
            dispatch_id,
            preview.verifier_reservation,
        )
        self._records.append(record)
        return record

    def release_verifier(
        self,
        pair_id: str,
        *,
        reason: Literal["producer_contract_failure", "producer_abandoned"],
    ) -> VerifierReleaseV1:
        record = VerifierReleaseV1(pair_id, reason)
        existing = tuple(
            item
            for item in self._records
            if isinstance(item, VerifierReleaseV1) and item.pair_id == pair_id
        )
        if existing:
            if existing[0] == record:
                return existing[0]
            raise Protocol28BudgetError("conflicting verifier reservation release")
        open_dispatches, pairs = _replay_open(self.records)
        pair = pairs.get(pair_id)
        if pair is None:
            raise Protocol28BudgetError("verifier release references unknown pair")
        verifier = open_dispatches.get(pair.verifier_dispatch_id)
        if verifier is None or verifier.role != "verifier":
            raise Protocol28BudgetError("verifier reservation is not open")
        self._records.append(record)
        return record

    def authorize(
        self, dimension: Literal["tokens", "active_ms"], new_limit: int
    ) -> BudgetAuthorizationV1:
        if dimension not in {"tokens", "active_ms"}:
            raise Protocol28BudgetError("authorization dimension is invalid")
        decision = self.decision
        old = decision.token_limit if dimension == "tokens" else decision.active_ms_limit
        if old is None:
            raise Protocol28BudgetError("unlimited resource cannot receive finite authorization")
        new = _accounting(new_limit, "new authorization")
        if new <= old:
            raise Protocol28BudgetError("authorization must increase the resource limit")
        record = BudgetAuthorizationV1(dimension, old, new)
        self._records.append(record)
        return record

    def record_adoption(
        self,
        slice_spec_id: str,
        *,
        producer_reservation: DispatchReservationV1,
        verifier_reservation: DispatchReservationV1,
    ) -> AdoptionAccountingV1:
        try:
            digest_value(slice_spec_id, "slice_spec_id")
        except ValueError as exc:
            raise Protocol28BudgetError(str(exc)) from exc
        _reservation_dict(producer_reservation)
        _reservation_dict(verifier_reservation)
        existing = tuple(
            item
            for item in self._records
            if isinstance(item, AdoptionAccountingV1)
            and item.slice_spec_id == slice_spec_id
        )
        record = AdoptionAccountingV1(
            slice_spec_id, producer_reservation, verifier_reservation
        )
        if existing:
            if existing[0] == record:
                return existing[0]
            raise Protocol28BudgetError("conflicting adoption accounting")
        self._records.append(record)
        return record


def _evaluate(
    policy: ExhaustiveBudgetPolicyV1,
    records: tuple[ResourceRecordV1, ...],
) -> L4ResourceDecisionV1:
    token_limit = policy.token_limit
    active_limit = policy.active_ms_limit
    for record in records:
        if isinstance(record, BudgetAuthorizationV1):
            current = token_limit if record.dimension == "tokens" else active_limit
            if current != record.old_value or record.new_value <= record.old_value:
                raise Protocol28BudgetError("authorization chain is invalid")
            if record.dimension == "tokens":
                token_limit = record.new_value
            else:
                active_limit = record.new_value

    open_dispatches, pairs = _replay_open(records)
    observations = {
        record.dispatch_id: record
        for record in records
        if isinstance(record, ResourceObservationV1)
    }
    abandonments = {
        record.dispatch_id
        for record in records
        if isinstance(record, ResourceAbandonmentV1)
    }
    releases = {
        record.pair_id: record
        for record in records
        if isinstance(record, VerifierReleaseV1)
    }
    charged_tokens = 0
    charged_active = 0
    trusted_tokens = 0
    trusted_active = 0
    open_tokens = 0
    open_active = 0
    unknown_tokens = {"producer": 0, "verifier": 0}
    unknown_active = {"producer": 0, "verifier": 0}
    generated = {"producer": 0, "verifier": 0}
    avoided = {"producer": 0, "verifier": 0}
    avoided_tokens = 0
    avoided_active_ms = 0
    breaches: set[str] = set()

    all_dispatches: dict[str, _OpenDispatch] = {}
    for pair in pairs.values():
        all_dispatches[pair.producer_dispatch_id] = _OpenDispatch(
            "producer", pair.producer_reservation, pair.identity
        )
        all_dispatches[pair.verifier_dispatch_id] = _OpenDispatch(
            "verifier", pair.verifier_reservation, pair.identity
        )
    for retry in (
        item for item in records if isinstance(item, VerifierRetryReservationV1)
    ):
        all_dispatches[retry.dispatch_id] = _OpenDispatch(
            "verifier", retry.verifier_reservation, retry.identity
        )
    for dispatch_id, dispatch in all_dispatches.items():
        if dispatch.role == "verifier" and dispatch.pair_id in releases:
            avoided["verifier"] += 1
            avoided_tokens = _add(
                avoided_tokens,
                dispatch.reservation.billable_tokens,
                "avoided tokens",
            )
            avoided_active_ms = _add(
                avoided_active_ms,
                dispatch.reservation.active_ms,
                "avoided active_ms",
            )
            continue
        observation = observations.get(dispatch_id)
        if dispatch_id in abandonments:
            generated[dispatch.role] += 1
            charged_tokens = _add(
                charged_tokens,
                dispatch.reservation.billable_tokens,
                "charged tokens",
            )
            charged_active = _add(
                charged_active,
                dispatch.reservation.active_ms,
                "charged active_ms",
            )
            unknown_tokens[dispatch.role] += 1
            unknown_active[dispatch.role] += 1
            continue
        if observation is None:
            charged_tokens = _add(
                charged_tokens, dispatch.reservation.billable_tokens, "charged tokens"
            )
            charged_active = _add(
                charged_active, dispatch.reservation.active_ms, "charged active_ms"
            )
            open_tokens = _add(
                open_tokens, dispatch.reservation.billable_tokens, "open tokens"
            )
            open_active = _add(
                open_active, dispatch.reservation.active_ms, "open active_ms"
            )
            continue
        generated[dispatch.role] += 1
        token_charge = conservative_charge(
            observation.billable_tokens,
            observation.token_status,
            dispatch.reservation.billable_tokens,
        )
        active_charge = conservative_charge(
            observation.active_ms,
            observation.active_status,
            dispatch.reservation.active_ms,
        )
        charged_tokens = _add(charged_tokens, token_charge, "charged tokens")
        charged_active = _add(charged_active, active_charge, "charged active_ms")
        if observation.token_status == "trusted_exact":
            trusted_tokens = _add(
                trusted_tokens, observation.billable_tokens or 0, "trusted tokens"
            )
        else:
            unknown_tokens[dispatch.role] += 1
        if observation.active_status == "trusted_exact":
            trusted_active = _add(
                trusted_active, observation.active_ms or 0, "trusted active_ms"
            )
        else:
            unknown_active[dispatch.role] += 1
        if (
            observation.token_status == "trusted_exact"
            and observation.billable_tokens is not None
            and observation.billable_tokens > dispatch.reservation.billable_tokens
        ) or (
            observation.active_status == "trusted_exact"
            and observation.active_ms is not None
            and observation.active_ms > dispatch.reservation.active_ms
        ):
            breaches.add(dispatch_id)

    adopted = 0
    for record in records:
        if not isinstance(record, AdoptionAccountingV1):
            continue
        adopted += 1
        avoided["producer"] += 1
        avoided["verifier"] += 1
        avoided_tokens = _add(
            avoided_tokens,
            record.producer_reservation.billable_tokens
            + record.verifier_reservation.billable_tokens,
            "avoided tokens",
        )
        avoided_active_ms = _add(
            avoided_active_ms,
            record.producer_reservation.active_ms + record.verifier_reservation.active_ms,
            "avoided active_ms",
        )

    exhausted: list[str] = []
    if token_limit is not None and charged_tokens >= token_limit:
        exhausted.append("tokens")
    if active_limit is not None and charged_active >= active_limit:
        exhausted.append("active_ms")

    return L4ResourceDecisionV1(
        charged_tokens,
        charged_active,
        trusted_tokens,
        trusted_active,
        open_tokens,
        open_active,
        token_limit,
        active_limit,
        MappingProxyType(dict(unknown_tokens)),
        MappingProxyType(dict(unknown_active)),
        MappingProxyType(dict(generated)),
        MappingProxyType(dict(avoided)),
        adopted,
        avoided_tokens,
        avoided_active_ms,
        tuple(exhausted),
        tuple(sorted(breaches)),
        policy.producer_attempt_limit,
        policy.verifier_contract_retry_limit,
    )


def _replay_open(
    records: tuple[ResourceRecordV1, ...],
) -> tuple[dict[str, _OpenDispatch], dict[str, PairedReservationCommitV1]]:
    pairs: dict[str, PairedReservationCommitV1] = {}
    dispatches: dict[str, _OpenDispatch] = {}
    observed: set[str] = set()
    abandoned: set[str] = set()
    released_pairs: set[str] = set()
    for record in records:
        if isinstance(record, PairedReservationCommitV1):
            if record.identity in pairs:
                raise Protocol28BudgetError("duplicate paired reservation")
            if record.producer_dispatch_id in dispatches or record.verifier_dispatch_id in dispatches:
                raise Protocol28BudgetError("duplicate paired dispatch ID")
            pairs[record.identity] = record
            dispatches[record.producer_dispatch_id] = _OpenDispatch(
                "producer", record.producer_reservation, record.identity
            )
            dispatches[record.verifier_dispatch_id] = _OpenDispatch(
                "verifier", record.verifier_reservation, record.identity
            )
        elif isinstance(record, VerifierRetryReservationV1):
            if record.dispatch_id in dispatches:
                raise Protocol28BudgetError("duplicate verifier retry dispatch ID")
            if any(
                isinstance(item, VerifierRetryReservationV1)
                and item.slice_spec_id == record.slice_spec_id
                and item.producer_attempt_number == record.producer_attempt_number
                and item != record
                for item in records
            ):
                raise Protocol28BudgetError("duplicate verifier retry reservation")
            dispatches[record.dispatch_id] = _OpenDispatch(
                "verifier", record.verifier_reservation, record.identity
            )
        elif isinstance(record, ResourceObservationV1):
            if (
                record.dispatch_id not in dispatches
                or record.dispatch_id in observed
                or record.dispatch_id in abandoned
            ):
                raise Protocol28BudgetError("observation does not match one open dispatch")
            pair = next(
                (
                    item
                    for item in pairs.values()
                    if item.verifier_dispatch_id == record.dispatch_id
                ),
                None,
            )
            if pair is not None and pair.producer_dispatch_id not in observed:
                raise Protocol28BudgetError(
                    "retained verifier requires its paired producer observation"
                )
            observed.add(record.dispatch_id)
        elif isinstance(record, ResourceAbandonmentV1):
            if (
                record.dispatch_id not in dispatches
                or record.dispatch_id in observed
                or record.dispatch_id in abandoned
            ):
                raise Protocol28BudgetError("abandonment does not match one open dispatch")
            abandoned.add(record.dispatch_id)
        elif isinstance(record, VerifierReleaseV1):
            pair = pairs.get(record.pair_id)
            if pair is None or record.pair_id in released_pairs:
                raise Protocol28BudgetError("verifier release does not match one open pair")
            if pair.verifier_dispatch_id in observed:
                raise Protocol28BudgetError("observed verifier reservation cannot be released")
            released_pairs.add(record.pair_id)
    for dispatch_id in observed:
        dispatches.pop(dispatch_id, None)
    for dispatch_id in abandoned:
        dispatches.pop(dispatch_id, None)
    for pair_id in released_pairs:
        pair = pairs[pair_id]
        dispatches.pop(pair.verifier_dispatch_id, None)
    return dispatches, pairs


def _usage(status: object, value: object, label: str) -> None:
    if status not in _USAGE_STATUSES:
        raise Protocol28BudgetError(f"{label} usage status is invalid")
    if status == "trusted_exact" and value is None:
        raise Protocol28BudgetError(f"trusted {label} usage requires a value")
    if status == "unavailable" and value is not None:
        raise Protocol28BudgetError(f"unavailable {label} usage cannot contain a value")
    if value is not None:
        _accounting(value, f"{label} usage")


def _accounting(value: object, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise Protocol28BudgetError(f"{field} must be a nonnegative integer")
    if value > MAX_ACCOUNTING_VALUE:
        raise Protocol28BudgetError(f"{field} exceeds signed 64-bit accounting bounds")
    return value


def _add(left: int, right: int, field: str) -> int:
    result = _accounting(left, field) + _accounting(right, field)
    if result > MAX_ACCOUNTING_VALUE:
        raise Protocol28BudgetError(f"{field} exceeds signed 64-bit accounting bounds")
    return result


__all__ = (
    "AdoptionAccountingV1",
    "BudgetAuthorizationV1",
    "L4ResourceDecisionV1",
    "L4ResourceLedger",
    "PairedReservationCommitV1",
    "PairedReservationPreviewV1",
    "Protocol28BudgetError",
    "ResourceAbandonmentV1",
    "ResourceObservationV1",
    "VerifierReleaseV1",
    "VerifierRetryPreviewV1",
    "VerifierRetryReservationV1",
)
