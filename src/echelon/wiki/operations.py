"""Optional local run-analysis projection for the generated human wiki."""

from __future__ import annotations

from pathlib import Path

from echelon.telemetry.analyzer import RunAnalysis
from echelon.telemetry.re_adapter import analyze_re_runs


def render_operations(project_root: Path, output_dir: Path) -> tuple[str, ...]:
    reports = analyze_re_runs(project_root / "runs")
    if not reports:
        return ()
    pages: list[str] = []
    index_lines = [
        "# Local Operations",
        "",
        "> This section is local and ephemeral. It is derived from ignored run state, not canonical published artifacts.",
        "",
        "## Reverse-engineering runs",
        "",
    ]
    for report in reports:
        relative = f"Operations/RE Runs/{report.run_id}.md"
        index_lines.append(f"- [{report.run_id}](RE%20Runs/{report.run_id}.md) — {report.status}")
        _write(output_dir, relative, _run_page(report))
        pages.append(relative)
    _write(output_dir, "Operations/Index.md", "\n".join(index_lines))
    pages.append("Operations/Index.md")
    views = {
        "Views/Performance.md": _performance(reports),
        "Views/Token Usage.md": _tokens(reports),
        "Views/Repeated Findings.md": _repeated(reports),
        "Views/Quality Debt.md": _debt(reports),
    }
    for relative, content in views.items():
        _write(output_dir, relative, content)
        pages.append(relative)
    return tuple(sorted(pages))


def _run_page(report: RunAnalysis) -> str:
    token = f"{report.tokens.total:,}" if report.tokens.total is not None else "unknown"
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
            f"| `{phase}` | {values['dispatches']} | {values['tokens']} | {values['duration_ms'] / 1000:.1f}s |"
            for phase, values in report.by_phase.items()
        )
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
            f"| [{report.run_id}](../Operations/RE%20Runs/{report.run_id}.md) | "
            f"{report.profile.get('name', 'legacy')} | {active} | "
            f"{report.compliance.get('performance_target', 'unknown')} |"
        )
    return "\n".join(lines)


def _tokens(reports: tuple[RunAnalysis, ...]) -> str:
    lines = ["# Token Usage", "", "| Run | Tokens | Unknown dispatches | Ceiling |", "|---|---:|---:|---|"]
    for report in reports:
        total = str(report.tokens.total) if report.tokens.total is not None else "unknown"
        lines.append(
            f"| [{report.run_id}](../Operations/RE%20Runs/{report.run_id}.md) | {total} | "
            f"{report.unknown_token_dispatches} | {report.compliance.get('token_ceiling', 'unknown')} |"
        )
    return "\n".join(lines)


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
        f"| [{report.run_id}](../Operations/RE%20Runs/{report.run_id}.md) | "
        f"{report.partial_debt_source_count} | {report.blocking_finding_count} | "
        f"{report.non_blocking_finding_count} |"
        for report in reports
    )
    return "\n".join(lines)


def _write(root: Path, relative: str, content: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.rstrip() + "\n", encoding="utf-8")
