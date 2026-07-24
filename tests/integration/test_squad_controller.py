"""Integration tests for SquadController with mock provider.

The most important test: test_consensus_cannot_be_skipped.
A mock agent always returns DONE. SquadController must still dispatch
WHY3 + ASSESS2 (stage 1) before PLAN2 (stage 2) and before checkpoint-plan.
"""
import sys
import json
import hashlib
import copy
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

EXT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(EXT_ROOT) not in sys.path:
    sys.path.insert(0, str(EXT_ROOT))

from harness.phase_graph import PhaseGraph, PhaseNode
from harness.phase_checkpoints import PhaseCheckpointError
from harness.squad import (
    SquadController,
    SquadResult,
    _constitution_artifact_is_real,
    _phase_requires_constitution_provenance,
)
from harness.squad_executors import AgentExecutor
from harness.squad_provider import SquadAgentResult
from harness.squad_state import SquadStateStore
from harness.understanding_gate import UnderstandingGateResult
from echelon.telemetry.spec_adapter import analyze_spec_run

DEFINITION = EXT_ROOT / "extension/workflow/definition.yaml"
EXT_YML = EXT_ROOT / "extension/extension.yml"


def _mock_provider(verdict: str = "DONE") -> MagicMock:
    provider = MagicMock()
    default_result = SquadAgentResult(
        exit_code=0,
        echelon_result={
            "verdict": verdict,
            "state_updates": {
                "evidence_resolution_status": "not_required",
                "finding_routes": {"findings": []},
            },
        },
        raw_output="",
        duration_ms=100,
        timed_out=False,
    )
    provider.exec_agent.return_value = default_result

    def default_exec_agent(*args, **kwargs):
        configured = provider.exec_agent.return_value
        if configured is not default_result:
            return configured
        return copy.deepcopy(default_result)

    provider.exec_agent.side_effect = default_exec_agent
    return provider


def _controller(tmp_path: Path, provider=None, mode: str = "banzai", squad_dir: Path = None):
    if not (tmp_path / ".git").exists():
        subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, check=True, capture_output=True)
        subprocess.run(
            ["git", "config", "user.name", "Echelon Tests"],
            cwd=tmp_path,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.email", "echelon@example.test"],
            cwd=tmp_path,
            check=True,
        )
        subprocess.run(
            ["git", "commit", "--allow-empty", "-m", "initial"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )
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


def _disable_lexicon_gate(tmp_path: Path) -> None:
    """Keep non-Lexicon controller tests focused on their declared behavior."""
    config_path = tmp_path / ".echelon" / "config.yml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    existing = (
        config_path.read_text(encoding="utf-8").rstrip()
        if config_path.exists()
        else ""
    )
    prefix = f"{existing}\n" if existing else ""
    config_path.write_text(
        f"{prefix}lexicon_gate:\n  enabled: false\n", encoding="utf-8"
    )


def _disable_governance_gate(tmp_path: Path) -> None:
    """Keep non-governance controller tests focused on their declared behavior."""
    config_path = tmp_path / ".echelon" / "config.yml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    existing = (
        config_path.read_text(encoding="utf-8").rstrip()
        if config_path.exists()
        else ""
    )
    prefix = f"{existing}\n" if existing else ""
    config_path.write_text(
        f"{prefix}governance:\n  enabled: false\n", encoding="utf-8"
    )


def _valid_lexicon_spec() -> str:
    return """ARTIFACT: SPEC
TITLE: Dashboard

REQ: FR-001
GIVEN: data is available
WHEN: the user opens the dashboard
THEN: The system SHALL render the dashboard
OUTPUT: The dashboard is visible
DEPENDS: none
EXAMPLE: AC-001

AC: AC-001
GIVEN: data is available
WHEN: the user opens the dashboard
THEN: The dashboard is visible
"""


def _valid_tasks() -> str:
    return """# Tasks

- [ ] T-001 complexity=standard phase=phase4-build req=FR-001 depends=none target=sources/app
  **Title:** Render dashboard
  **Description:** Render the dashboard from available data.
  **Files:** `sources/app/dashboard.py`
  **Test:** Open the dashboard with seeded data.
  **Acceptance Criteria:**
  - [ ] The dashboard is visible.
"""


def _write_valid_plan_artifacts(spec_dir: Path) -> None:
    (spec_dir / "requirements.lexicon.md").write_text(
        _valid_lexicon_spec(), encoding="utf-8"
    )
    (spec_dir / "tasks.md").write_text(_valid_tasks(), encoding="utf-8")
    for name in ("critical-path.md", "risk-matrix.md", "dependencies.md"):
        (spec_dir / name).write_text(f"# {name}\n", encoding="utf-8")
    (spec_dir / "targets.yml").write_text(
        "schema_version: 1\n"
        "targets:\n"
        "  - id: app\n"
        "    path: sources/app\n"
        "    role: primary\n",
        encoding="utf-8",
    )


def _install_passing_understanding(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep unrelated routing tests independent of metric-engine thresholds."""

    def run_gate(**kwargs: object) -> UnderstandingGateResult:
        project_root = Path(kwargs["project_root"])
        squad_dir = Path(kwargs["squad_dir"])
        spec_dir = Path(str(kwargs["spec_dir"]))
        if not spec_dir.is_absolute():
            spec_dir = project_root / spec_dir
        spec_path = spec_dir / "spec.md"
        spec_digest = hashlib.sha256(spec_path.read_bytes()).hexdigest()
        phase = str(kwargs["phase"])
        iteration = int(kwargs["iteration"])
        scores = {
            "overall": 0.95,
            "structure": 0.95,
            "testability": 0.95,
            "semantic": 0.95,
            "cognitive": 0.95,
            "readability": 0.95,
            "depth": 0.95,
            "behavioral": 0.95,
        }
        report = {
            "schema_version": 1,
            "status": "completed",
            "phase": phase,
            "iteration": iteration,
            "spec": {"path": str(spec_path), "sha256": spec_digest},
            "thresholds": {key: 0.5 for key in scores},
            "scores": scores,
            "gates": {
                key: {"score": value, "threshold": 0.5, "pass": True}
                for key, value in scores.items()
            },
            "pass": True,
            "requirement_count": 1,
            "per_requirement": [],
            "entity_analysis": {},
            "behavioral_analysis": {},
            "diagrams": {"enabled": False, "status": "skipped", "outputs": []},
            "findings": [],
            "generated_at": "2026-07-22T00:00:00+00:00",
        }
        report_path = (
            squad_dir
            / "evidence"
            / "understanding"
            / f"{phase}-iter-{iteration}.json"
        )
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        report_digest = hashlib.sha256(report_path.read_bytes()).hexdigest()
        return UnderstandingGateResult(
            completed=True,
            passed=True,
            phase=phase,
            iteration=iteration,
            report_path=report_path,
            report_digest=report_digest,
            report=report,
        )

    monkeypatch.setattr("harness.squad_executors.run_understanding_gate", run_gate)


def _write_re_index_generation(
    root: Path,
    generation: int,
    *,
    published_from_run: str = "fixture",
) -> None:
    path = root / "re" / "index.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "generation": generation,
                "publication_status": "complete",
                "published_at": "2026-07-12T12:00:00+00:00",
                "published_from_run": published_from_run,
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


def test_checkpoint_successful_phase_blocks_when_required_checkpoint_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ctrl, store = _controller(tmp_path)
    store.initialize("spec-run", "greenfield", "msg", 0, "phase3-plan")
    spec_dir = tmp_path / "squad" / "run-test" / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    state = store.load()
    state["spec_id"] = "001-demo"
    state["spec_dir"] = str(spec_dir.relative_to(tmp_path))
    store.save(state)

    def fail_checkpoint(**_kwargs: object) -> None:
        raise PhaseCheckpointError("simulated checkpoint failure")

    monkeypatch.setattr("harness.squad.create_phase_checkpoint", fail_checkpoint)

    assert ctrl._checkpoint_successful_phase("phase3-plan", "phase3-consensus") is False
    state = store.load()
    assert state["status"] == "blocked"
    assert state["phase"] == "terminal-blocked"
    assert state["blocked_reason"] == (
        "phase_checkpoint_failed: phase3-plan: simulated checkpoint failure"
    )


def test_checkpoint_successful_phase_is_non_blocking_without_active_spec(
    tmp_path: Path,
) -> None:
    ctrl, store = _controller(tmp_path)
    store.initialize("spec-run", "greenfield", "msg", 0, "phase1-discover")

    assert ctrl._checkpoint_successful_phase("phase1-discover", "phase1-why1") is True
    assert store.load()["status"] == "running"


def test_checkpoint_successful_phase_returns_true_after_checkpoint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ctrl, store = _controller(tmp_path)
    store.initialize("spec-run", "greenfield", "msg", 0, "phase1-what")
    spec_dir = tmp_path / "squad" / "run-test" / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    state = store.load()
    state["spec_id"] = "001-demo"
    state["spec_dir"] = str(spec_dir.relative_to(tmp_path))
    store.save(state)
    checkpoint_calls: list[dict[str, object]] = []

    def record_checkpoint(**kwargs: object) -> object:
        checkpoint_calls.append(kwargs)
        return object()

    monkeypatch.setattr("harness.squad.create_phase_checkpoint", record_checkpoint)

    assert ctrl._checkpoint_successful_phase("phase1-what", "phase1-why2") is True
    assert checkpoint_calls[0]["spec_dir"] == spec_dir
    assert store.load()["status"] == "running"


def test_cartographer_context_preservation_requires_spec_md(tmp_path: Path) -> None:
    """A reserved run-local path must not suppress the initial WHAT pass."""
    ctrl, store = _controller(tmp_path)
    store.initialize("spec-run", "banzai", "msg", 0, "phase1-what")
    planned = tmp_path / "runs" / "spec-run" / "specs" / "001-demo"
    planned.mkdir(parents=True)
    state = store.load()
    state["spec_id"] = "001-demo"
    state["spec_dir"] = str(planned.relative_to(tmp_path))
    store.save(state)

    state = store.load()
    ctrl._preserve_cartographer_spec_context(state)

    assert "cartographer_resume_existing_spec" not in state


class TestConsensusCannotBeSkipped:
    """Regression: phase3-consensus was previously skipped via EVOI fabrication.
    The plan now routes through deterministic Tasks Lexicon and Understanding
    nodes before consensus. Python evaluates every edge; no code path skips it.
    """

    def test_phase3_plan_transitions_to_consensus(self):
        graph = PhaseGraph(DEFINITION, EXT_YML)
        plan_node = graph.get("phase3-plan")
        assert plan_node.transitions == [
            {"to": "phase3-tasks-lexicon", "condition": "always"}
        ]
        assert graph.get("phase3-tasks-lexicon").transitions[-1] == {
            "to": "phase3-understanding",
            "condition": "tasks_lexicon_action in [proceed, proceed_with_warning]",
        }
        assert graph.get("phase3-understanding").transitions == [
            {"to": "phase3-consensus", "condition": "always"}
        ]

    def test_phase3_plan_to_consensus_condition_is_always(self):
        graph = PhaseGraph(DEFINITION, EXT_YML)
        plan_node = graph.get("phase3-plan")
        assert plan_node.transitions[0]["condition"] == "always"

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
                "specification authoring incomplete"
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

    def test_what_rejects_agent_authored_blocked_verdict(self, tmp_path):
        ctrl, _ = _controller(tmp_path)
        result = SquadAgentResult(
            exit_code=0,
            echelon_result={
                "verdict": "BLOCKED",
                "state_updates": {
                    "blocked_reason": "investigation is needed",
                },
            },
            raw_output="",
            duration_ms=100,
            timed_out=False,
        )

        validated = ctrl._executors["agent"]._validate_result_state_updates(
            ctrl._graph.get("phase1-what"), result
        )

        assert validated.verdict == "BLOCKED"
        assert "verdict 'BLOCKED' is not allowed" in validated.state_updates["blocked_reason"]

    def test_what_evidence_request_routes_to_investigator(self, tmp_path):
        provider = _mock_provider()
        provider.exec_agent.side_effect = [
            SquadAgentResult(
                exit_code=0,
                echelon_result={
                    "verdict": "FAIL",
                    "state_updates": {
                        "evidence_resolution_status": "pending",
                        "evidence_requests": {
                            "requests": [{
                                "id": "ER-001",
                                "question": "Which pagination scheme does the supplied API use?",
                                "affected_requirements": ["FR-012"],
                                "evidence_needed": "The declared primary API reference.",
                                "supplied_reference_ids": ["IN-REF-001"],
                            }],
                        },
                    },
                },
                raw_output="",
                duration_ms=100,
                timed_out=False,
            ),
            SquadAgentResult(
                exit_code=0,
                echelon_result={
                    "verdict": "DONE",
                    "state_updates": {
                        "evidence_resolution_status": "access_required",
                    },
                },
                raw_output="",
                duration_ms=100,
                timed_out=False,
            ),
        ]
        ctrl, store = _controller(tmp_path, provider=provider)
        store.initialize("r", "banzai", "msg", 0, "phase1-what", max_iterations=5)
        _mark_constitution_complete(tmp_path, store)
        spec_dir = tmp_path / "runs" / "run-test" / "specs" / "001-demo"
        (spec_dir / "investigation").mkdir(parents=True)
        for name in ("spec.md", "00-overview.md", "evidence-resolution.md", "evidence-grades.md"):
            (spec_dir / name).write_text(f"# {name}\n", encoding="utf-8")
        state = store.load()
        state["spec_dir"] = str(spec_dir.relative_to(tmp_path))
        store.save(state)

        result = ctrl.run("msg", "banzai")

        assert result.status == "blocked"
        assert [call.args[0] for call in provider.exec_agent.call_args_list] == [str(tmp_path), str(tmp_path)]
        assert store.load()["last_dispatch"]["phase_id"] == "phase1-investigate"

    def test_what_rejects_repeat_of_completed_evidence_request(self, tmp_path):
        ctrl, store = _controller(tmp_path)
        request = {
            "requests": [{
                "id": "ER-001",
                "question": "Which pagination scheme does the supplied API use?",
                "affected_requirements": ["FR-012"],
                "evidence_needed": "The declared primary API reference.",
                "supplied_reference_ids": ["IN-REF-001"],
            }],
        }
        fingerprint = hashlib.sha256(
            json.dumps(request, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        store.initialize("r", "banzai", "msg", 0, "phase1-what", max_iterations=5)
        state = store.load()
        state.update({
            "evidence_request_fingerprint": fingerprint,
            "evidence_resolution_status": "validated",
        })
        store.save(state)
        result = SquadAgentResult(
            exit_code=0,
            echelon_result={
                "verdict": "FAIL",
                "state_updates": {
                    "evidence_resolution_status": "pending",
                    "evidence_requests": request,
                },
            },
            raw_output="",
            duration_ms=100,
            timed_out=False,
        )

        assert ctrl._evaluate_transitions(ctrl._graph.get("phase1-what"), result) == "terminal-blocked"
        assert store.load()["blocked_reason"] == "evidence_resolution_no_new_evidence"

    def test_manual_next_phase_recovers_blocked_run_without_reinitializing_state(self, tmp_path):
        provider = _mock_provider()
        provider.exec_agent.return_value = SquadAgentResult(
            exit_code=0,
            echelon_result={
                "verdict": "BLOCKED",
                "state_updates": {"blocked_reason": "test stop"},
            },
            raw_output="",
            duration_ms=100,
            timed_out=False,
        )
        ctrl, store = _controller(tmp_path, provider=provider)
        store.initialize("r", "banzai", "msg", 0, "terminal-blocked", max_iterations=5)
        _mark_constitution_complete(tmp_path, store)
        state = store.load()
        state.update({
            "status": "blocked",
            "blocked_reason": "evidence route was not emitted",
            "escalation_question": "A stale escalation must not block an explicit phase retry.",
            "evidence_requests": {"requests": [{"id": "ER-001"}]},
            "phase_dispatch_counts": {"phase1-investigate": 5},
        })
        store.save(state)

        result = ctrl.run("msg", "banzai", next_phase_override="phase1-investigate")

        recovered = store.load()
        assert result.status == "blocked"
        assert recovered["evidence_requests"] == {"requests": [{"id": "ER-001"}]}
        assert recovered["last_dispatch"]["phase_id"] == "phase1-investigate"
        assert recovered.get("escalation_question") is None
        assert recovered["phase_dispatch_counts"]["phase1-investigate"] == 1
        assert recovered["manual_phase_recovery"] == {
            "phase": "phase1-investigate",
            "reset_dispatch_count": True,
        }

    def test_issue_resolution_consumes_declared_why2_repair_edge(self, tmp_path):
        provider = _mock_provider()
        provider.exec_agent.return_value = SquadAgentResult(
            exit_code=0,
            echelon_result={
                "verdict": "BLOCKED",
                "state_updates": {"blocked_reason": "test stop"},
            },
            raw_output="",
            duration_ms=100,
            timed_out=False,
        )
        ctrl, store = _controller(tmp_path, provider=provider)
        store.initialize("r", "semi", "msg", 0, "terminal-blocked", max_iterations=5)
        _mark_constitution_complete(tmp_path, store)
        state = store.load()
        state.update({
            "status": "blocked",
            "phase": "terminal-blocked",
            "blocked_reason": "phase_dispatch_limit",
            "phase_dispatch_limit_phase": "phase1-what",
            "phase_dispatch_counts": {"phase1-what": 12},
            "selected_issue_resolution": "ISS-002",
            "issue_resolution_ledger": {"ISS-002": {"status": "selected"}},
            "issue_resolution_recovery": {
                "issue_id": "ISS-002",
                "from_phase": "phase1-why2",
                "to_phase": "phase1-what",
                "reason": "issue_resolution",
            },
        })
        store.save(state)

        result = ctrl.run("msg", "semi")

        recovered = store.load()
        assert result.status == "blocked"
        assert recovered["last_dispatch"]["phase_id"] == "phase1-what"
        assert recovered["phase_dispatch_counts"]["phase1-what"] == 1
        assert recovered["issue_resolution_recovery"]["status"] == "consumed"
        assert recovered["phase_dispatch_limit_recovery"] == {
            "phase": "phase1-what",
            "resolver": "issue_resolution_workflow_edge",
            "issue_id": "ISS-002",
            "workflow_edge": "phase1-why2 -> phase1-what",
        }

    def test_selected_issue_repair_cannot_advance_without_spec_change(self, tmp_path):
        ctrl, store = _controller(tmp_path)
        spec_dir = tmp_path / "specs" / "001-demo"
        spec_dir.mkdir(parents=True)
        spec_path = spec_dir / "spec.md"
        spec_path.write_text("before", encoding="utf-8")
        store.initialize("r", "semi", "msg", 0, "phase1-what", max_iterations=5)
        state = store.load()
        state["spec_dir"] = str(spec_dir)
        baseline_digest = ctrl._selected_issue_spec_digest(state)
        state.update({
            "selected_issue_resolution": "ISS-002",
            "issue_resolution_ledger": {"ISS-002": {"status": "selected"}},
            "issue_resolution_repair_baseline": {
                "issue_id": "ISS-002",
                "repair_phase": "phase1-what",
                "spec_digest": baseline_digest,
            },
            "phase_dispatch_counts": {
                "phase1-lexicon": 12,
                "phase1-understanding": 5,
                "phase1-why2": 5,
            },
        })
        store.save(state)

        assert ctrl._selected_issue_repair_requires_artifact_progress("phase1-what") is True
        blocked = store.load()
        assert blocked["blocked_reason"] == "selected_issue_repair_no_artifact_progress"
        assert blocked["phase"] == "terminal-blocked"

        spec_path.write_text("after", encoding="utf-8")
        blocked["status"] = "running"
        blocked["phase"] = "phase1-what"
        store.save(blocked)
        assert ctrl._selected_issue_repair_requires_artifact_progress("phase1-what") is False
        progressed = store.load()
        assert progressed["phase_dispatch_counts"] == {
            "phase1-lexicon": 0,
            "phase1-understanding": 0,
            "phase1-why2": 0,
        }

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
        _disable_lexicon_gate(tmp_path)
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
        _disable_lexicon_gate(tmp_path)
        ctrl, store = _controller(tmp_path)
        store.initialize("r", "banzai", "msg", 0, "phase4-document", max_iterations=5)
        _mark_constitution_complete(tmp_path, store)
        spec_dir = tmp_path / "runs" / "run-test" / "specs" / "001-demo"
        spec_dir.mkdir(parents=True)
        for name in (
            "spec.md", "plan.md", "research.md", "data-model.md", "tasks.md",
            "test-strategy.md", "test-architecture.md", "coverage-map.md",
        ):
            (spec_dir / name).write_text(f"# {name}\n", encoding="utf-8")
        checkpoint_ledger = spec_dir / ".echelon" / "checkpoints.json"
        checkpoint_ledger.parent.mkdir()
        checkpoint_ledger.write_text("{\"checkpoints\": []}\n", encoding="utf-8")
        state = store.load()
        state["spec_id"] = "001-demo"
        state["spec_dir"] = "runs/run-test/specs/001-demo"
        store.save(state)
        kb_report = tmp_path / "runs" / "r" / "kb-apply-report.yaml"
        kb_report.parent.mkdir(parents=True)
        kb_report.write_text("status: degraded\n", encoding="utf-8")

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
        assert not (published_dir / ".echelon").exists()
        assert (published_dir / "kb" / "kb-apply-report.yaml").read_text(
            encoding="utf-8"
        ) == "status: degraded\n"
        history = json.loads((published_dir / "run-history.json").read_text(encoding="utf-8"))
        assert history["runs"][-1]["run_id"] == "r"
        assert history["runs"][-1]["phase"] == "A"
        assert history["runs"][-1]["status"] == "done"
        state = store.load()
        assert state["published_spec_dir"] == "specs/001-demo"

    def test_phase4_document_publishes_complete_artifacts_to_existing_slugged_spec(
        self, tmp_path,
    ):
        _disable_lexicon_gate(tmp_path)
        ctrl, store = _controller(tmp_path)
        store.initialize("r", "banzai", "msg", 0, "phase4-document", max_iterations=5)
        _mark_constitution_complete(tmp_path, store)

        active_spec_dir = tmp_path / "runs" / "run-test" / "specs" / "001"
        active_spec_dir.mkdir(parents=True)
        for name in (
            "spec.md", "plan.md", "research.md", "data-model.md", "tasks.md",
            "test-strategy.md", "test-architecture.md", "coverage-map.md",
        ):
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

    def test_done_run_reconciles_newer_run_local_artifacts_to_published_spec(
        self, tmp_path,
    ):
        ctrl, store = _controller(tmp_path)
        store.initialize("r", "banzai", "msg", 0, "DONE", max_iterations=5)
        _mark_constitution_complete(tmp_path, store)

        active_spec_dir = tmp_path / "squad" / "run-test" / "specs" / "001-demo"
        active_spec_dir.mkdir(parents=True)
        for name in (
            "spec.md", "plan.md", "research.md", "data-model.md", "tasks.md",
            "test-strategy.md", "test-architecture.md", "coverage-map.md",
        ):
            (active_spec_dir / name).write_text(f"# active {name}\n", encoding="utf-8")
        (active_spec_dir / "user-intent.md").write_text(
            "# User Intent\n\nfresh run-local artifact\n",
            encoding="utf-8",
        )

        published_dir = tmp_path / "specs" / "001-demo"
        published_dir.mkdir(parents=True)
        (published_dir / "spec.md").write_text("# stale spec\n", encoding="utf-8")

        state = store.load()
        state["status"] = "done"
        state["spec_id"] = "001-demo"
        state["spec_dir"] = "squad/run-test/specs/001-demo"
        state["published_spec_dir"] = "specs/001-demo"
        store.save(state)

        result = ctrl.run("msg", "banzai")
        state = store.load()

        assert result.status == "done"
        assert (published_dir / "spec.md").read_text(encoding="utf-8") == "# active spec.md\n"
        assert (published_dir / "user-intent.md").read_text(encoding="utf-8") == (
            "# User Intent\n\nfresh run-local artifact\n"
        )
        assert (published_dir / "ARTIFACTS.md").exists()
        assert (published_dir / "squad-report.md").exists()
        history = json.loads((published_dir / "run-history.json").read_text(encoding="utf-8"))
        assert history["runs"][-1]["run_id"] == "r"
        assert state["published_spec_dir"] == "specs/001-demo"

    def test_checkpoint_plan_auto_routes_without_commander_judgment(self, tmp_path):
        _disable_lexicon_gate(tmp_path)
        provider = MagicMock()
        provider.exec_agent.side_effect = AssertionError(
            "checkpoint-plan should not dispatch COMMANDER judgment in banzai"
        )
        ctrl, store = _controller(tmp_path, provider=provider)
        store.initialize("r", "banzai", "msg", 0, "checkpoint-plan", max_iterations=5)
        _mark_constitution_complete(tmp_path, store)

        spec_dir = tmp_path / "runs" / "run-test" / "specs" / "001-demo"
        spec_dir.mkdir(parents=True)
        for name in (
            "spec.md", "plan.md", "research.md", "data-model.md", "tasks.md",
            "test-strategy.md", "test-architecture.md", "coverage-map.md",
        ):
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
        existing_spec = tmp_path / "specs" / "072-pr-pipeline-fix"
        existing_spec.mkdir(parents=True)
        (existing_spec / "spec.md").write_text("# Existing spec\n", encoding="utf-8")
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
        assert "Do NOT create, switch, rename, or discover a branch or spec directory" in prompt
        assert "Existing spec_dir: specs/072-pr-pipeline-fix" in prompt
        assert "Existing feature_branch: 072-pr-pipeline-fix" in prompt


class TestSquadControllerBasics:
    def test_generation_change_does_not_mutate_attached_spec_context(self, tmp_path, monkeypatch):
        _disable_lexicon_gate(tmp_path)
        provider = _mock_provider()
        ctrl, store = _controller(tmp_path, provider=provider)
        monkeypatch.setattr(ctrl, "_lexicon_gate_config", lambda: {"lexicon_gate": {"enabled": False}})
        store.initialize("r", "brownfield", "msg", 0, "phase1-tracker")
        _mark_constitution_complete(tmp_path, store)
        state = store.load()
        state["re_generation"] = 1
        state["spec_dir"] = "specs/001-test"
        store.save(state)
        spec_dir = tmp_path / "specs" / "001-test"
        spec_dir.mkdir(parents=True)
        (spec_dir / "spec.md").write_text(_valid_lexicon_spec(), encoding="utf-8")
        (spec_dir / "00-overview.md").write_text("# Overview\n", encoding="utf-8")
        _install_passing_understanding(monkeypatch)
        monkeypatch.setattr(
            ctrl, "_publish_terminal_phase_a_artifacts_if_available", lambda: None
        )
        _write_re_index_generation(tmp_path, 2)

        result = ctrl.run("msg", "banzai")

        assert result.status == "done"
        state = store.load()
        assert state.get("blocked_reason") is None
        assert state["re_generation"] == 1
        assert provider.exec_agent.called

    def test_generation_change_does_not_block_manual_spec_phase(self, tmp_path):
        provider = _mock_provider()
        ctrl, store = _controller(tmp_path, provider=provider)
        store.initialize("r", "brownfield", "msg", 0, "phase1-tracker")
        _mark_constitution_complete(tmp_path, store)
        state = store.load()
        state["re_generation"] = 1
        store.save(state)
        _write_re_index_generation(tmp_path, 2)

        result = ctrl.run_single_phase("phase1-tracker", "msg", "banzai")

        assert result.status == "running"
        state = store.load()
        assert state.get("blocked_reason") is None
        assert state["re_generation"] == 1
        assert provider.exec_agent.called

    def test_legacy_generation_state_is_not_synchronized_during_spec_run(self, tmp_path, monkeypatch):
        _disable_lexicon_gate(tmp_path)
        provider = _mock_provider()
        ctrl, store = _controller(tmp_path, provider=provider)
        monkeypatch.setattr(ctrl, "_lexicon_gate_config", lambda: {"lexicon_gate": {"enabled": False}})
        store.initialize("r", "brownfield", "msg", 0, "phase1-tracker")
        _mark_constitution_complete(tmp_path, store)
        state = store.load()
        state["re_generation"] = 1
        state["spec_dir"] = "specs/001-test"
        store.save(state)
        spec_dir = tmp_path / "specs" / "001-test"
        spec_dir.mkdir(parents=True)
        (spec_dir / "spec.md").write_text(_valid_lexicon_spec(), encoding="utf-8")
        (spec_dir / "00-overview.md").write_text("# Overview\n", encoding="utf-8")
        _install_passing_understanding(monkeypatch)
        monkeypatch.setattr(
            ctrl, "_publish_terminal_phase_a_artifacts_if_available", lambda: None
        )
        _write_re_index_generation(
            tmp_path,
            2,
            published_from_run=ctrl._squad_dir.name,
        )

        result = ctrl.run("msg", "banzai")

        assert result.status != "blocked"
        state = store.load()
        assert state["re_generation"] == 1
        assert state.get("blocked_reason") is None
        assert "re_generation_expected" not in state
        assert "re_generation_actual" not in state
        assert provider.exec_agent.called

    def test_fresh_run_detects_project_mode_separately_from_autonomy_mode(self, tmp_path):
        for i in range(6):
            (tmp_path / f"module_{i}.py").write_text("pass\n", encoding="utf-8")

        ctrl, store = _controller(tmp_path, mode="banzai")

        result = ctrl.run("msg", "banzai", next_phase_override="DONE")

        assert result.status == "done"
        state = store.load()
        assert state["mode"] == "brownfield"
        assert state["autonomy_mode"] == "banzai"

    def test_brownfield_discovery_does_not_run_re_controller(
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

        executor.execute(graph.get("phase1-discover"), store)

        assert provider.exec_agent.call_count == 1
        state = store.load()
        assert "golddigger_status" not in state

    def test_spec_controller_has_no_nested_re_dispatch_recovery(
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

        assert not hasattr(ctrl, "_reset_discovery_dispatches_for_pending_recovery")
        assert store.get_phase_dispatch_count("phase1-discover") == 6

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

        assert not hasattr(ctrl, "_reset_discovery_dispatches_for_pending_recovery")
        assert store.get_phase_dispatch_count("phase1-discover") == 1

    def test_discovery_ignores_legacy_re_plan_state(
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

        executor.execute(graph.get("phase1-discover"), store)

        assert "golddigger_status" not in store.load()
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
        monkeypatch,
    ):
        """phase3-consensus can legitimately repeat up to max_iterations."""
        _disable_lexicon_gate(tmp_path)
        provider = _mock_provider("PASS")
        default_result = provider.exec_agent.return_value

        def consensus_result(project_root: str, prompt: str, *args, **kwargs):
            if "Operate in **PLAN2** mode" in prompt:
                return SquadAgentResult(
                    exit_code=0,
                    echelon_result={"verdict": "COMPLETE", "state_updates": {}},
                    raw_output="",
                    duration_ms=100,
                    timed_out=False,
                )
            return default_result

        provider.exec_agent.side_effect = consensus_result
        ctrl, store = _controller(tmp_path, provider, mode="semi")
        store.initialize("r", "semi", "msg", 0, "phase3-consensus", max_iterations=10)
        state = store.load()
        state["iteration"] = 4
        state["phase_dispatch_counts"] = {"phase3-consensus": 5}
        store.save(state)
        _mark_constitution_complete(tmp_path, store)
        spec_dir = tmp_path / "runs" / "run-test" / "specs" / "001-demo"
        spec_dir.mkdir(parents=True)
        for name in (
            "spec.md", "plan.md", "research.md", "data-model.md", "tasks.md",
            "test-strategy.md", "test-architecture.md", "coverage-map.md",
            "implementability-report.md",
        ):
            (spec_dir / name).write_text(f"# {name}\n", encoding="utf-8")
        state = store.load()
        state["spec_id"] = "001-demo"
        state["spec_dir"] = "runs/run-test/specs/001-demo"
        store.save(state)
        _install_passing_understanding(monkeypatch)

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

    def test_sage_quality_scores_are_quarantined_and_cannot_override_certified_failure(self, tmp_path):
        """WHY2 model output cannot replace controller-certified score history."""
        from harness.squad_provider import SquadAgentResult
        provider = _mock_provider()
        provider.exec_agent.return_value = SquadAgentResult(
            exit_code=0,
            echelon_result={
                "verdict": "FAIL",
                "state_updates": {
                    "evidence_resolution_status": "not_required",
                    "finding_routes": {
                        "findings": [{
                            "issue_id": "ISS-001",
                            "route": "spec_repair",
                            "rationale": "The supplied specification can be amended.",
                        }],
                    },
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
        state = store.load()
        state["quality_scores"] = [
            {
                "pass": False,
                "pass_id": "WHY2-iter-0",
                "source": "harness:understanding",
            }
        ]
        store.save(state)

        node = ctrl._graph.get("phase1-why2")
        result = ctrl._executors["agent"]._validate_result_state_updates(
            node,
            provider.exec_agent.return_value,
            result_contract=node.result_contract(),
        )
        assert result.state_updates == {
            "evidence_resolution_status": "not_required",
            "finding_routes": {
                "findings": [{
                    "issue_id": "ISS-001",
                    "route": "spec_repair",
                    "rationale": "The supplied specification can be amended.",
                }],
            },
        }
        assert "quality_scores" in result.quarantined_state_updates
        next_phase = ctrl._evaluate_transitions(node, result)
        store.advance(
            "phase1-why2",
            next_phase,
            result,
            allowed_state_update_keys=ctrl._advance_state_update_keys(node),
        )

        state = store.load()
        assert state["phase"] == "phase1-what"
        assert state["quality_scores"][-1]["pass"] is False
        assert state["quality_scores"][-1]["pass_id"] == "WHY2-iter-0"
        assert state["quality_scores"][-1]["source"] == "harness:understanding"
        assert state.get("why_fail_count", 0) >= 1

    def test_sage_qualitative_failure_overrides_certified_pass(self, tmp_path):
        """WHY2 may make a certified pass stricter without replacing its score."""
        ctrl, store = _controller(tmp_path)
        store.initialize("r", "banzai", "msg", 0, "phase1-why2", max_iterations=5)
        state = store.load()
        state["quality_scores"] = [
            {
                "pass": True,
                "pass_id": "WHY2-iter-0",
                "source": "harness:understanding",
            }
        ]
        store.save(state)
        result = SquadAgentResult(
            exit_code=0,
            echelon_result={"verdict": "FAIL", "state_updates": {}},
            raw_output="",
            duration_ms=0,
            timed_out=False,
        )

        next_phase = ctrl._evaluate_transitions(
            ctrl._graph.get("phase1-why2"),
            result,
        )

        assert next_phase == "phase1-what"
        assert store.load()["quality_scores"][-1]["pass"] is True
        assert store.load().get("why_fail_count", 0) == 1

    def test_why2_external_evidence_request_routes_to_investigator(self, tmp_path):
        """WHY2 sends source-dependent questions to INVESTIGATOR before WHAT."""
        ctrl, store = _controller(tmp_path)
        store.initialize("r", "semi", "msg", 0, "phase1-why2", max_iterations=5)
        state = store.load()
        state["quality_scores"] = [{"pass": False, "pass_id": "WHY2-iter-0"}]
        store.save(state)
        result = SquadAgentResult(
            exit_code=0,
            echelon_result={
                "verdict": "FAIL",
                "state_updates": {
                    "evidence_resolution_status": "pending",
                    "evidence_requests": {
                        "requests": [
                            {
                                "id": "ER-001",
                                "question": "What authentication mechanism does the service require?",
                            }
                        ]
                    },
                },
            },
            raw_output="",
            duration_ms=0,
            timed_out=False,
        )

        next_phase = ctrl._evaluate_transitions(
            ctrl._graph.get("phase1-why2"), result,
        )

        assert next_phase == "phase1-investigate"

    def test_why2_repeated_evidence_request_without_new_evidence_escalates(self, tmp_path):
        """A completed investigation cannot be silently sent through again."""
        ctrl, store = _controller(tmp_path)
        requests = {
            "requests": [
                {
                    "id": "ER-001",
                    "question": "What authentication mechanism does the service require?",
                }
            ]
        }
        fingerprint = hashlib.sha256(
            json.dumps(requests, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        store.initialize("r", "semi", "msg", 0, "phase1-why2", max_iterations=5)
        state = store.load()
        state.update(
            {
                "quality_scores": [{"pass": False, "pass_id": "WHY2-iter-1"}],
                "evidence_request_fingerprint": fingerprint,
                "evidence_resolution_status": "validated",
            }
        )
        store.save(state)
        result = SquadAgentResult(
            exit_code=0,
            echelon_result={
                "verdict": "FAIL",
                "state_updates": {
                    "evidence_resolution_status": "pending",
                    "evidence_requests": requests,
                },
            },
            raw_output="",
            duration_ms=0,
            timed_out=False,
        )

        next_phase = ctrl._evaluate_transitions(
            ctrl._graph.get("phase1-why2"), result,
        )

        assert next_phase == "terminal-blocked"
        blocked = store.load()
        assert blocked["blocked_reason"] == "evidence_resolution_no_new_evidence"
        assert "ER-001" in blocked["escalation_question"]

    def test_why2_stagnant_certified_metrics_escalate_after_two_cycles(self, tmp_path):
        """Repeated score plateaus stop semantic retries before the dispatch cap."""
        ctrl, store = _controller(tmp_path)
        store.initialize("r", "semi", "msg", 0, "phase1-why2", max_iterations=5)
        state = store.load()
        state.update(
            {
                "quality_scores": [
                    {"pass": False, "pass_id": "WHY2-iter-0", "overall": 0.64, "testability": 0.57},
                    {"pass": False, "pass_id": "WHY2-iter-1", "overall": 0.64, "testability": 0.57},
                ],
                "why2_metric_stagnation_count": 1,
            }
        )
        store.save(state)
        result = SquadAgentResult(
            exit_code=0,
            echelon_result={"verdict": "FAIL", "state_updates": {}},
            raw_output="",
            duration_ms=0,
            timed_out=False,
        )

        next_phase = ctrl._evaluate_transitions(
            ctrl._graph.get("phase1-why2"), result,
        )

        assert next_phase == "terminal-blocked"
        blocked = store.load()
        assert blocked["blocked_reason"] == "why2_metric_stagnation"
        assert "metrics did not improve" in blocked["escalation_question"]

    def test_understanding_operational_failure_remains_at_retryable_gate(self, tmp_path):
        ctrl, store = _controller(tmp_path)
        store.initialize("r", "banzai", "msg", 0, "phase1-understanding")
        result = SquadAgentResult(
            exit_code=0,
            echelon_result={
                "verdict": "BLOCKED",
                "state_updates": {
                    "blocked_reason": "Understanding analysis failed: temporary",
                    "understanding_evidence": {
                        "phase": "phase1-why2",
                        "status": "error",
                        "path": "/tmp/understanding-error.json",
                    },
                },
            },
            raw_output="",
            duration_ms=0,
            timed_out=False,
        )

        ctrl._block_after_executor_failure(
            "phase1-understanding",
            "Understanding analysis failed: temporary",
            result,
        )

        blocked = store.load()
        assert blocked["status"] == "blocked"
        assert blocked["phase"] == "phase1-understanding"
        assert blocked["understanding_evidence"]["status"] == "error"

    def test_missing_phase_output_preserves_recovery_context(self, tmp_path):
        ctrl, store = _controller(tmp_path)
        store.initialize("r", "semi", "msg", 0, "phase1-investigate")
        result = SquadAgentResult(
            exit_code=0,
            echelon_result={
                "verdict": "BLOCKED",
                "state_updates": {
                    "blocked_reason": "missing_phase_outputs",
                    "missing_outputs": ["evidence-grades.md"],
                    "recovery_state_updates": {
                        "evidence_resolution_status": "conflicting",
                    },
                },
            },
            raw_output="",
            duration_ms=0,
            timed_out=False,
        )

        ctrl._block_after_executor_failure(
            "phase1-investigate", "missing_phase_outputs", result,
        )

        blocked = store.load()
        assert blocked["missing_outputs"] == ["evidence-grades.md"]
        assert blocked["phase_output_recovery"] == {
            "phase": "phase1-investigate",
            "missing_outputs": ["evidence-grades.md"],
            "prior_state_updates": {
                "evidence_resolution_status": "conflicting",
            },
        }

    def test_missing_phase_output_recovery_is_rehydrated_for_older_runs(self, tmp_path):
        ctrl, store = _controller(tmp_path)
        store.initialize("r", "semi", "msg", 0, "phase1-investigate")
        spec_dir = tmp_path / "specs" / "001-demo"
        spec_dir.mkdir(parents=True)
        (spec_dir / "evidence-resolution.md").write_text("# Evidence\n", encoding="utf-8")
        state = store.load()
        state.update(
            {
                "status": "blocked",
                "phase": "terminal-blocked",
                "blocked_reason": "missing_phase_outputs",
                "spec_dir": "specs/001-demo",
                "last_dispatch": {"phase_id": "phase1-investigate"},
            }
        )
        store.save(state)

        assert ctrl._restore_missing_phase_output_recovery("phase1-investigate") is True

        recovered = store.load()
        assert recovered["missing_outputs"] == [
            "evidence-grades.md",
            "evidence-inventory.json",
        ]
        assert recovered["phase_output_recovery"] == {
            "phase": "phase1-investigate",
            "missing_outputs": [
                "evidence-grades.md",
                "evidence-inventory.json",
            ],
            "prior_state_updates": {},
        }

    def test_invalid_inventory_recovery_is_rehydrated_for_older_runs(self, tmp_path):
        ctrl, store = _controller(tmp_path)
        store.initialize("r", "semi", "msg", 0, "phase1-investigate")
        state = store.load()
        state.update(
            {
                "status": "blocked",
                "phase": "terminal-blocked",
                "blocked_reason": (
                    "invalid_evidence_inventory: sources[0].discovered_from "
                    "must be a non-empty string"
                ),
            }
        )
        store.save(state)

        assert ctrl._restore_missing_phase_output_recovery("phase1-investigate") is True

        assert store.load()["phase_output_recovery"] == {
            "phase": "phase1-investigate",
            "invalid_outputs": [{
                "path": "evidence-inventory.json",
                "reason": (
                    "inventory failed validation in a prior Echelon version; "
                    "rebuild it from declared source seeds"
                ),
            }],
            "prior_state_updates": {},
        }

    def test_missing_inventory_recovery_restores_quarantined_invalid_context(self, tmp_path):
        ctrl, store = _controller(tmp_path)
        store.initialize("r", "semi", "msg", 0, "phase1-investigate")
        spec_dir = tmp_path / "specs" / "001-demo"
        spec_dir.mkdir(parents=True)
        (spec_dir / "evidence-inventory.invalid.json").write_text(
            "{}\n", encoding="utf-8"
        )
        state = store.load()
        state.update(
            {
                "spec_dir": "specs/001-demo",
                "phase_output_recovery": {
                    "phase": "phase1-investigate",
                    "missing_outputs": ["evidence-inventory.json"],
                    "prior_state_updates": {},
                },
            }
        )
        store.save(state)

        assert ctrl._restore_missing_phase_output_recovery("phase1-investigate") is True
        invalid = store.load()["phase_output_recovery"]["invalid_outputs"]
        assert invalid[0]["path"] == "evidence-inventory.json"

    def test_blocked_understanding_gate_retries_without_reinitializing(self, tmp_path):
        _disable_lexicon_gate(tmp_path)
        ctrl, store = _controller(tmp_path)
        store.initialize("r", "banzai", "msg", 0, "phase1-understanding")
        state = store.load()
        state.update(
            {
                "status": "blocked",
                "blocked_reason": "Understanding analysis failed: temporary",
                "understanding_evidence": {
                    "phase": "phase1-why2",
                    "status": "error",
                    "path": "/tmp/original-evidence.json",
                },
            }
        )
        store.save(state)
        _mark_constitution_complete(tmp_path, store)
        retry = MagicMock()
        retry.execute.return_value = SquadAgentResult(
            exit_code=0,
            echelon_result={
                "verdict": "BLOCKED",
                "state_updates": {"blocked_reason": "retry failed"},
            },
            raw_output="",
            duration_ms=0,
            timed_out=False,
        )
        ctrl._executors["deterministic_understanding"] = retry

        with patch.object(ctrl._graph, "entry_phase", return_value="DONE"):
            resumed = ctrl.run("msg", "banzai")

        assert retry.execute.call_count == 1
        assert resumed.status == "blocked"
        assert store.load()["phase"] == "phase1-understanding"
        assert store.load()["understanding_evidence"]["path"] == "/tmp/original-evidence.json"

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

    def test_consecutive_why1_fails_remain_in_the_declared_discovery_loop(self, tmp_path):
        """WHY1 has no spec issue ledger, so its graph iteration cap owns retries."""
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
        state["why_failure_baseline"] = {
            "phase_id": "phase1-why1",
            "recorded_at": "2020-01-01T00:00:00Z",
        }
        store.save(state)
        result = ctrl._evaluate_transitions(ctrl._graph.get("phase1-why1"), provider.exec_agent.return_value)
        assert result == "phase1-discover"
        state = store.load()
        assert state.get("escalation_question") is None

    def test_consecutive_why2_fail_with_active_spec_progress_routes_to_repair(self, tmp_path):
        """Fresh WHY2 artifacts in state.spec_dir count as progress."""
        provider = _mock_provider()
        result = SquadAgentResult(
            exit_code=0,
            echelon_result={
                "verdict": "FAIL",
                "state_updates": {"quality_scores": [{"pass": False}]},
            },
            raw_output="",
            duration_ms=0,
            timed_out=False,
        )
        ctrl, store = _controller(tmp_path, provider=provider)
        store.initialize("r", "semi", "msg", 0, "phase1-why2", max_iterations=5)
        store.increment_why_fail_count()

        spec_dir = tmp_path / "runs" / "run-test" / "specs" / "001-demo"
        spec_dir.mkdir(parents=True)
        (spec_dir / "issues.md").write_text("# Fresh WHY2 findings\n", encoding="utf-8")
        state = store.load()
        state["spec_dir"] = "runs/run-test/specs/001-demo"
        state["last_dispatch"] = {"completed_at": "2020-01-01T00:00:00Z"}
        state["why_failure_baseline"] = {
            "phase_id": "phase1-why2",
            "recorded_at": "2020-01-01T00:00:00Z",
        }
        store.save(state)

        node = ctrl._graph.get("phase1-why2")
        next_phase = ctrl._evaluate_transitions(node, result)

        assert next_phase == "phase1-what"
        assert store.load().get("escalation_question") is None

    def test_what_artifact_repair_starts_a_fresh_why_failure_cycle(self, tmp_path):
        """A repaired spec must not inherit a WHY failure from its prior version."""
        ctrl, store = _controller(tmp_path)
        store.initialize("r", "semi", "msg", 0, "phase1-what", max_iterations=5)
        spec_dir = tmp_path / "runs" / "run-test" / "specs" / "001-demo"
        spec_dir.mkdir(parents=True)
        (spec_dir / "spec.md").write_text("# Repaired specification\n", encoding="utf-8")
        state = store.load()
        state.update(
            {
                "spec_dir": "runs/run-test/specs/001-demo",
                "why_fail_count": 1,
                "why2_metric_stagnation_count": 1,
                "why_failure_baseline": {
                    "phase_id": "phase1-why2",
                    "recorded_at": "2020-01-01T00:00:00+00:00",
                },
            }
        )
        store.save(state)

        what_result = SquadAgentResult(
            exit_code=0,
            echelon_result={
                "verdict": "DONE",
                "state_updates": {"evidence_resolution_status": "not_required"},
            },
            raw_output="", duration_ms=0, timed_out=False,
        )
        ctrl._evaluate_transitions(ctrl._graph.get("phase1-what"), what_result)

        refreshed = store.load()
        assert refreshed["why_fail_count"] == 0
        assert refreshed["why2_metric_stagnation_count"] == 0
        assert "why_failure_baseline" not in refreshed

        why2_result = SquadAgentResult(
            exit_code=0,
            echelon_result={
                "verdict": "FAIL",
                "state_updates": {"quality_scores": [{"pass": False}]},
            },
            raw_output="", duration_ms=0, timed_out=False,
        )
        assert ctrl._evaluate_transitions(ctrl._graph.get("phase1-why2"), why2_result) == "phase1-what"
        assert store.load()["why_fail_count"] == 1
        assert store.load().get("escalation_question") is None

    def test_consecutive_why_escalation_gives_an_actionable_question(self, tmp_path):
        ctrl, store = _controller(tmp_path)
        store.initialize("r", "semi", "msg", 0, "phase1-why2", max_iterations=5)
        spec_dir = tmp_path / "runs" / "run-test" / "specs" / "001-demo"
        spec_dir.mkdir(parents=True)
        (spec_dir / "issues.md").write_text("# Findings\n", encoding="utf-8")
        state = store.load()
        state.update(
            {
                "spec_dir": "runs/run-test/specs/001-demo",
                "why_fail_count": 1,
                "why_failure_baseline": {
                    "phase_id": "phase1-why2",
                    "recorded_at": "2999-01-01T00:00:00+00:00",
                },
            }
        )
        store.save(state)
        result = SquadAgentResult(
            exit_code=0,
            echelon_result={
                "verdict": "FAIL",
                "state_updates": {"quality_scores": [{"pass": False}]},
            },
            raw_output="", duration_ms=0, timed_out=False,
        )

        assert ctrl._evaluate_transitions(ctrl._graph.get("phase1-why2"), result) == "terminal-blocked"
        question = store.load()["escalation_question"]
        assert "No retry is authorized" in question
        assert "echelon spec resolve ISS-<n>" in question
        assert str(spec_dir / "issues.md") in question

    def test_banzai_escalation_inline_when_agent_sets_escalation_question(self, tmp_path, monkeypatch):
        """Banzai: WHY1 returns escalation_question in state_updates → inline COMMANDER, not routing judge."""
        from harness.squad_provider import SquadAgentResult
        _disable_lexicon_gate(tmp_path)
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
                            "spec_status": "planned",
                            "evidence_resolution_status": "not_required",
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
                        "state_updates": {
                            "quality_scores": [{"pass": True}],
                            "evidence_resolution_status": "not_required",
                            "finding_routes": {"findings": []},
                        },
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
        monkeypatch.setattr(ctrl, "_lexicon_gate_config", lambda: {"lexicon_gate": {"enabled": False}})
        # This fixture deliberately stops before producing Phase A build inputs.
        # Keep its assertion scoped to banzai escalation recovery rather than
        # finalization readiness, which is covered by dedicated readiness tests.
        from harness.phase_a_readiness import PhaseAReadinessResult
        monkeypatch.setattr(
            ctrl,
            "_publish_phase_a_artifacts_for_build",
            lambda: PhaseAReadinessResult(
                ready=True,
                blockers=[],
                missing={},
                ready_spec_dir=None,
            ),
        )
        store.initialize("r", "banzai", "msg", 0, "phase1-why1", max_iterations=5)
        _mark_constitution_complete(tmp_path, store)
        state = store.load()
        state["spec_id"] = "001-test"
        # This routing-focused test intentionally produces no Phase A artifact
        # tree; use the declared future location instead of the existing
        # staging directory so terminal publication is not falsely activated.
        state["spec_dir"] = "specs/001-test"
        store.save(state)
        spec_dir = tmp_path / "specs" / "001-test"
        spec_dir.mkdir(parents=True)
        (spec_dir / "spec.md").write_text(_valid_lexicon_spec(), encoding="utf-8")
        (spec_dir / "00-overview.md").write_text("# Overview\n", encoding="utf-8")
        _install_passing_understanding(monkeypatch)
        result = ctrl.run("msg", "banzai")
        # Provider called at least twice: once for WHY1, once for COMMANDER escalation
        assert provider.exec_agent.call_count >= 2
        # Run did not end blocked
        assert result.status != "blocked"
        final_state = store.load()
        assert final_state["escalation_resolved"] is True
        assert final_state["escalation_resolver"] == "COMMANDER-banzai"

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
        _disable_lexicon_gate(tmp_path)
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
        _disable_governance_gate(tmp_path)
        _disable_lexicon_gate(tmp_path)
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
        _disable_governance_gate(tmp_path)
        _disable_lexicon_gate(tmp_path)
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
    def test_accept_with_risk_cannot_override_sage_qualitative_failure(self, tmp_path):
        _disable_lexicon_gate(tmp_path)
        ctrl, store = _controller(tmp_path)
        store.initialize("r", "banzai", "msg", 0, "phase3-consensus", max_iterations=10)
        state = store.load()
        state.update(
            {
                "iteration": 9,
                "why3_verdict": "FAIL",
                "assess2_verdict": "PASS",
                "gate_decision": "accept_with_risk",
                "phase_recommendation": "advance_past_consensus_to_delivery",
                "quality_scores": [
                    {"pass": True, "source": "harness:understanding"}
                ],
            }
        )
        store.save(state)

        consensus_result = SquadAgentResult(
            exit_code=0,
            echelon_result={"verdict": "DONE", "state_updates": {}},
            raw_output="",
            duration_ms=0,
            timed_out=False,
        )
        assert ctrl._evaluate_transitions(
            ctrl._graph.get("phase3-consensus"), consensus_result
        ) == "phase3-consensus-tasks-lexicon"
        gate = ctrl._graph.get("phase3-consensus-tasks-lexicon")
        gate_result = ctrl._executors["deterministic_lexicon"].execute(gate, store)
        assert ctrl._evaluate_transitions(gate, gate_result) == "phase1-what"

    def test_accept_with_risk_can_override_feasibility_rejection_only(self, tmp_path):
        _disable_lexicon_gate(tmp_path)
        ctrl, store = _controller(tmp_path)
        store.initialize("r", "banzai", "msg", 0, "phase3-consensus", max_iterations=10)
        state = store.load()
        state.update(
            {
                "iteration": 9,
                "why3_verdict": "PASS",
                "assess2_verdict": "REJECTED",
                "gate_decision": "accept_with_risk",
                "quality_scores": [
                    {"pass": True, "source": "harness:understanding"}
                ],
            }
        )
        store.save(state)

        consensus_result = SquadAgentResult(
            exit_code=0,
            echelon_result={"verdict": "DONE", "state_updates": {}},
            raw_output="",
            duration_ms=0,
            timed_out=False,
        )
        assert ctrl._evaluate_transitions(
            ctrl._graph.get("phase3-consensus"), consensus_result
        ) == "phase3-consensus-tasks-lexicon"
        gate = ctrl._graph.get("phase3-consensus-tasks-lexicon")
        gate_result = ctrl._executors["deterministic_lexicon"].execute(gate, store)
        assert ctrl._evaluate_transitions(gate, gate_result) == "checkpoint-plan"


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

    def test_unknown_judgment_reporting_state_is_quarantined_before_mutation(self, tmp_path):
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

        assert next_phase == "phase1-why1"
        assert state.get("status") != "blocked"
        assert "unauthorized_key" not in state
        journal = tmp_path / "squad" / "run-test" / "reasoning-journal.jsonl"
        entries = [json.loads(line) for line in journal.read_text().splitlines()]
        assert entries[0]["type"] == "state_contract_warning"
        assert entries[0]["data"]["dropped_keys"] == ["unauthorized_key"]

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

    def test_banzai_consecutive_fail_recovery_resets_counter_controller_side(self, tmp_path):
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
        store.initialize("r", "banzai", "msg", 0, "phase1-why2", max_iterations=5)
        state = store.load()
        state["status"] = "blocked"
        state["why_fail_count"] = 2
        state["escalation_question"] = "Two consecutive WHY2 failures"
        state["blocked_reason"] = "consecutive_why_fails"
        store.save(state)

        ctrl._judgment_dispatch_escalation(
            "Two consecutive WHY2 failures",
            "phase1-why2",
        )

        assert store.load()["why_fail_count"] == 0

    def test_banzai_escalation_applies_commander_next_phase(self, tmp_path):
        """A banzai judgment route must replace terminal-blocked, not become metadata."""
        provider = _mock_provider()
        provider.exec_agent.return_value = SquadAgentResult(
            exit_code=0,
            echelon_result={
                "verdict": "JUDGMENT_RESOLVED",
                "state_updates": {
                    "next_phase": "checkpoint-assess",
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
        store.initialize("r", "banzai", "msg", 0, "terminal-blocked", max_iterations=5)
        state = store.load()
        state.update(
            {
                "status": "running",
                "escalation_question": "Two consecutive WHY2 failures",
                "blocked_reason": "consecutive_why_fails",
            }
        )
        store.save(state)

        ctrl._judgment_dispatch_escalation(
            "Two consecutive WHY2 failures",
            "phase1-why2",
            recovery_reason="consecutive_why_fails",
        )

        resumed = store.load()
        assert resumed["phase"] == "checkpoint-assess"
        assert "next_phase" not in resumed

    def test_terminal_blocked_never_runs_phase_a_finalization(self, tmp_path):
        """A terminal block is a stop state, even if an earlier handler set running."""
        ctrl, store = _controller(tmp_path)
        store.initialize("r", "banzai", "msg", 0, "terminal-blocked", max_iterations=5)
        state = store.load()
        state.update(
            {
                "status": "running",
                "blocked_reason": "consecutive_why_fails",
                "escalation_question": "Two consecutive WHY2 failures",
            }
        )
        store.save(state)

        with patch.object(ctrl, "_publish_terminal_phase_a_artifacts_if_available") as publish:
            result = ctrl.run("msg", "banzai")

        assert result.status == "blocked"
        assert store.load()["blocked_reason"] == "consecutive_why_fails"
        publish.assert_not_called()

    def test_banzai_phase_dispatch_limit_recovery_resets_capped_phase(self, tmp_path):
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
        store.initialize("r", "banzai", "msg", 0, "phase1-what", max_iterations=5)
        state = store.load()
        state.update(
            {
                "status": "running",
                "phase": "terminal-blocked",
                "blocked_reason": None,
                "escalation_question": (
                    "Phase 'phase1-what' has been dispatched 6 times (limit 5) "
                    "without converging or advancing."
                ),
                "phase_dispatch_limit_phase": "phase1-what",
                "phase_dispatch_counts": {"phase1-what": 6},
            }
        )
        store.save(state)

        ctrl._judgment_dispatch_escalation(
            state["escalation_question"],
            "terminal-blocked",
            recovery_reason="phase_dispatch_limit",
        )

        resumed = store.load()
        assert "phase1-what" not in resumed["phase_dispatch_counts"]
        assert resumed["phase_dispatch_limit_recovery"]["phase"] == "phase1-what"

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
        assert cfg["feasibility_structural_pass"] is False
        assert cfg["intent_alignment_check_structural_pass"] is False

    def test_gate_config_uses_local_overrides_and_extension_defaults(self, tmp_path):
        config_dir = tmp_path / ".echelon"
        config_dir.mkdir()
        (config_dir / "config.yml").write_text(
            "lexicon_gate:\n"
            "  enabled: true\n",
            encoding="utf-8",
        )
        (config_dir / "local.yml").write_text(
            "lexicon_gate:\n"
            "  artifacts:\n"
            "    tasks:\n"
            "      enabled: false\n",
            encoding="utf-8",
        )

        ctrl, _ = _controller(tmp_path)
        gate = ctrl._lexicon_gate_config()["lexicon_gate"]

        assert gate["enabled"] is True
        assert gate["artifacts"]["spec"]["enabled"] is True
        assert gate["artifacts"]["tasks"]["enabled"] is False

    def test_disabled_tasks_subgate_is_routing_inert(self, tmp_path):
        config_dir = tmp_path / ".echelon"
        config_dir.mkdir()
        (config_dir / "config.yml").write_text(
            "lexicon_gate:\n"
            "  enabled: true\n"
            "  artifacts:\n"
            "    tasks:\n"
            "      enabled: false\n",
            encoding="utf-8",
        )
        ctrl, store = _controller(tmp_path)
        node = ctrl._graph.get("phase3-plan")
        store.initialize("r", "banzai", "msg", 0, "phase3-plan", max_iterations=3)

        result = SquadAgentResult(
            exit_code=0,
            echelon_result={"verdict": "DONE", "state_updates": {}},
            raw_output="",
            duration_ms=0,
            timed_out=False,
        )
        with patch.object(
            ctrl,
            "_judgment_dispatch",
            side_effect=AssertionError("disabled tasks gate dispatched COMMANDER"),
        ):
            assert ctrl._evaluate_transitions(node, result) == "phase3-tasks-lexicon"
            gate = ctrl._graph.get("phase3-tasks-lexicon")
            gate_result = ctrl._executors["deterministic_lexicon"].execute(gate, store)
            assert gate_result.state_updates["tasks_lexicon_action"] == "proceed"
            assert ctrl._evaluate_transitions(gate, gate_result) == "phase3-understanding"


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
        st["spec_dir"] = "runs/run-test/specs/001-demo"
        store.save(st)
        spec_dir = tmp_path / "runs" / "run-test" / "specs" / "001-demo"
        spec_dir.mkdir(parents=True)
        (spec_dir / "spec.md").write_text("# Demo\n", encoding="utf-8")
        with patch.object(ctrl, "_judgment_dispatch",
                          side_effect=AssertionError("guard punted to COMMANDER")):
            nxt = ctrl._evaluate_transitions(
                node, self._result({"feasibility_structural_pass": False})
            )
        assert nxt == "phase2-decide"

    def test_omitted_feasibility_structural_result_does_not_fail_open(self, tmp_path):
        from unittest.mock import patch
        ctrl, store = _controller(tmp_path)
        node = ctrl._graph.get("phase2-decide")
        st = store.load()
        st["iteration"] = 0
        st["max_iterations"] = 3
        store.save(st)
        result = SquadAgentResult(
            exit_code=0,
            echelon_result={"verdict": "PASS", "state_updates": {}},
            raw_output="",
            duration_ms=0,
            timed_out=False,
        )

        with patch.object(ctrl, "_judgment_dispatch",
                          side_effect=AssertionError("guard punted to COMMANDER")):
            nxt = ctrl._evaluate_transitions(node, result)

        assert nxt == "phase2-decide"

    def test_omitted_intent_alignment_structural_result_does_not_fail_open(self, tmp_path):
        from unittest.mock import patch
        ctrl, store = _controller(tmp_path)
        node = ctrl._graph.get("phase2-tracker-alignment")
        st = store.load()
        st["iteration"] = 0
        st["max_iterations"] = 3
        store.save(st)
        result = SquadAgentResult(
            exit_code=0,
            echelon_result={"verdict": "ALIGNED", "state_updates": {}},
            raw_output="",
            duration_ms=0,
            timed_out=False,
        )

        with patch.object(ctrl, "_judgment_dispatch",
                          side_effect=AssertionError("guard punted to COMMANDER")):
            nxt = ctrl._evaluate_transitions(node, result)

        assert nxt == "phase2-tracker-alignment"

    def test_invalid_feasibility_artifact_overrides_stale_model_pass(self, tmp_path):
        ctrl, store = _controller(tmp_path)
        node = ctrl._graph.get("phase2-decide")
        spec_dir = tmp_path / "runs" / "run-test" / "specs" / "001-demo"
        spec_dir.mkdir(parents=True)
        (spec_dir / "feasibility.md").write_text("# Incomplete\n", encoding="utf-8")
        state = store.load()
        state.update({
            "iteration": 0,
            "max_iterations": 5,
            "spec_dir": str(spec_dir.relative_to(tmp_path)),
        })
        store.save(state)

        result = self._result({"feasibility_structural_pass": True})
        assert ctrl._evaluate_transitions(node, result) == "phase2-decide"
        assert result.state_updates["feasibility_structural_pass"] is False
        report = json.loads(
            Path(result.state_updates["feasibility_structural_report"]).read_text(
                encoding="utf-8"
            )
        )
        assert report["ok"] is False
        assert report["findings"]

    def test_valid_feasibility_artifact_overrides_stale_model_failure(self, tmp_path):
        ctrl, store = _controller(tmp_path)
        node = ctrl._graph.get("phase2-decide")
        spec_dir = tmp_path / "runs" / "run-test" / "specs" / "001-demo"
        spec_dir.mkdir(parents=True)
        (spec_dir / "feasibility.md").write_text(
            "# Feasibility\n\n"
            "## Metadata\nSpec: demo\n\n"
            "## Feasibility Verdict\nTechnical, resource, and domain feasibility confirmed.\n\n"
            "## Key Risks\nNo blocking risks.\n\n"
            "## Kill / Defer / Pass Decision\nDecision: PASS\n",
            encoding="utf-8",
        )
        state = store.load()
        state.update({
            "iteration": 0,
            "max_iterations": 5,
            "spec_dir": str(spec_dir.relative_to(tmp_path)),
        })
        store.save(state)

        result = SquadAgentResult(
            exit_code=0,
            echelon_result={
                "verdict": "PASS",
                "state_updates": {"feasibility_structural_pass": False},
            },
            raw_output="",
            duration_ms=0,
            timed_out=False,
        )
        assert ctrl._evaluate_transitions(node, result) == "phase2-strategic-overview"
        assert result.state_updates["feasibility_structural_pass"] is True

    def test_governance_warn_exhaustion_is_explicit(self, tmp_path):
        ctrl, store = _controller(tmp_path)
        node = ctrl._graph.get("phase2-decide")
        spec_dir = tmp_path / "runs" / "run-test" / "specs" / "001-demo"
        spec_dir.mkdir(parents=True)
        (spec_dir / "feasibility.md").write_text("# Incomplete\n", encoding="utf-8")
        state = store.load()
        state.update({
            "iteration": 3,
            "max_iterations": 5,
            "spec_dir": str(spec_dir.relative_to(tmp_path)),
            "feasibility_structural_attempts": 3,
        })
        store.save(state)

        result = SquadAgentResult(
            exit_code=0,
            echelon_result={"verdict": "PASS", "state_updates": {}},
            raw_output="",
            duration_ms=0,
            timed_out=False,
        )
        assert ctrl._evaluate_transitions(node, result) == "phase2-strategic-overview"
        assert result.state_updates["governance_gate_exhausted"] == "feasibility"

    def test_governance_block_exhaustion_stops_pipeline(self, tmp_path):
        config_dir = tmp_path / ".echelon"
        config_dir.mkdir()
        (config_dir / "config.yml").write_text(
            "governance:\n"
            "  enabled: true\n"
            "  max_repair_attempts: 1\n"
            "  on_exhausted: block\n",
            encoding="utf-8",
        )
        ctrl, store = _controller(tmp_path)
        node = ctrl._graph.get("phase2-decide")
        spec_dir = tmp_path / "runs" / "run-test" / "specs" / "001-demo"
        spec_dir.mkdir(parents=True)
        (spec_dir / "feasibility.md").write_text("# Incomplete\n", encoding="utf-8")
        state = store.load()
        state.update({
            "iteration": 0,
            "max_iterations": 5,
            "spec_dir": str(spec_dir.relative_to(tmp_path)),
        })
        store.save(state)

        result = SquadAgentResult(
            exit_code=0,
            echelon_result={"verdict": "PASS", "state_updates": {}},
            raw_output="",
            duration_ms=0,
            timed_out=False,
        )
        assert ctrl._evaluate_transitions(node, result) == "terminal-blocked"
        assert store.load()["blocked_reason"] == "governance_gate_exhausted"


class TestProductInputMappingRepair:
    def test_dispatch_reason_is_controller_owned(self, tmp_path):
        ctrl, store = _controller(tmp_path)
        store.initialize("r", "banzai", "msg", 0, "phase3-plan", max_iterations=5)
        assert ctrl._dispatch_reason("phase3-plan", 1) == "initial"
        assert ctrl._dispatch_reason("phase3-plan", 2) == "planned_iteration"
        assert ctrl._dispatch_reason("phase1-what", 2) == "semantic_repair"
        state = store.load()
        state["product_input_mapping_repair"] = {"protocol_version": 2}
        store.save(state)
        assert ctrl._dispatch_reason("phase3-plan", 2) == "deterministic_repair"

    def test_blocker_event_survives_mutable_state_rewrite(self, tmp_path):
        ctrl, store = _controller(tmp_path)
        store.initialize("r", "banzai", "msg", 0, "phase3-plan", max_iterations=5)
        ctrl._block_after_executor_failure(
            "phase3-plan", "agent_exit_code_1", SquadAgentResult(1, None, "", 0, False)
        )
        state = store.load()
        state["blocked_reason"] = "rewritten"
        store.save(state)
        events = [json.loads(line) for line in ctrl._telemetry_store.events_path.read_text().splitlines()]
        assert events[-1]["type"] == "blocker"
        assert events[-1]["reason"] == "agent_exit_code_1"

    def test_analyzer_uses_controller_blocker_history_not_state(self, tmp_path):
        ctrl, store = _controller(tmp_path)
        store.initialize("r", "banzai", "msg", 0, "phase3-plan", max_iterations=5)
        result = SquadAgentResult(1, None, "", 0, False)
        ctrl._block_after_executor_failure("phase3-plan", "agent_exit_code_1", result)
        ctrl._block_after_executor_failure("phase3-plan", "agent_exit_code_1", result)
        state = store.load()
        state["blocked_reason_history"] = []
        store.save(state)

        report = analyze_spec_run(store.squad_dir)

        assert report.workflow_metrics["repeated_blockers"] == {"agent_exit_code_1": 2}

    def test_plan_mapping_failure_is_requeued_with_controller_context(self, tmp_path):
        ctrl, store = _controller(tmp_path)
        store.initialize("r", "banzai", "msg", 0, "phase3-plan", max_iterations=5)

        repaired = ctrl._schedule_product_input_mapping_repair(
            "phase3-plan",
            "invalid product input task mappings: "
            "IN-REQ-1: unresolved disposition open_question",
        )

        state = store.load()
        assert repaired is True
        assert state["phase"] == "phase3-plan"
        assert state["status"] == "running"
        assert state["product_input_mapping_repair_attempts"] == 1
        assert state["product_input_mapping_repair"]["blockers"] == [
            "IN-REQ-1: unresolved disposition open_question"
        ]

    def test_what_phase_unknown_input_ids_are_requeued_with_canonical_ids(self, tmp_path):
        from echelon.product_inputs import parse_input_declaration, resolve_product_inputs

        ctrl, store = _controller(tmp_path)
        source = tmp_path / "requirements.md"
        source.write_text("A normative requirement.\n", encoding="utf-8")
        resolution = resolve_product_inputs(
            tmp_path,
            store.squad_dir,
            [parse_input_declaration("requirement:requirements.md")],
        )
        canonical_id = json.loads(resolution.catalog_path.read_text(encoding="utf-8"))["units"][0]["id"]
        store.initialize(
            "r", "banzai", "msg", 0, "phase1-what", max_iterations=5,
            product_inputs=resolution.state_payload(tmp_path),
        )

        repaired = ctrl._schedule_product_input_mapping_repair(
            "phase1-what",
            "invalid product input updates: product input update references unknown "
            "requirement unit 'IN-REQ-FILTER-GROUPS'",
        )

        state = store.load()
        assert repaired is True
        assert state["phase"] == "phase1-what"
        assert state["status"] == "running"
        assert state["product_input_mapping_repair"]["invalid_input_unit_ids"] == [
            "IN-REQ-FILTER-GROUPS"
        ]
        assert state["product_input_mapping_repair"]["valid_requirement_ids"] == [canonical_id]

    def test_plan_mapping_repair_stops_after_bounded_attempts(self, tmp_path):
        ctrl, store = _controller(tmp_path)
        store.initialize("r", "banzai", "msg", 0, "phase3-plan", max_iterations=5)
        state = store.load()
        state["product_input_mapping_repair_attempts"] = 2
        state["product_input_mapping_repair"] = {"protocol_version": 2}
        store.save(state)

        repaired = ctrl._schedule_product_input_mapping_repair(
            "phase3-plan",
            "invalid product input task mappings: "
            "IN-REQ-1: unresolved disposition open_question",
        )

        assert repaired is False

    def test_outdated_mapping_repair_protocol_gets_a_fresh_budget(self, tmp_path):
        ctrl, store = _controller(tmp_path)
        store.initialize("r", "banzai", "msg", 0, "phase3-plan", max_iterations=5)
        state = store.load()
        state["product_input_mapping_repair_attempts"] = 2
        state["product_input_mapping_repair"] = {"attempt": 2, "blockers": ["old"]}
        state["phase_dispatch_counts"] = {"phase3-plan": 4}
        store.save(state)

        repaired = ctrl._schedule_product_input_mapping_repair(
            "phase3-plan",
            "invalid product input task mappings: "
            "IN-REQ-1: unresolved disposition open_question",
        )

        state = store.load()
        assert repaired is True
        assert state["product_input_mapping_repair_attempts"] == 1
        assert state["product_input_mapping_repair"]["protocol_version"] == 2
        assert state["phase_dispatch_counts"]["phase3-plan"] == 0


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

    def test_spec_lexicon_node_certifies_valid_artifact_without_provider(self, tmp_path):
        provider = _mock_provider()
        ctrl, store = _controller(tmp_path, provider=provider)
        node = ctrl._graph.get("phase1-lexicon")
        spec_dir = tmp_path / "runs" / "run-test" / "specs" / "001-demo"
        spec_dir.mkdir(parents=True)
        source = """# Feature

- **FR-001**: Render the dashboard.
- **AC-001**: Given data, when rendering, then the dashboard is visible.
"""
        (spec_dir / "spec.md").write_text(source, encoding="utf-8")
        (spec_dir / "glossary.md").write_text(
            "### dashboard_key\n- **Definition:** A dashboard identifier.\n",
            encoding="utf-8",
        )
        digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
        (spec_dir / "requirements.lexicon.md").write_text(
            f"""# SOURCE: spec.md
# SOURCE_SHA256: {digest}
ARTIFACT: SPEC
TITLE: Dashboard

REQ: FR-001
GIVEN: dashboard_key is available
WHEN: the user opens the dashboard
THEN: The system SHALL render the dashboard
OUTPUT: The dashboard is visible
DEPENDS: none
EXAMPLE: AC-001

AC: AC-001
GIVEN: data is available
WHEN: the user opens the dashboard
THEN: The dashboard is visible
""",
            encoding="utf-8",
        )
        state = store.load()
        state["spec_dir"] = str(spec_dir.relative_to(tmp_path))
        store.save(state)

        result = ctrl._executors["deterministic_lexicon"].execute(node, store)

        provider.exec_agent.assert_not_called()
        assert result.verdict == "DONE"
        assert result.state_updates["lexicon_evaluation"] == "passed"
        assert result.state_updates["lexicon_pass"] is True
        assert result.state_updates["lexicon_attempts"] == 0
        assert result.state_updates["lexicon_findings"] == 0
        report_path = Path(result.state_updates["lexicon_report"])
        assert report_path.is_file()
        report = json.loads(report_path.read_text(encoding="utf-8"))
        assert report["ok"] is True
        assert report["artifact_sha256"] == hashlib.sha256(
            (spec_dir / "requirements.lexicon.md").read_bytes()
        ).hexdigest()
        assert report["source_sha256"] == hashlib.sha256(
            (spec_dir / "spec.md").read_bytes()
        ).hexdigest()
        assert report["glossary_sha256"] == hashlib.sha256(
            (spec_dir / "glossary.md").read_bytes()
        ).hexdigest()

    def test_legacy_understanding_resume_routes_through_visible_spec_gate(self, tmp_path):
        ctrl, store = _controller(tmp_path)
        state = store.load()
        state.update({
            "phase": "phase1-understanding",
            "spec_dir": "runs/run-test/specs/001-demo",
        })
        store.save(state)

        guarded = ctrl._guard_spec_lexicon_evidence("phase1-understanding")

        assert guarded == "phase1-lexicon"
        assert store.load()["phase"] == "phase1-lexicon"

    def test_later_phase_resume_without_current_evidence_reopens_spec_pipeline(
        self, tmp_path
    ):
        ctrl, store = _controller(tmp_path)
        state = store.load()
        state.update({
            "phase": "phase2-decide",
            "iteration": 9,
            "why_fail_count": 2,
            "convergence_forced": True,
            "convergence_detected": True,
            "convergence_guard_fire_count": 3,
            "phase_recommendation": "phase2-decide",
            "spec_dir": "runs/run-test/specs/001-demo",
            "completed_phases": [
                "phase1-what",
                "phase1-lexicon",
                "phase1-understanding",
                "phase1-why2",
                "checkpoint-assess",
            ],
            "phase_dispatch_counts": {
                "phase1-what": 1,
                "phase1-lexicon": 1,
                "phase1-understanding": 1,
                "phase1-why2": 1,
                "checkpoint-assess": 1,
            },
        })
        store.save(state)

        guarded = ctrl._guard_spec_lexicon_evidence("phase2-decide")

        assert guarded == "phase1-lexicon"
        persisted = store.load()
        assert persisted["completed_phases"] == ["phase1-what"]
        assert persisted["phase_dispatch_counts"] == {"phase1-what": 1}
        assert persisted["iteration"] == 0
        assert persisted["why_fail_count"] == 0
        assert "phase_recommendation" not in persisted
        assert persisted["convergence_forced"] is False
        assert persisted["convergence_detected"] is False
        assert persisted["convergence_guard_fire_count"] == 0

    def test_current_spec_lexicon_evidence_allows_understanding(self, tmp_path):
        provider = _mock_provider()
        ctrl, store = _controller(tmp_path, provider=provider)
        node = ctrl._graph.get("phase1-lexicon")
        spec_dir = tmp_path / "runs" / "run-test" / "specs" / "001-demo"
        spec_dir.mkdir(parents=True)
        source = """# Feature

- **FR-001**: Render the dashboard.
- **AC-001**: Given data, when rendering, then the dashboard is visible.
"""
        (spec_dir / "spec.md").write_text(source, encoding="utf-8")
        digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
        (spec_dir / "requirements.lexicon.md").write_text(
            "# SOURCE: spec.md\n"
            f"# SOURCE_SHA256: {digest}\n"
            "ARTIFACT: SPEC\n"
            "TITLE: Dashboard\n\n"
            "REQ: FR-001\n"
            "GIVEN: data is available\n"
            "WHEN: the user opens the dashboard\n"
            "THEN: The system SHALL render the dashboard\n"
            "OUTPUT: The dashboard is visible\n"
            "DEPENDS: none\n"
            "EXAMPLE: AC-001\n\n"
            "AC: AC-001\n"
            "GIVEN: data is available\n"
            "WHEN: the user opens the dashboard\n"
            "THEN: The dashboard is visible\n",
            encoding="utf-8",
        )
        state = store.load()
        state["spec_dir"] = str(spec_dir.relative_to(tmp_path))
        store.save(state)
        result = ctrl._executors["deterministic_lexicon"].execute(node, store)
        store.advance(
            node.id,
            "phase1-understanding",
            result,
            allowed_state_update_keys=ctrl._advance_state_update_keys(node),
        )

        guarded = ctrl._guard_spec_lexicon_evidence("phase1-understanding")

        assert guarded == "phase1-understanding"

        (spec_dir / "glossary.md").write_text("**Dashboard**\n", encoding="utf-8")
        guarded = ctrl._guard_spec_lexicon_evidence("phase1-understanding")

        assert guarded == "phase1-lexicon"

    def test_disabled_spec_lexicon_gate_allows_understanding_without_evidence(
        self, tmp_path
    ):
        _disable_lexicon_gate(tmp_path)
        ctrl, store = _controller(tmp_path)
        state = store.load()
        state["phase"] = "phase1-understanding"
        store.save(state)

        assert (
            ctrl._guard_spec_lexicon_evidence("phase1-understanding")
            == "phase1-understanding"
        )

    def test_manual_spec_lexicon_node_is_visible_and_provider_free(
        self, tmp_path, capsys
    ):
        provider = _mock_provider()
        ctrl, store = _controller(tmp_path, provider=provider)
        store.initialize("r", "brownfield", "msg", 0, "phase1-lexicon")
        _mark_constitution_complete(tmp_path, store)
        spec_dir = tmp_path / "runs" / "run-test" / "specs" / "001-demo"
        spec_dir.mkdir(parents=True)
        state = store.load()
        state["spec_dir"] = str(spec_dir.relative_to(tmp_path))
        store.save(state)

        result = ctrl.run_single_phase("phase1-lexicon", "validate", "banzai")

        provider.exec_agent.assert_not_called()
        assert result.phase == "phase1-what"
        assert "phase1-lexicon" in store.load()["completed_phases"]
        output = capsys.readouterr().out
        assert "Deterministic Spec Lexicon Gate" in output
        assert "spec Lexicon pending" in output

    def test_gate_config_loads_lexicon_gate_block(self, tmp_path):
        ctrl, _ = _controller(tmp_path)
        cfg = ctrl._lexicon_gate_config()
        assert "lexicon_gate" in cfg
        assert cfg["lexicon_gate"].get("enabled") is True

    def test_spec_lexicon_gate_uses_the_iteration_dispatch_budget(self):
        """WHAT repairs and their visible gate use max_iterations, not the generic cap."""
        from harness.squad import ITERATIVE_PHASES

        assert "phase1-what" in ITERATIVE_PHASES
        assert "phase1-lexicon" in ITERATIVE_PHASES

    @pytest.mark.parametrize(
        ("phase_id", "next_phase"),
        [
            ("phase3-tasks-lexicon", "phase3-understanding"),
            ("phase3-consensus-tasks-lexicon", "checkpoint-plan"),
        ],
    )
    def test_run_resumes_tasks_lexicon_nodes_without_provider(
        self,
        tmp_path,
        phase_id,
        next_phase,
    ):
        _disable_lexicon_gate(tmp_path)
        provider = _mock_provider()
        ctrl, store = _controller(tmp_path, provider=provider)
        store.initialize("r", "banzai", "msg", 0, phase_id, max_iterations=3)
        _mark_constitution_complete(tmp_path, store)
        state = store.load()
        state.update({
            "why3_verdict": "PASS",
            "assess2_verdict": "PASS",
            "quality_scores": [{"pass": True, "source": "harness:understanding"}],
        })
        store.save(state)
        ctrl._checkpoint_successful_phase = MagicMock(return_value=False)

        result = ctrl.run("msg", "banzai")

        provider.exec_agent.assert_not_called()
        assert result.phase == next_phase
        assert phase_id in store.load()["completed_phases"]
        ctrl._checkpoint_successful_phase.assert_called_once_with(
            phase_id,
            next_phase,
        )

    def test_plan_routes_to_visible_tasks_gate_without_hidden_certification(self, tmp_path):
        ctrl, store = _controller(tmp_path)
        node = ctrl._graph.get("phase3-plan")
        spec_dir = tmp_path / "runs" / "run-test" / "specs" / "001-demo"
        spec_dir.mkdir(parents=True)
        (spec_dir / "requirements.lexicon.md").write_text(_valid_lexicon_spec(), encoding="utf-8")
        (spec_dir / "tasks.md").write_text("not canonical tasks\n", encoding="utf-8")
        st = store.load()
        st.update({
            "iteration": 0,
            "max_iterations": 3,
            "spec_dir": str(spec_dir.relative_to(tmp_path)),
        })
        store.save(st)
        result = self._result({})
        with patch.object(ctrl, "_judgment_dispatch",
                          side_effect=AssertionError("guard punted to COMMANDER — not deterministic")):
            nxt = ctrl._evaluate_transitions(node, result)

        assert nxt == "phase3-tasks-lexicon"
        assert result.state_updates == {}
        assert not (spec_dir / "tasks-lexicon-report.json").exists()

    def test_tasks_gate_failure_redispatches_without_provider_or_commander(self, tmp_path):
        provider = _mock_provider()
        ctrl, store = _controller(tmp_path, provider=provider)
        node = ctrl._graph.get("phase3-tasks-lexicon")
        spec_dir = tmp_path / "runs" / "run-test" / "specs" / "001-demo"
        spec_dir.mkdir(parents=True)
        (spec_dir / "requirements.lexicon.md").write_text(
            _valid_lexicon_spec(), encoding="utf-8"
        )
        (spec_dir / "tasks.md").write_text("not canonical tasks\n", encoding="utf-8")
        st = store.load()
        st.update({
            "iteration": 0,
            "max_iterations": 3,
            "spec_dir": str(spec_dir.relative_to(tmp_path)),
        })
        store.save(st)

        result = ctrl._executors["deterministic_lexicon"].execute(node, store)
        with patch.object(ctrl, "_judgment_dispatch",
                          side_effect=AssertionError("gate punted to COMMANDER")):
            nxt = ctrl._evaluate_transitions(node, result)

        provider.exec_agent.assert_not_called()
        assert nxt == "phase3-plan"
        assert result.state_updates["tasks_lexicon_action"] == "repair"
        assert result.state_updates["tasks_lexicon_pass"] is False
        assert result.state_updates["tasks_lexicon_attempts"] == 1
        report_path = Path(result.state_updates["tasks_lexicon_report"])
        assert report_path.is_file()
        report = json.loads(report_path.read_text(encoding="utf-8"))
        assert report["ok"] is False
        assert any(item["code"] == "parse-error" for item in report["findings"])

    def test_tasks_gate_pass_falls_through_to_understanding(self, tmp_path):
        provider = _mock_provider()
        ctrl, store = _controller(tmp_path, provider=provider)
        node = ctrl._graph.get("phase3-tasks-lexicon")
        spec_dir = tmp_path / "runs" / "run-test" / "specs" / "001-demo"
        spec_dir.mkdir(parents=True)
        _write_valid_plan_artifacts(spec_dir)
        st = store.load()
        st.update({
            "iteration": 0,
            "max_iterations": 3,
            "spec_dir": str(spec_dir.relative_to(tmp_path)),
            "tasks_lexicon_pass": False,
            "tasks_lexicon_attempts": 3,
        })
        store.save(st)
        result = ctrl._executors["deterministic_lexicon"].execute(node, store)
        with patch.object(ctrl, "_judgment_dispatch",
                          side_effect=AssertionError("gate punted to COMMANDER")):
            nxt = ctrl._evaluate_transitions(node, result)

        provider.exec_agent.assert_not_called()
        assert nxt == "phase3-understanding"
        assert result.state_updates["tasks_lexicon_action"] == "proceed"
        assert result.state_updates["tasks_lexicon_pass"] is True
        assert result.state_updates["tasks_lexicon_attempts"] == 0

    def test_consensus_revalidates_tasks_after_plan2(self, tmp_path):
        provider = _mock_provider()
        ctrl, store = _controller(tmp_path, provider=provider)
        consensus = ctrl._graph.get("phase3-consensus")
        node = ctrl._graph.get("phase3-consensus-tasks-lexicon")
        spec_dir = tmp_path / "runs" / "run-test" / "specs" / "001-demo"
        spec_dir.mkdir(parents=True)
        _write_valid_plan_artifacts(spec_dir)
        (spec_dir / "tasks.md").write_text("PLAN2 broke the task grammar\n", encoding="utf-8")
        state = store.load()
        state.update({
            "iteration": 0,
            "max_iterations": 3,
            "spec_dir": str(spec_dir.relative_to(tmp_path)),
            "why3-verdict": "PASS",
            "assess2-verdict": "PASS",
            "tasks_lexicon_pass": True,
        })
        store.save(state)

        consensus_result = self._result({})
        assert (
            ctrl._evaluate_transitions(consensus, consensus_result)
            == "phase3-consensus-tasks-lexicon"
        )
        assert consensus_result.state_updates == {}

        result = ctrl._executors["deterministic_lexicon"].execute(node, store)
        with patch.object(
            ctrl,
            "_judgment_dispatch",
            side_effect=AssertionError("post-PLAN2 tasks gate punted to COMMANDER"),
        ):
            nxt = ctrl._evaluate_transitions(node, result)

        provider.exec_agent.assert_not_called()
        assert nxt == "phase3-plan"
        assert result.state_updates["tasks_lexicon_pass"] is False

    def test_tasks_gate_rejects_invalid_target_ownership(self, tmp_path):
        ctrl, store = _controller(tmp_path)
        node = ctrl._graph.get("phase3-tasks-lexicon")
        spec_dir = tmp_path / "runs" / "run-test" / "specs" / "001-demo"
        spec_dir.mkdir(parents=True)
        _write_valid_plan_artifacts(spec_dir)
        (spec_dir / "tasks.md").write_text(
            _valid_tasks().replace("target=sources/app", "target=sources/other"),
            encoding="utf-8",
        )
        state = store.load()
        state.update({
            "iteration": 0,
            "max_iterations": 3,
            "spec_dir": str(spec_dir.relative_to(tmp_path)),
        })
        store.save(state)

        result = ctrl._executors["deterministic_lexicon"].execute(node, store)
        assert ctrl._evaluate_transitions(node, result) == "phase3-plan"
        report = json.loads(
            Path(result.state_updates["tasks_lexicon_report"]).read_text(encoding="utf-8")
        )
        assert any(item["code"] == "undeclared-target" for item in report["findings"])

    def test_tasks_gate_reports_missing_plan_outputs(self, tmp_path):
        ctrl, store = _controller(tmp_path)
        node = ctrl._graph.get("phase3-consensus-tasks-lexicon")
        spec_dir = tmp_path / "runs" / "run-test" / "specs" / "001-demo"
        spec_dir.mkdir(parents=True)
        _write_valid_plan_artifacts(spec_dir)
        (spec_dir / "risk-matrix.md").unlink()
        state = store.load()
        state.update({
            "iteration": 0,
            "max_iterations": 3,
            "spec_dir": str(spec_dir.relative_to(tmp_path)),
            "why3-verdict": "PASS",
            "assess2-verdict": "PASS",
        })
        store.save(state)

        result = ctrl._executors["deterministic_lexicon"].execute(node, store)
        assert ctrl._evaluate_transitions(node, result) == "phase3-plan"
        report = json.loads(
            Path(result.state_updates["tasks_lexicon_report"]).read_text(encoding="utf-8")
        )
        assert {
            item["artifact"]
            for item in report["findings"]
            if item["code"] == "missing-plan-output"
        } == {"risk-matrix.md"}

    def test_what_routes_to_visible_spec_gate_without_commander(self, tmp_path):
        """WHAT cannot bypass the visible deterministic spec Lexicon node."""
        ctrl, store = _controller(tmp_path)
        node = ctrl._graph.get("phase1-what")
        st = store.load()
        st["iteration"] = 0
        st["max_iterations"] = 3
        st["spec_dir"] = "runs/run-test/specs/001-demo"
        store.save(st)
        spec_dir = tmp_path / "runs" / "run-test" / "specs" / "001-demo"
        spec_dir.mkdir(parents=True)
        (spec_dir / "spec.md").write_text("# Demo\n", encoding="utf-8")

        with patch.object(
            ctrl,
            "_judgment_dispatch",
            side_effect=AssertionError("missing Lexicon result punted to COMMANDER"),
        ):
            nxt = ctrl._evaluate_transitions(node, self._result({}))

        assert nxt == "phase1-lexicon"

    def test_spec_gate_marks_missing_derived_artifact_pending_without_false_result(self, tmp_path):
        """No derived artifact means validation has not happened, not failed."""
        ctrl, store = _controller(tmp_path)
        node = ctrl._graph.get("phase1-lexicon")
        st = store.load()
        st["iteration"] = 0
        st["max_iterations"] = 3
        st["spec_dir"] = "runs/run-test/specs/001-demo"
        store.save(st)
        spec_dir = tmp_path / "runs" / "run-test" / "specs" / "001-demo"
        spec_dir.mkdir(parents=True)
        (spec_dir / "spec.md").write_text("# Demo\n", encoding="utf-8")
        stale_report = spec_dir / "spec-lexicon-report.json"
        stale_report.write_text('{"ok": false}\n', encoding="utf-8")
        state = store.load()
        state["lexicon_report"] = str(stale_report)
        state["lexicon_findings"] = 4
        store.save(state)
        result = ctrl._executors["deterministic_lexicon"].execute(node, store)

        with patch.object(
            ctrl,
            "_judgment_dispatch",
            side_effect=AssertionError("missing artifact punted to COMMANDER"),
        ):
            nxt = ctrl._evaluate_transitions(node, result)

        assert nxt == "phase1-what"
        assert "lexicon_pass" not in result.state_updates
        assert "lexicon_findings" not in result.state_updates
        assert "lexicon_report" not in result.state_updates
        assert result.state_updates["lexicon_evaluation"] == "pending"

        store.advance(
            node.id,
            nxt,
            result,
            allowed_state_update_keys=ctrl._advance_state_update_keys(node),
        )
        persisted = store.load()
        assert persisted["lexicon_evaluation"] == "pending"
        assert "lexicon_pass" not in persisted
        assert "lexicon_findings" not in persisted
        assert "lexicon_report" not in persisted

    def test_spec_gate_uses_controller_validation_not_agent_stale_failure(self, tmp_path):
        """A valid artifact advances even if the agent reports stale failed state."""
        ctrl, store = _controller(tmp_path)
        node = ctrl._graph.get("phase1-lexicon")
        spec_dir = tmp_path / "runs" / "run-test" / "specs" / "001-demo"
        spec_dir.mkdir(parents=True)
        source = """# Feature\n\n- **FR-001**: Render the dashboard.\n- **AC-001**: Given data, when rendering, then the dashboard is visible.\n"""
        (spec_dir / "spec.md").write_text(source, encoding="utf-8")
        (spec_dir / "glossary.md").write_text("", encoding="utf-8")
        digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
        (spec_dir / "requirements.lexicon.md").write_text(
            f"""# SOURCE: spec.md
# SOURCE_SHA256: {digest}
ARTIFACT: SPEC
TITLE: Dashboard

REQ: FR-001
GIVEN: data is available
WHEN: the user opens the dashboard
THEN: The system SHALL render the dashboard
OUTPUT: The dashboard is visible
DEPENDS: none
EXAMPLE: AC-001

AC: AC-001
GIVEN: data is available
WHEN: the user opens the dashboard
THEN: The dashboard is visible
""",
            encoding="utf-8",
        )
        state = store.load()
        state.update({
            "iteration": 0,
            "max_iterations": 10,
            "spec_dir": str(spec_dir.relative_to(tmp_path)),
            "lexicon_pass": False,
            "lexicon_attempts": 3,
            "lexicon_findings": 55,
        })
        store.save(state)
        result = ctrl._executors["deterministic_lexicon"].execute(node, store)

        nxt = ctrl._evaluate_transitions(node, result)

        assert nxt == "phase1-understanding"
        assert result.state_updates["lexicon_evaluation"] == "passed"
        assert result.state_updates["lexicon_pass"] is True
        assert result.state_updates["lexicon_attempts"] == 0
        assert result.state_updates["lexicon_findings"] == 0
        report_path = Path(result.state_updates["lexicon_report"])
        assert report_path.is_file()
        assert json.loads(report_path.read_text(encoding="utf-8"))["ok"] is True

    def test_spec_gate_records_false_only_after_controller_validation(self, tmp_path):
        """An invalid derived artifact receives a real, controller-certified failure."""
        ctrl, store = _controller(tmp_path)
        node = ctrl._graph.get("phase1-lexicon")
        spec_dir = tmp_path / "runs" / "run-test" / "specs" / "001-demo"
        spec_dir.mkdir(parents=True)
        (spec_dir / "spec.md").write_text("# Feature\n", encoding="utf-8")
        (spec_dir / "requirements.lexicon.md").write_text("not Lexicon grammar\n", encoding="utf-8")
        state = store.load()
        state.update({
            "iteration": 0,
            "max_iterations": 3,
            "spec_dir": str(spec_dir.relative_to(tmp_path)),
            "lexicon_attempts": 1,
        })
        store.save(state)
        result = ctrl._executors["deterministic_lexicon"].execute(node, store)

        assert ctrl._evaluate_transitions(node, result) == "phase1-what"
        assert result.state_updates["lexicon_evaluation"] == "failed"
        assert result.state_updates["lexicon_pass"] is False
        assert result.state_updates["lexicon_findings"] > 0
        assert result.state_updates["lexicon_attempts"] == 2
        report_path = Path(result.state_updates["lexicon_report"])
        assert report_path.is_file()
        report = json.loads(report_path.read_text(encoding="utf-8"))
        assert report["schema_version"] == 1
        assert report["artifact_type"] == "SPEC"
        assert report["artifact_path"] == str(spec_dir / "requirements.lexicon.md")
        assert report["source_path"] == str(spec_dir / "spec.md")
        assert report["glossary_path"] == str(spec_dir / "glossary.md")
        assert report["ok"] is False
        assert report["findings"]
        assert {"code", "message"}.issubset(report["findings"][0])

    def test_spec_gate_uses_resolved_local_paths_in_report(self, tmp_path):
        config_dir = tmp_path / ".echelon"
        config_dir.mkdir(parents=True)
        (config_dir / "config.yml").write_text(
            "lexicon_gate:\n"
            "  enabled: true\n"
            "  artifacts:\n"
            "    spec:\n"
            "      enabled: true\n",
            encoding="utf-8",
        )
        (config_dir / "local.yml").write_text(
            "lexicon_gate:\n"
            "  glossary_file: domain-glossary.md\n"
            "  artifacts:\n"
            "    spec:\n"
            "      path: controlled-requirements.md\n"
            "      source_ref: product-spec.md\n",
            encoding="utf-8",
        )
        ctrl, store = _controller(tmp_path)
        node = ctrl._graph.get("phase1-lexicon")
        spec_dir = tmp_path / "runs/run-test/specs/001-demo"
        spec_dir.mkdir(parents=True)
        (spec_dir / "product-spec.md").write_text("# Product spec\n", encoding="utf-8")
        (spec_dir / "controlled-requirements.md").write_text(
            "not Lexicon grammar\n", encoding="utf-8"
        )
        (spec_dir / "domain-glossary.md").write_text("", encoding="utf-8")
        state = store.load()
        state.update({
            "iteration": 0,
            "max_iterations": 3,
            "spec_dir": str(spec_dir.relative_to(tmp_path)),
        })
        store.save(state)
        result = ctrl._executors["deterministic_lexicon"].execute(node, store)

        assert ctrl._evaluate_transitions(node, result) == "phase1-what"
        report = json.loads(
            Path(result.state_updates["lexicon_report"]).read_text(encoding="utf-8")
        )
        assert report["artifact_path"] == str(spec_dir / "controlled-requirements.md")
        assert report["source_path"] == str(spec_dir / "product-spec.md")
        assert report["glossary_path"] == str(spec_dir / "domain-glossary.md")

    def test_spec_gate_blocks_on_exhaustion_when_configured_hard(self, tmp_path):
        """A hard Lexicon gate cannot fall through after its final repair pass."""
        (tmp_path / ".echelon").mkdir()
        (tmp_path / ".echelon" / "config.yml").write_text(
            "lexicon_gate:\n"
            "  enabled: true\n"
            "  on_exhausted: block\n"
            "  artifacts:\n"
            "    spec:\n"
            "      enabled: true\n"
            "      path: requirements.lexicon.md\n",
            encoding="utf-8",
        )
        ctrl, store = _controller(tmp_path)
        node = ctrl._graph.get("phase1-lexicon")
        st = store.load()
        st["iteration"] = 3
        st["max_iterations"] = 3
        st["spec_dir"] = "runs/run-test/specs/001-demo"
        store.save(st)
        spec_dir = tmp_path / "runs" / "run-test" / "specs" / "001-demo"
        spec_dir.mkdir(parents=True)
        (spec_dir / "spec.md").write_text("# Demo\n", encoding="utf-8")

        result = ctrl._executors["deterministic_lexicon"].execute(node, store)
        nxt = ctrl._evaluate_transitions(node, result)

        assert nxt == "terminal-blocked"
        state = store.load()
        assert state["status"] == "blocked"
        assert state["blocked_reason"] == "lexicon_gate_exhausted"

    def test_pending_spec_gate_warns_without_commander_punt_at_iteration_cap(self, tmp_path):
        """A configured warning may advance at the cap without inventing a failure."""
        (tmp_path / ".echelon").mkdir()
        (tmp_path / ".echelon" / "config.yml").write_text(
            "lexicon_gate:\n"
            "  enabled: true\n"
            "  on_exhausted: warn\n"
            "  artifacts:\n"
            "    spec:\n"
            "      enabled: true\n"
            "      path: requirements.lexicon.md\n",
            encoding="utf-8",
        )
        ctrl, store = _controller(tmp_path)
        node = ctrl._graph.get("phase1-lexicon")
        state = store.load()
        state.update({
            "iteration": 3,
            "max_iterations": 3,
            "spec_dir": "runs/run-test/specs/001-demo",
        })
        store.save(state)
        spec_dir = tmp_path / "runs" / "run-test" / "specs" / "001-demo"
        spec_dir.mkdir(parents=True)
        (spec_dir / "spec.md").write_text("# Demo\n", encoding="utf-8")
        result = ctrl._executors["deterministic_lexicon"].execute(node, store)

        with patch.object(
            ctrl,
            "_judgment_dispatch",
            side_effect=AssertionError("pending Lexicon state punted to COMMANDER"),
        ):
            nxt = ctrl._evaluate_transitions(node, result)

        assert nxt == "phase1-understanding"
        assert result.state_updates["lexicon_evaluation"] == "pending"
        assert "lexicon_pass" not in result.state_updates
        assert result.state_updates["lexicon_warning_waiver"] is True

        store.advance(
            node.id,
            nxt,
            result,
            allowed_state_update_keys=ctrl._advance_state_update_keys(node),
        )
        assert ctrl._guard_spec_lexicon_evidence(nxt) == "phase1-understanding"

    def test_spec_gate_does_not_trust_stale_failure_without_validation(self, tmp_path):
        """Stale failure state cannot exhaust a gate whose artifact was not validated."""
        (tmp_path / ".echelon").mkdir()
        (tmp_path / ".echelon" / "config.yml").write_text(
            "lexicon_gate:\n"
            "  enabled: true\n"
            "  max_repair_attempts: 3\n"
            "  on_exhausted: block\n"
            "  artifacts:\n"
            "    spec:\n"
            "      enabled: true\n"
            "      path: requirements.lexicon.md\n",
            encoding="utf-8",
        )
        ctrl, store = _controller(tmp_path)
        node = ctrl._graph.get("phase1-lexicon")
        st = store.load()
        st["iteration"] = 0
        st["max_iterations"] = 10
        st["spec_dir"] = "runs/run-test/specs/001-demo"
        st["lexicon_pass"] = False
        st["lexicon_attempts"] = 3
        store.save(st)
        spec_dir = tmp_path / "runs" / "run-test" / "specs" / "001-demo"
        spec_dir.mkdir(parents=True)
        (spec_dir / "spec.md").write_text("# Demo\n", encoding="utf-8")

        result = ctrl._executors["deterministic_lexicon"].execute(node, store)
        nxt = ctrl._evaluate_transitions(node, result)

        assert nxt == "phase1-what"
        assert result.state_updates["lexicon_evaluation"] == "pending"
        assert "lexicon_pass" not in result.state_updates
        assert result.state_updates["lexicon_attempts"] == 0
