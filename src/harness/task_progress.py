"""Canonical tasks.md progress helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from kernel.task_contract import TASK_ID_PATTERN, validate_tasks_markdown


_TASK_ROW_RE = re.compile(
    rf"^(?P<prefix>- \[)(?P<status>[ xX])(?P<suffix>\]\s+"
    rf"(?P<task_id>{TASK_ID_PATTERN})(?:\s+\[P\])?\s+"
    r"complexity=(?:trivial|standard|complex)\s+"
    r"phase=[A-Za-z0-9_.-]+\s+"
    r"req=[A-Za-z0-9_,.-]+\s+"
    r"depends=(?:none|[A-Za-z0-9_,.-]+))$"
)
_STATUS_RE = re.compile(r"^\s+\*\*Status:\*\*\s*(?P<status>[A-Z_]+)\s*$")
_COMPLETED_STATUSES = {"DONE", "DONE_WITH_CONCERNS", "DEGRADED"}
_OPEN_STATUSES = {"BLOCKED", "PENDING"}
_ALLOWED_STATUSES = _COMPLETED_STATUSES | _OPEN_STATUSES


class TaskProgressError(RuntimeError):
    """Raised when canonical task progress cannot be updated or reconciled."""


@dataclass(frozen=True)
class TaskProgressSummary:
    valid: bool
    total_tasks: int
    completed_tasks: int
    tasks_completed_pct: int
    task_statuses: dict[str, str]
    errors: list[str]


def update_task_progress_markdown(markdown: str, task_id: str, status: str) -> str:
    """Update one canonical task block in tasks.md."""
    normalized_status = _normalize_status(status)
    lines = markdown.splitlines()
    start = _find_task_row(lines, task_id)
    if start is None:
        raise TaskProgressError(f"task id not found: {task_id}")

    end = _find_next_task_row(lines, start + 1)
    if end is None:
        end = len(lines)

    row_match = _TASK_ROW_RE.match(lines[start])
    if row_match is None:
        raise TaskProgressError(f"task row is not canonical: {task_id}")

    row_status = "x" if normalized_status in _COMPLETED_STATUSES else " "
    lines[start] = (
        f"{row_match.group('prefix')}{row_status}{row_match.group('suffix')}"
    )

    _upsert_status_line(lines, start, end, normalized_status)
    end = _find_next_task_row(lines, start + 1) or len(lines)

    if normalized_status in {"DONE", "DONE_WITH_CONCERNS"}:
        _check_nested_boxes(lines, start + 1, end)

    return "\n".join(lines) + ("\n" if markdown.endswith("\n") else "")


def summarize_task_progress(
    markdown: str,
    build_state: dict[str, Any] | None = None,
) -> TaskProgressSummary:
    """Return task progress and mismatches against a build state object."""
    validation = validate_tasks_markdown(markdown)
    errors = list(validation.errors)
    task_statuses: dict[str, str] = {}
    completed = 0

    lines = markdown.splitlines()
    for index, match in _iter_task_rows(lines):
        task_id = match.group("task_id")
        checked = match.group("status").lower() == "x"
        if checked:
            completed += 1
        block_end = _find_next_task_row(lines, index + 1) or len(lines)
        task_statuses[task_id] = _status_for_block(lines[index + 1:block_end], checked)

    total = validation.task_count
    pct = _pct(completed, total)
    _compare_build_state(build_state or {}, total, completed, pct, task_statuses, errors)

    return TaskProgressSummary(
        valid=not errors,
        total_tasks=total,
        completed_tasks=completed,
        tasks_completed_pct=pct,
        task_statuses=task_statuses,
        errors=errors,
    )


def _normalize_status(status: str) -> str:
    normalized = status.strip().upper()
    if normalized not in _ALLOWED_STATUSES:
        raise TaskProgressError(f"unsupported task status: {status}")
    return normalized


def _find_task_row(lines: list[str], task_id: str) -> int | None:
    for index, match in _iter_task_rows(lines):
        if match.group("task_id") == task_id:
            return index
    return None


def _find_next_task_row(lines: list[str], start: int) -> int | None:
    for index, _match in _iter_task_rows(lines, start=start):
        if index >= start:
            return index
    return None


def _iter_task_rows(
    lines: list[str],
    start: int = 0,
) -> list[tuple[int, re.Match[str]]]:
    rows: list[tuple[int, re.Match[str]]] = []
    in_fence = False
    for index, line in enumerate(lines):
        if line.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence or index < start:
            continue
        match = _TASK_ROW_RE.match(line)
        if match is not None:
            rows.append((index, match))
    return rows


def _upsert_status_line(lines: list[str], start: int, end: int, status: str) -> None:
    for index in range(start + 1, end):
        if _STATUS_RE.match(lines[index]) is not None:
            lines[index] = f"  **Status:** {status}"
            return
    lines.insert(start + 1, f"  **Status:** {status}")


def _check_nested_boxes(lines: list[str], start: int, end: int) -> None:
    for index in range(start, end):
        if lines[index].startswith("  - [ ]"):
            lines[index] = lines[index].replace("  - [ ]", "  - [x]", 1)


def _status_for_block(block_lines: list[str], checked: bool) -> str:
    for line in block_lines:
        match = _STATUS_RE.match(line)
        if match is not None:
            return match.group("status")
    return "DONE" if checked else "PENDING"


def _pct(completed: int, total: int) -> int:
    if total <= 0:
        return 0
    return round((completed / total) * 100)


def _compare_build_state(
    build: dict[str, Any],
    total: int,
    completed: int,
    pct: int,
    task_statuses: dict[str, str],
    errors: list[str],
) -> None:
    if not build:
        return

    expected = {
        "total_tasks": total,
        "completed_tasks": completed,
        "tasks_completed_pct": pct,
    }
    for key, value in expected.items():
        actual = build.get(key)
        if actual is not None and actual != value:
            if key == "completed_tasks":
                errors.append(
                    f"state completed_tasks={actual} but tasks.md has {value} checked task rows"
                )
            elif key == "tasks_completed_pct":
                errors.append(
                    f"state tasks_completed_pct={actual} but tasks.md computes {value}"
                )
            else:
                errors.append(f"state {key}={actual} but tasks.md has {value}")

    task_results = build.get("task_results")
    if isinstance(task_results, dict):
        for task_id, result in task_results.items():
            if task_id not in task_statuses:
                errors.append(f"state has result for unknown task id: {task_id}")
                continue
            if isinstance(result, dict):
                status = result.get("status")
                if status and _canonical_outcome(str(status)) != _canonical_outcome(
                    task_statuses[task_id]
                ):
                    errors.append(
                        f"state task_results.{task_id}.status={status} but tasks.md has {task_statuses[task_id]}"
                    )


def _canonical_outcome(status: str) -> str:
    normalized = status.strip().upper()
    if normalized == "DONE_WITH_CONCERNS":
        return "DONE"
    return normalized
