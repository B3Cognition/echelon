"""Integration coverage for run-local squad context generation."""
from __future__ import annotations

import sys
from pathlib import Path
import subprocess
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

EXT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(EXT_ROOT) not in sys.path:
    sys.path.insert(0, str(EXT_ROOT))

from echelon.context_builder import build_run_context
from echelon.context_metadata import artifact_hash
from harness.phase_graph import PhaseGraph, PhaseNode
from harness.phase_a_readiness import REQUIRED_PHASE_A_BUILD_INPUTS
from harness.squad import SquadController
from harness.squad_executors import AgentExecutor
from harness.squad_provider import SquadAgentResult
from harness.squad_state import SquadStateStore

DEFINITION = EXT_ROOT / "extension/workflow/definition.yaml"
EXT_YML = EXT_ROOT / "extension/extension.yml"


def _ensure_git_repo(project_root: Path) -> None:
    if (project_root / ".git").exists():
        return
    subprocess.run(
        ["git", "init", "-b", "main"],
        cwd=project_root,
        check=True,
        capture_output=True,
    )
    subprocess.run(["git", "config", "user.name", "Echelon Tests"], cwd=project_root, check=True)
    subprocess.run(
        ["git", "config", "user.email", "echelon@example.test"],
        cwd=project_root,
        check=True,
    )
    subprocess.run(
        ["git", "commit", "--allow-empty", "-m", "base"],
        cwd=project_root,
        check=True,
        capture_output=True,
    )


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


def _tracker_provider(verdict: str) -> MagicMock:
    state_updates = {}
    if verdict == "STOP_AND_ASK":
        state_updates = {
            "status": "blocked",
            "blocked_reason": "human_clarification_required",
            "escalation_question": "Which target repository should Echelon inspect?",
        }

    provider = MagicMock()
    provider.exec_agent.return_value = SquadAgentResult(
        exit_code=0,
        echelon_result={"verdict": verdict, "state_updates": state_updates},
        raw_output="",
        duration_ms=100,
        timed_out=False,
    )
    return provider


def _controller(
    tmp_path: Path,
    provider: MagicMock | None = None,
    squad_dir: Path | None = None,
) -> tuple[SquadController, SquadStateStore]:
    _ensure_git_repo(tmp_path)
    if squad_dir is None:
        squad_dir = tmp_path / "runs" / "run-test"
    squad_dir.mkdir(parents=True, exist_ok=True)
    (squad_dir / "staging").mkdir(exist_ok=True)
    graph = PhaseGraph(DEFINITION, EXT_YML)
    store = SquadStateStore(squad_dir)
    ctrl = SquadController(
        provider=provider or _mock_provider(),
        state_store=store,
        phase_graph=graph,
        ext_dir=EXT_ROOT / "extension",
        project_root=tmp_path,
        token_budget=0,
        squad_dir=squad_dir,
    )
    return ctrl, store


def test_run_context_generation_uses_runs_directory(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "spec-1"
    run_dir.mkdir(parents=True)

    result = build_run_context(tmp_path, run_dir, user_request="build photo sharing")

    assert result.context_dir == run_dir / "context"
    assert result.prior_context.exists()
    assert result.current_context.exists()
    assert result.stale_report.exists()


@pytest.mark.parametrize("verdict", ["ALIGNED", "DRIFT"])
def test_phase1_tracker_canonical_progress_verdicts_route_forward(
    tmp_path: Path,
    verdict: str,
) -> None:
    provider = _tracker_provider(verdict)
    ctrl, store = _controller(tmp_path, provider=provider)

    result = ctrl.run_single_phase("phase1-tracker", "build photo sharing", "semi")
    state = store.load()
    context_dir = Path(state["context_dir"])

    assert result.phase == "phase1-why1"
    assert state["last_dispatch"]["phase_id"] == "phase1-tracker"
    assert state["last_dispatch"]["verdict"] == verdict
    assert state["manual_phase_runs"][-1]["next_phase"] == "phase1-why1"
    assert context_dir == tmp_path / "runs" / "run-test" / "context"
    assert context_dir.exists()
    assert (context_dir / "prior-spec-context.md").exists()
    assert (context_dir / "current-feature-context.md").exists()
    assert (context_dir / "feature-registry.snapshot.json").exists()
    assert (context_dir / "mempalace-reconciliation.json").exists()
    assert (context_dir / "stale-memory-report.md").exists()


def test_phase1_tracker_stop_and_ask_verdict_routes_back(
    tmp_path: Path,
) -> None:
    provider = _tracker_provider("STOP_AND_ASK")
    ctrl, store = _controller(tmp_path, provider=provider)

    result = ctrl.run_single_phase("phase1-tracker", "build photo sharing", "semi")
    state = store.load()

    assert result.phase == "phase1-tracker"
    assert state["last_dispatch"]["phase_id"] == "phase1-tracker"
    assert state["last_dispatch"]["verdict"] == "STOP_AND_ASK"
    assert state["manual_phase_runs"][-1]["next_phase"] == "phase1-tracker"
    assert result.status == "blocked"
    assert state["blocked_reason"] == "human_clarification_required"
    assert state["escalation_question"] == "Which target repository should Echelon inspect?"


def test_run_context_refresh_retrieves_and_reconciles_mempalace_drawers(tmp_path: Path) -> None:
    spec = tmp_path / "specs" / "001-photo-album" / "spec.md"
    spec.parent.mkdir(parents=True)
    spec.write_text("FR-001: Upload a photo.\n", encoding="utf-8")
    drawer = SimpleNamespace(
        drawer_id="drawer-1",
        content="FR-001: Upload a photo.",
        metadata={
            "artifact_path": "specs/001-photo-album/spec.md",
            "artifact_hash": artifact_hash(spec),
            "lifecycle_status": "active",
            "status": "pending",
        },
    )
    reader = MagicMock()
    reader.search_requirements.return_value = [drawer]
    provider = _mock_provider()
    ctrl, store = _controller(tmp_path, provider=provider)
    store.initialize("run-test", "brownfield", "build upload flow", 0, "init", max_iterations=5)

    with patch("codegen.memory.context.MemPalaceContext.from_project", return_value=object()) as mock_ctx:
        with patch("codegen.memory.mempalace_reader.MemPalaceReader", return_value=reader):
            ctrl._refresh_run_context("test")

    prior_context = (
        tmp_path / "runs" / "run-test" / "context" / "prior-spec-context.md"
    ).read_text(encoding="utf-8")

    mock_ctx.assert_called_once_with(tmp_path, run_id="run-test")
    reader.search_requirements.assert_called_once_with("build upload flow", n_results=10)
    assert "## Reconciled MemPalace Results" in prior_context
    assert "drawer-1" in prior_context


def test_assemble_prompt_resolves_context_dir_context_pack_entries(tmp_path: Path) -> None:
    squad_dir = tmp_path / "runs" / "run-test"
    context_dir = squad_dir / "context"
    context_dir.mkdir(parents=True)
    (squad_dir / "staging").mkdir(parents=True, exist_ok=True)
    (context_dir / "prior-spec-context.md").write_text(
        "# Prior Spec Context\n\nKnown feature history.\n",
        encoding="utf-8",
    )

    provider = MagicMock()
    graph = MagicMock()
    graph.agent_file.return_value = None
    graph.all_phase_ids.return_value = []
    executor = AgentExecutor(
        provider=provider,
        phase_graph=graph,
        ext_dir=tmp_path / "extension",
        project_root=tmp_path,
        squad_dir=squad_dir,
    )
    node = PhaseNode(
        id="phase1-test",
        type="agent",
        context_pack=["{context_dir}/prior-spec-context.md"],
    )
    state = {
        "squad_dir": str(squad_dir),
        "staging_dir": str(squad_dir / "staging"),
        "context_dir": str(context_dir),
    }

    prompt = executor._assemble_prompt(node, state)

    assert str(context_dir) in prompt
    assert f"# {context_dir}/prior-spec-context.md" in prompt
    assert "Known feature history." in prompt


def test_assemble_prompt_ignores_retired_golddigger_cache_state(tmp_path: Path) -> None:
    squad_dir = tmp_path / "runs" / "run-test"
    cache_dir = squad_dir / "golddigger-cache"
    cache_dir.mkdir(parents=True)
    (squad_dir / "staging").mkdir(parents=True, exist_ok=True)
    (cache_dir / "auth.md").write_text("# Auth Deep Dive\n\nToken flow details.\n", encoding="utf-8")

    provider = MagicMock()
    graph = MagicMock()
    graph.agent_file.return_value = None
    graph.all_phase_ids.return_value = []
    executor = AgentExecutor(
        provider=provider,
        phase_graph=graph,
        ext_dir=tmp_path / "extension",
        project_root=tmp_path,
        squad_dir=squad_dir,
    )
    node = PhaseNode(id="phase1-test", type="agent")
    state = {
        "squad_dir": str(squad_dir),
        "staging_dir": str(squad_dir / "staging"),
        "golddigger_completed_domains": ["auth"],
    }

    prompt = executor._assemble_prompt(node, state)

    assert "# GOLDDIGGER Mode 2 Cache" not in prompt
    assert "golddigger-cache/auth.md" not in prompt
    assert "Token flow details." not in prompt


def test_run_context_refreshes_after_phase_updates_run_local_spec_artifacts(
    tmp_path: Path,
) -> None:
    _ensure_git_repo(tmp_path)
    definition = tmp_path / "definition.yaml"
    extension_yml = tmp_path / "extension.yml"
    definition.write_text(
        """
phases:
  - id: init
    type: agent
    transitions:
      - to: phase1-constitution
        condition: verdict = DONE
  - id: phase1-constitution
    type: agent
    context_pack:
      - "{context_dir}/current-feature-context.md"
    transitions:
      - to: DONE
        condition: always
""",
        encoding="utf-8",
    )
    extension_yml.write_text("provides: {commands: []}\n", encoding="utf-8")

    squad_dir = tmp_path / "runs" / "run-refresh"
    squad_dir.mkdir(parents=True, exist_ok=True)
    (squad_dir / "staging").mkdir(exist_ok=True)
    graph = PhaseGraph(definition, extension_yml)
    store = SquadStateStore(squad_dir)
    store.initialize(
        "run-refresh",
        "greenfield",
        "refresh run-local context",
        0,
        "init",
        autonomy_mode="banzai",
    )
    initial_state = store.load()
    initial_state["spec_id"] = "001-demo"
    initial_state["spec_dir"] = "runs/run-refresh/specs/001-demo"
    store.save(initial_state)

    provider = MagicMock()
    run_local_spec_dir = squad_dir / "specs" / "001-demo"
    call_count = 0

    def _exec_agent(project_root: str, prompt: str) -> SquadAgentResult:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            run_local_spec_dir.mkdir(parents=True, exist_ok=True)
            (run_local_spec_dir / "spec.md").write_text(
                "# Demo Spec\n\n- FR-123: Refreshed context.\n",
                encoding="utf-8",
            )
            for name in REQUIRED_PHASE_A_BUILD_INPUTS:
                if name != "spec.md":
                    content = (
                        '{\n'
                        '  "status": "pass",\n'
                        '  "findings": [],\n'
                        '  "sources": ["spec.md", "requirements-overview.md", "plan.md", "tasks.md"]\n'
                        '}\n'
                        if name == "plan-conformance.json"
                        else f"# {name}\n"
                    )
                    (run_local_spec_dir / name).write_text(
                        content, encoding="utf-8"
                    )
            return SquadAgentResult(
                exit_code=0,
                echelon_result={
                    "verdict": "DONE",
                    "state_updates": {},
                },
                raw_output="",
                duration_ms=50,
                timed_out=False,
            )
        return SquadAgentResult(
            exit_code=0,
            echelon_result={"verdict": "DONE", "state_updates": {}},
            raw_output="",
            duration_ms=50,
            timed_out=False,
        )

    provider.exec_agent.side_effect = _exec_agent

    ctrl = SquadController(
        provider=provider,
        state_store=store,
        phase_graph=graph,
        ext_dir=EXT_ROOT / "extension",
        project_root=tmp_path,
        token_budget=0,
        squad_dir=squad_dir,
    )

    result = ctrl.run("refresh run-local context", "banzai")

    current_context = (squad_dir / "context" / "current-feature-context.md").read_text(
        encoding="utf-8",
    )
    second_prompt = provider.exec_agent.call_args_list[1].args[1]

    assert result.status == "done"
    assert "FR-123" in current_context
    assert "FR-123" in second_prompt
