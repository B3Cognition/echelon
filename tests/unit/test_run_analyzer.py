from __future__ import annotations

import json
from pathlib import Path

import pytest

from echelon.telemetry.re_adapter import analyze_re_run
from echelon.telemetry.render import analysis_to_json, render_analysis_text


pytestmark = pytest.mark.unit


def _legacy_run(tmp_path: Path) -> Path:
    run = tmp_path / "re-legacy"
    (run / "re/workspace").mkdir(parents=True)
    (run / "state.json").write_text(
        json.dumps({"run_id": run.name, "run_kind": "re", "status": "blocked"}),
        encoding="utf-8",
    )
    prosaic_repairs = {f"domain-{index}": 5 for index in range(1, 12)}
    (run / "re/state.json").write_text(
        json.dumps(
            {
                "run_id": run.name,
                "status": "blocked",
                "phase": "re-extract-5-validate",
                "re_source_budgets": {
                    "max_domain_repairs": 5,
                    "max_source_cycles": 5,
                    "max_source_reanalysis": 5,
                },
                "re_source_states": {
                    "agent-registry-starter": {
                        "status": "partial_quality_debt",
                        "domain_repairs": {"scripts": 6},
                    },
                    "prosaic": {
                        "status": "partial_quality_debt",
                        "domain_repairs": prosaic_repairs,
                    },
                    "ruler": {"status": "passed", "domain_repairs": {}},
                    "spec-kit-skills-agents": {
                        "status": "passed",
                        "domain_repairs": {},
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    (run / "re/workspace/architecture-map.json").write_text(
        json.dumps({"domains": [{"domain_id": f"d-{index}"} for index in range(19)]}),
        encoding="utf-8",
    )
    return run


def test_legacy_baseline_reports_observed_facts_without_inventing_usage(
    tmp_path: Path,
) -> None:
    report = analyze_re_run(_legacy_run(tmp_path))

    assert report.source_count == 4
    assert report.domain_count == 19
    assert report.domain_repairs_by_source["prosaic"] == 55
    assert report.partial_debt_source_count == 2
    assert report.tokens.known is False
    assert report.active_duration_ms is None
    assert report.profile["name"] == "legacy"
    assert report.compliance["token_ceiling"] == "unknown"


def test_analyzer_aggregates_telemetry_by_phase(tmp_path: Path) -> None:
    run = _legacy_run(tmp_path)
    telemetry = run / "telemetry"
    telemetry.mkdir()
    (telemetry / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "workflow": "re",
                "run_id": run.name,
                "trace_id": "a" * 32,
                "profile": {"name": "balanced", "hard_token_limit": 100},
            }
        ),
        encoding="utf-8",
    )
    record = {
        "schema_version": 1,
        "trace_id": "a" * 32,
        "span_id": "b" * 16,
        "parent_span_id": None,
        "name": "re-extract-5-validate",
        "start_time": "2026-07-20T00:00:00Z",
        "end_time": "2026-07-20T00:00:01Z",
        "duration_ms": 1000,
        "status": "OK",
        "attributes": {"echelon.workflow.phase": "re-extract-5-validate"},
        "token_usage": {"input_tokens": 10, "output_tokens": 2, "total_tokens": 12},
    }
    (telemetry / "spans.jsonl").write_text(json.dumps(record) + "\n", encoding="utf-8")

    report = analyze_re_run(run)

    assert report.tokens.total == 12
    assert report.by_phase["re-extract-5-validate"]["tokens"] == 12
    assert report.by_phase["re-extract-5-validate"]["duration_ms"] == 1000


def test_re_analysis_does_not_treat_controller_counters_as_telemetry(
    tmp_path: Path,
) -> None:
    run = _legacy_run(tmp_path)
    outer_path = run / "state.json"
    outer = json.loads(outer_path.read_text(encoding="utf-8"))
    outer["token_usage"] = 500
    outer_path.write_text(json.dumps(outer), encoding="utf-8")
    inner_path = run / "re/state.json"
    inner = json.loads(inner_path.read_text(encoding="utf-8"))
    inner["re_token_usage"] = 700
    inner["re_unknown_token_dispatches"] = 3
    inner_path.write_text(json.dumps(inner), encoding="utf-8")

    report = analyze_re_run(run)

    assert report.tokens.total is None
    assert report.known_token_dispatches == 0
    assert report.unknown_token_dispatches == 0
    assert report.to_json_dict()["tokens"]["status"] == "unavailable"


def test_text_and_json_renderers_are_stable_and_expose_limitations(tmp_path: Path) -> None:
    report = analyze_re_run(_legacy_run(tmp_path))

    payload = json.loads(analysis_to_json(report))
    text = render_analysis_text(report)

    assert payload["schema_version"] == 1
    assert payload["run_id"] == "re-legacy"
    assert "Token usage: unavailable" in text
    assert "Active duration: unknown" in text
