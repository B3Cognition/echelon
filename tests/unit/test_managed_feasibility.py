"""Feasibility starts from real released Phase 1 approval, never phase labels."""
from copy import deepcopy
import os
from pathlib import Path

import pytest

from harness import discovery_assessment as assessment
from harness.discovery_spec import clarification_source
from harness.squad_completion import CompletionError
from tests.unit.test_managed_checkpoint_assess import (
    case, enrolled, turn_prepared, prepared, checkpoint_case,
    test_managed_checkpoint_uses_native_policy_and_stops_before_phase2 as complete_checkpoint,
)


def parent(case, state=None, source=None):
    root, store, _, _ = case
    state = store.load() if state is None else state
    function = getattr(assessment, "require_feasibility_parent", None)
    assert callable(function), "Feasibility must authenticate its released checkpoint predecessor"
    return function(root, store.squad_dir, state,
        clarification_source(state["last_human_input_completion"]) if source is None else source)


def assert_released_feasibility_parent(case, *, approved):
    """Also usable against retained real corridors without editing their state."""
    _, store, identity, _ = case
    before = store.load()
    history = identity.identity_history(spec_id="game")
    if not approved:
        with pytest.raises((ValueError, CompletionError)):
            parent(case)
        forged = deepcopy(before)
        forged.update(phase="phase2-decide", status="running")
        forged["blocked_decision"]["selected_option_id"] = "approve"
        with pytest.raises((ValueError, CompletionError)):
            parent(case, forged)
    else:
        binding = parent(case)
        assert binding.producer == "checkpoint" and binding.recovery["version"] == 30
        assert binding.candidate["route"] == "phase2-decide"
        assert binding.recovery["resolution"]["selected_option_id"] == "approve"
        source = clarification_source(before["last_human_input_completion"])
        for damage in ("phase", "status", "decision", "receipt", "cancelled", "source"):
            altered = deepcopy(before)
            selected = dict(source)
            if damage == "phase": altered["phase"] = "phase3-specialists"
            elif damage == "status": altered["status"] = "blocked"
            elif damage == "decision": altered["blocked_decision"]["selected_option_id"] = "reject"
            elif damage == "receipt": altered["last_human_input_completion"]["intent_sha256"] = "0" * 64
            elif damage == "cancelled": altered["cancel_requested"] = True
            else: selected["dispatch_id"] = "0" * 32
            with pytest.raises((ValueError, CompletionError)):
                parent(case, altered, selected)
    assert store.load() == before
    assert identity.identity_history(spec_id="game") == history


def assert_approval_cannot_authorize_structural_retry(case):
    from harness.discovery_producer import tracker_rounds
    _, store, _, _ = case
    state = deepcopy(store.load())
    rounds = state["managed_feasibility_rounds"]
    previous = rounds["active"]
    operation = rounds["rounds"][previous]["operation"]
    operation["attempts"] = [dict(number=1, result=dict(status="accepted",
        candidate_sha256="c" * 64, findings_sha256="d" * 64))]
    current = "feasibility-" + "b" * 32
    rounds["active"] = current
    source = dict(rounds["rounds"][previous]["source"], dispatch_id="b" * 32)
    rounds["rounds"][current] = dict(source=source, predecessor=previous,
        resolution=None, operation=None, turns=None)
    assert tracker_rounds(state, "feasibility")["active"] == current
    with pytest.raises((ValueError, CompletionError)):
        parent(case, state)


def test_feasibility_requires_released_approval_entry():
    function = getattr(assessment, "require_feasibility_parent", None)
    assert callable(function), "Feasibility must authenticate its released checkpoint predecessor"
    with pytest.raises(ValueError):
        function(Path("/not-a-workspace"), Path("/not-a-workspace/runs/first"),
            dict(phase="phase2-decide", status="running"), {})


def capture(case):
    from harness.discovery_bootstrap_state import bootstrap_from_state
    from harness.discovery_operation import _capture
    from harness.discovery_assessment import ASSESSMENT_OUTPUTS
    from tests.unit.test_managed_checkpoint_assess import selection
    root, store, identity, _ = case
    state = store.load()
    return _capture(root, store, identity, bootstrap_from_state(state), selection(case)["input_tree"],
        tuple(ASSESSMENT_OUTPUTS["feasibility"]), producer="feasibility")


def assert_feasibility_capture(case):
    root, store, identity, _ = case
    before = store.load()
    history = identity.identity_history(spec_id="game")
    fingerprint, baseline, evidence, captured_history, templates, runtime, sources, inputs = capture(case)
    assert set(templates) == {"feasibility.md", "prioritization.md", "estimates.md", "mvp-scope.md", "kill-report.md"}
    assert {"spec.md", "glossary.md", "requirements-overview.md", "assumptions.md", "issues.md"} <= set(baseline)
    assert all(templates.values())
    assert captured_history == history
    assert not sources.publication.operations
    assert inputs["authority"]["source_context"]["operation_id"] == (
        "discovery-completion-" + before["last_human_input_completion"]["completion_id"])
    assert runtime["autonomy_mode"] == before["autonomy_mode"]
    journal = (store.squad_dir / "reasoning-journal.jsonl").relative_to(root).as_posix()
    assert evidence[journal]
    if not (root / journal).exists():
        assert evidence[journal] == "[ABSENT: " + journal + "]"
    for name in ("calibration-profile.yaml", "estimates-log.yaml"):
        path = "knowledge-base/" + name
        if not (root / path).exists():
            assert evidence[path] == "[ABSENT: " + path + "]"
    assert len(fingerprint) == 64
    assert store.load() == before and identity.identity_history(spec_id="game") == history


def assert_feasibility_capture_refuses_changed_inputs(case):
    """Fault checks for a test-owned workspace; restore exact bytes each time."""
    root, store, identity, _ = case
    before = store.load()
    history = identity.identity_history(spec_id="game")
    # An unchanged released approval cannot cover later source/context edits.
    for relative in ("specs/game/spec.md", "runs/first/context/current-feature-context.md"):
        path = root / relative
        original = path.read_bytes()
        original_stat = path.stat()
        try:
            path.write_bytes(original + b"\nUnapproved changed input.\n")
            with pytest.raises((ValueError, CompletionError)):
                capture(case)
        finally:
            path.write_bytes(original)
            # Native Lexicon evidence checks source/report freshness as well
            # as content. Undo the test's mutation, including its timestamp.
            os.utime(path, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
        assert_feasibility_capture(case)
    # A missing required template cannot silently disable the authored contract.
    template = root / ".echelon/runtime/templates/kill-report.md"
    held = template.with_name("kill-report.test-held")
    assert not held.exists()
    template.rename(held)
    try:
        with pytest.raises(ValueError, match="discovery_template_missing"):
            capture(case)
    finally:
        held.rename(template)
    assert store.load() == before and identity.identity_history(spec_id="game") == history


def assert_feasibility_capture_preserves_populated_evidence(case):
    """Use test-owned cold inputs, then restore their original absence."""
    root, store, identity, _ = case
    before = store.load()
    history = identity.identity_history(spec_id="game")
    payloads = {
        "knowledge-base/calibration-profile.yaml": b"human_rate_usd: 120\r\n",
        "knowledge-base/estimates-log.yaml": b"entries: []\n",
        "runs/first/reasoning-journal.jsonl": b'{"phase":"phase1-what","summary":"Movement scope retained."}\n',
    }
    assert all(not (root / name).exists() for name in payloads)
    knowledge = root / "knowledge-base"
    created = not knowledge.exists()
    knowledge.mkdir(exist_ok=True)
    try:
        for name, content in payloads.items():
            (root / name).write_bytes(content)
        evidence = capture(case)[2]
        for name, content in payloads.items():
            assert evidence[name].encode("utf-8") == content
    finally:
        for name in payloads:
            (root / name).unlink(missing_ok=True)
        if created:
            knowledge.rmdir()
    assert store.load() == before and identity.identity_history(spec_id="game") == history


def assert_reviewed_feasibility(case, provider, *, feasibility_text=None):
    """Exercise the real operation owner after authenticated checkpoint release."""
    import json
    from echelon.spec_lifecycle import PhaseAExecutionLock, SpecRunExecutionLock
    from harness.discovery_assessment import ASSESSMENT_OUTPUTS
    from harness.discovery_operation import run_discovery_operation
    from harness.discovery_producer import tracker_round
    from tests.unit.test_managed_checkpoint_assess import selection
    from tests.unit.test_managed_feasibility_rounds import FeasibilityExecutor
    root, store, identity, _ = case
    executor = FeasibilityExecutor(provider, **({} if feasibility_text is None else dict(feasibility_text=feasibility_text)))
    before = store.load()
    history = identity.identity_history(spec_id="game")
    sources = {path.name: path.read_bytes() for path in (root / "specs/game").iterdir() if path.is_file()}
    paths = tuple(ASSESSMENT_OUTPUTS["feasibility"])
    args = dict(input_tree=selection(case)["input_tree"], artifact_paths=paths,
        unowned_writable_paths=paths, intent=dict(kind="assess", request="Assess the approved game specification"),
        producer="feasibility")
    with PhaseAExecutionLock.acquire(root, "test-feasibility"):
        with SpecRunExecutionLock.acquire(store.squad_dir, "test-feasibility"):
            parent(case)
            store.prepare_spec_round("feasibility", clarification_source(before["last_human_input_completion"]), expected_state=before)
            result = run_discovery_operation(root, store, executor, create=True, **args)
            assert result.status == "reviewed", (result.reason, len(executor.calls))
            assert result.dispatch_count == 3 and result.token_usage == 21
            assert result.candidate.operations == () and result.candidate.history == history
            assert json.loads(result.candidate.candidate_inputs)["routing"] == dict(verdict="PASS", state_updates={})
            assert executor.calls[0]["context"]["reply_fields"] == dict(new_subjects=[], revisions=[])
            assert "routing" in executor.calls[1]["context"]["reply_fields"]
            assert executor.calls[2]["assignment"]["routing"] == dict(verdict="PASS", state_updates={})
            assert_approval_cannot_authorize_structural_retry(case)
            retained = store.load()
            for _ in range(2):
                replay = run_discovery_operation(root, store, executor, replay_only=True, **args)
                assert replay == result
                assert len(executor.calls) == 3 and store.load() == retained
    row = tracker_round(store.load(), producer="feasibility")
    assert row["operation"]["attempts"][-1]["result"]["status"] == "accepted"
    assert store.load()["phase_dispatch_counts"]["phase2-decide"] == 1
    assert store.load()["phase"] == "phase2-decide"
    assert store.load()["blocked_decision"] == before["blocked_decision"]
    assert identity.identity_history(spec_id="game") == history
    assert {path.name: path.read_bytes() for path in (root / "specs/game").iterdir() if path.is_file()} == sources
    assert not store.load()["phase_dispatch_counts"].get("phase3-specialists")


@pytest.mark.parametrize("provider,mode,enabled,answer", [
    ("codex", "guided", False, "approve"),
    ("claude", "banzai", True, "approve"),
    ("claude", "semi", False, "reject"),
])
def test_feasibility_parent_is_real_native_checkpoint(checkpoint_case, provider, mode, enabled, answer):
    complete_checkpoint(checkpoint_case, provider, mode, enabled, answer)
    assert_released_feasibility_parent(checkpoint_case, approved=answer == "approve")
    if answer == "approve":
        assert_feasibility_capture(checkpoint_case)
        assert_feasibility_capture_refuses_changed_inputs(checkpoint_case)
        assert_feasibility_capture_preserves_populated_evidence(checkpoint_case)
        assert_reviewed_feasibility(checkpoint_case, provider)
