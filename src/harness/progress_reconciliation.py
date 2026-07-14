"""Deterministic task-progress reconciliation for verify-spec."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from kernel.task_contract import parse_task_rows
from harness.task_progress import (
    summarize_task_progress,
    update_task_progress_markdown,
)


@dataclass(frozen=True)
class ReconciliationResult:
    safe_count: int
    applied_count: int
    skipped_count: int
    ambiguous_count: int


@dataclass(frozen=True)
class _CandidateUpdate:
    task_id: str
    status: str
    evidence: str
    reason: str


def write_progress_reconciliation_candidates(
    *,
    tasks_path: Path,
    fulfillment_report_path: Path,
    fulfillment_gaps_path: Path,
    out_path: Path,
) -> dict[str, Any]:
    tasks = parse_task_rows(tasks_path.read_text(encoding="utf-8", errors="replace"))
    statuses = _fulfillment_statuses(
        fulfillment_report_path.read_text(encoding="utf-8", errors="replace")
    )
    safe: list[dict[str, str]] = []
    ambiguous: list[dict[str, str]] = []

    for task in tasks:
        if task.status.lower() == "x":
            continue
        requirements = [req for req in task.requirements if req != "UNMAPPED"]
        if not requirements:
            ambiguous.append(
                {
                    "task_id": task.task_id,
                    "evidence": "tasks.md req=UNMAPPED",
                    "reason": "task requirement ownership is unmapped",
                }
            )
            continue
        known_statuses = {req: statuses.get(req) for req in requirements}
        if all(status == "IMPLEMENTED" for status in known_statuses.values()):
            joined = ",".join(requirements)
            safe.append(
                {
                    "task_id": task.task_id,
                    "status": "DONE",
                    "evidence": f"fulfillment-report.md#{joined}",
                    "reason": f"all mapped requirements are IMPLEMENTED: {joined}",
                }
            )
        else:
            missing_or_open = [
                f"{req}={status or 'UNKNOWN'}"
                for req, status in known_statuses.items()
                if status != "IMPLEMENTED"
            ]
            ambiguous.append(
                {
                    "task_id": task.task_id,
                    "evidence": "fulfillment-report.md#" + ",".join(requirements),
                    "reason": "not all mapped requirements are IMPLEMENTED: "
                    + ", ".join(missing_or_open),
                }
            )

    payload = {
        "safe_task_updates": safe,
        "ambiguous_task_matches": ambiguous,
        "fulfillment_gap_tasks": _fulfillment_gap_tasks(fulfillment_gaps_path),
        "manual_followups": [],
    }
    _write_json(out_path, payload)
    return payload


def reconcile_progress(
    *,
    tasks_path: Path,
    candidate_path: Path,
    out_plan_json: Path,
    out_plan_md: Path,
    dry_run: bool,
    out_applied_json: Path | None = None,
    out_applied_md: Path | None = None,
) -> ReconciliationResult:
    """Validate candidate task updates and optionally apply safe progress changes."""
    candidate = _load_candidate(candidate_path)
    markdown = tasks_path.read_text(encoding="utf-8", errors="replace")
    summary = summarize_task_progress(markdown)
    if not summary.valid:
        raise ValueError(f"invalid task progress: {'; '.join(summary.errors)}")

    task_dependencies = _task_dependencies(markdown)
    updates = _candidate_updates(candidate.get("safe_task_updates", []))
    update_ids = {update.task_id for update in updates}
    safe: list[_CandidateUpdate] = []
    skipped: list[dict[str, str]] = []

    for update in updates:
        skip_reason = _skip_reason(update, summary.task_statuses, task_dependencies, update_ids)
        if skip_reason:
            skipped.append(_skip_payload(update, skip_reason))
        else:
            safe.append(update)

    plan_payload = _report_payload(candidate, safe, skipped, dry_run=dry_run)
    _write_json(out_plan_json, plan_payload)
    _write_text(out_plan_md, _render_markdown("Progress Reconciliation Plan", plan_payload))

    applied: list[_CandidateUpdate] = []
    applied_payload: dict[str, Any] | None = None
    if not dry_run:
        updated_markdown = markdown
        for update in safe:
            updated_markdown = update_task_progress_markdown(
                updated_markdown,
                update.task_id,
                "DONE",
            )
            applied.append(update)
        tasks_path.write_text(updated_markdown, encoding="utf-8")
        applied_summary = summarize_task_progress(updated_markdown)
        if not applied_summary.valid:
            raise ValueError(
                f"invalid reconciled task progress: {'; '.join(applied_summary.errors)}"
            )
        applied_payload = _report_payload(
            candidate,
            applied,
            skipped,
            dry_run=False,
            applied=True,
        )
        if out_applied_json is None or out_applied_md is None:
            raise ValueError("apply mode requires applied output paths")
        _write_json(out_applied_json, applied_payload)
        _write_text(
            out_applied_md,
            _render_markdown("Progress Reconciliation Applied", applied_payload),
        )

    return ReconciliationResult(
        safe_count=len(safe),
        applied_count=len(applied),
        skipped_count=len(skipped),
        ambiguous_count=len(_list(candidate.get("ambiguous_task_matches"))),
    )


def _load_candidate(candidate_path: Path) -> dict[str, Any]:
    data = json.loads(candidate_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("candidate reconciliation file must be a JSON object")
    return data


def _fulfillment_statuses(markdown: str) -> dict[str, str]:
    statuses: dict[str, str] = {}
    for line in markdown.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if len(cells) < 2 or cells[0] in {"ID", "---", "Status"}:
            continue
        if _looks_like_requirement_id(cells[0]):
            statuses[cells[0]] = cells[1].upper()
    return statuses


def _looks_like_requirement_id(value: str) -> bool:
    return bool(re.match(r"^(?:FR|US|AC|EDGE|NFR|SC|REQ)-?[A-Za-z0-9_.:-]+$", value))


def _fulfillment_gap_tasks(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    text = path.read_text(encoding="utf-8", errors="replace")
    count = len(re.findall(r"\b(?:FR|US|AC|EDGE|NFR|SC|REQ)-?[A-Za-z0-9_.:-]+\b", text))
    return {
        "count": count,
        "details": str(path),
    }


def _candidate_updates(value: object) -> list[_CandidateUpdate]:
    updates: list[_CandidateUpdate] = []
    for item in _list(value):
        updates.append(
            _CandidateUpdate(
                task_id=str(item.get("task_id", "")).strip(),
                status=str(item.get("status", "")).strip().upper(),
                evidence=str(item.get("evidence", "")).strip(),
                reason=str(item.get("reason", "")).strip(),
            )
        )
    return updates


def _skip_reason(
    update: _CandidateUpdate,
    task_statuses: dict[str, str],
    task_dependencies: dict[str, list[str]],
    update_ids: set[str],
) -> str | None:
    if not update.task_id:
        return "missing task id"
    if update.task_id not in task_statuses:
        return "unknown task id"
    if update.status != "DONE":
        return f"unsupported status: {update.status or '(missing)'}"
    for dependency in task_dependencies.get(update.task_id, []):
        if dependency in update_ids:
            continue
        if task_statuses.get(dependency, "PENDING") not in {
            "DONE",
            "DONE_WITH_CONCERNS",
            "DEGRADED",
            "DEFERRED",
        }:
            return f"open dependency: {dependency}"
    return None


def _task_dependencies(markdown: str) -> dict[str, list[str]]:
    dependencies: dict[str, list[str]] = {}
    row_re = re.compile(
        r"^- \[[ xX]\]\s+(?P<task_id>T-\d+)\s+.*\sdepends=(?P<depends>[A-Za-z0-9_,.-]+)$"
    )
    for line in markdown.splitlines():
        match = row_re.match(line)
        if match is None:
            continue
        depends = match.group("depends")
        dependencies[match.group("task_id")] = [] if depends == "none" else depends.split(",")
    return dependencies


def _report_payload(
    candidate: dict[str, Any],
    safe: list[_CandidateUpdate],
    skipped: list[dict[str, str]],
    *,
    dry_run: bool,
    applied: bool = False,
) -> dict[str, Any]:
    return {
        "mode": "dry_run" if dry_run else "apply",
        "applied": applied,
        "safe_task_updates": [_update_payload(update) for update in safe],
        "skipped_task_updates": skipped,
        "ambiguous_task_matches": _list(candidate.get("ambiguous_task_matches")),
        "fulfillment_gap_tasks": candidate.get("fulfillment_gap_tasks") or {},
        "manual_followups": _list(candidate.get("manual_followups")),
    }


def _update_payload(update: _CandidateUpdate) -> dict[str, str]:
    return {
        "task_id": update.task_id,
        "status": update.status,
        "evidence": update.evidence,
        "reason": update.reason,
    }


def _skip_payload(update: _CandidateUpdate, reason: str) -> dict[str, str]:
    payload = _update_payload(update)
    payload["skip_reason"] = reason
    return payload


def _render_markdown(title: str, payload: dict[str, Any]) -> str:
    lines = [
        f"# {title}",
        "",
        f"Mode: {payload['mode']}",
        "",
        "## Safe Task Updates",
        *_bullet_rows(payload["safe_task_updates"], include_status=True),
        "",
        "## Skipped Task Updates",
        *_bullet_rows(payload["skipped_task_updates"], include_skip=True),
        "",
        "## Ambiguous Task Matches",
        *_bullet_rows(payload["ambiguous_task_matches"]),
        "",
        "## Fulfillment Gap Tasks",
        _fulfillment_gap_line(payload["fulfillment_gap_tasks"]),
        "",
        "## Manual Follow-Ups",
        *_manual_rows(payload["manual_followups"]),
        "",
    ]
    return "\n".join(lines)


def _bullet_rows(
    rows: object,
    *,
    include_status: bool = False,
    include_skip: bool = False,
) -> list[str]:
    items = _list(rows)
    if not items:
        return ["- None"]
    rendered: list[str] = []
    for item in items:
        task_id = item.get("task_id", "(unknown)")
        evidence = item.get("evidence", "(no evidence)")
        reason = item.get("reason", "")
        parts = [f"- {task_id}", f"evidence: {evidence}"]
        if include_status:
            parts.append(f"status: {item.get('status', '')}")
        if include_skip:
            parts.append(f"skip: {item.get('skip_reason', '')}")
        if reason:
            parts.append(f"reason: {reason}")
        rendered.append("; ".join(parts))
    return rendered


def _manual_rows(rows: object) -> list[str]:
    items = _list(rows)
    if not items:
        return ["- None"]
    rendered: list[str] = []
    for item in items:
        rendered.append(f"- {item.get('kind', '(unknown)')}: {item.get('details', '')}")
    return rendered


def _fulfillment_gap_line(value: object) -> str:
    if not isinstance(value, dict) or not value:
        return "- None"
    return f"- {value.get('count', 0)} tasks; details: {value.get('details', '')}"


def _list(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
