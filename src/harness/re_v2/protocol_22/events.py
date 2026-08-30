"""Closed protocol-2.2 event payloads and replay ordering."""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Callable, Mapping

from harness.re_v2.events import (
    EventProtocol,
    EventRecord,
    EventReplayState,
    ReV2EventError,
    _canonical_payload,
    _parsed_rfc3339,
    _thaw_json,
)


_DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")
_SAFE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]*\Z")
_ATTEMPT_KINDS = frozenset(
    {"initial_generation", "result_contract_retry", "artifact_contract_retry"}
)
_RAW_RESULT_STATUSES = frozenset({"valid", "invalid", "not_applicable"})
_USAGE_STATUSES = frozenset({"trusted_exact", "unavailable", "untrusted"})
_FAILURE_CLASSES = frozenset(
    {
        "result_contract",
        "artifact_contract",
        "minimum_utility",
        "execution_indeterminate",
    }
)
_FAILURE_REASON_BY_CLASS = {
    "result_contract": frozenset({"result_unrecoverable"}),
    "artifact_contract": frozenset(
        {
            "candidate_tree_invalid",
            "authorial_schema_invalid",
            "artifact_bound_exceeded",
            "evidence_contract_invalid",
        }
    ),
    "minimum_utility": frozenset({"minimum_utility_not_met"}),
    "execution_indeterminate": frozenset({"execution_outcome_indeterminate"}),
}
_TERMINAL_EVENTS = frozenset({"run_completed", "run_failed"})
_PAUSED_CONTROL_EVENTS = frozenset({"budget_authorized", "operator_pause_requested"})
_PAUSED_RECOVERY_EVENTS = frozenset(
    {
        "dispatch_lease_retired",
        "dispatch_observed",
        "candidate_persisted",
        "result_contract_reconstructed",
        "candidate_certified",
        "candidate_rejected",
        "artifact_accepted",
        "dispatch_abandoned",
        "work_item_failed",
        "executor_failed",
    }
)


PayloadValidator = Callable[[object, str], None]


def _digest(value: object, field_name: str) -> None:
    if not isinstance(value, str) or not _DIGEST_RE.fullmatch(value):
        raise ReV2EventError(f"{field_name} must be a lowercase sha256 digest")


def _nullable_digest(value: object, field_name: str) -> None:
    if value is not None:
        _digest(value, field_name)


def _safe_id(value: object, field_name: str) -> None:
    if not isinstance(value, str) or not _SAFE_ID_RE.fullmatch(value):
        raise ReV2EventError(f"{field_name} must be a nonempty safe ID")


def _string(value: object, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ReV2EventError(f"{field_name} must be a nonempty string")


def _nonnegative(value: object, field_name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ReV2EventError(f"{field_name} must be a nonnegative integer")


def _positive(value: object, field_name: str) -> None:
    _nonnegative(value, field_name)
    if value == 0:
        raise ReV2EventError(f"{field_name} must be a positive integer")


def _nullable_nonnegative(value: object, field_name: str) -> None:
    if value is not None:
        _nonnegative(value, field_name)


def _choice(choices: frozenset[str]) -> PayloadValidator:
    def validate(value: object, field_name: str) -> None:
        if not isinstance(value, str) or value not in choices:
            raise ReV2EventError(f"{field_name} must be one of {sorted(choices)}")

    return validate


def _digest_array(value: object, field_name: str) -> None:
    if not isinstance(value, list):
        raise ReV2EventError(f"{field_name} must be an array")
    for item in value:
        _digest(item, field_name)
    if value != sorted(set(value)):
        raise ReV2EventError(f"{field_name} must be sorted and unique")


_PAYLOAD_SCHEMAS: Mapping[str, Mapping[str, PayloadValidator]] = {
    "run_created": {"run_manifest_id": _digest},
    "work_planned": {"work_item_ids": _digest_array},
    "dispatch_leased": {"dispatch_id": _safe_id, "work_item_id": _digest},
    "dispatch_lease_retired": {
        "dispatch_id": _safe_id,
        "lease_id": _digest,
        "reason": _string,
        "work_item_id": _digest,
    },
    "dispatch_started": {
        "active_ms_reservation": _positive,
        "attempt_index": _positive,
        "attempt_kind": _choice(_ATTEMPT_KINDS),
        "billable_token_reservation": _nonnegative,
        "dispatch_id": _safe_id,
        "execution_input_hash": _digest,
        "executor_contract_hash": _digest,
        "work_item_id": _digest,
    },
    "dispatch_observed": {
        "active_usage_status": _choice(_USAGE_STATUSES),
        "dispatch_id": _safe_id,
        "execution_capture_hash": _digest,
        "observed_active_ms": _nullable_nonnegative,
        "raw_result_contract_status": _choice(_RAW_RESULT_STATUSES),
        "reported_token_usage": _nullable_nonnegative,
        "token_usage_status": _choice(_USAGE_STATUSES),
        "work_item_id": _digest,
    },
    "candidate_persisted": {
        "candidate_id": _digest,
        "candidate_inventory_hash": _digest,
        "dispatch_id": _safe_id,
        "execution_capture_hash": _digest,
        "work_item_id": _digest,
    },
    "result_contract_reconstructed": {
        "candidate_id": _digest,
        "dispatch_id": _safe_id,
        "result_contract_id": _safe_id,
        "work_item_id": _digest,
    },
    "candidate_certified": {
        "candidate_assessment_id": _digest,
        "candidate_id": _digest,
        "certification_receipt_id": _digest,
        "work_item_id": _digest,
    },
    "candidate_rejected": {
        "candidate_assessment_id": _digest,
        "candidate_id": _digest,
        "certification_receipt_id": _nullable_digest,
        "work_item_id": _digest,
    },
    "artifact_accepted": {
        "artifact_acceptance_receipt_id": _digest,
        "artifact_hash": _digest,
        "artifact_key_id": _digest,
        "candidate_assessment_id": _nullable_digest,
        "certification_receipt_id": _digest,
        "work_item_id": _digest,
    },
    "dispatch_abandoned": {
        "dispatch_id": _safe_id,
        "execution_input_hash": _digest,
        "executor_contract_hash": _digest,
        "reason_code": _choice(frozenset({"execution_outcome_indeterminate"})),
        "work_item_id": _digest,
    },
    "work_item_failed": {
        "failure_class": _choice(_FAILURE_CLASSES),
        "failure_receipt_id": _digest,
        "reason_code": _safe_id,
        "work_item_id": _digest,
    },
    "executor_failed": {
        "executor_contract_hash": _digest,
        "executor_failure_receipt_id": _digest,
        "trigger_work_item_id": _digest,
    },
    "budget_authorized": {
        "authorized_by": _safe_id,
        "dimension": _choice(frozenset({"tokens", "active_ms"})),
        "new_value": _positive,
        "old_value": _nullable_nonnegative,
        "reason": _string,
    },
    "operator_pause_requested": {
        "reason": _string,
        "requested_by": _safe_id,
    },
    "run_paused": {"reason": _string, "reason_code": _safe_id},
    "run_resumed": {"reason": _string},
    "run_completed": {"reason": _string},
    "run_failed": {"reason": _string},
}


def _validate_payload(event_type: object, payload: Mapping[str, object]) -> None:
    if not isinstance(event_type, str) or event_type not in _PAYLOAD_SCHEMAS:
        raise ReV2EventError(f"unknown protocol-2.2 event type: {event_type!r}")
    schema = _PAYLOAD_SCHEMAS[event_type]
    present = frozenset(payload)
    expected = frozenset(schema)
    unknown = present - expected
    missing = expected - present
    if unknown:
        raise ReV2EventError(
            f"{event_type} payload has unknown fields: {', '.join(sorted(unknown))}"
        )
    if missing:
        raise ReV2EventError(
            f"{event_type} payload is missing fields: {', '.join(sorted(missing))}"
        )
    for field_name, validator in schema.items():
        validator(_thaw_json(payload[field_name]), field_name)
    if event_type == "dispatch_observed":
        _validate_usage_pair(
            payload["reported_token_usage"],
            payload["token_usage_status"],
            "token usage",
        )
        _validate_usage_pair(
            payload["observed_active_ms"],
            payload["active_usage_status"],
            "active usage",
        )
    elif event_type == "work_item_failed":
        failure_class = str(payload["failure_class"])
        if payload["reason_code"] not in _FAILURE_REASON_BY_CLASS[failure_class]:
            raise ReV2EventError(
                "work_item_failed reason_code does not match failure_class"
            )


def _validate_usage_pair(value: object, status: object, field_name: str) -> None:
    if status == "trusted_exact" and value is None:
        raise ReV2EventError(f"{field_name} trusted_exact requires a value")
    if status == "unavailable" and value is not None:
        raise ReV2EventError(f"{field_name} unavailable requires null")


@dataclass(slots=True)
class _ActiveAttempt:
    dispatch_id: str
    work_item_id: str
    execution_input_hash: str
    executor_contract_hash: str
    token_reservation: int
    active_reservation: int
    provider_backed: bool
    started_at: str
    stage: str = "started"
    capture_hash: str | None = None
    raw_result_status: str | None = None
    effective_result_status: str | None = None
    candidate_id: str | None = None
    candidate_assessment_id: str | None = None
    certification_receipt_id: str | None = None


@dataclass(slots=True)
class Protocol22ReplayState(EventReplayState):
    seen: int = 0
    terminal: bool = False
    paused: bool = False
    pause_requested: bool = False
    last_type: str | None = None
    lease_dispatch_id: str | None = None
    lease_work_item_id: str | None = None
    active: _ActiveAttempt | None = None
    dispatch_ids: set[str] = field(default_factory=set)
    candidate_ids: set[str] = field(default_factory=set)
    accepted_work_items: set[str] = field(default_factory=set)
    failed_work_items: set[str] = field(default_factory=set)
    failed_executors: set[str] = field(default_factory=set)
    initial_work_items: set[str] = field(default_factory=set)
    attempt_indices: dict[tuple[str, str], int] = field(default_factory=dict)
    retry_kind_by_work_item: dict[str, str] = field(default_factory=dict)
    retry_eligibility: dict[str, str] = field(default_factory=dict)
    indeterminate_work_items: set[str] = field(default_factory=set)

    @property
    def has_active_dispatch(self) -> bool:
        """Whether replay currently owns a lease or a started dispatch."""
        return self.active is not None or self.lease_dispatch_id is not None

    def mark_imported_work_accepted(
        self,
        work_item_id: str,
        event_type: str,
    ) -> None:
        """Apply the shared accepted-work transition for an authenticated import."""
        _digest(work_item_id, "work_item_id")
        if self.terminal:
            raise ReV2EventError("event appears after terminal run state")
        if self.seen == 0:
            raise ReV2EventError("run_created must be the first event")
        if self.paused or self.pause_requested:
            raise ReV2EventError(f"{event_type} is not allowed while pausing or paused")
        if self.has_active_dispatch:
            raise ReV2EventError(f"{event_type} is invalid during an active dispatch")
        if work_item_id in self.accepted_work_items:
            raise ReV2EventError("work item is already adopted or accepted")
        if work_item_id in self.failed_work_items:
            raise ReV2EventError("accepted imported work conflicts with failed work")
        self.accepted_work_items.add(work_item_id)
        self._finish(event_type)

    def consume(self, event: EventRecord) -> None:
        event_type = event.type
        payload = event.payload
        if self.terminal:
            raise ReV2EventError("event appears after terminal run state")
        if self.seen == 0 and event_type != "run_created":
            raise ReV2EventError("run_created must be the first event")
        if self.seen > 0 and event_type == "run_created":
            raise ReV2EventError("run_created may appear only once")

        if self.paused:
            if event_type == "run_resumed":
                if self.last_type not in _PAUSED_CONTROL_EVENTS:
                    raise ReV2EventError(
                        "paused run requires authorization or operator action before run_resumed"
                    )
                self.paused = False
                self._finish(event_type)
                return
            if event_type in _PAUSED_CONTROL_EVENTS:
                self._finish(event_type)
                return
            if event_type not in _PAUSED_RECOVERY_EVENTS:
                raise ReV2EventError(f"{event_type} is not allowed while run is paused")

        if self.pause_requested and event_type != "run_paused":
            raise ReV2EventError(
                "operator pause request must be followed by run_paused"
            )
        if event_type == "run_resumed":
            raise ReV2EventError("run_resumed requires a paused run")
        if event_type == "budget_authorized":
            raise ReV2EventError("budget_authorized requires a paused run")

        if event_type == "operator_pause_requested":
            self.pause_requested = True
        elif event_type == "run_paused":
            self.pause_requested = False
            self.paused = True
        elif event_type == "dispatch_leased":
            self._lease(payload)
        elif event_type == "dispatch_lease_retired":
            self._retire_lease(payload)
        elif event_type == "dispatch_started":
            self._start(event)
        elif event_type == "dispatch_observed":
            self._observe(event)
        elif event_type == "candidate_persisted":
            self._persist_candidate(payload)
        elif event_type == "result_contract_reconstructed":
            self._reconstruct_result(payload)
        elif event_type == "candidate_certified":
            self._candidate_certified(payload)
        elif event_type == "candidate_rejected":
            self._candidate_rejected(payload)
        elif event_type == "artifact_accepted":
            self._artifact_accepted(payload)
        elif event_type == "dispatch_abandoned":
            self._abandon(payload)
        elif event_type == "work_item_failed":
            self._work_failed(payload)
        elif event_type == "executor_failed":
            self._executor_failed(payload)
        elif event_type in _TERMINAL_EVENTS:
            self._terminate(event_type)

        self._finish(event_type)

    def _lease(self, payload: Mapping[str, object]) -> None:
        dispatch_id = str(payload["dispatch_id"])
        work_item_id = str(payload["work_item_id"])
        if self.lease_dispatch_id is not None:
            raise ReV2EventError("dispatch_leased conflicts with an active lease")
        if self.active is not None:
            eligible = self.retry_eligibility.get(work_item_id)
            if (
                self.active.work_item_id != work_item_id
                or eligible is None
                or self.active.stage not in {"observed", "persisted"}
            ):
                raise ReV2EventError(
                    "dispatch_leased requires no active work or exact retry eligibility"
                )
            self.active = None
        if dispatch_id in self.dispatch_ids:
            raise ReV2EventError("dispatch_id must be globally unique")
        if (
            work_item_id in self.accepted_work_items
            or work_item_id in self.failed_work_items
        ):
            raise ReV2EventError("dispatch_leased cannot reopen terminal work")
        self.dispatch_ids.add(dispatch_id)
        self.lease_dispatch_id = dispatch_id
        self.lease_work_item_id = work_item_id

    def _retire_lease(self, payload: Mapping[str, object]) -> None:
        dispatch_id = str(payload["dispatch_id"])
        work_item_id = str(payload["work_item_id"])
        if dispatch_id in self.dispatch_ids:
            if (
                dispatch_id != self.lease_dispatch_id
                or work_item_id != self.lease_work_item_id
            ):
                raise ReV2EventError("dispatch lease retirement conflicts with history")
            self.lease_dispatch_id = None
            self.lease_work_item_id = None
            return
        self.dispatch_ids.add(dispatch_id)

    def _start(self, event: EventRecord) -> None:
        payload = event.payload
        dispatch_id = str(payload["dispatch_id"])
        work_item_id = str(payload["work_item_id"])
        if (
            self.lease_dispatch_id != dispatch_id
            or self.lease_work_item_id != work_item_id
            or self.active is not None
        ):
            raise ReV2EventError("dispatch_started requires its matching active lease")
        executor_contract_hash = str(payload["executor_contract_hash"])
        if executor_contract_hash in self.failed_executors:
            raise ReV2EventError(
                "dispatch_started cannot use a failed executor contract"
            )
        kind = str(payload["attempt_kind"])
        index = int(payload["attempt_index"])
        expected_index = self.attempt_indices.get((work_item_id, kind), 0) + 1
        if index != expected_index:
            raise ReV2EventError(
                "dispatch_started attempt_index must be consecutive per work item and kind"
            )
        if kind == "initial_generation":
            if work_item_id in self.initial_work_items:
                raise ReV2EventError(
                    "initial_generation may occur only once per work item"
                )
            self.initial_work_items.add(work_item_id)
        else:
            if work_item_id not in self.initial_work_items:
                raise ReV2EventError(
                    "retry requires initial_generation as the first attempt"
                )
            if self.retry_eligibility.get(work_item_id) != kind:
                raise ReV2EventError(
                    f"{kind} lacks its immediately preceding eligible outcome"
                )
            previous = self.retry_kind_by_work_item.get(work_item_id)
            if previous is not None:
                raise ReV2EventError(
                    "one work item cannot consume both retry kinds; shared retry is exhausted"
                )
            self.retry_kind_by_work_item[work_item_id] = kind
            self.retry_eligibility.pop(work_item_id, None)
        token_reservation = int(payload["billable_token_reservation"])
        self.attempt_indices[(work_item_id, kind)] = index
        self.active = _ActiveAttempt(
            dispatch_id=dispatch_id,
            work_item_id=work_item_id,
            execution_input_hash=str(payload["execution_input_hash"]),
            executor_contract_hash=executor_contract_hash,
            token_reservation=token_reservation,
            active_reservation=int(payload["active_ms_reservation"]),
            provider_backed=token_reservation > 0,
            started_at=event.occurred_at,
        )
        self.lease_dispatch_id = None
        self.lease_work_item_id = None

    def _observe(self, event: EventRecord) -> None:
        active = self._require_active(event.payload, "started", "dispatch_observed")
        if _parsed_rfc3339(event.occurred_at) < _parsed_rfc3339(active.started_at):
            raise ReV2EventError("dispatch_observed occurs before dispatch_started")
        status = str(event.payload["raw_result_contract_status"])
        if active.provider_backed:
            if status == "not_applicable":
                raise ReV2EventError(
                    "provider dispatch cannot use not_applicable result status"
                )
        elif (
            status != "not_applicable"
            or event.payload["reported_token_usage"] != 0
            or event.payload["token_usage_status"] != "trusted_exact"
        ):
            raise ReV2EventError(
                "deterministic dispatch requires not_applicable and trusted zero token usage"
            )
        active.capture_hash = str(event.payload["execution_capture_hash"])
        active.raw_result_status = status
        active.effective_result_status = status
        active.stage = "observed"
        if status == "invalid":
            self.retry_eligibility[active.work_item_id] = "result_contract_retry"
        else:
            self.retry_eligibility.pop(active.work_item_id, None)

    def _persist_candidate(self, payload: Mapping[str, object]) -> None:
        active = self._require_active(payload, "observed", "candidate_persisted")
        if not active.provider_backed:
            raise ReV2EventError("deterministic execution cannot persist a candidate")
        if payload["execution_capture_hash"] != active.capture_hash:
            raise ReV2EventError("candidate_persisted does not match execution capture")
        candidate_id = str(payload["candidate_id"])
        if candidate_id in self.candidate_ids:
            raise ReV2EventError("candidate_id must be globally unique")
        self.candidate_ids.add(candidate_id)
        active.candidate_id = candidate_id
        active.stage = "persisted"

    def _reconstruct_result(self, payload: Mapping[str, object]) -> None:
        active = self._require_active(
            payload,
            "persisted",
            "result_contract_reconstructed",
            require_dispatch=True,
        )
        if (
            active.raw_result_status != "invalid"
            or payload["candidate_id"] != active.candidate_id
        ):
            raise ReV2EventError(
                "result reconstruction requires the matching candidate_persisted after invalid result"
            )
        active.effective_result_status = "reconstructed"
        active.stage = "reconstructed"
        self.retry_eligibility.pop(active.work_item_id, None)

    def _candidate_certified(self, payload: Mapping[str, object]) -> None:
        active = self._require_candidate_outcome(payload, "candidate_certified")
        active.candidate_assessment_id = str(payload["candidate_assessment_id"])
        active.certification_receipt_id = str(payload["certification_receipt_id"])
        active.stage = "certified"
        self.retry_eligibility.pop(active.work_item_id, None)

    def _candidate_rejected(self, payload: Mapping[str, object]) -> None:
        active = self._require_candidate_outcome(payload, "candidate_rejected")
        self.retry_eligibility[active.work_item_id] = "artifact_contract_retry"
        self.active = None

    def _require_candidate_outcome(
        self,
        payload: Mapping[str, object],
        event_type: str,
    ) -> _ActiveAttempt:
        if self.active is None or self.active.stage not in {
            "persisted",
            "reconstructed",
        }:
            raise ReV2EventError(f"{event_type} requires a persisted candidate")
        active = self.active
        if payload["work_item_id"] != active.work_item_id or (
            payload["candidate_id"] != active.candidate_id
        ):
            raise ReV2EventError(f"{event_type} does not match persisted candidate")
        if active.effective_result_status not in {"valid", "reconstructed"}:
            raise ReV2EventError(
                f"{event_type} requires valid or reconstructed result authority"
            )
        return active

    def _artifact_accepted(self, payload: Mapping[str, object]) -> None:
        work_item_id = str(payload["work_item_id"])
        if self.active is None or self.active.work_item_id != work_item_id:
            raise ReV2EventError("artifact_accepted requires active certified work")
        active = self.active
        candidate_assessment = payload["candidate_assessment_id"]
        if active.provider_backed:
            if active.stage != "certified":
                raise ReV2EventError(
                    "provider artifact_accepted requires candidate_certified"
                )
            if (
                candidate_assessment != active.candidate_assessment_id
                or payload["certification_receipt_id"]
                != active.certification_receipt_id
            ):
                raise ReV2EventError(
                    "artifact_accepted candidate assessment or certification mismatch"
                )
        elif (
            active.stage != "observed"
            or active.raw_result_status != "not_applicable"
            or candidate_assessment is not None
        ):
            raise ReV2EventError(
                "deterministic artifact_accepted requires null candidate assessment"
            )
        self.accepted_work_items.add(work_item_id)
        self.retry_eligibility.pop(work_item_id, None)
        self.indeterminate_work_items.discard(work_item_id)
        self.active = None

    def _abandon(self, payload: Mapping[str, object]) -> None:
        active = self._require_active(payload, "started", "dispatch_abandoned")
        if (
            payload["execution_input_hash"] != active.execution_input_hash
            or payload["executor_contract_hash"] != active.executor_contract_hash
        ):
            raise ReV2EventError(
                "dispatch_abandoned does not match started execution authority"
            )
        self.indeterminate_work_items.add(active.work_item_id)
        if active.provider_backed:
            self.retry_eligibility[active.work_item_id] = "result_contract_retry"
        self.active = None

    def _work_failed(self, payload: Mapping[str, object]) -> None:
        work_item_id = str(payload["work_item_id"])
        failure_class = str(payload["failure_class"])
        eligible = self.retry_eligibility.get(work_item_id)
        if (
            work_item_id in self.accepted_work_items
            or work_item_id in self.failed_work_items
        ):
            raise ReV2EventError("work_item_failed conflicts with terminal work")
        if failure_class == "execution_indeterminate":
            authorized = work_item_id in self.indeterminate_work_items
        elif failure_class == "result_contract":
            authorized = eligible == "result_contract_retry"
        else:
            authorized = eligible == "artifact_contract_retry"
        if not authorized:
            raise ReV2EventError(
                "work_item_failed requires matching exhausted attempt eligibility"
            )
        self.failed_work_items.add(work_item_id)
        self.retry_eligibility.pop(work_item_id, None)
        self.indeterminate_work_items.discard(work_item_id)
        if self.active is not None and self.active.work_item_id == work_item_id:
            self.active = None

    def _executor_failed(self, payload: Mapping[str, object]) -> None:
        executor_hash = str(payload["executor_contract_hash"])
        trigger = str(payload["trigger_work_item_id"])
        if executor_hash in self.failed_executors:
            raise ReV2EventError(
                "executor contract is already failed; receipt must be unique"
            )
        if trigger in self.accepted_work_items:
            raise ReV2EventError(
                "executor_failed cannot invalidate accepted trigger work"
            )
        self.failed_executors.add(executor_hash)
        if self.active is not None and self.active.work_item_id == trigger:
            if self.active.executor_contract_hash != executor_hash:
                raise ReV2EventError(
                    "executor_failed does not match active executor contract"
                )
            self.active = None
        if self.lease_work_item_id == trigger:
            self.lease_dispatch_id = None
            self.lease_work_item_id = None

    def _terminate(self, event_type: str) -> None:
        if self.active is not None or self.lease_dispatch_id is not None:
            raise ReV2EventError(f"{event_type} is invalid with active work")
        if event_type == "run_completed" and (
            self.failed_work_items or self.failed_executors
        ):
            raise ReV2EventError("run_completed conflicts with failed work")
        if event_type == "run_failed" and not (
            self.failed_work_items or self.failed_executors
        ):
            raise ReV2EventError("run_failed requires durable failure authority")
        self.terminal = True

    def _require_active(
        self,
        payload: Mapping[str, object],
        stage: str,
        event_type: str,
        *,
        require_dispatch: bool = True,
    ) -> _ActiveAttempt:
        if self.active is None or self.active.stage != stage:
            raise ReV2EventError(f"{event_type} requires {stage} active work")
        active = self.active
        if payload["work_item_id"] != active.work_item_id:
            raise ReV2EventError(f"{event_type} does not match active work item")
        if require_dispatch and payload["dispatch_id"] != active.dispatch_id:
            raise ReV2EventError(f"{event_type} does not match active dispatch")
        return active

    def _finish(self, event_type: str) -> None:
        self.seen += 1
        self.last_type = event_type


class _Protocol22Events(EventProtocol):
    def canonical_payload(
        self,
        event_type: str,
        payload: Mapping[str, object],
    ) -> Mapping[str, object]:
        canonical = _canonical_payload(_thaw_json(payload))
        _validate_payload(event_type, canonical)
        return canonical

    def new_state(self) -> EventReplayState:
        return Protocol22ReplayState()


PROTOCOL_22_EVENTS: EventProtocol = _Protocol22Events()


__all__ = (
    "PROTOCOL_22_EVENTS",
    "Protocol22ReplayState",
)
