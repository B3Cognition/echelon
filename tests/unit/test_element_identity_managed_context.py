from contextlib import closing, contextmanager
import hashlib
import json
from pathlib import Path
import sqlite3

import pytest

from harness.element_identity_store import IdentityStore, IdentityStoreError


DATABASE = ".echelon/identity/registry.sqlite3"


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def sql_state(path):
    with closing(sqlite3.connect(path / DATABASE)) as connection:
        return tuple(connection.iterdump())


def empty_tree_manifest(path):
    from harness.squad_source_manifest_codec import decode_source_manifest

    return decode_source_manifest(canonical({
        "version": "1",
        "files": [],
        "trees": [{
            "path": path,
            "exists": "true",
            "directories": [{"path": path, "mode": "493"}],
            "files": [],
        }],
    }))


def enroll(store, *, spec="demo", run="first", context="source",
           spec_path="specs/demo", source_operation="source-registration",
           managed_operation="managed-registration"):
    from harness.element_identity_managed import ManagedIdentityRequest

    manifest = empty_tree_manifest(spec_path)
    source = store.register_source_context(
        spec_id=spec,
        context_id=context,
        operation_id=source_operation,
        manifest=manifest,
    )
    request = ManagedIdentityRequest(
        source["workspace_uuid"], source["epoch_uuid"], run, context,
        spec_path, source_operation, manifest.sha256,
    )
    genesis = store.register_managed_identity(
        spec_id=spec, operation_id=managed_operation, request=request
    )
    return genesis, source


def seed_managed(path, **kwargs):
    store = IdentityStore.initialize(path)
    genesis, source = enroll(store, **kwargs)
    return store, genesis, source


def real_advance_setup(root):
    from harness.element_identity_managed import ManagedIdentityRequest
    from harness.element_identity_publication import PublicationIntentRequest, PublicationSourceClaim
    from harness.squad_publication import SquadPublicationTransaction
    from harness.squad_source_baseline_codec import encode_initial_publication_sources
    from harness.squad_source_manifest import snapshot_source_manifest

    root = root.resolve()
    squad = root / "runs/first"
    selected = Path("runs/first/specs/demo")
    (root / selected).mkdir(parents=True)
    transaction = SquadPublicationTransaction.begin(root, squad, "8" * 32)
    stage = transaction.build_path("definition")
    stage.write_bytes(b"accepted source\r\n")
    transaction.add_write(
        selected / "definition.md",
        stage,
        owned_paths={selected / "definition.md"},
    )
    prepared = transaction.seal()
    with prepared.inspect_sources(tree_paths=(selected.as_posix(),), file_paths=()) as initial:
        manifest = snapshot_source_manifest(trees=initial.trees, files=initial.files)
        baseline = encode_initial_publication_sources(initial)
    store = IdentityStore.initialize(root)
    initial_source = store.register_source_context(
        spec_id="demo",
        context_id="first-source",
        operation_id="source-registration",
        manifest=manifest,
    )
    request = ManagedIdentityRequest(
        initial_source["workspace_uuid"], initial_source["epoch_uuid"],
        "first", "first-source", selected.as_posix(),
        "source-registration", manifest.sha256,
    )
    genesis = store.register_managed_identity(
        spec_id="demo", operation_id="managed-registration", request=request
    )
    publication = PublicationIntentRequest(
        initial.publication.marker.manifest_sha256,
        "retained source recovery",
        (),
        PublicationSourceClaim("first-source", "source-registration", baseline),
    )
    return store, genesis, initial_source, prepared, initial, publication


def apply_real_source(store, prepared, initial, publication):
    prepared.publish_sources(
        initial,
        before_publish=lambda _: store.prepare_identity_publication(
            spec_id="demo", operation_id="source-publication", request=publication
        ),
        after_publish=lambda _: store.apply_identity_publication(
            spec_id="demo", operation_id="source-publication"
        ),
    )


@pytest.fixture
def secure_posix():
    from harness.squad_publication import _secure_posix_capabilities_available

    if not _secure_posix_capabilities_available():
        pytest.skip("secure POSIX source capture unavailable")


def test_check_managed_context_uses_actual_genesis_and_initial_source(tmp_path, secure_posix):
    from harness.element_identity_managed import ManagedIdentityRequest
    from harness.element_identity_store import IdentityStore
    from harness.squad_publication import SquadPublicationTransaction
    from harness.squad_source_manifest import snapshot_source_manifest

    root = tmp_path.resolve()
    squad = root / "runs/first"
    (squad / "specs/demo").mkdir(parents=True)
    prepared = SquadPublicationTransaction.begin(root, squad, "7" * 32).seal()
    with prepared.inspect_sources(tree_paths=("runs/first/specs/demo",), file_paths=()) as initial:
        manifest = snapshot_source_manifest(trees=initial.trees, files=initial.files)
    authority = IdentityStore.initialize(root)
    initial_source = authority.register_source_context(
        spec_id="demo",
        context_id="first-source",
        operation_id="source-registration",
        manifest=manifest,
    )
    request = ManagedIdentityRequest(
        initial_source["workspace_uuid"],
        initial_source["epoch_uuid"],
        "first",
        "first-source",
        "runs/first/specs/demo",
        "source-registration",
        manifest.sha256,
    )
    genesis = authority.register_managed_identity(
        spec_id="demo", operation_id="managed-registration", request=request
    )

    observed = authority.check_managed_context(spec_id="demo", run_id="first", record=genesis)
    assert observed == {"managed_identity": genesis, "source_context": initial_source}
    assert set(observed) == {"managed_identity", "source_context"}
    assert set(observed["source_context"]) == {
        "version", "workspace_uuid", "epoch_uuid", "spec_id", "context_id",
        "registration_operation_id", "operation_id", "sequence", "manifest",
    }
    assert observed["managed_identity"] is not genesis
    assert observed["source_context"] is not initial_source
    assert observed["source_context"]["manifest"] is not initial_source["manifest"]
    observed["managed_identity"]["context_id"] = "changed"
    observed["source_context"]["manifest"]["payload"] = "changed"
    assert authority.check_managed_context(
        spec_id="demo", run_id="first", record=genesis
    ) == {"managed_identity": genesis, "source_context": initial_source}


@pytest.mark.parametrize("phase", ["initial", "prepared", "applied", "released"])
def test_check_managed_context_observes_coherent_publication_phase(
    tmp_path, secure_posix, phase
):
    store, genesis, initial_source, prepared, initial, publication = real_advance_setup(tmp_path)
    if phase == "prepared":
        store.prepare_identity_publication(
            spec_id="demo", operation_id="source-publication", request=publication
        )
    elif phase in {"applied", "released"}:
        apply_real_source(store, prepared, initial, publication)
        if phase == "released":
            store.release_identity_publication(
                spec_id="demo",
                operation_id="source-publication",
                completion_payload="source publication complete",
            )
    expected_source = store.source_context(spec_id="demo", context_id="first-source")
    before = sql_state(tmp_path)

    observed = store.check_managed_context(
        spec_id="demo", run_id="first", record=genesis
    )

    assert observed == {
        "managed_identity": genesis,
        "source_context": expected_source,
    }
    assert observed["source_context"]["sequence"] == (
        "0" if phase in {"initial", "prepared"} else "1"
    )
    assert observed["managed_identity"]["source_manifest_sha256"] == initial_source["manifest"]["sha256"]
    assert sql_state(tmp_path) == before


def test_returned_snapshot_is_detached_and_does_not_claim_future_freshness(
    tmp_path, secure_posix
):
    store, genesis, initial_source, prepared, initial, publication = real_advance_setup(tmp_path)
    old = store.check_managed_context(spec_id="demo", run_id="first", record=genesis)
    apply_real_source(store, prepared, initial, publication)
    store.release_identity_publication(
        spec_id="demo",
        operation_id="source-publication",
        completion_payload="source publication complete",
    )
    accepted = store.source_context(spec_id="demo", context_id="first-source")
    old["managed_identity"]["run_id"] = "changed"
    old["source_context"]["manifest"]["payload"] = "changed"
    (tmp_path / "runs/first/specs/demo/definition.md").write_bytes(b"physical drift")

    current = store.check_managed_context(spec_id="demo", run_id="first", record=genesis)

    assert old["source_context"]["sequence"] == "0"
    assert current == {"managed_identity": genesis, "source_context": accepted}
    assert current["source_context"]["sequence"] == "1"
    assert current["managed_identity"]["source_manifest_sha256"] == initial_source["manifest"]["sha256"]
    assert current["source_context"]["manifest"]["sha256"] != initial_source["manifest"]["sha256"]


def test_exact_old_genesis_remains_accepted_after_later_identity_history(tmp_path):
    from harness.element_identity_lifecycle import ElementCreate

    store, genesis, source = seed_managed(tmp_path)
    label, = store.reserve(spec_id="demo", kind="FR", operation_id="reserve", count=1)
    store.apply_lifecycle(
        spec_id="demo",
        operation_id="lifecycle",
        changes=(ElementCreate(label, "Feature", "Body", "reserve"),),
    )
    before = sql_state(tmp_path)

    assert store.check_managed_context(
        spec_id="demo", run_id="first", record=genesis
    ) == {"managed_identity": genesis, "source_context": source}
    assert sql_state(tmp_path) == before


def test_closed_malformed_inputs_reject_before_opening_transaction(tmp_path, monkeypatch):
    store, genesis, _ = seed_managed(tmp_path)
    invalid_records = [
        None,
        False,
        {},
        {**genesis, "extra": "value"},
        {key: value for key, value in genesis.items() if key != "context_id"},
        {**genesis, "run_id": None},
        {**genesis, "version": "2"},
    ]
    entered = []

    def forbidden(**kwargs):
        entered.append(kwargs)
        raise AssertionError("invalid input reached authority transaction")

    monkeypatch.setattr(store, "_transaction", forbidden)
    for spec_id, run_id, record in [
        *((value, "first", genesis) for value in (None, False, [], "", " ", "\ud800")),
        *(("demo", value, genesis) for value in (None, False, [], "", " ", "\ud800")),
        *(("demo", "first", value) for value in invalid_records),
    ]:
        with pytest.raises(IdentityStoreError) as error:
            store.check_managed_context(spec_id=spec_id, run_id=run_id, record=record)
        assert str(error.value) == "invalid managed identity context"
        assert error.value.__cause__ is None and error.value.__context__ is None
    assert not entered


@pytest.mark.parametrize("selection", ["spec", "run"])
def test_independently_selected_spec_and_run_must_match_record(tmp_path, selection):
    store, genesis, _ = seed_managed(tmp_path)
    before = sql_state(tmp_path)
    arguments = {
        "spec_id": "other" if selection == "spec" else "demo",
        "run_id": "second" if selection == "run" else "first",
        "record": genesis,
    }
    with pytest.raises(IdentityStoreError):
        store.check_managed_context(**arguments)
    assert sql_state(tmp_path) == before


@pytest.mark.parametrize("field", [
    "workspace_uuid", "epoch_uuid", "operation_id", "context_id", "spec_path",
    "source_registration_operation_id", "source_manifest_sha256",
])
def test_valid_but_different_genesis_claims_cannot_select_authority(tmp_path, field):
    primary = tmp_path / "primary"
    foreign = tmp_path / "foreign"
    primary.mkdir()
    foreign.mkdir()
    store, genesis, _ = seed_managed(primary)
    _, other, _ = seed_managed(
        foreign,
        context="other-source",
        spec_path="other/specs/demo",
        source_operation="other-source-registration",
        managed_operation="other-managed-registration",
    )
    forged = {**genesis, field: other[field]}
    before = sql_state(primary)

    with pytest.raises(IdentityStoreError):
        store.check_managed_context(spec_id="demo", run_id="first", record=forged)
    assert sql_state(primary) == before


def test_two_contexts_and_specs_do_not_allow_context_substitution(tmp_path):
    store = IdentityStore.initialize(tmp_path)
    first, first_source = enroll(store)
    second, second_source = enroll(
        store,
        spec="other",
        run="second",
        context="other-source",
        spec_path="specs/other",
        source_operation="other-source-registration",
        managed_operation="other-managed-registration",
    )
    forged = {
        **first,
        "context_id": second_source["context_id"],
        "spec_path": "specs/other",
        "source_registration_operation_id": second_source["registration_operation_id"],
        "source_manifest_sha256": second_source["manifest"]["sha256"],
    }

    with pytest.raises(IdentityStoreError):
        store.check_managed_context(spec_id="demo", run_id="first", record=forged)
    assert store.check_managed_context(
        spec_id="demo", run_id="first", record=first
    )["source_context"] == first_source
    assert store.check_managed_context(
        spec_id="other", run_id="second", record=second
    )["source_context"] == second_source


@pytest.mark.parametrize(
    "field",
    ["workspace_uuid", "epoch_uuid", "spec_id", "context_id", "registration_operation_id"],
)
def test_current_source_result_must_associate_with_matched_genesis(
    tmp_path, monkeypatch, field
):
    from harness import element_identity_source_store

    store, genesis, _ = seed_managed(tmp_path)
    original = element_identity_source_store.read

    def mismatched(connection, authority, spec_id, context_id):
        source = original(connection, authority, spec_id, context_id)
        return {**source, field: "different"}

    monkeypatch.setattr(element_identity_source_store, "read", mismatched)
    with pytest.raises(IdentityStoreError):
        store.check_managed_context(spec_id="demo", run_id="first", record=genesis)


@pytest.mark.parametrize(
    "authority_kind", ["missing", "legacy", "orphan", "damaged", "source-head"]
)
def test_absent_or_damaged_managed_authority_rejects_without_side_effects(
    tmp_path, authority_kind
):
    foreign = tmp_path / "foreign"
    target = tmp_path / "target"
    foreign.mkdir()
    target.mkdir()
    _, record, _ = seed_managed(foreign)
    store = IdentityStore.initialize(target)
    if authority_kind == "legacy":
        store.import_identities(
            spec_id="demo",
            operation_id="legacy-import",
            definitions=(("FR-legacy", "Legacy feature"),),
        )
    elif authority_kind == "orphan":
        with closing(sqlite3.connect(target / DATABASE)) as connection:
            connection.execute(
                "INSERT INTO operations VALUES ('orphan','managed_identity','demo','bad')"
            )
            connection.commit()
    elif authority_kind in {"damaged", "source-head"}:
        record, _ = enroll(store)
        with closing(sqlite3.connect(target / DATABASE)) as connection:
            if authority_kind == "damaged":
                connection.execute(
                    "UPDATE managed_identity_specs SET request_sha256='bad' WHERE spec_id='demo'"
                )
            else:
                connection.execute(
                    "UPDATE source_contexts SET head_publication_id='missing' WHERE spec_id='demo'"
                )
            connection.commit()
    before = sql_state(target)

    with pytest.raises(IdentityStoreError):
        store.check_managed_context(spec_id="demo", run_id="first", record=record)
    assert sql_state(target) == before


def test_structurally_valid_state_metadata_is_not_durable_authentication(tmp_path):
    from harness.squad_state import SquadStateStore

    store, genesis, _ = seed_managed(tmp_path)
    forged = {**genesis, "operation_id": "untrusted-state-operation"}
    squad = tmp_path / "runs/first"
    squad.mkdir(parents=True)
    state_store = SquadStateStore(squad)
    state_store.initialize(
        run_id="first",
        mode="greenfield",
        user_message="game",
        token_budget=1000,
        entry_phase="phase0-discovery",
        managed_identity=forged,
    )
    caller_record = state_store.load()["managed_identity"]
    before = sql_state(tmp_path)

    with pytest.raises(IdentityStoreError):
        store.check_managed_context(
            spec_id="demo", run_id="first", record=caller_record
        )
    assert sql_state(tmp_path) == before


def test_public_error_drops_untrusted_exception_context_and_preserves_baseexception(
    tmp_path, monkeypatch
):
    from harness import element_identity_state

    store, genesis, _ = seed_managed(tmp_path)
    secret = "untrusted:" + "x" * 10000

    def ordinary(_):
        raise RuntimeError(secret)

    monkeypatch.setattr(element_identity_state, "validate_managed_identity_record", ordinary)
    with pytest.raises(IdentityStoreError) as error:
        store.check_managed_context(spec_id="demo", run_id="first", record=genesis)
    assert str(error.value) == "invalid managed identity context"
    assert error.value.__cause__ is None and error.value.__context__ is None
    assert secret not in repr(error.value)

    def stopped(_):
        raise KeyboardInterrupt()

    monkeypatch.setattr(element_identity_state, "validate_managed_identity_record", stopped)
    with pytest.raises(KeyboardInterrupt):
        store.check_managed_context(spec_id="demo", run_id="first", record=genesis)


@pytest.mark.parametrize("owner", ["managed", "source"])
def test_helper_and_storage_exceptions_are_bounded_after_handler(
    tmp_path, monkeypatch, owner
):
    from harness import element_identity_managed_store, element_identity_source_store

    store, genesis, _ = seed_managed(tmp_path)
    secret = "untrusted storage detail:" + "z" * 10000

    def broken(*args, **kwargs):
        raise sqlite3.DatabaseError(secret)

    target = (
        element_identity_managed_store
        if owner == "managed"
        else element_identity_source_store
    )
    monkeypatch.setattr(target, "read", broken)
    with pytest.raises(IdentityStoreError) as error:
        store.check_managed_context(spec_id="demo", run_id="first", record=genesis)
    assert str(error.value) == "invalid managed identity context"
    assert error.value.__cause__ is None and error.value.__context__ is None
    assert secret not in repr(error.value)


def test_one_query_only_transaction_blocks_actual_write_and_preserves_rows(
    tmp_path, monkeypatch
):
    from harness import element_identity_managed_store as managed_store

    store, genesis, source = seed_managed(tmp_path)
    original_transaction = store._transaction
    original_read = managed_store.read
    transactions = []
    write_rejections = []

    @contextmanager
    def transaction(*, write=False):
        transactions.append(write)
        with original_transaction(write=write) as connection:
            yield connection
            assert connection.execute("PRAGMA query_only").fetchone()[0] == 1

    def probing_read(connection, authority, spec_id):
        try:
            connection.execute(
                "INSERT INTO operations VALUES ('forbidden','import','demo','bad')"
            )
        except sqlite3.OperationalError as error:
            write_rejections.append(str(error))
        return original_read(connection, authority, spec_id)

    before = sql_state(tmp_path)
    monkeypatch.setattr(store, "_transaction", transaction)
    monkeypatch.setattr(managed_store, "read", probing_read)

    assert store.check_managed_context(
        spec_id="demo", run_id="first", record=genesis
    ) == {"managed_identity": genesis, "source_context": source}
    assert transactions == [False]
    assert len(write_rejections) == 1
    assert sql_state(tmp_path) == before


def test_check_avoids_identity_history_and_uses_managed_source_indexes(
    tmp_path, monkeypatch
):
    from harness import element_identity_source_store as source_store
    from harness.element_identity_bindings import IssueOccurrence, ReferenceClaim
    from harness.element_identity_lifecycle import ElementCreate

    store, genesis, source = seed_managed(tmp_path)
    fr, = store.reserve(spec_id="demo", kind="FR", operation_id="reserve-fr", count=1)
    issue, = store.reserve(spec_id="demo", kind="ISS", operation_id="reserve-issue", count=1)
    store.apply_lifecycle(
        spec_id="demo",
        operation_id="life",
        changes=(
            ElementCreate(fr, "Feature", "Feature body", "reserve-fr"),
            ElementCreate(issue, "Issue", "Issue body", "reserve-issue"),
        ),
    )
    store.record_reference_claims(
        spec_id="demo",
        operation_id="refs",
        claims=(ReferenceClaim("evidence.md", "b" * 64, "anchor", fr, "1", "reference"),),
    )
    store.record_issue_occurrences(
        spec_id="demo",
        operation_id="issues",
        occurrences=(IssueOccurrence(
            issue, "1", "report", "b" * 64, "ISS-display", "Issue", "Issue body"
        ),),
    )
    original_transaction = store._transaction
    forbidden = {
        "counters", "reservations", "entities", "revisions", "lifecycle_heads",
        "lifecycle_lineage", "lifecycle_receipts", "reference_claims",
        "issue_occurrences", "binding_receipts",
    }

    @contextmanager
    def transaction(*, write=False):
        with original_transaction(write=write) as connection:
            connection.set_authorizer(
                lambda action, table, *_: sqlite3.SQLITE_DENY
                if action == sqlite3.SQLITE_READ and table in forbidden
                else sqlite3.SQLITE_OK
            )
            yield connection

    monkeypatch.setattr(store, "_transaction", transaction)
    assert store.check_managed_context(
        spec_id="demo", run_id="first", record=genesis
    ) == {"managed_identity": genesis, "source_context": source}

    with original_transaction() as connection:
        checks = (
            ("SELECT * FROM managed_identity_specs WHERE spec_id=?", ("demo",), "PRIMARY KEY"),
            ("SELECT operation_id FROM operations WHERE spec_id=? AND method='managed_identity' LIMIT 2",
             ("demo",), "managed_identity_operations"),
            ("SELECT * FROM source_contexts WHERE spec_id=? AND context_id=?",
             ("demo", "source"), "PRIMARY KEY"),
            (source_store._HEAD, ("demo", "source"), "source_publication_heads"),
        )
        for query, arguments, index in checks:
            plan = " ".join(
                row[3] for row in connection.execute("EXPLAIN QUERY PLAN " + query, arguments)
            )
            assert "SEARCH" in plan and index in plan and "SCAN" not in plan


def test_check_reads_registry_snapshot_without_opening_or_stating_source_tree(
    tmp_path, monkeypatch
):
    import builtins

    store, genesis, source = seed_managed(tmp_path)
    original_open = builtins.open
    original_path_open = Path.open
    original_stat = Path.stat

    def guarded_open(path, *args, **kwargs):
        if not isinstance(path, int) and "specs" in Path(path).parts:
            raise AssertionError("managed context checker must not open current source files")
        return original_open(path, *args, **kwargs)

    def guarded_path_open(path, *args, **kwargs):
        if "specs" in path.parts:
            raise AssertionError("managed context checker must not open current source files")
        return original_path_open(path, *args, **kwargs)

    def guarded_stat(path, *args, **kwargs):
        if "specs" in Path(path).parts:
            raise AssertionError("managed context checker must not stat current source trees")
        return original_stat(path, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(builtins, "open", guarded_open)
        patch.setattr(Path, "open", guarded_path_open)
        patch.setattr(Path, "stat", guarded_stat)
        assert store.check_managed_context(
            spec_id="demo", run_id="first", record=genesis
        ) == {"managed_identity": genesis, "source_context": source}


@pytest.mark.parametrize("missing", ["authority.json", "registry.sqlite3"])
def test_missing_authority_files_are_not_created_or_repaired(tmp_path, missing):
    store, genesis, _ = seed_managed(tmp_path)
    target = tmp_path / ".echelon/identity" / missing
    target.unlink()

    with pytest.raises(IdentityStoreError):
        store.check_managed_context(spec_id="demo", run_id="first", record=genesis)
    assert not target.exists()


@pytest.mark.parametrize("damage", ["metadata", "namespace"])
def test_changed_or_corrupt_current_authority_is_not_repaired(tmp_path, damage):
    store, genesis, _ = seed_managed(tmp_path)
    directory = tmp_path / ".echelon/identity"
    if damage == "metadata":
        with closing(sqlite3.connect(directory / "registry.sqlite3")) as connection:
            connection.execute("DELETE FROM metadata")
            connection.commit()
        target = directory / "registry.sqlite3"
    else:
        marker = json.loads((directory / "authority.json").read_text())
        marker["workspace_uuid"] = "12345678-1234-1234-1234-123456789abc"
        (directory / "authority.json").write_text(canonical(marker))
        target = directory / "authority.json"
    before = target.read_bytes()

    with pytest.raises(IdentityStoreError):
        store.check_managed_context(spec_id="demo", run_id="first", record=genesis)
    assert target.read_bytes() == before


def test_supported_old_schema_requires_explicit_upgrade_without_mutation(tmp_path):
    from tests.unit.test_element_identity_managed import freeze_v5

    store, genesis, _ = seed_managed(tmp_path)
    freeze_v5(tmp_path)
    database = tmp_path / DATABASE
    before = database.read_bytes()

    with pytest.raises(IdentityStoreError):
        store.check_managed_context(spec_id="demo", run_id="first", record=genesis)
    assert database.read_bytes() == before
