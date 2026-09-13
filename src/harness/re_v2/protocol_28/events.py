"""Closed, content-free protocol-2.8 event vocabulary and projection replay."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Literal, Mapping

from harness.re_v2.events import (
    EventProtocol,
    EventRecord,
    EventReplayState,
    ReV2EventError,
    _canonical_payload,
    _thaw_json,
)


LifecycleStateV1 = Literal[
    "planned",
    "active",
    "resource_blocked",
    "execution_blocked",
    "evidence_complete",
    "closure_integrity_blocked",
    "complete",
    "running", "needs-attention", "complete-with-limitations",
]
Validator = Callable[[object, str], None]


def _digest(value: object, field_name: str) -> None:
    if not isinstance(value, str) or not value.startswith("sha256:"):
        raise ReV2EventError(f"{field_name} must be a lowercase sha256 digest")
    suffix = value.removeprefix("sha256:")
    if len(suffix) != 64 or any(item not in "0123456789abcdef" for item in suffix):
        raise ReV2EventError(f"{field_name} must be a lowercase sha256 digest")


def _safe_id(value: object, field_name: str) -> None:
    if (
        not isinstance(value, str)
        or not value
        or any(not (item.isalnum() or item in "._:-") for item in value)
    ):
        raise ReV2EventError(f"{field_name} must be a nonempty safe ID")


def _positive(value: object, field_name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ReV2EventError(f"{field_name} must be a positive integer")


def _nonnegative(value: object, field_name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ReV2EventError(f"{field_name} must be a nonnegative integer")


def _nullable_nonnegative(value: object, field_name: str) -> None:
    if value is not None:
        _nonnegative(value, field_name)


def _choice(*values: str) -> Validator:
    allowed = frozenset(values)

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


_ROLE = _choice("producer", "verifier")
_ROOT_KIND = _choice("target", "source", "run")
_BLOCKER_KIND = _choice("resource", "execution", "closure_integrity")

_PAYLOAD_SCHEMAS: dict[str, dict[str, Validator]] = {
    'knowledge_resource_settled': {'dispatch_id': _safe_id, 'resource_prefix_id': _digest,
        'charged_tokens': _nonnegative, 'charged_active_ms': _nonnegative},
    'knowledge_work_realized': {'work_item_id': _digest},
    'knowledge_artifact_recorded': {'dispatch_id': _safe_id, 'role': _ROLE, 'work_item_id': _digest, 'artifact_id': _digest},
    'knowledge_feedback_recorded': {'work_item_id': _digest, 'feedback_id': _digest, 'fingerprint_id': _digest},
    'knowledge_root_recorded': {'root_id': _digest, 'root_kind': _ROOT_KIND, 'revision_id': _digest,
        'required_accepted_slice_ids': _digest_array, 'required_root_ids': _digest_array, 'debt_ids': _digest_array},
    'knowledge_run_completed': {'run_root_id': _digest, 'revision_id': _digest, 'debt_ids': _digest_array},
    'knowledge_workflow_requested': {'intent_id': _digest},
    'knowledge_revision_requested': {'cause_id': _digest, 'intent_id': _digest},
    'knowledge_workflow_activated': {
        'authorization_id': _digest, 'pointer_id': _digest, 'revision_id': _digest,
        'planned_entry_ids': _digest_array, 'invalidated_result_ids': _digest_array,
    },
    'knowledge_revision_activated': {
        'authorization_id': _digest, 'pointer_id': _digest, 'revision_id': _digest,
        'planned_entry_ids': _digest_array, 'invalidated_result_ids': _digest_array,
    },
    "l4_run_created": {"run_manifest_id": _digest},
    "l4_closure_inputs_staged": {
        "closure_parent_bundle_id": _digest,
        "closure_run_manifest_id": _digest,
        "l4_run_root_id": _digest,
    },
    "l4_inputs_staged": {
        "coverage_proof_id": _digest,
        "exhaustive_plan_id": _digest,
        "parent_authority_bundle_id": _digest,
        "snapshot_evidence_catalog_id": _digest,
        "target_projection_catalog_id": _digest,
    },
    "l4_activated": {
        "activation_id": _digest,
        "planned_entry_ids": _digest_array,
    },
    "checkpoint_discovered": {
        "checkpoint_manifest_id": _digest,
        "output_artifact_key_id": _digest,
    },
    "checkpoint_rejected": {
        "checkpoint_manifest_id": _digest,
        "output_artifact_key_id": _digest,
        "reason_code": _safe_id,
    },
    "checkpoint_quarantined": {
        "checkpoint_manifest_id": _digest,
        "output_artifact_key_id": _digest,
        "reason_code": _safe_id,
    },
    "checkpoint_staged": {
        "checkpoint_manifest_id": _digest,
        "copied_object_count": _nonnegative,
        "output_artifact_key_id": _digest,
    },
    "checkpoint_adopted": {
        "accepted_slice_id": _digest,
        "checkpoint_manifest_id": _digest,
        "output_artifact_key_id": _digest,
    },
    "slice_realized": {
        "output_artifact_key_id": _digest,
        "plan_entry_id": _digest,
        "slice_spec_id": _digest,
    },
    "dispatch_reserved": {
        "dispatch_id": _safe_id,
        "output_artifact_key_id": _digest,
        "reservation_id": _digest,
        "role": _ROLE,
    },
    "dispatch_leased": {
        "dispatch_id": _safe_id,
        "lease_id": _digest,
        "owner_id": _safe_id,
        "role": _ROLE,
    },
    "provider_started": {
        "dispatch_id": _safe_id,
        "role": _ROLE,
    },
    "provider_capture_recorded": {
        "dispatch_id": _safe_id,
        "execution_capture_id": _digest,
        "raw_result_id": _digest,
        "role": _ROLE,
    },
    "provider_abandoned": {
        "dispatch_id": _safe_id,
        "reason_code": _safe_id,
        "role": _ROLE,
    },
    "candidate_recorded": {
        "candidate_id": _digest,
        "dispatch_id": _safe_id,
        "output_artifact_key_id": _digest,
        "slice_spec_id": _digest,
    },
    "candidate_rejected": {
        "dispatch_id": _safe_id,
        "output_artifact_key_id": _digest,
        "reason_code": _safe_id,
    },
    "verification_recorded": {
        "candidate_id": _digest,
        "dispatch_id": _safe_id,
        "output_artifact_key_id": _digest,
        "verdict": _choice("PASS", "REPAIR"),
        "verification_id": _digest,
    },
    "verification_rejected": {
        "dispatch_id": _safe_id,
        "output_artifact_key_id": _digest,
        "reason_code": _safe_id,
    },
    "certification_recorded": {
        "certification_receipt_id": _digest,
        "output_artifact_key_id": _digest,
        "slice_spec_id": _digest,
    },
    "acceptance_recorded": {
        "acceptance_receipt_id": _digest,
        "certification_receipt_id": _digest,
        "output_artifact_key_id": _digest,
        "slice_spec_id": _digest,
    },
    "accepted_slice_recorded": {
        "acceptance_receipt_id": _digest,
        "accepted_slice_id": _digest,
        "output_artifact_key_id": _digest,
        "slice_spec_id": _digest,
    },
    "repair_packet_recorded": {
        "diagnostic_set_id": _digest,
        "output_artifact_key_id": _digest,
        "repair_packet_id": _digest,
    },
    "plateau_reached": {
        "diagnostic_set_id": _digest,
        "output_artifact_key_id": _digest,
    },
    "slice_failed": {
        "output_artifact_key_id": _digest,
        "reason_code": _safe_id,
    },
    "root_recorded": {
        "required_accepted_slice_ids": _digest_array,
        "required_root_ids": _digest_array,
        "root_id": _digest,
        "root_kind": _ROOT_KIND,
    },
    "resource_authorized": {
        "authorized_by": _safe_id,
        "dimension": _choice("tokens", "active_ms"),
        "new_value": _positive,
        "old_value": _nullable_nonnegative,
    },
    "run_blocked": {
        "blocker_kind": _BLOCKER_KIND,
        "reason_code": _safe_id,
    },
    "materialization_completed": {"root_id": _digest},
    "closure_successor_linked": {
        "closure_run_manifest_id": _digest,
        "closure_run_id": _safe_id,
        "l4_run_root_id": _digest,
    },
    "closure_receipt_recorded": {
        "closure_receipt_id": _digest,
        "finding_id": _digest,
    },
    "closure_root_recorded": {
        "closure_root_id": _digest,
        "closure_run_manifest_id": _digest,
        "l4_run_root_id": _digest,
    },
    "run_completed": {
        "completion_kind": _choice("evidence_only", "semantic_closure"),
        "run_root_id": _digest,
    },
}


def _validate_payload(event_type: str, payload: Mapping[str, object]) -> None:
    schema = _PAYLOAD_SCHEMAS.get(event_type)
    if schema is None:
        raise ReV2EventError(f"unknown protocol-2.8 event type: {event_type!r}")
    unknown = set(payload) - set(schema)
    missing = set(schema) - set(payload)
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
class _DispatchStateV1:
    dispatch_id: str
    role: str
    output_artifact_key_id: str
    stage: str
    owner_id: str | None = None
    capture_id: str | None = None


@dataclass(slots=True)
class Protocol28ReplayState(EventReplayState):
    """Replay ordering and derive the rebuildable protocol-2.8 projection."""

    run_manifest_id: str | None = None
    inputs_staged: bool = False
    activated: bool = False
    planned_entry_ids: tuple[str, ...] = ()
    realized_by_entry: dict[str, tuple[str, str]] = field(default_factory=dict)
    certifications: dict[str, tuple[str, str]] = field(default_factory=dict)
    acceptances: dict[str, tuple[str, str]] = field(default_factory=dict)
    accepted_slices: dict[str, str] = field(default_factory=dict)
    failed_output_ids: set[str] = field(default_factory=set)
    dispatches: dict[str, _DispatchStateV1] = field(default_factory=dict)
    target_root_ids: set[str] = field(default_factory=set)
    source_root_ids: set[str] = field(default_factory=set)
    root_requirements: dict[str, tuple[str, tuple[str, ...], tuple[str, ...]]] = field(
        default_factory=dict
    )
    run_root_id: str | None = None
    materialized_root_ids: set[str] = field(default_factory=set)
    linked_closure_manifest_id: str | None = None
    closure_root_id: str | None = None
    blocker_kind: str | None = None
    terminal: bool = False
    knowledge_activation_intent_id: str | None = None
    knowledge_authorization_id: str | None = None
    knowledge_pointer_id: str | None = None
    knowledge_revision_id: str | None = None
    knowledge_revision_intent_id: str | None = None
    knowledge_work_ids: set[str] = field(default_factory=set)
    knowledge_debt_ids: tuple[str, ...] = ()

    @property
    def lifecycle_state(self) -> LifecycleStateV1:
        if self.knowledge_authorization_id is not None:
            if self.knowledge_revision_intent_id is not None:
                return 'needs-attention'
            if self.terminal:
                return 'complete-with-limitations' if self.knowledge_debt_ids else 'complete'
            return 'needs-attention' if self.blocker_kind else 'running'
        if self.terminal:
            return "complete"
        if self.blocker_kind == "closure_integrity":
            return "closure_integrity_blocked"
        if self.blocker_kind == "resource":
            return "resource_blocked"
        if self.blocker_kind == "execution":
            return "execution_blocked"
        if self.run_root_id is not None:
            return "evidence_complete"
        if self.activated:
            return "active"
        return "planned"

    def consume(self, event: EventRecord) -> None:
        if self.knowledge_revision_intent_id is not None and event.type != 'knowledge_revision_activated':
            raise ReV2EventError('knowledge revision is incomplete')
        if (self.knowledge_activation_intent_id is not None and self.knowledge_authorization_id is None
                and event.type != 'knowledge_workflow_activated'):
            raise ReV2EventError('knowledge activation is incomplete')
        if self.terminal and not (self.knowledge_authorization_id is not None and
                event.type in {'knowledge_revision_requested', 'knowledge_revision_activated'}):
            raise ReV2EventError("event appears after terminal protocol-2.8 state")
        payload = event.payload
        handler = getattr(self, f"_on_{event.type}", None)
        if handler is None:
            raise ReV2EventError(f"unknown protocol-2.8 event type: {event.type!r}")
        handler(payload)

    def _on_l4_run_created(self, payload: Mapping[str, object]) -> None:
        if self.run_manifest_id is not None:
            raise ReV2EventError("protocol-2.8 run was created twice")
        self.run_manifest_id = str(payload["run_manifest_id"])

    def _on_knowledge_workflow_requested(self, payload):
        self._require_active('knowledge workflow intent')
        if self.knowledge_authorization_id is not None or self.dispatches or self.accepted_slices or self.run_root_id:
            raise ReV2EventError('knowledge workflow requires an explicitly new execution path')
        self.knowledge_activation_intent_id = str(payload['intent_id'])

    def _on_knowledge_workflow_activated(self, payload):
        self._require_active('knowledge workflow activation')
        if (self.knowledge_activation_intent_id is None or self.knowledge_authorization_id is not None
                or self.dispatches or self.accepted_slices or self.run_root_id):
            raise ReV2EventError('knowledge workflow requires an explicitly new execution path')
        if tuple(payload['planned_entry_ids']) != self.planned_entry_ids or payload['invalidated_result_ids']:
            raise ReV2EventError('knowledge workflow plan mismatch')
        self.knowledge_authorization_id = str(payload['authorization_id'])
        self.knowledge_pointer_id = str(payload['pointer_id'])
        self.knowledge_revision_id = str(payload['revision_id'])

    def _on_knowledge_work_realized(self, payload):
        self._require_active('knowledge reconciliation')
        if self.knowledge_authorization_id is None:
            raise ReV2EventError('knowledge work requires explicit authorization')
        self.knowledge_work_ids.add(str(payload['work_item_id']))

    def _on_knowledge_resource_settled(self, payload):
        if self.knowledge_authorization_id is None or payload['dispatch_id'] not in self.dispatches:
            raise ReV2EventError('knowledge settlement requires a reserved dispatch')

    def _on_knowledge_artifact_recorded(self, payload):
        dispatch = self._dispatch(payload, 'captured')
        if payload['work_item_id'] not in self.knowledge_work_ids or dispatch.output_artifact_key_id != payload['work_item_id']:
            raise ReV2EventError('knowledge artifact does not match realized work')
        dispatch.stage = 'knowledge_artifact'

    def _on_knowledge_feedback_recorded(self, payload):
        if payload['work_item_id'] not in self.knowledge_work_ids:
            raise ReV2EventError('knowledge feedback requires realized work')

    def _on_knowledge_root_recorded(self, payload):
        if self.knowledge_authorization_id is None or payload['revision_id'] != self.knowledge_revision_id:
            raise ReV2EventError('knowledge root requires active reviewed authority')
        self._on_root_recorded({key: payload[key] for key in
            ('root_id', 'root_kind', 'required_accepted_slice_ids', 'required_root_ids')})
        if payload['root_kind'] == 'run':
            self.knowledge_debt_ids = tuple(payload['debt_ids'])

    def _on_knowledge_run_completed(self, payload):
        if (self.knowledge_authorization_id is None or payload['revision_id'] != self.knowledge_revision_id
                or self.run_root_id != payload['run_root_id'] or tuple(payload['debt_ids']) != self.knowledge_debt_ids):
            raise ReV2EventError('knowledge completion requires exact reviewed root')
        self.terminal = True
        self.blocker_kind = None

    def _on_knowledge_revision_requested(self, payload):
        self._require_active('knowledge revision intent')
        if self.knowledge_authorization_id is None:
            raise ReV2EventError('knowledge revision requires explicit workflow authority')
        self.knowledge_revision_intent_id = str(payload['intent_id'])

    def _on_knowledge_revision_activated(self, payload):
        self._require_active('knowledge revision activation')
        if self.knowledge_authorization_id != payload['authorization_id'] or any(
                d.stage in {'reserved', 'leased', 'started', 'captured'} for d in self.dispatches.values()):
            raise ReV2EventError('knowledge revision requires same authority and settled dispatches')
        invalidated = set(payload['invalidated_result_ids'])
        outputs = {k for k, v in self.accepted_slices.items() if v in invalidated}
        for mapping in (self.certifications, self.acceptances, self.accepted_slices):
            for key in outputs:
                mapping.pop(key, None)
        self.planned_entry_ids = tuple(payload['planned_entry_ids'])
        self.realized_by_entry = {k: v for k, v in self.realized_by_entry.items()
            if k in self.planned_entry_ids and v[1] not in outputs}
        self.failed_output_ids.clear()
        self.target_root_ids -= invalidated
        self.source_root_ids -= invalidated
        self.root_requirements = {k: v for k, v in self.root_requirements.items() if k not in invalidated}
        if self.run_root_id in invalidated:
            self.run_root_id = None
        self.blocker_kind = None
        self.terminal = False
        self.knowledge_work_ids.clear()
        self.knowledge_debt_ids = ()
        self.knowledge_pointer_id = str(payload['pointer_id'])
        self.knowledge_revision_intent_id = None
        self.knowledge_revision_id = str(payload['revision_id'])

    def _on_l4_inputs_staged(self, payload: Mapping[str, object]) -> None:
        self._require_created("input staging")
        if self.inputs_staged or self.activated:
            raise ReV2EventError("protocol-2.8 inputs were staged out of order")
        self.inputs_staged = True

    def _on_l4_closure_inputs_staged(self, payload: Mapping[str, object]) -> None:
        """Activate an immutable provider-free closure successor."""
        self._require_created("closure input staging")
        if self.inputs_staged or self.activated or self.run_root_id is not None:
            raise ReV2EventError("protocol-2.8 closure inputs were staged twice")
        if payload["closure_run_manifest_id"] != self.run_manifest_id:
            raise ReV2EventError("closure input staging does not match its manifest")
        self.inputs_staged = True
        self.activated = True
        self.run_root_id = str(payload["l4_run_root_id"])
        self.linked_closure_manifest_id = str(payload["closure_run_manifest_id"])

    def _on_l4_activated(self, payload: Mapping[str, object]) -> None:
        if not self.inputs_staged or self.activated:
            raise ReV2EventError("protocol-2.8 activation is out of order")
        self.planned_entry_ids = tuple(payload["planned_entry_ids"])
        self.activated = True

    def _on_slice_realized(self, payload: Mapping[str, object]) -> None:
        self._require_active("slice realization")
        entry_id = str(payload["plan_entry_id"])
        if entry_id not in self.planned_entry_ids:
            raise ReV2EventError("realized slice is outside the frozen plan")
        value = (
            str(payload["slice_spec_id"]),
            str(payload["output_artifact_key_id"]),
        )
        existing = self.realized_by_entry.get(entry_id)
        if existing is not None and existing != value:
            raise ReV2EventError("plan entry has conflicting slice realization")
        if any(
            item[1] == value[1] and key != entry_id
            for key, item in self.realized_by_entry.items()
        ):
            raise ReV2EventError("slice output key is not unique")
        self.realized_by_entry[entry_id] = value

    def _on_certification_recorded(self, payload: Mapping[str, object]) -> None:
        output_id = self._require_realized_output(payload, "certification")
        value = (
            str(payload["slice_spec_id"]),
            str(payload["certification_receipt_id"]),
        )
        self._set_once(self.certifications, output_id, value, "certification")

    def _on_acceptance_recorded(self, payload: Mapping[str, object]) -> None:
        output_id = self._require_realized_output(payload, "acceptance")
        certification = self.certifications.get(output_id)
        if certification != (
            str(payload["slice_spec_id"]),
            str(payload["certification_receipt_id"]),
        ):
            raise ReV2EventError("acceptance has no matching certification")
        self._set_once(
            self.acceptances,
            output_id,
            (str(payload["slice_spec_id"]), str(payload["acceptance_receipt_id"])),
            "acceptance",
        )

    def _on_accepted_slice_recorded(self, payload: Mapping[str, object]) -> None:
        output_id = self._require_realized_output(payload, "accepted slice")
        if self.acceptances.get(output_id) != (
            str(payload["slice_spec_id"]),
            str(payload["acceptance_receipt_id"]),
        ):
            raise ReV2EventError("accepted slice has no matching acceptance")
        if output_id in self.failed_output_ids:
            raise ReV2EventError("failed slice cannot become accepted")
        self._set_once(
            self.accepted_slices,
            output_id,
            str(payload["accepted_slice_id"]),
            "accepted slice",
        )

    def _on_slice_failed(self, payload: Mapping[str, object]) -> None:
        output_id = str(payload["output_artifact_key_id"])
        if output_id in self.accepted_slices:
            raise ReV2EventError("accepted slice cannot be reopened as failed")
        if output_id not in {item[1] for item in self.realized_by_entry.values()} | self.knowledge_work_ids:
            raise ReV2EventError("failed slice is outside realized work")
        self.failed_output_ids.add(output_id)

    def _on_dispatch_reserved(self, payload: Mapping[str, object]) -> None:
        self._require_active("dispatch reservation")
        dispatch_id = str(payload["dispatch_id"])
        if dispatch_id in self.dispatches:
            raise ReV2EventError("dispatch ID was reused")
        output_id = str(payload["output_artifact_key_id"])
        if output_id in self.accepted_slices or output_id in self.failed_output_ids:
            raise ReV2EventError("terminal slice cannot reserve another dispatch")
        self.dispatches[dispatch_id] = _DispatchStateV1(
            dispatch_id, str(payload["role"]), output_id, "reserved"
        )

    def _on_dispatch_leased(self, payload: Mapping[str, object]) -> None:
        dispatch = self._dispatch(payload, "reserved")
        dispatch.stage = "leased"
        dispatch.owner_id = str(payload["owner_id"])

    def _on_provider_started(self, payload: Mapping[str, object]) -> None:
        dispatch = self._dispatch(payload, "leased")
        dispatch.stage = "started"

    def _on_provider_capture_recorded(self, payload: Mapping[str, object]) -> None:
        dispatch = self._dispatch(payload, "started")
        dispatch.stage = "captured"
        dispatch.capture_id = str(payload["execution_capture_id"])

    def _on_provider_abandoned(self, payload: Mapping[str, object]) -> None:
        dispatch = self._dispatch(payload, "reserved", "leased", "started")
        dispatch.stage = "abandoned"

    def _on_candidate_recorded(self, payload: Mapping[str, object]) -> None:
        dispatch = self._dispatch(payload, "captured")
        if (
            dispatch.role != "producer"
            or dispatch.output_artifact_key_id != payload["output_artifact_key_id"]
        ):
            raise ReV2EventError("candidate does not match producer dispatch")
        self._require_realized_output(payload, "candidate")
        dispatch.stage = "candidate"

    def _on_candidate_rejected(self, payload: Mapping[str, object]) -> None:
        dispatch = self.dispatches.get(str(payload["dispatch_id"]))
        if (
            dispatch is None
            or dispatch.stage != "captured"
            or dispatch.role != "producer"
            or dispatch.output_artifact_key_id != payload["output_artifact_key_id"]
        ):
            raise ReV2EventError("candidate rejection does not match producer dispatch")
        dispatch.stage = "rejected"

    def _on_verification_recorded(self, payload: Mapping[str, object]) -> None:
        dispatch = self._dispatch(payload, "captured")
        if (
            dispatch.role != "verifier"
            or dispatch.output_artifact_key_id != payload["output_artifact_key_id"]
        ):
            raise ReV2EventError("verification does not match verifier dispatch")
        dispatch.stage = (
            "verified_pass" if payload["verdict"] == "PASS" else "verified_repair"
        )

    def _on_verification_rejected(self, payload: Mapping[str, object]) -> None:
        dispatch = self.dispatches.get(str(payload["dispatch_id"]))
        if (
            dispatch is None
            or dispatch.stage != "captured"
            or dispatch.role != "verifier"
            or dispatch.output_artifact_key_id != payload["output_artifact_key_id"]
        ):
            raise ReV2EventError(
                "verification rejection does not match verifier dispatch"
            )
        dispatch.stage = "rejected"

    def _on_repair_packet_recorded(self, payload: Mapping[str, object]) -> None:
        self._require_realized_key(
            str(payload["output_artifact_key_id"]), "repair packet"
        )

    def _on_plateau_reached(self, payload: Mapping[str, object]) -> None:
        self._require_realized_key(str(payload["output_artifact_key_id"]), "plateau")

    def _on_root_recorded(self, payload: Mapping[str, object]) -> None:
        self._require_active("root acceptance")
        root_id = str(payload["root_id"])
        kind = str(payload["root_kind"])
        accepted = set(self.accepted_slices.values())
        required_accepted = set(payload["required_accepted_slice_ids"])
        required_roots = set(payload["required_root_ids"])
        requirements = (
            kind,
            tuple(payload["required_accepted_slice_ids"]),
            tuple(payload["required_root_ids"]),
        )
        existing = self.root_requirements.get(root_id)
        if existing is not None:
            if existing != requirements:
                raise ReV2EventError("root authority conflicts")
            return
        if not required_accepted <= accepted:
            raise ReV2EventError("root references an unaccepted slice")
        if kind == "target":
            if required_roots:
                raise ReV2EventError("target root cannot depend on another root")
            self.target_root_ids.add(root_id)
            self.root_requirements[root_id] = requirements
            return
        if kind == "source":
            if not required_roots <= self.target_root_ids:
                raise ReV2EventError("source root requires recorded target roots")
            self.source_root_ids.add(root_id)
            self.root_requirements[root_id] = requirements
            return
        if set(self.realized_by_entry) != set(self.planned_entry_ids) or len(
            accepted
        ) != len(self.planned_entry_ids):
            raise ReV2EventError("run root requires exact accepted slice closure")
        if required_accepted != accepted:
            raise ReV2EventError("run root requires exact accepted slice closure")
        if required_roots != self.target_root_ids | self.source_root_ids:
            raise ReV2EventError("run root requires exact lower-root closure")
        if self.run_root_id is not None and self.run_root_id != root_id:
            raise ReV2EventError("run root authority conflicts")
        self.run_root_id = root_id
        self.root_requirements[root_id] = requirements

    def _on_materialization_completed(self, payload: Mapping[str, object]) -> None:
        root_id = str(payload["root_id"])
        if root_id not in self.target_root_ids | self.source_root_ids | {
            self.run_root_id,
            self.closure_root_id,
        }:
            raise ReV2EventError("materialization requires a durable root")
        self.materialized_root_ids.add(root_id)

    def _on_closure_successor_linked(self, payload: Mapping[str, object]) -> None:
        if self.run_root_id != payload["l4_run_root_id"]:
            raise ReV2EventError("closure successor requires the exact L4 run root")
        manifest_id = str(payload["closure_run_manifest_id"])
        if self.linked_closure_manifest_id not in {None, manifest_id}:
            raise ReV2EventError("closure successor link conflicts")
        self.linked_closure_manifest_id = manifest_id

    def _on_closure_receipt_recorded(self, payload: Mapping[str, object]) -> None:
        if self.linked_closure_manifest_id is None:
            raise ReV2EventError("closure receipt requires a linked successor")

    def _on_closure_root_recorded(self, payload: Mapping[str, object]) -> None:
        if (
            self.linked_closure_manifest_id != payload["closure_run_manifest_id"]
            or self.run_root_id != payload["l4_run_root_id"]
        ):
            raise ReV2EventError("closure root does not match linked authority")
        root_id = str(payload["closure_root_id"])
        if self.closure_root_id not in {None, root_id}:
            raise ReV2EventError("closure root authority conflicts")
        self.closure_root_id = root_id

    def _on_resource_authorized(self, payload: Mapping[str, object]) -> None:
        self._require_created("resource authorization")
        if self.blocker_kind == "resource":
            self.blocker_kind = None

    def _on_run_blocked(self, payload: Mapping[str, object]) -> None:
        self._require_created("run blocker")
        self.blocker_kind = str(payload["blocker_kind"])

    def _on_run_completed(self, payload: Mapping[str, object]) -> None:
        if self.run_root_id != payload["run_root_id"]:
            raise ReV2EventError("completion requires the exact run root")
        completion_kind = payload["completion_kind"]
        required_materialization = (
            self.closure_root_id
            if completion_kind == "semantic_closure"
            else self.run_root_id
        )
        if required_materialization not in self.materialized_root_ids:
            raise ReV2EventError("completion requires terminal-root materialization")
        if completion_kind == "semantic_closure" and self.closure_root_id is None:
            raise ReV2EventError("semantic completion requires a closure root")
        if (
            completion_kind == "evidence_only"
            and self.linked_closure_manifest_id is not None
        ):
            raise ReV2EventError(
                "linked closure successor cannot complete as evidence-only"
            )
        self.terminal = True
        self.blocker_kind = None

    def _on_checkpoint_discovered(self, payload: Mapping[str, object]) -> None:
        self._require_created("checkpoint discovery")

    def _on_checkpoint_rejected(self, payload: Mapping[str, object]) -> None:
        self._require_created("checkpoint rejection")

    def _on_checkpoint_quarantined(self, payload: Mapping[str, object]) -> None:
        self._require_created("checkpoint quarantine")

    def _on_checkpoint_staged(self, payload: Mapping[str, object]) -> None:
        self._require_created("checkpoint staging")

    def _on_checkpoint_adopted(self, payload: Mapping[str, object]) -> None:
        self._require_active("checkpoint adoption")

    def _require_created(self, operation: str) -> None:
        if self.run_manifest_id is None:
            raise ReV2EventError(f"{operation} requires run creation")

    def _require_active(self, operation: str) -> None:
        if not self.activated:
            raise ReV2EventError(f"{operation} requires activation")

    def _require_realized_key(self, output_id: str, operation: str) -> None:
        if output_id not in {item[1] for item in self.realized_by_entry.values()}:
            raise ReV2EventError(f"{operation} requires a realized slice")

    def _require_realized_output(
        self, payload: Mapping[str, object], operation: str
    ) -> str:
        output_id = str(payload["output_artifact_key_id"])
        expected = (str(payload["slice_spec_id"]), output_id)
        if expected not in self.realized_by_entry.values():
            raise ReV2EventError(f"{operation} does not match a realized slice")
        return output_id

    def _dispatch(
        self, payload: Mapping[str, object], *stages: str
    ) -> _DispatchStateV1:
        dispatch = self.dispatches.get(str(payload["dispatch_id"]))
        if (
            dispatch is None
            or dispatch.stage not in stages
            or ("role" in payload and dispatch.role != payload["role"])
        ):
            raise ReV2EventError("dispatch transition is out of order")
        return dispatch

    @staticmethod
    def _set_once(target: dict, key: str, value: object, label: str) -> None:  # type: ignore[type-arg]
        existing = target.get(key)
        if existing is not None and existing != value:
            raise ReV2EventError(f"conflicting {label} authority")
        target[key] = value


@dataclass(frozen=True, slots=True)
class Protocol28ProjectionV1:
    schema_version: int
    lifecycle_state: LifecycleStateV1
    run_manifest_id: str | None
    planned_slice_count: int
    realized_slice_count: int
    accepted_output_artifact_key_ids: tuple[str, ...]
    failed_output_artifact_key_ids: tuple[str, ...]
    active_dispatch_ids: tuple[str, ...]
    target_root_ids: tuple[str, ...]
    source_root_ids: tuple[str, ...]
    run_root_id: str | None
    materialized_root_ids: tuple[str, ...]
    linked_closure_manifest_id: str | None
    closure_root_id: str | None

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "lifecycle_state": self.lifecycle_state,
            "run_manifest_id": self.run_manifest_id,
            "planned_slice_count": self.planned_slice_count,
            "realized_slice_count": self.realized_slice_count,
            "accepted_output_artifact_key_ids": list(
                self.accepted_output_artifact_key_ids
            ),
            "failed_output_artifact_key_ids": list(self.failed_output_artifact_key_ids),
            "active_dispatch_ids": list(self.active_dispatch_ids),
            "target_root_ids": list(self.target_root_ids),
            "source_root_ids": list(self.source_root_ids),
            "run_root_id": self.run_root_id,
            "materialized_root_ids": list(self.materialized_root_ids),
            "linked_closure_manifest_id": self.linked_closure_manifest_id,
            "closure_root_id": self.closure_root_id,
        }


def replay_protocol_28(events: tuple[EventRecord, ...]) -> Protocol28ReplayState:
    state = Protocol28ReplayState()
    for event in events:
        state.consume(event)
    return state


def project_protocol_28(events: tuple[EventRecord, ...]) -> Protocol28ProjectionV1:
    state = replay_protocol_28(events)
    active_stages = {"reserved", "leased", "started", "captured"}
    return Protocol28ProjectionV1(
        schema_version=1,
        lifecycle_state=state.lifecycle_state,
        run_manifest_id=state.run_manifest_id,
        planned_slice_count=len(state.planned_entry_ids),
        realized_slice_count=len(state.realized_by_entry),
        accepted_output_artifact_key_ids=tuple(sorted(state.accepted_slices)),
        failed_output_artifact_key_ids=tuple(sorted(state.failed_output_ids)),
        active_dispatch_ids=tuple(
            sorted(
                dispatch_id
                for dispatch_id, dispatch in state.dispatches.items()
                if dispatch.stage in active_stages
            )
        ),
        target_root_ids=tuple(sorted(state.target_root_ids)),
        source_root_ids=tuple(sorted(state.source_root_ids)),
        run_root_id=state.run_root_id,
        materialized_root_ids=tuple(sorted(state.materialized_root_ids)),
        linked_closure_manifest_id=state.linked_closure_manifest_id,
        closure_root_id=state.closure_root_id,
    )


class _Protocol28EventProtocol(EventProtocol):
    def canonical_payload(
        self, event_type: str, payload: Mapping[str, object]
    ) -> Mapping[str, object]:
        canonical = _canonical_payload(_thaw_json(payload))
        _validate_payload(event_type, canonical)
        return canonical

    def new_state(self) -> EventReplayState:
        return Protocol28ReplayState()


PROTOCOL_28_EVENTS: EventProtocol = _Protocol28EventProtocol()


__all__ = (
    "PROTOCOL_28_EVENTS",
    "Protocol28ProjectionV1",
    "Protocol28ReplayState",
    "project_protocol_28",
    "replay_protocol_28",
)
