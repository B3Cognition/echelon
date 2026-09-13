"""Sole-writer protocol-2.8 event and projection controller."""

from __future__ import annotations

from collections.abc import Callable
import os
from pathlib import Path
import tempfile
from typing import Literal, Mapping

from harness.re_v2.canonical import canonical_json_bytes
from harness.re_v2.events import EventRecord, EventStore
from harness.re_v2.ledger import ObjectStore
from harness.re_v2.protocol_28.events import (
    PROTOCOL_28_EVENTS,
    Protocol28ProjectionV1,
    project_protocol_28,
)
from harness.re_v2.protocol_28.graph import (
    L4FindingClosureReceiptV1,
    L4RunRootV1,
    L4SemanticClosureRootV1,
    L4SourceRootV1,
    L4TargetRootV1,
)


class Protocol28ControllerError(RuntimeError):
    """Raised when the controller cannot publish an authoritative transition."""


class Protocol28Controller:
    """Append one transition and refresh only the rebuildable projection."""

    def __init__(
        self,
        event_store: EventStore,
        object_store: ObjectStore,
        projection_path: Path,
        *,
        clock: Callable[[], str],
        fault: Callable[[str], None] | None = None,
    ) -> None:
        if event_store.protocol is not PROTOCOL_28_EVENTS:
            raise Protocol28ControllerError(
                "protocol-2.8 controller requires the protocol-2.8 event vocabulary"
            )
        if not isinstance(object_store, ObjectStore):
            raise Protocol28ControllerError("controller object store is invalid")
        if not callable(clock):
            raise Protocol28ControllerError("controller clock is invalid")
        self.event_store = event_store
        self.object_store = object_store
        self.projection_path = Path(projection_path)
        self.clock = clock
        self.fault = fault

    def append_once(
        self,
        event_type: str,
        payload: Mapping[str, object],
    ) -> EventRecord:
        """Append exactly one matching content-free transition."""
        canonical = self.event_store.protocol.canonical_payload(event_type, payload)
        for event in self.event_store.replay():
            if event.type == event_type and event.payload == canonical:
                self.rebuild_projection()
                return event
        event = self.event_store.append(
            event_type,
            payload,
            occurred_at=self.clock(),
        )
        self._fault("after_event_before_projection")
        self.rebuild_projection()
        return event

    def record_root(
        self,
        root: L4TargetRootV1 | L4SourceRootV1 | L4RunRootV1,
        *,
        root_kind: Literal["target", "source", "run"],
    ) -> EventRecord:
        """Persist root bytes before publishing their event authority."""
        required_accepted: tuple[str, ...]
        required_roots: tuple[str, ...]
        if root_kind == "target" and isinstance(root, L4TargetRootV1):
            required_accepted = root.accepted_slice_ids
            required_roots = ()
        elif root_kind == "source" and isinstance(root, L4SourceRootV1):
            required_accepted = ()
            required_roots = tuple(
                sorted(
                    {
                        root.source_composition_root_id,
                        *root.selected_domain_root_ids,
                    }
                )
            )
        elif root_kind == "run" and isinstance(root, L4RunRootV1):
            required_accepted = root.accepted_slice_ids
            required_roots = tuple(
                sorted({*root.target_root_ids, *root.source_root_ids})
            )
        else:
            raise Protocol28ControllerError("root type does not match root kind")
        object_id = self.object_store.put_blob(
            canonical_json_bytes(root.to_json_dict())
        )
        if object_id != root.identity:
            raise Protocol28ControllerError("root object identity changed while stored")
        self._fault("after_root_object")
        return self.append_once(
            "root_recorded",
            {
                "required_accepted_slice_ids": list(required_accepted),
                "required_root_ids": list(required_roots),
                "root_id": root.identity,
                "root_kind": root_kind,
            },
        )

    def record_materialization(self, root_id: str) -> EventRecord:
        return self.append_once("materialization_completed", {"root_id": root_id})

    def record_knowledge_root(self, root):
        from harness.re_v2.protocol_28.reconciliation import knowledge_root_event_payload
        try:
            payload = knowledge_root_event_payload(root)
        except ValueError as exc:
            raise Protocol28ControllerError('invalid reviewed knowledge root') from exc
        if self.object_store.put_blob(canonical_json_bytes(root.to_json_dict())) != root.identity:
            raise Protocol28ControllerError('reviewed root identity changed')
        self._fault('after_knowledge_root_object')
        return self.append_once('knowledge_root_recorded', payload)

    def block_run(
        self,
        blocker_kind: Literal["resource", "execution", "closure_integrity"],
        reason_code: str,
    ) -> EventRecord:
        """Record a repeatable blocker without suppressing a later recurrence."""
        events = self.event_store.replay()
        projection = project_protocol_28(events)
        payload = {"blocker_kind": blocker_kind, "reason_code": reason_code}
        if projection.lifecycle_state == f"{blocker_kind}_blocked" and events:
            latest = events[-1]
            canonical = self.event_store.protocol.canonical_payload(
                "run_blocked", payload
            )
            if latest.type == "run_blocked" and latest.payload == canonical:
                self.rebuild_projection()
                return latest
        event = self.event_store.append(
            "run_blocked", payload, occurred_at=self.clock()
        )
        self._fault("after_event_before_projection")
        self.rebuild_projection()
        return event

    def link_closure_successor(
        self,
        closure_run_id: str,
        closure_run_manifest_id: str,
        l4_run_root_id: str,
    ) -> EventRecord:
        """Link deterministic closure authority without any provider seam."""
        return self.append_once(
            "closure_successor_linked",
            {
                "closure_run_id": closure_run_id,
                "closure_run_manifest_id": closure_run_manifest_id,
                "l4_run_root_id": l4_run_root_id,
            },
        )

    def record_closure_root(
        self,
        closure_root: L4SemanticClosureRootV1,
        closure_run_manifest_id: str,
    ) -> EventRecord:
        if not isinstance(closure_root, L4SemanticClosureRootV1):
            raise Protocol28ControllerError("closure root authority is invalid")
        object_id = self.object_store.put_blob(
            canonical_json_bytes(closure_root.to_json_dict())
        )
        if object_id != closure_root.identity:
            raise Protocol28ControllerError("closure root object identity changed")
        self._fault("after_closure_root_object")
        return self.append_once(
            "closure_root_recorded",
            {
                "closure_root_id": closure_root.identity,
                "closure_run_manifest_id": closure_run_manifest_id,
                "l4_run_root_id": closure_root.l4_run_root_id,
            },
        )

    def record_closure_receipt(
        self,
        receipt: L4FindingClosureReceiptV1,
    ) -> EventRecord:
        """Persist one deterministic finding closure before exposing its ID."""
        if not isinstance(receipt, L4FindingClosureReceiptV1):
            raise Protocol28ControllerError("closure receipt authority is invalid")
        object_id = self.object_store.put_blob(
            canonical_json_bytes(receipt.to_json_dict())
        )
        if object_id != receipt.identity:
            raise Protocol28ControllerError("closure receipt object identity changed")
        self._fault("after_closure_receipt_object")
        return self.append_once(
            "closure_receipt_recorded",
            {
                "closure_receipt_id": receipt.identity,
                "finding_id": receipt.finding_id,
            },
        )

    def complete_run(self, run_root_id: str, *, closure_required: bool) -> EventRecord:
        return self.append_once(
            "run_completed",
            {
                "completion_kind": (
                    "semantic_closure" if closure_required else "evidence_only"
                ),
                "run_root_id": run_root_id,
            },
        )

    def rebuild_projection(self) -> Protocol28ProjectionV1:
        projection = project_protocol_28(self.event_store.replay())
        self._write_projection(canonical_json_bytes(projection.to_json_dict()))
        return projection

    def _write_projection(self, payload: bytes) -> None:
        parent = self.projection_path.parent
        if parent.is_symlink() or not parent.is_dir():
            raise Protocol28ControllerError(
                "projection parent must be a real existing directory"
            )
        if self.projection_path.is_symlink():
            raise Protocol28ControllerError("projection path must not be a symlink")
        fd, temporary = tempfile.mkstemp(prefix=".projection-", dir=parent)
        temporary_path = Path(temporary)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_path, self.projection_path)
            directory_fd = os.open(parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            if temporary_path.exists():
                temporary_path.unlink()

    def _fault(self, seam: str) -> None:
        if self.fault is not None:
            self.fault(seam)


__all__ = (
    "Protocol28Controller",
    "Protocol28ControllerError",
)
