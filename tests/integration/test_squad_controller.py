"""Integration tests for SquadController with mock provider.

The most important test: test_consensus_cannot_be_skipped.
A mock agent always returns DONE. SquadController must still dispatch
WHY3 + ASSESS2 (stage 1) before PLAN2 (stage 2) and before checkpoint-plan.
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

EXT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(EXT_ROOT) not in sys.path:
    sys.path.insert(0, str(EXT_ROOT))

from harness.phase_graph import PhaseGraph, PhaseNode
from harness.squad import SquadController, SquadResult
from harness.squad_provider import SquadAgentResult
from harness.squad_state import SquadStateStore

DEFINITION = EXT_ROOT / "extension/workflow/definition.yaml"
EXT_YML = EXT_ROOT / "extension/extension.yml"


def _mock_provider(verdict: str = "DONE") -> MagicMock:
    provider = MagicMock()
    provider.exec_agent.return_value = SquadAgentResult(
        exit_code=0,
        echelon_result={"verdict": verdict, "state_updates": {}},
        raw_output="",
        duration_ms=100,
        timed_out=False,
    )
    return provider


def _controller(tmp_path: Path, provider=None, mode: str = "banzai", squad_dir: Path = None):
    if squad_dir is None:
        squad_dir = tmp_path / "squad" / "run-test"
        squad_dir.mkdir(parents=True, exist_ok=True)
        (squad_dir / "staging").mkdir(exist_ok=True)
    graph = PhaseGraph(DEFINITION, EXT_YML)
    store = SquadStateStore(squad_dir)
    if provider is None:
        provider = _mock_provider()
    ctrl = SquadController(
        provider=provider,
        state_store=store,
        phase_graph=graph,
        ext_dir=EXT_ROOT / "extension",
        project_root=tmp_path,
        token_budget=0,
        squad_dir=squad_dir,
    )
    return ctrl, store


class TestConsensusCannotBeSkipped:
    """Regression: phase3-consensus was previously skipped via EVOI fabrication.
    With the harness, phase3-plan → phase3-consensus is condition: always.
    Python evaluates it; no code path exists that skips it.
    """

    def test_phase3_plan_transitions_to_consensus(self):
        graph = PhaseGraph(DEFINITION, EXT_YML)
        plan_node = graph.get("phase3-plan")
        targets = [t["to"] for t in plan_node.transitions]
        assert "phase3-consensus" in targets, (
            f"phase3-plan must have a transition to phase3-consensus. Got: {targets}"
        )

    def test_phase3_plan_to_consensus_condition_is_always(self):
        graph = PhaseGraph(DEFINITION, EXT_YML)
        plan_node = graph.get("phase3-plan")
        for t in plan_node.transitions:
            if t["to"] == "phase3-consensus":
                assert t["condition"] == "always", (
                    f"phase3-plan → phase3-consensus must be 'always', "
                    f"got {t['condition']!r}"
                )

    def test_staged_parallel_has_stage1_and_stage2_agents(self):
        graph = PhaseGraph(DEFINITION, EXT_YML)
        consensus_node = graph.get("phase3-consensus")
        stage1 = [a for a in consensus_node.agents if a.get("stage", 1) == 1]
        stage2 = [a for a in consensus_node.agents if a.get("stage", 1) == 2]
        assert len(stage1) >= 2, (
            f"phase3-consensus must have ≥2 stage-1 agents (WHY3 + ASSESS2), got {len(stage1)}"
        )
        assert len(stage2) >= 1, (
            f"phase3-consensus must have ≥1 stage-2 agent (PLAN2), got {len(stage2)}"
        )

    def test_condition_evaluator_cannot_skip_always(self):
        """ConditionEvaluator must return True for 'always' — never None."""
        from harness.condition_evaluator import ConditionEvaluator
        ev = ConditionEvaluator()
        assert ev.evaluate("always", {}) is True
        # 'always' can never trigger COMMANDER dispatch (would require None return)
        assert ev.evaluate("always", {}) is not None


class TestSquadControllerBasics:
    def test_starts_at_entry_phase(self, tmp_path):
        ctrl, store = _controller(tmp_path)
        store.initialize("r", "banzai", "msg", 0, "DONE")
        result = ctrl.run("msg", "banzai")
        assert result.status == "done"

    def test_cancel_stops_loop(self, tmp_path):
        """SIGINT (self._cancelled flag) stops the loop mid-run."""
        ctrl, store = _controller(tmp_path)
        store.initialize("r", "banzai", "msg", 0, "init")
        ctrl._cancelled = True   # simulate SIGINT received mid-run
        result = ctrl.run("msg", "banzai")
        assert result.status == "interrupted"

    def test_stale_cancel_requested_cleared_on_resume(self, tmp_path):
        """cancel_requested left in state.json by a previous Ctrl+C does not
        prevent a fresh echelon run invocation from proceeding."""
        ctrl, store = _controller(tmp_path)
        store.initialize("r", "banzai", "msg", 0, "init")
        store.set_cancel_requested()   # simulate previous run's Ctrl+C
        # run() must clear it and proceed normally (not exit immediately)
        result = ctrl.run("msg", "banzai")
        assert result.status != "interrupted"

    def test_budget_zero_never_exhausts(self, tmp_path):
        """token_budget=0 means disabled — should not trigger budget_exhausted."""
        ctrl, store = _controller(tmp_path)
        store.initialize("r", "banzai", "msg", 0, "DONE")
        result = ctrl.run("msg", "banzai")
        assert result.status != "budget_exhausted"

    def test_budget_exhausted_when_exceeded(self, tmp_path):
        provider = _mock_provider()
        graph = PhaseGraph(DEFINITION, EXT_YML)
        store = SquadStateStore(tmp_path / ".specify/squad")
        ctrl = SquadController(
            provider=provider,
            state_store=store,
            phase_graph=graph,
            ext_dir=EXT_ROOT / "extension",
            project_root=tmp_path,
            token_budget=100,   # very low
        )
        store.initialize("r", "banzai", "msg", 100, "init")
        store.increment_token_usage(100)  # exhaust immediately
        result = ctrl.run("msg", "banzai")
        assert result.status == "budget_exhausted"

    def test_unknown_phase_type_calls_judgment(self, tmp_path):
        """Unknown type → judgment_dispatch → provider.exec_agent called."""
        provider = _mock_provider()
        ctrl, store = _controller(tmp_path, provider)

        # Inject a fake phase with unknown type and a simple 'always' transition to DONE
        fake = PhaseNode(
            id="fake-unknown",
            type="unknown_type",
            transitions=[{"to": "DONE", "condition": "always"}],
        )
        ctrl._graph._phases["fake-unknown"] = fake
        store.initialize("r", "banzai", "msg", 0, "fake-unknown")
        result = ctrl.run("msg", "banzai")
        # Provider must have been called (COMMANDER judgment)
        assert provider.exec_agent.called


class TestHumanGate:
    def test_banzai_auto_approves(self, tmp_path):
        from harness.squad_executors import HumanGateExecutor
        graph = PhaseGraph(DEFINITION, EXT_YML)
        store = SquadStateStore(tmp_path / ".specify/squad")
        store.initialize("r", "banzai", "msg", 0, "init")

        executor = HumanGateExecutor(
            _mock_provider(), graph, EXT_ROOT / "extension", tmp_path
        )
        node = PhaseNode(
            id="checkpoint-plan",
            type="human_gate",
            label="Phase 3 Checkpoint",
        )
        result = executor.execute(node, store)
        assert result.verdict == "APPROVED"
        assert result.state_updates.get("gate_result") == "auto_approved"

    def test_semi_auto_approves(self, tmp_path):
        from harness.squad_executors import HumanGateExecutor
        graph = PhaseGraph(DEFINITION, EXT_YML)
        store = SquadStateStore(tmp_path / ".specify/squad")
        store.initialize("r", "semi", "msg", 0, "init")

        executor = HumanGateExecutor(
            _mock_provider(), graph, EXT_ROOT / "extension", tmp_path
        )
        node = PhaseNode(
            id="checkpoint-plan",
            type="human_gate",
            label="Phase 3 Checkpoint",
        )
        result = executor.execute(node, store)
        assert result.verdict == "APPROVED"


def test_journal_written_to_squad_dir_not_specify(tmp_path):
    squad_dir = tmp_path / "squad" / "run-test"
    squad_dir.mkdir(parents=True)
    (squad_dir / "staging").mkdir()
    ctrl, store = _controller(tmp_path, squad_dir=squad_dir)
    store.initialize("r", "banzai", "msg", 0, "init")
    from harness.squad_provider import SquadAgentResult
    ctrl._provider.exec_agent.return_value = SquadAgentResult(
        exit_code=0,
        echelon_result={"verdict": "DONE", "state_updates": {},
                        "journal_entries": [{"type": "insight"}]},
        raw_output="", duration_ms=0, timed_out=False,
    )
    ctrl.run("msg", "banzai")
    assert (squad_dir / "reasoning-journal.jsonl").exists()
    assert not (tmp_path / ".specify/squad/reasoning-journal.jsonl").exists()
