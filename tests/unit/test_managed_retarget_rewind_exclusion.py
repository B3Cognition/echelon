"""Managed ownership blocks native source transitions before their first effect."""

from contextlib import closing, contextmanager
import json
import os
from pathlib import Path
import select
import sqlite3
import subprocess
import sys

import pytest

from tests.unit.test_cli_spec_retarget import _git, _activate_retarget_retry, retarget_cli_workspace
from harness.element_identity_legacy_guard import LEGACY_IDENTITY_EXECUTION_BLOCKED
from harness.element_identity_managed import ManagedIdentityRequest
from harness.element_identity_store import IdentityStore, IdentityStoreError
from harness.squad_source_manifest import snapshot_source_manifest
from harness.squad_source_snapshot import inspect_project_tree
from tests.unit.test_element_identity_legacy_guard import StringSubclass, TupleSubclass


def _enroll(root, *, spec="001-demo", run="squad-base"):
    store = IdentityStore.open(root) if (root / ".echelon/identity").exists() else IdentityStore.initialize(root)
    selected = f"runs/{run}/specs/{spec}"
    selected_path = root / selected
    saved = selected_path.with_name(spec + ".fixture-content")
    had_content = selected_path.exists()
    if had_content:
        selected_path.rename(saved)
    selected_path.mkdir(parents=True)
    with inspect_project_tree(root, selected) as tree:
        manifest = snapshot_source_manifest(trees=(tree,), files=())
    source = store.register_source_context(
        spec_id=spec, context_id="source", operation_id=f"source-{spec}", manifest=manifest,
    )
    record = store.register_managed_identity(
        spec_id=spec, operation_id=f"managed-{spec}", request=ManagedIdentityRequest(
            source["workspace_uuid"], source["epoch_uuid"], run, "source", selected,
            f"source-{spec}", manifest.sha256,
        ),
    )
    if had_content:
        selected_path.rmdir()
        saved.rename(selected_path)
    return record


def _state(root, run="squad-base", **updates):
    path = root / "runs" / run / "state.json"
    state = json.loads(path.read_text())
    state.update(updates)
    path.write_text(json.dumps(state, indent=2) + "\n")
    return state


def _snapshot(root):
    # Lock directories are transient native lease infrastructure. Include every
    # retained file (including stage/source/graph bytes), SQL and Git authority.
    files = tuple(
        (p.relative_to(root).as_posix(), str(p.readlink()) if p.is_symlink() else p.read_bytes())
        for p in sorted(root.rglob("*"))
        if (p.is_symlink() or p.is_file()) and ".git" not in p.parts
    )
    database = root / ".echelon/identity/registry.sqlite3"
    sql = None
    if database.is_file():
        with closing(sqlite3.connect(database)) as connection:
            sql = tuple(connection.iterdump())
    return (
        files, sql, _git(root, "rev-parse", "HEAD"), _git(root, "show-ref"),
        (root / ".git/index").read_bytes(),
        tuple(p.relative_to(root / ".git/objects").as_posix()
              for p in sorted((root / ".git/objects").rglob("*")) if p.is_file()),
    )


def test_managed_retarget_rejects_before_first_durable_effect(retarget_cli_workspace, monkeypatch):
    import echelon.spec_retarget as retarget

    root = retarget_cli_workspace
    record = _enroll(root)
    _state(root, managed_identity=record)
    effects = []

    def forbidden(preview):
        effects.append("append_prepared_revision")
        pytest.fail("managed retarget reached its first durable effect")

    monkeypatch.setattr(retarget, "append_prepared_revision_from_preview", forbidden)
    before = _snapshot(root)
    with pytest.raises(retarget.RetargetEligibilityError, match=LEGACY_IDENTITY_EXECUTION_BLOCKED):
        retarget.prepare_spec_retarget(root, "001-demo", ("apps/web",), confirm=True)
    assert effects == []
    assert _snapshot(root) == before


def _blocked(action, error=IdentityStoreError, message=LEGACY_IDENTITY_EXECUTION_BLOCKED):
    with pytest.raises(error) as raised:
        action()
    assert str(raised.value) == message
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None


@pytest.mark.parametrize("spec,damage,blocked", [
    ("001-demo", None, True), ("legacy", None, False),
    (" 001-demo ", None, False),
    ("001-demo", "UPDATE managed_identity_specs SET request='{}',request_sha256='bad'", True),
    ("001-demo", "UPDATE source_contexts SET manifest='broken'", True),
    ("legacy", "DELETE FROM managed_identity_specs", True),
    ("legacy", "INSERT INTO operations VALUES ('orphan','managed_identity','other','bad')", True),
])
def test_spec_only_query_observes_retained_ownership_without_decoding(tmp_path, spec, damage, blocked):
    _enroll(tmp_path)
    if damage:
        with closing(sqlite3.connect(tmp_path / ".echelon/identity/registry.sqlite3")) as connection:
            connection.execute(damage)
            connection.commit()
    from tests.unit.test_element_identity_legacy_guard import sql_state
    before = sql_state(tmp_path)
    action = lambda: IdentityStore.open(tmp_path).require_unmanaged_execution(spec_id=spec, run_ids=())
    if blocked:
        _blocked(action, message="invalid unmanaged execution authority or request")
    else:
        assert action() is None
    assert sql_state(tmp_path) == before


@pytest.mark.parametrize("spec,runs", [
    (None, ()), ("", ()), (" ", ()), (False, ()), (1, ()), ("\ud800", ()),
    ("bad\x00", ()), ("legacy", []), ("legacy", ["run"]),
    ("legacy", ("run", "run")), ("legacy", (None,)), ("legacy", (1,)),
    (StringSubclass("legacy"), ()), ("legacy", TupleSubclass(())),
    ("legacy", (StringSubclass("run"),)),
])
def test_invalid_spec_only_query_never_opens_transaction(tmp_path, monkeypatch, spec, runs):
    store = IdentityStore.initialize(tmp_path)
    def forbidden(**kwargs):
        pytest.fail("invalid selector entered authority transaction")
    monkeypatch.setattr(store, "_transaction", forbidden)
    _blocked(lambda: store.require_unmanaged_execution(spec_id=spec, run_ids=runs),
             message="invalid unmanaged execution authority or request")


def test_spec_only_query_is_one_indexed_query_only_transaction(tmp_path, monkeypatch):
    import harness.element_identity_store as module
    from tests.unit.test_element_identity_legacy_guard import sql_state
    _enroll(tmp_path)
    store = IdentityStore.open(tmp_path)
    before = sql_state(tmp_path)
    statements = []
    original = module._database
    allowed = {"sqlite_master", "metadata", "managed_identity_specs", "operations"}
    def authorize(action, table, *args):
        return sqlite3.SQLITE_DENY if action == sqlite3.SQLITE_READ and table not in allowed else sqlite3.SQLITE_OK
    @contextmanager
    def observed(path):
        with original(path) as connection:
            connection.set_trace_callback(statements.append)
            connection.set_authorizer(authorize)
            yield connection
    monkeypatch.setattr(module, "_database", observed)
    store.require_unmanaged_execution(spec_id="legacy", run_ids=())
    assert statements.count("BEGIN") == statements.count("COMMIT") == 1
    assert statements.count("PRAGMA query_only=ON") == 1
    queries = [s for s in statements if s.startswith("SELECT 1 FROM")]
    assert len(queries) == 2
    assert statements.index("PRAGMA query_only=ON") < statements.index(queries[0])
    assert not any(s.startswith(("INSERT", "UPDATE", "DELETE", "REPLACE")) for s in statements)
    with closing(sqlite3.connect(tmp_path / ".echelon/identity/registry.sqlite3")) as connection:
        plans = [" ".join(row[3] for row in connection.execute("EXPLAIN QUERY PLAN " + query)) for query in queries]
    assert "SEARCH" in plans[0] and "PRIMARY KEY" in plans[0]
    assert "managed_identity_operations" in plans[1] and "SEARCH managed" in plans[1]
    assert sql_state(tmp_path) == before


@pytest.mark.parametrize("spec", [None, "", " ", False, 1, "\x00", "\ud800", StringSubclass("legacy")])
def test_selected_spec_guard_validates_before_authority_io(tmp_path, monkeypatch, spec):
    from harness.element_identity_legacy_guard import require_legacy_identity_spec
    def forbidden(*args, **kwargs):
        pytest.fail("invalid selected spec accessed authority")
    monkeypatch.setattr(Path, "lstat", forbidden)
    _blocked(lambda: require_legacy_identity_spec(project_root=tmp_path, spec_id=spec))


@pytest.mark.parametrize("authority", ["absent-parent", "absent-child", "unrelated", "managed", "missing-db", "missing-marker", "parent-file", "parent-dangling", "parent-symlink", "leaf-dangling", "leaf-directory"])
def test_selected_spec_guard_presence_open_and_no_repair(tmp_path, authority):
    from harness.element_identity_legacy_guard import require_legacy_identity_spec
    from tests.unit.test_element_identity_legacy_guard import filesystem_state
    parent = tmp_path / ".echelon"
    if authority in {"unrelated", "managed", "missing-db", "missing-marker"}:
        _enroll(tmp_path, spec="001-demo" if authority == "managed" else "002-other")
        if authority == "missing-db":
            (parent / "identity/registry.sqlite3").unlink()
        if authority == "missing-marker":
            (parent / "identity/authority.json").unlink()
    elif authority == "parent-file":
        parent.write_text("broken")
    elif authority.startswith("parent-"):
        target = tmp_path / "target"
        if authority == "parent-symlink":
            target.mkdir()
        parent.symlink_to(target, target_is_directory=True)
    elif authority != "absent-parent":
        parent.mkdir()
        if authority == "leaf-dangling":
            (parent / "identity").symlink_to(tmp_path / "missing")
        if authority == "leaf-directory":
            (parent / "identity").mkdir()
    before = filesystem_state(tmp_path)
    action = lambda: require_legacy_identity_spec(project_root=tmp_path, spec_id="001-demo")
    if authority in {"absent-parent", "absent-child", "unrelated"}:
        assert action() is None
    else:
        _blocked(action)
    assert filesystem_state(tmp_path) == before


@pytest.mark.parametrize("exception", [RuntimeError("private payload"), KeyboardInterrupt(), SystemExit()])
def test_selected_spec_guard_bounds_errors_without_chaining(tmp_path, monkeypatch, exception):
    from harness.element_identity_legacy_guard import require_legacy_identity_spec
    IdentityStore.initialize(tmp_path)
    def failing(*args, **kwargs):
        raise exception
    monkeypatch.setattr(IdentityStore, "open", failing)
    action = lambda: require_legacy_identity_spec(project_root=tmp_path, spec_id="legacy")
    if isinstance(exception, Exception):
        _blocked(action)
    else:
        with pytest.raises(type(exception)):
            action()


def _prepare_adoption(root):
    from echelon.spec_retarget import _build_retarget_preview, append_prepared_revision_from_preview
    from harness.phase_checkpoints import commit_retarget_checkpoint
    preview = _build_retarget_preview(root, "001-demo", ("apps/web",))
    revision = append_prepared_revision_from_preview(preview)
    commit_retarget_checkpoint(project_root=root, spec_dir=preview.spec_dir,
                              run_id=preview.baseline.run_id, revision_id=revision.revision_id)


def _leases_released(root, run="squad-base"):
    from echelon.spec_lifecycle import SpecMutationLock, PhaseAExecutionLock, SpecRunExecutionLock
    with SpecMutationLock.acquire(root, "001-demo", "prove-release"):
        with PhaseAExecutionLock.acquire(root, "prove-release"):
            with SpecRunExecutionLock.acquire(root / "runs" / run, "prove-release"):
                pass


@pytest.mark.parametrize("branch", ["apply", "adopt", "checkpointed", "invalidating", "rebuilding", "finalizing"])
@pytest.mark.parametrize("witness", ["record", "malformed", "selected-spec", "physical-run", "declared-run", "claimed-spec", "active-run", "active-metadata", "invalid-authority"])
def test_retarget_native_owners_refuse_each_independent_witness(retarget_cli_workspace, monkeypatch, branch, witness):
    import echelon.spec_retarget as retarget
    from echelon.spec_retarget_history import advance_retarget_revision, load_retarget_history
    root = retarget_cli_workspace
    active = "squad-base"
    if branch == "adopt":
        _prepare_adoption(root)
    elif branch != "apply":
        active, _ = _activate_retarget_retry(root, status="rebuilding" if branch == "finalizing" else branch)
        if branch == "finalizing":
            revision = load_retarget_history(root / "specs/001-demo").revisions[-1]
            advance_retarget_revision(root / "specs/001-demo", revision.revision_id,
                                     expected_status="rebuilding", status="finalizing", updates={})
            state = _state(root, active)
            state["retarget"]["status"] = "finalizing"
            _state(root, active, retarget=state["retarget"])
    if witness == "record":
        _state(root, managed_identity=_enroll(root))
    elif witness == "malformed":
        _state(root, managed_identity=False)
    elif witness == "selected-spec":
        _enroll(root, run="retained-other")
        # Native selectors strip this claim; admission must also check the
        # independently selected canonical ID without rewriting the raw state.
        _state(root, spec_id=" 001-demo ")
    elif witness == "physical-run":
        _enroll(root, spec="002-other")
    elif witness == "declared-run":
        _enroll(root, spec="002-other", run="declared-owner")
        _state(root, run_id="declared-owner")
    elif witness == "claimed-spec":
        _enroll(root, spec=" 001-demo ", run="other-owner")
        _state(root, spec_id=" 001-demo ")
    elif witness == "active-run":
        _enroll(root, spec="002-other", run=active)
    elif witness == "active-metadata":
        _state(root, active, managed_identity={})
    else:
        (root / ".echelon/identity").mkdir()
    effects = []
    def forbidden(*args, **kwargs):
        effects.append("effect")
        pytest.fail("managed owner reached a durable effect or callback")
    for name in ("append_prepared_revision_from_preview", "commit_retarget_checkpoint",
                 "start_retarget_phase_a_spec_from_preview", "purge_retarget_spec_memory",
                 "invalidate_retarget_artifacts", "mark_retarget_failed", "mark_retarget_failed_before_bootstrap"):
        monkeypatch.setattr(retarget, name, forbidden)
    before = _snapshot(root)
    _blocked(lambda: retarget.prepare_spec_retarget(root, "001-demo", ("apps/web",),
             confirm=True, checkpoint_created=forbidden), retarget.RetargetEligibilityError)
    assert not effects
    assert _snapshot(root) == before
    _leases_released(root)


@pytest.mark.parametrize("mode", ["guided", "semi", "banzai"])
def test_unrelated_authority_retains_native_retarget_and_managed_preview(retarget_cli_workspace, mode):
    from echelon.spec_retarget import prepare_spec_retarget
    root = retarget_cli_workspace
    _enroll(root, spec="002-other", run="other")
    _state(root, autonomy_mode=mode, managed_identity=None)
    before = _snapshot(root)
    assert not prepare_spec_retarget(root, "001-demo", ("apps/web",), confirm=False).applied
    assert _snapshot(root) == before
    from echelon.spec_retarget import RetargetEligibilityError
    _blocked(lambda: prepare_spec_retarget(root, "001-demo", ("apps/web",), confirm=True), RetargetEligibilityError)
    assert _snapshot(root) == before
    state_path = root / "runs/squad-base/state.json"
    state = json.loads(state_path.read_text())
    del state["managed_identity"]
    state_path.write_text(json.dumps(state))
    result = prepare_spec_retarget(root, "001-demo", ("apps/web",), confirm=True)
    assert result.applied
    assert (root / "runs/.current").read_text().strip() == result.replacement_run_id


def _captured_recovery(root):
    from harness.phase_checkpoints import load_checkpoint_ledger
    from tests.unit.test_spec_retarget_recovery import _memory_receipt, _invalidation_receipt
    active, _ = _activate_retarget_retry(root, status="checkpointed")
    checkpoint = load_checkpoint_ledger(root / "specs/001-demo").checkpoints[-1]
    state = _state(root, active)
    state["retarget"].update(memory_purge=_memory_receipt().to_dict(),
                             graph_invalidation=_invalidation_receipt().to_dict())
    return checkpoint, _state(root, active, retarget=state["retarget"])


@pytest.mark.parametrize("entry", ["recover_retarget_checkpoint", "_require_recovery_revision"])
@pytest.mark.parametrize("witness", ["selected", "replacement-run", "replacement-metadata", "baseline-run-missing-state", "baseline-run-missing-directory", "baseline-declared", "baseline-claimed", "baseline-metadata", "baseline-malformed", "baseline-symlink", "baseline-dangling", "baseline-directory", "baseline-parent-symlink", "baseline-parent-file", "runs-parent-symlink"])
def test_recovery_refuses_before_captured_receipt_history_advance(retarget_cli_workspace, monkeypatch, entry, witness):
    import echelon.spec_retarget_recovery as recovery
    root = retarget_cli_workspace
    checkpoint, state = _captured_recovery(root)
    baseline = root / "runs/squad-base/state.json"
    if witness == "selected":
        _enroll(root, run="other")
    elif witness == "replacement-run":
        _enroll(root, spec="002-other", run=state["run_id"])
    elif witness == "replacement-metadata":
        state["managed_identity"] = None
    elif witness == "baseline-run-missing-state":
        _enroll(root, spec="002-other")
        baseline.unlink()
    elif witness == "baseline-run-missing-directory":
        _enroll(root, spec="002-other")
        baseline.parent.rename(root / "retained-baseline")
    elif witness == "baseline-declared":
        _enroll(root, spec="002-other", run="declared-owner")
        _state(root, run_id="declared-owner")
    elif witness == "baseline-claimed":
        _enroll(root, spec="002-other", run="other")
        _state(root, spec_id="002-other")
    elif witness == "baseline-metadata":
        _state(root, managed_identity=False)
    elif witness == "baseline-malformed":
        baseline.write_text("[]")
    elif witness == "runs-parent-symlink":
        (root / "runs").rename(root / "retained-runs")
        (root / "runs").symlink_to(root / "retained-runs", target_is_directory=True)
    elif witness.startswith("baseline-parent"):
        saved = baseline.parent.with_name("retained-baseline")
        baseline.parent.rename(saved)
        if witness == "baseline-parent-file":
            baseline.parent.write_text("bad")
        else:
            baseline.parent.symlink_to(saved, target_is_directory=True)
    else:
        baseline.unlink()
        if witness == "baseline-directory":
            baseline.mkdir()
        else:
            target = root / "baseline-state"
            if witness == "baseline-symlink":
                target.write_text("{}")
            baseline.symlink_to(target)
    effects = []
    def forbidden(*args, **kwargs):
        effects.append("recovery-effect")
        pytest.fail("managed recovery reached reconciliation or a mutation")
    for name in ("advance_retarget_revision", "restore_or_recreate_baseline_state",
                 "purge_retarget_spec_memory", "refresh_retarget_spec_memory", "finalize_retarget_graphs",
                 "create_or_recover_retarget_recovery_commit", "persist_recovered_baseline_state",
                 "activate_recovered_spec_run"):
        monkeypatch.setattr(recovery, name, forbidden)
    before = _snapshot(root)
    directories = tuple(str(p.relative_to(root)) for p in root.rglob("*") if p.is_dir())
    # Non-recovered committed probes are native read-only no-ops, before the
    # admitted revision owner is reached.
    assert recovery.verified_committed_retarget_recovery(root, checkpoint, state) is None
    assert recovery.resume_committed_retarget_recovery(root, checkpoint, state) is None
    _blocked(lambda: getattr(recovery, entry)(root, checkpoint, state), recovery.RetargetRecoveryError)
    assert not effects
    assert _snapshot(root) == before
    assert tuple(str(p.relative_to(root)) for p in root.rglob("*") if p.is_dir()) == directories


def test_native_captured_recovery_legacy_control_advances_history_without_recreating_missing_baseline(retarget_cli_workspace):
    from echelon.spec_retarget_recovery import _require_recovery_revision
    root = retarget_cli_workspace
    checkpoint, state = _captured_recovery(root)
    _enroll(root, spec="002-other", run="other")
    baseline = root / "runs/squad-base"
    baseline.rename(root / "retained-baseline")
    _, revision = _require_recovery_revision(root, checkpoint, state)
    assert revision.status == "failed"
    assert revision.graph_invalidation is not None
    assert not baseline.exists()


def test_managed_committed_recovery_refuses_before_resume_publication(retarget_cli_workspace, monkeypatch):
    import echelon.spec_retarget_recovery as recovery
    from echelon.spec_retarget_history import advance_retarget_revision
    from tests.unit.test_spec_retarget_recovery import _failed_revision, _checkpoint, _replacement_state, _memory_receipt, _graph_receipt
    root = retarget_cli_workspace
    commit = _git(root, "rev-parse", "HEAD").strip()
    spec_dir, failed = _failed_revision(root, checkpoint_commit=commit)
    recovered = advance_retarget_revision(spec_dir, failed.revision_id, expected_status="failed", status="recovered",
        updates={"memory_finalization": _memory_receipt().to_dict(), "graph_finalization": _graph_receipt().to_dict(), "failure_code": None})
    checkpoint = _checkpoint(recovered.revision_id, commit=commit)
    recovery_commit = recovery.create_or_recover_retarget_recovery_commit(root, spec_dir, recovered, checkpoint)
    state = _replacement_state(recovered.revision_id)
    state["retarget"]["checkpoint_commit"] = commit
    run_dir = root / "runs/squad-replacement"
    run_dir.mkdir()
    (run_dir / "state.json").write_text(json.dumps(state))
    assert recovery.verified_committed_retarget_recovery(root, checkpoint, state) == recovery_commit
    _enroll(root, spec="002-other", run="squad-replacement")
    before = _snapshot(root)
    def forbidden(*args, **kwargs):
        pytest.fail("managed committed recovery attempted state or pointer publication")
    monkeypatch.setattr(recovery, "persist_recovered_baseline_state", forbidden)
    monkeypatch.setattr(recovery, "activate_recovered_spec_run", forbidden)
    for entry in (recovery.verified_committed_retarget_recovery, recovery.resume_committed_retarget_recovery):
        _blocked(lambda: entry(root, checkpoint, state), recovery.RetargetRecoveryError)
    assert _snapshot(root) == before


def _rewind_checkpoint(root, *, kind="ordinary", moving=False):
    from harness.phase_checkpoints import PhaseCheckpoint, record_checkpoint_metadata
    if kind == "retarget":
        checkpoint, state = _captured_recovery(root)
        active = state["run_id"]
    else:
        active = "squad-base"
        _state(root, spec_dir="specs/001-demo")
        head = _git(root, "rev-parse", "HEAD").strip()
        checkpoint = PhaseCheckpoint("phase3-plan", "001-demo", "phase3-plan", "phase3-consensus",
                                     head, head, "auto", active, "2026-09-13T00:00:00Z")
        record_checkpoint_metadata(root / "specs/001-demo", checkpoint)
    if moving:
        (root / "later.txt").write_text("later\n")
        _git(root, "add", "later.txt")
        _git(root, "commit", "-m", "later")
    return checkpoint, active


def _assert_only_native_state_bookkeeping(root, before, run):
    after = _snapshot(root)
    expected_lock = f"runs/{run}/state.lock"
    assert set(dict(after[0])) - set(dict(before[0])) <= {expected_lock}
    assert tuple(item for item in after[0] if item[0] != expected_lock) == tuple(item for item in before[0] if item[0] != expected_lock)
    assert after[1:] == before[1:]
    if expected_lock in dict(after[0]):
        assert dict(after[0])[expected_lock] == b""


@pytest.mark.parametrize("kind", ["ordinary", "retarget"])
@pytest.mark.parametrize("moving", [False, True])
@pytest.mark.parametrize("confirm", [False, True])
@pytest.mark.parametrize("mode", ["guided", "semi", "banzai"])
@pytest.mark.parametrize("witness", ["record", "removed", "malformed"])
def test_cli_rewind_refuses_native_preview_noop_and_confirm_before_effects(retarget_cli_workspace, monkeypatch, capsys, kind, moving, confirm, mode, witness):
    from echelon.cli import _cmd_rewind
    import echelon.rewind as rewind
    import echelon.spec_retarget_recovery as recovery
    import harness.phase_checkpoints as checkpoints
    from harness.squad_state import SquadStateStore
    root = retarget_cli_workspace
    checkpoint, active = _rewind_checkpoint(root, kind=kind, moving=moving)
    record = _enroll(root, run=active) if witness != "malformed" else None
    updates = {"autonomy_mode": mode}
    if witness != "removed":
        updates["managed_identity"] = record if witness == "record" else False
    _state(root, active, **updates)
    effects = []
    def forbidden(*args, **kwargs):
        effects.append("rewind-effect")
        pytest.fail("managed CLI rewind reached an effect")
    for module, names in ((rewind, ("create_backup_ref", "reset_branch_to_commit", "_discard_recovery_dirty_paths")),
                          (recovery, ("advance_retarget_revision", "persist_recovered_baseline_state", "activate_recovered_spec_run")),
                          (checkpoints, ("write_checkpoint_ledger",)),
                          (SquadStateStore, ("save", "rewind_failed_banzai_human_gate"))):
        for name in names:
            monkeypatch.setattr(module, name, forbidden)
    before = _snapshot(root)
    directories_before = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_dir()}
    assert not (root / "runs" / active / "state.lock").exists()
    with pytest.raises(SystemExit) as raised:
        _cmd_rewind([f"checkpoint:{checkpoint.id}"] + (["--confirm"] if confirm else []), root)
    assert raised.value.code == 1
    if witness == "malformed":
        assert raised.value.__context__ is None
    output = capsys.readouterr()
    assert LEGACY_IDENTITY_EXECUTION_BLOCKED in output.err
    assert "COMPLETE" not in output.out and "Already at checkpoint" not in output.out
    assert not effects
    _assert_only_native_state_bookkeeping(root, before, active)
    directories_after = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_dir()}
    assert directories_after - directories_before <= {
        ".echelon/runtime", ".echelon/runtime/spec-mutations",
        f"runs/{active}/staging", f"runs/{active}/.echelon", f"runs/{active}/.echelon/runtime",
    }
    _leases_released(root)


@pytest.mark.parametrize("moving", [False, True])
@pytest.mark.parametrize("witness", ["selected-directory", "checkpoint-spec"])
def test_standalone_confirmed_rewind_checks_both_exact_spec_witnesses(retarget_cli_workspace, monkeypatch, moving, witness):
    from echelon.rewind import prepare_rewind, RewindError
    import echelon.rewind as rewind
    root = retarget_cli_workspace
    checkpoint, _ = _rewind_checkpoint(root, moving=moving)
    spec_dir = root / "specs/001-demo"
    if witness == "selected-directory":
        # Native library permits an explicit directory with independently named
        # checkpoint ownership; the selected directory must be checked too.
        moved = root / "specs/002-other"
        spec_dir.rename(moved)
        spec_dir = moved
        _enroll(root, spec="002-other", run="other")
        _git(root, "add", "specs")
        _git(root, "commit", "-m", "alternate explicit directory")
        if not moving:
            from dataclasses import replace
            from harness.phase_checkpoints import write_checkpoint_ledger, CheckpointLedger
            checkpoint = replace(checkpoint, commit=_git(root, "rev-parse", "HEAD").strip())
            write_checkpoint_ledger(spec_dir, CheckpointLedger("001-demo", [checkpoint]))
    else:
        _enroll(root)
    def forbidden(*args, **kwargs):
        pytest.fail("managed standalone rewind reached Git or file effects")
    for name in ("create_backup_ref", "reset_branch_to_commit", "_discard_recovery_dirty_paths"):
        monkeypatch.setattr(rewind, name, forbidden)
    before = _snapshot(root)
    _blocked(lambda: prepare_rewind(project_root=root, spec="001-demo", spec_dir=spec_dir,
                                   target=f"checkpoint:{checkpoint.id}", confirm=True), RewindError)
    assert _snapshot(root) == before
    preview = prepare_rewind(project_root=root, spec="001-demo", spec_dir=spec_dir,
                             target=f"checkpoint:{checkpoint.id}", confirm=False)
    assert preview.applied is (not moving)
    assert _snapshot(root) == before


@contextmanager
def _held_native_lease(root, lease):
    # A separate native process owns the lease: no self-deadlock or fabricated
    # owner file, and the pipe bounds startup and release without sleep.
    script = """
from pathlib import Path
import sys
from echelon.spec_lifecycle import SpecMutationLock, PhaseAExecutionLock, SpecRunExecutionLock
root = Path(sys.argv[1])
kind = sys.argv[2]
lock = (SpecMutationLock.acquire(root, '001-demo', 'held-owner') if kind == 'spec'
        else PhaseAExecutionLock.acquire(root, 'held-owner') if kind == 'phase'
        else SpecRunExecutionLock.acquire(root / 'runs/squad-base', 'held-owner'))
with lock:
    print('READY', flush=True)
    sys.stdin.readline()
"""
    process = subprocess.Popen([sys.executable, "-c", script, str(root), lease],
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[2] / "src")},
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        assert select.select([process.stdout], [], [], 10)[0], "native lease startup timed out"
        assert process.stdout.readline().strip() == "READY"
        yield
    finally:
        output, error = process.communicate("release\n", timeout=10)
        assert process.returncode == 0, (output, error)


@pytest.mark.parametrize("entry", ["retarget", "rewind"])
@pytest.mark.parametrize("lease", ["spec", "phase", "run"])
def test_busy_native_lease_precedes_managed_admission(retarget_cli_workspace, capsys, entry, lease):
    from echelon.spec_retarget import prepare_spec_retarget
    from echelon.cli import _cmd_rewind
    from echelon.spec_lifecycle import SpecLifecycleLocked
    root = retarget_cli_workspace
    if entry == "rewind":
        checkpoint, _ = _rewind_checkpoint(root)
    _enroll(root)
    with _held_native_lease(root, lease):
        before = _snapshot(root)
        if entry == "retarget":
            with pytest.raises(SpecLifecycleLocked) as raised:
                prepare_spec_retarget(root, "001-demo", ("apps/web",), confirm=True)
            assert raised.value.operation_id == "held-owner"
            assert _snapshot(root) == before
        else:
            with pytest.raises(SystemExit) as raised:
                _cmd_rewind([f"checkpoint:{checkpoint.id}", "--confirm"], root)
            assert raised.value.code == 1
            output = capsys.readouterr()
            assert "held-owner" in output.err
            assert LEGACY_IDENTITY_EXECUTION_BLOCKED not in output.err
            _assert_only_native_state_bookkeeping(root, before, "squad-base")
    _leases_released(root)


@pytest.mark.parametrize("valid", [False, True])
def test_cli_keeps_failed_gate_preflight_but_never_consumes_managed_claim(retarget_cli_workspace, monkeypatch, capsys, valid):
    from tests.unit.test_blocked_decision import _v3_decision
    from echelon.cli import _cmd_rewind, _failed_gate_rewind_authority
    from harness.squad_state import SquadStateStore
    root = retarget_cli_workspace
    checkpoint, _ = _rewind_checkpoint(root)
    decision = _v3_decision(status="failed", attempts=1, failure_code="provider_failed",
                           source_kind="human_gate", source_phase="phase3-consensus")
    recovery = {"schema_version": 2, "kind": "manual_diagnosis", "reason_code": decision["reason_code"],
                "phase": "", "requires_human_input": False, "decision_id": decision["id"]}
    state = _state(root, autonomy_mode="banzai", status="blocked", phase="phase3-consensus",
                   state_revision=4, blocked_decision=decision, recovery_instruction=recovery)
    assert _failed_gate_rewind_authority(state, checkpoint, project_root=root).decision_id == decision["id"]
    if not valid:
        _state(root, recovery_instruction=None)
    _enroll(root)
    def forbidden(*args, **kwargs):
        pytest.fail("managed rewind consumed failed-gate claim")
    monkeypatch.setattr(SquadStateStore, "rewind_failed_banzai_human_gate", forbidden)
    before = _snapshot(root)
    with pytest.raises(SystemExit) as raised:
        _cmd_rewind([f"checkpoint:{checkpoint.id}", "--confirm"], root)
    assert raised.value.code == 1
    error = capsys.readouterr().err
    assert (LEGACY_IDENTITY_EXECUTION_BLOCKED if valid else "versioned decision authority is invalid") in error
    _assert_only_native_state_bookkeeping(root, before, "squad-base")


@pytest.mark.parametrize("witness", ["selected", "physical", "declared", "claimed", "invalid-authority"])
def test_cli_uses_selected_spec_and_original_run_claims_independently(retarget_cli_workspace, capsys, witness):
    from echelon.cli import _cmd_rewind
    root = retarget_cli_workspace
    checkpoint, _ = _rewind_checkpoint(root)
    if witness == "selected":
        _enroll(root, run="other")
        _state(root, spec_id="002-other")
    elif witness == "physical":
        _enroll(root, spec="002-other")
        _state(root, run_id="different")
    elif witness == "declared":
        _enroll(root, spec="002-other", run="declared")
        _state(root, run_id="declared")
    elif witness == "claimed":
        _enroll(root, spec="002-other", run="other")
        _state(root, spec_id="002-other")
    else:
        (root / ".echelon/identity").mkdir()
    before = _snapshot(root)
    with pytest.raises(SystemExit) as raised:
        _cmd_rewind([f"checkpoint:{checkpoint.id}"], root)
    assert raised.value.code == 1
    assert LEGACY_IDENTITY_EXECUTION_BLOCKED in capsys.readouterr().err
    _assert_only_native_state_bookkeeping(root, before, "squad-base")


def test_unrelated_authority_keeps_legacy_cli_same_head_preview_effects(retarget_cli_workspace, capsys):
    from echelon.cli import _cmd_rewind
    from tests.unit.test_element_identity_legacy_guard import sql_state
    root = retarget_cli_workspace
    checkpoint, _ = _rewind_checkpoint(root)
    _enroll(root, spec="002-other", run="other")
    before = sql_state(root)
    _cmd_rewind([f"checkpoint:{checkpoint.id}"], root)
    assert "REWIND COMPLETE" in capsys.readouterr().out
    assert _git(root, "rev-parse", "HEAD").strip() == checkpoint.commit
    assert sql_state(root) == before


@pytest.mark.parametrize("exception", [PermissionError("private path"), KeyboardInterrupt(), SystemExit()])
def test_optional_baseline_read_bounds_io_failure_and_preserves_process_control(retarget_cli_workspace, monkeypatch, exception):
    import echelon.spec_retarget_recovery as recovery
    root = retarget_cli_workspace
    checkpoint, state = _captured_recovery(root)
    baseline_path = root / "runs/squad-base/state.json"
    original = Path.read_text
    def read(path, *args, **kwargs):
        if path == baseline_path:
            raise exception
        return original(path, *args, **kwargs)
    before = _snapshot(root)
    monkeypatch.setattr(Path, "read_text", read)
    action = lambda: recovery._require_recovery_revision(root, checkpoint, state)
    if isinstance(exception, Exception):
        _blocked(action, recovery.RetargetRecoveryError)
    else:
        with pytest.raises(type(exception)):
            action()
    assert _snapshot(root) == before


def test_cli_rewind_rejects_baseline_only_metadata_before_first_effect(retarget_cli_workspace, monkeypatch, capsys):
    from echelon.cli import _cmd_rewind
    from echelon.spec_retarget import prepare_spec_retarget
    import echelon.rewind as rewind
    import harness.phase_checkpoints as checkpoints
    root = retarget_cli_workspace
    result = prepare_spec_retarget(root, "001-demo", ("apps/web",), confirm=True)
    assert result.applied is True
    _state(root, managed_identity=False)
    effects = []
    def forbidden(*args, **kwargs):
        effects.append("rewind-effect")
        pytest.fail("baseline-only managed rewind reached its first effect")
    for name in ("create_backup_ref", "reset_branch_to_commit", "_discard_recovery_dirty_paths"):
        monkeypatch.setattr(rewind, name, forbidden)
    monkeypatch.setattr(checkpoints, "write_checkpoint_ledger", forbidden)
    before = _snapshot(root)
    with pytest.raises(SystemExit) as raised:
        _cmd_rewind([f"checkpoint:{result.checkpoint_id}", "--confirm"], root)
    assert raised.value.code == 1
    assert LEGACY_IDENTITY_EXECUTION_BLOCKED in capsys.readouterr().err
    from echelon.rewind import RewindError
    assert type(raised.value.__context__) is RewindError
    assert raised.value.__context__.__cause__ is None
    assert raised.value.__context__.__context__ is None
    assert effects == []
    _assert_only_native_state_bookkeeping(root, before, result.replacement_run_id)
    _leases_released(root, result.replacement_run_id)


def _native_retarget_rewind(root, head):
    from echelon.spec_retarget import (
        prepare_spec_retarget, _build_retarget_preview,
        append_prepared_revision_from_preview, start_retarget_phase_a_spec_from_preview,
    )
    from echelon.spec_retarget_recovery import retarget_recovery_dirty_paths
    from echelon.rewind import prepare_rewind
    if head == "clean-noop":
        from echelon.spec_lifecycle import SpecMutationLock, PhaseAExecutionLock, SpecRunExecutionLock
        from harness.phase_checkpoints import commit_retarget_checkpoint
        preview = _build_retarget_preview(root, "001-demo", ("apps/web",))
        with SpecMutationLock.acquire(root, preview.spec_id, preview.operation_id):
            with PhaseAExecutionLock.acquire(root, preview.operation_id):
                with SpecRunExecutionLock.acquire(preview.baseline.run_dir, preview.operation_id):
                    revision = append_prepared_revision_from_preview(preview)
                    checkpoint = commit_retarget_checkpoint(project_root=root, spec_dir=preview.spec_dir,
                        run_id=preview.baseline.run_id, revision_id=revision.revision_id)
                    replacement = start_retarget_phase_a_spec_from_preview(preview, revision, checkpoint)
        checkpoint_id, checkpoint_commit, active_id = checkpoint.id, checkpoint.commit, replacement.run.run_id
    else:
        result = prepare_spec_retarget(root, "001-demo", ("apps/web",), confirm=True)
        assert result.applied
        checkpoint_id, checkpoint_commit, active_id = result.checkpoint_id, result.checkpoint_commit, result.replacement_run_id
    if head == "moving":
        (root / "later.txt").write_text("later unrelated commit\n")
        _git(root, "add", "later.txt")
        _git(root, "commit", "-m", "later")
    assert (_git(root, "rev-parse", "HEAD").strip() == checkpoint_commit) is (head != "moving")
    state = json.loads((root / "runs" / active_id / "state.json").read_text())
    spec_dir = root / "specs/001-demo"
    # A newly bootstrapped checkpointed runtime with prepared history is the
    # native pre-invalidation state. Its library rewind is already at HEAD;
    # the CLI admission must precede even later dirty-plan validation.
    dirty_paths = (frozenset() if head == "clean-noop"
                   else retarget_recovery_dirty_paths(root, spec_dir, state))
    preview = prepare_rewind(project_root=root, spec="001-demo", spec_dir=spec_dir,
        target=f"checkpoint:{checkpoint_id}", confirm=False,
        discard_active_spec_dirty_paths=dirty_paths)
    assert preview.applied is (head == "clean-noop")
    if head == "clean-noop":
        assert preview.message == "Already at checkpoint."
    return checkpoint_id, active_id


@pytest.mark.parametrize("head", ["same", "moving", "clean-noop"])
@pytest.mark.parametrize("confirm", [False, True])
@pytest.mark.parametrize("witness", ["metadata", "physical", "declared", "claimed", "missing-state", "missing-run", "malformed", "symlink"])
def test_cli_baseline_only_recovery_admission_precedes_every_rewind_route(retarget_cli_workspace, monkeypatch, capsys, head, confirm, witness):
    from echelon.cli import _cmd_rewind
    from echelon.rewind import RewindError
    import echelon.rewind as rewind
    import echelon.spec_retarget_recovery as recovery
    import harness.phase_checkpoints as checkpoints
    from harness.squad_state import SquadStateStore
    root = retarget_cli_workspace
    checkpoint_id, active_id = _native_retarget_rewind(root, head)
    baseline_path = root / "runs/squad-base/state.json"
    if witness == "metadata":
        _state(root, managed_identity=False)
    elif witness in {"physical", "missing-state", "missing-run"}:
        _enroll(root, spec="002-retained-baseline")
        if witness == "missing-state":
            baseline_path.unlink()
        elif witness == "missing-run":
            baseline_path.parent.rename(root / "retained-baseline")
    elif witness == "declared":
        _enroll(root, spec="002-retained-baseline", run="baseline-declared-owner")
        _state(root, run_id="baseline-declared-owner")
    elif witness == "claimed":
        _enroll(root, spec="002-retained-baseline", run="other")
        _state(root, spec_id="002-retained-baseline")
    elif witness == "malformed":
        baseline_path.write_text("[]")
    else:
        baseline_path.unlink()
        baseline_path.symlink_to(root / "missing-baseline-state")
    effects = []
    def forbidden(*args, **kwargs):
        effects.append("rewind-or-recovery-effect")
        pytest.fail("baseline-only admission reached a rewind/recovery effect")
    for module, names in ((rewind, ("create_backup_ref", "reset_branch_to_commit", "_discard_recovery_dirty_paths")),
                          (checkpoints, ("write_checkpoint_ledger",)),
                          (recovery, ("advance_retarget_revision", "restore_or_recreate_baseline_state",
                                      "purge_retarget_spec_memory", "refresh_retarget_spec_memory",
                                      "finalize_retarget_graphs", "persist_recovered_baseline_state",
                                      "create_or_recover_retarget_recovery_commit", "activate_recovered_spec_run")),
                          (SquadStateStore, ("save",))):
        for name in names:
            monkeypatch.setattr(module, name, forbidden)
    before = _snapshot(root)
    with pytest.raises(SystemExit) as raised:
        _cmd_rewind([f"checkpoint:{checkpoint_id}"] + (["--confirm"] if confirm else []), root)
    assert raised.value.code == 1
    output = capsys.readouterr()
    assert LEGACY_IDENTITY_EXECUTION_BLOCKED in output.err
    assert "COMPLETE" not in output.out and "Already at checkpoint" not in output.out
    assert type(raised.value.__context__) is RewindError
    assert raised.value.__context__.__cause__ is None
    assert raised.value.__context__.__context__ is None
    assert effects == []
    _assert_only_native_state_bookkeeping(root, before, active_id)
    if witness == "missing-run":
        assert not baseline_path.parent.exists()
    _leases_released(root, active_id)


def test_recovery_admission_wrapper_does_not_reconcile_captured_receipts(retarget_cli_workspace):
    from echelon.spec_retarget_recovery import require_legacy_retarget_recovery, _require_recovery_revision
    from echelon.spec_retarget_history import load_retarget_history
    root = retarget_cli_workspace
    checkpoint, state = _captured_recovery(root)
    _enroll(root, spec="002-other", run="other")
    before = _snapshot(root)
    assert require_legacy_retarget_recovery(root, checkpoint, state) is None
    assert _snapshot(root) == before
    assert load_retarget_history(root / "specs/001-demo").revisions[-1].status == "prepared"
    _, revision = _require_recovery_revision(root, checkpoint, state)
    assert revision.status == "failed"
    assert revision.graph_invalidation == state["retarget"]["graph_invalidation"]


@pytest.mark.parametrize("exception", [PermissionError("private path"), KeyboardInterrupt(), SystemExit()])
def test_recovery_admission_wrapper_preserves_bounded_io_and_process_control(retarget_cli_workspace, monkeypatch, exception):
    from echelon.spec_retarget_recovery import require_legacy_retarget_recovery, RetargetRecoveryError
    root = retarget_cli_workspace
    checkpoint, state = _captured_recovery(root)
    baseline_path = root / "runs/squad-base/state.json"
    original = Path.read_text
    def read(path, *args, **kwargs):
        if path == baseline_path:
            raise exception
        return original(path, *args, **kwargs)
    before = _snapshot(root)
    monkeypatch.setattr(Path, "read_text", read)
    action = lambda: require_legacy_retarget_recovery(root, checkpoint, state)
    if isinstance(exception, Exception):
        _blocked(action, RetargetRecoveryError)
    else:
        with pytest.raises(type(exception)):
            action()
    assert _snapshot(root) == before
