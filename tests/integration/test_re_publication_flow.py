from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from harness.re_controller import ReControllerResult
from harness.phase_graph import PhaseNode
from harness.re_publication import publish_re_run
from harness.re_registry import canonical_re_artifacts, load_published_index
from harness.squad_executors import AgentExecutor
from harness.squad_provider import SquadAgentResult
from harness.squad_state import SquadStateStore
from tests.unit.test_re_publication import _deep_spec, write_valid_re_run


def _pre_dispatch_executor(
    root: Path,
    run_dir: Path,
    status: str,
) -> tuple[AgentExecutor, PhaseNode, MagicMock]:
    ext_dir = root / "ext"
    agent_dir = ext_dir / "agents"
    agent_dir.mkdir(parents=True, exist_ok=True)
    (agent_dir / "golddigger.md").write_text("# GOLDDIGGER\n", encoding="utf-8")
    provider = MagicMock()
    provider.exec_agent.return_value = SquadAgentResult(
        exit_code=0,
        echelon_result={
            "verdict": "DONE",
            "state_updates": {"golddigger_status": status},
            "journal_entries": [],
        },
        raw_output="",
        duration_ms=1,
        timed_out=False,
    )
    graph = MagicMock()
    graph.agent_file.return_value = "agents/golddigger.md"
    executor = AgentExecutor(provider, graph, ext_dir, root, run_dir)
    node = PhaseNode(
        id="phase1-discover",
        type="agent",
        pre_dispatch=[
            {"id": "golddigger_mode1", "agent": "speckit-echelon-golddigger"}
        ],
        allowed_state_updates=["golddigger_status"],
    )
    return executor, node, provider


def _stub_mode1_controller(
    monkeypatch: pytest.MonkeyPatch,
    outcome: ReControllerResult = ReControllerResult(completed=True),
) -> list[dict[str, object]]:
    calls: list[dict[str, object]] = []

    class StubController:
        def __init__(self, **kwargs: object) -> None:
            calls.append(kwargs)

        def run(self) -> ReControllerResult:
            return outcome

    monkeypatch.setattr("harness.squad_executors.ReExtractionController", StubController)
    return calls


def test_complete_golddigger_publishes_canonical_workspace_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir = write_valid_re_run(tmp_path, ("api",), run_id="run-test")
    state_store = SquadStateStore(run_dir)
    state = state_store.load()
    state.update(
        {
            "re_refresh_sources": ["api"],
            "re_generation": 0,
            "re_publication_required": True,
            "re_workspace_synthesis_required": True,
            "re_analysis_required": True,
        }
    )
    state_store.save(state)
    _stub_mode1_controller(monkeypatch)

    ext_dir = tmp_path / "ext"
    agent_dir = ext_dir / "agents"
    agent_dir.mkdir(parents=True)
    (agent_dir / "golddigger.md").write_text("# GOLDDIGGER\n", encoding="utf-8")
    provider = MagicMock()
    provider.exec_agent.return_value = SquadAgentResult(
        exit_code=0,
        echelon_result={
            "verdict": "DONE",
            "state_updates": {"golddigger_status": "complete"},
            "journal_entries": [],
        },
        raw_output="",
        duration_ms=1,
        timed_out=False,
    )
    graph = MagicMock()
    graph.agent_file.return_value = "agents/golddigger.md"
    executor = AgentExecutor(provider, graph, ext_dir, tmp_path, run_dir)
    node = PhaseNode(
        id="phase1-discover",
        type="agent",
        pre_dispatch=[
            {"id": "golddigger_mode1", "agent": "speckit-echelon-golddigger"}
        ],
        allowed_state_updates=["golddigger_status"],
    )

    result = executor._run_pre_dispatch(node, state_store.load(), state_store)

    assert result is None
    index = json.loads((tmp_path / "re/index.json").read_text(encoding="utf-8"))
    assert index["generation"] == 1
    assert set(index["sources"]) == {"api"}
    updated = state_store.load()
    assert updated["re_generation"] == 1
    assert updated["golddigger_status"] == "complete"
    assert updated["golddigger_mode"] == "workspace-full-re"
    assert updated["re_artifacts"]["manifest"] == str(tmp_path / "re/index.json")
    assert updated["golddigger_artifacts"] == updated["re_artifacts"]
    assert updated["re_sources"]["api"] == str(
        tmp_path / "re/sources/api/manifest.json"
    )
    assert updated["re_workspace"] == str(tmp_path / "re/workspace/manifest.json")
    assert not updated["re_publication_required"]


def test_mode1_runs_harness_controller_before_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir = write_valid_re_run(tmp_path, ("api",), run_id="run-controller")
    state_store = SquadStateStore(run_dir)
    state = state_store.load()
    state.update(
        {
            "re_refresh_sources": ["api"],
            "re_generation": 0,
            "re_publication_required": True,
            "re_workspace_synthesis_required": True,
            "re_analysis_required": True,
        }
    )
    state_store.save(state)
    executor, node, provider = _pre_dispatch_executor(tmp_path, run_dir, "complete")
    calls: list[dict[str, object]] = []

    class CompleteController:
        def __init__(self, **kwargs: object) -> None:
            calls.append(kwargs)

        def run(self) -> ReControllerResult:
            return ReControllerResult(completed=True)

    monkeypatch.setattr("harness.squad_executors.ReExtractionController", CompleteController)

    result = executor._run_pre_dispatch(node, state_store.load(), state_store)

    assert result is None
    assert len(calls) == 1
    assert calls[0]["run_dir"] == run_dir
    provider.exec_agent.assert_not_called()
    assert (tmp_path / "re" / "index.json").is_file()


def test_mode1_controller_rebuilds_missing_state_and_specs_before_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir = write_valid_re_run(tmp_path, ("api",), run_id="run-fresh")
    run_re = run_dir / "re"
    shutil.rmtree(run_re / "sources")
    (run_re / "state.json").unlink()
    (run_re / "re-analysis-manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "workspace": {"root": str(tmp_path)},
                "sources": [{"id": "api", "path": "sources/api"}],
            }
        ),
        encoding="utf-8",
    )

    state_store = SquadStateStore(run_dir)
    state = state_store.load()
    state.update(
        {
            "re_refresh_sources": ["api"],
            "re_generation": 0,
            "re_publication_required": True,
            "re_workspace_synthesis_required": True,
            "re_analysis_required": True,
        }
    )
    state_store.save(state)

    ext_dir = tmp_path / "ext"
    for name in (
        "analyzer",
        "specifier",
        "verifier",
        "expander",
        "validator",
        "checklister",
        "constituter",
    ):
        path = ext_dir / "agents" / "re" / f"{name}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# {name}\n", encoding="utf-8")
    script = ext_dir / "scripts" / "bash" / "re" / "run-analysis.sh"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text("#!/usr/bin/env bash\n", encoding="utf-8")

    script_calls: list[tuple[list[str], dict[str, object]]] = []

    def run_analysis(
        _controller: object,
        command: list[str],
        environment: dict[str, str],
    ) -> subprocess.CompletedProcess[str]:
        script_calls.append((command, {"environment": environment, "timeout": 10_800}))
        source = run_re / "sources" / "api"
        source.mkdir(parents=True, exist_ok=True)
        (source / "analysis.json").write_text("{}\n", encoding="utf-8")
        (source / "overview.md").write_text("# API\n", encoding="utf-8")
        (run_re / "analysis.json").write_text("{}\n", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(
        "harness.re_controller.ReExtractionController._execute_analysis_command",
        run_analysis,
    )

    class PipelineProvider:
        def __init__(self) -> None:
            self.phases: list[str] = []

        def exec_agent(self, project_root: str, prompt: str) -> SquadAgentResult:
            phase = prompt.split("RE phase: ", 1)[1].split("\n", 1)[0]
            self.phases.append(phase)
            source = run_re / "sources" / "api"
            if phase == "re-extract-2-specify" and "Domain ID: `" in prompt:
                domain_id = prompt.split("Domain ID: `", 1)[1].split("`", 1)[0]
                spec = source / "specs" / domain_id / "spec.md"
                spec.parent.mkdir(parents=True, exist_ok=True)
                spec.write_text(_deep_spec("api", "v1"), encoding="utf-8")
            updates: dict[str, int] = {}
            if phase == "re-extract-3-verify":
                updates["coverage_pct"] = 80
            if phase == "re-extract-5-validate":
                updates["resolution_pct"] = 80
            payload: dict[str, object] = {
                "verdict": "DONE",
                "state_updates": updates,
                "journal_entries": [],
            }
            if phase == "re-extract-5-validate":
                manifest = json.loads(
                    (source / "domain-manifest.json").read_text(encoding="utf-8")
                )
                payload["semantic_quality_review"] = {
                    "schema_version": 1,
                    "domains": [
                        {
                            "source_id": manifest["source_id"],
                            "domain_id": domain["domain_id"],
                            "verdict": "PASS",
                            "findings": [],
                            "source_evidence": [],
                        }
                        for domain in manifest["domains"]
                    ],
                }
            return SquadAgentResult(
                exit_code=0,
                echelon_result=payload,
                raw_output="",
                duration_ms=1,
                timed_out=False,
            )

    provider = PipelineProvider()
    graph = MagicMock()
    executor = AgentExecutor(provider, graph, ext_dir, tmp_path, run_dir)
    node = PhaseNode(
        id="phase1-discover",
        type="agent",
        pre_dispatch=[
            {"id": "golddigger_mode1", "agent": "speckit-echelon-golddigger"}
        ],
        allowed_state_updates=["golddigger_status"],
    )

    result = executor._run_pre_dispatch(node, state_store.load(), state_store)

    assert result is None
    assert len(script_calls) == 1
    assert script_calls[0][0] == [
        "bash",
        str(script),
        "--output",
        str(run_re),
        "--manifest",
        str(run_re / "re-analysis-manifest.json"),
        "--source-output-root",
        str(run_re / "sources"),
        "--profile",
        "full",
        "--depth",
        "full",
        "--max-lines-per-file",
        "5000",
        "--git-history-limit",
        "2500",
    ]
    assert script_calls[0][1]["timeout"] == 10_800
    assert provider.phases == [
        "re-extract-2-specify",
        "re-extract-2-specify",
        "re-extract-5-validate",
        "re-extract-6-checklist",
        "re-extract-7-constitute",
    ]
    assert (tmp_path / "re" / "index.json").is_file()
    assert (run_re / "sources" / "api" / "specs" / "001-re-src" / "spec.md").is_file()
    assert json.loads((run_re / "state.json").read_text(encoding="utf-8"))["status"] == "done"
    updated = state_store.load()
    assert updated["golddigger_status"] == "complete"
    assert updated["re_generation"] == 1
    assert updated["re_publication_required"] is False


def test_golddigger_mode1_does_not_dispatch_an_outer_agent_after_controller_completion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir = write_valid_re_run(tmp_path, ("api",), run_id="run-nested-result")
    state_store = SquadStateStore(run_dir)
    state = state_store.load()
    state.update(
        {
            "re_refresh_sources": ["api"],
            "re_generation": 0,
            "re_publication_required": True,
            "re_workspace_synthesis_required": True,
            "re_analysis_required": True,
        }
    )
    state_store.save(state)
    _stub_mode1_controller(monkeypatch)

    ext_dir = tmp_path / "ext"
    agent_dir = ext_dir / "agents"
    agent_dir.mkdir(parents=True)
    (agent_dir / "golddigger.md").write_text("# GOLDDIGGER\n", encoding="utf-8")
    provider = MagicMock()
    provider.exec_agent.side_effect = [
        SquadAgentResult(
            exit_code=0,
            echelon_result={
                "verdict": "DONE",
                "phase_id": "re-extract-1-analyze",
                "state_updates": {
                    "mode": "workspace",
                    "domains": [],
                    "artifacts": {"analysis_json": "runs/run-nested-result/re/analysis.json"},
                },
                "journal_entries": [],
            },
            raw_output="nested RE result",
            duration_ms=1,
            timed_out=False,
        ),
        SquadAgentResult(
            exit_code=0,
            echelon_result={
                "verdict": "DONE",
                "state_updates": {"golddigger_status": "complete"},
                "journal_entries": [],
            },
            raw_output="outer GOLDDIGGER result",
            duration_ms=1,
            timed_out=False,
        ),
    ]
    graph = MagicMock()
    graph.agent_file.return_value = "agents/golddigger.md"
    executor = AgentExecutor(provider, graph, ext_dir, tmp_path, run_dir)
    node = PhaseNode(
        id="phase1-discover",
        type="agent",
        pre_dispatch=[
            {"id": "golddigger_mode1", "agent": "speckit-echelon-golddigger"}
        ],
        allowed_state_updates=["golddigger_status"],
    )

    result = executor._run_pre_dispatch(node, state_store.load(), state_store)

    assert result is None
    provider.exec_agent.assert_not_called()
    assert (tmp_path / "re/index.json").is_file()
    assert state_store.load()["golddigger_status"] == "complete"


def test_all_empty_workspace_publishes_successfully_without_source_specs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir = write_valid_re_run(
        tmp_path,
        ("empty",),
        run_id="run-empty",
        actions={"empty": "skip-empty"},
    )
    state_store = SquadStateStore(run_dir)
    state = state_store.load()
    state.update(
        {
            "re_refresh_sources": [],
            "re_empty_sources": ["empty"],
            "re_generation": 0,
            "re_publication_required": True,
            "re_workspace_synthesis_required": True,
            "re_analysis_required": False,
        }
    )
    state_store.save(state)
    _stub_mode1_controller(monkeypatch)

    ext_dir = tmp_path / "ext"
    agent_dir = ext_dir / "agents"
    agent_dir.mkdir(parents=True)
    (agent_dir / "golddigger.md").write_text("# GOLDDIGGER\n", encoding="utf-8")
    provider = MagicMock()
    provider.exec_agent.return_value = SquadAgentResult(
        exit_code=0,
        echelon_result={
            "verdict": "DONE",
            "state_updates": {"golddigger_status": "complete"},
            "journal_entries": [],
        },
        raw_output="",
        duration_ms=1,
        timed_out=False,
    )
    graph = MagicMock()
    graph.agent_file.return_value = "agents/golddigger.md"
    executor = AgentExecutor(provider, graph, ext_dir, tmp_path, run_dir)
    node = PhaseNode(
        id="phase1-discover",
        type="agent",
        pre_dispatch=[
            {"id": "golddigger_mode1", "agent": "speckit-echelon-golddigger"}
        ],
        allowed_state_updates=["golddigger_status"],
    )

    result = executor._run_pre_dispatch(node, state_store.load(), state_store)

    assert result is None
    index = json.loads((tmp_path / "re/index.json").read_text(encoding="utf-8"))
    assert index["sources"]["empty"]["status"] == "empty"
    source_root = tmp_path / "re/sources/empty"
    assert (source_root / "overview.md").is_file()
    assert not list(source_root.glob("specs/*/spec.md"))
    updated = state_store.load()
    assert updated["golddigger_status"] == "complete"
    assert updated["re_generation"] == 1


def test_zero_source_workspace_publishes_workspace_generation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir = write_valid_re_run(tmp_path, (), run_id="run-zero")
    state_store = SquadStateStore(run_dir)
    state = state_store.load()
    state.update(
        {
            "re_refresh_sources": [],
            "re_generation": 0,
            "re_publication_required": True,
            "re_workspace_synthesis_required": True,
            "re_analysis_required": False,
        }
    )
    state_store.save(state)
    _stub_mode1_controller(monkeypatch)
    executor, node, provider = _pre_dispatch_executor(
        tmp_path,
        run_dir,
        "complete",
    )

    result = executor._run_pre_dispatch(node, state_store.load(), state_store)

    assert result is None
    provider.exec_agent.assert_not_called()
    index = json.loads((tmp_path / "re/index.json").read_text(encoding="utf-8"))
    assert index["generation"] == 1
    assert index["sources"] == {}
    assert (tmp_path / "re/workspace/overview.md").is_file()


def test_second_unchanged_run_reuses_canonical_context_without_golddigger(
    tmp_path: Path,
) -> None:
    first_run = write_valid_re_run(tmp_path, ("api",), run_id="run-first")
    publish_re_run(tmp_path, first_run)
    index = load_published_index(tmp_path)
    assert index is not None
    canonical = canonical_re_artifacts(tmp_path, index)
    assert canonical["architecture_map"] == str(
        tmp_path / "re/workspace/architecture-map.json"
    )
    assert canonical["domain_catalog"] == str(
        tmp_path / "re/workspace/domain-catalog.md"
    )
    assert canonical["domain_catalog"] in canonical["re_contexts"]

    second_run = tmp_path / "runs/run-second"
    second_run.mkdir(parents=True)
    state_store = SquadStateStore(second_run)
    state_store.initialize(
        "run-second",
        "brownfield",
        "reuse context",
        0,
        "phase1-discover",
    )
    state = state_store.load()
    state.update(
        {
            "re_refresh_sources": [],
            "re_missing_sources": [],
            "re_empty_sources": [],
            "re_generation": 1,
            "re_publication_required": False,
            "re_workspace_synthesis_required": False,
            "re_analysis_required": False,
            "re_artifacts": canonical,
        }
    )
    state_store.save(state)
    executor, node, provider = _pre_dispatch_executor(
        tmp_path,
        second_run,
        "complete",
    )

    result = executor._run_pre_dispatch(node, state_store.load(), state_store)

    assert result is None
    provider.exec_agent.assert_not_called()
    updated = state_store.load()
    assert updated["golddigger_status"] == "complete"
    assert updated["golddigger_artifacts"] == canonical
    assert updated["golddigger_artifacts"]["manifest"] == str(
        tmp_path / "re/index.json"
    )
    assert all(
        str(tmp_path / "re") in path
        for path in updated["golddigger_artifacts"]["re_contexts"]
    )


def test_controller_failure_is_not_published(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir = write_valid_re_run(
        tmp_path,
        ("api",),
        run_id="run-partial",
        status="partial",
    )
    state_store = SquadStateStore(run_dir)
    state = state_store.load()
    state.update(
        {
            "re_refresh_sources": ["api"],
            "re_generation": 0,
            "re_publication_required": True,
            "re_workspace_synthesis_required": True,
            "re_analysis_required": True,
        }
    )
    state_store.save(state)
    _stub_mode1_controller(
        monkeypatch,
        ReControllerResult(completed=False, blocked_reason="re_agent_dispatch_failed"),
    )
    executor, node, provider = _pre_dispatch_executor(
        tmp_path,
        run_dir,
        "partial",
    )

    result = executor._run_pre_dispatch(node, state_store.load(), state_store)

    assert result is not None
    assert result.blocked
    provider.exec_agent.assert_not_called()
    assert not (tmp_path / "re/index.json").exists()
    updated = state_store.load()
    assert updated["golddigger_status"] == "partial"
    assert updated["re_generation"] == 0
    assert updated["re_publication_required"] is True
