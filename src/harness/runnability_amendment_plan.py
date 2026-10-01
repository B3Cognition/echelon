"""Pure correction of a published plan missing runnability-contract ownership."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

from harness.task_targets import task_declares_file
from kernel.task_contract import parse_task_rows, validate_tasks_markdown


class RunnabilityAmendmentPlanError(ValueError):
    """A published plan cannot be amended without changing existing work."""


@dataclass(frozen=True)
class OwnerTaskProposal:
    target_id: str
    task_id: str
    contract_path: str
    markdown: str


_ROW_START = re.compile(r"(?m)^- \[[ xX]\]\s+T-")
_COUNT = re.compile(r"(?m)^- Total tasks: (\d+)[ \t]*$")
_TASK_ROW = re.compile(r"^- \[[ xX]\](?=\s+T-)")
_NESTED_BOX = re.compile(r"^([ \t]+- )\[[ xX]\](?=\s+)")
_STATUS = re.compile(r"^[ \t]+\*\*Status:\*\*[ \t]*([A-Z_]+)[ \t]*$")
_KNOWN_STATUSES = {
    "PENDING", "BLOCKED", "DONE", "DONE_WITH_CONCERNS", "DEGRADED", "DEFERRED",
}
_NUMERIC_TASK_ID = re.compile(r"T-(\d{3,})\Z")
_PHASE_SUMMARY = re.compile(r"(?m)^## Summary by Phase[ \t]*$")
_RELEASE_COUNT = re.compile(r"(?m)^(\|[ \t]*release[ \t]*\|[ \t]*)(\d+)([ \t]*\|[^\n]*)$")
_TOTAL_COUNT = re.compile(r"(?m)^(\|[ \t]*\*\*Total\*\*[ \t]*\|[ \t]*\*\*)(\d+)(\*\*[ \t]*\|[^\n]*)$")


def _validated_rows(markdown: str) -> list:
    result = validate_tasks_markdown(markdown)
    rows = parse_task_rows(markdown)
    if not result.valid or len(_ROW_START.findall(markdown)) != len(rows):
        raise RunnabilityAmendmentPlanError("malformed canonical task row")
    counts = _COUNT.findall(markdown)
    if len(counts) != 1 or int(counts[0]) != len(rows):
        raise RunnabilityAmendmentPlanError("malformed total task count")
    return rows


def _without_progress(markdown: str) -> str:
    """Mask only controller-owned progress, keeping every definition byte."""
    normalized: list[str] = []
    in_fence = False
    in_task = False
    in_checklist = False
    for line in markdown.splitlines(keepends=True):
        body = line.rstrip("\r\n")
        ending = line[len(body):]
        if body.startswith("```"):
            in_fence = not in_fence
        if not in_fence and body.startswith("## "):
            in_task = False
            in_checklist = False
        if not in_fence and _TASK_ROW.match(body):
            in_task = True
            in_checklist = False
            body = _TASK_ROW.sub("- [ ]", body, count=1)
        elif in_task and not in_fence:
            status = _STATUS.match(body)
            if status:
                if status.group(1) not in _KNOWN_STATUSES:
                    raise RunnabilityAmendmentPlanError("unrecognized task status")
                continue
            if body.startswith("  **"):
                in_checklist = body in {"  **Acceptance Criteria:**", "  **Test Tasks:**"}
            if in_checklist:
                body = _NESTED_BOX.sub(r"\1[ ]", body, count=1)
        normalized.append(body + ending)
    return "".join(normalized)


def _validate_working_progress(published_tasks: str, working_tasks: str) -> None:
    published_rows = _validated_rows(published_tasks)
    working_rows = _validated_rows(working_tasks)
    if [row.task_id for row in working_rows] != [row.task_id for row in published_rows]:
        raise RunnabilityAmendmentPlanError("old task definition changed: task inventory")
    if _without_progress(published_tasks) != _without_progress(working_tasks):
        raise RunnabilityAmendmentPlanError("old task definition changed outside progress")


def _replace_count(markdown: str, count: int) -> str:
    if len(_COUNT.findall(markdown)) != 1:
        raise RunnabilityAmendmentPlanError("malformed total task count")
    return _COUNT.sub(f"- Total tasks: {count}", markdown, count=1)


def _replace_summary_counts(markdown: str, added_tasks: int) -> str:
    """Keep factual task totals in the published plan's optional phase footer."""
    old_count = len(_validated_rows(markdown))
    updated = _replace_count(markdown, old_count + added_tasks)
    summaries = list(_PHASE_SUMMARY.finditer(updated))
    if not summaries:
        return updated
    if len(summaries) != 1:
        raise RunnabilityAmendmentPlanError("malformed phase summary")
    before, footer = updated[:summaries[0].end()], updated[summaries[0].end():]
    release_matches = list(_RELEASE_COUNT.finditer(footer))
    total_matches = list(_TOTAL_COUNT.finditer(footer))
    if len(release_matches) != 1 or len(total_matches) != 1:
        raise RunnabilityAmendmentPlanError("malformed phase summary task counts")
    expected_release = sum(row.phase == "release" for row in parse_task_rows(markdown))
    if (int(release_matches[0].group(2)) != expected_release
            or int(total_matches[0].group(2)) != old_count):
        raise RunnabilityAmendmentPlanError("phase summary task counts disagree with rows")
    footer = _RELEASE_COUNT.sub(
        lambda match: match.group(1) + str(expected_release + added_tasks) + match.group(3),
        footer, count=1,
    )
    footer = _TOTAL_COUNT.sub(
        lambda match: match.group(1) + str(old_count + added_tasks) + match.group(3),
        footer, count=1,
    )
    return before + footer


def _new_pending_owner_task(
    target: str,
    contract: str,
    task_id: str,
    dependency: str,
) -> OwnerTaskProposal:
    markdown = (
        "\n## Amendment: Required runnability contract\n\n"
        f"- [ ] {task_id} complexity=standard phase=release req=INFRA "
        f"depends={dependency} target={target}\n"
        "  **Status:** PENDING\n\n"
        "  **Title:** Define the target's executable runnability contract\n\n"
        "  **Files:**\n"
        f"  - `{contract}` - target-owned composed verification commands\n\n"
        "  **Description:**\n"
        "  Define stack-compatible install, start, readiness, primary-journey, "
        "and stop operations for the actual product. Choose commands from the "
        "implemented project rather than inventing them in the plan.\n\n"
        "  **Test:** Execute the composed journey against the built target and "
        "confirm startup, readiness, browser observation when required, and cleanup.\n\n"
        "  **Acceptance Criteria:**\n"
        "  - [ ] The contract names executable commands for all stack-required operations.\n"
        "  - [ ] The ordinary verification and review gates pass without bypasses.\n"
    )
    return OwnerTaskProposal(target, task_id, contract, markdown)


def plan_owner_tasks(
    published_tasks: str,
    working_tasks: str,
    targets: tuple[str, ...],
    required_targets: tuple[str, ...],
) -> tuple[OwnerTaskProposal, ...]:
    """Propose only missing owners; caller resolves stack policy and deferrals."""
    rows = _validated_rows(published_tasks)
    _validate_working_progress(published_tasks, working_tasks)
    if len(set(targets)) != len(targets) or len(set(required_targets)) != len(required_targets):
        raise RunnabilityAmendmentPlanError("duplicate target")
    if not set(required_targets).issubset(targets):
        raise RunnabilityAmendmentPlanError("required target is not declared")
    next_number = max(
        (int(match.group(1)) for row in rows
         if (match := _NUMERIC_TASK_ID.fullmatch(row.task_id))),
        default=0,
    ) + 1
    proposals: list[OwnerTaskProposal] = []
    for target in required_targets:
        contract = (Path(target) / ".echelon/runnability.yml").as_posix()
        target_rows = [row for row in rows if (row.target or ".") == target]
        owners = [row.task_id for row in target_rows
                  if task_declares_file(published_tasks, row.task_id, contract)]
        if len(owners) > 1:
            raise RunnabilityAmendmentPlanError(f"ambiguous owner for {target}")
        if owners:
            continue
        task_id = f"T-{next_number:03d}"
        next_number += 1
        dependency = target_rows[-1].task_id if target_rows else "none"
        proposals.append(_new_pending_owner_task(target, contract, task_id, dependency))
    return tuple(proposals)


def render_owner_tasks(
    published_tasks: str,
    proposals: tuple[OwnerTaskProposal, ...],
) -> str:
    """Render a proposed published plan while retaining every old task byte."""
    _validated_rows(published_tasks)
    if not proposals:
        raise RunnabilityAmendmentPlanError("proposal has no new task")
    rendered = _replace_summary_counts(published_tasks, len(proposals))
    rendered += "".join(item.markdown for item in proposals)
    if len(_validated_rows(rendered)) != len(parse_task_rows(published_tasks)) + len(proposals):
        raise RunnabilityAmendmentPlanError("rendered task inventory is malformed")
    return rendered


def project_progress(
    published_tasks: str,
    working_tasks: str,
    proposed_tasks: str,
) -> str:
    """Add the new task suffix without rewriting old working task progress."""
    _validate_working_progress(published_tasks, working_tasks)
    old_count = len(_validated_rows(published_tasks))
    new_count = len(_validated_rows(proposed_tasks))
    if new_count <= old_count:
        raise RunnabilityAmendmentPlanError("proposal has no new task")
    expected_prefix = _replace_summary_counts(published_tasks, new_count - old_count)
    if not proposed_tasks.startswith(expected_prefix):
        raise RunnabilityAmendmentPlanError("old task definition changed in proposal")
    suffix = proposed_tasks[len(expected_prefix):]
    return _replace_summary_counts(working_tasks, new_count - old_count) + suffix
