"""The requesting WHY1 re-runs against accepted refreshed producer output."""
from dataclasses import replace
from copy import deepcopy
import json

import pytest

from tests.unit.test_synthesis_refresh_publication import (
    case, enrolled, turn_prepared, prepared, checkpoint_case, selection,
    install_why1, RefreshExecutor,
)
from tests.unit.test_discovery_completion import controller


class RereviewExecutor(RefreshExecutor):
    def run_inspection_turn(self, *args, **kwargs):
        assignment = json.loads(args[1].split("\nHOST_INPUT_JSON\n", 1)[1])["assignment"]
        rereview = assignment.get("producer") == "why1" and any(
            call["assignment"]["operation_id"].startswith("synthesizer-") for call in self.calls)
        if rereview:
            self.why_verdict = "PASS"
            self.report = self.report.replace("**HIGH:** 1", "**HIGH:** 0").replace("**LOW:** 0", "**LOW:** 1").replace(
                "**Verdict:** FAIL", "**Verdict:** PASS").replace("**Severity:** HIGH", "**Severity:** LOW").replace(
                "Camera evidence is incomplete.", "Camera uncertainty is explicitly recorded for the scene prototype.")
        response = super().run_inspection_turn(*args, **kwargs)
        if rereview and assignment["step"] == "propose":
            reply = json.loads(response.stdout)
            reply["revisions"] = [dict(id=label, expected_revision=revision) for label, revision in assignment["editable_revisions"]]
            return replace(response, stdout=json.dumps(reply))
        return response


@pytest.mark.parametrize("provider", ["codex", "claude"])
def test_repair_refresh_returns_to_why1_and_reaches_constitution(checkpoint_case, provider, monkeypatch):
    from harness.discovery_producer import tracker_round
    root, store, identity, _ = checkpoint_case
    install_why1(checkpoint_case)
    executor = RereviewExecutor(provider)
    selected = {**selection(checkpoint_case), "through_phase": "phase1-why1"}
    assert controller(checkpoint_case, executor).run(managed_discovery=selected,
        create_managed_discovery=True).phase == "phase1-discover"
    original = store.load()["managed_why1_rounds"]
    from harness import discovery_publication
    from harness.discovery_completion import decode_binding, _refresh_predecessor, _require_refresh_dependencies, _released_discovery_projections
    from harness.element_identity_publication import encode_publication_request
    from harness.squad_completion import CompletionError
    prepare = discovery_publication.prepare_discovery_publication
    checked = []
    def check_proof(*args, **kwargs):
        package = prepare(*args, **kwargs)
        if kwargs.get("producer") != "why1":
            return package
        state = store.load()
        why = tracker_round(state, producer="why1")
        recovery = json.loads(package.request.recovery_payload)
        assert recovery["version"] == 11
        payload = dict(kind="external", marker=package.publication.marker.to_dict(),
            managed_discovery=dict(version=1, request=encode_publication_request(package.request)))
        decoded = decode_binding(payload, state=state)
        previous = _refresh_predecessor(root, store.squad_dir, state, why, producer="why1")
        arguments = (previous, why["refresh"]["predecessor_source"], decoded.sources, decoded.source,
            state["managed_discovery_bootstrap"]["selection"], store.squad_dir, root)
        _require_refresh_dependencies(why, *arguments, producer="why1")
        changed = deepcopy(why)
        changed["execution_input"]["dependencies"]["after_sha256"] = "0" * 64
        with pytest.raises(ValueError): _require_refresh_dependencies(changed, *arguments, producer="why1")
        for damage in ("version", "input", "parent", "predecessor", "comparison"):
            changed = deepcopy(recovery)
            if damage == "version":
                changed["version"] = 6
                for key in ("refresh", "execution_input", "predecessor", "tracker_parent"): del changed[key]
            elif damage == "input": changed["source_completion"] = why["source"]
            elif damage == "parent": changed["tracker_parent"] = original["rounds"][original["active"]]["tracker_parent"]
            elif damage == "predecessor": changed["predecessor"] = "why1-" + "0" * 32
            else: changed["execution_input"]["dependencies"]["after_sha256"] = "0" * 64
            forged = replace(package.request, recovery_payload=json.dumps(changed, sort_keys=True, separators=(",", ":")))
            envelope = {**payload, "managed_discovery": dict(version=1, request=encode_publication_request(forged))}
            with pytest.raises(CompletionError): decode_binding(envelope, state=state)
        # A well-shaped, retained but wrong Tracker must also fail traversal,
        # independently of the state-vs-envelope equality check above.
        wrong = replace(decoded, recovery={**decoded.recovery,
            "tracker_parent": original["rounds"][original["active"]]["tracker_parent"]})
        with pytest.raises(CompletionError):
            _released_discovery_projections(root, store.squad_dir, state,
                source=why["execution_input"]["source"], historical=True, refresh_child=wrong)
        checked.append(recovery)
        return package
    monkeypatch.setattr(discovery_publication, "prepare_discovery_publication", check_proof)
    result = controller(checkpoint_case, executor).run(managed_discovery=selected)
    assert result.phase == "phase1-constitution", result
    saved = store.load()
    why = tracker_round(saved, producer="why1")
    assert why["operation"] is not None
    assert why["execution_input"]["source"] != why["refresh"]["repair_source"]
    assert saved["phase_dispatch_counts"]["phase1-why1"] == 2
    assert saved["token_usage"] == 168 and len(executor.calls) == 24
    assert len(checked) == 1
    assert all(saved["managed_why1_rounds"]["rounds"][key] == value for key, value in original["rounds"].items())
    history = identity.identity_history(spec_id="game")
    assert controller(checkpoint_case, executor).run(managed_discovery=selected).phase == "phase1-constitution"
    assert store.load() == saved and len(executor.calls) == 24
    assert identity.identity_history(spec_id="game") == history


def test_rereview_recovers_binding_publication_and_answer_with_old_why1_history(checkpoint_case, monkeypatch):
    from harness.discovery_producer import tracker_round
    from harness.element_identity_store import IdentityStore
    from harness.tracker_clarification import previous_records
    from tests.unit.test_discovery_turns import Interrupted
    root, store, identity, _ = checkpoint_case
    state = store.load()
    state["autonomy_mode"] = "guided"
    store.save(state)
    install_why1(checkpoint_case)
    executor = RereviewExecutor("claude")
    executor.why_verdict = "STOP_AND_ASK"
    selected = {**selection(checkpoint_case), "through_phase": "phase1-why1"}
    result = controller(checkpoint_case, executor).run(managed_discovery=selected, create_managed_discovery=True)
    assert result.summary == "human_clarification_required" and result.phase == "phase1-why1", result
    assert controller(checkpoint_case, executor).resume_with_human_input("Single player")
    executor.why_verdict = "FAIL"
    assert controller(checkpoint_case, executor).run(managed_discovery=selected).phase == "phase1-discover"
    original = deepcopy(store.load()["managed_why1_rounds"])
    bind = store.bind_refresh_input
    def interrupt_binding(producer, *args, **kwargs):
        saved = bind(producer, *args, **kwargs)
        if producer == "why1":
            raise Interrupted()
        return saved
    with monkeypatch.context() as patch:
        patch.setattr(store, "bind_refresh_input", interrupt_binding)
        with pytest.raises(Interrupted): controller(checkpoint_case, executor).run(managed_discovery=selected)
    bound = store.load()
    assert bound["phase"] == "phase1-why1" and tracker_round(bound, producer="why1")["operation"] is None
    assert len(executor.calls) == 24 and bound["token_usage"] == 168
    target = root / "specs/game/issues.md"
    raw = target.read_bytes()
    try:
        target.write_bytes(raw + b"Unexpected change before re-review\n")
        assert controller(checkpoint_case, executor).run(managed_discovery=selected).status == "blocked"
        assert store.load() == bound and len(executor.calls) == 24
    finally:
        target.write_bytes(raw)
    turn = executor.run_inspection_turn
    def ask_again(*args, **kwargs):
        response = turn(*args, **kwargs)
        reply = json.loads(response.stdout)
        if reply.get("producer") == "why1" and reply["step"] == "author" and "**Question:** Which lighting?" not in json.dumps(executor.calls[-1]["context"]["evidence"]):
            reply["routing"] = dict(verdict="STOP_AND_ASK", question="Which lighting?", recommended_answer=None, risk_level=None)
            reply["artifacts"]["assumption-review.md"] = reply["artifacts"]["assumption-review.md"].replace("Verdict: PASS", "Verdict: FAIL")
        return replace(response, stdout=json.dumps(reply))
    monkeypatch.setattr(executor, "run_inspection_turn", ask_again)
    apply = IdentityStore.apply_identity_publication
    def interrupt_publication(*args, **kwargs):
        apply(*args, **kwargs)
        raise Interrupted()
    with monkeypatch.context() as patch:
        patch.setattr(IdentityStore, "apply_identity_publication", interrupt_publication)
        with pytest.raises(Interrupted): controller(checkpoint_case, executor).run(managed_discovery=selected)
    result = controller(checkpoint_case, executor).run(managed_discovery=selected)
    assert result.summary == "human_clarification_required" and len(executor.calls) == 27, result
    with monkeypatch.context() as patch:
        patch.setattr(IdentityStore, "apply_identity_publication", interrupt_publication)
        with pytest.raises(Interrupted): controller(checkpoint_case, executor).resume_with_human_input("Daylight")
    result = controller(checkpoint_case, executor).run(managed_discovery=selected)
    assert result.phase == "phase1-constitution", result
    saved = store.load()
    assert len(executor.calls) == 30 and saved["token_usage"] == 210
    assert [(item.question, item.answer) for item in previous_records(saved, saved["managed_why1_rounds"]["active"], "why1")] == [
        ("Which audience?", "Single player"), ("Which lighting?", "Daylight")]
    assert all(saved["managed_why1_rounds"]["rounds"][key] == value for key, value in original["rounds"].items())
    history = identity.identity_history(spec_id="game")
    assert controller(checkpoint_case, executor).run(managed_discovery=selected).phase == "phase1-constitution"
    assert store.load() == saved and len(executor.calls) == 30
    assert identity.identity_history(spec_id="game") == history
