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
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

EXT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(EXT_ROOT) not in sys.path:
    sys.path.insert(0, str(EXT_ROOT))

from harness.controller_state_contracts import ControllerStateContractViolation
from harness.phase_graph import PhaseGraph, PhaseNode
from harness.squad_executors import (
    AgentExecutor,
    ConditionalSequentialExecutor,
    DeterministicLexiconExecutor,
    StagedParallelExecutor,
    _MANDATORY_PHASE_OUTPUTS,
    _canonical_echelon_result_contract,
    _allowed_state_updates_contract,
    _validate_evidence_inventory,
)
from harness.squad_provider import SquadAgentResult
from harness.squad_state import SquadStateStore
from harness.spec_lexicon_gate import SpecLexiconGateResult
from harness.tasks_lexicon_gate import TasksLexiconGateResult


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


def test_phase1_investigate_requires_evidence_artifacts() -> None:
    assert _MANDATORY_PHASE_OUTPUTS["phase1-investigate"] == (
        "evidence-resolution.md",
        "evidence-grades.md",
        "evidence-inventory.json",
    )


def test_evidence_inventory_requires_source_dispositions_and_a_frontier(tmp_path) -> None:
    valid = tmp_path / "evidence-inventory.json"
    valid.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "sources": [
                    {
                        "id": "SRC-001",
                        "locator": "https://example.test/docs",
                        "kind": "documentation_portal",
                        "status": "expanded",
                        "disposition": "included",
                        "discovered_from": "declared_input",
                        "discovery_method": "manifest",
                    }
                ],
                "frontier": {
                    "disposition": "complete",
                    "expanded_seed_locators": ["https://example.test/docs"],
                    "unvisited_relevant_sources": [],
                },
            }
        ),
        encoding="utf-8",
    )
    invalid = tmp_path / "invalid-evidence-inventory.json"
    invalid.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "sources": [
                    {
                        "id": "SRC-001",
                        "locator": "https://example.test/docs",
                        "kind": "documentation_portal",
                        "status": "expanded",
                        "disposition": "included",
                        "discovered_from": "declared_input",
                        "discovery_method": "manifest",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    assert _validate_evidence_inventory(valid) is None
    assert _validate_evidence_inventory(invalid) == "missing required object: frontier"


def test_evidence_inventory_requires_every_declared_url_seed(tmp_path) -> None:
    inventory = tmp_path / "evidence-inventory.json"
    inventory.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "sources": [
                    {
                        "id": "SRC-001",
                        "locator": "https://example.test/linked-schema.json",
                        "kind": "api_schema",
                        "status": "retrieved",
                        "disposition": "included",
                        "discovered_from": "SRC-000",
                        "discovery_method": "link",
                    }
                ],
                "frontier": {
                    "disposition": "complete",
                    "expanded_seed_locators": [
                        "https://example.test/linked-schema.json"
                    ],
                    "unvisited_relevant_sources": [],
                },
            }
        ),
        encoding="utf-8",
    )

    assert _validate_evidence_inventory(
        inventory, required_seed_locators=("https://example.test/portal",)
    ) == "missing declared source seed(s): https://example.test/portal"


def test_invalid_inventory_is_quarantined_before_investigator_retry(tmp_path) -> None:
    squad_dir = tmp_path / "runs" / "run-test"
    squad_dir.mkdir(parents=True)
    spec_dir = tmp_path / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    inventory = spec_dir / "evidence-inventory.json"
    inventory.write_text('{"stale": true}\n', encoding="utf-8")
    executor = _executor(tmp_path, squad_dir=squad_dir)
    store = SquadStateStore(squad_dir)
    store.initialize("r", "greenfield", "msg", 0, "phase1-investigate")
    state = store.load()
    state.update(
        {
            "spec_dir": "specs/001-demo",
            "phase_output_recovery": {
                "phase": "phase1-investigate",
                "invalid_outputs": [{
                    "path": "evidence-inventory.json",
                    "reason": "missing declared source seed",
                }],
            },
        }
    )
    store.save(state)

    from harness.phase_graph import PhaseNode

    executor._quarantine_invalid_recovery_outputs(
        PhaseNode(id="phase1-investigate", type="agent"), store.load(), store
    )

    assert not inventory.exists()
    assert (spec_dir / "evidence-inventory.invalid.json").exists()
    assert store.load()["phase_output_recovery"]["quarantined_invalid_outputs"] == [
        "evidence-inventory.invalid.json"
    ]


def test_invalid_inventory_repair_excludes_stale_investigation_context(tmp_path) -> None:
    squad_dir = tmp_path / "runs" / "run-test"
    squad_dir.mkdir(parents=True)
    spec_dir = tmp_path / "specs" / "001-demo"
    investigation_dir = spec_dir / "investigation"
    investigation_dir.mkdir(parents=True)
    (spec_dir / "evidence-resolution.md").write_text("STALE EVIDENCE\n", encoding="utf-8")
    (investigation_dir / "old.md").write_text("STALE INVESTIGATION\n", encoding="utf-8")
    (spec_dir / "evidence-inventory.json").write_text("{\"stale\": true}\n", encoding="utf-8")
    executor = _executor(tmp_path, squad_dir=squad_dir)
    from harness.phase_graph import PhaseNode

    node = PhaseNode(
        id="phase1-investigate",
        type="agent",
        context_pack=[
            "{spec_dir}/evidence-resolution.md",
            "{spec_dir}/investigation/",
            "{spec_dir}/evidence-inventory.json",
            ".specify/squad/reasoning-journal.jsonl [phase=phase1-why2]",
        ],
    )
    prompt = executor._assemble_prompt(
        node,
        {
            "squad_dir": str(squad_dir),
            "staging_dir": str(squad_dir / "staging"),
            "spec_dir": "specs/001-demo",
            "phase_output_recovery": {
                "phase": "phase1-investigate",
                "invalid_outputs": [{
                    "path": "evidence-inventory.json",
                    "reason": "missing declared seed",
                }],
            },
        },
    )

    assert "STALE EVIDENCE" not in prompt
    assert "STALE INVESTIGATION" not in prompt
    assert "Use tools to inspect the declared inputs" in prompt


def test_phase1_investigate_preserves_valid_evidence_result_when_grade_artifact_is_missing(tmp_path):
    squad_dir = tmp_path / "runs" / "spec-20260724-123456"
    squad_dir.mkdir(parents=True)
    spec_dir = tmp_path / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    (spec_dir / "evidence-resolution.md").write_text("# Evidence\n", encoding="utf-8")

    ext_dir = tmp_path / "ext"
    agent_dir = ext_dir / "agents"
    agent_dir.mkdir(parents=True)
    (agent_dir / "investigator.md").write_text("# Investigator\n", encoding="utf-8")
    provider = MagicMock()
    provider.exec_agent.return_value = SquadAgentResult(
        exit_code=0,
        echelon_result={
            "verdict": "COMPLETE",
            "state_updates": {"evidence_resolution_status": "conflicting"},
        },
        raw_output="",
        duration_ms=0,
        timed_out=False,
    )
    graph = MagicMock()
    graph.agent_file.return_value = "agents/investigator.md"
    graph.all_phase_ids.return_value = []
    executor = AgentExecutor(provider, graph, ext_dir, tmp_path, squad_dir)
    store = SquadStateStore(squad_dir)
    store.initialize("r", "greenfield", "msg", 0, "phase1-investigate")
    state = store.load()
    state["spec_dir"] = "specs/001-demo"
    store.save(state)

    from harness.phase_graph import PhaseNode

    node = PhaseNode(
        id="phase1-investigate",
        type="agent",
        agent="INVESTIGATOR",
        allowed_state_updates=["evidence_resolution_status"],
        required_state_updates=["evidence_resolution_status"],
        state_update_types={"evidence_resolution_status": "string"},
        state_update_enums={"evidence_resolution_status": ["conflicting"]},
        allowed_verdicts=["COMPLETE"],
    )

    result = executor.execute(node, store)

    assert result.verdict == "BLOCKED"
    assert result.state_updates["missing_outputs"] == [
        "evidence-grades.md",
        "evidence-inventory.json",
    ]
    assert result.state_updates["recovery_state_updates"] == {
        "evidence_resolution_status": "conflicting"
    }


def _journal_entry(entry_type: str = "insight", **overrides) -> dict:
    data_by_type = {
        "insight": {
            "artifact": "spec.md",
            "section": "requirements",
            "reasoning": "test reasoning",
            "confidence": 0.8,
            "evidence_grade": "B",
        },
        "assumption": {
            "artifact": "spec.md",
            "section": "assumptions",
            "reasoning": "test assumption",
            "validation_method": "review",
        },
        "challenge": {
            "artifact": "spec.md",
            "section": "requirements",
            "reasoning": "test challenge",
            "confidence": 0.7,
            "severity": "medium",
            "action_required": "clarify",
        },
        "quality_check": {
            "pass": True,
            "scores": {"structure": 0.8},
            "issues": [],
        },
    }
    entry = {"type": entry_type}
    if entry_type in data_by_type:
        entry["data"] = data_by_type[entry_type]
    entry.update(overrides)
    return entry


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
        _result(entries=[_journal_entry("insight")]),
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
        _result(entries=[_journal_entry("insight"), _journal_entry("assumption")]),
        "phase1-discover",
    )
    entries = _read_journal(tmp_path)
    assert entries[0]["id"] == 1
    assert entries[1]["id"] == 2


def test_second_call_continues_id_sequence(tmp_path):
    ex = _executor(tmp_path)
    ex._write_journal_entries(_result(entries=[_journal_entry("insight")]), "phase1-a")
    ex._write_journal_entries(_result(entries=[_journal_entry("challenge")]), "phase1-b")
    entries = _read_journal(tmp_path)
    assert len(entries) == 2
    assert entries[0]["id"] == 1
    assert entries[1]["id"] == 2


def test_existing_id_not_overwritten(tmp_path):
    ex = _executor(tmp_path)
    ex._write_journal_entries(
        _result(entries=[_journal_entry("insight", id=99)]),
        "phase1-discover",
    )
    entries = _read_journal(tmp_path)
    assert entries[0]["id"] == 99


def test_existing_phase_not_overwritten(tmp_path):
    ex = _executor(tmp_path)
    ex._write_journal_entries(
        _result(entries=[_journal_entry("insight", phase="already-set")]),
        "phase1-discover",
    )
    entries = _read_journal(tmp_path)
    assert entries[0]["phase"] == "already-set"


def test_non_dict_entries_skipped(tmp_path):
    ex = _executor(tmp_path)
    ex._write_journal_entries(
        _result(entries=["not-a-dict", None, _journal_entry("insight")]),
        "phase1-discover",
    )
    entries = _read_journal(tmp_path)
    assert len(entries) == 1
    assert entries[0]["type"] == "insight"


def test_parallel_results_written_serially(tmp_path):
    """Simulate stage-1 parallel agents: journal written after join, ids contiguous."""
    ex = _executor(tmp_path)
    why3_result = _result(entries=[_journal_entry("challenge", agent="why3")])
    assess2_result = _result(entries=[_journal_entry("quality_check", agent="assess2")])
    # Both calls happen after ThreadPoolExecutor join — serial by construction
    ex._write_journal_entries(why3_result, "phase3-consensus")
    ex._write_journal_entries(assess2_result, "phase3-consensus")
    entries = _read_journal(tmp_path)
    assert len(entries) == 2
    assert entries[0]["id"] == 1
    assert entries[1]["id"] == 2
    types = {e["type"] for e in entries}
    assert types == {"challenge", "quality_check"}


def test_invalid_registered_entry_is_quarantined_as_schema_warning(tmp_path):
    ex = _executor(tmp_path)
    ex._write_journal_entries(
        _result(
            entries=[
                {
                    "type": "routing_decision",
                    "data": {
                        "from_phase": "phase1-why1",
                        "to_phase": "phase2-how",
                        "reason": "missing evoi score",
                    },
                }
            ]
        ),
        "phase1-why1",
    )

    entries = _read_journal(tmp_path)
    assert [entry["type"] for entry in entries] == ["schema_warning"]
    assert entries[0]["data"]["violating_entry_type"] == "routing_decision"
    assert entries[0]["data"]["violation_type"] == "missing_required_field"


def test_unknown_entry_type_is_preserved_without_schema_warning(tmp_path):
    ex = _executor(tmp_path)
    ex._write_journal_entries(
        _result(entries=[{"type": "new_future_signal", "data": {"anything": True}}]),
        "phase1-discover",
    )

    entries = _read_journal(tmp_path)
    assert len(entries) == 1
    assert entries[0]["type"] == "new_future_signal"


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


def _commit_blocked_judgment(ctrl, phase_id: str) -> None:
    """Seal and commit one ambiguous route so deferred journals may publish."""
    node = PhaseNode(
        id=phase_id,
        type="agent",
        transitions=[
            {
                "to": "phase1-discover",
                "condition": "unknown.judgment",
            }
        ],
    )
    state = ctrl._state_store.load()
    state["phase"] = phase_id
    ctrl._state_store.save(state)
    snapshot = ctrl._state_store.capture_routing_snapshot(
        expected_phase=phase_id,
    )
    prepared = ctrl._prepare_phase_result(
        node,
        SquadAgentResult(
            exit_code=0,
            echelon_result={"verdict": "DONE", "state_updates": {}},
            raw_output="",
            duration_ms=0,
            timed_out=False,
        ),
        snapshot,
    )
    decision = ctrl._coordinate_transition_routing(
        node,
        prepared,
        snapshot,
    )
    assert ctrl._advance_prepared_result_or_block(node, decision) is not None


def test_judgment_journal_entries_publish_only_after_committed_route(tmp_path):
    """Returned COMMANDER journals are deferred until routing commits."""
    ctrl, provider = _squad_controller(tmp_path)
    provider.exec_agent.return_value = SquadAgentResult(
        exit_code=0,
        echelon_result={
            "verdict": "BLOCKED",
            "state_updates": {
                "status": "blocked",
                "blocked_reason": "test judgment block",
            },
            "journal_entries": [{"type": "escalation", "data": {"reason": "test"}}],
        },
        raw_output="",
        duration_ms=0,
        timed_out=False,
    )
    _commit_blocked_judgment(ctrl, "phase1-discover")
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
            "state_updates": {
                "status": "blocked",
                "blocked_reason": "test judgment block",
            },
            "journal_entries": [
                {
                    "id": None,
                    "timestamp": None,
                    "phase": None,
                    **_journal_entry("quality_check"),
                }
            ],
        },
        raw_output="",
        duration_ms=0,
        timed_out=False,
    )
    _commit_blocked_judgment(ctrl, "phase1-why2")
    entries = _read_journal(tmp_path, squad_dir=tmp_path / "squad" / "run-test")
    assert entries[0]["id"] == 1
    assert entries[0]["timestamp"] is not None
    assert entries[0]["phase"] == "phase1-why2"


def test_judgment_dispatch_empty_entries_writes_nothing(tmp_path):
    """No journal file created when COMMANDER returns no entries."""
    ctrl, provider = _squad_controller(tmp_path)
    provider.exec_agent.return_value = SquadAgentResult(
        exit_code=0,
        echelon_result={
            "verdict": "JUDGMENT_RESOLVED",
            "state_updates": {},
            "journal_entries": [],
        },
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
    ex._write_journal_entries(_result(entries=[_journal_entry("insight")]), "phase1-a")

    ctrl, provider = _squad_controller(tmp_path)
    provider.exec_agent.return_value = SquadAgentResult(
        exit_code=0,
        echelon_result={
            "verdict": "BLOCKED",
            "state_updates": {
                "status": "blocked",
                "blocked_reason": "test judgment block",
            },
            "journal_entries": [{"type": "escalation"}],
        },
        raw_output="",
        duration_ms=0,
        timed_out=False,
    )
    _commit_blocked_judgment(ctrl, "phase1-b")
    entries = _read_journal(tmp_path, squad_dir=shared_squad_dir)
    assert len(entries) == 2
    assert entries[0]["id"] == 1
    assert entries[1]["id"] == 2


def test_commander_judgment_canonicalization_is_read_only(tmp_path):
    ctrl, _provider = _squad_controller(tmp_path)
    result = SquadAgentResult(
        exit_code=0,
        echelon_result={
            "verdict": "JUDGMENT_RESOLVED",
            "state_updates": {
                "next_phase": "phase1-discover",
                "total_tasks": 61,
            },
            "journal_entries": [],
        },
        raw_output="",
        duration_ms=0,
        timed_out=False,
    )

    before = ctrl._state_store.load()
    canonical = ctrl._canonicalize_judgment_result(result)
    ctrl._write_journal_entries(canonical, "phase1-discover")

    state = ctrl._state_store.load()
    assert state == before
    assert canonical.state_updates == {"next_phase": "phase1-discover"}
    assert "total_tasks" not in state
    entries = _read_journal(tmp_path, squad_dir=tmp_path / "squad" / "run-test")
    assert entries[0]["type"] == "state_contract_warning"
    assert entries[0]["data"]["dropped_keys"] == ["total_tasks"]


# ── Structural: no direct >> reasoning-journal.jsonl appends in spec files ───

_DIRECT_APPEND_RE = re.compile(r">>\s*.*reasoning-journal\.jsonl")
_DIRECT_JOURNAL_INSTRUCTION_RE = re.compile(
    r"\bAppend entries to `reasoning-journal\.jsonl`"
    r"|\bThen append .* to `reasoning-journal\.jsonl`"
)
_PHASES_DIR = EXT_ROOT / "extension/workflow/phases"
_AGENTS_DIR = EXT_ROOT / "extension/agents"


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


def test_agent_files_do_not_instruct_direct_reasoning_journal_writes():
    """Agent protocols should route journal data through echelon_result."""
    direct_patterns = re.compile(
        r"\bappend (?:a |the |.*? )?reasoning journal entry\b"
        r"|\bappend .* to the reasoning journal\b"
        r"|\blog .* to the reasoning journal\b"
        r"|\blog .* to your reasoning journal\b"
        r"|\blog in your reasoning journal\b"
        r"|\brecord(?:ed)? in the reasoning journal\b"
        r"|\brecord(?:ed)? .* in reasoning journal\b"
        r"|\brecord(?:ed)? .* in the reasoning journal\b"
        r"|\bflag .* in the reasoning journal\b",
        re.IGNORECASE,
    )
    allowed_patterns = re.compile(
        r"echelon_result|commander .*writes to the reasoning journal|writes to the reasoning journal",
        re.IGNORECASE,
    )
    violations = []
    for md_file in _AGENTS_DIR.rglob("*.md"):
        for lineno, line in enumerate(md_file.read_text().splitlines(), start=1):
            if direct_patterns.search(line) and not allowed_patterns.search(line):
                violations.append(f"{md_file.relative_to(EXT_ROOT)}:{lineno}: {line.strip()}")

    assert not violations, (
        "Agent files must return journal_entries in echelon_result instead of "
        "instructing direct reasoning journal writes:\n" + "\n".join(violations)
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


def test_markdown_prose_does_not_teach_xml_echelon_result_blocks():
    """The canonical output contract is YAML; XML examples train the wrong shape."""
    violations = []
    for md_file in (EXT_ROOT / "extension").rglob("*.md"):
        if "node_modules" in md_file.parts:
            continue
        text = md_file.read_text(encoding="utf-8", errors="ignore")
        if "<echelon_result>" in text or "</echelon_result>" in text:
            violations.append(str(md_file.relative_to(EXT_ROOT)))

    assert not violations, (
        "Markdown prompts must not teach XML-style echelon_result blocks:\n"
        + "\n".join(violations)
    )


def test_production_echelon_result_template_exists_and_is_canonical():
    template = EXT_ROOT / "extension" / "templates" / "echelon-result-template.yaml"

    text = template.read_text(encoding="utf-8")

    assert template.exists()
    assert "echelon_result:" in text
    assert "state_updates:" in text
    assert "journal_entries:" in text
    assert "NEVER emit `<echelon_result>` XML" in text
    assert "```echelon_result" in text


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
    assert "pass: <true|false>" in contract
    assert 'pass_id: "WHY2-iter-{N}"' in contract
    assert 'pass: "WHY2-iter-{N}"' not in contract
    assert "overall:" in contract


def test_spec_lexicon_routing_contract_requires_certificate_fields():
    """Derivation agents do not report fields owned by controller validation."""
    from harness.phase_graph import PhaseGraph
    from harness.squad_executors import _routing_contract

    root = Path(__file__).resolve().parents[2]
    node = PhaseGraph(
        root / "extension/workflow/definition.yaml",
        root / "extension/extension.yml",
    ).get("phase1-lexicon-derive")

    contract = _routing_contract(node)

    assert "lexicon_pass:" not in contract
    assert "lexicon_attempts:" not in contract
    assert "lexicon_findings:" not in contract

    phase_text = (
        Path(__file__).resolve().parents[2]
        / "extension/workflow/phases/phase1-lexicon-derive.md"
    ).read_text()
    assert "do not execute validation" in phase_text.lower()


def test_phase1_lexicon_derive_prompt_injects_resolved_configuration(tmp_path):
    config_dir = tmp_path / ".echelon"
    config_dir.mkdir(parents=True)
    (config_dir / "config.yml").write_text(
        "lexicon_gate:\n"
        "  enabled: true\n"
        "  artifacts:\n"
        "    spec:\n"
        "      enabled: true\n"
        "      type: spec\n"
        "      mode: derived\n",
        encoding="utf-8",
    )
    (config_dir / "local.yml").write_text(
        "lexicon_gate:\n"
        "  glossary_file: domain-glossary.md\n"
        "  max_repair_attempts: 7\n"
        "  artifacts:\n"
        "    spec:\n"
        "      path: controlled-requirements.md\n"
        "      source_ref: product-spec.md\n",
        encoding="utf-8",
    )
    squad_dir = tmp_path / "runs" / "run-test"
    squad_dir.mkdir(parents=True)
    ex = _executor(tmp_path, squad_dir=squad_dir)
    from harness.phase_graph import PhaseNode

    prompt = ex._assemble_prompt(
        PhaseNode(id="phase1-lexicon-derive", type="agent"),
        {
            "squad_dir": str(squad_dir),
            "spec_dir": "runs/run-test/specs/001-demo",
        },
    )

    assert prompt.count("# Controller Configuration") == 1
    assert "<controller_configuration>" in prompt
    assert "enabled: true" in prompt
    assert "artifact_type: spec" in prompt
    assert "mode: derived" in prompt
    assert "artifact_path: controlled-requirements.md" in prompt
    assert "source_path: product-spec.md" in prompt
    assert "glossary_path: domain-glossary.md" in prompt
    assert "max_repair_attempts: 7" in prompt
    assert "Do not discover or override these values" in prompt


def test_phase1_lexicon_derive_prompt_marks_disabled_spec_subgate(tmp_path):
    config_dir = tmp_path / ".echelon"
    config_dir.mkdir(parents=True)
    (config_dir / "config.yml").write_text(
        "lexicon_gate:\n"
        "  enabled: true\n"
        "  artifacts:\n"
        "    spec:\n"
        "      enabled: false\n",
        encoding="utf-8",
    )
    squad_dir = tmp_path / "runs" / "run-test"
    squad_dir.mkdir(parents=True)
    ex = _executor(tmp_path, squad_dir=squad_dir)
    from harness.phase_graph import PhaseNode

    prompt = ex._assemble_prompt(
        PhaseNode(id="phase1-lexicon-derive", type="agent"),
        {
            "squad_dir": str(squad_dir),
            "spec_dir": "runs/run-test/specs/001-demo",
        },
    )

    assert "enabled: false" in prompt
    assert "When disabled, do not create or amend a derived Lexicon artifact." in prompt


def test_phase1_lexicon_derive_prompt_injects_controller_repair_report(tmp_path):
    squad_dir = tmp_path / "runs" / "run-test"
    squad_dir.mkdir(parents=True)
    ex = _executor(tmp_path, squad_dir=squad_dir)
    from harness.phase_graph import PhaseNode

    report = tmp_path / "runs/run-test/specs/001-demo/spec-lexicon-report.json"
    report.parent.mkdir(parents=True)
    report.write_text(
        json.dumps(
            {
                "ok": False,
                "findings": [
                    {
                        "code": "parse-error",
                        "message": "Unexpected token OUTPUT",
                        "line": 12,
                        "span": "OUTPUT",
                    },
                    {
                        "code": "banned-word",
                        "message": "banned word 'robust'",
                        "line": 27,
                        "span": "robust",
                    },
                    {
                        "code": "banned-word",
                        "message": "banned word 'simple'",
                        "line": 42,
                        "span": "simple",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    prompt = ex._assemble_prompt(
        PhaseNode(id="phase1-lexicon-derive", type="agent"),
        {
            "squad_dir": str(squad_dir),
            "spec_dir": "runs/run-test/specs/001-demo",
            "lexicon_evaluation": "failed",
            "lexicon_pass": False,
            "lexicon_attempts": 2,
            "lexicon_report": str(report),
        },
    )

    assert prompt.count("# Spec Lexicon Repair (Controller-Enforced)") == 1
    assert prompt.count(str(report)) == 1
    assert "Attempt: `2`" in prompt
    assert "Validation execution and deterministic verdict reporting are controller-owned." in prompt
    assert "Finding count: `3`" in prompt
    assert "`parse-error`: 1" in prompt
    assert "`banned-word`: 2" in prompt
    assert "line 12" in prompt
    assert "Unexpected token OUTPUT" in prompt
    assert "span `robust`" in prompt
    assert "return `requirements.lexicon.md` in `output_files`" in prompt
    assert "Do not declare specification quality" in prompt
    assert "Do not edit spec.md" in prompt


def test_phase1_what_prompt_does_not_receive_spec_lexicon_repair(tmp_path):
    squad_dir = tmp_path / "runs" / "run-test"
    squad_dir.mkdir(parents=True)
    ex = _executor(tmp_path, squad_dir=squad_dir)
    from harness.phase_graph import PhaseNode

    prompt = ex._assemble_prompt(
        PhaseNode(id="phase1-what", type="agent"),
        {
            "squad_dir": str(squad_dir),
            "spec_dir": "runs/run-test/specs/001-demo",
            "lexicon_evaluation": "failed",
            "lexicon_pass": False,
            "lexicon_report": "/evidence/spec-lexicon-report.json",
        },
    )

    assert "# Controller Configuration" not in prompt
    assert "# Spec Lexicon Repair (Controller-Enforced)" not in prompt


def test_unrelated_phase_does_not_receive_spec_lexicon_configuration(tmp_path):
    squad_dir = tmp_path / "runs" / "run-test"
    squad_dir.mkdir(parents=True)
    ex = _executor(tmp_path, squad_dir=squad_dir)
    from harness.phase_graph import PhaseNode

    prompt = ex._assemble_prompt(
        PhaseNode(id="phase2-how", type="agent"),
        {
            "squad_dir": str(squad_dir),
            "lexicon_evaluation": "failed",
            "lexicon_pass": False,
            "lexicon_report": "/evidence/spec-lexicon-report.json",
        },
    )

    assert "# Controller Configuration" not in prompt
    assert "# Spec Lexicon Repair (Controller-Enforced)" not in prompt


def test_phase1_what_outputs_are_checked_by_the_executor(tmp_path):
    squad_dir = tmp_path / "runs" / "run-test"
    squad_dir.mkdir(parents=True)
    ex = _executor(tmp_path, squad_dir=squad_dir)
    from harness.phase_graph import PhaseNode

    spec_dir = tmp_path / "runs/run-test/specs/001-demo"
    spec_dir.mkdir(parents=True)
    state = {"spec_dir": str(spec_dir.relative_to(tmp_path))}
    node = PhaseNode(id="phase1-what", type="agent")

    assert ex._required_phase_outputs_missing(node, state) == [
        "spec.md",
        "requirements-overview.md",
    ]
    (spec_dir / "spec.md").write_text("# Spec\n", encoding="utf-8")
    (spec_dir / "requirements-overview.md").write_text("# Overview\n", encoding="utf-8")
    assert ex._required_phase_outputs_missing(node, state) == []


def test_phase1_lexicon_derive_checks_only_derived_artifact(tmp_path):
    squad_dir = tmp_path / "runs" / "run-test"
    squad_dir.mkdir(parents=True)
    ex = _executor(tmp_path, squad_dir=squad_dir)
    from harness.phase_graph import PhaseNode

    spec_dir = tmp_path / "runs/run-test/specs/001-demo"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text("# Spec\n", encoding="utf-8")
    state = {"spec_dir": str(spec_dir.relative_to(tmp_path))}
    node = PhaseNode(id="phase1-lexicon-derive", type="agent")

    assert ex._required_phase_outputs_missing(node, state) == [
        "requirements.lexicon.md",
    ]
    (spec_dir / "requirements.lexicon.md").write_text(
        "ARTIFACT: SPEC\n",
        encoding="utf-8",
    )
    assert ex._required_phase_outputs_missing(node, state) == []


def test_allowed_state_updates_contract_renders_empty_allowlist():
    contract = _allowed_state_updates_contract([])

    assert "## Allowed state_updates for this dispatch" in contract
    assert "Allowed keys: none." in contract
    assert "state_updates: {}" in contract


def test_canonical_result_contract_includes_schema_complete_journal_entry_shape(tmp_path):
    contract = _canonical_echelon_result_contract(tmp_path / "missing-ext")

    assert "Registered journal-entry types require `data`" in contract
    assert "data:" in contract
    assert "artifact:" in contract
    assert "reasoning:" in contract


def test_journal_written_to_squad_dir(tmp_path):
    """Journal entries go to squad_dir/reasoning-journal.jsonl, not .specify/squad."""
    squad_dir = tmp_path / "squad" / "run-test"
    squad_dir.mkdir(parents=True)
    ex = _executor(tmp_path, squad_dir=squad_dir)
    ex._write_journal_entries(_result(entries=[_journal_entry("insight")]), "phase1-a")
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


def test_assemble_prompt_injects_resolved_project_quality_gates(tmp_path):
    """SAGE receives project-resolved gates instead of copied prompt literals."""
    config = tmp_path / ".echelon" / "config.yml"
    config.parent.mkdir(parents=True)
    config.write_text(
        "quality_gates:\n"
        "  overall: 0.81\n"
        "  structure: 0.82\n"
        "  testability: 0.83\n"
        "  semantic: 0.64\n",
        encoding="utf-8",
    )
    squad_dir = tmp_path / "runs" / "run-test"
    (squad_dir / "staging").mkdir(parents=True)
    ex = _executor(tmp_path, squad_dir=squad_dir)

    from harness.phase_graph import PhaseNode

    prompt = ex._assemble_prompt(
        PhaseNode(id="phase1-why2", type="agent"),
        {"squad_dir": str(squad_dir), "staging_dir": str(squad_dir / "staging")},
    )

    assert "Resolved Quality Gates" in prompt
    assert "overall: >= 0.81" in prompt
    assert "structure: >= 0.82" in prompt
    assert "testability: >= 0.83" in prompt
    assert "semantic: >= 0.64" in prompt
    assert "Never substitute thresholds copied from agent or phase files" in prompt


def test_why2_prompt_injects_certified_understanding_evidence_once(tmp_path):
    squad_dir = tmp_path / "runs" / "run-test"
    squad_dir.mkdir(parents=True)
    ex = _executor(tmp_path, squad_dir=squad_dir)
    from harness.phase_graph import PhaseNode

    report = squad_dir / "evidence" / "understanding" / "phase1-why2-iter-2.json"
    state = {
        "squad_dir": str(squad_dir),
        "understanding_evidence": {
            "phase": "phase1-why2",
            "iteration": 2,
            "status": "completed",
            "path": str(report),
            "digest": "abc123",
            "pass": False,
            "failing_gates": ["testability", "behavioral"],
            "error": None,
        },
    }

    prompt = ex._assemble_prompt(PhaseNode(id="phase1-why2", type="agent"), state)

    assert prompt.count("# Certified Understanding Evidence") == 1
    assert prompt.count(str(report)) == 1
    assert "Digest: `abc123`" in prompt
    assert "Certified pass: `false`" in prompt
    assert "Failing gates: `testability`, `behavioral`" in prompt


def test_why1_prompt_does_not_receive_understanding_evidence(tmp_path):
    squad_dir = tmp_path / "runs" / "run-test"
    squad_dir.mkdir(parents=True)
    ex = _executor(tmp_path, squad_dir=squad_dir)
    from harness.phase_graph import PhaseNode

    prompt = ex._assemble_prompt(
        PhaseNode(id="phase1-why1", type="agent"),
        {
            "squad_dir": str(squad_dir),
            "understanding_evidence": {
                "phase": "phase1-why2",
                "status": "completed",
                "path": "/evidence/report.json",
            },
        },
    )

    assert "# Certified Understanding Evidence" not in prompt


def test_assemble_prompt_injects_extension_path_resolution(tmp_path):
    """Runtime agents get unambiguous installed-extension path mappings."""
    squad_dir = tmp_path / "squad" / "run-test"
    squad_dir.mkdir(parents=True)
    ext_dir = tmp_path / ".specify" / "extensions" / "echelon"
    ext_dir.mkdir(parents=True)

    from harness.phase_graph import PhaseNode
    provider = MagicMock()
    graph = MagicMock()
    graph.agent_file.return_value = None
    graph.all_phase_ids.return_value = []
    ex = AgentExecutor(provider, graph, ext_dir, tmp_path, squad_dir)

    node = PhaseNode(id="phase1-test", type="agent")
    state = {"squad_dir": str(squad_dir), "staging_dir": str(squad_dir / "staging")}
    prompt = ex._assemble_prompt(node, state)

    assert f"EXTENSION_DIR={ext_dir}" in prompt
    assert f"EXTENSION_TEMPLATES_DIR={ext_dir / 'templates'}" in prompt
    assert "`extension/templates/foo.md` resolves to `${EXTENSION_DIR}/templates/foo.md`" in prompt
    assert "NEVER resolve it as `${EXTENSION_DIR}/extension/templates/foo.md`" in prompt


def test_assemble_prompt_injects_workspace_source_roots(tmp_path):
    """Agents receive explicit source-root boundaries for codebase searches."""
    (tmp_path / ".git").mkdir()
    sources_dir = tmp_path / "sources"
    app = sources_dir / "app"
    docs = sources_dir / "docs"
    app.mkdir(parents=True)
    docs.mkdir(parents=True)
    (app / "package.json").write_text("{}", encoding="utf-8")
    (docs / "pyproject.toml").write_text("[project]\nname = 'docs'\n", encoding="utf-8")

    squad_dir = tmp_path / "squad" / "run-test"
    squad_dir.mkdir(parents=True)
    ex = _executor(tmp_path, squad_dir=squad_dir)

    from harness.phase_graph import PhaseNode

    node = PhaseNode(id="phase3-how", type="agent")
    state = {"squad_dir": str(squad_dir), "staging_dir": str(squad_dir / "staging")}

    prompt = ex._assemble_prompt(node, state)

    assert "## Workspace Source Roots" in prompt
    assert f"WORKSPACE_ROOT={tmp_path}" in prompt
    assert f"SOURCE_ROOT[app]={app}" in prompt
    assert f"SOURCE_ROOT[docs]={docs}" in prompt
    assert "ALWAYS perform source-code reads, searches, edits, and tests inside SOURCE_ROOT paths." in prompt
    assert "NEVER treat PROJECT_ROOT as the source tree unless a SOURCE_ROOT entry points to PROJECT_ROOT." in prompt


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
    assert "NEVER use Write, Edit, Bash redirection" in prompt
    assert "ALWAYS read your agent-specific belief register when present" in prompt
    assert "belief-registers/<agent-slug>.yaml" in prompt
    assert prompt.index("## Shared Agent Contract") < prompt.index("# Scout")
    assert prompt.index("# Scout") < prompt.index("# Squad Run Context")
    assert "## Canonical echelon_result contract — REQUIRED FINAL BLOCK" in prompt
    assert "Registered journal-entry types require `data`" in prompt
    assert "    - type: insight" in prompt
    assert "        evidence_grade: <A|B|C|D|E>" in prompt
    assert "NEVER emit `<echelon_result>` XML" in prompt


def test_assemble_prompt_strips_agent_frontmatter_before_model_prompt(tmp_path):
    """Agent YAML frontmatter is runtime metadata, not prompt text."""
    squad_dir = tmp_path / "squad" / "run-test"
    squad_dir.mkdir(parents=True)
    ext_dir = tmp_path / "ext"
    agent_dir = ext_dir / "agents"
    agent_dir.mkdir(parents=True)
    (agent_dir / "chief.md").write_text(
        "---\n"
        "model: local-qwen\n"
        "tools: [Read, Write]\n"
        "color: blue\n"
        "---\n"
        "# Chief\n"
        "Coordinate Phase A artifacts.\n",
        encoding="utf-8",
    )

    from harness.phase_graph import PhaseNode
    provider = MagicMock()
    graph = MagicMock()
    graph.agent_file.return_value = "agents/chief.md"
    graph.all_phase_ids.return_value = []
    ex = AgentExecutor(provider, graph, ext_dir, tmp_path, squad_dir)

    node = PhaseNode(id="phase1-test", type="agent", agent="CHIEF")
    state = {"squad_dir": str(squad_dir), "staging_dir": str(squad_dir / "staging")}
    prompt = ex._assemble_prompt(node, state)

    assert "# Chief" in prompt
    assert "Coordinate Phase A artifacts." in prompt
    assert "model: local-qwen" not in prompt
    assert "tools: [Read, Write]" not in prompt
    assert "color: blue" not in prompt


def test_pre_dispatch_prompt_strips_agent_frontmatter(tmp_path):
    """Pre-dispatch agents use the same frontmatter/body split."""
    squad_dir = tmp_path / "squad" / "run-test"
    squad_dir.mkdir(parents=True)
    ext_dir = tmp_path / "ext"
    agent_dir = ext_dir / "agents"
    agent_dir.mkdir(parents=True)
    agent_path = agent_dir / "sentinel.md"
    agent_path.write_text(
        "---\n"
        "model: local-sentinel\n"
        "reasoning_effort: high\n"
        "---\n"
        "# Sentinel\n"
        "Check the dispatch boundary.\n",
        encoding="utf-8",
    )

    provider = MagicMock()
    graph = MagicMock()
    graph.all_phase_ids.return_value = []
    ex = AgentExecutor(provider, graph, ext_dir, tmp_path, squad_dir)

    prompt = ex._assemble_pre_dispatch_prompt(
        agent_path,
        {},
        {"squad_dir": str(squad_dir), "staging_dir": str(squad_dir / "staging")},
    )

    assert "# Sentinel" in prompt
    assert "Check the dispatch boundary." in prompt
    assert "model: local-sentinel" not in prompt
    assert "reasoning_effort: high" not in prompt


def test_execute_passes_agent_frontmatter_metadata_to_provider(tmp_path):
    """Parsed frontmatter travels out-of-band to the provider."""
    squad_dir = tmp_path / "squad" / "run-test"
    squad_dir.mkdir(parents=True)
    ext_dir = tmp_path / "ext"
    agent_dir = ext_dir / "agents"
    agent_dir.mkdir(parents=True)
    (agent_dir / "chief.md").write_text(
        "---\n"
        "model: frontmatter-model\n"
        "effort: high\n"
        "---\n"
        "# Chief\n"
        "Coordinate Phase A artifacts.\n",
        encoding="utf-8",
    )

    from harness.phase_graph import PhaseNode
    provider = MagicMock()
    provider.exec_agent.return_value = _result()
    graph = MagicMock()
    graph.agent_file.return_value = "agents/chief.md"
    graph.all_phase_ids.return_value = []
    ex = AgentExecutor(provider, graph, ext_dir, tmp_path, squad_dir)
    store = SquadStateStore(squad_dir)
    store.save({"squad_dir": str(squad_dir), "staging_dir": str(squad_dir / "staging")})

    result = ex.execute(PhaseNode(id="phase1-test", type="agent", agent="CHIEF"), store)

    assert result.exit_code == 0
    provider.exec_agent.assert_called_once()
    assert provider.exec_agent.call_args.kwargs["prompt_metadata"] == {
        "model": "frontmatter-model",
        "effort": "high",
    }


def test_assemble_prompt_uses_echelon_result_template(tmp_path):
    """The canonical final result block is owned by extension/templates."""
    squad_dir = tmp_path / "squad" / "run-test"
    squad_dir.mkdir(parents=True)
    ext_dir = tmp_path / "ext"
    agent_dir = ext_dir / "agents"
    template_dir = ext_dir / "templates"
    agent_dir.mkdir(parents=True)
    template_dir.mkdir(parents=True)
    (agent_dir / "scout.md").write_text("# Scout\nRole-specific instructions.")
    (template_dir / "echelon-result-template.yaml").write_text(
        "CANONICAL_TEMPLATE_MARKER\n"
        "echelon_result:\n"
        "  verdict: <DONE>\n"
        "  state_updates: {}\n"
        "  journal_entries: []\n",
        encoding="utf-8",
    )

    from harness.phase_graph import PhaseNode
    provider = MagicMock()
    graph = MagicMock()
    graph.agent_file.return_value = "agents/scout.md"
    graph.all_phase_ids.return_value = []
    ex = AgentExecutor(provider, graph, ext_dir, tmp_path, squad_dir)

    node = PhaseNode(id="phase1-test", type="agent", agent="SCOUT")
    state = {"squad_dir": str(squad_dir), "staging_dir": str(squad_dir / "staging")}
    prompt = ex._assemble_prompt(node, state)

    assert "CANONICAL_TEMPLATE_MARKER" in prompt
    assert prompt.rstrip().endswith("journal_entries: []")


def test_assemble_prompt_includes_allowed_state_updates(tmp_path):
    squad_dir = tmp_path / "squad" / "run-test"
    squad_dir.mkdir(parents=True)
    ex = _executor(tmp_path, squad_dir=squad_dir)
    from harness.phase_graph import PhaseNode
    node = PhaseNode(
        id="phase1-test",
        type="agent",
        allowed_state_updates=["spec_id", "spec_dir"],
    )
    state = {"squad_dir": str(squad_dir), "staging_dir": str(squad_dir / "staging")}

    prompt = ex._assemble_prompt(node, state)

    assert "## Allowed state_updates for this dispatch" in prompt
    assert "- `spec_id`" in prompt
    assert "- `spec_dir`" in prompt
    assert "Undeclared reporting-only keys are quarantined" in prompt
    assert "Missing or invalid required routing keys block." in prompt
    assert "Put task counts, report summaries, evidence, and diagnostics in journal_entries" in prompt


def test_assemble_prompt_includes_empty_allowed_state_updates(tmp_path):
    squad_dir = tmp_path / "squad" / "run-test"
    squad_dir.mkdir(parents=True)
    ex = _executor(tmp_path, squad_dir=squad_dir)
    from harness.phase_graph import PhaseNode
    node = PhaseNode(id="phase1-test", type="agent", allowed_state_updates=[])
    state = {"squad_dir": str(squad_dir), "staging_dir": str(squad_dir / "staging")}

    prompt = ex._assemble_prompt(node, state)

    assert "Allowed keys: none." in prompt
    assert "state_updates: {}" in prompt


def test_pre_dispatch_prompt_includes_parent_allowed_state_updates(tmp_path):
    squad_dir = tmp_path / "squad" / "run-test"
    squad_dir.mkdir(parents=True)
    agent_path = tmp_path / "guardian.md"
    agent_path.write_text("# GUARDIAN\n")
    ex = _executor(tmp_path, squad_dir=squad_dir)
    state = {"squad_dir": str(squad_dir), "staging_dir": str(squad_dir / "staging")}

    prompt = ex._assemble_pre_dispatch_prompt(
        agent_path,
        {"id": "guardian_init"},
        state,
        ["guardian_status"],
    )

    assert "## Allowed state_updates for this dispatch" in prompt
    assert "- `guardian_status`" in prompt
    assert f"EXTENSION_TEMPLATES_DIR={tmp_path / 'ext' / 'templates'}" in prompt
    assert "NEVER resolve it as `${EXTENSION_DIR}/extension/templates/foo.md`" in prompt


def test_agent_prompt_includes_authoritative_implementation_target_contract(tmp_path):
    from harness.phase_graph import PhaseNode

    squad_dir = tmp_path / "squad" / "run-test"
    squad_dir.mkdir(parents=True)
    ex = _executor(tmp_path, squad_dir=squad_dir)
    node = PhaseNode(id="phase3-plan", type="agent")
    state = {
        "squad_dir": str(squad_dir),
        "staging_dir": str(squad_dir / "staging"),
        "implementation_targets": ["sources/web", "sources/api"],
    }

    prompt = ex._assemble_prompt(node, state)

    assert "## Implementation Target Contract" in prompt
    assert "IMPLEMENTATION_TARGETS:" in prompt
    assert "- sources/web" in prompt
    assert "- sources/api" in prompt
    assert "Only these repositories are writable implementation destinations" in prompt
    assert "Do not infer or add another implementation target" in prompt


def test_pre_dispatch_quarantines_unallowed_state_updates_before_mutation(tmp_path):
    """Pre-dispatch reporting fields never enter the state mutation plane."""
    from harness.phase_graph import PhaseNode

    squad_dir = tmp_path / "squad" / "run-test"
    squad_dir.mkdir(parents=True)
    ext_dir = tmp_path / "ext"
    agent_dir = ext_dir / "agents"
    agent_dir.mkdir(parents=True)
    (agent_dir / "guardian.md").write_text("# GUARDIAN\nPre-dispatch agent.")

    state_store = SquadStateStore(squad_dir)
    state_store.initialize("r", "greenfield", "msg", 0, "phase1-discover")

    provider = MagicMock()
    provider.exec_agent.return_value = SquadAgentResult(
        exit_code=0,
        echelon_result={
            "verdict": "DONE",
            "state_updates": {"unexpected": True},
            "journal_entries": [{"type": "insight"}],
        },
        raw_output="",
        duration_ms=0,
        timed_out=False,
    )
    graph = MagicMock()
    graph.agent_file.return_value = "agents/guardian.md"
    graph.all_phase_ids.return_value = []
    ex = AgentExecutor(provider, graph, ext_dir, tmp_path, squad_dir)
    node = PhaseNode(
        id="phase1-discover",
        type="agent",
        pre_dispatch=[
            {"id": "test_pre_dispatch", "agent": "speckit-echelon-guardian"}
        ],
        allowed_state_updates=["allowed_key"],
    )

    result = ex._run_pre_dispatch(node, state_store.load(), state_store)

    state = state_store.load()
    assert result is None
    assert "unexpected" not in state
    assert not state.get("blocked_reason")
    journal = _read_journal(tmp_path, squad_dir=squad_dir)
    assert journal[0]["type"] == "state_contract_warning"
    assert journal[0]["data"]["dropped_keys"] == ["unexpected"]


def test_agent_execute_quarantines_unallowed_state_updates_before_state_write(tmp_path):
    """Normal agent dispatch retains artifacts/journal without expanding state."""
    from harness.phase_graph import PhaseNode

    squad_dir = tmp_path / "squad" / "run-test"
    squad_dir.mkdir(parents=True)
    state_store = SquadStateStore(squad_dir)
    state_store.initialize(
        run_id="r",
        mode="greenfield",
        user_message="msg",
        token_budget=0,
        entry_phase="phase-test",
    )

    provider = MagicMock()
    provider.exec_agent.return_value = SquadAgentResult(
        exit_code=0,
        echelon_result={
            "verdict": "DONE",
            "state_updates": {"unexpected": True},
            "journal_entries": [{"type": "insight"}],
        },
        raw_output="",
        duration_ms=0,
        timed_out=False,
    )
    ex = _executor(tmp_path, squad_dir=squad_dir)
    ex._provider = provider
    node = PhaseNode(id="phase-test", type="agent", allowed_state_updates=[])

    result = ex.execute(node, state_store)

    assert result.blocked is False
    assert result.state_updates == {}
    assert result.quarantined_state_updates == {"unexpected": True}
    journal = _read_journal(tmp_path, squad_dir=squad_dir)
    assert journal[0]["type"] == "state_contract_warning"


def test_pre_dispatch_applies_allowed_state_updates(tmp_path):
    """Allowed pre-dispatch updates still flow into state."""
    from harness.phase_graph import PhaseNode

    squad_dir = tmp_path / "squad" / "run-test"
    squad_dir.mkdir(parents=True)
    ext_dir = tmp_path / "ext"
    agent_dir = ext_dir / "agents"
    agent_dir.mkdir(parents=True)
    (agent_dir / "guardian.md").write_text("# GUARDIAN\nPre-dispatch agent.")

    state_store = SquadStateStore(squad_dir)
    state_store.initialize("r", "greenfield", "msg", 0, "phase1-discover")

    provider = MagicMock()
    provider.exec_agent.return_value = SquadAgentResult(
        exit_code=0,
        echelon_result={
            "verdict": "DONE",
            "state_updates": {"allowed_key": True},
            "journal_entries": [],
        },
        raw_output="",
        duration_ms=0,
        timed_out=False,
    )
    graph = MagicMock()
    graph.agent_file.return_value = "agents/guardian.md"
    graph.all_phase_ids.return_value = []
    ex = AgentExecutor(provider, graph, ext_dir, tmp_path, squad_dir)
    node = PhaseNode(
        id="phase1-discover",
        type="agent",
        pre_dispatch=[
            {"id": "test_pre_dispatch", "agent": "speckit-echelon-guardian"}
        ],
        allowed_state_updates=["allowed_key"],
    )

    result = ex._run_pre_dispatch(node, state_store.load(), state_store)

    assert result is None
    assert state_store.load()["allowed_key"] is True


def test_pre_dispatch_rejects_allowlisted_transaction_owned_update_before_write(
    tmp_path,
):
    squad_dir = tmp_path / "squad" / "run-test"
    ext_dir = tmp_path / "ext"
    agent_dir = ext_dir / "agents"
    agent_dir.mkdir(parents=True)
    (agent_dir / "guardian.md").write_text("# GUARDIAN\nPre-dispatch agent.")

    state_store = SquadStateStore(squad_dir)
    state_store.initialize("r", "greenfield", "msg", 0, "phase1-discover")
    provider = MagicMock()
    provider.exec_agent.return_value = SquadAgentResult(
        exit_code=0,
        echelon_result={
            "verdict": "DONE",
            "state_updates": {"manual_phase_runs": ["forged"]},
            "journal_entries": [],
        },
        raw_output="",
        duration_ms=0,
        timed_out=False,
    )
    graph = MagicMock()
    graph.agent_file.return_value = "agents/guardian.md"
    graph.all_phase_ids.return_value = []
    executor = AgentExecutor(provider, graph, ext_dir, tmp_path, squad_dir)
    node = PhaseNode(
        id="phase1-discover",
        type="agent",
        pre_dispatch=[{
            "id": "guard",
            "agent": "speckit-echelon-guardian",
            "allowed_state_updates": ["manual_phase_runs"],
        }],
        allowed_state_updates=[],
    )

    with pytest.raises(ControllerStateContractViolation) as raised:
        executor._run_pre_dispatch(node, state_store.load(), state_store)

    assert raised.value.contract == "provider"
    assert raised.value.validator == "ownership"
    assert raised.value.json_path == "$.state_updates.manual_phase_runs"
    assert "manual_phase_runs" not in state_store.load()


def test_pre_dispatch_stop_and_ask_short_circuits_without_state_write(tmp_path):
    squad_dir = tmp_path / "squad" / "run-test"
    ext_dir = tmp_path / "ext"
    agent_dir = ext_dir / "agents"
    agent_dir.mkdir(parents=True)
    (agent_dir / "guardian.md").write_text("# GUARDIAN\nPre-dispatch agent.")

    state_store = SquadStateStore(squad_dir)
    state_store.initialize("r", "greenfield", "msg", 0, "phase1-discover")
    provider = MagicMock()
    provider.exec_agent.return_value = SquadAgentResult(
        exit_code=0,
        echelon_result={
            "verdict": "STOP_AND_ASK",
            "state_updates": {
                "status": "blocked",
                "blocked_reason": "clarification required",
                "escalation_question": "Which target should be used?",
            },
            "journal_entries": [],
        },
        raw_output="",
        duration_ms=0,
        timed_out=False,
    )
    graph = MagicMock()
    graph.agent_file.return_value = "agents/guardian.md"
    graph.all_phase_ids.return_value = []
    executor = AgentExecutor(provider, graph, ext_dir, tmp_path, squad_dir)
    node = PhaseNode(
        id="phase1-discover",
        type="agent",
        pre_dispatch=[{
            "id": "guard",
            "agent": "speckit-echelon-guardian",
            "allowed_state_updates": [
                "status",
                "blocked_reason",
                "escalation_question",
            ],
        }],
        allowed_state_updates=[],
    )

    result = executor._run_pre_dispatch(
        node,
        state_store.load(),
        state_store,
    )

    assert result is not None
    assert result.verdict == "STOP_AND_ASK"
    state = state_store.load()
    assert state["status"] == "running"
    assert "blocked_reason" not in state
    assert "escalation_question" not in state


def test_conditional_nested_rejects_transaction_owned_update_before_write(
    tmp_path,
):
    squad_dir = tmp_path / "squad" / "run-test"
    ext_dir = tmp_path / "ext"
    agent_dir = ext_dir / "agents"
    agent_dir.mkdir(parents=True)
    (agent_dir / "guardian.md").write_text("# GUARDIAN\nNested agent.")
    state_store = SquadStateStore(squad_dir)
    state_store.initialize("r", "greenfield", "msg", 0, "phase-test")
    provider = MagicMock()
    provider.exec_agent.return_value = SquadAgentResult(
        exit_code=0,
        echelon_result={
            "verdict": "DONE",
            "state_updates": {"manual_phase_runs": ["forged"]},
            "journal_entries": [],
        },
        raw_output="",
        duration_ms=0,
        timed_out=False,
    )
    graph = MagicMock()
    graph.agent_file.return_value = "agents/guardian.md"
    graph.all_phase_ids.return_value = []
    executor = ConditionalSequentialExecutor(
        provider,
        graph,
        ext_dir,
        tmp_path,
        squad_dir,
    )
    node = SimpleNamespace(
        id="phase-test",
        agents=[{
            "id": "speckit-echelon-guardian",
            "condition": "always",
            "allowed_state_updates": ["manual_phase_runs"],
        }],
        allowed_state_updates=[],
    )

    with pytest.raises(ControllerStateContractViolation) as raised:
        executor.execute(node, state_store)

    assert raised.value.validator == "ownership"
    assert raised.value.json_path == "$.state_updates.manual_phase_runs"
    assert "manual_phase_runs" not in state_store.load()


def test_staged_nested_rejects_transaction_owned_update_before_write(tmp_path):
    squad_dir = tmp_path / "squad" / "run-test"
    state_store = SquadStateStore(squad_dir)
    state_store.initialize("r", "greenfield", "msg", 0, "phase3-consensus")
    provider = MagicMock()
    provider.exec_agent.return_value = SquadAgentResult(
        exit_code=0,
        echelon_result={
            "verdict": "PASS",
            "state_updates": {"manual_phase_runs": ["forged"]},
            "journal_entries": [],
        },
        raw_output="",
        duration_ms=0,
        timed_out=False,
    )
    graph = MagicMock()
    graph.agent_file.return_value = None
    graph.all_phase_ids.return_value = []
    executor = StagedParallelExecutor(
        provider,
        graph,
        tmp_path / "ext",
        tmp_path,
        squad_dir,
    )
    node = SimpleNamespace(
        id="phase3-consensus",
        agents=[{
            "id": "speckit-echelon-sage",
            "mode": "WHY3",
            "stage": 1,
            "context_pack": [],
            "allowed_state_updates": ["manual_phase_runs"],
        }],
        allowed_state_updates=[],
    )

    with pytest.raises(ControllerStateContractViolation) as raised:
        executor.execute(node, state_store)

    assert raised.value.validator == "ownership"
    assert raised.value.json_path == "$.state_updates.manual_phase_runs"
    assert "manual_phase_runs" not in state_store.load()


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
    assert "NEVER use Write, Edit, Bash redirection" in prompt
    assert "ALWAYS read your agent-specific belief register when present" in prompt
    assert "belief-registers/<agent-slug>.yaml" in prompt
    assert prompt.index("## Shared Agent Contract") < prompt.index("# WHY3")
    assert prompt.index("# WHY3") < prompt.index("# Squad Run Context")
    assert "## Canonical echelon_result contract — REQUIRED FINAL BLOCK" in prompt
    assert "Registered journal-entry types require `data`" in prompt
    assert "    - type: insight" in prompt
    assert "        evidence_grade: <A|B|C|D|E>" in prompt
    assert "NEVER emit `<echelon_result>` XML" in prompt


def test_staged_prompt_uses_echelon_result_template(tmp_path):
    """Staged consensus prompts use the same template-backed final block."""
    squad_dir = tmp_path / "squad" / "run-test"
    squad_dir.mkdir(parents=True)
    ext_dir = tmp_path / "ext"
    agent_dir = ext_dir / "agents"
    template_dir = ext_dir / "templates"
    agent_dir.mkdir(parents=True)
    template_dir.mkdir(parents=True)
    (agent_dir / "why3.md").write_text("# WHY3\nRole-specific instructions.")
    (template_dir / "echelon-result-template.yaml").write_text(
        "STAGED_TEMPLATE_MARKER\n"
        "echelon_result:\n"
        "  verdict: <PASS>\n"
        "  state_updates: {}\n"
        "  journal_entries: []\n",
        encoding="utf-8",
    )

    provider = MagicMock()
    graph = MagicMock()
    graph.agent_file.return_value = "agents/why3.md"
    graph.all_phase_ids.return_value = []
    ex = StagedParallelExecutor(provider, graph, ext_dir, tmp_path, squad_dir)

    state = {"squad_dir": str(squad_dir), "staging_dir": str(squad_dir / "staging")}
    prompt = ex._build_agent_prompt({"id": "WHY3", "mode": "WHY3"}, state)

    assert "STAGED_TEMPLATE_MARKER" in prompt
    assert prompt.rstrip().endswith("journal_entries: []")


def test_staged_prompt_includes_allowed_state_updates(tmp_path):
    """Staged consensus agents see the parent phase state-update allowlist."""
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
    prompt = ex._build_agent_prompt(
        {"id": "WHY3", "mode": "WHY3"},
        state,
        allowed_state_updates=["quality_scores"],
    )

    assert "## Allowed state_updates for this dispatch" in prompt
    assert "- `quality_scores`" in prompt


def test_why3_staged_prompt_injects_certified_understanding_evidence(tmp_path):
    squad_dir = tmp_path / "squad" / "run-test"
    squad_dir.mkdir(parents=True)
    ext_dir = tmp_path / "ext"
    (ext_dir / "agents").mkdir(parents=True)
    (ext_dir / "agents" / "why3.md").write_text("# WHY3\n", encoding="utf-8")
    graph = MagicMock()
    graph.agent_file.return_value = "agents/why3.md"
    ex = StagedParallelExecutor(MagicMock(), graph, ext_dir, tmp_path, squad_dir)
    report = squad_dir / "evidence" / "understanding" / "phase3-consensus-iter-1.json"

    prompt = ex._build_agent_prompt(
        {"id": "speckit-echelon-sage", "mode": "WHY3"},
        {
            "squad_dir": str(squad_dir),
            "understanding_evidence": {
                "phase": "phase3-consensus",
                "iteration": 1,
                "status": "completed",
                "path": str(report),
                "digest": "def456",
                "pass": True,
                "failing_gates": [],
                "error": None,
            },
        },
    )

    assert prompt.count("# Certified Understanding Evidence") == 1
    assert prompt.count(str(report)) == 1
    assert "Certified pass: `true`" in prompt


def test_blocked_validation_result_preserves_original_error(tmp_path):
    """Provider-created BLOCKED wrappers are harness-owned, not phase state writes."""
    ex = _executor(tmp_path)
    node = SimpleNamespace(id="phase3-consensus", allowed_state_updates=["quality_scores"])
    result = SquadAgentResult(
        exit_code=0,
        echelon_result={
            "verdict": "BLOCKED",
            "state_updates": {
                "blocked_reason": "echelon_result validation failed: quality_scores must be a list",
            },
            "journal_entries": [],
        },
        raw_output="",
        duration_ms=0,
        timed_out=False,
    )

    validated = ex._validate_result_state_updates(node, result)

    assert validated.verdict == "BLOCKED"
    assert validated.state_updates["blocked_reason"] == (
        "echelon_result validation failed: quality_scores must be a list"
    )


def test_conditional_sequential_prompt_includes_allowed_state_updates(tmp_path):
    """Conditional sequential dispatches no longer send raw agent text only."""
    squad_dir = tmp_path / "squad" / "run-test"
    ext_dir = tmp_path / "ext"
    agent_dir = ext_dir / "agents"
    agent_dir.mkdir(parents=True)
    (agent_dir / "guardian.md").write_text("# Guardian\nRole-specific instructions.")

    state_store = SquadStateStore(squad_dir)
    state_store.initialize("r", "greenfield", "msg", 0, "phase-test")

    provider = MagicMock()
    provider.exec_agent.return_value = SquadAgentResult(
        exit_code=0,
        echelon_result={
            "verdict": "DONE",
            "state_updates": {"risk_status": "reviewed"},
            "journal_entries": [],
        },
        raw_output="",
        duration_ms=0,
        timed_out=False,
    )
    graph = MagicMock()
    graph.agent_file.return_value = "agents/guardian.md"
    graph.all_phase_ids.return_value = []
    executor = ConditionalSequentialExecutor(provider, graph, ext_dir, tmp_path, squad_dir)
    node = SimpleNamespace(
        id="phase-test",
        agents=[{"id": "speckit-echelon-guardian", "condition": "always"}],
        allowed_state_updates=["risk_status"],
    )

    result = executor.execute(node, state_store)
    prompt = provider.exec_agent.call_args.args[1]

    assert result.verdict == "DONE"
    assert "## Shared Agent Contract" in prompt
    assert "## Allowed state_updates for this dispatch" in prompt
    assert "- `risk_status`" in prompt


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


def test_staged_parallel_quarantines_state_update_outside_allowlist(tmp_path):
    squad_dir = tmp_path / "squad" / "run-test"
    state_store = SquadStateStore(squad_dir)
    state_store.initialize("r", "greenfield", "msg", 0, "phase3-consensus")

    provider = MagicMock()
    provider.exec_agent.return_value = SquadAgentResult(
        exit_code=0,
        echelon_result={
            "verdict": "PASS",
            "state_updates": {"unexpected": True},
            "journal_entries": [],
        },
        raw_output="",
        duration_ms=0,
        timed_out=False,
    )
    graph = MagicMock()
    graph.agent_file.return_value = None
    graph.all_phase_ids.return_value = []
    executor = StagedParallelExecutor(provider, graph, tmp_path / "ext", tmp_path, squad_dir)
    node = SimpleNamespace(
        id="phase3-consensus",
        agents=[
            {
                "id": "speckit-echelon-sage",
                "mode": "WHY3",
                "stage": 1,
                "context_pack": [],
            }
        ],
        allowed_state_updates=[],
    )

    result = executor.execute(node, state_store)

    assert result.verdict == "PASS"
    assert state_store.load()["why3_verdict"] == "PASS"
    assert "unexpected" not in state_store.load()
    entries = _read_journal(tmp_path, squad_dir=squad_dir)
    assert entries[0]["type"] == "state_contract_warning"
    assert entries[0]["data"]["dropped_keys"] == ["unexpected"]


def test_staged_parallel_blocks_plan2_when_implementability_report_is_missing(tmp_path):
    squad_dir = tmp_path / "squad" / "run-test"
    state_store = SquadStateStore(squad_dir)
    state_store.initialize("r", "greenfield", "msg", 0, "phase3-consensus")
    spec_dir = tmp_path / "runs" / "run-test" / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    state = state_store.load()
    state["spec_dir"] = str(spec_dir)
    state_store.save(state)

    provider = MagicMock()
    provider.exec_agent.return_value = SquadAgentResult(
        exit_code=0,
        echelon_result={
            "verdict": "PASS",
            "state_updates": {},
            "journal_entries": [],
        },
        raw_output="",
        duration_ms=0,
        timed_out=False,
    )
    graph = MagicMock()
    graph.agent_file.return_value = None
    graph.all_phase_ids.return_value = []
    executor = StagedParallelExecutor(
        provider, graph, tmp_path / "ext", tmp_path, squad_dir
    )
    node = SimpleNamespace(
        id="phase3-consensus",
        agents=[
            {
                "id": "speckit-echelon-gatekeeper",
                "mode": "ASSESS2",
                "stage": 1,
                "context_pack": [],
                "allowed_verdicts": ["PASS", "REJECTED", "BLOCKED"],
            },
            {
                "id": "speckit-echelon-orchestrator",
                "mode": "PLAN2",
                "stage": 2,
                "context_pack": [],
                "allowed_verdicts": ["COMPLETE", "DONE", "BLOCKED"],
            },
        ],
        allowed_state_updates=[],
    )

    result = executor.execute(node, state_store)

    assert result.verdict == "BLOCKED"
    assert result.state_updates["blocked_reason"] == "missing_consensus_prerequisite"
    assert result.state_updates["missing_outputs"] == [
        str(spec_dir / "implementability-report.md")
    ]
    assert provider.exec_agent.call_count == 1


def test_plan2_reporting_state_is_quarantined_without_blocking(tmp_path):
    ex = _executor(tmp_path)
    node = SimpleNamespace(
        id="phase3-consensus",
        allowed_state_updates=["tasks_lexicon_attempts"],
        required_state_updates=[],
        state_update_types={"tasks_lexicon_attempts": "integer"},
        allowed_verdicts=["COMPLETE", "BLOCKED"],
    )
    result = SquadAgentResult(
        exit_code=0,
        echelon_result={
            "verdict": "COMPLETE",
            "state_updates": {
                "phase3_plan_verdict": "COMPLETE",
                "critical_path_length_days": 118,
                "total_tasks": 61,
                "parallelizable_tasks": 40,
                "high_risk_tasks": 9,
                "blocking_gates": [],
                "test_automation_coverage": 0.92,
            },
            "journal_entries": [],
        },
        raw_output="",
        duration_ms=0,
        timed_out=False,
    )

    validated = ex._validate_result_state_updates(node, result)

    assert validated.verdict == "COMPLETE"
    assert validated.state_updates == {}
    assert set(validated.quarantined_state_updates) == {
        "phase3_plan_verdict",
        "critical_path_length_days",
        "total_tasks",
        "parallelizable_tasks",
        "high_risk_tasks",
        "blocking_gates",
        "test_automation_coverage",
    }


def test_quarantined_state_updates_are_recorded_as_controller_journal_warning(tmp_path):
    ex = _executor(tmp_path)
    result = _result()
    result.quarantined_state_updates = {"total_tasks": 61, "high_risk_tasks": 9}

    ex._write_journal_entries(result, "phase3-consensus")

    entries = _read_journal(tmp_path)
    assert len(entries) == 1
    assert entries[0]["type"] == "state_contract_warning"
    assert entries[0]["data"]["dropped_keys"] == ["high_risk_tasks", "total_tasks"]
    assert entries[0]["data"]["action"] == "quarantined"


def test_staged_prompt_uses_agent_specific_state_contract(tmp_path):
    squad_dir = tmp_path / "squad" / "run-test"
    squad_dir.mkdir(parents=True)
    ext_dir = tmp_path / "ext"
    agent_dir = ext_dir / "agents"
    agent_dir.mkdir(parents=True)
    (agent_dir / "plan2.md").write_text("# PLAN2\nRole-specific instructions.")

    provider = MagicMock()
    graph = MagicMock()
    graph.agent_file.return_value = "agents/plan2.md"
    graph.all_phase_ids.return_value = []
    ex = StagedParallelExecutor(provider, graph, ext_dir, tmp_path, squad_dir)
    state = {"squad_dir": str(squad_dir), "staging_dir": str(squad_dir / "staging")}
    entry = {
        "id": "speckit-echelon-orchestrator",
        "mode": "PLAN2",
        "allowed_state_updates": ["tasks_lexicon_attempts"],
        "required_state_updates": [],
        "state_update_types": {"tasks_lexicon_attempts": "integer"},
        "allowed_verdicts": ["COMPLETE", "BLOCKED"],
    }

    prompt = ex._build_agent_prompt(
        entry,
        state,
        allowed_state_updates=entry["allowed_state_updates"],
        required_state_updates=entry["required_state_updates"],
        state_update_types=entry["state_update_types"],
        allowed_verdicts=entry["allowed_verdicts"],
    )

    assert "- `tasks_lexicon_pass` (boolean)" not in prompt
    assert "- `tasks_lexicon_attempts` (integer)" in prompt
    assert "Allowed verdicts: `COMPLETE`, `BLOCKED`" in prompt
    assert "quality_scores" not in prompt


def test_staged_prompt_includes_directory_context_pack_contents(tmp_path):
    """Directory context items such as contracts/ are expanded deterministically."""
    squad_dir = tmp_path / "squad" / "run-test"
    staging_dir = squad_dir / "staging"
    staging_dir.mkdir(parents=True)
    ext_dir = tmp_path / "ext"
    agent_dir = ext_dir / "agents"
    agent_dir.mkdir(parents=True)
    (agent_dir / "assess2.md").write_text("# ASSESS2\nRole-specific instructions.")

    spec_dir = tmp_path / "specs" / "001-demo"
    contracts = spec_dir / "contracts"
    contracts.mkdir(parents=True)
    (contracts / "internal-interfaces.md").write_text("CONTRACT CONTENT", encoding="utf-8")

    provider = MagicMock()
    graph = MagicMock()
    graph.agent_file.return_value = "agents/assess2.md"
    graph.all_phase_ids.return_value = []
    ex = StagedParallelExecutor(provider, graph, ext_dir, tmp_path, squad_dir)

    prompt = ex._build_agent_prompt(
        {"id": "ASSESS2", "mode": "ASSESS2", "context_pack": ["contracts/"]},
        {
            "squad_dir": str(squad_dir),
            "staging_dir": str(staging_dir),
            "spec_dir": "specs/001-demo",
        },
    )

    assert f"# {contracts.resolve()}/" in prompt
    assert f"## {contracts.resolve()}/internal-interfaces.md" in prompt
    assert "CONTRACT CONTENT" in prompt


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


def test_assemble_prompt_preserves_active_run_spec_dir(tmp_path):
    """state.spec_dir under runs/.../specs/... is the active squad artifact root."""
    squad_dir = tmp_path / "runs" / "spec-20260618-123456"
    staging_dir = squad_dir / "staging"
    staging_dir.mkdir(parents=True)
    real_spec = tmp_path / "specs" / "006-element-creator"
    real_spec.mkdir(parents=True)
    (real_spec / "spec.md").write_text("REAL SPEC", encoding="utf-8")
    active_spec = squad_dir / "specs" / "006-element-creator"
    active_spec.mkdir(parents=True)
    (active_spec / "spec.md").write_text("ACTIVE RUN SPEC", encoding="utf-8")

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
        "spec_dir": str(active_spec.relative_to(tmp_path)),
    }

    prompt = ex._assemble_prompt(node, state)

    assert "ACTIVE RUN SPEC" in prompt
    assert "REAL SPEC" not in prompt
    assert f"ACTIVE_SPEC_DIR={active_spec.resolve()}" in prompt
    assert "PUBLISHED_SPEC_DIR=" in prompt
    assert f"# {active_spec.resolve() / 'spec.md'}" in prompt


def test_assemble_prompt_reads_fresh_clarifications_from_run_staging(tmp_path):
    """Explicit staging refs must not resolve to a stale spec-dir copy."""
    squad_dir = tmp_path / "runs" / "run-test"
    staging_dir = squad_dir / "staging"
    active_spec = squad_dir / "specs" / "006-element-creator"
    staging_dir.mkdir(parents=True)
    active_spec.mkdir(parents=True)
    (staging_dir / "user-clarifications.md").write_text(
        "FRESH RUN CLARIFICATION", encoding="utf-8"
    )
    (active_spec / "user-clarifications.md").write_text(
        "STALE SPEC CLARIFICATION", encoding="utf-8"
    )

    ex = _executor(tmp_path, squad_dir=squad_dir)
    from harness.phase_graph import PhaseNode

    node = PhaseNode(
        id="phase1-what",
        type="agent",
        context_pack=["{staging_dir}/user-clarifications.md"],
    )
    state = {
        "squad_dir": str(squad_dir),
        "staging_dir": str(staging_dir),
        "spec_dir": str(active_spec.relative_to(tmp_path)),
    }

    prompt = ex._assemble_prompt(node, state)

    assert "FRESH RUN CLARIFICATION" in prompt
    assert "STALE SPEC CLARIFICATION" not in prompt


def test_staged_prompt_preserves_active_run_spec_dir(tmp_path):
    """Staged agent prompts must keep the active squad artifact root."""
    squad_dir = tmp_path / "runs" / "spec-20260618-123456"
    staging_dir = squad_dir / "staging"
    staging_dir.mkdir(parents=True)
    real_spec = tmp_path / "specs" / "006-element-creator"
    real_spec.mkdir(parents=True)
    (real_spec / "spec.md").write_text("REAL SPEC", encoding="utf-8")
    active_spec = squad_dir / "specs" / "006-element-creator"
    active_spec.mkdir(parents=True)
    (active_spec / "spec.md").write_text("ACTIVE RUN SPEC", encoding="utf-8")

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
        "spec_dir": str(active_spec.relative_to(tmp_path)),
    }
    prompt = ex._build_agent_prompt(
        {"id": "WHY3", "mode": "WHY3", "context_pack": ["{spec_dir}/spec.md"]},
        state,
    )

    assert "ACTIVE RUN SPEC" in prompt
    assert "REAL SPEC" not in prompt
    assert f"ACTIVE_SPEC_DIR={active_spec.resolve()}" in prompt
    assert f"# {active_spec.resolve() / 'spec.md'}" in prompt
    assert "{spec_dir}" not in prompt


def test_agent_prompt_declares_subagent_without_global_skill_tool_ban(tmp_path):
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
    assert "Do NOT invoke the Skill tool" not in prompt


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


def test_deterministic_tasks_lexicon_executor_dispatches_provider_free_service(
    tmp_path,
    monkeypatch,
):
    squad_dir = tmp_path / "runs" / "run-test"
    store = SquadStateStore(squad_dir)
    store.initialize("run-test", "brownfield", "demo", 0, "phase3-tasks-lexicon")
    state = store.load()
    state.update(
        {
            "spec_dir": "specs/001-demo",
            "iteration": 2,
            "max_iterations": 5,
            "tasks_lexicon_attempts": 1,
        }
    )
    store.save(state)
    observed = {}

    def fake_gate(**kwargs):
        observed.update(kwargs)
        return TasksLexiconGateResult(
            action="proceed",
            passed=True,
            attempts=0,
            findings=0,
            detail="tasks are valid",
        )

    monkeypatch.setattr(
        "harness.squad_executors.run_tasks_lexicon_gate",
        fake_gate,
        raising=False,
    )
    monkeypatch.setattr(
        "harness.config.get_full_resolved_config",
        lambda *_args, **_kwargs: {"lexicon_gate": {"enabled": True}},
    )
    executor = DeterministicLexiconExecutor(
        MagicMock(spec=PhaseGraph),
        tmp_path / "extension",
        tmp_path,
        squad_dir,
    )
    node = PhaseNode(
        id="phase3-tasks-lexicon",
        type="deterministic_lexicon",
        lexicon_artifact="tasks",
        allowed_state_updates=[],
    )

    result = executor.execute(node, store)

    assert result.verdict == "DONE"
    assert result.state_updates == {
        "tasks_lexicon_action": "proceed",
        "tasks_lexicon_pass": True,
        "tasks_lexicon_attempts": 0,
        "tasks_lexicon_findings": 0,
    }
    assert observed["project_root"] == tmp_path
    assert observed["spec_dir_ref"] == "specs/001-demo"
    assert observed["previous_attempts"] == 1
    assert observed["workflow_iteration"] == 2
    assert observed["max_workflow_iterations"] == 5


def test_deterministic_spec_lexicon_executor_is_read_only_before_advance(
    tmp_path,
    monkeypatch,
):
    squad_dir = tmp_path / "runs" / "run-test"
    store = SquadStateStore(squad_dir)
    store.initialize("run-test", "brownfield", "demo", 0, "phase1-lexicon")
    state = store.load()
    state.update(
        {
            "lexicon_warning_waiver": True,
            "lexicon_pass": True,
            "lexicon_findings": 0,
            "lexicon_report": "stale-report.json",
        }
    )
    store.save(state)
    monkeypatch.setattr(
        "harness.squad_executors.run_spec_lexicon_gate",
        lambda **_kwargs: SpecLexiconGateResult(
            evaluation="pending",
            passed=None,
            attempts=0,
            detail="disabled",
        ),
    )
    monkeypatch.setattr(
        "harness.config.get_full_resolved_config",
        lambda *_args, **_kwargs: {"lexicon_gate": {"enabled": False}},
    )
    executor = DeterministicLexiconExecutor(
        MagicMock(spec=PhaseGraph),
        tmp_path / "extension",
        tmp_path,
        squad_dir,
    )
    node = PhaseNode(
        id="phase1-lexicon",
        type="deterministic_lexicon",
        lexicon_artifact="spec",
        allowed_state_updates=[],
    )
    before = store.load()

    with patch.object(store, "save", wraps=store.save) as save:
        result = executor.execute(node, store)

    assert result.state_updates == {
        "lexicon_evaluation": "pending",
        "lexicon_attempts": 0,
    }
    assert save.call_count == 0
    assert store.load() == before


def test_deterministic_lexicon_executor_blocks_unsupported_artifact(tmp_path):
    squad_dir = tmp_path / "runs" / "run-test"
    store = SquadStateStore(squad_dir)
    store.initialize("run-test", "brownfield", "demo", 0, "bad-gate")
    executor = DeterministicLexiconExecutor(
        MagicMock(spec=PhaseGraph),
        tmp_path / "extension",
        tmp_path,
        squad_dir,
    )
    node = PhaseNode(
        id="bad-gate",
        type="deterministic_lexicon",
        lexicon_artifact="unknown",
        allowed_state_updates=[],
    )

    result = executor.execute(node, store)

    assert result.verdict == "BLOCKED"
    assert "unsupported artifact 'unknown'" in result.state_updates["blocked_reason"]


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
