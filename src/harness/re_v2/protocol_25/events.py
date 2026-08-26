"""Protocol-2.5 semantic events over the shared protocol-2.4 replay machine."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar, Literal, Mapping

from harness.re_v2.events import (
    EventProtocol,
    EventRecord,
    EventReplayState,
    ReV2EventError,
    _canonical_payload,
    _thaw_json,
)
from harness.re_v2.protocol_24.events import PROTOCOL_24_EVENTS, Protocol24ReplayState


SemanticStateV1 = Literal[
    "running_prerequisites",
    "running_audit",
    "epoch_frozen",
    "running_resolution",
    "running_closure_recheck",
    "running_source_guard",
    "paused_resource",
    "blocked_incomplete",
    "blocked_plateau",
    "next_epoch_required",
    "complete",
]

_DIGEST_PREFIX = "sha256:"
_SEMANTIC_START_EVENTS = frozenset(
    {
        "semantic_resolution_started",
        "closure_recheck_started",
        "source_composition_guard_started",
    }
)
_SEMANTIC_EVENTS = frozenset(
    {
        "audit_candidate_accepted",
        "audit_epoch_frozen",
        *_SEMANTIC_START_EVENTS,
        "semantic_resolution_accepted",
        "target_closure_assessed",
        "source_composition_assessed",
        "finding_closure_recorded",
        "semantic_progress_recorded",
        "semantic_plateau_reached",
        "audit_closure_root_accepted",
        "l3_source_root_accepted",
        "semantic_budget_authorized",
    }
)


def _digest(value: object, field_name: str) -> None:
    if not isinstance(value, str) or not value.startswith(_DIGEST_PREFIX):
        raise ReV2EventError(f"{field_name} must be a lowercase sha256 digest")
    suffix = value[len(_DIGEST_PREFIX) :]
    if len(suffix) != 64 or any(character not in "0123456789abcdef" for character in suffix):
        raise ReV2EventError(f"{field_name} must be a lowercase sha256 digest")


def _safe_id(value: object, field_name: str) -> None:
    if not isinstance(value, str) or not value or any(
        not (character.isalnum() or character in "._:-") for character in value
    ):
        raise ReV2EventError(f"{field_name} must be a nonempty safe ID")


def _positive(value: object, field_name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ReV2EventError(f"{field_name} must be a positive integer")


def _nullable_nonnegative(value: object, field_name: str) -> None:
    if value is not None and (
        not isinstance(value, int) or isinstance(value, bool) or value < 0
    ):
        raise ReV2EventError(f"{field_name} must be null or a nonnegative integer")


def _string(value: object, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ReV2EventError(f"{field_name} must be a nonempty string")


def _boolean(value: object, field_name: str) -> None:
    if not isinstance(value, bool):
        raise ReV2EventError(f"{field_name} must be a boolean")


def _choice(*choices: str):  # type: ignore[no-untyped-def]
    allowed = frozenset(choices)

    def validate(value: object, field_name: str) -> None:
        if value not in allowed:
            raise ReV2EventError(f"{field_name} must be one of {sorted(allowed)}")

    return validate


def _digest_array(value: object, field_name: str) -> None:
    if not isinstance(value, list):
        raise ReV2EventError(f"{field_name} must be an array")
    for item in value:
        _digest(item, field_name)
    if value != sorted(set(value)):
        raise ReV2EventError(f"{field_name} must be sorted and unique")


_TARGET_OPERATION_FIELDS = {
    "audit_target_id": _digest,
    "dispatch_id": _safe_id,
    "semantic_round": _positive,
    "source_cycle_id": _safe_id,
    "source_id": _digest,
    "work_item_id": _digest,
}
_PAYLOAD_SCHEMAS = {
    "audit_candidate_accepted": {
        "audit_candidate_authority_id": _digest,
        "audit_target_id": _digest,
    },
    "audit_epoch_frozen": {
        "audit_epoch_id": _digest,
        "audit_target_ids": _digest_array,
    },
    "semantic_resolution_started": _TARGET_OPERATION_FIELDS,
    "semantic_resolution_accepted": {
        "audit_target_id": _digest,
        "resolution_overlay_id": _digest,
        "semantic_round": _positive,
        "source_cycle_id": _safe_id,
        "source_id": _digest,
        "work_item_id": _digest,
    },
    "closure_recheck_started": _TARGET_OPERATION_FIELDS,
    "target_closure_assessed": {
        "audit_target_id": _digest,
        "semantic_round": _positive,
        "source_cycle_id": _safe_id,
        "source_id": _digest,
        "target_closure_assessment_id": _digest,
        "work_item_id": _digest,
    },
    "source_composition_guard_started": {
        "dispatch_id": _safe_id,
        "participating_target_ids": _digest_array,
        "semantic_round": _positive,
        "source_cycle_id": _safe_id,
        "source_id": _digest,
        "work_item_id": _digest,
    },
    "source_composition_assessed": {
        "implicated_finding_ids": _digest_array,
        "passed": _boolean,
        "semantic_round": _positive,
        "source_composition_assessment_id": _digest,
        "source_cycle_id": _safe_id,
        "source_id": _digest,
        "work_item_id": _digest,
    },
    "finding_closure_recorded": {
        "audit_target_id": _digest,
        "finding_closure_receipt_id": _digest,
        "finding_key_id": _digest,
        "semantic_round": _positive,
        "source_composition_assessment_id": _digest,
        "source_cycle_id": _safe_id,
        "verdict": _choice("closed", "open"),
    },
    "semantic_progress_recorded": {
        "audit_target_id": _digest,
        "semantic_round": _positive,
        "source_cycle_id": _safe_id,
        "unresolved_after_ids": _digest_array,
        "unresolved_before_ids": _digest_array,
    },
    "semantic_plateau_reached": {
        "audit_target_id": _digest,
        "semantic_round": _positive,
        "unresolved_finding_ids": _digest_array,
    },
    "audit_closure_root_accepted": {
        "audit_closure_root_id": _digest,
        "audit_epoch_id": _digest,
        "deferred_observation_ids": _digest_array,
        "unresolved_finding_ids": _digest_array,
    },
    "l3_source_root_accepted": {
        "l3_source_root_id": _digest,
        "scope_state": _choice("complete", "next_epoch_required"),
        "source_id": _digest,
    },
    "semantic_budget_authorized": {
        "authorized_by": _safe_id,
        "dimension": _choice("tokens", "active_ms"),
        "new_value": _positive,
        "old_value": _nullable_nonnegative,
        "reason": _string,
    },
}


def _validate_semantic_payload(event_type: str, payload: Mapping[str, object]) -> None:
    schema = _PAYLOAD_SCHEMAS.get(event_type)
    if schema is None:
        raise ReV2EventError(f"unknown protocol-2.5 event type: {event_type!r}")
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


@dataclass(slots=True)
class _SemanticOperation:
    event_type: str
    dispatch_id: str
    work_item_id: str
    source_cycle_id: str
    source_id: str
    semantic_round: int
    audit_target_id: str | None
    stage: str = "provider"


@dataclass(slots=True)
class _SourceCycle:
    source_cycle_id: str
    source_id: str
    semantic_round: int
    resolution_targets: set[str] = field(default_factory=set)
    accepted_resolution_targets: set[str] = field(default_factory=set)
    target_assessments: dict[str, str] = field(default_factory=dict)
    participating_targets: tuple[str, ...] = ()
    source_assessment_id: str | None = None
    guard_passed: bool | None = None
    closure_verdicts_by_target: dict[str, dict[str, str]] = field(
        default_factory=dict
    )
    progress_targets: set[str] = field(default_factory=set)

    @property
    def complete(self) -> bool:
        return bool(self.participating_targets) and self.progress_targets == set(
            self.participating_targets
        )


@dataclass(slots=True)
class Protocol25ReplayState(EventReplayState):
    """Replay only L3 ordering while delegating shared/adoption behavior."""

    shared: Protocol24ReplayState = field(default_factory=Protocol24ReplayState)
    audit_candidates: dict[str, str] = field(default_factory=dict)
    audit_epoch_id: str | None = None
    audit_target_ids: tuple[str, ...] = ()
    pending_semantic_binding: bool = False
    semantic_operation: _SemanticOperation | None = None
    source_cycles: dict[str, _SourceCycle] = field(default_factory=dict)
    rounds_by_target: dict[str, int] = field(default_factory=dict)
    no_reduction_rounds_by_target: dict[str, int] = field(default_factory=dict)
    unresolved_by_target: dict[str, frozenset[str]] = field(default_factory=dict)
    plateau_targets: set[str] = field(default_factory=set)
    audit_closure_roots: set[str] = field(default_factory=set)
    l3_source_root_states: dict[str, str] = field(default_factory=dict)

    def consume(self, event: EventRecord) -> None:
        if self.shared.shared.terminal:
            raise ReV2EventError("event appears after terminal run state")
        if self.pending_semantic_binding and event.type not in _SEMANTIC_START_EVENTS:
            raise ReV2EventError(
                "dispatch after audit epoch freeze must be bound to a semantic operation"
            )
        if self.semantic_operation is not None and self.semantic_operation.stage == "accepted":
            expected = {
                "semantic_resolution_started": "semantic_resolution_accepted",
                "closure_recheck_started": "target_closure_assessed",
                "source_composition_guard_started": "source_composition_assessed",
            }[self.semantic_operation.event_type]
            if event.type != expected:
                raise ReV2EventError(f"accepted semantic artifact must be followed by {expected}")

        if event.type in _SEMANTIC_EVENTS:
            self._consume_semantic(event)
            return

        if event.type == "run_completed":
            if not self.audit_closure_roots:
                raise ReV2EventError("run completion requires an audit closure root")
            if not self.l3_source_root_states:
                raise ReV2EventError("run completion requires an L3 source root")
            if any(not cycle.complete for cycle in self.source_cycles.values()):
                raise ReV2EventError("run completion conflicts with an incomplete source cycle")

        if event.type == "run_failed" and self.plateau_targets:
            unresolved_targets = {
                target
                for target, unresolved in self.unresolved_by_target.items()
                if unresolved
            }
            if not unresolved_targets or not unresolved_targets <= self.plateau_targets:
                raise ReV2EventError(
                    "semantic plateau cannot fail a child with runnable unresolved targets"
                )
            shared = self.shared.shared
            if shared.active is not None or shared.lease_dispatch_id is not None:
                raise ReV2EventError("run_failed is invalid with active work")
            shared.terminal = True
            shared._finish(event.type)
            return

        self.shared.consume(event)
        if event.type == "dispatch_started" and self.audit_epoch_id is not None:
            self.pending_semantic_binding = True
        if event.type == "artifact_accepted" and self.semantic_operation is not None:
            if event.payload["work_item_id"] != self.semantic_operation.work_item_id:
                raise ReV2EventError("semantic artifact acceptance does not match active operation")
            self.semantic_operation.stage = "accepted"

    def semantic_state(self, *, prerequisites_complete: bool) -> SemanticStateV1:
        """Derive routing state from replay plus authenticated prerequisite closure."""
        shared = self.shared.shared
        if shared.paused:
            return "paused_resource"
        if shared.terminal:
            if shared.last_type == "run_failed":
                return "blocked_plateau" if self.plateau_targets else "blocked_incomplete"
            if "next_epoch_required" in self.l3_source_root_states.values():
                return "next_epoch_required"
            return "complete"
        unresolved_targets = {
            target for target, unresolved in self.unresolved_by_target.items() if unresolved
        }
        if unresolved_targets and unresolved_targets <= self.plateau_targets:
            return "blocked_plateau"
        if not prerequisites_complete:
            return "running_prerequisites"
        if self.audit_epoch_id is None:
            return "running_audit"
        operation = self.semantic_operation
        if operation is not None:
            if operation.event_type == "semantic_resolution_started":
                return "running_resolution"
            if operation.event_type == "closure_recheck_started":
                return "running_closure_recheck"
            return "running_source_guard"
        incomplete = [cycle for cycle in self.source_cycles.values() if not cycle.complete]
        if incomplete:
            cycle = incomplete[-1]
            if cycle.guard_passed is None:
                if cycle.target_assessments:
                    return "running_source_guard"
                return "running_closure_recheck"
            return "running_closure_recheck"
        if self.rounds_by_target:
            return "running_resolution"
        return "epoch_frozen"

    def _consume_semantic(self, event: EventRecord) -> None:
        event_type = event.type
        payload = event.payload
        if self.shared.shared.seen == 0:
            raise ReV2EventError("run_created must be the first event")
        if event_type == "audit_candidate_accepted":
            self._accept_audit_candidate(payload)
        elif event_type == "audit_epoch_frozen":
            self._freeze_epoch(payload)
        elif event_type in _SEMANTIC_START_EVENTS:
            self._start_semantic(event_type, payload)
        elif event_type == "semantic_resolution_accepted":
            self._accept_resolution(payload)
        elif event_type == "target_closure_assessed":
            self._accept_target_assessment(payload)
        elif event_type == "source_composition_assessed":
            self._accept_source_assessment(payload)
        elif event_type == "finding_closure_recorded":
            self._record_closure(payload)
        elif event_type == "semantic_progress_recorded":
            self._record_progress(payload)
        elif event_type == "semantic_plateau_reached":
            self._record_plateau(payload)
        elif event_type == "audit_closure_root_accepted":
            self._accept_audit_root(payload)
        elif event_type == "l3_source_root_accepted":
            self._accept_source_root(payload)
        elif event_type == "semantic_budget_authorized":
            if not self.shared.shared.paused:
                raise ReV2EventError("semantic_budget_authorized requires a paused run")
            # Preserve the shared resume gate without changing the run-wide ceiling.
            self.shared.shared.last_type = "budget_authorized"

    def _accept_audit_candidate(self, payload: Mapping[str, object]) -> None:
        if self.audit_epoch_id is not None:
            raise ReV2EventError("audit candidate cannot be accepted after epoch freeze")
        target = str(payload["audit_target_id"])
        authority = str(payload["audit_candidate_authority_id"])
        if target in self.audit_candidates or authority in self.audit_candidates.values():
            raise ReV2EventError("audit candidate target and authority must be unique")
        self.audit_candidates[target] = authority

    def _freeze_epoch(self, payload: Mapping[str, object]) -> None:
        if self.audit_epoch_id is not None:
            raise ReV2EventError("audit epoch may freeze only once")
        targets = tuple(payload["audit_target_ids"])
        if not targets or set(targets) != set(self.audit_candidates):
            raise ReV2EventError("audit epoch must contain exactly the accepted audit targets")
        self.audit_epoch_id = str(payload["audit_epoch_id"])
        self.audit_target_ids = targets

    def _start_semantic(self, event_type: str, payload: Mapping[str, object]) -> None:
        if self.audit_epoch_id is None:
            raise ReV2EventError("semantic operation requires a frozen audit epoch")
        if not self.pending_semantic_binding:
            raise ReV2EventError("semantic operation must bind the active shared dispatch")
        active = self.shared.shared.active
        if active is None or active.stage != "started":
            raise ReV2EventError("semantic operation requires active started provider work")
        if (
            payload["dispatch_id"] != active.dispatch_id
            or payload["work_item_id"] != active.work_item_id
        ):
            raise ReV2EventError("semantic operation does not match active shared dispatch")
        cycle_id = str(payload["source_cycle_id"])
        source_id = str(payload["source_id"])
        round_index = int(payload["semantic_round"])
        target = (
            str(payload["audit_target_id"])
            if "audit_target_id" in payload
            else None
        )
        cycle = self.source_cycles.get(cycle_id)
        if cycle is None:
            cycle = _SourceCycle(cycle_id, source_id, round_index)
            self.source_cycles[cycle_id] = cycle
        elif (
            cycle.source_id != source_id
            or cycle.semantic_round != round_index
            or cycle.complete
        ):
            raise ReV2EventError("source cycle identity is inconsistent or already complete")

        if event_type == "semantic_resolution_started":
            assert target is not None
            if target not in self.audit_target_ids:
                raise ReV2EventError("resolution target is outside the frozen audit epoch")
            if (
                target in self.plateau_targets
                or self.no_reduction_rounds_by_target.get(target, 0) >= 2
            ):
                raise ReV2EventError(
                    "semantic resolution cannot reopen a target at plateau"
                )
            if self.rounds_by_target.get(target, 0) >= 3:
                raise ReV2EventError(
                    "semantic resolution cannot exceed three semantic rounds"
                )
            expected = self.rounds_by_target.get(target, 0) + 1
            if round_index != expected:
                raise ReV2EventError("semantic round must be consecutive per audit target")
            if target in cycle.resolution_targets:
                raise ReV2EventError("audit target resolution already started in this cycle")
            cycle.resolution_targets.add(target)
        elif event_type == "closure_recheck_started":
            assert target is not None
            if target not in cycle.accepted_resolution_targets:
                raise ReV2EventError("closure recheck requires an accepted resolution first")
            if target in cycle.target_assessments:
                raise ReV2EventError("audit target was already rechecked in this cycle")
        else:
            participants = tuple(payload["participating_target_ids"])
            if set(participants) != set(cycle.target_assessments):
                raise ReV2EventError(
                    "source guard requires every participating target assessment first"
                )
            if cycle.participating_targets:
                raise ReV2EventError("source guard already started for this cycle")
            cycle.participating_targets = participants

        self.semantic_operation = _SemanticOperation(
            event_type=event_type,
            dispatch_id=str(payload["dispatch_id"]),
            work_item_id=str(payload["work_item_id"]),
            source_cycle_id=cycle_id,
            source_id=source_id,
            semantic_round=round_index,
            audit_target_id=target,
        )
        self.pending_semantic_binding = False

    def _matching_operation(
        self, expected_type: str, payload: Mapping[str, object]
    ) -> tuple[_SemanticOperation, _SourceCycle]:
        operation = self.semantic_operation
        if operation is None or operation.event_type != expected_type or operation.stage != "accepted":
            raise ReV2EventError(f"event requires accepted {expected_type} artifact")
        fields = (
            ("work_item_id", operation.work_item_id),
            ("source_cycle_id", operation.source_cycle_id),
            ("source_id", operation.source_id),
            ("semantic_round", operation.semantic_round),
        )
        if any(payload[name] != expected for name, expected in fields):
            raise ReV2EventError("semantic result does not match its started operation")
        if operation.audit_target_id is not None and (
            payload.get("audit_target_id") != operation.audit_target_id
        ):
            raise ReV2EventError("semantic result does not match its audit target")
        return operation, self.source_cycles[operation.source_cycle_id]

    def _accept_resolution(self, payload: Mapping[str, object]) -> None:
        operation, cycle = self._matching_operation("semantic_resolution_started", payload)
        assert operation.audit_target_id is not None
        cycle.accepted_resolution_targets.add(operation.audit_target_id)
        self.semantic_operation = None

    def _accept_target_assessment(self, payload: Mapping[str, object]) -> None:
        operation, cycle = self._matching_operation("closure_recheck_started", payload)
        assert operation.audit_target_id is not None
        cycle.target_assessments[operation.audit_target_id] = str(
            payload["target_closure_assessment_id"]
        )
        self.semantic_operation = None

    def _accept_source_assessment(self, payload: Mapping[str, object]) -> None:
        _operation, cycle = self._matching_operation(
            "source_composition_guard_started", payload
        )
        assessment = str(payload["source_composition_assessment_id"])
        if any(
            other.source_assessment_id == assessment
            for other in self.source_cycles.values()
            if other is not cycle
        ):
            raise ReV2EventError("source composition assessment must be unique")
        cycle.source_assessment_id = assessment
        cycle.guard_passed = bool(payload["passed"])
        self.semantic_operation = None

    def _cycle_for_payload(self, payload: Mapping[str, object]) -> _SourceCycle:
        cycle = self.source_cycles.get(str(payload["source_cycle_id"]))
        if cycle is None:
            raise ReV2EventError("semantic event refers to an unknown source cycle")
        if int(payload["semantic_round"]) != cycle.semantic_round:
            raise ReV2EventError("semantic event round does not match source cycle")
        return cycle

    def _record_closure(self, payload: Mapping[str, object]) -> None:
        cycle = self._cycle_for_payload(payload)
        if cycle.guard_passed is not True:
            raise ReV2EventError("closure receipt requires a passing source composition guard")
        if payload["source_composition_assessment_id"] != cycle.source_assessment_id:
            raise ReV2EventError("closure receipt does not match source composition assessment")
        target = str(payload["audit_target_id"])
        if target not in cycle.participating_targets:
            raise ReV2EventError("closure receipt target did not participate in the source cycle")
        finding = str(payload["finding_key_id"])
        findings = cycle.closure_verdicts_by_target.setdefault(target, {})
        if finding in findings:
            raise ReV2EventError("finding closure may be recorded only once per source cycle")
        findings[finding] = str(payload["verdict"])

    def _record_progress(self, payload: Mapping[str, object]) -> None:
        cycle = self._cycle_for_payload(payload)
        if cycle.guard_passed is None:
            raise ReV2EventError("semantic progress requires a source composition assessment")
        target = str(payload["audit_target_id"])
        if target not in cycle.participating_targets or target in cycle.progress_targets:
            raise ReV2EventError("semantic progress must occur once per participating target")
        expected_round = self.rounds_by_target.get(target, 0) + 1
        if cycle.semantic_round != expected_round:
            raise ReV2EventError("semantic progress round must be consecutive per target")
        before = frozenset(payload["unresolved_before_ids"])
        after = frozenset(payload["unresolved_after_ids"])
        previous = self.unresolved_by_target.get(target)
        if previous is not None and before != previous:
            raise ReV2EventError("unresolved-before IDs do not match replayed target state")
        if not after <= before:
            raise ReV2EventError("semantic progress cannot add unresolved finding IDs")
        if cycle.guard_passed:
            receipts = cycle.closure_verdicts_by_target.get(target, {})
            if set(receipts) != set(before):
                raise ReV2EventError(
                    "semantic progress must follow closure receipts for every input finding"
                )
            expected_after = {
                finding for finding, verdict in receipts.items() if verdict == "open"
            }
            if expected_after != set(after):
                raise ReV2EventError(
                    "semantic progress unresolved IDs must match closure verdicts"
                )
        elif after != before:
            raise ReV2EventError("failed source guard cannot reduce unresolved findings")
        self.rounds_by_target[target] = expected_round
        if after < before:
            self.no_reduction_rounds_by_target[target] = 0
        else:
            self.no_reduction_rounds_by_target[target] = (
                self.no_reduction_rounds_by_target.get(target, 0) + 1
            )
        self.unresolved_by_target[target] = after
        cycle.progress_targets.add(target)

    def _record_plateau(self, payload: Mapping[str, object]) -> None:
        target = str(payload["audit_target_id"])
        if self.no_reduction_rounds_by_target.get(target, 0) < 2:
            raise ReV2EventError("semantic plateau requires two no-reduction rounds")
        if payload["semantic_round"] != self.rounds_by_target.get(target):
            raise ReV2EventError("semantic plateau round does not match target progress")
        if frozenset(payload["unresolved_finding_ids"]) != self.unresolved_by_target.get(target):
            raise ReV2EventError("semantic plateau unresolved IDs do not match replay")
        self.plateau_targets.add(target)

    def _accept_audit_root(self, payload: Mapping[str, object]) -> None:
        if payload["audit_epoch_id"] != self.audit_epoch_id:
            raise ReV2EventError("audit closure root does not match frozen epoch")
        if self.semantic_operation is not None or any(
            not cycle.complete for cycle in self.source_cycles.values()
        ):
            raise ReV2EventError("audit closure root requires completed semantic cycles")
        root = str(payload["audit_closure_root_id"])
        if root in self.audit_closure_roots:
            raise ReV2EventError("audit closure root must be unique")
        self.audit_closure_roots.add(root)

    def _accept_source_root(self, payload: Mapping[str, object]) -> None:
        if not self.audit_closure_roots:
            raise ReV2EventError("L3 source root requires an audit closure root")
        source = str(payload["source_id"])
        if source in self.l3_source_root_states:
            raise ReV2EventError("L3 source root may be accepted once per source")
        self.l3_source_root_states[source] = str(payload["scope_state"])


class _Protocol25Events(EventProtocol):
    PROTOCOL_VERSION: ClassVar[str] = "2.5"

    def canonical_payload(
        self, event_type: str, payload: Mapping[str, object]
    ) -> Mapping[str, object]:
        if event_type not in _SEMANTIC_EVENTS:
            return PROTOCOL_24_EVENTS.canonical_payload(event_type, payload)
        canonical = _canonical_payload(_thaw_json(payload))
        _validate_semantic_payload(event_type, canonical)
        return canonical

    def new_state(self) -> EventReplayState:
        return Protocol25ReplayState()


PROTOCOL_25_EVENTS: EventProtocol = _Protocol25Events()


__all__ = (
    "PROTOCOL_25_EVENTS",
    "Protocol25ReplayState",
    "SemanticStateV1",
)
