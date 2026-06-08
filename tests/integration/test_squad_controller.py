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
from harness.squad_executors import AgentExecutor
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


class TestSolutionPhaseOrdering:
    def test_specialists_feed_architect_before_sentinel(self):
        graph = PhaseGraph(DEFINITION, EXT_YML)

        specialists_node = graph.get("phase3-specialists")
        specialist_targets = [t["to"] for t in specialists_node.transitions]
        assert specialist_targets == ["phase3-how"]

        how_node = graph.get("phase3-how")
        how_targets = [t["to"] for t in how_node.transitions]
        assert how_targets == ["phase3-sentinel"]

    def test_sentinel_runs_before_plan_so_tests_become_tasks(self):
        graph = PhaseGraph(DEFINITION, EXT_YML)

        sentinel_node = graph.get("phase3-sentinel")
        sentinel_targets = [t["to"] for t in sentinel_node.transitions]
        assert sentinel_targets == ["phase3-plan"]


class TestCartographerResumeGuard:
    def test_phase1_what_prompt_blocks_duplicate_specify_on_resume(self, tmp_path):
        graph = PhaseGraph(DEFINITION, EXT_YML)
        squad_dir = tmp_path / "runs" / "spec-test"
        staging_dir = squad_dir / "staging"
        staging_dir.mkdir(parents=True)
        executor = AgentExecutor(
            _mock_provider(),
            graph,
            EXT_ROOT / "extension",
            tmp_path,
            squad_dir,
        )

        prompt = executor._assemble_prompt(
            graph.get("phase1-what"),
            {
                "squad_dir": str(squad_dir),
                "staging_dir": str(staging_dir),
                "cartographer_resume_existing_spec": True,
                "spec_dir": "specs/072-pr-pipeline-fix",
                "feature_branch": "072-pr-pipeline-fix",
            },
        )

        assert "## CARTOGRAPHER Resume Guard" in prompt
        assert "Do NOT call speckit.specify" in prompt
        assert "Existing spec_dir: specs/072-pr-pipeline-fix" in prompt
        assert "Existing feature_branch: 072-pr-pipeline-fix" in prompt


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
        store = SquadStateStore(tmp_path / "squad" / "run-test")
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

    def test_iterative_phase3_consensus_uses_max_iterations_not_generic_cap(
        self,
        tmp_path,
    ):
        """phase3-consensus can legitimately repeat up to max_iterations."""
        provider = _mock_provider("PASS")
        ctrl, store = _controller(tmp_path, provider, mode="semi")
        store.initialize("r", "semi", "msg", 0, "phase3-consensus", max_iterations=10)
        state = store.load()
        state["iteration"] = 4
        state["phase_dispatch_counts"] = {"phase3-consensus": 5}
        store.save(state)

        result = ctrl.run("msg", "semi")

        assert provider.exec_agent.called
        assert result.status == "done"
        assert store.load().get("blocked_reason") != "phase_dispatch_limit"

    def test_why_fail_increments_on_fail(self, tmp_path):
        """why_fail_count increments when a WHY phase returns quality_gates.fail."""
        from harness.squad_provider import SquadAgentResult
        provider = _mock_provider()
        provider.exec_agent.return_value = SquadAgentResult(
            exit_code=0,
            echelon_result={
                "verdict": "FAIL",
                "state_updates": {"quality_scores": [{"pass": False}]},
            },
            raw_output="", duration_ms=0, timed_out=False,
        )
        ctrl, store = _controller(tmp_path, provider=provider)
        store.initialize("r", "banzai", "msg", 0, "phase1-why1", max_iterations=5)
        ctrl.run("msg", "banzai")
        # why_fail_count should have been incremented (≥1)
        assert store.load().get("why_fail_count", 0) >= 1

    def test_why_fail_resets_on_pass(self, tmp_path):
        """why_fail_count resets when a WHY phase passes."""
        from harness.squad_provider import SquadAgentResult
        provider = _mock_provider()
        provider.exec_agent.return_value = SquadAgentResult(
            exit_code=0,
            echelon_result={
                "verdict": "DONE",
                "state_updates": {"quality_scores": [{"pass": True}]},
            },
            raw_output="", duration_ms=0, timed_out=False,
        )
        ctrl, store = _controller(tmp_path, provider=provider)
        store.initialize("r", "banzai", "msg", 0, "phase1-why1", max_iterations=5)
        store.increment_why_fail_count()
        store.increment_why_fail_count()
        ctrl.run("msg", "banzai")
        assert store.load().get("why_fail_count", 0) == 0

    def test_consecutive_fails_force_escalation(self, tmp_path):
        """≥2 consecutive WHY fails with no staging progress → auto-escalation."""
        from harness.squad_provider import SquadAgentResult
        provider = _mock_provider()
        provider.exec_agent.return_value = SquadAgentResult(
            exit_code=0,
            echelon_result={
                "verdict": "FAIL",
                "state_updates": {"quality_scores": [{"pass": False}]},
            },
            raw_output="", duration_ms=0, timed_out=False,
        )
        ctrl, store = _controller(tmp_path, provider=provider)
        store.initialize("r", "semi", "msg", 0, "phase1-why1", max_iterations=5)
        # Pre-set why_fail_count=1 so next fail triggers guard
        store.increment_why_fail_count()
        # Set last_dispatch.completed_at to a past timestamp so
        # _staging_changed_since does not return True (no staging .md files)
        state = store.load()
        state["last_dispatch"] = {"completed_at": "2020-01-01T00:00:00Z"}
        store.save(state)
        result = ctrl.run("msg", "semi")
        # Should be blocked by consecutive-fail guard
        assert result.status == "blocked"
        state = store.load()
        assert state.get("escalation_question") is not None
        assert "consecutive" in state.get("escalation_question", "").lower()

    def test_banzai_escalation_inline_when_agent_sets_escalation_question(self, tmp_path):
        """Banzai: WHY1 returns escalation_question in state_updates → inline COMMANDER, not routing judge."""
        from harness.squad_provider import SquadAgentResult
        call_count = {"n": 0}

        def side_effect(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                # First call: WHY1 returns FAIL with escalation_question
                return SquadAgentResult(
                    exit_code=0,
                    echelon_result={
                        "verdict": "FAIL",
                        "state_updates": {
                            "quality_scores": [],
                            "escalation_question": "Q1: Do you own the IP?",
                            "blocked_reason": "WHY1: user-gated CRITICAL issues",
                        },
                    },
                    raw_output="", duration_ms=0, timed_out=False,
                )
            if call_count["n"] == 2:
                # Second call: COMMANDER banzai judgment clears the block
                return SquadAgentResult(
                    exit_code=0,
                    echelon_result={
                        "verdict": "JUDGMENT_RESOLVED",
                        "state_updates": {
                            "escalation_question": None,
                            "escalation_resolved": True,
                            "escalation_resolver": "COMMANDER-banzai",
                            "blocked_reason": None,
                        },
                    },
                    raw_output="", duration_ms=0, timed_out=False,
                )
            # Third call+: WHY1 re-dispatch passes (quality_scores present)
            return SquadAgentResult(
                exit_code=0,
                echelon_result={
                    "verdict": "DONE",
                    "state_updates": {"quality_scores": [{"pass": True}]},
                },
                raw_output="", duration_ms=0, timed_out=False,
            )

        provider = _mock_provider()
        provider.exec_agent.side_effect = side_effect
        ctrl, store = _controller(tmp_path, provider=provider)
        store.initialize("r", "banzai", "msg", 0, "phase1-why1", max_iterations=5)
        result = ctrl.run("msg", "banzai")
        # Provider called at least twice: once for WHY1, once for COMMANDER escalation
        assert provider.exec_agent.call_count >= 2
        # Run did not end blocked
        assert result.status != "blocked"

    def test_semi_escalation_inline_when_agent_sets_escalation_question(self, tmp_path):
        """Semi: WHY1 returns escalation_question in state_updates → run stops blocked."""
        from harness.squad_provider import SquadAgentResult
        provider = _mock_provider()
        provider.exec_agent.return_value = SquadAgentResult(
            exit_code=0,
            echelon_result={
                "verdict": "FAIL",
                "state_updates": {
                    "quality_scores": [],
                    "escalation_question": "Q1: Do you own the IP?",
                    "blocked_reason": "WHY1: user-gated CRITICAL issues",
                },
            },
            raw_output="", duration_ms=0, timed_out=False,
        )
        ctrl, store = _controller(tmp_path, provider=provider)
        store.initialize("r", "semi", "msg", 0, "phase1-why1", max_iterations=5)
        result = ctrl.run("msg", "semi")
        assert result.status == "blocked"
        # escalation_question must be in state for echelon resume to pick up
        assert store.load().get("escalation_question")

    def test_banzai_escalation_dispatches_commander_not_stops(self, tmp_path):
        """Banzai mode: blocked+escalation_question → COMMANDER called, run continues."""
        from harness.squad_provider import SquadAgentResult
        provider = _mock_provider()
        # COMMANDER judgment clears the block
        provider.exec_agent.return_value = SquadAgentResult(
            exit_code=0,
            echelon_result={
                "verdict": "JUDGMENT_RESOLVED",
                "state_updates": {
                    "escalation_question": None,
                    "escalation_resolved": True,
                    "escalation_resolver": "COMMANDER-banzai",
                    "blocked_reason": None,
                },
            },
            raw_output="", duration_ms=0, timed_out=False,
        )
        ctrl, store = _controller(tmp_path, provider=provider)
        store.initialize("r", "banzai", "msg", 0, "DONE", max_iterations=5)
        # Pre-set blocked with escalation_question and mode=banzai in state
        state = store.load()
        state["status"] = "blocked"
        state["escalation_question"] = "Q1: Do you have author rights?"
        state["blocked_reason"] = "WHY1: user-gated issues"
        state["mode"] = "banzai"
        store.save(state)

        result = ctrl.run("msg", "banzai")
        # COMMANDER was dispatched, block cleared, run completed (phase=DONE)
        assert result.status != "blocked"
        assert provider.exec_agent.called

    def test_semi_escalation_stops_run(self, tmp_path):
        """Semi mode: blocked+escalation_question → run stops with status=blocked."""
        ctrl, store = _controller(tmp_path)
        store.initialize("r", "semi", "msg", 0, "DONE", max_iterations=5)
        state = store.load()
        state["status"] = "blocked"
        state["escalation_question"] = "Q1: Do you have author rights?"
        state["blocked_reason"] = "WHY1: user-gated issues"
        state["mode"] = "semi"
        store.save(state)
        result = ctrl.run("msg", "semi")
        assert result.status == "blocked"

    def test_guided_escalation_stops_run(self, tmp_path):
        """Guided mode: blocked+escalation_question → run stops with status=blocked."""
        ctrl, store = _controller(tmp_path)
        store.initialize("r", "guided", "msg", 0, "DONE", max_iterations=5)
        state = store.load()
        state["status"] = "blocked"
        state["escalation_question"] = "Q1: Do you have author rights?"
        state["mode"] = "guided"
        store.save(state)
        result = ctrl.run("msg", "guided")
        assert result.status == "blocked"


class TestHumanGate:
    def test_banzai_auto_approves(self, tmp_path):
        from harness.squad_executors import HumanGateExecutor
        graph = PhaseGraph(DEFINITION, EXT_YML)
        store = SquadStateStore(tmp_path / "squad" / "run-test")
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
        store = SquadStateStore(tmp_path / "squad" / "run-test")
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


class TestConvergenceRoutingGuard:
    def test_forced_convergence_skips_why2_dispatch(self, tmp_path):
        provider = _mock_provider("KILL")
        ctrl, store = _controller(tmp_path, provider=provider)
        store.initialize("r", "banzai", "msg", 0, "phase1-why2", max_iterations=5)
        state = store.load()
        state.update({
            "convergence_forced": True,
            "convergence_detected": True,
            "phase_recommendation": "phase2-decide",
            "why_fail_count": 13,
        })
        store.save(state)

        result = ctrl.run("msg", "banzai")

        assert result.status == "done"
        assert store.load()["last_dispatch"]["phase_id"] == "phase2-decide"
        assert provider.exec_agent.call_count == 1

    def test_blocked_empty_escalation_with_convergence_recovers_to_recommendation(self, tmp_path):
        provider = _mock_provider("KILL")
        ctrl, store = _controller(tmp_path, provider=provider)
        store.initialize("r", "banzai", "msg", 0, "phase1-what", max_iterations=5)
        state = store.load()
        state.update({
            "status": "blocked",
            "blocked_reason": "consecutive_why_fails",
            "escalation_question": "",
            "convergence_forced": True,
            "phase_recommendation": "phase2-decide",
        })
        store.save(state)

        result = ctrl.run("msg", "banzai")

        assert result.status == "done"
        assert store.load()["last_dispatch"]["phase_id"] == "phase2-decide"
        assert provider.exec_agent.call_count == 1


class TestBuildPhaseRouting:
    """Regression: 12 build-phase transition conditions used lowercase 'and'
    (e.g. 'verdict = FAIL and fix_cycle < 2'). The evaluator splits only on
    uppercase AND/OR, so every compound was treated as a single field=value
    match that always returned False — fix-cycle routing was silently broken.

    Each test starts SquadController at the relevant build phase, injects the
    appropriate initial state (fix_cycle, etc.), and asserts the first
    (from, to) transition recorded by patching store.advance.
    """

    def _sequenced(self, responses: list) -> MagicMock:
        """Provider whose exec_agent returns responses in order, then DONE."""
        idx = {"n": 0}
        provider = _mock_provider()

        def _side_effect(*args, **kwargs):
            i = idx["n"]
            idx["n"] += 1
            verdict, updates = responses[i] if i < len(responses) else ("DONE", {})
            return SquadAgentResult(
                exit_code=0,
                echelon_result={"verdict": verdict, "state_updates": updates},
                raw_output="",
                duration_ms=0,
                timed_out=False,
            )

        provider.exec_agent.side_effect = _side_effect
        return provider

    def _run_and_capture(
        self,
        tmp_path: Path,
        start_phase: str,
        initial_state: dict,
        provider: MagicMock,
    ) -> list:
        """Run from start_phase and return list of (from_phase, to_phase) transitions."""
        ctrl, store = _controller(tmp_path, provider)
        store.initialize("r", "banzai", "msg", 0, start_phase)
        state = store.load()
        state.update(initial_state)
        store.save(state)

        with patch.object(store, "advance", wraps=store.advance) as spy:
            ctrl.run("msg", "banzai")

        return [(c.args[0], c.args[1]) for c in spy.call_args_list]

    # Shared terminal tail: once a gate passes, drive to build-done quickly.
    # Sequence after the gate under test: implement→spec-guard→code-review→
    # test-guard→progress(all_done)→build-8-finalize(no-op)→build-done.
    _TAIL_FROM_IMPLEMENT = [
        ("DONE", {}),                # implement → spec-guard
        ("PASS", {}),                # spec-guard → code-review
        ("APPROVED", {}),            # code-review → test-guard
        ("PASS", {}),                # test-guard → progress
        ("DONE", {"all_tasks_complete": True, "no_more_phase_checkpoints": True}),
    ]
    _TAIL_FROM_SPEC_GUARD = [
        ("PASS", {}),                # spec-guard → code-review
        ("APPROVED", {}),            # code-review → test-guard
        ("PASS", {}),                # test-guard → progress
        ("DONE", {"all_tasks_complete": True, "no_more_phase_checkpoints": True}),
    ]
    _TAIL_FROM_CODE_REVIEW = [
        ("APPROVED", {}),            # code-review → test-guard
        ("PASS", {}),                # test-guard → progress
        ("DONE", {"all_tasks_complete": True, "no_more_phase_checkpoints": True}),
    ]
    _TAIL_FROM_TEST_GUARD = [
        ("PASS", {}),                # test-guard → progress
        ("DONE", {"all_tasks_complete": True, "no_more_phase_checkpoints": True}),
    ]
    _TAIL_FROM_PROGRESS = [
        ("DONE", {"all_tasks_complete": True, "no_more_phase_checkpoints": True}),
    ]

    # ── build-3-spec-guard ──────────────────────────────────────────────────

    def test_spec_guard_fail_early_routes_to_implement(self, tmp_path):
        """FAIL AND fix_cycle < 2 → implement (fix cycle)."""
        transitions = self._run_and_capture(
            tmp_path,
            start_phase="build-3-spec-guard",
            initial_state={"fix_cycle": 0},
            provider=self._sequenced(
                [("FAIL", {})] + self._TAIL_FROM_IMPLEMENT
            ),
        )
        assert transitions[0] == ("build-3-spec-guard", "build-2-implement")

    def test_spec_guard_fail_late_routes_to_code_review(self, tmp_path):
        """FAIL AND fix_cycle >= 2 → code-review (DEGRADED, skip back-route)."""
        transitions = self._run_and_capture(
            tmp_path,
            start_phase="build-3-spec-guard",
            initial_state={"fix_cycle": 2},
            provider=self._sequenced(
                [("FAIL", {})] + self._TAIL_FROM_CODE_REVIEW
            ),
        )
        assert transitions[0] == ("build-3-spec-guard", "build-4-code-review")

    # ── build-4-code-review ─────────────────────────────────────────────────

    def test_code_review_changes_early_routes_to_implement(self, tmp_path):
        """CHANGES_REQUESTED AND fix_cycle < 2 → implement."""
        transitions = self._run_and_capture(
            tmp_path,
            start_phase="build-4-code-review",
            initial_state={"fix_cycle": 0},
            provider=self._sequenced(
                [("CHANGES_REQUESTED", {})] + self._TAIL_FROM_IMPLEMENT
            ),
        )
        assert transitions[0] == ("build-4-code-review", "build-2-implement")

    def test_code_review_changes_late_routes_to_test_guard(self, tmp_path):
        """CHANGES_REQUESTED AND fix_cycle >= 2 → test-guard (DEGRADED)."""
        transitions = self._run_and_capture(
            tmp_path,
            start_phase="build-4-code-review",
            initial_state={"fix_cycle": 2},
            provider=self._sequenced(
                [("CHANGES_REQUESTED", {})] + self._TAIL_FROM_TEST_GUARD
            ),
        )
        assert transitions[0] == ("build-4-code-review", "build-5-test-guard")

    # ── build-5-test-guard ──────────────────────────────────────────────────

    def test_test_guard_fail_early_routes_to_implement(self, tmp_path):
        """FAIL AND fix_cycle < 2 → implement."""
        transitions = self._run_and_capture(
            tmp_path,
            start_phase="build-5-test-guard",
            initial_state={"fix_cycle": 0},
            provider=self._sequenced(
                [("FAIL", {})] + self._TAIL_FROM_IMPLEMENT
            ),
        )
        assert transitions[0] == ("build-5-test-guard", "build-2-implement")

    def test_test_guard_fail_late_routes_to_progress(self, tmp_path):
        """FAIL AND fix_cycle >= 2 → progress (DEGRADED)."""
        transitions = self._run_and_capture(
            tmp_path,
            start_phase="build-5-test-guard",
            initial_state={"fix_cycle": 2},
            provider=self._sequenced(
                [("FAIL", {})] + self._TAIL_FROM_PROGRESS
            ),
        )
        assert transitions[0] == ("build-5-test-guard", "build-6-progress")

    # ── build-6-progress ────────────────────────────────────────────────────

    def test_progress_all_done_routes_to_finalize(self, tmp_path):
        """all_tasks_complete AND no_more_phase_checkpoints → build-8-finalize."""
        transitions = self._run_and_capture(
            tmp_path,
            start_phase="build-6-progress",
            initial_state={},
            provider=self._sequenced(
                [("DONE", {"all_tasks_complete": True, "no_more_phase_checkpoints": True})]
            ),
        )
        assert transitions[0] == ("build-6-progress", "build-8-finalize")

    def test_progress_more_tasks_routes_to_implement(self, tmp_path):
        """more_tasks_in_phase_group → build-2-implement (next task)."""
        transitions = self._run_and_capture(
            tmp_path,
            start_phase="build-6-progress",
            initial_state={"more_tasks_in_phase_group": True},
            provider=self._sequenced(
                [("DONE", {})] + self._TAIL_FROM_IMPLEMENT
            ),
        )
        assert transitions[0] == ("build-6-progress", "build-2-implement")

    # ── build-7-integration ─────────────────────────────────────────────────

    def test_integration_fail_early_routes_to_implement(self, tmp_path):
        """FAIL AND fix_cycle < 2 → implement."""
        transitions = self._run_and_capture(
            tmp_path,
            start_phase="build-7-integration",
            initial_state={"fix_cycle": 0},
            provider=self._sequenced(
                [("FAIL", {})] + self._TAIL_FROM_IMPLEMENT
            ),
        )
        assert transitions[0] == ("build-7-integration", "build-2-implement")

    def test_integration_fail_late_routes_to_finalize(self, tmp_path):
        """FAIL AND fix_cycle >= 2 → build-8-finalize (DEGRADED)."""
        transitions = self._run_and_capture(
            tmp_path,
            start_phase="build-7-integration",
            initial_state={"fix_cycle": 2},
            provider=self._sequenced([("FAIL", {})]),
        )
        assert transitions[0] == ("build-7-integration", "build-8-finalize")

    def test_integration_pass_more_groups_routes_to_implement(self, tmp_path):
        """PASS AND more_phase_groups → implement (next phase group)."""
        transitions = self._run_and_capture(
            tmp_path,
            start_phase="build-7-integration",
            initial_state={"more_phase_groups": True},
            provider=self._sequenced(
                [("PASS", {})] + self._TAIL_FROM_IMPLEMENT
            ),
        )
        assert transitions[0] == ("build-7-integration", "build-2-implement")

    def test_integration_pass_all_done_routes_to_finalize(self, tmp_path):
        """PASS AND all_phase_groups_complete → build-8-finalize."""
        transitions = self._run_and_capture(
            tmp_path,
            start_phase="build-7-integration",
            initial_state={"all_phase_groups_complete": True},
            provider=self._sequenced([("PASS", {})]),
        )
        assert transitions[0] == ("build-7-integration", "build-8-finalize")

    # ── build-2-implement (self-loop on NEEDS_CONTEXT) ──────────────────────

    def test_implement_needs_context_early_retries(self, tmp_path):
        """NEEDS_CONTEXT AND retry_count < 2 → self-loop back to implement."""
        transitions = self._run_and_capture(
            tmp_path,
            start_phase="build-2-implement",
            initial_state={"retry_count": 0},
            provider=self._sequenced(
                [("NEEDS_CONTEXT", {})] + self._TAIL_FROM_IMPLEMENT
            ),
        )
        assert transitions[0] == ("build-2-implement", "build-2-implement")


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


class TestConstitutionPhase:
    """Regression: phase1-constitution must dispatch CHIEF (agent), not be a no-op."""

    def test_phase1_constitution_is_agent_not_commander_internal(self, tmp_path):
        """phase1-constitution must be type=agent so CHIEF gets dispatched."""
        graph = PhaseGraph(DEFINITION, EXT_YML)
        node = graph.get("phase1-constitution")
        assert node.type == "agent", (
            f"phase1-constitution must be type=agent (so CHIEF is dispatched by the harness). "
            f"Got: {node.type!r}. commander_internal silently skips the phase."
        )

    def test_phase1_constitution_agent_is_chief_not_commander(self, tmp_path):
        """phase1-constitution must dispatch CHIEF, not COMMANDER."""
        graph = PhaseGraph(DEFINITION, EXT_YML)
        node = graph.get("phase1-constitution")
        assert node.agent == "speckit-echelon-chief", (
            f"phase1-constitution must dispatch speckit-echelon-chief. "
            f"Got: {node.agent!r}. COMMANDER must not own constitution creation."
        )

    def test_chief_resolves_to_agent_file(self, tmp_path):
        """speckit-echelon-chief must resolve to a real agent file path."""
        graph = PhaseGraph(DEFINITION, EXT_YML)
        rel = graph.agent_file("speckit-echelon-chief")
        assert rel == "agents/control/chief.md", (
            f"speckit-echelon-chief should resolve to agents/control/chief.md. "
            f"Got: {rel!r}. Check extension.yml provides.commands registration."
        )
        agent_path = EXT_ROOT / "extension" / rel
        assert agent_path.exists(), f"Agent file not found: {agent_path}"

    def test_chief_has_constitution_context_pack(self, tmp_path):
        """phase1-constitution must include staging artifacts in context_pack."""
        graph = PhaseGraph(DEFINITION, EXT_YML)
        node = graph.get("phase1-constitution")
        pack = " ".join(node.context_pack)
        assert "glossary" in pack
        assert "mental-model" in pack
        assert "boundaries" in pack
        assert "assumptions" in pack
        assert "user-intent" in pack

    def test_chief_dispatched_in_controller(self, tmp_path):
        """SquadController dispatches an agent (not no-op) for phase1-constitution."""
        provider = _mock_provider()
        ctrl, store = _controller(tmp_path, provider)
        store.initialize("r", "banzai", "msg", 0, "phase1-constitution")
        ctrl.run("msg", "banzai")
        # AgentExecutor calls exec_agent; CommanderInternalExecutor does not.
        assert provider.exec_agent.called, (
            "exec_agent was not called — phase1-constitution is still a harness no-op. "
            "It must be type=agent so CHIEF gets dispatched."
        )
