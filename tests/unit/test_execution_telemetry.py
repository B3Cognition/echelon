from __future__ import annotations

import json
from pathlib import Path

import pytest

from echelon.telemetry.model import ExecutionSpan, PhaseTimingEvent, TokenUsage
from echelon.telemetry.phase_timing import (
    main as phase_timing_main,
    record_phase_finish,
    record_phase_start,
)
from echelon.telemetry.store import TelemetryStore


pytestmark = pytest.mark.unit


def test_token_usage_preserves_known_components() -> None:
    usage = TokenUsage.from_mapping(
        {
            "input_tokens": 10,
            "output_tokens": 4,
            "reasoning_output_tokens": 2,
            "cache_read_input_tokens": 3,
        }
    )

    assert usage.total == 19
    assert usage.known is True


def test_missing_provider_usage_remains_unknown() -> None:
    usage = TokenUsage.unknown()

    assert usage.known is False
    assert usage.total is None


def test_store_writes_manifest_and_append_only_spans(tmp_path: Path) -> None:
    store = TelemetryStore(
        tmp_path,
        workflow="re",
        run_id="re-1",
        profile={"name": "balanced"},
        trace_id="a" * 32,
    )
    store.ensure_manifest()
    store.append_span(
        ExecutionSpan(
            trace_id="a" * 32,
            span_id="b" * 16,
            parent_span_id=None,
            name="re-extract-5-validate",
            start_time="2026-07-20T00:00:00Z",
            end_time="2026-07-20T00:00:01Z",
            duration_ms=1000,
            status="OK",
            attributes={"echelon.workflow.phase": "re-extract-5-validate"},
            token_usage=TokenUsage(input_tokens=10, output_tokens=2),
        )
    )

    manifest = json.loads((tmp_path / "telemetry/manifest.json").read_text())
    spans, diagnostics = store.read_spans()
    assert manifest["workflow"] == "re"
    assert manifest["trace_id"] == "a" * 32
    assert len(spans) == 1
    assert spans[0].token_usage.total == 12
    assert diagnostics == ()


def test_store_ignores_only_truncated_final_line(tmp_path: Path) -> None:
    store = TelemetryStore(
        tmp_path,
        workflow="re",
        run_id="re-1",
        profile={"name": "balanced"},
        trace_id="a" * 32,
    )
    path = tmp_path / "telemetry/spans.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text('{"trace_id":"bad"}\n{"trace_id":', encoding="utf-8")

    spans, diagnostics = store.read_spans()

    assert spans == ()
    assert len(diagnostics) == 2
    assert diagnostics[-1].code == "truncated-final-line"


def test_phase_timing_events_survive_a_later_state_replacement(tmp_path: Path) -> None:
    store = TelemetryStore(
        tmp_path,
        workflow="spec",
        run_id="spec-1",
        profile={"name": "banzai"},
        trace_id="a" * 32,
    )

    store.append_phase_timing(
        PhaseTimingEvent.started(
            trace_id="a" * 32,
            phase="phase2-decide",
            budget_seconds=1800,
            event_time="2026-07-20T18:00:00Z",
        )
    )
    (tmp_path / "state.json").write_text('{"phase":"phase2-decide"}\n', encoding="utf-8")
    (tmp_path / "state.json").write_text('{"phase":"phase3-plan"}\n', encoding="utf-8")
    store.append_phase_timing(
        PhaseTimingEvent.finished(
            trace_id="a" * 32,
            phase="phase2-decide",
            budget_seconds=1800,
            elapsed_seconds=1810,
            event_time="2026-07-20T18:30:10Z",
        )
    )

    events, diagnostics = store.read_phase_timings()

    assert diagnostics == ()
    assert [event.event for event in events] == ["started", "finished"]
    assert events[1].over_budget is False
    assert json.loads((tmp_path / "state.json").read_text()) == {"phase": "phase3-plan"}


def test_phase_timing_finish_uses_its_last_start_event(tmp_path: Path) -> None:
    store = TelemetryStore(
        tmp_path,
        workflow="spec",
        run_id="spec-1",
        profile={"name": "banzai"},
        trace_id="a" * 32,
    )

    record_phase_start(
        store,
        phase="phase2-decide",
        budget_seconds=60,
        event_time="2026-07-20T18:00:00Z",
    )
    finished = record_phase_finish(
        store,
        phase="phase2-decide",
        event_time="2026-07-20T18:01:13Z",
    )

    assert finished.elapsed_seconds == 73
    assert finished.over_budget is True


def test_phase_timing_start_is_idempotent_until_the_phase_finishes(tmp_path: Path) -> None:
    store = TelemetryStore(
        tmp_path,
        workflow="spec",
        run_id="spec-1",
        profile={"name": "banzai"},
        trace_id="a" * 32,
    )
    initial = record_phase_start(
        store,
        phase="phase4-build",
        budget_seconds=7200,
        event_time="2026-07-20T18:00:00Z",
    )
    repeated = record_phase_start(
        store,
        phase="phase4-build",
        budget_seconds=7200,
        event_time="2026-07-20T18:10:00Z",
    )
    finished = record_phase_finish(
        store,
        phase="phase4-build",
        event_time="2026-07-20T18:20:00Z",
    )
    events, diagnostics = store.read_phase_timings()

    assert diagnostics == ()
    assert repeated == initial
    assert [event.event for event in events] == ["started", "finished"]
    assert finished.elapsed_seconds == 1200


def test_phase_timing_cli_treats_missing_telemetry_as_a_non_blocking_diagnostic(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = phase_timing_main(
        ["start_phase", "phase2-decide", "300", "--run-dir", str(tmp_path)]
    )

    assert result == 0
    assert "phase timing diagnostic" in capsys.readouterr().err
