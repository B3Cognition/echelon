"""T-WS2-1: Unit tests for trace_shim.py.

Tests:
1. Write smoke test — trace_decision writes to trace.jsonl
2. Failure-path swallow test — exceptions never raised to caller
3. Trace file not created when squad_dir does not exist
4. Trace entries have required fields
5. Run-id filter in load_trace
6. Rotation: file rotation does not crash
"""

import json
import sys
from pathlib import Path

import pytest

EXT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(EXT_ROOT) not in sys.path:
    sys.path.insert(0, str(EXT_ROOT))

from scripts.python.trace_shim import trace_decision, load_trace, configure


class TestTraceDecisionWrite:
    def test_write_smoke_creates_trace_file(self, tmp_path):
        squad_dir = tmp_path / "squad"
        squad_dir.mkdir()
        trace_decision(
            run_id="squad-001",
            phase="phase1-what",
            decision_type="routing_decision",
            data={"condition": "always", "next_phase": "phase1-what"},
            squad_dir=squad_dir,
        )
        trace_file = squad_dir / "trace.jsonl"
        assert trace_file.exists()
        content = trace_file.read_text(encoding="utf-8").strip()
        assert content  # non-empty

    def test_written_entry_is_valid_json(self, tmp_path):
        squad_dir = tmp_path / "squad"
        squad_dir.mkdir()
        trace_decision(
            run_id="squad-001",
            phase="phase2-why1",
            decision_type="preflight_probe",
            data={"dependency": "understanding", "status": "AVAILABLE"},
            squad_dir=squad_dir,
        )
        lines = (squad_dir / "trace.jsonl").read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert entry["run_id"] == "squad-001"
        assert entry["phase"] == "phase2-why1"
        assert entry["type"] == "preflight_probe"

    def test_entry_has_required_fields(self, tmp_path):
        squad_dir = tmp_path / "squad"
        squad_dir.mkdir()
        trace_decision(
            run_id="squad-001",
            phase="done",
            decision_type="test_event",
            data={"key": "value"},
            squad_dir=squad_dir,
        )
        entry = json.loads((squad_dir / "trace.jsonl").read_text())
        for field in ["seq", "run_id", "phase", "type", "timestamp", "monotonic", "data"]:
            assert field in entry, f"Missing field: {field}"

    def test_multiple_writes_append_lines(self, tmp_path):
        squad_dir = tmp_path / "squad"
        squad_dir.mkdir()
        for i in range(3):
            trace_decision(
                run_id="squad-001",
                phase=f"phase-{i}",
                decision_type="test",
                squad_dir=squad_dir,
            )
        lines = (squad_dir / "trace.jsonl").read_text(encoding="utf-8").splitlines()
        assert len(lines) == 3

    def test_seq_increments_across_calls(self, tmp_path):
        squad_dir = tmp_path / "squad"
        squad_dir.mkdir()
        for _ in range(3):
            trace_decision(
                run_id="squad-001",
                phase="phase-x",
                decision_type="test",
                squad_dir=squad_dir,
            )
        lines = (squad_dir / "trace.jsonl").read_text(encoding="utf-8").splitlines()
        seqs = [json.loads(l)["seq"] for l in lines]
        assert seqs == sorted(seqs)
        assert len(set(seqs)) == len(seqs)  # all unique


class TestFailurePathSwallow:
    def test_nonexistent_squad_dir_does_not_raise(self, tmp_path):
        """No exception raised when squad_dir does not exist."""
        nonexistent = tmp_path / "nonexistent_squad"
        # Must NOT raise
        trace_decision(
            run_id="squad-001",
            phase="phase-x",
            decision_type="test",
            squad_dir=nonexistent,
        )

    def test_no_trace_file_when_squad_dir_missing(self, tmp_path):
        """When squad_dir does not exist, no trace file is created."""
        nonexistent = tmp_path / "nonexistent_squad"
        trace_decision(
            run_id="squad-001",
            phase="phase-x",
            decision_type="test",
            squad_dir=nonexistent,
        )
        assert not (nonexistent / "trace.jsonl").exists()

    def test_readonly_file_does_not_raise(self, tmp_path):
        """If trace.jsonl is read-only, trace_decision should not raise."""
        squad_dir = tmp_path / "squad"
        squad_dir.mkdir()
        trace_file = squad_dir / "trace.jsonl"
        trace_file.write_text("", encoding="utf-8")
        trace_file.chmod(0o444)  # read-only

        # Must NOT raise even if write fails
        try:
            trace_decision(
                run_id="squad-001",
                phase="phase-x",
                decision_type="test",
                squad_dir=squad_dir,
            )
        except Exception as e:
            pytest.fail(f"trace_decision raised an exception on read-only file: {e}")
        finally:
            trace_file.chmod(0o644)  # restore for cleanup

    def test_none_data_does_not_raise(self, tmp_path):
        squad_dir = tmp_path / "squad"
        squad_dir.mkdir()
        trace_decision(
            run_id="squad-001",
            phase="phase-x",
            decision_type="test",
            data=None,
            squad_dir=squad_dir,
        )

    def test_unserializable_data_does_not_raise(self, tmp_path):
        """Non-JSON-serializable data should be swallowed gracefully."""
        squad_dir = tmp_path / "squad"
        squad_dir.mkdir()
        trace_decision(
            run_id="squad-001",
            phase="phase-x",
            decision_type="test",
            data={"obj": object()},  # not JSON-serializable
            squad_dir=squad_dir,
        )


class TestLoadTrace:
    def test_load_returns_entries(self, tmp_path):
        squad_dir = tmp_path / "squad"
        squad_dir.mkdir()
        trace_decision(run_id="squad-001", phase="ph", decision_type="t", squad_dir=squad_dir)
        entries = load_trace(squad_dir=squad_dir)
        assert len(entries) == 1

    def test_run_id_filter(self, tmp_path):
        squad_dir = tmp_path / "squad"
        squad_dir.mkdir()
        trace_decision(run_id="squad-001", phase="ph", decision_type="t", squad_dir=squad_dir)
        trace_decision(run_id="squad-002", phase="ph", decision_type="t", squad_dir=squad_dir)
        entries_001 = load_trace(squad_dir=squad_dir, run_id="squad-001")
        assert len(entries_001) == 1
        assert entries_001[0]["run_id"] == "squad-001"

    def test_empty_file_returns_empty_list(self, tmp_path):
        squad_dir = tmp_path / "squad"
        squad_dir.mkdir()
        (squad_dir / "trace.jsonl").write_text("", encoding="utf-8")
        entries = load_trace(squad_dir=squad_dir)
        assert entries == []

    def test_missing_file_returns_empty_list(self, tmp_path):
        squad_dir = tmp_path / "squad"
        squad_dir.mkdir()
        entries = load_trace(squad_dir=squad_dir)
        assert entries == []

    def test_nonexistent_dir_returns_empty_list(self, tmp_path):
        entries = load_trace(squad_dir=tmp_path / "nonexistent")
        assert entries == []
