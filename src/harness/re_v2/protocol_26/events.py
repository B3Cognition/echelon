"""Protocol-2.6 checkpoint adoption composed over existing layer events."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, ClassVar, Mapping, cast

from harness.re_v2.events import (
    EventProtocol,
    EventRecord,
    EventReplayState,
    EventStore,
    ReV2EventError,
    _canonical_payload,
    _thaw_json,
)
from harness.re_v2.canonical import canonical_json_bytes
from harness.re_v2.protocol_22.events import PROTOCOL_22_EVENTS
from harness.re_v2.protocol_22.ledger import Protocol22Ledger
from harness.re_v2.protocol_22.schema import (
    Protocol22SchemaError,
    digest_value,
    exact_object,
    one_of,
    safe_id,
)
from harness.re_v2.protocol_24.events import PROTOCOL_24_EVENTS
from harness.re_v2.protocol_24.model import AdoptedArtifactAuthorityV1
from harness.re_v2.protocol_25.events import PROTOCOL_25_EVENTS

from .adoption import (
    CheckpointAdoptionReportV1,
    Protocol26AdoptionError,
    checkpoint_adoption_report,
)
from .inputs import ValidatedProtocol26Inputs
from .model import CHECKPOINT_SELECTION_REASONS, TargetLayerV1


_CHECKPOINT_EVENT = "checkpoint_artifact_adopted"
_CHECKPOINT_FIELDS = frozenset(
    {
        "checkpoint_selection_bundle_id",
        "checkpoint_manifest_id",
        "adopted_artifact_authority",
        "origin_run_id",
        "work_item_id",
        "selection_reason",
    }
)
_WORK_DISPATCH_EVENTS = frozenset(
    {"dispatch_leased", "dispatch_started", "dispatch_lease_retired"}
)


@dataclass(frozen=True, slots=True)
class _CheckpointAdoptionPayload:
    selection_bundle_id: str
    checkpoint_manifest_id: str
    authority: AdoptedArtifactAuthorityV1
    origin_run_id: str
    work_item_id: str
    selection_reason: str


def _checkpoint_adoption_payload(
    payload: Mapping[str, object],
) -> _CheckpointAdoptionPayload:
    try:
        raw = exact_object(payload, _CHECKPOINT_FIELDS, f"{_CHECKPOINT_EVENT} payload")
        selection_bundle_id = digest_value(
            raw["checkpoint_selection_bundle_id"],
            "checkpoint_selection_bundle_id",
        )
        checkpoint_manifest_id = digest_value(
            raw["checkpoint_manifest_id"],
            "checkpoint_manifest_id",
        )
        authority = AdoptedArtifactAuthorityV1.from_json_dict(
            raw["adopted_artifact_authority"]
        )
        origin_run_id = safe_id(raw["origin_run_id"], "origin_run_id")
        work_item_id = digest_value(raw["work_item_id"], "work_item_id")
        selection_reason = one_of(
            raw["selection_reason"],
            CHECKPOINT_SELECTION_REASONS,
            "selection_reason",
        )
    except (Protocol22SchemaError, ValueError) as exc:
        raise ReV2EventError(str(exc)) from exc
    if authority.source_run_id != origin_run_id:
        raise ReV2EventError(
            "checkpoint adoption origin disagrees with adopted authority"
        )
    return _CheckpointAdoptionPayload(
        selection_bundle_id,
        checkpoint_manifest_id,
        authority,
        origin_run_id,
        work_item_id,
        selection_reason,
    )


@dataclass(slots=True)
class Protocol26ReplayState(EventReplayState):
    """Replay checkpoint ordering while delegating all layer transitions."""

    delegate: EventReplayState
    dispatched_work_items: set[str] = field(default_factory=set)
    adopted_work_items: set[str] = field(default_factory=set)
    artifact_keys: set[str] = field(default_factory=set)
    acceptance_receipts: set[str] = field(default_factory=set)

    @property
    def shared(self) -> EventReplayState:
        """Expose the established replay-composition seam to budget consumers."""
        return self.delegate

    def consume(self, event: EventRecord) -> None:
        if event.type != _CHECKPOINT_EVENT:
            self.delegate.consume(event)
            if event.type in _WORK_DISPATCH_EVENTS:
                self.dispatched_work_items.add(str(event.payload["work_item_id"]))
            return

        payload = _checkpoint_adoption_payload(event.payload)
        if payload.work_item_id in self.dispatched_work_items:
            raise ReV2EventError(
                "checkpoint_artifact_adopted must precede every dispatch or lease "
                "for its work item"
            )
        active = bool(getattr(self.delegate, "has_active_dispatch", False))
        if active:
            raise ReV2EventError(
                "checkpoint_artifact_adopted is invalid during an active dispatch"
            )
        if payload.work_item_id in self.adopted_work_items:
            raise ReV2EventError("checkpoint adoption contains a duplicate work item")
        if payload.authority.artifact_key_id in self.artifact_keys:
            raise ReV2EventError(
                "checkpoint adoption contains a duplicate artifact key"
            )
        acceptance_id = payload.authority.artifact_acceptance_receipt_id
        if acceptance_id in self.acceptance_receipts:
            raise ReV2EventError(
                "checkpoint adoption contains a duplicate acceptance receipt"
            )

        mark_accepted = getattr(self.delegate, "mark_imported_work_accepted", None)
        if not callable(mark_accepted):
            raise ReV2EventError("layer replay does not support imported acceptance")
        mark_accepted(payload.work_item_id, event.type)
        self.adopted_work_items.add(payload.work_item_id)
        self.artifact_keys.add(payload.authority.artifact_key_id)
        self.acceptance_receipts.add(acceptance_id)


@dataclass(frozen=True, slots=True)
class _Protocol26Events(EventProtocol):
    target_layer: TargetLayerV1
    delegate: EventProtocol

    PROTOCOL_VERSION: ClassVar[str] = "2.6"

    def canonical_payload(
        self,
        event_type: str,
        payload: Mapping[str, object],
    ) -> Mapping[str, object]:
        if event_type != _CHECKPOINT_EVENT:
            return self.delegate.canonical_payload(event_type, payload)
        canonical = _canonical_payload(_thaw_json(payload))
        _checkpoint_adoption_payload(canonical)
        return canonical

    def new_state(self) -> EventReplayState:
        return Protocol26ReplayState(self.delegate.new_state())


def protocol_26_events_for(target_layer: TargetLayerV1) -> EventProtocol:
    """Compose checkpoint adoption over the target layer's existing protocol."""
    delegates: dict[str, EventProtocol] = {
        "L1": PROTOCOL_22_EVENTS,
        "L2": PROTOCOL_24_EVENTS,
        "L3": PROTOCOL_25_EVENTS,
    }
    try:
        delegate = delegates[target_layer]
    except (KeyError, TypeError) as exc:
        raise ReV2EventError(
            f"unsupported protocol-2.6 target layer: {target_layer!r}"
        ) from exc
    return _Protocol26Events(target_layer, delegate)


def append_missing_checkpoint_events(
    inputs: ValidatedProtocol26Inputs,
    event_store: EventStore,
    ledger: Protocol22Ledger,
    clock: Callable[[], str],
) -> CheckpointAdoptionReportV1:
    """Append the frozen adoption-event suffix after typed ledger import."""
    if not isinstance(inputs, ValidatedProtocol26Inputs):
        raise Protocol26AdoptionError(
            "checkpoint events require ValidatedProtocol26Inputs"
        )
    protocol = event_store.protocol
    if (
        getattr(protocol, "PROTOCOL_VERSION", None) != "2.6"
        or getattr(protocol, "target_layer", None) != inputs.manifest.target_layer
    ):
        raise Protocol26AdoptionError(
            "checkpoint event store does not match the schema-5 target layer"
        )
    report = checkpoint_adoption_report(inputs, ledger)
    expected = {
        selection.expected_work_item_id: selection.to_event_payload(
            inputs.checkpoint_selection.identity
        )
        for selection in inputs.checkpoint_selection.selected
        if selection.source_kind == "workspace_checkpoint"
    }
    history = event_store.replay()
    for event in history:
        if event.type != _CHECKPOINT_EVENT:
            continue
        work_item_id = str(event.payload["work_item_id"])
        payload = expected.get(work_item_id)
        if payload is None or canonical_json_bytes(
            _thaw_json(event.payload)
        ) != canonical_json_bytes(payload):
            raise Protocol26AdoptionError(
                "existing checkpoint adoption event conflicts with frozen selection"
            )

    state = cast(Protocol26ReplayState, event_store.protocol.new_state())
    if not isinstance(state, Protocol26ReplayState):
        raise Protocol26AdoptionError(
            "checkpoint event store does not expose protocol-2.6 replay"
        )
    for event in history:
        state.consume(event)
    for selection in inputs.checkpoint_selection.selected:
        if selection.source_kind != "workspace_checkpoint":
            continue
        if selection.expected_work_item_id in state.adopted_work_items:
            continue
        event = event_store.append(
            _CHECKPOINT_EVENT,
            selection.to_event_payload(inputs.checkpoint_selection.identity),
            occurred_at=clock(),
        )
        state.consume(event)
    return report


__all__ = (
    "Protocol26ReplayState",
    "append_missing_checkpoint_events",
    "protocol_26_events_for",
)
