from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from echelon.telemetry.store import TelemetryStore
from harness.phase_graph import PhaseGraph
from harness.squad import SquadController
from harness.squad_state import SquadStateStore
from unittest.mock import MagicMock


pytestmark = pytest.mark.unit

ROOT = Path(__file__).parents[2]
SCRIPT = ROOT / "extension/scripts/bash/phase-timing.sh"
DEFINITION = ROOT / "extension/workflow/definition.yaml"
EXTENSION = ROOT / "extension/extension.yml"


def _controller(tmp_path: Path) -> SquadController:
    run_dir = tmp_path / "runs" / "spec-1"
    state_store = SquadStateStore(run_dir)
    state_store.initialize("spec-1", "greenfield", "msg", 0, "phase2-decide")
    return SquadController(
        provider=MagicMock(),
        state_store=state_store,
        phase_graph=PhaseGraph(DEFINITION, EXTENSION),
        ext_dir=ROOT / "extension",
        project_root=tmp_path,
        squad_dir=run_dir,
    )


def test_controller_owns_declared_phase_timing_lifecycle(tmp_path: Path) -> None:
    controller = _controller(tmp_path)
    graph = controller._graph

    controller._ensure_telemetry_manifest()
    controller._start_declared_phase_timing(graph.get("phase2-decide"))
    controller._apply_declared_phase_timing_transition(
        graph.get("phase3-specialists"), "phase3-how"
    )
    controller._apply_declared_phase_timing_transition(
        graph.get("phase3-plan"), "phase3-understanding"
    )
    controller._apply_declared_phase_timing_transition(
        graph.get("phase4-document"), "done"
    )

    events, diagnostics = controller._telemetry_store.read_phase_timings()
    assert diagnostics == ()
    assert [(event.phase, event.event) for event in events] == [
        ("phase2-decide", "started"),
        ("phase2-decide", "finished"),
        ("phase3-solution", "started"),
        ("phase3-solution", "finished"),
        ("phase4-build", "started"),
        ("phase4-build", "finished"),
    ]


def test_controller_does_not_transition_timing_on_phase_self_loop(tmp_path: Path) -> None:
    controller = _controller(tmp_path)
    node = controller._graph.get("phase3-plan")

    controller._ensure_telemetry_manifest()
    controller._apply_declared_phase_timing_transition(node, node.id)

    events, diagnostics = controller._telemetry_store.read_phase_timings()
    assert diagnostics == ()
    assert events == ()


def test_controller_recovers_missing_prior_timing_start_on_resume(tmp_path: Path) -> None:
    controller = _controller(tmp_path)

    controller._ensure_telemetry_manifest()
    controller._apply_declared_phase_timing_transition(
        controller._graph.get("phase3-plan"), "phase3-understanding"
    )

    events, diagnostics = controller._telemetry_store.read_phase_timings()
    assert diagnostics == ()
    assert [(event.phase, event.event) for event in events] == [
        ("phase3-solution", "started"),
        ("phase3-solution", "finished"),
        ("phase4-build", "started"),
    ]


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
