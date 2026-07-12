from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

from harness.phase_graph import PhaseNode
from harness.squad_executors import AgentExecutor
from harness.squad_provider import SquadAgentResult
from harness.squad_state import SquadStateStore
from tests.unit.test_re_publication import write_valid_re_run


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
