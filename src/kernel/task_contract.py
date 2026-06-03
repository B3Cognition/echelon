"""Canonical tasks.md row parser and validator."""

from __future__ import annotations

import re
from dataclasses import dataclass


_TASK_ROW_RE = re.compile(
    r"^- \[(?P<status>[ xX])\]\s+"
    r"(?P<task_id>T-\d{3,4})"
    r"(?:\s+(?P<parallel>\[P\]))?\s+"
    r"complexity=(?P<complexity>trivial|standard|complex)\s+"
    r"phase=(?P<phase>[A-Za-z0-9_.-]+)\s+"
    r"req=(?P<requirements>[A-Za-z0-9_,.-]+)\s+"
    r"depends=(?P<dependencies>none|[A-Za-z0-9_,.-]+)\s*$"
)


@dataclass(frozen=True)
class TaskRow:
    task_id: str
    status: str
    parallel: bool
    complexity: str
    phase: str
    requirements: list[str]
    dependencies: list[str]


@dataclass(frozen=True)
class TaskValidationResult:
    valid: bool
    task_count: int
    errors: list[str]


def parse_task_rows(markdown: str) -> list[TaskRow]:
    """Return canonical top-level task rows from a tasks.md document."""
    tasks: list[TaskRow] = []
    in_fence = False
    for line in markdown.splitlines():
        if line.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        match = _TASK_ROW_RE.match(line.rstrip())
        if match is None:
            continue
        data = match.groupdict()
        tasks.append(
            TaskRow(
                task_id=data["task_id"],
                status=data["status"],
                parallel=data["parallel"] == "[P]",
                complexity=data["complexity"],
                phase=data["phase"],
                requirements=_split_csv(data["requirements"]),
                dependencies=[] if data["dependencies"] == "none" else _split_csv(data["dependencies"]),
            )
        )
    return tasks


def validate_tasks_markdown(markdown: str) -> TaskValidationResult:
    tasks = parse_task_rows(markdown)
    errors: list[str] = []

    if not tasks:
        errors.append("no canonical task rows found")

    seen: set[str] = set()
    for task in tasks:
        if task.task_id in seen:
            errors.append(f"duplicate task id: {task.task_id}")
        seen.add(task.task_id)

    return TaskValidationResult(
        valid=not errors,
        task_count=len(tasks),
        errors=errors,
    )


def _split_csv(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]
