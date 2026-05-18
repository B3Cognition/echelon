"""Tests for PhaseExecutor._write_journal_entries — single-writer journal protocol."""
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

EXT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(EXT_ROOT) not in sys.path:
    sys.path.insert(0, str(EXT_ROOT))

from harness.squad_executors import AgentExecutor
from harness.squad_provider import SquadAgentResult


def _executor(tmp_path: Path) -> AgentExecutor:
    provider = MagicMock()
    graph = MagicMock()
    graph.agent_file.return_value = None
    return AgentExecutor(
        provider=provider,
        phase_graph=graph,
        ext_dir=tmp_path / "ext",
        project_root=tmp_path,
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


def _read_journal(tmp_path: Path) -> list[dict]:
    p = tmp_path / ".specify/squad/reasoning-journal.jsonl"
    if not p.exists():
        return []
    return [json.loads(ln) for ln in p.read_text().splitlines() if ln.strip()]


def test_no_entries_writes_nothing(tmp_path):
    ex = _executor(tmp_path)
    ex._write_journal_entries(_result(entries=[]), "phase1-test")
    assert not (tmp_path / ".specify/squad/reasoning-journal.jsonl").exists()


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
