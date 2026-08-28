"""Protocol-2.4 adoption events over the shared protocol-2.2 replay machine."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar, Mapping

from harness.re_v2.events import (
    EventProtocol,
    EventRecord,
    EventReplayState,
    ReV2EventError,
    _canonical_payload,
    _thaw_json,
)
from harness.re_v2.protocol_22.events import (
    PROTOCOL_22_EVENTS,
    Protocol22ReplayState,
)
from harness.re_v2.protocol_22.schema import (
    Protocol22SchemaError,
    digest_value,
    exact_object,
)

from .model import AdoptedArtifactAuthorityV1


_ADOPTION_FIELDS = frozenset(
    {
        "adopted_artifact_authority",
        "parent_authority_bundle_hash",
        "work_item_id",
    }
)
_WORK_DISPATCH_EVENTS = frozenset(
    {"dispatch_leased", "dispatch_started", "dispatch_lease_retired"}
)


def _adoption_payload(payload: Mapping[str, object]) -> tuple[str, str, str, str]:
    try:
        raw = exact_object(payload, _ADOPTION_FIELDS, "artifact_adopted payload")
        bundle_hash = digest_value(
            raw["parent_authority_bundle_hash"],
            "parent_authority_bundle_hash",
        )
        work_item_id = digest_value(raw["work_item_id"], "work_item_id")
        authority = AdoptedArtifactAuthorityV1.from_json_dict(
            raw["adopted_artifact_authority"]
        )
    except (Protocol22SchemaError, ValueError) as exc:
        raise ReV2EventError(str(exc)) from exc
    return (
        bundle_hash,
        work_item_id,
        authority.artifact_key_id,
        authority.artifact_acceptance_receipt_id,
    )


@dataclass(slots=True)
class Protocol24ReplayState(EventReplayState):
    """Add adoption ordering while delegating every shared transition to 2.2."""

    shared: Protocol22ReplayState = field(default_factory=Protocol22ReplayState)
    dispatched_work_items: set[str] = field(default_factory=set)
    adopted_work_items: set[str] = field(default_factory=set)
    adopted_artifact_keys: set[str] = field(default_factory=set)
    adopted_acceptance_receipts: set[str] = field(default_factory=set)

    @property
    def has_active_dispatch(self) -> bool:
        return self.shared.has_active_dispatch

    def mark_imported_work_accepted(
        self,
        work_item_id: str,
        event_type: str,
    ) -> None:
        """Apply the shared accepted-work transition without forging an L2 event."""
        self.shared.mark_imported_work_accepted(work_item_id, event_type)

    def consume(self, event: EventRecord) -> None:
        if event.type != "artifact_adopted":
            self.shared.consume(event)
            if event.type in _WORK_DISPATCH_EVENTS:
                self.dispatched_work_items.add(str(event.payload["work_item_id"]))
            return

        bundle_hash, work_item_id, artifact_key_id, acceptance_id = _adoption_payload(
            event.payload
        )
        del bundle_hash
        if self.shared.terminal:
            raise ReV2EventError("event appears after terminal run state")
        if self.shared.seen == 0:
            raise ReV2EventError("run_created must be the first event")
        if self.shared.paused or self.shared.pause_requested:
            raise ReV2EventError(
                "artifact_adopted is not allowed while pausing or paused"
            )
        if (
            work_item_id in self.dispatched_work_items
            or self.shared.lease_work_item_id == work_item_id
            or (
                self.shared.active is not None
                and self.shared.active.work_item_id == work_item_id
            )
        ):
            raise ReV2EventError(
                "artifact_adopted must precede every dispatch or lease for its work item"
            )
        if (
            work_item_id in self.adopted_work_items
            or work_item_id in self.shared.accepted_work_items
        ):
            raise ReV2EventError("work item is already adopted or accepted")
        if artifact_key_id in self.adopted_artifact_keys:
            raise ReV2EventError("artifact_adopted contains a duplicate artifact key")
        if acceptance_id in self.adopted_acceptance_receipts:
            raise ReV2EventError(
                "artifact_adopted contains a duplicate acceptance receipt"
            )
        self.adopted_work_items.add(work_item_id)
        self.adopted_artifact_keys.add(artifact_key_id)
        self.adopted_acceptance_receipts.add(acceptance_id)
        self.shared.accepted_work_items.add(work_item_id)
        self.shared._finish(event.type)


class _Protocol24Events(EventProtocol):
    PROTOCOL_VERSION: ClassVar[str] = "2.4"

    def canonical_payload(
        self,
        event_type: str,
        payload: Mapping[str, object],
    ) -> Mapping[str, object]:
        if event_type != "artifact_adopted":
            return PROTOCOL_22_EVENTS.canonical_payload(event_type, payload)
        canonical = _canonical_payload(_thaw_json(payload))
        _adoption_payload(canonical)
        return canonical

    def new_state(self) -> EventReplayState:
        return Protocol24ReplayState()


PROTOCOL_24_EVENTS: EventProtocol = _Protocol24Events()


__all__ = (
    "PROTOCOL_24_EVENTS",
    "Protocol24ReplayState",
)
