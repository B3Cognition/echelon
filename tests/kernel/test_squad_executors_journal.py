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
from unittest.mock import MagicMock

EXT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(EXT_ROOT) not in sys.path:
    sys.path.insert(0, str(EXT_ROOT))

from harness.phase_graph import PhaseGraph
from harness.re_controller import ReControllerResult
from harness.re_publication import RePublicationResult, RePublicationValidationError
from harness.squad_executors import (
    AgentExecutor,
    ConditionalSequentialExecutor,
    StagedParallelExecutor,
    _canonical_echelon_result_contract,
    _allowed_state_updates_contract,
)
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


def _stub_mode1_controller(monkeypatch, outcome=ReControllerResult(completed=True)):
    class StubController:
        def __init__(self, **_kwargs):
            pass

        def run(self):
            return outcome

    monkeypatch.setattr("harness.squad_executors.ReExtractionController", StubController)


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
                    **_journal_entry("quality_check"),
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
    ex._write_journal_entries(_result(entries=[_journal_entry("insight")]), "phase1-a")

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
    assert "Any other top-level key blocks the run." in prompt


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
    agent_path = tmp_path / "golddigger.md"
    agent_path.write_text("# GOLDDIGGER\n")
    ex = _executor(tmp_path, squad_dir=squad_dir)
    state = {"squad_dir": str(squad_dir), "staging_dir": str(squad_dir / "staging")}

    prompt = ex._assemble_pre_dispatch_prompt(
        agent_path,
        {"id": "golddigger_mode1", "mode": 1},
        state,
        ["golddigger_status"],
    )

    assert "## Allowed state_updates for this dispatch" in prompt
    assert "- `golddigger_status`" in prompt
    assert f"EXTENSION_TEMPLATES_DIR={tmp_path / 'ext' / 'templates'}" in prompt
    assert "NEVER resolve it as `${EXTENSION_DIR}/extension/templates/foo.md`" in prompt


def test_pre_dispatch_prompt_includes_re_execution_context(tmp_path):
    squad_dir = tmp_path / "squad" / "run-test"
    squad_dir.mkdir(parents=True)
    agent_path = tmp_path / "golddigger.md"
    agent_path.write_text("# GOLDDIGGER\n")
    ex = _executor(tmp_path, squad_dir=squad_dir)
    state = {
        "squad_dir": str(squad_dir),
        "staging_dir": str(squad_dir / "staging"),
        "re_policy": "target-only",
        "target_source": "prosaic",
        "re_refresh_sources": ["prosaic"],
        "re_missing_sources": [],
        "re_empty_sources": [],
        "re_unavailable_sources": ["archive"],
        "re_execution_plan": {"removed_sources": ["retired"]},
        "re_analysis_required": True,
        "re_workspace_synthesis_required": True,
        "re_publication_required": True,
        "re_forbidden_source_roots": [str(tmp_path / "sources" / "original-a")],
        "re_artifacts": {
            "source_index": str(squad_dir / "re" / "re-source-index.json"),
            "analysis_manifest": str(squad_dir / "re" / "re-analysis-manifest.json"),
            "workspace_inputs": str(squad_dir / "re" / "re-workspace-inputs.json"),
            "analysis": str(squad_dir / "re" / "analysis.json"),
        },
    }

    prompt = ex._assemble_pre_dispatch_prompt(
        agent_path,
        {"id": "golddigger_mode1", "mode": 1},
        state,
        ["golddigger_status"],
    )

    assert "## Reverse Engineering Execution Plan" in prompt
    assert "RE_POLICY=target-only" in prompt
    assert "RE_REFRESH_SOURCES=prosaic" in prompt
    assert "RE_UNAVAILABLE_SOURCES=archive" in prompt
    assert "RE_REMOVED_SOURCES=retired" in prompt
    assert "RE_ANALYSIS_REQUIRED=true" in prompt
    assert "RE_WORKSPACE_SYNTHESIS_REQUIRED=true" in prompt
    assert "RE_PUBLICATION_REQUIRED=true" in prompt
    assert "re-analysis-manifest.json" in prompt
    assert "re-workspace-inputs.json" in prompt
    assert "FORBIDDEN_SOURCE_ROOTS:" in prompt
    assert str(tmp_path / "sources" / "original-a") in prompt
    assert "RE_TARGET_SOURCE" not in prompt


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


def test_golddigger_mode1_skips_when_re_plan_has_no_refresh_sources(tmp_path):
    from harness.phase_graph import PhaseNode

    squad_dir = tmp_path / "squad" / "run-test"
    squad_dir.mkdir(parents=True)
    ext_dir = tmp_path / "ext"
    agent_dir = ext_dir / "agents"
    agent_dir.mkdir(parents=True)
    (agent_dir / "golddigger.md").write_text("# GOLDDIGGER\nPre-dispatch agent.")

    state_store = SquadStateStore(squad_dir)
    state_store.initialize("r", "greenfield", "msg", 0, "phase1-discover")
    state = state_store.load()
    state.update(
        {
            "re_policy": "changed",
            "re_refresh_sources": [],
            "re_missing_sources": [],
            "re_artifacts": {
                "analysis": str(squad_dir / "re" / "analysis.json"),
                "source_index": str(squad_dir / "re" / "re-source-index.json"),
                "per_repo": [str(squad_dir / "re" / "original-a")],
            },
        }
    )
    state_store.save(state)

    provider = MagicMock()
    graph = MagicMock()
    graph.agent_file.return_value = "agents/golddigger.md"
    graph.all_phase_ids.return_value = []
    ex = AgentExecutor(provider, graph, ext_dir, tmp_path, squad_dir)
    node = PhaseNode(
        id="phase1-discover",
        type="agent",
        pre_dispatch=[
            {"id": "golddigger_mode1", "agent": "speckit-echelon-golddigger"}
        ],
        allowed_state_updates=[
            "golddigger_artifacts",
            "golddigger_status",
            "golddigger_mode",
            "golddigger_notes",
        ],
    )

    result = ex._run_pre_dispatch(node, state_store.load(), state_store)

    provider.exec_agent.assert_not_called()
    assert result is None
    updated = state_store.load()
    assert updated["golddigger_status"] == "complete"
    assert updated["golddigger_mode"] == "cached-re"
    assert updated["golddigger_artifacts"]["source_index"] == str(
        squad_dir / "re" / "re-source-index.json"
    )


def test_golddigger_mode1_complete_publishes_canonical_context(tmp_path, monkeypatch):
    from harness.phase_graph import PhaseNode

    squad_dir = tmp_path / "runs" / "run-test"
    squad_dir.mkdir(parents=True)
    ext_dir = tmp_path / "ext"
    agent_dir = ext_dir / "agents"
    agent_dir.mkdir(parents=True)
    (agent_dir / "golddigger.md").write_text("# GOLDDIGGER\n")

    state_store = SquadStateStore(squad_dir)
    state_store.initialize("run-test", "brownfield", "msg", 0, "phase1-discover")
    state = state_store.load()
    state.update(
        {
            "re_refresh_sources": ["api"],
            "re_publication_required": True,
            "re_generation": 1,
            "re_artifacts": {"manifest": str(tmp_path / "re/index.json")},
        }
    )
    state_store.save(state)
    _stub_mode1_controller(monkeypatch)

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
    graph.all_phase_ids.return_value = []
    executor = AgentExecutor(provider, graph, ext_dir, tmp_path, squad_dir)
    node = PhaseNode(
        id="phase1-discover",
        type="agent",
        pre_dispatch=[
            {"id": "golddigger_mode1", "agent": "speckit-echelon-golddigger"}
        ],
        allowed_state_updates=["golddigger_status"],
    )

    publish = MagicMock(
        return_value=RePublicationResult(
            generation=2,
            status="complete",
            index_path=tmp_path / "re/index.json",
            changed_sources=("api",),
            removed_sources=(),
            warnings=(),
        )
    )
    canonical = {
        "manifest": str(tmp_path / "re/index.json"),
        "source_manifests": {"api": str(tmp_path / "re/sources/api/manifest.json")},
        "workspace_manifest": str(tmp_path / "re/workspace/manifest.json"),
        "re_overview": str(tmp_path / "re/workspace/overview.md"),
        "re_specs": [str(tmp_path / "re/sources/api/specs/domain/spec.md")],
    }
    monkeypatch.setattr("harness.squad_executors.publish_re_run", publish)
    monkeypatch.setattr(
        "harness.squad_executors.load_published_index",
        lambda _root: SimpleNamespace(generation=2),
    )
    monkeypatch.setattr(
        "harness.squad_executors.canonical_re_artifacts",
        lambda _root, _index: canonical,
    )

    result = executor._run_pre_dispatch(node, state_store.load(), state_store)

    assert result is None
    publish.assert_called_once_with(
        tmp_path,
        squad_dir,
        allow_partial=False,
        status_override="complete",
        expected_generation=1,
    )
    updated = state_store.load()
    assert updated["re_generation"] == 2
    assert updated["re_artifacts"] == canonical
    assert updated["golddigger_artifacts"] == canonical
    assert updated["re_sources"] == canonical["source_manifests"]
    assert updated["re_workspace"] == canonical["workspace_manifest"]


def test_golddigger_mode1_partial_publishes_canonical_context(tmp_path, monkeypatch):
    from harness.phase_graph import PhaseNode

    squad_dir = tmp_path / "runs" / "run-test"
    squad_dir.mkdir(parents=True)
    ext_dir = tmp_path / "ext"
    agent_dir = ext_dir / "agents"
    agent_dir.mkdir(parents=True)
    (agent_dir / "golddigger.md").write_text("# GOLDDIGGER\n")

    state_store = SquadStateStore(squad_dir)
    state_store.initialize("run-test", "brownfield", "msg", 0, "phase1-discover")
    state = state_store.load()
    state.update(
        {
            "re_refresh_sources": ["api"],
            "re_publication_required": True,
            "re_generation": 1,
            "re_artifacts": {"manifest": str(tmp_path / "re/index.json")},
        }
    )
    state_store.save(state)
    monkeypatch.setattr(
        AgentExecutor,
        "_run_golddigger_mode1_controller",
        lambda _executor: SquadAgentResult(
            exit_code=0,
            echelon_result={
                "verdict": "DONE",
                "state_updates": {
                    "golddigger_status": "partial",
                    "golddigger_notes": ["quality debt remains: api"],
                },
                "journal_entries": [],
            },
            raw_output="",
            duration_ms=1,
            timed_out=False,
        ),
    )

    provider = MagicMock()
    graph = MagicMock()
    graph.agent_file.return_value = "agents/golddigger.md"
    graph.all_phase_ids.return_value = []
    executor = AgentExecutor(provider, graph, ext_dir, tmp_path, squad_dir)
    node = PhaseNode(
        id="phase1-discover",
        type="agent",
        pre_dispatch=[
            {"id": "golddigger_mode1", "agent": "speckit-echelon-golddigger"}
        ],
        allowed_state_updates=["golddigger_status"],
    )

    publish = MagicMock(
        return_value=RePublicationResult(
            generation=2,
            status="partial",
            index_path=tmp_path / "re/index.json",
            changed_sources=("api",),
            removed_sources=(),
            warnings=("quality debt remains: api",),
        )
    )
    canonical = {
        "manifest": str(tmp_path / "re/index.json"),
        "source_manifests": {"api": str(tmp_path / "re/sources/api/manifest.json")},
        "workspace_manifest": str(tmp_path / "re/workspace/manifest.json"),
        "re_overview": str(tmp_path / "re/workspace/overview.md"),
        "re_specs": [str(tmp_path / "re/sources/api/specs/domain/spec.md")],
    }
    monkeypatch.setattr("harness.squad_executors.publish_re_run", publish)
    monkeypatch.setattr(
        "harness.squad_executors.load_published_index",
        lambda _root: SimpleNamespace(generation=2),
    )
    monkeypatch.setattr(
        "harness.squad_executors.canonical_re_artifacts",
        lambda _root, _index: canonical,
    )

    result = executor._run_pre_dispatch(node, state_store.load(), state_store)

    assert result is None
    publish.assert_called_once_with(
        tmp_path,
        squad_dir,
        allow_partial=True,
        status_override="partial",
        expected_generation=1,
    )
    updated = state_store.load()
    assert updated["golddigger_status"] == "partial"
    assert updated["re_generation"] == 2
    assert updated["re_artifacts"] == canonical
    assert updated["golddigger_artifacts"] == canonical
    assert updated["re_publication_required"] is False


def test_golddigger_publication_failure_blocks_and_preserves_context(tmp_path, monkeypatch):
    from harness.phase_graph import PhaseNode

    squad_dir = tmp_path / "runs" / "run-test"
    squad_dir.mkdir(parents=True)
    ext_dir = tmp_path / "ext"
    agent_dir = ext_dir / "agents"
    agent_dir.mkdir(parents=True)
    (agent_dir / "golddigger.md").write_text("# GOLDDIGGER\n")
    old_context = {"manifest": str(tmp_path / "re/index.json"), "generation": 1}

    state_store = SquadStateStore(squad_dir)
    state_store.initialize("run-test", "brownfield", "msg", 0, "phase1-discover")
    state = state_store.load()
    state.update(
        {
            "re_refresh_sources": ["api"],
            "re_publication_required": True,
            "re_generation": 1,
            "re_artifacts": old_context,
        }
    )
    state_store.save(state)
    _stub_mode1_controller(monkeypatch)

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
    executor = AgentExecutor(provider, graph, ext_dir, tmp_path, squad_dir)
    node = PhaseNode(
        id="phase1-discover",
        type="agent",
        pre_dispatch=[
            {"id": "golddigger_mode1", "agent": "speckit-echelon-golddigger"}
        ],
        allowed_state_updates=["golddigger_status"],
    )
    monkeypatch.setattr(
        "harness.squad_executors.publish_re_run",
        MagicMock(side_effect=RePublicationValidationError("workspace mismatch")),
    )

    result = executor._run_pre_dispatch(node, state_store.load(), state_store)

    assert result is not None and result.blocked
    assert result.state_updates["blocked_reason"] == "re_publication_failed"
    assert "workspace mismatch" in result.state_updates["re_publication_error"]
    updated = state_store.load()
    assert updated["re_generation"] == 1
    assert updated["re_artifacts"] == old_context
    assert "golddigger_status" not in updated


def test_blocked_publication_error_is_persisted_in_squad_state(tmp_path):
    ctrl, _provider = _squad_controller(tmp_path)
    result = SquadAgentResult(
        exit_code=0,
        echelon_result={
            "verdict": "BLOCKED",
            "state_updates": {
                "blocked_reason": "re_publication_failed",
                "re_publication_error": "shallow reverse-engineering spec is not publishable",
            },
            "journal_entries": [],
        },
        raw_output="",
        duration_ms=0,
        timed_out=False,
    )

    ctrl._block_after_executor_failure("phase1-discover", "re_publication_failed", result)

    state = ctrl._state_store.load()
    assert state["blocked_reason"] == "re_publication_failed"
    assert state["re_publication_error"] == (
        "shallow reverse-engineering spec is not publishable"
    )


def test_blocked_golddigger_result_never_publishes(tmp_path, monkeypatch):
    from harness.phase_graph import PhaseNode

    squad_dir = tmp_path / "runs" / "run-test"
    squad_dir.mkdir(parents=True)
    ext_dir = tmp_path / "ext"
    agent_dir = ext_dir / "agents"
    agent_dir.mkdir(parents=True)
    (agent_dir / "golddigger.md").write_text("# GOLDDIGGER\n")
    state_store = SquadStateStore(squad_dir)
    state_store.initialize("run-test", "brownfield", "msg", 0, "phase1-discover")
    state = state_store.load()
    state.update(
        {
            "re_refresh_sources": ["api"],
            "re_publication_required": True,
            "re_generation": 0,
        }
    )
    state_store.save(state)
    _stub_mode1_controller(
        monkeypatch,
        ReControllerResult(completed=False, blocked_reason="re_agent_dispatch_failed"),
    )
    provider = MagicMock()
    provider.exec_agent.return_value = SquadAgentResult(
        exit_code=0,
        echelon_result={
            "verdict": "BLOCKED",
            "state_updates": {
                "blocked_reason": "agent blocked",
                "golddigger_status": "complete",
            },
            "journal_entries": [],
        },
        raw_output="",
        duration_ms=1,
        timed_out=False,
    )
    graph = MagicMock()
    graph.agent_file.return_value = "agents/golddigger.md"
    executor = AgentExecutor(provider, graph, ext_dir, tmp_path, squad_dir)
    node = PhaseNode(
        id="phase1-discover",
        type="agent",
        pre_dispatch=[
            {"id": "golddigger_mode1", "agent": "speckit-echelon-golddigger"}
        ],
        allowed_state_updates=["golddigger_status"],
    )
    publish = MagicMock()
    monkeypatch.setattr("harness.squad_executors.publish_re_run", publish)

    result = executor._run_pre_dispatch(node, state_store.load(), state_store)

    assert result is not None and result.blocked
    publish.assert_not_called()


def test_blocked_golddigger_result_preserves_re_detail(tmp_path, monkeypatch):
    from harness.phase_graph import PhaseNode

    squad_dir = tmp_path / "runs" / "run-test"
    squad_dir.mkdir(parents=True)
    ext_dir = tmp_path / "ext"
    agent_dir = ext_dir / "agents"
    agent_dir.mkdir(parents=True)
    (agent_dir / "golddigger.md").write_text("# GOLDDIGGER\n")
    state_store = SquadStateStore(squad_dir)
    state_store.initialize("run-test", "brownfield", "msg", 0, "phase1-discover")
    state = state_store.load()
    state.update({"re_refresh_sources": ["api"], "re_publication_required": True})
    state_store.save(state)
    _stub_mode1_controller(
        monkeypatch,
        ReControllerResult(
            completed=False,
            blocked_reason="re_semantic_quality_review_invalid",
            blocked_detail=(
                "semantic quality review invalid for api/001-re-domain: "
                "invalid source_evidence `sources/api/specs/001-re-domain/spec.md:10-12`"
            ),
        ),
    )
    graph = MagicMock()
    graph.agent_file.return_value = "agents/golddigger.md"
    executor = AgentExecutor(MagicMock(), graph, ext_dir, tmp_path, squad_dir)
    node = PhaseNode(
        id="phase1-discover",
        type="agent",
        pre_dispatch=[
            {"id": "golddigger_mode1", "agent": "speckit-echelon-golddigger"}
        ],
    )

    result = executor._run_pre_dispatch(node, state_store.load(), state_store)

    assert result is not None and result.blocked
    assert result.state_updates["blocked_reason"] == "re_semantic_quality_review_invalid"
    assert "api/001-re-domain" in result.state_updates["re_agent_result_detail"]


def test_golddigger_no_refresh_still_dispatches_for_workspace_synthesis(tmp_path):
    executor = _executor(tmp_path)

    assert not executor._golddigger_mode1_cache_hit(
        {
            "re_refresh_sources": [],
            "re_publication_required": True,
            "re_workspace_synthesis_required": True,
        }
    )


def test_golddigger_mode1_skip_empty_sources_is_success(tmp_path):
    from harness.phase_graph import PhaseNode

    squad_dir = tmp_path / "squad" / "run-test"
    squad_dir.mkdir(parents=True)
    ext_dir = tmp_path / "ext"
    agent_dir = ext_dir / "agents"
    agent_dir.mkdir(parents=True)
    (agent_dir / "golddigger.md").write_text("# GOLDDIGGER\nPre-dispatch agent.")

    state_store = SquadStateStore(squad_dir)
    state_store.initialize("r", "brownfield", "msg", 0, "phase1-discover")
    state = state_store.load()
    state.update(
        {
            "re_policy": "target-changed",
            "target_source": "prosaic",
            "re_refresh_sources": [],
            "re_missing_sources": [],
            "re_empty_sources": ["prosaic"],
            "re_artifacts": {
                "analysis": str(squad_dir / "re" / "analysis.json"),
                "source_index": str(squad_dir / "re" / "re-source-index.json"),
                "per_repo": [],
            },
        }
    )
    state_store.save(state)

    provider = MagicMock()
    graph = MagicMock()
    graph.agent_file.return_value = "agents/golddigger.md"
    graph.all_phase_ids.return_value = []
    ex = AgentExecutor(provider, graph, ext_dir, tmp_path, squad_dir)
    node = PhaseNode(
        id="phase1-discover",
        type="agent",
        pre_dispatch=[
            {"id": "golddigger_mode1", "agent": "speckit-echelon-golddigger"}
        ],
        allowed_state_updates=[
            "golddigger_artifacts",
            "golddigger_status",
            "golddigger_mode",
            "golddigger_notes",
        ],
    )

    result = ex._run_pre_dispatch(node, state_store.load(), state_store)

    provider.exec_agent.assert_not_called()
    assert result is None
    updated = state_store.load()
    assert updated["golddigger_status"] == "complete"
    assert updated["golddigger_mode"] == "cached-re"
    assert "empty source roots skipped: prosaic" in updated["golddigger_notes"][0]


def test_pre_dispatch_blocks_unallowed_state_updates_before_mutation(tmp_path):
    """Pre-dispatch agents must obey the phase state_update allowlist."""
    from harness.phase_graph import PhaseNode

    squad_dir = tmp_path / "squad" / "run-test"
    squad_dir.mkdir(parents=True)
    ext_dir = tmp_path / "ext"
    agent_dir = ext_dir / "agents"
    agent_dir.mkdir(parents=True)
    (agent_dir / "golddigger.md").write_text("# GOLDDIGGER\nPre-dispatch agent.")

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
    graph.agent_file.return_value = "agents/golddigger.md"
    graph.all_phase_ids.return_value = []
    ex = AgentExecutor(provider, graph, ext_dir, tmp_path, squad_dir)
    node = PhaseNode(
        id="phase1-discover",
        type="agent",
        pre_dispatch=[
            {"id": "test_pre_dispatch", "agent": "speckit-echelon-golddigger"}
        ],
        allowed_state_updates=["allowed_key"],
    )

    result = ex._run_pre_dispatch(node, state_store.load(), state_store)

    state = state_store.load()
    assert result is not None
    assert result.verdict == "BLOCKED"
    assert (
        "state_updates key 'unexpected' is not allowed"
        in result.state_updates["blocked_reason"]
    )
    assert "unexpected" not in state
    assert not state.get("blocked_reason")
    assert not (squad_dir / "reasoning-journal.jsonl").exists()


def test_agent_execute_blocks_unallowed_state_updates_before_journal_write(tmp_path):
    """Normal agent dispatch must validate allowlists before journal mutation."""
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

    assert result.blocked is True
    assert (
        "state_updates key 'unexpected' is not allowed"
        in result.state_updates["blocked_reason"]
    )
    assert not (squad_dir / "reasoning-journal.jsonl").exists()


def test_pre_dispatch_applies_allowed_state_updates(tmp_path):
    """Allowed pre-dispatch updates still flow into state."""
    from harness.phase_graph import PhaseNode

    squad_dir = tmp_path / "squad" / "run-test"
    squad_dir.mkdir(parents=True)
    ext_dir = tmp_path / "ext"
    agent_dir = ext_dir / "agents"
    agent_dir.mkdir(parents=True)
    (agent_dir / "golddigger.md").write_text("# GOLDDIGGER\nPre-dispatch agent.")

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
    graph.agent_file.return_value = "agents/golddigger.md"
    graph.all_phase_ids.return_value = []
    ex = AgentExecutor(provider, graph, ext_dir, tmp_path, squad_dir)
    node = PhaseNode(
        id="phase1-discover",
        type="agent",
        pre_dispatch=[
            {"id": "test_pre_dispatch", "agent": "speckit-echelon-golddigger"}
        ],
        allowed_state_updates=["allowed_key"],
    )

    result = ex._run_pre_dispatch(node, state_store.load(), state_store)

    assert result is None
    assert state_store.load()["allowed_key"] is True


def test_golddigger_mode2_queue_dispatches_without_agent_field(tmp_path):
    """Mode 2 queue entries run even when definition.yaml omits an agent field."""
    from harness.phase_graph import PhaseNode

    squad_dir = tmp_path / "squad" / "run-test"
    squad_dir.mkdir(parents=True)
    ext_dir = tmp_path / "ext"
    agent_dir = ext_dir / "agents" / "exploration"
    agent_dir.mkdir(parents=True)
    (agent_dir / "golddigger.md").write_text("# GOLDDIGGER\nDeep-dive agent.")

    state_store = SquadStateStore(squad_dir)
    state_store.initialize("r", "brownfield", "msg", 0, "phase1-what")
    state = state_store.load()
    state["golddigger_requests"] = [
        {
            "domain": "auth",
            "repo": None,
            "requested_by": "test",
            "reason": "need topology",
        }
    ]
    state["golddigger_completed_domains"] = []
    state_store.save(state)

    provider = MagicMock()

    def _exec_agent(project_root, prompt):
        cache_dir = squad_dir / "golddigger-cache"
        cache_dir.mkdir(parents=True)
        (cache_dir / "auth.md").write_text("# Auth deep dive\n", encoding="utf-8")
        return SquadAgentResult(
            exit_code=0,
            echelon_result={
                "verdict": "COMPLETE",
                "state_updates": {
                    "golddigger_status": "complete",
                    "golddigger_mode": "deep-dive",
                },
                "journal_entries": [],
            },
            raw_output="",
            duration_ms=0,
            timed_out=False,
        )

    provider.exec_agent.side_effect = _exec_agent
    graph = MagicMock()
    graph.agent_file.return_value = "agents/exploration/golddigger.md"
    graph.all_phase_ids.return_value = []
    ex = AgentExecutor(provider, graph, ext_dir, tmp_path, squad_dir)
    node = PhaseNode(
        id="phase1-what",
        type="agent",
        pre_dispatch=[{"id": "golddigger_mode2_queue", "action": "process"}],
        allowed_state_updates=["golddigger_status", "golddigger_mode"],
    )

    result = ex._run_pre_dispatch(node, state_store.load(), state_store)

    updated = state_store.load()
    assert result is None
    provider.exec_agent.assert_called_once()
    assert "Mode 2 (Deep Dive)" in provider.exec_agent.call_args.args[1]
    assert updated["golddigger_requests"] == []
    assert updated["golddigger_completed_domains"] == ["auth"]


def test_golddigger_mode2_queue_respects_disabled_policy(tmp_path):
    """Disabled policy leaves the queue untouched and skips Mode 2 dispatch."""
    from harness.phase_graph import PhaseNode

    squad_dir = tmp_path / "squad" / "run-test"
    squad_dir.mkdir(parents=True)
    ext_dir = tmp_path / "ext"
    agent_dir = ext_dir / "agents" / "exploration"
    agent_dir.mkdir(parents=True)
    (agent_dir / "golddigger.md").write_text("# GOLDDIGGER\nDeep-dive agent.")
    config_dir = tmp_path / ".specify" / "extensions" / "echelon"
    config_dir.mkdir(parents=True)
    (config_dir / "echelon-config.yml").write_text(
        "golddigger:\n  mode2_policy: disabled\n",
        encoding="utf-8",
    )

    state_store = SquadStateStore(squad_dir)
    state_store.initialize("r", "brownfield", "msg", 0, "phase1-what")
    state = state_store.load()
    state["golddigger_requests"] = [
        {
            "domain": "auth",
            "repo": None,
            "requested_by": "test",
            "reason": "need topology",
        }
    ]
    state["golddigger_completed_domains"] = ["billing"]
    state_store.save(state)

    provider = MagicMock()
    graph = MagicMock()
    graph.agent_file.return_value = "agents/exploration/golddigger.md"
    graph.all_phase_ids.return_value = []
    ex = AgentExecutor(provider, graph, ext_dir, tmp_path, squad_dir)
    node = PhaseNode(
        id="phase1-what",
        type="agent",
        pre_dispatch=[{"id": "golddigger_mode2_queue", "action": "process"}],
        allowed_state_updates=["golddigger_status", "golddigger_mode"],
    )

    result = ex._run_pre_dispatch(node, state_store.load(), state_store)

    updated = state_store.load()
    assert result is None
    provider.exec_agent.assert_not_called()
    assert updated["golddigger_requests"] == [
        {
            "domain": "auth",
            "repo": None,
            "requested_by": "test",
            "reason": "need topology",
        }
    ]
    assert updated["golddigger_completed_domains"] == ["billing"]


def test_golddigger_mode2_queue_preserves_blocked_request(tmp_path):
    """A blocked deep-dive leaves the current and remaining requests queued."""
    from harness.phase_graph import PhaseNode

    squad_dir = tmp_path / "squad" / "run-test"
    squad_dir.mkdir(parents=True)
    ext_dir = tmp_path / "ext"
    agent_dir = ext_dir / "agents" / "exploration"
    agent_dir.mkdir(parents=True)
    (agent_dir / "golddigger.md").write_text("# GOLDDIGGER\nDeep-dive agent.")

    state_store = SquadStateStore(squad_dir)
    state_store.initialize("r", "brownfield", "msg", 0, "phase1-what")
    state = state_store.load()
    state["golddigger_requests"] = [
        {
            "domain": "auth",
            "repo": None,
            "requested_by": "test",
            "reason": "need auth topology",
        },
        {
            "domain": "billing",
            "repo": None,
            "requested_by": "test",
            "reason": "need billing topology",
        },
    ]
    state["golddigger_completed_domains"] = []
    state_store.save(state)

    provider = MagicMock()
    provider.exec_agent.return_value = SquadAgentResult(
        exit_code=0,
        echelon_result={
            "verdict": "BLOCKED",
            "state_updates": {"golddigger_status": "failed"},
            "journal_entries": [],
        },
        raw_output="",
        duration_ms=0,
        timed_out=False,
    )
    graph = MagicMock()
    graph.agent_file.return_value = "agents/exploration/golddigger.md"
    graph.all_phase_ids.return_value = []
    ex = AgentExecutor(provider, graph, ext_dir, tmp_path, squad_dir)
    node = PhaseNode(
        id="phase1-what",
        type="agent",
        pre_dispatch=[{"id": "golddigger_mode2_queue", "action": "process"}],
        allowed_state_updates=["golddigger_status"],
    )

    result = ex._run_pre_dispatch(node, state_store.load(), state_store)

    updated = state_store.load()
    assert result is not None
    assert result.blocked is True
    assert updated["golddigger_requests"] == [
        {
            "domain": "auth",
            "repo": None,
            "requested_by": "test",
            "reason": "need auth topology",
        },
        {
            "domain": "billing",
            "repo": None,
            "requested_by": "test",
            "reason": "need billing topology",
        },
    ]
    assert updated["golddigger_completed_domains"] == []


def test_golddigger_mode2_queue_preserves_failed_clean_result(tmp_path):
    """A clean failed/partial Mode 2 result is not marked completed or dequeued."""
    from harness.phase_graph import PhaseNode

    squad_dir = tmp_path / "squad" / "run-test"
    squad_dir.mkdir(parents=True)
    ext_dir = tmp_path / "ext"
    agent_dir = ext_dir / "agents" / "exploration"
    agent_dir.mkdir(parents=True)
    (agent_dir / "golddigger.md").write_text("# GOLDDIGGER\nDeep-dive agent.")

    state_store = SquadStateStore(squad_dir)
    state_store.initialize("r", "brownfield", "msg", 0, "phase1-what")
    request = {
        "domain": "auth",
        "repo": None,
        "requested_by": "test",
        "reason": "need auth topology",
    }
    state = state_store.load()
    state["golddigger_requests"] = [request]
    state["golddigger_completed_domains"] = []
    state_store.save(state)

    provider = MagicMock()
    provider.exec_agent.return_value = SquadAgentResult(
        exit_code=0,
        echelon_result={
            "verdict": "COMPLETE",
            "state_updates": {"golddigger_status": "failed"},
            "journal_entries": [],
        },
        raw_output="",
        duration_ms=0,
        timed_out=False,
    )
    graph = MagicMock()
    graph.agent_file.return_value = "agents/exploration/golddigger.md"
    graph.all_phase_ids.return_value = []
    ex = AgentExecutor(provider, graph, ext_dir, tmp_path, squad_dir)
    node = PhaseNode(
        id="phase1-what",
        type="agent",
        pre_dispatch=[{"id": "golddigger_mode2_queue", "action": "process"}],
        allowed_state_updates=["golddigger_status"],
    )

    result = ex._run_pre_dispatch(node, state_store.load(), state_store)

    updated = state_store.load()
    assert result is None
    assert updated["golddigger_requests"] == [request]
    assert updated["golddigger_completed_domains"] == []
    assert updated["golddigger_status"] == "failed"


def test_golddigger_mode2_queue_blocks_complete_result_without_cache(tmp_path):
    """A claimed complete deep-dive must produce its cache artifact."""
    from harness.phase_graph import PhaseNode

    squad_dir = tmp_path / "squad" / "run-test"
    squad_dir.mkdir(parents=True)
    ext_dir = tmp_path / "ext"
    agent_dir = ext_dir / "agents" / "exploration"
    agent_dir.mkdir(parents=True)
    (agent_dir / "golddigger.md").write_text("# GOLDDIGGER\nDeep-dive agent.")

    state_store = SquadStateStore(squad_dir)
    state_store.initialize("r", "brownfield", "msg", 0, "phase1-what")
    request = {
        "domain": "auth",
        "repo": None,
        "requested_by": "test",
        "reason": "need auth topology",
    }
    state = state_store.load()
    state["golddigger_requests"] = [request]
    state["golddigger_completed_domains"] = []
    state_store.save(state)

    provider = MagicMock()
    provider.exec_agent.return_value = SquadAgentResult(
        exit_code=0,
        echelon_result={
            "verdict": "COMPLETE",
            "state_updates": {"golddigger_status": "complete"},
            "journal_entries": [],
        },
        raw_output="",
        duration_ms=0,
        timed_out=False,
    )
    graph = MagicMock()
    graph.agent_file.return_value = "agents/exploration/golddigger.md"
    graph.all_phase_ids.return_value = []
    ex = AgentExecutor(provider, graph, ext_dir, tmp_path, squad_dir)
    node = PhaseNode(
        id="phase1-what",
        type="agent",
        pre_dispatch=[{"id": "golddigger_mode2_queue", "action": "process"}],
        allowed_state_updates=["golddigger_status"],
    )

    result = ex._run_pre_dispatch(node, state_store.load(), state_store)

    updated = state_store.load()
    assert result is not None
    assert result.blocked is True
    assert result.state_updates["blocked_reason"] == "golddigger_mode2_missing_cache"
    assert updated["golddigger_requests"] == [request]
    assert updated["golddigger_completed_domains"] == []


def test_golddigger_mode2_queue_blocks_harness_owned_state_updates(tmp_path):
    """Mode 2 subagents cannot mutate harness-owned queue/cache state keys."""
    from harness.phase_graph import PhaseNode

    squad_dir = tmp_path / "squad" / "run-test"
    squad_dir.mkdir(parents=True)
    ext_dir = tmp_path / "ext"
    agent_dir = ext_dir / "agents" / "exploration"
    agent_dir.mkdir(parents=True)
    (agent_dir / "golddigger.md").write_text("# GOLDDIGGER\nDeep-dive agent.")

    state_store = SquadStateStore(squad_dir)
    state_store.initialize("r", "brownfield", "msg", 0, "phase1-what")
    original_request = {
        "domain": "auth",
        "repo": None,
        "requested_by": "test",
        "reason": "need topology",
    }
    state = state_store.load()
    state["golddigger_requests"] = [original_request]
    state["golddigger_completed_domains"] = ["billing"]
    state_store.save(state)

    provider = MagicMock()
    provider.exec_agent.return_value = SquadAgentResult(
        exit_code=0,
        echelon_result={
            "verdict": "COMPLETE",
            "state_updates": {
                "golddigger_requests": [],
                "golddigger_completed_domains": ["auth"],
            },
            "journal_entries": [],
        },
        raw_output="",
        duration_ms=0,
        timed_out=False,
    )
    graph = MagicMock()
    graph.agent_file.return_value = "agents/exploration/golddigger.md"
    graph.all_phase_ids.return_value = []
    ex = AgentExecutor(provider, graph, ext_dir, tmp_path, squad_dir)
    node = PhaseNode(
        id="phase1-what",
        type="agent",
        pre_dispatch=[{"id": "golddigger_mode2_queue", "action": "process"}],
        allowed_state_updates=[
            "golddigger_status",
            "golddigger_requests",
            "golddigger_completed_domains",
        ],
    )

    result = ex._run_pre_dispatch(node, state_store.load(), state_store)

    updated = state_store.load()
    prompt = provider.exec_agent.call_args.args[1]
    assert result is not None
    assert result.blocked is True
    assert "golddigger_requests" in result.state_updates["blocked_reason"]
    assert "- `golddigger_status`" in prompt
    assert "- `golddigger_requests`" not in prompt
    assert "- `golddigger_completed_domains`" not in prompt
    assert updated["golddigger_requests"] == [original_request]
    assert updated["golddigger_completed_domains"] == ["billing"]
    assert "golddigger_status" not in updated
    assert not (squad_dir / "reasoning-journal.jsonl").exists()


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


def test_staged_parallel_blocks_state_update_outside_allowlist(tmp_path):
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

    assert result.verdict == "BLOCKED"
    assert "not allowed" in result.state_updates["blocked_reason"]
    assert "unexpected" not in state_store.load()


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

    assert "# contracts/" in prompt
    assert "## contracts/internal-interfaces.md" in prompt
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
    assert "ACTIVE_SPEC_DIR=" in prompt
    assert "PUBLISHED_SPEC_DIR=" in prompt


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
