"""Optional local run-analysis projection for the generated human wiki."""

from __future__ import annotations

from pathlib import Path

from echelon.telemetry.analyzer import RunAnalysis
from echelon.telemetry.re_adapter import analyze_re_runs
from echelon.telemetry.spec_adapter import analyze_spec_runs


def render_operations(project_root: Path, output_dir: Path) -> tuple[str, ...]:
    reports = analyze_re_runs(project_root / "runs") + analyze_spec_runs(
        project_root / "runs"
    )
    if not reports:
        return ()
    pages: list[str] = []
    index_lines = [
        "# Local Operations",
        "",
        "> This section is local and ephemeral. It is derived from ignored run state, not canonical published artifacts.",
        "",
        "## Local workflow runs",
        "",
    ]
    for report in reports:
        directory = "RE Runs" if report.workflow == "re" else "Spec Runs"
        relative = f"Operations/{directory}/{report.run_id}.md"
        index_lines.append(
            f"- [{report.run_id}]({directory.replace(' ', '%20')}/{report.run_id}.md) "
            f"— {report.workflow} · {report.status}"
        )
        _write(output_dir, relative, _run_page(report))
        pages.append(relative)
    _write(output_dir, "Operations/Index.md", "\n".join(index_lines))
    pages.append("Operations/Index.md")
    views = {
        "Views/Performance.md": _performance(reports),
        "Views/Token Usage.md": _tokens(reports),
        "Views/Repeated Findings.md": _repeated(reports),
        "Views/Quality Debt.md": _debt(reports),
        "Views/Spec Repair Loops.md": _spec_repairs(reports),
    }
    for relative, content in views.items():
        _write(output_dir, relative, content)
        pages.append(relative)
    return tuple(sorted(pages))


def _run_page(report: RunAnalysis) -> str:
    token = _token_summary(report)
    active = (
        f"{report.active_duration_ms / 60_000:.1f} minutes"
        if report.active_duration_ms is not None
        else "unknown"
    )
    lines = [
        f"# {report.run_id}",
        "",
        "> Local and ephemeral run analysis. Rebuild with `echelon wiki build --include-runs`.",
        "",
        f"- Status: `{report.status}`",
        f"- Phase: `{report.phase}`",
        f"- Profile: `{report.profile.get('name', 'legacy')}`",
        f"- Token usage: {token}",
        f"- Active duration: {active}",
        f"- Sources/domains: {report.source_count}/{report.domain_count}",
        f"- Partial quality-debt sources: {report.partial_debt_source_count}",
        f"- Semantic audit: `{report.semantic_audit_status}`",
        "- First-pass repair rate: "
        + (f"{report.first_pass_repair_rate:.1%}" if report.first_pass_repair_rate is not None else "not evaluated"),
        "- Validator dispatches/domain: "
        + (f"{report.validator_dispatches_per_domain:.2f}" if report.validator_dispatches_per_domain is not None else "not evaluated"),
        f"- Published baseline: `{report.baseline.get('status', 'unknown')}` generation {report.baseline.get('generation', 0)}",
        "",
        "## Profile compliance",
        "",
    ]
    lines.extend(f"- {key.replace('_', ' ')}: `{value}`" for key, value in report.compliance.items())
    lines.extend(["", "## Domain repairs", ""])
    lines.extend(
        f"- `{source}`: {count}" for source, count in report.domain_repairs_by_source.items()
    )
    if report.by_phase:
        lines.extend(["", "## Phase cost", "", "| Phase | Dispatches | Tokens | Duration |", "|---|---:|---:|---:|"])
        lines.extend(
            f"| `{phase}` | {values['dispatches']} | {_bucket_tokens(values)} | {values['duration_ms'] / 1000:.1f}s |"
            for phase, values in report.by_phase.items()
        )
    if report.workflow == "spec":
        loops = report.workflow_metrics.get("repair_loops", {})
        lines.extend(["", "## Repair loops", ""])
        if isinstance(loops, dict):
            lines.extend(f"- {name}: {count}" for name, count in loops.items())
        blockers = report.workflow_metrics.get("repeated_blockers", {})
        lines.extend(["", "## Repeated blockers", ""])
        if isinstance(blockers, dict) and blockers:
            lines.extend(f"- {name}: {count}" for name, count in blockers.items())
        else:
            lines.append("No repeated blockers were recorded.")
    if report.diagnostics:
        lines.extend(["", "## Data limitations", ""])
        lines.extend(f"- {item}" for item in report.diagnostics)
    lines.extend(["", "Source run path:", "", f"`runs/{report.run_id}/`"])
    return "\n".join(lines)


def _performance(reports: tuple[RunAnalysis, ...]) -> str:
    lines = ["# Performance", "", "| Run | Profile | Active duration | Target |", "|---|---|---:|---|"]
    for report in reports:
        active = (
            f"{report.active_duration_ms / 60_000:.1f}m"
            if report.active_duration_ms is not None
            else "unknown"
        )
        lines.append(
            f"| [{report.run_id}]({_report_link(report)}) | "
            f"{report.profile.get('name', 'legacy')} | {active} | "
            f"{report.compliance.get('performance_target', 'unknown')} |"
        )
    return "\n".join(lines)


def _tokens(reports: tuple[RunAnalysis, ...]) -> str:
    lines = [
        "# Token Usage",
        "",
        "| Run | Observed tokens | Coverage | Status | Ceiling |",
        "|---|---:|---:|---|---|",
    ]
    for report in reports:
        total = str(report.tokens.total) if report.tokens.total is not None else "unavailable"
        coverage = (
            f"{report.token_coverage:.0%} "
            f"({report.known_token_dispatches}/{report.known_token_dispatches + report.unknown_token_dispatches})"
            if report.token_coverage is not None
            else "unavailable"
        )
        lines.append(
            f"| [{report.run_id}]({_report_link(report)}) | {total} | "
            f"{coverage} | {report.token_status} | {report.compliance.get('token_ceiling', 'unknown')} |"
        )
    return "\n".join(lines)


def _token_summary(report: RunAnalysis) -> str:
    if report.tokens.total is None:
        return "unavailable (no provider usage telemetry)"
    total = f"{report.tokens.total:,}"
    if report.token_status != "partial":
        return total
    dispatches = report.known_token_dispatches + report.unknown_token_dispatches
    return (
        f"{total} observed (partial; {report.known_token_dispatches}/"
        f"{dispatches} dispatches reported)"
    )


def _bucket_tokens(values: dict[str, int]) -> str:
    total = str(values["tokens"])
    unknown = values.get("unknown_token_dispatches", 0)
    if not unknown:
        return total
    return f"{total} observed (partial; {values.get('known_token_dispatches', 0)}/{values['dispatches']})"


def _repeated(reports: tuple[RunAnalysis, ...]) -> str:
    lines = ["# Repeated Findings", ""]
    found = False
    for report in reports:
        for finding, count in report.repeated_findings.items():
            found = True
            lines.append(f"- `{report.run_id}` × {count}: {finding}")
    if not found:
        lines.append("No repeated structured findings were available.")
    return "\n".join(lines)


def _debt(reports: tuple[RunAnalysis, ...]) -> str:
    lines = ["# Quality Debt", "", "| Run | Partial sources | Blocking findings | Non-blocking findings |", "|---|---:|---:|---:|"]
    lines.extend(
        f"| [{report.run_id}]({_report_link(report)}) | "
        f"{report.partial_debt_source_count} | {report.blocking_finding_count} | "
        f"{report.non_blocking_finding_count} |"
        for report in reports
    )
    return "\n".join(lines)


def _spec_repairs(reports: tuple[RunAnalysis, ...]) -> str:
    lines = [
        "# Spec Repair Loops",
        "",
        "| Run | WHY | WHAT | PLAN | Repair dispatches |",
        "|---|---:|---:|---:|---:|",
    ]
    for report in reports:
        if report.workflow != "spec":
            continue
        loops = report.workflow_metrics.get("repair_loops", {})
        values = loops if isinstance(loops, dict) else {}
        lines.append(
            f"| [{report.run_id}]({_report_link(report)}) | {values.get('why', 0)} | "
            f"{values.get('what', 0)} | {values.get('plan', 0)} | "
            f"{report.workflow_metrics.get('repair_dispatches', 0)} |"
        )
    return "\n".join(lines)


def _report_link(report: RunAnalysis) -> str:
    directory = "RE%20Runs" if report.workflow == "re" else "Spec%20Runs"
    return f"../Operations/{directory}/{report.run_id}.md"


def _write(root: Path, relative: str, content: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.rstrip() + "\n", encoding="utf-8")
