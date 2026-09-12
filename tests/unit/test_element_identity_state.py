"""Managed genesis metadata is immutable state, not routing authority."""

from copy import deepcopy
import json
from pathlib import Path

import pytest


def record():
    return {
        "version": "1",
        "workspace_uuid": "12345678-1234-1234-1234-123456789abc",
        "epoch_uuid": "23456789-2345-2345-2345-23456789abcd",
        "spec_id": "demo", "operation_id": "managed-registration",
        "run_id": "first", "context_id": "first-source",
        "spec_path": "runs/first/specs/demo",
        "source_registration_operation_id": "source-registration",
        "source_manifest_sha256": "a" * 64,
    }


def initialize(store, **kwargs):
    options = dict(run_id="first", mode="greenfield", user_message="game",
                   token_budget=1000, entry_phase="phase0-discovery")
    options.update(kwargs)
    store.initialize(**options)


def managed_store(tmp_path, **kwargs):
    from harness.squad_state import SquadStateStore
    store = SquadStateStore(tmp_path)
    initialize(store, managed_identity=record(), **kwargs)
    return store


def durable_bytes(store):
    return {path.name: path.read_bytes() for path in store._squad_dir.iterdir()
            if path.name in {"state.json", "state.json.bak"} or path.name.endswith(".tmp")}


def test_record_is_detached_exact_and_pure(monkeypatch):
    from harness.element_identity_state import validate_managed_identity_record
    import builtins
    import sqlite3
    def forbidden(*args, **kwargs):
        raise AssertionError("validator attempted I/O")
    monkeypatch.setattr(builtins, "open", forbidden)
    monkeypatch.setattr(Path, "resolve", forbidden)
    monkeypatch.setattr(sqlite3, "connect", forbidden)
    value = record()
    observed = validate_managed_identity_record(value)
    assert type(observed) is dict and observed == record() and observed is not value
    value["spec_id"] = "different"
    assert observed["spec_id"] == "demo"


@pytest.mark.parametrize("field", list(record()))
def test_record_rejects_missing_and_non_string_fields(field):
    from harness.element_identity_state import validate_managed_identity_record
    missing = record()
    del missing[field]
    for value in (missing, {**record(), field: None}, {**record(), field: False},
                  {**record(), field: 1}, {**record(), field: {"value": "x"}}):
        with pytest.raises(ValueError) as caught:
            validate_managed_identity_record(value)
        assert len(str(caught.value)) < 100
        assert caught.value.__suppress_context__ and caught.value.__cause__ is None


@pytest.mark.parametrize("field,value", [
    ("version", "2"), ("version", "01"), ("workspace_uuid", "BAD"),
    ("epoch_uuid", "23456789-2345-2345-2345-23456789ABCD"),
    ("spec_path", "../escape"), ("spec_path", "/absolute"),
    ("spec_path", "runs//first"), ("source_manifest_sha256", "A" * 64),
    ("source_manifest_sha256", "a" * 63), ("source_manifest_sha256", "a" * 65),
    ("spec_id", "  "), ("operation_id", "\x00secret"),
    ("run_id", ""), ("context_id", "\ud800"),
    ("source_registration_operation_id", ""),
])
def test_record_rejects_malformed_strings(field, value):
    from harness.element_identity_state import validate_managed_identity_record
    with pytest.raises(ValueError) as caught:
        validate_managed_identity_record({**record(), field: value})
    assert "secret" not in str(caught.value)
    assert caught.value.__suppress_context__


def test_record_rejects_hostile_containers_and_subclasses():
    from harness.element_identity_state import validate_managed_identity_record
    class HostileDict(dict):
        def __iter__(self):
            raise RuntimeError("secret")
    class HostileString(str):
        def __hash__(self):
            return hash("spec_id")
        def __eq__(self, other):
            raise RuntimeError("secret")
    for value in (None, False, {}, [], HostileDict(record()),
                  {**record(), "extra": "x"}, {**record(), "spec_id": HostileString("demo")},
                  {HostileString("spec_id"): "demo"}):
        with pytest.raises(ValueError) as caught:
            validate_managed_identity_record(value)
        assert "secret" not in str(caught.value)
        assert caught.value.__suppress_context__


def test_record_preserves_baseexception(monkeypatch):
    import harness.element_identity_state as module
    class Stop(BaseException):
        pass
    def stop(*args, **kwargs):
        raise Stop()
    monkeypatch.setattr(module, "ManagedIdentityRequest", stop)
    with pytest.raises(Stop):
        module.validate_managed_identity_record(record())


def test_record_normalizes_ordinary_failures_without_retaining_exception_context(monkeypatch):
    import harness.element_identity_state as module
    def fail(*args, **kwargs):
        raise RuntimeError("private registry claim text")
    monkeypatch.setattr(module, "ManagedIdentityRequest", fail)
    with pytest.raises(ValueError) as caught:
        module.validate_managed_identity_record(record())
    assert caught.value.__context__ is None
    assert caught.value.__cause__ is None
    assert "private" not in str(caught.value)


@pytest.mark.parametrize("invalid", [False, {}, {"version": "1"}, [], {**record(), "spec_id": "\ud800"}])
def test_invalid_initialization_record_never_creates_state_or_backup(tmp_path, invalid):
    from harness.squad_state import SquadStateStore, StateAdvanceError
    store = SquadStateStore(tmp_path)
    with pytest.raises(StateAdvanceError) as caught:
        initialize(store, managed_identity=invalid)
    assert caught.value.json_path == "$.managed_identity"
    assert durable_bytes(store) == {}


@pytest.mark.parametrize("autonomy", ["guided", "semi", "banzai"])
def test_initialize_preserves_same_run_and_rejects_rebinding(tmp_path, autonomy):
    from harness.squad_state import StateAdvanceError
    store = managed_store(tmp_path, autonomy_mode=autonomy)
    assert "feature_branch" not in store.load()
    for options in ({}, {"managed_identity": None}, {"managed_identity": record()}):
        initialize(store, autonomy_mode=autonomy, **options)
        assert store.load()["managed_identity"] == record()
        assert store.load()["spec_id"] == "demo"
        assert store.load()["autonomy_mode"] == autonomy
    before = durable_bytes(store)
    for options in ({"run_id": "next"}, {"managed_identity": {**record(), "operation_id": "new"}}):
        with pytest.raises(StateAdvanceError) as caught:
            initialize(store, autonomy_mode=autonomy, **options)
        assert caught.value.json_path == "$.managed_identity"
        assert durable_bytes(store) == before


@pytest.mark.parametrize("method", ["save", "exact", "writer"])
@pytest.mark.parametrize("change", ["remove", "replace", "run", "spec", "null", "false", "empty", "partial"])
def test_all_writes_reject_managed_changes_before_backup_or_temp(tmp_path, monkeypatch, method, change):
    import harness.squad_state as module
    store = managed_store(tmp_path)
    store.save(store.load())  # Distinct existing backup must also be preserved.
    before = store.load()
    desired = deepcopy(before)
    if change == "remove":
        del desired["managed_identity"]
    elif change == "run":
        desired["run_id"] = "next"
    elif change == "spec":
        desired["spec_id"] = "next"
    else:
        desired["managed_identity"] = {"replace": {**record(), "operation_id": "new"},
            "null": None, "false": False, "empty": {}, "partial": {"version": "1"}}[change]
    original = durable_bytes(store)
    def forbidden(*args, **kwargs):
        pytest.fail("invalid metadata reached a write")
    with monkeypatch.context() as patch:
        patch.setattr(Path, "write_text", forbidden)
        patch.setattr(module.tempfile, "mkstemp", forbidden)
        with pytest.raises(module.StateAdvanceError) as caught:
            if method == "save":
                store.save(desired)
            else:
                with store._lock(exclusive=True):
                    if method == "exact":
                        store._save_exact_state_unlocked(before, desired,
                            json_path="$.test", error_message="test save failed")
                    else:
                        store._save_unlocked(desired)
        assert caught.value.json_path == "$.managed_identity"
    assert durable_bytes(store) == original


@pytest.mark.parametrize("method", ["save", "exact", "writer"])
def test_ordinary_write_cannot_introduce_managed_field(tmp_path, method):
    from harness.squad_state import SquadStateStore, StateAdvanceError
    store = SquadStateStore(tmp_path)
    initialize(store)
    before = store.load()
    desired = {**before, "managed_identity": record(), "spec_id": "demo"}
    original = durable_bytes(store)
    with pytest.raises(StateAdvanceError) as caught:
        if method == "save":
            store.save(desired)
        else:
            with store._lock(exclusive=True):
                if method == "exact":
                    store._save_exact_state_unlocked(before, desired,
                        json_path="$.test", error_message="test save failed")
                else:
                    store._save_unlocked(desired)
    assert caught.value.json_path == "$.managed_identity"
    assert durable_bytes(store) == original
    initialize(store, managed_identity=record())
    assert store.load()["managed_identity"] == record()


def test_legacy_shape_and_supplied_run_mismatch(tmp_path):
    from harness.squad_state import SquadStateStore, StateAdvanceError
    store = SquadStateStore(tmp_path)
    initialize(store)
    assert "managed_identity" not in store.load() and "spec_id" not in store.load()
    before = durable_bytes(store)
    for run_id in ("next", None, False, 1):
        with pytest.raises(StateAdvanceError) as caught:
            initialize(store, run_id=run_id, managed_identity=record())
        assert caught.value.json_path == "$.managed_identity"
        assert durable_bytes(store) == before


@pytest.mark.parametrize("value", [None, False, {}, {"version": "1"}, {**record(), "run_id": "next"}])
def test_retained_malformed_record_cannot_be_loaded_or_stripped(tmp_path, value):
    from harness.squad_state import StateAdvanceError
    store = managed_store(tmp_path)
    desired = store.load()
    store._path.write_text(json.dumps({**desired, "managed_identity": value}))
    del desired["managed_identity"]
    before = durable_bytes(store)
    for operation in (store.load, lambda: initialize(store),
                      lambda: initialize(store, managed_identity=record()),
                      lambda: store._save_unlocked(desired)):
        with pytest.raises(StateAdvanceError) as caught:
            operation()
        assert caught.value.json_path == "$.managed_identity"
        assert durable_bytes(store) == before


def test_managed_initialize_rejects_malformed_json_without_changing_legacy_policy(tmp_path):
    from harness.squad_state import SquadStateStore, StateAdvanceError
    store = SquadStateStore(tmp_path)
    store._path.write_text('{"unknown":')
    before = durable_bytes(store)
    with pytest.raises(StateAdvanceError) as caught:
        initialize(store, managed_identity=record())
    assert caught.value.json_path == "$.managed_identity"
    assert durable_bytes(store) == before
    initialize(store)
    assert "managed_identity" not in store.load()


def prepared_route(store, **kwargs):
    from harness.phase_graph import PhaseNode
    from harness.prepared_phase_result import prepare_phase_result
    from harness.squad_provider import SquadAgentResult
    phase = store.load()["phase"]
    prepared = prepare_phase_result(
        PhaseNode(id=phase, type="agent", allowed_state_updates=[]),
        SquadAgentResult(exit_code=0, raw_output="", duration_ms=0, timed_out=False,
            echelon_result={"verdict": "DONE", "state_updates": {}}),
        controller_updates={},
    )
    return store.prepare_routing_decision(prepared,
        snapshot=store.capture_routing_snapshot(), from_phase=phase, to_phase="next", **kwargs)


def test_metadata_survives_save_exact_routing_and_reopen_without_source_lookup(tmp_path, monkeypatch):
    import sqlite3
    from harness.element_identity_store import IdentityStore
    from harness.squad_state import SquadStateStore
    store = managed_store(tmp_path)
    def forbidden(*args, **kwargs):
        pytest.fail("state metadata attempted authority access")
    monkeypatch.setattr(sqlite3, "connect", forbidden)
    monkeypatch.setattr(IdentityStore, "managed_identity", forbidden)
    monkeypatch.setattr(Path, "resolve", forbidden)
    state = store.load()
    state.update(note="ordinary update", spec_dir="a/later/export")
    store.save(state)
    before = store.load()
    desired = {**before, "note": "exact update"}
    with store._lock(exclusive=True):
        exact = store._save_exact_state_unlocked(before, desired,
            json_path="$.test", error_message="test save failed")
    assert exact["managed_identity"] == record()
    route = prepared_route(store, transaction_state_updates={"spec_dir": "relocated/spec"})
    store.advance("phase0-discovery", "next", route)
    initialize(store)
    reopened = SquadStateStore(tmp_path).load()
    assert reopened["managed_identity"] == record() and reopened["spec_id"] == "demo"


@pytest.mark.parametrize("field", ["spec_id", "run_id"])
@pytest.mark.parametrize("value", [None, False, 1, "other"])
def test_load_rejects_nonexact_state_association(tmp_path, field, value):
    from harness.squad_state import StateAdvanceError
    store = managed_store(tmp_path)
    state = store.load()
    state[field] = value
    store._path.write_text(json.dumps(state))
    before = durable_bytes(store)
    with pytest.raises(StateAdvanceError) as caught:
        store.load()
    assert caught.value.json_path == "$.managed_identity"
    assert durable_bytes(store) == before


@pytest.mark.parametrize("effect", ["queue", "trusted_update", "trusted_removal", "spec_change", "spec_removal"])
def test_real_routing_cannot_change_managed_metadata(tmp_path, effect):
    from harness.controller_state_contracts import ControllerStateContractViolation
    from harness.squad_state import StateAdvanceError
    store = managed_store(tmp_path)
    before = durable_bytes(store)
    options = {
        "queue": {"queued_state_updates": {"managed_identity": record()}},
        "trusted_update": {"transaction_state_updates": {"managed_identity": record()}},
        "trusted_removal": {"transaction_state_removals": {"managed_identity"}},
        "spec_change": {"transaction_state_updates": {"spec_id": "other"}},
        "spec_removal": {"transaction_state_removals": {"spec_id"}},
    }
    with pytest.raises((StateAdvanceError, ControllerStateContractViolation)):
        route = prepared_route(store, **options[effect])
        store.advance("phase0-discovery", "next", route)
    assert durable_bytes(store) == before


@pytest.mark.parametrize("change", ["remove", "introduce", "replace"])
def test_snapshot_recovery_owner_cannot_mutate_metadata(tmp_path, change):
    from harness.squad_state import SquadStateStore, StateAdvanceError
    store = SquadStateStore(tmp_path)
    initialize(store, **({} if change == "introduce" else {"managed_identity": record()}))
    snapshot = store.capture_routing_snapshot()
    desired = snapshot.state
    if change == "remove":
        del desired["managed_identity"]
    else:
        desired.update(managed_identity={**record(), "operation_id": "other"}, spec_id="demo")
    before = durable_bytes(store)
    with pytest.raises(StateAdvanceError) as caught:
        store.commit_routing_snapshot_state(snapshot, desired)
    assert caught.value.json_path == "$.managed_identity"
    assert durable_bytes(store) == before


@pytest.mark.parametrize("stage", ["pre_replace", "post_replace"])
def test_real_save_fault_retains_exact_genesis(tmp_path, monkeypatch, stage):
    import errno
    import os
    import stat
    import harness.squad_state as module
    store = managed_store(tmp_path)
    before = store.load()
    original = store._path.read_bytes()
    desired = {**before, "note": "written"}
    real_fsync = os.fsync
    def fail_sync(fd):
        is_dir = stat.S_ISDIR(os.fstat(fd).st_mode)
        if is_dir == (stage == "post_replace"):
            raise OSError(errno.EIO, "injected sync failure")
        real_fsync(fd)
    with monkeypatch.context() as patch:
        patch.setattr(module.os, "fsync", fail_sync)
        expected_error = module.StateDurabilityError if stage == "post_replace" else module.StateAdvanceError
        with pytest.raises(expected_error) as caught:
            with store._lock(exclusive=True):
                store._save_exact_state_unlocked(before, desired,
                    json_path="$.test", error_message="test save failed")
    if stage == "post_replace":
        assert caught.value.stage == "post_replace"
    else:
        assert caught.value.validator == "save"
        assert store._path.read_bytes() == original
    reopened = module.SquadStateStore(tmp_path).load()
    assert reopened["managed_identity"] == record()
    assert (reopened.get("note") == "written") == (stage == "post_replace")
    assert not list(tmp_path.glob(".state-*.tmp"))


def test_exact_save_readback_after_replace_retains_metadata(tmp_path, monkeypatch):
    import os
    import harness.squad_state as module
    store = managed_store(tmp_path)
    before = store.load()
    real_replace = os.replace
    def replace_then_raise(*args):
        real_replace(*args)
        raise OSError("injected after replacement")
    monkeypatch.setattr(module.os, "replace", replace_then_raise)
    with store._lock(exclusive=True):
        observed = store._save_exact_state_unlocked(before, {**before, "note": "exact"},
            json_path="$.test", error_message="test save failed")
    assert observed["managed_identity"] == record()
    assert observed["note"] == "exact"
    assert store.load() == observed


def test_two_writers_from_one_revision_cannot_overwrite_or_reset_identity(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from harness.squad_state import SquadStateStore, StateAdvanceError
    store = managed_store(tmp_path)
    baseline = store.load()
    barrier = Barrier(2)
    def write(note):
        writer = SquadStateStore(tmp_path)
        desired = {**baseline, "note": note}
        barrier.wait(timeout=5)
        try:
            writer.save(desired)
            return "saved"
        except StateAdvanceError as error:
            return error.validator
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(write, note) for note in ("one", "two")]
        assert sorted(f.result(timeout=10) for f in futures) == ["saved", "stale_state"]
    final = store.load()
    assert final["managed_identity"] == record() and final["run_id"] == "first"
    with pytest.raises(StateAdvanceError):
        store.save({**baseline, "run_id": "replacement"})
    assert store.load() == final


def test_initializer_selects_preserved_metadata_only_under_its_exclusive_lock(tmp_path, monkeypatch):
    from contextlib import contextmanager
    from harness.squad_state import SquadStateStore
    store = SquadStateStore(tmp_path)
    initialize(store)
    original_lock = store._lock
    entered = []
    @contextmanager
    def locked(*, exclusive):
        # Another owner initializes immediately before this caller acquires
        # its lock: a pre-lock preservation read would lose this record.
        assert not entered
        entered.append(exclusive)
        competing = SquadStateStore(tmp_path)
        initialize(competing, managed_identity=record())
        with original_lock(exclusive=exclusive):
            yield
    with monkeypatch.context() as patch:
        patch.setattr(store, "_lock", locked)
        initialize(store)
    assert entered == [True]
    assert store.load()["managed_identity"] == record()


@pytest.fixture
def secure_posix():
    from harness.squad_publication import _secure_posix_capabilities_available
    if not _secure_posix_capabilities_available():
        pytest.skip("secure POSIX source capture unavailable")


def test_initialize_accepts_real_managed_genesis(tmp_path, secure_posix):
    from harness.element_identity_store import IdentityStore
    from harness.element_identity_managed import ManagedIdentityRequest
    from harness.squad_publication import SquadPublicationTransaction
    from harness.squad_source_manifest import snapshot_source_manifest
    from harness.squad_state import SquadStateStore
    root = tmp_path.resolve()
    squad = root / "runs/first"
    (squad / "specs/demo").mkdir(parents=True)
    prepared = SquadPublicationTransaction.begin(root, squad, "7" * 32).seal()
    with prepared.inspect_sources(tree_paths=("runs/first/specs/demo",), file_paths=()) as initial:
        manifest = snapshot_source_manifest(trees=initial.trees, files=initial.files)
    authority = IdentityStore.initialize(root)
    source = authority.register_source_context(spec_id="demo", context_id="first-source",
        operation_id="source-registration", manifest=manifest)
    request = ManagedIdentityRequest(source["workspace_uuid"], source["epoch_uuid"],
        "first", "first-source", "runs/first/specs/demo", "source-registration", manifest.sha256)
    genesis = authority.register_managed_identity(spec_id="demo", operation_id="managed-registration",
        request=request)
    state = SquadStateStore(squad)
    state.initialize(run_id="first", mode="greenfield", user_message="game", token_budget=1000,
        entry_phase="phase0-discovery", managed_identity=genesis)
    assert state.load()["managed_identity"] == genesis
    assert state.load()["spec_id"] == "demo"
    assert authority.managed_identity(spec_id="demo") == genesis
