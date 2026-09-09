"""Exercise real staged dispatch and durable state with only the provider faked."""
from dataclasses import asdict
import json
from unittest.mock import MagicMock

import pytest

from harness.phase3_repair import RepairIdentity
from harness.phase_graph import PhaseNode
from harness.squad_executors import StagedParallelExecutor
from harness.squad_provider import SquadAgentResult
from harness.squad_state import SquadStateStore


@pytest.mark.parametrize("mutate_input", [False, True])
@pytest.mark.parametrize("legacy_identity", [False, True])
@pytest.mark.parametrize("missing_review", [False, True])
@pytest.mark.parametrize("mutate_plan2", [False, True])
def test_sage_closure_survives_plan2_block_unless_reviewed_input_changed(tmp_path, mutate_input, legacy_identity, missing_review, mutate_plan2):
    run = tmp_path / "runs" / "r"
    spec = run / "specs" / "001-demo"
    spec.mkdir(parents=True)
    (spec / "spec.md").write_text("Keep behavior unchanged.")
    (spec / "data-model.md").write_text("requested -> ignored; enum includes ignored")
    (spec / "implementability-report.md").write_text("Feasible; other issue remains.")
    (spec / "issues.md").write_text("### ISS-B: Other issue\n- **Responsible agent:** HOW\n")
    store = SquadStateStore(run)
    store.initialize("r", "greenfield", "task", 0, "phase3-consensus")
    identity = RepairIdentity("r", "f" * 64, 7)
    state = store.load()
    state.update({"spec_dir": str(spec), "selected_issue_resolution": "ISS-A",
        "issue_resolution_ledger": {"ISS-A": {"status": "repaired", "repair_phase": "phase3-how",
            "repair_identity": asdict(identity), "title": "Missing ignored enum"}},
        "issue_resolution_repair_baseline": {"issue_id": "ISS-A"}})
    store.save(state)
    if legacy_identity:
        state = store.load()
        del state["issue_resolution_ledger"]["ISS-A"]["repair_identity"]
        store.save(state)
    saw_review = []

    def result(verdict, **extra):
        return SquadAgentResult(exit_code=0, echelon_result={"verdict": verdict, "state_updates": {}, "journal_entries": [], **extra}, raw_output="", duration_ms=0, timed_out=False)

    def dispatch(cwd, prompt, **kwargs):
        if "Operate in **WHY3**" in prompt:
            marker = "## Phase 3 selected-issue review envelope\n```json\n"
            assert marker in prompt
            envelope = json.loads(prompt.split(marker)[1].split("\n```", 1)[0])
            if not legacy_identity:
                assert envelope["identity"] == asdict(identity)
            else:
                assert envelope["identity"]["run_id"] == "r"
                assert len(envelope["identity"]["issue_fingerprint"]) == 64
            assert "data-model.md" in envelope["input_manifest"]
            saw_review.append(True)
            if missing_review:
                return result("PASS")
            if mutate_input:
                (spec / "data-model.md").write_text("enum no longer includes ignored")
            return result("FAIL", phase3_issue_review={"schema_version": 1, "identity": envelope["identity"],
                "outcome": "resolved", "reviewed_artifacts": envelope["input_manifest"],
                "rationale": "The enum declares ignored."})
        assert "Operate in **PLAN2**" in prompt
        assert store.load()["issue_resolution_ledger"]["ISS-A"]["status"] == "validated"
        if mutate_plan2:
            (spec / "data-model.md").write_text("PLAN2 changed the reviewed candidate")
        return result("BLOCKED")

    provider = MagicMock()
    provider.exec_agent.side_effect = dispatch
    graph = MagicMock()
    graph.agent_file.return_value = None
    graph.all_phase_ids.return_value = []
    executor = StagedParallelExecutor(provider, graph, tmp_path / "ext", tmp_path, run)
    node = PhaseNode(id="phase3-consensus", type="staged_parallel", agents=[
        {"id": "echelon.sage", "mode": "WHY3", "stage": 1, "context_pack": []},
        {"id": "echelon.orchestrator", "mode": "PLAN2", "stage": 2, "context_pack": []},
    ])
    observed = executor.execute(node, store)
    assert saw_review
    persisted = SquadStateStore(run).load()
    assert persisted["why3_verdict"] == ("PASS" if missing_review else "FAIL")
    if missing_review:
        assert persisted["selected_issue_resolution"] == "ISS-A"
        assert observed.reason == "repair_review_missing"
    elif mutate_input:
        assert persisted["selected_issue_resolution"] == "ISS-A"
        assert observed.reason == "repair_review_stale"
    else:
        assert observed.verdict == "BLOCKED"
        assert persisted["selected_issue_resolution"] is None
        assert persisted["issue_resolution_ledger"]["ISS-A"]["status"] == "validated"
        assert len(saw_review) == (2 if mutate_plan2 else 1)
        if mutate_plan2:
            assert len(persisted["phase3_issue_reviews"]) == 2
            assert not persisted["issue_resolution_ledger"]["ISS-A"].get("review_revalidation_required")
