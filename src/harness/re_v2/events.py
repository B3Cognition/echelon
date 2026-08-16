"""Append-only, hash-chained execution events for RE v2."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import fcntl
import json
import math
import os
from pathlib import Path
import re
from types import MappingProxyType
from typing import Callable, Iterable, Mapping

from .canonical import canonical_json_bytes, content_digest
from .model import ExecutionObservation
from .run_store import ReV2Paths


EVENT_SCHEMA_VERSION = 1

_DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")
_SAFE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]*\Z")
_RFC3339_RE = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})\Z"
)


class ReV2EventError(RuntimeError):
    """Raised when event history cannot be trusted or extended safely."""


def _thaw_json(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value


def _freeze_json(value: object) -> object:
    if isinstance(value, dict):
        return MappingProxyType(
            {key: _freeze_json(item) for key, item in value.items()}
        )
    if isinstance(value, list):
        return tuple(_freeze_json(item) for item in value)
    return value


@dataclass(frozen=True, slots=True)
class EventRecord:
    schema_version: int
    seq: int
    previous_event_hash: str | None
    occurred_at: str
    type: str
    payload: Mapping[str, object]
    event_hash: str

    def to_json_dict(self) -> dict[str, object]:
        return {
            "event_hash": self.event_hash,
            "occurred_at": self.occurred_at,
            "payload": _thaw_json(self.payload),
            "previous_event_hash": self.previous_event_hash,
            "schema_version": self.schema_version,
            "seq": self.seq,
            "type": self.type,
        }

    def identity_dict(self) -> dict[str, object]:
        value = self.to_json_dict()
        del value["event_hash"]
        return value


def _string(value: object, field: str) -> None:
    if not isinstance(value, str) or not value:
        raise ReV2EventError(f"{field} must be a nonempty string")


def _safe_id(value: object, field: str) -> None:
    if not isinstance(value, str) or not _SAFE_ID_RE.fullmatch(value):
        raise ReV2EventError(f"{field} must be a nonempty safe ID")


def _digest(value: object, field: str) -> None:
    if not isinstance(value, str) or not _DIGEST_RE.fullmatch(value):
        raise ReV2EventError(f"{field} must be a lowercase sha256 digest")


def _nonnegative(value: object, field: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ReV2EventError(f"{field} must be a nonnegative integer")


def _positive(value: object, field: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ReV2EventError(f"{field} must be a positive integer")


def _digest_array(value: object, field: str) -> None:
    if not isinstance(value, list):
        raise ReV2EventError(f"{field} must be an array")
    for item in value:
        _digest(item, field)
    if value != sorted(set(value)):
        raise ReV2EventError(f"{field} must be unique and sorted")


def _observation(value: object, field: str) -> None:
    try:
        ExecutionObservation.from_json_dict(value)
    except (TypeError, ValueError) as exc:
        raise ReV2EventError(f"{field} is invalid: {exc}") from exc


def _nullable_nonnegative(value: object, field: str) -> None:
    if value is not None:
        _nonnegative(value, field)


def _budget_dimension(value: object, field: str) -> None:
    if value not in {"tokens", "active_ms"}:
        raise ReV2EventError(f"{field} must be tokens or active_ms")


def _attempt_kind(value: object, field: str) -> None:
    if value not in {
        "initial_generation",
        "semantic_repair",
        "result_contract_retry",
    }:
        raise ReV2EventError(f"{field} has an unsupported attempt kind")


PayloadValidator = Callable[[object, str], None]

_PAYLOAD_SCHEMAS: dict[str, dict[str, PayloadValidator]] = {
    "run_created": {"run_manifest_id": _digest},
    "work_planned": {"work_item_ids": _digest_array},
    "dispatch_leased": {"dispatch_id": _safe_id, "work_item_id": _digest},
    "dispatch_lease_retired": {
        "dispatch_id": _safe_id,
        "reason": _string,
        "work_item_id": _digest,
    },
    "dispatch_started": {
        "attempt_index": _positive,
        "attempt_kind": _attempt_kind,
        "dispatch_id": _safe_id,
        "work_item_id": _digest,
    },
    "dispatch_observed": {
        "dispatch_id": _safe_id,
        "observation": _observation,
        "work_item_id": _digest,
    },
    "candidate_persisted": {
        "candidate_id": _safe_id,
        "dispatch_id": _safe_id,
        "work_item_id": _digest,
    },
    "candidate_certified": {
        "candidate_id": _safe_id,
        "certification_id": _digest,
        "work_item_id": _digest,
    },
    "candidate_rejected": {
        "candidate_id": _safe_id,
        "certification_id": _digest,
        "reason": _string,
        "work_item_id": _digest,
    },
    "artifact_accepted": {
        "artifact_hash": _digest,
        "artifact_key_id": _digest,
        "certification_id": _digest,
        "work_item_id": _digest,
    },
    "budget_authorized": {
        "authorized_by": _safe_id,
        "dimension": _budget_dimension,
        "new_value": _positive,
        "old_value": _nullable_nonnegative,
        "reason": _string,
    },
    "operator_pause_requested": {"reason": _string, "requested_by": _safe_id},
    "checkpoint_recorded": {
        "artifact_hash": _digest,
        "certification_id": _digest,
        "work_item_id": _digest,
    },
    "synthesis_requested": {
        "input_root_hashes": _digest_array,
        "synthesis_policy_hash": _digest,
    },
    "synthesis_accepted": {
        "artifact_hash": _digest,
        "input_root_hashes": _digest_array,
        "synthesis_policy_hash": _digest,
    },
    "run_paused": {"reason": _string, "reason_code": _safe_id},
    "run_resumed": {"reason": _string},
    "run_completed": {"reason": _string},
    "run_finalized_partial": {"reason": _string},
    "run_failed": {"reason": _string},
}

_TERMINAL_TYPES = {"run_completed", "run_finalized_partial", "run_failed"}
_PAUSED_CONTROL_TYPES = {"budget_authorized", "operator_pause_requested"}
_PAUSED_RECOVERY_TYPES = {
    "dispatch_lease_retired",
    "dispatch_started",
    "dispatch_observed",
    "candidate_persisted",
    "candidate_certified",
    "candidate_rejected",
    "artifact_accepted",
    "checkpoint_recorded",
}
def _validate_rfc3339(value: object) -> str:
    if not isinstance(value, str) or not _RFC3339_RE.fullmatch(value):
        raise ReV2EventError("occurred_at must be an RFC3339 timestamp")
    try:
        datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError as exc:
        raise ReV2EventError("occurred_at must be an RFC3339 timestamp") from exc
    return value


def _parsed_rfc3339(value: str) -> datetime:
    return datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)


def _canonical_payload(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise ReV2EventError("event payload must be a JSON object")
    try:
        canonical = json.loads(canonical_json_bytes(dict(value)))
    except (TypeError, ValueError) as exc:
        raise ReV2EventError(f"event payload must contain canonical JSON values: {exc}") from exc
    return _freeze_json(canonical)  # type: ignore[return-value]


def _validate_payload(event_type: object, payload: Mapping[str, object]) -> None:
    if not isinstance(event_type, str) or event_type not in _PAYLOAD_SCHEMAS:
        raise ReV2EventError(f"unknown event type: {event_type!r}")
    schema = _PAYLOAD_SCHEMAS[event_type]
    present = set(payload)
    expected = set(schema)
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
    for field, validator in schema.items():
        validator(_thaw_json(payload[field]), field)


def _event_hash(identity: Mapping[str, object]) -> str:
    return content_digest(dict(identity))


@dataclass(slots=True)
class _ReplayState:
    seen: int = 0
    terminal: bool = False
    paused: bool = False
    pause_requested: bool = False
    last_type: str | None = None
    dispatch_id: str | None = None
    work_item_id: str | None = None
    work_stage: str | None = None
    candidate_id: str | None = None
    certification_id: str | None = None
    last_acceptance: tuple[str, str, str] | None = None
    synthesis: tuple[tuple[str, ...], str] | None = None
    dispatch_ids: set[str] = field(default_factory=set)
    candidate_ids: set[str] = field(default_factory=set)
    attempt_indices: dict[tuple[str, str], int] = field(default_factory=dict)
    initial_generation_work_items: set[str] = field(default_factory=set)
    dispatched_work_items: set[str] = field(default_factory=set)
    dispatch_started_at: dict[str, str] = field(default_factory=dict)
    active_attempt_kind: str | None = None
    active_result_contract_valid: bool | None = None
    eligible_work_item_id: str | None = None
    semantic_repair_eligible: bool = False
    result_contract_retry_eligible: bool = False

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
                if self.last_type not in _PAUSED_CONTROL_TYPES:
                    raise ReV2EventError(
                        "paused run requires authorization or operator action before run_resumed"
                    )
                self.paused = False
            elif event_type in _PAUSED_CONTROL_TYPES:
                self._finish(event_type)
                return
            elif event_type not in _PAUSED_RECOVERY_TYPES:
                raise ReV2EventError(f"{event_type} is not allowed while run is paused")
            if event_type == "run_resumed":
                self._finish(event_type)
                return

        if self.pause_requested and event_type != "run_paused":
            raise ReV2EventError("operator pause request must be followed by run_paused")
        if event_type == "run_resumed":
            raise ReV2EventError("run_resumed requires a paused run")
        if event_type == "budget_authorized":
            raise ReV2EventError("budget_authorized requires a paused run")
        if event_type == "operator_pause_requested":
            self.pause_requested = True
        elif event_type == "run_paused":
            self.pause_requested = False
            self.paused = True
        elif event_type == "dispatch_lease_retired":
            dispatch_id = str(payload["dispatch_id"])
            if dispatch_id in self.dispatch_ids:
                raise ReV2EventError("dispatch_id must be globally unique")
            self.dispatch_ids.add(dispatch_id)
        elif event_type == "dispatch_leased":
            if self.work_stage is not None:
                if not (
                    self.work_stage == "observed"
                    and self.work_item_id == self.eligible_work_item_id
                    and self.result_contract_retry_eligible
                ):
                    raise ReV2EventError("dispatch_leased requires no active work item")
                if payload["work_item_id"] != self.eligible_work_item_id:
                    raise ReV2EventError(
                        "dispatch_leased retry must retain the eligible work item"
                    )
                self._clear_work()
            dispatch_id = str(payload["dispatch_id"])
            if dispatch_id in self.dispatch_ids:
                raise ReV2EventError("dispatch_id must be globally unique")
            self.dispatch_ids.add(dispatch_id)
            self.dispatch_id = dispatch_id
            self.work_item_id = str(payload["work_item_id"])
            self.work_stage = "leased"
        elif event_type == "dispatch_started":
            self._require_work(event, "leased")
            work_item_id = str(payload["work_item_id"])
            attempt_kind = str(payload["attempt_kind"])
            attempt_index = int(payload["attempt_index"])
            attempt_key = (work_item_id, attempt_kind)
            expected_index = self.attempt_indices.get(attempt_key, 0) + 1
            if attempt_index != expected_index:
                raise ReV2EventError(
                    "dispatch_started attempt_index must be consecutive per work item and kind"
                )
            if attempt_kind == "initial_generation" and work_item_id in self.dispatched_work_items:
                raise ReV2EventError(
                    "dispatch_started requires initial_generation as a work item's first dispatch"
                )
            if (
                attempt_kind != "initial_generation"
                and work_item_id not in self.initial_generation_work_items
            ):
                raise ReV2EventError(
                    "dispatch_started requires initial_generation as a work item's first dispatch"
                )
            if attempt_kind == "semantic_repair" and not self._eligible_for(
                work_item_id, "semantic_repair"
            ):
                raise ReV2EventError(
                    "semantic_repair requires the immediately preceding rejected generation"
                )
            if attempt_kind == "result_contract_retry" and not self._eligible_for(
                work_item_id, "result_contract_retry"
            ):
                raise ReV2EventError(
                    "result_contract_retry requires the immediately preceding invalid contract observation"
                )
            self.attempt_indices[attempt_key] = attempt_index
            if attempt_kind == "initial_generation":
                self.initial_generation_work_items.add(work_item_id)
            else:
                self._clear_eligibility()
            self.dispatched_work_items.add(work_item_id)
            self.dispatch_started_at[str(payload["dispatch_id"])] = event.occurred_at
            self.active_attempt_kind = attempt_kind
            self.active_result_contract_valid = None
            self.work_stage = "started"
        elif event_type == "dispatch_observed":
            self._require_work(event, "started")
            started_at = self.dispatch_started_at.get(str(payload["dispatch_id"]))
            if started_at is None or _parsed_rfc3339(event.occurred_at) < _parsed_rfc3339(started_at):
                raise ReV2EventError("dispatch_observed occurs before dispatch_started")
            self.active_result_contract_valid = bool(
                payload["observation"]["result_contract_valid"]
            )
            if self.active_result_contract_valid:
                self._clear_eligibility()
            else:
                self._set_eligibility(
                    str(payload["work_item_id"]), semantic_repair=False,
                    result_contract_retry=True,
                )
            self.work_stage = "observed"
        elif event_type == "candidate_persisted":
            self._require_work(event, "observed")
            candidate_id = str(payload["candidate_id"])
            if candidate_id in self.candidate_ids:
                raise ReV2EventError("candidate_id must be globally unique")
            self.candidate_ids.add(candidate_id)
            self.candidate_id = candidate_id
            self.work_stage = "persisted"
        elif event_type in {"candidate_certified", "candidate_rejected"}:
            self._require_work(event, "persisted", require_dispatch=False)
            if payload["candidate_id"] != self.candidate_id:
                raise ReV2EventError(f"{event_type} does not match persisted candidate")
            self.certification_id = str(payload["certification_id"])
            if event_type == "candidate_rejected":
                self._set_eligibility(
                    str(payload["work_item_id"]),
                    semantic_repair=self.active_attempt_kind
                    in {"initial_generation", "semantic_repair"},
                    result_contract_retry=self.active_result_contract_valid is False,
                )
                self._clear_work()
            else:
                self._clear_eligibility()
                self.work_stage = "certified"
        elif event_type == "artifact_accepted":
            self._require_work(event, "certified", require_dispatch=False)
            if payload["certification_id"] != self.certification_id:
                raise ReV2EventError("artifact_accepted does not match certification")
            self.last_acceptance = (
                str(payload["work_item_id"]),
                str(payload["certification_id"]),
                str(payload["artifact_hash"]),
            )
            self._clear_eligibility()
            self._clear_work()
        elif event_type == "checkpoint_recorded":
            observed = (
                str(payload["work_item_id"]),
                str(payload["certification_id"]),
                str(payload["artifact_hash"]),
            )
            if self.last_type != "artifact_accepted" or observed != self.last_acceptance:
                raise ReV2EventError("checkpoint_recorded requires a matching accepted artifact")
            self.last_acceptance = None
        elif event_type == "synthesis_requested":
            if self.synthesis is not None:
                raise ReV2EventError("synthesis_requested conflicts with pending synthesis")
            self.synthesis = (
                tuple(payload["input_root_hashes"]),
                str(payload["synthesis_policy_hash"]),
            )
        elif event_type == "synthesis_accepted":
            observed = (
                tuple(payload["input_root_hashes"]),
                str(payload["synthesis_policy_hash"]),
            )
            if observed != self.synthesis:
                raise ReV2EventError("synthesis_accepted requires matching synthesis_requested")
            self.synthesis = None
        elif event_type in _TERMINAL_TYPES:
            if event_type != "run_failed" and self.work_stage is not None:
                raise ReV2EventError(f"{event_type} is invalid with active work")
            self.terminal = True

        self._finish(event_type)

    def _require_work(
        self, event: EventRecord, stage: str, *, require_dispatch: bool = True
    ) -> None:
        if self.work_stage != stage:
            raise ReV2EventError(f"{event.type} requires {stage} work")
        if event.payload["work_item_id"] != self.work_item_id:
            raise ReV2EventError(f"{event.type} does not match active work item")
        if require_dispatch and event.payload["dispatch_id"] != self.dispatch_id:
            raise ReV2EventError(f"{event.type} does not match active dispatch")

    def _clear_work(self) -> None:
        self.dispatch_id = None
        self.work_item_id = None
        self.work_stage = None
        self.candidate_id = None
        self.certification_id = None
        self.active_attempt_kind = None
        self.active_result_contract_valid = None

    def _set_eligibility(
        self, work_item_id: str, *, semantic_repair: bool, result_contract_retry: bool
    ) -> None:
        self.eligible_work_item_id = work_item_id
        self.semantic_repair_eligible = semantic_repair
        self.result_contract_retry_eligible = result_contract_retry

    def _clear_eligibility(self) -> None:
        self.eligible_work_item_id = None
        self.semantic_repair_eligible = False
        self.result_contract_retry_eligible = False

    def _eligible_for(self, work_item_id: str, attempt_kind: str) -> bool:
        if work_item_id != self.eligible_work_item_id:
            return False
        if attempt_kind == "semantic_repair":
            return self.semantic_repair_eligible
        return self.result_contract_retry_eligible

    def _finish(self, event_type: str) -> None:
        self.seen += 1
        self.last_type = event_type


class EventStore:
    """Serialize durable appends and replay the complete validated history."""

    def __init__(self, path: Path | ReV2Paths):
        self.path = path.events if isinstance(path, ReV2Paths) else Path(path)
        self.lock_path = self.path.with_name("events.lock")

    def append(
        self, event_type: str, payload: Mapping[str, object], *, occurred_at: str
    ) -> EventRecord:
        timestamp = _validate_rfc3339(occurred_at)
        canonical_payload = _canonical_payload(payload)
        _validate_payload(event_type, canonical_payload)
        self._validate_parent()

        lock_fd = self._open_lock()
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            history = self._read_replay()
            previous = history[-1].event_hash if history else None
            identity: dict[str, object] = {
                "occurred_at": timestamp,
                "payload": _thaw_json(canonical_payload),
                "previous_event_hash": previous,
                "schema_version": EVENT_SCHEMA_VERSION,
                "seq": len(history) + 1,
                "type": event_type,
            }
            event = EventRecord(
                event_hash=_event_hash(identity),
                occurred_at=timestamp,
                payload=canonical_payload,
                previous_event_hash=previous,
                schema_version=EVENT_SCHEMA_VERSION,
                seq=len(history) + 1,
                type=event_type,
            )
            state = _replay_state(history)
            state.consume(event)
            existed = self.path.exists()
            fd = self._open_events_for_append()
            try:
                _write_all(fd, canonical_json_bytes(event.to_json_dict()))
                _fsync(fd)
            finally:
                os.close(fd)
            if not existed:
                _fsync_directory(self.path.parent)
            return event
        except ReV2EventError:
            raise
        except OSError as exc:
            raise ReV2EventError(f"cannot append durable event: {exc}") from exc
        finally:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
            finally:
                os.close(lock_fd)

    def replay(self) -> tuple[EventRecord, ...]:
        self._validate_parent()
        lock_fd = self._open_lock()
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_SH)
            return self._read_replay()
        except ReV2EventError:
            raise
        except OSError as exc:
            raise ReV2EventError(f"cannot replay durable events: {exc}") from exc
        finally:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
            finally:
                os.close(lock_fd)

    def _read_replay(self) -> tuple[EventRecord, ...]:
        if not self.path.exists():
            return ()
        if self.path.is_symlink() or not self.path.is_file():
            raise ReV2EventError(f"unsafe event log path: {self.path}")
        payload = self.path.read_bytes()
        if not payload:
            return ()
        if not payload.endswith(b"\n"):
            raise ReV2EventError("partial final event record")

        events: list[EventRecord] = []
        for index, line in enumerate(payload.splitlines(), start=1):
            try:
                raw = json.loads(
                    line,
                    parse_constant=_reject_json_constant,
                    parse_float=_finite_json_float,
                )
            except (UnicodeDecodeError, ValueError, OverflowError) as exc:
                raise ReV2EventError(f"event record {index} is invalid JSON") from exc
            try:
                event = _record_from_raw(raw, index)
                canonical = canonical_json_bytes(event.to_json_dict())
            except ReV2EventError as exc:
                if str(exc).startswith(f"event record {index} "):
                    raise
                raise ReV2EventError(f"event record {index} is invalid: {exc}") from exc
            except (TypeError, ValueError, OverflowError) as exc:
                raise ReV2EventError(
                    f"event record {index} cannot be canonicalized"
                ) from exc
            if canonical != line + b"\n":
                raise ReV2EventError(f"event record {index} is not canonical JSON")
            events.append(event)
        return validate_event_history(events)

    def _validate_parent(self) -> None:
        if self.path.parent.is_symlink() or not self.path.parent.is_dir():
            raise ReV2EventError(f"event log parent is not a safe directory: {self.path.parent}")

    def _open_lock(self) -> int:
        if self.lock_path.is_symlink():
            raise ReV2EventError(f"unsafe event lock path: {self.lock_path}")
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        try:
            return os.open(self.lock_path, flags, 0o600)
        except OSError as exc:
            raise ReV2EventError(f"cannot open event lock: {exc}") from exc

    def _open_events_for_append(self) -> int:
        if self.path.is_symlink():
            raise ReV2EventError(f"unsafe event log path: {self.path}")
        flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        return os.open(self.path, flags, 0o600)


def _record_from_raw(raw: object, index: int) -> EventRecord:
    fields = {
        "event_hash",
        "occurred_at",
        "payload",
        "previous_event_hash",
        "schema_version",
        "seq",
        "type",
    }
    if not isinstance(raw, dict):
        raise ReV2EventError(f"event record {index} must be a JSON object")
    unknown = set(raw) - fields
    missing = fields - set(raw)
    if unknown:
        raise ReV2EventError(
            f"event record {index} has unknown fields: {', '.join(sorted(unknown))}"
        )
    if missing:
        raise ReV2EventError(
            f"event record {index} is missing fields: {', '.join(sorted(missing))}"
        )

    return EventRecord(
        event_hash=raw["event_hash"],
        occurred_at=raw["occurred_at"],
        payload=_canonical_payload(raw["payload"]),
        previous_event_hash=raw["previous_event_hash"],
        schema_version=raw["schema_version"],
        seq=raw["seq"],
        type=raw["type"],
    )


def validate_event_history(events: Iterable[EventRecord]) -> tuple[EventRecord, ...]:
    """Validate the complete immutable event history before any projection reads it."""
    history = tuple(events)
    state = _ReplayState()
    previous: str | None = None
    for index, event in enumerate(history, start=1):
        _validate_event_record(event, index)
        if event.seq != index:
            raise ReV2EventError(
                f"event record {index} has nonconsecutive sequence {event.seq}"
            )
        if event.previous_event_hash != previous:
            raise ReV2EventError(f"event record {index} has wrong previous event hash")
        state.consume(event)
        previous = event.event_hash
    return history


def _validate_event_record(event: object, index: int) -> None:
    if not isinstance(event, EventRecord):
        raise ReV2EventError(f"event record {index} must be an EventRecord")
    if event.schema_version != EVENT_SCHEMA_VERSION or isinstance(
        event.schema_version, bool
    ):
        raise ReV2EventError(f"event record {index} has unknown event schema version")
    if not isinstance(event.seq, int) or isinstance(event.seq, bool) or event.seq <= 0:
        raise ReV2EventError(f"event record {index} has invalid sequence")
    if event.previous_event_hash is not None:
        _digest(event.previous_event_hash, "previous_event_hash")
    _validate_rfc3339(event.occurred_at)
    if not isinstance(event.payload, Mapping):
        raise ReV2EventError(f"event record {index} payload must be a JSON object")
    _digest(event.event_hash, "event_hash")
    if event.event_hash != _event_hash(event.identity_dict()):
        raise ReV2EventError(f"event record {index} has invalid event hash")
    _validate_payload(event.type, event.payload)


def _reject_json_constant(value: str) -> object:
    raise ValueError(f"nonfinite JSON number: {value}")


def _finite_json_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError(f"overflowing JSON number: {value}")
    return parsed


def _replay_state(events: tuple[EventRecord, ...]) -> _ReplayState:
    state = _ReplayState()
    for event in events:
        state.consume(event)
    return state


def _write_all(fd: int, payload: bytes) -> None:
    offset = 0
    while offset < len(payload):
        try:
            written = os.write(fd, payload[offset:])
        except InterruptedError:
            continue
        if written <= 0:
            raise OSError("short write while appending event")
        offset += written


def _fsync(fd: int) -> None:
    while True:
        try:
            os.fsync(fd)
            return
        except InterruptedError:
            continue


def _fsync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_CLOEXEC", 0))
    try:
        _fsync(fd)
    finally:
        os.close(fd)


__all__ = (
    "EVENT_SCHEMA_VERSION",
    "EventRecord",
    "EventStore",
    "ReV2EventError",
    "validate_event_history",
)
