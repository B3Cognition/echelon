from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import json
import os
import subprocess
import threading
from pathlib import Path

import pytest

from echelon.telemetry.model import PhaseTimingEvent
from echelon.telemetry.phase_timing import record_phase_start
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
        graph.get("phase3-plan"), "phase3-tasks-lexicon"
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
        controller._graph.get("phase3-plan"), "phase3-tasks-lexicon"
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


def test_completion_timing_keeps_legacy_event_serialization_unchanged() -> None:
    event = PhaseTimingEvent.started(
        trace_id="a" * 32,
        phase="phase3-solution",
        budget_seconds=300,
        event_time="2026-07-23T10:00:00Z",
    )

    record = event.to_json_dict()

    assert "completion_id" not in record
    assert "effect_id" not in record
    assert PhaseTimingEvent.from_json_dict(record) == event


def test_completion_timing_identity_round_trips() -> None:
    completion_id = "b" * 32
    effect_id = (
        f"{completion_id}:timing:open:phase4-build"
    )
    event = PhaseTimingEvent.started(
        trace_id="a" * 32,
        phase="phase4-build",
        budget_seconds=600,
        event_time="2026-07-23T10:00:00Z",
        completion_id=completion_id,
        effect_id=effect_id,
    )

    assert PhaseTimingEvent.from_json_dict(
        event.to_json_dict()
    ) == event


@pytest.mark.parametrize(
    ("event", "effect_suffix"),
    [
        ("started", "close:phase4-build"),
        ("started", "open:other-phase"),
        ("started", "resume:phase4-build"),
        ("finished", "open:phase4-build"),
    ],
)
def test_completion_timing_rejects_effect_identity_semantic_drift(
    event: str,
    effect_suffix: str,
) -> None:
    completion_id = "b" * 32
    record = {
        "schema_version": 1,
        "type": "phase_timing",
        "trace_id": "a" * 32,
        "phase": "phase4-build",
        "event": event,
        "event_time": "2026-07-23T10:00:00Z",
        "budget_seconds": 600,
        "elapsed_seconds": None if event == "started" else 1.0,
        "over_budget": None if event == "started" else False,
        "completion_id": completion_id,
        "effect_id": f"{completion_id}:timing:{effect_suffix}",
    }

    with pytest.raises(ValueError, match="completion identity"):
        PhaseTimingEvent.from_json_dict(record)


def test_completion_timing_two_stores_share_one_effect_transaction(
    tmp_path: Path,
) -> None:
    stores = [
        TelemetryStore(
            tmp_path,
            workflow="spec",
            run_id="run-1",
            profile={"name": "banzai"},
            trace_id="a" * 32,
        )
        for _ in range(2)
    ]
    stores[0].ensure_manifest()
    first_locked = threading.Event()
    release_first = threading.Event()
    second_attempted = threading.Event()
    second_read = threading.Event()
    first_transaction = stores[0].phase_timing_transaction
    second_transaction = stores[1].phase_timing_transaction
    second_reader = stores[1]._read_phase_timings_unlocked

    @contextmanager
    def held_first_transaction():
        with first_transaction() as snapshot:
            first_locked.set()
            assert release_first.wait(timeout=2)
            yield snapshot

    @contextmanager
    def observed_second_transaction():
        second_attempted.set()
        with second_transaction() as snapshot:
            yield snapshot

    def observed_second_read():
        second_read.set()
        return second_reader()

    stores[0].phase_timing_transaction = (  # type: ignore[method-assign]
        held_first_transaction
    )
    stores[1].phase_timing_transaction = (  # type: ignore[method-assign]
        observed_second_transaction
    )
    stores[1]._read_phase_timings_unlocked = (  # type: ignore[method-assign]
        observed_second_read
    )
    completion_id = "d" * 32
    effect_id = f"{completion_id}:timing:open:phase4-build"

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(
            record_phase_start,
            stores[0],
            phase="phase4-build",
            budget_seconds=600,
            completion_id=completion_id,
            effect_id=effect_id,
        )
        assert first_locked.wait(timeout=2)
        second = executor.submit(
            record_phase_start,
            stores[1],
            phase="phase4-build",
            budget_seconds=600,
            completion_id=completion_id,
            effect_id=effect_id,
        )
        assert second_attempted.wait(timeout=2)
        assert not second_read.wait(timeout=0.1)
        release_first.set()
        first.result(timeout=5)
        second.result(timeout=5)
        assert second_read.is_set()

    fresh = TelemetryStore(
        tmp_path,
        workflow="spec",
        run_id="run-1",
        profile={"name": "banzai"},
        trace_id="a" * 32,
    )
    events, diagnostics = fresh.read_phase_timings()
    assert diagnostics == ()
    assert [event.effect_id for event in events] == [effect_id]
