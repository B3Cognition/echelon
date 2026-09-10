"""Real controller/state boundaries; only external provider calls are simulated."""
from tests.integration.test_squad_controller import _controller
from tests.unit.test_phase3_repair_routing import work_state
from harness.phase3_repair_context import capture_review_inputs
from harness.squad_provider import SquadAgentResult

import json
from pathlib import Path
from dataclasses import asdict
from unittest.mock import MagicMock
import pytest

from harness.phase3_repair import RepairIdentity
from harness.phase_graph import PhaseNode
from harness.squad_executors import AgentExecutor, StagedParallelExecutor, DeterministicLexiconExecutor, DeterministicUnderstandingExecutor, _render_issue_resolution_context
from harness.squad_state import SquadStateStore
from tests.kernel.test_phase3_work_assessment import ISSUES
from harness.issue_identity import issue_fingerprint


def test_plan2_block_routes_certified_technical_work_without_human_decision(tmp_path):
    controller, store = _controller(tmp_path)
    store.initialize("r", "greenfield", "task", 0, "phase3-consensus")
    spec = tmp_path / "specs" / "008-test"
    (spec / "contracts").mkdir(parents=True)
    (spec / "spec.md").write_text("Preserve requirements")
    (spec / "contracts/api.md").write_text("Observation missing")
    state, _ = work_state()
    (spec / "issues.md").write_text(ISSUES)
    state["phase3_pending_action"]["identity"]["issue_fingerprint"] = issue_fingerprint("Observation missing", ISSUES.split("\n", 1)[1])
    state["phase3_pending_action"]["assessment"]["identity"] = state["phase3_pending_action"]["identity"]
    manifest, _ = capture_review_inputs(spec, project_root=tmp_path)
    state["phase3_pending_action"]["input_manifest"] = manifest
    state["spec_dir"] = str(spec)
    saved = store.load()
    saved.update(state)
    store.save(saved)
    node = controller._graph.get("phase3-consensus")
    snapshot = store.capture_routing_snapshot()
    result = SquadAgentResult(exit_code=0, echelon_result={"verdict": "BLOCKED", "state_updates": {},
        "journal_entries": []}, raw_output="PLAN2 needs an observation contract", duration_ms=0, timed_out=False)
    prepared = controller._prepare_phase_result(node, result, snapshot)
    routing = controller._construct_routing_decision_or_block(node, prepared, snapshot)
    assert routing is not None
    assert routing.decision.to_phase == "phase3-how"
    assert routing.human_input is None
    receipt = controller._advance_prepared_result_or_block(node, routing.decision)
    assert receipt is not None
    current = store.load()
    assert current["selected_issue_resolution"] == "ISS-002"
    assert current["issue_resolution_ledger"]["ISS-002"]["status"] == "selected"
    assert current["why3_verdict"] == "FAIL"
    assert current["iteration"] == 1
    # COMPLETE without edits is still a submission, not proof of repair.
    node = controller._graph.get("phase3-how")
    snapshot = store.capture_routing_snapshot()
    result.echelon_result["verdict"] = "COMPLETE"
    prepared = controller._prepare_phase_result(node, result, snapshot)
    updates = controller._coordinate_selected_issue_repair_updates(node, prepared, snapshot)
    assert updates["issue_resolution_ledger"]["ISS-002"]["submission_count"] == 1
    assert updates["issue_resolution_ledger"]["ISS-002"]["status"] == "repaired"


@pytest.mark.parametrize("restart", [False, True])
@pytest.mark.parametrize("entry_phase", ["phase3-consensus", "phase3-plan"])
def test_repaired_a_hands_off_b_without_waiving_final_review(tmp_path, restart, entry_phase):
    controller, store = _controller(tmp_path)
    run = tmp_path / "squad/run-test"
    spec = tmp_path / "specs/008-test"
    (spec / "contracts").mkdir(parents=True)
    (spec / "spec.md").write_text("FR-001: Preserve visible anatomy")
    (spec / "contracts/api.md").write_text("A: enum fixed. B: observation missing")
    (spec / "issues.md").write_text(ISSUES)
    fixtures = Path(__file__).resolve().parents[1] / "fixtures/lexicon"
    (spec / "tasks.md").write_text((fixtures / "tasks_ok.md").read_text().replace("depends=none", "depends=none target=sources/app").replace("depends=T-001", "depends=T-001 target=sources/app"))
    (spec / "requirements.lexicon.md").write_text((fixtures / "spec_ok.md").read_text())
    (spec / "targets.yml").write_text("schema_version: 1\ntargets:\n  - id: app\n    path: sources/app\n    role: primary\n    branch: main\n")
    for name in ("critical-path.md", "risk-matrix.md", "dependencies.md"):
        (spec / name).write_text("T-001 precedes T-002; no external dependency.")
    store.initialize("r", "greenfield", "task", 0, entry_phase, autonomy_mode="banzai")
    state = store.load()
    state.update(spec_dir=str(spec), why3_verdict="FAIL", selected_issue_resolution="ISS-A",
        issue_resolution_ledger={"ISS-A": {"title": "Missing enum", "status": "repaired",
            "repair_phase": "phase3-how", "repair_identity": asdict(RepairIdentity("r", "a" * 64, 1))}},
        issue_resolution_repair_baseline={"issue_id": "ISS-A", "repair_phase": "phase3-how"})
    store.save(state)
    reviews, classifications, owners, feasibility, planning = [], [], [], [], []

    def dispatch(cwd, prompt, **kwargs):
        payload = {"verdict": "FAIL", "state_updates": {}, "journal_entries": []}
        if store.load()["phase"] == "phase3-plan":
            payload.update(verdict="BLOCKED", state_updates={"blocked_reason": "B requires an architecture-owned observation contract"},
                phase3_blocker={"issue_id": "ISS-002", "owner_phase": "phase3-how",
                    "detail": "Observation missing", "next_action": "Design B observation protocol"})
        elif "Selected Technical Work (Controller-Owned" in prompt:
            assert "Design B observation protocol" in prompt
            assert "Missing enum" not in prompt
            owners.append("phase3-how")
            (spec / "contracts/api.md").write_text("A: enum fixed. B: reproducible observation protocol")
            for name in ("plan.md", "research.md", "data-model.md"):
                (spec / name).write_text("B observation uses the existing scene fixture; preserve requirements.")
            payload["verdict"] = "COMPLETE"
        elif "Operate in **ASSESS2**" in prompt:
            feasibility.append("ASSESS2")
            (spec / "implementability-report.md").write_text("Feasible with the retained scene fixture.")
            payload["verdict"] = "PASS"
        elif "## Phase 3 work assessment envelope" in prompt:
            envelope = json.loads(prompt.split("## Phase 3 work assessment envelope\n```json\n")[1].split("\n```", 1)[0])
            classifications.append(envelope["issue_id"])
            payload["phase3_repair_action"] = {"schema_version": 1, "identity": envelope["identity"],
                "kind": "investigate_or_design", "owner_phase": "phase3-how", "affected_artifacts": ["contracts/api.md"],
                "evidence_refs": ["spec.md#FR-001"], "action": "Design B observation protocol",
                "constraints": ["Preserve FR-001; proposals are not facts."]}
        elif "Operate in **WHY3**" in prompt:
            marker = "## Phase 3 selected-issue review envelope\n```json\n"
            if marker not in prompt:
                assert "## Fixed-candidate final review" in prompt
                return SquadAgentResult(exit_code=0, echelon_result={"verdict": "PASS", "state_updates": {},
                    "journal_entries": []}, raw_output="Final candidate checked", duration_ms=0, timed_out=False)
            envelope = json.loads(prompt.split(marker)[1].split("\n```", 1)[0])
            reviews.append(envelope["selected_issue"])
            if entry_phase == "phase3-plan" and len(reviews) == 1:
                assert "Planner dependency handoff (advisory)" in prompt
                assert "Observation missing" in prompt
            fixed = "reproducible" in (spec / "contracts/api.md").read_text()
            if envelope["selected_issue"] == "ISS-002":
                assert fixed
                assert envelope["repair_action"]["action"] == "Design B observation protocol"
            payload["verdict"] = "PASS" if fixed else "FAIL"
            payload["phase3_issue_review"] = {"schema_version": 1, "identity": envelope["identity"],
                "outcome": "resolved", "reviewed_artifacts": envelope["input_manifest"],
                "rationale": "Checked the actual contract against the retained requirement."}
        else:
            assert "Operate in **PLAN2**" in prompt
            planning.append("PLAN2")
            payload["verdict"] = "DONE" if "reproducible" in (spec / "contracts/api.md").read_text() else "BLOCKED"
        return SquadAgentResult(exit_code=0, echelon_result=payload, raw_output="", duration_ms=0, timed_out=False)

    provider = MagicMock()
    provider.exec_agent.side_effect = dispatch
    graph = MagicMock()
    graph.agent_file.return_value = None
    graph.all_phase_ids.return_value = []
    executor = StagedParallelExecutor(provider, graph, tmp_path / "ext", tmp_path, run)
    consensus = PhaseNode(id="phase3-consensus", type="staged_parallel", agents=[
        {"id": "echelon.sage", "mode": "WHY3", "stage": 1, "context_pack": []},
        {"id": "echelon.gatekeeper", "mode": "ASSESS2", "stage": 1, "context_pack": []},
        {"id": "echelon.orchestrator", "mode": "PLAN2", "stage": 2, "context_pack": []}])

    def advance(result):
        node = controller._graph.get(store.load()["phase"])
        snapshot = store.capture_routing_snapshot()
        prepared = controller._prepare_phase_result(node, result, snapshot)
        routed = controller._construct_routing_decision_or_block(node, prepared, snapshot)
        assert routed is not None and routed.human_input is None
        assert controller._advance_prepared_result_or_block(node, routed.decision) is not None
        return routed.decision.to_phase

    if entry_phase == "phase3-plan":
        planner = AgentExecutor(provider, graph, tmp_path / "ext", tmp_path, run)
        assert advance(planner.execute(controller._graph.get("phase3-plan"), store)) == "phase3-consensus"
        assert store.load()["issue_resolution_ledger"]["ISS-A"]["status"] == "repaired"
    result = executor.execute(consensus, store)
    assert result.verdict == "FAIL"
    assert planning == []  # Classify the unresolved owner before dependent planning.
    assert store.load()["issue_resolution_ledger"]["ISS-A"]["status"] == "validated"
    if restart:
        controller, store = _controller(tmp_path, squad_dir=run)
    assert advance(result) == "phase3-how"
    owner_prompt = _render_issue_resolution_context(store.load())
    assert "Design B observation protocol" in owner_prompt
    assert "Missing enum" not in owner_prompt
    assert store.load()["why3_verdict"] == "FAIL"
    # Existing owner and downstream phases submit through sealed controller routes.
    complete = SquadAgentResult(exit_code=0, echelon_result={"verdict": "COMPLETE", "state_updates": {}, "journal_entries": []}, raw_output="", duration_ms=0, timed_out=False)
    owner_executor = AgentExecutor(provider, graph, tmp_path / "ext", tmp_path, run)
    assert advance(owner_executor.execute(controller._graph.get("phase3-how"), store)) == "phase3-sentinel"
    assert store.load()["issue_resolution_ledger"]["ISS-002"]["status"] == "repaired"
    assert advance(complete) == "phase3-plan"
    assert advance(complete) == "phase3-tasks-lexicon"
    lexicon = DeterministicLexiconExecutor(controller._graph, controller._ext_dir, tmp_path, run)
    assert advance(lexicon.execute(controller._graph.get("phase3-tasks-lexicon"), store)) == "phase3-understanding"
    understanding = DeterministicUnderstandingExecutor(controller._graph, controller._ext_dir, tmp_path, run)
    assert advance(understanding.execute(controller._graph.get("phase3-understanding"), store)) == "phase3-consensus"
    # B changed reviewed dependencies, so A also needs fresh review before exit.
    assert advance(executor.execute(consensus, store)) == "phase3-consensus"
    assert advance(executor.execute(consensus, store)) == "phase3-consensus"
    assert advance(executor.execute(consensus, store)) == "phase3-consensus-tasks-lexicon"
    final = store.load()
    assert final["selected_issue_resolution"] is None
    assert final["issue_resolution_ledger"]["ISS-A"]["status"] == "validated"
    assert final["issue_resolution_ledger"]["ISS-002"]["status"] == "validated"
    assert final["why3_verdict"] == "PASS"
    assert final["issue_resolution_ledger"]["ISS-002"]["submission_count"] == 1
    assert classifications == ["ISS-002"]
    assert reviews == ["ISS-A", "ISS-002", "ISS-A"]
    assert owners == ["phase3-how"]
    assert len(feasibility) == 4
    assert planning == ["PLAN2"]
    assert final["iteration"] == 1  # Only assigning B consumed a repair iteration.
