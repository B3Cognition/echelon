"""Fresh discovery enrollment uses the real state and identity owners."""
from copy import deepcopy
from contextlib import closing
import json
from pathlib import Path
import sqlite3

import pytest

from harness.squad_state import SquadStateStore, StateAdvanceError
from harness.element_identity_store import IdentityStore, IdentityStoreError
from harness.element_identity_legacy_guard import require_legacy_identity_execution
from harness.squad_publication import SquadPublicationTransaction


KEY = "managed_discovery_bootstrap"


@pytest.fixture
def case(tmp_path):
    root = tmp_path.resolve()
    run = root / "runs/first"
    state = SquadStateStore(run)
    state.initialize(run_id="first", mode="greenfield", user_message="Create an isometric game",
                     token_budget=100000, entry_phase="phase1-discover", autonomy_mode="banzai")
    store = IdentityStore.initialize(root)
    (root / "specs/game").mkdir(parents=True)
    marker = SquadPublicationTransaction.begin(root, run, "6" * 32).seal().marker.to_dict()
    authority = store.audit()["authority"]
    selection = dict(spec_id="game", run_id="first", operation_id="discovery", project_root=str(root),
        run_dir=str(run), spec_path="specs/game", workspace_uuid=authority["workspace_uuid"],
        epoch_uuid=authority["epoch_uuid"], capture_marker=marker)
    return root, state, store, selection


def sql_rows(root):
    with closing(sqlite3.connect(root / ".echelon/identity/registry.sqlite3")) as connection:
        return tuple(connection.iterdump())


def capture(case):
    from harness.squad_publication import load_prepared_publication
    from harness.squad_source_manifest import snapshot_source_manifest
    root, state, _, selection = case
    prepared = load_prepared_publication(root, state.squad_dir, selection["capture_marker"])
    with prepared.inspect_sources(tree_paths=("specs/game",), file_paths=()) as initial:
        return snapshot_source_manifest(trees=initial.trees, files=initial.files)


def test_owned_selection_is_durable_and_exact_retry_preserves_revision(case):
    root, state, _, selection = case
    before = state.load()
    selected = state.prepare_discovery_bootstrap(selection)
    assert selected[KEY] == {"schema_version": 1, "selection": selection, "source_manifest": None}
    assert selected["spec_id"] == "game"
    assert state.load() == selected
    assert state.prepare_discovery_bootstrap(selection) == selected
    for key in ("token_usage", "autonomy_mode", "iteration", "last_dispatch", "phase_dispatch_counts"):
        assert selected[key] == before[key]
    with pytest.raises(IdentityStoreError):
        require_legacy_identity_execution(project_root=root, run_dir=state.squad_dir, state=selected)


def test_generic_save_cannot_inject_bootstrap_metadata(case):
    _, state, _, selection = case
    candidate = state.load()
    candidate["spec_id"] = "game"
    candidate[KEY] = dict(schema_version=1, selection=selection, source_manifest=None)
    before = state.load()
    with pytest.raises(StateAdvanceError):
        state.save(candidate)
    assert state.load() == before


@pytest.mark.parametrize("damage", ["remove", "operation", "run", "source", "reset"])
def test_normal_state_writers_cannot_change_bootstrap_selection(case, damage):
    _, state, _, selection = case
    before = state.prepare_discovery_bootstrap(selection)
    candidate = deepcopy(before)
    with pytest.raises(StateAdvanceError):
        if damage == "reset":
            state.initialize(run_id="first", mode="greenfield", user_message="reset",
                             token_budget=100000, entry_phase="phase1-discover")
        else:
            if damage == "remove": del candidate[KEY]
            if damage == "operation": candidate[KEY]["selection"]["operation_id"] = "other"
            if damage == "run": candidate["run_id"] = "other"
            if damage == "source": candidate[KEY]["source_manifest"] = capture(case).payload
            state.save(candidate)
    assert state.load() == before


def test_source_capture_is_single_assignment_and_genesis_requires_it(case):
    _, state, _, selection = case
    before = state.prepare_discovery_bootstrap(selection)
    with pytest.raises(StateAdvanceError):
        state.complete_discovery_bootstrap(selection, {})
    assert state.load() == before
    manifest = capture(case)
    saved = state.capture_discovery_bootstrap(selection, manifest.payload)
    assert saved[KEY]["source_manifest"] == manifest.payload
    assert state.capture_discovery_bootstrap(selection, manifest.payload) == saved
    with pytest.raises(StateAdvanceError):
        state.capture_discovery_bootstrap(selection, manifest.payload + " ")
    assert state.load() == saved


@pytest.mark.parametrize("value", [None, {}, {"schema_version": True}, "untrusted"])
def test_malformed_bootstrap_state_fails_load_and_legacy_admission(case, value):
    root, state, _, _ = case
    supplied = state.load()
    supplied[KEY] = value
    (state.squad_dir / "state.json").write_text(json.dumps(supplied))
    with pytest.raises(StateAdvanceError):
        state.load()
    with pytest.raises(IdentityStoreError):
        require_legacy_identity_execution(project_root=root, run_dir=state.squad_dir, state=supplied)


@pytest.mark.parametrize("override", [dict(run_id="other"), dict(spec_id=""), dict(spec_path="../escape"),
    dict(workspace_uuid="bad"), dict(capture_marker={}), dict(extra=True)])
def test_invalid_selection_cannot_change_state(case, override):
    root, state, _, selection = case
    before = state.load()
    db = sql_rows(root)
    with pytest.raises(StateAdvanceError):
        state.prepare_discovery_bootstrap({**selection, **override})
    assert state.load() == before
    assert sql_rows(root) == db


def bootstrap(case, *, create=False, **overrides):
    from harness.discovery_bootstrap import bootstrap_discovery
    from echelon.spec_lifecycle import PhaseAExecutionLock, SpecRunExecutionLock
    root, state, _, selection = case
    request = {key: selection[key] for key in ("spec_id", "run_id", "operation_id", "spec_path", "capture_marker")}
    with PhaseAExecutionLock.acquire(root, "bootstrap-test"):
        with SpecRunExecutionLock.acquire(state.squad_dir, "bootstrap-test"):
            return bootstrap_discovery(root, state, **(request | overrides), create=create)


def test_fresh_enrollment_is_durable_before_real_reservations(case):
    from harness.discovery_reservations import DiscoveryReservationJournal
    from harness.discovery_semantics import DiscoveryAssignment
    root, state, store, _ = case
    before = state.load()
    record = bootstrap(case, create=True)
    assert state.load()["managed_identity"] == record
    assert store.managed_identity(spec_id="game") == record
    db = sql_rows(root)
    completed = state.load()
    assert bootstrap(case) == record
    assert state.load() == completed
    assert sql_rows(root) == db
    for key in ("autonomy_mode", "token_usage", "iteration", "phase_dispatch_counts"):
        assert completed[key] == before[key]
    assert list((root / "specs/game").iterdir()) == []
    with closing(sqlite3.connect(root / ".echelon/identity/registry.sqlite3")) as connection:
        assert dict(connection.execute("SELECT method,COUNT(*) FROM operations GROUP BY method")) == {
            "source_context": 1, "managed_identity": 1}
        assert connection.execute("SELECT COUNT(*) FROM reservations").fetchone() == (0,)
    assignment = DiscoveryAssignment("discovery", "proposal", "game", "first", "propose", "a" * 64, ("unknowns.md",))
    proposal = {**assignment.identity(), "action": "final", "new_subjects": [
        dict(key="camera", kind="U", subject="camera-subject", caption="Camera choice")], "revisions": []}
    with DiscoveryReservationJournal(state.squad_dir) as journal:
        journal.select(store, spec_id="game", run_id="first", operation_id="discovery", managed_identity=record, create=True)
        assert journal.bind(assignment, proposal)[0].element_id == "U-000001"
    with DiscoveryReservationJournal(state.squad_dir) as journal:
        journal.select(store, spec_id="game", run_id="first", operation_id="discovery", managed_identity=record)
        assert journal.bind(assignment, proposal)[0].element_id == "U-000001"


class Interrupted(BaseException):
    pass


@pytest.mark.parametrize("method", ["register_source_context", "register_managed_identity"])
@pytest.mark.parametrize("when", ["before", "after"])
def test_registration_interruptions_reuse_durable_selection(case, monkeypatch, method, when):
    root, state, store, _ = case
    original = getattr(IdentityStore, method)
    def interrupted(self, **kwargs):
        saved = state.load()
        assert saved[KEY]["source_manifest"] is not None
        with pytest.raises(IdentityStoreError):
            require_legacy_identity_execution(project_root=root, run_dir=state.squad_dir, state=saved)
        if when == "before":
            raise Interrupted()
        original(self, **kwargs)
        raise Interrupted()
    with monkeypatch.context() as patch:
        patch.setattr(IdentityStore, method, interrupted)
        with pytest.raises(Interrupted):
            bootstrap(case, create=True)
    selection = deepcopy(state.load()[KEY])
    result = bootstrap(case)
    assert state.load()[KEY] == selection
    assert result == store.managed_identity(spec_id="game")
    with closing(sqlite3.connect(root / ".echelon/identity/registry.sqlite3")) as connection:
        assert dict(connection.execute("SELECT method,COUNT(*) FROM operations GROUP BY method")) == {
            "source_context": 1, "managed_identity": 1}


@pytest.mark.parametrize("stage", ["prepare", "capture", "complete"])
@pytest.mark.parametrize("when", ["before", "after"])
def test_state_persistence_interruptions_do_not_duplicate_enrollment(case, monkeypatch, stage, when):
    root, state, store, _ = case
    save = state._save_unlocked
    def interrupted(value, **kwargs):
        current = "complete" if "managed_identity" in value else (
            "capture" if value.get(KEY, {}).get("source_manifest") is not None else "prepare")
        if current == stage and when == "before":
            raise Interrupted()
        result = save(value, **kwargs)
        if current == stage:
            raise Interrupted()
        return result
    with monkeypatch.context() as patch:
        patch.setattr(state, "_save_unlocked", interrupted)
        with pytest.raises(Interrupted):
            bootstrap(case, create=True)
    if stage == "prepare" and when == "before":
        with pytest.raises(ValueError):
            bootstrap(case)  # No durable selection is not permission to initialize.
        result = bootstrap(case, create=True)
    else:
        result = bootstrap(case)
    assert state.load()["managed_identity"] == store.managed_identity(spec_id="game") == result
    with closing(sqlite3.connect(root / ".echelon/identity/registry.sqlite3")) as connection:
        assert dict(connection.execute("SELECT method,COUNT(*) FROM operations GROUP BY method")) == {
            "source_context": 1, "managed_identity": 1}


@pytest.mark.parametrize("override", [dict(spec_id="other"), dict(run_id="other"), dict(operation_id="other"),
    dict(spec_path="specs/other"), dict(capture_marker={"schema_version": 1, "transaction_id": "7" * 32, "manifest_sha256": "b" * 64})])
def test_resume_requires_exact_independent_selection(case, override):
    root, state, _, _ = case
    bootstrap(case, create=True)
    before, db = state.load(), sql_rows(root)
    with pytest.raises(ValueError):
        bootstrap(case, **override)
    assert state.load() == before
    assert sql_rows(root) == db


@pytest.mark.parametrize("damage", ["missing", "file", "directory"])
def test_nonempty_or_missing_spec_cannot_enroll(case, damage):
    root, _, store, _ = case
    selected = root / "specs/game"
    if damage == "missing": selected.rmdir()
    if damage == "file": (selected / "existing.md").write_text("Retained evidence for U-001")
    if damage == "directory": (selected / "nested").mkdir()
    before = sql_rows(root)
    with pytest.raises(ValueError):
        bootstrap(case, create=True)
    assert sql_rows(root) == before
    assert store.managed_identity(spec_id="game") is None


def test_completed_genesis_is_not_rebuilt_when_database_receipt_is_missing(case):
    root, state, _, _ = case
    bootstrap(case, create=True)
    with closing(sqlite3.connect(root / ".echelon/identity/registry.sqlite3")) as connection:
        connection.execute("DELETE FROM managed_identity_specs")
        connection.execute("DELETE FROM operations WHERE method='managed_identity'")
        connection.commit()
    before = sql_rows(root)
    with pytest.raises(ValueError):
        bootstrap(case)
    assert sql_rows(root) == before
    assert "managed_identity" in state.load()


def test_existing_allocation_prevents_fresh_genesis(case):
    root, _, store, _ = case
    store.reserve(spec_id="game", kind="U", operation_id="old", count=1)
    with pytest.raises(ValueError):
        bootstrap(case, create=True)
    assert store.managed_identity(spec_id="game") is None
    assert store.reservation(spec_id="game", kind="U", operation_id="old", count=1) == ("U-000001",)


@pytest.mark.parametrize("damage", ["absent", "malformed", "wrong_run"])
def test_missing_or_corrupt_selected_metadata_does_not_fall_back(case, damage):
    root, state, _, _ = case
    bootstrap(case, create=True)
    supplied = state.load()
    if damage == "absent":
        del supplied[KEY]
    if damage == "malformed":
        supplied[KEY] = None
    if damage == "wrong_run":
        supplied["run_id"] = "other"
    path = state.squad_dir / "state.json"
    path.write_text(json.dumps(supplied))
    before, db = path.read_bytes(), sql_rows(root)
    with pytest.raises(ValueError):
        bootstrap(case)
    assert path.read_bytes() == before
    assert sql_rows(root) == db
    with pytest.raises(IdentityStoreError):
        require_legacy_identity_execution(project_root=root, run_dir=state.squad_dir, state=supplied)


@pytest.mark.parametrize("damage", ["database_missing", "identity_missing", "different_namespace"])
def test_established_authority_is_never_initialized_or_replaced_by_bootstrap(case, damage):
    root, state, _, _ = case
    bootstrap(case, create=True)
    directory = root / ".echelon/identity"
    if damage == "database_missing":
        (directory / "registry.sqlite3").rename(root / "retained.sqlite3")
    else:
        directory.rename(root / "retained-identity")
        if damage == "different_namespace":
            IdentityStore.initialize(root)
    before = (state.squad_dir / "state.json").read_bytes()
    with pytest.raises(ValueError):
        bootstrap(case)
    assert (state.squad_dir / "state.json").read_bytes() == before
    if damage == "database_missing": assert not (directory / "registry.sqlite3").exists()
    if damage == "identity_missing": assert not directory.exists()
    if damage == "different_namespace": assert IdentityStore.open(root).managed_identity(spec_id="game") is None


@pytest.mark.parametrize("stage", ["captured", "completed"])
def test_changed_captured_source_blocks_recovery_without_overwriting_files(case, monkeypatch, stage):
    root, state, _, _ = case
    if stage == "captured":
        def interrupted(self, **request):
            raise Interrupted()
        with monkeypatch.context() as patch:
            patch.setattr(IdentityStore, "register_source_context", interrupted)
            with pytest.raises(Interrupted):
                bootstrap(case, create=True)
    else:
        bootstrap(case, create=True)
    path = root / "specs/game/evidence.md"
    path.write_text("Retained findings for U-001\r\n")
    before, db, content = state.load(), sql_rows(root), path.read_bytes()
    with pytest.raises(ValueError):
        bootstrap(case)
    assert state.load() == before
    assert sql_rows(root) == db
    assert path.read_bytes() == content


@pytest.mark.parametrize("change", ["phase", "status", "completion", "publication"])
def test_bootstrap_rejects_ineligible_controller_state(case, change):
    root, state, _, _ = case
    current = state.load()
    if change == "phase": current["phase"] = "phase2-specify"
    if change == "status": current["status"] = "completed"
    if change == "completion": current["_spec_step_effect_plan"] = {}
    if change == "publication": current["_spec_step_publication_plan"] = {}
    # Fault fixture: no public controller operation is used to manufacture a pending outbox.
    path = state.squad_dir / "state.json"
    path.write_text(json.dumps(current))
    before, db = path.read_bytes(), sql_rows(root)
    with pytest.raises(ValueError):
        bootstrap(case, create=True)
    assert path.read_bytes() == before
    assert sql_rows(root) == db


def test_capture_transaction_with_writes_cannot_be_bootstrap_authority(case):
    root, state, store, _ = case
    transaction = SquadPublicationTransaction.begin(root, state.squad_dir, "7" * 32)
    staged = transaction.build_path("unexpected")
    staged.write_text("Not a bootstrap operation")
    transaction.add_write(Path("specs/game/unknowns.md"), staged, owned_paths={Path("specs/game/unknowns.md")})
    marker = transaction.seal().marker.to_dict()
    before = sql_rows(root)
    with pytest.raises(ValueError):
        bootstrap(case, capture_marker=marker, create=True)
    assert sql_rows(root) == before
    assert store.managed_identity(spec_id="game") is None
    assert list((root / "specs/game").iterdir()) == []


@pytest.mark.parametrize("kind", ["source", "genesis"])
def test_retained_registration_conflict_is_not_repaired(case, kind):
    from harness.discovery_bootstrap_state import bootstrap_ids
    root, state, store, selection = case
    state.prepare_discovery_bootstrap(selection)
    state.capture_discovery_bootstrap(selection, capture(case).payload)
    ids = bootstrap_ids(selection)
    operation = ids["source_registration_operation_id"] if kind == "source" else ids["operation_id"]
    store.reserve(spec_id="other", kind="U", operation_id=operation, count=1)
    with pytest.raises(ValueError):
        bootstrap(case)
    assert store.managed_identity(spec_id="game") is None
    assert store.reservation(spec_id="other", kind="U", operation_id=operation, count=1) == ("U-000001",)


def test_bootstrap_state_owner_only_checks_claims_and_never_registers(case):
    from harness.discovery_bootstrap_state import bootstrap_genesis
    root, state, store, selection = case
    before = sql_rows(root)
    state.prepare_discovery_bootstrap(selection)
    manifest = capture(case)
    state.capture_discovery_bootstrap(selection, manifest.payload)
    claimed = bootstrap_genesis(selection, manifest.payload)
    with pytest.raises(StateAdvanceError):
        state.complete_discovery_bootstrap(selection, {**claimed, "source_manifest_sha256": "0" * 64})
    completed = state.complete_discovery_bootstrap(selection, claimed)
    assert state.complete_discovery_bootstrap(selection, claimed) == completed
    assert sql_rows(root) == before
    assert store.managed_identity(spec_id="game") is None
    with pytest.raises(ValueError):
        bootstrap(case)  # A claimed completed receipt never grants enrollment authority.
    assert sql_rows(root) == before


@pytest.mark.parametrize("mode", ["guided", "semi", "banzai"])
@pytest.mark.parametrize("entry", ["run", "single"])
def test_pending_bootstrap_blocks_real_squad_entry_before_any_provider(case, mode, entry):
    from harness.phase_graph import PhaseGraph
    from harness.squad import SquadController
    root, state, store, selection = case
    current = state.load()
    current["autonomy_mode"] = mode
    state.save(current)
    state.prepare_discovery_bootstrap(selection)
    extension = Path(__file__).resolve().parents[2]
    graph = PhaseGraph(extension / "runtime/workflow/definition.yaml",
                       prosaic_subagents_dir=extension / "prosaic/subagents")
    class NoProvider:
        def exec_agent(self, *args, **kwargs):
            pytest.fail("pending bootstrap reached a provider")
    controller = SquadController(provider=NoProvider(), state_store=state, phase_graph=graph,
        ext_dir=extension, project_root=root, squad_dir=state.squad_dir)
    before, db = (state.squad_dir / "state.json").read_bytes(), sql_rows(root)
    result = controller.run() if entry == "run" else controller.run_single_phase("phase1-discover")
    assert result.status == "blocked"
    assert result.summary == "identity authority does not permit legacy execution"
    assert (state.squad_dir / "state.json").read_bytes() == before
    assert sql_rows(root) == db
    assert store.managed_identity(spec_id="game") is None


@pytest.mark.parametrize("method", ["register_source_context", "register_managed_identity"])
def test_source_drift_during_registration_cannot_complete_bootstrap(case, monkeypatch, method):
    root, state, store, _ = case
    original = getattr(IdentityStore, method)
    raced = root / "specs/game/raced.md"
    def changed(self, **request):
        result = original(self, **request)
        raced.write_text("External source change")
        return result
    with monkeypatch.context() as patch:
        patch.setattr(IdentityStore, method, changed)
        with pytest.raises(ValueError):
            bootstrap(case, create=True)
    assert "managed_identity" not in state.load()
    assert state.load()[KEY]["source_manifest"] is not None
    assert raced.read_text() == "External source change"
    db = sql_rows(root)
    with pytest.raises(ValueError):
        bootstrap(case)
    assert "managed_identity" not in state.load()
    assert sql_rows(root) == db
    # Restore this test's external edit, then recover the retained registrations.
    raced.unlink()
    result = bootstrap(case)
    assert state.load()["managed_identity"] == store.managed_identity(spec_id="game") == result
    assert sql_rows(root) == db
