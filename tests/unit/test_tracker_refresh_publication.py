"""Offline accepted Synthesis→Tracker input admission and proof execution."""
from copy import deepcopy
from dataclasses import replace
import json

import pytest

from tests.unit.test_synthesis_refresh_publication import (
    case, enrolled, turn_prepared, prepared, checkpoint_case, controller,
    publish_synthesis_refresh,
)


def bind_tracker(root, store):
    from echelon.spec_lifecycle import PhaseAExecutionLock, SpecRunExecutionLock
    from harness.discovery_repair_admission import bind_repair_refresh_input
    with PhaseAExecutionLock.acquire(root, "test-tracker-refresh"):
        with SpecRunExecutionLock.acquire(store.squad_dir, "test-tracker-refresh"):
            return bind_repair_refresh_input(root, store, "tracker")


@pytest.mark.parametrize("provider", ["codex", "claude"])
def test_tracker_binds_accepted_synthesis_not_repair(checkpoint_case, provider, monkeypatch):
    from harness.discovery_producer import tracker_round, SOURCE_FIELDS
    from harness.squad_state import SquadStateStore, StateAdvanceError
    root, store, identity, _ = checkpoint_case
    executor, request = publish_synthesis_refresh(checkpoint_case, provider, monkeypatch, prepare_tracker=True)
    before = store.load()
    history = identity.identity_history(spec_id="game")
    calls = len(executor.calls)
    owner = store.bind_refresh_input
    def raced(*args, **kwargs):
        store.save(store.load())
        return owner(*args, **kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(store, "bind_refresh_input", raced)
        with pytest.raises(StateAdvanceError): bind_tracker(root, store)
    assert "execution_input" not in tracker_round(store.load())
    before = store.load()
    saved = bind_tracker(root, store)
    row = tracker_round(saved)
    assert row["execution_input"]["source"] == {key: before["last_dispatch"][key] for key in SOURCE_FIELDS}
    assert row["execution_input"]["source"] != row["source"] == row["refresh"]["repair_source"]
    assert row["execution_input"]["dependencies"]["changed"]
    assert bind_tracker(root, SquadStateStore(store.squad_dir)) == saved
    assert identity.identity_history(spec_id="game") == history and len(executor.calls) == calls
    assert row["operation"] is None and row["turns"] is None
    assert saved["token_usage"] == before["token_usage"]
    from harness.element_identity_store import IdentityStore
    publication = IdentityStore.identity_publication
    def damaged_parent(self, **kwargs):
        value = publication(self, **kwargs)
        if kwargs["operation_id"] == "discovery-completion-" + row["execution_input"]["source"]["dispatch_id"]:
            return {**value, "completion_payload": "{}"}
        return value
    with monkeypatch.context() as patch:
        patch.setattr(IdentityStore, "identity_publication", damaged_parent)
        with pytest.raises(ValueError): bind_tracker(root, store)
    for target in (root / "specs/game/issues.md", root / ".echelon/runtime/templates/user-intent-template.md"):
        raw = target.read_bytes()
        try:
            target.write_bytes(raw + b"Changed accepted input\n")
            with pytest.raises(ValueError): bind_tracker(root, store)
        finally:
            target.write_bytes(raw)
    assert store.load() == saved and len(executor.calls) == calls
    from harness.discovery_operation import run_discovery_operation
    from harness.discovery_publication import prepare_discovery_publication
    from harness.discovery_completion import decode_binding, released_discovery_input_projectors
    from harness.element_identity_publication import encode_publication_request
    from harness.squad_completion import CompletionError
    from tests.integration.test_squad_controller import _install_prepared_routed_completion
    from tests.unit.test_discovery_completion import drain
    from tests.unit.test_discovery_turns import Interrupted
    paths = ("user-intent.md", "stakeholder-model.md")
    original = deepcopy(saved["managed_tracker_rounds"])
    retained_files = {path: path.read_bytes() for path in (
        *store.squad_dir.glob("*turns*.json"), *store.squad_dir.glob("*reservations*.json"),
        *store.staging_dir.glob("*")) if path.is_file()}
    old_reports = {path: (root / "specs/game" / path).read_bytes()
        for path in ("unknowns.md", "issues.md", "assumption-review.md")}
    revision = "2" if provider == "claude" else "1"
    # Test the operation/publication owners directly; automatic ordering is
    # still a separate guarded checkpoint, not simulated provider routing.
    active = deepcopy(saved)
    active["phase"] = "phase1-tracker"
    store.save(active)
    def execute():
        return run_discovery_operation(root, store, executor, producer="tracker", create=True,
            input_tree="inputs", artifact_paths=paths, editable_revisions=(("UI-000001", revision),),
            unowned_writable_paths=paths, intent=original["rounds"][row["predecessor"]]["operation"]["binding"]["intent"])
    before_dispatch = store.load()
    target = root / "specs/game/issues.md"
    raw = target.read_bytes()
    try:
        target.write_bytes(raw + b"Changed after binding, before dispatch\n")
        assert execute().status == "blocked"
        assert store.load() == before_dispatch and len(executor.calls) == calls
        assert identity.identity_history(spec_id="game") == history
    finally:
        target.write_bytes(raw)
    outcome = execute()
    assert outcome.status == "reviewed", outcome
    assert len(executor.calls) == calls + 3 and outcome.token_usage == 21
    if provider == "claude":
        evidence = json.dumps(executor.calls[-3]["context"]["evidence"])
        assert "Use arrow keys" in evidence and "Single player" in evidence
    package = prepare_discovery_publication(root, store, executor, producer="tracker", completion_id="e" * 32)
    recovery = json.loads(package.request.recovery_payload)
    assert recovery["version"] == 10
    assert recovery["source_completion"] == row["execution_input"]["source"]
    assert all(recovery[key] == row[key] for key in ("refresh", "execution_input", "predecessor"))
    ctrl = controller(checkpoint_case, executor)
    sealed = ctrl._prepare_spec_step_effects(from_phase="phase1-tracker", to_phase="phase1-why1",
        snapshot=store.capture_routing_snapshot(expected_phase="phase1-tracker"), manual_phase_run=False,
        conditional_skip=False, record_completion=True, publication_marker=package.publication.marker.to_dict(),
        completion_id="e" * 32, managed_discovery_request=encode_publication_request(package.request))
    assert decode_binding(sealed.intent.publication, state=store.load()).producer == "tracker"
    from harness.discovery_completion import _refresh_predecessor, _require_refresh_dependencies
    previous = _refresh_predecessor(root, store.squad_dir, store.load(), row, producer="tracker")
    decoded = decode_binding(sealed.intent.publication, state=store.load())
    arguments = (previous, row["refresh"]["predecessor_source"], decoded.sources, decoded.source,
        store.load()["managed_discovery_bootstrap"]["selection"], store.squad_dir, root)
    _require_refresh_dependencies(row, *arguments, producer="tracker")
    altered = deepcopy(row)
    altered["execution_input"]["dependencies"]["after_sha256"] = "0" * 64
    with pytest.raises(ValueError): _require_refresh_dependencies(altered, *arguments, producer="tracker")
    for damage in ("version", "source", "repair", "predecessor", "comparison"):
        changed = deepcopy(recovery)
        if damage == "version":
            changed["version"] = 4
            for key in ("refresh", "execution_input", "predecessor"): del changed[key]
        elif damage == "source": changed["source_completion"] = row["source"]
        elif damage == "repair": changed["refresh"]["repair_unit"] = "0" * 64
        elif damage == "predecessor": changed["predecessor"] = "tracker-" + "0" * 32
        else: changed["execution_input"]["dependencies"]["after_sha256"] = "0" * 64
        forged = replace(package.request, recovery_payload=json.dumps(changed, sort_keys=True, separators=(",", ":")))
        payload = deepcopy(sealed.intent.publication)
        payload["managed_discovery"]["request"] = encode_publication_request(forged)
        with pytest.raises(CompletionError): decode_binding(payload, state=store.load())
    _install_prepared_routed_completion(store, sealed, token_usage_delta=21)
    apply = IdentityStore.apply_identity_publication
    def interrupt(*args, **kwargs):
        apply(*args, **kwargs)
        raise Interrupted()
    with monkeypatch.context() as patch:
        patch.setattr(IdentityStore, "apply_identity_publication", interrupt)
        with pytest.raises(Interrupted): drain(ctrl)
    assert drain(controller(checkpoint_case, executor)).recovered
    completed = store.load()
    assert completed["phase"] == "phase1-why1" and completed["token_usage"] == saved["token_usage"] + 21
    assert completed["phase_dispatch_counts"]["phase1-tracker"] == saved["phase_dispatch_counts"]["phase1-tracker"] + 1
    assert all(completed["managed_tracker_rounds"]["rounds"][key] == value
        for key, value in original["rounds"].items() if key != original["active"])
    assert all(path.read_bytes() == raw for path, raw in retained_files.items())
    assert all((root / "specs/game" / path).read_bytes() == raw for path, raw in old_reports.items())
    heads = {item["element_id"]: item["revision"] for item in json.loads(identity.identity_history(spec_id="game").payload)["entities"]}
    # Re-evaluation alone must not manufacture a revision for unchanged intent.
    assert heads["UI-000001"] == revision and heads["U-000001"] == "4"
    source = {key: completed["last_dispatch"][key] for key in SOURCE_FIELDS}
    released_discovery_input_projectors(root, store.squad_dir, completed, source=source)
    assert len(executor.calls) == calls + 3 and not drain(controller(checkpoint_case, executor)).recovered


def test_refreshed_tracker_clarification_restarts_with_complete_history(checkpoint_case, monkeypatch):
    from harness.discovery_producer import tracker_round, SOURCE_FIELDS
    from harness.discovery_completion import released_discovery_input_projectors
    from harness.element_identity_store import IdentityStore
    from harness.tracker_clarification import previous_records
    from tests.unit.test_discovery_turns import Interrupted
    root, store, identity, _ = checkpoint_case
    executor, request = publish_synthesis_refresh(checkpoint_case, "claude", monkeypatch, prepare_tracker=True)
    saved = bind_tracker(root, store)
    saved["phase"] = "phase1-tracker"
    store.save(saved)
    request = {**request, "through_phase": "phase1-tracker"}
    provider_turn = executor.run_inspection_turn
    def ask_once(*args, **kwargs):
        response = provider_turn(*args, **kwargs)
        reply = json.loads(response.stdout)
        evidence = json.dumps(executor.calls[-1]["context"]["evidence"])
        if reply.get("producer") == "tracker" and reply["step"] == "author" and "**Question:** Which lighting style?" not in evidence:
            reply["routing"] = dict(verdict="STOP_AND_ASK", question="Which lighting style?",
                recommended_answer=None, risk_level=None)
        return replace(response, stdout=json.dumps(reply))
    monkeypatch.setattr(executor, "run_inspection_turn", ask_once)
    ctrl = controller(checkpoint_case, executor)
    result = ctrl.run(managed_discovery=request)
    assert result.phase == "phase1-tracker" and result.summary == "human_clarification_required", result
    before = store.load()
    assert before["blocked_decision"]["question"] == "Which lighting style?"
    assert before["token_usage"] == 189 and len(executor.calls) == 27
    old_history = identity.identity_history(spec_id="game")
    receipt_before = (store.staging_dir / "user-clarifications.md").read_bytes()
    apply = IdentityStore.apply_identity_publication
    def interrupt(*args, **kwargs):
        apply(*args, **kwargs)
        raise Interrupted()
    with monkeypatch.context() as patch:
        patch.setattr(IdentityStore, "apply_identity_publication", interrupt)
        with pytest.raises(Interrupted): ctrl.resume_with_human_input("Daylight")
    assert identity.identity_history(spec_id="game") == old_history
    result = controller(checkpoint_case, executor).run(managed_discovery=request)
    assert result.phase == "phase1-why1", result
    completed = store.load()
    assert completed["token_usage"] == 210 and len(executor.calls) == 30
    assert completed["phase_dispatch_counts"]["phase1-tracker"] == 4
    records = previous_records(completed, completed["managed_tracker_rounds"]["active"])
    assert [(item.question, item.answer) for item in records] == [
        ("Which movement controls?", "Use arrow keys"), ("Which audience?", "Single player"),
        ("Which lighting style?", "Daylight")]
    assert (store.staging_dir / "user-clarifications.md").read_bytes().startswith(receipt_before)
    assert tracker_round(completed)["resolution"]["decision"]["answer_text"] == "Daylight"
    released_discovery_input_projectors(root, store.squad_dir, completed,
        source={key: completed["last_dispatch"][key] for key in SOURCE_FIELDS})
    assert controller(checkpoint_case, executor).run(managed_discovery=request).phase == "phase1-why1"
    assert store.load() == completed and len(executor.calls) == 30
