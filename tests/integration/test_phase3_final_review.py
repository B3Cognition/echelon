"""Fixed-candidate review uses real executor, state, and sealed routing."""
import json
import hashlib
from pathlib import Path

import pytest

from harness.squad_provider import SquadAgentResult
from harness.squad_executors import ExecutorBlockedResult
from harness.squad_state import SquadStateStore
from tests.integration.test_phase3_review_scheduling import scheduling_fixture, advance


def final_fixture(tmp_path, mode, *, after_review=None, final_verdict="PASS", repairs=False, keep_plan=False, final_outcome="resolved"):
    ctrl, store, executor, _, spec, _ = scheduling_fixture(tmp_path, mode=mode)
    state = store.load()
    if not repairs:
        state.update(selected_issue_resolution=None, issue_resolution_ledger={})
    store.save(state)
    node = ctrl._graph.get("phase3-consensus")
    calls = []

    def dispatch(cwd, prompt, **kwargs):
        final = "## Fixed-candidate final review" in prompt
        payload = dict(verdict="PASS", state_updates={}, journal_entries=[])
        if "Operate in **WHY3**" in prompt:
            calls.append(("WHY3", final))
            payload["verdict"] = final_verdict if final else "PASS"
            marker = "## Phase 3 selected-issue review envelope\n```json\n"
            if marker in prompt:
                envelope = json.loads(prompt.split(marker)[1].split("\n```", 1)[0])
                payload["phase3_issue_review"] = dict(schema_version=2, selected_issue=envelope["selected_issue"],
                    outcome=final_outcome if final else "resolved", rationale="Checked current requirements", evidence_refs=["spec.md"])
            (spec / "issues.md").write_text("No issues" if payload["verdict"] == "PASS" else "New concrete failure")
            (spec / "quality-gates.md").write_text(f"Review revision {len(calls)}")
            if final and after_review:
                after_review(spec)
        elif "Operate in **ASSESS2**" in prompt:
            calls.append(("ASSESS2", final))
            (spec / "implementability-report.md").write_text(f"All tasks ready; review revision {len(calls)}")
            payload["state_updates"] = dict(gate_decision="PASS", phase_recommendation="proceed-to-build",
                                              implementability_metrics={})
        else:
            assert "Operate in **PLAN2**" in prompt
            calls.append(("PLAN2", False))
            if not keep_plan:
                (spec / "tasks.md").write_text("Final task plan")
            payload["verdict"] = "COMPLETE"
        return SquadAgentResult(exit_code=0, echelon_result=payload, raw_output="", duration_ms=0, timed_out=False)

    executor._provider.exec_agent.side_effect = dispatch
    return ctrl, store, executor, node, spec, calls


@pytest.mark.parametrize("mode", ["banzai", "semi", "guided"])
@pytest.mark.parametrize("restart", [False, True])
@pytest.mark.parametrize("repairs", [False, True])
def test_final_review_completes_without_report_revision_replanning(tmp_path, mode, restart, repairs):
    ctrl, store, executor, node, spec, calls = final_fixture(tmp_path, mode, repairs=repairs)
    for _ in range(6):
        result = executor.execute(node, store)
        route = advance(ctrl, store, result)
        if route != "phase3-consensus":
            break
        if restart:
            store = SquadStateStore(tmp_path / "squad/run-test")
    assert route == "phase3-consensus-tasks-lexicon"
    assert calls.count(("PLAN2", False)) == 1
    assert ("WHY3", True) in calls and ("ASSESS2", True) in calls
    assert calls.index(("PLAN2", False)) < calls.index(("WHY3", True))
    assert not store.load().get("phase3_final_review")
    assert store.load()["iteration"] == 1
    assert (spec / "tasks.md").read_text() == "Final task plan"


@pytest.mark.parametrize("mode", ["banzai", "semi", "guided"])
@pytest.mark.parametrize("quality_pass", [False, True])
def test_normal_controller_loop_reaches_existing_checkpoint_after_final_review(tmp_path, monkeypatch, mode, quality_pass):
    from tests.integration.test_squad_controller import _mark_constitution_complete, _install_passing_understanding
    from tests.integration.test_human_input_routing import _decision_result
    from harness.spec_lexicon_gate import run_spec_lexicon_gate

    ctrl, store, executor, node, spec, calls = final_fixture(tmp_path, mode, keep_plan=True)
    if quality_pass:
        # Use the existing metric-engine fixture for the successful branch;
        # real evidence persistence, freshness guards and all routing still run.
        # The other branch runs the actual engine on this intentionally small
        # spec and proves final-review PASS cannot waive its quality failure.
        _install_passing_understanding(monkeypatch)
    fixtures = Path(__file__).resolve().parents[1] / "fixtures/lexicon"
    source = "# Feature\n\n- **REQ-001**: Parse the document.\n- **REQ-002**: Check coverage.\n- **AC-001**: Return the tree.\n- **AC-002**: All requirements covered.\n"
    (spec / "spec.md").write_text(source)
    (spec / "requirements.lexicon.md").write_text(
        f"# SOURCE: spec.md\n# SOURCE_SHA256: {hashlib.sha256(source.encode()).hexdigest()}\n"
        + (fixtures / "spec_ok.md").read_text())
    (spec / "tasks.md").write_text((fixtures / "tasks_ok.md").read_text().replace("depends=none", "depends=none target=sources/app").replace("depends=T-001", "depends=T-001 target=sources/app"))
    (spec / "targets.yml").write_text("schema_version: 1\ntargets:\n  - id: app\n    path: sources/app\n    role: primary\n    branch: main\n")
    for name in ("critical-path.md", "risk-matrix.md", "dependencies.md"):
        (spec / name).write_text("T-001 precedes T-002; no external dependency.")
    _mark_constitution_complete(tmp_path, store)
    gate = run_spec_lexicon_gate(project_root=tmp_path, spec_dir_ref=str(spec),
                                config=ctrl._lexicon_gate_config(), previous_attempts=0)
    assert gate.passed, gate
    state = store.load()
    state.update(gate.state_updates())
    state.update(phase="phase3-plan", max_iterations=5)
    store.save(state)
    consensus_dispatch = executor._provider.exec_agent.side_effect

    def dispatch(cwd, prompt, **kwargs):
        phase = store.load()["phase"]
        if "# COMMANDER DECISION RESOLUTION" in prompt:
            return _decision_result()
        if phase == "phase3-consensus":
            return consensus_dispatch(cwd, prompt, **kwargs)
        if phase == "phase3-plan":
            calls.append(("PLAN", False))
            return SquadAgentResult(exit_code=0, echelon_result=dict(verdict="COMPLETE", state_updates={}, journal_entries=[]),
                                    raw_output="Tasks ready", duration_ms=0, timed_out=False)
        # Stop at the downstream boundary, not by replacing routing, guards or
        # checkpoint executors. No additional product work belongs to this test.
        calls.append((phase, False))
        return SquadAgentResult(exit_code=1, echelon_result=None, raw_output="Downstream observation boundary",
                                duration_ms=0, timed_out=True)

    ctrl._provider.exec_agent.side_effect = dispatch
    # Substitute only the external provider on the real staged executor too.
    executor._provider.exec_agent.side_effect = dispatch
    ctrl._executors["staged_parallel"] = executor
    result = ctrl.run("task", "greenfield")
    final = store.load()
    assert calls.count(("PLAN", False)) == 1
    assert calls.count(("PLAN2", False)) == 1
    assert ("WHY3", True) in calls and ("ASSESS2", True) in calls
    assert "phase3-consensus-tasks-lexicon" in final["completed_phases"]
    assert final["tasks_lexicon_action"] in ("proceed", "proceed_with_warning")
    assert not final.get("phase3_final_review")
    if not quality_pass:
        assert ("phase1-what", False) in calls
        assert "checkpoint-plan" not in final["completed_phases"]
    elif mode == "guided":
        assert result.status == "blocked"
        assert final["phase"] == "checkpoint-plan"
        assert final["blocked_decision"]["status"] == "awaiting_human"
    else:
        assert final["blocked_decision"]["status"] == "resolved"
        assert final["blocked_decision"]["selected_option_id"] == "approve"
        # This deliberately incomplete product fixture reaches finalization;
        # the existing readiness gate must still reject its missing artifacts.
        assert final["blocked_reason"] == "phase_a_readiness_failed"


@pytest.mark.parametrize("mode", ["banzai", "semi", "guided"])
@pytest.mark.parametrize("path", ["spec.md", "estimates.md", "contracts/new.md"])
def test_final_review_cannot_rewrite_its_candidate(tmp_path, mode, path):
    def mutate(spec):
        target = spec / path
        target.parent.mkdir(exist_ok=True)
        target.write_text("Unexpected candidate change")

    ctrl, store, executor, node, _, calls = final_fixture(tmp_path, mode, after_review=mutate)
    assert advance(ctrl, store, executor.execute(node, store)) == "phase3-consensus"
    result = executor.execute(node, store)
    assert isinstance(result, ExecutorBlockedResult) and result.reason == "repair_review_stale"
    assert calls.count(("PLAN2", False)) == 1


@pytest.mark.parametrize("mode", ["banzai", "semi", "guided"])
def test_failed_final_gate_does_not_claim_success_or_replan_in_same_dispatch(tmp_path, mode):
    ctrl, store, executor, node, _, calls = final_fixture(tmp_path, mode, final_verdict="FAIL")
    assert advance(ctrl, store, executor.execute(node, store)) == "phase3-consensus"
    result = executor.execute(node, store)
    assert result.verdict == "FAIL"
    assert not store.load().get("phase3_final_review")
    assert calls.count(("PLAN2", False)) == 1


@pytest.mark.parametrize("outcome", ["unresolved", "unverifiable"])
@pytest.mark.parametrize("mode", ["banzai", "semi", "guided"])
def test_fresh_nonclosure_retires_review_round_instead_of_looping(tmp_path, outcome, mode):
    ctrl, store, executor, node, _, _ = final_fixture(tmp_path, mode, repairs=True, final_outcome=outcome)
    for _ in range(3):
        if store.load().get("phase3_final_review"):
            break
        assert advance(ctrl, store, executor.execute(node, store)) == "phase3-consensus"
    result = executor.execute(node, store)
    assert not store.load().get("phase3_final_review")
    assert result.verdict == "FAIL"
    assert store.load()["why3_verdict"] == "FAIL"
    if mode == "banzai":
        assert advance(ctrl, store, result) == "terminal-blocked"
        assert store.load()["blocked_reason"] == "repair_budget_exhausted"


@pytest.mark.parametrize("input_name", ["spec.md", "estimates.md", "result-contract", "role"])
def test_changed_authoritative_input_between_rounds_requires_planning(tmp_path, input_name):
    ctrl, store, executor, node, spec, calls = final_fixture(tmp_path, "banzai")
    if input_name in {"result-contract", "role"}:
        path = tmp_path / "ext" / ("templates/echelon-result-template.yaml" if input_name == "result-contract" else "role.md")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("Original protocol")
        if input_name == "role":
            executor._graph.agent_file.return_value = "role.md"
    else:
        path = spec / input_name
    assert advance(ctrl, store, executor.execute(node, store)) == "phase3-consensus"
    path.write_text("Changed authoritative input")
    assert advance(ctrl, store, executor.execute(node, store)) == "phase3-consensus"
    assert calls.count(("PLAN2", False)) == 2


def test_fresh_final_review_does_not_inherit_selected_issue_render_limit(tmp_path):
    ctrl, store, executor, node, spec, calls = final_fixture(tmp_path, "semi", keep_plan=True)
    (spec / "tasks.md").write_text("A substantial task plan.\n" * 15000)
    result = executor.execute(node, store)
    assert not isinstance(result, ExecutorBlockedResult)
    assert advance(ctrl, store, result) == "phase3-consensus"
    assert advance(ctrl, store, executor.execute(node, store)) == "phase3-consensus-tasks-lexicon"
    assert calls.count(("PLAN2", False)) == 1


def test_final_review_requires_its_implementability_report(tmp_path):
    ctrl, store, executor, node, spec, _ = final_fixture(tmp_path, "semi")
    assert advance(ctrl, store, executor.execute(node, store)) == "phase3-consensus"
    previous = executor._provider.exec_agent.side_effect

    def dispatch(cwd, prompt, **kwargs):
        result = previous(cwd, prompt, **kwargs)
        if "Operate in **ASSESS2**" in prompt:
            (spec / "implementability-report.md").unlink()
        return result

    executor._provider.exec_agent.side_effect = dispatch
    result = executor.execute(node, store)
    assert isinstance(result, ExecutorBlockedResult)
    assert result.reason == "missing_consensus_prerequisite"


def test_final_receipt_state_commit_failure_cannot_advance(tmp_path, monkeypatch):
    ctrl, store, executor, node, _, _ = final_fixture(tmp_path, "banzai")
    original = store.commit_routing_snapshot_state

    def reject_receipt(snapshot, state):
        if state.get("phase3_final_review"):
            return False
        return original(snapshot, state)

    monkeypatch.setattr(store, "commit_routing_snapshot_state", reject_receipt)
    result = executor.execute(node, store)
    assert isinstance(result, ExecutorBlockedResult)
    assert result.reason == "repair_review_stale"
    assert not store.load().get("phase3_final_review")
