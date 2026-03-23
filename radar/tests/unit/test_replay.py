"""Tests for load_replay — JSONL recording to Scenario conversion."""
import json
import pytest
from pathlib import Path


def _write_recording(tmp_path, lines):
    p = tmp_path / "recording.jsonl"
    p.write_text("\n".join(json.dumps(l) for l in lines) + "\n")
    return str(p)


_SNAPSHOT_PAYLOAD = {
    "run_id": "test-run-001",
    "run": {"run_id": "test-run-001", "status": "running", "phase": "discover",
            "phase_display": "DISCOVER", "iteration": 1,
            "created_at": "2026-03-22T10:00:00Z", "updated_at": "2026-03-22T10:00:00Z",
            "completed_at": None},
    "agents": {
        "SCOUT-1": {"id": "SCOUT-1", "codename": "SCOUT", "display_name": "Scout 1",
                    "state": "idle", "phase": "discover", "dispatched_at": "2026-03-22T10:00:00Z"}
    },
    "dispatch_order": ["SCOUT-1"],
    "updated_at": "2026-03-22T10:00:00Z",
}

_SNAPSHOT_LINE = {"recorded_at_ms": 1000000, "event_type": "snapshot", "payload": _SNAPSHOT_PAYLOAD}
_EVENT_1 = {"recorded_at_ms": 1005000, "event_type": "agent_state_change",
             "payload": {"dispatch_id": "SCOUT-1", "state": "working"}}
_EVENT_2 = {"recorded_at_ms": 1012000, "event_type": "agent_state_change",
             "payload": {"dispatch_id": "SCOUT-1", "state": "complete"}}


def test_load_replay_missing_file_raises(tmp_path):
    from radar.scenarios.replay import load_replay
    with pytest.raises(FileNotFoundError):
        load_replay(str(tmp_path / "nonexistent.jsonl"))

def test_load_replay_returns_scenario(tmp_path):
    from radar.scenarios.replay import load_replay
    from radar.scenarios import Scenario
    path = _write_recording(tmp_path, [_SNAPSHOT_LINE, _EVENT_1, _EVENT_2])
    s = load_replay(path)
    assert isinstance(s, Scenario)

def test_load_replay_name_is_replay(tmp_path):
    from radar.scenarios.replay import load_replay
    path = _write_recording(tmp_path, [_SNAPSHOT_LINE, _EVENT_1])
    s = load_replay(path)
    assert s.name == "replay"

def test_load_replay_description_contains_filename(tmp_path):
    from radar.scenarios.replay import load_replay
    path = _write_recording(tmp_path, [_SNAPSHOT_LINE, _EVENT_1])
    s = load_replay(path)
    assert "recording.jsonl" in s.description

def test_load_replay_loop_false(tmp_path):
    from radar.scenarios.replay import load_replay
    path = _write_recording(tmp_path, [_SNAPSHOT_LINE, _EVENT_1])
    s = load_replay(path)
    assert s.loop is False

def test_load_replay_initial_run_from_snapshot(tmp_path):
    from radar.scenarios.replay import load_replay
    path = _write_recording(tmp_path, [_SNAPSHOT_LINE, _EVENT_1])
    s = load_replay(path)
    assert s.initial_run["run_id"] == "test-run-001"
    assert s.initial_run["status"] == "running"

def test_load_replay_agents_from_snapshot(tmp_path):
    from radar.scenarios.replay import load_replay
    path = _write_recording(tmp_path, [_SNAPSHOT_LINE, _EVENT_1])
    s = load_replay(path)
    assert len(s.initial_agents) == 1
    assert s.initial_agents[0].dispatch_id == "SCOUT-1"

def test_load_replay_snapshot_not_in_event_sequence(tmp_path):
    from radar.scenarios.replay import load_replay
    path = _write_recording(tmp_path, [_SNAPSHOT_LINE, _EVENT_1, _EVENT_2])
    s = load_replay(path)
    types = [e.event_type for e in s.event_sequence]
    assert "snapshot" not in types

def test_load_replay_first_event_delay_zero(tmp_path):
    from radar.scenarios.replay import load_replay
    path = _write_recording(tmp_path, [_SNAPSHOT_LINE, _EVENT_1, _EVENT_2])
    s = load_replay(path)
    assert s.event_sequence[0].delay_ms == 0

def test_load_replay_subsequent_delay_from_timestamps(tmp_path):
    from radar.scenarios.replay import load_replay
    path = _write_recording(tmp_path, [_SNAPSHOT_LINE, _EVENT_1, _EVENT_2])
    s = load_replay(path)
    # _EVENT_2.recorded_at_ms - _EVENT_1.recorded_at_ms = 1012000 - 1005000 = 7000
    assert s.event_sequence[1].delay_ms == 7000

def test_load_replay_no_snapshot_raises(tmp_path):
    from radar.scenarios.replay import load_replay
    path = _write_recording(tmp_path, [_EVENT_1, _EVENT_2])
    with pytest.raises(ValueError, match="No snapshot event"):
        load_replay(path)

def test_load_replay_skips_malformed_lines(tmp_path):
    from radar.scenarios.replay import load_replay
    p = tmp_path / "recording.jsonl"
    p.write_text(
        json.dumps(_SNAPSHOT_LINE) + "\n"
        + "NOT_JSON\n"
        + json.dumps(_EVENT_1) + "\n"
    )
    s = load_replay(str(p))
    assert len(s.event_sequence) == 1  # only _EVENT_1; malformed skipped
