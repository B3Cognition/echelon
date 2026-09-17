"""Negative ownership queries and the legacy admission adapter stay read-only."""

from contextlib import closing, contextmanager
import json
from pathlib import Path
import sqlite3

import pytest

from harness.element_identity_legacy_guard import require_legacy_identity_execution
from harness.element_identity_managed import ManagedIdentityRequest
from harness.element_identity_store import IdentityStore, IdentityStoreError
from harness.squad_source_manifest_codec import decode_source_manifest


BLOCKED = "identity authority does not permit legacy execution"
DATABASE = ".echelon/identity/registry.sqlite3"


def sql_state(root):
    with closing(sqlite3.connect(root / DATABASE)) as connection:
        return tuple(connection.iterdump())


def enroll(store, *, spec="demo", run="first"):
    selected = f"runs/{run}/specs/{spec}"
    manifest = decode_source_manifest(json.dumps({
        "version": "1", "files": [], "trees": [{
            "path": selected, "exists": "true",
            "directories": [{"path": selected, "mode": "493"}], "files": [],
        }],
    }, sort_keys=True, separators=(",", ":")))
    source = store.register_source_context(
        spec_id=spec, context_id="source", operation_id=f"source-{spec}", manifest=manifest,
    )
    return store.register_managed_identity(
        spec_id=spec, operation_id=f"managed-{spec}", request=ManagedIdentityRequest(
            source["workspace_uuid"], source["epoch_uuid"], run, "source", selected,
            f"source-{spec}", manifest.sha256,
        ),
    )


def unchanged_error(action, *, message=BLOCKED):
    with pytest.raises(IdentityStoreError) as raised:
        action()
    assert str(raised.value) == message
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None


@pytest.mark.parametrize("spec,runs,blocked", [
    (None, ("legacy",), False), ("legacy", ("legacy",), False),
    ("demo", ("later",), True), (None, ("first",), True),
    (None, ("physical", "first"), True), ("legacy", ("first", "declared"), True),
    (" demo ", (" first ",), False),
])
def test_query_checks_spec_and_every_exact_run_without_writing(tmp_path, spec, runs, blocked):
    store = IdentityStore.initialize(tmp_path)
    enroll(store)
    enroll(store, spec="another", run="another-run")
    before = sql_state(tmp_path)
    for handle in (store, IdentityStore.open(tmp_path)):
        action = lambda: handle.require_unmanaged_execution(spec_id=spec, run_ids=runs)
        if blocked:
            unchanged_error(action, message="invalid unmanaged execution authority or request")
        else:
            assert action() is None
        assert sql_state(tmp_path) == before


@pytest.mark.parametrize("damage,spec,runs", [
    ("DELETE FROM managed_identity_specs", "legacy", ("legacy",)),
    ("UPDATE managed_identity_specs SET request='{}',request_sha256='bad'", "demo", ("later",)),
    ("UPDATE managed_identity_specs SET request='{}',request_sha256='bad'", None, ("first",)),
    ("UPDATE source_contexts SET manifest='broken'", "demo", ("later",)),
    ("INSERT INTO operations VALUES ('orphan','managed_identity','other','bad')", None, ("legacy",)),
])
def test_retained_damaged_matching_owner_and_orphan_registration_refuse(tmp_path, damage, spec, runs):
    store = IdentityStore.initialize(tmp_path)
    enroll(store)
    with closing(sqlite3.connect(tmp_path / DATABASE)) as connection:
        connection.execute(damage)
        connection.commit()
    before = sql_state(tmp_path)
    for handle in (store, IdentityStore.open(tmp_path)):
        unchanged_error(lambda: handle.require_unmanaged_execution(spec_id=spec, run_ids=runs),
                        message="invalid unmanaged execution authority or request")
    assert sql_state(tmp_path) == before


class StringSubclass(str):
    pass


class TupleSubclass(tuple):
    pass


@pytest.mark.parametrize("spec,runs", [
    (1, ("run",)), (False, ("run",)), ("", ("run",)), (" ", ("run",)),
    ("bad\x00", ("run",)), ("\ud800", ("run",)), (StringSubclass("demo"), ("run",)),
    (None, []), (None, ["run"]), (None, "run"), (None, ()),
    (None, TupleSubclass(("run",))), (None, ("run", "run")),
    (None, (1,)), (None, (False,)), (None, (None,)), (None, ("",)),
    (None, (" ",)), (None, ("bad\x00",)), (None, ("\ud800",)),
    (None, (StringSubclass("run"),)),
])
def test_invalid_identifiers_refuse_before_transaction(tmp_path, monkeypatch, spec, runs):
    store = IdentityStore.initialize(tmp_path)
    transactions = []
    def unexpected(**kwargs):
        transactions.append(kwargs)
        raise AssertionError("invalid identifiers entered a transaction")
    monkeypatch.setattr(store, "_transaction", unexpected)
    unchanged_error(lambda: store.require_unmanaged_execution(spec_id=spec, run_ids=runs),
                    message="invalid unmanaged execution authority or request")
    assert transactions == []


def test_no_artificial_identifier_or_tuple_width_cap(tmp_path):
    store = IdentityStore.initialize(tmp_path)
    assert store.require_unmanaged_execution(
        spec_id="s" * 10000, run_ids=tuple(f"run-{i}" for i in range(1100)),
    ) is None


def test_one_query_only_transaction_uses_owner_indexes_without_child_history(tmp_path, monkeypatch):
    import harness.element_identity_store as module

    store = IdentityStore.initialize(tmp_path)
    enroll(store)
    before = sql_state(tmp_path)
    original = module._database
    statements, reads = [], []
    allowed = {"sqlite_master", "metadata", "managed_identity_specs", "operations"}
    def authorize(action, table, *args):
        if action == sqlite3.SQLITE_READ:
            reads.append(table)
            if table not in allowed:
                return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK
    @contextmanager
    def observed(path):
        with original(path) as connection:
            connection.set_trace_callback(statements.append)
            connection.set_authorizer(authorize)
            yield connection
    monkeypatch.setattr(module, "_database", observed)
    assert store.require_unmanaged_execution(spec_id="legacy", run_ids=("physical", "declared")) is None
    assert statements.count("BEGIN") == 1
    assert statements.count("COMMIT") == 1
    assert statements.count("PRAGMA query_only=ON") == 1
    assert not any(s.startswith(("INSERT", "UPDATE", "DELETE", "REPLACE")) for s in statements)
    assert set(reads) <= allowed
    queries = [s for s in statements if s.startswith("SELECT 1 FROM")]
    assert len(queries) == 4
    assert statements.index("PRAGMA query_only=ON") < statements.index(queries[0])
    with closing(sqlite3.connect(tmp_path / DATABASE)) as connection:
        plans = [" ".join(row[3] for row in connection.execute("EXPLAIN QUERY PLAN " + query))
                 for query in queries]
    assert "SEARCH" in plans[0] and "PRIMARY KEY" in plans[0]
    assert all("SEARCH" in plan and "run_id=?" in plan and "SCAN" not in plan for plan in plans[1:3])
    assert "managed_identity_operations" in plans[3] and "SEARCH managed" in plans[3]
    assert sql_state(tmp_path) == before


@pytest.mark.parametrize("exception", [RuntimeError("private payload"), KeyboardInterrupt(), SystemExit()])
def test_query_bounds_ordinary_failures_and_propagates_process_control(tmp_path, monkeypatch, exception):
    store = IdentityStore.initialize(tmp_path)
    @contextmanager
    def failing(**kwargs):
        raise exception
        yield
    monkeypatch.setattr(store, "_transaction", failing)
    action = lambda: store.require_unmanaged_execution(spec_id=None, run_ids=("run",))
    if isinstance(exception, Exception):
        unchanged_error(action, message="invalid unmanaged execution authority or request")
    else:
        with pytest.raises(type(exception)):
            action()


def guard(root, state, *, run="legacy"):
    return require_legacy_identity_execution(project_root=root, run_dir=root / "runs" / run, state=state)


@pytest.mark.parametrize("parent_present", [False, True])
def test_absent_authority_preserves_old_state_without_initialization_or_markdown_io(tmp_path, monkeypatch, parent_present):
    if parent_present:
        (tmp_path / ".echelon").mkdir()
    def unexpected(*args, **kwargs):
        pytest.fail("absent authority must not open, initialize, or read Markdown")
    monkeypatch.setattr(IdentityStore, "open", unexpected)
    monkeypatch.setattr(IdentityStore, "initialize", unexpected)
    monkeypatch.setattr(Path, "read_text", unexpected)
    assert guard(tmp_path, {"run_id": 7, "spec_id": [], "unrelated": object()}) is None
    assert list(tmp_path.iterdir()) == ([tmp_path / ".echelon"] if parent_present else [])
    assert not (tmp_path / ".echelon/identity").exists()


@pytest.mark.parametrize("record", [None, False, {}, "", "untrusted", {"run_id": "unrelated"}])
@pytest.mark.parametrize("key", ["managed_identity", "managed_discovery_bootstrap", "managed_discovery_turns", "managed_discovery_operation"])
def test_any_present_managed_key_refuses_without_authority(tmp_path, record, key):
    unchanged_error(lambda: guard(tmp_path, {key: record}))
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("state", [None, [], {"run_id": 0}, {"run_id": False}, {"run_id": " "},
    {"run_id": "\ud800"}, {"run_id": StringSubclass("")}, {"spec_id": False},
    {"spec_id": "\x00"}, {"spec_id": StringSubclass("demo")}])
def test_existing_authority_rejects_invalid_claims(tmp_path, state):
    IdentityStore.initialize(tmp_path)
    before = sql_state(tmp_path)
    unchanged_error(lambda: guard(tmp_path, state))
    assert sql_state(tmp_path) == before


@pytest.mark.parametrize("state,run,blocked", [
    ({}, "first", True), ({"run_id": "changed", "spec_id": "changed"}, "first", True),
    ({"run_id": "first"}, "legacy", True), ({"spec_id": "demo"}, "later", True),
    ({"run_id": "legacy", "spec_id": "legacy"}, "legacy", False),
    ({"run_id": None, "spec_id": None}, "legacy", False),
    ({"run_id": "", "spec_id": ""}, "legacy", False),
])
def test_removed_metadata_still_checks_physical_declared_run_and_spec(tmp_path, state, run, blocked):
    store = IdentityStore.initialize(tmp_path)
    enroll(store)
    before = sql_state(tmp_path)
    if blocked:
        unchanged_error(lambda: guard(tmp_path, state, run=run))
    else:
        assert guard(tmp_path, state, run=run) is None
    assert sql_state(tmp_path) == before


def filesystem_state(root):
    return {str(path.relative_to(root)): (
        path.lstat().st_mode,
        str(path.readlink()) if path.is_symlink() else path.read_bytes() if path.is_file() else None,
    ) for path in root.rglob("*")}


@pytest.mark.parametrize("damage", ["directory", "missing-marker", "missing-db", "marker", "schema", "file", "symlink", "dangling"])
def test_present_invalid_authority_never_falls_back_or_repairs(tmp_path, damage):
    root = tmp_path.resolve()
    authority = root / ".echelon/identity"
    if damage in {"missing-marker", "missing-db", "marker", "schema"}:
        IdentityStore.initialize(root)
        if damage == "missing-marker":
            (authority / "authority.json").unlink()
        elif damage == "missing-db":
            (authority / "registry.sqlite3").unlink()
        elif damage == "marker":
            (authority / "authority.json").write_text("{}")
        else:
            with closing(sqlite3.connect(root / DATABASE)) as connection:
                connection.execute("DROP TABLE managed_identity_specs")
                connection.commit()
    else:
        authority.parent.mkdir()
        if damage == "directory":
            authority.mkdir()
        elif damage == "file":
            authority.write_bytes(b"not an authority")
        else:
            target = root / "target"
            if damage == "symlink":
                target.mkdir()
            authority.symlink_to(target, target_is_directory=True)
    before = filesystem_state(root)
    unchanged_error(lambda: guard(root, {}))
    assert filesystem_state(root) == before


@pytest.mark.parametrize("exception", [PermissionError("private path"), KeyboardInterrupt(), SystemExit()])
def test_presence_errors_are_bounded_except_process_control(tmp_path, monkeypatch, exception):
    def failing(*args):
        raise exception
    monkeypatch.setattr(Path, "lstat", failing)
    if isinstance(exception, Exception):
        unchanged_error(lambda: guard(tmp_path, {}))
    else:
        with pytest.raises(type(exception)):
            guard(tmp_path, {})


@pytest.mark.parametrize("parent", ["dangling", "symlink", "file"])
def test_present_invalid_authority_parent_is_not_absence(tmp_path, parent):
    echelon = tmp_path / ".echelon"
    if parent == "file":
        echelon.write_bytes(b"not a directory")
    else:
        target = tmp_path / "target"
        if parent == "symlink":
            target.mkdir()
        echelon.symlink_to(target, target_is_directory=True)
    before = filesystem_state(tmp_path)
    unchanged_error(lambda: guard(tmp_path, {}))
    assert filesystem_state(tmp_path) == before


def test_nonselected_damaged_payload_is_not_a_full_authority_audit(tmp_path):
    store = IdentityStore.initialize(tmp_path)
    enroll(store)
    with closing(sqlite3.connect(tmp_path / DATABASE)) as connection:
        connection.execute("UPDATE managed_identity_specs SET request='damaged'")
        connection.commit()
    before = sql_state(tmp_path)
    assert guard(tmp_path, {"spec_id": "legacy"}) is None
    assert sql_state(tmp_path) == before


def test_sql_failure_is_bounded_without_nested_error_or_writes(tmp_path, monkeypatch):
    import harness.element_identity_store as module

    store = IdentityStore.initialize(tmp_path)
    before = sql_state(tmp_path)
    original = module._database
    denied = []
    @contextmanager
    def inaccessible(path):
        with original(path) as connection:
            def authorize(action, table, *args):
                if action == sqlite3.SQLITE_READ and table == "managed_identity_specs":
                    denied.append(table)
                    return sqlite3.SQLITE_DENY
                return sqlite3.SQLITE_OK
            connection.set_authorizer(authorize)
            yield connection
    monkeypatch.setattr(module, "_database", inaccessible)
    unchanged_error(lambda: store.require_unmanaged_execution(spec_id=None, run_ids=("legacy",)),
                    message="invalid unmanaged execution authority or request")
    assert denied
    assert sql_state(tmp_path) == before


def test_exact_state_dict_required_even_without_authority(tmp_path):
    class StateSubclass(dict):
        pass
    unchanged_error(lambda: guard(tmp_path, StateSubclass()))
    assert list(tmp_path.iterdir()) == []
