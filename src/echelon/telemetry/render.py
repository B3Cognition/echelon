"""Stable human and machine renderers for run analysis."""

from __future__ import annotations

import json

from echelon.telemetry.analyzer import RunAnalysis


def analysis_to_json(analysis: RunAnalysis) -> str:
    return json.dumps(analysis.to_json_dict(), indent=2, sort_keys=True) + "\n"


def render_analysis_text(analysis: RunAnalysis) -> str:
    token_text = _token_text(analysis)
    active_text = (
        _duration(analysis.active_duration_ms)
        if analysis.active_duration_ms is not None
        else "unknown"
    )
    lines = [
        f"{analysis.workflow.upper()} run: {analysis.run_id}",
        f"Status: {analysis.status} · phase {analysis.phase}",
        f"Profile: {analysis.profile.get('name', 'legacy')}",
        f"Token usage: {token_text}",
        f"Active duration: {active_text}",
    ]
    if analysis.workflow == "re":
        lines.extend(
            [
                f"Sources/domains: {analysis.source_count}/{analysis.domain_count}",
                f"Partial quality-debt sources: {analysis.partial_debt_source_count}",
                f"Semantic audit: {analysis.semantic_audit_status}",
                "First-pass repair rate: "
                + (
                    f"{analysis.first_pass_repair_rate:.1%}"
                    if analysis.first_pass_repair_rate is not None
                    else "not evaluated"
                ),
                "Validator dispatches/domain: "
                + (
                    f"{analysis.validator_dispatches_per_domain:.2f}"
                    if analysis.validator_dispatches_per_domain is not None
                    else "not evaluated"
                ),
                f"Repeated finding records: {analysis.repeated_finding_count}",
            ]
        )
    else:
        loops = analysis.workflow_metrics.get("repair_loops", {})
        lines.append(f"Spec: {analysis.workflow_metrics.get('spec_id', 'unknown')}")
        if isinstance(loops, dict):
            lines.append(
                "Repair loops: "
                + ", ".join(f"{key}={value}" for key, value in loops.items())
            )
    if analysis.compliance:
        lines.append(
            "Compliance: "
            + ", ".join(f"{key}={value}" for key, value in analysis.compliance.items())
        )
    if analysis.domain_repairs_by_source:
        lines.append("Domain repairs:")
        lines.extend(
            f"  {source}: {count}"
            for source, count in analysis.domain_repairs_by_source.items()
        )
    if analysis.by_phase:
        lines.append("Phase cost:")
        lines.extend(
            f"  {phase}: {values['dispatches']} dispatches, "
            f"{_bucket_token_text(values)}, {_duration(values['duration_ms'])}"
            for phase, values in analysis.by_phase.items()
        )
    if analysis.diagnostics:
        lines.append("Limitations:")
        lines.extend(f"  - {item}" for item in analysis.diagnostics)
    return "\n".join(lines) + "\n"


def _duration(milliseconds: int) -> str:
    seconds = milliseconds / 1000
    if seconds < 60:
        return f"{seconds:.1f}s"
    return f"{seconds / 60:.1f}m"


def _token_text(analysis: RunAnalysis) -> str:
    if analysis.tokens.total is None:
        return "unavailable"
    total = f"{analysis.tokens.total:,}"
    if analysis.token_status != "partial":
        return total
    dispatches = analysis.known_token_dispatches + analysis.unknown_token_dispatches
    return (
        f"{total} observed (partial; {analysis.known_token_dispatches}/"
        f"{dispatches} dispatches reported)"
    )


def _bucket_token_text(values: dict[str, int]) -> str:
    total = f"{values['tokens']:,} tokens"
    unknown = values.get("unknown_token_dispatches", 0)
    if not unknown:
        return total
    return f"{total} observed (partial; {values.get('known_token_dispatches', 0)}/{values['dispatches']} dispatches reported)"
