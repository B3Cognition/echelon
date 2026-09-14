"""Inactive selected-run proposal/reservation receipts; no provider or publisher.

The caller owns execution leases and durable operation selection. Explicit
creation is only for that newly selected operation; resume must load its journal.
Checksums detect corruption, not semantic approval or controller authority.
"""
from __future__ import annotations

from copy import deepcopy
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat

from harness.discovery_candidate import DiscoveryReservation
from harness.discovery_semantics import DiscoveryAssignment, validate_discovery_reply
from harness.durable_json import write_text_atomic
from harness.element_identity_lifecycle import text
from harness.inspection_io import _open_root_directory


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
    identity = {key: value[key] for key in fields if key in value}
    _closed(identity, fields)
    if any(type(identity[key]) is not list for key in ("artifact_paths", "editable_revisions", "assigned_ids")):
        raise ValueError("invalid recovered discovery assignment")
    assignment = DiscoveryAssignment(**{key: (tuple(tuple(pair) for pair in item) if key == "editable_revisions"
        else tuple(item) if key in {"artifact_paths", "assigned_ids"} else item)
        for key, item in identity.items() if key != "schema_version"})
    if assignment.identity() != identity:
        raise ValueError("invalid recovered discovery assignment")
    return assignment


def _intents(binding, proposal, known):
    new = []
    for subject in proposal["new_subjects"]:
        previous = known.get(subject["key"])
        if previous is not None and previous[0] != subject:
            raise ValueError("discovery key cannot change subject, kind or caption")
        if previous is None:
            new.append(subject)
    result = []
    for kind in ("A", "U"):
        keys = sorted(item["key"] for item in new if item["kind"] == kind)
        if keys:
            identity = {"binding": binding, "proposal_sha256": _digest(proposal), "kind": kind, "keys": keys}
            result.append(dict(kind=kind, keys=keys, operation_id="discovery-reserve-" + _digest(identity), ids=None))
    return result


def _validate(data, binding):
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
        proposal = validate_discovery_reply(record["proposal"], assignment)
        if (assignment.step != "propose" or proposal["action"] != "final"
                or (assignment.operation_id, assignment.spec_id, assignment.run_id) != (
                    binding["operation_id"], binding["spec_id"], binding["run_id"])
                or proposal != record["proposal"] or _digest(proposal) != record["sha256"]
                or assignment.dispatch_id in dispatches):
            raise ValueError("invalid discovery proposal association")
        dispatches.add(assignment.dispatch_id)
        selected = (sorted(assignment.artifact_paths), sorted(assignment.editable_revisions))
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


class DiscoveryReservationJournal:
    """Serialize exact associations; a completed result is verified read-only."""

    def __init__(self, run_dir: Path):
        self.run_dir = Path(os.path.abspath(run_dir))
        self.path = self.run_dir / "discovery-reservations.json"
        self._root = self._lock = None
        self._data = self._binding = self._store = self._raw = None

    def __enter__(self):
        if self._root is not None:
            raise ValueError("discovery reservation journal already open")
        self._root = _open_root_directory(self.run_dir)
        try:
            self._lock = os.open("discovery-reservations.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK,
                                 0o600, dir_fd=self._root)
            info = os.fstat(self._lock)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise ValueError("unsafe discovery reservation lock")
            fcntl.flock(self._lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BaseException:
            self.__exit__()
            raise
        return self

    def __exit__(self, *args):
        for field in ("_lock", "_root"):
            descriptor = getattr(self, field)
            if descriptor is not None:
                os.close(descriptor)
                setattr(self, field, None)
        self._store = self._data = self._binding = self._raw = None

    def _check_directory(self):
        if self._root is None or self._lock is None:
            raise ValueError("discovery reservation journal is not open")
        current = _open_root_directory(self.run_dir)
        try:
            original, actual = os.fstat(self._root), os.fstat(current)
            lock = os.stat("discovery-reservations.lock", dir_fd=current, follow_symlinks=False)
            held = os.fstat(self._lock)
            if ((original.st_dev, original.st_ino) != (actual.st_dev, actual.st_ino)
                    or (lock.st_dev, lock.st_ino) != (held.st_dev, held.st_ino) or lock.st_nlink != 1):
                raise ValueError("discovery reservation directory or lock changed")
        finally:
            os.close(current)

    def _read(self):
        self._check_directory()
        try:
            descriptor = os.open(self.path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=self._root)
        except FileNotFoundError:
            return None
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > _MAX_BYTES:
                raise ValueError("unsafe discovery reservation record")
            with os.fdopen(descriptor, "rb", closefd=False) as stream:
                raw = stream.read(_MAX_BYTES + 1)
            if len(raw) > _MAX_BYTES:
                raise ValueError("discovery reservation record exceeds limit")
            return raw.decode("utf-8")
        finally:
            os.close(descriptor)

    def _save(self):
        _validate(self._data, self._binding)
        raw = _canonical({"payload": self._data, "sha256": _digest(self._data)}) + "\n"
        if len(raw.encode("utf-8")) > _MAX_BYTES:
            raise ValueError("discovery reservation record exceeds limit")
        try:
            self._check_directory()
            write_text_atomic(self.path, raw, trusted_root=self.run_dir, expected_text=self._raw)
            self._check_directory()
            self._raw = raw
        except BaseException:
            # A failed fsync/replace can leave either image: only reopen may decide.
            self._store = None
            raise

    def select(self, store, *, spec_id, run_id, operation_id, managed_identity, create=False):
        if self._store is not None or type(create) is not bool:
            raise ValueError("invalid discovery reservation selection")
        text(operation_id, "operation_id")
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
                _validate(data, binding)
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
        _validate(self._data, binding)
        for record in self._data["proposals"]:
            for intent in record["intents"]:
                retained = self._store.reservation(spec_id=binding["spec_id"], kind=intent["kind"],
                    operation_id=intent["operation_id"], count=len(intent["keys"]))
                if intent["ids"] is not None and (retained is None or list(retained) != intent["ids"]):
                    raise ValueError("completed discovery reservation differs from authority")

    def bind(self, assignment: DiscoveryAssignment, reply: dict) -> tuple[DiscoveryReservation, ...]:
        self._authenticate()
        proposal = validate_discovery_reply(reply, assignment)
        if assignment.step != "propose" or proposal["action"] != "final":
            raise ValueError("discovery reservation requires a final proposal")
        records = self._data["proposals"]
        matching = [record for record in records if record["proposal"]["dispatch_id"] == assignment.dispatch_id]
        if matching:
            record, = matching
            if record["proposal"] != proposal:
                raise ValueError("discovery dispatch proposal changed")
        else:
            if any(intent["ids"] is None for record in records for intent in record["intents"]):
                raise ValueError("previous discovery reservation must be recovered first")
            known = _validate(self._data, self._binding)
            record = dict(proposal=proposal, sha256=_digest(proposal), intents=_intents(self._binding, proposal, known))
            candidate = deepcopy(self._data)
            candidate["proposals"].append(record)
            _validate(candidate, self._binding)
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
        known = _validate(self._data, self._binding)
        return tuple(known[item["key"]][1] for item in proposal["new_subjects"])
