"""Read-only, bounded quality-debt orientation for staged RE runs."""

from __future__ import annotations

import re
import shlex
from pathlib import Path
from typing import Callable, TextIO


def _text(value: object, limit: int = 220) -> str:
    text = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", str(value))
    text = "".join(char for char in " ".join(text.split()) if ord(char) >= 32 and ord(char) != 127)
    return text if len(text) <= limit else text[:limit - 1] + "…"


def _items(value: object) -> list[dict]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _findings(failure: dict) -> list[str]:
    # Records and legacy strings describe the same findings, not two inventories.
    values = failure.get("semantic_findings")
    if isinstance(values, list) and values:
        return [value for value in values if isinstance(value, str) and value.strip()]
    return [
        record["text"] for record in _items(failure.get("semantic_finding_records"))
        if isinstance(record.get("text"), str) and record["text"].strip()
    ]


def semantic_debt_label(report: dict) -> str | None:
    failures = _items(report.get("semantic_failures"))
    if not failures:
        return None
    count = sum(len(_findings(failure)) for failure in failures)
    domains = len({failure.get("domain_id") for failure in failures if isinstance(failure.get("domain_id"), str)})
    if not count:
        return f"semantic review incomplete · {domains} domain(s)"
    return f"{count} semantic finding{'s' if count != 1 else ''} · {domains} domain(s)"


def repair_command(inner: dict, outer: dict) -> str | None:
    budgets = inner.get("re_source_budgets")
    values = [budgets.get(key) for key in ("max_source_cycles", "max_domain_repairs", "max_source_reanalysis")] if isinstance(budgets, dict) else []
    values.extend((inner.get("re_source_budget_override"), inner.get("re_max_inner"), outer.get("re_max_inner")))
    limits = [value for value in values if isinstance(value, int) and not isinstance(value, bool) and value > 0]
    if not limits:
        return None
    return f"echelon re continue --re-max-inner {max(limits) + 1}"


def synthesis_label(run_re_dir: Path, inner: dict, *, finalized_partial: bool = False) -> str:
    if inner.get("re_workspace_synthesis_complete") is True:
        states = inner.get("re_source_states")
        if isinstance(states, dict) and any(
            isinstance(state, dict) and state.get("status") == "partial_quality_debt"
            for state in states.values()
        ):
            return "artifacts generated; not quality-approved"
        return "complete"
    if (run_re_dir / "workspace" / "overview.md").is_file():
        return "draft artifacts present; not quality-approved"
    return "incomplete (accepted partial debt)" if finalized_partial else "pending"


def print_quality_debt(
    run_re_dir: Path,
    inner: dict,
    outer: dict,
    read_state: Callable[[Path], dict],
    *,
    file: TextIO,
    show_actions: bool = False,
) -> None:
    states = inner.get("re_source_states")
    if not isinstance(states, dict):
        return
    partial = outer.get("finalized_partial") is True
    debt = []
    for source_id, state in states.items():
        if not isinstance(source_id, str) or not isinstance(state, dict):
            continue
        # Never follow a source identifier outside the known report directory.
        if source_id in {".", ".."} or "/" in source_id or "\\" in source_id:
            continue
        report_path = run_re_dir / "quality" / "sources" / f"{source_id}.json"
        report = read_state(report_path)
        if state.get("status") == "partial_quality_debt" or report.get("passed") is False:
            debt.append((source_id, report, report_path))
    if not debt:
        return
    print("\nQuality debt" + (" (accepted, not resolved)" if partial else " (unresolved)"), file=file)
    print("  100% file coverage does not mean the generated knowledge is correct.", file=file)
    print("  Semantic findings flag unsupported, incomplete, or contradicted descriptions; they are not automatically source-code defects.", file=file)
    remaining_domains = 12
    for source_id, report, report_path in debt:
        label = semantic_debt_label(report)
        print(f"\n  {_text(source_id)}: {label or ('report unavailable' if not report else 'source-quality gate not passed')}", file=file)
        orphan_paths = report.get("orphan_paths")
        if isinstance(orphan_paths, list) and orphan_paths:
            print("    Uncovered files: " + ", ".join(_text(path, 100) for path in orphan_paths[:3]), file=file)
            if len(orphan_paths) > 3:
                print(f"    … {len(orphan_paths) - 3} more uncovered files in the report", file=file)
        failures = _items(report.get("domain_failures")) + _items(report.get("semantic_failures"))
        for failure in failures[:remaining_domains]:
            findings = _findings(failure)
            domain = _text(failure.get("domain_id") or "unnamed domain")
            explanation = f"{len(findings)} semantic finding(s)" if findings else _text(failure.get("reason") or "incomplete domain")
            print(f"    {domain}: {explanation}", file=file)
            if findings:
                print(f"      Example: {_text(findings[0])}", file=file)
            sections = failure.get("missing_sections")
            if isinstance(sections, list) and sections:
                print("      Missing sections: " + ", ".join(_text(section, 80) for section in sections[:5]), file=file)
        shown = min(len(failures), remaining_domains)
        remaining_domains -= shown
        if len(failures) > shown:
            print(f"    … {len(failures) - shown} more affected domains in the report", file=file)
        print(f"    Full report: {report_path}", file=file)
    if not show_actions or partial:
        return
    command = repair_command(inner, outer)
    print("\nNext steps (choose one)", file=file)
    if command:
        print(f"  Repair: {command}", file=file)
        print("    Raises source-local attempt limits, not token/time ceilings; convergence is not guaranteed.", file=file)
    else:
        print("  Repair: source-local limits are unavailable; inspect the controller state before choosing --re-max-inner.", file=file)
    run_id = shlex.quote(run_re_dir.parent.name)
    print("  Or explicitly accept the remaining debt, if structurally publishable:", file=file)
    print(f"    echelon re finalize {run_id} --allow-partial", file=file)
    print("  After successful finalization, publish the partial knowledge:", file=file)
    print(f"    echelon re publish {run_id} --allow-partial", file=file)
