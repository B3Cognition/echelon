"""Tests for the single-writer journal protocol.

Covers:
- PhaseExecutor._write_journal_entries (all executor paths)
- SquadController._write_journal_entries (judgment dispatch path)
- Structural: no phase spec file contains direct >> reasoning-journal.jsonl appends
"""
import json
import re
import sys
from pathlib import Path
from unittest.mock import MagicMock

EXT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(EXT_ROOT) not in sys.path:
    sys.path.insert(0, str(EXT_ROOT))

from harness.phase_graph import PhaseGraph
from harness.squad_executors import AgentExecutor, StagedParallelExecutor
from harness.squad_provider import SquadAgentResult


def _executor(tmp_path: Path, squad_dir: Path = None) -> AgentExecutor:
    if squad_dir is None:
        squad_dir = tmp_path / "squad" / "run-test"
        squad_dir.mkdir(parents=True, exist_ok=True)
    provider = MagicMock()
    graph = MagicMock(spec=PhaseGraph)
    graph.agent_file.return_value = None
    graph.all_phase_ids.return_value = ["init", "phase1-discover", "DONE"]
    return AgentExecutor(
        provider=provider,
        phase_graph=graph,
        ext_dir=tmp_path / "ext",
        project_root=tmp_path,
        squad_dir=squad_dir,
    )


def _result(entries=None, verdict="DONE") -> SquadAgentResult:
    return SquadAgentResult(
        exit_code=0,
        echelon_result={
            "verdict": verdict,
            "state_updates": {},
            "journal_entries": entries or [],
        },
        raw_output="",
        duration_ms=0,
        timed_out=False,
    )


def _read_journal(tmp_path: Path, squad_dir: Path = None) -> list[dict]:
    if squad_dir is None:
        squad_dir = tmp_path / "squad" / "run-test"
    p = squad_dir / "reasoning-journal.jsonl"
    if not p.exists():
        return []
    return [json.loads(ln) for ln in p.read_text().splitlines() if ln.strip()]


def test_no_entries_writes_nothing(tmp_path):
    ex = _executor(tmp_path)
    ex._write_journal_entries(_result(entries=[]), "phase1-test")
    assert not (tmp_path / "squad" / "run-test" / "reasoning-journal.jsonl").exists()


def test_single_entry_written(tmp_path):
    ex = _executor(tmp_path)
    ex._write_journal_entries(
        _result(entries=[{"type": "insight", "data": {"msg": "hello"}}]),
        "phase1-discover",
    )
    entries = _read_journal(tmp_path)
    assert len(entries) == 1
    assert entries[0]["type"] == "insight"
    assert entries[0]["phase"] == "phase1-discover"
    assert "id" in entries[0]
    assert "timestamp" in entries[0]


def test_ids_are_monotonically_increasing(tmp_path):
    ex = _executor(tmp_path)
    ex._write_journal_entries(
        _result(entries=[{"type": "insight"}, {"type": "assumption"}]),
        "phase1-discover",
    )
    entries = _read_journal(tmp_path)
    assert entries[0]["id"] == 1
    assert entries[1]["id"] == 2


def test_second_call_continues_id_sequence(tmp_path):
    ex = _executor(tmp_path)
    ex._write_journal_entries(_result(entries=[{"type": "insight"}]), "phase1-a")
    ex._write_journal_entries(_result(entries=[{"type": "challenge"}]), "phase1-b")
    entries = _read_journal(tmp_path)
    assert len(entries) == 2
    assert entries[0]["id"] == 1
    assert entries[1]["id"] == 2


def test_existing_id_not_overwritten(tmp_path):
    ex = _executor(tmp_path)
    ex._write_journal_entries(
        _result(entries=[{"type": "insight", "id": 99}]),
        "phase1-discover",
    )
    entries = _read_journal(tmp_path)
    assert entries[0]["id"] == 99


def test_existing_phase_not_overwritten(tmp_path):
    ex = _executor(tmp_path)
    ex._write_journal_entries(
        _result(entries=[{"type": "insight", "phase": "already-set"}]),
        "phase1-discover",
    )
    entries = _read_journal(tmp_path)
    assert entries[0]["phase"] == "already-set"


def test_non_dict_entries_skipped(tmp_path):
    ex = _executor(tmp_path)
    ex._write_journal_entries(
        _result(entries=["not-a-dict", None, {"type": "insight"}]),
        "phase1-discover",
    )
    entries = _read_journal(tmp_path)
    assert len(entries) == 1
    assert entries[0]["type"] == "insight"


def test_parallel_results_written_serially(tmp_path):
    """Simulate stage-1 parallel agents: journal written after join, ids contiguous."""
    ex = _executor(tmp_path)
    why3_result = _result(entries=[{"type": "challenge", "agent": "why3"}])
    assess2_result = _result(entries=[{"type": "quality_check", "agent": "assess2"}])
    # Both calls happen after ThreadPoolExecutor join — serial by construction
    ex._write_journal_entries(why3_result, "phase3-consensus")
    ex._write_journal_entries(assess2_result, "phase3-consensus")
    entries = _read_journal(tmp_path)
    assert len(entries) == 2
    assert entries[0]["id"] == 1
    assert entries[1]["id"] == 2
    types = {e["type"] for e in entries}
    assert types == {"challenge", "quality_check"}


# ── SquadController._judgment_dispatch journal coverage ──────────────────────

def _squad_controller(tmp_path: Path):
    """Minimal SquadController wired to a mock provider."""
    from harness.phase_graph import PhaseGraph, PhaseNode
    from harness.squad import SquadController
    from harness.squad_state import SquadStateStore

    provider = MagicMock()
    graph = MagicMock(spec=PhaseGraph)
    graph.all_phase_ids.return_value = ["init", "phase1-discover", "DONE"]
    squad_dir = tmp_path / "squad" / "run-test"
    squad_dir.mkdir(parents=True, exist_ok=True)
    store = SquadStateStore(squad_dir)
    store.initialize(
        run_id="test-run",
        mode="semi",
        user_message="test",
        token_budget=0,
        entry_phase="init",
    )
    ctrl = SquadController(
        provider=provider,
        state_store=store,
        phase_graph=graph,
        ext_dir=tmp_path / "ext",
        project_root=tmp_path,
        token_budget=0,
        squad_dir=squad_dir,
    )
    return ctrl, provider


def _node(phase_id: str = "test-phase"):
    from harness.phase_graph import PhaseNode
    return PhaseNode(id=phase_id, type="agent")


def test_judgment_dispatch_writes_returned_journal_entries(tmp_path):
    """Journal entries in COMMANDER's echelon_result are written to disk."""
    ctrl, provider = _squad_controller(tmp_path)
    provider.exec_agent.return_value = SquadAgentResult(
        exit_code=0,
        echelon_result={
            "verdict": "BLOCKED",
            "state_updates": {},
            "journal_entries": [{"type": "escalation", "data": {"reason": "test"}}],
        },
        raw_output="",
        duration_ms=0,
        timed_out=False,
    )
    ctrl._judgment_dispatch("test reason", _node("phase1-discover"))
    entries = _read_journal(tmp_path, squad_dir=tmp_path / "squad" / "run-test")
    assert len(entries) == 1
    assert entries[0]["type"] == "escalation"
    assert entries[0]["phase"] == "phase1-discover"


def test_judgment_dispatch_empty_entries_writes_nothing(tmp_path):
    """No journal file created when COMMANDER returns no entries."""
    ctrl, provider = _squad_controller(tmp_path)
    provider.exec_agent.return_value = SquadAgentResult(
        exit_code=0,
        echelon_result={"verdict": "DONE", "state_updates": {}, "journal_entries": []},
        raw_output="",
        duration_ms=0,
        timed_out=False,
    )
    ctrl._judgment_dispatch("test reason", _node())
    assert not (tmp_path / "squad" / "run-test" / "reasoning-journal.jsonl").exists()


def test_judgment_dispatch_continues_id_sequence_after_executor_writes(tmp_path):
    """IDs from judgment dispatch continue after phase executor writes."""
    # Use the same squad dir that SquadController uses (squad/run-test)
    shared_squad_dir = tmp_path / "squad" / "run-test"
    shared_squad_dir.mkdir(parents=True, exist_ok=True)
    ex = _executor(tmp_path, squad_dir=shared_squad_dir)
    ex._write_journal_entries(_result(entries=[{"type": "insight"}]), "phase1-a")

    ctrl, provider = _squad_controller(tmp_path)
    provider.exec_agent.return_value = SquadAgentResult(
        exit_code=0,
        echelon_result={
            "verdict": "BLOCKED",
            "state_updates": {},
            "journal_entries": [{"type": "escalation"}],
        },
        raw_output="",
        duration_ms=0,
        timed_out=False,
    )
    ctrl._judgment_dispatch("reason", _node("phase1-b"))
    entries = _read_journal(tmp_path, squad_dir=shared_squad_dir)
    assert len(entries) == 2
    assert entries[0]["id"] == 1
    assert entries[1]["id"] == 2


# ── Structural: no direct >> reasoning-journal.jsonl appends in spec files ───

_DIRECT_APPEND_RE = re.compile(r">>\s*.*reasoning-journal\.jsonl")
_PHASES_DIR = EXT_ROOT / "extension/workflow/phases"


def test_no_direct_journal_appends_in_phase_specs():
    """Phase spec files must use journal-append.sh, never direct >> appends.

    Direct appends bypass ID assignment and schema validation.
    """
    violations = []
    for md_file in _PHASES_DIR.glob("*.md"):
        for lineno, line in enumerate(md_file.read_text().splitlines(), start=1):
            if _DIRECT_APPEND_RE.search(line):
                violations.append(f"{md_file.name}:{lineno}: {line.strip()}")

    assert not violations, (
        "Direct >> reasoning-journal.jsonl appends found in phase specs "
        "(use journal-append.sh instead):\n" + "\n".join(violations)
    )


def test_journal_written_to_squad_dir(tmp_path):
    """Journal entries go to squad_dir/reasoning-journal.jsonl, not .specify/squad."""
    squad_dir = tmp_path / "squad" / "run-test"
    squad_dir.mkdir(parents=True)
    ex = _executor(tmp_path, squad_dir=squad_dir)
    ex._write_journal_entries(_result(entries=[{"type": "insight"}]), "phase1-a")
    journal = squad_dir / "reasoning-journal.jsonl"
    assert journal.exists()
    assert not (tmp_path / ".specify/squad/reasoning-journal.jsonl").exists()


def test_assemble_prompt_injects_squad_context(tmp_path):
    """_assemble_prompt prepends SQUAD_DIR and STAGING_DIR to the prompt."""
    squad_dir = tmp_path / "squad" / "run-test"
    squad_dir.mkdir(parents=True)
    (squad_dir / "staging").mkdir()
    ex = _executor(tmp_path, squad_dir=squad_dir)
    from harness.phase_graph import PhaseNode
    node = PhaseNode(id="init", type="agent")
    state = {"squad_dir": str(squad_dir), "staging_dir": str(squad_dir / "staging")}
    prompt = ex._assemble_prompt(node, state)
    assert str(squad_dir) in prompt
    assert "STAGING_DIR" in prompt


def test_assemble_prompt_injects_shared_endocrine_contract(tmp_path):
    """Agent prompts include the shared endocrine contract before role text."""
    squad_dir = tmp_path / "squad" / "run-test"
    squad_dir.mkdir(parents=True)
    ext_dir = tmp_path / "ext"
    agent_dir = ext_dir / "agents"
    agent_dir.mkdir(parents=True)
    (agent_dir / "scout.md").write_text("# Scout\nRole-specific instructions.")

    from harness.phase_graph import PhaseNode
    provider = MagicMock()
    graph = MagicMock()
    graph.agent_file.return_value = "agents/scout.md"
    graph.all_phase_ids.return_value = []
    ex = AgentExecutor(provider, graph, ext_dir, tmp_path, squad_dir)

    node = PhaseNode(id="phase1-test", type="agent", agent="SCOUT")
    state = {"squad_dir": str(squad_dir), "staging_dir": str(squad_dir / "staging")}
    prompt = ex._assemble_prompt(node, state)

    assert "## Shared Agent Contract" in prompt
    assert "ALWAYS read any `[ENDOCRINE]` block" in prompt
    assert "NEVER ignore endocrine state" in prompt
    assert "ALWAYS end your response with an `echelon_result` block" in prompt
    assert "NEVER write to `reasoning-journal.jsonl` directly" in prompt
    assert prompt.index("## Shared Agent Contract") < prompt.index("# Scout")


def test_staged_prompt_injects_shared_endocrine_contract(tmp_path):
    """Staged parallel prompts receive the same shared endocrine contract."""
    squad_dir = tmp_path / "squad" / "run-test"
    squad_dir.mkdir(parents=True)
    ext_dir = tmp_path / "ext"
    agent_dir = ext_dir / "agents"
    agent_dir.mkdir(parents=True)
    (agent_dir / "why3.md").write_text("# WHY3\nRole-specific instructions.")

    provider = MagicMock()
    graph = MagicMock()
    graph.agent_file.return_value = "agents/why3.md"
    graph.all_phase_ids.return_value = []
    ex = StagedParallelExecutor(provider, graph, ext_dir, tmp_path, squad_dir)

    state = {"squad_dir": str(squad_dir), "staging_dir": str(squad_dir / "staging")}
    prompt = ex._build_agent_prompt({"id": "WHY3", "mode": "WHY3"}, state)

    assert "## Shared Agent Contract" in prompt
    assert "ALWAYS read any `[ENDOCRINE]` block" in prompt
    assert "NEVER ignore endocrine state" in prompt
    assert "ALWAYS end your response with an `echelon_result` block" in prompt
    assert "NEVER write to `reasoning-journal.jsonl` directly" in prompt
    assert prompt.index("## Shared Agent Contract") < prompt.index("# WHY3")


def test_assemble_prompt_translates_legacy_paths(tmp_path):
    """Legacy .specify/squad/staging/ references in spec content are replaced."""
    squad_dir = tmp_path / "squad" / "run-test"
    squad_dir.mkdir(parents=True)
    (squad_dir / "staging").mkdir()
    ext_dir = tmp_path / "ext"
    ext_dir.mkdir()
    spec_dir = ext_dir / "workflow" / "phases"
    spec_dir.mkdir(parents=True)
    (spec_dir / "test.md").write_text("Write outputs to .specify/squad/staging/")
    from harness.phase_graph import PhaseNode
    node = PhaseNode(id="test", type="agent", spec_file="workflow/phases/test.md")
    from harness.squad_executors import AgentExecutor
    from unittest.mock import MagicMock
    provider = MagicMock()
    graph = MagicMock()
    graph.agent_file.return_value = None
    graph.all_phase_ids.return_value = []
    ex = AgentExecutor(provider, graph, ext_dir, tmp_path, squad_dir)
    state = {"squad_dir": str(squad_dir), "staging_dir": str(squad_dir / "staging")}
    prompt = ex._assemble_prompt(node, state)
    assert ".specify/squad/staging/" not in prompt
    assert str(squad_dir / "staging") in prompt


def test_assemble_prompt_injects_state_json_from_squad_dir(tmp_path):
    """state.json is read from squad_dir, not .specify/squad."""
    squad_dir = tmp_path / "squad" / "run-test"
    squad_dir.mkdir(parents=True)
    (squad_dir / "staging").mkdir()
    # Write a state.json in squad_dir
    (squad_dir / "state.json").write_text(json.dumps({"phase": "phase1-test", "squad_dir": str(squad_dir)}))
    # Also write a different state.json in the legacy location to verify it's NOT read
    legacy_dir = tmp_path / ".specify" / "squad"
    legacy_dir.mkdir(parents=True)
    (legacy_dir / "state.json").write_text(json.dumps({"phase": "phase1-legacy"}))
    ex = _executor(tmp_path, squad_dir=squad_dir)
    from harness.phase_graph import PhaseNode
    node = PhaseNode(id="init", type="agent")
    state = {"squad_dir": str(squad_dir), "staging_dir": str(squad_dir / "staging")}
    prompt = ex._assemble_prompt(node, state)
    assert "phase1-test" in prompt
    assert "phase1-legacy" not in prompt
