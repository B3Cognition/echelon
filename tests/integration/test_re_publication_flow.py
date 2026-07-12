from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

from harness.phase_graph import PhaseNode
from harness.re_publication import publish_re_run
from harness.re_registry import canonical_re_artifacts, load_published_index
from harness.squad_executors import AgentExecutor
from harness.squad_provider import SquadAgentResult
from harness.squad_state import SquadStateStore
from tests.unit.test_re_publication import write_valid_re_run


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


def test_complete_golddigger_publishes_canonical_workspace_context(tmp_path: Path) -> None:
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


def test_golddigger_mode1_recovers_forwarded_nested_re_extract_result(
    tmp_path: Path,
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
    assert provider.exec_agent.call_count == 2
    recovery_prompt = provider.exec_agent.call_args_list[1].args[1]
    assert "forwarded a nested re-extract result" in recovery_prompt
    assert (tmp_path / "re/index.json").is_file()
    assert state_store.load()["golddigger_status"] == "complete"


def test_all_empty_workspace_publishes_successfully_without_source_specs(
    tmp_path: Path,
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


def test_zero_source_workspace_publishes_workspace_generation(tmp_path: Path) -> None:
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
    executor, node, provider = _pre_dispatch_executor(
        tmp_path,
        run_dir,
        "complete",
    )

    result = executor._run_pre_dispatch(node, state_store.load(), state_store)

    assert result is None
    provider.exec_agent.assert_called_once()
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


def test_automatic_partial_output_is_not_published(tmp_path: Path) -> None:
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
    executor, node, provider = _pre_dispatch_executor(
        tmp_path,
        run_dir,
        "partial",
    )

    result = executor._run_pre_dispatch(node, state_store.load(), state_store)

    assert result is None
    provider.exec_agent.assert_called_once()
    assert not (tmp_path / "re/index.json").exists()
    updated = state_store.load()
    assert updated["golddigger_status"] == "partial"
    assert updated["re_generation"] == 0
    assert updated["re_publication_required"] is True
