"""Deterministic planning for reopening fulfillment gaps."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from kernel.task_contract import parse_task_rows


MAX_ROOT_CAUSE_SEQUENCES = 20
MAX_EXECUTABLE_TASK_ROWS = 60

_REQ_ID_RE = re.compile(
    r"^(?:FR|EDGE|NFR|SC)-[A-Za-z0-9]+$|^US\d+(?:-AC\d+)?$|^TASK-PROGRESS$"
)
_TABLE_ROW_RE = re.compile(r"^\|\s*(?P<id>[^|]+?)\s*\|(?P<rest>.*)\|\s*$")
_HEADING_RE = re.compile(r"^(?P<marks>#{2,6})\s+(?P<title>.+?)\s*$")
_FG_LABEL_RE = re.compile(r"\bFG-T\d+\b")
_REQ_TOKEN_RE = re.compile(
    r"\b(?:FR|EDGE|NFR|SC)-[A-Za-z0-9]+\b|\bUS\d+(?:-AC\d+)?\b|\bTASK-PROGRESS\b"
)


@dataclass(frozen=True)
class ReopenPlanResult:
    status: str
    reason: str
    clusters: list[dict[str, str]]
    skipped: list[dict[str, str]]
    manual_followups: list[dict[str, str]]
    proposed_tasks: list[dict[str, str]]
    task_rows_to_append: int


def plan_reopen_gaps(
    *,
    gaps_path: Path,
    tasks_path: Path,
    existing_reopen_paths: list[Path],
    out_plan_json: Path,
    out_plan_md: Path,
) -> ReopenPlanResult:
    """Plan reopen work from fulfillment gaps without mutating tasks.md."""
    gaps_text = gaps_path.read_text(encoding="utf-8", errors="replace")
    tasks_text = tasks_path.read_text(encoding="utf-8", errors="replace")
    task_rows = parse_task_rows(tasks_text)
    fulfillment_reqs = {
        req
        for task in task_rows
        if task.phase == "fulfillment-gap"
        for req in task.requirements
        if req != "UNMAPPED"
    }
    planned_reqs = {
        req
        for task in task_rows
        if task.phase != "fulfillment-gap"
        for req in task.requirements
        if req != "UNMAPPED"
    }
    reopen_reqs = _existing_reopen_requirements(existing_reopen_paths)

    clusters: list[dict[str, str]] = []
    skipped: list[dict[str, str]] = []
    manual_followups: list[dict[str, str]] = []
    seen_cluster_keys: set[str] = set()

    for gap in _parse_gap_rows(gaps_text):
        req = gap["id"]
        if req in {"ID", "ROW"}:
            continue
        if not _REQ_ID_RE.match(req):
            skipped.append(_skip(gap, "unsupported gap id"))
            continue
        if _needs_manual_decision(gap):
            manual_followups.append(
                {
                    "id": req,
                    "section": gap["section"],
                    "reason": "manual spec/code decision required",
                    "missing": gap["missing"],
                    "next_action": gap["next_action"],
                }
            )
            continue
        if _is_cross_reference(gap):
            skipped.append(_skip(gap, "cross-reference row folded into controlling gap"))
            continue
        if req in fulfillment_reqs:
            skipped.append(_skip(gap, "covered by existing fulfillment-gap task"))
            continue
        if req in reopen_reqs:
            skipped.append(_skip(gap, "covered by existing reopen summary"))
            continue
        if _is_planned_phase_missing(gap) and req in planned_reqs:
            skipped.append(_skip(gap, "planned work already exists in base tasks"))
            continue

        cluster_key = _cluster_key(gap)
        if cluster_key in seen_cluster_keys:
            skipped.append(_skip(gap, "duplicate root-cause cluster"))
            continue
        seen_cluster_keys.add(cluster_key)
        clusters.append(
            {
                "primary_req": req,
                "section": gap["section"],
                "missing": gap["missing"],
                "next_action": gap["next_action"],
                "cluster_key": cluster_key,
            }
        )

    proposed_tasks = _proposed_tasks(clusters, _next_numeric_task_id(task_rows))
    status = "ready"
    reason = "ready"
    task_rows_to_append = len(proposed_tasks)
    if not clusters:
        status = "manual_review" if manual_followups else "noop"
        reason = (
            "manual decisions required before task generation"
            if manual_followups
            else "no new actionable root-cause clusters"
        )
    elif (
        len(clusters) > MAX_ROOT_CAUSE_SEQUENCES
        or task_rows_to_append > MAX_EXECUTABLE_TASK_ROWS
    ):
        status = "manual_review"
        reason = (
            "proposed reopen plan exceeds safety cap: "
            f"{len(clusters)} root-cause sequences, {task_rows_to_append} task rows"
        )
        task_rows_to_append = 0
        proposed_tasks = []

    payload = {
        "status": status,
        "reason": reason,
        "source_gaps": str(gaps_path),
        "clusters": clusters,
        "skipped": skipped,
        "manual_followups": manual_followups,
        "proposed_tasks": proposed_tasks,
        "task_rows_to_append": task_rows_to_append,
        "limits": {
            "max_root_cause_sequences": MAX_ROOT_CAUSE_SEQUENCES,
            "max_executable_task_rows": MAX_EXECUTABLE_TASK_ROWS,
        },
    }
    _write_json(out_plan_json, payload)
    _write_text(out_plan_md, _render_markdown(payload))

    return ReopenPlanResult(
        status=status,
        reason=reason,
        clusters=clusters,
        skipped=skipped,
        manual_followups=manual_followups,
        proposed_tasks=proposed_tasks,
        task_rows_to_append=task_rows_to_append,
    )


def _parse_gap_rows(markdown: str) -> list[dict[str, str]]:
    gaps: list[dict[str, str]] = []
    section = ""
    for line in markdown.splitlines():
        heading = _HEADING_RE.match(line)
        if heading is not None:
            section = heading.group("title")
            continue
        row = _TABLE_ROW_RE.match(line)
        if row is None:
            continue
        gap_id = row.group("id").strip().strip("`")
        if set(gap_id) <= {"-"}:
            continue
        cells = [cell.strip() for cell in row.group("rest").split("|")]
        if not cells:
            continue
        gaps.append(
            {
                "id": gap_id.upper(),
                "section": section,
                "missing": _clean_cell(cells[-2] if len(cells) >= 2 else ""),
                "next_action": _clean_cell(cells[-1]),
                "raw": line,
            }
        )
    return gaps


def _existing_reopen_requirements(paths: list[Path]) -> set[str]:
    reqs: set[str] = set()
    for path in paths:
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        reqs.update(_REQ_TOKEN_RE.findall(text))
    return reqs


def _is_cross_reference(gap: dict[str, str]) -> bool:
    text = f"{gap['missing']} {gap['next_action']}".lower()
    return "see " in text and " next action" in text


def _needs_manual_decision(gap: dict[str, str]) -> bool:
    text = f"{gap['missing']} {gap['next_action']}".lower()
    decision_terms = (
        "divergence",
        "spec/code",
        "spec vs code",
        "manual decision",
        "cartographer decision",
        "decide whether",
        "choose whether",
        "spec amendment",
        "amend spec",
        "obsolete or",
    )
    return any(term in text for term in decision_terms)


def _is_planned_phase_missing(gap: dict[str, str]) -> bool:
    text = f"{gap['section']} {gap['missing']}".lower()
    return "missing gaps" in text or "phase " in text


def _cluster_key(gap: dict[str, str]) -> str:
    text = f"{gap['missing']} {gap['next_action']}".lower()
    tokens = re.findall(r"[a-z0-9_]+", text)
    stop = {
        "add",
        "and",
        "the",
        "with",
        "test",
        "tests",
        "implement",
        "wire",
        "no",
        "not",
        "missing",
    }
    useful = [token for token in tokens if token not in stop]
    return " ".join(useful[:10]) or gap["id"]


def _task_rows_for_clusters(clusters: list[dict[str, str]]) -> int:
    total = 0
    for cluster in clusters:
        total += 1 if cluster["primary_req"] == "TASK-PROGRESS" else 3
    return total


def _next_numeric_task_id(task_rows: list[Any]) -> int:
    numeric_ids: list[int] = []
    for task in task_rows:
        match = re.match(r"^T-(\d+)$", task.task_id)
        if match is not None:
            numeric_ids.append(int(match.group(1)))
    return max(numeric_ids, default=0) + 1


def _proposed_tasks(
    clusters: list[dict[str, str]],
    next_task_number: int,
) -> list[dict[str, str]]:
    tasks: list[dict[str, str]] = []
    task_number = next_task_number
    for index, cluster in enumerate(clusters, start=1):
        req = cluster["primary_req"]
        if req == "TASK-PROGRESS":
            task_id = _format_task_id(task_number)
            tasks.append(
                {
                    "task_id": task_id,
                    "row": (
                        f"- [ ] {task_id} complexity=standard "
                        "phase=fulfillment-gap req=TASK-PROGRESS depends=none"
                    ),
                    "title": (
                        f"FG-T{index}.1 - Reconcile task progress evidence for "
                        "verified implemented requirements"
                    ),
                    "cluster_req": req,
                }
            )
            task_number += 1
            continue

        first = _format_task_id(task_number)
        second = _format_task_id(task_number + 1)
        third = _format_task_id(task_number + 2)
        gap_label = _safe_title_fragment(cluster["missing"])
        tasks.extend(
            [
                {
                    "task_id": first,
                    "row": (
                        f"- [ ] {first} complexity=standard "
                        f"phase=fulfillment-gap req={req} depends=none"
                    ),
                    "title": f"FG-T{index}.1 - Add failing test for {gap_label}",
                    "cluster_req": req,
                },
                {
                    "task_id": second,
                    "row": (
                        f"- [ ] {second} complexity=standard "
                        f"phase=fulfillment-gap req={req} depends={first}"
                    ),
                    "title": f"FG-T{index}.2 - Implement missing or deviated behavior for {gap_label}",
                    "cluster_req": req,
                },
                {
                    "task_id": third,
                    "row": (
                        f"- [ ] {third} complexity=standard "
                        f"phase=fulfillment-gap req={req} depends={second}"
                    ),
                    "title": f"FG-T{index}.3 - Rerun verify-spec and update fulfillment evidence",
                    "cluster_req": req,
                },
            ]
        )
        task_number += 3
    return tasks


def _format_task_id(value: int) -> str:
    return f"T-{value:03d}"


def _safe_title_fragment(value: str) -> str:
    cleaned = re.sub(r"[*_\[\]()`#|]+", "", value)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned[:96] or "verified fulfillment gap"


def _skip(gap: dict[str, str], reason: str) -> dict[str, str]:
    return {
        "id": gap["id"],
        "section": gap["section"],
        "reason": reason,
    }


def _render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Reopen Gap Plan",
        "",
        f"Status: {payload['status']}",
        f"Reason: {payload['reason']}",
        f"Task rows to append: {payload['task_rows_to_append']}",
        "",
        "## Root-Cause Clusters",
    ]
    clusters = payload["clusters"]
    if clusters:
        for cluster in clusters:
            lines.append(
                f"- {cluster['primary_req']}: {cluster['missing']} -> {cluster['next_action']}"
            )
    else:
        lines.append("- None")
    lines.extend(["", "## Skipped"])
    skipped = payload["skipped"]
    if skipped:
        for row in skipped:
            lines.append(f"- {row['id']}: {row['reason']} ({row['section']})")
    else:
        lines.append("- None")
    lines.extend(["", "## Manual Follow-Ups"])
    manual_followups = payload["manual_followups"]
    if manual_followups:
        for row in manual_followups:
            lines.append(
                f"- {row['id']}: {row['reason']} -> {row['next_action']}"
            )
    else:
        lines.append("- None")
    lines.extend(["", "## Proposed Task Rows"])
    proposed_tasks = payload["proposed_tasks"]
    if proposed_tasks:
        for task in proposed_tasks:
            lines.append(task["row"])
            lines.append(f"  **Title:** {task['title']}")
    else:
        lines.append("- None")
    lines.append("")
    return "\n".join(lines)


def _clean_cell(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("`", "")).strip()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
