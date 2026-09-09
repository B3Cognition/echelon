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


def test_bad_legacy_selection_blocks_without_dispatch_or_false_closure(tmp_path):
    store = SquadStateStore(tmp_path / "run")
    store.initialize("r", "greenfield", "task", 0, "phase3-consensus")
    state = store.load()
    (tmp_path / "spec.md").write_text("Retained requirement")
    state["spec_dir"] = str(tmp_path)
    state.update(selected_issue_resolution="ISS-A", issue_resolution_ledger={"ISS-A": {
        "status": "repaired", "repair_phase": "phase3-how", "repair_identity": "broken"}})
    store.save(state)
    executor = StagedParallelExecutor(MagicMock(), MagicMock(), tmp_path / "ext", tmp_path, tmp_path / "run")
    result = executor.execute(PhaseNode(id="phase3-consensus", type="staged_parallel"), store)
    assert result.reason == "repair_review_stale"
    assert store.load()["selected_issue_resolution"] == "ISS-A"


@pytest.mark.parametrize("mutate_input", [False, True])
@pytest.mark.parametrize("legacy_identity", [False, True])
@pytest.mark.parametrize("missing_review", [False, True])
@pytest.mark.parametrize("mutate_plan2", [False, True])
@pytest.mark.parametrize("sage_verdict", ["FAIL", "BLOCKED"])
@pytest.mark.parametrize("outcome", ["resolved", "unresolved"])
def test_sage_closure_survives_plan2_block_unless_reviewed_input_changed(tmp_path, mutate_input, legacy_identity, missing_review, mutate_plan2, sage_verdict, outcome):
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
            return result(sage_verdict, phase3_issue_review={"schema_version": 1, "identity": envelope["identity"],
                "outcome": outcome, "reviewed_artifacts": envelope["input_manifest"],
                "rationale": "The enum declares ignored."})
        assert "Operate in **PLAN2**" in prompt
        assert store.load()["issue_resolution_ledger"]["ISS-A"]["status"] == ("validated" if outcome == "resolved" else "repaired")
        if mutate_plan2:
            (spec / "data-model.md").write_text("PLAN2 changed the reviewed candidate")
        return result("BLOCKED", phase3_blocker={"issue_id": "ISS-B", "owner_phase": "phase3-how",
            "detail": "Observation contract is missing", "next_action": "ARCHITECT must define the fixture"})

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
    reports = [json.loads(path.read_text()) for path in (run / "context-budget").glob("*sage.json")]
    assert reports
    assert all(any(section["name"] == "Required Phase 3 review context"
                   for section in report["bounded"]["top_sections"]) for report in reports)
    persisted = SquadStateStore(run).load()
    assert persisted["why3_verdict"] == ("PASS" if missing_review else sage_verdict)
    if missing_review:
        assert persisted["selected_issue_resolution"] == "ISS-A"
        assert observed.reason == "repair_review_missing"
    elif mutate_input:
        assert persisted["selected_issue_resolution"] == "ISS-A"
        assert observed.reason == "repair_review_stale"
    else:
        assert observed.verdict == "BLOCKED"
        assert persisted["selected_issue_resolution"] == (None if outcome == "resolved" else "ISS-A")
        assert persisted["issue_resolution_ledger"]["ISS-A"]["status"] == ("validated" if outcome == "resolved" else "repaired")
        revalidated = mutate_plan2 and sage_verdict != "BLOCKED"
        assert len(saw_review) == (2 if revalidated else 1)
        if revalidated:
            assert len(persisted["phase3_issue_reviews"]) == 2
            assert not persisted["issue_resolution_ledger"]["ISS-A"].get("review_revalidation_required")
        if sage_verdict != "BLOCKED":
            assert persisted["phase3_last_blocker"]["producer"] == "PLAN2"
            assert persisted["phase3_last_blocker"]["detail"] == "Observation contract is missing"
