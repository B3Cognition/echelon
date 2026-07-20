"""Stable human and machine renderers for run analysis."""

from __future__ import annotations

import json

from echelon.telemetry.analyzer import RunAnalysis


def analysis_to_json(analysis: RunAnalysis) -> str:
    return json.dumps(analysis.to_json_dict(), indent=2, sort_keys=True) + "\n"


def render_analysis_text(analysis: RunAnalysis) -> str:
    token_text = (
        f"{analysis.tokens.total:,}" if analysis.tokens.total is not None else "unknown"
    )
    active_text = (
        _duration(analysis.active_duration_ms)
        if analysis.active_duration_ms is not None
        else "unknown"
    )
    lines = [
        f"RE run: {analysis.run_id}",
        f"Status: {analysis.status} · phase {analysis.phase}",
        f"Profile: {analysis.profile.get('name', 'legacy')}",
        f"Token usage: {token_text}",
        f"Active duration: {active_text}",
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
        "Compliance: "
        + ", ".join(f"{key}={value}" for key, value in analysis.compliance.items()),
    ]
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
            f"{values['tokens']:,} tokens, {_duration(values['duration_ms'])}"
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
