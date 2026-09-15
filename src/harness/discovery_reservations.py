"""Inactive selected-run proposal/reservation receipts; no provider or publisher.

The caller owns execution leases and durable operation selection. Explicit
creation is only for that newly selected operation; resume must load its journal.
Checksums detect corruption, not semantic approval or controller authority.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path

from harness.discovery_candidate import DiscoveryReservation
from harness.discovery_semantics import DiscoveryAssignment, decode_discovery_assignment, validate_discovery_reply
from harness.discovery_receipts import DiscoveryReceiptFile
from harness.element_identity_lifecycle import text


_MAX_BYTES = 16 * 1024 * 1024


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def _digest(value):
    return hashlib.sha256(_canonical(value).encode("ascii")).hexdigest()


def _closed(value, fields):
    if type(value) is not dict or set(value) != set(fields):
        raise ValueError("invalid discovery reservation schema")


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate discovery reservation field")
        result[key] = value
    return result


def _assignment(value):
    fields = {"schema_version", "operation_id", "dispatch_id", "spec_id", "run_id", "step",
              "input_fingerprint", "artifact_paths", "editable_revisions", "assigned_ids"}
    if value.get("schema_version") in {2, 3, 4}:
        fields.add("producer")
    if value.get("schema_version") in {3, 4} and value.get("step") == "review":
        fields.add("routing")
    identity = {key: value[key] for key in fields if key in value}
    return decode_discovery_assignment(identity)


def _intents(binding, proposal, known):
    new = []
    for subject in proposal["new_subjects"]:
        previous = known.get(subject["key"])
        if previous is not None and previous[0] != subject:
            raise ValueError("discovery key cannot change subject, kind or caption")
        if previous is None:
            new.append(subject)
    result = []
    for kind in (("ISS", "U") if proposal.get("producer") == "why1" else ("II", "UI") if proposal.get("producer") == "tracker" else ("A", "U")):
        keys = sorted(item["key"] for item in new if item["kind"] == kind)
        if keys:
            identity = {"binding": binding, "proposal_sha256": _digest(proposal), "kind": kind, "keys": keys}
            result.append(dict(kind=kind, keys=keys, operation_id="discovery-reserve-" + _digest(identity), ids=None))
    return result


def _validate(data, binding, producer=None):
    _closed(data, ("schema_version", "binding", "proposals"))
    if type(data["schema_version"]) is not int or data["schema_version"] != 1 or data["binding"] != binding:
        raise ValueError("discovery reservation selection changed")
    records = data["proposals"]
    if type(records) is not list or len(records) > 3:
        raise ValueError("invalid discovery proposal receipt count")
    known, dispatches, scope = {}, set(), None
    for index, record in enumerate(records):
        _closed(record, ("proposal", "sha256", "intents"))
        assignment = _assignment(record["proposal"])
        if producer is not None and assignment.producer != producer:
            raise ValueError("discovery reservation producer changed")
        proposal = validate_discovery_reply(record["proposal"], assignment)
        if (assignment.step != "propose" or proposal["action"] != "final"
                or (assignment.operation_id, assignment.spec_id, assignment.run_id) != (
                    binding["operation_id"], binding["spec_id"], binding["run_id"])
                or proposal != record["proposal"] or _digest(proposal) != record["sha256"]
                or assignment.dispatch_id in dispatches):
            raise ValueError("invalid discovery proposal association")
        dispatches.add(assignment.dispatch_id)
        selected = (assignment.producer, sorted(assignment.artifact_paths), sorted(assignment.editable_revisions))
        if scope is not None and selected != scope:
            raise ValueError("discovery reservation scope changed")
        scope = selected
        expected = _intents(binding, proposal, known)
        intents = record["intents"]
        if type(intents) is not list or len(intents) != len(expected):
            raise ValueError("invalid discovery reservation intents")
        pending = False
        for actual, wanted in zip(intents, expected):
            _closed(actual, wanted)
            if {**actual, "ids": None} != wanted:
                raise ValueError("discovery reservation intent changed")
            ids = actual["ids"]
            if ids is None:
                pending = True
                if index != len(records) - 1:
                    raise ValueError("discovery proposal follows incomplete reservation")
            elif pending or type(ids) is not list or len(ids) != len(actual["keys"]) or any(type(item) is not str for item in ids):
                raise ValueError("invalid discovery reservation result")
            subjects = {item["key"]: item for item in proposal["new_subjects"]}
            for offset, key in enumerate(actual["keys"]):
                known[key] = (subjects[key], None if ids is None else DiscoveryReservation(
                    key, ids[offset], actual["operation_id"]))
    return known


class DiscoveryReservationJournal(DiscoveryReceiptFile):
    """Serialize exact associations; a completed result is verified read-only."""

    def __init__(self, run_dir: Path, *, producer="discovery", round_operation_id: str | None = None):
        super().__init__(run_dir, "discovery-reservations", producer=producer, round_operation_id=round_operation_id)
        self._data = self._binding = self._store = None

    def __exit__(self, *args):
        super().__exit__(*args)
        self._store = self._data = self._binding = None

    def _save(self):
        _validate(self._data, self._binding, self.producer)
        raw = _canonical({"payload": self._data, "sha256": _digest(self._data)}) + "\n"
        if len(raw.encode("utf-8")) > _MAX_BYTES:
            raise ValueError("discovery reservation record exceeds limit")
        try:
            self._write(raw)
        except BaseException:
            # A failed fsync/replace can leave either image: only reopen may decide.
            self._store = None
            raise

    def select(self, store, *, spec_id, run_id, operation_id, managed_identity, create=False):
        if self._store is not None or type(create) is not bool:
            raise ValueError("invalid discovery reservation selection")
        text(operation_id, "operation_id")
        if self.round_operation_id is not None and operation_id != self.round_operation_id:
            raise ValueError("Tracker receipt round selection changed")
        self._check_directory()
        context = store.check_managed_context(spec_id=spec_id, run_id=run_id, record=managed_identity)
        binding = dict(operation_id=operation_id, spec_id=spec_id, run_id=run_id,
                       run_dir=str(self.run_dir), context=context)
        raw = self._read()
        if create:
            if raw is not None:
                raise ValueError("discovery reservation journal already exists")
            data = dict(schema_version=1, binding=binding, proposals=[])
        else:
            if raw is None:
                raise ValueError("required discovery reservation journal is missing")
            try:
                envelope = json.loads(raw, object_pairs_hook=_pairs)
                _closed(envelope, ("payload", "sha256"))
                data = envelope["payload"]
                if envelope["sha256"] != _digest(data):
                    raise ValueError("checksum mismatch")
                _validate(data, binding, self.producer)
            except (ValueError, TypeError, KeyError, RecursionError, OverflowError):
                raise ValueError("invalid discovery reservation recovery record") from None
        self._store, self._data, self._binding, self._raw = store, data, binding, raw
        try:
            self._authenticate()
            if create:
                self._save()
        except BaseException:
            self._store = None
            raise

    def _authenticate(self):
        if self._store is None:
            raise ValueError("discovery reservation operation is not selected")
        if self._read() != self._raw:
            raise ValueError("discovery reservation record changed")
        binding = self._binding
        observed = self._store.check_managed_context(spec_id=binding["spec_id"], run_id=binding["run_id"],
            record=binding["context"]["managed_identity"])
        if observed != binding["context"]:
            raise ValueError("discovery reservation source context changed")
        _validate(self._data, binding, self.producer)
        for record in self._data["proposals"]:
            for intent in record["intents"]:
                retained = self._store.reservation(spec_id=binding["spec_id"], kind=intent["kind"],
                    operation_id=intent["operation_id"], count=len(intent["keys"]))
                if intent["ids"] is not None and (retained is None or list(retained) != intent["ids"]):
                    raise ValueError("completed discovery reservation differs from authority")

    def bind(self, assignment: DiscoveryAssignment, reply: dict, *, replay_only=False) -> tuple[DiscoveryReservation, ...]:
        if type(replay_only) is not bool:
            raise ValueError("invalid discovery reservation replay mode")
        self._authenticate()
        proposal = validate_discovery_reply(reply, assignment)
        if assignment.producer != self.producer or assignment.step != "propose" or proposal["action"] != "final":
            raise ValueError("discovery reservation requires a final proposal")
        records = self._data["proposals"]
        matching = [record for record in records if record["proposal"]["dispatch_id"] == assignment.dispatch_id]
        if replay_only and (not matching or any(intent["ids"] is None for intent in matching[0]["intents"])):
            raise ValueError("completed discovery reservation receipt required")
        if matching:
            record, = matching
            if record["proposal"] != proposal:
                raise ValueError("discovery dispatch proposal changed")
        else:
            if any(intent["ids"] is None for record in records for intent in record["intents"]):
                raise ValueError("previous discovery reservation must be recovered first")
            known = _validate(self._data, self._binding, self.producer)
            record = dict(proposal=proposal, sha256=_digest(proposal), intents=_intents(self._binding, proposal, known))
            candidate = deepcopy(self._data)
            candidate["proposals"].append(record)
            _validate(candidate, self._binding, self.producer)
            self._data = candidate
            self._save()  # Complete intent set precedes the first allocator call.
        for intent in record["intents"]:
            if intent["ids"] is None:
                self._authenticate()
                request = dict(spec_id=self._binding["spec_id"], kind=intent["kind"],
                               operation_id=intent["operation_id"], count=len(intent["keys"]))
                ids = self._store.reservation(**request)
                if ids is None:
                    ids = self._store.reserve(**request)
                intent["ids"] = list(ids)
                self._save()
        self._authenticate()
        known = _validate(self._data, self._binding, self.producer)
        return tuple(known[item["key"]][1] for item in proposal["new_subjects"])
