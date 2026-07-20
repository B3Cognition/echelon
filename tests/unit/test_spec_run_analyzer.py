from __future__ import annotations

import json
from pathlib import Path

from echelon.telemetry.model import ExecutionSpan, TokenUsage
from echelon.telemetry.render import render_analysis_text
from echelon.telemetry.spec_adapter import analyze_spec_run, analyze_spec_runs
from echelon.telemetry.store import TelemetryStore


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value) + "\n", encoding="utf-8")


def _spec_run(root: Path, name: str = "spec-1") -> Path:
    run = root / name
    _write_json(
        run / "state.json",
        {
            "run_id": name,
            "status": "done",
            "phase": "DONE",
            "token_usage": 12,
            "spec_id": "001-demo",
            "why_fail_count": 2,
            "what_repair_count": 1,
            "plan_repair_count": 3,
            "blocked_reason_history": ["traceability", "traceability", "coverage"],
        },
    )
    return run


def test_spec_analysis_aggregates_phase_agent_model_and_loops(tmp_path: Path) -> None:
    run = _spec_run(tmp_path)
    store = TelemetryStore(
        run,
        workflow="spec",
        run_id="spec-1",
        profile={"name": "banzai"},
        trace_id="a" * 32,
    )
    for index, (phase, agent, kind, model, tokens) in enumerate(
        (
            ("phase1-what", "CARTOGRAPHER", "phase", "sonnet", 10),
            ("phase1-why1", "SAGE", "repair", "sonnet", 2),
        )
    ):
        store.append_span(
            ExecutionSpan(
                trace_id="a" * 32,
                span_id=f"{index + 1:016x}",
                parent_span_id=None,
                name=phase,
                start_time=f"2026-07-20T00:00:0{index}Z",
                end_time=f"2026-07-20T00:00:0{index + 1}Z",
                duration_ms=1000,
                status="OK",
                attributes={
                    "echelon.workflow.phase": phase,
                    "echelon.agent.name": agent,
                    "echelon.dispatch.kind": kind,
                    "gen_ai.response.model": model,
                },
                token_usage=TokenUsage(reported_total_tokens=tokens),
            )
        )

    for index, phase in enumerate(("phase1-why1", "phase1-why2", "phase1-what", "phase3-plan", "phase3-plan", "phase3-plan")):
        store.append_event({"schema_version": 1, "type": "dispatch", "trace_id": "a" * 32, "phase": phase, "agent": "test", "attempt": index + 1, "reason": "initial", "outcome": "OK", "event_time": "2026-07-20T00:00:00Z", "started_at": "2026-07-20T00:00:00Z", "ended_at": "2026-07-20T00:00:00Z", "duration_ms": 0, "model": "test", "blocker": ""})
    for _ in range(2):
        store.append_event({"schema_version": 1, "type": "blocker", "trace_id": "a" * 32, "phase": "phase1-why1", "reason": "traceability", "event_time": "2026-07-20T00:00:00Z"})

    _write_json(run / "state.json", {"run_id": "spec-1", "status": "done", "phase": "DONE", "spec_id": "001-demo", "why_fail_count": 0, "what_repair_count": 0, "plan_repair_count": 0, "blocked_reason_history": []})

    report = analyze_spec_run(run)

    assert report.workflow == "spec"
    assert report.tokens.total == 12
    assert report.dimensions["by_agent"]["CARTOGRAPHER"]["tokens"] == 10
    assert report.dimensions["by_model"]["sonnet"]["dispatches"] == 2
    assert report.workflow_metrics["repair_loops"] == {"why": 2, "what": 1, "plan": 3}
    assert report.workflow_metrics["repeated_blockers"] == {"traceability": 2}


def test_spec_analysis_does_not_treat_budget_counter_as_telemetry(tmp_path: Path) -> None:
    run = _spec_run(tmp_path / "runs", "spec-2")
    _write_json(tmp_path / "runs/re-1/state.json", {"run_id": "re-1"})

    report = analyze_spec_run(run)
    reports = analyze_spec_runs(tmp_path / "runs")

    assert report.tokens.total is None
    assert report.tokens.known is False
    assert report.to_json_dict()["tokens"]["status"] == "unavailable"
    assert report.to_json_dict()["tokens"]["coverage"] is None
    assert report.provenance["tokens"] == "unavailable"
    assert "telemetry spans are unavailable" in report.diagnostics
    assert [item.run_id for item in reports] == ["spec-2"]


def test_spec_analysis_marks_mixed_dispatch_usage_as_partial(tmp_path: Path) -> None:
    run = _spec_run(tmp_path)
    store = TelemetryStore(
        run,
        workflow="spec",
        run_id="spec-1",
        profile={"name": "balanced"},
        trace_id="a" * 32,
    )
    for index, usage in enumerate(
        (TokenUsage(reported_total_tokens=10), TokenUsage.unknown())
    ):
        store.append_span(
            ExecutionSpan(
                trace_id="a" * 32,
                span_id=f"{index + 1:016x}",
                parent_span_id=None,
                name="phase1-what",
                start_time=f"2026-07-20T00:00:0{index}Z",
                end_time=f"2026-07-20T00:00:0{index + 1}Z",
                duration_ms=1000,
                status="OK",
                token_usage=usage,
            )
        )

    report = analyze_spec_run(run)

    assert report.tokens.total == 10
    assert report.known_token_dispatches == 1
    assert report.unknown_token_dispatches == 1
    assert report.token_coverage == 0.5
    assert report.to_json_dict()["tokens"]["status"] == "partial"
    assert "Token usage: 10 observed (partial; 1/2 dispatches reported)" in render_analysis_text(report)
    assert "10 tokens observed (partial; 1/2 dispatches reported)" in render_analysis_text(report)
