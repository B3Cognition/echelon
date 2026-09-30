import json
from unittest.mock import MagicMock

import pytest

from harness.phase_graph import PhaseNode
from harness.phase_execution import PhaseExecutionAccumulator
from harness.squad_executors import StagedParallelExecutor, ExecutorBlockedResult
from harness.squad_provider import SquadAgentResult
from harness.squad_state import SquadStateStore


ISSUES = """### ISS-002: Observation missing
- **Responsible agent:** ARCHITECT
- **Action Required:** Define a reproducible observation protocol.
### Resolution Guidance
- **Decision required:** Derive the observation mechanism.
- **Suggested option:** Investigate the existing scene fixture.
- **Evidence basis:** spec.md#FR-001
- **Banzai eligible:** no
"""


@pytest.mark.parametrize("malformed", [False, True])
def test_missing_action_gets_one_durable_sage_assessment_not_answer_adoption(tmp_path, malformed):
    spec = tmp_path / "spec"
    (spec / "contracts").mkdir(parents=True)
    (spec / "spec.md").write_text("Preserve visible anatomy")
    (spec / "contracts/api.md").write_text("Existing scene fixture")
    (spec / "issues.md").write_text(ISSUES)
    run = tmp_path / "run"
    store = SquadStateStore(run)
    store.initialize("r", "greenfield", "task", 0, "phase3-consensus")
    state = store.load()
    state.update(spec_dir=str(spec), autonomy_mode="banzai", why3_verdict="FAIL")
    store.save(state)
    prompts = []

    def dispatch(cwd, prompt, **kwargs):
        prompts.append(prompt)
        marker = "## Phase 3 work assessment envelope\n```json\n"
        envelope = json.loads(prompt.split(marker)[1].split("\n```", 1)[0])
        assert "Existing scene fixture" in prompt
        assert "Banzai eligible" in prompt
        payload = {"verdict": "FAIL", "state_updates": {}, "journal_entries": []}
        if not malformed:
            payload["phase3_repair_action"] = {"schema_version": 1, "identity": envelope["identity"],
                "kind": "investigate_or_design", "owner_phase": "phase3-how",
                "affected_artifacts": ["contracts/api.md"], "evidence_refs": ["spec.md#FR-001"],
                "action": "Design the observation protocol", "constraints": ["Preserve validated requirements."]}
        return SquadAgentResult(exit_code=0, echelon_result=payload, raw_output="", duration_ms=0, timed_out=False)

    graph = MagicMock()
    graph.agent_file.return_value = None
    graph.all_phase_ids.return_value = []
    provider = MagicMock()
    provider.exec_agent.side_effect = dispatch
    executor = StagedParallelExecutor(provider, graph, tmp_path / "ext", tmp_path, run)
    node = PhaseNode(id="phase3-consensus", type="staged_parallel", agents=[
        {"id": "echelon.sage", "mode": "WHY3", "stage": 1, "context_pack": []}])
    accumulator = PhaseExecutionAccumulator(node.id)
    result = executor._assess_phase3_work(
        node,
        store,
        accumulator,
        store.load(),
    )
    if malformed:
        assert isinstance(result, ExecutorBlockedResult)
        assert result.reason == "repair_action_unclassified"
        assert result.execution is not None
    else:
        assert isinstance(result, dict)
        pending = result["phase3_pending_action"]
        assert pending["assessment"]["kind"] == "investigate_or_design"
        assert store.load().get("selected_issue_resolution") is None
        assert store.load()["why3_verdict"] == "FAIL"
        assert "phase3_pending_action" not in store.load()
        execution = accumulator.freeze(
            SquadAgentResult(
                exit_code=0,
                echelon_result={"verdict": "FAIL", "state_updates": result},
                raw_output="",
                duration_ms=0,
                timed_out=False,
            )
        )
        assert execution.manifest[0].occurrence_id == "sage/work-assessment"
        assert provider.exec_agent.call_args.kwargs["prompt_metadata"][
            "tool_write_paths"
        ] == []
    # Restart and report renumbering cannot grant another classification attempt.
    (spec / "issues.md").write_text(ISSUES.replace("ISS-002", "ISS-009"))
    restarted = PhaseExecutionAccumulator(node.id)
    executor._assess_phase3_work(
        node,
        SquadStateStore(run),
        restarted,
        SquadStateStore(run).load(),
    )
    assert len(prompts) == 1
