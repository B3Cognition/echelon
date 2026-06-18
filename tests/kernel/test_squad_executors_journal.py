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
from harness.squad_state import SquadStateStore


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


def test_judgment_dispatch_replaces_null_journal_metadata(tmp_path):
    """COMMANDER/SAGE placeholders like id: null must not persist to JSONL."""
    ctrl, provider = _squad_controller(tmp_path)
    provider.exec_agent.return_value = SquadAgentResult(
        exit_code=0,
        echelon_result={
            "verdict": "BLOCKED",
            "state_updates": {},
            "journal_entries": [
                {
                    "id": None,
                    "timestamp": None,
                    "phase": None,
                    "type": "quality_check",
                }
            ],
        },
        raw_output="",
        duration_ms=0,
        timed_out=False,
    )
    ctrl._judgment_dispatch("test reason", _node("phase1-why2"))
    entries = _read_journal(tmp_path, squad_dir=tmp_path / "squad" / "run-test")
    assert entries[0]["id"] == 1
    assert entries[0]["timestamp"] is not None
    assert entries[0]["phase"] == "phase1-why2"


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
_DIRECT_JOURNAL_INSTRUCTION_RE = re.compile(
    r"\bAppend entries to `reasoning-journal\.jsonl`"
    r"|\bThen append .* to `reasoning-journal\.jsonl`"
)
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


def test_phase_specs_do_not_instruct_agents_to_append_to_journal():
    """Agents should return journal_entries; the harness writes the JSONL file."""
    violations = []
    for md_file in _PHASES_DIR.glob("*.md"):
        for lineno, line in enumerate(md_file.read_text().splitlines(), start=1):
            if _DIRECT_JOURNAL_INSTRUCTION_RE.search(line):
                violations.append(f"{md_file.name}:{lineno}: {line.strip()}")

    assert not violations, (
        "Phase specs must instruct agents to return echelon_result.journal_entries, "
        "not append directly to reasoning-journal.jsonl:\n" + "\n".join(violations)
    )


def test_agent_output_blocks_do_not_request_null_journal_metadata():
    """Harness owns journal IDs/timestamps; agent examples should not show nulls."""
    violations = []
    for md_file in (EXT_ROOT / "extension" / "agents").rglob("*.md"):
        text = md_file.read_text(encoding="utf-8")
        for marker in ("id: null", "timestamp: null"):
            if marker in text:
                violations.append(f"{md_file.relative_to(EXT_ROOT)} contains {marker!r}")

    assert not violations, (
        "Agent output blocks must omit journal id/timestamp metadata because "
        "the harness fills them:\n" + "\n".join(violations)
    )


def test_agent_output_blocks_do_not_put_list_directly_under_echelon_result():
    """Examples must name journal_entries/output_files instead of raw YAML lists."""
    pattern = re.compile(r"^echelon_result:\n\s+-\s+", re.M)
    violations = []
    for md_file in (EXT_ROOT / "extension" / "agents").rglob("*.md"):
        if pattern.search(md_file.read_text(encoding="utf-8")):
            violations.append(str(md_file.relative_to(EXT_ROOT)))

    assert not violations, (
        "Agent examples must not place a list directly under echelon_result:\n"
        + "\n".join(violations)
    )


def test_why2_routing_contract_uses_full_quality_score_shape():
    from harness.phase_graph import PhaseNode
    from harness.squad_executors import _routing_contract

    node = PhaseNode(
        id="phase1-why2",
        type="agent",
        transitions=[{"condition": "quality_gates.fail", "to": "phase1-what"}],
    )
    contract = _routing_contract(node)

    assert "quality_scores:" in contract
    assert "[{pass: true}]" not in contract
    assert 'pass: "WHY2-iter-{N}"' in contract
    assert "overall:" in contract


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
    assert "ALWAYS read your agent-specific belief register when present" in prompt
    assert "belief-registers/<agent-slug>.yaml" in prompt
    assert prompt.index("## Shared Agent Contract") < prompt.index("# Scout")
    assert prompt.index("# Scout") < prompt.index("# Squad Run Context")


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
    assert "ALWAYS read your agent-specific belief register when present" in prompt
    assert "belief-registers/<agent-slug>.yaml" in prompt
    assert prompt.index("## Shared Agent Contract") < prompt.index("# WHY3")
    assert prompt.index("# WHY3") < prompt.index("# Squad Run Context")


def test_staged_prompt_uses_state_spec_dir_before_other_specs(tmp_path):
    """Consensus context must not pull bare artifact names from older specs/* dirs."""
    squad_dir = tmp_path / "squad" / "run-test"
    staging_dir = squad_dir / "staging"
    staging_dir.mkdir(parents=True)
    ext_dir = tmp_path / "ext"
    agent_dir = ext_dir / "agents"
    agent_dir.mkdir(parents=True)
    (agent_dir / "why3.md").write_text("# WHY3\nRole-specific instructions.")

    stale_spec = tmp_path / "specs" / "016-old"
    stale_spec.mkdir(parents=True)
    (stale_spec / "spec.md").write_text("WRONG SPEC 016")

    stale_plan = tmp_path / "specs" / "063-pvas"
    stale_plan.mkdir(parents=True)
    (stale_plan / "tasks.md").write_text("WRONG TASKS 063")

    active_spec = tmp_path / "specs" / "071-rule-studio"
    active_spec.mkdir(parents=True)
    (active_spec / "spec.md").write_text("RIGHT SPEC 071")
    (active_spec / "tasks.md").write_text("RIGHT TASKS 071")
    (staging_dir / "implementability-report.md").write_text("RIGHT STAGING REPORT")

    provider = MagicMock()
    graph = MagicMock()
    graph.agent_file.return_value = "agents/why3.md"
    graph.all_phase_ids.return_value = []
    ex = StagedParallelExecutor(provider, graph, ext_dir, tmp_path, squad_dir)

    state = {
        "squad_dir": str(squad_dir),
        "staging_dir": str(staging_dir),
        "spec_dir": "specs/071-rule-studio",
    }
    prompt = ex._build_agent_prompt(
        {
            "id": "WHY3",
            "mode": "WHY3",
            "context_pack": ["spec.md", "tasks.md", "implementability-report.md"],
        },
        state,
    )

    assert "RIGHT SPEC 071" in prompt
    assert "RIGHT TASKS 071" in prompt
    assert "RIGHT STAGING REPORT" in prompt
    assert "WRONG SPEC 016" not in prompt
    assert "WRONG TASKS 063" not in prompt


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


def test_assemble_prompt_prefers_project_spec_dir_over_poisoned_run_relative_spec_dir(tmp_path):
    """A bad state.spec_dir under runs/.../specs/... must resolve back to PROJECT_ROOT/specs/..."""
    squad_dir = tmp_path / "runs" / "spec-20260618-123456"
    staging_dir = squad_dir / "staging"
    staging_dir.mkdir(parents=True)
    real_spec = tmp_path / "specs" / "006-element-creator"
    real_spec.mkdir(parents=True)
    (real_spec / "spec.md").write_text("REAL SPEC", encoding="utf-8")
    # Poisoned path mirrors the bug seen in the SENTINEL run.
    poisoned = squad_dir / "specs" / "006-element-creator"
    poisoned.mkdir(parents=True)
    (poisoned / "spec.md").write_text("WRONG RUN SPEC", encoding="utf-8")

    ext_dir = tmp_path / "ext"
    agent_dir = ext_dir / "agents"
    agent_dir.mkdir(parents=True)
    (agent_dir / "sentinel.md").write_text("# Sentinel\nRole-specific instructions.")

    from harness.phase_graph import PhaseNode
    provider = MagicMock()
    graph = MagicMock()
    graph.agent_file.return_value = "agents/sentinel.md"
    graph.all_phase_ids.return_value = []
    ex = AgentExecutor(provider, graph, ext_dir, tmp_path, squad_dir)

    node = PhaseNode(
        id="phase3-sentinel",
        type="agent",
        agent="SENTINEL",
        context_pack=["{spec_dir}/spec.md"],
    )
    state = {
        "squad_dir": str(squad_dir),
        "staging_dir": str(staging_dir),
        "spec_dir": str(poisoned.relative_to(tmp_path)),
    }

    prompt = ex._assemble_prompt(node, state)

    assert "REAL SPEC" in prompt
    assert "WRONG RUN SPEC" not in prompt


def test_staged_prompt_prefers_project_spec_dir_over_poisoned_run_relative_spec_dir(tmp_path):
    """Staged agent prompts must normalize bad runs/.../specs/... state.spec_dir the same way."""
    squad_dir = tmp_path / "runs" / "spec-20260618-123456"
    staging_dir = squad_dir / "staging"
    staging_dir.mkdir(parents=True)
    real_spec = tmp_path / "specs" / "006-element-creator"
    real_spec.mkdir(parents=True)
    (real_spec / "spec.md").write_text("REAL SPEC", encoding="utf-8")
    poisoned = squad_dir / "specs" / "006-element-creator"
    poisoned.mkdir(parents=True)
    (poisoned / "spec.md").write_text("WRONG RUN SPEC", encoding="utf-8")

    ext_dir = tmp_path / "ext"
    agent_dir = ext_dir / "agents"
    agent_dir.mkdir(parents=True)
    (agent_dir / "why3.md").write_text("# WHY3\nRole-specific instructions.")

    provider = MagicMock()
    graph = MagicMock()
    graph.agent_file.return_value = "agents/why3.md"
    graph.all_phase_ids.return_value = []
    ex = StagedParallelExecutor(provider, graph, ext_dir, tmp_path, squad_dir)

    state = {
        "squad_dir": str(squad_dir),
        "staging_dir": str(staging_dir),
        "spec_dir": str(poisoned.relative_to(tmp_path)),
    }
    prompt = ex._build_agent_prompt(
        {"id": "WHY3", "mode": "WHY3", "context_pack": ["{spec_dir}/spec.md"]},
        state,
    )

    assert "REAL SPEC" in prompt
    assert "WRONG RUN SPEC" not in prompt


def test_agent_prompt_declares_subagent_and_forbids_skill_tool(tmp_path):
    squad_dir = tmp_path / "runs" / "spec-20260618-123456"
    staging_dir = squad_dir / "staging"
    staging_dir.mkdir(parents=True)
    spec_dir = tmp_path / "specs" / "006-element-creator"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text("REAL SPEC", encoding="utf-8")

    ext_dir = tmp_path / "ext"
    agent_dir = ext_dir / "agents"
    agent_dir.mkdir(parents=True)
    (agent_dir / "sentinel.md").write_text("# Sentinel\nRole-specific instructions.")

    from harness.phase_graph import PhaseNode
    provider = MagicMock()
    graph = MagicMock()
    graph.agent_file.return_value = "agents/sentinel.md"
    graph.all_phase_ids.return_value = []
    ex = AgentExecutor(provider, graph, ext_dir, tmp_path, squad_dir)

    node = PhaseNode(
        id="phase3-sentinel",
        type="agent",
        agent="SENTINEL",
        context_pack=["{spec_dir}/spec.md"],
    )
    state = {
        "squad_dir": str(squad_dir),
        "staging_dir": str(staging_dir),
        "spec_dir": "specs/006-element-creator",
    }

    prompt = ex._assemble_prompt(node, state)

    assert "You were dispatched as a subagent to execute a specific task." in prompt
    assert "Do NOT invoke the Skill tool" in prompt


def test_agent_prompt_substitutes_spec_dir_placeholders_in_phase_text(tmp_path):
    squad_dir = tmp_path / "runs" / "spec-20260618-123456"
    staging_dir = squad_dir / "staging"
    staging_dir.mkdir(parents=True)
    spec_dir = tmp_path / "specs" / "006-element-creator"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text("REAL SPEC", encoding="utf-8")

    ext_dir = tmp_path / "ext"
    agent_dir = ext_dir / "agents"
    agent_dir.mkdir(parents=True)
    (agent_dir / "sentinel.md").write_text("# Sentinel\nRole-specific instructions.")
    workflow_dir = ext_dir / "workflow" / "phases"
    workflow_dir.mkdir(parents=True)
    (workflow_dir / "phase3-sentinel.md").write_text(
        "Produce outputs in `{spec_dir}/` and verify `{spec_dir}/test-strategy.md`.",
        encoding="utf-8",
    )

    from harness.phase_graph import PhaseNode
    provider = MagicMock()
    graph = MagicMock()
    graph.agent_file.return_value = "agents/sentinel.md"
    graph.all_phase_ids.return_value = []
    ex = AgentExecutor(provider, graph, ext_dir, tmp_path, squad_dir)

    node = PhaseNode(
        id="phase3-sentinel",
        type="agent",
        agent="SENTINEL",
        spec_file="workflow/phases/phase3-sentinel.md",
        context_pack=["{spec_dir}/spec.md"],
    )
    state = {
        "squad_dir": str(squad_dir),
        "staging_dir": str(staging_dir),
        "spec_dir": "specs/006-element-creator",
    }

    prompt = ex._assemble_prompt(node, state)

    assert "{spec_dir}" not in prompt
    assert "specs/006-element-creator/test-strategy.md" in prompt


def test_phase3_sentinel_blocks_when_required_outputs_missing(tmp_path):
    squad_dir = tmp_path / "runs" / "spec-20260618-123456"
    staging_dir = squad_dir / "staging"
    staging_dir.mkdir(parents=True)
    spec_dir = tmp_path / "specs" / "006-element-creator"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text("# Spec\n", encoding="utf-8")

    ext_dir = tmp_path / "ext"
    agent_dir = ext_dir / "agents"
    agent_dir.mkdir(parents=True)
    (agent_dir / "sentinel.md").write_text("# Sentinel\nRole-specific instructions.")

    from harness.phase_graph import PhaseNode
    provider = MagicMock()
    provider.exec_agent.return_value = SquadAgentResult(
        exit_code=0,
        echelon_result={"verdict": "DONE", "state_updates": {}},
        raw_output="",
        duration_ms=0,
        timed_out=False,
    )
    graph = MagicMock()
    graph.agent_file.return_value = "agents/sentinel.md"
    graph.all_phase_ids.return_value = []
    ex = AgentExecutor(provider, graph, ext_dir, tmp_path, squad_dir)
    store = SquadStateStore(squad_dir)
    store.initialize("r", "greenfield", "msg", 0, "phase3-sentinel")
    state = store.load()
    state["spec_dir"] = "specs/006-element-creator"
    store.save(state)

    node = PhaseNode(
        id="phase3-sentinel",
        type="agent",
        agent="SENTINEL",
    )

    result = ex.execute(node, store)

    assert result.verdict == "BLOCKED"
    assert result.state_updates["blocked_reason"] == "missing_phase_outputs"
    assert result.state_updates["missing_outputs"] == [
        "test-strategy.md",
        "test-architecture.md",
        "coverage-map.md",
    ]


def test_phase3_plan_blocks_when_required_outputs_missing(tmp_path):
    squad_dir = tmp_path / "runs" / "spec-20260618-123456"
    staging_dir = squad_dir / "staging"
    staging_dir.mkdir(parents=True)
    spec_dir = tmp_path / "specs" / "006-element-creator"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text("# Spec\n", encoding="utf-8")
    (spec_dir / "test-strategy.md").write_text("# Test Strategy\n", encoding="utf-8")

    ext_dir = tmp_path / "ext"
    agent_dir = ext_dir / "agents"
    agent_dir.mkdir(parents=True)
    (agent_dir / "orchestrator.md").write_text("# Orchestrator\nRole-specific instructions.")

    from harness.phase_graph import PhaseNode
    provider = MagicMock()
    provider.exec_agent.return_value = SquadAgentResult(
        exit_code=0,
        echelon_result={"verdict": "DONE", "state_updates": {}},
        raw_output="",
        duration_ms=0,
        timed_out=False,
    )
    graph = MagicMock()
    graph.agent_file.return_value = "agents/orchestrator.md"
    graph.all_phase_ids.return_value = []
    ex = AgentExecutor(provider, graph, ext_dir, tmp_path, squad_dir)
    store = SquadStateStore(squad_dir)
    store.initialize("r", "greenfield", "msg", 0, "phase3-plan")
    state = store.load()
    state["spec_dir"] = "specs/006-element-creator"
    store.save(state)

    node = PhaseNode(
        id="phase3-plan",
        type="agent",
        agent="ORCHESTRATOR",
    )

    result = ex.execute(node, store)

    assert result.verdict == "BLOCKED"
    assert result.state_updates["blocked_reason"] == "missing_phase_outputs"
    assert result.state_updates["missing_outputs"] == [
        "tasks.md",
        "critical-path.md",
        "risk-matrix.md",
        "dependencies.md",
    ]


def test_phase3_sentinel_recovers_outputs_from_run_local_shadow_spec_dir(tmp_path):
    squad_dir = tmp_path / "runs" / "spec-20260618-123456"
    staging_dir = squad_dir / "staging"
    staging_dir.mkdir(parents=True)
    spec_dir = tmp_path / "specs" / "006-element-creator"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text("# Spec\n", encoding="utf-8")

    shadow_spec_dir = squad_dir / "specs" / "006-element-creator"
    shadow_spec_dir.mkdir(parents=True)
    (shadow_spec_dir / "test-strategy.md").write_text("# Test Strategy\n", encoding="utf-8")
    (shadow_spec_dir / "test-architecture.md").write_text("# Test Architecture\n", encoding="utf-8")
    (shadow_spec_dir / "coverage-map.md").write_text("# Coverage Map\n", encoding="utf-8")

    ext_dir = tmp_path / "ext"
    agent_dir = ext_dir / "agents"
    agent_dir.mkdir(parents=True)
    (agent_dir / "sentinel.md").write_text("# Sentinel\nRole-specific instructions.")

    from harness.phase_graph import PhaseNode
    provider = MagicMock()
    provider.exec_agent.return_value = SquadAgentResult(
        exit_code=0,
        echelon_result={
            "verdict": "COMPLETE",
            "state_updates": {},
            "output_files": [
                "specs/006-element-creator/test-strategy.md",
                "specs/006-element-creator/test-architecture.md",
                "specs/006-element-creator/coverage-map.md",
            ],
        },
        raw_output="",
        duration_ms=0,
        timed_out=False,
    )
    graph = MagicMock()
    graph.agent_file.return_value = "agents/sentinel.md"
    graph.all_phase_ids.return_value = []
    ex = AgentExecutor(provider, graph, ext_dir, tmp_path, squad_dir)
    store = SquadStateStore(squad_dir)
    store.initialize("r", "greenfield", "msg", 0, "phase3-sentinel")
    state = store.load()
    state["spec_dir"] = "specs/006-element-creator"
    store.save(state)

    node = PhaseNode(
        id="phase3-sentinel",
        type="agent",
        agent="SENTINEL",
    )

    result = ex.execute(node, store)

    assert result.verdict == "COMPLETE"
    assert (spec_dir / "test-strategy.md").exists()
    assert (spec_dir / "test-architecture.md").exists()
    assert (spec_dir / "coverage-map.md").exists()
    assert result.state_updates["shadow_output_recovered"] == [
        "test-strategy.md",
        "test-architecture.md",
        "coverage-map.md",
    ]


def test_phase3_sentinel_does_not_recover_shadow_outputs_without_explicit_output_claims(tmp_path):
    squad_dir = tmp_path / "runs" / "spec-20260618-123456"
    staging_dir = squad_dir / "staging"
    staging_dir.mkdir(parents=True)
    spec_dir = tmp_path / "specs" / "006-element-creator"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text("# Spec\n", encoding="utf-8")

    shadow_spec_dir = squad_dir / "specs" / "006-element-creator"
    shadow_spec_dir.mkdir(parents=True)
    (shadow_spec_dir / "test-strategy.md").write_text("# Test Strategy\n", encoding="utf-8")
    (shadow_spec_dir / "test-architecture.md").write_text("# Test Architecture\n", encoding="utf-8")
    (shadow_spec_dir / "coverage-map.md").write_text("# Coverage Map\n", encoding="utf-8")

    ext_dir = tmp_path / "ext"
    agent_dir = ext_dir / "agents"
    agent_dir.mkdir(parents=True)
    (agent_dir / "sentinel.md").write_text("# Sentinel\nRole-specific instructions.")

    from harness.phase_graph import PhaseNode
    provider = MagicMock()
    provider.exec_agent.return_value = SquadAgentResult(
        exit_code=0,
        echelon_result={
            "verdict": "COMPLETE",
            "state_updates": {},
        },
        raw_output="",
        duration_ms=0,
        timed_out=False,
    )
    graph = MagicMock()
    graph.agent_file.return_value = "agents/sentinel.md"
    graph.all_phase_ids.return_value = []
    ex = AgentExecutor(provider, graph, ext_dir, tmp_path, squad_dir)
    store = SquadStateStore(squad_dir)
    store.initialize("r", "greenfield", "msg", 0, "phase3-sentinel")
    state = store.load()
    state["spec_dir"] = "specs/006-element-creator"
    store.save(state)

    node = PhaseNode(
        id="phase3-sentinel",
        type="agent",
        agent="SENTINEL",
    )

    result = ex.execute(node, store)

    assert result.verdict == "BLOCKED"
    assert result.state_updates["blocked_reason"] == "missing_phase_outputs"
    assert not (spec_dir / "test-strategy.md").exists()
