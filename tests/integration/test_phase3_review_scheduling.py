"""Review scheduling uses real executor, store and sealed controller routing."""
from dataclasses import asdict
import json
from unittest.mock import MagicMock

import pytest

from harness.phase3_repair import RepairIdentity
from harness.phase3_repair_context import capture_review_inputs
from harness.phase_graph import PhaseNode
from harness.squad_executors import StagedParallelExecutor
from harness.squad_provider import SquadAgentResult
from harness.squad_state import SquadStateStore
from tests.integration.test_squad_controller import _controller


def scheduling_fixture(tmp_path, *, mode="banzai", verdict="PASS", mutate_plan=False, plan_result=None, during_plan=None, spec_ref="specs/008-test"):
    controller, store = _controller(tmp_path)
    run = tmp_path / "squad/run-test"
    spec = tmp_path / spec_ref
    spec.mkdir(parents=True)
    (spec / "spec.md").write_text("FR-001: Preserve requirements")
    (spec / "tasks.md").write_text("Original task plan")
    (spec / "issues.md").write_text("")
    (spec / "implementability-report.md").write_text("Feasible")
    store.initialize("r", "greenfield", "task", 0, "phase3-consensus", autonomy_mode=mode)
    state = store.load()
    state.update(spec_dir=str(spec), iteration=1, max_iterations=1, selected_issue_resolution="ISS-A",
        issue_resolution_ledger={key: {"status": "repaired", "repair_phase": "phase3-how",
            "title": key, "review_revalidation_required": True,
            "repair_identity": asdict(RepairIdentity("r", char * 64, index))}
            for index, (key, char) in enumerate((("ISS-A", "a"), ("ISS-B", "b")), 1)})
    store.save(state)
    calls = []

    def dispatch(cwd, prompt, **kwargs):
        payload = {"verdict": verdict, "state_updates": {}, "journal_entries": []}
        if "Operate in **WHY3**" in prompt:
            envelope = json.loads(prompt.split("## Phase 3 selected-issue review envelope\n```json\n")[1].split("\n```", 1)[0])
            calls.append(("review", envelope["selected_issue"]))
            payload["phase3_issue_review"] = {"schema_version": 1, "identity": envelope["identity"],
                "outcome": "resolved", "reviewed_artifacts": envelope["input_manifest"], "rationale": "Verified requirements"}
        elif "Operate in **ASSESS2**" in prompt:
            (spec / "implementability-report.md").write_text("Feasible")
            payload.update(verdict="PASS", state_updates={"gate_decision": "PASS",
                "phase_recommendation": "proceed-to-build", "implementability_metrics": {}})
        else:
            assert "Operate in **PLAN2**" in prompt
            calls.append(("plan", None))
            if mutate_plan:
                (spec / "tasks.md").write_text(f"New task plan {len(calls)}")
            if during_plan is not None:
                during_plan()
            if plan_result is not None:
                return plan_result
            payload["verdict"] = "DONE"
        return SquadAgentResult(exit_code=0, echelon_result=payload, raw_output="", duration_ms=0, timed_out=False)

    provider, graph = MagicMock(), MagicMock()
    provider.exec_agent.side_effect = dispatch
    graph.agent_file.return_value = None
    graph.all_phase_ids.return_value = []
    executor = StagedParallelExecutor(provider, graph, tmp_path / "ext", tmp_path, run)
    node = PhaseNode(id="phase3-consensus", type="staged_parallel", agents=[
        {"id": "echelon.sage", "mode": "WHY3", "stage": 1, "context_pack": []},
        {"id": "echelon.orchestrator", "mode": "PLAN2", "stage": 2, "context_pack": []}])
    return controller, store, executor, node, spec, calls


def advance(controller, store, result):
    node = controller._graph.get("phase3-consensus")
    snapshot = store.capture_routing_snapshot()
    prepared = controller._prepare_phase_result(node, result, snapshot)
    routing = controller._construct_routing_decision_or_block(node, prepared, snapshot)
    assert routing is not None and routing.human_input is None
    assert controller._advance_prepared_result_or_block(node, routing.decision) is not None
    return routing.decision.to_phase


@pytest.mark.parametrize("verdict", ["PASS", "FAIL"])
def test_pending_reviews_do_not_rewrite_plan_or_spend_repair_budget(tmp_path, verdict):
    controller, store, executor, node, spec, calls = scheduling_fixture(tmp_path, verdict=verdict, mutate_plan=True)
    result = executor.execute(node, store)
    assert (spec / "tasks.md").read_text() == "Original task plan"
    assert calls == [("review", "ISS-A")]
    assert advance(controller, store, result) == "phase3-consensus"
    assert store.load()["iteration"] == 1
    assert store.load()["max_iterations"] == 1
    assert store.load()["selected_issue_resolution"] == "ISS-B"


@pytest.mark.parametrize("restart", [False, True])
@pytest.mark.parametrize("real_workflow", [False, True])
def test_final_planning_change_is_reviewed_without_another_rewrite(tmp_path, restart, real_workflow):
    controller, store, executor, node, spec, calls = scheduling_fixture(tmp_path, mutate_plan=True)
    if real_workflow:
        node = controller._graph.get("phase3-consensus")
    assert advance(controller, store, executor.execute(node, store)) == "phase3-consensus"
    assert advance(controller, store, executor.execute(node, store)) == "phase3-consensus"
    if restart:
        store = SquadStateStore(tmp_path / "squad/run-test")
    if real_workflow:
        # The full workflow reviews both gates in a separate fixed round;
        # one selected-issue closure is recorded per review dispatch.
        assert advance(controller, store, executor.execute(node, store)) == "phase3-consensus"
    assert advance(controller, store, executor.execute(node, store)) == "phase3-consensus-tasks-lexicon"
    assert calls == [("review", "ISS-A"), ("review", "ISS-B"), ("plan", None),
                     *(([("review", "ISS-A"), ("review", "ISS-B")]) if real_workflow else
                       [("review", "ISS-B"), ("review", "ISS-A")])]
    final = store.load()
    manifest, _ = capture_review_inputs(spec, project_root=tmp_path)
    for entry in final["issue_resolution_ledger"].values():
        assert entry["status"] == "validated"
        assert final["phase3_issue_reviews"][entry["last_review_dispatch_id"]]["reviewed_artifacts"] == manifest
    assert final["iteration"] == 1


def test_review_only_reconciliation_does_not_increment_at_cap(tmp_path):
    controller, store, _, _, _, _ = scheduling_fixture(tmp_path)
    state = store.load()
    state["selected_issue_resolution"] = None
    store.save(state)
    result = SquadAgentResult(exit_code=0, echelon_result={"verdict": "PASS", "state_updates": {}},
                              raw_output="", duration_ms=0, timed_out=False)
    assert advance(controller, store, result) == "phase3-consensus"
    assert store.load()["iteration"] == 1


def test_semi_mode_keeps_existing_staged_planning(tmp_path):
    _, store, executor, node, _, calls = scheduling_fixture(tmp_path, mode="semi", verdict="FAIL")
    assert executor.execute(node, store).verdict == "FAIL"
    assert ("plan", None) in calls


def test_sage_review_metadata_is_ignored_when_no_issue_is_selected(tmp_path):
    _, store, executor, node, _, _ = scheduling_fixture(tmp_path)
    state = store.load()
    state["selected_issue_resolution"] = None
    state["issue_resolution_ledger"] = {}
    store.save(state)

    def dispatch(cwd, prompt, **kwargs):
        payload = {
            "verdict": "PASS",
            "state_updates": {},
            "journal_entries": [],
        }
        if "Operate in **WHY3**" in prompt:
            payload["phase3_issue_review"] = {
                "schema_version": 2,
                "selected_issue": "ISS-OLD",
                "outcome": "resolved",
                "rationale": "Stale optional metadata from an earlier review.",
                "evidence_refs": ["spec.md"],
            }
        else:
            assert "Operate in **PLAN2**" in prompt
            payload["verdict"] = "DONE"
        return SquadAgentResult(
            exit_code=0,
            echelon_result=payload,
            raw_output="",
            duration_ms=0,
            timed_out=False,
        )

    executor._provider.exec_agent.side_effect = dispatch

    result = executor.execute(node, store)

    assert result.verdict == "PASS"
    assert store.load().get("phase3_issue_reviews") in (None, {})


def test_non_sage_cannot_submit_issue_review_metadata(tmp_path):
    _, store, executor, node, _, _ = scheduling_fixture(tmp_path)
    state = store.load()
    state["selected_issue_resolution"] = None
    state["issue_resolution_ledger"] = {}
    store.save(state)
    node.agents = [
        {
            "id": "echelon.gatekeeper",
            "mode": "ASSESS2",
            "stage": 1,
            "context_pack": [],
        }
    ]
    executor._provider.exec_agent.side_effect = None
    executor._provider.exec_agent.return_value = SquadAgentResult(
        exit_code=0,
        echelon_result={
            "verdict": "PASS",
            "state_updates": {},
            "journal_entries": [],
            "phase3_issue_review": {
                "schema_version": 2,
                "selected_issue": "ISS-OLD",
                "outcome": "resolved",
                "rationale": "Unauthorized review.",
                "evidence_refs": ["spec.md"],
            },
        },
        raw_output="",
        duration_ms=0,
        timed_out=False,
    )

    result = executor.execute(node, store)

    assert result.reason == "invalid_phase_outputs"


def test_workspace_references_survive_legacy_inline_revalidation(tmp_path):
    failure = SquadAgentResult(0, {"verdict": "BLOCKED", "state_updates": {}}, "Another planner issue", 0, False)
    _, store, executor, node, spec, _ = scheduling_fixture(
        tmp_path, mode="semi", mutate_plan=True, plan_result=failure)
    original = executor._provider.exec_agent.side_effect
    reviews = []

    def dispatch(cwd, prompt, **kwargs):
        result = original(cwd, prompt, **kwargs)
        payload = result.echelon_result
        if "phase3_issue_review" in payload:
            reviews.append(True)
            payload["phase3_issue_review"] = dict(schema_version=2, selected_issue="ISS-A",
                outcome="resolved", rationale="Current plan inspected",
                evidence_refs=[str((spec / "tasks.md").relative_to(tmp_path)) + "#tasks"])
        return result

    executor._provider.exec_agent.side_effect = dispatch
    result = executor.execute(node, store)
    assert result.blocked  # Preserve PLAN2's separate failure, not a path rejection.
    assert len(reviews) == 2
    entry = store.load()["issue_resolution_ledger"]["ISS-A"]
    assert entry["status"] == "validated"
    receipt = store.load()["phase3_issue_reviews"][entry["last_review_dispatch_id"]]
    manifest, _ = capture_review_inputs(spec, project_root=tmp_path)
    assert receipt["reviewed_artifacts"] == manifest


@pytest.mark.parametrize("changed_input", ["spec.md", "implementability-report.md", "issues.md", "role.md"])
def test_changed_planning_inputs_invalidate_completion_receipt(tmp_path, changed_input):
    controller, store, executor, node, spec, calls = scheduling_fixture(tmp_path, mutate_plan=True)
    # Include report and role inputs outside the selected-issue manifest.
    node.agents[-1]["context_pack"] = ["{spec_dir}/issues.md"]
    role = tmp_path / "ext/role.md"
    role.parent.mkdir()
    role.write_text("Plan the tasks")
    executor._graph.agent_file.side_effect = lambda agent: "role.md" if agent == "echelon.orchestrator" else None
    assert advance(controller, store, executor.execute(node, store)) == "phase3-consensus"
    assert advance(controller, store, executor.execute(node, store)) == "phase3-consensus"
    path = role if changed_input == "role.md" else spec / changed_input
    path.write_text("Changed planning requirement or evidence")
    # A changed product input invalidates both reviews; drain them first.
    for _ in range(3):
        result = executor.execute(node, store)
        next_phase = advance(controller, store, result)
        if len([call for call in calls if call[0] == "plan"]) == 2:
            break
        assert next_phase == "phase3-consensus"
    assert len([call for call in calls if call[0] == "plan"]) == 2


@pytest.mark.parametrize("verdict,exit_code,timed_out", [("BLOCKED", 0, False), ("DONE", 1, False), ("DONE", 0, True)])
def test_failed_plan_invalidates_older_completion_receipt(tmp_path, verdict, exit_code, timed_out):
    failure = SquadAgentResult(exit_code=exit_code, echelon_result={"verdict": verdict, "state_updates": {}},
                              raw_output="Planner failed", duration_ms=0, timed_out=timed_out)
    _, store, executor, node, _, _ = scheduling_fixture(tmp_path, plan_result=failure)
    state = store.load()
    del state["issue_resolution_ledger"]["ISS-B"]
    state["phase3_plan2_completion"] = {"schema_version": 1, "run_id": "r", "input_manifest": {}, "prompt_sha256": "old"}
    store.save(state)
    result = executor.execute(node, store)
    assert result.blocked
    assert not store.load().get("phase3_plan2_completion")


@pytest.mark.parametrize("changed_input", ["role.md", "implementability-report.md", "spec.md"])
def test_planning_cannot_certify_input_changed_during_dispatch(tmp_path, changed_input):
    def mutate_input():
        path = role if changed_input == "role.md" else spec / changed_input
        path.write_text("New requirement not seen by the planner")

    controller, store, executor, node, spec, _ = scheduling_fixture(tmp_path, mutate_plan=True, during_plan=mutate_input)
    role = tmp_path / "ext/role.md"
    role.parent.mkdir()
    role.write_text("Original planner instruction")
    executor._graph.agent_file.side_effect = lambda agent: "role.md" if agent == "echelon.orchestrator" else None
    assert advance(controller, store, executor.execute(node, store)) == "phase3-consensus"
    executor.execute(node, store)
    assert not store.load().get("phase3_plan2_completion")
