from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from echelon.telemetry.store import TelemetryStore


pytestmark = pytest.mark.unit

ROOT = Path(__file__).parents[2]
SCRIPT = ROOT / "extension/scripts/bash/phase-timing.sh"


def test_phase_timing_script_does_not_mutate_controller_state(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs/spec-1"
    state_path = run_dir / "state.json"
    run_dir.mkdir(parents=True)
    original_state = '{"phase":"phase2-decide","run_id":"spec-1"}\n'
    state_path.write_text(original_state, encoding="utf-8")
    store = TelemetryStore(
        run_dir,
        workflow="spec",
        run_id="spec-1",
        profile={"name": "banzai"},
        trace_id="a" * 32,
    )
    store.ensure_manifest()
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "src") + os.pathsep + env.get("PYTHONPATH", "")

    subprocess.run(
        [
            "bash",
            str(SCRIPT),
            "start_phase",
            "phase2-decide",
            "300",
            "--state-file",
            str(state_path),
        ],
        check=True,
        env=env,
    )

    events, diagnostics = store.read_phase_timings()
    assert state_path.read_text(encoding="utf-8") == original_state
    assert diagnostics == ()
    assert [(event.phase, event.event) for event in events] == [
        ("phase2-decide", "started")
    ]


def test_split_metrics_script_records_an_event_without_mutating_state(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs/spec-1"
    state_path = run_dir / "state.json"
    run_dir.mkdir(parents=True)
    original_state = '{"phase":"phase4-build","run_id":"spec-1"}\n'
    state_path.write_text(original_state, encoding="utf-8")
    store = TelemetryStore(
        run_dir,
        workflow="spec",
        run_id="spec-1",
        profile={"name": "banzai"},
        trace_id="a" * 32,
    )
    store.ensure_manifest()
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "src") + os.pathsep + env.get("PYTHONPATH", "")

    subprocess.run(
        [
            "bash",
            str(SCRIPT),
            "record_split_metrics",
            "2",
            "1",
            "0.75",
            "--state-file",
            str(state_path),
        ],
        check=True,
        env=env,
    )

    records = [
        json.loads(line)
        for line in (run_dir / "telemetry/events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert state_path.read_text(encoding="utf-8") == original_state
    assert records[0]["type"] == "split_metrics"
    assert records[0]["qa_coverage"] == 0.75
