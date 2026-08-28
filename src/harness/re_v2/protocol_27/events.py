"""Closed protocol-2.7 event payloads and synthesis replay ordering."""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Callable, ClassVar, Mapping

from harness.re_v2.events import (
    EventProtocol,
    EventRecord,
    EventReplayState,
    ReV2EventError,
    _canonical_payload,
    _thaw_json,
)
from harness.re_v2.protocol_22.events import PROTOCOL_22_EVENTS


_DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")
_SAFE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]*\Z")
_ATTEMPT_KINDS = frozenset(
    {"initial_generation", "result_contract_retry", "artifact_contract_retry"}
)
_SHARED_EVENTS = frozenset(
    {
        "run_created",
        "work_planned",
        "dispatch_started",
        "dispatch_observed",
        "dispatch_abandoned",
        "candidate_persisted",
        "work_item_failed",
        "executor_failed",
        "operator_pause_requested",
        "run_paused",
        "run_resumed",
        "run_completed",
        "run_failed",
    }
)
_SYNTHESIS_EVENTS = frozenset(
    {
        "synthesis_request_frozen",
        "partial_source_accepted",
        "synthesis_candidate_certified",
        "checkpoint_adopted",
        "synthesis_artifact_accepted",
        "synthesis_root_accepted",
        "synthesis_materialized",
        "synthesis_published",
        "synthesis_budget_authorized",
    }
)

PayloadValidator = Callable[[object, str], None]


def _digest(value: object, field_name: str) -> None:
    if not isinstance(value, str) or not _DIGEST_RE.fullmatch(value):
        raise ReV2EventError(f"{field_name} must be a lowercase sha256 digest")


def _safe_id(value: object, field_name: str) -> None:
    if not isinstance(value, str) or not _SAFE_ID_RE.fullmatch(value):
        raise ReV2EventError(f"{field_name} must be a nonempty safe ID")


def _string(value: object, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ReV2EventError(f"{field_name} must be a nonempty string")


def _positive(value: object, field_name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ReV2EventError(f"{field_name} must be a positive integer")


def _nullable_nonnegative(value: object, field_name: str) -> None:
    if value is not None and (
        not isinstance(value, int) or isinstance(value, bool) or value < 0
    ):
        raise ReV2EventError(f"{field_name} must be null or nonnegative")


def _boolean(value: object, field_name: str) -> None:
    if not isinstance(value, bool):
        raise ReV2EventError(f"{field_name} must be a boolean")


def _choice(choices: frozenset[str]) -> PayloadValidator:
    def validate(value: object, field_name: str) -> None:
        if value not in choices:
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
    "synthesis_request_frozen": {"request_id": _digest},
    "partial_source_accepted": {
        "receipt_id": _digest,
        "request_id": _digest,
        "source_id": _safe_id,
    },
    "synthesis_candidate_certified": {
        "artifact_hash": _digest,
        "artifact_key_id": _digest,
        "candidate_assessment_id": _digest,
        "candidate_id": _digest,
        "certification_id": _digest,
        "generated_dependency_key_ids": _digest_array,
        "work_item_id": _digest,
    },
    "checkpoint_adopted": {
        "acceptance_receipt_id": _digest,
        "adoption_receipt_id": _digest,
        "artifact_hash": _digest,
        "artifact_key_id": _digest,
        "certification_id": _digest,
        "work_item_id": _digest,
    },
    "synthesis_artifact_accepted": {
        "acceptance_receipt_id": _digest,
        "adopted": _boolean,
        "artifact_hash": _digest,
        "artifact_key_id": _digest,
        "certification_id": _digest,
        "generated_dependency_key_ids": _digest_array,
        "work_item_id": _digest,
    },
    "synthesis_root_accepted": {
        "required_artifact_key_ids": _digest_array,
        "synthesis_root_id": _digest,
    },
    "synthesis_materialized": {
        "materialization_manifest_id": _digest,
        "synthesis_root_id": _digest,
    },
    "synthesis_published": {
        "materialization_manifest_id": _digest,
        "publication_descriptor_id": _digest,
        "synthesis_root_id": _digest,
    },
    "synthesis_budget_authorized": {
        "authorized_by": _safe_id,
        "dimension": _choice(frozenset({"tokens", "active_ms"})),
        "new_value": _positive,
        "old_value": _nullable_nonnegative,
        "reason": _string,
    },
}


def _validate_synthesis_payload(
    event_type: str,
    payload: Mapping[str, object],
) -> None:
    schema = _PAYLOAD_SCHEMAS.get(event_type)
    if schema is None:
        raise ReV2EventError(f"unknown protocol-2.7 event type: {event_type!r}")
    present = frozenset(payload)
    expected = frozenset(schema)
    if present - expected:
        raise ReV2EventError(
            f"{event_type} payload has unknown fields: "
            + ", ".join(sorted(present - expected))
        )
    if expected - present:
        raise ReV2EventError(
            f"{event_type} payload is missing fields: "
            + ", ".join(sorted(expected - present))
        )
    for field_name, validator in schema.items():
        validator(_thaw_json(payload[field_name]), field_name)


@dataclass(slots=True)
class _ActiveSynthesisDispatch:
    dispatch_id: str
    work_item_id: str
    stage: str
    candidate_id: str | None = None
    certification_id: str | None = None
    artifact_key_id: str | None = None
    artifact_hash: str | None = None
    generated_dependency_key_ids: tuple[str, ...] = ()


@dataclass(slots=True)
class Protocol27ReplayState(EventReplayState):
    seen: int = 0
    terminal: bool = False
    paused: bool = False
    request_id: str | None = None
    partial_acceptances: dict[str, str] = field(default_factory=dict)
    planned_work_item_ids: set[str] = field(default_factory=set)
    attempts_by_work_item: dict[str, int] = field(default_factory=dict)
    active: _ActiveSynthesisDispatch | None = None
    adopted_by_work_item: dict[str, tuple[str, str, str, str]] = field(
        default_factory=dict
    )
    accepted_artifacts: dict[str, str] = field(default_factory=dict)
    accepted_work_item_ids: set[str] = field(default_factory=set)
    synthesis_root_id: str | None = None
    materialization_manifest_id: str | None = None
    publication_descriptor_id: str | None = None

    @property
    def has_active_dispatch(self) -> bool:
        return self.active is not None

    def consume(self, event: EventRecord) -> None:
        if self.terminal:
            raise ReV2EventError("event appears after terminal synthesis state")
        event_type = event.type
        payload = event.payload
        if self.seen == 0 and event_type != "run_created":
            raise ReV2EventError("run_created must be the first event")
        if event_type == "run_created":
            if self.seen:
                raise ReV2EventError("run_created may appear only once")
        elif event_type == "synthesis_request_frozen":
            if self.seen == 0 or self.request_id is not None:
                raise ReV2EventError("synthesis request may freeze only after run creation")
            self.request_id = str(payload["request_id"])
        elif event_type == "partial_source_accepted":
            self._accept_partial(payload)
        elif event_type == "work_planned":
            if self.request_id is None or self.planned_work_item_ids:
                raise ReV2EventError("work planning requires one frozen synthesis request")
            self.planned_work_item_ids = set(payload["work_item_ids"])
        elif event_type == "dispatch_started":
            self._start_dispatch(payload)
        elif event_type == "dispatch_observed":
            self._observe_dispatch(payload)
        elif event_type == "dispatch_abandoned":
            self._abandon_dispatch(payload)
        elif event_type == "candidate_persisted":
            self._persist_candidate(payload)
        elif event_type == "synthesis_candidate_certified":
            self._certify_candidate(payload)
        elif event_type == "checkpoint_adopted":
            self._adopt_checkpoint(payload)
        elif event_type == "synthesis_artifact_accepted":
            self._accept_artifact(payload)
        elif event_type == "synthesis_root_accepted":
            self._accept_root(payload)
        elif event_type == "synthesis_materialized":
            if self.synthesis_root_id != payload["synthesis_root_id"]:
                raise ReV2EventError("materialization requires the accepted synthesis root")
            if self.materialization_manifest_id is not None:
                raise ReV2EventError("synthesis materialization may be recorded once")
            self.materialization_manifest_id = str(payload["materialization_manifest_id"])
        elif event_type == "synthesis_published":
            if self.materialization_manifest_id is None:
                raise ReV2EventError("publication requires synthesis materialization")
            if (
                payload["synthesis_root_id"] != self.synthesis_root_id
                or payload["materialization_manifest_id"]
                != self.materialization_manifest_id
                or self.publication_descriptor_id is not None
            ):
                raise ReV2EventError("publication authority does not match materialization")
            self.publication_descriptor_id = str(payload["publication_descriptor_id"])
        elif event_type == "run_completed":
            if self.synthesis_root_id is None or self.active is not None:
                raise ReV2EventError("run completion requires a closed synthesis root")
            self.terminal = True
        elif event_type == "run_failed":
            if self.active is not None:
                raise ReV2EventError("run failure is invalid with active synthesis work")
            self.terminal = True
        elif event_type == "work_item_failed":
            if self.active is not None and (
                event.payload["work_item_id"] == self.active.work_item_id
            ):
                self.active = None
        elif event_type == "run_paused":
            if self.active is not None:
                raise ReV2EventError("run pause is invalid with active synthesis work")
            self.paused = True
        elif event_type == "run_resumed":
            if not self.paused:
                raise ReV2EventError("run resume requires a paused synthesis run")
            self.paused = False
        elif event_type in {
            "executor_failed",
            "operator_pause_requested",
        }:
            pass
        elif event_type == "synthesis_budget_authorized":
            if not self.paused:
                raise ReV2EventError(
                    "synthesis budget authorization requires a paused run"
                )
        else:
            raise ReV2EventError(f"unsupported protocol-2.7 replay event: {event_type}")
        self.seen += 1

    def _accept_partial(self, payload: Mapping[str, object]) -> None:
        if self.request_id is None or payload["request_id"] != self.request_id:
            raise ReV2EventError("partial acceptance requires its frozen request")
        source_id = str(payload["source_id"])
        receipt_id = str(payload["receipt_id"])
        if source_id in self.partial_acceptances:
            raise ReV2EventError("partial source acceptance must be unique")
        self.partial_acceptances[source_id] = receipt_id

    def _start_dispatch(self, payload: Mapping[str, object]) -> None:
        work_item_id = str(payload["work_item_id"])
        if self.paused or self.active is not None:
            raise ReV2EventError("dispatch conflicts with synthesis run state")
        if work_item_id not in self.planned_work_item_ids:
            raise ReV2EventError("dispatch work item was not planned")
        expected = self.attempts_by_work_item.get(work_item_id, 0) + 1
        if payload["attempt_index"] != expected:
            raise ReV2EventError("synthesis dispatch attempt index must be consecutive")
        attempt_kind = str(payload["attempt_kind"])
        if attempt_kind not in _ATTEMPT_KINDS:
            raise ReV2EventError("synthesis dispatch attempt kind is invalid")
        self.attempts_by_work_item[work_item_id] = expected
        self.active = _ActiveSynthesisDispatch(
            str(payload["dispatch_id"]),
            work_item_id,
            "started",
        )

    def _matching_active(
        self,
        payload: Mapping[str, object],
        stage: str,
    ) -> _ActiveSynthesisDispatch:
        active = self.active
        if active is None or active.stage != stage:
            if stage == "certified":
                raise ReV2EventError(
                    "synthesis artifact acceptance requires certification"
                )
            raise ReV2EventError(f"event requires active {stage} synthesis work")
        if payload.get("work_item_id") != active.work_item_id:
            raise ReV2EventError("event does not match active synthesis work item")
        if "dispatch_id" in payload and payload["dispatch_id"] != active.dispatch_id:
            raise ReV2EventError("event does not match active synthesis dispatch")
        return active

    def _observe_dispatch(self, payload: Mapping[str, object]) -> None:
        active = self._matching_active(payload, "started")
        active.stage = "observed"

    def _abandon_dispatch(self, payload: Mapping[str, object]) -> None:
        self._matching_active(payload, "started")
        self.active = None

    def _persist_candidate(self, payload: Mapping[str, object]) -> None:
        active = self._matching_active(payload, "observed")
        active.candidate_id = str(payload["candidate_id"])
        active.stage = "persisted"

    def _certify_candidate(self, payload: Mapping[str, object]) -> None:
        active = self._matching_active(payload, "persisted")
        if payload["candidate_id"] != active.candidate_id:
            raise ReV2EventError("certification does not match persisted candidate")
        self._require_dependencies(payload["generated_dependency_key_ids"])
        active.certification_id = str(payload["certification_id"])
        active.artifact_key_id = str(payload["artifact_key_id"])
        active.artifact_hash = str(payload["artifact_hash"])
        active.generated_dependency_key_ids = tuple(
            payload["generated_dependency_key_ids"]
        )
        active.stage = "certified"

    def _adopt_checkpoint(self, payload: Mapping[str, object]) -> None:
        work_item_id = str(payload["work_item_id"])
        if self.active is not None or work_item_id not in self.planned_work_item_ids:
            raise ReV2EventError("checkpoint adoption requires idle planned work")
        if work_item_id in self.adopted_by_work_item:
            raise ReV2EventError("checkpoint may be adopted once per work item")
        self.adopted_by_work_item[work_item_id] = (
            str(payload["artifact_key_id"]),
            str(payload["artifact_hash"]),
            str(payload["certification_id"]),
            str(payload["acceptance_receipt_id"]),
        )

    def _accept_artifact(self, payload: Mapping[str, object]) -> None:
        work_item_id = str(payload["work_item_id"])
        observed = (
            str(payload["artifact_key_id"]),
            str(payload["artifact_hash"]),
            str(payload["certification_id"]),
            str(payload["acceptance_receipt_id"]),
        )
        if bool(payload["adopted"]):
            if self.adopted_by_work_item.get(work_item_id) != observed:
                raise ReV2EventError("adopted acceptance requires matching checkpoint authority")
        else:
            active = self._matching_active(payload, "certified")
            if (
                active.artifact_key_id,
                active.artifact_hash,
                active.certification_id,
            ) != observed[:3]:
                raise ReV2EventError("artifact acceptance does not match certification")
        self._require_dependencies(payload["generated_dependency_key_ids"])
        artifact_key_id, artifact_hash = observed[:2]
        if artifact_key_id in self.accepted_artifacts:
            raise ReV2EventError("synthesis artifact key may be accepted once")
        self.accepted_artifacts[artifact_key_id] = artifact_hash
        self.accepted_work_item_ids.add(work_item_id)
        if not bool(payload["adopted"]):
            self.active = None

    def _require_dependencies(self, values: object) -> None:
        missing = set(values) - set(self.accepted_artifacts)  # type: ignore[arg-type]
        if missing:
            raise ReV2EventError("synthesis artifact requires accepted dependencies")

    def _accept_root(self, payload: Mapping[str, object]) -> None:
        if self.active is not None or self.synthesis_root_id is not None:
            raise ReV2EventError("synthesis root requires idle unclosed work")
        if self.accepted_work_item_ids != self.planned_work_item_ids:
            raise ReV2EventError("synthesis root requires complete work closure")
        if set(payload["required_artifact_key_ids"]) != set(self.accepted_artifacts):
            raise ReV2EventError("synthesis root artifact closure mismatch")
        self.synthesis_root_id = str(payload["synthesis_root_id"])


@dataclass(frozen=True, slots=True)
class _Protocol27Events(EventProtocol):
    parent_protocol: EventProtocol
    PROTOCOL_VERSION: ClassVar[str] = "2.7"

    def canonical_payload(
        self,
        event_type: str,
        payload: Mapping[str, object],
    ) -> Mapping[str, object]:
        if event_type in _SHARED_EVENTS:
            return self.parent_protocol.canonical_payload(event_type, payload)
        if event_type not in _SYNTHESIS_EVENTS:
            raise ReV2EventError(f"unknown protocol-2.7 event type: {event_type!r}")
        canonical = _canonical_payload(_thaw_json(payload))
        _validate_synthesis_payload(event_type, canonical)
        return canonical

    def new_state(self) -> EventReplayState:
        return Protocol27ReplayState()


def protocol_27_events(
    parent_protocol: EventProtocol = PROTOCOL_22_EVENTS,
) -> EventProtocol:
    if not callable(getattr(parent_protocol, "canonical_payload", None)):
        raise ReV2EventError("protocol-2.7 parent event protocol is invalid")
    return _Protocol27Events(parent_protocol)


PROTOCOL_27_EVENTS: EventProtocol = protocol_27_events()


__all__ = (
    "PROTOCOL_27_EVENTS",
    "Protocol27ReplayState",
    "protocol_27_events",
)
