"""A resumed author consumes the released answer, never the old question head."""
from copy import deepcopy
import json

import pytest

from tests.unit.test_managed_alignment_resolution import (
    case, enrolled, turn_prepared, prepared, checkpoint_case,
    test_alignment_answer_application_recovers_without_redispatch as complete_answer,
)


def assert_answer_round(case, provider):
    from echelon.spec_lifecycle import PhaseAExecutionLock, SpecRunExecutionLock
    from harness.discovery_assessment import require_alignment_parent
    from harness.discovery_operation import run_discovery_operation
    from harness.discovery_producer import SOURCE_FIELDS, tracker_round
    from harness.discovery_spec import clarification_source, current_spec_source
    from harness.squad_state import StateAdvanceError
    from harness.squad_completion import CompletionError
    from tests.unit.test_managed_alignment import capture
    from tests.unit.test_managed_alignment_execution import AlignmentExecutor
    from tests.unit.test_managed_checkpoint_assess import selection
    root, store, identity, _ = case
    before, history = store.load(), identity.identity_history(spec_id="game")
    source = clarification_source(before["last_human_input_completion"])
    old_source = {key: before["last_dispatch"][key] for key in SOURCE_FIELDS}
    existing = tracker_round(before, producer="alignment")
    already_selected = existing["resolution"] is not None
    predecessor = existing["predecessor"] if already_selected else before["managed_alignment_rounds"]["active"]
    documents = {p.relative_to(root).as_posix(): p.read_bytes()
        for tree in (root / "specs/game", store.staging_dir) for p in tree.rglob("*") if p.is_file()}
    executor = AlignmentExecutor(provider)
    args = dict(input_tree=selection(case)["input_tree"], artifact_paths=("intent-alignment-check.md",),
        unowned_writable_paths=("intent-alignment-check.md",),
        intent=dict(kind="align", request="Reassess alignment using the published movement answer"), producer="alignment")
    with PhaseAExecutionLock.acquire(root, "test-answer-round"):
        with SpecRunExecutionLock.acquire(store.squad_dir, "test-answer-round"):
            parent = require_alignment_parent(root, store.squad_dir, before, source)
            assert parent.recovery["version"] == 41 and parent.candidate["route"] == "phase2-tracker-alignment"
            assert current_spec_source(root, before, "alignment") == source
            with pytest.raises(ValueError): require_alignment_parent(root, store.squad_dir, before, old_source)
            selected = store.prepare_spec_round("alignment", source, expected_state=before)
            assert store.prepare_spec_round("alignment", source, expected_state=selected) == selected
            row = tracker_round(selected, producer="alignment")
            assert row == dict(source=source, resolution=dict(decision=before["blocked_decision"],
                completion=before["last_human_input_completion"]), predecessor=predecessor,
                operation=existing["operation"] if already_selected else None, turns=existing["turns"] if already_selected else None)
            with pytest.raises(StateAdvanceError): store.prepare_spec_round("alignment", old_source, expected_state=selected)
            if not already_selected:
                with pytest.raises(StateAdvanceError): store.prepare_spec_round("alignment", source, expected_state=before)
            require_alignment_parent(root, store.squad_dir, selected, source)
            captured = capture(case)
            assert "Use WASD" in captured[2]["runs/first/staging/user-clarifications.md"]
            for damage in ("answer", "receipt", "predecessor", "historical", "count", "typed_count", "budget", "typed_budget", "charge"):
                changed = deepcopy(selected)
                current = changed["managed_alignment_rounds"]["rounds"][changed["managed_alignment_rounds"]["active"]]
                if damage == "answer": current["resolution"]["decision"]["answer_text"] = "Use arrows"
                elif damage == "receipt": current["resolution"]["completion"]["intent_sha256"] = "0" * 64
                elif damage == "predecessor": current["predecessor"] = None
                elif damage == "historical": changed["managed_alignment_rounds"]["rounds"][predecessor]["operation"] = None
                elif damage == "count": changed["phase_dispatch_counts"]["phase2-tracker-alignment"] += 1
                elif damage == "typed_count": changed["phase_dispatch_counts"]["phase2-tracker-alignment"] = float(changed["phase_dispatch_counts"]["phase2-tracker-alignment"])
                elif damage == "budget": changed["iteration"] += 1
                elif damage == "typed_budget": changed["iteration"] = float(changed["iteration"])
                else: changed["token_usage"] += 1
                with pytest.raises((ValueError, CompletionError)): require_alignment_parent(root, store.squad_dir, changed, source)
            from tests.unit.test_discovery_turns import Interrupted
            advance = store.advance_discovery_operation
            interruptions = []
            def interrupted_finish(binding, event, **kwargs):
                result = advance(binding, event, **kwargs)
                if event == "finish":
                    interruptions.append(event)
                    raise Interrupted()
                return result
            with pytest.MonkeyPatch.context() as patch:
                patch.setattr(store, "advance_discovery_operation", interrupted_finish)
                with pytest.raises(Interrupted):
                    run_discovery_operation(root, store, executor, **args, create=True)
            assert interruptions == ["finish"] and len(executor.calls) == 3
            result = run_discovery_operation(root, store, executor, **args)
            assert result.status == "reviewed", result.reason
            assert result.dispatch_count == 3 and result.token_usage == 21
            assert result.candidate.operations == () and result.candidate.history == history
            accepted = store.load()
            replay = run_discovery_operation(root, store, executor, **args, replay_only=True)
            assert replay.candidate == result.candidate and len(executor.calls) == 3
            assert [call["assignment"]["step"] for call in executor.calls] == ["propose", "author", "review"]
            assert all("Use WASD" in json.dumps(call) for call in executor.calls)
            require_alignment_parent(root, store.squad_dir, accepted, source)
            from tests.unit.test_discovery_completion import controller
            from harness.human_input import HumanInputPolicyError
            ctrl = controller(case, executor)
            assert ctrl.resume_pending_human_input() is False
            with pytest.raises(HumanInputPolicyError): ctrl.resume_with_human_input("Replace the saved answer")
            assert store.load() == accepted and len(executor.calls) == 3
    assert accepted["managed_alignment_rounds"]["rounds"][predecessor] == before["managed_alignment_rounds"]["rounds"][predecessor]
    assert accepted["phase_dispatch_counts"]["phase2-tracker-alignment"] == before["phase_dispatch_counts"]["phase2-tracker-alignment"] + 1
    for key in ("blocked_decision", "last_human_input_completion", "last_dispatch", "token_usage", "iteration",
            "max_iterations", "feasibility_structural_attempts", "governance_gate_exhausted"):
        assert (key in accepted, accepted.get(key)) == (key in before, before.get(key))
    assert identity.identity_history(spec_id="game") == history and identity.pending_identity_publication(spec_id="game") is None
    assert {p.relative_to(root).as_posix(): p.read_bytes()
        for tree in (root / "specs/game", store.staging_dir) for p in tree.rglob("*") if p.is_file()} == documents
    assert not accepted["phase_dispatch_counts"].get("phase3-specialists")


@pytest.mark.parametrize("provider,mode", [("codex", "guided"), ("claude", "banzai")])
def test_released_answer_drives_one_resumed_alignment_author(checkpoint_case, provider, mode):
    complete_answer(checkpoint_case, provider, mode)
    assert_answer_round(checkpoint_case, provider)
