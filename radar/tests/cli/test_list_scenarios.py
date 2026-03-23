import subprocess, sys, os
from pathlib import Path

RADAR_EXT = str(Path(__file__).parent.parent.parent.parent.resolve())

def test_list_scenarios_exits_zero(tmp_path):
    env = os.environ.copy()
    env["PYTHONPATH"] = RADAR_EXT
    r = subprocess.run(
        [sys.executable, "-m", "radar.mock_server", "--list-scenarios"],
        env=env, capture_output=True, text=True, timeout=5,
    )
    assert r.returncode == 0

def test_list_scenarios_contains_default(tmp_path):
    env = os.environ.copy()
    env["PYTHONPATH"] = RADAR_EXT
    r = subprocess.run(
        [sys.executable, "-m", "radar.mock_server", "--list-scenarios"],
        env=env, capture_output=True, text=True, timeout=5,
    )
    assert "default" in r.stdout

def test_list_scenarios_contains_all_blocked(tmp_path):
    env = os.environ.copy()
    env["PYTHONPATH"] = RADAR_EXT
    r = subprocess.run(
        [sys.executable, "-m", "radar.mock_server", "--list-scenarios"],
        env=env, capture_output=True, text=True, timeout=5,
    )
    assert "all-blocked" in r.stdout

def test_list_scenarios_mentions_replay(tmp_path):
    env = os.environ.copy()
    env["PYTHONPATH"] = RADAR_EXT
    r = subprocess.run(
        [sys.executable, "-m", "radar.mock_server", "--list-scenarios"],
        env=env, capture_output=True, text=True, timeout=5,
    )
    assert "replay" in r.stdout
