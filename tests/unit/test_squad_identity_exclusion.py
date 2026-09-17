"""Existing managed ownership cannot reach legacy controller effects."""

from contextlib import closing, contextmanager
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace
from threading import Event, Thread
from unittest.mock import MagicMock

import pytest

from harness.element_identity_managed import ManagedIdentityRequest
from harness.element_identity_store import IdentityStore
from harness.human_input import HumanInputPolicyRegistry
from harness.squad import SquadController, SquadResult
from harness.squad_publication import SquadPublicationTransaction
from harness.squad_source_manifest import snapshot_source_manifest
from harness.squad_state import SquadStateStore


BLOCKED = "identity authority does not permit legacy execution"


def sql_state(root):
    with closing(sqlite3.connect(root / ".echelon/identity/registry.sqlite3")) as connection:
        return tuple(connection.iterdump())


class TerminalGraph:
    def entry_phase(self):
        return "DONE"

    def all_phase_ids(self):
        return {"DONE"}

    def human_input_policy_registry(self):
        return HumanInputPolicyRegistry(())


@pytest.fixture
def secure_posix():
    from harness.squad_publication import _secure_posix_capabilities_available

    if not _secure_posix_capabilities_available():
        pytest.skip("secure POSIX source capture unavailable")


def managed_controller(tmp_path, *, mode="semi", graph=None):
    root = tmp_path.resolve()
    run = root / "runs/first"
    selected = "runs/first/specs/demo"
    (root / selected).mkdir(parents=True)
    prepared = SquadPublicationTransaction.begin(root, run, "7" * 32).seal()
    with prepared.inspect_sources(tree_paths=(selected,), file_paths=()) as initial:
        manifest = snapshot_source_manifest(trees=initial.trees, files=initial.files)
    authority = IdentityStore.initialize(root)
    source = authority.register_source_context(
        spec_id="demo", context_id="source", operation_id="source-registration",
        manifest=manifest,
    )
    record = authority.register_managed_identity(
        spec_id="demo", operation_id="managed-registration",
        request=ManagedIdentityRequest(
            source["workspace_uuid"], source["epoch_uuid"], "first", "source",
            selected, "source-registration", manifest.sha256,
        ),
    )
    state = SquadStateStore(run)
    state.initialize(
        run_id="first", mode="greenfield", user_message="Retain the managed spec",
        token_budget=1000, entry_phase="DONE", autonomy_mode=mode,
        managed_identity=record,
    )
    provider = MagicMock()
    controller = SquadController(
        provider=provider, state_store=state, phase_graph=graph or TerminalGraph(),
        ext_dir=root / "extension", project_root=root, squad_dir=run,
    )
    return controller, state, provider, authority


def observe_legacy_entry(monkeypatch, controller):
    calls = []
    monkeypatch.setattr(controller, "_drain_pending_controller_completion", lambda: (
        calls.append("recovery") or SimpleNamespace(recovered=False, manual_phase_run=False)
    ))
    monkeypatch.setattr(controller, "_emit_pending_retarget_comparison", lambda: calls.append("retarget"))
    monkeypatch.setattr(controller, "_cleanup_controller_completion_orphans", lambda: calls.append("cleanup") or True)

    def execute(*args, **kwargs):
        calls.append("execute")
        return SquadResult(status="completed", phase="DONE", run_id="first")

    monkeypatch.setattr(controller, "_run_locked", execute)
    monkeypatch.setattr(controller, "_run_single_phase_locked", execute)
    return calls


def test_managed_run_refuses_legacy_recovery_before_any_effect(tmp_path, monkeypatch, secure_posix):
    controller, state, provider, _ = managed_controller(tmp_path)
    calls = observe_legacy_entry(monkeypatch, controller)
    state_path = state.squad_dir / "state.json"
    before_state = state_path.read_bytes()
    before_sql = sql_state(tmp_path)

    result = controller.run(user_message="Retain the managed spec")

    assert result.status == "blocked"
    assert result.summary == BLOCKED
    assert calls == []
    assert state_path.read_bytes() == before_state
    assert sql_state(tmp_path) == before_sql
    provider.exec_agent.assert_not_called()


def remove_managed_metadata(state, **changes):
    """Deliberate raw fixture damage: production state writes prohibit removal."""
    path = state.squad_dir / "state.json"
    value = json.loads(path.read_bytes())
    value.pop("managed_identity")
    value.update(changes)
    path.write_text(json.dumps(value))


@pytest.mark.parametrize("mode", ["guided", "semi", "banzai"])
@pytest.mark.parametrize("entry", ["run", "run_single_phase"])
@pytest.mark.parametrize("removed", [False, True])
def test_public_entries_refuse_all_modes_before_legacy_callbacks(
    tmp_path, monkeypatch, secure_posix, mode, entry, removed,
):
    controller, state, provider, _ = managed_controller(tmp_path, mode=mode)
    if removed:
        remove_managed_metadata(state, run_id="changed", spec_id="changed")
    calls = observe_legacy_entry(monkeypatch, controller)
    path = state.squad_dir / "state.json"
    before, before_sql = path.read_bytes(), sql_state(tmp_path)

    result = (controller.run(user_message="Retain the managed spec", mode=mode)
              if entry == "run" else controller.run_single_phase("DONE", mode=mode))

    assert (result.status, result.phase, result.run_id, result.summary) == (
        "blocked", "DONE", "first", BLOCKED,
    )
    assert calls == []
    assert path.read_bytes() == before
    assert sql_state(tmp_path) == before_sql
    provider.exec_agent.assert_not_called()


@pytest.mark.parametrize("entry", ["run", "run_single_phase"])
def test_rejection_preserves_budget_dispatch_and_repair_state_with_real_phase_entry(
    tmp_path, monkeypatch, secure_posix, entry,
):
    controller, state, provider, _ = managed_controller(tmp_path, mode="banzai")
    value = state.load()
    value.update(status="blocked", blocked_reason="token_budget_exhausted", token_usage=1000)
    state.save(value)
    before, before_sql = (state.squad_dir / "state.json").read_bytes(), sql_state(tmp_path)
    touched = []
    def unexpected(*args, **kwargs):
        touched.append("legacy-write-boundary")
        pytest.fail("legacy writes must not be reached")
    for name in ("save", "claim_failed_automatic_decision_for_manual_phase_replay"):
        monkeypatch.setattr(state, name, unexpected)
    monkeypatch.setattr(controller, "_drain_pending_controller_completion", unexpected)
    result = controller.run() if entry == "run" else controller.run_single_phase("DONE")
    assert result.summary == BLOCKED
    assert touched == []
    assert (state.squad_dir / "state.json").read_bytes() == before
    assert sql_state(tmp_path) == before_sql
    provider.exec_agent.assert_not_called()


@pytest.mark.parametrize("entry", ["run", "run_single_phase"])
@pytest.mark.parametrize("lock_kind", ["workspace", "run"])
def test_managed_owner_keeps_existing_busy_lock_outcome(tmp_path, monkeypatch, secure_posix, entry, lock_kind):
    from echelon.spec_lifecycle import PhaseAExecutionLock, SpecRunExecutionLock

    controller, state, provider, _ = managed_controller(tmp_path)
    calls = observe_legacy_entry(monkeypatch, controller)
    before, before_sql = (state.squad_dir / "state.json").read_bytes(), sql_state(tmp_path)
    lock = PhaseAExecutionLock if lock_kind == "workspace" else SpecRunExecutionLock
    root = tmp_path if lock_kind == "workspace" else state.squad_dir
    with external_owner(lock, root):
        result = controller.run() if entry == "run" else controller.run_single_phase("DONE")
    assert result.status == "busy"
    assert calls == []
    assert (state.squad_dir / "state.json").read_bytes() == before
    assert sql_state(tmp_path) == before_sql
    provider.exec_agent.assert_not_called()


@contextmanager
def external_owner(lock, root):
    acquired, release = Event(), Event()
    failures = []
    def hold():
        try:
            with lock.acquire(root, "another-owner"):
                acquired.set()
                assert release.wait(timeout=5)
        except BaseException as error:
            failures.append(error)
            acquired.set()
    owner = Thread(target=hold)
    owner.start()
    try:
        assert acquired.wait(timeout=5)
        assert not failures
        yield
    finally:
        release.set()
        owner.join(timeout=5)
        assert not owner.is_alive()
        assert not failures


@pytest.mark.parametrize("authority_present", [False, True])
@pytest.mark.parametrize("entry", ["run", "run_single_phase"])
def test_genuine_legacy_control_reaches_execution_without_registry_writes(
    tmp_path, monkeypatch, authority_present, entry,
):
    root = tmp_path.resolve()
    state = SquadStateStore(root / "runs/legacy")
    state.initialize("legacy", "greenfield", "Legacy content", 1000, "DONE")
    if authority_present:
        authority = IdentityStore.initialize(root)
        authority.import_identities(spec_id="legacy", operation_id="legacy-import", definitions=(("FR-old", "Old"),))
    before_sql = sql_state(root) if authority_present else None
    provider = MagicMock()
    controller = SquadController(
        provider=provider, state_store=state, phase_graph=TerminalGraph(),
        ext_dir=root / "extension", project_root=root, squad_dir=state.squad_dir,
    )
    calls = observe_legacy_entry(monkeypatch, controller)
    result = controller.run() if entry == "run" else controller.run_single_phase("DONE")
    assert result.status == "completed"
    assert calls == ["recovery", "retarget", "cleanup", "execute"]
    if authority_present:
        assert sql_state(root) == before_sql
    else:
        assert not (root / ".echelon/identity").exists()


def human_request(controller, state):
    from harness.human_input import HumanInputOption, HumanInputPolicy

    policy = HumanInputPolicy(
        source_kind="human_gate", producer_id="checkpoint-plan",
        reason_code="checkpoint_plan_decision_required", classification="operational",
        semi_policy="auto_if_recommended_low_risk", resolution_handler="gate_outcome",
        allow_free_text=False, allowed_phase_ids=frozenset({"DONE"}),
        allowed_target_phases=frozenset({"DONE"}), context_state_keys=("phase",),
        context_paths=(), options=(HumanInputOption(
            id="approve", label="Approve", description="Finish.", recommended=True,
            risk_level="low", next_phase="DONE", outcome="approved",
        ),),
    )
    registry = HumanInputPolicyRegistry((policy,))
    controller._human_input_registry = registry
    return registry.prepare(
        source_kind="human_gate", producer_id="checkpoint-plan", phase_id="DONE",
        reason_code=policy.reason_code, question="Approve this completion?",
        source_state_revision=state.load()["state_revision"],
    )


def test_refusal_does_not_consume_native_failed_decision_manual_replay_claim(tmp_path, secure_posix):
    from harness.human_input import HumanInputPolicy

    controller, state, provider, _ = managed_controller(tmp_path, mode="banzai")
    spec_dir = str(state.squad_dir / "specs/demo")
    value = state.load()
    value["spec_dir"] = spec_dir
    state.save(value)
    policy = HumanInputPolicy(
        source_kind="controller_safeguard", producer_id="agent_blocked",
        reason_code="human_clarification_required", classification="operational",
        semi_policy="auto_if_recommended_low_risk", resolution_handler="clarification_resume",
        allow_free_text=True, allowed_phase_ids=frozenset({"DONE"}),
        allowed_target_phases=frozenset({"DONE"}), context_state_keys=("phase",),
        context_paths=(), options=(),
    )
    request = HumanInputPolicyRegistry((policy,)).prepare(
        source_kind=policy.source_kind, producer_id=policy.producer_id,
        phase_id="DONE", reason_code=policy.reason_code, question="How should we continue?",
        recommended_answer="Continue", risk_level="low",
        source_state_revision=state.load()["state_revision"],
    )
    state.set_human_input_decision(request, initial_status="pending")
    pending = state.load()
    failed = state.fail_pending_human_input_decision(
        pending["blocked_decision"]["id"], expected_state_revision=pending["state_revision"],
        failure_code="fixture_setup_failure", v2_automatic_eligible=True,
    )
    updates = {"manual_phase_run": True, "spec_id": "demo", "spec_dir": spec_dir,
               "phase_run_source_spec_dir": spec_dir, "published_spec_dir": spec_dir}
    assert state.authorize_failed_automatic_decision_for_manual_phase_replay(
        "DONE", decision_id=failed["blocked_decision"]["id"],
        expected_state_revision=failed["state_revision"], v2_automatic_eligible=True,
        expected_spec_id="demo", expected_spec_dir=spec_dir, initial_state_updates=updates,
    )
    before, before_sql = (state.squad_dir / "state.json").read_bytes(), sql_state(tmp_path)

    assert controller.run_single_phase("DONE", initial_state_updates=updates).summary == BLOCKED

    # A real claim still succeeds once: rejected entry did not consume its capability.
    assert state.claim_failed_automatic_decision_for_manual_phase_replay("DONE") is True
    assert state.claim_failed_automatic_decision_for_manual_phase_replay("DONE") is False
    assert (state.squad_dir / "state.json").read_bytes() == before
    assert sql_state(tmp_path) == before_sql
    provider.exec_agent.assert_not_called()


@pytest.mark.parametrize("mode", ["guided", "semi", "banzai"])
@pytest.mark.parametrize("entry", ["handle", "apply", "pending", "answer"])
@pytest.mark.parametrize("removed", [False, True])
def test_human_input_boundaries_raise_handled_refusal_before_decision_effects(
    tmp_path, monkeypatch, secure_posix, mode, entry, removed,
):
    from harness.human_input import AppliedHumanInputResolution, HumanInputPolicyError

    controller, state, provider, _ = managed_controller(tmp_path, mode=mode)
    request = human_request(controller, state)
    if entry != "handle":
        state.set_human_input_decision(request, initial_status="awaiting_human" if entry == "answer" else "pending")
    if removed:
        remove_managed_metadata(state)
    snapshot = state.load()
    before, before_sql = (state.squad_dir / "state.json").read_bytes(), sql_state(tmp_path)
    calls = []
    def unexpected(*args, **kwargs):
        calls.append("effect")
        pytest.fail("human input admission must precede all effects")
    for name in ("set_human_input_decision", "apply_human_input_state_resolution",
                 "reopen_failed_proportional_controller_decision", "recover_interrupted_human_input_decision"):
        monkeypatch.setattr(state, name, unexpected)
    monkeypatch.setattr(controller, "_drain_pending_controller_completion", unexpected)
    with pytest.raises(HumanInputPolicyError) as raised:
        if entry == "handle":
            controller.handle_human_input(request)
        elif entry == "apply":
            controller.apply_human_input_resolution(
                snapshot["blocked_decision"]["id"], expected_state_revision=snapshot["state_revision"],
                resolution=AppliedHumanInputResolution(selected_option_id="approve", answer_text=None, resolved_by="user"),
            )
        elif entry == "pending":
            controller.resume_pending_human_input()
        else:
            controller.resume_with_human_input("approve")
    assert str(raised.value) == BLOCKED
    assert raised.value.__cause__ is None and raised.value.__context__ is None
    assert calls == []
    assert (state.squad_dir / "state.json").read_bytes() == before
    assert sql_state(tmp_path) == before_sql
    provider.exec_agent.assert_not_called()


@pytest.mark.parametrize("entry", ["run", "pending", "answer"])
def test_removed_metadata_preserves_real_pending_completion_and_publication_stages(
    tmp_path, monkeypatch, secure_posix, entry,
):
    from harness.human_input import HumanInputPolicyError
    from harness.squad_completion import prepare_controller_completion

    controller, state, provider, _ = managed_controller(tmp_path)
    root = tmp_path.resolve()
    transaction = SquadPublicationTransaction.begin(root, state.squad_dir, "8" * 32)
    staged = transaction.build_path("retained-spec")
    staged.write_bytes(b"# Retained candidate\n")
    transaction.add_write(
        Path("runs/first/specs/demo/spec.md"), staged,
        owned_paths={Path("runs/first/specs/demo/spec.md")},
    )
    publication = transaction.seal()
    prepared = prepare_controller_completion(
        root, state.squad_dir, completion_id="9" * 32, origin="terminal",
        publication={"kind": "external", "marker": publication.marker.to_dict()},
        route={"kind": "terminal", "terminal_phase": "DONE"}, effect_plan=(),
        checkpoint_prestate={"kind": "none"}, context_reason="retained completion",
        mine_phase_a=False, judgment_payload_sha256=(), judgments=(),
    )
    state.begin_terminal_controller_completion(prepared, snapshot=state.capture_routing_snapshot())
    remove_managed_metadata(state)
    before = {str(path.relative_to(state.squad_dir)): (path.stat().st_mode, path.read_bytes())
              for path in state.squad_dir.rglob("*") if path.is_file()}
    before_sql = sql_state(root)
    calls = []
    def unexpected():
        calls.append("drain")
        pytest.fail("retained managed stages must not reach recovery")
    monkeypatch.setattr(controller, "_drain_pending_controller_completion", unexpected)
    if entry == "run":
        assert controller.run().summary == BLOCKED
    else:
        with pytest.raises(HumanInputPolicyError, match=BLOCKED):
            controller.resume_pending_human_input() if entry == "pending" else controller.resume_with_human_input("approve")
    assert calls == []
    after = {str(path.relative_to(state.squad_dir)): (path.stat().st_mode, path.read_bytes())
             for path in state.squad_dir.rglob("*") if path.is_file()}
    # Execution leases may create their own lock file; all retained artifacts stay exact.
    assert {key: after[key] for key in before} == before
    assert not (root / "runs/first/specs/demo/spec.md").exists()
    assert sql_state(root) == before_sql
    provider.exec_agent.assert_not_called()
