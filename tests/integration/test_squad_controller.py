"""Integration tests for SquadController with mock provider.

The most important test: test_consensus_cannot_be_skipped.
A mock agent always returns DONE. SquadController must still dispatch
WHY3 + ASSESS2 (stage 1) before PLAN2 (stage 2) and before checkpoint-plan.
"""
import sys
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

EXT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(EXT_ROOT) not in sys.path:
    sys.path.insert(0, str(EXT_ROOT))

from harness.phase_graph import PhaseGraph, PhaseNode
from harness.re_controller import ReControllerResult
from harness.squad import (
    SquadController,
    SquadResult,
    _constitution_artifact_is_real,
    _phase_requires_constitution_provenance,
)
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


def _mark_constitution_complete(tmp_path: Path, store: SquadStateStore) -> None:
    const_path = tmp_path / ".specify" / "memory" / "constitution.md"
    const_path.parent.mkdir(parents=True, exist_ok=True)
    const_path.write_text("# Constitution\n\nReal project rules.\n", encoding="utf-8")
    state = store.load()
    completed = state.get("completed_phases")
    completed_phases = completed if isinstance(completed, list) else []
    if "phase1-constitution" not in completed_phases:
        completed_phases.append("phase1-constitution")
    state["completed_phases"] = completed_phases
    store.save(state)


def _write_re_index_generation(root: Path, generation: int) -> None:
    path = root / "re" / "index.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "generation": generation,
                "publication_status": "complete",
                "published_at": "2026-07-12T12:00:00+00:00",
                "published_from_run": "fixture",
                "sources": {},
                "workspace": {
                    "manifest": "re/workspace/manifest.json",
                    "overview": "re/workspace/overview.md",
                    "relationships": "re/workspace/relationships.md",
                    "contracts": "re/workspace/contracts.md",
                },
                "warnings": [],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


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


class TestAgentResultIntegrity:
    def test_provider_session_limit_is_primary_over_missing_result(self, tmp_path):
        provider = _mock_provider()
        provider.exec_agent.return_value = SquadAgentResult(
            exit_code=2,
            echelon_result=None,
            raw_output="You've hit your session limit · resets 4am (Europe/Prague)",
            duration_ms=100,
            timed_out=False,
            provider_limit_message="You've hit your session limit · resets 4am (Europe/Prague)",
        )
        ctrl, store = _controller(tmp_path, provider=provider)
        store.initialize("r", "banzai", "msg", 0, "phase1-what", max_iterations=5)
        _mark_constitution_complete(tmp_path, store)

        result = ctrl.run("msg", "banzai")
        state = store.load()

        assert result.status == "blocked"
        assert state["blocked_reason"] == "provider_session_limit"
        assert state["provider_limit_message"] == "You've hit your session limit · resets 4am (Europe/Prague)"
        assert state["blocked_context"] == "missing_echelon_result"

    def test_agent_phase_without_parseable_echelon_result_blocks(self, tmp_path):
        provider = _mock_provider()
        provider.exec_agent.return_value = SquadAgentResult(
            exit_code=0,
            echelon_result=None,
            raw_output=(
                "speckit-echelon-cartographer (CARTOGRAPHER) BLOCKED — "
                "speckit.specify execution incomplete"
            ),
            duration_ms=100,
            timed_out=False,
        )
        ctrl, store = _controller(tmp_path, provider=provider)
        store.initialize("r", "banzai", "msg", 0, "phase1-what", max_iterations=5)
        _mark_constitution_complete(tmp_path, store)

        result = ctrl.run("msg", "banzai")
        state = store.load()

        assert result.status == "blocked"
        assert state["phase"] == "terminal-blocked"
        assert state["status"] == "blocked"
        assert state["blocked_reason"] == "missing_echelon_result"
        assert "phase1-what" not in state.get("completed_phases", [])

    def test_phase1_what_missing_result_preserves_existing_spec_context(self, tmp_path):
        provider = _mock_provider()
        provider.exec_agent.return_value = SquadAgentResult(
            exit_code=0,
            echelon_result=None,
            raw_output="connection closed after CARTOGRAPHER wrote spec artifacts",
            duration_ms=100,
            timed_out=False,
        )
        spec_dir = tmp_path / "specs" / "001-demo-notes"
        spec_dir.mkdir(parents=True)
        (spec_dir / "spec.md").write_text("# Demo Notes\n", encoding="utf-8")
        ctrl, store = _controller(tmp_path, provider=provider)
        store.initialize("r", "banzai", "msg", 0, "phase1-what", max_iterations=5)
        _mark_constitution_complete(tmp_path, store)

        with patch.object(ctrl, "_current_git_branch", return_value="001-demo-notes"):
            result = ctrl.run("msg", "banzai")
        state = store.load()

        assert result.status == "blocked"
        assert state["phase"] == "terminal-blocked"
        assert state["blocked_reason"] == "missing_echelon_result"
        assert state["spec_id"] == "001-demo-notes"
        assert state["spec_dir"] == "specs/001-demo-notes"
        assert state["published_spec_dir"] == "specs/001-demo-notes"
        assert state["feature_branch"] == "001-demo-notes"
        assert state["cartographer_resume_existing_spec"] is True
        assert "phase1-what" not in state.get("completed_phases", [])

    def test_phase4_document_blocks_when_phase_a_build_inputs_are_missing(
        self, tmp_path,
    ):
        ctrl, store = _controller(tmp_path)
        store.initialize("r", "banzai", "msg", 0, "phase4-document", max_iterations=5)
        _mark_constitution_complete(tmp_path, store)
        spec_dir = tmp_path / "runs" / "run-test" / "specs" / "001-demo"
        spec_dir.mkdir(parents=True)
        for name in ("plan.md", "research.md", "data-model.md", "tasks.md"):
            (spec_dir / name).write_text(f"# {name}\n", encoding="utf-8")
        state = store.load()
        state["spec_id"] = "001-demo"
        state["spec_dir"] = "runs/run-test/specs/001-demo"
        store.save(state)

        result = ctrl.run("msg", "banzai")
        state = store.load()

        assert result.status == "blocked"
        assert state["phase"] == "terminal-blocked"
        assert state["blocked_reason"] == "phase_a_readiness_failed"
        assert "spec.md absent" in "\n".join(state["phase_a_readiness_blockers"])

    def test_phase4_document_completes_when_phase_a_build_inputs_exist(
        self, tmp_path,
    ):
        ctrl, store = _controller(tmp_path)
        store.initialize("r", "banzai", "msg", 0, "phase4-document", max_iterations=5)
        _mark_constitution_complete(tmp_path, store)
        spec_dir = tmp_path / "runs" / "run-test" / "specs" / "001-demo"
        spec_dir.mkdir(parents=True)
        for name in ("spec.md", "plan.md", "research.md", "data-model.md", "tasks.md"):
            (spec_dir / name).write_text(f"# {name}\n", encoding="utf-8")
        state = store.load()
        state["spec_id"] = "001-demo"
        state["spec_dir"] = "runs/run-test/specs/001-demo"
        store.save(state)

        result = ctrl.run("msg", "banzai")

        assert result.status == "done"
        published_dir = tmp_path / "specs" / "001-demo"
        assert (published_dir / "spec.md").exists()
        assert (published_dir / "plan.md").exists()
        assert (published_dir / "tasks.md").exists()
        assert (
            published_dir / "constitution.md"
        ).read_text(encoding="utf-8") == "# Constitution\n\nReal project rules.\n"
        assert (published_dir / "ARTIFACTS.md").exists()
        assert (published_dir / "squad-report.md").exists()
        history = json.loads((published_dir / "run-history.json").read_text(encoding="utf-8"))
        assert history["runs"][-1]["run_id"] == "r"
        assert history["runs"][-1]["phase"] == "A"
        assert history["runs"][-1]["status"] == "done"
        state = store.load()
        assert state["published_spec_dir"] == "specs/001-demo"

    def test_phase4_document_publishes_complete_artifacts_to_existing_slugged_spec(
        self, tmp_path,
    ):
        ctrl, store = _controller(tmp_path)
        store.initialize("r", "banzai", "msg", 0, "phase4-document", max_iterations=5)
        _mark_constitution_complete(tmp_path, store)

        active_spec_dir = tmp_path / "runs" / "run-test" / "specs" / "001"
        active_spec_dir.mkdir(parents=True)
        for name in ("spec.md", "plan.md", "research.md", "data-model.md", "tasks.md"):
            (active_spec_dir / name).write_text(f"# active {name}\n", encoding="utf-8")
        (active_spec_dir / "contracts").mkdir()
        (active_spec_dir / "contracts" / "api.md").write_text("# Contract\n", encoding="utf-8")

        published_dir = tmp_path / "specs" / "001-themed-ascii-animation"
        published_dir.mkdir(parents=True)
        (published_dir / "spec.md").write_text("# stale spec\n", encoding="utf-8")
        (published_dir / "manual-note.md").write_text("# Keep me\n", encoding="utf-8")

        state = store.load()
        state["spec_id"] = "001"
        state["spec_dir"] = "runs/run-test/specs/001"
        store.save(state)

        result = ctrl.run("msg", "banzai")
        state = store.load()

        assert result.status == "done"
        assert (published_dir / "spec.md").read_text(encoding="utf-8") == "# active spec.md\n"
        assert (published_dir / "plan.md").exists()
        assert (published_dir / "research.md").exists()
        assert (published_dir / "data-model.md").exists()
        assert (published_dir / "tasks.md").exists()
        assert (
            published_dir / "constitution.md"
        ).read_text(encoding="utf-8") == "# Constitution\n\nReal project rules.\n"
        assert (published_dir / "contracts" / "api.md").exists()
        assert (published_dir / "manual-note.md").exists()
        assert (published_dir / "ARTIFACTS.md").exists()
        assert (published_dir / "squad-report.md").exists()
        assert (published_dir / "run-history.json").exists()
        assert state["published_spec_dir"] == "specs/001-themed-ascii-animation"

    def test_checkpoint_plan_auto_routes_without_commander_judgment(self, tmp_path):
        provider = MagicMock()
        provider.exec_agent.side_effect = AssertionError(
            "checkpoint-plan should not dispatch COMMANDER judgment in banzai"
        )
        ctrl, store = _controller(tmp_path, provider=provider)
        store.initialize("r", "banzai", "msg", 0, "checkpoint-plan", max_iterations=5)
        _mark_constitution_complete(tmp_path, store)

        spec_dir = tmp_path / "runs" / "run-test" / "specs" / "001-demo"
        spec_dir.mkdir(parents=True)
        for name in ("spec.md", "plan.md", "research.md", "data-model.md", "tasks.md"):
            (spec_dir / name).write_text(f"# {name}\n", encoding="utf-8")
        state = store.load()
        state["spec_id"] = "001-demo"
        state["spec_dir"] = "runs/run-test/specs/001-demo"
        store.save(state)

        result = ctrl.run("msg", "banzai")

        assert result.status == "done"
        assert provider.exec_agent.call_count == 0


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
    def test_generation_change_blocks_before_normal_executor_dispatch(self, tmp_path):
        provider = _mock_provider()
        ctrl, store = _controller(tmp_path, provider=provider)
        store.initialize("r", "brownfield", "msg", 0, "phase1-tracker")
        state = store.load()
        state["re_generation"] = 1
        store.save(state)
        _write_re_index_generation(tmp_path, 2)

        result = ctrl.run("msg", "banzai")

        assert result.status == "blocked"
        state = store.load()
        assert state["blocked_reason"] == "re_generation_mismatch"
        assert state["re_generation_expected"] == 1
        assert state["re_generation_actual"] == 2
        assert state.get("phase_dispatch_counts", {}).get("phase1-tracker", 0) == 0
        provider.exec_agent.assert_not_called()

    def test_generation_change_blocks_manual_phase_before_executor_dispatch(self, tmp_path):
        provider = _mock_provider()
        ctrl, store = _controller(tmp_path, provider=provider)
        store.initialize("r", "brownfield", "msg", 0, "phase1-tracker")
        state = store.load()
        state["re_generation"] = 1
        store.save(state)
        _write_re_index_generation(tmp_path, 2)

        result = ctrl.run_single_phase("phase1-tracker", "msg", "banzai")

        assert result.status == "blocked"
        state = store.load()
        assert state["blocked_reason"] == "re_generation_mismatch"
        assert state["re_generation_expected"] == 1
        assert state["re_generation_actual"] == 2
        provider.exec_agent.assert_not_called()

    def test_fresh_run_detects_project_mode_separately_from_autonomy_mode(self, tmp_path):
        for i in range(6):
            (tmp_path / f"module_{i}.py").write_text("pass\n", encoding="utf-8")

        ctrl, store = _controller(tmp_path, mode="banzai")

        result = ctrl.run("msg", "banzai", next_phase_override="DONE")

        assert result.status == "done"
        state = store.load()
        assert state["mode"] == "brownfield"
        assert state["autonomy_mode"] == "banzai"

    def test_brownfield_discovery_runs_mode1_controller_before_scout(
        self,
        tmp_path,
        monkeypatch,
    ):
        provider = MagicMock()
        provider.exec_agent.return_value = SquadAgentResult(
            exit_code=0,
            echelon_result={"verdict": "DONE", "state_updates": {}},
            raw_output="",
            duration_ms=50,
            timed_out=False,
        )
        graph = PhaseGraph(DEFINITION, EXT_YML)
        squad_dir = tmp_path / "squad" / "run-test"
        squad_dir.mkdir(parents=True, exist_ok=True)
        (squad_dir / "staging").mkdir(exist_ok=True)
        store = SquadStateStore(squad_dir)
        store.initialize("r", "brownfield", "msg", 0, "phase1-discover", autonomy_mode="banzai")
        executor = AgentExecutor(
            provider,
            graph,
            EXT_ROOT / "extension",
            tmp_path,
            squad_dir,
        )

        controller_calls = []

        class CompleteController:
            def __init__(self, **kwargs):
                controller_calls.append(kwargs)

            def run(self):
                return ReControllerResult(completed=True)

        monkeypatch.setattr(
            "harness.squad_executors.ReExtractionController",
            CompleteController,
        )

        executor.execute(graph.get("phase1-discover"), store)

        assert len(controller_calls) == 1
        assert controller_calls[0]["project_root"] == tmp_path
        assert controller_calls[0]["run_dir"] == squad_dir
        assert provider.exec_agent.call_count == 1
        state = store.load()
        assert state["golddigger_status"] == "complete"

    def test_blocked_re_recovery_does_not_consume_discovery_dispatches(
        self, tmp_path
    ):
        ctrl, store = _controller(tmp_path)
        store.initialize("r", "brownfield", "msg", 0, "phase1-discover")
        for _ in range(6):
            store.increment_phase_dispatch_count("phase1-discover")
        re_state_path = ctrl._squad_dir / "re" / "state.json"
        re_state_path.parent.mkdir(parents=True, exist_ok=True)
        re_state_path.write_text(
            json.dumps(
                {
                    "status": "blocked",
                    "phase": "re-extract-2-specify",
                    "blocked_reason": "re_quality_repair_modified_non_target_output",
                }
            ),
            encoding="utf-8",
        )

        ctrl._reset_discovery_dispatches_for_pending_recovery("phase1-discover")

        assert store.get_phase_dispatch_count("phase1-discover") == 0

    def test_discovery_dispatch_count_remains_for_non_re_failure(self, tmp_path):
        ctrl, store = _controller(tmp_path)
        store.initialize("r", "brownfield", "msg", 0, "phase1-discover")
        store.increment_phase_dispatch_count("phase1-discover")
        re_state_path = ctrl._squad_dir / "re" / "state.json"
        re_state_path.parent.mkdir(parents=True, exist_ok=True)
        re_state_path.write_text(
            json.dumps({"status": "done", "phase": "re-extract-7-constitute"}),
            encoding="utf-8",
        )

        ctrl._reset_discovery_dispatches_for_pending_recovery("phase1-discover")

        assert store.get_phase_dispatch_count("phase1-discover") == 1

    def test_golddigger_mode1_complete_is_preserved_when_publication_not_required(
        self,
        tmp_path,
        monkeypatch,
    ):
        provider = MagicMock()
        provider.exec_agent.return_value = SquadAgentResult(
            exit_code=0,
            echelon_result={"verdict": "DONE", "state_updates": {}},
            raw_output="",
            duration_ms=50,
            timed_out=False,
        )
        graph = PhaseGraph(DEFINITION, EXT_YML)
        squad_dir = tmp_path / "squad" / "run-test"
        squad_dir.mkdir(parents=True, exist_ok=True)
        (squad_dir / "staging").mkdir(exist_ok=True)
        store = SquadStateStore(squad_dir)
        store.initialize("r", "brownfield", "msg", 0, "phase1-discover", autonomy_mode="banzai")
        executor = AgentExecutor(
            provider,
            graph,
            EXT_ROOT / "extension",
            tmp_path,
            squad_dir,
        )

        class CompleteController:
            def __init__(self, **_kwargs):
                pass

            def run(self):
                return ReControllerResult(completed=True)

        monkeypatch.setattr(
            "harness.squad_executors.ReExtractionController",
            CompleteController,
        )

        executor.execute(graph.get("phase1-discover"), store)

        assert store.load()["golddigger_status"] == "complete"
        assert provider.exec_agent.call_count == 1

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
        state = store.load()
        assert state["status"] == "interrupted"
        assert state["phase"] == "init"
        assert state["interrupted_phase"] == "init"

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
        _mark_constitution_complete(tmp_path, store)
        spec_dir = tmp_path / "runs" / "run-test" / "specs" / "001-demo"
        spec_dir.mkdir(parents=True)
        for name in ("spec.md", "plan.md", "research.md", "data-model.md", "tasks.md"):
            (spec_dir / name).write_text(f"# {name}\n", encoding="utf-8")
        state = store.load()
        state["spec_id"] = "001-demo"
        state["spec_dir"] = "runs/run-test/specs/001-demo"
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

    def test_why_fail_string_pass_value_routes_to_repair(self, tmp_path):
        """Non-boolean quality_scores.pass must not make WHY failure pass."""
        from harness.squad_provider import SquadAgentResult
        provider = _mock_provider()
        provider.exec_agent.return_value = SquadAgentResult(
            exit_code=0,
            echelon_result={
                "verdict": "FAIL",
                "state_updates": {
                    "quality_scores": [{
                        "pass": "WHY2-iter-0",
                        "overall": 0.745,
                        "structure": 0.660,
                        "testability": 0.679,
                    }]
                },
            },
            raw_output="",
            duration_ms=0,
            timed_out=False,
        )
        ctrl, store = _controller(tmp_path, provider=provider)
        store.initialize("r", "banzai", "msg", 0, "phase1-why2", max_iterations=5)
        _mark_constitution_complete(tmp_path, store)

        node = ctrl._graph.get("phase1-why2")
        result = provider.exec_agent.return_value
        next_phase = ctrl._evaluate_transitions(node, result)
        store.advance(
            "phase1-why2",
            next_phase,
            result,
            allowed_state_update_keys=node.allowed_state_updates,
        )

        state = store.load()
        assert state["phase"] == "phase1-what"
        assert state["quality_scores"][-1]["pass"] is False
        assert state["quality_scores"][-1]["pass_id"] == "WHY2-iter-0"
        assert state.get("why_fail_count", 0) >= 1

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

    def test_banzai_escalation_inline_when_agent_sets_escalation_question(self, tmp_path, monkeypatch):
        """Banzai: WHY1 returns escalation_question in state_updates → inline COMMANDER, not routing judge."""
        from harness.squad_provider import SquadAgentResult
        call_count = {"n": 0}
        checkpoint_calls = []

        def fake_checkpoint(**kwargs):
            checkpoint_calls.append(kwargs)
            return None

        monkeypatch.setattr("harness.squad.create_phase_checkpoint", fake_checkpoint)

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
            if call_count["n"] == 3:
                # Third call: WHY1 re-dispatch passes (quality_scores present)
                return SquadAgentResult(
                    exit_code=0,
                    echelon_result={
                        "verdict": "DONE",
                        "state_updates": {"quality_scores": [{"pass": True}]},
                    },
                    raw_output="", duration_ms=0, timed_out=False,
                )
            if call_count["n"] == 4:
                # CHIEF/constitution uses a different phase contract.
                return SquadAgentResult(
                    exit_code=0,
                    echelon_result={
                        "verdict": "DONE",
                        "state_updates": {"constitution_status": "exists"},
                    },
                    raw_output="", duration_ms=0, timed_out=False,
                )
            if call_count["n"] == 5:
                # CARTOGRAPHER/WHAT writes spec metadata, not quality scores.
                return SquadAgentResult(
                    exit_code=0,
                    echelon_result={
                        "verdict": "DONE",
                        "state_updates": {
                            "spec_id": "001-test",
                            "spec_dir": "specs/001-test",
                            "spec_status": "drafted",
                            "lexicon_pass": True,
                        },
                    },
                    raw_output="", duration_ms=0, timed_out=False,
                )
            if call_count["n"] == 6:
                # WHY2 quality gate passes.
                return SquadAgentResult(
                    exit_code=0,
                    echelon_result={
                        "verdict": "DONE",
                        "state_updates": {"quality_scores": [{"pass": True}]},
                    },
                    raw_output="", duration_ms=0, timed_out=False,
                )
            # End the flow at phase2-decide so this test remains focused on
            # banzai escalation recovery rather than full Phase A artifact output.
            return SquadAgentResult(
                exit_code=0,
                echelon_result={
                    "verdict": "KILL",
                    "state_updates": {},
                },
                raw_output="", duration_ms=0, timed_out=False,
            )

        provider = _mock_provider()
        provider.exec_agent.side_effect = side_effect
        ctrl, store = _controller(tmp_path, provider=provider)
        store.initialize("r", "banzai", "msg", 0, "phase1-why1", max_iterations=5)
        _mark_constitution_complete(tmp_path, store)
        staging = tmp_path / "squad" / "run-test" / "staging"
        state = store.load()
        state["spec_id"] = "001-test"
        state["spec_dir"] = str(staging.relative_to(tmp_path))
        store.save(state)
        result = ctrl.run("msg", "banzai")
        # Provider called at least twice: once for WHY1, once for COMMANDER escalation
        assert provider.exec_agent.call_count >= 2
        # Run did not end blocked
        assert result.status != "blocked"
        assert any(
            call["phase"] == "phase1-why1"
            and call["next_phase"] == "phase1-why1"
            and call["spec_id"] == "001-test"
            for call in checkpoint_calls
        )

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

    def test_phase1_tracker_stop_and_ask_blocks_with_resume_question(self, tmp_path):
        """TRACKER STOP_AND_ASK must produce a resumable blocked run."""
        from harness.squad_provider import SquadAgentResult
        provider = _mock_provider()
        provider.exec_agent.return_value = SquadAgentResult(
            exit_code=0,
            echelon_result={
                "verdict": "STOP_AND_ASK",
                "state_updates": {
                    "status": "blocked",
                    "blocked_reason": "phase1-tracker: user intent needs clarification",
                    "escalation_question": "Should Echelon target Opta Stark, MSA, or both?",
                },
            },
            raw_output="",
            duration_ms=0,
            timed_out=False,
        )
        ctrl, store = _controller(tmp_path, provider=provider)
        store.initialize("r", "semi", "msg", 0, "phase1-tracker", max_iterations=5)

        result = ctrl.run("msg", "semi")
        state = store.load()

        assert result.status == "blocked"
        assert state["phase"] == "phase1-tracker"
        assert state["blocked_reason"] == "phase1-tracker: user intent needs clarification"
        assert state["escalation_question"] == "Should Echelon target Opta Stark, MSA, or both?"

    def test_fresh_checkpoint_question_ignores_stale_escalation_resolved(self, tmp_path):
        """A prior resume must not suppress a later checkpoint human-gate question."""
        provider = _mock_provider()
        provider.exec_agent.return_value = SquadAgentResult(
            exit_code=0,
            echelon_result={
                "verdict": "JUDGMENT_RESOLVED",
                "state_updates": {
                    "status": "blocked",
                    "blocked_reason": "checkpoint-assess human gate",
                    "escalation_question": "Approve the Phase 1 gate?",
                    "escalation_options": [
                        {
                            "id": "proceed_to_decide",
                            "label": "Approve gate",
                            "next_phase": "phase2-decide",
                        }
                    ],
                },
            },
            raw_output="",
            duration_ms=0,
            timed_out=False,
        )
        ctrl, store = _controller(tmp_path, provider=provider, mode="semi")
        store.initialize("r", "semi", "msg", 0, "checkpoint-assess", max_iterations=5)
        _mark_constitution_complete(tmp_path, store)
        state = store.load()
        state["escalation_resolved"] = True
        store.save(state)

        result = ctrl.run("msg", "semi")
        state = store.load()

        assert result.status == "blocked"
        assert provider.exec_agent.call_count == 1
        assert state["blocked_reason"] == "checkpoint-assess human gate"
        assert state["escalation_question"] == "Approve the Phase 1 gate?"
        assert state["escalation_resolved"] is False
        assert state.get("blocked_reason") != "phase_dispatch_limit"

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
        _mark_constitution_complete(tmp_path, store)

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
        _mark_constitution_complete(tmp_path, store)

        result = ctrl.run("msg", "banzai")

        assert result.status == "done"
        assert store.load()["last_dispatch"]["phase_id"] == "phase2-decide"
        assert provider.exec_agent.call_count == 1


class TestConsensusAcceptWithRiskRouting:
    def test_accept_with_risk_consensus_advances_to_checkpoint_not_how(self, tmp_path):
        provider = MagicMock()

        def _side_effect(project_root: str, prompt: str, *args, **kwargs):
            if "Operate in **WHY3** mode" in prompt:
                return SquadAgentResult(
                    exit_code=0,
                    echelon_result={"verdict": "FAIL", "state_updates": {}},
                    raw_output="",
                    duration_ms=0,
                    timed_out=False,
                )
            if "Operate in **ASSESS2** mode" in prompt:
                return SquadAgentResult(
                    exit_code=0,
                    echelon_result={"verdict": "PASS", "state_updates": {}},
                    raw_output="",
                    duration_ms=0,
                    timed_out=False,
                )
            if "Operate in **PLAN2** mode" in prompt:
                return SquadAgentResult(
                    exit_code=0,
                    echelon_result={
                        "verdict": "COMPLETE",
                        "state_updates": {
                            "gate_decision": "accept_with_risk",
                            "convergence_forced": True,
                            "phase_recommendation": "advance_past_consensus_to_delivery",
                        },
                    },
                    raw_output="",
                    duration_ms=0,
                    timed_out=False,
                )
            if "COMMANDER JUDGMENT REQUEST" in prompt:
                return SquadAgentResult(
                    exit_code=0,
                    echelon_result={
                        "verdict": "DONE",
                        "state_updates": {"next_phase": "phase4-document"},
                    },
                    raw_output="",
                    duration_ms=0,
                    timed_out=False,
                )
            raise AssertionError(f"unexpected agent prompt:\n{prompt[:400]}")

        provider.exec_agent.side_effect = _side_effect
        ctrl, store = _controller(tmp_path, provider=provider)
        store.initialize("r", "banzai", "msg", 0, "phase3-consensus", max_iterations=10)
        state = store.load()
        state.update({"iteration": 9, "spec_dir": "specs/071-rule-studio"})
        store.save(state)
        _mark_constitution_complete(tmp_path, store)
        spec_dir = tmp_path / "specs" / "071-rule-studio"
        spec_dir.mkdir(parents=True)
        for name in ("spec.md", "plan.md", "research.md", "data-model.md", "tasks.md"):
            (spec_dir / name).write_text(f"# {name}\n", encoding="utf-8")

        with patch.object(store, "advance", wraps=store.advance) as spy:
            result = ctrl.run("msg", "banzai")

        transitions = [(c.args[0], c.args[1]) for c in spy.call_args_list]

        assert result.status == "done"
        assert ("phase3-consensus", "checkpoint-plan") in transitions
        assert ("phase3-consensus", "phase3-how") not in transitions


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
        _mark_constitution_complete(tmp_path, store)

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

    def test_progress_all_done_routes_to_documentation(self, tmp_path):
        """all_tasks_complete AND no_more_phase_checkpoints → build-8-documentation."""
        transitions = self._run_and_capture(
            tmp_path,
            start_phase="build-6-progress",
            initial_state={},
            provider=self._sequenced(
                [("DONE", {"all_tasks_complete": True, "no_more_phase_checkpoints": True})]
            ),
        )
        assert transitions[0] == ("build-6-progress", "build-8-documentation")

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

    def test_integration_fail_late_routes_to_documentation(self, tmp_path):
        """FAIL AND fix_cycle >= 2 → build-8-documentation (DEGRADED)."""
        transitions = self._run_and_capture(
            tmp_path,
            start_phase="build-7-integration",
            initial_state={"fix_cycle": 2},
            provider=self._sequenced([("FAIL", {})]),
        )
        assert transitions[0] == ("build-7-integration", "build-8-documentation")

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

    def test_integration_pass_all_done_routes_to_documentation(self, tmp_path):
        """PASS AND all_phase_groups_complete → build-8-documentation."""
        transitions = self._run_and_capture(
            tmp_path,
            start_phase="build-7-integration",
            initial_state={"all_phase_groups_complete": True},
            provider=self._sequenced([("PASS", {})]),
        )
        assert transitions[0] == ("build-7-integration", "build-8-documentation")

    def test_documentation_routes_to_docs_verifier(self, tmp_path):
        """TECH WRITER output is verified before build finalization."""
        transitions = self._run_and_capture(
            tmp_path,
            start_phase="build-8-documentation",
            initial_state={},
            provider=self._sequenced([("DONE", {})]),
        )
        assert transitions[0] == ("build-8-documentation", "build-8-verify-docs")

    def test_docs_verifier_pass_routes_to_finalize(self, tmp_path):
        """Docs verifier PASS → build-8-finalize."""
        transitions = self._run_and_capture(
            tmp_path,
            start_phase="build-8-verify-docs",
            initial_state={},
            provider=self._sequenced([("PASS", {})]),
        )
        assert transitions[0] == ("build-8-verify-docs", "build-8-finalize")

    def test_docs_verifier_fail_routes_to_documentation_repair(self, tmp_path):
        """Docs verifier FAIL → TECH WRITER repair loop."""
        transitions = self._run_and_capture(
            tmp_path,
            start_phase="build-8-verify-docs",
            initial_state={},
            provider=self._sequenced([("FAIL", {})]),
        )
        assert transitions[0] == ("build-8-verify-docs", "build-8-documentation")

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
        assert "user-intent.md" in pack
        assert "glossary" in pack
        assert "mental-model" in pack
        assert "boundaries" in pack
        assert "assumptions" in pack
        assert "user-intent" in pack

    def test_phase1_what_requires_constitution_completion_provenance(self, tmp_path):
        """Existing-spec resumes must not skip CHIEF/phase1-constitution."""
        ctrl, store = _controller(tmp_path)
        store.initialize("r", "banzai", "msg", 0, "phase1-what")

        guarded = ctrl._guard_constitution_provenance("phase1-what")

        assert guarded == "phase1-constitution"
        assert store.load()["phase"] == "phase1-constitution"

    def test_pre_constitution_context_phases_do_not_require_constitution_provenance(self):
        """TRACKER must run before CHIEF so user-intent.md exists for constitution."""
        for phase in [
            "init",
            "phase1-discover",
            "phase1-synthesizer",
            "phase1-modeler",
            "phase1-tracker",
            "phase1-why1",
            "phase1-constitution",
        ]:
            assert _phase_requires_constitution_provenance(phase) is False

    def test_phase1_what_still_requires_constitution_provenance(self):
        assert _phase_requires_constitution_provenance("phase1-what") is True

    def test_run_dispatches_chief_before_phase1_what_without_provenance(self, tmp_path):
        provider = _mock_provider()
        ctrl, store = _controller(tmp_path, provider=provider)
        store.initialize("r", "banzai", "msg", 0, "phase1-what")

        with patch.object(ctrl, "_evaluate_transitions", return_value="DONE"):
            result = ctrl.run("msg", "banzai")

        assert result.status == "done"
        assert store.load()["last_dispatch"]["phase_id"] == "phase1-constitution"
        first_prompt = provider.exec_agent.call_args.args[1]
        assert "speckit.constitution" in first_prompt

    def test_phase1_what_allowed_after_constitution_completion_provenance(self, tmp_path):
        ctrl, store = _controller(tmp_path)
        store.initialize("r", "banzai", "msg", 0, "phase1-what")
        state = store.load()
        state["completed_phases"] = ["phase1-constitution"]
        store.save(state)
        const_path = tmp_path / ".specify" / "memory" / "constitution.md"
        const_path.parent.mkdir(parents=True)
        const_path.write_text("# Constitution\n\nReal rules.\n", encoding="utf-8")

        assert ctrl._guard_constitution_provenance("phase1-what") == "phase1-what"

    def test_constitution_guard_allows_sync_impact_report_placeholder_history(self, tmp_path):
        const_path = tmp_path / ".specify" / "memory" / "constitution.md"
        const_path.parent.mkdir(parents=True)
        const_path.write_text(
            """<!--
Sync Impact Report
Modified principles:
  - [PRINCIPLE_1_NAME] -> I. Real Principle
-->

# Constitution

## Core Principles

### I. Real Principle

Ready.
""",
            encoding="utf-8",
        )

        assert _constitution_artifact_is_real(tmp_path) is True

    def test_constitution_guard_rejects_body_placeholder_after_sync_report(self, tmp_path):
        const_path = tmp_path / ".specify" / "memory" / "constitution.md"
        const_path.parent.mkdir(parents=True)
        const_path.write_text(
            """<!--
Sync Impact Report
Modified principles:
  - [PRINCIPLE_1_NAME] -> I. Real Principle
-->

# Constitution

## Core Principles

### [PRINCIPLE_2_NAME]
""",
            encoding="utf-8",
        )

        assert _constitution_artifact_is_real(tmp_path) is False

    def test_greenfield_modeler_phase_is_skipped_before_dispatch(self, tmp_path):
        provider = _mock_provider()
        ctrl, store = _controller(tmp_path, provider=provider)

        result = ctrl.run_single_phase("phase1-modeler", "msg", "banzai")
        state = store.load()

        assert result.status == "running"
        assert state["phase"] == "phase1-tracker"
        assert state["last_dispatch"]["phase_id"] == "phase1-modeler"
        assert "phase1-modeler" in state["completed_phases"]
        provider.exec_agent.assert_not_called()

    def test_completed_constitution_with_missing_artifact_blocks(self, tmp_path):
        ctrl, store = _controller(tmp_path)
        store.initialize("r", "banzai", "msg", 0, "phase1-what")
        state = store.load()
        state["completed_phases"] = ["phase1-constitution"]
        store.save(state)

        assert ctrl._guard_constitution_provenance("phase1-what") == "terminal-blocked"
        state = store.load()
        assert state["status"] == "blocked"
        assert state["blocked_reason"] == "constitution_artifact_mismatch"

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


class TestCommanderJudgmentStateUpdates:
    @staticmethod
    def _ambiguous_node() -> PhaseNode:
        return PhaseNode(
            id="phase1-discover",
            type="agent",
            transitions=[
                {
                    "to": "phase1-why1",
                    "condition": "quality_gates.pass",
                }
            ],
        )

    @staticmethod
    def _phase_result() -> SquadAgentResult:
        return SquadAgentResult(
            exit_code=0,
            echelon_result={"verdict": "DONE", "state_updates": {}},
            raw_output="",
            duration_ms=0,
            timed_out=False,
        )

    def test_invalid_judgment_state_update_blocks_before_mutation(self, tmp_path):
        provider = _mock_provider()
        provider.exec_agent.return_value = SquadAgentResult(
            exit_code=0,
            echelon_result={
                "verdict": "JUDGMENT_RESOLVED",
                "state_updates": {
                    "next_phase": "phase1-why1",
                    "unauthorized_key": "must-not-persist",
                },
            },
            raw_output="",
            duration_ms=0,
            timed_out=False,
        )
        ctrl, store = _controller(tmp_path, provider=provider)

        next_phase = ctrl._evaluate_transitions(
            self._ambiguous_node(),
            self._phase_result(),
        )
        state = store.load()

        assert next_phase == "terminal-blocked"
        assert state["status"] == "blocked"
        assert state["phase"] == "terminal-blocked"
        assert "unauthorized_key" not in state
        assert "unauthorized_key" in state["blocked_reason"]
        assert "judgment state_updates validation failed" in state["blocked_reason"]

    def test_valid_judgment_iteration_update_still_persists(self, tmp_path):
        provider = _mock_provider()
        provider.exec_agent.return_value = SquadAgentResult(
            exit_code=0,
            echelon_result={
                "verdict": "JUDGMENT_RESOLVED",
                "state_updates": {
                    "next_phase": "phase1-why1",
                    "iteration": 2,
                },
            },
            raw_output="",
            duration_ms=0,
            timed_out=False,
        )
        ctrl, store = _controller(tmp_path, provider=provider)

        next_phase = ctrl._evaluate_transitions(
            self._ambiguous_node(),
            self._phase_result(),
        )

        assert next_phase == "phase1-why1"
        assert store.load()["iteration"] == 2

    def test_banzai_escalation_cleanup_deletes_only_allowed_null_keys(self, tmp_path):
        provider = _mock_provider()
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
            raw_output="",
            duration_ms=0,
            timed_out=False,
        )
        ctrl, store = _controller(tmp_path, provider=provider)
        store.initialize("r", "banzai", "msg", 0, "phase1-why1", max_iterations=5)
        state = store.load()
        state["status"] = "running"
        state["escalation_question"] = "Q1?"
        state["blocked_reason"] = "WHY1: user-gated issues"
        store.save(state)

        ctrl._judgment_dispatch_escalation("Q1?", "phase1-why1")
        state = store.load()

        assert "escalation_question" not in state
        assert "blocked_reason" not in state
        assert state["escalation_resolved"] is True
        assert state["escalation_resolver"] == "COMMANDER-banzai"

    def test_banzai_escalation_invalid_cleanup_key_blocks(self, tmp_path):
        provider = _mock_provider()
        provider.exec_agent.return_value = SquadAgentResult(
            exit_code=0,
            echelon_result={
                "verdict": "JUDGMENT_RESOLVED",
                "state_updates": {
                    "escalation_question": None,
                    "blocked_reason": None,
                    "last_dispatch": {"phase_id": "forged"},
                },
            },
            raw_output="",
            duration_ms=0,
            timed_out=False,
        )
        ctrl, store = _controller(tmp_path, provider=provider)
        store.initialize("r", "banzai", "msg", 0, "phase1-why1", max_iterations=5)
        state = store.load()
        state["status"] = "running"
        state["escalation_question"] = "Q1?"
        state["blocked_reason"] = "WHY1: user-gated issues"
        store.save(state)

        ctrl._judgment_dispatch_escalation("Q1?", "phase1-why1")
        state = store.load()

        assert state["status"] == "blocked"
        assert state["phase"] == "terminal-blocked"
        assert state["escalation_question"] == "Q1?"
        assert state["last_dispatch"] is None
        assert "last_dispatch" in state["blocked_reason"]


class TestGovernanceConfigMerge:
    def test_governance_block_merged_into_eval_state(self, tmp_path):
        ctrl, _ = _controller(tmp_path)
        cfg = ctrl._governance_config()
        assert cfg.get("governance", {}).get("enabled") is True


class TestStructuralGuardDeterminism:
    """Regression: phase2-decide with feasibility_structural_pass=False must
    re-dispatch deterministically via ConditionEvaluator — never punt to COMMANDER.

    The condition is:
      governance.enabled AND NOT feasibility_structural_pass AND iteration < max_iterations
    All three operands are resolvable state keys once the governance config is
    merged into eval_state (via _governance_config). The test patches
    _judgment_dispatch to RAISE, proving no COMMANDER punt occurs.
    """

    @staticmethod
    def _result(updates):
        from harness.squad_provider import SquadAgentResult
        return SquadAgentResult(
            exit_code=0,
            echelon_result={"verdict": "DONE", "state_updates": updates},
            raw_output="",
            duration_ms=0,
            timed_out=False,
        )

    def test_feasibility_fail_redispatches_without_commander(self, tmp_path):
        from unittest.mock import patch
        ctrl, store = _controller(tmp_path)
        node = ctrl._graph.get("phase2-decide")
        st = store.load()
        st["iteration"] = 0
        st["max_iterations"] = 3
        store.save(st)
        with patch.object(ctrl, "_judgment_dispatch",
                          side_effect=AssertionError("guard punted to COMMANDER")):
            nxt = ctrl._evaluate_transitions(
                node, self._result({"feasibility_structural_pass": False})
            )
        assert nxt == "phase2-decide"


class TestLexiconGateGuardDeterminism:
    """The lexicon-gate self-loop guards (phase3-plan tasks gate) must route
    deterministically via ConditionEvaluator — never punt to COMMANDER.

    Regression: a live run flagged the guard as referencing undefined state keys
    (lexicon_gate.*, tasks_lexicon_pass), making the condition indeterminate.
    Fix = NOT handler in ConditionEvaluator + merging the lexicon_gate config
    block into the eval state so `lexicon_gate.enabled` resolves.
    """

    @staticmethod
    def _result(updates: dict) -> SquadAgentResult:
        return SquadAgentResult(
            exit_code=0,
            echelon_result={"verdict": "DONE", "state_updates": updates},
            raw_output="", duration_ms=0, timed_out=False,
        )

    def test_gate_config_loads_lexicon_gate_block(self, tmp_path):
        ctrl, _ = _controller(tmp_path)
        cfg = ctrl._lexicon_gate_config()
        assert "lexicon_gate" in cfg
        assert cfg["lexicon_gate"].get("enabled") is True

    def test_tasks_gate_failure_redispatches_without_commander(self, tmp_path):
        ctrl, store = _controller(tmp_path)
        node = ctrl._graph.get("phase3-plan")
        st = store.load(); st["iteration"] = 0; st["max_iterations"] = 3; store.save(st)
        with patch.object(ctrl, "_judgment_dispatch",
                          side_effect=AssertionError("guard punted to COMMANDER — not deterministic")):
            nxt = ctrl._evaluate_transitions(node, self._result({"tasks_lexicon_pass": False}))
        assert nxt == "phase3-plan"   # deterministic re-dispatch on gate failure

    def test_tasks_gate_pass_falls_through_to_consensus(self, tmp_path):
        ctrl, store = _controller(tmp_path)
        node = ctrl._graph.get("phase3-plan")
        st = store.load(); st["iteration"] = 0; st["max_iterations"] = 3; store.save(st)
        with patch.object(ctrl, "_judgment_dispatch",
                          side_effect=AssertionError("guard punted to COMMANDER — not deterministic")):
            nxt = ctrl._evaluate_transitions(node, self._result({"tasks_lexicon_pass": True}))
        assert nxt == "phase3-consensus"   # deterministic fall-through on gate pass
