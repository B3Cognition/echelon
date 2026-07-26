from __future__ import annotations

from dataclasses import replace
import json

from echelon.telemetry.analyzer import RunAnalysis
from echelon.telemetry.health import analyze_spec_health
from echelon.telemetry.model import TokenUsage
from echelon.telemetry.render import health_to_json, render_health_text


def _report(
    run_id: str,
    *,
    created_at: str = "2026-07-20T00:00:00Z",
    status: str = "done",
    phase: str = "DONE",
    duration_ms: int | None = 1_000,
    tokens: int | None = 100,
    token_dispatches: tuple[int, int] = (1, 0),
    profile: str = "semi",
    provider: str = "codex",
    model: str = "gpt-test",
    dispatches: dict[str, object] | None = None,
    blockers: dict[str, dict[str, int]] | None = None,
    diagnostics: tuple[str, ...] = (),
) -> RunAnalysis:
    normalized_dispatches = dispatches or {
        "total": 1,
        "by_reason": {"initial": 1},
        "by_phase": {
            "phase1-what": {
                "total": 1,
                "by_reason": {"initial": 1},
                "max_attempt": 1,
                "errors": 0,
            }
        },
    }
    total_usage = (
        TokenUsage(reported_total_tokens=tokens)
        if tokens is not None
        else TokenUsage.unknown()
    )
    dimensions: dict[str, dict[str, dict[str, int]]] = {
        "by_provider": (
            {
                provider: {
                    "dispatches": 1,
                    "duration_ms": duration_ms or 0,
                    "tokens": tokens or 0,
                    "known_token_dispatches": token_dispatches[0],
                    "unknown_token_dispatches": token_dispatches[1],
                }
            }
            if provider
            else {}
        ),
        "by_model": (
            {
                model: {
                    "dispatches": 1,
                    "duration_ms": duration_ms or 0,
                    "tokens": tokens or 0,
                    "known_token_dispatches": token_dispatches[0],
                    "unknown_token_dispatches": token_dispatches[1],
                }
            }
            if model
            else {}
        ),
    }
    return RunAnalysis(
        schema_version=1,
        run_id=run_id,
        workflow="spec",
        status=status,
        phase=phase,
        profile={"name": profile, "autonomy_mode": profile},
        source_count=0,
        domain_count=0,
        domain_repairs_by_source={},
        partial_debt_source_count=0,
        tokens=total_usage,
        known_token_dispatches=token_dispatches[0],
        unknown_token_dispatches=token_dispatches[1],
        active_duration_ms=duration_ms,
        wall_clock_duration_ms=None,
        by_phase={},
        dimensions=dimensions,
        workflow_metrics={
            "spec_id": "001-demo",
            "dispatches": normalized_dispatches,
            "blockers_by_phase": blockers or {},
            "phase_order": list(normalized_dispatches.get("by_phase", {})),
            "recency": {"value": created_at, "source": "state.created_at"},
        },
        diagnostics=diagnostics,
    )


def test_health_is_insufficient_without_dispatch_telemetry() -> None:
    report = _report(
        "spec-1",
        dispatches={"total": 0, "by_reason": {}, "by_phase": {}},
        provider="",
        model="",
    )

    health = analyze_spec_health((report,))

    assert health.state == "INSUFFICIENT_DATA"
    assert health.cohort["latest_run"] == "spec-1"
    assert health.findings[0].code == "telemetry.dispatches_unavailable"
    assert health.findings[0].severity == "warning"


def test_health_reports_blocked_runs_and_phase_exceptions() -> None:
    report = _report(
        "spec-2",
        status="blocked",
        phase="terminal-blocked",
        dispatches={
            "total": 5,
            "by_reason": {
                "initial": 1,
                "deterministic_repair": 2,
                "manual_rerun": 1,
                "provider_retry": 1,
            },
            "by_phase": {
                "phase1-lexicon": {
                    "total": 5,
                    "by_reason": {
                        "initial": 1,
                        "deterministic_repair": 2,
                        "manual_rerun": 1,
                        "provider_retry": 1,
                    },
                    "max_attempt": 4,
                    "errors": 2,
                }
            },
        },
        blockers={"phase1-lexicon": {"lexicon_gate_exhausted": 2}},
    )

    health = analyze_spec_health((report,))

    assert health.state == "DEGRADED"
    assert health.summary["blocked_runs"] == 1
    assert health.phase_observations["phase1-lexicon"] == {
        "dispatches": 5,
        "repairs": 2,
        "manual_reruns": 1,
        "provider_retries": 1,
        "errors": 2,
        "max_attempt": 4,
        "blockers": {"lexicon_gate_exhausted": 2},
    }
    assert any(
        finding.code == "reliability.blocked_runs"
        and finding.severity == "critical"
        for finding in health.findings
    )
    assert any(
        finding.code == "convergence.phase_repairs"
        and finding.subject == "phase1-lexicon"
        for finding in health.findings
    )
    assert any(
        finding.code == "reliability.blocker"
        and finding.subject == "phase1-lexicon:lexicon_gate_exhausted"
        for finding in health.findings
    )


def test_health_selects_latest_compatible_cohort_deterministically() -> None:
    older = _report("spec-z", created_at="2026-07-20T00:00:00Z")
    latest = _report("spec-a", created_at="2026-07-21T00:00:00Z")
    other_profile = _report(
        "spec-other",
        created_at="2026-07-19T00:00:00Z",
        profile="banzai",
    )
    other_model = _report(
        "spec-model",
        created_at="2026-07-18T00:00:00Z",
        model="gpt-other",
    )

    health = analyze_spec_health(
        (other_model, latest, other_profile, older)
    )

    assert health.cohort["latest_run"] == "spec-a"
    assert health.cohort["eligible_runs"] == 2
    assert health.cohort["discovered_runs"] == 4
    assert health.excluded_runs == {
        "model_mismatch": 1,
        "profile_mismatch": 1,
    }


def test_health_marks_partial_telemetry_and_orders_findings_stably() -> None:
    report = _report(
        "spec-1",
        token_dispatches=(1, 1),
        diagnostics=("invalid span at line 2",),
    )

    first = analyze_spec_health((report,))
    second = analyze_spec_health((report,))

    assert first == second
    assert first.state == "DEGRADED"
    assert [finding.severity for finding in first.findings] == [
        "warning",
        "warning",
    ]
    assert {finding.code for finding in first.findings} == {
        "telemetry.partial_tokens",
        "telemetry.diagnostics",
    }


def test_performance_regressions_require_five_eligible_observations() -> None:
    historical = (
        _report(
            "spec-1",
            created_at="2026-07-20T00:00:01Z",
            duration_ms=100,
            tokens=100,
        ),
        _report(
            "spec-2",
            created_at="2026-07-20T00:00:02Z",
            duration_ms=110,
            tokens=110,
        ),
        _report(
            "spec-3",
            created_at="2026-07-20T00:00:03Z",
            duration_ms=120,
            tokens=120,
        ),
        _report(
            "spec-4",
            created_at="2026-07-20T00:00:04Z",
            duration_ms=130,
            tokens=130,
        ),
    )
    latest = _report(
        "spec-5",
        created_at="2026-07-20T00:00:05Z",
        duration_ms=300,
        tokens=300,
    )

    four_run_health = analyze_spec_health(historical[:-1] + (latest,))
    five_run_health = analyze_spec_health(historical + (latest,))

    assert not any(
        finding.code.startswith("performance.")
        for finding in four_run_health.findings
    )
    performance_codes = {
        finding.code
        for finding in five_run_health.findings
        if finding.code.startswith("performance.")
    }
    assert performance_codes == {
        "performance.active_duration_regression",
        "performance.token_regression",
    }
    assert all(
        finding.severity == "info"
        for finding in five_run_health.findings
        if finding.code.startswith("performance.")
    )
    assert five_run_health.state == "HEALTHY"


def test_unknown_identity_is_not_used_for_cross_run_comparison() -> None:
    unknown_old = _report(
        "spec-1",
        created_at="2026-07-20T00:00:00Z",
        provider="",
        model="",
    )
    unknown_latest = replace(
        unknown_old,
        run_id="spec-2",
        workflow_metrics={
            **unknown_old.workflow_metrics,
            "recency": {
                "value": "2026-07-21T00:00:00Z",
                "source": "state.created_at",
            },
        },
    )

    health = analyze_spec_health((unknown_old, unknown_latest))

    assert health.cohort["latest_run"] == "spec-2"
    assert health.cohort["eligible_runs"] == 1
    assert health.excluded_runs == {"identity_unavailable": 1}
    assert any(
        finding.code == "telemetry.identity_unavailable"
        for finding in health.findings
    )


def test_health_renderers_are_stable_and_expose_the_same_conclusions() -> None:
    health = analyze_spec_health(
        (
            _report(
                "spec-1",
                status="blocked",
                phase="terminal-blocked",
                blockers={"phase1-lexicon": {"lexicon_gate_exhausted": 1}},
            ),
        )
    )

    json_output = health_to_json(health)
    text_output = render_health_text(health)
    payload = json.loads(json_output)

    assert payload["schema_version"] == 1
    assert payload["workflow"] == "spec"
    assert payload["state"] == health.state
    assert [item["code"] for item in payload["findings"]] == [
        finding.code for finding in health.findings
    ]
    assert "SPEC TELEMETRY HEALTH" in text_output
    assert f"State: {health.state}" in text_output
    assert f"Latest run: {health.cohort['latest_run']}" in text_output
    assert health.findings[0].code in text_output
    assert "phase1-lexicon" in text_output
    assert "lexicon_gate_exhausted=1" in text_output
    assert health_to_json(health) == json_output
    assert render_health_text(health) == text_output


def test_health_text_renders_exclusions_and_diagnostics() -> None:
    report = _report(
        "spec-1",
        diagnostics=("truncated final telemetry line",),
    )
    other = _report(
        "spec-2",
        created_at="2026-07-19T00:00:00Z",
        profile="banzai",
    )

    text_output = render_health_text(analyze_spec_health((other, report)))

    assert "Excluded runs: profile_mismatch=1" in text_output
    assert "Data limitations:" in text_output
    assert "truncated final telemetry line" in text_output
