"""Controller-owned, pre-analysis discovery acquisition over the RE run store.

This phase resolves frozen evidence; it neither schedules providers nor publishes
analysis plans. Its journal uses the existing durable envelope and run ownership
lock. Request intent consumes a round before work; the final context receipt is
the only active-pointer authority. Orphan staged objects never activate anything.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Callable

from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.knowledge_discovery import (
    DiscoveryBoundary, DiscoveryError, _closed_errors, _load, _obj, _selector,
)
from harness.re_v2.ledger import DurableLedger, LedgerRecord, ObjectStore
from harness.re_v2.protocol_22.recovery import protocol_22_run_lock
from harness.re_v2.protocol_22.schema import digest_value
from harness.re_v2.run_store import ReV2Paths


@dataclass(frozen=True, slots=True)
class DiscoveryProgress:
    revision_id: str
    binding_id: str
    rounds: int
    pending_id: str | None


def _sync_directory(path):
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    fd = os.open(path, flags)
    try:
        while True:
            try:
                os.fsync(fd)
                break
            except InterruptedError:
                continue
    finally:
        os.close(fd)


def _public_context(base: bytes, outcomes: list[dict]) -> bytes:
    context = _load(base)
    if outcomes:
        context["evidence_request_outcomes"] = [
            {key: row[key] for key in ("request_id", "selector", "reason_class", "obligation_id",
                                      "disposition", "reason_code", "projection_id")}
            for row in outcomes
        ]
    encoded = canonical_json_bytes(context)
    if len(encoded) > 262_144:
        raise DiscoveryError("discovery-context-bound")
    return encoded


def _scope(binding: dict) -> dict:
    return {key: binding[key] for key in ("snapshot_id", "partition_id", "source_id", "depth",
                                        "origin_obligation_id", "security_policy_id")}


class _AcquisitionProtocol:
    def __init__(self, opening: dict, boundary: DiscoveryBoundary):
        self.opening = opening
        self.boundary = boundary

    def canonical_payload(self, record_type, value):
        if record_type not in {"discovery_opened", "expansion_requested", "evidence_resolved", "evidence_reused", "context_committed"}:
            raise DiscoveryError("invalid-acquisition-event")
        _obj(value, ("receipt_id",))
        digest_value(value["receipt_id"], "receipt")
        return dict(value)

    def new_state(self):
        return _AcquisitionState(self)


class _AcquisitionState:
    def __init__(self, protocol):
        self.protocol = protocol
        self.progress = None
        self.context_id = None
        self.pending = None
        self.requests = {}
        self.resolved = {}
        self.outcome_ids = []
        self.outcomes = {}
        self.completed = {}

    def view(self):
        # This replay state is local to the phase. Public callers receive only
        # the immutable DiscoveryProgress projection, never these mutable maps.
        return self

    def idempotent_record(self, history, record_type, payload):
        return next((record for record in history if record.type == record_type and record.payload == payload), None)

    def consume(self, record: LedgerRecord, objects: ObjectStore):
        payload = self.protocol.canonical_payload(record.type, dict(record.payload))
        receipt_id = payload["receipt_id"]
        receipt = _load(objects.read_blob(receipt_id))
        if record.type == "discovery_opened":
            if self.progress is not None or receipt != self.protocol.opening:
                raise DiscoveryError("discovery-opening-mismatch")
            self.progress = DiscoveryProgress(receipt_id, receipt["initial_binding_id"], 0, None)
            self.context_id = receipt["context_id"]
            objects.read_blob(self.context_id)
            return
        if self.progress is None:
            raise DiscoveryError("missing-discovery-opening")
        if record.type == "expansion_requested":
            _obj(receipt, ("schema_version", "kind", "scope_id", "binding_id", "batch_id",
                           "previous_revision_id", "round", "request_keys"))
            if (receipt["schema_version"] != 1 or receipt["kind"] != "discovery_expansion_intent"
                    or receipt["scope_id"] != content_digest(self.protocol.opening)
                    or self.pending is not None or receipt["binding_id"] != self.progress.binding_id
                    or receipt["previous_revision_id"] != self.progress.revision_id
                    or type(receipt["round"]) is not int or receipt["round"] != self.progress.rounds + 1
                    or receipt["round"] > 2 or receipt["batch_id"] in self.completed):
                raise DiscoveryError("invalid-expansion-transition")
            rows = self.protocol.boundary.read_requests(receipt["binding_id"], receipt["batch_id"])
            if all(_semantic_key(row) in self.reusable() for row in rows):
                raise DiscoveryError("redundant-evidence-expansion")
            keys = _request_keys(self.protocol.opening, self.progress.revision_id, rows)
            if receipt["request_keys"] != keys:
                raise DiscoveryError("evidence-request-key-mismatch")
            self.pending, self.requests, self.resolved = receipt, {r["request_id"]: r for r in rows}, {}
            self.progress = DiscoveryProgress(self.progress.revision_id, self.progress.binding_id,
                                              receipt["round"], receipt_id)
        elif record.type in {"evidence_resolved", "evidence_reused"}:
            if self.pending is None:
                raise DiscoveryError("unsolicited-evidence-outcome")
            previous_id = None
            if record.type == "evidence_reused":
                _obj(receipt, ("schema_version", "kind", "previous_outcome_id", "outcome_id"))
                if (type(receipt["schema_version"]) is not int or receipt["schema_version"] != 1
                        or receipt["kind"] != "discovery_evidence_reuse"
                        or receipt["previous_outcome_id"] not in self.outcome_ids):
                    raise DiscoveryError("invalid-evidence-reuse")
                previous_id, receipt_id = receipt["previous_outcome_id"], receipt["outcome_id"]
                receipt = _load(objects.read_blob(receipt_id))
            request_id = receipt["request_id"]
            if (receipt["binding_id"] != self.pending["binding_id"]
                    or receipt["batch_id"] != self.pending["batch_id"]
                    or request_id not in self.requests or request_id in self.resolved):
                raise DiscoveryError("evidence-outcome-scope-mismatch")
            # Intent admission already authenticated this batch and its base
            # context in this replay. Still verify each selected evidence range
            # against the real pinned reader; never cache across replay calls.
            if previous_id is None:
                outcome = self.protocol.boundary._validate_admitted_outcome(
                    receipt_id, self.pending["binding_id"], self.pending["batch_id"], self.requests[request_id])
            else:
                previous = self.outcomes[previous_id]
                expected = _rebound_outcome(previous, self.pending, self.requests[request_id])
                if _semantic_key(previous) != _semantic_key(self.requests[request_id]) or receipt != expected:
                    raise DiscoveryError("evidence-reuse-scope-mismatch")
                outcome = receipt
            self.resolved[request_id] = receipt_id
            self.outcomes[receipt_id] = outcome
        else:
            _obj(receipt, ("schema_version", "kind", "scope_id", "previous_revision_id", "intent_id",
                           "binding_id", "context_id", "round", "outcome_ids"))
            if (self.pending is None or receipt["schema_version"] != 1
                    or receipt["kind"] != "discovery_context_revision"
                    or receipt["scope_id"] != content_digest(self.protocol.opening)
                    or receipt["previous_revision_id"] != self.progress.revision_id
                    or receipt["intent_id"] != self.progress.pending_id
                    or type(receipt["round"]) is not int or receipt["round"] != self.progress.rounds
                    or set(self.resolved) != set(self.requests)):
                raise DiscoveryError("incomplete-discovery-commit")
            expected_outcomes = self.outcome_ids + [self.resolved[key] for key in sorted(self.requests)]
            if receipt["outcome_ids"] != expected_outcomes:
                raise DiscoveryError("discovery-outcome-closure-mismatch")
            outcomes = [self.outcomes[oid] for oid in expected_outcomes]
            expected_binding = _expanded_binding(self.protocol.boundary, self.progress.binding_id, outcomes, persist=False)
            if receipt["binding_id"] != expected_binding:
                raise DiscoveryError("discovery-expanded-binding-mismatch")
            expected_context = _public_context(self.protocol.boundary.provider_bytes(expected_binding), outcomes)
            if objects.read_blob(receipt["context_id"]) != expected_context:
                raise DiscoveryError("discovery-expanded-context-mismatch")
            self.progress = DiscoveryProgress(receipt_id, expected_binding, self.progress.rounds, None)
            self.context_id, self.outcome_ids = receipt["context_id"], expected_outcomes
            self.completed[self.pending["batch_id"]] = self.progress
            self.pending, self.requests, self.resolved = None, {}, {}

    def reusable(self):
        # Scope is pinned by the opening. Binding/revision changes do not make
        # the same frozen selector new evidence or grant another expansion.
        return {_semantic_key(self.outcomes[oid]): oid for oid in self.outcome_ids}


def _request_keys(opening, revision_id, rows):
    return {row["request_id"]: content_digest({
        "logical_run_id": opening["logical_run_id"], "origin_obligation_id": row["obligation_id"],
        "revision_id": revision_id, "selector": row["selector"], "reason_class": row["reason_class"],
    }) for row in rows}


def _semantic_key(row):
    return content_digest({key: row[key] for key in ("obligation_id", "reason_class", "selector")})


def _rebound_outcome(previous, intent, request):
    return {**previous, "binding_id": intent["binding_id"], "batch_id": intent["batch_id"],
            "request_id": request["request_id"]}


def _expanded_binding(boundary, binding_id, outcomes, *, persist=True):
    binding = boundary.binding_details(binding_id)
    selectors = {canonical_json_bytes(row): row for row in binding["selectors"]}
    for outcome in outcomes:
        if outcome["projection_id"] is not None:
            row = outcome["selector"]
            selectors[canonical_json_bytes(row)] = row
    prepare = boundary.prepare if persist else boundary.verify_selection
    return prepare(
        tuple(_selector(selectors[key]) for key in sorted(selectors)),
        schema_version=binding["schema_version"],
    )


class DiscoveryAcquisition:
    """Resolve/recover one bounded discovery phase; never invoke a provider.

    The initial binding and logical run are immutable. All context revisions use
    that same run's object store and budget identity. Internal revisions cannot
    grant resources or rename the origin to acquire another two rounds.
    """

    @_closed_errors
    def __init__(self, paths: ReV2Paths, boundary: DiscoveryBoundary, initial_binding_id: str,
                 *, fault_hook: Callable[[str], None] | None = None):
        self.paths, self.boundary, self.objects = paths, boundary, boundary.object_store
        self.fault_hook = fault_hook
        if self.objects.root.resolve() != paths.objects.resolve():
            raise DiscoveryError("discovery-run-store-mismatch")
        binding = boundary.binding_details(initial_binding_id)
        self.opening = {"schema_version": 1, "kind": "discovery_acquisition_scope",
                        "logical_run_id": paths.root.parent.name, "budget_run_id": paths.root.parent.name,
                        "initial_binding_id": initial_binding_id, "context_id": binding["context_id"],
                        "evidence_scope": _scope(binding)}
        with protocol_22_run_lock(paths):
            # One initial discovery obligation per selected source. Hash its
            # exact ID to avoid aliases on case-insensitive filesystems. Origin
            # and revision stay out of this key: renaming either cannot acquire
            # fresh counters for the same pinned source.
            source_key = content_digest({"source_id": binding["source_id"]}).split(":", 1)[1]
            root = paths.root / "discovery" / source_key
            for directory in (root.parent, root):
                if directory.is_symlink() or (directory.exists() and not directory.is_dir()):
                    raise DiscoveryError("unsafe-discovery-store")
                directory.mkdir(mode=0o700, exist_ok=True)
                # Also sync on reopen: the previous owner may have crashed
                # after mkdir but before persisting its parent's directory entry.
                _sync_directory(directory.parent)
            self.ledger = DurableLedger(root / "ledger.jsonl", self.objects, _AcquisitionProtocol(self.opening, boundary))
            self._record("discovery_opened", self.objects.put_blob(canonical_json_bytes(self.opening)))

    def _record(self, kind, receipt_id):
        self.ledger._append(kind, {"receipt_id": receipt_id})

    def _fault(self, name):
        if self.fault_hook is not None:
            self.fault_hook(name)

    @_closed_errors
    def status(self) -> DiscoveryProgress:
        return self.ledger.replay().progress

    @_closed_errors
    def provider_bytes(self) -> bytes:
        with protocol_22_run_lock(self.paths):
            return self._provider_bytes_locked()

    def _provider_bytes_locked(self):
        state = self.ledger.replay()
        if state.progress.pending_id is not None:
            raise DiscoveryError("evidence-expansion-pending")
        base = self.boundary.provider_bytes(state.progress.binding_id)
        outcomes = [state.outcomes[oid] for oid in state.outcome_ids]
        context = _public_context(base, outcomes)
        if self.objects.read_blob(state.context_id) != context:
            raise DiscoveryError("discovery-expanded-context-mismatch")
        return context

    @_closed_errors
    def resolve(self, binding_id: str, batch_id: str) -> DiscoveryProgress:
        with protocol_22_run_lock(self.paths):
            return self._resolve_locked(binding_id, batch_id)

    def _resolve_locked(self, binding_id, batch_id):
        state = self.ledger.replay()
        rows = self.boundary.read_requests(binding_id, batch_id)
        if batch_id in state.completed:
            # A retry must return current progress, never an old counter.
            return state.progress
        if state.pending is not None:
            if batch_id != state.pending["batch_id"] or binding_id != state.pending["binding_id"]:
                raise DiscoveryError("evidence-expansion-pending")
        else:
            if binding_id != state.progress.binding_id:
                raise DiscoveryError("stale-discovery-binding")
            if all(_semantic_key(row) in state.reusable() for row in rows):
                return state.progress
            if state.progress.rounds >= 2:
                raise DiscoveryError("evidence-expansion-limit")
            intent = {"schema_version": 1, "kind": "discovery_expansion_intent",
                      "scope_id": content_digest(self.opening), "binding_id": binding_id, "batch_id": batch_id,
                      "previous_revision_id": state.progress.revision_id, "round": state.progress.rounds + 1,
                      "request_keys": _request_keys(self.opening, state.progress.revision_id, rows)}
            self._record("expansion_requested", self.objects.put_blob(canonical_json_bytes(intent)))
            self._fault("request_recorded")
        return self._recover_locked()

    @_closed_errors
    def recover(self) -> DiscoveryProgress:
        with protocol_22_run_lock(self.paths):
            return self._recover_locked()

    def _recover_locked(self):
        state = self.ledger.replay()
        if state.pending is None:
            return state.progress
        reusable = state.reusable()
        for request_id in sorted(state.requests):
            if request_id not in state.resolved:
                previous_id = reusable.get(_semantic_key(state.requests[request_id]))
                if previous_id is None:
                    outcome_id = self.boundary.resolve_request(state.pending["binding_id"], state.pending["batch_id"], request_id)
                    record_type, receipt_id = "evidence_resolved", outcome_id
                else:
                    outcome = _rebound_outcome(state.outcomes[previous_id], state.pending, state.requests[request_id])
                    outcome_id = self.objects.put_blob(canonical_json_bytes(outcome))
                    receipt_id = self.objects.put_blob(canonical_json_bytes({
                        "schema_version": 1, "kind": "discovery_evidence_reuse",
                        "previous_outcome_id": previous_id, "outcome_id": outcome_id,
                    }))
                    record_type = "evidence_reused"
                self._fault("outcome_staged")
                self._record(record_type, receipt_id)
                state.resolved[request_id] = outcome_id
                state.outcomes[outcome_id] = _load(self.objects.read_blob(outcome_id))
                self._fault("outcome_recorded")
        outcome_ids = state.outcome_ids + [state.resolved[key] for key in sorted(state.requests)]
        outcomes = [state.outcomes[oid] for oid in outcome_ids]
        binding_id = _expanded_binding(self.boundary, state.progress.binding_id, outcomes)
        context_id = self.objects.put_blob(_public_context(self.boundary.provider_bytes(binding_id), outcomes))
        manifest = {"schema_version": 1, "kind": "discovery_context_revision", "scope_id": content_digest(self.opening),
                    "previous_revision_id": state.progress.revision_id, "intent_id": state.progress.pending_id,
                    "binding_id": binding_id, "context_id": context_id, "round": state.progress.rounds,
                    "outcome_ids": outcome_ids}
        manifest_id = self.objects.put_blob(canonical_json_bytes(manifest))
        self._fault("context_staged")
        self._record("context_committed", manifest_id)
        self._fault("context_committed")
        return self.ledger.replay().progress
