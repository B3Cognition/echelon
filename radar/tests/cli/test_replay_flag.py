"""CLI tests for --replay flag."""
import json
import subprocess
import sys
import os
from pathlib import Path

RADAR_EXT = str(Path(__file__).parent.parent.parent.parent.resolve())


def _minimal_recording(tmp_path) -> str:
    """Write a minimal JSONL recording that starts and immediately ends."""
    snap = {
        "run_id": "replay-test-001",
        "run": {"run_id": "replay-test-001", "status": "running", "phase": "discover",
                "phase_display": "DISCOVER", "iteration": 1,
                "created_at": "2026-03-22T10:00:00Z", "updated_at": "2026-03-22T10:00:00Z",
                "completed_at": None},
        "agents": {
            "SCOUT-1": {"id": "SCOUT-1", "codename": "SCOUT", "display_name": "Scout 1",
                        "state": "idle", "phase": "discover",
                        "dispatched_at": "2026-03-22T10:00:00Z"}
        },
        "dispatch_order": ["SCOUT-1"],
        "updated_at": "2026-03-22T10:00:00Z",
    }
    lines = [
        {"recorded_at_ms": 1000000, "event_type": "snapshot", "payload": snap},
        {"recorded_at_ms": 1001000, "event_type": "agent_state_change",
         "payload": {"dispatch_id": "SCOUT-1", "state": "working"}},
    ]
    p = tmp_path / "test.jsonl"
    p.write_text("\n".join(json.dumps(l) for l in lines) + "\n")
    return str(p)


def test_replay_nonexistent_file_exits_nonzero(tmp_path):
    env = os.environ.copy()
    env["PYTHONPATH"] = RADAR_EXT
    env["RADAR_SQUAD_DIR"] = str(tmp_path / "squad")
    r = subprocess.run(
        [sys.executable, "-m", "radar.mock_server", "--replay", str(tmp_path / "nonexistent.jsonl")],
        env=env, capture_output=True, text=True, timeout=5,
    )
    assert r.returncode != 0
    assert "not found" in r.stderr.lower() or "not found" in r.stdout.lower()


def test_replay_scenario_and_replay_mutually_exclusive(tmp_path):
    env = os.environ.copy()
    env["PYTHONPATH"] = RADAR_EXT
    recording = _minimal_recording(tmp_path)
    r = subprocess.run(
        [sys.executable, "-m", "radar.mock_server", "--scenario", "default", "--replay", recording],
        env=env, capture_output=True, text=True, timeout=5,
    )
    assert r.returncode != 0  # argparse rejects mutually exclusive args
